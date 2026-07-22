import pytest
from fastapi import HTTPException
from app.auth import verify_token


def test_verify_token_accepts_matching_token(monkeypatch):
    monkeypatch.setenv("RESUME_TAILOR_TOKEN", "secret123")
    verify_token(authorization="Bearer secret123")  # should not raise


def test_verify_token_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("RESUME_TAILOR_TOKEN", "secret123")
    with pytest.raises(HTTPException) as exc_info:
        verify_token(authorization="Bearer wrong")
    assert exc_info.value.status_code == 401


def test_verify_token_rejects_missing_header(monkeypatch):
    monkeypatch.setenv("RESUME_TAILOR_TOKEN", "secret123")
    with pytest.raises(HTTPException) as exc_info:
        verify_token(authorization="")
    assert exc_info.value.status_code == 401


def test_verify_token_rejects_non_bearer_scheme(monkeypatch):
    monkeypatch.setenv("RESUME_TAILOR_TOKEN", "secret123")
    with pytest.raises(HTTPException) as exc_info:
        verify_token(authorization="Basic secret123")
    assert exc_info.value.status_code == 401


def test_verify_token_errors_if_unconfigured(monkeypatch):
    monkeypatch.delenv("RESUME_TAILOR_TOKEN", raising=False)
    with pytest.raises(HTTPException) as exc_info:
        verify_token(authorization="Bearer anything")
    assert exc_info.value.status_code == 500
