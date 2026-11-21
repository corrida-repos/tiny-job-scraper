"""PNG charts for Tiny's Daily Report, embedded inline in the HTML email.

Email clients run no scripts and Gmail strips inline SVG, so charts are static
PNGs rendered at 2x for sharp display. Every chart is optional: if matplotlib is
missing or the data is incomplete, the email keeps its text equivalent.
"""
import io

# Reference data-viz palette (validated): first three categorical slots for
# places, a one-hue blue ramp for rain, an orange ramp for traffic delay.
SURFACE = '#fcfcfb'
INK = '#0b0b0b'
INK_2 = '#52514e'
MUTED = '#898781'
GRID = '#e1e0d9'
AXIS = '#c3c2b7'
SERIES = ['#2a78d6', '#eb6834', '#1baf7a']
RAIN_RAMP = ['#f3f7fd', '#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95']
DELAY_RAMP = ['#fdf1ea', '#fbd5c1', '#f6b293', '#f08d63', '#eb6834', '#c4521f', '#9a3f16']
# Status hues as tints so 'OK' recedes and concern stands out; each cell also
# carries a symbol, so meaning never rests on colour alone.
STATUS = {0: ('#dff1df', '#006300', 'OK'), 1: ('#fde3a7', '#5c3d00', 'Caution'),
          2: ('#d03b3b', '#ffffff', 'High')}
WIDTH_PX = 640
DPI = 200


def _pyplot():
    try:
        import matplotlib
        matplotlib.use('Agg')
        from matplotlib import pyplot
        from matplotlib.colors import LinearSegmentedColormap
    except ImportError:
        return None, None
    pyplot.rcParams.update({
        'font.family': 'DejaVu Sans', 'font.size': 9, 'axes.edgecolor': AXIS,
        'axes.labelcolor': INK_2, 'xtick.color': MUTED, 'ytick.color': MUTED,
        'axes.titlecolor': INK, 'text.color': INK, 'axes.linewidth': 0.8,
        'xtick.major.size': 0, 'ytick.major.size': 0, 'figure.facecolor': SURFACE,
        'axes.facecolor': SURFACE, 'savefig.facecolor': SURFACE})
    return pyplot, LinearSegmentedColormap


def _png(figure, pyplot):
    buffer = io.BytesIO()
    figure.savefig(buffer, format='png', dpi=DPI, bbox_inches='tight', pad_inches=0.12)
    pyplot.close(figure)
    return buffer.getvalue()


def _hour_axis(axis, hours):
    axis.set_xlim(hours[0] - 0.5, hours[-1] + 0.5)
    ticks = [h for h in hours if h % 2 == 0]
    axis.set_xticks(ticks)
    axis.set_xticklabels([f'{h:02d}h' for h in ticks])


def _clean(axis, left=False):
    for side in ('top', 'right') + (('left',) if not left else ()):
        axis.spines[side].set_visible(False)


