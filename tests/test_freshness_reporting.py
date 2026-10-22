"""Unverified/future publication can be displayed without passing freshness."""
import unittest

from pm_scraper.daily import prepare_email, select_roles
from pm_scraper.filtering import Screener
from pm_scraper.branding import company_heading
from test_screening import CFG, NOW, BASE, job


class FreshnessReportingTests(unittest.TestCase):
    def setUp(self):
        self.screener = Screener(CFG)
        self.payload = {'started_at': NOW.isoformat(), 'freshness_hours': 48,
                        'sources': [], 'coverage': {'sources': 1, 'complete': 1, 'attention': 0},
                        'criteria': {**CFG, 'include_unknown_freshness': True, 'include_future_dated': True}}

    def pair(self, **values):
        candidate = job(**values)
        return candidate, self.screener.assess(candidate, NOW)

    def position_heading(self, draft):
        return next(line for line in draft['body_markdown'].splitlines() if line.startswith('### '))

    def test_missing_date_is_included_and_explicitly_labelled(self):
        pair = self.pair(posted_at=None, date_kind='unknown')
        self.assertEqual(pair[1].status, 'review')
        self.assertEqual(pair[1].checks['freshness']['status'], 'unknown')
        draft = prepare_email([pair], self.payload)
        self.assertEqual(draft['job_keys'], [pair[0].key])
        self.assertEqual(draft['unknown_freshness_job_keys'], [pair[0].key])
        self.assertTrue(draft['body_markdown'].startswith('# Unknown Freshness\n'))
        self.assertNotIn('freshness', self.position_heading(draft).lower())
        self.assertNotIn('future and unverified dates excluded', draft['body_markdown'])

    def test_last_published_and_recent_date_only_remain_unknown(self):
        for values in [{'date_kind': 'last_published'}, {'date_kind': 'updated'},
                       {'posted_at': '2026-10-19', 'date_kind': 'original_posted'}]:
            with self.subTest(values=values):
                pair = self.pair(**values)
                draft = prepare_email([pair], self.payload)
                self.assertEqual(draft['unknown_freshness_job_keys'], [pair[0].key])
                self.assertEqual(pair[1].checks['freshness']['status'], 'unknown')

    def test_future_original_and_syndicated_dates_use_unknown_freshness_category(self):
        for kind in ['original_posted', 'last_published']:
            with self.subTest(kind=kind):
                pair = self.pair(posted_at='2026-10-20T12:00:00Z', date_kind=kind)
                draft = prepare_email([pair], self.payload)
                self.assertEqual(draft['future_dated_job_keys'], [pair[0].key])
                self.assertEqual(draft['unknown_freshness_job_keys'], [pair[0].key])
                self.assertTrue(draft['body_markdown'].startswith('# Unknown Freshness\n'))
                self.assertNotIn('freshness', self.position_heading(draft).lower())
                self.assertNotIn('**Future-dated**', draft['body_markdown'])
                self.assertEqual(pair[1].status, 'review')
                self.assertEqual(pair[1].checks['freshness']['category'], 'future_date')

    def test_combined_unknown_freshness_count_includes_both_kinds(self):
        missing = self.pair(title='Alpha Project Manager', posted_at=None)
        future = self.pair(source_id='future', title='Beta Project Manager', posted_at='2026-10-20')
        draft = prepare_email([missing, future], self.payload)
        self.assertEqual(set(draft['unknown_freshness_job_keys']), {missing[0].key, future[0].key})
        self.assertEqual(draft['body_markdown'].count('# Unknown Freshness\n'), 1)
        self.assertNotIn('**Unknown freshness**', draft['body_markdown'])
        self.assertNotIn('Future-dated', draft['body_markdown'])

    def test_unknown_and_future_switches_are_independent(self):
        missing = self.pair(posted_at=None, date_kind='unknown')
        future = self.pair(source_id='future', posted_at='2026-10-20T12:00:00Z')
        for allow_unknown, allow_future, expected in [(False, False, []),
                (True, False, [missing[0].key]), (False, True, [future[0].key]),
                (True, True, [missing[0].key, future[0].key])]:
            with self.subTest(unknown=allow_unknown, future=allow_future):
                selected, _ = select_roles([missing, future], True, allow_unknown, allow_future)
                self.assertEqual({j.key for j, a in selected}, set(expected))

    def test_known_old_dates_other_hard_failures_and_unchecked_forms_stay_excluded(self):
        pairs = [self.pair(posted_at='2026-01-01'),
                 self.pair(source_id='residence', posted_at=None, date_kind='unknown', description=BASE+' You must reside in Lisbon.'),
                 self.pair(source_id='experience', posted_at='2026-10-20', description=BASE+' Minimum 8 years of experience required.'),
                 self.pair(source_id='form', posted_at=None, metadata={'application_requirements_checked': False})]
        self.assertEqual(prepare_email(pairs, self.payload)['job_keys'], [])

    def test_unknown_and_future_dates_cannot_bypass_other_hard_requirements(self):
        screener = Screener({**CFG, 'max_office_days_per_week': 3})
        failures = [
            ('attendance', {'workplace': 'onsite', 'location': 'Porto', 'description': BASE+' Attend the office 3 days per week.'}),
            ('attendance', {'workplace': 'presencial', 'location': 'Porto'}),
            ('attendance', {'location': 'Porto, Portugal (On-site)'}),
            ('attendance', {'description': BASE+' This role is fully on-site.'}),
            ('attendance', {'description': BASE+' This is an on-site position.'}),
            ('attendance', {'description': BASE+' Regime de trabalho presencial.'}),
            ('attendance', {'description': BASE+' Modelo de trabalho: presencial.'}),
            ('attendance', {'workplace': 'hybrid', 'location': 'Porto', 'description': BASE+' Attend the office 4 days per week.'}),
            ('residence', {'description': BASE+' This candidate must reside in Lisbon.'}),
            ('residence', {'metadata': {'application_questions': [{'label': 'This candidate must reside in Lisbon.', 'description': ''}]}}),
            ('experience', {'description': BASE+' Minimum 8 years of experience required.'}),
            ('languages', {'description': BASE+' Fluent German is required.'}),
            ('travel', {'description': BASE.replace('No travel required.', 'Business travel is at most 10 calendar days per quarter including transit.')}),
            ('code_writing', {'description': BASE+' You must write production code.'}),
            ('work_schedule', {'description': BASE+' You must join the on-call rotation.'}),
            ('portugal_eligibility', {'countries': ['US'], 'location': 'Remote United States', 'description': BASE.replace('within Portugal', 'within the United States')}),
        ]
        for date in [None, '2026-10-20T12:00:00Z']:
            for requirement, values in failures:
                with self.subTest(date=date, requirement=requirement, values=values):
                    candidate = job(posted_at=date, **values)
                    assessed = screener.assess(candidate, NOW)
                    self.assertEqual(assessed.checks[requirement]['status'], 'fail')
                    self.assertEqual(prepare_email([(candidate, assessed)], self.payload)['job_keys'], [])

    def test_three_day_hybrid_remains_distinct_from_full_onsite(self):
        screener = Screener({**CFG, 'max_office_days_per_week': 3})
        candidate = job(posted_at=None, workplace='hybrid', location='Porto', description=BASE+' Hybrid role: attend the office 3 days per week.')
        assessed = screener.assess(candidate, NOW)
        self.assertEqual(assessed.checks['attendance']['status'], 'pass')
        self.assertEqual(prepare_email([(candidate, assessed)], self.payload)['job_keys'], [candidate.key])

    def test_attendance_override_cannot_allow_an_explicit_onsite_role(self):
        candidate = job(posted_at=None, workplace='onsite', location='Porto')
        assessed = self.screener.assess(candidate, NOW, {'verified_at': NOW.isoformat(),
            'evidence': 'Older office arrangement confirmation', 'checks': {'attendance': 'pass'}})
        self.assertEqual(assessed.checks['attendance']['status'], 'fail')
        self.assertEqual(prepare_email([(candidate, assessed)], self.payload)['job_keys'], [])

    def test_verified_only_mode_still_excludes_unverified_matches(self):
        self.payload['criteria']['include_potential_matches'] = False
        pairs = [self.pair(), self.pair(source_id='unknown', posted_at=None),
                 self.pair(source_id='future', posted_at='2026-10-20')]
        self.assertEqual(prepare_email(pairs, self.payload)['job_keys'], [pairs[0][0].key])

    def test_known_recent_posting_has_no_unverified_badge(self):
        draft = prepare_email([self.pair()], self.payload)
        self.assertNotIn('Unknown freshness', self.position_heading(draft))
        self.assertNotIn('Future-dated', self.position_heading(draft))
        self.assertEqual(draft['unknown_freshness_job_keys'], [])
        self.assertEqual(draft['future_dated_job_keys'], [])

    def test_unclassified_unknown_freshness_is_not_automatically_admitted(self):
        pair = self.pair(posted_at=None)
        del pair[1].checks['freshness']['category']
        self.assertEqual(prepare_email([pair], self.payload)['job_keys'], [])

    def test_future_date_does_not_gain_verified_recency_priority(self):
        unknown = self.pair(title='Alpha Project Manager', posted_at=None)
        future = self.pair(source_id='future', title='Beta Project Manager', posted_at='2026-10-20')
        selected, _ = select_roles([future, unknown], True, True, True)
        self.assertEqual([j.key for j, a in selected], [unknown[0].key, future[0].key])

    def test_hierarchy_is_freshness_then_company_then_position(self):
        verified_bosch = self.pair(source_id='verified-bosch', title='Verified Project Manager', description=BASE.replace('No travel required.', ''))
        verified_vestas = self.pair(source_id='verified-vestas', company_id='vestas', company='Vestas')
        unknown_mindera = self.pair(source_id='unknown-mindera', company_id='mindera', company='Mindera', posted_at=None)
        unknown_bosch = self.pair(source_id='unknown-bosch', title='Unknown Project Manager', posted_at=None)
        future_bosch = self.pair(source_id='future-bosch', title='Future Project Manager', posted_at='2026-10-20')
        for pair, rank in [(verified_bosch,20), (verified_vestas,30), (unknown_mindera,1), (unknown_bosch,20), (future_bosch,20)]:
            pair[0].metadata['employer_rank'] = rank
        draft = prepare_email([unknown_bosch, unknown_mindera, verified_vestas, future_bosch, verified_bosch], self.payload)
        body = draft['body_markdown']
        verified, unknown = body.split('# Unknown Freshness\n')
        self.assertTrue(verified.startswith('# Verified Freshness\n'))
        self.assertLess(verified.index(company_heading('bosch','Bosch')),verified.index(company_heading('vestas','Vestas')))
        self.assertLess(unknown.index(company_heading('mindera','Mindera')),unknown.index(company_heading('bosch','Bosch')))
        self.assertEqual(unknown.count(company_heading('bosch','Bosch')+'\n'),1)
        self.assertIn('### **Future Project Manager**',unknown)
        self.assertIn('### **Unknown Project Manager**',unknown)
        self.assertNotIn('**Unknown freshness**',body)
        self.assertEqual(draft['job_keys'],[p[0].key for p in [verified_bosch,verified_vestas,unknown_mindera,future_bosch,unknown_bosch]])
