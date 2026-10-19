"""Tests for transactional email URL helpers (Phase 0)."""
import os

from apis.core.email_links import get_email_logo_url, get_frontend_base_url


def test_get_frontend_base_url_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.example.com/")
    assert get_frontend_base_url() == "https://app.example.com"


def test_get_email_logo_url_default_s3(monkeypatch):
    monkeypatch.delenv("EMAIL_LOGO_URL", raising=False)
    monkeypatch.delenv("EMAIL_LOGO_USE_FRONTEND", raising=False)
    from apis.core.email_links import DEFAULT_EMAIL_LOGO_URL

    assert get_email_logo_url() == DEFAULT_EMAIL_LOGO_URL


def test_get_email_logo_url_frontend_fallback(monkeypatch):
    monkeypatch.delenv("EMAIL_LOGO_URL", raising=False)
    monkeypatch.setenv("EMAIL_LOGO_USE_FRONTEND", "true")
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.example.com")
    assert get_email_logo_url() == "https://app.example.com/email/complycore-logo.png"


def test_get_email_logo_url_explicit_override(monkeypatch):
    monkeypatch.setenv("EMAIL_LOGO_URL", "https://cdn.example.com/logo.png")
    assert get_email_logo_url() == "https://cdn.example.com/logo.png"