def weather_chart(visuals):
    """Temperature lines per place above an hourly rain-chance heatmap."""
    pyplot, colormap = _pyplot()
    places = [(name, data) for name, data in (visuals.get('places') or {}).items() if data]
    if pyplot is None or not places:
        return None
    start = max(0, min(visuals.get('first_departure_hour', 8) - 2, 23))
    hours = list(range(start, 24))
    series = []
    for name, data in places:
        by_hour = {row['hour']: row for row in data.get('hourly', [])}
        if not all(h in by_hour for h in hours):
            return None
        series.append((name, [by_hour[h] for h in hours]))
    width = WIDTH_PX / 100
    figure, (top, bottom) = pyplot.subplots(
        2, 1, figsize=(width, 1.7 + 0.42 * len(series) + 1.1), sharex=True,
        gridspec_kw={'height_ratios': [2.2, 0.42 * len(series) + 0.3], 'hspace': 0.18})
    # Temperature (one measure, one axis).
    temps = [r['temp'] for _, rows in series for r in rows]
    for index, (name, rows) in enumerate(series):
        color = SERIES[index % len(SERIES)]
        values = [r['temp'] for r in rows]
        top.plot(hours, values, color=color, linewidth=2, solid_capstyle='round',
                 solid_joinstyle='round', label=name, zorder=3)
        top.scatter([hours[-1]], [values[-1]], s=30, color=color, edgecolor=SURFACE,
                    linewidth=1.5, zorder=4)
    span = max(temps) - min(temps) or 1
    top.set_ylim(min(temps) - span * 0.25, max(temps) + span * 0.35)
    top.yaxis.set_major_formatter(lambda v, _: f'{v:.0f}°')
    top.grid(axis='y', color=GRID, linewidth=0.8)
    top.set_axisbelow(True)
    _clean(top)
    top.set_title('Temperature (°C)', loc='left', fontsize=9, color=INK_2, pad=4)
    legend = top.legend(loc='upper left', bbox_to_anchor=(0, 1.32), ncol=len(series),
                        frameon=False, handlelength=1.4, columnspacing=1.6, fontsize=8.5)
    for text in legend.get_texts():
        text.set_color(INK_2)
    hottest = max(((name, max(r['temp'] for r in rows)) for name, rows in series), key=lambda x: x[1])
    coldest = min(((name, min(r['temp'] for r in rows)) for name, rows in series), key=lambda x: x[1])
    top.text(1, 1.2, f'High {hottest[1]:.0f}° ({hottest[0]}) · Low {coldest[1]:.0f}° ({coldest[0]})',
             transform=top.transAxes, ha='right', va='center', fontsize=8, color=MUTED)
    # Rain chance heatmap, with mm/h labels on wet hours.
    cmap = colormap.from_list('rain', RAIN_RAMP)
    grid = [[r['probability'] for r in rows] for _, rows in series]
    bottom.imshow(grid, aspect='auto', cmap=cmap, vmin=0, vmax=100,
                  extent=(hours[0] - 0.5, hours[-1] + 0.5, len(series) - 0.5, -0.5))
    for y, (_, rows) in enumerate(series):
        for x, row in zip(hours, rows):
            if row['rain'] >= 0.1:
                dark = row['probability'] >= 55
                bottom.text(x, y, f"{row['rain']:.1f}", ha='center', va='center', fontsize=6.5,
                            color='#ffffff' if dark else INK)
    for y in range(1, len(series)):
        bottom.axhline(y - 0.5, color=SURFACE, linewidth=2)
    for x in hours[1:]:
        bottom.axvline(x - 0.5, color=SURFACE, linewidth=1)
    bottom.set_yticks(range(len(series)))
    bottom.set_yticklabels([name for name, _ in series], color=INK_2)
    for spine in bottom.spines.values():
        spine.set_visible(False)
    bottom.set_title('Chance of rain — darker is likelier; numbers are mm/h', loc='left',
                     fontsize=9, color=INK_2, pad=4)
    _hour_axis(bottom, hours)
    return _png(figure, pyplot)


