import os
import html
import logging
from pathlib import Path

from dotenv import dotenv_values, load_dotenv
import boto3
from botocore.exceptions import ClientError

from datetime import datetime

from apis.core.email_renderer import (
    build_collab_document_uploaded_context,
    build_document_published_context,
    build_mention_context,
    build_otp_context,
    build_password_changed_context,
    build_submission_received_context,
    build_welcome_context,
    build_workflow_context,
    humanize_stage,
    render_email,
)

logger = logging.getLogger(__name__)

# Load backend .env, then prefer repo-root SES_SOURCE_EMAIL (Celery cwd often loads backend first).
_MAIL_DIR = Path(__file__).resolve().parent
_AI_ENV = _MAIL_DIR.parents[1] / ".env"
_REPO_ENV = _MAIL_DIR.parents[2] / ".env"
if _AI_ENV.exists():
    load_dotenv(_AI_ENV, override=False)
if _REPO_ENV.exists():
    repo_ses = (dotenv_values(_REPO_ENV).get("SES_SOURCE_EMAIL") or "").strip()
    if repo_ses:
        os.environ["SES_SOURCE_EMAIL"] = repo_ses

# OTP TTL for custom email MFA (must match frontend countdown; see OTP_EXPIRE_MINUTES in .env)
OTP_EXPIRE_MINUTES = int(os.getenv("OTP_EXPIRE_MINUTES", "1"))

# Initialize SES client outside verifying credentials availability
# Boto3 will look for credentials in env vars or ~/.aws/credentials
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
ses_client = boto3.client("ses", region_name=AWS_REGION)

def _ensure_ses_email_identity(source_email: str) -> None:
    """
    Trigger SES email identity verification if the Source identity isn't verified.

    Note: SES verification is asynchronous; after triggering, you must check the
    destination inbox for a verification link before sending will succeed.
    """
    source_email = (source_email or "").strip()
    if not source_email:
        return

    try:
        attrs = ses_client.get_identity_verification_attributes(Identities=[source_email])
        ver_attrs = attrs.get("VerificationAttributes", {}) or {}
        st = ver_attrs.get(source_email, {}).get("VerificationStatus")
        if st == "Success":
            return
    except Exception:
        # If checking fails, still attempt to request verification.
        logger.exception("SES: failed checking verification status; will attempt re-verify")

    try:
        ses_client.verify_email_identity(EmailAddress=source_email)
        logger.info("SES: verification requested for %s (check inbox to complete)", source_email)
        # Best-effort: log latest verification status after requesting.
        try:
            attrs = ses_client.get_identity_verification_attributes(Identities=[source_email])
            ver_attrs = attrs.get("VerificationAttributes", {}) or {}
            st = ver_attrs.get(source_email, {}).get("VerificationStatus")
            logger.info("SES: post-request verification status=%s for %s", st, source_email)
        except Exception:
            logger.exception("SES: failed to re-check verification status for %s", source_email)
    except Exception:
        logger.exception("SES: failed to request verification for %s", source_email)

def send_otp_sync(recipient: str, otp: str, subject: str = "Your OTP"):
    """Synchronous function to send OTP via AWS SES. Should be run in an executor."""
    sender = os.getenv("SES_SOURCE_EMAIL")
    if not sender:
        logger.warning("SES_SOURCE_EMAIL not set. Skipping email sending.")
        logger.info(f"OTP for {recipient}: {otp}")
        return

    body_text = f"Your one-time code is: {otp}. It expires in {OTP_EXPIRE_MINUTES} minutes."
    body_html = f"""<html>
<head></head>
<body>
  <h1>One-Time Password</h1>
  <p>Your verification code is: <strong>{otp}</strong></p>
  <p>This code expires in {OTP_EXPIRE_MINUTES} minutes.</p>
</body>
</html>
            """

    try:
        response = ses_client.send_email(
            Source=sender,
            Destination={
                'ToAddresses': [recipient],
            },
            Message={
                'Subject': {
                    'Data': subject,
                    'Charset': 'UTF-8'
                },
                'Body': {
                    'Text': {
                        'Data': body_text,
                        'Charset': 'UTF-8'
                    },
                    'Html': {
                        'Data': body_html,
                        'Charset': 'UTF-8'
                    }
                }
            }
        )
        logger.info(f"Email sent! Message ID: {response['MessageId']}")
    except ClientError as e:
        logger.error(f"SES ClientError: {e.response['Error']['Message']}")
    except Exception as e:
        logger.error(f"Failed to send email via SES: {e}")


