import json,unittest
from pathlib import Path
from pm_scraper.fetchers import Fetcher
from pm_scraper.filtering import Screener
from pm_scraper.http import FetchError
from pm_scraper.htmlutil import enrich_job
from pm_scraper.models import Job
ROOT=Path(__file__).resolve().parents[1]
class FakeHTTP:
 def __init__(self,data):self.data=data;self.calls=[]
 def json(self,url,**kwargs):
  self.calls.append(url);return self.data[len(self.calls)-1]
 def text(self,url,**kwargs):return '<html><main><p>Public description without an original posting date.</p></main></html>'
class AdapterTests(unittest.TestCase):
 def setUp(self):self.s=Screener(json.loads((ROOT/'tests/fixtures/criteria.json').read_text()))
 def test_56_individually_configured_employers(self):
  cs=json.loads((ROOT/'config/companies.json').read_text());self.assertEqual(len(cs),56);self.assertEqual(len({c['id'] for c in cs}),56)
  self.assertEqual([c['rank'] for c in cs],list(range(1,57)))
  self.assertFalse({c['id'] for c in cs} & {'cocus','float','jta-the-data-scientists','namecheap'})
  for c in cs:self.assertTrue(hasattr(Fetcher,c['source']['adapter']),c['name'])
 def test_ashby_last_publication_not_original(self):
  h=FakeHTTP([{'jobs':[{'id':'1','title':'Product Manager','location':'Remote Portugal','jobUrl':'https://example.org/1','publishedAt':'2026-10-18','isRemote':True,'descriptionPlain':'A sufficiently long position description about project stakeholders and delivery management.'}]}])
  r=Fetcher(h,self.s).fetch({'id':'x','name':'X','source':{'adapter':'ashby','board':'x'}})
  self.assertEqual(r.status,'ok');j=r.jobs[0];self.assertEqual(j.date_kind,'last_published')
  enrich_job(j,'<script type="application/ld+json">{"@type":"JobPosting","title":"Product Manager","datePosted":"2026-10-19"}</script>',j.url)
  self.assertEqual(j.date_kind,'last_published')
 def test_greenhouse_first_publication_wins(self):
  h=FakeHTTP([{'jobs':[{'id':1,'title':'Project Manager','absolute_url':'https://example.org/1','location':{'name':'Portugal'},'first_published':'2026-01-01','updated_at':'2026-10-19','content':'&lt;p&gt;Job description in escaped HTML for responsible project delivery.&lt;/p&gt;'}],'meta':{'total':1}}])
  r=Fetcher(h,self.s).fetch({'id':'x','name':'X','source':{'adapter':'greenhouse','board':'x'}})
  self.assertEqual(r.jobs[0].posted_at,'2026-01-01');self.assertNotIn('&lt;',r.jobs[0].description)
 def test_repeated_pagination_page_is_failure(self):
  page=[{'id':str(i),'text':'Account Executive'} for i in range(100)]
  h=FakeHTTP([page,page]);r=Fetcher(h,self.s).fetch({'id':'x','name':'X','source':{'adapter':'lever','board':'x'}})
  self.assertFalse(r.complete);self.assertEqual(r.status,'pagination_error')
 def test_schema_change_not_empty_success(self):
  r=Fetcher(FakeHTTP([{'error':'something changed'}]),self.s).fetch({'id':'x','name':'X','source':{'adapter':'ashby','board':'x'}})
  self.assertFalse(r.complete);self.assertEqual(r.status,'schema_changed')
if __name__=='__main__':unittest.main()

class HtmlRegressions(unittest.TestCase):
 def test_microdata_date_title_and_description(self):
  j=Job('vestas','Vestas','Project Manager','https://example.org/job/1')
  body='<div itemscope itemtype="https://schema.org/JobPosting"><meta itemprop="datePosted" content="Sat Sep 26 02:00:00 UTC 2026"><meta itemprop="addressLocality" content="Porto"><meta itemprop="addressCountry" content="PT"><span itemprop="title">Senior Project Manager</span><span itemprop="description">Manage projects, stakeholder expectations, delivery deadlines and risk registers.</span></div>'
  enrich_job(j,body,j.url)
  self.assertEqual(j.title,'Senior Project Manager');self.assertEqual(j.date_kind,'original_posted');self.assertTrue(j.detail_ok);self.assertEqual(j.countries,['PT'])
 def test_language_links_are_not_pagination_and_page_one_is_alias(self):
  class Pages:
   def __init__(self):self.urls=[]
   def text(self,url,**kw):
    self.urls.append(url)
    if len(self.urls)>2:raise AssertionError('Unbounded/locale pagination')
    if 'startrow=10' in url:return '<a href="/job/Engineer2/2">Engineer</a><a href="?startrow=0">1</a><a href="?startrow=10&locale=fr_FR">French</a>'
    return '<a href="/job/Engineer/1">Engineer</a><a href="?startrow=0">1</a><a href="?startrow=10">2</a>'
  h=Pages();c={'id':'x','name':'X','source':{'adapter':'html','listing_url':'https://example.org/search/','job_pattern':'/job/','page_pattern':'startrow='}}
  r=Fetcher(h,Screener(json.loads((ROOT/'tests/fixtures/criteria.json').read_text()))).fetch(c)
  self.assertEqual(r.status,'ok');self.assertEqual(r.discovered,2);self.assertEqual(len(h.urls),2)

