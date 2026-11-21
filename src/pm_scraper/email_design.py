"""Styled HTML layout for Tiny's Daily Report.

The Markdown draft stays the plain-text part and the audit record. This module
only presents it: weather tiles, window cards and charts come from the
checkpointed ``travel_visuals`` data; the job report is the rendered Markdown
with inline styles (Gmail ignores most stylesheet rules) and job cards.
"""
from html import escape

from .branding import render_email_html

JOB_SEPARATOR = '\n---\n\n# Job report\n\n'
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
PAGE = '#eef0ec'
CARD = '#ffffff'
INK = '#0b0b0b'
INK_2 = '#52514e'
MUTED = '#898781'
LINE = '#e1e0d9'
TINT = '#f6f7f4'
BRAND = '#1c3b5a'
ACCENT = '#2a78d6'
CHIPS = {0: ('#e3f4e3', '#006300', '✓ Lower weather concern'),
         1: ('#fff3d6', '#7a5200', '! Weather caution')}

STYLES = {
    'h1': f'margin:32px 0 12px;padding:0 0 8px;font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:{BRAND};border-bottom:2px solid {BRAND};',
    'h2': f'margin:24px 0 4px;font-size:18px;line-height:1.3;color:{INK};',
    'h3': f'margin:0 0 6px;font-size:15px;line-height:1.35;color:{INK};',
    'p': f'margin:0 0 10px;font-size:14px;line-height:1.55;color:{INK_2};',
    'ul': 'margin:0 0 4px;padding:0 0 0 18px;',
    'ol': 'margin:0 0 4px;padding:0 0 0 18px;',
    'li': f'margin:0 0 6px;font-size:14px;line-height:1.5;color:{INK_2};',
    'a': f'color:{ACCENT};text-decoration:none;font-weight:600;',
    'strong': f'color:{INK};',
    'hr': f'border:0;border-top:1px solid {LINE};margin:20px 0;',
    'code': f'font-size:13px;background:{TINT};padding:1px 4px;border-radius:4px;',
}
BUTTON = (f'display:inline-block;padding:6px 14px;border-radius:999px;background:{ACCENT};'
          'color:#ffffff;font-size:13px;font-weight:600;text-decoration:none;')
GHOST = (f'display:inline-block;padding:4px 12px;border-radius:999px;border:1px solid {LINE};'
         f'color:{INK_2};font-size:12px;font-weight:600;text-decoration:none;')
JOB_CARD = (f'margin:10px 0 14px;padding:16px 18px;border:1px solid {LINE};border-radius:12px;'
            f'background:{CARD};border-left:4px solid {ACCENT};')


def weather_icon(codes):
    codes = set(codes or [])
    if codes & {95, 96, 99}:
        return '⛈️', 'Thunderstorms'
    if codes & {71, 73, 75, 77, 85, 86}:
        return '🌨️', 'Snow'
    if codes & {61, 63, 65, 66, 67, 80, 81, 82}:
        return '🌧️', 'Rain'
    if codes & {51, 53, 55, 56, 57}:
        return '🌦️', 'Drizzle'
    if codes & {45, 48}:
        return '🌫️', 'Fog'
    if codes & {3}:
        return '☁️', 'Cloudy'
    if codes & {1, 2}:
        return '⛅', 'Partly cloudy'
    return '☀️', 'Clear'


def section_title(text, subtitle=''):
    sub = f'<div style="font-size:13px;color:{MUTED};margin-top:2px;">{escape(subtitle)}</div>' if subtitle else ''
    return (f'<div style="margin:28px 0 12px;"><div style="font-size:13px;letter-spacing:.08em;'
            f'text-transform:uppercase;font-weight:700;color:{BRAND};">{escape(text)}</div>{sub}</div>')


def chart_image(cid, alt, embed, data):
    if embed:
        source = f'cid:{cid}'
    else:
        import base64
        source = 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')
    return (f'<div style="margin:6px 0 4px;padding:12px;background:#fcfcfb;border:1px solid {LINE};'
            f'border-radius:12px;"><img src="{source}" alt="{escape(alt)}" width="600" '
            'style="display:block;width:100%;max-width:600px;height:auto;border:0;"></div>')


def weather_tiles(places):
    cells = []
    for name, data in places.items():
        if not data:
            body = f'<div style="font-size:13px;color:{MUTED};">Weather unavailable</div>'
            icon, label = '❔', 'Unavailable'
        else:
            icon, label = weather_icon(data.get('codes'))
            body = (f'<div style="font-size:22px;font-weight:700;color:{INK};line-height:1.2;">'
                    f'{data["min_temp"]:.0f}°<span style="color:{MUTED};font-weight:400;"> / </span>{data["max_temp"]:.0f}°</div>'
                    f'<div style="font-size:12px;color:{INK_2};margin-top:6px;line-height:1.6;">'
                    f'💧 {data["rain"]:.1f} mm · {data["probability"]:.0f}%<br>'
                    f'💨 gusts {data["gust"]:.0f} km/h</div>')
        cells.append(
            f'<td valign="top" style="width:33%;padding:6px;">'
            f'<div style="background:{TINT};border-radius:12px;padding:14px 12px;text-align:left;">'
            f'<div style="font-size:12px;font-weight:700;color:{INK_2};text-transform:uppercase;letter-spacing:.06em;">{escape(name)}</div>'
            f'<div style="font-size:26px;line-height:1.3;margin:4px 0 2px;">{icon}</div>'
            f'<div style="font-size:12px;color:{MUTED};margin-bottom:6px;">{escape(label)}</div>{body}</div></td>')
    rows = [cells[i:i + 3] for i in range(0, len(cells), 3)]
    return ''.join('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                   f'style="border-collapse:collapse;margin:0 -6px;"><tr>{"".join(row)}</tr></table>'
                   for row in rows)


