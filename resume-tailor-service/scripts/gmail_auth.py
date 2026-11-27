"""One time Gmail consent for the mail sync pipeline. Run it yourself, locally:

    cd resume-tailor-service
    uv run python scripts/gmail_auth.py

It opens the browser on Google's consent screen for YOUR OAuth client (a Desktop app
client from Google Cloud, saved as GMAIL_CLIENT_SECRET_FILE, default
data/gmail_client_secret.json) and asks for one scope, gmail.readonly. The token is
written to GMAIL_TOKEN_FILE (default data/gmail_token.json) with mode 0600. `data/` is
gitignored; never commit either file. Rerun it if the token is revoked or expires.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.mail.gmail import SCOPES, client_secret_file, save_token, token_file  # noqa: E402


def main() -> int:
    from google_auth_oauthlib.flow import InstalledAppFlow

    secret = client_secret_file()
    if not secret.is_file():
        print(f"No OAuth client file at {secret}. Download the Desktop app client JSON from "
              "Google Cloud and save it there, or set GMAIL_CLIENT_SECRET_FILE.", file=sys.stderr)
        return 1
    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    # A loopback redirect on a free local port; nothing listens beyond this one exchange.
    creds = flow.run_local_server(host="127.0.0.1", port=0, open_browser=True)
    granted = set(creds.scopes or SCOPES)
    if granted != set(SCOPES):
        print(f"Refusing to save a token with scopes {sorted(granted)}; only gmail.readonly is allowed.",
              file=sys.stderr)
        return 1
    path = save_token(creds, token_file())
    print(f"Saved a read only Gmail token to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
