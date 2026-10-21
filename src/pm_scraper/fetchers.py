"""Read public employer boards. No credentials, application submissions or challenge bypass.

Every adapter exposes pagination/coverage failure rather than returning a successful empty board.
Only allowed title families receive expensive detail requests; all listed IDs count toward health.
"""
import html as htmllib
import json
import re
import time
from urllib.parse import urljoin, urlsplit, urlencode, parse_qsl, urlunsplit, unquote
from lxml import html, etree
from .models import Job, FetchResult, canonical_url, parse_date
from .htmlutil import plain, document, jsonld_nodes, from_schema, enrich_job, norm
from .http import FetchError


def with_query(url, **values):
    p = urlsplit(url)
    q = dict(parse_qsl(p.query)); q.update({k:str(v) for k,v in values.items()})
    return urlunsplit((p.scheme,p.netloc,p.path,urlencode(q),''))


def require_list(data, key):
    value = data.get(key) if isinstance(data, dict) else None
    if not isinstance(value, list):
        raise FetchError(f"Expected array '{key}'; source format changed", 'schema_changed')
    return value


class Fetcher:
    def __init__(self, http, screener, max_pages=None, max_details=250):
        self.http, self.screener = http, screener
        self.page_limit_override, self.max_details = max_pages, max_details
        self.r = None

    def fetch(self, company):
        self.c, self.s = company, company['source']
        self.max_pages = self.page_limit_override if self.page_limit_override is not None else self.s.get('max_pages', 60)
        self.r = FetchResult(company['id'], company['name'], self.s['adapter'])
        self.details = 0
        self.deadline = time.monotonic() + self.s.get("budget_seconds", 180)
        started = time.monotonic()
        try:
            method = getattr(self, self.s['adapter'], None)
            if not method: raise FetchError('Unsupported adapter: ' + self.s['adapter'], 'configuration_error')
            method()
        except FetchError as e:
            self.r.status, self.r.complete = e.kind, False
            self.r.messages.append(str(e))
        except (KeyError, TypeError, ValueError, IndexError) as e:
            self.r.status, self.r.complete = 'schema_changed', False
            self.r.messages.append(f'{type(e).__name__}: {e}')
        except Exception as e:
            self.r.status, self.r.complete = 'error', False
            self.r.messages.append(f'{type(e).__name__}: {e}')
        if not self.r.complete and self.s.get('wwr_fallback'):
            try:
                self.wwr_fallback()
            except FetchError as e:
                self.r.messages.append('Secondary WWR feed unavailable: '+str(e))
            except (KeyError, TypeError, ValueError, IndexError) as e:
                self.r.messages.append('Secondary WWR feed schema changed: '+type(e).__name__)
        self.r.jobs = list({j.key:j for j in self.r.jobs}.values())
        self.r.elapsed_seconds = round(time.monotonic()-started,2)
        self.r.source_urls = list(dict.fromkeys(self.r.source_urls))
        return self.r

    def read(self, url, *, payload=None, as_json=False, form=None, refresh=False):
        if time.monotonic() > self.deadline: raise FetchError("Per-source time budget reached; remaining coverage unverified", "budget_exceeded")
        self.r.source_urls.append(url)
        self.r.pages += 1
        cache_options={'refresh':True} if refresh else {}
        if as_json: return self.http.json(url, payload=payload, form=form, public_api="smartrecruiters-postings" if url.startswith("https://api.smartrecruiters.com/v1/companies/") else None,**cache_options)
        return self.http.text(url, payload=payload, form=form,**cache_options)

    def partial(self, message):
        self.r.status, self.r.complete = 'partial', False
        if message not in self.r.messages: self.r.messages.append(message)

    def new(self, title, url, sid='', **kw):
        return Job(self.c['id'],self.c['name'],htmllib.unescape(str(title)).strip(),canonical_url(url),str(sid or ''),**kw)

    def wanted(self, title):
        return bool(self.screener.family(title))

    def wwr_fallback(self):
        # Public syndication is a supplementary discovery source, never proof
        # of a full employer inventory or original publication time.
        feed='https://weworkremotely.com/remote-jobs.rss'
        config=self.s['wwr_fallback']
        names={norm(name) for name in config['employer_names']}
        hosts=set(config['employer_hosts'])
        try:
            root=etree.fromstring(self.read(feed).encode(),etree.XMLParser(resolve_entities=False,no_network=True))
        except etree.XMLSyntaxError as e:
            raise FetchError('Malformed WWR RSS XML','schema_changed') from e
        if root.tag!='rss' or len(root.findall('channel'))!=1:
            raise FetchError('Expected WWR RSS channel','schema_changed')
        channel=root.find('channel')
        if channel.findtext('link')!=feed:
            raise FetchError('WWR RSS channel identity changed','schema_changed')
        seen=set();unverified=0
        for item in channel.findall('item'):
            company,separator,title=(item.findtext('title') or '').partition(':')
            if not separator or norm(company) not in names:continue
            description=item.findtext('description') or ''
            # Match the feed's explicit employer URL field, not an arbitrary
            # mention/link in the vacancy text or a same-named company.
            d=document(description)
            employer_links=d.xpath('//strong[normalize-space(.)="URL:"]/following-sibling::a[1]/@href')
            if len(employer_links)!=1 or urlsplit(employer_links[0]).scheme not in {'https','http'} or urlsplit(employer_links[0]).hostname not in hosts:
                unverified+=1;continue
            link=item.findtext('link') or ''
            parts=urlsplit(link)
            if parts.scheme!='https' or parts.hostname!='weworkremotely.com' or not re.fullmatch(r'/remote-jobs/[a-z0-9-]+',parts.path):
                unverified+=1;continue
            link=canonical_url(link)
            if link in seen:continue
            seen.add(link);self.r.discovered+=1
            if not self.wanted(title):continue
            j=self.new(title,link,'wwr:'+parts.path.rsplit('/',1)[-1],
                       location=item.findtext('region') or '',description=plain(description),
                       evidence=[feed,link,employer_links[0]])
            j.detail_ok=len(j.description)>60
            j.metadata.update({'secondary_source':'We Work Remotely RSS',
                               'original_date_unproven':True,
                               'syndicated_pub_date':item.findtext('pubDate'),
                               'source_scope':'Recent public RSS items only; full employer inventory unverified'})
            self.r.jobs.append(j)
        self.partial(f'Secondary WWR RSS checked: {len(seen)} employer listings; recent syndicated subset only, full inventory and original dates unverified')
        if unverified:self.r.messages.append(f'WWR items skipped because employer or job identity could not be verified: {unverified}')

    def detail(self, job, url=None):
        if self.details >= self.max_details:
            self.partial(f'Detail cap ({self.max_details}) reached; remaining candidates need another run/configuration change')
            return job
        self.details += 1
        try:
            target = url or job.url
            body = self.read(target)
            enrich_job(job,body,target,self.s.get('body_xpath'))
            if self.s.get('detail_title_xpath'):
                nodes = document(body).xpath(self.s['detail_title_xpath'])
                if nodes: job.title = ' '.join(nodes[0].text_content().split())
            if not job.detail_ok or len(job.description)<60:
                self.partial('Some candidate descriptions could not be extracted')
                job.metadata['detail_error'] = 'No recognizable full job description'
        except FetchError as e:
            self.partial('Some candidate details are unavailable; see per-job detail_error')
            job.metadata['detail_error'] = str(e)
        return job

    def greenhouse(self):
        base = 'https://boards-api.greenhouse.io/v1/boards/' + self.s['board']
        data = self.read(base+'/jobs?content=true',as_json=True)
        jobs = require_list(data,'jobs'); self.r.discovered = len(jobs)
        total = (data.get('meta') or {}).get('total')
        if total is not None and total != len(jobs): self.partial(f'Board returned {len(jobs)} of {total} jobs')
        for x in jobs:
            if not self.wanted(x['title']): continue
            desc = plain(htmllib.unescape(x.get('content') or ''))
            date = x.get('first_published')
            j = self.new(x['title'],x['absolute_url'],x['id'],location=(x.get('location') or {}).get('name',''),description=desc,
                posted_at=date,date_kind='original_posted' if date else 'unknown',date_evidence='Greenhouse.first_published' if date else '',
                updated_at=x.get('updated_at'),valid_through=x.get('application_deadline'),detail_ok=bool(desc),evidence=[base+'/jobs/'+str(x['id'])])
            if not date or not desc:
                try:
                    detail=self.read(base+'/jobs/'+str(x['id']),as_json=True)
                    if detail.get('content'): j.description=plain(htmllib.unescape(detail['content']));j.detail_ok=True
                    if detail.get('first_published'): j.posted_at=detail['first_published'];j.date_kind='original_posted';j.date_evidence='Greenhouse.first_published'
                except FetchError as e: self.partial(str(e))
            self.r.jobs.append(j)

    def ashby(self):
        data=self.read('https://api.ashbyhq.com/posting-api/job-board/'+self.s['board']+'?includeCompensation=true',as_json=True)
        jobs=require_list(data,'jobs');self.r.discovered=len(jobs)
        self.ashby_jobs(jobs)

    def ashby_jobs(self, jobs):
        for x in jobs:
            if x.get('isListed') is False or not self.wanted(x['title']):continue
            locations=[x.get('location','')]+[z.get('location','') for z in x.get('secondaryLocations',[])]
            addresses=[x.get('address',{})]+[z.get('address',{}) for z in x.get('secondaryLocations',[])]
            countries=[a.get('postalAddress',{}).get('addressCountry','') for a in addresses if isinstance(a,dict)]
            j=self.new(x['title'],x.get('jobUrl') or x.get('url'),x['id'],location='; '.join(filter(None,locations)),countries=list(dict.fromkeys(filter(None,countries))),
                workplace=x.get('workplaceType') or ('remote' if x.get('isRemote') else 'unknown'),description=x.get('descriptionPlain') or plain(x.get('descriptionHtml','')),
                posted_at=x.get('publishedAt'),date_kind='last_published',date_evidence='Ashby.publishedAt (last publication, not original)',detail_ok=bool(x.get('descriptionPlain') or x.get('descriptionHtml')),
                metadata={'compensation':x.get('compensation',{}),'original_date_unproven':True})
            j.evidence=[j.url];self.r.jobs.append(j)

    def lever(self):
        base='https://api.'+('eu.' if self.s.get('region')=='eu' else '')+'lever.co/v0/postings/'+self.s['board']
        seen=set()
        for page in range(self.max_pages):
            data=self.read(base+'?'+urlencode({'mode':'json','skip':page*100,'limit':100}),as_json=True)
            if not isinstance(data,list):raise FetchError('Expected Lever posting array','schema_changed')
            fresh=[x for x in data if x['id'] not in seen]
            if data and not fresh:raise FetchError('Lever pagination repeated a page','pagination_error')
            for x in fresh:
                seen.add(x['id']);self.r.discovered+=1
                if not self.wanted(x['text']):continue
                cat=x.get('categories') or {}
                desc=x.get('descriptionPlain') or plain(x.get('description',''))
                for block in x.get('lists',[]):desc+='\n'+str(block.get('text',''))+'\n'+plain(block.get('content',''))
                desc+='\n'+(x.get('additionalPlain') or plain(x.get('additional','')))
                # createdAt can be requisition creation, not original public publication.
                j=self.new(x['text'],x['hostedUrl'],x['id'],location=cat.get('location',''),workplace=x.get('workplaceType','unknown'),description=desc,detail_ok=len(desc)>60,
                    posted_at=str(x['createdAt']) if x.get('createdAt') else None,date_kind='created',date_evidence='Lever.createdAt (not verified original public publication)',evidence=[x['hostedUrl']])
                self.detail(j);self.r.jobs.append(j)
            if len(data)<100:return
        self.partial('Lever pagination limit reached')

    def recruitee(self):
        url=self.s['base'].rstrip('/')+'/api/offers/'
        jobs=require_list(self.read(url,as_json=True),'offers');self.r.discovered=len(jobs)
        for x in jobs:
            if not self.wanted(x['title']):continue
            locs=x.get('locations') or []
            countries=[z.get('country_code') or z.get('country','') for z in locs]+[x.get('country_code') or x.get('country','')]
            desc=plain((x.get('description') or '')+'\n'+(x.get('requirements') or ''))
            j=self.new(x['title'],x.get('careers_url') or x.get('url'),x['id'],location=x.get('location') or '; '.join(z.get('city','') for z in locs),countries=list(dict.fromkeys(filter(None,countries))),
                workplace='hybrid' if x.get('hybrid') else 'remote' if x.get('remote') else 'onsite' if x.get('on_site') else 'unknown',description=desc,detail_ok=len(desc)>60,
                posted_at=x.get('published_at'),date_kind='published',date_evidence='Recruitee.published_at; original publication not independently established',updated_at=x.get('updated_at'),valid_through=x.get('close_at'),evidence=[url])
            self.detail(j);self.r.jobs.append(j)

    def remote_public(self):
        base=self.s['base']+'/api/public/jobs'
        data=self.read(base,as_json=True);jobs=require_list(data,'jobs')
        if data.get('next') or data.get('next_page'):self.partial('Remote returned unhandled pagination')
        self.r.discovered=len(jobs)
        def rich_text(value):
            if isinstance(value,str):return value
            if isinstance(value,list):return '\n'.join(filter(None,(rich_text(v) for v in value)))
            if isinstance(value,dict):return value.get('text','')+'\n'+rich_text(value.get('content',[]))
            return ''
        for x in jobs:
            if x.get('status')!='open' or not x.get('accepting_applications') or not self.wanted(x['title']):continue
            sid=x['public_id'];j=self.new(x['title'],self.s['base']+'/jobs/'+sid,sid,location=x.get('location',''),workplace=x.get('workplace','unknown'))
            try:
                detail=self.read(base+'/'+sid,as_json=True)['job']
                desc='\n'.join(rich_text(v.get('doc',{})) for v in detail.get('advert_sections') or [])
                desc+='\n'+str(detail.get('description') or '')+'\n'+str(detail.get('requirements') or '')+'\n'+str(detail.get('pay_text') or '')
                j.description=desc.strip();j.detail_ok=len(j.description)>60
                j.posted_at=detail.get('opened_at');j.date_kind='opened'
                j.date_evidence='Remote.opened_at; reopening vs original publication unverified'
                j.metadata['salary_display']=detail.get('pay');j.evidence.append(base+'/'+sid)
                if not j.detail_ok:self.partial('Remote candidate description missing')
            except FetchError as e:self.partial(str(e));j.metadata['detail_error']=str(e)
            self.r.jobs.append(j)

    def pinpoint(self):
        url=self.s['base']+'/jobs.json';data=self.read(url,as_json=True);jobs=require_list(data,'data');self.r.discovered=len(jobs)
        for x in jobs:
            if not self.wanted(x['title']):continue
            desc='\n'.join(plain(x.get(k) or '') for k in ['description','key_responsibilities','skills_knowledge_expertise','benefits'])
            loc=x.get('location') or {};loc=loc.get('name','') if isinstance(loc,dict) else str(loc)
            j=self.new(x['title'],x.get('url') or urljoin(self.s['base'],x['path']),x['id'],location=loc,workplace=x.get('workplace_type','unknown'),description=desc,detail_ok=len(desc)>60,valid_through=x.get('deadline_at'))
            self.detail(j);self.r.jobs.append(j)
        if data.get('links',{}).get('next'):self.partial('Pinpoint returned unexpected pagination; more pages may exist')

    def workable(self):
        base='https://apply.workable.com';url=base+'/api/v3/accounts/'+self.s['board']+'/jobs'
        payload={'query':'','location':[],'department':[],'worktype':[],'remote':[]};seen=set()
        for _ in range(self.max_pages):
            data=self.read(url,payload=payload,as_json=True);jobs=require_list(data,'results')
            for x in jobs:
                sid=x.get('shortcode') or x.get('id')
                if sid in seen:continue
                seen.add(sid);self.r.discovered+=1
                if not self.wanted(x['title']):continue
                loc=x.get('location') or {};locstr=', '.join(str(loc.get(k) or '') for k in ['city','country']) if isinstance(loc,dict) else str(loc)
                j=self.new(x['title'],x.get('url') or f'{base}/j/{sid}/',sid,location=locstr,countries=[loc.get('country_code') or loc.get('countryCode','')] if isinstance(loc,dict) else [],workplace='remote' if x.get('remote') else 'unknown')
                try:
                    detail_url=f'{base}/api/v2/accounts/{self.s["board"]}/jobs/{sid}'
                    detail=self.read(detail_url,as_json=True)
                    j.description='\n'.join(plain(detail.get(k) or '') for k in ['description','requirements','benefits'])
                    j.detail_ok=len(j.description)>60
                    j.posted_at=detail.get('published');j.date_kind='published'
                    j.date_evidence='Workable.published; original publication unverified'
                    j.evidence.append(detail_url)
                    if not j.detail_ok:self.partial('Workable candidate description missing')
                except FetchError as e:
                    self.partial(str(e));j.metadata['detail_error']=str(e)
                self.r.jobs.append(j)
            token=data.get('nextPage')
            if not token:
                if data.get('total',len(seen))>len(seen):self.partial('Workable total exceeds received jobs')
                if not seen:self.partial('Public Workable account returned zero; employer page still advertises roles, source needs reconciliation')
                return
            payload['token']=token
        self.partial('Workable pagination limit reached')

    def bamboohr(self):
        data=self.read(self.s['base']+'/careers/list',as_json=True);jobs=require_list(data,'result');self.r.discovered=len(jobs)
        total=(data.get('meta') or {}).get('totalCount',len(jobs))
        if total>len(jobs):self.partial('BambooHR total exceeds returned jobs')
        for x in jobs:
            title=x.get('jobOpeningName') or x.get('title','')
            if not self.wanted(title):continue
            sid=x.get('id');j=self.new(title,self.s['base']+'/careers/'+str(sid),sid)
            self.detail(j);self.r.jobs.append(j)
        if not jobs:self.partial('BambooHR public list is empty; employer careers page still advertises openings')

    def smartrecruiters(self):
        base='https://api.smartrecruiters.com/v1/companies/'+self.s['board']+'/postings';seen=set()
        for page in range(self.max_pages):
            data=self.read(base+'?'+urlencode({'country':self.s['country'],'limit':100,'offset':page*100}),as_json=True)
            jobs=require_list(data,'content');new=0
            for x in jobs:
                if x['id'] in seen:continue
                seen.add(x['id']);new+=1;self.r.discovered+=1
                if not self.wanted(x['name']):continue
                loc=x.get('location') or {};url='https://jobs.smartrecruiters.com/'+self.s['board']+'/'+str(x['id'])
                j=self.new(x['name'],url,x['id'],location=loc.get('fullLocation') or loc.get('city',''),countries=[loc.get('country','')],workplace='hybrid' if loc.get('hybrid') else 'remote' if loc.get('remote') else 'unknown',posted_at=x.get('releasedDate'),date_kind='released',date_evidence='SmartRecruiters.releasedDate (original date unproven)')
                try:
                    detail=self.read(base+'/'+str(x['id']),as_json=True)
                    sections=(detail.get('jobAd') or {}).get('sections',{})
                    j.description='\n'.join(plain(v.get('text','')) for v in sections.values() if isinstance(v,dict));j.detail_ok=len(j.description)>60
                    j.description+='\n'+str(loc.get('hybridDescription',''))
                    j.evidence=[base+'/'+str(x['id'])]
                    j.metadata['original_date_unproven']=True
                except FetchError as e:self.partial(str(e))
                self.r.jobs.append(j)
            total=data.get('totalFound')
            if total is None:raise FetchError('SmartRecruiters missing totalFound','schema_changed')
            if len(seen)>=total:return
            if not new:raise FetchError('SmartRecruiters stopped before totalFound','pagination_error')
        self.partial('SmartRecruiters pagination limit reached')

    def workday(self):
        base=self.s['base']+'/wday/cxs/'+self.s['tenant']+'/'+self.s['site'];seen=set()
        for term in self.s.get('search_terms',['Portugal']):
            offset=0
            for _ in range(self.max_pages):
                data=self.read(base+'/jobs',payload={'appliedFacets':{},'limit':20,'offset':offset,'searchText':term},as_json=True)
                jobs=require_list(data,'jobPostings');total=data.get('total')
                if not isinstance(total,int):raise FetchError('Workday missing total','schema_changed')
                for x in jobs:
                    path=x['externalPath']
                    if path in seen:continue
                    seen.add(path);self.r.discovered+=1
                    if not self.wanted(x['title']):continue
                    url=self.s['base']+'/en-US/'+self.s['site']+path
                    j=self.new(x['title'],url,path,location=x.get('locationsText',''))
                    try:
                        detail=self.read(base+path,as_json=True);d=detail.get('jobPostingInfo')
                        if not isinstance(d,dict):raise FetchError('Missing Workday jobPostingInfo','schema_changed')
                        j.source_id=str(d.get('jobReqId') or path);j.description=plain(d.get('jobDescription',''));j.detail_ok=len(j.description)>60
                        j.location='; '.join(filter(None,[d.get('location',j.location)]+d.get('additionalLocations',[])))
                        country=d.get('country') or {};j.countries=[country.get('descriptor','')] if isinstance(country,dict) else [str(country)]
                        j.posted_at=d.get('startDate');j.date_kind='published';j.date_evidence='Workday.startDate; original publication not independently established'
                        j.valid_through=d.get('endDate');j.evidence=[base+path]
                        self.detail(j)
                    except FetchError as e:self.partial(str(e))
                    self.r.jobs.append(j)
                offset+=len(jobs)
                if offset>=total:break
                if not jobs:raise FetchError('Workday stopped before total','pagination_error')
            else:self.partial('Workday pagination limit reached')
        self.r.messages.append('Query scope: '+self.s.get('scope','configured Workday search terms'))
        # This is complete for the configured query, not a claim to cover every global role.

    def intellias(self):
        # The official public filter JS posts this read-only action to WordPress AJAX.
        posts=[];total=None;seen=set()
        for page in range(1,self.max_pages+1):
            data=self.read('https://career.intellias.com/wp-admin/admin-ajax.php',form={'action':'fly_vacancies','page':page},as_json=True)
            batch=require_list(data,'posts');total=data.get('total')
            fresh=[x for x in batch if x not in seen]
            if batch and not fresh:raise FetchError('Intellias repeated listing page','pagination_error')
            posts.extend(fresh);seen.update(fresh)
            if data.get('end') is True:break
            if not batch:raise FetchError('Intellias stopped without end marker','pagination_error')
        else:self.partial('Intellias pagination limit reached')
        self.html(initial_body='<html><body>'+''.join(posts)+'</body></html>')
        if total is not None and self.r.discovered<int(total):self.partial('Intellias returned fewer unique jobs than its total')

    def phenom(self):
        seen=set()
        for page in range(self.max_pages):
            payload={'lang':'en_global','deviceType':'desktop','country':'global','pageName':'search-results','ddoKey':'refineSearch','sortBy':'Most recent','subsearch':'','from':page*100,'jobs':True,'counts':True,'all_fields':['country','WorkType','city','CareerLevel','category'],'size':100,'clearAll':False,'jdsource':'facets','isSliderEnable':False,'pageType':'search-results','keywords':'','global':True,'selected_fields':{'country':['Portugal']},'sort':{},'locationData':{}}
            url='https://jobs.kuehne-nagel.com/widgets'
            data=self.read(url,payload=payload,as_json=True).get('refineSearch',{})
            if data.get('status')!=200:raise FetchError('Phenom public search returned an error','source_error')
            jobs=require_list(data.get('data',{}),'jobs');total=data.get('totalHits');new=0
            for x in jobs:
                sid=x['jobSeqNo']
                if sid in seen:continue
                seen.add(sid);new+=1;self.r.discovered+=1
                if not self.wanted(x['title']):continue
                joburl=urljoin(url,'/global/en/job/'+sid+'/'+re.sub(r'[^A-Za-z0-9]+','-',x['title']).strip('-'))
                j=self.new(x['title'],joburl,sid,location=x.get('location') or x.get('cityStateCountry',''),countries=[x.get('country','')],workplace=x.get('remote','unknown'),posted_at=x.get('postedDate'),date_kind='published',date_evidence='Phenom.postedDate; original publication unverified')
                self.detail(j);self.r.jobs.append(j)
            if total is None:raise FetchError('Phenom missing totalHits','schema_changed')
            if len(seen)>=int(total):return
            if not new:raise FetchError('Phenom repeated a page or stopped early','pagination_error')
        self.partial('Phenom pagination limit reached')

    def ashby_embedded(self):
        # Some employers enable the hosted board but not Ashby's optional posting API.
        url='https://jobs.ashbyhq.com/'+self.s['board'];body=self.read(url)
        m=re.search(r'window\.__appData\s*=\s*',body)
        if not m:raise FetchError('Ashby hosted board data missing','schema_changed')
        data,_=json.JSONDecoder().raw_decode(body[m.end():]);jobs=require_list(data.get('jobBoard') or {},'jobPostings')
        self.r.discovered=len(jobs)
        for x in jobs:
            if not self.wanted(x['title']):continue
            locs=[x.get('locationName','')]+[z.get('locationName','') for z in x.get('secondaryLocations',[])]
            j=self.new(x['title'],url+'/'+x['id'],x['id'],location='; '.join(filter(None,locs)),workplace=x.get('workplaceType','unknown'),metadata={'original_date_unproven':True})
            self.detail(j);self.r.jobs.append(j)

    def sap_unified(self):
        base=self.s['base'];seen=set()
        for page in range(self.max_pages):
            data=self.read(base+'/services/recruiting/v1/jobs',payload={'keywords':'','locale':'en_US','location':'Portugal','pageNumber':page,'sortBy':'recent'},as_json=True)
            rows=require_list(data,'jobSearchResult');total=data.get('totalJobs');new=0
            for row in rows:
                x=row['response'];sid=str(x['id'])
                if sid in seen:continue
                seen.add(sid);new+=1;self.r.discovered+=1
                title=x['unifiedStandardTitle']
                if not self.wanted(title):continue
                from urllib.parse import quote
                url=base+'/job/'+quote(htmllib.unescape(x.get('unifiedUrlTitle') or title),safe='-')+'/'+sid+'-en_US'
                j=self.new(title,url,sid,location='; '.join(x.get('jobLocationShort',[])),countries=x.get('jobLocationCountry',[]),posted_at=x.get('unifiedStandardStart'),date_kind='published',date_evidence='SAP unified start date; original public posting unverified',valid_through=x.get('unifiedStandardEnd'))
                self.detail(j);self.r.jobs.append(j)
            if total is None:raise FetchError('SAP unified search missing totalJobs','schema_changed')
            if len(seen)>=int(total):return
            if not new:raise FetchError('SAP unified pagination repeated or stopped early','pagination_error')
        self.partial('SAP unified pagination limit reached')

    def namecheap(self):
        # The public HTML page includes the exact paginated data consumed by
        # its Vue component. Never follow its internal backend pagination URLs.
        base=self.s['base'];url=base+'/careers/openings/';seen=set();expected=None
        for page in range(1,self.max_pages+1):
            body=self.read(with_query(url,page=page))
            match=re.search(r'window\.openingsData\s*=\s*',body)
            if not match:raise FetchError('Namecheap openings data missing','schema_changed')
            try:data,_=json.JSONDecoder().raw_decode(body[match.end():])
            except ValueError as e:raise FetchError('Invalid Namecheap openings data','schema_changed') from e
            d=data.get('jobs') if isinstance(data,dict) else None
            if not isinstance(d,dict):raise FetchError('Namecheap jobs envelope missing','schema_changed')
            jobs=require_list(d,'data')
            total=d.get('total');last=d.get('last_page');current=d.get('current_page')
            if not all(isinstance(x,int) and not isinstance(x,bool) for x in (total,last,current)) or total<0 or last<1 or current!=page:
                raise FetchError('Namecheap pagination metadata inconsistent','pagination_error')
            if expected is not None and total!=expected:self.partial('Namecheap total changed during pagination')
            expected=total;new=0
            for x in jobs:
                sid=str(x['jobid'])
                if sid in seen:continue
                seen.add(sid);new+=1;self.r.discovered+=1
                if not self.wanted(x['title']):continue
                j=self.new(x['title'],base+'/careers/details/'+sid+'/',sid,location='; '.join(filter(None,[x.get('country'),x.get('location')])))
                self.detail(j);self.r.jobs.append(j)
            if page>=last:
                if len(seen)!=expected:self.partial(f'Namecheap returned {len(seen)} of {expected} postings')
                return
            if not new:raise FetchError('Namecheap pagination repeated or stopped early','pagination_error')
        self.partial('Namecheap pagination limit reached')

    def cocus(self):
        try:
            self.html()
            return
        except FetchError as error:
            if error.kind not in {'blocked','network_error','robots_denied','robots_unavailable'}:raise
            reason=str(error)
        self.partial('ATS inventory unavailable; employer-page subset only: '+reason)
        body=self.read(self.s['fallback_url']);d=document(body);seen=set()
        for a in d.xpath('//a[@href]'):
            url=canonical_url(urljoin(self.s['fallback_url'],a.get('href')))
            if urlsplit(url).hostname!='talent.sage.hr' or not re.search(r'/jobs/[a-f0-9-]{36}$',url):continue
            title=' '.join(a.text_content().split())
            if not title or 'open application' in norm(title) or url in seen:continue
            seen.add(url);self.r.discovered+=1
            if self.wanted(title):self.r.jobs.append(self.detail(self.new(title,url)))
        if not seen:self.r.messages.append('Employer page no longer contains recognizable vacancy cards')

    def sitemap(self):
        # An explicitly declared sitemap scope, not a claim that unpublished
        # or unlisted postings have been discovered. lastmod is never a datePosted.
        start=self.s['sitemap_url'];host=urlsplit(start).hostname
        queue=[start];visited=set();urls=set()
        parser=etree.XMLParser(resolve_entities=False,no_network=True)
        while queue:
            url=queue.pop(0)
            if url in visited:continue
            if len(visited)>=self.max_pages:
                self.partial('Sitemap page limit reached');break
            if urlsplit(url).hostname!=host:raise FetchError('Cross-host sitemap reference refused','schema_changed')
            visited.add(url)
            try:root=etree.fromstring(self.read(url).encode(),parser)
            except etree.XMLSyntaxError as e:raise FetchError('Malformed sitemap XML','schema_changed') from e
            kind=etree.QName(root).localname
            entries=[u.strip() for u in root.xpath('./*[local-name()="sitemap" or local-name()="url"]/*[local-name()="loc"]/text()') if u.strip()]
            if kind=='sitemapindex':queue.extend(u for u in entries if u not in visited)
            elif kind=='urlset':
                for u in entries:
                    if urlsplit(u).hostname==host and re.search(self.s['job_pattern'],urlsplit(u).path):urls.add(canonical_url(u))
            else:raise FetchError('Unrecognized sitemap root','schema_changed')
        if not urls:raise FetchError('Sitemap contains no recognizable job URLs; coverage unverified','schema_changed')
        self.r.discovered=len(urls)
        self.r.messages.append('Coverage scope: all sitemap-listed job URLs; allowed titles selected from URL slugs; sitemap lastmod is not original publication')
        for url in sorted(urls):
            slug=unquote(urlsplit(url).path.split('/job/',1)[-1].split('/')[0]).replace('-',' ')
            if not self.wanted(slug):continue
            if self.details>=self.max_details:
                self.partial('Sitemap candidate detail limit reached');break
            self.details+=1
            j=self.new(slug,url)
            try:
                body=self.read(url);d=document(body)
                if self.s.get('detail_kind')=='jobposting':
                    schemas=jsonld_nodes(body)
                    identity=re.search(r'/job/(\d+)',urlsplit(url).path)
                    valid=[]
                    for node in schemas:
                        target=urljoin(url,node.get('url') or url)
                        other=re.search(r'/job/(\d+)',urlsplit(target).path)
                        if urlsplit(target).hostname==host and (urlsplit(target).path==urlsplit(url).path or identity and other and identity.group(1)==other.group(1)):
                            valid.append(node)
                    if len(valid)!=1:
                        self.partial('Sitemap detail lacks an unambiguous matching JobPosting')
                        j.metadata['detail_error']='Matching JobPosting missing'
                    else:
                        j=from_schema(self.c,valid[0],url)
                        if identity:j.source_id=identity.group(1)
                        j.detail_ok=len(j.description)>60
                        if not j.detail_ok:self.partial('Some sitemap descriptions are incomplete')
                    if self.wanted(j.title):self.r.jobs.append(j)
                    continue
                title_nodes=d.xpath('//*[@itemprop="title"]')
                desc_nodes=d.xpath('//*[@itemprop="description"]')
                if not title_nodes or not desc_nodes:
                    self.partial('Some sitemap job pages lack expected job detail fields')
                    j.metadata['detail_error']='Job title or description missing'
                else:
                    j.title=' '.join(title_nodes[0].text_content().split())
                    j.description='\n'.join(plain(html.tostring(n,encoding='unicode')) for n in desc_nodes)
                    j.detail_ok=len(j.description)>60
                    if not j.detail_ok:self.partial('Some sitemap descriptions are incomplete')
                    # Field labels vary with the site's locale. Do not infer
                    # posting dates from publication-start labels or sitemap dates.
                    for label in d.xpath('//*[contains(@class,"joblayouttoken-label")]'):
                        text=norm(label.text_content()).strip(' :\xa0')
                        if text in {'location','work location','lieu de travail','local de trabalho','localizacao'}:
                            values=label.getparent().xpath('.//span[not(contains(@class,"joblayouttoken-label"))]')
                            if values:j.location=' '.join(values[-1].text_content().split())
                    canonical=d.xpath('//link[@rel="canonical"]/@href')
                    if canonical and urlsplit(canonical[0]).hostname==host and re.search(self.s['job_pattern'],urlsplit(canonical[0]).path):
                        j.url=canonical_url(canonical[0]);j.source_id=urlsplit(j.url).path.rstrip('/').rsplit('/',1)[-1]
                    enrich_job(j,body,url)
            except FetchError as error:
                self.partial('Some sitemap job details unavailable')
                j.metadata['detail_error']=str(error)
            if self.wanted(j.title):self.r.jobs.append(j)

    def eightfold_pcsx(self):
        # Current public careers UI contract. Enumerate its inventory rather than
        # sitemap slugs, which can omit new jobs and retain withdrawn IDs.
        base=self.s['base'];domain=self.s['domain'];seen=set();start=0;expected=None
        for page in range(self.max_pages):
            url=base+'/api/pcsx/search?'+urlencode({'domain':domain,'query':'','location':'','start':start})
            data=self.pcsx_data(url)
            rows=require_list(data,'positions');total=data.get('count')
            if not isinstance(total,int) or isinstance(total,bool) or total<0:
                raise FetchError('PCSX search total missing or invalid','schema_changed')
            if expected is not None and total!=expected:self.partial('PCSX inventory changed during pagination')
            expected=total;new=0
            for row in rows:
                sid=str(row.get('id',''));title=row.get('name')
                if not re.fullmatch(r'[1-9]\d*',sid) or not isinstance(title,str) or not title.strip():
                    raise FetchError('PCSX listing identity or title missing','schema_changed')
                if sid in seen:
                    self.partial('PCSX pagination contained duplicate IDs');continue
                seen.add(sid);new+=1;self.r.discovered+=1
                if self.wanted(title):
                    target=base+'/careers/job/'+sid+'?'+urlencode({'domain':domain})
                    self.r.jobs.append(self.new(title,target,sid))
            start+=len(rows)
            if start>=total:
                if len(seen)!=total:self.partial(f'PCSX returned {len(seen)} unique jobs of {total}')
                break
            if not new:raise FetchError('PCSX pagination repeated or stopped before total','pagination_error')
        else:self.partial('PCSX pagination limit reached')
        self.r.messages.append('Coverage scope: public PCSX search inventory, all locations and titles')
        for j in self.r.jobs:
            if self.details>=self.max_details:
                self.partial('PCSX candidate detail limit reached');break
            self.details+=1
            try:
                body=self.read(j.url);schemas=jsonld_nodes(body)
                matching=[]
                for node in schemas:
                    target=urlsplit(urljoin(j.url,node.get('url') or j.url))
                    identity=re.search(r'/careers/job/(\d+)(?:[-/]|$)',target.path)
                    if target.hostname==urlsplit(base).hostname and identity and identity.group(1)==j.source_id:
                        matching.append(node)
                if len(matching)==1:
                    parsed=from_schema(self.c,matching[0],j.url)
                    # Retain the stable inventory ID, even if the schema uses an ATS ID.
                    for field in ('title','description','location','countries','workplace','posted_at','date_kind','date_evidence','valid_through','salary'):
                        setattr(j,field,getattr(parsed,field))
                    j.evidence.append(j.url)
                elif schemas:
                    raise FetchError('PCSX detail has ambiguous or unrelated JobPosting data','schema_changed')
                else:
                    detail_url=base+'/api/pcsx/position_details?'+urlencode({'position_id':j.source_id,'domain':domain,'hl':'en'})
                    data=self.pcsx_data(detail_url)
                    if str(data.get('id'))!=j.source_id or not isinstance(data.get('name'),str) or not data['name'].strip():
                        raise FetchError('PCSX detail identity does not match listing','schema_changed')
                    j.title=data['name'];j.description=plain(data.get('jobDescription') or '')
                    locations=data.get('standardizedLocations') or data.get('locations') or []
                    if not isinstance(locations,list) or not all(isinstance(x,str) for x in locations):
                        raise FetchError('PCSX detail locations invalid','schema_changed')
                    j.location='; '.join(locations)
                    j.workplace={'remote':'remote','hybrid':'hybrid','onsite':'onsite'}.get(data.get('workLocationOption'),'unknown')
                    # postedTs is not evidence of *original* publication. Only
                    # matched JobPosting.datePosted above can supply freshness.
                    j.metadata['pcsx_posted_ts']=data.get('postedTs')
                    j.evidence.extend([j.url,detail_url])
                j.detail_ok=bool(j.title.strip()) and len(j.description)>60
                if not j.detail_ok:raise FetchError('PCSX full job description missing','schema_changed')
            except FetchError as error:
                j.detail_ok=False;j.metadata['detail_error']=str(error)
                self.partial('Some PCSX candidate details unavailable; see per-job detail_error')
        self.r.jobs=[j for j in self.r.jobs if self.wanted(j.title)]

    def pcsx_data(self,url):
        envelope=self.read(url,as_json=True)
        if not isinstance(envelope,dict) or envelope.get('status')!=200 or envelope.get('error') not in (None, {}, {'message':'','body':''}) or not isinstance(envelope.get('data'),dict):
            raise FetchError('PCSX response envelope missing or unsuccessful','schema_changed')
        metadata=envelope.get('metadata')
        if metadata is not None and (not isinstance(metadata,dict) or metadata.get('isFallback')):
            raise FetchError('PCSX fallback response cannot verify current inventory','schema_changed')
        return envelope['data']

    def eightfold(self):
        base=self.s['base'];seen=set()
        for page in range(self.max_pages):
            url=base+'/api/apply/v2/jobs?'+urlencode({'domain':self.s['domain'],'query':'','location':self.s['location'],'start':page*100,'num':100})
            data=self.read(url,as_json=True);jobs=require_list(data,'positions')
            for x in jobs:
                sid=str(x['id'])
                if sid in seen:continue
                seen.add(sid);self.r.discovered+=1
                if not self.wanted(x['name']):continue
                url=x.get('canonicalPositionUrl') or base+'/careers/job/'+sid+'?domain='+self.s['domain']
                locs=x.get('locations') or [];locs=[str(a) for a in locs]
                j=self.new(x['name'],url,sid,location='; '.join(locs),posted_at=x.get('postedTs'),date_kind='published',date_evidence='Eightfold.postedTs (original publication unverified)')
                self.detail(j);self.r.jobs.append(j)
            total=data.get('count') or data.get('total')
            if total is not None and len(seen)>=int(total):return
            if len(jobs)<100:return
            if not jobs:raise FetchError('Eightfold stopped before reported total','pagination_error')
        self.partial('Eightfold pagination limit reached')

    def duckduckgo(self):
        # Endpoint resolved from the careers site's public client bundle.
        if not self.s.get('jobs_url'):raise FetchError('Dynamic careers API route needs resolution; careers page is retained for manual checking','needs_mapping')
        data=self.read(self.s['jobs_url'],as_json=True)
        jobs=data if isinstance(data,list) else require_list(data,'jobs')
        self.r.discovered=len(jobs);self.ashby_jobs(jobs)

    def astro(self):
        url=self.s['listing_url'];body=self.read(url)
        fragments=re.findall(r'fetch\(\s*["\'](/_server-islands/[^"\']+)',body)
        if not fragments:raise FetchError('Expected Astro careers island missing','schema_changed')
        for fragment in fragments:
            if 'OpenRoles' in fragment:body+='\n'+self.read(urljoin(url,htmllib.unescape(fragment)))
        self.html(initial_body=body)

    def html(self,initial_body=None):
        start=self.s['listing_url'];queue=[start];seenpages=set();seenjobs=set();matched=0
        def pagekey(u):
            p=urlsplit(u);q=dict(parse_qsl(p.query));q.pop('cHash',None)
            for k in list(q):
                if (k.lower() in {'page','currentpage'} or k.endswith('[currentPage]')) and q[k]=='1':q.pop(k)
                elif k.lower()=='startrow' and q[k]=='0':q.pop(k)
            if self.s.get('kind')=='continental':
                q={k:v for k,v in q.items() if not (k.endswith('[controller]') and v=='Frontend\\Toc')}
            return canonical_url(urlunsplit((p.scheme,p.netloc,p.path,urlencode(q),'')))
        while queue:
            url=queue.pop(0)
            if pagekey(url) in seenpages:continue
            if len(seenpages)>=self.max_pages:
                self.partial('HTML pagination limit reached');break
            seenpages.add(pagekey(url))
            body=initial_body if url==start and initial_body is not None else self.read(url)
            d=document(body);page_jobs=0
            if self.s.get('kind')=='continental' and not any(re.search(self.s['job_pattern'],a.get('href','')) for a in d.xpath('//a[@href]')):
                # This public directory intermittently returns a valid page
                # shell without its jobs. Re-read once, without memoizing the
                # same empty response; persistent absence still fails below.
                body=self.read(url,refresh=True);d=document(body)
                self.r.messages.append('Empty Continental listing page re-fetched once before coverage validation')
            for node in jsonld_nodes(body):
                # Ignore a generic company page that accidentally embeds unrelated cards.
                j=from_schema(self.c,node,url)
                if not j.title or j.url in seenjobs:continue
                seenjobs.add(j.url);self.r.discovered+=1;page_jobs+=1
                if self.wanted(j.title):self.r.jobs.append(j)
            for a in d.xpath('//a[@href]'):
                link=urljoin(url,htmllib.unescape(a.get('href')))
                if urlsplit(link).scheme not in {'https','http'}:continue
                if self.s.get('page_pattern') and re.search(self.s['page_pattern'],link) and urlsplit(link).netloc==urlsplit(start).netloc:
                    samepath=urlsplit(link).path.rstrip('/')==urlsplit(start).path.rstrip('/')
                    locale=dict(parse_qsl(urlsplit(link).query)).get('locale')
                    initial_locale=dict(parse_qsl(urlsplit(start).query)).get('locale')
                    if samepath and locale==initial_locale and pagekey(link) not in seenpages and not any(pagekey(link)==pagekey(q) for q in queue):queue.append(link)
                if not re.search(self.s['job_pattern'],link):continue
                link=canonical_url(link)
                page_jobs+=1
                if link in seenjobs:continue
                seenjobs.add(link);self.r.discovered+=1
                title=' '.join(a.text_content().split())
                if self.s.get('title_xpath'):
                    names=a.xpath(self.s['title_xpath'])
                    if names:title=' '.join(names[0].text_content().split())
                if not self.wanted(title) and not self.s.get('fetch_all_details'):continue
                j=self.new(title,link,location='')
                self.detail(j)
                if self.wanted(j.title):self.r.jobs.append(j)
            matched+=page_jobs
            if not page_jobs and len(seenpages)>1:
                self.partial('A pagination page contained no recognizable job links')
            # A JS Load more button without a crawlable next link cannot prove completeness.
            more=d.xpath('//button[contains(translate(normalize-space(.),"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"load more")]|//*[@data-next-page]')
            if more and not queue:self.partial('Dynamic pagination control found; complete enumeration is unverified')
        if not matched and d.xpath('//*[@data-total-results="0"]'):
            self.r.status='ok';self.r.complete=True;self.r.messages=['Employer search explicitly returned zero results for the configured Portugal scope'];return
        if not matched:
            text=norm(plain(initial_body or body))
            if self.s.get('inline_roles'):
                # JTA currently has a spontaneous-application form, not a structured vacancy board.
                # Detect future inline role headings and surface them for review.
                for e in d.xpath('//h1|//h2|//h3|//h4'):
                    title=' '.join(e.text_content().split())
                    if self.wanted(title):
                        j=self.new(title,start,source_key(title),description=plain(html.tostring(e.getparent(),encoding='unicode')),detail_ok=False)
                        j.metadata['inline_heading']=True;self.r.jobs.append(j);self.r.discovered+=1
            if self.s.get('empty_pattern') and re.search(self.s['empty_pattern'],text):
                if self.s.get('empty_is_unverified'):
                    self.r.status='limited';self.r.complete=False;self.r.messages.append('Careers page monitored; spontaneous applications only, no enumerated vacancy feed')
                else:self.r.messages.append('Recognized empty/open-application-only careers page')
            else:raise FetchError('No recognizable vacancies or explicit empty-board marker; dynamic page/schema may have changed','schema_changed')
        if self.s.get('kind')=='intellias' and 'pagination' in body and not any('page' in u for u in seenpages):
            self.partial('Intellias dynamic pagination requires its public listing endpoint')


def source_key(title):
    return 'inline:'+norm(title)
