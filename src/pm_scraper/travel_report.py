"""Same-day weather and independently evaluated, directional driving windows.

Only TomTom supplies travel times; absent traffic is never replaced with a guess.
Weather-only mode explicitly uses an approximate geographic corridor.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

LISBON = ZoneInfo('Europe/Lisbon')
FIELDS = ('temperature_2m', 'precipitation', 'precipitation_probability',
          'wind_gusts_10m', 'visibility', 'weather_code')
ROUTES = [('Areias', 'Braga'), ('Braga', 'Areias'),
          ('Areias', 'Porto'), ('Porto', 'Areias')]


def get_json(url, params):
    # Never log URLs/exceptions: the TomTom query contains the API key.
    request = urllib.request.Request(url + '?' + urllib.parse.urlencode(params),
                                     headers={'User-Agent': 'TinyDailyReport/1.0'})
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.load(response)


def point_key(point):
    return tuple(round(float(v), 2) for v in point)


def distance(a, b):
    lat = math.radians((a[0] + b[0]) / 2)
    return math.hypot((a[0] - b[0]), (a[1] - b[1]) * math.cos(lat))


def sample_path(points, count=5):
    """Sample actual route geometry with proportional distance offsets."""
    cumulative = [0.0]
    for a, b in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + distance(a, b))
    total = cumulative[-1]
    if not total:
        raise ValueError('Empty route')
    samples = []
    index = 1
    for n in range(count):
        fraction = n / (count - 1)
        target = total * fraction
        while index < len(points) - 1 and cumulative[index] < target:
            index += 1
        a, b = points[index - 1], points[index]
        span = cumulative[index] - cumulative[index - 1]
        f = (target - cumulative[index - 1]) / span if span else 0
        samples.append((point_key([a[k] + f * (b[k] - a[k]) for k in (0, 1)]), fraction))
    return samples


def routing(task, places, key):
    origin, destination, departure = task
    a, b = places[origin], places[destination]
    result = {'origin': origin, 'destination': destination, 'departure': departure,
              'traffic': False, 'minutes': None}
    if key:
        try:
            locations = f'{a[0]},{a[1]}:{b[0]},{b[1]}'
            data = get_json('https://api.tomtom.com/routing/1/calculateRoute/' + locations + '/json',
                            {'key': key, 'traffic': 'true', 'travelMode': 'car',
                             'routeType': 'fastest', 'computeTravelTimeFor': 'all',
                             'departAt': departure.isoformat(), 'routeRepresentation': 'polyline'})
            route = data['routes'][0]
            summary = route['summary']
            seconds = float(summary['travelTimeInSeconds'])
            # noTrafficTravelTimeInSeconds establishes the requested traffic comparison.
            baseline = float(summary['noTrafficTravelTimeInSeconds'])
            if not (0 < seconds < 14400 and baseline > 0):
                raise ValueError('Invalid route duration')
            points = [(p['latitude'], p['longitude']) for leg in route['legs'] for p in leg['points']]
            result.update(traffic=True, minutes=seconds / 60,
                          delay=max(0, seconds - baseline) / 60, samples=sample_path(points))
        except Exception:
            result['traffic_error'] = True
    if not result['traffic']:
        result['samples'] = sample_path([a, b])
    return result


def forecasts(points):
    result = {}
    points = sorted(set(points))
    for start in range(0, len(points), 30):
        batch = points[start:start + 30]
        data = get_json('https://api.open-meteo.com/v1/forecast', {
            'latitude': ','.join(str(p[0]) for p in batch),
            'longitude': ','.join(str(p[1]) for p in batch),
            'hourly': ','.join(FIELDS), 'timezone': 'UTC',
            'timeformat': 'unixtime', 'forecast_days': 2, 'past_days': 1,
            'wind_speed_unit': 'kmh', 'precipitation_unit': 'mm'})
        rows = data if isinstance(data, list) else [data]
        if len(rows) != len(batch):
            raise ValueError('Incomplete weather response')
        for point, row in zip(batch, rows):
            hourly = row['hourly']
            result[point] = {stamp: {name: hourly[name][i] for name in FIELDS}
                             for i, stamp in enumerate(hourly['time'])}
    return result


def weather_at(hourly, when):
    """Use both bounding hours conservatively; never fill missing observations."""
    stamp = when.timestamp()
    floor = int(stamp // 3600) * 3600
    keys = [floor] if stamp == floor else [floor, floor + 3600]
    rows = [hourly[k] for k in keys]
    if any(row.get(name) is None for row in rows for name in FIELDS):
        raise ValueError('Missing weather fields')
    return {'rain': max(r['precipitation'] for r in rows),
            'probability': max(r['precipitation_probability'] for r in rows),
            'gust': max(r['wind_gusts_10m'] for r in rows),
            'visibility': min(r['visibility'] for r in rows),
            'temp': min(r['temperature_2m'] for r in rows),
            'codes': {r['weather_code'] for r in rows}}


def weather_risk(w):
    """Explainable screening bands, not a calibrated road-safety model."""
    codes = w['codes']
    if (w['rain'] >= 4 or w['gust'] >= 60 or w['visibility'] < 1000
            or codes & {56, 57, 66, 67, 71, 73, 75, 77, 85, 86, 95, 96, 99}
            or (w['temp'] <= 2 and w['rain'] > 0)):
        return 2
    if w['rain'] >= 0.5 or w['gust'] >= 40 or w['visibility'] < 5000:
        return 1
    return 0


def assess(route, weather):
    observations = []
    for point, fraction in route['samples']:
        # Without routing, inspect the entire next two hours, not an invented ETA.
        offsets = [fraction * route['minutes']] if route['traffic'] else [0, 60, 120]
        for offset in offsets:
            observations.append(weather_at(weather[point], route['departure'] + timedelta(minutes=offset)))
    w = {'rain': max(r['rain'] for r in observations),
         'probability': max(r['probability'] for r in observations),
         'gust': max(r['gust'] for r in observations),
         'visibility': min(r['visibility'] for r in observations),
         'temp': min(r['temp'] for r in observations),
         'codes': set().union(*(r['codes'] for r in observations))}
    return dict(route, weather=w, risk=weather_risk(w))


def best_windows(rows, traffic):
    """Rank adjacent evaluated departures; exclude severe weather and missing data."""
    windows = []
    for a, b in zip(rows, rows[1:]):
        if b['departure'] - a['departure'] != timedelta(hours=1):
            continue
        if max(a['risk'], b['risk']) >= 2:
            continue
        if traffic and not (a['traffic'] and b['traffic']):
            continue
        rain = max(a['weather']['rain'], b['weather']['rain'])
        probability = max(a['weather']['probability'], b['weather']['probability'])
        minutes = max(a['minutes'], b['minutes']) if traffic else 0
        # Weather band first, then minutes plus explicit rain/probability penalties.
        score = (max(a['risk'], b['risk']), minutes + 5 * rain + probability / 20)
        windows.append((score, a, b))
    selected = []
    for _, a, b in sorted(windows, key=lambda w: (w[0], w[1]['departure'])):
        if any(a['departure'] <= y['departure'] and b['departure'] >= x['departure'] for x, y in selected):
            continue
        selected.append((a, b))
        if len(selected) == 3:
            break
    return selected


def build_report(config, now=None, key=None):
    now = (now or datetime.now(timezone.utc)).astimezone(LISBON)
    key = os.environ.get('TOMTOM_API_KEY', '') if key is None else key
    places = config['places']
    hours = range(config['first_departure_hour'], config['last_departure_hour'] + 1)
    departures = [now.replace(hour=h, minute=0, second=0, microsecond=0) for h in hours]
    departures = [d for d in departures if d > now]
    tasks = [(a, b, d) for a, b in ROUTES for d in departures]
    with ThreadPoolExecutor(max_workers=4) as pool:
        routes = list(pool.map(lambda task: routing(task, places, key), tasks))
    points = [point_key(p) for p in places.values()]
    points += [p for route in routes for p, _ in route['samples']]
    weather = forecasts(points)
    lines = ['# Weather and driving today', '',
             f'{now:%A, %d %B %Y} · Europe/Lisbon · generated {now:%H:%M %Z}.', '',
             'Areias, Santo Tirso → Braga / Porto and return. Locations are parish/city centres; toll roads are allowed.', '',
             '## Today’s weather', '']
    for name, point in places.items():
        today = [r for stamp, r in weather[point_key(point)].items()
                 if datetime.fromtimestamp(stamp, LISBON).date() == now.date()]
        if not today or any(r.get(f) is None for r in today for f in FIELDS):
            lines.append(f'- **{name}:** weather unavailable.')
            continue
        lines.append(f"- **{name}:** {min(r['temperature_2m'] for r in today):.0f}–{max(r['temperature_2m'] for r in today):.0f} °C; "
                     f"{sum(r['precipitation'] for r in today):.1f} mm rain; "
                     f"rain probability up to {max(r['precipitation_probability'] for r in today):.0f}%; "
                     f"gusts up to {max(r['wind_gusts_10m'] for r in today):.0f} km/h.")
    lines += ['', '## Best departure windows', '']
    unavailable = 0
    for origin, destination in ROUTES:
        raw = [r for r in routes if (r['origin'], r['destination']) == (origin, destination)]
        rows = []
        for route in raw:
            try:
                rows.append(assess(route, weather))
            except (KeyError, ValueError, TypeError):
                unavailable += 1
        traffic = bool(rows) and all(r['traffic'] for r in rows)
        lines += [f'### {origin} → {destination}', '']
        if not traffic:
            lines += ['**Weather-only comparison: traffic unavailable or incomplete.** Approximate corridor; no journey-time claim.', '']
        windows = best_windows(rows, traffic)
        for a, b in windows:
            w = [a['weather'], b['weather']]
            label = 'lower weather concern' if max(a['risk'], b['risk']) == 0 else 'weather caution'
            timing = (f"; {min(a['minutes'], b['minutes']):.0f}–{max(a['minutes'], b['minutes']):.0f} min, "
                      f"traffic uplift up to {max(a['delay'], b['delay']):.0f} min") if traffic else ''
            lines.append(f"- **{a['departure']:%H:%M}–{b['departure']:%H:%M}**: {label}{timing}; "
                         f"rain ≤{max(x['rain'] for x in w):.1f} mm/h, "
                         f"gusts ≤{max(x['gust'] for x in w):.0f} km/h, "
                         f"visibility ≥{min(x['visibility'] for x in w)/1000:.1f} km.")
        if not windows:
            lines.append('No recommended window: severe forecast conditions, insufficient data, or fewer than two future departure samples.')
        severe = [r['departure'].strftime('%H:%M') for r in rows if r['risk'] == 2]
        if severe:
            lines.append('Higher weather concern at sampled departures: ' + ', '.join(severe) + '.')
        lines.append('')
    if unavailable:
        lines += [f'Weather coverage missing for {unavailable} departure samples; those samples were excluded.', '']
    lines += [f"Departures sampled hourly from {config['first_departure_hour']:02d}:00 to {config['last_departure_hour']:02d}:00; "
              'windows span two evaluated departures. Conditions between samples may vary. '
              'Recommendations favour better weather, then shorter journeys. '
              'Heavy rain, very poor visibility, strong gusts, snow, ice or thunderstorms exclude a window. '
              'These are planning recommendations, not road-safety guarantees.', '',
              'Sources: [Open-Meteo](https://open-meteo.com/) hourly forecast; '
              '[TomTom Routing](https://developer.tomtom.com/routing-api/documentation/tomtom-maps/calculate-route) '
              'traffic-aware forecasts when configured (historical traffic plus available live information). '
              'Later traffic is a prediction; incidents and closures can change. Check navigation and '
              '[IPMA warnings](https://www.ipma.pt/en/otempo/prev-sam/) before leaving.', '']
    return '\n'.join(lines)


def attach_report(draft, source):
    """Generate once per new draft. Prepared retries keep the checkpointed email."""
    path = Path(source) / 'config/daily-report.json'
    if not path.exists():
        return draft
    from .daily import SUBJECT
    draft['subject'] = SUBJECT
    try:
        report = build_report(json.loads(path.read_text()))
    except Exception:
        # Provider errors do not suppress jobs or leak credential-bearing URLs.
        report = '# Weather and driving today\n\nWeather/travel data unavailable for this run; no driving windows can be recommended.\n'
    draft['body_markdown'] = report + '\n---\n\n# Job report\n\n' + draft['body_markdown']
    return draft
