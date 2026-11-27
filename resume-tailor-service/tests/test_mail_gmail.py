from datetime import date

import httpx
import pytest

from app.mail import gmail
from tests.mail_fixtures import FakeTransport, raw_message


def test_scope_is_read_only_and_paths_default_under_gitignored_data(monkeypatch, tmp_path):
    assert gmail.SCOPES == ["https://www.googleapis.com/auth/gmail.readonly"]
    monkeypatch.delenv("GMAIL_CLIENT_SECRET_FILE", raising=False)
    monkeypatch.delenv("GMAIL_TOKEN_FILE", raising=False)
    assert gmail.token_file().parent == gmail.DATA_DIR
    assert gmail.client_secret_file().parent == gmail.DATA_DIR
    assert gmail.DATA_DIR.name == "data" and gmail.DATA_DIR.parent.name == "resume-tailor-service"
    monkeypatch.setenv("GMAIL_TOKEN_FILE", str(tmp_path / "t.json"))
    monkeypatch.setenv("GMAIL_CLIENT_SECRET_FILE", str(tmp_path / "c.json"))
    assert gmail.token_file() == tmp_path / "t.json"
    assert gmail.client_secret_file() == tmp_path / "c.json"


def test_queries_follow_the_mail_sync_prompt():
    outcome, ats = gmail.queries(date(2026, 1, 29))
    for q in (outcome, ats):
        assert q.endswith("after:2026/01/29 -in:sent")
    assert '"unfortunately"' in outcome and "subject:interview" in outcome
    assert '-subject:("thank you for applying"' in outcome
    assert "from:(ashbyhq.com" in ats and "workatastartup@ycombinator.com" in ats
    assert '-subject:("thank you for applying" OR "application received")' in ats


def test_parse_message_reads_headers_date_and_plain_body():
    raw = raw_message("m1", subject="Your application to Acme", day="2026-01-31",
                      body="Hi,\n\nUnfortunately we decided not to move forward.\n")
    message = gmail.parse_message(raw)
    assert message.id == "m1" and message.thread_id == "tm1"
    assert message.subject == "Your application to Acme"
    assert message.sender.startswith("Acme Recruiting")
    assert message.date == "2026-01-31"
    assert message.body == "Hi, Unfortunately we decided not to move forward."


def test_parse_message_falls_back_to_html_and_caps_the_body():
    raw = raw_message("m2", subject="Interview", html="<p>Let&#39;s <b>talk</b></p><style>x{}</style>")
    assert gmail.parse_message(raw).body == "Let's talk"
    raw = raw_message("m3", subject="Long", body="word " * 2000)
    assert len(gmail.parse_message(raw).body) == gmail.BODY_LIMIT


def test_fetch_unions_queries_skips_known_and_receipts_and_sorts_oldest_first():
    messages = {
        "a1": raw_message("a1", subject="Update on your Acme application", day="2026-02-02", body="Unfortunately"),
        "a2": raw_message("a2", subject="Interview with Acme", day="2026-02-01", body="Pick a time"),
        "a3": raw_message("a3", subject="Thank you for applying to Acme", day="2026-02-01", body="received"),
        "a4": raw_message("a4", subject="Acme assessment", day="2026-02-03", body="Take home"),
    }
    transport = FakeTransport(messages, {'"unfortunately"': ["a1", "a2", "a3"], "from:(ashbyhq.com": ["a2", "a4"]})
    client = gmail.GmailClient(transport)
    found, known, receipts = client.fetch(date(2026, 1, 30), skip={"a4"})
    assert [m.id for m in found] == ["a2", "a1"]
    assert known == 1 and [m.id for m in receipts] == ["a3"]
    # The known message is never opened.
    assert ("messages/a4", {"format": "full"}) not in transport.calls


def test_fetch_pages_and_limits():
    messages = {f"m{i}": raw_message(f"m{i}", subject="Acme next step", day=f"2026-02-{i + 1:02d}", body="x")
                for i in range(5)}
    transport = FakeTransport(messages, {'"unfortunately"': list(messages)}, page_size=2)
    found, _, _ = gmail.GmailClient(transport).fetch(date(2026, 1, 1), limit=3)
    assert [m.id for m in found] == ["m0", "m1", "m2"]
    assert sum(1 for path, _ in transport.calls if path == "messages") >= 3


def test_message_refuses_odd_ids():
    with pytest.raises(gmail.GmailError):
        gmail.GmailClient(FakeTransport({})).message("../labels")


class _Creds:
    def __init__(self, token):
        self.token = token


def test_http_transport_sends_bearer_and_raises_on_errors():
    seen = {}

    def get(url, params, headers, timeout):
        seen.update(url=url, params=params, headers=headers)
        return httpx.Response(200, json={"messages": []})

    transport = gmail.HttpTransport(_Creds("tok"), get=get)
    assert transport("messages", {"q": "x"}) == {"messages": []}
    assert seen["url"] == f"{gmail.API}/messages"
    assert seen["headers"]["Authorization"] == "Bearer tok"

    failing = gmail.HttpTransport(_Creds("tok"), get=lambda *a, **k: httpx.Response(500, text="nope"))
    with pytest.raises(gmail.GmailError, match="HTTP 500"):
        failing("messages", {})


def test_missing_token_says_how_to_authorize(tmp_path, monkeypatch):
    monkeypatch.setenv("GMAIL_TOKEN_FILE", str(tmp_path / "missing.json"))
    with pytest.raises(gmail.GmailNotConfigured, match="gmail_auth.py"):
        gmail.load_credentials()


def test_save_token_is_private(tmp_path):
    class Creds:
        def to_json(self):
            return '{"token": "x"}'

    path = gmail.save_token(Creds(), tmp_path / "sub" / "token.json")
    assert path.read_text() == '{"token": "x"}'
    assert oct(path.stat().st_mode & 0o777) == "0o600"
