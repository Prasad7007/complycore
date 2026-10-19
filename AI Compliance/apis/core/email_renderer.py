"""
Render ComplyCore transactional emails from Jinja templates.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from apis.core.email_links import (
    get_document_comment_url,
    get_document_detail_url,
    get_document_edit_url,
    get_document_review_url,
    get_email_logo_url,
    get_login_url,
    get_profile_url,
    get_published_document_url,
)

_TEMPLATES_DIR = Path(__file__).parent / "email_templates"

_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

BRAND = {
    "name": "ComplyCore",
    "blue": "#1683d6",
    "purple": "#9b3fd1",
    "accent": "#6a3fd6",
    "accent_dark": "#5630b8",
    "ink": "#1f2430",
    "body": "#454b5c",
    "muted": "#8b909c",
    "line": "#ececf1",
    "soft": "#f7f6fb",
    "page_bg": "#eceef1",
    "font": '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif',
}

# template_id -> (jinja template file, default subject)
TEMPLATE_REGISTRY: dict[str, dict[str, str]] = {
    "otp": {
        "file": "otp.html",
        "subject": "Your ComplyCore verification code",
        "preheader": "Your one-time code is inside - expires soon.",
        "tone": "neutral",
        "eyebrow": "Verification",
        "heading": "Your one-time code",
    },
    "password_reset": {
        "file": "password_reset.html",
        "subject": "Reset your ComplyCore password",
        "preheader": "Use this code to reset your password - expires soon.",
        "tone": "neutral",
        "eyebrow": "Password reset",
        "heading": "Reset your password",
    },
    "mention": {
        "file": "mention.html",
        "subject": "{actor_name} mentioned you in a comment",
        "preheader": "{actor_name} mentioned you on {document_name}.",
        "tone": "info",
        "eyebrow": "Mention",
        "heading": "You were mentioned in a comment",
    },
    "workflow_to_sme": {
        "file": "workflow_to_sme.html",
        "subject": "{document_name} is ready for your review",
        "preheader": "A document has been assigned to you for SME review.",
        "tone": "info",
        "eyebrow": "Assigned to you",
        "heading": "A document needs your review",
    },
    "workflow_sme_changes": {
        "file": "workflow_sme_changes.html",
        "subject": "Changes requested on {document_name}",
        "preheader": "{actor_name} requested changes before this can move forward.",
        "tone": "warn",
        "eyebrow": "Changes requested",
        "heading": "Changes requested by SME",
    },
    "workflow_sme_reject": {
        "file": "workflow_sme_reject.html",
        "subject": "{document_name} rejected at SME review",
        "preheader": "This submission was rejected at SME review.",
        "tone": "danger",
        "eyebrow": "Rejected",
        "heading": "Rejected at SME review",
    },
    "workflow_sme_approve": {
        "file": "workflow_sme_approve.html",
        "subject": "{document_name} approved by SME",
        "preheader": "SME review complete — moving to AI analysis.",
        "tone": "success",
        "eyebrow": "Approved",
        "heading": "SME review approved",
    },
    "workflow_to_compliance": {
        "file": "workflow_to_compliance.html",
        "subject": "{document_name} is ready for compliance review",
        "preheader": "A document has reached Compliance review.",
        "tone": "info",
        "eyebrow": "Assigned to you",
        "heading": "A document needs compliance review",
    },
    "workflow_compliance_approve": {
        "file": "workflow_compliance_approve.html",
        "subject": "{document_name} approved by Compliance",
        "preheader": "Compliance approved — ready to publish.",
        "tone": "success",
        "eyebrow": "Approved",
        "heading": "Compliance review approved",
    },
    "workflow_compliance_changes": {
        "file": "workflow_compliance_changes.html",
        "subject": "Compliance requested changes on {document_name}",
        "preheader": "Compliance requested changes before approval.",
        "tone": "warn",
        "eyebrow": "Changes requested",
        "heading": "Changes requested by Compliance",
    },
    "workflow_compliance_reject": {
        "file": "workflow_compliance_reject.html",
        "subject": "{document_name} rejected at compliance review",
        "preheader": "This document was rejected at compliance review.",
        "tone": "danger",
        "eyebrow": "Rejected",
        "heading": "Rejected at compliance review",
    },
    "welcome": {
        "file": "welcome.html",
        "subject": "Welcome to ComplyCore — your account is ready",
        "preheader": "Your ComplyCore account is ready. Sign in with your temporary password.",
        "tone": "success",
        "eyebrow": "Welcome",
        "heading": "Your account is ready",
    },
    "password_changed": {
        "file": "password_changed.html",
        "subject": "Your ComplyCore password was changed",
        "preheader": "Your password was just changed.",
        "tone": "neutral",
        "eyebrow": "Security",
        "heading": "Your password was changed",
    },
    "document_published": {
        "file": "document_published.html",
        "subject": "{document_name} is now published",
        "preheader": "{document_name} has been published.",
        "tone": "success",
        "eyebrow": "Published",
        "heading": "Your document is live",
    },
    "workflow_submission_received": {
        "file": "workflow_submission_received.html",
        "subject": "We've received {document_name}",
        "preheader": "Your submission has entered the review workflow.",
        "tone": "neutral",
        "eyebrow": "Submission received",
        "heading": "Your submission was received",
    },
    "collab_document_uploaded": {
        "file": "collab_document_uploaded.html",
        "subject": "New version uploaded: {document_name}",
        "preheader": "Your new document version was uploaded.",
        "tone": "info",
        "eyebrow": "Upload",
        "heading": "A new version was uploaded",
    },
}

_ROLE_DISPLAY: dict[str, str] = {
    "sme": "SME Reviewer",
    "marketing": "Marketing",
    "compliance": "Compliance Reviewer",
    "super_admin": "Super Admin",
}

_STAGE_LABELS: dict[str, str] = {
    "document_upload": "Document Upload",
    "sme_review": "SME Review",
    "marketing_review": "Marketing",
    "compliance_review": "Compliance Review",
    "rejected": "Rejected",
    "approved": "Approved",
    "published": "Published",
}


def title_case_first_name(raw: str | None) -> str:
    """Title-case first name; fall back to 'there' per client spec."""
    name = (raw or "").strip()
    if not name:
        return "there"
    if "@" in name:
        name = name.split("@", 1)[0]
    part = name.split()[0] if name.split() else name
    if not part:
        return "there"
    return part[:1].upper() + part[1:].lower()


def format_otp_display(otp: str) -> str:
    """Display OTP as '542 908' when six digits."""
    digits = re.sub(r"\D", "", str(otp or ""))
    if len(digits) == 6:
        return f"{digits[:3]} {digits[3:]}"
    return str(otp).strip()


def humanize_stage(stage: str, *, revisions: bool = False) -> str:
    key = (stage or "").strip().lower()
    if revisions and key == "marketing_review":
        return "Marketing — Revisions"
    if key in _STAGE_LABELS:
        return _STAGE_LABELS[key]
    return (stage or "").replace("_", " ").title() or "Unknown"


def _truncate_note(text: str | None, limit: int = 800) -> str:
    raw = (text or "").strip()
    if len(raw) <= limit:
        return raw
    return raw[: limit - 3] + "..."


def _truncate_excerpt(text: str | None, limit: int = 400) -> str:
    return _truncate_note(text, limit)


def _format_subject(template: str, ctx: dict[str, Any]) -> str:
    try:
        return template.format_map(
            {k: str(v) for k, v in ctx.items() if isinstance(v, (str, int))}
        )
    except KeyError:
        return template


def humanize_role_name(raw: str | None) -> str:
    """Human-readable role for welcome email."""
    name = (raw or "").strip()
    if not name:
        return "ComplyCore user"
    key = name.lower().replace(" ", "_")
    if key in _ROLE_DISPLAY:
        return _ROLE_DISPLAY[key]
    return name.replace("_", " ").title()


def format_email_timestamp(when: datetime | None = None) -> str:
    """Human-readable timestamp for security / publish emails."""
    dt = when or datetime.now(timezone.utc)
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    hour = dt.strftime("%I").lstrip("0") or "12"
    return f"{dt.strftime('%d %b %Y')}, {hour}:{dt.strftime('%M %p')}"


def humanize_minutes(minutes: int) -> str:
    n = max(1, int(minutes))
    return "1 minute" if n == 1 else f"{n} minutes"


def _brand_context() -> dict[str, Any]:
    ctx = dict(BRAND)
    ctx["logo_url"] = html.escape(get_email_logo_url(), quote=True)
    return ctx


def wrap_html_email(fragment: str) -> str:
    """
    Wrap template fragment in a UTF-8 HTML document.

    Without this, some clients treat the body as Latin-1 and mojibake smart
    punctuation (em dash, curly quotes, copyright).
    """
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />\n'
        '<meta charset="UTF-8" />\n'
        "<title>ComplyCore</title>\n"
        "</head>\n"
        '<body style="margin:0;padding:0;">\n'
        f"{fragment}\n"
        "</body>\n"
        "</html>"
    )


def render_email(
    template_id: str,
    context: dict[str, Any] | None = None,
    *,
    subject_override: str | None = None,
) -> tuple[str, str, str]:
    """
    Render subject, plain text, and HTML for a transactional email.

    Returns:
        (subject, body_text, body_html)
    """
    meta = TEMPLATE_REGISTRY.get(template_id)
    if not meta:
        raise ValueError(f"Unknown email template_id: {template_id}")

    ctx: dict[str, Any] = {"brand": _brand_context()}
    for key in ("preheader", "tone", "eyebrow", "heading"):
        if key in meta:
            ctx[key] = meta[key]
    if context:
        ctx.update(context)

    pre = meta.get("preheader")
    if pre and "{" in str(pre):
        ctx["preheader"] = _format_subject(str(pre), ctx)
    elif pre and "preheader" not in ctx:
        ctx["preheader"] = pre

    template = _ENV.get_template(meta["file"])
    body_html = wrap_html_email(template.render(**ctx))
    body_text = render_plain_text(template_id, ctx)
    subject = subject_override or _format_subject(meta["subject"], ctx)
    return subject, body_text, body_html


def render_plain_text(template_id: str, ctx: dict[str, Any]) -> str:
    """Plain-text counterpart for inbox clients that prefer text."""
    first = ctx.get("first_name") or "there"
    lines = [f"Hi {first},"]

    if template_id == "otp":
        lines.append("")
        intro = (ctx.get("intro_line") or "Enter this code to finish signing in.").strip()
        lines.append(intro)
        lines.append("")
        lines.append(f"Your one-time code is: {ctx.get('otp_code', '')}")
        lines.append(f"Expires in {ctx.get('otp_expires', '')}.")
        warn = (ctx.get("otp_warn") or "").strip()
        if warn:
            lines.append("")
            lines.append(warn)
    elif template_id == "password_reset":
        lines.append("")
        lines.append("We received a request to reset your password. Enter the code below to continue.")
        lines.append("")
        lines.append(f"Your one-time code is: {ctx.get('otp_code', '')}")
        lines.append(f"Expires in {ctx.get('otp_expires', '')}.")
        warn = (ctx.get("otp_warn") or "").strip()
        if warn:
            lines.append("")
            lines.append(warn)
    elif template_id == "mention":
        lines.append("")
        lines.append(
            f"{ctx.get('actor_name', 'Someone')} mentioned you on "
            f"\"{ctx.get('document_name', 'a document')}\"."
        )
        excerpt = (ctx.get("comment_excerpt") or "").strip()
        if excerpt:
            lines.append("")
            lines.append(f"Comment:\n{excerpt}")
        url = (ctx.get("comment_url") or "").strip()
        if url:
            lines.append("")
            lines.append(f"View comment: {url}")
    elif template_id.startswith("workflow_"):
        lines.append("")
        intro = (ctx.get("intro_line") or "").strip()
        if intro:
            lines.append(intro)
        note = (ctx.get("reviewer_note") or "").strip()
        if note:
            lines.append("")
            lines.append(f"Note:\n{note}")
        fs = ctx.get("from_stage_label") or ""
        ts = ctx.get("to_stage_label") or ""
        if fs and ts:
            lines.append("")
            lines.append(f"Stage: {fs} -> {ts}")
        for key in ("review_url", "edit_url", "document_url", "published_url"):
            url = (ctx.get(key) or "").strip()
            if url:
                label = key.replace("_", " ").title()
                lines.append(f"{label}: {url}")
                break
    elif template_id == "welcome":
        lines.append("")
        lines.append(
            f"An account has been created for you as {ctx.get('role_name', 'a ComplyCore user')}."
        )
        lines.append(f"Email: {ctx.get('account_email', '')}")
        lines.append(f"Temporary password: {ctx.get('temp_password', '')}")
        lines.append("")
        lines.append(f"Sign in: {ctx.get('login_url', '')}")
        sub = (ctx.get("cta_sub") or "").strip()
        if sub:
            lines.append("")
            lines.append(sub)
    elif template_id == "password_changed":
        lines.append("")
        lines.append("Your ComplyCore password was changed.")
        lines.append(f"When: {ctx.get('changed_at', '')}")
        lines.append(f"Account: {ctx.get('account_email', '')}")
        url = (ctx.get("profile_url") or "").strip()
        if url:
            lines.append(f"Account settings: {url}")
        sub = (ctx.get("cta_sub") or "").strip()
        if sub:
            lines.append("")
            lines.append(sub)
    elif template_id == "document_published":
        lines.append("")
        lines.append(
            f"{ctx.get('document_name', 'Your document')} has been published."
        )
        for label, key in (
            ("Published on", "publish_date"),
            ("Final version", "version_label"),
        ):
            val = (ctx.get(key) or "").strip()
            if val:
                lines.append(f"{label}: {val}")
        url = (ctx.get("published_url") or "").strip()
        if url:
            lines.append(f"View document: {url}")
    elif template_id == "workflow_submission_received":
        lines.append("")
        lines.append(
            f"Thanks — {ctx.get('document_name', 'Your document')} has entered the review workflow."
        )
        fs = ctx.get("from_stage_label") or ""
        ts = ctx.get("to_stage_label") or ""
        if fs and ts:
            lines.append(f"Stage: {fs} -> {ts}")
        submitted = (ctx.get("submitted_at") or "").strip()
        if submitted:
            lines.append(f"Submitted on: {submitted}")
        url = (ctx.get("document_url") or "").strip()
        if url:
            lines.append(f"View status: {url}")
    elif template_id == "collab_document_uploaded":
        lines.append("")
        doc = ctx.get("document_name") or "Your document"
        ver = (ctx.get("version_label") or "").strip()
        if ver:
            lines.append(f"You uploaded {doc} (version {ver}).")
        else:
            lines.append(f"You uploaded {doc}.")
        url = (ctx.get("document_url") or "").strip()
        if url:
            lines.append(f"Open document: {url}")
    else:
        lines.append("")
        lines.append("Please view this message in an HTML-capable email client.")

    lines.append("")
    lines.append("-- ComplyCore")
    return "\n".join(lines)


def build_otp_context(
    *,
    recipient_name: str,
    otp: str,
    expire_minutes: int,
    intro_line: str | None = None,
    template_id: str = "otp",
) -> dict[str, Any]:
    """Shared context for login OTP and password-reset code emails."""
    expires = humanize_minutes(expire_minutes)
    if template_id == "password_reset":
        default_intro = None
        warn = (
            "If you didn't request a password reset, your password has not been changed. "
            "Don't share this code, and contact your administrator to flag this attempt."
        )
        preheader = f"Use this code to reset your password - expires in {expires}."
    else:
        default_intro = "Enter this code to finish signing in."
        warn = (
            "Never share this code with anyone - ComplyCore staff will never ask for it. "
            "If you didn't request this code, contact your administrator immediately."
        )
        preheader = f"Your one-time code is inside - expires in {expires}."

    return {
        "first_name": title_case_first_name(recipient_name),
        "intro_line": (intro_line or default_intro or "").strip(),
        "otp_code": format_otp_display(otp),
        "otp_expires": expires,
        "otp_warn": warn,
        "preheader": preheader,
    }


def build_mention_context(
    *,
    recipient_name: str,
    actor_name: str,
    document_name: str,
    comment_excerpt: str,
    doc_id: str,
    org_slug: str | None = None,
    comment_id: str | None = None,
) -> dict[str, Any]:
    return {
        "first_name": title_case_first_name(recipient_name),
        "actor_name": (actor_name or "Someone").strip(),
        "document_name": (document_name or "Document").strip(),
        "comment_excerpt": _truncate_excerpt(comment_excerpt),
        "comment_url": get_document_comment_url(
            doc_id,
            org_slug=org_slug,
            comment_id=comment_id,
        ),
        "cta_label": "View comment",
    }


def resolve_submission_route(stage: str | None) -> str:
    """Map post-classification workflow stage to submission-received copy variant."""
    key = (stage or "").strip().lower()
    if key == "marketing_review":
        return "ai"
    if key == "compliance_review":
        return "compliance"
    return "sme"


def submission_route_stage_labels(route: str) -> tuple[str, str]:
    """Return (to_stage_label, current_stage_label) for submission-received emails."""
    key = (route or "sme").strip().lower()
    if key == "ai":
        return "AI Analysis", "AI Analysis"
    if key == "compliance":
        return "Compliance Review", "Compliance Review"
    return "SME Review", "SME Review"


def build_submission_received_context(
    *,
    recipient_name: str,
    document_name: str,
    doc_id: str,
    route: str,
    submitted_at: datetime | None = None,
    org_slug: str | None = None,
) -> dict[str, Any]:
    doc = (document_name or "Document").strip()
    to_label, current_stage = submission_route_stage_labels(route)
    submitted_display = format_email_timestamp(submitted_at)
    return {
        "first_name": title_case_first_name(recipient_name),
        "document_name": doc,
        "from_stage_label": "Document Upload",
        "to_stage_label": to_label,
        "current_stage_label": current_stage,
        "submitted_at": submitted_display,
        "document_url": get_document_detail_url(doc_id, org_slug=org_slug),
        "cta_label": "View status",
        "info_rows": [
            {"label": "Document", "value": html.escape(doc)},
            {"label": "Submitted on", "value": submitted_display},
            {"label": "Current stage", "value": current_stage},
        ],
    }


def build_collab_document_uploaded_context(
    *,
    recipient_name: str,
    document_name: str,
    doc_id: str,
    version_label: str | None = None,
    org_slug: str | None = None,
) -> dict[str, Any]:
    doc = (document_name or "Document").strip()
    ver = (version_label or "").strip()
    rows: list[dict[str, str]] = [
        {"label": "Document", "value": html.escape(doc)},
    ]
    if ver:
        rows.append({"label": "Version", "value": html.escape(ver)})
    rows.append({"label": "Stage", "value": "Document Upload"})
    return {
        "first_name": title_case_first_name(recipient_name),
        "document_name": doc,
        "version_label": ver,
        "document_url": get_document_detail_url(doc_id, org_slug=org_slug),
        "cta_label": "Open document",
        "info_rows": rows,
    }


def build_workflow_context(
    template_id: str,
    *,
    recipient_name: str,
    document_name: str,
    actor_name: str,
    from_stage: str,
    to_stage: str,
    doc_id: str,
    org_slug: str | None = None,
    reviewer_note: str | None = None,
) -> dict[str, Any]:
    """Context for Phase 2 workflow transactional emails."""
    doc = (document_name or "Document").strip()
    actor = (actor_name or "A reviewer").strip()
    note = _truncate_note(reviewer_note)
    revisions = template_id in ("workflow_sme_changes", "workflow_compliance_changes")

    ctx: dict[str, Any] = {
        "first_name": title_case_first_name(recipient_name),
        "actor_name": actor,
        "document_name": doc,
        "from_stage_label": humanize_stage(from_stage),
        "to_stage_label": humanize_stage(to_stage, revisions=revisions),
        "reviewer_note": note,
        "document_url": get_document_detail_url(doc_id, org_slug=org_slug),
        "review_url": get_document_review_url(doc_id, org_slug=org_slug),
        "edit_url": get_document_edit_url(doc_id, org_slug=org_slug),
    }

    if template_id == "workflow_to_sme":
        ctx["from_stage_label"] = "Marketing"
        ctx["to_stage_label"] = "SME Review"
        ctx["intro_line"] = (
            f"{doc} has been submitted by {actor} and assigned to you for SME review."
        )
        ctx["cta_label"] = "Start review"
    elif template_id == "workflow_sme_changes":
        ctx["intro_line"] = (
            f"{actor} reviewed {doc} and requested changes before it can proceed."
        )
        ctx["cta_label"] = "Make changes"
    elif template_id == "workflow_sme_reject":
        ctx["intro_line"] = f"{actor} rejected {doc} at SME review."
        ctx["cta_label"] = "View document"
    elif template_id == "workflow_sme_approve":
        ctx["from_stage_label"] = "SME Review"
        ctx["to_stage_label"] = "AI Analysis"
        ctx["intro_line"] = f"{doc} passed SME review by {actor} and is moving on."
        ctx["cta_label"] = "View document"
    elif template_id == "workflow_to_compliance":
        ctx["from_stage_label"] = "Marketing"
        ctx["to_stage_label"] = "Compliance Review"
        ctx["intro_line"] = (
            f"{doc} has been assigned for compliance review."
        )
        ctx["cta_label"] = "Start compliance review"
    elif template_id == "workflow_compliance_approve":
        ctx["from_stage_label"] = "Compliance Review"
        ctx["to_stage_label"] = "Ready to publish"
        ctx["intro_line"] = f"{doc} has been approved by {actor} in compliance review."
        ctx["cta_label"] = "View document"
    elif template_id == "workflow_compliance_changes":
        ctx["intro_line"] = (
            f"{actor} reviewed {doc} and requested changes before it can be published."
        )
        ctx["cta_label"] = "Make changes"
    elif template_id == "workflow_compliance_reject":
        ctx["intro_line"] = f"{actor} rejected {doc} at compliance review."
        ctx["cta_label"] = "View document"
    else:
        ctx["intro_line"] = f"{doc} moved from {ctx['from_stage_label']} to {ctx['to_stage_label']}."

    return ctx


def resolve_workflow_template_id(
    from_stage: str,
    to_stage: str,
    *,
    workflow_action: str | None = None,
    email_template_id: str | None = None,
) -> str | None:
    """Map a workflow transition to a Phase 2 template id, or None for generic mail."""
    if email_template_id:
        return email_template_id
    fs = (from_stage or "").strip().lower()
    ts = (to_stage or "").strip().lower()
    action = (workflow_action or "").strip().lower()
    if fs == "document_upload" and ts == "sme_review":
        return "workflow_to_sme"
    if fs == "sme_review" and ts == "marketing_review" and action == "request_changes":
        return "workflow_sme_changes"
    if fs == "sme_review" and ts == "marketing_review" and action == "approve":
        return "workflow_sme_approve"
    if fs == "sme_review" and ts == "rejected":
        return "workflow_sme_reject"
    if fs == "marketing_review" and ts == "compliance_review":
        return "workflow_to_compliance"
    if fs == "compliance_review" and ts == "marketing_review" and action == "request_changes":
        return "workflow_compliance_changes"
    if fs == "compliance_review" and ts == "rejected":
        return "workflow_compliance_reject"
    if fs == "compliance_review" and ts == "approved" and action == "approve":
        return "workflow_compliance_approve"
    return None


def build_welcome_context(
    *,
    recipient_name: str,
    account_email: str,
    temp_password: str,
    role_name: str,
) -> dict[str, Any]:
    esc = html.escape
    return {
        "first_name": title_case_first_name(recipient_name),
        "role_name": humanize_role_name(role_name),
        "account_email": account_email,
        "temp_password": temp_password,
        "info_rows": [
            {"label": "Email", "value": esc(account_email)},
            {
                "label": "Temporary password",
                "value": (
                    f'<span style="font-family:ui-monospace,Menlo,monospace;">'
                    f"{esc(temp_password)}</span>"
                ),
            },
        ],
        "login_url": get_login_url(),
        "cta_label": "Sign in to ComplyCore",
        "cta_sub": "For your security, change this password after you sign in.",
    }


def build_password_changed_context(
    *,
    recipient_name: str,
    account_email: str,
    changed_at: datetime | None = None,
    org_slug: str | None = None,
) -> dict[str, Any]:
    esc = html.escape
    when = format_email_timestamp(changed_at)
    return {
        "first_name": title_case_first_name(recipient_name),
        "account_email": account_email,
        "changed_at": when,
        "info_rows": [
            {"label": "When", "value": esc(when)},
            {"label": "Account", "value": esc(account_email)},
        ],
        "profile_url": get_profile_url(org_slug=org_slug),
        "cta_label": "Open account settings",
        "cta_sub": (
            "Didn't do this? Open your account settings and change your password again right away."
        ),
    }


def build_document_published_context(
    *,
    recipient_name: str,
    document_name: str,
    doc_id: str,
    version_label: str,
    published_at: datetime | None = None,
    org_slug: str | None = None,
) -> dict[str, Any]:
    esc = html.escape
    when = format_email_timestamp(published_at)
    doc = (document_name or "Document").strip()
    version = (version_label or "1.0").strip()
    return {
        "first_name": title_case_first_name(recipient_name),
        "document_name": doc,
        "from_stage_label": "Compliance Review",
        "to_stage_label": "Published",
        "publish_date": when,
        "version_label": version,
        "info_rows": [
            {"label": "Document", "value": esc(doc)},
            {"label": "Published on", "value": esc(when)},
            {"label": "Final version", "value": esc(version)},
        ],
        "published_url": get_published_document_url(doc_id, org_slug=org_slug),
        "cta_label": "View published document",
    }
