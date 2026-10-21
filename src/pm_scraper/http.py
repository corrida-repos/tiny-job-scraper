"""Public, unauthenticated HTTP only. No browser impersonation or challenge bypass."""
import gzip
import json
import re
import threading
import time
import urllib.error
import urllib.request
import urllib.robotparser
from urllib.parse import urlsplit, urljoin, urlencode

USER_AGENT = "PMCareerMonitor/1.0 (personal vacancy monitor; public employer job listings)"

class FetchError(Exception):
    def __init__(self, message, kind="error"):
        super().__init__(message)
        self.kind = kind

class HttpClient:
    def __init__(self, timeout=25, delay=1.0, retries=1, max_bytes=40_000_000):
        self.timeout, self.delay, self.retries, self.max_bytes = timeout, delay, retries, max_bytes
        self._locks, self._last, self._robots, self._memo = {}, {}, {}, {}
        self._guard = threading.RLock()
        self.requests = 0

    def _lock(self, host):
        with self._guard:
            return self._locks.setdefault(host, threading.RLock())

    def _request(self, url, payload=None, headers=None, form=None):
        parts = urlsplit(url)
        if parts.scheme not in {"https", "http"} or not parts.hostname:
            raise FetchError("Unsupported URL: " + url, "invalid_url")
        host = parts.netloc
        if payload is not None and form is not None: raise ValueError("Use one request encoding")
        raw = urlencode(form, doseq=True).encode() if form is not None else json.dumps(payload).encode() if payload is not None else None
        hd = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9, */*;q=0.5", "Accept-Encoding": "gzip"}
        if raw is not None:
            hd["Content-Type"] = "application/x-www-form-urlencoded" if form is not None else "application/json"
        hd.update(headers or {})
        for attempt in range(self.retries + 1):
            with self._lock(host):
                pause = self.delay - (time.monotonic() - self._last.get(host, 0))
                if pause > 0:
                    time.sleep(pause)
                self._last[host] = time.monotonic()
                self.requests += 1
                try:
                    request = urllib.request.Request(url, data=raw, headers=hd)
                    with urllib.request.urlopen(request, timeout=self.timeout) as response:
                        data = response.read(self.max_bytes + 1)
                        if len(data) > self.max_bytes:
                            raise FetchError("Response exceeds safety limit: " + url, "truncated")
                        if response.headers.get("Content-Encoding") == "gzip":
                            data = gzip.decompress(data)
                            if len(data) > self.max_bytes:
                                raise FetchError("Decompressed response exceeds limit", "truncated")
                        return data.decode(response.headers.get_content_charset() or "utf-8", "replace"), response.url, dict(response.headers)
                except urllib.error.HTTPError as e:
                    if e.code in {429, 500, 502, 503, 504} and attempt < self.retries:
                        retry = e.headers.get("Retry-After", "2")
                        delay = float(retry) if retry.isdigit() else 2.0
                        if delay > 30:
                            raise FetchError(f"HTTP {e.code}; retry deferred ({retry}s): {url}", "rate_limited")
                    else:
                        kind = "blocked" if e.code in {401, 403, 429} else "not_found" if e.code in {404, 410} else "error"
                        raise FetchError(f"HTTP {e.code}: {url}", kind) from e
                except (urllib.error.URLError, TimeoutError, OSError) as e:
                    if attempt >= self.retries:
                        raise FetchError(f"{type(e).__name__}: {e}: {url}", "network_error") from e
                    delay = 2.0
            time.sleep(delay)
        raise FetchError("Request failed: " + url)

    def _check_robots(self, url):
        p = urlsplit(url)
        root = p.scheme + "://" + p.netloc
        with self._lock(p.netloc):
            if root not in self._robots:
                rp = urllib.robotparser.RobotFileParser(root + "/robots.txt")
                try:
                    body, _, _ = self._request(root + "/robots.txt")
                    # RFC 9309: ignore unparseable lines (some sites return their SPA for
                    # a missing robots route), but never mistake a challenge for permission.
                    if any(x in body[:30000].lower() for x in ["cf-chl-", "verify you are human", "captcha-delivery.com", "just a moment..."]):
                        raise FetchError("robots.txt returned a human-verification challenge", "robots_unavailable")
                    rp.parse(body.splitlines())
                except FetchError as e:
                    if e.kind == "not_found" or re.match(r"HTTP 4(?:0[0-9]|[1-2][0-8]|[3-9][0-9]):", str(e)):
                        # RFC 9309 2.3.1.3: a 4xx robots resource is unavailable.
                        # A 401/403 on the actual job endpoint still stops retrieval.
                        rp.parse([])
                    else:
                        self._robots[root] = e
                        raise
                self._robots[root] = rp
            rp = self._robots[root]
            if isinstance(rp, FetchError):
                raise rp
            if not rp.can_fetch(USER_AGENT, url):
                raise FetchError("robots.txt disallows this URL: " + url, "robots_denied")

    def get(self, url, *, payload=None, headers=None, public_api=None, form=None):
        key = (url, json.dumps({"json":payload,"form":form}, sort_keys=True))
        with self._guard:
            if key in self._memo:
                return self._memo[key]
        if public_api == "smartrecruiters-postings":
            p = urlsplit(url)
            if p.hostname != "api.smartrecruiters.com" or not re.fullmatch(r"/v1/companies/[A-Za-z0-9_-]+/postings(?:/[A-Za-z0-9_-]+)?", p.path) or payload is not None or form is not None:
                raise FetchError("URL is outside the documented public postings API", "invalid_url")
            # Documented unauthenticated Posting API contract; no internal/private endpoints.
            # https://developers.smartrecruiters.com/docs/authentication
        else:
            self._check_robots(url)
        result = self._request(url, payload, headers, form)
        body = result[0]
        if any(x in body[:30000].lower() for x in ["just a moment...", "cf-chl-", "verify you are human", "captcha-delivery.com"]):
            raise FetchError("Human-verification page; not bypassed: " + url, "blocked")
        with self._guard:
            self._memo[key] = result
        return result

    def text(self, url, **kwargs):
        return self.get(url, **kwargs)[0]

    def json(self, url, **kwargs):
        body = self.text(url, **kwargs)
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            raise FetchError("Expected JSON; source schema/access changed: " + url, "schema_changed") from e
