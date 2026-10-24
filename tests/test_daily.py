import unittest
from pm_scraper.daily import prepare_email, select_roles, salary_positive
from test_screening import job, NOW, CFG
from pm_scraper.filtering import Screener
from pm_scraper.branding import company_heading

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
  self.assertTrue(email['body_markdown'].startswith('# Verified Freshness\n\n'+company_heading('bosch','Bosch')+'\n'))
  from markdown_it import MarkdownIt
  rendered=MarkdownIt('commonmark',{'html':False}).render(email['body_markdown'])
  self.assertTrue(rendered.startswith('<h1>Verified Freshness</h1>'))
  from lxml import html
  self.assertEqual(html.fromstring(rendered).xpath('//h2')[0].text_content().strip(),'Bosch')
  self.assertIn('<h3><strong>Project Manager',rendered)
  self.assertEqual(rendered.count('<h2>'),1)  # Company.
  self.assertEqual(rendered.count('<h1>'),2)  # Freshness plus Run notes.
  self.assertEqual(rendered.count('<h3>'),13)
  self.assertEqual(email['body_markdown'].count('[Company careers]'),1)
  self.assertEqual(email['body_markdown'].count('- **Pros:**'),13)
  self.assertEqual(email['body_markdown'].count('- **Cons:**'),13)
  self.assertEqual(email['subject'],"Tiny's Daily Job Report")
  self.assertEqual(email['delivery_status'],'not_sent')
  self.assertIn('# Run notes',email['body_markdown'])
  self.assertEqual(prepare_email(pairs,self.payload),email)

 def test_company_groups_keep_rank_without_numbering(self):
  a=self.pair(source_id='a',title='Alpha Project Manager')
  b=self.pair(source_id='b',company_id='vestas',company='Vestas',title='Beta Project Manager')
  c=self.pair(source_id='c',title='Gamma Project Manager')
  b[0].metadata['employer_rank']=21
  email=prepare_email([b,c,a],self.payload)
  body=email['body_markdown']
  self.assertEqual(email['job_keys'],[a[0].key,c[0].key,b[0].key])
  self.assertEqual(body.count(company_heading('bosch','Bosch')+'\n'),1)
  self.assertEqual(body.count(company_heading('vestas','Vestas')+'\n'),1)
  self.assertIn('### **Alpha Project Manager**',body)
  self.assertIn('### **Gamma Project Manager**',body)
  self.assertIn('### **Beta Project Manager**',body)
  self.assertEqual(body.count('[View job]'),3)
  self.assertEqual(body.count('[Company careers]'),2)
  self.assertLess(body.index('### **Gamma Project Manager**'),body.index(company_heading('vestas','Vestas')))
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
 def test_elastic_country_editions_with_salary_differences_report_portugal_once(self):
  pairs=[]
  body=('Manage the platform product engineering team, coach engineers and coordinate stakeholder priorities.\n'*4)
  for country,amount in [('Spain','€67.000—€106.000 EUR'),('Greece','€61.100—€96.600 EUR'),('Portugal','€55.800—€88.300 EUR')]:
   pairs.append(self.pair(company_id='elastic',company='Elastic',title='Software Engineering Manager - Global UX - Applications - Platform',
                         source_id=country,url='https://example.org/'+country,location=country,countries=[],workplace='unknown',
                         description=body+'\nThe typical starting salary range for this role is:\n'+amount,
                         salary={'range':amount}))
  # Isolate grouping from country exclusion, which is tested separately.
  for candidate,assessment in pairs:
   assessment.status='review'
   assessment.checks['portugal_eligibility']['status']='pass' if candidate.location=='Portugal' else 'unknown'
  selected,alternatives=select_roles(pairs)
  self.assertEqual(len(selected),1)
  self.assertEqual(selected[0][0].location,'Portugal')
  self.assertEqual(selected[0][0].salary,{'range':'€55.800—€88.300 EUR'})
  self.assertEqual(len(alternatives[selected[0][0].key]),2)
  self.assertIn('€67.000—€106.000 EUR',pairs[0][0].description)
  email=prepare_email(pairs,self.payload)
  self.assertEqual(email['body_markdown'].count('### **Software Engineering Manager'),1)
 def test_country_dedup_preserves_different_requirements_questions_and_same_location_openings(self):
  body=job().description+' Coordinate platform delivery and manage all stakeholder expectations across projects.'
  first=self.pair(source_id='a',location='Porto',countries=[],workplace='unknown',description=body)
  cases=[dict(description=body+' Required office attendance once per quarter.'),
         dict(description=body+' Manage an additional implementation team.'),
         dict(metadata={'application_questions':[{'label':'Must you live in Porto?','required':True}]}),
         dict(location='Porto'),dict(company_id='other')]
  for case in cases:
   values=dict(source_id='b',url='https://example.org/b',location='Braga',countries=[],workplace='unknown',description=body)
   values.update(case)
   other=self.pair(**values)
   with self.subTest(case=case):self.assertEqual(len(select_roles([first,other])[0]),2)
 def test_salary_normalization_does_not_hide_experience_or_other_numbers(self):
  from pm_scraper.daily import duplicate_description
  self.assertNotEqual(duplicate_description('Minimum 4 years of experience.'),duplicate_description('Minimum 5 years of experience.'))
  self.assertNotEqual(duplicate_description('Travel €500 budget and 3 days required.'),duplicate_description('Travel €600 budget and 4 days required.'))
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
     code=main(['run','--only','bosch','--criteria',str(Path(__file__).parent/'fixtures/criteria.json'),'--max-post-age-days',str(days),'--state',str(root/f'{days}.sqlite3'),'--output',str(out)])
    self.assertEqual(code,0)
    email=json.loads((out/'email.json').read_text())
    self.assertEqual(len(email['job_keys']),expected)
    self.assertIn(f'within {days*24} hours',email['body_markdown'])
   self.assertEqual(json.loads((Path(__file__).parent/'fixtures/criteria.json').read_text())['max_post_age_days'],2)
