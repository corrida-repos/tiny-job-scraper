import unittest
from datetime import datetime

from pm_scraper.criteria import validate, experience_ceiling
from pm_scraper.filtering import Screener
from test_screening import CFG, BASE, job


class ExperienceGrowthTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {**CFG, 'max_mandatory_experience_years':4,
                    'experience_growth_anchor':'2026-09-01'}

    def test_annual_rollover_uses_lisbon_local_date(self):
        for timestamp, expected in [('2026-10-22T12:00:00+00:00',4),
                                    ('2027-08-31T22:59:59+00:00',4),
                                    ('2027-08-31T23:00:00+00:00',5),
                                    ('2028-08-31T23:00:00+00:00',6),
                                    ('2025-09-01T12:00:00+00:00',4)]:
            with self.subTest(timestamp=timestamp):
                self.assertEqual(experience_ceiling(self.cfg,datetime.fromisoformat(timestamp)),expected)

    def test_requirement_and_evidence_follow_annual_ceiling(self):
        s=Screener(self.cfg)
        for timestamp, limit in [('2026-10-22T12:00:00+00:00',4),('2027-09-01T12:00:00+00:00',5),('2028-09-01T12:00:00+00:00',6)]:
            for minimum in [4,5,6,7]:
                j=job(description=BASE+f' {minimum}+ years of experience required.')
                check=s.assess(j,datetime.fromisoformat(timestamp)).checks['experience']
                self.assertEqual(check['status'],'pass' if minimum<=limit else 'fail')
                self.assertEqual(check['limit_years'],limit)

    def test_preference_remains_allowed_and_range_uses_minimum(self):
        s=Screener(self.cfg);now=datetime.fromisoformat('2026-10-22T12:00:00+00:00')
        for text in ['4–6 years of experience required.','8 years of experience preferred.']:
            self.assertEqual(s.assess(job(description=BASE+text),now).checks['experience']['status'],'pass')
        self.assertEqual(s.assess(job(description=BASE+'5+ years of experience required; 8 years of experience preferred.'),now).checks['experience']['status'],'fail')

    def test_without_anchor_limit_remains_fixed(self):
        self.assertEqual(experience_ceiling(CFG,datetime.fromisoformat('2035-10-22T12:00:00+00:00')),CFG['max_mandatory_experience_years'])

    def test_invalid_anchor_rejected(self):
        for value in [None,True,2026,'2026-02-30','20260901','2026-9-1']:
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'experience_growth_anchor'):
                validate({**self.cfg,'experience_growth_anchor':value})

    def test_growth_continues_without_changing_base_setting(self):
        self.assertEqual(experience_ceiling(self.cfg,datetime.fromisoformat('2090-09-01T12:00:00+00:00')),68)


if __name__=='__main__':
    unittest.main()
