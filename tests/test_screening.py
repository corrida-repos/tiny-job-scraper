import json
import unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from pm_scraper.models import Job,parse_date,canonical_url
from pm_scraper.filtering import Screener
CFG=json.loads((Path(__file__).resolve().parents[1]/'config/criteria.json').read_text())
NOW=datetime(2026,10,19,12,tzinfo=timezone.utc)
BASE='Fully remote within Portugal. You will coordinate delivery, manage stakeholder expectations and review technical proposals. No travel required. English is required.'
def job(**kw):
 d=dict(company_id='bosch',company='Bosch',title='Technical Project Manager',url='https://example.org/jobs/123',source_id='123',location='Portugal',countries=['PT'],workplace='remote',description=BASE,posted_at='2026-10-18T12:00:00Z',date_kind='original_posted',date_evidence='fixture original publication',detail_ok=True)
 d.update(kw);return Job(**d)
class Screening(unittest.TestCase):
 def setUp(self):self.s=Screener(CFG)
 def assess(self,**kw):return self.s.assess(job(**kw),NOW)
 def test_qualified_remote_role(self):self.assertEqual(self.assess().status,'eligible')
 def test_all_45_families_and_explicit_employers(self):
  self.assertEqual(len(CFG['role_families']),45)
  for title in CFG['role_families']:self.assertIsNotNone(self.s.family('Senior '+title))
  for c in ['Bosch','Vestas','DACHSER']:self.assertEqual(self.assess(company=c).checks['employer']['status'],'pass')
  for c in ['COCUS','Float','JTA — The Data Scientists','Namecheap']:
   self.assertEqual(self.assess(company=c).checks['employer']['status'],'fail')
 def test_title_order_and_seniority(self):
  for title in ['Head of Project Management','Director, Product Manager','Programme Director','Delivery Lead','Manager of Products','Projects Manager','Technical Account Manager']:
   self.assertIsNone(self.s.family(title),title)
  self.assertEqual(self.s.family('Senior Programme Manager'),'Program Manager')
  self.assertEqual(self.s.family('Gestor de Projetos'),'Project Manager')
 def test_writing_code_vs_reviewing(self):
  self.assertEqual(self.assess(description=BASE+' You must write production code.').checks['code_writing']['status'],'fail')
  self.assertEqual(self.assess(description=BASE+' You will read and review code, but writing code is not required.').checks['code_writing']['status'],'pass')
  self.assertEqual(self.assess(description=BASE+' A coding assessment is required.').checks['code_writing']['status'],'fail')
 def test_foreign_language_optional_vs_required(self):
  self.assertEqual(self.assess(description=BASE+' Fluent German is required.').checks['languages']['status'],'fail')
  self.assertEqual(self.assess(description=BASE+' German is a nice-to-have.').checks['languages']['status'],'pass')
 def test_travel_is_quarterly_not_annual_average(self):
  for text in ['Travel up to 5 days per year.','Two annual retreats are expected.','Travel up to 5% of working time.','Travel up to one week per quarter.']:
   self.assertEqual(self.assess(description=BASE.replace('No travel required.',text)).checks['travel']['status'],'unknown',text)
  text='All required international travel, including transit and offsites, is at most 7 calendar days per quarter.'
  self.assertEqual(self.assess(description=BASE.replace('No travel required.',text)).checks['travel']['status'],'pass')
  self.assertEqual(self.assess(description=BASE.replace('No travel required.','Travel up to 2 weeks per quarter.')).checks['travel']['status'],'fail')
 def test_near_hybrid_2_days_but_not_3_or_far(self):
  for days,expected in [(2,'pass'),(3,'fail')]:
   a=self.assess(location='Porto, Portugal',workplace='hybrid',description=BASE.replace('Fully remote within Portugal.',f'Hybrid role. Attend the office {days} days per week.'))
   self.assertEqual(a.checks['attendance']['status'],expected)
  a=self.assess(location='Lisbon, Portugal',workplace='hybrid',description=BASE.replace('Fully remote within Portugal.','Hybrid role. Attend the office every month.'))
  self.assertEqual(a.checks['attendance']['status'],'fail')
 def test_remote_does_not_override_hiring_country(self):
  a=self.assess(location='Remote Germany',countries=['DE'],description=BASE.replace('within Portugal','within Germany'))
  self.assertEqual(a.checks['portugal_eligibility']['status'],'fail')
 def test_freshness_never_uses_updated_last_published_or_first_seen(self):
  for kind in ['last_published','updated','first_seen','created','published']:
   self.assertEqual(self.assess(date_kind=kind).checks['freshness']['status'],'unknown')
  self.assertEqual(self.assess(posted_at='2026-10-12').checks['freshness']['status'],'fail')
 def test_missing_detail_and_salary(self):
  self.assertEqual(self.assess(description='',detail_ok=False).status,'review')
  self.assertEqual(self.assess().checks['salary']['status'],'informational')
 def test_expired_evidence_does_not_resolve_unknown(self):
  a=self.s.assess(job(description=BASE.replace('No travel required.','')),NOW,{'verified_at':'2026-01-01','evidence':'old email','checks':{'travel':'pass'}})
  self.assertEqual(a.status,'review')
 def test_dates_and_meaningful_query_identity(self):
  self.assertEqual(parse_date('2026-10-08 15:22:13 UTC').hour,15)
  self.assertEqual(canonical_url('https://x.org/job?utm_source=x&gh_jid=123#top'),'https://x.org/job?gh_jid=123')
