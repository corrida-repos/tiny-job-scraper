"""Best times to leave home and to return home today, from rain and traffic.

Only TomTom supplies travel times; absent traffic is never replaced with a guess.
The home address lives in the HOME_ADDRESS secret (the repository is public) and
is geocoded at run time; the configured parish centre is the fallback.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

LISBON = ZoneInfo('Europe/Lisbon')
FIELDS = ('temperature_2m', 'precipitation', 'precipitation_probability',
          'wind_gusts_10m', 'visibility', 'weather_code')
HOME = 'Home'


# TomTom free keys allow only a few routing queries per second; one burst used to
# fail every direction. Space requests and retry transient refusals.
TOMTOM_MIN_INTERVAL = 0.3
RETRIES = 3
_throttle_lock = threading.Lock()
_last_tomtom = [0.0]


def _throttle(url):
    if 'api.tomtom.com' not in url:
        return
    with _throttle_lock:
        wait = _last_tomtom[0] + TOMTOM_MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_tomtom[0] = time.monotonic()


def _transient(error):
    if isinstance(error, urllib.error.HTTPError):
        if error.code == 429 or error.code >= 500:
            return True
        if error.code == 403:
            # TomTom reports QPS overruns as 403 "Developer Over Qps".
            try:
                return b'qps' in error.read(2048).lower()
            except Exception:
                return False
        return False
    return isinstance(error, (urllib.error.URLError, TimeoutError, ConnectionError))


def get_json(url, params):
    # Never log URLs/exceptions: the TomTom query contains the API key.
    request = urllib.request.Request(url + '?' + urllib.parse.urlencode(params),
                                     headers={'User-Agent': 'TinyDailyReport/1.0'})
    for attempt in range(RETRIES):
        _throttle(url)
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                return json.load(response)
        except Exception as error:
            if attempt == RETRIES - 1 or not _transient(error):
                raise
            delay = 2 ** attempt
            headers = getattr(error, 'headers', None)
            retry_after = headers.get('Retry-After') if headers else None
            if retry_after and str(retry_after).isdigit():
                delay = min(int(retry_after), 10)
            time.sleep(delay)


def error_category(error):
    """Credential-free failure label for workflow logs."""
    if isinstance(error, urllib.error.HTTPError):
        return f'HTTP {error.code}'
    if isinstance(error, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return 'network error'
    if isinstance(error, (KeyError, IndexError, TypeError, ValueError)):
        return 'unexpected response'
    return 'other error'


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
        except Exception as error:
            result['traffic_error'] = error_category(error)
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


def geocode(address, key):
    data = get_json('https://api.tomtom.com/search/2/geocode/'
                    + urllib.parse.quote(address, safe='') + '.json',
                    {'key': key, 'countrySet': 'PT', 'limit': 1})
    position = data['results'][0]['position']
    return float(position['lat']), float(position['lon'])


def resolve_home(config, key, diagnostics):
    """Geocode HOME_ADDRESS; never log or print the address or its coordinates."""
    fallback = tuple(config['home']['fallback'])
    address = os.environ.get('HOME_ADDRESS', '').strip()
    if not address:
        diagnostics['home'] = 'HOME_ADDRESS not set'
        return fallback, False
    if not key:
        diagnostics['home'] = 'TOMTOM_API_KEY needed to locate HOME_ADDRESS'
        return fallback, False
    try:
        point = geocode(address, key)
    except Exception as error:
        diagnostics['home'] = 'address lookup failed (' + error_category(error) + ')'
        return fallback, False
    # A match far from the configured area is a wrong match, not home.
    if distance(point, fallback) > 0.15:
        diagnostics['home'] = 'address lookup matched a place too far from the configured area'
        return fallback, False
    diagnostics['home'] = 'ok'
    return point, True


RAIN_PENALTY = 15  # rain worth about 15 extra minutes of driving; see docs


def score(row, traffic):
    """One scale for rain and traffic: predicted minutes plus rain penalties."""
    minutes = row['minutes'] if traffic else 0
    w = row['weather']
    return minutes + RAIN_PENALTY * row['risk'] + 5 * w['rain'] + w['probability'] / 20


def describe(row, traffic):
    w = row['weather']
    if w['rain'] == 0 and w['probability'] < 20:
        rain = 'dry'
    elif w['rain'] < 0.5:
        rain = f"little or no rain, {w['probability']:.0f}% chance"
    elif w['rain'] < 4:
        rain = f"rain up to {w['rain']:.1f} mm/h, {w['probability']:.0f}% chance"
    else:
        rain = f"heavy rain up to {w['rain']:.1f} mm/h"
    extras = []
    if w['gust'] >= 40:
        extras.append(f"gusts {w['gust']:.0f} km/h")
    if w['visibility'] < 5000:
        extras.append(f"visibility {w['visibility'] / 1000:.1f} km")
    if traffic:
        delay = row['delay']
        level = 'light' if delay < 5 else 'moderate' if delay < 15 else 'heavy'
        text = f"about {row['minutes']:.0f} min · {level} traffic (+{delay:.0f} min) · {rain}"
    else:
        text = rain
    return text + ''.join(' · ' + e for e in extras)


def choose(rows):
    """Best, runner-up and worst departure. Severe weather is never recommended."""
    traffic = any(r['traffic'] for r in rows)
    usable = [r for r in rows if r['traffic'] or not traffic]
    ranked = sorted((r for r in usable if r['risk'] < 2),
                    key=lambda r: (score(r, traffic), r['departure']))
    worst = max(usable, key=lambda r: (r['risk'] == 2, score(r, traffic), -r['departure'].timestamp()), default=None)
    return traffic, ranked, worst


def leg_lines(title, rows, hours):
    lines = []
    span = f'{hours[0]:02d}:00–{hours[-1]:02d}:00'
    if not rows:
        return [f'**{title}:** no times left to check today ({span}).']
    traffic, ranked, worst = choose(rows)
    if not ranked:
        return [f'**{title}:** no good time between {span}: heavy rain, storms, strong wind, '
                'ice or poor visibility are forecast at every hour checked.']
    best = ranked[0]
    lines.append(f"**{title}: {best['departure']:%H:%M}** · {describe(best, traffic)}")
    if len(ranked) > 1:
        lines.append(f"- Next best: {ranked[1]['departure']:%H:%M} · {describe(ranked[1], traffic)}")
    if worst is not None and worst not in ranked[:2] and score(worst, traffic) > score(best, traffic):
        lines.append(f"- Avoid: {worst['departure']:%H:%M} · {describe(worst, traffic)}")
    missing = [r['departure'].strftime('%H:%M') for r in rows if not r['traffic']]
    if not traffic:
        lines.append('_Traffic forecast unavailable, so this is based on rain only._')
    elif missing:
        lines.append('_No traffic forecast for ' + ', '.join(missing) + '; not considered._')
    return lines


def build_report(config, now=None, key=None, diagnostics=None):
    diagnostics = {} if diagnostics is None else diagnostics
    now = (now or datetime.now(timezone.utc)).astimezone(LISBON)
    key = os.environ.get('TOMTOM_API_KEY', '') if key is None else key
    home, exact = resolve_home(config, key, diagnostics)
    places = {HOME: home, **{n: tuple(p) for n, p in config['destinations'].items()}}
    windows = {'leave': list(range(config['leave_hours'][0], config['leave_hours'][1] + 1)),
               'return': list(range(config['return_hours'][0], config['return_hours'][1] + 1))}

    def future(hours):
        times = [now.replace(hour=h, minute=0, second=0, microsecond=0) for h in hours]
        return [t for t in times if t > now]

    tasks = []
    for name in config['destinations']:
        tasks += [(HOME, name, d) for d in future(windows['leave'])]
        tasks += [(name, HOME, d) for d in future(windows['return'])]
    with ThreadPoolExecutor(max_workers=2) as pool:
        routes = list(pool.map(lambda task: routing(task, places, key), tasks))
    points = [point_key(p) for p in places.values()]
    points += [p for route in routes for p, _ in route['samples']]
    weather = forecasts(points)

    label = config['home']['label']
    where = f'from home ({label})' if exact else f'from {label} centre (home address not set up)'
    lines = ['# Leaving and returning home today', '',
             f'{now:%A, %d %B %Y} · {where} · generated {now:%H:%M %Z}.', '']
    unavailable = 0
    for name in config['destinations']:
        lines += [f'## {name}', '']
        for leg, origin, destination, title in (('leave', HOME, name, 'Leave home'),
                                                ('return', name, HOME, 'Return home')):
            rows = []
            for route in routes:
                if (route['origin'], route['destination']) == (origin, destination):
                    try:
                        rows.append(assess(route, weather))
                    except (KeyError, ValueError, TypeError):
                        unavailable += 1
            lines += leg_lines(title, rows, windows[leg]) + ['']
            diagnostics.setdefault('weather_only', 0)
            if rows and not any(r['traffic'] for r in rows):
                diagnostics['weather_only'] += 1
    diagnostics['legs'] = 2 * len(config['destinations'])
    diagnostics['routes'] = len(routes)
    diagnostics['traffic_ok'] = sum(r['traffic'] for r in routes)
    errors = {}
    for r in routes:
        if r.get('traffic_error'):
            errors[r['traffic_error']] = errors.get(r['traffic_error'], 0) + 1
    diagnostics['errors'] = errors

    lines += ['## Weather today', '']
    for name, point in places.items():
        today = [r for stamp, r in weather[point_key(point)].items()
                 if datetime.fromtimestamp(stamp, LISBON).date() == now.date()]
        shown = 'Home' if name == HOME else name
        if not today or any(r.get(f) is None for r in today for f in FIELDS):
            lines.append(f'- **{shown}:** weather unavailable.')
            continue
        wet = [datetime.fromtimestamp(stamp, LISBON).hour for stamp, r in sorted(weather[point_key(point)].items())
               if datetime.fromtimestamp(stamp, LISBON).date() == now.date() and r['precipitation'] >= 0.5]
        periods = []
        for hour in wet:
            if periods and periods[-1][1] == hour:
                periods[-1][1] = hour + 1
            else:
                periods.append([hour, hour + 1])
        when = ', '.join(f'{a:02d}:00–{b % 24:02d}:00' for a, b in periods)
        lines.append(f"- **{shown}:** {min(r['temperature_2m'] for r in today):.0f}–{max(r['temperature_2m'] for r in today):.0f} °C, "
                     f"{sum(r['precipitation'] for r in today):.1f} mm rain"
                     + (f" (rain {when})" if when else ', no rain expected') + '.')
    lines.append('')
    if unavailable:
        lines += [f'Weather data missing for {unavailable} departure times; those were left out.', '']
    lines += [f"Leave times checked hourly {windows['leave'][0]:02d}:00–{windows['leave'][-1]:02d}:00, "
              f"return times {windows['return'][0]:02d}:00–{windows['return'][-1]:02d}:00. "
              'Best balances rain against predicted journey time: rain counts like roughly 15–25 extra minutes of traffic. '
              'Heavy rain, storms, strong gusts, ice or very poor visibility rule a time out. '
              'Rain is checked along the route at the time you would pass each point.', '',
              'Sources: [Open-Meteo](https://open-meteo.com/) forecast; '
              '[TomTom](https://developer.tomtom.com/) predicted traffic. '
              'Check navigation and [IPMA warnings](https://www.ipma.pt/en/otempo/prev-sam/) before leaving.', '']
    return '\n'.join(lines)


def traffic_status(report, key=None, diagnostics=None):
    """Workflow-log summary that confirms setup without revealing the key, address or report."""
    key = os.environ.get('TOMTOM_API_KEY', '') if key is None else key
    diagnostics = diagnostics or {}
    home = diagnostics.get('home')
    home_text = '' if home in (None, 'ok') else f' Home location: {home}; using the configured parish centre.'
    if not key:
        return 'TOMTOM_API_KEY not configured; recommendations use rain only.' + home_text
    legs = diagnostics.get('legs', 0)
    weather_only = diagnostics.get('weather_only', 0)
    detail = ''
    if diagnostics.get('routes'):
        detail = f" {diagnostics['traffic_ok']}/{diagnostics['routes']} departure forecasts succeeded"
        if diagnostics.get('errors'):
            detail += ' (failures: ' + ', '.join(f'{k} ×{v}' for k, v in sorted(diagnostics['errors'].items())) + ')'
        detail += '.'
    if not weather_only:
        return f'TomTom traffic used for all {legs} trips.' + detail + home_text
    errors = diagnostics.get('errors', {})
    hint = ''
    if 'HTTP 401' in errors or 'HTTP 403' in errors:
        hint = ' HTTP 401/403 means the key is invalid or lacks Routing API access.'
    elif 'HTTP 429' in errors:
        hint = ' HTTP 429 means the daily quota or rate limit was exceeded.'
    return (f'TOMTOM_API_KEY is set but {weather_only} of {legs} trips fell back to rain only '
            '(routing failed: check the key, Routing API access and quota).' + detail + hint + home_text)


def attach_report(draft, source):
    """Generate once per new draft. Prepared retries keep the checkpointed email."""
    path = Path(source) / 'config/daily-report.json'
    if not path.exists():
        return draft
    from .daily import SUBJECT
    draft['subject'] = SUBJECT
    try:
        diagnostics = {}
        report = build_report(json.loads(path.read_text()), diagnostics=diagnostics)
        print('::notice title=Traffic forecasts::' + traffic_status(report, diagnostics=diagnostics))
    except Exception:
        # Provider errors do not suppress jobs or leak credential-bearing URLs.
        report = '# Leaving and returning home today\n\nWeather/traffic data unavailable for this run; no times can be recommended.\n'
        print('::notice title=Traffic forecasts::Weather/traffic data unavailable; no leave/return times in this report.')
    draft['body_markdown'] = report + '\n---\n\n# Job report\n\n' + draft['body_markdown']
    return draft
