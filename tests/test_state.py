import tempfile,unittest
from pathlib import Path
from pm_scraper.state import State
from pm_scraper.models import FetchResult,Assessment,Job
NOW='2026-10-19T12:00:00+00:00'
class StateTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=State(Path(self.tmp.name)/'state.db')
  self.j=Job('x','Employer','Project Manager','https://example.org/job/1','1',posted_at='2026-10-01',date_kind='original_posted')
  self.a=Assessment('eligible','Project Manager',[],{},80);self.r=FetchResult('x','Employer','test',jobs=[self.j])
 def tearDown(self):self.s.close();self.tmp.cleanup()
 def test_refresh_never_resets_original(self):
  self.s.record(self.r,[(self.j,self.a)],NOW)
  self.j.posted_at='2026-10-19';self.s.original(self.j)
  self.assertTrue(self.j.posted_at.startswith('2026-10-01'))
 def test_no_repeats_only_after_delivery_success(self):
  self.s.record(self.r,[(self.j,self.a)],NOW)
  token,items=self.s.eligible_delivery([(self.j,self.a)],NOW);self.assertEqual(len(items),1)
  token2,items=self.s.eligible_delivery([(self.j,self.a)],NOW);self.assertEqual(token,token2);self.assertEqual(len(items),1)
  self.s.ack(token,NOW,'test-mail-id');self.assertEqual(self.s.eligible_delivery([(self.j,self.a)],NOW),(None,[]))
  self.assertFalse(self.s.ack(token,NOW,'test-mail-id'))
 def test_network_failure_does_not_close_jobs(self):
  self.s.record(self.r,[(self.j,self.a)],NOW)
  failed=FetchResult('x','Employer','test',status='blocked',complete=False)
  for _ in range(3):self.s.record(failed,[],NOW)
  row=self.s.db.execute('SELECT status,misses FROM jobs').fetchone();self.assertEqual(tuple(row),('present',0))
 def test_two_healthy_absences_are_unconfirmed_missing(self):
  self.s.record(self.r,[(self.j,self.a)],NOW)
  self.s.record(self.r,[],NOW);self.assertEqual(self.s.stats(),{'not_seen_once':1})
  self.s.record(self.r,[],NOW);self.assertEqual(self.s.stats(),{'missing_unconfirmed':1})
  self.s.record(self.r,[(self.j,self.a)],NOW);self.assertEqual(self.s.stats(),{'present':1})
if __name__=='__main__':unittest.main()
