import json
import tempfile
import unittest
from pathlib import Path
from datetime import timedelta

from pm_scraper.htmlutil import enrich_job
from pm_scraper.posting_dates import enrich_dates, report_date
from pm_scraper.models import Job, FetchResult, Assessment
from pm_scraper.state import State
from pm_scraper.fetchers import Fetcher
from pm_scraper.http import FetchError
from pm_scraper.filtering import Screener
from test_screening import job, NOW, CFG


def schema(**values):
    return '<script type="application/ld+json">'+json.dumps({'@type':'JobPosting', **values})+'</script>'


class PostingDateTests(unittest.TestCase):
    def test_intellias_malformed_title_with_exact_job_id_recovers_date_only(self):
        j = job(company_id='intellias', posted_at=None, date_kind='unknown')
        original_title, description = j.title, j.description
        enrich_job(j, schema(title='Intellias', **{'@id':j.url+'/#JobPosting'}, datePosted='2026-10-18T10:00:00Z'), j.url)
        self.assertEqual(j.posted_at, '2026-10-18T10:00:00Z')
        self.assertEqual(j.date_kind, 'original_posted')
        self.assertEqual((j.title,j.description), (original_title,description))

    def test_same_title_other_job_does_not_supply_date(self):
        for fields in [{'url':'https://example.org/jobs/other'}, {'identifier':{'value':'other'}}, {'@id':'https://other.example/job/123'}]:
            j = job(posted_at=None, date_kind='unknown')
            enrich_dates(j, schema(title=j.title,datePosted='2026-10-18',**fields),j.url)
            self.assertIsNone(j.posted_at)

    def test_related_cards_and_ambiguous_title_do_not_supply_date(self):
        j = job(posted_at=None, date_kind='unknown')
        enrich_dates(j, schema(title=j.title,datePosted='2026-10-18')*2,j.url)
        self.assertIsNone(j.posted_at)

    def test_conflicting_identifiers_veto_url_match(self):
        j = job(posted_at=None, date_kind='unknown')
        enrich_dates(j,schema(url=j.url,identifier={'value':'other'},datePosted='2026-10-18'),j.url)
        self.assertIsNone(j.posted_at)

    def test_repost_date_is_retained_as_supporting_evidence_only(self):
        j = job(posted_at='2026-10-18',date_kind='last_published',metadata={'original_date_unproven':True})
        enrich_dates(j,schema(url=j.url,datePosted='2026-10-19'),j.url)
        self.assertEqual(j.date_kind,'last_published')
        self.assertEqual(j.posted_at,'2026-10-18')
        self.assertTrue(any(e['value']=='2026-10-19' and e['kind']=='published' for e in j.metadata['posting_date_evidence']))

    def test_multiple_original_dates_keep_earliest(self):
        j = job(posted_at='2026-10-18T12:00:00Z')
        enrich_dates(j,schema(url=j.url,datePosted='2026-10-19')+schema(url=j.url,datePosted='2026-09-01'),j.url)
        self.assertEqual(j.posted_at,'2026-09-01')

    def test_modification_and_unrelated_metadata_never_supply_posting_date(self):
        j = job(posted_at=None,date_kind='unknown')
        enrich_dates(j,schema(url=j.url,dateModified='2026-10-18',dateCreated='2026-10-18'),j.url)
        self.assertIsNone(j.posted_at)

    def test_microdata_without_description_can_supply_date(self):
        j=job(posted_at=None,date_kind='unknown')
        body=f'<div itemscope itemtype="https://schema.org/JobPosting"><meta itemprop="url" content="{j.url}"><meta itemprop="datePosted" content="2026-10-18"></div>'
        enrich_dates(j,body,j.url)
        self.assertEqual(j.posted_at,'2026-10-18')

    def test_visible_labels_preserve_missing_year_and_ambiguous_numeric_date(self):
        j=job(posted_at=None,date_kind='unknown')
        body=f'<h1>{j.title}</h1><div><span class="joblayouttoken-label">Posting Start Date:</span>10/12/26</div><span>Published<i>19 of October</i></span>'
        enrich_dates(j,body,j.url)
        self.assertIsNone(j.posted_at)
        self.assertEqual([e['value'] for e in j.metadata['posting_date_evidence']],['10/12/26','19 of October'])
        self.assertIn('original unverified',report_date(j))

    def test_date_only_window_overlap_and_future_stay_unknown(self):
        s=Screener(CFG)
        for date in [(NOW-timedelta(days=2)).date().isoformat(),NOW.date().isoformat(),(NOW+timedelta(days=1)).date().isoformat()]:
            self.assertEqual(s.assess(job(posted_at=date),NOW).checks['freshness']['status'],'unknown')
        self.assertEqual(s.assess(job(posted_at=(NOW-timedelta(days=3)).date().isoformat()),NOW).checks['freshness']['status'],'fail')

    def test_seen_since_never_proves_recent_but_can_prove_old(self):
        s=Screener(CFG)
        for kind in ['unknown','last_published','original_posted']:
            recent=job(posted_at=NOW.isoformat(),date_kind=kind,metadata={'first_seen':(NOW-timedelta(days=3)).isoformat()})
            self.assertEqual(s.assess(recent,NOW).checks['freshness']['status'],'fail')
        j=job(posted_at=None,date_kind='unknown',metadata={'first_seen':NOW.isoformat()})
        self.assertEqual(s.assess(j,NOW).checks['freshness']['status'],'unknown')
        self.assertIn('observation, not publication',report_date(j))

    def test_state_retains_date_only_precision_and_observation(self):
        with tempfile.TemporaryDirectory() as d:
            state=State(Path(d)/'state.db')
            try:
                j=job(posted_at=NOW.date().isoformat())
                state.record(FetchResult(j.company_id,j.company,'test'),[(j,Assessment('review',None,[],{}))],NOW.isoformat())
                current=job(posted_at=None,date_kind='unknown')
                state.original(current)
                self.assertEqual(current.posted_at,NOW.date().isoformat())
                self.assertEqual(current.metadata['first_seen'],NOW.isoformat())
                self.assertEqual(Screener(CFG).assess(current,NOW).checks['freshness']['status'],'unknown')
            finally:
                state.close()

    def test_optional_lookup_failure_preserves_source_coverage(self):
        class HTTP:
            def json(self,*args,**kwargs):
                return {'jobs':[{'id':'1','title':'Product Manager','location':'Remote Portugal','jobUrl':'https://example.org/jobs/1','publishedAt':'2026-10-18','isRemote':True,'descriptionPlain':'Coordinate product delivery with stakeholders and manage the backlog.'}]}
            def text(self,*args,**kwargs):
                raise FetchError('Unavailable','blocked')
        r=Fetcher(HTTP(),Screener(CFG)).fetch({'id':'x','name':'X','source':{'adapter':'ashby','board':'x'}})
        self.assertTrue(r.complete)
        self.assertEqual(r.status,'ok')
        self.assertEqual(r.jobs[0].metadata['date_lookup_status'],'blocked')

    def test_employer_declared_publication_and_reposting_qualify(self):
        s=Screener({**CFG,'accept_employer_dates':True})
        for kind in ['published','last_published','released','opened','posting_start','original_posted']:
            j=job(posted_at=NOW.date().isoformat(),date_kind=kind,metadata={'first_seen':(NOW-timedelta(days=30)).isoformat()})
            self.assertEqual(s.assess(j,NOW).checks['freshness']['status'],'pass',kind)
        for kind in ['updated','created','first_seen','unknown']:
            self.assertEqual(s.assess(job(posted_at=NOW.isoformat(),date_kind=kind),NOW).checks['freshness']['status'],'unknown',kind)

    def test_repost_survives_earlier_original_restoration(self):
        j=job(posted_at='2026-01-01',metadata={'first_seen':'2026-01-02','posting_date_evidence':[
            {'value':NOW.isoformat(),'kind':'last_published','source':'Employer publication','url':'https://example.org/jobs/123'}]})
        a=Screener({**CFG,'accept_employer_dates':True}).assess(j,NOW)
        self.assertEqual(a.checks['freshness']['status'],'pass')
        self.assertEqual(j.posted_at,'2026-01-01')
        self.assertIn('Earliest original date: 2026-01-01',report_date(j,a.checks['freshness']))

    def test_state_preserves_current_publication_before_restoring_original(self):
        with tempfile.TemporaryDirectory() as d:
            state=State(Path(d)/'state.db')
            try:
                old=job(posted_at='2026-01-01')
                state.record(FetchResult(old.company_id,old.company,'test'),[(old,Assessment('review',None,[],{}))],'2026-01-02')
                current=job(posted_at=NOW.isoformat(),date_kind='last_published')
                state.original(current)
                self.assertEqual(current.posted_at,'2026-01-01')
                self.assertEqual(Screener({**CFG,'accept_employer_dates':True}).assess(current,NOW).checks['freshness']['status'],'pass')
            finally:
                state.close()

    def test_employer_dates_old_future_and_boundary(self):
        s=Screener({**CFG,'accept_employer_dates':True})
        for date,expected in [((NOW-timedelta(days=3)).isoformat(),'fail'),((NOW+timedelta(days=1)).isoformat(),'unknown'),((NOW-timedelta(days=2)).date().isoformat(),'unknown'),(NOW.isoformat(),'pass')]:
            self.assertEqual(s.assess(job(posted_at=date,date_kind='last_published'),NOW).checks['freshness']['status'],expected)

    def test_fujitsu_locale_declares_month_day_order(self):
        j=job(url='https://example.org/job/8307-en_US',posted_at=None,date_kind='unknown')
        enrich_dates(j,f'<span itemprop="title">{j.title}</span><div><span class="joblayouttoken-label">Posting Start Date:</span>10/12/26</div>',j.url)
        self.assertEqual(j.metadata['posting_date_evidence'][0]['value'],'2026-10-12')
        self.assertEqual(j.metadata['posting_date_evidence'][0]['kind'],'posting_start')

    def test_bizneo_heading_excludes_location_tags_in_inventory_title(self):
        j=job(title='Senior Business Analyst - Banking Channels Lisboa Híbrido',posted_at=None,date_kind='unknown')
        enrich_dates(j,'<h1>Senior Business Analyst - Banking Channels</h1><span>Published<i>19 of October</i></span>',j.url)
        self.assertEqual(j.metadata['posting_date_evidence'][0]['value'],'19 of October')
        self.assertIsNone(j.posted_at)

    def test_sitemap_slug_alias_requires_same_requisition_and_canonical(self):
        j=job(url='https://example.org/job/Product-Manager/8307-en_US',posted_at=None,date_kind='unknown')
        body=f'<link rel="canonical" href="{j.url}"><span itemprop="title">{j.title}</span><div><span class="joblayouttoken-label">Posting Start Date:</span>10/12/26</div>'
        enrich_dates(j,body,'https://example.org/job/Other-Old-Slug/8307-en_US')
        self.assertEqual(j.metadata['posting_date_evidence'][0]['value'],'2026-10-12')
        other=job(url=j.url,posted_at=None,date_kind='unknown')
        enrich_dates(other,body,'https://example.org/job/Other-Old-Slug/9999-en_US')
        self.assertFalse(other.metadata.get('posting_date_evidence'))

    def test_employer_date_does_not_override_residence_or_onsite(self):
        s=Screener({**CFG,'accept_employer_dates':True})
        for changes in [{'workplace':'onsite'}, {'description':'You must reside in Lisbon.'}]:
            j=job(posted_at=NOW.isoformat(),date_kind='last_published',**changes)
            a=s.assess(j,NOW)
            self.assertEqual(a.checks['freshness']['status'],'pass')
            self.assertEqual(a.status,'rejected')

    def test_optional_lookup_is_bounded_and_reuses_existing_detail(self):
        import time
        class HTTP:
            calls=0
            def text(self,*args,**kwargs):
                self.calls+=1
                return '<html></html>'
        h=HTTP();f=Fetcher(h,Screener({**CFG,'accept_employer_dates':True}))
        f.r=FetchResult('x','X','test',jobs=[job(source_id=str(i),posted_at=None,date_kind='unknown') for i in range(20)])
        f.r.jobs[0].metadata['date_page_checked']=True
        f.details=0;f.max_details=100;f.deadline=time.monotonic()+30
        f.date_fallbacks()
        self.assertEqual(h.calls,12)
        self.assertEqual(f.details,12)
        self.assertEqual(f.r.jobs[-1].metadata['date_lookup_status'],'budget_exhausted')
        self.assertTrue(f.r.complete)


if __name__=='__main__':
    unittest.main()