if __name__=='__main__':unittest.main()

class AdditionalRegressions(unittest.TestCase):
 def setUp(self):self.s=Screener(CFG)
 def test_distant_weekly_visits_cannot_pass_remote_label(self):
  j=job(location='Lisbon, Portugal',description=BASE+' You must attend our Lisbon office 1 day per week.')
  self.assertEqual(self.s.assess(j,NOW).checks['attendance']['status'],'fail')
 def test_travel_exception_cannot_pass_no_travel_claim(self):
  j=job(description=BASE.replace('No travel required.','No travel required except for two mandatory international retreats.'))
  self.assertEqual(self.s.assess(j,NOW).checks['travel']['status'],'unknown')
 def test_successfactors_date_format(self):
  self.assertEqual(parse_date('Sat Sep 26 02:00:00 UTC 2026').isoformat(),'2026-09-26T02:00:00+00:00')


class CurrentPolicyRegressions(unittest.TestCase):
 def setUp(self):self.s=Screener(CFG)
 def test_exact_freshness_boundaries(self):
  for posted, expected in [
   ('2026-10-17T12:00:00Z','pass'),
   ('2026-10-17T11:59:59Z','fail'),
   ('2026-10-19T12:00:01Z','unknown'),
   ('2026-10-18','pass'),
   ('2026-10-19','unknown'),
   ('2026-10-17','fail'),
  ]:
   with self.subTest(posted=posted):
    self.assertEqual(self.s.assess(job(posted_at=posted),NOW).checks['freshness']['status'],expected)
 def test_salary_never_changes_status_or_score(self):
  baseline=self.s.assess(job(),NOW)
  for ceiling in [20000,45000,55000,100000]:
   salary={'currency':'EUR','value':{'unitText':'YEAR','maxValue':ceiling}}
   actual=self.s.assess(job(salary=salary),NOW)
   self.assertEqual((actual.status,actual.score,actual.reasons),(baseline.status,baseline.score,baseline.reasons))
 def test_experience_minimums_and_preferences(self):
  for text, expected in [
   ('At least 7 years of professional experience required.','fail'),
   ('6+ years of leadership experience.','fail'),
   ('6+ years of experience required and 8 years of experience preferred.','fail'),
   ('8 years of experience preferred and minimum 6 years of experience required.','fail'),
   ('Minimo seis anos de experiencia obrigatoria.','fail'),
   ('Minimum 6–10 years of experience.','fail'),
   ('5+ years of experience required.','pass'),
   ('5–7 years of experience required.','pass'),
   ('3–5 years of experience required.','pass'),
   ('6+ years of experience preferred.','pass'),
   ('Ideally 8 years of experience.','pass'),
   ('8 years of experience.','unknown'),
   ('At least seven years of experience required.','fail'),
   ('Experiencia minima obrigatoria de 8 anos.','fail'),
   ('8 years of experience preferred; minimum 6 years of domain experience required.','fail'),
  ]:
   with self.subTest(text=text):
    result=self.s.assess(job(description=BASE+' '+text),NOW)
    self.assertEqual(result.checks['experience']['status'],expected)
