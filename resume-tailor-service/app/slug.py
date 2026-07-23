import re


def safe_slug(company: str, role: str) -> str:
    raw = f"{company}-{role}".lower().replace(" ", "-")
    cleaned = re.sub(r"[^a-z0-9._-]", "", raw).lstrip(".-")
    return cleaned or "job"