def window_card(route):
    title = f'{escape(route["origin"])} <span style="color:{MUTED};">→</span> {escape(route["destination"])}'
    parts = [f'<div style="font-size:15px;font-weight:700;color:{INK};margin-bottom:8px;">{title}</div>']
    if not route.get('traffic'):
        parts.append(f'<div style="font-size:12px;color:#7a5200;background:#fff3d6;border-radius:8px;'
                     'padding:6px 10px;margin-bottom:8px;">Weather-only: traffic unavailable, no journey-time claim.</div>')
    elif route.get('missing'):
        parts.append(f'<div style="font-size:12px;color:{INK_2};margin-bottom:8px;">Traffic missing for '
                     f'{route["missing"]} departures; excluded.</div>')
    for index, window in enumerate(route.get('windows', [])):
        background, ink, label = CHIPS[window['risk']]
        timing = ''
        if window.get('min_minutes') is not None:
            low, high = round(window['min_minutes']), round(window['max_minutes'])
            span = f'{low}' if low == high else f'{low}–{high}'
            timing = (f'<div style="font-size:20px;font-weight:700;color:{INK};line-height:1.1;">{span}'
                      f'<span style="font-size:12px;font-weight:600;color:{MUTED};"> min</span></div>'
                      f'<div style="font-size:11px;color:{MUTED};">+{window["delay"]:.0f} min traffic</div>')
        best = (f'<span style="font-size:10px;font-weight:700;letter-spacing:.06em;color:{ACCENT};'
                'text-transform:uppercase;margin-left:6px;">Best</span>') if index == 0 else ''
        parts.append(
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse;border-top:1px solid {LINE};"><tr>'
            f'<td valign="middle" style="padding:8px 0;">'
            f'<div style="font-size:15px;font-weight:700;color:{INK};">{window["start"]}–{window["end"]}{best}</div>'
            f'<div style="margin-top:4px;"><span style="display:inline-block;font-size:11px;font-weight:600;'
            f'color:{ink};background:{background};border-radius:999px;padding:2px 8px;">{label}</span></div>'
            f'<div style="font-size:11px;color:{MUTED};margin-top:4px;">rain ≤{window["rain"]:.1f} mm/h · '
            f'gusts ≤{window["gust"]:.0f} km/h · vis ≥{window["visibility"] / 1000:.1f} km</div></td>'
            f'<td valign="middle" align="right" style="padding:8px 0 8px 8px;white-space:nowrap;">{timing}</td>'
            '</tr></table>')
    if not route.get('windows'):
        parts.append(f'<div style="font-size:13px;color:{INK_2};border-top:1px solid {LINE};padding-top:8px;">'
                     'No recommended window today.</div>')
    if route.get('severe'):
        parts.append(f'<div style="font-size:12px;color:#a32020;margin-top:6px;">‼ Higher weather concern at '
                     f'{escape(", ".join(route["severe"]))}</div>')
    return (f'<td class="stack" valign="top" style="width:50%;padding:6px;"><div style="border:1px solid {LINE};'
            f'border-radius:12px;padding:14px 16px;background:{CARD};">{"".join(parts)}</div></td>')


