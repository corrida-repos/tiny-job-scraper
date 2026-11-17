from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import io
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from pm_scraper import travel_report as travel


class TravelReportTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 11, 7, tzinfo=travel.LISBON)
        self.config = json.loads((Path(__file__).parents[1] / 'config/daily-report.json').read_text())
        self.row = dict(zip(travel.FIELDS, [14, 0, 10, 15, 10000, 1]))
        # No test may reach IPMA; dedicated tests below feed it fixtures.
        empty = {'nearest': {}, 'hourly': {}, 'probability': {}, 'daily': {}, 'warnings': []}
        self.ipma_patch = patch.object(travel, 'ipma_layer', return_value=empty)
        self.ipma_patch.start()
        self.addCleanup(patch.stopall)
        self.dest = list(self.config['destinations'])

    def forecasts(self, points):
        start = self.now.replace(hour=0).timestamp()
        return {p: {int(start + h * 3600): dict(self.row) for h in range(48)} for p in points}

    def route_data(self, url, params):
        # Reverse directions deliberately get different traffic predictions.
        minutes = 40 if '/41.36205,' in url else 60
        ends = [tuple(map(float, p.split(','))) for p in url.split('/calculateRoute/')[1].split('/')[0].split(':')]
        return {'routes': [{'summary': {'travelTimeInSeconds': minutes * 60,
                                       'noTrafficTravelTimeInSeconds': 30 * 60},
                            'legs': [{'points': [{'latitude': a, 'longitude': b} for a, b in ends]}]}]}

    def report_for(self, key='fixture', router=None, env=None, now=None):
        diagnostics = {}
        with patch.object(travel, 'get_json', side_effect=router or self.route_data), \
                patch.object(travel, 'forecasts', side_effect=self.forecasts), \
                patch.dict('os.environ', env or {}, clear=False):
            if not env:
                import os
                os.environ.pop('HOME_ADDRESS', None)
            report = travel.build_report(self.config, now or self.now, key=key, diagnostics=diagnostics)
        return report, diagnostics

    def test_best_leave_and_return_times_per_destination(self):
        def router(url, params):
            data = self.route_data(url, params)
            hour = int(params['departAt'][11:13])
            # Rush hours are slower: 08:00 and 18:00 should never win.
            if hour in (8, 18):
                data['routes'][0]['summary']['travelTimeInSeconds'] += 20 * 60
            return data
        report, diagnostics = self.report_for(router=router)
        for name in self.dest:
            self.assertIn(f'## {name}', report)
        self.assertEqual(report.count('**Leave home: 09:00**'), 4)
        self.assertEqual(report.count('**Return home: 15:00**'), 4)
        self.assertIn('- Avoid: 08:00', report)
        self.assertIn('- Avoid: 18:00', report)
        self.assertIn('heavy traffic', report)
        self.assertNotIn('rain only', report)
        self.assertEqual(diagnostics['routes'], 48)
        self.assertIn('used for all 8 trips', travel.traffic_status(report, key='fixture', diagnostics=diagnostics))

    def test_rain_moves_the_recommendation(self):
        start = self.now.replace(hour=0).timestamp()
        def forecasts(points):
            data = self.forecasts(points)
            for hourly in data.values():
                for h in (9, 10, 15, 16):
                    hourly[int(start + h * 3600)]['precipitation'] = 2
                    hourly[int(start + h * 3600)]['precipitation_probability'] = 90
            return data
        with patch.object(travel, 'get_json', side_effect=self.route_data), patch.object(travel, 'forecasts', side_effect=forecasts):
            report = travel.build_report(self.config, self.now, key='fixture')
        self.assertEqual(report.count('**Leave home: 11:00**'), 4)
        self.assertEqual(report.count('**Return home: 17:00**'), 4)
        self.assertIn('(rain 09:00–11:00, 15:00–17:00)', report)

    def test_home_address_is_geocoded_and_never_printed(self):
        seen = []
        def router(url, params):
            if '/geocode/' in url:
                return {'results': [{'position': {'lat': 41.3611, 'lon': -8.4801}}]}
            seen.append(url)
            return self.route_data(url, params)
        report, diagnostics = self.report_for(router=router, env={'HOME_ADDRESS': 'Secret Street 1, Areias'})
        self.assertEqual(diagnostics['home'], 'ok')
        self.assertTrue(any('41.3611,-8.4801:' in u for u in seen))
        self.assertIn('from home (Areias, Santo Tirso)', report)
        status = travel.traffic_status(report, key='fixture', diagnostics=diagnostics)
        self.assertNotIn('Secret', report + status)
        self.assertNotIn('41.3611', report + status)

    def test_far_or_failed_geocode_falls_back_to_parish_centre(self):
        def far(url, params):
            if '/geocode/' in url:
                return {'results': [{'position': {'lat': 38.72, 'lon': -9.14}}]}
            return self.route_data(url, params)
        report, diagnostics = self.report_for(router=far, env={'HOME_ADDRESS': 'x'})
        self.assertIn('too far', diagnostics['home'])
        self.assertIn('from Areias, Santo Tirso centre (home address not set up)', report)
        report, diagnostics = self.report_for()
        self.assertEqual(diagnostics['home'], 'HOME_ADDRESS not set')
        self.assertIn('HOME_ADDRESS not set', travel.traffic_status(report, key='fixture', diagnostics=diagnostics))

    def test_no_key_uses_rain_only_and_never_calls_router(self):
        with patch.object(travel, 'get_json') as network, patch.object(travel, 'forecasts', side_effect=self.forecasts):
            report = travel.build_report(self.config, self.now, key='')
        network.assert_not_called()
        self.assertEqual(report.count('based on rain only'), 8)
        self.assertNotIn('traffic (+', report)
        self.assertIn('not configured', travel.traffic_status(report, key=''))

    def test_provider_failure_degrades_to_rain_only_without_leaking(self):
        error = urllib.error.HTTPError('https://api.tomtom.com/x?key=private-key', 403, 'Forbidden', {}, None)
        report, diagnostics = self.report_for(key='private-key', router=lambda *a: (_ for _ in ()).throw(error))
        self.assertEqual(report.count('based on rain only'), 8)
        status = travel.traffic_status(report, key='private-key', diagnostics=diagnostics)
        self.assertIn('8 of 8 trips fell back', status)
        self.assertIn('HTTP 403 ×48', status)
        self.assertIn('São Vítor, Braga: lookup failed (HTTP 403)', status)
        self.assertIn('invalid or lacks Routing API access', status)
        self.assertNotIn('private-key', status + report)

    def test_one_failed_departure_keeps_traffic_for_the_trip(self):
        def flaky(url, params):
            if params['departAt'].startswith('2026-11-11T09:'):
                raise urllib.error.HTTPError(url, 429, 'Too Many Requests', {}, None)
            return self.route_data(url, params)
        report, diagnostics = self.report_for(router=flaky)
        self.assertNotIn('rain only', report)
        self.assertIn('No traffic forecast for 09:00', report)
        self.assertNotIn('**Leave home: 09:00**', report)
        self.assertEqual(diagnostics['errors'], {'HTTP 429': 4})

    # Real IPMA locality records for the area (api.ipma.pt public-data/forecast/locations.json).
    IPMA_LOCATIONS = [
        {'globalIdLocal': 1131400, 'local': 'Santo Tirso', 'idAreaAviso': 'PTO', 'latitude': '41.3412', 'longitude': '-8.4776'},
        {'globalIdLocal': 1131800, 'local': 'Trofa', 'idAreaAviso': 'PTO', 'latitude': '41.3390', 'longitude': '-8.5602'},
        {'globalIdLocal': 1130600, 'local': 'Maia', 'idAreaAviso': 'PTO', 'latitude': '41.2335', 'longitude': '-8.6216'},
        {'globalIdLocal': 1131200, 'local': 'Porto', 'idAreaAviso': 'PTO', 'latitude': '41.1580', 'longitude': '-8.6294'},
        {'globalIdLocal': 1031200, 'local': 'Vila Nova de Famalicão', 'idAreaAviso': 'BRG', 'latitude': '41.4087', 'longitude': '-8.5205'},
        {'globalIdLocal': 1030300, 'local': 'Braga', 'idAreaAviso': 'BRG', 'latitude': '41.5475', 'longitude': '-8.4227'},
        {'globalIdLocal': 1080500, 'local': 'Faro', 'idAreaAviso': 'FAR', 'latitude': '37.0146', 'longitude': '-7.9331'},
    ]

    def ipma_router(self, hourly=None, warnings=(), fail=False):
        """Serve IPMA fixtures shaped like the live API, TomTom routes otherwise."""
        start = self.now.replace(hour=0).astimezone(timezone.utc)
        def aggregate(gid):
            rows = []
            for h in range(48):
                when = start + timedelta(hours=h)
                row = {'idPeriodo': 1, 'globalIdLocal': gid, 'dataPrev': when.strftime('%Y-%m-%dT%H:%M:%S'),
                       'idTipoTempo': 3, 'probabilidadePrecipita': '5.0' if h % 3 == 0 else '-99.0'}
                row.update((hourly or (lambda gid, hour: {}))(gid, h))
                rows.append(row)
            rows.append({'idPeriodo': 24, 'globalIdLocal': gid, 'dataPrev': start.strftime('%Y-%m-%dT00:00:00'),
                         'idTipoTempo': 9, 'probabilidadePrecipita': '95.0'})
            return rows
        def router(url, params):
            if 'api.ipma.pt' in url:
                if fail:
                    raise urllib.error.URLError('down')
                if url.endswith('locations.json'):
                    return self.IPMA_LOCATIONS
                if 'warnings' in url:
                    return list(warnings)
                return aggregate(int(url.rsplit('/', 1)[1].split('.')[0]))
            return self.route_data(url, params)
        return router

    def ipma_report(self, **kw):
        self.ipma_patch.stop()
        return self.report_for(router=self.ipma_router(**kw))

    def test_ipma_probability_and_intensity_override_ecmwf(self):
        # ECMWF fixture says 10%; IPMA says 90% and moderate rain from 08:00 to 10:00 UTC.
        def wet(gid, hour):
            return {'probabilidadePrecipita': '90.0', 'idIntensidadePrecipita': 2, 'idTipoTempo': 9} if 8 <= hour <= 10 else {}
        report, diagnostics = self.ipma_report(hourly=wet)
        self.assertEqual(diagnostics['ipma'], 'ok')
        self.assertIn('moderate rain, 90% chance', report)
        self.assertEqual(report.count('**Leave home: 11:00**'), 4)
        self.assertIn('IPMA (Santo Tirso): rain/showers, 95% rain chance', report)
        self.assertIn('IPMA (Braga)', report)

    def test_orange_warning_rules_out_only_that_district(self):
        warning = {'idAreaAviso': 'BRG', 'awarenessTypeName': 'Precipitação', 'awarenessLevelID': 'orange',
                   'startTime': '2026-11-11T07:00:00', 'endTime': '2026-11-11T13:00:00',
                   'text': 'Chuva por vezes forte.'}
        sea = dict(warning, awarenessTypeName='Agitação Marítima', awarenessLevelID='red')
        report, _ = self.ipma_report(warnings=[warning, sea])
        self.assertIn('IPMA orange warning — rain, Braga district, 07:00–11/11 13:00.** Chuva por vezes forte.', report)
        self.assertNotIn('IPMA red', report)
        self.assertEqual(report.count('⚠ **IPMA'), 1)
        braga = report.split('## São Vítor, Braga')[1].split('## ')[0]
        self.assertIn('**Leave home:** no good time', braga)
        self.assertIn('**Return home: 15:00**', braga)
        porto = report.split('## Porto city centre')[1].split('## ')[0]
        self.assertIn('**Leave home: 08:00**', porto)

    def test_ipma_thunderstorms_are_never_recommended(self):
        storm = lambda gid, hour: {'idTipoTempo': 23, 'idIntensidadePrecipita': 2}
        report, _ = self.ipma_report(hourly=storm)
        self.assertEqual(report.count('no good time'), 8)

    def test_ipma_outage_keeps_ecmwf_report(self):
        report, diagnostics = self.ipma_report(fail=True)
        self.assertIn('IPMA was unavailable for this run', report)
        self.assertEqual(report.count('**Leave home: 08:00**'), 4)
        self.assertIn('IPMA unavailable (network error); ECMWF only.',
                      travel.traffic_status(report, key='fixture', diagnostics=diagnostics))

    def test_ipma_ignores_localities_far_away(self):
        self.ipma_patch.stop()
        with patch.object(travel, 'get_json', side_effect=self.ipma_router()):
            layer = travel.ipma_layer([(41.36, -8.48), (39.5, -8.0)], self.now.date())
        self.assertEqual([l['local'] for l in layer['nearest'].values()], ['Santo Tirso'])

    def test_rate_limited_requests_are_retried_but_bad_keys_are_not(self):
        url = 'https://api.tomtom.com/routing'
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        calls = []
        def throttled(request, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.HTTPError(url, 403, 'Forbidden', {}, io.BytesIO(b'Developer Over Qps'))
            if len(calls) == 2:
                raise urllib.error.HTTPError(url, 429, 'Too Many Requests', {}, None)
            return Response(b'{"ok": true}')
        with patch('urllib.request.urlopen', side_effect=throttled), patch.object(travel.time, 'sleep'):
            self.assertEqual(travel.get_json(url, {'key': 'k'}), {'ok': True})
        self.assertEqual(len(calls), 3)
        calls.clear()
        def forbidden(request, timeout):
            calls.append(1)
            raise urllib.error.HTTPError(url, 403, 'Forbidden', {}, io.BytesIO(b'Developer Inactive'))
        with patch('urllib.request.urlopen', side_effect=forbidden), patch.object(travel.time, 'sleep'):
            with self.assertRaises(urllib.error.HTTPError):
                travel.get_json(url, {'key': 'k'})
        self.assertEqual(len(calls), 1)

    def test_missing_weather_excludes_samples_instead_of_assuming_clear(self):
        self.row['visibility'] = None
        report, _ = self.report_for(key='')
        self.assertNotIn('**Leave home:', report.replace('**Leave home:** no', ''))
        self.assertIn('Weather data missing for 48 departure times', report)

    def test_severe_weather_never_recommends_least_bad_time(self):
        self.row['precipitation'] = 6
        report, _ = self.report_for(key='')
        self.assertEqual(report.count('no good time'), 8)

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
        report, _ = self.report_for(key='', now=self.now.replace(hour=22))
        self.assertEqual(report.count('no times left to check today'), 8)
        report, _ = self.report_for(key='', now=self.now.replace(hour=13))
        self.assertEqual(report.count('**Leave home:** no times left'), 4)
        self.assertEqual(report.count('**Return home: 15:00**'), 4)

    def test_full_day_summary_uses_lisbon_date_across_summer_offset(self):
        utc = datetime(2026, 7, 10, 0, tzinfo=timezone.utc)
        self.now = utc.astimezone(travel.LISBON)
        self.assertEqual(utc.astimezone(travel.LISBON).hour, 1)
        with patch.object(travel, 'forecasts', side_effect=self.forecasts):
            report = travel.build_report(self.config, utc, key='')
        self.assertIn('generated 01:00 WEST', report)
        self.assertIn('**Home:** 14–14 °C', report)

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
