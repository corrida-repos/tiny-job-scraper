import unittest
from pm_scraper.daily import prepare_email, select_roles, salary_positive
from test_screening import job, NOW, CFG
from pm_scraper.filtering import Screener

class DailyReportTests(unittest.TestCase):
 def setUp(self):
  self.s = Screener(CFG)
  self.payload={'started_at':NOW.isoformat(),'coverage':{'sources':1,'complete':1,'attention':0},'sources':[]}
 def pair(self, **kwargs):
  j=job(**kwargs);j.metadata.update(employer_rank=20,careers_url='https://example.org/careers')
  return j,self.s.assess(j,NOW)
 def test_complete_email_has_no_ten_role_cap(self):
  pairs=[self.pair(source_id=str(i),url=f'https://example.org/jobs/{i}',title=f'Project Manager {i}',workplace='unknown') for i in range(13)]
  email=prepare_email(pairs,self.payload)
  self.assertEqual(len(email['job_keys']),13)
  self.assertTrue(email['body_markdown'].startswith('1. Bosch'))
  self.assertEqual(email['body_markdown'].count('- **Pros:**'),13)
  self.assertEqual(email['body_markdown'].count('- **Cons:**'),13)
  self.assertEqual(email['subject'],"Tiny's Daily Job Report")
  self.assertEqual(email['delivery_status'],'not_sent')
  self.assertIn('## Run notes',email['body_markdown'])
  self.assertEqual(prepare_email(pairs,self.payload),email)
 def test_fresh_review_included_old_and_rejected_excluded(self):
  fresh=self.pair(description=job().description.replace('No travel required.',''))
  self.assertEqual(fresh[1].status,'review')
  pairs=[fresh,self.pair(posted_at='2026-10-01'),self.pair(date_kind='updated'),self.pair(description=job().description+' Minimum 8 years of experience required.')]
  email=prepare_email(pairs,self.payload)
  self.assertEqual(email['job_keys'],[fresh[0].key])
  self.assertIn('Potential match; requirements unconfirmed',email['body_markdown'])
 def test_rank_precedes_eligibility(self):
  a=self.pair(source_id='a',description=job().description.replace('No travel required.',''))
  b=self.pair(source_id='b')
  a[0].metadata['employer_rank']=1
  self.assertEqual(select_roles([b,a])[0][0][0].source_id,'a')
 def test_location_duplicates_prefer_braga_and_preserve_alternatives(self):
  pairs=[self.pair(source_id=x,location=x+', Portugal',url='https://example.org/'+x) for x in ['Lisbon','Porto','Braga']]
  selected, alternatives=select_roles(pairs)
  self.assertEqual(len(selected),1)
  self.assertEqual(selected[0][0].location,'Braga, Portugal')
  self.assertEqual(len(alternatives[selected[0][0].key]),2)
  different=self.pair(source_id='different',description=job().description+' Manage a separate implementation team.')
  self.assertEqual(len(select_roles(pairs+[different])[0]),2)
 def test_partial_is_not_empty_success(self):
  self.payload['coverage']={'sources':1,'complete':0,'attention':1}
  self.payload['sources']=[dict(company='Example',status='network_error',complete=False,messages=['403'])]
  email=prepare_email([],self.payload)
  self.assertTrue(email['body_markdown'].startswith('Retrieval failed or was incomplete'))
  self.assertIn('Example: network_error',email['body_markdown'])
 def test_salary_display_requires_explicit_gross_annual_eur(self):
  j=job(salary={'currency':'EUR','value':{'unitText':'YEAR','minValue':40000,'maxValue':60000}})
  self.assertEqual(salary_positive(j),'')
  j.description+=' Gross annual salary.'
  self.assertIn('€40,000–€60,000, up to €60,000',salary_positive(j))

class CliFailureTests(unittest.TestCase):
 def test_bad_configuration_writes_fresh_failure_email_and_exits_one(self):
  import json
  import tempfile
  from pathlib import Path
  from pm_scraper.cli import main
  with tempfile.TemporaryDirectory() as temp:
   out=Path(temp)/'output'
   out.mkdir()
   (out/'email.md').write_text('stale previous report')
   result=main(['run','--companies',str(Path(temp)/'missing.json'),'--output',str(out),'--state',str(Path(temp)/'state.sqlite3')])
   self.assertEqual(result,1)
   self.assertTrue((out/'email.md').read_text().startswith('Retrieval failed'))
   self.assertEqual(json.loads((out/'email.json').read_text())['delivery_status'],'not_sent')
   self.assertFalse((Path(temp)/'state.sqlite3').exists())

 def test_production_guard_refuses_missing_state(self):
  import tempfile
  from pathlib import Path
  from pm_scraper.cli import main
  with tempfile.TemporaryDirectory() as temp:
   state=Path(temp)/'missing.sqlite3'
   result=main(['run','--require-existing-state','--state',str(state),'--output',str(Path(temp)/'out')])
   self.assertEqual(result,1)
   self.assertFalse(state.exists())

 def test_seven_day_cli_override_is_scoped_to_one_run(self):
  import json
  import tempfile
  from pathlib import Path
  from unittest.mock import patch
  from pm_scraper.cli import main
  from pm_scraper.models import FetchResult
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)
   for days, expected in [(7,1),(2,0)]:
    out=root/str(days)
    result=FetchResult('bosch','Bosch','fixture',jobs=[job(posted_at='2026-10-15T12:00:00Z')])
    with patch('pm_scraper.cli.utcnow',return_value=NOW),patch('pm_scraper.cli.Fetcher') as fetcher:
     fetcher.return_value.fetch.return_value=result
     code=main(['run','--only','20','--max-post-age-days',str(days),'--state',str(root/f'{days}.sqlite3'),'--output',str(out)])
    self.assertEqual(code,0)
    email=json.loads((out/'email.json').read_text())
    self.assertEqual(len(email['job_keys']),expected)
    self.assertIn(f'within {days*24} hours',email['body_markdown'])
   self.assertEqual(json.loads((Path(__file__).resolve().parents[1]/'config/criteria.json').read_text())['max_post_age_days'],2)
