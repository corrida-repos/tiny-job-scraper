"""Prepare a complete per-run email; delivery remains an external operation."""
import re
from zoneinfo import ZoneInfo
from .htmlutil import norm
from .models import parse_date
from .branding import company_heading
from .posting_dates import report_date

SUBJECT = "Tiny's Daily Job Report"


def location_tier(job):
    location = norm(job.location)
    if re.search(r"\bbraga\b", location):
        return 0
    if re.search(r"\b(?:porto|oporto)\b", location):
        return 1
    countries = {c.upper() for c in job.countries}
    if 'portugal' in location or countries & {'PT', 'PRT'}:
        return 2
    if countries & {'DK', 'FI', 'IS', 'NO', 'SE'} or re.search(r"\b(?:denmark|finland|iceland|norway|sweden)\b", location):
        return 3
    if countries & {'AT','BE','BG','HR','CY','CZ','EE','FR','DE','GR','HU','IE','IT','LV','LT','LU','MT','NL','PL','RO','SK','SI','ES'} or re.search(r"\b(?:european union|eu|germany|france|spain|netherlands|ireland|italy|austria|belgium|poland)\b", location):
        return 4
    return 5


def unknown_freshness(assessment):
    check = assessment.checks.get('freshness', {})
    return check.get('status') == 'unknown' and check.get('category') in {'original_date_unverified', 'date_only_uncertain'}


def future_dated(assessment):
    check = assessment.checks.get('freshness', {})
    return check.get('status') == 'unknown' and check.get('category') == 'future_date'


def duplicate_description(description):
    """Ignore only standalone monetary ranges, never duties/experience numbers."""
    amount = r'[€£$]\s*\d[\d.,]*(?:\s*[–—-]\s*[€£$]?\s*\d[\d.,]*)?'
    monetary_line = amount + r'(?:\s*(?:EUR|USD|GBP|CAD|AUD))?(?:\s*(?:per year|annually|/year|/yr))?'
    return norm('\n'.join(line for line in description.splitlines()
                          if not re.fullmatch(monetary_line, line.strip(), flags=re.I)))


def select_roles(pairs, include_potential_matches=True, include_unknown_freshness=False, include_future_dated=False, require_portugal_eligibility=False):
    groups = {}
    for job, assessment in pairs:
        if any(assessment.checks.get(key, {}).get('status') != 'pass' for key in ('title', 'employer')):
            continue
        if any(check.get('status') == 'fail' for check in assessment.checks.values()):
            continue
        if not include_potential_matches and job.metadata.get('application_requirements_checked') is False:
            continue
        if require_portugal_eligibility and assessment.checks.get('portugal_eligibility', {}).get('status') != 'pass':
            continue
        allowed = {'eligible', 'review'} if include_potential_matches else {'eligible'}
        freshness_ok = assessment.checks.get('freshness', {}).get('status') == 'pass'
        if assessment.status not in allowed or not (freshness_ok
                or (include_unknown_freshness and unknown_freshness(assessment))
                or (include_future_dated and future_dated(assessment))):
            continue
        # Country editions can lack an explicit remote label and carry local
        # salary bands. Merge identical duties, preserving the chosen edition's
        # salary and requirements; never merge by title or fuzzy similarity alone.
        description = duplicate_description(job.description)
        remote = norm(job.workplace) in {'remote', 'fully remote', 'telecommute'}
        questions = tuple(sorted((norm(q.get('label','')), norm(q.get('description','')), bool(q.get('required')))
                                 for q in job.metadata.get('application_questions', [])))
        key = (job.company_id, norm(job.title), description, norm(job.workplace),
               assessment.checks.get('freshness', {}).get('category'), questions,
               tuple(sorted((k, v['status']) for k, v in assessment.checks.items() if k != 'portugal_eligibility'))) if len(description) >= 200 or (remote and description) else (job.key,)
        groups.setdefault(key, []).append((job, assessment))
    chosen = []
    alternatives = {}
    for variants in groups.values():
        variants.sort(key=lambda pair: (location_tier(pair[0]), pair[0].url))
        editions = []
        for pair in variants:
            job, _ = pair
            remote = norm(job.workplace) in {'remote', 'fully remote', 'telecommute'}
            cluster = next((group for group in editions if
                            (norm(job.location) and all(norm(j.location) != norm(job.location) for j, _ in group)) or
                            (remote and all(norm(j.description) == norm(job.description) and j.salary == job.salary for j, _ in group))), None)
            if cluster is None:
                editions.append([pair])
            else:
                cluster.append(pair)
        for cluster in editions:
            job, assessment = cluster[0]
            chosen.append((job, assessment))
            alternatives[job.key] = sorted({j.url for j, _ in cluster[1:] if j.url != job.url})
    def order(pair):
        job, assessment = pair
        unknown = sum(v['status'] == 'unknown' for v in assessment.checks.values())
        important = sum(assessment.checks.get(k, {}).get('status') != 'pass' for k in ('work_schedule', 'portugal_eligibility', 'attendance', 'travel', 'experience'))
        freshness = assessment.checks.get('freshness', {})
        posted = parse_date(freshness.get('date', job.posted_at)) if freshness.get('status') == 'pass' else None
        return (job.metadata.get('employer_rank', 999), assessment.status != 'eligible', important, unknown,
                -(posted.timestamp() if posted else 0), norm(job.title), job.url)
    return sorted(chosen, key=order), alternatives


