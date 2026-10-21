import json
import unittest
from pathlib import Path
from pm_scraper.fetchers import Fetcher
from pm_scraper.filtering import Screener
from pm_scraper.http import FetchError

CFG=json.loads((Path(__file__).resolve().parents[1]/'config/criteria.json').read_text())

class Pages:
 def __init__(self,pages):self.pages=pages;self.calls=[]
 def text(self,url,**kwargs):
  self.calls.append(url)
  value=self.pages[url]
  if isinstance(value,Exception):raise value
  return value

class CoverageRepairsTests(unittest.TestCase):
 def fetch(self,http,source,details=250):
  return Fetcher(http,Screener(CFG),max_details=details).fetch({'id':'x','name':'Example','source':source})
 def test_namecheap_public_pages_reconcile_total_and_ignore_internal_next_url(self):
  def page(current,rows):return '<script>window.openingsData = '+json.dumps({'jobs':{'data':rows,'current_page':current,'last_page':2,'total':2,'next_page_url':'http://private.invalid/openings?page=2'}})+'</script>'
  row=lambda i:{'jobid':str(i),'title':'Software Engineer'}
  http=Pages({'https://example.org/careers/openings/?page=1':page(1,[row(1)]),'https://example.org/careers/openings/?page=2':page(2,[row(2)])})
  result=self.fetch(http,{'adapter':'namecheap','base':'https://example.org'})
  self.assertTrue(result.complete);self.assertEqual(result.discovered,2)
  self.assertTrue(all(url.startswith('https://example.org/') for url in http.calls))
 def test_namecheap_repeated_page_is_not_complete(self):
  body='<script>window.openingsData = '+json.dumps({'jobs':{'data':[{'jobid':'1','title':'Engineer'}],'current_page':1,'last_page':2,'total':2}})+'</script>'
  http=Pages({f'https://example.org/careers/openings/?page={i}':body for i in (1,2)})
  result=self.fetch(http,{'adapter':'namecheap','base':'https://example.org'})
  self.assertFalse(result.complete);self.assertEqual(result.status,'pagination_error')
 def test_sitemap_detail_fields_and_lastmod_never_becomes_posting_date(self):
  url='https://example.org/job/Porto-Project-Manager/123'
  sitemap=f'<urlset><url><loc>{url}</loc><lastmod>2026-10-21</lastmod></url></urlset>'
  detail='<link rel="canonical" href="'+url+'"><span itemprop="title">Project Manager</span><span itemprop="description">Manage delivery, stakeholders and risks across multiple complex projects with our team.</span>'
  http=Pages({'https://example.org/sitemap.xml':sitemap,url:detail})
  result=self.fetch(http,{'adapter':'sitemap','sitemap_url':'https://example.org/sitemap.xml','job_pattern':'/job/'})
  self.assertTrue(result.complete);self.assertEqual(result.discovered,1);self.assertTrue(result.jobs[0].detail_ok)
  self.assertIsNone(result.jobs[0].posted_at);self.assertEqual(result.jobs[0].title,'Project Manager')
 def test_sitemap_blocked_detail_and_detail_cap_remain_visible(self):
  url='https://example.org/job/Project-Manager/123'
  sitemap=f'<urlset><url><loc>{url}</loc></url></urlset>'
  source={'adapter':'sitemap','sitemap_url':'https://example.org/sitemap.xml','job_pattern':'/job/'}
  http=Pages({'https://example.org/sitemap.xml':sitemap,url:FetchError('HTTP 403','blocked')})
  result=self.fetch(http,source)
  self.assertFalse(result.complete);self.assertIn('403',result.jobs[0].metadata['detail_error'])
  self.assertFalse(self.fetch(http,source,details=0).complete)
 def test_sitemap_rejects_cross_host_index(self):
  http=Pages({'https://example.org/sitemap.xml':'<sitemapindex><sitemap><loc>https://other.invalid/map.xml</loc></sitemap></sitemapindex>'})
  result=self.fetch(http,{'adapter':'sitemap','sitemap_url':'https://example.org/sitemap.xml','job_pattern':'/job/'})
  self.assertFalse(result.complete);self.assertEqual(len(http.calls),1)
 def test_sitemap_parses_verified_jobposting_and_rejects_unrelated_schema(self):
  url='https://example.org/careers/job/123-project-manager-portugal'
  sitemap=f'<urlset><url><loc>{url}</loc></url></urlset>'
  node={'@type':'JobPosting','title':'Project Manager','url':url,'description':'Coordinate delivery and stakeholder expectations across complex projects and maintain risk registers.','datePosted':'2026-10-20'}
  source={'adapter':'sitemap','sitemap_url':'https://example.org/sitemap.xml','job_pattern':'/careers/job/','detail_kind':'jobposting'}
  http=Pages({'https://example.org/sitemap.xml':sitemap,url:'<script type="application/ld+json">'+json.dumps(node)+'</script>'})
  result=self.fetch(http,source);self.assertTrue(result.complete);self.assertEqual(result.jobs[0].date_kind,'original_posted')
  node['url']='https://example.org/careers/job/999-unrelated'
  http.pages[url]='<script type="application/ld+json">'+json.dumps(node)+'</script>'
  self.assertFalse(self.fetch(http,source).complete)
 def test_cocus_employer_fallback_does_not_claim_complete_inventory(self):
  http=Pages({'https://talent.sage.hr/board/vacancies':FetchError('HTTP 403','blocked'),'https://example.org/careers':'<a href="https://talent.sage.hr/jobs/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee">Engineer</a><a href="https://talent.sage.hr/jobs/11111111-2222-3333-4444-555555555555">Submit open application</a>'})
  result=self.fetch(http,{'adapter':'cocus','listing_url':'https://talent.sage.hr/board/vacancies','job_pattern':'/jobs/','fallback_url':'https://example.org/careers'})
  self.assertFalse(result.complete);self.assertEqual(result.status,'partial');self.assertEqual(result.discovered,1)
