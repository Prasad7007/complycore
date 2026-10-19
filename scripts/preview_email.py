#!/usr/bin/env python3
"""
Render ComplyCore email templates to HTML files for local preview.

Usage (from repo root):
  PYTHONPATH="AI Compliance" python scripts/preview_email.py otp
  PYTHONPATH="AI Compliance" python scripts/preview_email.py --all

Opens files under tmp/email-previews/.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_AI_ROOT = _REPO_ROOT / "AI Compliance"
if str(_AI_ROOT) not in sys.path:
    sys.path.insert(0, str(_AI_ROOT))

from apis.core.email_renderer import (  # noqa: E402
    TEMPLATE_REGISTRY,
    build_collab_document_uploaded_context,
    build_document_published_context,
    build_mention_context,
    build_otp_context,
    build_password_changed_context,
    build_submission_received_context,
    build_welcome_context,
    build_workflow_context,
    render_email,
)


def _sample_context(template_id: str) -> dict:
    if template_id in {"otp", "password_reset"}:
        minutes = (
            10
            if template_id == "password_reset"
            else int(os.getenv("OTP_EXPIRE_MINUTES", "1"))
        )
        return build_otp_context(
            recipient_name="becky",
            otp="542908",
            expire_minutes=minutes,
            template_id=template_id,
        )
    if template_id == "mention":
        return build_mention_context(
            recipient_name="becky",
            actor_name="Alex Morgan",
            document_name="Q2 Investor Brochure",
            comment_excerpt="Please review the claims on page 4 before we submit.",
            doc_id="00000000-0000-0000-0000-000000000001",
            org_slug="acme",
            comment_id="00000000-0000-0000-0000-000000000002",
        )
    if template_id == "workflow_submission_received":
        return build_submission_received_context(
            recipient_name="becky",
            document_name="Q2 Investor Brochure",
            doc_id="00000000-0000-0000-0000-000000000001",
            route="sme",
            org_slug="acme",
        )
    if template_id == "collab_document_uploaded":
        return build_collab_document_uploaded_context(
            recipient_name="becky",
            document_name="Q2 Investor Brochure",
            doc_id="00000000-0000-0000-0000-000000000001",
            version_label="1.1",
            org_slug="acme",
        )
    if template_id == "workflow_sme_approve":
        return build_workflow_context(
            template_id,
            recipient_name="becky",
            document_name="Q2 Investor Brochure",
            actor_name="Alex Morgan",
            from_stage="sme_review",
            to_stage="marketing_review",
            doc_id="00000000-0000-0000-0000-000000000001",
            org_slug="acme",
        )
    if template_id == "workflow_to_compliance":
        return build_workflow_context(
            template_id,
            recipient_name="becky",
            document_name="Q2 Investor Brochure",
            actor_name="Alex Morgan",
            from_stage="marketing_review",
            to_stage="compliance_review",
            doc_id="00000000-0000-0000-0000-000000000001",
            org_slug="acme",
        )
    if template_id == "workflow_compliance_approve":
        return build_workflow_context(
            template_id,
            recipient_name="becky",
            document_name="Q2 Investor Brochure",
            actor_name="Alex Morgan",
            from_stage="compliance_review",
            to_stage="approved",
            doc_id="00000000-0000-0000-0000-000000000001",
            org_slug="acme",
        )
    if template_id.startswith("workflow_"):
        return build_workflow_context(
            template_id,
            recipient_name="becky",
            document_name="Q2 Investor Brochure",
            actor_name="Alex Morgan",
            from_stage="sme_review",
            to_stage="marketing_review",
            doc_id="00000000-0000-0000-0000-000000000001",
            org_slug="acme",
            reviewer_note="Please soften guaranteed returns language on page 4.",
        )
    if template_id == "welcome":
        return build_welcome_context(
            recipient_name="becky",
            account_email="becky@acme.com",
            temp_password="K7m-9q2pR",
            role_name="marketing",
        )
    if template_id == "password_changed":
        return build_password_changed_context(
            recipient_name="becky",
            account_email="becky@acme.com",
            org_slug="acme",
        )
    if template_id == "document_published":
        return build_document_published_context(
            recipient_name="becky",
            document_name="Q2 Investor Brochure",
            doc_id="00000000-0000-0000-0000-000000000001",
            version_label="1.0",
            org_slug="acme",
        )
    return {"first_name": "Becky"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview ComplyCore email templates")
    parser.add_argument(
        "template_id",
        nargs="?",
        help=f"Template id ({', '.join(TEMPLATE_REGISTRY)})",
    )
    parser.add_argument("--all", action="store_true", help="Render all registered templates")
    parser.add_argument(
        "--out-dir",
        default=str(_AI_ROOT / "tmp" / "email-previews"),
        help="Output directory",
    )
    args = parser.parse_args()

    os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:5173")
    from apis.core.email_links import DEFAULT_EMAIL_LOGO_URL

    os.environ.setdefault("EMAIL_LOGO_URL", DEFAULT_EMAIL_LOGO_URL)

    ids = list(TEMPLATE_REGISTRY) if args.all else [args.template_id or "otp"]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for tid in ids:
        if tid not in TEMPLATE_REGISTRY:
            print(f"Unknown template: {tid}", file=sys.stderr)
            return 1
        subject, text, html = render_email(tid, _sample_context(tid))
        html_path = out_dir / f"{tid}.html"
        text_path = out_dir / f"{tid}.txt"
        html_path.write_text(html, encoding="utf-8")
        text_path.write_text(f"Subject: {subject}\n\n{text}", encoding="utf-8")
        print(f"Wrote {html_path}")
        print(f"Wrote {text_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
