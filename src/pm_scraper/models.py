from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

def utcnow():
    return datetime.now(timezone.utc)

def parse_date(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / (1000 if value > 10**11 else 1), timezone.utc)
        except (ValueError, OverflowError, OSError):
            return None
    try:
        d = datetime.fromisoformat(str(value).strip().replace(" UTC", "+00:00").replace("Z", "+00:00"))
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)
    except ValueError:
        for fmt in ("%a %b %d %H:%M:%S UTC %Y", "%b %d, %Y", "%B %d, %Y", "%d %B %Y", "%m/%d/%y"):
            try: return datetime.strptime(str(value).strip(), fmt).replace(tzinfo=timezone.utc)
            except ValueError: pass
        return None

def canonical_url(url):
    p = urlsplit(url.replace("\\u0026", "&"))
    ignored = {"gh_src", "source", "ref", "referral", "trk", "lever-source", "lever-origin", "embed"}
    pairs = [(k, v) for k, v in parse_qsl(p.query) if k.lower() not in ignored and not k.lower().startswith("utm_")]
    # Retain gh_jid and other meaningful requisition query parameters.
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", urlencode(sorted(set(pairs))), ""))

@dataclass
class Job:
    company_id: str
    company: str
    title: str
    url: str
    source_id: str = ""
    location: str = ""
    countries: list[str] = field(default_factory=list)
    workplace: str = "unknown"
    description: str = ""
    posted_at: str | None = None
    date_kind: str = "unknown"
    date_evidence: str = ""
    updated_at: str | None = None
    valid_through: str | None = None
    detail_ok: bool = False
    evidence: list[str] = field(default_factory=list)
    salary: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    @property
    def key(self):
        identity = self.source_id or canonical_url(self.url)
        return self.company_id + ":" + sha256(identity.encode()).hexdigest()[:24]

    def to_dict(self):
        result = asdict(self)
        result["key"] = self.key
        return result

@dataclass
class Assessment:
    status: str  # eligible, review, rejected
    family: str | None
    reasons: list[str]
    checks: dict
    score: int = 0

@dataclass
class FetchResult:
    company_id: str
    company: str
    adapter: str
    status: str = "ok"
    jobs: list[Job] = field(default_factory=list)
    discovered: int = 0
    pages: int = 0
    complete: bool = True
    messages: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0

    def summary(self):
        return {k: v for k, v in asdict(self).items() if k != "jobs"} | {"candidates": len(self.jobs)}
