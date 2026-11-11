from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pm_scraper import travel_report as travel


class TravelReportTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 11, 7, tzinfo=travel.LISBON)
        self.config = json.loads((Path(__file__).parents[1] / 'config/daily-report.json').read_text())
        self.row = dict(zip(travel.FIELDS, [14, 0, 10, 15, 10000, 1]))

    def forecasts(self, points):
        start = self.now.replace(hour=0).timestamp()
        return {p: {int(start + h * 3600): dict(self.row) for h in range(48)} for p in points}

    def route_data(self, url, params):
        # Reverse directions deliberately get different traffic predictions.
        minutes = 40 if '/41.36205,' in url else 60
        return {'routes': [{'summary': {'travelTimeInSeconds': minutes * 60,
                                       'noTrafficTravelTimeInSeconds': 30 * 60},
                            'legs': [{'points': [{'latitude': 41.36, 'longitude': -8.48},
                                                 {'latitude': 41.55, 'longitude': -8.43}]}]}]}

    def test_forecast_traffic_directions_and_weather_are_in_report(self):
        with patch.object(travel, 'get_json', side_effect=self.route_data), patch.object(travel, 'forecasts', side_effect=self.forecasts):
            report = travel.build_report(self.config, self.now, key='fixture')
        self.assertNotIn('Weather-only comparison', report)
        self.assertIn('40–40 min', report)
        self.assertIn('60–60 min', report)
        self.assertIn('08:00–09:00', report)
        for a, b in travel.ROUTES:
            self.assertIn(f'{a} → {b}', report)

    def test_no_key_does_not_invent_traffic_or_call_router(self):
        with patch.object(travel, 'get_json') as network, patch.object(travel, 'forecasts', side_effect=self.forecasts):
            report = travel.build_report(self.config, self.now, key='')
        network.assert_not_called()
        self.assertEqual(report.count('Weather-only comparison'), 4)
        self.assertNotIn('traffic uplift up to', report)

    def test_provider_failure_degrades_to_explicit_weather_only(self):
        with patch.object(travel, 'get_json', side_effect=RuntimeError('secret-url')), patch.object(travel, 'forecasts', side_effect=self.forecasts):
            report = travel.build_report(self.config, self.now, key='private-key')
        self.assertEqual(report.count('Weather-only comparison'), 4)
        self.assertNotIn('private-key', report)
        self.assertNotIn('secret-url', report)

    def test_missing_weather_excludes_samples_instead_of_assuming_clear(self):
        self.row['visibility'] = None
        with patch.object(travel, 'forecasts', side_effect=self.forecasts):
            report = travel.build_report(self.config, self.now, key='')
        self.assertNotIn('**08:00–09:00**', report)
        self.assertIn('No recommended window', report)
        self.assertIn('Weather coverage missing for 56 departure samples', report)

    def test_severe_weather_never_recommends_least_bad_window(self):
        self.row['precipitation'] = 6
        with patch.object(travel, 'forecasts', side_effect=self.forecasts):
            report = travel.build_report(self.config, self.now, key='')
        self.assertEqual(report.count('No recommended window'), 4)
        self.assertIn('Higher weather concern', report)

    def test_bounding_hours_catch_rain_at_arrival(self):
        t = int(self.now.timestamp())
        hourly = {t: dict(self.row), t + 3600: dict(self.row, precipitation=7)}
        self.assertEqual(travel.weather_at(hourly, self.now + timedelta(minutes=15))['rain'], 7)
        del hourly[t + 3600]
        with self.assertRaises(KeyError):
            travel.weather_at(hourly, self.now + timedelta(minutes=15))

    def test_route_sampling_follows_bend_not_straight_line(self):
        points = [(41, -8), (42, -8), (42, -7)]
        samples = travel.sample_path(points)
        self.assertEqual(samples[0][0], points[0])
        self.assertEqual(samples[-1][0], points[-1])
        self.assertTrue(all(p[1] == -8 or p[0] == 42 for p, _ in samples))

    def test_late_manual_run_has_no_past_departure_recommendations(self):
        with patch.object(travel, 'forecasts', side_effect=self.forecasts):
            report = travel.build_report(self.config, self.now.replace(hour=22), key='')
        self.assertEqual(report.count('No recommended window'), 4)
        self.assertNotIn('**08:00–09:00**', report)

    def test_full_day_summary_uses_lisbon_date_across_summer_offset(self):
        utc = datetime(2026, 7, 10, 0, tzinfo=timezone.utc)
        self.now = utc.astimezone(travel.LISBON)
        self.assertEqual(utc.astimezone(travel.LISBON).hour, 1)
        with patch.object(travel, 'forecasts', side_effect=self.forecasts):
            report = travel.build_report(self.config, utc, key='')
        self.assertIn('generated 01:00 WEST', report)
        self.assertIn('**Areias:** 14–14 °C', report)

    def test_weather_outage_keeps_job_report_and_renames_email(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'config').mkdir()
            (root / 'config/daily-report.json').write_text(json.dumps(self.config))
            with patch.object(travel, 'build_report', side_effect=RuntimeError('secret')):
                result = travel.attach_report({'subject': 'old', 'body_markdown': 'Job evidence'}, root)
        self.assertEqual(result['subject'], 'Tiny’s Daily Report')
        self.assertIn('data unavailable', result['body_markdown'])
        self.assertIn('Job evidence', result['body_markdown'])
        self.assertNotIn('secret', result['body_markdown'])

    def test_schedule_selects_one_trigger_in_winter_and_summer(self):
        workflow = (Path(__file__).parents[1] / '.github/workflows/daily-jobs.yml').read_text()
        # Execute the actual workflow gate without adding a YAML dependency.
        gate = workflow.split("python - <<'PYGATE'\n", 1)[1].split('          PYGATE', 1)[0]
        gate = '\n'.join(line[10:] for line in gate.splitlines())
        for month, expected_hour in [(1, 6), (7, 5)]:
            for cron_hour in (5, 6):
                class Clock(datetime):
                    @classmethod
                    def now(cls, tz=None):
                        # A delayed execution still chooses the seasonal trigger.
                        return datetime(2026, month, 10, 9, tzinfo=travel.LISBON)
                with tempfile.TemporaryDirectory() as temp:
                    output = Path(temp) / 'gate'
                    env = {'EVENT_NAME': 'schedule', 'EVENT_SCHEDULE': f'53 {cron_hour} * * *', 'GITHUB_OUTPUT': str(output)}
                    with patch.dict('os.environ', env), patch('datetime.datetime', Clock):
                        exec(gate, {})
                    self.assertEqual(output.exists(), cron_hour == expected_hour)


if __name__ == '__main__':
    unittest.main()
