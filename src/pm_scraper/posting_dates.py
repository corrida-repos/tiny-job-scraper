"""Job-specific publication evidence, with original and employer-declared policies."""
import re
from urllib.parse import urljoin, urlsplit
from .models import canonical_url, parse_date


def add_evidence(job, value, kind, source, url):
    if value is None or not str(value).strip():
        return
    entry = {'value': str(value).strip(), 'kind': kind, 'source': source, 'url': url}
    evidence = job.metadata.setdefault('posting_date_evidence', [])
    if entry not in evidence:
        evidence.append(entry)


def matches(job, node, url):
    """Explicit identifiers take precedence over titles; conflicting identity vetoes."""
    identities = []
    for key in ('url', '@id'):
        value = node.get(key)
        if isinstance(value, str):
            identities.append(canonical_url(urljoin(url, value)) == canonical_url(job.url))
    identifier = node.get('identifier')
    if isinstance(identifier, dict):
        identifier = identifier.get('value')
    if identifier and job.source_id:
        identities.append(str(identifier) == str(job.source_id))
    if identities:
        return all(identities)
    # An exact title is only sufficient for one unambiguous schema on this detail URL.
    return False


def enrich_dates(job, body, url):
    from .htmlutil import document, jsonld_nodes, norm
    add_evidence(job, job.posted_at, job.date_kind, job.date_evidence, job.url)
    nodes = jsonld_nodes(body)
    exact = [n for n in nodes if matches(job, n, url)]
    if not exact and len(nodes) == 1:
        n = nodes[0]
        explicit = any(n.get(k) for k in ('url', '@id', 'identifier'))
        if not explicit and canonical_url(url) == canonical_url(job.url) and norm(n.get('title', '')) == norm(job.title):
            exact = [n]
    originals = []
    for node in exact:
        value = node.get('datePosted')
        kind = 'published' if job.metadata.get('original_date_unproven') else 'original_posted'
        add_evidence(job, value, kind, 'Matching JobPosting.datePosted', url)
        if kind == 'original_posted' and parse_date(value):
            originals.append(str(value))
        add_evidence(job, node.get('dateModified'), 'updated', 'JobPosting.dateModified', url)
    d = document(body)
    scopes = d.xpath('//*[@itemscope and contains(@itemtype,"JobPosting")]')
    for scope in scopes:
        node = {}
        for prop in ('title', 'url', 'identifier', 'datePosted', 'dateModified'):
            values = scope.xpath('.//*[@itemprop="'+prop+'"]')
            if len(values) == 1:
                element = values[0]
                node[prop] = element.get('content') or element.get('datetime') or element.get('href') or element.text_content().strip()
        matched = matches(job, node, url)
        if not any(node.get(k) for k in ('url', 'identifier')):
            matched = len(scopes) == 1 and canonical_url(url) == canonical_url(job.url) and bool(node.get('title')) and norm(node['title']) == norm(job.title)
        if matched:
            value = node.get('datePosted')
            kind = 'published' if job.metadata.get('original_date_unproven') else 'original_posted'
            add_evidence(job, value, kind, 'JobPosting microdata datePosted', url)
            if kind == 'original_posted' and parse_date(value):
                originals.append(str(value))
    if originals:
        # Conflicting originals cannot make an older job look fresh.
        candidates = originals + ([str(job.posted_at)] if job.date_kind == 'original_posted' and parse_date(job.posted_at) else [])
        job.posted_at = min(candidates, key=parse_date)
        job.date_kind = 'original_posted'
        job.date_evidence = 'Matching JobPosting.datePosted (earliest evidence)'
    headings = d.xpath('//h1') or d.xpath('//*[@itemprop="title"]')
    # Bizneo adds location/work-model labels to inventory titles. The single
    # detail heading is its exact prefix. SuccessFactors uses itemprop, not h1.
    heading = norm(headings[0].text_content()) if len(headings) == 1 else ''
    title = norm(job.title)
    same_page = canonical_url(url) == canonical_url(job.url)
    canonical = d.xpath('//link[@rel="canonical"]/@href')
    # SuccessFactors maps a sitemap platform ID to a different requisition ID.
    # Accept its explicit canonical mapping on the same host, with the unique
    # job heading checked below; never infer an alias from a similar title alone.
    if len(canonical) == 1 and canonical_url(urljoin(url,canonical[0])) == canonical_url(job.url):
        supplied, target = urlsplit(url), urlsplit(job.url)
        same_page = same_page or supplied.hostname == target.hostname
    page_matches = same_page and len(heading.split()) >= 2 and (title == heading or title.startswith(heading+' '))
    if page_matches:
        # These employer labels are useful to readers but may be refreshed/reposted.
        for label in d.xpath('//*[contains(@class,"joblayouttoken-label")]'):
            if norm(label.text_content()).strip(' :\xa0') == 'posting start date':
                text = ' '.join(label.getparent().text_content().split())
                value = re.sub(r'^posting start date\s*:\s*', '', text, flags=re.I)
                # The URL explicitly declares this site's US locale; do not guess
                # the ordering of ambiguous numeric dates on other pages.
                parsed = parse_date(value) if re.search(r'en_US(?:$|[/?#])', job.url) else None
                add_evidence(job, parsed.date().isoformat() if parsed else value, 'posting_start' if parsed else 'posting_start_unparsed', 'Employer Posting Start Date', url)
        for label in d.xpath('//span[i and contains(normalize-space(text()),"Published")]'):
            values = label.xpath('./i/text()')
            if values:
                add_evidence(job, values[0], 'published', 'Employer Published label (year may be absent)', url)
    job.metadata['date_page_checked'] = True
    return job


def publication_candidate(job, accept_employer_dates=False):
    entries = list(job.metadata.get('posting_date_evidence', []))
    entries.append({'value':job.posted_at,'kind':job.date_kind,'source':job.date_evidence})
    allowed = {'original_posted'}
    if accept_employer_dates:
        allowed.update({'published','last_published','released','opened','posting_start'})
    candidates = [e for e in entries if e['kind'] in allowed and parse_date(e['value'])]
    if not candidates:
        return None
    return (max if accept_employer_dates else min)(candidates, key=lambda e:parse_date(e['value']))


def report_date(job, freshness=None):
    if freshness and freshness.get('date'):
        parts = ['Employer posting/repost date: ' + str(freshness['date'])]
        if job.date_kind == 'original_posted' and job.posted_at and str(job.posted_at) != str(freshness['date']):
            parts.append('Earliest original date: ' + str(job.posted_at))
        return '; '.join(parts)
    if job.date_kind == 'original_posted' and job.posted_at:
        return 'Employer posting date: ' + str(job.posted_at)
    entries = job.metadata.get('posting_date_evidence', [])
    parts = []
    if job.posted_at:
        parts.append('Employer date (original unverified): ' + str(job.posted_at))
    elif entries:
        item = entries[0]
        parts.append('Employer date (original unverified): ' + item['value'])
    if job.metadata.get('first_seen'):
        parts.append('Seen since: ' + job.metadata['first_seen'] + ' (observation, not publication)')
    return '; '.join(parts)
