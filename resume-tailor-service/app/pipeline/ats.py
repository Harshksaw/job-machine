"""Applicant tracking system helpers for the code steps: tell which ATS or job board a URL
belongs to, and fetch a posting's full description from the public endpoints listed in
docs/AGENT-PLAYBOOK.md ("Fetching full JD text without a browser").

Every network call goes through one `Http` callable, `(method, url) -> (status,
final_url, body)`, so tests replay recorded payloads and never reach a live site. The
default `http` is plain urllib: a timeout, an honest User-Agent, redirects followed, and
any network trouble returned as status 0 instead of raised.
"""
from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

Http = Callable[[str, str], tuple[int, str, str]]

USER_AGENT = "job-machine-pipeline/1.0 (personal job search)"
TIMEOUT = 20
_MAX_BODY = 2_000_000


def http(method: str, url: str) -> tuple[int, str, str]:
    request = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read(_MAX_BODY) if method != "HEAD" else b""
            return response.status, response.geturl(), body.decode("utf-8", "ignore")
    except urllib.error.HTTPError as error:
        return error.code, error.geturl() or url, ""
    except Exception:  # network trouble is "no answer", never a crash
        return 0, url, ""


@dataclass(frozen=True)
class Posting:
    kind: str  # ashby, greenhouse, lever, linkedin
    org: str
    id: str


_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_PATTERNS = (
    ("ashby", re.compile(rf"^https?://jobs\.ashbyhq\.com/([^/?#]+)/({_UUID})", re.I)),
    ("greenhouse", re.compile(r"^https?://(?:[\w-]+\.)*greenhouse\.io/([\w-]+)/jobs/(\d+)", re.I)),
    ("lever", re.compile(rf"^https?://jobs\.(?:eu\.)?lever\.co/([^/?#]+)/({_UUID})", re.I)),
)
_LINKEDIN = re.compile(r"(?:/view/(?:[^/?]*-)?|currentJobId=)(\d{8,})")