def departure_chart(visuals):
    """Departure planner: drive-time heatmap (traffic) over weather concern."""
    pyplot, colormap = _pyplot()
    routes = [r for r in visuals.get('routes') or [] if r.get('departures')]
    if pyplot is None or not routes:
        return None
    hours = sorted({d['hour'] for r in routes for d in r['departures']})
    if len(hours) < 2 or hours != list(range(hours[0], hours[-1] + 1)):
        return None
    labels = [f"{r['origin']} → {r['destination']}" for r in routes]
    traffic = any(r.get('traffic') for r in routes)
    rows_per = len(routes)
    width = WIDTH_PX / 100
    panels = 2 if traffic else 1
    ratios = [rows_per * 0.36 + 0.2] * panels
    figure, axes = pyplot.subplots(panels, 1, figsize=(width, sum(ratios) + 0.5 * panels + 0.2),
                                   sharex=True, gridspec_kw={'height_ratios': ratios, 'hspace': 0.55})
    axes = list(axes) if panels > 1 else [axes]
    extent = (hours[0] - 0.5, hours[-1] + 0.5, rows_per - 0.5, -0.5)

    def frame(axis, title):
        axis.set_yticks(range(rows_per))
        axis.set_yticklabels(labels, color=INK_2)
        for spine in axis.spines.values():
            spine.set_visible(False)
        for y in range(1, rows_per):
            axis.axhline(y - 0.5, color=SURFACE, linewidth=3)
        for x in hours[1:]:
            axis.axvline(x - 0.5, color=SURFACE, linewidth=2)
        axis.set_title(title, loc='left', fontsize=9, color=INK_2, pad=4)

    def outline_windows(axis):
        from matplotlib.patches import Rectangle
        for y, route in enumerate(routes):
            for window in route.get('windows', []):
                axis.add_patch(Rectangle((window['start_hour'] - 0.47, y - 0.44),
                                         window['end_hour'] - window['start_hour'] + 0.94, 0.88,
                                         fill=False, edgecolor=INK, linewidth=1.6, zorder=5))

    if traffic:
        axis = axes[0]
        delays = [d['delay'] for r in routes for d in r['departures'] if d.get('delay') is not None]
        top = max(10, max(delays, default=0))
        cmap = colormap.from_list('delay', DELAY_RAMP).with_extremes(bad='#f0efec')
        grid = []
        for route in routes:
            by_hour = {d['hour']: d for d in route['departures']}
            grid.append([by_hour[h]['delay'] if h in by_hour and by_hour[h].get('delay') is not None
                         else float('nan') for h in hours])
        axis.imshow(grid, aspect='auto', cmap=cmap, vmin=0, vmax=top, extent=extent)
        for y, route in enumerate(routes):
            by_hour = {d['hour']: d for d in route['departures']}
            for x in hours:
                d = by_hour.get(x)
                if d and d.get('minutes') is not None:
                    dark = (d.get('delay') or 0) >= top * 0.55
                    axis.text(x, y, f"{d['minutes']:.0f}", ha='center', va='center', fontsize=7.5,
                              color='#ffffff' if dark else INK, fontweight='bold' if dark else 'normal')
                else:
                    axis.text(x, y, '–', ha='center', va='center', fontsize=7.5, color=MUTED)
        frame(axis, 'Drive time (min) — darker means more traffic delay')
        outline_windows(axis)

    axis = axes[-1]
    from matplotlib.colors import ListedColormap
    cmap = ListedColormap([STATUS[0][0], STATUS[1][0], STATUS[2][0]]).with_extremes(bad='#f0efec')
    grid = []
    for route in routes:
        by_hour = {d['hour']: d['risk'] for d in route['departures']}
        grid.append([by_hour.get(h, float('nan')) for h in hours])
    axis.imshow(grid, aspect='auto', cmap=cmap, vmin=-0.5, vmax=2.5, extent=extent)
    for y, route in enumerate(routes):
        for d in route['departures']:
            _, ink, text = STATUS[d['risk']]
            axis.text(d['hour'], y, '✓' if d['risk'] == 0 else '!' if d['risk'] == 1 else '!!',
                      ha='center', va='center', fontsize=7.5, color=ink, fontweight='bold')
    frame(axis, 'Weather concern at departure — ✓ OK · ! caution · !! high')
    if not traffic:
        outline_windows(axis)
    _hour_axis(axis, hours)
    axis.tick_params(axis='x', labelbottom=True)
    axes[0].text(1, 1.0 + 0.32 / ratios[0], '▭ recommended window', transform=axes[0].transAxes,
                 ha='right', va='bottom', fontsize=8, color=INK_2)
    return _png(figure, pyplot)


def build_charts(visuals):
    """Return [(cid, png_bytes, alt_text)] for every chart that could be drawn."""
    charts = []
    for cid, render, alt in (
            ('tiny-chart-weather', weather_chart, 'Hourly temperature and chance of rain by place'),
            ('tiny-chart-departures', departure_chart, 'Drive time and weather concern by departure hour')):
        try:
            data = render(visuals or {})
        except Exception:
            data = None  # A chart failure never blocks the email.
        if data:
            charts.append((cid, data, alt))
    return charts
