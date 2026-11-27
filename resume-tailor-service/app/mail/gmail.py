"""Read only Gmail client for the mail sync pipeline (spec 13.3).

Harsh's own OAuth client, scope `gmail.readonly` only: this module can list and read
messages and nothing else. It never sends, labels, archives or deletes. The consent
flow runs once, locally, through `scripts/gmail_auth.py`, which stores the token.

Paths come from the environment and default under `resume-tailor-service/data/`, which
is gitignored:

- `GMAIL_CLIENT_SECRET_FILE`: the OAuth client JSON downloaded from Google Cloud.
- `GMAIL_TOKEN_FILE`: the token the auth script writes (refreshed here when it expires).

Plain HTTPS to the Gmail REST API (two GET endpoints) through `httpx`, with
`google-auth` for loading and refreshing the token. Every request goes through an
injectable `Transport`, so tests run on synthetic messages with no network.
"""
from __future__ import annotations

import base64
import html
import os
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import httpx

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
API = "https://gmail.googleapis.com/gmail/v1/users/me"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
BODY_LIMIT = 2000
SEARCH_LIMIT = 500

# The two searches from prompts/mail-sync.md step 2.
OUTCOME_QUERY = (
    '("unfortunately" OR "not to move forward" OR "other candidates" OR "decided not to" '
    'OR "position has been filled" OR subject:interview OR "schedule an interview" '
    'OR "was accepted" OR "assessment" OR "next step")'
)
ATS_QUERY = (
    "from:(ashbyhq.com OR greenhouse-mail.io OR hire.lever.co OR myworkday.com "
    "OR ats.rippling.com OR remail.wellfound.com OR workatastartup@ycombinator.com) "
    '-subject:("thank you for applying" OR "application received")'
)
_EXCLUDE_RECEIPTS = '-subject:("thank you for applying" OR "application received" OR "we received your application")'

# Subjects that are never an outcome: receipts and sign in codes. Subject only, since a
# rejection body often thanks the candidate for applying.
_SKIP_SUBJECT = re.compile(
    r"thanks? (you )?for applying|application (received|submitted|confirmation)"
    r"|we(?:'ve| have)? received your application|verification code|security code"
    r"|verify your email|confirm your email|one[ -]?time (?:pass)?code",
    re.I,
)

Transport = Callable[[str, dict], dict]


class GmailError(RuntimeError):
    pass


class GmailNotConfigured(GmailError):
    """No token yet: Harsh has to run scripts/gmail_auth.py once."""


def client_secret_file() -> Path:
    return Path(os.environ.get("GMAIL_CLIENT_SECRET_FILE") or DATA_DIR / "gmail_client_secret.json").expanduser()


def token_file() -> Path:
    return Path(os.environ.get("GMAIL_TOKEN_FILE") or DATA_DIR / "gmail_token.json").expanduser()


def queries(after: date) -> list[str]:
    window = f"after:{after:%Y/%m/%d} -in:sent"
    return [f"{OUTCOME_QUERY} {_EXCLUDE_RECEIPTS} {window}", f"{ATS_QUERY} {window}"]


def is_skippable(subject: str) -> bool:
    return bool(_SKIP_SUBJECT.search(subject or ""))


@dataclass(frozen=True)
class MailMessage:
    id: str
    thread_id: str
    sender: str
    subject: str
    date: str  # YYYY-MM-DD, UTC, from Gmail's internalDate
    snippet: str
    body: str

    def to_dict(self) -> dict:
        return asdict(self)


# --- parsing ---------------------------------------------------------------------------


def _b64(data: str) -> str:
    raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    return raw.decode("utf-8", errors="replace")