def send_transactional_email_sync(
    *,
    to_email: str,
    template_id: str,
    context: dict | None = None,
    subject_override: str | None = None,
) -> None:
    """Send a branded transactional email via SES (HTML + plain text)."""
    subject, body_text, body_html = render_email(
        template_id,
        context,
        subject_override=subject_override,
    )
    sender = os.getenv("SES_SOURCE_EMAIL")
    if not sender:
        logger.error(
            "SES_SOURCE_EMAIL not set. Cannot send %s email to %s",
            template_id,
            to_email,
        )
        return

    try:
        ses_client.send_email(
            Source=sender,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": body_text, "Charset": "UTF-8"},
                    "Html": {"Data": body_html, "Charset": "UTF-8"},
                },
            },
        )
        logger.info(
            "Transactional email sent template=%s to=%s from=%s",
            template_id,
            to_email,
            sender,
        )
    except ClientError as e:
        err_code = e.response.get("Error", {}).get("Code")
        err_msg = e.response.get("Error", {}).get("Message") or str(e)
        logger.error(
            "SES send failed template=%s code=%s msg=%s sender=%s to=%s",
            template_id,
            err_code,
            err_msg,
            sender,
            to_email,
        )
        if err_code == "MessageRejected" and "not verified" in err_msg.lower():
            _ensure_ses_email_identity(sender)
    except Exception:
        logger.exception(
            "SES send failed unexpectedly template=%s to=%s",
            template_id,
            to_email,
        )


def send_mfa_otp_email_sync(
    *,
    to_email: str,
    recipient_name: str,
    otp: str,
    subject: str | None = None,
    intro_line: str | None = None,
    template_id: str | None = None,
) -> None:
    """
    Send MFA/OTP email via AWS SES using ComplyCore templates.
    template_id: ``otp`` (login) or ``password_reset``; inferred from subject when omitted.
    """
    resolved_template = template_id
    if not resolved_template:
        subj_lower = (subject or "").lower()
        if "reset" in subj_lower or "password" in subj_lower:
            resolved_template = "password_reset"
        else:
            resolved_template = "otp"

    expire_minutes = OTP_EXPIRE_MINUTES
    if resolved_template == "password_reset":
        expire_minutes = int(os.getenv("PASSWORD_RESET_OTP_EXPIRE_MINUTES", "10"))

    ctx = build_otp_context(
        recipient_name=recipient_name or to_email,
        otp=otp,
        expire_minutes=expire_minutes,
        intro_line=intro_line,
        template_id=resolved_template,
    )
    send_transactional_email_sync(
        to_email=to_email,
        template_id=resolved_template,
        context=ctx,
        subject_override=subject,
    )


def send_welcome_email_sync(
    *,
    to_email: str,
    recipient_name: str,
    temp_password: str,
    role_name: str,
) -> None:
    """Welcome email after admin provisions a new user."""
    ctx = build_welcome_context(
        recipient_name=recipient_name or to_email,
        account_email=to_email,
        temp_password=temp_password,
        role_name=role_name,
    )
    send_transactional_email_sync(
        to_email=to_email,
        template_id="welcome",
        context=ctx,
    )


def send_password_changed_email_sync(
    *,
    to_email: str,
    recipient_name: str,
    org_slug: str | None = None,
) -> None:
    """Security confirmation after the user changes their password."""
    from datetime import datetime, timezone

    ctx = build_password_changed_context(
        recipient_name=recipient_name or to_email,
        account_email=to_email,
        changed_at=datetime.now(timezone.utc),
        org_slug=org_slug,
    )
    send_transactional_email_sync(
        to_email=to_email,
        template_id="password_changed",
        context=ctx,
    )


