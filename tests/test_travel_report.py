from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import io
import unittest
import urllib.error
from unittest.mock import patch

from pm_scraper import travel_report as travel


class TravelReportTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 11, 7, tzinfo=travel.LISBON)
        self.config = json.loads((Path(__file__).parents[1] / 'config/daily-report.json').read_text())
        self.row = dict(zip(travel.FIELDS, [14, 0, 10, 15, 10000, 1]))
        for name in ('TOMTOM_INTERVAL', 'TOMTOM_BACKOFF'):
            patcher = patch.object(travel, name, 0)
            patcher.start()
            self.addCleanup(patcher.stop)

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

    def test_traffic_status_distinguishes_missing_key_working_and_failing_routing(self):
        with patch.object(travel, 'get_json', side_effect=self.route_data), patch.object(travel, 'forecasts', side_effect=self.forecasts):
            working = travel.build_report(self.config, self.now, key='private-key')
        with patch.object(travel, 'get_json', side_effect=RuntimeError('secret-url')), patch.object(travel, 'forecasts', side_effect=self.forecasts):
            failing = travel.build_report(self.config, self.now, key='private-key')
        self.assertIn('not configured', travel.traffic_status(failing, key=''))
        self.assertIn('used for all 4 directions', travel.traffic_status(working, key='private-key'))
        status = travel.traffic_status(failing, key='private-key')
        self.assertIn('4 of 4 directions fell back', status)
        self.assertNotIn('private-key', status)

    @staticmethod
    def http_error(code):
        return urllib.error.HTTPError('https://api.tomtom.com/?key=private-key', code, 'error',
                                      {}, io.BytesIO(b''))

    def test_rate_limited_requests_are_retried_instead_of_dropping_traffic(self):
        calls = []

        def flaky(url, params):
            calls.append(url)
            if len(calls) % 3 == 1:
                raise self.http_error(429)
            return self.route_data(url, params)
        diagnostics = {}
        with patch.object(travel, 'get_json', side_effect=flaky), patch.object(travel, 'forecasts', side_effect=self.forecasts):
            report = travel.build_report(self.config, self.now, key='private-key', diagnostics=diagnostics)
        self.assertNotIn('Weather-only comparison', report)
        self.assertNotIn('Traffic unavailable for', report)
        self.assertEqual(diagnostics['failed'], 0)
        self.assertGreater(len(calls), 56)

    def test_one_failed_departure_keeps_traffic_for_the_rest_of_the_direction(self):
        def one_failure(url, params):
            if '/41.36205,' in url and params['departAt'].startswith('2026-11-11T21'):
                raise self.http_error(400)
            return self.route_data(url, params)
        diagnostics = {}
        with patch.object(travel, 'get_json', side_effect=one_failure), patch.object(travel, 'forecasts', side_effect=self.forecasts):
            report = travel.build_report(self.config, self.now, key='private-key', diagnostics=diagnostics)
        self.assertNotIn('Weather-only comparison', report)
        self.assertEqual(report.count('Traffic unavailable for 1 of 14 departures'), 2)
        self.assertNotIn('**20:00–21:00**: lower weather concern; 40', report)
        status = travel.traffic_status(report, key='private-key', diagnostics=diagnostics)
        self.assertIn('used for all 4 directions', status)
        self.assertIn('2 of 56 routing requests failed (HTTP 400 ×2)', status)

    def test_rejected_key_is_reported_with_status_code_but_without_secrets(self):
        diagnostics = {}
        with patch.object(travel, 'get_json', side_effect=self.http_error(403)) as network, \
                patch.object(travel, 'forecasts', side_effect=self.forecasts):
            report = travel.build_report(self.config, self.now, key='private-key', diagnostics=diagnostics)
        self.assertEqual(network.call_count, 56)  # 403 is not retried
        status = travel.traffic_status(report, key='private-key', diagnostics=diagnostics)
        self.assertIn('4 of 4 directions fell back', status)
        self.assertIn('HTTP 403 ×56', status)
        self.assertIn('lacks Routing API access', status)
        self.assertNotIn('private-key', status + report)

    def test_late_run_status_says_traffic_was_not_queried(self):
        diagnostics = {}
        with patch.object(travel, 'get_json') as network, patch.object(travel, 'forecasts', side_effect=self.forecasts):
            report = travel.build_report(self.config, self.now.replace(hour=22), key='private-key', diagnostics=diagnostics)
        network.assert_not_called()
        status = travel.traffic_status(report, key='private-key', diagnostics=diagnostics)
        self.assertIn('TomTom was not queried', status)
        self.assertNotIn('routing failed', status)

    def test_throttle_spaces_requests_across_threads(self):
        throttle = travel.Throttle(0.05)
        starts = []
        with travel.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: (throttle.wait(), starts.append(travel.time.monotonic())), range(5)))
        starts.sort()
        self.assertGreaterEqual(starts[-1] - starts[0], 0.19)

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