# Hosts of employer side applicant tracking systems other than the three with public
# JSON APIs. A URL on one of these with a posting path counts as the employer's own
# application page.
OTHER_ATS_HOSTS = (
    "myworkdayjobs.com", "workable.com", "smartrecruiters.com", "rippling.com",
    "bamboohr.com", "recruitee.com", "breezy.hr", "jazzhr.com", "applytojob.com",
    "teamtailor.com", "personio.de", "personio.com", "icims.com", "jobvite.com",
    "workforcenow.adp.com", "ultipro.com", "pinpointhq.com", "dover.com", "gem.com",
)
# Job boards and aggregators: a listing there is not the employer's application page.
BOARD_HOSTS = (
    "himalayas.app", "remotive.com", "remotive.io", "jobicy.com", "remoteok.com",
    "remoteok.io", "workingnomads.com", "workingnomads.co", "wellfound.com", "angel.co",
)
AGGREGATOR_HOSTS = BOARD_HOSTS + (
    "linkedin.com", "indeed.com", "glassdoor.com", "ziprecruiter.com", "ycombinator.com",
    "google.com", "monster.com", "simplyhired.com", "builtin.com", "dice.com",
)
_CAREERS_WORDS = re.compile(r"career|jobs?\b|/job/|join|apply|position|opening|vacanc|hiring|work-with-us", re.I)
_DEAD_MARKERS = re.compile(r"job_not_found|closed_job|not[-_]found|error=", re.I)


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _on(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def detect(url: str) -> Posting | None:
    """The ATS posting behind a URL, when its description can be fetched by API."""
    url = (url or "").strip()
    for kind, pattern in _PATTERNS:
        match = pattern.search(url)
        if match:
            return Posting(kind, match.group(1), match.group(2).lower())
    if _on(_host(url), ("linkedin.com",)):
        match = _LINKEDIN.search(url)
        if match:
            return Posting("linkedin", "", match.group(1))
    return None


def is_board(url: str) -> bool:
    return _on(_host(url), BOARD_HOSTS)


def is_ats_posting(url: str) -> bool:
    """True when the URL is an employer's own posting on an applicant tracking system."""
    posting = detect(url)
    if posting is not None:
        return posting.kind != "linkedin"
    host = _host(url)
    if not _on(host, OTHER_ATS_HOSTS) or _DEAD_MARKERS.search(url):
        return False
    path = [part for part in urlsplit(url).path.split("/") if part]
    return len(path) >= 2


def is_careers_page(url: str) -> bool:
    """A page on the employer's own site that looks like a job or careers page."""
    host = _host(url)
    if not host or _on(host, AGGREGATOR_HOSTS) or _DEAD_MARKERS.search(url):
        return False
    if any(_on(host, (domain,)) for domain in ("ashbyhq.com", "greenhouse.io", "lever.co")):
        return False  # an ATS index or dead link, not a posting
    if _on(host, OTHER_ATS_HOSTS):
        return is_ats_posting(url)
    parts = urlsplit(url)
    return bool(_CAREERS_WORDS.search(parts.path)) or host.split(".")[0] in ("careers", "jobs")


_BLOCK_TAGS = re.compile(r"<\s*(br|/p|/div|/li|/h\d|/ul|/ol|/tr|/section)\b[^>]*>", re.I)


def html_to_text(raw: str) -> str:
    text = re.sub(r"<(script|style)\b.*?</\1\s*>", " ", raw or "", flags=re.I | re.S)
    text = re.sub(r"<\s*li\b[^>]*>", "\n- ", text, flags=re.I)
    text = _BLOCK_TAGS.sub("\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text)).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _json(body: str) -> object:
    try:
        return json.loads(body)
    except ValueError:
        return None


def _ashby(posting: Posting, get: Http) -> str:
    status, _, body = get("GET", f"https://api.ashbyhq.com/posting-api/job-board/{posting.org}")
    data = _json(body) if status == 200 else None
    for job in (data or {}).get("jobs", []) if isinstance(data, dict) else []:
        if str(job.get("id", "")).lower() == posting.id:
            plain = (job.get("descriptionPlain") or "").strip()
            return plain or html_to_text(job.get("descriptionHtml") or "")
    return ""


def _greenhouse(posting: Posting, get: Http) -> str:
    status, _, body = get(
        "GET", f"https://boards-api.greenhouse.io/v1/boards/{posting.org}/jobs/{posting.id}"
    )
    data = _json(body) if status == 200 else None
    if not isinstance(data, dict):
        return ""
    # The API escapes the HTML once, so unescape before stripping tags.
    return html_to_text(html.unescape(data.get("content") or ""))


def _lever(posting: Posting, get: Http, host: str) -> str:
    api = "api.eu.lever.co" if ".eu." in host else "api.lever.co"
    status, _, body = get("GET", f"https://{api}/v0/postings/{posting.org}/{posting.id}")
    data = _json(body) if status == 200 else None
    if not isinstance(data, dict):
        return ""
    parts = [(data.get("descriptionPlain") or "").strip() or html_to_text(data.get("description") or "")]
    for section in data.get("lists") or []:
        heading = (section.get("text") or "").strip()
        items = html_to_text(section.get("content") or "")
        parts.append(f"{heading}\n{items}".strip())
    parts.append((data.get("additionalPlain") or "").strip() or html_to_text(data.get("additional") or ""))
    return "\n\n".join(part for part in parts if part)


def _linkedin(posting: Posting, get: Http) -> str:
    status, _, body = get("GET", f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{posting.id}")
    if status != 200:
        return ""
    match = re.search(r'class="show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>', body, re.S)
    return html_to_text(match.group(1)) if match else ""


def fetch_description(url: str, get: Http = http) -> tuple[str, str]:
    """(kind, plain text) for a supported posting URL, or ("", "") when none answers."""
    posting = detect(url)
    if posting is None:
        return "", ""
    try:
        if posting.kind == "ashby":
            text = _ashby(posting, get)
        elif posting.kind == "greenhouse":
            text = _greenhouse(posting, get)
        elif posting.kind == "lever":
            text = _lever(posting, get, _host(url))
        else:
            text = _linkedin(posting, get)
    except Exception:  # a malformed payload or network error is "no text", not a crash
        return posting.kind, ""
    return posting.kind, text.strip()