def send_submission_received_email_sync(
    *,
    to_email: str,
    recipient_name: str,
    document_name: str,
    doc_id: str,
    route: str,
    submitted_at: datetime | None = None,
    org_slug: str | None = None,
) -> None:
    """Notify document author after in-scope classification."""
    ctx = build_submission_received_context(
        recipient_name=recipient_name or to_email,
        document_name=document_name,
        doc_id=doc_id,
        route=route,
        submitted_at=submitted_at,
        org_slug=org_slug,
    )
    send_transactional_email_sync(
        to_email=to_email,
        template_id="workflow_submission_received",
        context=ctx,
    )


def send_collab_document_uploaded_email_sync(
    *,
    to_email: str,
    recipient_name: str,
    document_name: str,
    doc_id: str,
    version_label: str | None = None,
    org_slug: str | None = None,
) -> None:
    """Notify document author when a new version (v2+) is uploaded."""
    ctx = build_collab_document_uploaded_context(
        recipient_name=recipient_name or to_email,
        document_name=document_name,
        doc_id=doc_id,
        version_label=version_label,
        org_slug=org_slug,
    )
    send_transactional_email_sync(
        to_email=to_email,
        template_id="collab_document_uploaded",
        context=ctx,
    )


def send_document_published_email_sync(
    *,
    to_email: str,
    recipient_name: str,
    document_name: str,
    doc_id: str,
    version_label: str,
    org_slug: str | None = None,
    published_at=None,
) -> None:
    """Notify document author when marketing publishes."""
    ctx = build_document_published_context(
        recipient_name=recipient_name or to_email,
        document_name=document_name,
        doc_id=doc_id,
        version_label=version_label,
        published_at=published_at,
        org_slug=org_slug,
    )
    send_transactional_email_sync(
        to_email=to_email,
        template_id="document_published",
        context=ctx,
    )


def send_mention_notification_email(
    *,
    to_email: str,
    recipient_name: str,
    author_name: str,
    document_title: str,
    comment_preview: str,
    doc_id: str,
    org_slug: str | None = None,
    comment_id: str | None = None,
    open_url: str | None = None,
) -> None:
    """Notify a user they were @mentioned in a document review comment."""
    ctx = build_mention_context(
        recipient_name=recipient_name or to_email,
        actor_name=author_name,
        document_name=document_title,
        comment_excerpt=comment_preview,
        doc_id=doc_id,
        org_slug=org_slug,
        comment_id=comment_id,
    )
    if open_url:
        ctx["comment_url"] = open_url
    send_transactional_email_sync(
        to_email=to_email,
        template_id="mention",
        context=ctx,
    )