class NonJobMetadata(unittest.TestCase):
 def test_organization_microdata_cannot_replace_posting(self):
  j=Job('x','X','Project Manager','https://example.org/jobs/1')
  body='<div itemscope itemtype="https://schema.org/Organization"><meta itemprop="title" content="Company"><span itemprop="description">Company tagline</span></div><main>Coordinate complex project deliveries and discuss requirements, budgets and delivery plans with stakeholders.</main>'
  enrich_job(j,body,j.url)
  self.assertEqual(j.title,'Project Manager');self.assertGreater(len(j.description),60)

class BadSchemaRegression(unittest.TestCase):
 def test_single_malformed_schema_does_not_override_role_or_date(self):
  j=Job('intellias','Intellias','Project Manager','https://example.org/vacancy/1')
  body='<script type="application/ld+json">{"@type":"JobPosting","title":"Intellias","datePosted":"2026-10-19","description":"Corporate tagline"}</script><main>A proper job description about planning delivery work, managing risks and coordinating with stakeholders.</main>'
  enrich_job(j,body,j.url)
  self.assertEqual(j.title,'Project Manager');self.assertIsNone(j.posted_at);self.assertGreater(len(j.description),60)

class CoverageRepairs(unittest.TestCase):
 def setUp(self):self.s=Screener(json.loads((ROOT/'tests/fixtures/criteria.json').read_text()))
 def test_remote_structured_sections_and_no_original_date_assumption(self):
  row={'public_id':'abc','status':'open','accepting_applications':True,'title':'Product Manager','location':'EMEA','workplace':'remote'}
  detail=dict(row,opened_at='2026-10-20',description='-',advert_sections=[{'doc':{'content':[{'content':[{'text':'Coordinate product delivery with stakeholders, manage requirements and maintain a prioritized product backlog.'}]}]}}])
  h=FakeHTTP([{'jobs':[row]},{'job':detail}]);r=Fetcher(h,self.s).fetch({'id':'remote','name':'Remote','source':{'adapter':'remote_public','base':'https://apply.remote.com'}})
  self.assertTrue(r.complete);self.assertTrue(r.jobs[0].detail_ok);self.assertIn('prioritized',r.jobs[0].description);self.assertEqual(r.jobs[0].date_kind,'opened')
 def test_workable_details_use_public_api_and_follow_token(self):
  row={'shortcode':'ABC','title':'Project Manager','remote':True,'location':{'countryCode':'PT','country':'Portugal'}}
  h=FakeHTTP([{'results':[row],'nextPage':'next'},{'description':'Coordinate delivery and manage stakeholder expectations across multiple software projects.','requirements':'English required','published':'2026-10-20'},{'results':[],'total':1}])
  r=Fetcher(h,self.s).fetch({'id':'mindera','name':'Mindera','source':{'adapter':'workable','board':'minderacraft'}})
  self.assertTrue(r.complete);self.assertTrue(r.jobs[0].detail_ok);self.assertEqual(r.jobs[0].countries,['PT']);self.assertIn('https://apply.workable.com/api/v2/accounts/minderacraft/jobs/ABC',h.calls)
 def test_stellaxius_nonmatching_cards_need_no_detail_fetch(self):
  class Page:
   def text(self,url,**kw):
    if url!='https://example.org/careers/':raise AssertionError('Unrelated role fetched')
    return '<article><h2>Lead Data Engineer</h2><a href="/lead-data-engineer-m-f-d/">Apply now</a></article>'
  r=Fetcher(Page(),self.s).fetch({'id':'s','name':'S','source':{'adapter':'html','listing_url':'https://example.org/careers/','job_pattern':'-m-f-d/','title_xpath':'ancestor::article[1]//h2','fetch_all_details':False}})
  self.assertTrue(r.complete);self.assertEqual(r.discovered,1);self.assertEqual(r.jobs,[])
