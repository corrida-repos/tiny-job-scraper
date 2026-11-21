from datetime import datetime
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from lxml import html

from pm_scraper import travel_report as travel
from pm_scraper import email_charts
from pm_scraper.actions_runner import Gmail
from pm_scraper.branding import company_heading
from pm_scraper.email_design import JOB_SEPARATOR, render_draft_html

JOBS = (company_heading('bosch', 'Bosch') + '\n[Company careers](https://example.org/careers)\n\n'
        '### **Project Manager**\n[View job](https://example.org/job)\n'
        '- **Pros:** Hybrid Braga.\n- **Cons:** Travel unconfirmed.\n')


class EmailDesignTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 11, 7, tzinfo=travel.LISBON)
        self.config = json.loads((Path(__file__).parents[1] / 'config/daily-report.json').read_text())
        patcher = patch.object(travel, 'TOMTOM_INTERVAL', 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def forecasts(self, points):
        start = self.now.replace(hour=0).timestamp()
        row = dict(zip(travel.FIELDS, [14, 0, 10, 15, 10000, 1]))
        wet = dict(row, precipitation=1.2, precipitation_probability=80, weather_code=61)
        return {p: {int(start + h * 3600): dict(wet if h in (15, 16) else row) for h in range(48)} for p in points}

    @staticmethod
    def route_data(url, params):
        minutes = 30 + (12 if datetime.fromisoformat(params['departAt']).hour == 18 else 0)
        return {'routes': [{'summary': {'travelTimeInSeconds': minutes * 60, 'noTrafficTravelTimeInSeconds': 30 * 60},
                            'legs': [{'points': [{'latitude': 41.36, 'longitude': -8.48},
                                                 {'latitude': 41.55, 'longitude': -8.43}]}]}]}

    def draft(self, key='fixture'):
        visuals = {}
        with patch.object(travel, 'get_json', side_effect=self.route_data), \
                patch.object(travel, 'forecasts', side_effect=self.forecasts):
            report = travel.build_report(self.config, self.now, key=key, visuals=visuals)
        # Round-trip through JSON exactly as the checkpointed email.json does.
        return {'subject': 'Tiny’s Daily Report', 'body_markdown': report + JOB_SEPARATOR + JOBS,
                'travel_visuals': json.loads(json.dumps(visuals))}

    def test_visuals_match_report_windows_and_hourly_weather(self):
        draft = self.draft()
        visuals = draft['travel_visuals']
        self.assertEqual([(r['origin'], r['destination']) for r in visuals['routes']], travel.ROUTES)
        self.assertEqual(len(visuals['places']['Braga']['hourly']), 24)
        for route in visuals['routes']:
            self.assertTrue(route['traffic'])
            self.assertEqual(len(route['departures']), 14)
            for window in route['windows']:
                self.assertIn(f"**{window['start']}–{window['end']}**", draft['body_markdown'])

    def test_email_embeds_charts_and_logos_inline(self):
        with patch('pm_scraper.actions_runner.smtplib.SMTP_SSL') as smtp:
            smtp.return_value.__enter__.return_value.send_message.return_value = {}
            Gmail('sender@example.org', 'fixture').send('recipient@example.org', self.draft(), '<fixture@example.org>')
        message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        images = {part['Content-ID']: part for part in message.walk() if part.get_content_type() == 'image/png'}
        self.assertEqual(set(images), {'<tiny-logo-bosch>', '<tiny-chart-weather>', '<tiny-chart-departures>'})
        for part in images.values():
            self.assertEqual(part.get_content_disposition(), 'inline')
            self.assertTrue(part.get_payload(decode=True).startswith(b'\x89PNG'))
        page = next(p for p in message.walk() if p.get_content_type() == 'text/html').get_content()
        document = html.fromstring(page)
        sources = document.xpath('//img/@src')
        self.assertIn('cid:tiny-chart-weather', sources)
        self.assertIn('cid:tiny-chart-departures', sources)
        self.assertIn('Areias', document.text_content())
        self.assertIn('View job →', document.text_content())
        plain = next(p for p in message.walk() if p.get_content_type() == 'text/plain').get_content()
        self.assertIn('# Weather and driving today', plain)

    def test_weather_only_still_draws_departure_chart_without_traffic_claims(self):
        page, attachments = render_draft_html(self.draft(key=''))
        self.assertIn('tiny-chart-departures', [cid for cid, _ in attachments])
        self.assertIn('Weather-only', page)
        self.assertNotIn('min traffic', page)

    def test_missing_matplotlib_or_visuals_degrades_to_styled_markdown(self):
        draft = self.draft()
        with patch.object(email_charts, '_pyplot', return_value=(None, None)):
            page, attachments = render_draft_html(draft)
        self.assertEqual([cid for cid, _ in attachments], ['tiny-logo-bosch'])
        self.assertIn('Best departure windows', page)
        legacy = dict(draft)
        del legacy['travel_visuals']
        page, attachments = render_draft_html(legacy)
        self.assertIn('Weather and driving today', page)
        self.assertEqual([cid for cid, _ in attachments], ['tiny-logo-bosch'])

    def test_failed_weather_report_does_not_attach_visuals(self):
        source = Path(__file__).parents[1]
        with patch.object(travel, 'build_report', side_effect=RuntimeError('provider down')):
            draft = travel.attach_report({'body_markdown': JOBS}, source)
        self.assertNotIn('travel_visuals', draft)
        page, _ = render_draft_html(draft)
        self.assertIn('Weather/travel data unavailable', page)


if __name__ == '__main__':
    unittest.main()