def send_social_monitoring_post_email(
    *,
    to_email: str,
    content_type: str,
    platform: str,
    author_name: str,
    post_url: str,
    post_full_text: str,
    ai_findings: list,
) -> None:
    """
    Send social-monitoring per-post email.
    """
    subject = f"[Social Monitoring] {platform} post analyzed"

    esc = html.escape
    safe_content_type = esc(content_type or "")
    safe_platform = esc(platform or "")
    safe_author = esc(author_name or "")
    safe_post_url = esc(post_url or "", quote=True)
    safe_full_post = esc(post_full_text or "")

    def norm_severity(raw: str) -> str:
        u = (raw or "").strip().upper()
        if u in {"HIGH", "MEDIUM", "LOW"}:
            return u
        return "LOW"

    def severity_styles(sev: str) -> dict:
        # Approximation of UI FindingCard styles, adapted for email-safe inline CSS.
        if sev == "HIGH":
            return {
                "cardBorder": "rgba(255, 131, 43, 0.40)",
                "badgeBorder": "#FF832B",
                "badgeText": "#FF832B",
            }
        if sev == "MEDIUM":
            return {
                "cardBorder": "rgba(241, 194, 27, 0.40)",
                "badgeBorder": "#F1C21B",
                "badgeText": "#B45309",
            }
        return {
            "cardBorder": "rgba(91, 192, 235, 0.40)",
            "badgeBorder": "#5BC0EB",
            "badgeText": "#0369A1",
        }

    ai_findings = ai_findings or []
    if not ai_findings:
        cards_html = (
            '<p style="margin:0;padding:18px 0;text-align:center;font-family:Arial,Helvetica,sans-serif;color:#6b7280;font-size:14px;">No findings — post is compliant.</p>'
        )
    else:
        finding_cards = []
        for f in ai_findings:
            title = esc(str(f.get("title") or "Compliance Finding"))
            rule_code = esc(str(f.get("rule_code") or "").strip())
            sev = norm_severity(str(f.get("risk_level") or f.get("severity") or "LOW"))
            styles = severity_styles(sev)
            badge_label = sev.title()

            description = esc(str(f.get("description") or f.get("summary") or "").strip())
            why_risky = esc(str(f.get("why_risky") or "").strip())
            rationale = esc(str(f.get("rationale") or f.get("rule_rationale") or "").strip())
            ai_suggestion = esc(
                str(f.get("ai_suggestion") or f.get("suggestedAlternative") or f.get("alternate_suggestion") or "").strip()
            )

            rule_line_html = (
                f'<p style="margin:0;font-size:12px;color:#128BDA;">{rule_code}</p>' if rule_code else ""
            )

            finding_cards.append(
                f"""
        <div style="border:1px solid {styles['cardBorder']};border-radius:16px;background:#ffffff;padding:20px;margin:10px 0;">
          <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;">
            <div>
              <p style="margin:0 0 6px 0;font-size:14px;font-weight:700;color:#111827;font-family:Arial,Helvetica,sans-serif;">{title}</p>
              {rule_line_html}
            </div>
            <span style="display:inline-flex;align-items:center;gap:6px;border:1px solid {styles['badgeBorder']};background:#ffffff;color:{styles['badgeText']};border-radius:9999px;padding:4px 10px;font-size:12px;font-weight:700;font-family:Arial,Helvetica,sans-serif;">
              <span style="font-size:12px;line-height:1;color:{styles['badgeText']};">&#9888;</span>
              {badge_label}
            </span>
          </div>

          <div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:14px;">
            <div style="flex:1;min-width:200px;">
              <p style="margin:0 0 6px 0;font-size:12px;font-weight:700;color:#111827;font-family:Arial,Helvetica,sans-serif;">Description</p>
              <p style="margin:0;font-size:12px;color:#6b7280;line-height:1.55;font-family:Arial,Helvetica,sans-serif;">{description or "-"}</p>
            </div>
            <div style="flex:1;min-width:200px;">
              <p style="margin:0 0 6px 0;font-size:12px;font-weight:700;color:#111827;font-family:Arial,Helvetica,sans-serif;">Why This Is Risky</p>
              <p style="margin:0;font-size:12px;color:#6b7280;line-height:1.55;font-family:Arial,Helvetica,sans-serif;">{why_risky or "-"}</p>
            </div>
            <div style="flex:1;min-width:200px;">
              <p style="margin:0 0 6px 0;font-size:12px;font-weight:700;color:#111827;font-family:Arial,Helvetica,sans-serif;">Regulatory Rationale</p>
              <p style="margin:0;font-size:12px;color:#6b7280;line-height:1.55;font-family:Arial,Helvetica,sans-serif;">{rationale or "-"}</p>
            </div>
          </div>

          <div style="margin-top:16px;border-radius:10px;border:1px solid rgba(0,0,0,0.07);background:#F7F8F9;padding:12px 14px;">
            <p style="margin:0 0 6px 0;display:flex;align-items:center;gap:8px;font-size:12px;font-weight:700;color:#111827;font-family:Arial,Helvetica,sans-serif;">
              AI Suggested Alternative
            </p>
            <p style="margin:0;font-size:12px;color:#6b7280;line-height:1.55;font-family:Arial,Helvetica,sans-serif;">{ai_suggestion or "-"}</p>
          </div>
        </div>
""".strip()
            )

        cards_html = "\n".join(finding_cards)

    body_text = (
        "Social monitoring detected and analyzed a post.\n\n"
        f"Platform: {platform}\n"
        f"Content Type: {content_type}\n"
        f"Author: {author_name}\n"
        f"Post URL: {post_url}\n\n"
        "Full Post:\n"
        f"{post_full_text or 'N/A'}\n\n"
        "AI findings:\n"
        + (
            "\n".join(
                [
                    f"- {f.get('title') or 'Finding'} (Risk {f.get('risk_level') or 'LOW'})\n"
                    f"  Why This Is Risky: {f.get('why_risky') or ''}\n"
                    f"  Regulatory Rationale: {f.get('rationale') or ''}\n"
                    f"  AI Suggested Alternative: {f.get('ai_suggestion') or ''}"
                    for f in (ai_findings or [])
                ]
            )
            if ai_findings
            else "No findings."
        )
    )

    body_html = f"""<html><body style="margin:0;padding:0;background:#f6f8fb;">
  <div style="max-width:680px;margin:0 auto;padding:18px;">
    <div style="background:#ffffff;border-radius:14px;padding:22px 22px 18px 22px;box-shadow:0 1px 2px rgba(0,0,0,0.06);">
      <h2 style="margin:0 0 12px 0;font-family:Arial,Helvetica,sans-serif;color:#111827;">Social Monitoring Report</h2>
      <p style="margin:0 0 14px 0;font-family:Arial,Helvetica,sans-serif;color:#374151;">
        <strong>Platform:</strong> {safe_platform}
        <span style="color:#9ca3af;">&nbsp;|&nbsp;</span>
        <strong>Content Type:</strong> {safe_content_type}
      </p>

      <div style="background:#f3f4f6;border-radius:12px;padding:14px 16px;margin:12px 0;">
        <p style="margin:0 0 8px 0;font-family:Arial,Helvetica,sans-serif;color:#111827;">
          <strong>Author:</strong> {safe_author or "-"}
        </p>
        <p style="margin:0;font-family:Arial,Helvetica,sans-serif;color:#111827;">
          <strong>Post:</strong>
          <a href="{safe_post_url}" style="color:#2563eb;text-decoration:none;">View on LinkedIn</a>
        </p>
      </div>

      <h3 style="margin:16px 0 10px 0;font-family:Arial,Helvetica,sans-serif;color:#111827;">Full Post</h3>
      <div style="border:1px solid #e5e7eb;border-radius:12px;background:#f9fafb;padding:12px 14px;">
        <pre style="margin:0;white-space:pre-wrap;font-family:Arial,Helvetica,sans-serif;line-height:1.45;color:#111827;">{safe_full_post or "N/A"}</pre>
      </div>

      <h3 style="margin:18px 0 10px 0;font-family:Arial,Helvetica,sans-serif;color:#111827;">AI Findings</h3>
      {cards_html}
    </div>
    <p style="margin:14px 0 0 0;text-align:center;font-family:Arial,Helvetica,sans-serif;color:#9ca3af;font-size:12px;">
      This email is generated by the social profile monitoring digest.
    </p>
  </div>
</body></html>"""

    sender = os.getenv("SES_SOURCE_EMAIL")
    if sender:
        try:
            ses_client.send_email(
                Source=sender,
                Destination={"ToAddresses": [to_email]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": body_text, "Charset": "UTF-8"},
                        "Html": {"Data": body_html, "Charset": "UTF-8"},
                    },
                },
            )
            logger.info("Social monitoring email sent via SES to %s", to_email)
            return
        except Exception as e:
            logger.error("Failed social monitoring email via SES: %s", e)

    logger.warning("No SES_SOURCE_EMAIL configured for social monitoring email to %s", to_email)


