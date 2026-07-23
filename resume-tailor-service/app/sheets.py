"""Sync client for the Google Apps Script application-log read endpoint.

`APPS_SCRIPT_URL` and `APPS_SCRIPT_READ_SECRET` are read ONLY here. No error
raised by this module may contain either value — `SheetsError` messages are
surfaced to clients (as 502s) and may be logged.
"""

import os

import httpx

from app.errors import SheetsError
from app.models import Application

_TIMEOUT = 15.0


def _require_config() -> tuple[str, str]:
    url = os.environ.get("APPS_SCRIPT_URL", "").strip()
    secret = os.environ.get("APPS_SCRIPT_READ_SECRET", "").strip()
    if not url or not secret:
        raise SheetsError(
            "applications sheet is not configured "
            "(set APPS_SCRIPT_URL and APPS_SCRIPT_READ_SECRET)"
        )
    return url, secret


def _cell(row: dict, key: str) -> str:
    value = row.get(key)
    return "" if value is None else str(value)


def _normalize(row: dict) -> Application:
    return Application(
        company=_cell(row, "company"),
        role=_cell(row, "role"),
        source=_cell(row, "source"),
        job_url=_cell(row, "jobUrl"),  # camelCase in the sheet -> snake_case
        status=_cell(row, "status"),
        fit=_cell(row, "fit"),
        people=_cell(row, "people"),
        hooks=_cell(row, "hooks"),
        outreach=_cell(row, "outreach"),
        notes=_cell(row, "notes"),
        timestamp=_cell(row, "timestamp"),
    )


def fetch_applications() -> list[Application]:
    """Read the application log and return normalized rows.

    Raises ``SheetsError`` on missing config, transport failure, non-200,
    ``ok`` not true, or malformed JSON — always with a message free of the URL
    and secret.
    """
    url, secret = _require_config()

    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(url, params={"action": "read", "secret": secret})
    except httpx.HTTPError as exc:
        # Do NOT interpolate exc/url — httpx error text embeds the request URL.
        raise SheetsError("could not reach the applications sheet") from exc

    if resp.status_code != 200:
        raise SheetsError(f"applications sheet returned HTTP {resp.status_code}")

    try:
        payload = resp.json()
    except ValueError as exc:  # json.JSONDecodeError is a ValueError subclass
        raise SheetsError("applications sheet returned malformed JSON") from exc

    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise SheetsError("applications sheet reported an error")

    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise SheetsError("applications sheet response was missing rows")

    return [_normalize(row) for row in rows if isinstance(row, dict)]
