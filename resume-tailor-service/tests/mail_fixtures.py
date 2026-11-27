"""Synthetic Gmail API messages for tests. Generic companies only; no real mail."""
import base64


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def raw_message(message_id: str, *, subject: str, sender: str = "Acme Recruiting <no-reply@ashbyhq.com>",
                day: str = "2026-01-31", body: str = "", html: str = "", snippet: str = "") -> dict:
    from datetime import datetime, timezone

    ms = int(datetime.fromisoformat(day).replace(hour=12, tzinfo=timezone.utc).timestamp() * 1000)
    parts = []
    if body:
        parts.append({"mimeType": "text/plain", "body": {"data": _b64(body)}})
    if html:
        parts.append({"mimeType": "text/html", "body": {"data": _b64(html)}})
    return {
        "id": message_id,
        "threadId": f"t{message_id}",
        "internalDate": str(ms),
        "snippet": snippet or body[:80],
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": subject},
                        {"name": "Date", "value": day}],
            "parts": parts,
        },
    }


class FakeTransport:
    """Answers `messages` searches from a {query substring: [ids]} map and
    `messages/<id>` from stored raw messages. Records every call."""

    def __init__(self, messages: dict[str, dict], searches: dict[str, list[str]] | None = None, page_size: int = 100):
        self.messages = messages
        self.searches = searches
        self.page_size = page_size
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, path: str, params: dict) -> dict:
        self.calls.append((path, dict(params)))
        if path == "messages":
            if self.searches is None:
                ids = list(self.messages)
            else:
                ids = []
                for needle, found in self.searches.items():
                    if needle in params["q"]:
                        ids.extend(found)
            start = int(params.get("pageToken") or 0)
            size = min(self.page_size, params["maxResults"])
            page = {"messages": [{"id": i, "threadId": f"t{i}"} for i in ids[start:start + size]]}
            if start + size < len(ids):
                page["nextPageToken"] = str(start + size)
            return page
        message_id = path.split("/", 1)[1]
        return self.messages[message_id]
