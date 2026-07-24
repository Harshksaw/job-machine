"""Local stand-in for the Google Apps Script /exec read endpoint.

GET /exec?action=read[&secret=...] -> {"ok": true, "rows": [...]}, mirroring the
contract app/sheets.py expects. Started by scripts/start.sh for local runs.
Run directly: APPS_SCRIPT_READ_SECRET=<s> python3 scripts/mock_sheet.py 8799
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

ROWS = [
    {"company": "Acme Cloud", "role": "Backend Engineer", "source": "LinkedIn",
     "jobUrl": "https://example.com/acme", "status": "applied", "fit": "8",
     "people": "", "hooks": "distributed systems, message queues", "outreach": "",
     "notes": "strong match on Go/Python + CI/CD", "timestamp": "2026-07-23T06:05:00Z"},
    {"company": "Vectra AI", "role": "AI/ML Engineer", "source": "Wellfound",
     "jobUrl": "https://example.com/vectra", "status": "people-mined", "fit": "9",
     "people": "CTO, Eng Lead", "hooks": "RAG, vector DB, LLM failover", "outreach": "",
     "notes": "Document Intelligence Platform is a direct match",
     "timestamp": "2026-07-23T06:10:00Z"},
    {"company": "Ridewell", "role": "Mobile Engineer", "source": "Referral",
     "jobUrl": "https://example.com/ridewell", "status": "outreach-sent", "fit": "7",
     "people": "Hiring Manager", "hooks": "React Native, native modules",
     "outreach": "connection note sent", "notes": "2 prod RN apps at Jythu",
     "timestamp": "2026-07-23T06:11:00Z"},
    {"company": "Northwind Labs", "role": "Full-Stack Engineer", "source": "Company site",
     "jobUrl": "https://example.com/northwind", "status": "interview", "fit": "8",
     "people": "", "hooks": "Next.js, Postgres", "outreach": "",
     "notes": "awaiting scheduling", "timestamp": "2026-07-22T18:00:00Z"},
    {"company": "Globex", "role": "Platform Engineer", "source": "LinkedIn",
     "jobUrl": "https://example.com/globex", "status": "rejected", "fit": "6",
     "people": "", "hooks": "K8s, Terraform", "outreach": "",
     "notes": "went with a senior candidate", "timestamp": "2026-07-21T12:00:00Z"},
]
SECRET = os.environ.get("APPS_SCRIPT_READ_SECRET", "").strip()


class Handler(BaseHTTPRequestHandler):
    def _json(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        if (qs.get("action") or [""])[0] != "read":
            return self._json({"ok": False, "error": "unknown action"})
        if SECRET and (qs.get("secret") or [""])[0] != SECRET:
            return self._json({"ok": False, "error": "bad secret"})
        return self._json({"ok": True, "rows": ROWS})

    def log_message(self, fmt, *args):
        sys.stderr.write("[mock_sheet] " + (fmt % args) + "\n")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
    print(f"[mock_sheet] serving {len(ROWS)} rows on http://127.0.0.1:{port}/exec")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