def send_workflow_stage_email_sync(
    *,
    to_email: str,
    recipient_name: str,
    document_title: str,
    from_stage: str,
    to_stage: str,
    open_url: str,
    template_id: str | None = None,
    actor_name: str | None = None,
    reviewer_note: str | None = None,
    doc_id: str | None = None,
    org_slug: str | None = None,
) -> None:
    """
    Send workflow transition email (branded template when ``template_id`` is set).
    """
    if template_id and doc_id:
        ctx = build_workflow_context(
            template_id,
            recipient_name=recipient_name or to_email,
            document_name=document_title,
            actor_name=actor_name or "A reviewer",
            from_stage=from_stage,
            to_stage=to_stage,
            doc_id=doc_id,
            org_slug=org_slug,
            reviewer_note=reviewer_note,
        )
        if open_url:
            if template_id in ("workflow_to_sme",):
                ctx["review_url"] = open_url
            elif template_id.endswith("_changes"):
                ctx["edit_url"] = open_url
            else:
                ctx["document_url"] = open_url
        send_transactional_email_sync(
            to_email=to_email,
            template_id=template_id,
            context=ctx,
        )
        return

    esc = html.escape
    safe_name = esc(recipient_name or to_email.split("@")[0])
    safe_doc = esc(document_title or "Document")
    from_label = humanize_stage(from_stage)
    to_label = humanize_stage(to_stage)
    safe_from = esc(from_label)
    safe_to = esc(to_label)

    subject = f"Workflow update: {document_title} -> {to_label}"
    body_text = (
        f"Hi {recipient_name or to_email},\n\n"
        f"'{document_title}' moved from {from_label} to {to_label}.\n"
    )
    if open_url:
        body_text += f"\nOpen: {open_url}\n"
    body_html = f"""<html><body>
  <p>Hi {safe_name},</p>
  <p><strong>{safe_doc}</strong> moved from <strong>{safe_from}</strong> to <strong>{safe_to}</strong>.</p>
</body></html>"""

    sender = os.getenv("SES_SOURCE_EMAIL")
    if not sender:
        logger.warning("No SES_SOURCE_EMAIL configured for workflow transition email to %s", to_email)
        return
    try:
        ses_client.send_email(
            Source=sender,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": body_text, "Charset": "UTF-8"},
                    "Html": {"Data": body_html, "Charset": "UTF-8"},
                },
            },
        )
        logger.info("Workflow transition email (generic) sent via SES to %s", to_email)
    except Exception as e:
        logger.error("Failed workflow transition email via SES: %s", e)


