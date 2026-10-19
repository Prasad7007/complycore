"""Load test configuration from environment (see .env.example)."""

import os
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def api_base_url() -> str:
    """
    Base URL including /api/v1, e.g. https://uat.example.com/api/v1
    Locust --host should match this value.
    """
    return _env("UAT_BASE_URL", "http://localhost:8052/api/v1").rstrip("/")


def auth_token() -> str:
    return _env("AUTH_TOKEN")


def org_slug() -> str:
    return _env("ORG_SLUG", "legacy-default")


def fixture_pdf_path() -> Path:
    raw = _env("FIXTURE_PDF_PATH", str(Path(__file__).resolve().parent / "fixtures" / "sample.pdf"))
    return Path(raw).expanduser()


def poll_interval_sec() -> float:
    return float(_env("POLL_INTERVAL_SEC", "5"))


def analysis_timeout_sec() -> float:
    return float(_env("ANALYSIS_TIMEOUT_SEC", "1800"))


def document_type() -> str:
    return _env("DOCUMENT_TYPE", "Marketing Material")


def upload_routing() -> str:
    """Upload workflow: marketing = skip SME and auto-queue analysis (required for load tests)."""
    return _env("UPLOAD_ROUTING", "marketing")


def auth_headers() -> dict[str, str]:
    token = auth_token()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def report_dir() -> Path:
    """Directory for JSON/HTML summaries (created if missing)."""
    raw = _env("LOADTEST_REPORT_DIR", str(Path(__file__).resolve().parent / "reports"))
    path = Path(raw).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path
