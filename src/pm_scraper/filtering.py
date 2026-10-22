"""Conservative screening. Every decision retains its evidence or uncertainty."""
import re
from datetime import timedelta
from .htmlutil import norm
from .models import Assessment, parse_date, utcnow
from .criteria import LANGUAGES, validate, experience_ceiling
from .residence import incompatible_residence
from .posting_dates import publication_candidate

NUMBERS = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,"ten":10,"um":1,"uma":1,"dois":2,"duas":2,"tres":3,"quatro":4,"cinco":5,"seis":6,"sete":7,"oito":8,"nove":9,"dez":10}
N = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez)"

def number(s):
    return int(s) if s.isdigit() else NUMBERS.get(s, 999)

def tokens(s):
    return re.findall(r"[a-z0-9]+", norm(s).replace("programme", "program"))

def subsequence(needle, haystack):
    it = iter(haystack)
    return all(any(word == target for word in it) for target in needle)

class Screener:
    def __init__(self, cfg):
        self.cfg = cfg = validate(cfg)
        pairs = [(x, x) for x in cfg["role_families"]] + [(title, family) for title, family in cfg['portuguese_titles'].items() if family in cfg['role_families']]
        self.titles = sorted([(tokens(x), family) for x, family in pairs], key=lambda x: len(x[0]), reverse=True)

    def family(self, title):
        t = norm(title)
        if re.search(r"\b(head|director|diretor|directora|diretora|vice president|vp|svp|evp|chief|ceo|cto|cio|coo|cfo|president|presidente|managing partner|general manager)\b", t):
            return None
        words = tokens(t)
        for base, family in self.titles:
            if subsequence(base, words):
                return family
        return None

    @staticmethod
    def sentences(text):
        return [s.strip() for s in re.split(r"[\n;]|(?<=[.!?])\s+", norm(text).replace(" • ", "\n")) if s.strip()]

    def assess(self, job, now=None, override=None):
        now = now or utcnow()
        family = self.family(job.title)
        checks, rejected, pending, notes = {}, [], [], []
        def check(key, status, evidence):
            checks[key] = {"status":status, "evidence":evidence}
            if status == "fail": rejected.append(key + ": " + evidence)
            elif status == "unknown": pending.append(key + ": " + evidence)
        check("title", "pass" if family else "fail", family or "Not an allowed title family, or excluded seniority")
        company_norm = norm(job.company)
        excluded = [x for x in self.cfg["excluded_companies"] if re.search(r"\b" + re.escape(norm(x)) + r"\b", company_norm)]
        check("employer", "fail" if excluded else "pass", ", ".join(excluded) if excluded else "Named employer in the configured watchlist")
        questions = job.metadata.get('application_questions', [])
        residence_text = job.description + '\n' + '\n'.join(q['label'] + '\n' + q.get('description', '') for q in questions)
        residence_failures = incompatible_residence(residence_text, self.cfg['allowed_residence_locations'])
        check('residence', 'fail' if residence_failures else 'pass',
              '; '.join(residence_failures) or 'No explicit residence requirement outside the permitted Porto/Braga area found')
        if job.metadata.get('application_requirements_checked') is False:
            check('application_requirements', 'unknown', 'Application requirements could not be checked; withheld from reporting')
        if not job.detail_ok or len(job.description) < 60:
            check("description", "unknown", "Full job description was not retrieved")
        else:
            check("description", "pass", "Job detail retrieved")

        text = norm(job.description)
        title = norm(job.title)
        # Preserve individual clauses so a nice-to-have elsewhere does not negate a requirement.
        sentences = [norm(x) for x in re.split(r"[\n;]|(?<=[.!?])\s+", job.description) if x.strip()]
        coding = []
        coding_pattern = re.compile(r"\b(?:write|writing|implement|implementing|develop|developing|produce|producing|contribute|contributing)\b.{0,65}\b(?:code|scripts?|software features|applications|algorithms)\b|\b(?:hands[- ]on (?:software )?(?:development|coding|programming)|coding (?:test|challenge|assessment|exercise)|programming (?:test|exercise)|escrever codigo|programacao obrigatoria)\b")
        for sentence in sentences:
            if not coding_pattern.search(sentence): continue
            if re.search(r"\b(no|not|without|never|nao|sem)\b.{0,35}\b(cod|program|writ|escrever)", sentence): continue
            if re.search(r"nice[- ]to[- ]have|optional|not required|nao obrigatori|opcional", sentence): continue
            if re.search(r"\b(engineers|developers|team members|equipa)\b.{0,20}(?:who |that )?(?:write|writing|develop|developing|implement)", sentence) and not re.search(r"\byou (?:will|must|are expected to)\b.{0,30}(?:write|develop|implement)", sentence):
                continue
            coding.append(sentence[:350])
        check("code_writing", "fail" if coding else "pass" if job.detail_ok else "unknown", "; ".join(coding) or "No mandatory code-writing requirement found; code review is allowed")
        if not self.cfg['exclude_mandatory_coding']:
            checks['code_writing'] = {'status': 'informational', 'evidence': '; '.join(coding) or 'Code-writing requirements are not an exclusion in saved criteria'}

        language_fail = []
        other_languages = '|'.join(re.escape(alias) for name, aliases in LANGUAGES.items() if name not in self.cfg['allowed_languages'] for alias in aliases)
        for sentence in [title] + sentences:
            if not other_languages or not re.search(r"\b(?:" + other_languages + r")\b", sentence): continue
            if re.search(r"nice[- ]to[- ]have|optional|bonus|plus|advantage|not required|desirable|prefer(?:red|able)|valorizad|opcional|nao obrigatori", sentence): continue
            if re.search(r"fluent|fluency|native|proficien|mandatory|required|must|c1|c2|b2|speaking|speaker|fluente|obrigatori|dominio", sentence):
                language_fail.append(sentence[:350])
        check("languages", "fail" if language_fail else "pass" if job.detail_ok else "unknown", "; ".join(language_fail) or 'No recognized mandatory language outside: ' + ', '.join(self.cfg['allowed_languages']))

        schedule_flags = []
        for sentence in sentences:
            if re.search(r"no (?:on.call|shift|weekend)|not required|without on.call|sem turnos", sentence): continue
            if re.search(r"(?:participate|join|required|must|rotat|24/7|regular).{0,45}(?:on.call|shift|weekend)|(?:on.call|shift|weekend).{0,45}(?:rotation|required|24/7)|trabalho por turnos", sentence):
                schedule_flags.append(sentence[:350])
        check("work_schedule", "fail" if schedule_flags else "pass" if job.detail_ok else "unknown", "; ".join(schedule_flags) or "No required shift/on-call pattern identified; actual workload still merits interview checks")
        if not self.cfg['exclude_shift_on_call']:
            checks['work_schedule'] = {'status': 'informational', 'evidence': '; '.join(schedule_flags) or 'Shift/on-call requirements are not an exclusion in saved criteria'}

        loc = norm(job.location)
        country = [norm(c) for c in job.countries]
        pt = any(x in {"pt", "prt", "portugal"} for x in country) or bool(re.search(r"\bportugal\b", loc))
        near = any(re.search(r"\b" + re.escape(norm(x)) + r"\b", loc) for x in self.cfg["nearby_locations"])
        if near: pt = True
        remote = job.workplace.lower() in {"remote", "fully remote", "telecommute"} or bool(re.search(r"remote|remoto|teletrabalho", loc))
        # Use explicit eligibility, not a passing mention of a Portuguese office.
        if re.search(r"(?:remote|work|based|resid\w*|located).{0,45}(?:anywhere in portugal|within portugal|from portugal)|portugal.{0,25}(?:remote|remoto)|100% remote|fully remote", text):
            remote = True
        if re.search(r"(?:based|resid\w*|work|remote|located).{0,35}(?:in|from|within) portugal|portugal.{0,20}(?:eligible|remote|remoto)", text):
            pt = True
        worldwide = bool(re.search(r"worldwide|anywhere in the world|work from anywhere|globally remote", loc + " " + text))
        excludes_pt = bool(re.search(r"(?:except|excluding|not (?:in|from)|cannot (?:hire|employ).{0,12})\s*portugal", text))
        if excludes_pt:
            check("portugal_eligibility", "fail", "Portugal explicitly excluded")
        elif pt:
            check("portugal_eligibility", "pass", job.location or ", ".join(job.countries))
        elif country and not worldwide:
            check("portugal_eligibility", "fail", "Eligible countries/location do not include Portugal: " + ", ".join(job.countries))
        elif worldwide and remote:
            check("portugal_eligibility", "unknown", "Worldwide wording; Portuguese employment eligibility still needs confirmation")
        else:
            check("portugal_eligibility", "unknown", "Portugal eligibility not explicit in this posting")

        office_values, office_evidence = [], []
        for sentence in sentences:
            if re.search(r"office|on.site|onsite|escritorio|presencial", sentence):
                patterns = [rf"({N})(?:\s*(?:to|a|-|–)\s*({N}))?\s*(?:days?|dias?).{{0,50}}(?:per|a|each|por|/|every)\s*(?:week|semana)", rf"(?:office|on.site|onsite).{{0,30}}({N})\s*(?:days?|dias?)\s*(?:a|per|each|por|/)\s*(?:week|semana)"]
                for pattern in patterns:
                    m = re.search(pattern, sentence)
                    if m:
                        vals = [number(x) for x in m.groups() if x]
                        office_values.append(max(vals)); office_evidence.append(sentence[:300]); break
        distant_frequent = any(re.search(r"office|on.site|onsite|presencial|escritorio", s) and re.search(r"weekly|monthly|every month|once a month|twice a month|mensal|semanal", s) for s in sentences)
        quarterly_office_counts=[]
        for sentence in sentences:
            if re.search(r"office|on.site|onsite|presencial|escritorio",sentence):
                m=re.search(rf"({N})\s*(?:visits?|times?|vezes).{{0,20}}(?:per|each|a|por)\s*(?:quarter|trimestre)",sentence)
                if m:quarterly_office_counts.append(number(m.group(1)))
                if re.search(r"twice (?:a |per )?quarter|twice quarterly",sentence):quarterly_office_counts.append(2)
        rare_office = any(re.search(r"office|visit|gathering|meetup|offsite|encontro", s) and re.search(r"at most quarterly|no more than.{0,12}quarter|once (?:a|per|every) quarter|once every (?:three|3) months|quarterly|trimestral", s) for s in sentences)
        if rare_office and not quarterly_office_counts:
            quarterly_office_counts.append(1)
        distant_limit = self.cfg['max_distant_office_visits_per_quarter']
        no_office = remote and (pt or worldwide) and not re.search(r"hybrid|hibrido|\b(?:office attendance|mandatory office|regular office)\b", text + " " + loc)
        onsite = norm(job.workplace).replace('_', ' ') in {'onsite', 'on-site', 'on site', 'presencial', 'in person', 'in-person'}
        model_label = re.sub(r'\b(?:not|no|sem|nao)\s+(?:on[ -]?site|presencial)\b', '', loc + ' ' + title)
        onsite = onsite or (bool(re.search(r'\bon[ -]?site\b|\bpresencial\b', model_label)) and not re.search(r'\bhybrid\b|\bhibrid[oa]\b', model_label))
        for sentence in sentences:
            if re.search(r'\b(?:not|no|sem|nao)\b.{0,15}(?:on[ -]?site|presencial)', sentence):
                continue
            if re.search(r'\b(?:this|the)\s+(?:role|position|job)\s+(?:is|will be)\s+(?:(?:fully|strictly|entirely|100%)\s+)?on[ -]?site\b|\b(?:fully|strictly|entirely|100%)\s+on[ -]?site\b|\b(?:an?|the)\s+on[ -]?site\s+(?:role|position|job)\b|\b(?:work(?:ing)? (?:model|arrangement)|location type)\s*:\s*(?:on[ -]?site|presencial)\b|\b(?:(?:regime|modelo)(?: de trabalho)?|modalidade|trabalho|funcao|vaga|posicao)\s*:?\s+(?:100%\s+)?presencial\b', sentence):
                onsite = True
        if onsite:
            check('attendance', 'fail', 'Explicit on-site/presencial role; only remote or compatible hybrid roles are permitted')
        elif office_values and max(office_values) > self.cfg["max_office_days_per_week"]:
            check("attendance", "fail", "; ".join(office_evidence))
        elif office_values and near:
            check("attendance", "pass", "; ".join(office_evidence))
        elif not near and (distant_frequent or (office_values and max(office_values) > 0) or (quarterly_office_counts and max(quarterly_office_counts)>distant_limit)):
            check("attendance", "fail", f"Distant-office attendance exceeds the configured {distant_limit} visits/quarter cap or requires a routine weekly/monthly pattern")
        elif remote and quarterly_office_counts:
            check("attendance", "pass", f"Remote arrangement within {distant_limit} office visits/quarter; travel duration checked separately")
        elif no_office:
            check("attendance", "pass", "Explicit remote arrangement; no routine office requirement identified")
        else:
            check("attendance", "unknown", "Exact office frequency is not published" + ("; North Portugal location" if near else ""))

        travel_sentences = [s for s in sentences if re.search(r"travel|travelling|traveling|offsite|off.site|retreat|meetup|viagen|deslocac", s)]
        travel_fail, travel_pass = [], []
        for sentence in travel_sentences:
            # A vacation/workation benefit does not describe required business travel.
            if re.search(r"work from abroad|workation|vacation|paid time off|holiday|volunteer", sentence) and not re.search(r"required|mandatory|business travel", sentence): continue
            if re.search(r"no (?:business |international )?travel(?: is)? required|travel(?: requirement)?:?\s*(?:none|0\s*%)|no travel|sem viagens", sentence):
                if re.search(r"except|unless|mandatory.{0,25}(?:retreat|offsite|trip)|(?:retreat|offsite).{0,25}(?:required|mandatory)", sentence): continue
                travel_pass.append(sentence[:350]); continue
            if re.search(r"frequent|extensive|regular travel|weekly travel|travel weekly|travel every month|viagens frequentes", sentence):
                travel_fail.append(sentence[:350]); continue
            percentages = [int(x) for x in re.findall(r"(\d+)\s*%", sentence)]
            if percentages and max(percentages) >= 10:
                travel_fail.append(sentence[:350]); continue
            m = re.search(rf"({N})\s*(?:calendar\s+)?(days?|weeks?|dias?|semanas?).{{0,25}}(?:per|a|each|por|every|/)\s*(quarter|trimester|trimestre)", sentence)
            if m:
                days = number(m.group(1)) * (7 if m.group(2).startswith(("week", "semana")) else 1)
                if days > self.cfg["max_abroad_calendar_days_per_quarter"]:
                    travel_fail.append(sentence[:350])
                elif re.search(r"(?:maximum|max\b|up to|no more than|at most|ate|no maximo)", sentence) and re.search(r"including (?:travel|transit)|calendar|calendario|porta.a.porta", sentence):
                    travel_pass.append(sentence[:350])
        if travel_fail:
            check("travel", "fail", "; ".join(travel_fail))
        elif travel_pass and (len(travel_pass) == len(travel_sentences) or not any(re.search(r"required|mandatory|must|expect|attend", s) for s in travel_sentences if s[:350] not in travel_pass)):
            check("travel", "pass", "; ".join(travel_pass))
        else:
            check("travel", "unknown", f"At most {self.cfg['max_abroad_calendar_days_per_quarter']} calendar days abroad per quarter, including all trips and transit, is not explicitly established" + (": " + "; ".join(travel_sentences)[:550] if travel_sentences else ""))

        accept_employer_dates = self.cfg.get('accept_employer_dates', False)
        publication = publication_candidate(job, accept_employer_dates)
        date_value = publication['value'] if publication else job.posted_at
        posted = parse_date(date_value)
        freshness_category = 'original_date_unverified'
        first_seen = parse_date(job.metadata.get('first_seen'))
        if not (accept_employer_dates and publication) and first_seen and now - first_seen > timedelta(days=self.cfg['max_post_age_days']):
            freshness_category = 'older_than_window'
            check('freshness', 'fail', 'This same posting was already observed before the freshness window; original publication date remains unverified')
        elif posted and posted > now:
            freshness_category = 'future_date'
            check("freshness", "unknown", "Posting date is in the future: " + str(date_value))
        elif posted and publication:
            window = timedelta(days=self.cfg["max_post_age_days"])
            age = now - posted
            # A date without a clock denotes an interval, not invented midnight
            # precision. Under employer-declared policy an active posting bounds
            # today's date by the current observation; old-edge overlaps stay unknown.
            raw = str(date_value).strip()
            date_only = not isinstance(date_value, (int, float)) and not re.search(r"\d{1,2}:\d{2}", raw)
            if age > window and (not date_only or posted + timedelta(days=1) <= now - window):
                freshness_category = 'older_than_window'
                check("freshness", "fail", f"Posting date is older than {self.cfg['max_post_age_days']*24} hours; source: {publication['source']}")
            elif date_only and ((posted + timedelta(days=1) > now and not accept_employer_dates) or age > window):
                freshness_category = 'date_only_uncertain'
                check("freshness", "unknown", "Date-only original publication does not establish the full freshness interval")
            else:
                freshness_category = 'verified_recent'
                basis = 'Employer-declared posting/repost' if accept_employer_dates else 'Original posting'
                check("freshness", "pass", f"{basis} date {date_value}; source: {publication['source']}")
        else:
            check("freshness", "unknown", 'Usable employer publication date unavailable; modification and first-seen dates do not prove freshness' if accept_employer_dates else "Original posting date unverified; updated/last-published/first-seen dates are not treated as new")
        checks['freshness']['category'] = freshness_category
        if publication:
            checks['freshness'].update(date=date_value, source=publication['source'], basis='employer_declared' if accept_employer_dates else 'original')
        expires = parse_date(job.valid_through)
        check("active", "fail" if expires and expires < now else "pass", "Posting deadline expired" if expires and expires < now else "Present in current public board; no expired deadline found")

        # Salary is retained on Job for optional display, never for screening.
        checks["salary"] = {"status":"informational", "evidence":"Salary has no eligibility or ranking requirement"}

        experience_fail, experience_unknown, experience_optional = [], [], []
        experience_limit = experience_ceiling(self.cfg, now)
        pattern = re.compile(rf"(?P<low>{N})(?:\s*[-–—]\s*(?:{N}))?\s*\+?\s*(?:years?|anos?)\b.{{0,65}}(?:experience|experiencia|leadership|management|professional|lideranca|gestao)|(?:experience|experiencia).{{0,35}}?(?P<after>{N})(?:\s*[-–—]\s*(?:{N}))?\s*\+?\s*(?:years?|anos?)\b")
        # Split optional and mandatory clauses independently: a preference must
        # never cancel a distinct mandatory minimum in the same sentence.
        clauses = [norm(x) for x in re.split(r"[\n;]|(?<=[.!?])\s+|,\s*|\bbut\b|\band\b(?=\s+(?:(?:at least|minimum|ideally|preferably)\s+)?(?:\d|six|seven|eight|nine|ten))", job.description) if x.strip()]
        for clause in clauses:
            matches = list(pattern.finditer(clause))
            high = [m for m in matches if number(m.group("low") or m.group("after")) > experience_limit]
            if not high:
                continue
            optional = re.search(r"preferred|preferable|nice[- ]to[- ]have|optional|bonus|desirable|ideally|opcional|preferencial|valorizad", clause)
            mandatory = re.search(r"required|mandatory|must|minimum|at least|obrigatori|minimo|\d\s*\+", clause)
            if mandatory and not optional:
                experience_fail.append(clause[:500])
            elif optional:
                experience_optional.append(clause[:500])
            else:
                experience_unknown.append(clause[:500])
        check("experience", "fail" if experience_fail else "unknown" if experience_unknown else "pass" if job.detail_ok else "unknown",
              "; ".join(experience_fail + experience_unknown + experience_optional) or f"No mandatory experience minimum above {experience_limit} years identified")
        checks['experience']['limit_years'] = experience_limit
        checks["work_life_balance"] = {"status":"unverified", "evidence":"Employer-level reputation is contextual; actual workload, overtime and leave use require team-level confirmation"}

        # Overrides require dated evidence and can only resolve explicitly named checks.
        if override:
            verified = parse_date(override.get("verified_at"))
            if verified and timedelta(0) <= now - verified < timedelta(days=90) and override.get("evidence"):
                for key, val in override.get("checks", {}).items():
                    if key == 'attendance' and val == 'pass' and onsite:
                        continue
                    if key in {"travel", "attendance", "portugal_eligibility", "code_writing", "work_schedule"} and val in {"pass", "fail"}:
                        checks[key] = {"status":val, "evidence":"Verified override: " + override["evidence"]}
                rejected = [k + ": " + v["evidence"] for k, v in checks.items() if v["status"] == "fail"]
                pending = [k + ": " + v["evidence"] for k, v in checks.items() if v["status"] == "unknown"]
        rejected = [k + ': ' + v['evidence'] for k, v in checks.items() if v['status'] == 'fail']
        pending = [k + ': ' + v['evidence'] for k, v in checks.items() if v['status'] == 'unknown']
        status = "rejected" if rejected else "review" if pending else "eligible"
        score = 60 + (20 if remote else 10 if near else 0) + (10 if checks["travel"]["status"] == "pass" else 0) + (10 if checks["freshness"]["status"] == "pass" else 0)
        return Assessment(status, family, rejected + pending, checks, score)