def clean(value):
    # Postings are untrusted data, including Markdown metacharacters.
    text = re.sub(r'[\[\]*`<>]', '', ' '.join(str(value if value is not None else '').split()))
    text = re.sub(r'([,;])(?:\s*[,;])+', r'\1', text)
    text = re.sub(r'\s+([,;])', r'\1', text)
    return text.strip(' ,;')


def fragments(values):
    parts = [clean(value).strip(' .,;') for value in values]
    return clean('; '.join(part for part in parts if part))


def display_title(value):
    marker = r'(?:m|f|w|d|x|div\.?|diverse|non[- ]binary|all genders|any gender)'
    text = re.sub(r'\s*\(\s*'+marker+r'(?:\s*[/|,\-]\s*'+marker+r')*\s*\)', '', str(value), flags=re.I)
    return clean(text)


def link(url):
    return str(url).replace('(', '%28').replace(')', '%29').replace(' ', '%20').replace('\n', '').replace('\r', '')


def salary_positive(job):
    salary = job.salary or {}
    value = salary.get('value', {}) if isinstance(salary, dict) else {}
    if salary.get('currency') != 'EUR' or not isinstance(value, dict) or str(value.get('unitText', '')).upper() not in {'YEAR', 'ANNUAL'}:
        return ''
    try:
        low = float(value.get('minValue', value.get('value', value.get('maxValue'))))
        high = float(value.get('maxValue', value.get('value', low)))
    except (ValueError, TypeError):
        return ''
    # JSON-LD alone does not establish gross versus net pay.
    if high < 45000 or not re.search(r'\bgross\b|\bbrut[oa]\b', norm(job.description)):
        return ''
    if low != high:
        return f'advertised gross annual range €{low:,.0f}–€{high:,.0f}' + (f', up to €{high:,.0f}' if low < 45000 else '')
    return f'advertised gross annual salary €{high:,.0f}'


