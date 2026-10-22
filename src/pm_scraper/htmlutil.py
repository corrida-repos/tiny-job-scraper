import html as html_std
import json
import re
import unicodedata
from urllib.parse import urljoin
from lxml import html, etree
from .models import Job, parse_date

def norm(s):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c)).lower().split())

def document(body):
    try:
        return html.fromstring(body or "<html></html>")
    except (etree.ParserError, ValueError):
        return html.fromstring("<html></html>")

def plain(body):
    d = document(body)
    for e in d.xpath("//script|//style|//noscript|//nav|//footer"):
        e.drop_tree()
    for e in d.xpath("//p|//li|//h1|//h2|//h3|//div|//br|//section"):
        e.tail = "\n" + (e.tail or "")
    return "\n".join(" ".join(line.split()) for line in d.text_content().splitlines() if line.strip())

def jsonld_nodes(body):
    d = document(body)
    found = []
    def walk(x):
        if isinstance(x, list):
            for y in x: walk(y)
        elif isinstance(x, dict):
            kinds = x.get("@type", [])
            if kinds == "JobPosting" or isinstance(kinds, list) and "JobPosting" in kinds:
                found.append(x)
            for k, y in x.items():
                if k != "description" and isinstance(y, (dict, list)): walk(y)
    for script in d.xpath('//script[contains(@type,"ld+json")]/text()'):
        try: walk(json.loads(script.strip()))
        except (ValueError, TypeError):
            try: walk(json.loads(html_std.unescape(script.strip())))
            except (ValueError, TypeError): pass
    return found

def schema_location(j):
    locations, countries = [], []
    locs = j.get("jobLocation", [])
    for loc in locs if isinstance(locs, list) else [locs]:
        if not isinstance(loc, dict): continue
        address = loc.get("address", {})
        if isinstance(address, str):
            locations.append(address); continue
        if isinstance(address, dict):
            country = address.get("addressCountry", "")
            if isinstance(country, dict): country = country.get("name", "")
            if country: countries.append(str(country))
            locations.append(", ".join(str(address.get(k, "")) for k in ["addressLocality", "addressRegion"] if address.get(k)) + (", " + str(country) if country else ""))
    eligible = j.get("applicantLocationRequirements", [])
    for loc in eligible if isinstance(eligible, list) else [eligible]:
        if isinstance(loc, dict) and loc.get("name"):
            countries.append(loc["name"])
    return "; ".join(x.strip(", ") for x in locations if x.strip(", ")), list(dict.fromkeys(countries))

def from_schema(c, j, url):
    location, countries = schema_location(j)
    identifier = j.get("identifier", {})
    if isinstance(identifier, list): identifier = identifier[0] if identifier else {}
    sid = identifier.get("value", "") if isinstance(identifier, dict) else str(identifier)
    workplace = "remote" if "TELECOMMUTE" in str(j.get("jobLocationType", "")).upper() else "unknown"
    posted = j.get("datePosted")
    return Job(c["id"], c["name"], html_std.unescape(str(j.get("title", ""))), urljoin(url, j.get("url") or url), str(sid or ""), location, countries,
               workplace, plain(j.get("description", "")), str(posted) if posted else None,
               "original_posted" if parse_date(posted) else "unknown", "JobPosting.datePosted" if posted else "", valid_through=j.get("validThrough"), detail_ok=bool(j.get("description")),
               evidence=[url], salary=j.get("baseSalary") or {})

def enrich_job(job, body, url, body_xpath=None):
    schemas = jsonld_nodes(body)
    if schemas:
        # On a detail page, prefer title/identifier match instead of first unrelated card.
        node = next((x for x in schemas if len(norm(x.get("title", "")).split()) >= 2 and (norm(x.get("title", "")) == norm(job.title) or norm(x.get("title", "")) in norm(job.title) or norm(job.title) in norm(x.get("title", "")))), None)
        if node:
            parsed = from_schema({"id":job.company_id,"name":job.company}, node, url)
            if parsed.title: job.title = parsed.title
            if parsed.description: job.description = parsed.description
            if parsed.location: job.location = parsed.location
            if parsed.countries: job.countries = parsed.countries
            if parsed.workplace != "unknown": job.workplace = parsed.workplace
            if parsed.valid_through: job.valid_through = parsed.valid_through
            if parsed.salary: job.salary = parsed.salary
            if not job.source_id and parsed.source_id: job.source_id = parsed.source_id
            job.detail_ok = bool(job.description)
    d = document(body)
    scopes=d.xpath('//*[@itemscope and contains(@itemtype,"JobPosting")]')
    micro_root=scopes[0] if len(scopes) == 1 else None
    def micro(prop):
        nodes = micro_root.xpath('.//*[@itemprop="'+prop+'"]') if micro_root is not None else []
        return (nodes[0].get('content') or nodes[0].get('datetime') or nodes[0].text_content()).strip() if nodes else ''
    # Namecheap renders its current posting as escaped JSON on a Vue component.
    components=d.xpath('//job-details-component')
    if components:
        try:
            x=json.loads(components[0].get(':job','{}'))
            if x.get('description'):
                job.description=plain(x['description']);job.detail_ok=len(job.description)>60
            if x.get('title'):job.title=x['title']
            if x.get('country'):job.location=str(x['country']);job.countries=[str(x['country'])]
            # created_at/updated_at are database timestamps, not original publication.
        except (ValueError,TypeError):pass
    desc_nodes=micro_root.xpath('.//*[@itemprop="description"]') if micro_root is not None else []
    if desc_nodes:
        job.description=plain(html.tostring(desc_nodes[0],encoding="unicode"));job.detail_ok=len(job.description)>60
        if micro('title'):job.title=micro('title')
        if micro('validThrough'):job.valid_through=micro('validThrough')
        loc=', '.join(filter(None,[micro('addressLocality'),micro('addressRegion'),micro('addressCountry')])) or micro('streetAddress')
        if loc:job.location=loc
        if micro('addressCountry'):job.countries=[micro('addressCountry')]
    if not job.description:
        d = document(body)
        nodes = d.xpath(body_xpath) if body_xpath else d.xpath("//main|//article|//*[contains(@class,'job-description')]|//*[contains(@class,'jobDescription')]|//*[contains(@class,'jobdescription')]")
        if nodes:
            job.description = plain(html.tostring(nodes[0], encoding="unicode"))
            job.detail_ok = len(job.description) > 100
    if url not in job.evidence: job.evidence.append(url)
    from .posting_dates import enrich_dates
    enrich_dates(job, body, url)
    return job
