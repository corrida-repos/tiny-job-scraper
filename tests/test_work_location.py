import json
import unittest
from pathlib import Path
from datetime import datetime, timezone
from pm_scraper.models import Job
from pm_scraper.filtering import Screener

CFG = json.loads((Path(__file__).resolve().parents[1] / 'tests/fixtures/criteria.json').read_text())
NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
BODY = 'You will coordinate delivery, manage stakeholder expectations and review technical proposals. No travel required. English is required.'


def job(**kw):
    d = dict(company_id='bosch', company='Bosch', title='Technical Project Manager', url='https://example.org/jobs/1',
             source_id='1', location='Portugal', countries=['PT'], workplace='unknown', description=BODY,
             posted_at='2026-10-18T12:00:00Z', date_kind='original_posted', date_evidence='fixture', detail_ok=True)
    d.update(kw)
    return Job(**d)


class WorkLocation(unittest.TestCase):
    def setUp(self):
        self.s = Screener(CFG)

    def check(self, **kw):
        a = self.s.assess(job(**kw), NOW)
        return a, a.checks.get('work_location', {}).get('status')

    def test_dictated_non_north_location_is_rejected(self):
        for location, workplace in [('Lisbon, Portugal', 'hybrid'), ('Lisboa', 'unknown'), ('Oeiras, Lisbon, Portugal', ''),
                                    ('Coimbra, Portugal', 'hybrid'), ('Aveiro', 'onsite'), ('Faro, Portugal', 'unknown'),
                                    ('Lisbon, Portugal; Madrid, Spain', 'hybrid')]:
            a, status = self.check(location=location, workplace=workplace)
            self.assertEqual(status, 'fail', location)
            self.assertEqual(a.status, 'rejected', location)

    def test_description_dictated_location_is_rejected(self):
        for text in ['Hybrid role based in our Lisbon office.', 'This position is based in Coimbra.',
                     'Location: Lisboa (hybrid).', 'You will work from our Oeiras office three days a week.']:
            _, status = self.check(description=BODY + ' ' + text)
            self.assertEqual(status, 'fail', text)

    def test_compatible_locations_are_not_rejected(self):
        cases = [dict(location='Porto, Portugal', workplace='hybrid'),
                 dict(location='Lisbon or Porto, Portugal', workplace='hybrid'),
                 dict(location='Lisbon, Portugal', workplace='remote'),
                 dict(location='Remote - Lisbon, Portugal'),
                 dict(location='Lisbon, Portugal', description=BODY + ' This role is fully remote within Portugal.'),
                 dict(location='Portugal'),
                 dict(location='Guimaraes, Portugal'),
                 dict(description=BODY + ' Our head office is in Lisbon.'),
                 dict(description=BODY + ' You can also work from our Lisbon office if you prefer.'),
                 dict(description=BODY + ' Hybrid role in Porto; occasional visits to the Lisbon office.')]
        for kw in cases:
            self.assertNotEqual(self.check(**kw)[1], 'fail', kw)


if __name__ == '__main__':
    unittest.main()
