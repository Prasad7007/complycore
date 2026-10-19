"""
URL helpers for transactional email (Phase 0: hosted logo; Phase 1+: deep links).
"""
from __future__ import annotations

import os

_DEFAULT_FRONTEND_BASE = "http://localhost:5173"
# Public S3 asset (comply-core-assets); works in Gmail for all API envs without CloudFront.
DEFAULT_EMAIL_LOGO_URL = (
    "https://comply-core-assets.s3.ca-central-1.amazonaws.com/complycore-logo.png"
)
# Local SPA copy for dev preview only: full-frontend/public/email/complycore-logo.png
_EMAIL_LOGO_PATH = "/email/complycore-logo.png"


def get_frontend_base_url() -> str:
    return (os.getenv("FRONTEND_BASE_URL") or _DEFAULT_FRONTEND_BASE).rstrip("/")


def get_email_logo_url() -> str:
    """
    Public HTTPS URL for the ComplyCore mark in email headers.

    Defaults to ``DEFAULT_EMAIL_LOGO_URL`` (S3). Override with ``EMAIL_LOGO_URL``
    (e.g. CloudFront) or, for local-only testing, ``{FRONTEND_BASE_URL}{_EMAIL_LOGO_PATH}``.
    """
    explicit = (os.getenv("EMAIL_LOGO_URL") or "").strip()
    if explicit:
        return explicit
    use_frontend = (os.getenv("EMAIL_LOGO_USE_FRONTEND") or "").strip().lower()
    if use_frontend in ("1", "true", "yes"):
        return f"{get_frontend_base_url()}{_EMAIL_LOGO_PATH}"
    return DEFAULT_EMAIL_LOGO_URL


def _document_detail_path(doc_id: str, org_slug: str | None = None) -> str:
    if org_slug:
        return f"/orgs/{org_slug}/validate-documents/detail/{doc_id}"
    return f"/validate-documents/detail/{doc_id}"


def get_document_detail_url(doc_id: str, *, org_slug: str | None = None) -> str:
    """Document preview page (read-only status view)."""
    return f"{get_frontend_base_url()}{_document_detail_path(doc_id, org_slug)}"


def get_document_comment_url(
    doc_id: str,
    *,
    org_slug: str | None = None,
    comment_id: str | None = None,
) -> str:
    """
    Document detail with discussion panel (``?panel=trail``).

    ``comment_id`` is reserved for deep-linking when the SPA supports it.
    """
    base = get_document_detail_url(doc_id, org_slug=org_slug)
    url = f"{base}?panel=trail"
    if comment_id:
        url = f"{url}&commentId={comment_id}"
    return url


def get_document_review_url(doc_id: str, *, org_slug: str | None = None) -> str:
    """SME / compliance review screen (same route as detail today)."""
    return get_document_detail_url(doc_id, org_slug=org_slug)


def get_document_edit_url(doc_id: str, *, org_slug: str | None = None) -> str:
    """Author edit / revisions view (detail page until dedicated edit route exists)."""
    return get_document_detail_url(doc_id, org_slug=org_slug)


def get_login_url() -> str:
    return f"{get_frontend_base_url()}/login"


def get_profile_url(*, org_slug: str | None = None) -> str:
    """Account settings / profile (global route today)."""
    _ = org_slug
    return f"{get_frontend_base_url()}/user-profile"


def get_published_documents_url(*, org_slug: str | None = None) -> str:
    if org_slug:
        return f"{get_frontend_base_url()}/orgs/{org_slug}/published-documents"
    return f"{get_frontend_base_url()}/published-documents"


def get_published_document_url(doc_id: str, *, org_slug: str | None = None) -> str:
    """Open published doc (detail view used from published list)."""
    return get_document_detail_url(doc_id, org_slug=org_slug)