def travel_section(visuals, charts, embed):
    html = [section_title('Today’s weather', 'Areias (Santo Tirso), Braga and Porto')]
    html.append(weather_tiles(visuals.get('places', {})))
    for cid, data, alt in charts:
        if cid == 'tiny-chart-weather':
            html.append(chart_image(cid, alt, embed, data))
    routes = visuals.get('routes', [])
    html.append(section_title('Best departure windows', 'Up to three two-hour windows per direction, best first'))
    if routes:
        cards = [window_card(r) for r in routes]
        for i in range(0, len(cards), 2):
            html.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                        f'style="border-collapse:collapse;margin:0 -6px;"><tr>{"".join(cards[i:i + 2])}</tr></table>')
    else:
        html.append(f'<p style="{STYLES["p"]}">No future departures remain today.</p>')
    for cid, data, alt in charts:
        if cid == 'tiny-chart-departures':
            html.append(section_title('Departure planner', 'Every sampled departure at a glance'))
            html.append(chart_image(cid, alt, embed, data))
    if visuals.get('unavailable'):
        html.append(f'<p style="{STYLES["p"]}">Weather coverage missing for {visuals["unavailable"]} '
                    'departure samples; those samples were excluded.</p>')
    html.append(
        f'<p style="margin:14px 0 0;font-size:11px;line-height:1.55;color:{MUTED};">Departures sampled hourly from '
        f'{visuals.get("first_departure_hour", 8):02d}:00 to {visuals.get("last_departure_hour", 21):02d}:00; windows span '
        'two evaluated departures and favour better weather, then shorter journeys. Heavy rain, very poor visibility, '
        'strong gusts, snow, ice or thunderstorms exclude a window. Planning guidance, not a road-safety guarantee. '
        f'Sources: <a href="https://open-meteo.com/" style="color:{MUTED};">Open-Meteo</a>, '
        f'<a href="https://developer.tomtom.com/routing-api/documentation/tomtom-maps/calculate-route" style="color:{MUTED};">TomTom Routing</a> '
        f'when configured. Check navigation and <a href="https://www.ipma.pt/en/otempo/prev-sam/" style="color:{MUTED};">IPMA warnings</a> before leaving.</p>')
    return ''.join(html)


def style_markdown_html(rendered):
    """Inline styles on rendered Markdown; group each job (h3 onwards) in a card."""
    from lxml import html as lxml_html
    root = lxml_html.fragment_fromstring(rendered, create_parent='div')
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        style = STYLES.get(element.tag)
        if style:
            element.set('style', style + element.get('style', ''))
    for anchor in root.iter('a'):
        text = anchor.text_content().strip()
        parent = anchor.getparent()
        alone = parent is not None and parent.tag == 'p' and len(parent) == 1 and not (parent.text or '').strip()
        if text == 'View job' and alone:
            anchor.set('style', BUTTON)
            anchor.text = 'View job →'
        elif text == 'Company careers' and alone:
            anchor.set('style', GHOST)
            anchor.text = 'Careers page ↗'
    for image in root.iter('img'):
        heading = image.getparent()
        if heading is not None and heading.tag == 'h2':
            heading.set('style', STYLES['h2'] + 'display:block;')
    children = list(root)
    card = None
    for child in children:
        tag = child.tag if isinstance(child.tag, str) else ''
        if tag == 'h3':
            card = lxml_html.Element('div', style=JOB_CARD)
            child.addprevious(card)
        elif tag in ('h1', 'h2', 'hr') or card is None:
            card = None
            continue
        card.append(child)
    # A horizontal rule right after a card adds noise; cards already separate jobs.
    for rule in root.iter('hr'):
        previous = rule.getprevious()
        if previous is not None and previous.tag == 'div':
            rule.set('style', f'border:0;margin:6px 0;')
    return ''.join(lxml_html.tostring(child, encoding='unicode') for child in root)


def render_draft_html(draft, embed=True):
    """Return (html, [(cid, bytes)]) for the complete styled email."""
    markdown = draft['body_markdown']
    visuals = draft.get('travel_visuals')
    travel_html = ''
    if visuals and JOB_SEPARATOR in markdown:
        from .email_charts import build_charts
        charts = build_charts(visuals)
        travel_html = travel_section(visuals, charts, embed)
        markdown = markdown.split(JOB_SEPARATOR, 1)[1]
        markdown = '# Job report\n\n' + markdown
    else:
        charts = []
    rendered, attachments = render_email_html(markdown, embed=embed)
    body = style_markdown_html(rendered)
    attachments = list(attachments) + ([(cid, data) for cid, data, _ in charts] if embed else [])
    date = visuals.get('date', '') if visuals else ''
    generated = f' · generated {visuals["generated"]}' if visuals and visuals.get('generated') else ''
    title = escape(draft.get('subject', 'Tiny’s Daily Report'))
    page = f'''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">
<title>{title}</title>
<style>@media only screen and (max-width:540px){{td.stack{{display:block!important;width:auto!important}}}}</style></head>
<body style="margin:0;padding:0;background:{PAGE};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAGE};border-collapse:collapse;">
<tr><td align="center" style="padding:20px 10px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:680px;border-collapse:separate;font-family:{FONT};">
<tr><td style="background:{BRAND};background-image:linear-gradient(135deg,#1c3b5a 0%,#2a78d6 100%);border-radius:16px 16px 0 0;padding:26px 28px;">
<div style="font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#cde2fb;font-weight:700;">Good morning</div>
<div style="font-size:26px;font-weight:800;color:#ffffff;margin-top:4px;">{title}</div>
<div style="font-size:13px;color:#cde2fb;margin-top:6px;">{escape(date)}{escape(generated)}</div>
</td></tr>
<tr><td style="background:{CARD};border-radius:0 0 16px 16px;padding:4px 24px 28px;">
{travel_html}
{body}
</td></tr>
<tr><td align="center" style="padding:16px 8px;font-size:11px;color:{MUTED};font-family:{FONT};">
Tiny’s Daily Report · automated by the tiny-job-scraper workflow</td></tr>
</table></td></tr></table></body></html>'''
    return page, attachments
