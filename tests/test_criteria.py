"""User settings must change screening/reporting without editing Python."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pm_scraper.cli import main
from pm_scraper.criteria import freshness_days, load, validate
from pm_scraper.daily import prepare_email
from pm_scraper.filtering import Screener
from pm_scraper.models import FetchResult
from test_screening import CFG, NOW, BASE, job

ROOT = Path(__file__).resolve().parents[1]


class ConfigurableCriteriaTests(unittest.TestCase):
    def assess(self, settings=None, **values):
        return Screener({**CFG, **(settings or {})}).assess(job(**values), NOW)

    def test_repository_settings_are_valid(self):
        load(ROOT / 'config/criteria.json')

    def test_reject_invalid_settings(self):
        for changes in [{'max_post_age_days': 0}, {'max_post_age_days': True},
                        {'max_mandatory_experience_years': -1}, {'max_office_days_per_week': 6},
                        {'include_potential_matches': 'false'}, {'role_families': []},
                        {'allowed_languages': ['Klingon']}, {'allowed_languages': ['English', 'English']},
                        {'max_experence_years': 8}, {'timezone': 'invalid/zone'}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate({**CFG, **changes})

    def test_removed_role_family_disables_its_translated_alias(self):
        screener = Screener({**CFG, 'role_families': ['Project Manager']})
        self.assertIsNone(screener.family('Product Manager'))
        self.assertIsNone(screener.family('Gestor de Produto'))
        self.assertEqual(screener.family('Gestor de Projeto'), 'Project Manager')

    def test_languages_are_configurable_in_both_directions(self):
        text = BASE + ' Fluent German is required.'
        self.assertEqual(self.assess(description=text).checks['languages']['status'], 'fail')
        self.assertEqual(self.assess({'allowed_languages': CFG['allowed_languages'] + ['German']},
                                    description=text).checks['languages']['status'], 'pass')
        self.assertEqual(self.assess({'allowed_languages': ['Portuguese']}).checks['languages']['status'], 'fail')
        self.assertEqual(self.assess(description=BASE + ' German is optional.').checks['languages']['status'], 'pass')

    def test_experience_threshold_and_evidence_follow_setting(self):
        text = BASE + ' Minimum 7 years of experience required.'
        self.assertEqual(self.assess(description=text).checks['experience']['status'], 'fail')
        changed = self.assess({'max_mandatory_experience_years': 8}, description=text)
        self.assertEqual(changed.checks['experience']['status'], 'pass')
        self.assertIn('8 years', changed.checks['experience']['evidence'])

    def test_office_and_travel_caps_follow_settings(self):
        text = BASE.replace('Fully remote within Portugal.', 'Hybrid. Attend the office 3 days per week.')
        self.assertEqual(self.assess(location='Porto', description=text).checks['attendance']['status'], 'fail')
        self.assertEqual(self.assess({'max_office_days_per_week': 3}, location='Porto', description=text).checks['attendance']['status'], 'pass')
        text = BASE + ' Visit the office twice per quarter.'
        self.assertEqual(self.assess(location='Lisbon', description=text).checks['attendance']['status'], 'fail')
        self.assertEqual(self.assess({'max_distant_office_visits_per_quarter': 2}, location='Lisbon', description=text).checks['attendance']['status'], 'pass')
        text = BASE + ' Visit the office quarterly.'
        self.assertEqual(self.assess({'max_distant_office_visits_per_quarter': 0}, location='Lisbon', description=text).checks['attendance']['status'], 'fail')
        text = BASE.replace('No travel required.', 'All business travel is at most 10 calendar days per quarter including transit.')
        self.assertEqual(self.assess(description=text).checks['travel']['status'], 'fail')
        self.assertEqual(self.assess({'max_abroad_calendar_days_per_quarter': 10}, description=text).checks['travel']['status'], 'pass')

    def test_coding_and_on_call_switches_preserve_other_failures(self):
        for setting, check, extra in [('exclude_mandatory_coding', 'code_writing', ' You must write production code.'),
                                     ('exclude_shift_on_call', 'work_schedule', ' You must join the on-call rotation.')]:
            with self.subTest(setting=setting):
                self.assertEqual(self.assess(description=BASE + extra).checks[check]['status'], 'fail')
                relaxed = self.assess({setting: False}, description=BASE + extra)
                self.assertEqual(relaxed.status, 'eligible')
                self.assertEqual(relaxed.checks[check]['status'], 'informational')
                self.assertEqual(self.assess({setting: False}, description=BASE + extra + ' Fluent German required.').status, 'rejected')

    def test_report_switch_never_includes_stale_unknown_or_rejected_roles(self):
        jobs = [job(source_id='eligible'), job(source_id='review', description=BASE.replace('No travel required.', '')),
                job(source_id='old', posted_at='2026-01-01'), job(source_id='unknown', date_kind='updated'),
                job(source_id='rejected', description=BASE + ' Fluent German required.')]
        pairs = [(j, self.assess(source_id=j.source_id, description=j.description, posted_at=j.posted_at, date_kind=j.date_kind)) for j in jobs]
        payload = {'started_at': NOW.isoformat(), 'coverage': {'sources': 1, 'complete': 1, 'attention': 0}, 'sources': []}
        self.assertEqual(set(prepare_email(pairs, payload)['job_keys']), {jobs[0].key, jobs[1].key})
        payload['criteria'] = {'include_potential_matches': False}
        self.assertEqual(prepare_email(pairs, payload)['job_keys'], [jobs[0].key])

    def test_configured_freshness_and_manual_override_leave_file_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);(root / 'config').mkdir()
            path = root / 'config/criteria.json'
            raw = json.dumps({**CFG, 'max_post_age_days': 5});path.write_text(raw)
            self.assertEqual(freshness_days(root), 5)
            self.assertEqual(freshness_days(root, 7), 7)
            self.assertEqual(path.read_text(), raw)

    def test_cli_applies_custom_file_and_records_effective_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);path = root / 'criteria.json';out = root / 'out'
            cfg = {**CFG, 'max_post_age_days': 5, 'max_mandatory_experience_years': 8,
                   'include_potential_matches': False}
            path.write_text(json.dumps(cfg))
            result = FetchResult('bosch', 'Bosch', 'fixture', jobs=[job(posted_at='2026-10-15T12:00:00Z',
                                 description=BASE + ' Minimum 7 years of experience required.')])
            with patch('pm_scraper.cli.utcnow', return_value=NOW), patch('pm_scraper.cli.Fetcher') as fetcher:
                fetcher.return_value.fetch.return_value = result
                code = main(['run', '--only', 'bosch', '--criteria', str(path), '--state', str(root / 'state.sqlite3'), '--output', str(out)])
            self.assertEqual(code, 0)
            report = json.loads((out / 'results.json').read_text())
            self.assertEqual(report['criteria'], cfg)
            self.assertEqual(report['freshness_hours'], 120)
            self.assertEqual(len(json.loads((out / 'email.json').read_text())['job_keys']), 1)

    def test_bad_settings_fail_before_retrieval(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);path = root / 'criteria.json'
            path.write_text(json.dumps({**CFG, 'allowed_languages': ['Englsh']}))
            with patch('pm_scraper.cli.HttpClient') as http:
                self.assertEqual(main(['validate-criteria', '--criteria', str(path)]), 1)
                self.assertEqual(main(['run', '--criteria', str(path), '--state', str(root / 'state.sqlite3'), '--output', str(root / 'out')]), 1)
                http.assert_not_called()
            self.assertFalse((root / 'state.sqlite3').exists())
