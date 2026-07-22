import hmac
import os
from fastapi import Header, HTTPException


def verify_token(authorization: str = Header(default="")) -> None:
    expected = os.environ.get("RESUME_TAILOR_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=500, detail="RESUME_TAILOR_TOKEN not configured")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="invalid or missing token")