def prepare_email(pairs, payload, saving='Local report generated; durable saving and email delivery not confirmed'):
    criteria = payload.get('criteria', {})
    allow_unknown = criteria.get('include_unknown_freshness', False)
    allow_future = criteria.get('include_future_dated', False)
    selected, alternatives = select_roles(pairs, criteria.get('include_potential_matches', True), allow_unknown, allow_future, criteria.get('require_portugal_eligibility', False))
    freshness_groups = {'Verified Freshness': {}, 'Unknown Freshness': {}}
    for pair in selected:
        category = 'Verified Freshness' if pair[1].checks['freshness']['status'] == 'pass' else 'Unknown Freshness'
        freshness_groups[category].setdefault(pair[0].company_id, []).append(pair)
    selected = [pair for companies in freshness_groups.values() for jobs in companies.values() for pair in jobs]
    freshness_hours = payload.get('freshness_hours', 48)
    lines = []
    current_freshness = None
    current_company = None
    for job, assessment in selected:
        category = 'Verified Freshness' if assessment.checks['freshness']['status'] == 'pass' else 'Unknown Freshness'
        if category != current_freshness:
            if lines:
                lines += ['---', '']
            current_freshness = category
            current_company = None
            lines += [f'# {category}', '']
        if job.company_id != current_company:
            if current_company is not None:
                lines += ['---', '']
            current_company = job.company_id
            lines += [company_heading(job.company_id, clean(job.company)),
                      f'[Company careers]({link(job.metadata.get("careers_url", job.url))})', '']
        pros = [assessment.family or 'Allowed role family']
        for key in ('portugal_eligibility', 'attendance', 'travel'):
            check = assessment.checks.get(key, {})
            if check.get('status') == 'pass':
                pros.append(clean(check['evidence']).rstrip('.'))
        salary = salary_positive(job)
        if salary:
            pros.append(salary)
        concerns = [clean(v['evidence']).rstrip('.') for v in assessment.checks.values() if v['status'] == 'unknown']
        experience = assessment.checks.get('experience', {}).get('evidence', '')
        if re.search(r'prefer|ideally|optional|nice.to.have', experience):
            concerns.append(clean(experience).rstrip('.'))
        cons = ('Potential match; requirements unconfirmed: ' if assessment.status == 'review' else '') + (fragments(concerns) or 'No material concerns identified in retrieved evidence; suitability still requires confirmation')
        lines += [f'### **{display_title(job.title)}**',
                  f'[View job]({link(job.url)})',
                  f'- **Pros:** {fragments(pros)}.', f'- **Cons:** {clean(cons).rstrip(".")}.', '']
        date_line = report_date(job, assessment.checks.get('freshness'))
        if date_line:
            lines[-1:-1] = ['- **Date evidence:** ' + clean(date_line)]
    coverage = payload['coverage']
    if not selected:
        if allow_unknown or allow_future:
            lines = [('Retrieval failed or was incomplete; no roles passing the saved reporting criteria were found.' if coverage['attention'] else 'No roles passed the saved reporting criteria.'), '']
        else:
            lines = [('Retrieval failed or was incomplete; no qualifying fresh roles were verified in the retrieved results.' if coverage['attention'] else f'No roles passed the verified {freshness_hours}-hour freshness gate and other hard filters.'), '']
    timestamp = parse_date(payload['started_at'])
    marker = 'tiny-' + timestamp.strftime('%Y%m%dT%H%M%S.%fZ')
    failures = []
    for source in payload['sources']:
        if not source['complete'] or source['status'] != 'ok':
            messages = fragments(source['messages'])
            failures.append(clean(source['company'])+': '+clean(source['status'])+(' — '+messages if messages else ''))
    freshness_note = f'Verified original publication within {freshness_hours} hours of run start; known older original dates excluded'
    if criteria.get('accept_employer_dates', False):
        freshness_note = f'Employer-declared posting/repost date within {freshness_hours} hours; known older publication dates excluded; modification dates do not qualify'
    freshness_note += '; unresolved publication dates included as Unknown freshness' if allow_unknown else '; unresolved publication dates excluded'
    freshness_note += '; future dates also included as Unknown freshness' if allow_future else '; future dates excluded'
    lines += ['# Run notes', '',
              f'- Checked: {timestamp.astimezone(ZoneInfo("Europe/Lisbon")).isoformat()}; {coverage["sources"]} configured source scopes.',
              f'- Coverage: {coverage["complete"]} complete; {coverage["attention"]} need attention.',
              f'- Results: {len(selected)} included; all current-run candidates retained in results.json.',
              '- Freshness: ' + freshness_note + '.',
              '- Filters: saved employer ranks and screening criteria; '
              + ('potential matches included' if criteria.get('include_potential_matches', True) else 'verified eligible roles only')
              + '; salary informational only.'
              + (' Active settings are recorded in results.json.' if criteria else ''),
              '- Coverage gaps: ' + ('; '.join(failures) or 'None in the selected scopes.'),
              '- Saving: ' + saving + '.', f'- Run marker: {marker}', '']
    return {'subject': SUBJECT, 'run_marker': marker, 'delivery_status': 'not_sent',
            'job_keys': [j.key for j, _ in selected], 'alternative_urls': alternatives,
            'unknown_freshness_job_keys': [j.key for j, a in selected if unknown_freshness(a) or future_dated(a)],
            'future_dated_job_keys': [j.key for j, a in selected if future_dated(a)],
            'body_markdown': '\n'.join(lines)}
