"""Prepare a complete per-run email; delivery remains an external operation."""
import re
from zoneinfo import ZoneInfo
from .htmlutil import norm
from .models import parse_date

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


def select_roles(pairs, include_potential_matches=True):
    groups = {}
    for job, assessment in pairs:
        if job.metadata.get('application_requirements_checked') is False:
            continue
        allowed = {'eligible', 'review'} if include_potential_matches else {'eligible'}
        if assessment.status not in allowed or assessment.checks.get('freshness', {}).get('status') != 'pass':
            continue
        # Merge only exact substantive descriptions and assessments for remote
        # location variants. Uncertain duplicates remain separate for inspection.
        remote = job.workplace.lower() in {'remote', 'fully remote', 'telecommute'}
        key = (job.company_id, norm(job.title), norm(job.description),
               str(job.salary), assessment.status,
               tuple(sorted((k, v['status']) for k, v in assessment.checks.items()))) if remote and job.description else (job.key,)
        groups.setdefault(key, []).append((job, assessment))
    chosen = []
    alternatives = {}
    for variants in groups.values():
        variants.sort(key=lambda pair: (location_tier(pair[0]), pair[0].url))
        job, assessment = variants[0]
        chosen.append((job, assessment))
        alternatives[job.key] = sorted({j.url for j, _ in variants[1:] if j.url != job.url})
    def order(pair):
        job, assessment = pair
        unknown = sum(v['status'] == 'unknown' for v in assessment.checks.values())
        important = sum(assessment.checks.get(k, {}).get('status') != 'pass' for k in ('work_schedule', 'portugal_eligibility', 'attendance', 'travel', 'experience'))
        posted = parse_date(job.posted_at)
        return (job.metadata.get('employer_rank', 999), assessment.status != 'eligible', important, unknown,
                -(posted.timestamp() if posted else 0), norm(job.title), job.url)
    return sorted(chosen, key=order), alternatives


def clean(value):
    # Postings are untrusted data, including Markdown metacharacters.
    return re.sub(r'[\[\]*`<>]', '', ' '.join(str(value).split()))


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
    selected, alternatives = select_roles(pairs, criteria.get('include_potential_matches', True))
    freshness_hours = payload.get('freshness_hours', 48)
    lines = []
    for index, (job, assessment) in enumerate(selected, 1):
        if lines:
            lines += ['---', '']
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
        cons = ('Potential match; requirements unconfirmed: ' if assessment.status == 'review' else '') + ('; '.join(concerns) or 'No material concerns identified in retrieved evidence; suitability still requires confirmation')
        lines += [f'{index}. {clean(job.company)} — {clean(job.title)}',
                  f'[View job]({link(job.url)}) · [Company careers]({link(job.metadata.get("careers_url", job.url))})',
                  f'- **Pros:** {"; ".join(pros)}.', f'- **Cons:** {cons}.', '']
    coverage = payload['coverage']
    if not selected:
        lines = [('Retrieval failed or was incomplete; no qualifying fresh roles were verified in the retrieved results.' if coverage['attention'] else f'No roles passed the verified {freshness_hours}-hour freshness gate and other hard filters.'), '']
    timestamp = parse_date(payload['started_at'])
    marker = 'tiny-' + timestamp.strftime('%Y%m%dT%H%M%S.%fZ')
    failures = ['{}: {}{}'.format(clean(s['company']), clean(s['status']), ' — ' + clean('; '.join(s['messages'])) if s['messages'] else '') for s in payload['sources'] if not s['complete'] or s['status'] != 'ok']
    lines += ['## Run notes', '',
              f'- Checked: {timestamp.astimezone(ZoneInfo("Europe/Lisbon")).isoformat()}; {coverage["sources"]} configured source scopes.',
              f'- Coverage: {coverage["complete"]} complete; {coverage["attention"]} need attention.',
              f'- Results: {len(selected)} included; all current-run candidates retained in results.json.',
              f'- Freshness: verified original publication within {freshness_hours} hours of run start; future and unverified dates excluded.',
              '- Filters: saved employer ranks and screening criteria; '
              + ('fresh potential matches included' if criteria.get('include_potential_matches', True) else 'verified eligible roles only')
              + '; salary informational only.'
              + (' Active settings are recorded in results.json.' if criteria else ''),
              '- Coverage gaps: ' + ('; '.join(failures) or 'None in the selected scopes.'),
              '- Saving: ' + saving + '.', f'- Run marker: {marker}', '']
    return {'subject': SUBJECT, 'run_marker': marker, 'delivery_status': 'not_sent',
            'job_keys': [j.key for j, _ in selected], 'alternative_urls': alternatives,
            'body_markdown': '\n'.join(lines)}