def _html_text(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", text)
    return html.unescape(re.sub(r"<[^>]+>", " ", text))


def _parts(payload: dict) -> Iterable[dict]:
    yield payload
    for part in payload.get("parts") or []:
        yield from _parts(part)


def _body(payload: dict) -> str:
    plain, rich = "", ""
    for part in _parts(payload):
        data = (part.get("body") or {}).get("data")
        if not data:
            continue
        mime = part.get("mimeType", "")
        if mime == "text/plain" and not plain:
            plain = _b64(data)
        elif mime == "text/html" and not rich:
            rich = _html_text(_b64(data))
    text = plain or rich
    return " ".join(text.split())[:BODY_LIMIT]


def _date(raw: dict) -> str:
    try:
        moment = datetime.fromtimestamp(int(raw["internalDate"]) / 1000, tz=timezone.utc)
    except (KeyError, TypeError, ValueError):
        return ""
    return moment.date().isoformat()


def parse_message(raw: dict) -> MailMessage:
    payload = raw.get("payload") or {}
    headers = {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers") or []}
    return MailMessage(
        id=str(raw["id"]),
        thread_id=str(raw.get("threadId", "")),
        sender=headers.get("from", ""),
        subject=headers.get("subject", ""),
        date=_date(raw),
        snippet=html.unescape(raw.get("snippet", "")),
        body=_body(payload),
    )


# --- client ----------------------------------------------------------------------------


class GmailClient:
    def __init__(self, transport: Transport):
        self._transport = transport

    def search(self, query: str, limit: int = SEARCH_LIMIT) -> list[str]:
        ids: list[str] = []
        token = None
        while len(ids) < limit:
            params: dict = {"q": query, "maxResults": min(100, limit - len(ids))}
            if token:
                params["pageToken"] = token
            page = self._transport("messages", params)
            ids.extend(str(item["id"]) for item in page.get("messages") or [])
            token = page.get("nextPageToken")
            if not token:
                break
        return ids

    def message(self, message_id: str) -> MailMessage:
        if not re.fullmatch(r"[A-Za-z0-9]+", message_id):
            raise GmailError(f"unexpected message id {message_id!r}")
        return parse_message(self._transport(f"messages/{message_id}", {"format": "full"}))

    def fetch(self, after: date, *, skip: set[str] | frozenset = frozenset(),
              limit: int = 100) -> tuple[list[MailMessage], int]:
        """New messages from both searches since `after`, oldest first, at most `limit`.
        Returns the messages and how many matched but were already known."""
        seen: list[str] = []
        known = 0
        for query in queries(after):
            for message_id in self.search(query):
                if message_id in seen:
                    continue
                seen.append(message_id)
        fresh = [message_id for message_id in seen if message_id not in skip]
        known = len(seen) - len(fresh)
        messages = [self.message(message_id) for message_id in fresh]
        messages = [m for m in messages if not is_skippable(m.subject)]
        messages.sort(key=lambda m: (m.date, m.id))
        return messages[:limit], known


# --- the real transport ----------------------------------------------------------------


def load_credentials(path: Path | None = None):
    """The stored token, refreshed (and saved back) when it has expired."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    path = path or token_file()
    if not path.is_file():
        raise GmailNotConfigured(
            f"no Gmail token at {path}; run `uv run python scripts/gmail_auth.py` once"
        )
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if not creds.valid:
        if not (creds.expired and creds.refresh_token):
            raise GmailNotConfigured("the Gmail token is not usable; run scripts/gmail_auth.py again")
        creds.refresh(Request())
        save_token(creds, path)
    return creds


def save_token(creds, path: Path | None = None) -> Path:
    path = path or token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(creds.to_json())
    os.chmod(path, 0o600)
    return path


class HttpTransport:
    """GET against the Gmail REST API with the stored token."""

    def __init__(self, credentials=None, *, timeout: float = 30,
                 get: Callable[..., httpx.Response] = httpx.get):
        self._creds = credentials
        self._timeout = timeout
        self._get = get

    def _token(self, refresh: bool = False) -> str:
        if self._creds is None or refresh:
            self._creds = load_credentials()
        return self._creds.token

    def __call__(self, path: str, params: dict) -> dict:
        response = None
        for attempt in range(2):
            headers = {"Authorization": f"Bearer {self._token(refresh=attempt > 0)}"}
            try:
                response = self._get(f"{API}/{path}", params=params, headers=headers, timeout=self._timeout)
            except httpx.HTTPError as exc:
                raise GmailError(f"Gmail request failed: {type(exc).__name__}") from exc
            if response.status_code != 401:
                break
        if response.status_code != 200:
            raise GmailError(f"Gmail API HTTP {response.status_code}: {response.text[:200]}")
        return response.json()


def default_client() -> GmailClient:
    return GmailClient(HttpTransport())