def send_support_email_sync(
    *,
    user_name: str,
    user_email: str,
    tenant_name: str,
    timestamp: str,
    description: str,
    file_bytes: bytes | None = None,
    file_name: str | None = None,
) -> None:
    """Send support / issue report email to info@complycore.ca via SES."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication

    sender = os.getenv("SES_SOURCE_EMAIL")
    if not sender:
        logger.warning("SES_SOURCE_EMAIL not set. Skipping support email sending.")
        logger.info("Support request from %s (%s) - tenant: %s. Description: %s", user_name, user_email, tenant_name, description)
        return

    recipient = "info@complycore.ca"
    subject = f"Support Request: Issue Reported by {user_name}"

    # Construct email
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    body_text = f"""Support Request Details:
------------------------
Reporter Name: {user_name}
Reporter Email: {user_email}
Organization/Tenant: {tenant_name}
Date & Time: {timestamp} (UTC)

Description of the Issue:
-------------------------
{description}
"""
    msg.attach(MIMEText(body_text, "plain"))

    if file_bytes and file_name:
        part = MIMEApplication(file_bytes)
        part.add_header("Content-Disposition", "attachment", filename=file_name)
        msg.attach(part)

    try:
        response = ses_client.send_raw_email(
            Source=sender,
            Destinations=[recipient],
            RawMessage={"Data": msg.as_string()},
        )
        logger.info("Support email sent successfully! Message ID: %s", response.get("MessageId"))
    except ClientError as e:
        logger.error("SES raw email send failed: %s", e.response.get("Error", {}).get("Code") or str(e))
        raise e
    except Exception as e:
        logger.exception("Failed to send support email via SES raw email")
        raise e

