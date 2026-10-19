import os
from typing import Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form, BackgroundTasks, Query, Request
from fastapi.responses import StreamingResponse, Response
import uuid
import tempfile
import asyncpg
import asyncio
import logging
import io
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from botocore.exceptions import ClientError

from apis.core.security import (
    get_current_user,
    require_app_access_ready,
    assert_app_access_ready,
    require_tenant_context,
    build_tenant_context,
)
from apis.core.encrypted_fields import decode_extracted_text, encode_extracted_text
from apis.services.ai.core.s3_client import save_marketing_doc_versioned
# AI-related imports moved inside functions to support the slim API container
from apis.core.email_links import get_document_detail_url
from apis.core.email_renderer import (
    resolve_submission_route,
    resolve_workflow_template_id,
    submission_route_stage_labels,
)
from apis.core.mail import (
    send_collab_document_uploaded_email_sync,
    send_document_published_email_sync,
    send_submission_received_email_sync,
    send_workflow_stage_email_sync,
)
from apis.services.realtime_streams import publish_notification, check_recent_notification_exists, publish_review_comment
from apis.services.upload_quota import (
    acquire_upload_quota_lock,
    evaluate_upload_quota_change,
    fetch_upload_quota_state,
)

from apis.services.reports import generate_compliance_report  # [Branch 1]
from apis.services.ai.core import s3_client as s3_helper
from apis.services.ai.core import config as ai_config

from apis.core.database import get_db
from apis.models.documents import Document
from apis.v1.routers.audit import log_audit_event, _standardize_stage_name

# Import error logger
from apis.core.error_logger import (
    ErrorLogger, ErrorSeverity, ErrorCategory,
    log_error, log_upload_error, log_ai_error, log_s3_error, 
    log_doc_error, log_validation_error, log_db_error
)

# Global chunker instance removed; using local instantiation in worker
# AI client and services moved inside functions for lazy loading
llm_client = None
classifier_service = None

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger(__name__)


def _tenant_org_super_admin(tenant_ctx: dict) -> bool:
    return (tenant_ctx.get("role_in_org") or "").strip().lower() == "super_admin"


def _raise_upload_quota_exceeded(quota_check: dict) -> None:
    effective = quota_check["effective_quota"]
    usage = quota_check["usage"]
    incoming = quota_check["incoming"]
    projected = quota_check["projected"]
    exceeded = quota_check["would_exceed"]
    remaining = quota_check["remaining"]

    reasons: list[str] = []
    if exceeded["count"]:
        reasons.append("document count limit")
    if exceeded["bytes"]:
        reasons.append("storage size limit")

    message = "Organization upload quota exceeded."
    if reasons:
        message = f"Organization monthly quota exceeded. You have reached your " + " and ".join(reasons) + "."
    raise HTTPException(
        status_code=409,
        detail={
            "code": "ORG_UPLOAD_QUOTA_EXCEEDED",
            "message": message,
            "organization_id": effective["organization_id"],
            "organization_slug": effective.get("organization_slug"),
            "quota": {
                "upload_limit_count": effective["upload_limit_count"],
                "upload_limit_bytes": effective["upload_limit_bytes"],
                "rolling_window_days": effective["rolling_window_days"],
            },
            "usage": {
                "upload_count_used": usage["upload_count_used"],
                "upload_bytes_used": usage["upload_bytes_used"],
            },
            "incoming": {
                "upload_count": incoming["upload_count"],
                "upload_bytes": incoming["upload_bytes"],
            },
            "projected": {
                "upload_count_used": projected["upload_count_used"],
                "upload_bytes_used": projected["upload_bytes_used"],
            },
            "remaining": {
                "upload_count_remaining": remaining["upload_count_remaining"],
                "upload_bytes_remaining": remaining["upload_bytes_remaining"],
            },
            "would_exceed": {
                "count": exceeded["count"],
                "bytes": exceeded["bytes"],
            },
        },
    )


@router.get("/upload-quota")
async def get_upload_quota_state(
    _current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    """Read-only upload quota state for the current tenant/org."""
    organization_id = tenant_ctx["organization_id"]
    return await fetch_upload_quota_state(db, str(organization_id))


def _document_row_to_model(d_dict: dict) -> Document:
    """Normalize DB row dict to Document (shared by get + internal callers)."""
    d_dict["id"] = str(d_dict["id"]) if d_dict.get("id") else None
    d_dict["current_version_id"] = str(d_dict["current_version_id"]) if d_dict.get("current_version_id") else None
    d_dict["submitted_by"] = str(d_dict["submitted_by"]) if d_dict.get("submitted_by") else None
    d_dict["review_id"] = str(d_dict["review_id"]) if d_dict.get("review_id") else None
    d_dict["assigned_to"] = str(d_dict["assigned_to"]) if d_dict.get("assigned_to") else None
    d_dict["assigned_to_name"] = d_dict.get("assigned_to_name")
    d_dict["name"] = _ensure_name_has_extension(d_dict.get("name"), d_dict.pop("version_s3_key", None))
    if d_dict.get("workflow_stage") == "sme_approved":
        d_dict["workflow_stage"] = "marketing_review"
    elif d_dict.get("workflow_stage") == "compliance_approved":
        d_dict["workflow_stage"] = "approved"
    valid_types = [
        "educational_content",
        "opinion",
        "product_feature",
        "performance_related",
        "disclosure",
        "client_communications",
    ]
    if d_dict.get("type") not in valid_types:
        mapped_type = "client_communications"
        if d_dict.get("type"):
            lower_type = d_dict["type"].lower().replace(" ", "_")
            for vt in valid_types:
                if vt in lower_type or lower_type in vt:
                    mapped_type = vt
                    break
        d_dict["type"] = mapped_type
    return Document(**d_dict)


async def _require_document_in_org_for_user(
    db,
    doc_id: str,
    current_user: dict,
    tenant_ctx: dict,
) -> dict:
    """
    Load document row scoped to tenant; enforce assignment/participation rules.
    Returns raw row dict (before _document_row_to_model).
    """
    organization_id = tenant_ctx["organization_id"]
    user_id = str(current_user.get("id"))
    roles = set(current_user.get("roles") or [])
    is_admin = _tenant_org_super_admin(tenant_ctx)

    query = """
        SELECT
            d.id, d.document_code, d.name, d.type, d.current_version_id,
            d.submitted_by, d.created_at, d.updated_at,
            v.status as status,
            v.version_label as version_label,
            v.s3_key as version_s3_key,
            cr.id as review_id,
            w.id as workflow_id,
            w.current_stage as workflow_stage,
            w.assigned_to as assigned_to,
            w.assigned_role as assigned_role,
            up.full_name as assigned_to_name
        FROM documents d
        LEFT JOIN document_versions v ON d.current_version_id = v.id
        LEFT JOIN LATERAL (
            SELECT id
            FROM content_reviews
            WHERE document_version_id = v.id
            ORDER BY created_at DESC
            LIMIT 1
        ) cr_lat ON TRUE
        LEFT JOIN content_reviews cr ON cr.id = cr_lat.id
        LEFT JOIN workflows w ON w.review_id = cr.id
        LEFT JOIN user_profiles up ON w.assigned_to = up.id
        WHERE d.id=$1 AND d.organization_id=$2
    """
    row = await db.fetchrow(query, doc_id, organization_id)
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    if not is_admin:
        submitted_by = str(row["submitted_by"])
        assigned_to = str(row["assigned_to"]) if row["assigned_to"] else None
        assigned_role = row["assigned_role"]
        workflow_id = row["workflow_id"]

        can_access = (
            user_id == submitted_by
            or user_id == assigned_to
            or (assigned_to is None and assigned_role in roles)
        )

        if not can_access and workflow_id:
            past_participant = await db.fetchval(
                "SELECT 1 FROM workflow_steps WHERE workflow_id=$1 AND (claimed_by=$2 OR completed_by=$2) LIMIT 1",
                workflow_id,
                user_id,
            )
            if past_participant:
                can_access = True

        # Grant limited (read + comment) access to users who were @mentioned in
        # any comment on this document's review. They cannot perform workflow
        # actions — canActOnCurrentStage on the frontend evaluates to false
        # for users with no assigned workflow role, so no extra gating is needed.
        if not can_access:
            was_mentioned = await db.fetchval(
                """
                SELECT 1
                FROM comment_mentions cm
                JOIN content_comments cc ON cc.id = cm.comment_id
                JOIN content_reviews cr ON cr.id = cc.review_id
                JOIN document_versions dv ON cr.document_version_id = dv.id
                WHERE dv.document_id = $1
                  AND cm.mentioned_user_id = $2::uuid
                LIMIT 1
                """,
                doc_id,
                user_id,
            )
            if was_mentioned:
                can_access = True

        if not can_access:
            raise HTTPException(status_code=403, detail="You do not have access to this document")

    return dict(row)


async def _document_model_for_user(
    db,
    doc_id: str,
    current_user: dict,
    tenant_ctx: dict,
) -> Document:
    row = await _require_document_in_org_for_user(db, doc_id, current_user, tenant_ctx)
    return _document_row_to_model(row)


# ---------------------------------------------------------------------------
# SSE pub/sub for real-time AI analysis progress
# ---------------------------------------------------------------------------
_sse_subscribers: dict[str, list[asyncio.Queue]] = {}
_sse_lock = asyncio.Lock()


async def _sse_subscribe(doc_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    async with _sse_lock:
        _sse_subscribers.setdefault(doc_id, []).append(q)
    return q


async def _sse_unsubscribe(doc_id: str, q: asyncio.Queue):
    async with _sse_lock:
        subs = _sse_subscribers.get(doc_id)
        if subs:
            try:
                subs.remove(q)
            except ValueError:
                pass
            if not subs:
                _sse_subscribers.pop(doc_id, None)


def _sse_publish(doc_id: str, data: dict):
    """Fire-and-forget publish from any context (sync or async)."""
    subs = _sse_subscribers.get(doc_id)
    if not subs:
        return
    for q in list(subs):
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            pass


def _user_id_for_celery(current_user: Optional[dict]) -> Optional[str]:
    """Extract user UUID for Celery broker payloads (never pass full JWT dict)."""
    if not current_user:
        return None
    uid = current_user.get("id")
    return str(uid) if uid else None


async def _queue_ai_analysis_if_needed(
    *,
    db,
    background_tasks: BackgroundTasks,
    doc_id: str,
    current_user: dict,
    trigger_source: str,
    organization_id: Optional[str] = None,
) -> dict:
    """
    Queue AI analysis exactly once for the current document review/version.
    Uses a pg_advisory_xact_lock keyed on the review UUID to serialise
    concurrent callers (e.g. upload-path + frontend auto-trigger).
    Writes ``ai_analysis_started`` immediately so subsequent callers and
    the frontend see ``processing`` without a gap.
    """
    if organization_id:
        review_row = await db.fetchrow(
            """
            SELECT cr.id AS review_id
            FROM documents d
            JOIN document_versions dv ON d.current_version_id = dv.id
            JOIN content_reviews cr ON cr.document_version_id = dv.id
            WHERE d.id = $1 AND d.organization_id = $2::uuid
            ORDER BY cr.created_at DESC
            LIMIT 1
            """,
            doc_id,
            organization_id,
        )
    else:
        review_row = await db.fetchrow(
            """
            SELECT cr.id AS review_id
            FROM documents d
            JOIN document_versions dv ON d.current_version_id = dv.id
            JOIN content_reviews cr ON cr.document_version_id = dv.id
            WHERE d.id = $1
            ORDER BY cr.created_at DESC
            LIMIT 1
            """,
            doc_id,
        )
    if not review_row:
        from apis.services.celery_tasks import analyze_document_task
        analyze_document_task.delay(doc_id, _user_id_for_celery(current_user))
        logger.info(
            "AI_ANALYSIS_QUEUE_DECISION doc_id=%s source=%s decision=queued reason=no_review",
            doc_id,
            trigger_source,
        )
        return {"queued": True, "reason": "no_review"}

    review_id = str(review_row["review_id"])

    # Serialise per-review: advisory lock prevents two concurrent callers
    # (e.g. upload-path + frontend auto-trigger) from both passing the check.
    lock_key = hash(review_id) % (2**63)
    try:
        await db.execute("SELECT pg_advisory_lock($1)", lock_key)

        latest_ai_event = await db.fetchrow(
            """
            SELECT event_type
            FROM audit_events
            WHERE review_id=$1
              AND is_ai=true
              AND event_type IN ('ai_analysis_started', 'ai_analysis_completed', 'ai_analysis_failed')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            review_id,
        )

        latest_type = str(latest_ai_event["event_type"]) if latest_ai_event else None
        if latest_type == "ai_analysis_started":
            logger.info(
                "AI_ANALYSIS_QUEUE_DECISION doc_id=%s review_id=%s source=%s decision=skipped reason=already_processing",
                doc_id,
                review_id,
                trigger_source,
            )
            return {"queued": False, "reason": "already_processing"}

        if latest_type == "ai_analysis_completed":
            logger.info(
                "AI_ANALYSIS_QUEUE_DECISION doc_id=%s review_id=%s source=%s decision=skipped reason=already_completed",
                doc_id,
                review_id,
                trigger_source,
            )
            return {"queued": False, "reason": "already_completed"}

        # Write start event immediately so /review returns "processing" right away.
        triggered_by = (current_user or {}).get("id")
        try:
            await log_audit_event(
                db,
                review_id=review_id,
                event_type="ai_analysis_started",
                description="AI compliance analysis started",
                is_ai=True,
                triggered_by_user_id=triggered_by,
            )
        except Exception as evt_err:
            logger.warning("Could not pre-log ai_analysis_started: %s", evt_err)

        from apis.services.celery_tasks import analyze_document_task
        analyze_document_task.delay(doc_id, _user_id_for_celery(current_user))
        reason = "retry_after_failed" if latest_type == "ai_analysis_failed" else "first_run"
        logger.info(
            "AI_ANALYSIS_QUEUE_DECISION doc_id=%s review_id=%s source=%s decision=queued reason=%s",
            doc_id,
            review_id,
            trigger_source,
            reason,
        )
        return {"queued": True, "reason": reason}
    finally:
        await db.execute("SELECT pg_advisory_unlock($1)", lock_key)


def _send_document_published_email_background(
    to_email: str,
    recipient_name: str,
    document_name: str,
    doc_id: str,
    version_label: str,
    org_slug: str | None,
    published_at,
) -> None:
    send_document_published_email_sync(
        to_email=to_email,
        recipient_name=recipient_name,
        document_name=document_name,
        doc_id=doc_id,
        version_label=version_label,
        org_slug=org_slug,
        published_at=published_at,
    )


def _send_workflow_transition_emails_background(
    recipients: list[tuple[str, str]],
    document_title: str,
    from_stage: str,
    to_stage: str,
    open_url: str,
    *,
    doc_id: str,
    org_slug: str | None,
    template_id: str | None,
    actor_name: str | None,
    reviewer_note: str | None,
) -> None:
    for to_email, recipient_name in recipients:
        send_workflow_stage_email_sync(
            to_email=to_email,
            recipient_name=recipient_name,
            document_title=document_title,
            from_stage=from_stage,
            to_stage=to_stage,
            open_url=open_url,
            template_id=template_id,
            actor_name=actor_name,
            reviewer_note=reviewer_note,
            doc_id=doc_id,
            org_slug=org_slug,
        )


def _send_post_classification_author_emails_background(
    *,
    to_email: str,
    recipient_name: str,
    document_name: str,
    doc_id: str,
    route: str,
    submitted_at,
    org_slug: str | None,
    send_reupload_ack: bool,
    version_label: str | None,
) -> None:
    send_submission_received_email_sync(
        to_email=to_email,
        recipient_name=recipient_name,
        document_name=document_name,
        doc_id=doc_id,
        route=route,
        submitted_at=submitted_at,
        org_slug=org_slug,
    )
    if send_reupload_ack:
        send_collab_document_uploaded_email_sync(
            to_email=to_email,
            recipient_name=recipient_name,
            document_name=document_name,
            doc_id=doc_id,
            version_label=version_label,
            org_slug=org_slug,
        )


def is_document_reupload(version_count: int) -> bool:
    """True when the classified version is not the document's first upload."""
    return int(version_count or 0) > 1


_POST_CLASSIFICATION_REVIEWER_STAGES = frozenset({"sme_review", "compliance_review"})


def should_notify_reviewers_after_classification(stage: str | None) -> bool:
    """Reviewer emails after classification only when an external reviewer queue exists."""
    return (stage or "").strip().lower() in _POST_CLASSIFICATION_REVIEWER_STAGES


async def _notify_post_classification_reviewers(
    *,
    db,
    doc_id: str,
    review_id: str,
    current_stage: str,
    assigned_role: Optional[str],
    assigned_to: Optional[str],
    organization_id: Optional[str] = None,
    org_slug: Optional[str] = None,
) -> None:
    """
    Notify reviewer(s) once classification confirms the document is in scope.
    Author-facing submission acks are sent separately (Phase 2).
    Direct-to-AI uploads (marketing_review) skip reviewer notify — no external queue.
    """
    if not should_notify_reviewers_after_classification(current_stage):
        logger.info(
            "CLASSIFICATION_IN_SCOPE doc_id=%s skipped reviewer notify for stage=%s",
            doc_id,
            current_stage,
        )
        return

    await _notify_workflow_transition(
        db=db,
        background_tasks=None,
        doc_id=doc_id,
        review_id=review_id,
        from_stage="document_upload",
        to_stage=current_stage,
        assigned_role=assigned_role,
        assigned_to=assigned_to,
        organization_id=organization_id,
        org_slug=org_slug,
    )
    logger.info(
        "CLASSIFICATION_IN_SCOPE doc_id=%s dispatched reviewer notifications for stage=%s",
        doc_id,
        current_stage,
    )


async def _notify_post_classification_author(
    *,
    db,
    doc_id: str,
    version_id: str,
    current_stage: str,
    org_slug: Optional[str] = None,
) -> None:
    """Author-facing emails after in-scope classification (submission ack + optional reupload)."""
    doc_row = await db.fetchrow(
        "SELECT name, submitted_by FROM documents WHERE id=$1",
        doc_id,
    )
    if not doc_row or not doc_row["submitted_by"]:
        logger.info(
            "CLASSIFICATION_IN_SCOPE doc_id=%s skipped author notify (no submitted_by)",
            doc_id,
        )
        return

    author_row = await db.fetchrow(
        "SELECT id, email, full_name FROM user_profiles WHERE id=$1 AND is_active=TRUE",
        str(doc_row["submitted_by"]),
    )
    if not author_row:
        logger.info(
            "CLASSIFICATION_IN_SCOPE doc_id=%s skipped author notify (author inactive)",
            doc_id,
        )
        return

    version_row = await db.fetchrow(
        """
        SELECT version_label, uploaded_at
        FROM document_versions
        WHERE id=$1
        """,
        version_id,
    )
    version_count = await db.fetchval(
        "SELECT COUNT(*)::int FROM document_versions WHERE document_id=$1",
        doc_id,
    ) or 1

    document_title = (doc_row["name"] or "Document Review").strip()
    email = (author_row.get("email") or "").strip()
    author_name = (
        (author_row.get("full_name") or "").strip()
        or (email.split("@")[0] if email else "Author")
    )
    route = resolve_submission_route(current_stage)
    _, current_stage_label = submission_route_stage_labels(route)
    send_reupload_ack = is_document_reupload(version_count)
    version_label = (version_row.get("version_label") if version_row else None) or None
    submitted_at = version_row.get("uploaded_at") if version_row else None

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    author_id = str(author_row["id"])
    notif_title = "Submission received"
    notif_message = (
        f"{document_title} entered the workflow at {current_stage_label}"
    )
    if await check_recent_notification_exists(db, author_id, notif_title, notif_message, doc_id, 5):
        logger.info("Skipping duplicate post-classification author notification for user %s", author_id)
    else:
        notif_id = str(uuid.uuid4())
        await db.execute(
            """
            INSERT INTO notifications (id, user_id, type, title, message, reference_type, reference_id, is_read, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7::uuid, $8, $9)
            """,
            notif_id,
            author_id,
            "workflow_submission_received",
            notif_title,
            notif_message,
            "document",
            doc_id,
            False,
            now_utc,
        )
        await publish_notification(
            author_id,
            {
                "event": "notification_created",
                "notification": {
                    "id": notif_id,
                    "user_id": author_id,
                    "type": "workflow_submission_received",
                    "title": notif_title,
                    "message": notif_message,
                    "reference_type": "document",
                    "reference_id": doc_id,
                    "is_read": False,
                    "created_at": now_utc.isoformat(),
                },
            },
        )


    if email:
        await asyncio.to_thread(
            _send_post_classification_author_emails_background,
            to_email=email,
            recipient_name=author_name,
            document_name=document_title,
            doc_id=doc_id,
            route=route,
            submitted_at=submitted_at,
            org_slug=org_slug,
            send_reupload_ack=send_reupload_ack,
            version_label=str(version_label) if version_label else None,
        )
        logger.info(
            "CLASSIFICATION_IN_SCOPE doc_id=%s dispatched author emails route=%s reupload_ack=%s",
            doc_id,
            route,
            send_reupload_ack,
        )
    else:
        logger.info(
            "CLASSIFICATION_IN_SCOPE doc_id=%s author in-app only (no email on file)",
            doc_id,
        )


async def _notify_workflow_transition(
    *,
    db,
    background_tasks: Optional[BackgroundTasks],
    doc_id: str,
    review_id: str,
    from_stage: str,
    to_stage: str,
    assigned_role: Optional[str],
    assigned_to: Optional[str],
    organization_id: Optional[str] = None,
    org_slug: Optional[str] = None,
    workflow_action: Optional[str] = None,
    email_template_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    reviewer_note: Optional[str] = None,
) -> None:
    """
    Notify intended reviewer(s) for workflow transitions:
    - If assigned_to exists: notify only that user.
    - If unassigned: broadcast to all active users in assigned_role.
    """
    role = (assigned_role or "").strip().lower()
    assignee = str(assigned_to) if assigned_to else None

    if assignee:
        recipient_rows = await db.fetch(
            "SELECT id, email, full_name FROM user_profiles WHERE id=$1 AND is_active=TRUE",
            assignee,
        )
    elif role:
        if organization_id:
            recipient_rows = await db.fetch(
                """
                SELECT DISTINCT up.id, up.email, up.full_name
                FROM user_profiles up
                JOIN organization_users ou ON ou.user_id = up.id AND ou.organization_id = $2::uuid
                JOIN user_roles ur ON ur.user_id = up.id
                JOIN roles r ON r.id = ur.role_id
                WHERE up.is_active = TRUE
                  AND lower(r.name) = $1
                """,
                role,
                organization_id,
            )
        else:
            recipient_rows = await db.fetch(
                """
                SELECT DISTINCT up.id, up.email, up.full_name
                FROM user_profiles up
                JOIN user_roles ur ON ur.user_id = up.id
                JOIN roles r ON r.id = ur.role_id
                WHERE up.is_active = TRUE
                  AND lower(r.name) = $1
                """,
                role,
            )
    else:
        recipient_rows = []

    if not recipient_rows:
        return

    doc_name = await db.fetchval("SELECT name FROM documents WHERE id=$1", doc_id)
    document_title = doc_name or "Document Review"
    open_url = get_document_detail_url(doc_id, org_slug=org_slug)

    template_id = resolve_workflow_template_id(
        from_stage,
        to_stage,
        workflow_action=workflow_action,
        email_template_id=email_template_id,
    )

    actor_name: str | None = None
    if actor_user_id:
        actor_row = await db.fetchrow(
            "SELECT full_name, email FROM user_profiles WHERE id=$1",
            str(actor_user_id),
        )
        if actor_row:
            actor_name = (actor_row.get("full_name") or actor_row.get("email") or "").strip()
    if not actor_name and template_id == "workflow_to_sme":
        submitter_row = await db.fetchrow(
            """
            SELECT up.full_name, up.email
            FROM documents d
            LEFT JOIN user_profiles up ON up.id = d.submitted_by
            WHERE d.id = $1
            """,
            doc_id,
        )
        if submitter_row:
            actor_name = (
                submitter_row.get("full_name") or submitter_row.get("email") or ""
            ).strip()
    if not actor_name:
        actor_name = "A reviewer"

    from_label = from_stage.replace("_", " ").title()
    to_label = to_stage.replace("_", " ").title()

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    email_recipients: list[tuple[str, str]] = []

    for row in recipient_rows:
        uid = str(row["id"])
        email = (row.get("email") or "").strip()
        name = (row.get("full_name") or "").strip() or (email.split("@")[0] if email else "Reviewer")
        notif_id = str(uuid.uuid4())
        notif_title = f"Workflow moved to {to_label}"
        notif_message = f"{document_title} moved from {from_label} to {to_label}"

        if await check_recent_notification_exists(db, uid, notif_title, notif_message, doc_id, 5):
            logger.info("Skipping duplicate workflow transition notification for user %s", uid)
        else:
            await db.execute(
                """
                INSERT INTO notifications (id, user_id, type, title, message, reference_type, reference_id, is_read, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7::uuid, $8, $9)
                """,
                notif_id,
                uid,
                "workflow_transition",
                notif_title,
                notif_message,
                "document",
                doc_id,
                False,
                now_utc,
            )
            await publish_notification(
                uid,
                {
                    "event": "notification_created",
                    "notification": {
                        "id": notif_id,
                        "user_id": uid,
                        "type": "workflow_transition",
                        "title": notif_title,
                        "message": notif_message,
                        "reference_type": "document",
                        "reference_id": doc_id,
                        "is_read": False,
                        "created_at": now_utc.isoformat(),
                    },
                },
            )

        if email:
            email_recipients.append((email, name))

    if email_recipients:
        payload = (
            email_recipients,
            document_title,
            from_stage,
            to_stage,
            open_url,
        )
        kwargs = {
            "doc_id": doc_id,
            "org_slug": org_slug,
            "template_id": template_id,
            "actor_name": actor_name,
            "reviewer_note": reviewer_note,
        }
        if background_tasks:
            background_tasks.add_task(
                _send_workflow_transition_emails_background,
                *payload,
                **kwargs,
            )
        else:
            await asyncio.to_thread(
                _send_workflow_transition_emails_background,
                *payload,
                **kwargs,
            )

async def _publish_workflow_event(
    review_id: str,
    doc_id: str,
    action: str,
    from_stage: str,
    to_stage: str,
) -> None:
    """Helper to emit workflow stage changes to the real-time SSE comments stream."""
    try:
        await publish_review_comment(
            review_id,
            {
                "event": "workflow_stage_changed",
                "doc_id": doc_id,
                "action": action,
                "from_stage": from_stage,
                "to_stage": to_stage,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as e:
        logger.warning("Failed to publish workflow event: %s", e)


logger.info(
    "LLM_CLIENT_INIT provider=%s client=%s model_id=%s",
    ai_config.LLM_PROVIDER,
    llm_client.__class__.__name__,
    getattr(llm_client, "model_id", "unknown"),
)


def _chunk_texts_and_metadata_with_tables(chunks_raw: list) -> tuple[list[str], list[list]]:
    """Build chunk texts for the pipeline, appending table cell text so tables are analyzed as text."""
    from bs4 import BeautifulSoup

    chunk_texts: list[str] = []
    chunk_metadatas: list[list] = []
    for c in chunks_raw:
        parts: list[str] = []
        base = (c.get("text") or "").strip()
        if base:
            parts.append(base)
        for m in c.get("media") or []:
            if m.get("type") == "table" and m.get("html"):
                table_plain = BeautifulSoup(m["html"], "html.parser").get_text(" ", strip=True)
                if table_plain:
                    parts.append("[TABLE]\n" + table_plain)
        combined = "\n\n".join(parts).strip()
        if not combined:
            continue
        chunk_texts.append(combined)
        chunk_metadatas.append(c.get("metadata") or [])
    return chunk_texts, chunk_metadatas

# Deterministic color palette for violations (RGB 0-1 range, pastel tones)
_HIGHLIGHT_PALETTE = [
    (1.0, 1.0, 0.4),    # bright yellow
    (0.6, 1.0, 1.0),    # bright cyan
    (0.6, 1.0, 0.6),    # bright lime green
    (1.0, 0.7, 0.8),    # bright pink
    (0.8, 0.8, 1.0),    # bright lavender
]

_ANNOTATION_ENGINE_VERSION = "hl_v2"
_OFFICE_PREVIEW_ENGINE_VERSION = "office_pdf_v1"
_OFFICE_PREVIEW_EXTENSIONS = {".doc", ".docx", ".ppt", ".pptx"}

# PDF, Word (incl. legacy .doc), PowerPoint (incl. legacy .ppt) — must match upload validation
ALLOWED_MARKETING_DOC_EXTENSIONS = frozenset({".pdf", ".doc", ".docx", ".ppt", ".pptx"})


def _extension_from_filename(filename: str) -> str:
    if not filename or "." not in filename:
        return ""
    return Path(filename).suffix.lower()


def _ensure_name_has_extension(name: Optional[str], s3_key: Optional[str]) -> str:
    """If `name` lacks a file extension, derive it from the S3 key (which always has one)."""
    if not name:
        return "Untitled Document"
    if "." in name and _extension_from_filename(name):
        return name
    if s3_key:
        ext = _extension_from_filename(Path(s3_key).name)
        if ext:
            return f"{name}{ext}"
    return name


def _mime_from_extension(ext: str) -> str:
    """Return Content-Type for allowed marketing document extensions (ext with or without dot)."""
    e = ext.lower().lstrip(".")
    if e == "pdf":
        return "application/pdf"
    if e == "docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if e == "doc":
        return "application/msword"
    if e == "pptx":
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if e == "ppt":
        return "application/vnd.ms-powerpoint"
    return "application/octet-stream"


def _validate_marketing_upload(filename: str, content: bytes) -> str:
    """
    Enforce allowed types (extension + magic bytes). Returns Content-Type for S3.
    Raises HTTPException on validation failure.
    """
    ext = _extension_from_filename(filename)
    if ext not in ALLOWED_MARKETING_DOC_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Allowed: PDF, Word (.doc, .docx), PowerPoint (.ppt, .pptx).",
        )
    if not content or len(content) < 8:
        raise HTTPException(status_code=400, detail="File is empty or too small.")

    if ext == ".pdf":
        if not content.startswith(b"%PDF"):
            raise HTTPException(status_code=400, detail="File does not appear to be a valid PDF.")
    elif ext in (".docx", ".pptx"):
        if not content.startswith(b"PK\x03\x04"):
            raise HTTPException(status_code=400, detail="File does not appear to be a valid Office document (.docx/.pptx).")
    elif ext in (".doc", ".ppt"):
        if not content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise HTTPException(status_code=400, detail="File does not appear to be a valid legacy Office document (.doc/.ppt).")

    return _mime_from_extension(ext)


def _presigned_url_for_key(bucket: str, key: str, filename: Optional[str] = None) -> str:
    try:
        params = {"Bucket": bucket, "Key": key}
        if filename:
            # Force download via ResponseContentDisposition
            # This ensures the browser triggers a download even if it can render the file type (like PDF)
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
        
        return s3_helper.s3_client.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=3600,
        )
    except ClientError as e:
        # Log S3 credential/access errors without exposing to user
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        log_s3_error(
            error=e,
            operation="generate_presigned_url",
            resource=key,
            context={
                "bucket": bucket,
                "error_code": error_code,
                "filename": filename
            }
        )
        raise HTTPException(status_code=500, detail="Unable to access document. Please try again later.")
    except Exception as e:
        # Log other unexpected errors
        log_error(
            error=e,
            category=ErrorCategory.S3_STORAGE,
            operation="generate_presigned_url",
            severity=ErrorSeverity.ERROR,
            context={"bucket": bucket, "key": key}
        )
        raise HTTPException(status_code=500, detail="Unable to access document. Please try again later.")


async def _next_step_order(db, workflow_id: str) -> int:
    """Get the next step_order for a workflow."""
    val = await db.fetchval(
        "SELECT COALESCE(MAX(step_order), 0) FROM workflow_steps WHERE workflow_id=$1",
        workflow_id,
    )
    return (val or 0) + 1


def _normalize_claim_for_hash(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _hash_claim_text(text: str) -> str:
    normalized = _normalize_claim_for_hash(text)
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _parse_location_page_line(location: str | None) -> tuple[int | None, int | None]:
    if not location:
        return (None, None)
    page_match = re.search(r"Page\s+(\d+)", location)
    line_match = re.search(r"Line\s+(\d+)", location)
    page_no = int(page_match.group(1)) if page_match else None
    line_no = int(line_match.group(1)) if line_match else None
    return (page_no, line_no)


def _build_findings_hash(claims_with_location: list[dict]) -> str:
    parts = [_ANNOTATION_ENGINE_VERSION]
    for item in claims_with_location:
        canonical_key = str(item.get("canonical_key") or "").strip().lower()
        claim = _normalize_claim_for_hash(str(item.get("claim") or ""))
        claim_part = canonical_key or claim
        location = str(item.get("location") or "").strip().lower()
        if claim_part:
            parts.append(f"{claim_part}|{location}")
    digest = hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()
    return digest


def _annotation_cache_key(doc_id: str, version_id: str, findings_hash: str, source_key: str) -> str:
    ext = Path(source_key).suffix.lower() or ".pdf"
    return f"annotated/{doc_id}/{version_id}/{findings_hash}/annotated{ext}"


def _office_preview_hash(source_key: str, source_ext: str) -> str:
    payload = f"{_OFFICE_PREVIEW_ENGINE_VERSION}|{source_key}|{source_ext.lower()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _office_preview_cache_key(doc_id: str, version_id: str, preview_hash: str) -> str:
    return f"office-preview/{doc_id}/{version_id}/{preview_hash}/preview.pdf"


def _convert_office_to_pdf_bytes(raw_bytes: bytes, source_name: str) -> tuple[bytes, str]:
    source_ext = _extension_from_filename(source_name)
    if source_ext not in _OFFICE_PREVIEW_EXTENSIONS:
        raise ValueError(f"Unsupported office extension for conversion: {source_ext}")

    safe_stem = Path(source_name).stem or "document"
    output_name = f"{safe_stem}.pdf"
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / f"source{source_ext}"
        input_path.write_bytes(raw_bytes)
        user_installation = f"file://{Path(tmpdir) / f'lo-profile-{uuid.uuid4()}'}"
        convert_filter = "pdf:impress_pdf_Export" if source_ext in {".ppt", ".pptx"} else "pdf"
        command = [
            "soffice",
            "--headless",
            "--invisible",
            "--nologo",
            "--nodefault",
            "--norestore",
            "--nofirststartwizard",
            "-env:UserInstallation=" + user_installation,
            "--convert-to",
            convert_filter,
            "--outdir",
            str(Path(tmpdir)),
            str(input_path),
        ]
        import os
        custom_env = os.environ.copy()
        custom_env["HOME"] = tmpdir
        result = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=120, env=custom_env
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"LibreOffice conversion failed (code {result.returncode}): {(result.stderr or result.stdout or '').strip()}"
            )
        converted_path = Path(tmpdir) / output_name
        if not converted_path.exists():
            # Fallback to any produced PDF name when LibreOffice rewrites names.
            pdf_files = sorted(Path(tmpdir).glob("*.pdf"))
            if not pdf_files:
                raise RuntimeError(
                    "LibreOffice conversion did not produce a PDF file. "
                    f"stdout={(result.stdout or '').strip()} "
                    f"stderr={(result.stderr or '').strip()}"
                )
            converted_path = pdf_files[0]
            output_name = converted_path.name
        return converted_path.read_bytes(), output_name


async def _build_office_pdf_preview_response(
    *,
    db,
    doc_id: str,
    version_id: str,
    bucket: str,
    source_key: str,
) -> dict:
    original_name = Path(source_key).name
    original_mime = _mime_from_extension(Path(source_key).suffix)
    original_url = _presigned_url_for_key(bucket, source_key)
    source_ext = _extension_from_filename(original_name)
    if source_ext not in _OFFICE_PREVIEW_EXTENSIONS:
        return {
            "url": original_url,
            "file_name": original_name,
            "mime": original_mime,
            "original_url": original_url,
            "original_file_name": original_name,
            "original_mime": original_mime,
            "preview_fallback": False,
        }

    preview_hash = _office_preview_hash(source_key, source_ext)
    cached_row = await db.fetchrow(
        """
        SELECT s3_bucket, s3_key
        FROM ai_annotated_artifacts
        WHERE document_version_id=$1 AND findings_hash=$2 AND engine_version=$3
        LIMIT 1
        """,
        version_id,
        preview_hash,
        _OFFICE_PREVIEW_ENGINE_VERSION,
    )
    if cached_row:
        cache_bucket = cached_row["s3_bucket"]
        cache_key = cached_row["s3_key"]
        try:
            s3_helper.s3_client.head_object(Bucket=cache_bucket, Key=cache_key)
            await db.execute(
                "UPDATE ai_annotated_artifacts SET last_accessed_at=$1 WHERE document_version_id=$2 AND findings_hash=$3 AND engine_version=$4",
                datetime.now(timezone.utc).replace(tzinfo=None),
                version_id,
                preview_hash,
                _OFFICE_PREVIEW_ENGINE_VERSION,
            )
            return {
                "url": _presigned_url_for_key(cache_bucket, cache_key),
                "file_name": Path(cache_key).name,
                "mime": "application/pdf",
                "original_url": original_url,
                "original_file_name": original_name,
                "original_mime": original_mime,
                "preview_fallback": False,
            }
        except Exception as cache_err:
            # Treat cache miss/corruption as a regeneration path.
            logger.warning(
                "OFFICE_PREVIEW_CACHE_MISS doc_id=%s version_id=%s key=%s err=%s",
                doc_id,
                version_id,
                cache_key,
                str(cache_err),
            )

    try:
        def _download() -> bytes:
            resp = s3_helper.s3_client.get_object(Bucket=bucket, Key=source_key)
            return resp["Body"].read()

        raw_bytes = await asyncio.to_thread(_download)
        converted_pdf_bytes, converted_name = await asyncio.to_thread(_convert_office_to_pdf_bytes, raw_bytes, original_name)
        preview_key = _office_preview_cache_key(doc_id, version_id, preview_hash)
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        s3_helper.s3_client.put_object(
            Bucket=bucket,
            Key=preview_key,
            Body=converted_pdf_bytes,
            ContentType="application/pdf",
        )
        await db.execute(
            """
            INSERT INTO ai_annotated_artifacts (
                id, document_id, document_version_id, review_id, findings_hash, s3_bucket, s3_key,
                engine_version, generated_at, last_accessed_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $9)
            ON CONFLICT (document_version_id, findings_hash, engine_version)
            DO UPDATE SET
                s3_bucket = EXCLUDED.s3_bucket,
                s3_key = EXCLUDED.s3_key,
                generated_at = EXCLUDED.generated_at,
                last_accessed_at = EXCLUDED.last_accessed_at
            """,
            str(uuid.uuid4()),
            doc_id,
            version_id,
            None,
            preview_hash,
            bucket,
            preview_key,
            _OFFICE_PREVIEW_ENGINE_VERSION,
            now_utc,
        )
        return {
            "url": _presigned_url_for_key(bucket, preview_key),
            "file_name": converted_name,
            "mime": "application/pdf",
            "original_url": original_url,
            "original_file_name": original_name,
            "original_mime": original_mime,
            "preview_fallback": False,
        }
    except Exception as conversion_err:
        logger.warning("OFFICE_PDF_PREVIEW_FALLBACK doc_id=%s version_id=%s err=%s", doc_id, version_id, str(conversion_err))
        return {
            "url": original_url,
            "file_name": original_name,
            "mime": original_mime,
            "original_url": original_url,
            "original_file_name": original_name,
            "original_mime": original_mime,
            "preview_fallback": True,
        }


async def _warm_office_preview_cache_bg(
    doc_id: str,
    version_id: str,
    bucket: str,
    source_key: str,
) -> None:
    """
    Pre-generate Office preview PDF artifact in background (idempotent).
    Safe to call repeatedly; cache lookup in _build_office_pdf_preview_response prevents duplicate work.
    """
    source_name = Path(source_key).name
    source_ext = _extension_from_filename(source_name)
    if source_ext not in _OFFICE_PREVIEW_EXTENSIONS:
        return

    from apis.core.database import db_pool

    if not db_pool:
        logger.warning("OFFICE_PREVIEW_WARMUP_SKIPPED doc_id=%s version_id=%s reason=no_db_pool", doc_id, version_id)
        return

    try:
        async with db_pool.acquire() as conn:
            result = await _build_office_pdf_preview_response(
                db=conn,
                doc_id=doc_id,
                version_id=version_id,
                bucket=bucket,
                source_key=source_key,
            )
        logger.info(
            "OFFICE_PREVIEW_WARMUP_DONE doc_id=%s version_id=%s fallback=%s preview_file=%s",
            doc_id,
            version_id,
            bool(result.get("preview_fallback")),
            result.get("file_name"),
        )
    except Exception as e:
        logger.warning(
            "OFFICE_PREVIEW_WARMUP_FAIL doc_id=%s version_id=%s err=%s",
            doc_id,
            version_id,
            str(e),
        )

async def _pre_extract_text_bg(
    doc_id: str,
    version_id: str,
    bucket: str,
    s3_key: str,
) -> None:
    """Pre-extract document text in background on upload so parsing is done before SME approves."""
    from apis.core.database import db_pool

    if not db_pool:
        return
    try:
        async with db_pool.acquire() as db:
            existing = await db.fetchval(
                "SELECT extracted_text FROM document_versions WHERE id=$1", version_id
            )
            if existing:
                return

        def _download_and_parse() -> str:
            raw = s3_helper.s3_client.get_object(Bucket=bucket, Key=s3_key)["Body"].read()
            source_ext = _extension_from_filename(s3_key)
            if source_ext in _OFFICE_PREVIEW_EXTENSIONS:
                raw, _ = _convert_office_to_pdf_bytes(raw, Path(s3_key).name)
                suffix = ".pdf"
            else:
                suffix = source_ext or ".pdf"
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
                input_path = Path(tmpdir) / f"input{suffix}"
                input_path.write_bytes(raw)
                from apis.services.ai.processing.parsing import Parsing
                parser = Parsing(input_path)
                out_dir = Path(tmpdir) / "out"
                html_path = parser.add_metadata_to_file(out_dir, "output.html")
                return html_path.read_text(encoding="utf-8")

        html_content = await asyncio.to_thread(_download_and_parse)
        if html_content:
            async with db_pool.acquire() as db:
                await db.execute(
                    "UPDATE document_versions SET extracted_text=$1 WHERE id=$2",
                    encode_extracted_text(html_content), version_id,
                )
            logger.info("PRE_EXTRACT_DONE doc_id=%s version_id=%s chars=%d", doc_id, version_id, len(html_content))
    except Exception as e:
        logger.warning("PRE_EXTRACT_FAIL doc_id=%s version_id=%s err=%s", doc_id, version_id, str(e))


async def _classify_document_bg(
    doc_id: str,
    version_id: str,
    bucket: str,
    s3_key: str,
    user_id: str,
    initial_stage: str,
    organization_id: Optional[str] = None,
) -> None:
    """
    Background classification worker function.
    Runs in Celery, fetches DB pool, parses the document, and runs classification.
    If in-scope and initial_stage == "marketing_review", it triggers analysis.
    """
    from apis.core.database import db_pool
    if not db_pool:
        logger.warning("CLASSIFICATION_SKIPPED doc_id=%s reason=no_db_pool", doc_id)
        return

    try:
        review_id = None
        async with db_pool.acquire() as db:
            review_id = await db.fetchval(
                "SELECT id FROM content_reviews WHERE document_version_id=$1 LIMIT 1",
                version_id,
            )
            if review_id:
                await log_audit_event(
                    db,
                    review_id=str(review_id),
                    event_type="ai_phase_parsing_document",
                    description="Parsing document using Docling (15% progress)",
                    is_ai=True,
                )

        _publish_phase(doc_id, "parsing_document", 0, 1)

        def _download_and_parse() -> str:
            raw = s3_helper.s3_client.get_object(Bucket=bucket, Key=s3_key)["Body"].read()
            source_ext = _extension_from_filename(s3_key)
            if source_ext in _OFFICE_PREVIEW_EXTENSIONS:
                raw, _ = _convert_office_to_pdf_bytes(raw, Path(s3_key).name)
                suffix = ".pdf"
            else:
                suffix = source_ext or ".pdf"
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
                input_path = Path(tmpdir) / f"input{suffix}"
                input_path.write_bytes(raw)
                from apis.services.ai.processing.parsing import Parsing
                parser = Parsing(input_path)
                out_dir = Path(tmpdir) / "out"
                html_path = parser.add_metadata_to_file(out_dir, "output.html")
                return html_path.read_text(encoding="utf-8")

        html_content = await asyncio.to_thread(_download_and_parse)
        if not html_content:
            logger.warning("CLASSIFICATION_FAIL doc_id=%s reason=no_html", doc_id)
            return

        from apis.services.ai.compliance_engine.classifier import ClassifierService
        local_classifier = ClassifierService()

        if review_id:
            async with db_pool.acquire() as db:
                await log_audit_event(
                    db,
                    review_id=str(review_id),
                    event_type="ai_phase_classifying_document",
                    description="Extracting text with AI model (30% progress)",
                    is_ai=True,
                )

        _publish_phase(doc_id, "classifying_document", 0, 1)
        classification = await asyncio.to_thread(local_classifier.classify_document, html_content)
        is_in_scope = bool(classification.get("is_in_scope", True))
        detected_type = classification.get("detected_type")

        async with db_pool.acquire() as db:
            await db.execute(
                "UPDATE document_versions SET extracted_text=$1 WHERE id=$2",
                encode_extracted_text(html_content),
                version_id,
            )

            # Retrieve review_id for audit log and workflow transitions
            review_id = await db.fetchval(
                "SELECT id FROM content_reviews WHERE document_version_id=$1 LIMIT 1",
                version_id,
            )

            if not is_in_scope:
                await db.execute(
                    "UPDATE document_versions SET status='skipped' WHERE id=$1",
                    version_id,
                )
                # Terminate the workflow since the document is classified as out of scope
                if review_id:
                    await db.execute(
                        "DELETE FROM workflows WHERE review_id = $1::uuid",
                        str(review_id),
                    )
                    logger.info("CLASSIFICATION_OUT_OF_SCOPE doc_id=%s, deleted active workflows.", doc_id)
            else:
                # Document is in scope: send notifications/emails now that it has been validated as educational
                if review_id:
                    w_row = await db.fetchrow(
                        "SELECT current_stage, assigned_role, assigned_to FROM workflows WHERE review_id = $1::uuid",
                        str(review_id),
                    )
                    if w_row:
                        org_slug = None
                        if organization_id:
                            org_slug = await db.fetchval("SELECT slug FROM organizations WHERE id = $1::uuid", str(organization_id))

                        current_stage = w_row["current_stage"]
                        await _notify_post_classification_reviewers(
                            db=db,
                            doc_id=doc_id,
                            review_id=str(review_id),
                            current_stage=current_stage,
                            assigned_role=w_row["assigned_role"],
                            assigned_to=w_row["assigned_to"] if w_row["assigned_to"] else None,
                            organization_id=organization_id,
                            org_slug=org_slug,
                        )
                        await _notify_post_classification_author(
                            db=db,
                            doc_id=doc_id,
                            version_id=version_id,
                            current_stage=current_stage,
                            org_slug=org_slug,
                        )

            if review_id:
                await log_audit_event(
                    db,
                    review_id=str(review_id),
                    event_type="ai_classification_completed",
                    description=(
                        "Document classification completed - "
                        f"{'in scope' if is_in_scope else 'out of scope'}"
                    ),
                    is_ai=True,
                    details=json.dumps(
                        {
                            "phase": "classification",
                            "is_in_scope": is_in_scope,
                            "classifier_detected_type": detected_type,
                        }
                    ),
                    triggered_by_user_id=user_id,
                )

            # Direct-to-marketing or compliance uploads should kick off full AI analysis if in-scope
            logger.info(f"Checking if should analyze: in_scope={is_in_scope}, initial_stage={initial_stage}")
            if is_in_scope and initial_stage in ("marketing_review", "compliance_review"):
                from apis.services.celery_tasks import analyze_document_task
                analyze_document_task.delay(doc_id, user_id)

        logger.info(
            "CLASSIFICATION_DONE doc_id=%s version_id=%s in_scope=%s detected_type=%s",
            doc_id, version_id, is_in_scope, detected_type,
        )

        from apis.services.celery_tasks import _redis_publish
        _redis_publish(doc_id, {"phase": "classification_done", "is_in_scope": is_in_scope})

    except Exception as e:
        logger.error("CLASSIFICATION_ERR doc_id=%s err=%s", doc_id, str(e), exc_info=True)



@router.get("/{doc_id}/analysis-stream")
async def analysis_progress_stream(
    request: Request,
    doc_id: str,
    token: Optional[str] = None,
    db=Depends(get_db),
):
    """SSE endpoint for real-time AI analysis progress. Authenticates via the
    httpOnly session cookie (preferred for browser EventSource with
    ``withCredentials=true``) and falls back to a ``?token=`` query parameter
    for legacy callers."""
    from apis.core.security import get_session_token, resolve_user_from_token

    effective_token = (
        get_session_token(request)
        or (token.strip() if isinstance(token, str) else "")
        or ""
    )
    if not effective_token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        current = await resolve_user_from_token(effective_token, db)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    await assert_app_access_ready(db, str(current["id"]))

    path = request.url.path or ""
    m = re.search(r"/orgs/([^/]+)/", path)
    if not m:
        raise HTTPException(status_code=400, detail="Tenant path must include /orgs/{org_slug}/")
    org_slug = m.group(1)
    tenant_ctx = await build_tenant_context(org_slug, current, db)
    in_org = await db.fetchval(
        "SELECT 1 FROM documents WHERE id = $1::uuid AND organization_id = $2::uuid LIMIT 1",
        doc_id,
        tenant_ctx["organization_id"],
    )
    if not in_org:
        raise HTTPException(status_code=404, detail="Document not found")

    async def _event_generator():
        import redis.asyncio as aioredis
        queue = await _sse_subscribe(doc_id)
        redis_client = None
        pubsub = None
        try:
            # Also subscribe to Redis so we receive events from the Celery worker
            # (which runs in a separate Docker container and cannot reach in-memory queues)
            try:
                redis_client = aioredis.from_url(
                    os.environ.get("REDIS_URL", "redis://redis:6379/0"),
                    decode_responses=True,
                )
                pubsub = redis_client.pubsub()
                await pubsub.subscribe("doc_updates")
            except Exception as redis_err:
                logger.warning("SSE_REDIS_SUBSCRIBE_FAIL doc_id=%s err=%s", doc_id, redis_err)
                pubsub = None

            import time
            last_active = time.time()
            while True:
                # 1. Check in-memory queue (same-process events, e.g. progress ticks)
                try:
                    data = queue.get_nowait()
                    yield f"data: {json.dumps(data)}\n\n"
                    last_active = time.time()
                    if data.get("phase") in ("completed", "failed"):
                        break
                    continue
                except asyncio.QueueEmpty:
                    pass

                # 2. Check Redis pub/sub for cross-process events from the worker
                if pubsub:
                    try:
                        msg = await asyncio.wait_for(
                            pubsub.get_message(ignore_subscribe_messages=True), timeout=0.1
                        )
                        if msg and msg.get("type") == "message":
                            payload = json.loads(msg["data"])
                            if payload.get("doc_id") == doc_id:
                                event_data = {k: v for k, v in payload.items() if k != "doc_id"}
                                yield f"data: {json.dumps(event_data)}\n\n"
                                last_active = time.time()
                                if event_data.get("phase") in ("completed", "failed"):
                                    break
                                continue
                    except (asyncio.TimeoutError, Exception):
                        pass

                # 3. Block for up to 0.5s, send keepalive if nothing arrived
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=0.5)
                    yield f"data: {json.dumps(data)}\n\n"
                    last_active = time.time()
                    if data.get("phase") in ("completed", "failed"):
                        break
                except asyncio.TimeoutError:
                    pass

                if time.time() - last_active > 25.0:
                    yield ": keepalive\n\n"
                    last_active = time.time()
        finally:
            await _sse_unsubscribe(doc_id, queue)
            if pubsub:
                try:
                    await pubsub.unsubscribe("doc_updates")
                    await pubsub.close()
                except Exception:
                    pass
            if redis_client:
                try:
                    await redis_client.aclose()
                except Exception:
                    pass

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("", response_model=List[Document])
async def list_documents(
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    user_id = str(current_user.get("id"))
    roles = set(current_user.get("roles") or [])
    is_admin = _tenant_org_super_admin(tenant_ctx)
    organization_id = tenant_ctx["organization_id"]

    # Filter based on user roles and assignment
    where_parts = ["d.organization_id = $1::uuid"]
    where_args: list[Any] = [organization_id]

    if not is_admin:
        # Rules:
        # 1. Marketing users: Only see documents they submitted
        # 2. SME/Compliance: See documents assigned to them OR unclaimed documents in their role
        
        # We'll use a complex OR condition in SQL
        # Part A: Submitted by the user (mostly for Marketing)
        # Part B: Assigned specifically to the user (w.assigned_to = user_id)
        # Part C: Unassigned but in the user's role (w.assigned_to IS NULL AND w.assigned_role IN users_roles)
        
        role_list = list(roles)
        role_start_idx = len(where_args) + 1
        role_placeholders = ", ".join([f"${role_start_idx + i}" for i in range(len(role_list))])
        where_args.extend(role_list)
        current_idx = len(where_args)

        where_args.append(user_id)
        user_placeholder = f"${current_idx + 1}"
        
        filter_sql = f"""
            (
                d.submitted_by = {user_placeholder} OR 
                w.assigned_to = {user_placeholder} OR 
                (w.assigned_to IS NULL AND w.assigned_role IN ({role_placeholders})) OR
                EXISTS (
                    SELECT 1 FROM workflow_steps ws 
                    WHERE ws.workflow_id = w.id 
                    AND (ws.claimed_by = {user_placeholder} OR ws.completed_by = {user_placeholder})
                ) OR
                EXISTS (
                    SELECT 1 FROM comment_mentions cm
                    JOIN content_comments cc ON cc.id = cm.comment_id
                    JOIN content_reviews cr_ment ON cr_ment.id = cc.review_id
                    JOIN document_versions dv_ment ON cr_ment.document_version_id = dv_ment.id
                    WHERE dv_ment.document_id = d.id
                      AND cm.mentioned_user_id = {user_placeholder}::uuid
                )
            )
        """
        where_parts.append(filter_sql)

    where_clause = "WHERE " + " AND ".join(where_parts)

    query = f"""
        SELECT
            d.id, d.document_code, d.name, d.type, d.current_version_id,
            d.submitted_by, d.created_at,
            COALESCE(GREATEST(d.updated_at, v.uploaded_at, w.updated_at, cr.updated_at), d.updated_at, d.created_at) AS updated_at,
            v.status as status,
            v.version_label as version_label,
            v.s3_key as version_s3_key,
            cr.id as review_id,
            w.current_stage as workflow_stage,
            w.assigned_to as assigned_to,
            w.assigned_role as assigned_role,
            up_assign.full_name as assigned_to_name
        FROM documents d
        LEFT JOIN document_versions v ON d.current_version_id = v.id
        LEFT JOIN LATERAL (
            SELECT id
            FROM content_reviews
            WHERE document_version_id = v.id
            ORDER BY created_at DESC
            LIMIT 1
        ) cr_lat ON TRUE
        LEFT JOIN content_reviews cr ON cr.id = cr_lat.id
        LEFT JOIN workflows w ON w.review_id = cr.id
        LEFT JOIN user_profiles up_assign ON w.assigned_to = up_assign.id
        {where_clause}
        ORDER BY d.created_at DESC
    """
    rows = await db.fetch(query, *where_args)
    
    docs = []
    valid_types = [
        'educational_content', 'opinion', 'product_feature', 
        'performance_related', 'disclosure', 'client_communications'
    ]
    for r in rows:
        d_dict = dict(r)
        d_dict["id"] = str(d_dict["id"]) if d_dict.get("id") else None
        d_dict["current_version_id"] = str(d_dict["current_version_id"]) if d_dict.get("current_version_id") else None
        d_dict["submitted_by"] = str(d_dict["submitted_by"]) if d_dict.get("submitted_by") else None
        d_dict["review_id"] = str(d_dict["review_id"]) if d_dict.get("review_id") else None
        d_dict["assigned_to"] = str(d_dict["assigned_to"]) if d_dict.get("assigned_to") else None
        d_dict["assigned_to_name"] = d_dict.get("assigned_to_name")  # [Branch 1]
        d_dict["name"] = _ensure_name_has_extension(d_dict.get("name"), d_dict.pop("version_s3_key", None))
        if d_dict.get("workflow_stage") == "sme_approved":
            d_dict["workflow_stage"] = "marketing_review"
        elif d_dict.get("workflow_stage") == "compliance_approved":
            d_dict["workflow_stage"] = "approved"
        
        # Sanitize legacy types on read
        if d_dict.get("type") not in valid_types:
            mapped_type = 'client_communications'
            if d_dict.get("type"):
                lower_type = d_dict["type"].lower().replace(" ", "_")
                for vt in valid_types:
                    if vt in lower_type or lower_type in vt:
                        mapped_type = vt
                        break
            d_dict["type"] = mapped_type
            
        docs.append(Document(**d_dict))
    return docs

@router.get("/{doc_id}", response_model=Document)
async def get_document(
    doc_id: str,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    return await _document_model_for_user(db, doc_id, current_user, tenant_ctx)


@router.get("/versions/{version_id}/file-url")
async def get_version_file_url(
    version_id: str,
    download: bool = Query(False),
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    """Presigned S3 URL for the original file (embeds/previews cannot send Authorization headers to streamed URLs).
    
    NOTE: filename is intentionally NOT passed to allow inline display instead of attachment/download unless download is explicitly requested.
    For audit trail previews, we want to show the document inline in an iframe, not trigger download.
    """
    try:
        row = await db.fetchrow(
            """
            SELECT dv.id, dv.s3_bucket, dv.s3_key, dv.document_id
            FROM document_versions dv
            JOIN documents d ON d.id = dv.document_id
            WHERE dv.id = $1 AND d.organization_id = $2
            """,
            version_id,
            tenant_ctx["organization_id"],
        )
        if not row:
            raise HTTPException(status_code=404, detail="Version not found")

        doc_id = str(row["document_id"])
        await _document_model_for_user(db, doc_id, current_user, tenant_ctx)

        bucket = row["s3_bucket"] or ai_config.AWS_S3_BUCKET
        key = row["s3_key"]
        if not key:
            raise HTTPException(status_code=404, detail="S3 key not found for this version")

        file_name = key.split("/")[-1]
        ext = file_name.split(".")[-1].lower() if "." in file_name else ""
        if not download and f".{ext}" in _OFFICE_PREVIEW_EXTENSIONS:
            return await _build_office_pdf_preview_response(
                db=db,
                doc_id=doc_id,
                version_id=version_id,
                bucket=bucket,
                source_key=key,
            )
        # Pass filename only when download is requested to enable ResponseContentDisposition: attachment
        url = _presigned_url_for_key(bucket, key, filename=file_name if download else None)
        mime = _mime_from_extension(ext) if ext else "application/octet-stream"
        return {
            "url": url,
            "file_name": file_name,
            "mime": mime,
            "original_url": url,
            "original_file_name": file_name,
            "original_mime": mime,
            "preview_fallback": False,
        }
    except HTTPException:
        raise
    except Exception as e:
        log_error(
            error=e,
            category=ErrorCategory.FILE_UPLOAD,
            operation="get_version_file_url",
            severity=ErrorSeverity.ERROR,
            context={"version_id": version_id}
        )
        raise HTTPException(status_code=500, detail="Unable to load document. Please try again later.")


@router.get("/versions/{version_id}/file")
async def get_version_file(
    version_id: str,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    """Serve the original document file from S3 for a specific version."""
    row = await db.fetchrow(
        """
        SELECT dv.id, dv.s3_bucket, dv.s3_key, dv.document_id
        FROM document_versions dv
        JOIN documents d ON d.id = dv.document_id
        WHERE dv.id = $1 AND d.organization_id = $2
        """,
        version_id,
        tenant_ctx["organization_id"],
    )
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")

    doc_id = str(row["document_id"])

    await _document_model_for_user(db, doc_id, current_user, tenant_ctx)
    
    bucket = row["s3_bucket"] or ai_config.AWS_S3_BUCKET
    key = row["s3_key"]
    
    if not key:
        raise HTTPException(status_code=404, detail="S3 key not found for this version")

    file_name = key.split("/")[-1]
    ext = _extension_from_filename(file_name)
    media_type = _mime_from_extension(ext) if ext else "application/octet-stream"

    try:
        response = s3_helper.s3_client.get_object(Bucket=bucket, Key=key)
        return StreamingResponse(
            io.BytesIO(response['Body'].read()), 
            media_type=media_type,
        )
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        log_s3_error(
            error=e,
            operation="get_object",
            resource=key,
            context={"bucket": bucket, "error_code": error_code, "version_id": version_id}
        )
        raise HTTPException(status_code=500, detail="Unable to fetch document. Please try again later.")
    except Exception as e:
        log_error(
            error=e,
            category=ErrorCategory.FILE_UPLOAD,
            operation="stream_document_file",
            severity=ErrorSeverity.ERROR,
            context={"version_id": version_id, "key": key}
        )
        raise HTTPException(status_code=500, detail="Unable to fetch document. Please try again later.")

@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    organization_id = tenant_ctx["organization_id"]
    await _require_document_in_org_for_user(db, doc_id, current_user, tenant_ctx)

    await db.execute("DELETE FROM documents WHERE id=$1 AND organization_id=$2", doc_id, organization_id)

    return {"ok": True}

@router.post("/upload", response_model=Document)
async def upload_document(
    document_name: str = Form(...),
    document_type: str = Form(...),
    file: UploadFile = File(...),
    routing: Optional[str] = Form(None),
    sme_reviewer_id: Optional[str] = Form(None),
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db=Depends(get_db),
):
    """
    Critical operation: Upload a new marketing document.
    Handles file validation, S3 storage, database record creation, and workflow initialization.
    """
    user_id = (current_user or {}).get("id")
    roles = set((current_user or {}).get("roles") or [])
    
    logger.info(f"[UPLOAD_START] User: {user_id}, Document: {document_name}, File: {file.filename}")
    
    try:
        # Normalize roles to lowercase for case-insensitive comparison
        roles_lower = {r.lower().strip() if isinstance(r, str) else str(r).lower().strip() for r in roles}

        # Only marketing + super admin (global or org-scoped) can upload
        if (
            "marketing" not in roles_lower
        ):
            error_msg = f"User {user_id} lacks upload permissions. Roles: {list(roles)}"
            log_validation_error(
                ValueError(error_msg),
                operation="document_upload_permission_check",
                field="user_roles",
                value=list(roles),
            )
            logger.warning(error_msg)
            raise HTTPException(
                status_code=403, 
                detail=f"Only marketing and super admin can upload documents. Your roles: {', '.join(roles) if roles else 'none'}"
            )

        # For dev without full auth:
        if not user_id:
            row = await db.fetchrow("SELECT id FROM user_profiles LIMIT 1")
            user_id = row['id'] if row else None

        organization_id = tenant_ctx["organization_id"]
            
        doc_id = str(uuid.uuid4())
        version_id = str(uuid.uuid4())
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        
        # 1. Document code generation moved to DB transaction to prevent concurrency bugs        
        # 1.5 Map document_type to enum
        valid_types = [
            'educational_content', 'opinion', 'product_feature', 
            'performance_related', 'disclosure', 'client_communications'
        ]
        mapped_type = 'client_communications'
        lower_type = document_type.lower().replace(" ", "_")
        for vt in valid_types:
            if vt in lower_type or lower_type in vt:
                mapped_type = vt
                break
        document_type = mapped_type
        logger.debug(f"[UPLOAD] Mapped document type: {document_type}")

        # 2. Read file
        try:
            content = await file.read()
            file_size = len(content)
            logger.info(f"[UPLOAD] File read successfully. Size: {file_size} bytes, Name: {file.filename}")
        except Exception as e:
            log_upload_error(
                e,
                "read_uploaded_file",
                filename=file.filename,
                context={"user_id": user_id},
            )
            raise HTTPException(status_code=400, detail=f"Failed to read uploaded file: {str(e)}")

        # 3. Validate file
        try:
            content_type = _validate_marketing_upload(file.filename or "", content)
            logger.info(f"[UPLOAD] File validation passed. Content-Type: {content_type}")
        except HTTPException as e:
            log_upload_error(
                ValueError(e.detail),
                "validate_uploaded_file",
                filename=file.filename,
                file_size=file_size,
                context={"validation_error": e.detail, "user_id": user_id},
            )
            logger.warning(f"[UPLOAD] File validation failed: {e.detail}")
            raise

        quota_precheck = await evaluate_upload_quota_change(
            db,
            str(organization_id),
            incoming_upload_count=1,
            incoming_upload_bytes=file_size,
        )
        if quota_precheck["should_block"]:
            _raise_upload_quota_exceeded(quota_precheck)

        # 4. Save to S3
        try:
            s3_key = save_marketing_doc_versioned(
                document_id=doc_id,
                file_name=file.filename or "uploaded.pdf",
                file_bytes=content,
                content_type=content_type,
            )
            logger.info(f"[UPLOAD] S3 save successful. Key: {s3_key}")
        except Exception as e:
            log_s3_error(
                e,
                "save_document_to_s3",
                bucket=ai_config.AWS_S3_BUCKET,
                context={"document_id": doc_id, "user_id": user_id}
            )
            logger.error(f"[UPLOAD] S3 save failed: {str(e)}. Fallback S3 key generated.")
            # Fallback for demo mode
            s3_key = f"marketing_docs/{doc_id}/1.0/{file.filename}"
        
        # 5. Save to DB (document + version + initial review + workflow)
        try:
            async with db.transaction():
                await acquire_upload_quota_lock(db, str(organization_id))
                quota_locked_check = await evaluate_upload_quota_change(
                    db,
                    str(organization_id),
                    incoming_upload_count=1,
                    incoming_upload_bytes=file_size,
                )
                if quota_locked_check["should_block"]:
                    _raise_upload_quota_exceeded(quota_locked_check)

                # [CONCURRENCY FIX] Acquire advisory lock for this tenant to prevent race conditions
                # The lock is automatically released at the end of this transaction.
                await db.execute("SELECT pg_advisory_xact_lock(hashtext($1))", str(organization_id))
                
                # Safely generate document_code now that we hold the lock
                count_row = await db.fetchrow(
                    "SELECT COUNT(*)::int AS c FROM documents WHERE organization_id = $1",
                    organization_id,
                )
                next_num = (count_row["c"] or 0) + 1
                doc_code = f"DOC-{next_num:03d}"
                logger.debug(f"[UPLOAD] Generated document code: {doc_code}")

                # documents table
                await db.execute(
                    """
                    INSERT INTO documents (id, organization_id, document_code, name, type, submitted_by, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $7)
                    """,
                    doc_id, organization_id, doc_code, document_name, document_type, user_id, now_utc
                )
                logger.debug(f"[UPLOAD] Document record created in DB. Doc ID: {doc_id}")
                
                # document_versions table
                await db.execute(
                    """
                    INSERT INTO document_versions (
                        id, document_id, version_label, uploaded_at, status, s3_bucket, s3_key, extracted_text, file_size_bytes
                    )
                    VALUES ($1, $2, '1.0', $3, 'processing', $4, $5, NULL, $6)
                    """,
                    version_id, doc_id, now_utc, ai_config.AWS_S3_BUCKET or 'demo-bucket', s3_key, file_size
                )
                logger.debug(f"[UPLOAD] Document version record created. Version ID: {version_id}")
                
                # update current_version_id
                await db.execute(
                    "UPDATE documents SET current_version_id=$1 WHERE id=$2",
                    version_id, doc_id
                )

                # Initialize a review + workflow so assignment/claiming exists before AI runs
                review_id = str(uuid.uuid4())
                workflow_id = str(uuid.uuid4())

                # Workflow start depends on routing:
                # - "sme": SME review first (default)
                # - "marketing": direct marketing review (skip SME)
                route = (routing or "").strip().lower()
                if route in {"marketing", "marketing_review", "admin"}:
                    initial_stage = "marketing_review"
                    assigned_role = "marketing"
                    initial_assignee = user_id
                else:
                    # Default: go to SME review stage
                    initial_stage = "sme_review"
                    assigned_role = "sme"
                    # Assign SME if provided, otherwise leave unassigned (all SMEs can claim)
                    initial_assignee = sme_reviewer_id if sme_reviewer_id else None

                logger.debug(f"[UPLOAD] Workflow initialized. Stage: {initial_stage}, Role: {assigned_role}")

                # Backwards compatible: some environments may not have `compliance_status` on `content_reviews`.
                try:
                    await db.execute(
                        """
                        INSERT INTO content_reviews (id, content_type, document_version_id, compliance_status, review_status, created_at, updated_at)
                        VALUES ($1, 'marketing_material', $2, 'conditional', 'pending', $3, $3)
                        """,
                        review_id, version_id, now_utc
                    )
                except asyncpg.UndefinedColumnError as e:
                    log_db_error(e, "insert_content_review", query="CREATE review without compliance_status")
                    await db.execute(
                        """
                        INSERT INTO content_reviews (id, content_type, document_version_id, review_status, created_at, updated_at)
                        VALUES ($1, 'marketing_material', $2, 'pending', $3, $3)
                        """,
                        review_id, version_id, now_utc
                    )

                await db.execute(
                    """
                    INSERT INTO workflows (id, review_id, current_stage, assigned_to, assigned_role, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $6)
                    """,
                    workflow_id, review_id, initial_stage, initial_assignee, assigned_role, now_utc
                )
                logger.debug(f"[UPLOAD] Workflow record created. Workflow ID: {workflow_id}")

                await db.execute(
                    """
                    INSERT INTO workflow_steps (
                        id, workflow_id, stage, action, comment, previous_stage, step_order, completed_by, completed_at, created_at
                    ) VALUES ($1, $2, 'marketing_review', $3, $4, $5, 1, $6, $7, $7)
                    """,
                    str(uuid.uuid4()),
                    workflow_id,
                    "uploaded",
                    None,
                    None,
                    user_id,
                    now_utc,
                )
                logger.debug(f"[UPLOAD] Workflow step created.")

                # Log audit event for document upload
                try:
                    role_row = await db.fetchrow(
                        "SELECT string_agg(r.name, ', ' ORDER BY r.name) as names FROM user_roles ur JOIN roles r ON ur.role_id = r.id WHERE ur.user_id = $1",
                        user_id,
                    )
                    user_role = role_row["names"] if role_row and role_row["names"] else "unknown"
                    
                    await log_audit_event(
                        db,
                        review_id=review_id,
                        event_type="document_upload",
                        description=f"Document '{document_name}' uploaded",
                        user_id=user_id,
                        user_role=user_role,
                        workflow_stage=initial_stage,
                        details=f"Document type: {document_type}, Version: 1.0",
                    )
                    logger.info(f"[UPLOAD] Audit event logged for document upload")
                except Exception as e:
                    log_db_error(e, "log_audit_event_upload", user_id=user_id)
                    logger.error(f"[UPLOAD] Failed to log audit event: {str(e)}")

                # Workflow transition notifications and emails are now deferred until after background
                # AI classification completes successfully, ensuring out-of-scope files do not trigger alerts.
                pass

        except HTTPException:
            # Re-raise explicit HTTP exceptions (e.g. 409 Quota Exceeded) 
            raise
        except Exception as e:
            log_db_error(
                e,
                "create_document_records",
                context={"document_id": doc_id, "user_id": user_id, "file": file.filename},
                user_id=user_id,
            )
            logger.error(f"[UPLOAD] Failed to create database records: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to create document records: {str(e)}")

        # Classification and pre-extraction now handled fully in background via Celery worker.
        try:
            from apis.services.celery_tasks import classify_document_task
            classify_document_task.delay(
                doc_id=doc_id,
                version_id=version_id,
                bucket=ai_config.AWS_S3_BUCKET or "demo-bucket",
                s3_key=s3_key,
                user_id=user_id,
                initial_stage=initial_stage,
                organization_id=tenant_ctx.get("organization_id")
            )
            logger.info("[UPLOAD] Classification and pre-extraction queued via Celery. doc_id=%s version_id=%s", doc_id, version_id)
        except Exception as class_err:
            logger.warning(
                "UPLOAD_CLASSIFICATION_DISPATCH_FAILED doc_id=%s version_id=%s err=%s",
                doc_id, version_id, str(class_err)
            )

        # Warm Office preview cache in background on upload (doc/docx/ppt/pptx).
        source_ext = _extension_from_filename(file.filename or Path(s3_key).name)
        if source_ext in _OFFICE_PREVIEW_EXTENSIONS:
            from apis.services.celery_tasks import warm_office_preview_task
            warm_office_preview_task.delay(
                doc_id,
                version_id,
                ai_config.AWS_S3_BUCKET or "demo-bucket",
                s3_key,
            )
            logger.info("[UPLOAD] Office preview warmup queued via Celery. doc_id=%s version_id=%s", doc_id, version_id)

        try:
            logger.info(f"[UPLOAD_SUCCESS] Document uploaded successfully. Doc ID: {doc_id}, Code: {doc_code}")
            return await _document_model_for_user(db, doc_id, current_user, tenant_ctx)
        except Exception as e:
            log_db_error(e, "fetch_created_document", context={"document_id": doc_id}, user_id=user_id)
            raise HTTPException(status_code=500, detail=f"Document created but failed to retrieve: {str(e)}")

    except HTTPException:
        raise
    except Exception as e:
        log_error(
            e,
            ErrorCategory.FILE_UPLOAD,
            "upload_document",
            ErrorSeverity.CRITICAL,
            context={"file": file.filename, "document_name": document_name},
            user_id=user_id,
        )
        logger.error(f"[UPLOAD_FAILED] Unexpected error during document upload: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to upload document: {str(e)}")

async def _prebuild_annotated_pdf(
    doc_id: str, version_id: str, review_id: str,
    bucket: str, source_key: str, pdf_bytes: bytes, db=None,
):
    """Pre-build annotated PDF artifact so the first preview is instant.
    Acquires its own DB connection from the pool to avoid contention
    when called concurrently with other operations on the caller's connection.
    Retries once on transient errors (e.g. connection busy).
    """
    from apis.core.database import db_pool
    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        try:
            async with db_pool.acquire() as conn:
                findings_rows = await conn.fetch(
                    "SELECT claim_text, location FROM ai_findings WHERE review_id=$1 AND claim_text IS NOT NULL AND claim_text != ''",
                    review_id,
                )
                if not findings_rows:
                    return

                claims_with_location = [{"claim": r["claim_text"], "location": r["location"]} for r in findings_rows]
                findings_hash = _build_findings_hash(claims_with_location)
                cache_key = _annotation_cache_key(doc_id, version_id, findings_hash, source_key)

                try:
                    s3_helper.s3_client.head_object(Bucket=bucket, Key=cache_key)
                    return
                except ClientError:
                    pass

                highlights = []
                for idx, row in enumerate(findings_rows):
                    color = _HIGHLIGHT_PALETTE[idx % len(_HIGHLIGHT_PALETTE)]
                    highlights.append((row["claim_text"], color, None))

                from apis.services.ai.processing.highlighting import highlight_pdf_bytes
                annotated = await asyncio.to_thread(highlight_pdf_bytes, pdf_bytes, highlights)

                now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                s3_helper.s3_client.put_object(Bucket=bucket, Key=cache_key, Body=annotated, ContentType="application/pdf")
                await conn.execute(
                    """
                    INSERT INTO ai_annotated_artifacts (
                        id, document_id, document_version_id, review_id, findings_hash,
                        s3_bucket, s3_key, engine_version, generated_at, last_accessed_at
                    ) VALUES ($1, $2::uuid, $3::uuid, $4::uuid, $5, $6, $7, $8, $9, $9)
                    ON CONFLICT (document_version_id, findings_hash, engine_version)
                    DO UPDATE SET s3_bucket=EXCLUDED.s3_bucket, s3_key=EXCLUDED.s3_key,
                                  generated_at=EXCLUDED.generated_at, last_accessed_at=EXCLUDED.last_accessed_at
                    """,
                    str(uuid.uuid4()), doc_id, version_id, review_id,
                    findings_hash, bucket, cache_key, _ANNOTATION_ENGINE_VERSION, now_utc,
                )
                logger.info("PREBUILD_ANNOTATED_PDF_DONE doc_id=%s findings=%d", doc_id, len(findings_rows))
                return
        except Exception as e:
            if attempt < max_attempts:
                logger.info("PREBUILD_ANNOTATED_PDF_RETRY doc_id=%s attempt=%d err=%s", doc_id, attempt, e)
                await asyncio.sleep(1.0)
            else:
                logger.warning("PREBUILD_ANNOTATED_PDF_ERR doc_id=%s err=%s", doc_id, e)


def _publish_phase(doc_id: str, phase: str, rules_checked: int, rules_total: int):
    """Publish an SSE progress event for all connected subscribers.
    Writes to both:
    - the in-memory queue (for same-process API subscribers)
    - Redis pub/sub (for cross-process Celery worker → API → browser path)
    """
    payload = {
        "phase": phase,
        "rules_checked": rules_checked,
        "rules_total": rules_total,
    }
    # In-memory path (works when analysis runs in the API process)
    _sse_publish(doc_id, payload)

    # Redis path (works when analysis runs in the Celery worker container)
    try:
        import redis as _redis_sync
        import json as _json
        _r = _redis_sync.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
        _r.publish("doc_updates", _json.dumps({"doc_id": doc_id, **payload}))
        _r.close()
    except Exception:
        pass  # Non-fatal: browser will still work via in-memory path when in same process


async def _emit_rule_progress_event(
    doc_id: str, review_id: str, rules_checked: int, rules_total: int, user_id: Optional[str]
):
    """Emit SSE progress update for rule checking (no audit trail entry for intermediate steps)."""
    _publish_phase(doc_id, "performing_ai_analysis", rules_checked, rules_total)


async def _analyze_document_pipeline(
    doc_id: str,
    triggered_by_user_id: Optional[str] = None,
) -> dict:
    """
    Long-running S3 + LLM work must not hold a pool connection (asyncpg default pool is small;
    starving login and other APIs). Use short acquire() bursts + no DB during compute.
    """
    from apis.core.database import db_pool

    if not db_pool:
        raise HTTPException(status_code=500, detail="Database not initialized")

    findings_saved = 0  # [Branch 2] initialize early
    user_id_to_log = triggered_by_user_id

    # Phase 1: short DB read + audit (release connection before heavy work)
    enabled_rules_total = 1
    async with db_pool.acquire() as db:
        review_row_pre = await db.fetchrow(
            """
            SELECT cr.id as review_id
            FROM documents d
            JOIN document_versions dv ON d.current_version_id = dv.id
            JOIN content_reviews cr ON cr.document_version_id = dv.id
            WHERE d.id = $1
            ORDER BY cr.created_at DESC
            LIMIT 1
            """,
            doc_id,
        )
        review_id_pre = str(review_row_pre["review_id"]) if review_row_pre else None

        if review_id_pre:
            # Guard: if another run already completed for this review, exit early.
            already_done = await db.fetchrow(
                """
                SELECT event_type FROM audit_events
                WHERE review_id=$1 AND is_ai=true
                  AND event_type = 'ai_analysis_completed'
                ORDER BY created_at DESC LIMIT 1
                """,
                review_id_pre,
            )
            if already_done:
                logger.info(
                    "PIPELINE_SKIP doc_id=%s review_id=%s reason=already_completed",
                    doc_id, review_id_pre,
                )
                _publish_phase(doc_id, "completed", 0, 1)
                return {"ok": True, "review_id": review_id_pre, "violations_count": 0}

            # Only log ai_analysis_started if the queue helper didn't already.
            existing_start = await db.fetchrow(
                """
                SELECT 1 FROM audit_events
                WHERE review_id=$1 AND is_ai=true
                  AND event_type = 'ai_analysis_started'
                ORDER BY created_at DESC LIMIT 1
                """,
                review_id_pre,
            )
            if not existing_start:
                await log_audit_event(
                    db,
                    review_id=review_id_pre,
                    event_type="ai_analysis_started",
                    description="AI compliance analysis started",
                    is_ai=True,
                    triggered_by_user_id=user_id_to_log,
                )
            enabled_rules_total = max(
                1, int(await db.fetchval("SELECT COUNT(*) FROM compliance_rules") or 0)
            )
            _publish_phase(doc_id, "parsing_document", 0, enabled_rules_total)

        doc_row = await db.fetchrow(
            "SELECT d.*, dv.id as version_id, dv.extracted_text, dv.s3_bucket, dv.s3_key FROM documents d "
            "LEFT JOIN document_versions dv ON d.current_version_id = dv.id WHERE d.id=$1",
            doc_id,
        )
        if not doc_row:
            raise HTTPException(status_code=404, detail="Document not found")

        html_content = decode_extracted_text(doc_row["extracted_text"])
        version_id = doc_row["version_id"]
        bucket = doc_row.get("s3_bucket") or ai_config.AWS_S3_BUCKET
        key = doc_row.get("s3_key")

    # Phase 2: S3 + parse (no pool connection held during download / docling)
    # We always download raw bytes so PyMuPDF can locate violations physically later.
    pdf_bytes: bytes | None = None

    if key:
        def _download_raw() -> bytes:
            resp = s3_helper.s3_client.get_object(Bucket=bucket, Key=key)
            raw_bytes = resp["Body"].read()
            source_ext = _extension_from_filename(key)
            if source_ext in _OFFICE_PREVIEW_EXTENSIONS:
                raw_bytes, _ = _convert_office_to_pdf_bytes(raw_bytes, Path(key).name)
            return raw_bytes

        try:
            pdf_bytes = await asyncio.to_thread(_download_raw)
        except Exception as e:
            logger.warning("PDF_DOWNLOAD_WARN doc_id=%s error=%s (location lookup disabled)", doc_id, str(e))
            pdf_bytes = None

    # Lazy import — only needed in worker, not in slim API container
    from apis.services.ai.compliance_engine.models import ExtractionResult

    # Vision from same Docling workspace when we parse here (single temp, one Docling run).
    visual_prefetch: ExtractionResult | None = None

    if not html_content:
        if not key or pdf_bytes is None:
            raise HTTPException(status_code=404, detail="Document S3 key not found")

        def _parse_pdf_to_html_and_visual(
            raw: bytes, llm: Any, doc_id_for_log: str
        ) -> tuple[str, ExtractionResult | None]:
            """One temp dir: Docling parse + optional vision from artifacts; dir removed on exit."""
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
                logger.debug(
                    "ANALYSIS_PARSE_TEMP_CREATED doc_id=%s path=%s", doc_id_for_log, tmpdir
                )
                pdf_path = Path(tmpdir) / "input.pdf"
                pdf_path.write_bytes(raw)
                from apis.services.ai.processing.parsing import Parsing
                parser = Parsing(pdf_path)
                out_dir = Path(tmpdir) / "out"
                html_path = parser.add_metadata_to_file(out_dir, "output.html")
                html_str = html_path.read_text(encoding="utf-8")
                vm: ExtractionResult | None = None
                if hasattr(llm, "invoke_with_image"):
                    try:
                        vm = extract_visual_extractions_from_html_workspace(html_path, llm)
                    except Exception as ve:
                        logger.warning(
                            "VISUAL_PREFETCH_FAILED doc_id=%s err=%s",
                            doc_id_for_log,
                            str(ve),
                        )
            logger.debug(
                "ANALYSIS_PARSE_TEMP_REMOVED doc_id=%s path=%s (TemporaryDirectory cleanup)",
                doc_id_for_log,
                tmpdir,
            )
            return html_str, vm

        try:
            html_content, visual_prefetch = await asyncio.to_thread(
                _parse_pdf_to_html_and_visual, pdf_bytes, llm_client, doc_id
            )
        except Exception as e:
            logger.error("DOCLING_PARSE_ERROR doc_id=%s error=%s", doc_id, str(e))
            raise HTTPException(status_code=500, detail=f"Docling parsing failed: {str(e)}")

        if visual_prefetch and visual_prefetch.claims:
            logger.info(
                "VISUAL_PREFETCH_OK doc_id=%s visual_claims=%s (single_parse_workspace)",
                doc_id,
                len(visual_prefetch.claims),
            )

        async with db_pool.acquire() as db:
            await db.execute(
                "UPDATE document_versions SET extracted_text=$1 WHERE id=$2",
                encode_extracted_text(html_content),
                version_id,
            )

    if not html_content:
        raise HTTPException(status_code=404, detail="Document text extraction failed")

    # Phase 3: classification + chunking + LLM (no DB)
    # Emit classification phase event
    if review_id_pre:
        _publish_phase(doc_id, "classifying_document", 0, enabled_rules_total)

    from apis.services.ai.processing.chunking import Chunker
    from apis.services.ai.compliance_engine.classifier import ClassifierService
    from apis.services.ai.llm.client import get_llm_client
    
    # Run chunking + classification in parallel (both only need html_content)
    chunker = Chunker()
    local_classifier = ClassifierService()
    local_llm_client = get_llm_client()
    
    chunks_raw, classification = await asyncio.gather(
        asyncio.to_thread(chunker.chunk_html_with_media, html_content),
        asyncio.to_thread(local_classifier.classify_document, html_content),
    )
    chunk_texts = [c.get("text", "") for c in chunks_raw if (c.get("text") or "").strip()]
    chunk_metadatas = [c.get("metadata", []) for c in chunks_raw if (c.get("text") or "").strip()]
    # Visual triage (images + tables): analyze vs skip — logged for ops; vision merge comes later.
    try:
        from apis.services.ai.processing.media_triage import triage_html_metadata
        media_triage = await asyncio.to_thread(triage_html_metadata, html_content)
        mt = media_triage.get("summary") or {}
        logger.info(
            "MEDIA_TRIAGE doc_id=%s total_visual=%s to_analyze=%s to_skip=%s "
            "analyze_images=%s analyze_tables=%s skip_images=%s skip_tables=%s",
            doc_id,
            mt.get("total_visual_items_detected"),
            mt.get("to_analyze"),
            mt.get("to_skip"),
            mt.get("analyze_images"),
            mt.get("analyze_tables"),
            mt.get("skip_images"),
            mt.get("skip_tables"),
        )
    except Exception as e:
        logger.warning("MEDIA_TRIAGE_FAILED doc_id=%s error=%s", doc_id, str(e))

    # Phase 3: chunking + LLM (no DB)
    from apis.services.ai.processing.chunking import Chunker
    from apis.services.ai.llm.client import get_llm_client
    chunker = Chunker()
    local_llm_client = get_llm_client()
    chunks_raw = chunker.chunk_html_with_media(html_content)
    chunk_texts, chunk_metadatas = _chunk_texts_and_metadata_with_tables(chunks_raw)
    
    # Limit for demo to avoid huge costs/time
    MAX_CHUNKS = getattr(local_llm_client, "MAX_CHUNKS", 5)
    if MAX_CHUNKS:
        chunk_texts = chunk_texts[:MAX_CHUNKS]
        chunk_metadatas = chunk_metadatas[:MAX_CHUNKS]

    # [Branch 2] Document Classification — already ran in parallel above
    is_in_scope = classification.get("is_in_scope", True)

    pipeline_result = None
    skip_analysis = False

    if not is_in_scope:
        logger.info("CLASSIFICATION_SKIP doc_id=%s type=%s", doc_id, classification.get("detected_type"))
        skip_analysis = True
    else:
        _publish_phase(doc_id, "performing_ai_analysis", 0, enabled_rules_total)

        # Thread-safe callback: emit per-rule progress audit events from the pipeline thread
        _loop = asyncio.get_running_loop()
        _last_emitted_count = 0

        def _on_rules_progress(completed_rules: set[int]):
            nonlocal _last_emitted_count
            count = len(completed_rules)
            if count <= _last_emitted_count:
                return
            _last_emitted_count = count
            asyncio.run_coroutine_threadsafe(
                _emit_rule_progress_event(
                    doc_id, review_id_pre, count, enabled_rules_total, user_id_to_log
                ),
                _loop,
            )
        # Re-use vision from single-parse path when present; else one parse for cached HTML.
        visual_merge = visual_prefetch
        if not visual_merge and pdf_bytes:
            try:
                from apis.services.ai.processing.visual_document import extract_visual_extractions_from_pdf_bytes
                from apis.services.ai.llm.client import get_llm_client
                local_llm_client = get_llm_client()
                visual_merge = await asyncio.to_thread(
                    extract_visual_extractions_from_pdf_bytes,
                    pdf_bytes,
                    local_llm_client,
                )
            except Exception as e:
                logger.warning("VISUAL_EXTRACT_FAILED doc_id=%s err=%s", doc_id, str(e))
        if visual_merge and visual_merge.claims:
            logger.info(
                "VISUAL_EXTRACT_MERGED doc_id=%s visual_claims=%s prefetch=%s",
                doc_id,
                len(visual_merge.claims),
                bool(visual_prefetch),
            )

        try:
            from apis.services.ai.compliance_engine.pipeline import run_pipeline
            from apis.services.ai.llm.client import get_llm_client
            local_llm_client = get_llm_client()
            # Run synchronous pipeline in a thread so it doesn't block the async event loop
            pipeline_result = await asyncio.to_thread(
                lambda vm=visual_merge: run_pipeline(
                    chunks=chunk_texts,
                    llm_client=local_llm_client,
                    document_id=str(doc_id),
                    metadata_dicts=chunk_metadatas,
                    on_rules_progress=_on_rules_progress if review_id_pre else None,
                    visual_extraction_merge=vm,
                )
            )

            # [Branch 1] Log pipeline result summary
            logger.info(
                "AI_PIPELINE_RESULT doc_id=%s violations_count=%s chunks_processed=%s",
                doc_id,
                len(pipeline_result.violations) if pipeline_result else 0,
                len(chunk_texts)
            )

            # [Branch 1] Log each violation structure
            if pipeline_result:
                for idx, v in enumerate(pipeline_result.violations):
                    logger.info(
                        "AI_VIOLATION doc_id=%s idx=%s rule=%s severity=%s has_what_was_checked=%s has_would_break_compliance=%s has_suggested_alternative=%s",
                        doc_id, idx, v.rule, v.severity,
                        bool(getattr(v, "what_was_checked", "")),
                        bool(getattr(v, "would_break_compliance", "")),
                        bool(getattr(v, "suggested_alternative", ""))
                    )
                    logger.debug(
                        "AI_VIOLATION_FULL doc_id=%s idx=%s violation=%s",
                        doc_id, idx,
                        {
                            "rule": v.rule,
                            "rule_name": v.rule_name,
                            "severity": v.severity,
                            "reasoning": v.reasoning[:100] if v.reasoning else "",
                            "what_was_checked": getattr(v, "what_was_checked", ""),
                            "would_break_compliance": getattr(v, "would_break_compliance", ""),
                            "suggested_alternative": getattr(v, "suggested_alternative", ""),
                        }
                    )
        except Exception as e:
            logger.error("AI_PIPELINE_ERROR doc_id=%s error=%s", doc_id, str(e))
            raise HTTPException(status_code=500, detail=f"AI Pipeline failed: {str(e)}")

    violations_count = len(pipeline_result.violations) if pipeline_result else 0
    rules_checked = enabled_rules_total

    # Phase 4: persist results (single short acquire + transaction)
    async with db_pool.acquire() as db:
        # Find existing review/workflow for this version (created at upload); fallback if missing.
        review_row = await db.fetchrow(
            "SELECT id FROM content_reviews WHERE document_version_id=$1 ORDER BY created_at DESC LIMIT 1",
            version_id,
        )
        review_id = str(review_row["id"]) if review_row else str(uuid.uuid4())
        _publish_phase(doc_id, "consolidating_result", rules_checked, enabled_rules_total)

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        # Determine compliance status
        compliance_status = "pass"
        if not skip_analysis and pipeline_result:
            highest_severity = "low"
            for v in pipeline_result.violations:
                if v.severity.lower() == "high":
                    highest_severity = "high"
                elif v.severity.lower() == "medium" and highest_severity != "high":
                    highest_severity = "medium"
            compliance_status = "conditional" if pipeline_result.violations else "pass"
            if highest_severity == "high":
                compliance_status = "fail"

        async with db.transaction():
            if not review_row:
                # Create review and workflow if missing (older data)
                try:
                    await db.execute(
                        """
                        INSERT INTO content_reviews (id, content_type, document_version_id, compliance_status, review_status, created_at, updated_at)
                        VALUES ($1, 'marketing_material', $2, $3, 'pending', $4, $4)
                        """,
                        review_id, version_id, compliance_status, now_utc
                    )
                except asyncpg.UndefinedColumnError:
                    await db.execute(
                        """
                        INSERT INTO content_reviews (id, content_type, document_version_id, review_status, created_at, updated_at)
                        VALUES ($1, 'marketing_material', $2, 'pending', $3, $3)
                        """,
                        review_id, version_id, now_utc
                    )
                await db.execute(
                    """
                    INSERT INTO workflows (id, review_id, current_stage, created_at, updated_at)
                    VALUES ($1, $2, 'marketing_review', $3, $3)
                    """,
                    str(uuid.uuid4()), review_id, now_utc
                )
            else:
                # Update existing review status + compliance status
                try:
                    await db.execute(
                        """
                        UPDATE content_reviews
                        SET compliance_status=$1, updated_at=$2
                        WHERE id=$3
                        """,
                        compliance_status, now_utc, review_id
                    )
                except asyncpg.UndefinedColumnError:
                    await db.execute(
                        "UPDATE content_reviews SET updated_at=$1 WHERE id=$2",
                        now_utc, review_id,
                    )

            # Clear old findings for idempotent re-run
            await db.execute("DELETE FROM ai_findings WHERE review_id=$1", review_id)

            # Rules mapping
            rules_rows = await db.fetch("SELECT id, rule_code FROM compliance_rules")
            rule_map = {r["rule_code"]: r["id"] for r in rules_rows}

            logger.info(
                "analyze_document saving findings doc_id=%s review_id=%s rule_map_size=%s",
                doc_id, review_id, len(rule_map),
            )

            if not rule_map:
                logger.error("No compliance rules found in database! Findings cannot be saved.")
                return {"ok": False, "review_id": review_id, "violations_count": violations_count}

            # Persist classifier skip on the version so list views can render non-educational correctly.
            if skip_analysis:
                await db.execute(
                    "UPDATE document_versions SET status='skipped' WHERE id=$1",
                    version_id,
                )

            # [Branch 2] If document was skipped by classifier, insert an informational "out of scope" finding
            if skip_analysis:
                finding_id = str(uuid.uuid4())
                rule_id = list(rule_map.values())[0]  # Use first rule as placeholder
                await db.execute(
                    """
                    INSERT INTO ai_findings (
                        id, finding_code, review_id, rule_id, title, risk_level, description,
                        why_risky, rationale, ai_suggestion, location, status, created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'pending', $12)
                    """,
                    finding_id,
                    f"FIND-{int(now_utc.timestamp())}-SKIP",
                    review_id,
                    rule_id,
                    "Document Out of Scope",
                    "LOW",
                    "Compliance analysis skipped: This document was identified as non-educational content and is out of scope.",
                    "N/A - This content does not fall under standard compliance review requirements.",
                    "The internal AI classifier determined that this document is not 'Educational Content'.",
                    "No compliance action needed.",
                    "Document Level",
                    now_utc,
                )
            elif pipeline_result:
                # --- Batch all find_claim_location calls in parallel ---
                async def _fallback_location(fb: str) -> str:
                    return fb

                loc_tasks = []
                for v in pipeline_result.violations:
                    claim_text_for_loc = (
                        getattr(v, "claim_text", "")
                        or getattr(v, "problematic_phrase", "")
                        or ""
                    )
                    if pdf_bytes and claim_text_for_loc:
                        from apis.services.ai.processing.highlighting import find_claim_location
                        loc_tasks.append(asyncio.to_thread(find_claim_location, pdf_bytes, claim_text_for_loc))
                    else:
                        fallback = f"Section {v.chunk_index}" if v.chunk_index != -1 else "Document Level"
                        loc_tasks.append(_fallback_location(fallback))

                loc_results = await asyncio.gather(*loc_tasks, return_exceptions=True)

                # Save violations as findings
                for idx, v in enumerate(pipeline_result.violations):
                    finding_id = str(uuid.uuid4())
                    rule_id = None

                    rule_code_to_find = f"RULE-{v.rule}"
                    if rule_code_to_find in rule_map:
                        rule_id = rule_map[rule_code_to_find]
                    else:
                        for rc, rid in rule_map.items():
                            if rc.upper().endswith(f"-{v.rule}") or rc.upper() == f"RULE-{v.rule}":
                                rule_id = rid
                                break
                        if not rule_id and rule_map:
                            logger.warning(
                                "No rule_id found for violation rule=%s rule_name=%s, using first rule as fallback",
                                v.rule, v.rule_name,
                            )
                            rule_id = list(rule_map.values())[0]

                    if rule_id:
                        why_risky = getattr(v, "would_break_compliance", "").strip()
                        if not why_risky and v.reasoning:
                            why_risky = v.reasoning.strip()

                        rationale = getattr(v, "what_was_checked", "").strip()
                        if not rationale:
                            rationale = (
                                f"NI 31-103 Rule {v.rule} ({v.rule_name}) prohibits {v.rule_name.lower()}. "
                                f"The evaluation checked whether the claim complies with this requirement."
                            )

                        logger.info(
                            "DB_MAPPING doc_id=%s finding_idx=%s rule=%s why_risky_from_ai=%s rationale_from_ai=%s suggestion_from_ai=%s",
                            doc_id, idx, v.rule,
                            bool(getattr(v, "would_break_compliance", "")),
                            bool(getattr(v, "what_was_checked", "")),
                            bool(getattr(v, "suggested_alternative", ""))
                        )
                        logger.debug(
                            "DB_MAPPING_FULL doc_id=%s finding_idx=%s mapping=%s",
                            doc_id, idx,
                            {
                                "ai_would_break_compliance": getattr(v, "would_break_compliance", ""),
                                "db_why_risky": why_risky[:100] if why_risky else "",
                                "ai_what_was_checked": getattr(v, "what_was_checked", ""),
                                "db_rationale": rationale[:100] if rationale else "",
                                "ai_suggested_alternative": getattr(v, "suggested_alternative", ""),
                                "db_ai_suggestion": (v.suggested_alternative or "No alternative provided.")[:100],
                            }
                        )

                        loc_result = loc_results[idx]
                        if isinstance(loc_result, Exception):
                            logger.warning("LOCATION_LOOKUP_FAIL idx=%s err=%s", idx, loc_result)
                            location_str = f"Section {v.chunk_index}" if v.chunk_index != -1 else "Document Level"
                        else:
                            location_str = loc_result

                        if location_str == "Document Level" and v.chunk_index != -1:
                            location_str = f"Section {v.chunk_index}"

                        await db.execute(
                            """
                            INSERT INTO ai_findings (id, finding_code, review_id, rule_id, title, risk_level, description, why_risky, rationale, ai_suggestion, location, status, claim_id, claim_text, created_at)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'pending', $12, $13, $14)
                            """,
                            finding_id,
                            f"FIND-{idx + 1:03d}-{finding_id[:8].upper()}",
                            review_id,
                            rule_id,
                            f"Violation of Rule {v.rule}: {v.rule_name}",
                            v.severity.upper(),
                            v.reasoning[:200] + "..." if len(v.reasoning) > 200 else v.reasoning,
                            why_risky,
                            rationale,
                            v.suggested_alternative or "No alternative provided.",
                            location_str,
                            getattr(v, "claim_id", "") or "",
                            getattr(v, "claim_text", "") or "",
                            now_utc
                        )

                        page_no, line_no = _parse_location_page_line(location_str)
                        claim_hash = _hash_claim_text(getattr(v, "claim_text", "") or "")
                        await db.execute(
                            """
                            INSERT INTO ai_finding_anchors (
                                id, finding_id, document_version_id, page_no_start, page_no_end, line_no,
                                bbox_json, match_method, match_confidence, normalized_claim_hash, created_at, updated_at
                            )
                            VALUES ($1, $2, $3, $4, $4, $5, $6::jsonb, $7, $8, $9, $10, $10)
                            ON CONFLICT (finding_id)
                            DO UPDATE SET
                                document_version_id = EXCLUDED.document_version_id,
                                page_no_start = EXCLUDED.page_no_start,
                                page_no_end = EXCLUDED.page_no_end,
                                line_no = EXCLUDED.line_no,
                                bbox_json = EXCLUDED.bbox_json,
                                match_method = EXCLUDED.match_method,
                                match_confidence = EXCLUDED.match_confidence,
                                normalized_claim_hash = EXCLUDED.normalized_claim_hash,
                                updated_at = EXCLUDED.updated_at
                            """,
                            str(uuid.uuid4()),
                            finding_id,
                            version_id,
                            page_no,
                            line_no,
                            json.dumps([]),
                            "location_text",
                            1.0 if page_no is not None else 0.0,
                            claim_hash,
                            now_utc,
                        )
                        findings_saved += 1

            logger.info(
                "analyze_document completed doc_id=%s review_id=%s findings_saved=%s",
                doc_id, review_id, findings_saved,
            )

            # Pre-build the annotated PDF artifact before publishing completion so
            # the frontend can show findings and the highlighted preview together.
            # Uses its own pooled connection to avoid contention with this one.
            annotate_task = None
            if pdf_bytes and pipeline_result and pipeline_result.violations and key:
                annotate_task = asyncio.create_task(
                    _prebuild_annotated_pdf(doc_id, version_id, review_id, bucket, key, pdf_bytes)
                )

            completion_event_type = "ai_analysis_completed"
            completion_description = f"AI compliance analysis completed - {findings_saved} findings identified"
            completion_phase = "completed"
            completion_rules_checked = rules_checked

            if skip_analysis:
                completion_event_type = "ai_analysis_skipped"
                completion_description = "AI compliance analysis skipped - document classified as out of scope"
                completion_phase = "skipped"
                completion_rules_checked = 0

            if annotate_task:
                try:
                    await annotate_task
                except Exception as ann_err:
                    logger.warning("PREBUILD_ANNOTATED_PDF_FAIL doc_id=%s err=%s", doc_id, ann_err)

            await log_audit_event(
                db,
                review_id=review_id,
                event_type=completion_event_type,
                description=completion_description,
                is_ai=True,
                details=json.dumps(
                    {
                        "phase": completion_phase,
                        "rules_checked": completion_rules_checked,
                        "rules_total": enabled_rules_total,
                        "violations_count": violations_count,
                        "findings_saved": findings_saved,
                        "skip_analysis": skip_analysis,
                        "classifier_detected_type": classification.get("detected_type"),
                    }
                ),
                triggered_by_user_id=user_id_to_log,
            )
            _publish_phase(doc_id, completion_phase, completion_rules_checked, enabled_rules_total)

    return {"ok": True, "review_id": review_id, "violations_count": violations_count}


@router.post("/{doc_id}/analyze")
async def analyze_document(
    doc_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    """Queue AI compliance analysis (same as post–SME-approve). Runs in background to avoid HTTP timeouts."""
    roles = set((current_user or {}).get("roles") or [])
    roles_lower = {str(r).lower().strip() for r in roles}
    if not roles_lower.intersection({"marketing", "compliance"}):
        raise HTTPException(
            status_code=403,
            detail="Only marketing or compliance can run AI analysis.",
        )
    await _require_document_in_org_for_user(db, doc_id, current_user, tenant_ctx)
    decision = await _queue_ai_analysis_if_needed(
        db=db,
        background_tasks=background_tasks,
        doc_id=doc_id,
        current_user=current_user,
        trigger_source="manual_analyze_endpoint",
        organization_id=tenant_ctx["organization_id"],
    )
    return {"ok": True, "queued": decision["queued"], "reason": decision["reason"]}


@router.get("/{doc_id}/review")
async def get_document_review(
    doc_id: str,
    version_id: Optional[str] = Query(default=None, description="Specific document version ID. Defaults to current version."),
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    user_id = str(current_user.get("id"))
    roles = set(current_user.get("roles") or [])
    is_admin = _tenant_org_super_admin(tenant_ctx)

    doc_row = await db.fetchrow(
        "SELECT current_version_id, submitted_by FROM documents WHERE id=$1 AND organization_id=$2",
        doc_id,
        tenant_ctx["organization_id"],
    )
    if not doc_row or not doc_row["current_version_id"]:
        raise HTTPException(status_code=404, detail="Document version not found")

    # Use the requested version_id if provided and valid, else fall back to current version
    if version_id:
        # Validate the version belongs to this document
        valid_version = await db.fetchval(
            "SELECT id FROM document_versions WHERE id=$1 AND document_id=$2",
            version_id, doc_id
        )
        if not valid_version:
            raise HTTPException(status_code=404, detail="Version not found for this document")
        resolved_version_id = version_id
    else:
        resolved_version_id = doc_row["current_version_id"]

    submitted_by = doc_row["submitted_by"]
    
    review_row = await db.fetchrow(
        "SELECT * FROM content_reviews WHERE document_version_id=$1 ORDER BY created_at DESC LIMIT 1", 
        resolved_version_id
    )
    if not review_row:
        raise HTTPException(status_code=404, detail="Review not found for this document")

    version_row = await db.fetchrow(
        "SELECT status FROM document_versions WHERE id=$1",
        resolved_version_id
    )
    version_status = version_row["status"] if version_row else None

    # Access check for non-admins
    if not is_admin:
        w_row_chk = await db.fetchrow("SELECT id, assigned_to, assigned_role FROM workflows WHERE review_id=$1", review_row["id"])
        if w_row_chk:
            assigned_to = str(w_row_chk["assigned_to"]) if w_row_chk["assigned_to"] else None
            assigned_role = w_row_chk["assigned_role"]
            workflow_id = w_row_chk["id"]
            
            can_access = (
                user_id == str(submitted_by) or
                user_id == assigned_to or
                (assigned_to is None and assigned_role in roles)
            )
            
            if not can_access and workflow_id:
                # Check historical participation
                past_participant = await db.fetchval(
                    "SELECT 1 FROM workflow_steps WHERE workflow_id=$1 AND (claimed_by=$2 OR completed_by=$2) LIMIT 1",
                    workflow_id, user_id
                )
                if past_participant:
                    can_access = True

            if not can_access:
                was_mentioned = await db.fetchval(
                    """
                    SELECT 1
                    FROM comment_mentions cm
                    JOIN content_comments cc ON cc.id = cm.comment_id
                    WHERE cc.review_id = $1
                      AND cm.mentioned_user_id = $2::uuid
                    LIMIT 1
                    """,
                    review_row["id"], user_id
                )
                if was_mentioned:
                    can_access = True
                    
            if not can_access:
                raise HTTPException(status_code=403, detail="You do not have access to this document review")
        
    result = dict(review_row)
    
    w_row = await db.fetchrow("SELECT * FROM workflows WHERE review_id=$1", review_row["id"])
    if w_row:
        result["workflow"] = dict(w_row)

    # AI analysis state/phase (used by frontend to show staged progress vs failed/no findings)
    try:
        ai_state_rows = await db.fetch(
            """
            SELECT event_type, details, created_at
            FROM audit_events
            WHERE review_id=$1
              AND is_ai=true
              AND event_type IN (
                'ai_analysis_started',
                'ai_analysis_completed',
                'ai_analysis_skipped',
                'ai_analysis_failed',
                'ai_phase_analysing_document',
                'ai_phase_parsing_document',
                'ai_phase_classifying_document',
                'ai_phase_performing_analysis',
                'ai_phase_consolidating_result',
                'ai_classification_completed'
              )
            ORDER BY created_at ASC
            """,
            review_row["id"],
        )
        last_by_type = {}
        latest_phase = "not_started"
        latest_rules_checked = 0
        latest_rules_total = 1
        _phase_from_audit_event = {
            "ai_phase_parsing_document": "parsing_document",
            "ai_phase_classifying_document": "classifying_document",
            "ai_phase_analysing_document": "analysing_document",
            "ai_phase_performing_analysis": "performing_ai_analysis",
            "ai_phase_consolidating_result": "consolidating_result",
            "ai_classification_completed": "classification_done",
        }
        for r in ai_state_rows:
            event_type = str(r["event_type"])
            last_by_type[event_type] = r["created_at"]

            details_raw = r.get("details")
            details_json = {}
            if isinstance(details_raw, str):
                try:
                    details_json = json.loads(details_raw)
                except Exception:
                    details_json = {}

            if event_type in _phase_from_audit_event:
                latest_phase = _phase_from_audit_event[event_type]
            elif event_type == "ai_analysis_started":
                latest_phase = "parsing_document"
            elif event_type == "ai_analysis_completed":
                latest_phase = "completed"
            elif event_type == "ai_analysis_skipped":
                latest_phase = "skipped"
            elif event_type == "ai_analysis_failed":
                latest_phase = "failed"

            if isinstance(details_json, dict):
                latest_rules_checked = int(details_json.get("rules_checked") or latest_rules_checked or 0)
                latest_rules_total = max(1, int(details_json.get("rules_total") or latest_rules_total or 1))

        last_started = last_by_type.get("ai_analysis_started")
        last_completed = last_by_type.get("ai_analysis_completed")
        last_skipped = last_by_type.get("ai_analysis_skipped")
        last_failed = last_by_type.get("ai_analysis_failed")
        last_classification = last_by_type.get("ai_classification_completed")

        # Latest event among the three wins (supports: fail → retry → complete)
        candidates = []
        if last_started:
            candidates.append((last_started, "ai_analysis_started"))
        if last_completed:
            candidates.append((last_completed, "ai_analysis_completed"))
        if last_skipped:
            candidates.append((last_skipped, "ai_analysis_skipped"))
        if last_failed:
            candidates.append((last_failed, "ai_analysis_failed"))

        if not candidates:
            if version_status == "processing":
                result["ai_analysis_state"] = "processing"
                if last_classification:
                    latest_phase = "classification_done"
                elif latest_phase not in ("parsing_document", "classifying_document"):
                    latest_phase = "parsing_document"
            else:
                result["ai_analysis_state"] = "not_started"
        else:
            _latest_ts, latest_type = max(candidates, key=lambda x: x[0])
            if latest_type == "ai_analysis_started":
                result["ai_analysis_state"] = "processing"
            elif latest_type in ("ai_analysis_completed", "ai_analysis_skipped"):
                result["ai_analysis_state"] = "completed"
            else:
                result["ai_analysis_state"] = "failed"

        # When overall state is terminal, force phase to match so the
        # frontend never shows a stale intermediate phase (e.g. stuck
        # on "consolidating_result" while state is already "completed").
        resolved_state = result.get("ai_analysis_state")
        if resolved_state == "completed":
            latest_phase = "completed"
        elif resolved_state == "failed":
            latest_phase = "failed"

        result["ai_analysis_phase"] = latest_phase
        result["ai_rules_checked"] = latest_rules_checked
        result["ai_rules_total"] = latest_rules_total

        # [Branch 1] Expose exact timestamps so the frontend can compute accurate progress
        result["ai_started_at"] = last_started.isoformat() if last_started else None
        result["ai_completed_at"] = last_completed.isoformat() if last_completed else None
        result["ai_skipped_at"] = last_skipped.isoformat() if last_skipped else None
        result["ai_failed_at"] = last_failed.isoformat() if last_failed else None
    except Exception:
        result["ai_analysis_state"] = "unknown"
        result["ai_analysis_phase"] = "not_started"
        result["ai_rules_checked"] = 0
        result["ai_rules_total"] = 1
        result["ai_started_at"] = None   # [Branch 1]
        result["ai_completed_at"] = None  # [Branch 1]
        result["ai_skipped_at"] = None
        result["ai_failed_at"] = None

    # [Branch 1] Role check uses BOTH DB roles and JWT roles (union) for accuracy.
    # Pure-SME users (sme but no higher role) are blocked from seeing AI findings.
    db_role_rows = await db.fetch(
        """
        SELECT r.name FROM user_roles ur
        JOIN roles r ON ur.role_id = r.id
        WHERE ur.user_id = $1
        """,
        (current_user or {}).get("id"),
    )
    db_roles = set(r["name"] for r in db_role_rows)
    jwt_roles = set((current_user or {}).get("roles") or [])
    roles = db_roles | jwt_roles  # Union of both sources

    is_sme_only = "sme" in roles and not (
        roles & {"marketing", "compliance", "super_admin"}
    )

    if not is_sme_only:
        findings = await db.fetch(
            """
            SELECT 
                af.*,
                COALESCE(afa.normalized_claim_hash, '') AS canonical_claim_hash,
                cr.rule_code,
                cr.name as rule_name
            FROM ai_findings af
            LEFT JOIN ai_finding_anchors afa ON afa.finding_id = af.id
            LEFT JOIN compliance_rules cr ON af.rule_id = cr.id
            WHERE af.review_id=$1 
            ORDER BY af.created_at ASC, af.finding_code ASC
            """,
            review_row["id"]
        )
        result["ai_findings"] = [dict(f) for f in findings]
        # [Branch 1] Debug logging with full role context
        logger.info(
            "get_document_review doc_id=%s review_id=%s db_roles=%s jwt_roles=%s findings_count=%s ai_state=%s",
            doc_id, review_row["id"],
            list(db_roles), list(jwt_roles),
            len(findings), result.get("ai_analysis_state"),
        )
    else:
        result["ai_findings"] = []

    return result


@router.get("/{doc_id}/annotated_file")
async def get_annotated_document_file(
    doc_id: str,
    version_id: str | None = None,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    """
    Return a presigned URL for the annotated PDF (cache-first).
    Falls back to the raw file URL if annotation is unavailable or non-PDF.
    """
    roles = set(current_user.get("roles") or [])
    if not roles.intersection({"marketing", "compliance"}):
        raise HTTPException(
            status_code=403, 
            detail="Only marketing and compliance can download compliance certificates."
        )

    await _require_document_in_org_for_user(db, doc_id, current_user, tenant_ctx)

    # Fetch S3 key from specific document version or current
    if version_id:
        row = await db.fetchrow(
            """
            SELECT dv.id as version_id, dv.s3_bucket, dv.s3_key
            FROM document_versions dv
            JOIN documents d ON d.id = dv.document_id
            WHERE dv.document_id=$1 AND dv.id=$2 AND d.organization_id=$3
            """,
            doc_id,
            version_id,
            tenant_ctx["organization_id"],
        )
    else:
        row = await db.fetchrow(
            """
            SELECT dv.id as version_id, dv.s3_bucket, dv.s3_key FROM documents d
            LEFT JOIN document_versions dv ON d.current_version_id = dv.id
            WHERE d.id=$1 AND d.organization_id=$2
            """,
            doc_id,
            tenant_ctx["organization_id"],
        )
    if not row or not row.get("s3_key"):
        raise HTTPException(status_code=404, detail="Document version file not found")

    bucket = row.get("s3_bucket") or ai_config.AWS_S3_BUCKET
    key = row["s3_key"]
    version_id = str(row["version_id"]) if row.get("version_id") else None

    # Only annotate PDFs — for other types stream raw
    source_ext = _extension_from_filename(key)
    is_office = source_ext in _OFFICE_PREVIEW_EXTENSIONS
    is_pdf = source_ext == ".pdf" or is_office

    # Fetch violation claim_texts for this specific version
    if version_id:
        review_row = await db.fetchrow(
            """
            SELECT cr.id
            FROM content_reviews cr
            JOIN document_versions dv ON cr.document_version_id = dv.id
            JOIN documents d ON d.id = dv.document_id
            WHERE dv.id = $1 AND d.organization_id = $2
            ORDER BY cr.created_at DESC LIMIT 1
            """,
            version_id,
            tenant_ctx["organization_id"],
        )
    else:
        review_row = await db.fetchrow(
            """
            SELECT cr.id
            FROM content_reviews cr
            JOIN document_versions dv ON cr.document_version_id = dv.id
            JOIN documents d ON d.current_version_id = dv.id
            WHERE d.id = $1 AND d.organization_id = $2
            ORDER BY cr.created_at DESC LIMIT 1
            """,
            doc_id,
            tenant_ctx["organization_id"],
        )

    highlights: list[tuple[str, tuple, int | None]] = []
    unique_claims: list[dict] = []
    findings_hash: str | None = None
    if review_row and is_pdf:
        findings_rows = await db.fetch(
            "SELECT af.claim_text, af.location, COALESCE(afa.normalized_claim_hash, '') AS canonical_claim_hash "
            "FROM ai_findings af "
            "LEFT JOIN ai_finding_anchors afa ON afa.finding_id = af.id "
            "WHERE af.review_id=$1 AND af.claim_text IS NOT NULL AND af.claim_text != '' "
            "ORDER BY af.created_at ASC, af.finding_code ASC",
            review_row["id"],
        )
        
        # Deduplicate claims to exactly match the grouping behavior in the frontend UI (`documentdetail.tsx`), 
        # ensuring the index-based color mapping is perfectly synchronized.
        seen = set()
        for f in findings_rows:
            claim = (f["claim_text"] or "").strip()
            if not claim:
                continue
            canonical_key = str(f.get("canonical_claim_hash") or "").strip().lower()
            dedupe_key = canonical_key or _hash_claim_text(claim)
            if dedupe_key and dedupe_key not in seen:
                seen.add(dedupe_key)
                unique_claims.append(
                    {
                        "claim": claim,
                        "location": f["location"],
                        "canonical_key": dedupe_key,
                    }
                )

        findings_hash = _build_findings_hash(unique_claims) if unique_claims else None
        for idx, item in enumerate(unique_claims):
            color = _HIGHLIGHT_PALETTE[idx % len(_HIGHLIGHT_PALETTE)]
            
            # Parse page number from "Page X, Line Y" if available to supercharge highlighting speed
            target_page = None
            if item["location"]:
                match = re.search(r"Page\s+(\d+)", item["location"])
                if match:
                    target_page = int(match.group(1)) - 1  # PyMuPDF is 0-indexed

            highlights.append((item["claim"], color, target_page))

    if is_pdf and findings_hash and version_id:
        cached_row = await db.fetchrow(
            """
            SELECT s3_bucket, s3_key
            FROM ai_annotated_artifacts
            WHERE document_version_id=$1 AND findings_hash=$2 AND engine_version=$3
            LIMIT 1
            """,
            version_id,
            findings_hash,
            _ANNOTATION_ENGINE_VERSION,
        )
        if cached_row:
            cache_bucket = cached_row["s3_bucket"]
            cache_key = cached_row["s3_key"]
            try:
                s3_helper.s3_client.head_object(Bucket=cache_bucket, Key=cache_key)
                await db.execute(
                    "UPDATE ai_annotated_artifacts SET last_accessed_at=$1 WHERE document_version_id=$2 AND findings_hash=$3 AND engine_version=$4",
                    datetime.now(timezone.utc).replace(tzinfo=None),
                    version_id,
                    findings_hash,
                    _ANNOTATION_ENGINE_VERSION,
                )
                return {
                    "url": _presigned_url_for_key(cache_bucket, cache_key),
                    "file_name": Path(cache_key).name,
                    "mime": "application/pdf",
                }
            except ClientError as cache_err:
                log_s3_error(
                    error=cache_err,
                    operation="verify_cached_annotation",
                    resource=cache_key,
                    context={"bucket": cache_bucket}
                )
            except Exception as cache_err:
                log_error(
                    error=cache_err,
                    category=ErrorCategory.FILE_UPLOAD,
                    operation="retrieve_cached_annotation",
                    severity=ErrorSeverity.WARNING,
                    context={"doc_id": doc_id, "version_id": version_id}
                )

    # Download raw PDF bytes
    def _download() -> bytes:
        resp = s3_helper.s3_client.get_object(Bucket=bucket, Key=key)
        raw_b = resp["Body"].read()
        if is_office:
            preview_hash = _office_preview_hash(key, source_ext)
            preview_key = _office_preview_cache_key(doc_id, version_id, preview_hash)
            try:
                preview_resp = s3_helper.s3_client.get_object(Bucket=bucket, Key=preview_key)
                return preview_resp["Body"].read()
            except ClientError:
                pdf_bytes, _ = _convert_office_to_pdf_bytes(raw_b, Path(key).name)
                return pdf_bytes
        return raw_b

    try:
        raw_bytes = await asyncio.to_thread(_download)
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        log_s3_error(
            error=e,
            operation="get_object",
            resource=key,
            context={"bucket": bucket, "error_code": error_code}
        )
        raise HTTPException(status_code=500, detail="Unable to fetch document. Please try again later.")
    except Exception as e:
        log_error(
            error=e,
            category=ErrorCategory.FILE_UPLOAD,
            operation="download_document",
            severity=ErrorSeverity.ERROR,
            context={"key": key, "bucket": bucket}
        )
        raise HTTPException(status_code=500, detail="Unable to fetch document. Please try again later.")

    # If we have highlights and it's a PDF, annotate it in-memory
    if highlights and is_pdf:
        try:
            from apis.services.ai.processing.highlighting import highlight_pdf_bytes
            annotated = await asyncio.to_thread(highlight_pdf_bytes, raw_bytes, highlights)
        except Exception as e:
            logger.warning("HIGHLIGHT_FAIL doc_id=%s err=%s — falling back to raw", doc_id, str(e))
            annotated = raw_bytes
    else:
        annotated = raw_bytes

    cache_bucket = bucket
    cache_key = key
    cache_ready = False
    if is_pdf and highlights and findings_hash and version_id:
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        cache_key = _annotation_cache_key(doc_id, version_id, findings_hash, key)
        try:
            s3_helper.s3_client.put_object(
                Bucket=cache_bucket,
                Key=cache_key,
                Body=annotated,
                ContentType="application/pdf",
            )
            cache_ready = True
            await db.execute(
                """
                INSERT INTO ai_annotated_artifacts (
                    id, document_id, document_version_id, review_id, findings_hash, s3_bucket, s3_key,
                    engine_version, generated_at, last_accessed_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $9)
                ON CONFLICT (document_version_id, findings_hash, engine_version)
                DO UPDATE SET
                    s3_bucket = EXCLUDED.s3_bucket,
                    s3_key = EXCLUDED.s3_key,
                    generated_at = EXCLUDED.generated_at,
                    last_accessed_at = EXCLUDED.last_accessed_at
                """,
                str(uuid.uuid4()),
                doc_id,
                version_id,
                str(review_row["id"]) if review_row else None,
                findings_hash,
                cache_bucket,
                cache_key,
                _ANNOTATION_ENGINE_VERSION,
                now_utc,
            )
        except ClientError as cache_write_err:
            logger.warning(
                "ANNOTATION_CACHE_WRITE_FAIL doc_id=%s version_id=%s err=%s",
                doc_id,
                version_id,
                str(cache_write_err),
            )
    else:
        source_ext = _extension_from_filename(Path(key).name)
        if source_ext in _OFFICE_PREVIEW_EXTENSIONS and version_id:
            return await _build_office_pdf_preview_response(
                db=db,
                doc_id=doc_id,
                version_id=version_id,
                bucket=bucket,
                source_key=key,
            )
        # Non-PDF or no highlights: return raw file URL to keep frontend simple.
        raw_url = _presigned_url_for_key(bucket, key)
        raw_name = Path(key).name
        raw_mime = _mime_from_extension(Path(key).suffix)
        return {
            "url": raw_url,
            "file_name": raw_name,
            "mime": raw_mime,
            "original_url": raw_url,
            "original_file_name": raw_name,
            "original_mime": raw_mime,
            "preview_fallback": False,
        }

    return {
        "url": _presigned_url_for_key(cache_bucket if cache_ready else bucket, cache_key if cache_ready else key),
        "file_name": Path(cache_key if cache_ready else key).name,
        "mime": "application/pdf",
        "original_url": _presigned_url_for_key(bucket, key),
        "original_file_name": Path(key).name,
        "original_mime": _mime_from_extension(Path(key).suffix),
        "preview_fallback": False,
    }


@router.get("/{doc_id}/file")
async def get_document_file(
    doc_id: str,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    """Return a presigned URL for the current document version's file (if available)."""
    await _require_document_in_org_for_user(db, doc_id, current_user, tenant_ctx)
    row = await db.fetchrow(
        """
        SELECT dv.id as version_id, dv.s3_bucket, dv.s3_key, dv.uploaded_at, dv.status, dv.version_label
        FROM documents d
        LEFT JOIN document_versions dv ON d.current_version_id = dv.id
        WHERE d.id=$1 AND d.organization_id=$2
        """,
        doc_id,
        tenant_ctx["organization_id"],
    )
    if not row or not row.get("s3_key"):
        raise HTTPException(status_code=404, detail="Document file not found")

    bucket = row.get("s3_bucket") or ai_config.AWS_S3_BUCKET
    key = row.get("s3_key")

    file_name = key.split("/")[-1]
    ext = file_name.split(".")[-1].lower() if "." in file_name else ""
    version_id = str(row["version_id"]) if row.get("version_id") else None
    if f".{ext}" in _OFFICE_PREVIEW_EXTENSIONS and version_id:
        return await _build_office_pdf_preview_response(
            db=db,
            doc_id=doc_id,
            version_id=version_id,
            bucket=bucket,
            source_key=key,
        )
    url = _presigned_url_for_key(bucket, key)
    mime = "application/octet-stream"
    if ext in ("pdf", "doc", "docx", "ppt", "pptx"):
        mime = _mime_from_extension(ext)
    elif ext in ("png", "jpg", "jpeg", "webp"):
        mime = f"image/{'jpeg' if ext == 'jpg' else ext}"
    elif ext in ("mp4", "webm"):
        mime = f"video/{ext}"

    return {
        "url": url,
        "file_name": file_name,
        "mime": mime,
        "original_url": url,
        "original_file_name": file_name,
        "original_mime": mime,
        "preview_fallback": False,
    }


@router.post("/{doc_id}/assign")
async def assign_document(
    doc_id: str,
    assignee_id: Optional[str] = None,
    assigned_role: Optional[str] = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    roles = set((current_user or {}).get("roles") or [])
    if "marketing" not in roles:
        raise HTTPException(status_code=403, detail="Only marketing can assign reviewers")

    doc_row = await db.fetchrow(
        """
        SELECT d.current_version_id, dv.status as version_status
        FROM documents d
        LEFT JOIN document_versions dv ON dv.id = d.current_version_id
        WHERE d.id=$1 AND d.organization_id=$2
        """,
        doc_id,
        tenant_ctx["organization_id"],
    )
    if not doc_row or not doc_row["current_version_id"]:
        raise HTTPException(status_code=404, detail="Document/version not found")

    if str(doc_row.get("version_status") or "").lower() == "skipped":
        raise HTTPException(
            status_code=409,
            detail="Document is classified as non-educational (out of scope) and cannot be sent to compliance",
        )

    version_id = doc_row["current_version_id"]
    review_row = await db.fetchrow("SELECT * FROM content_reviews WHERE document_version_id=$1 ORDER BY created_at DESC LIMIT 1", version_id)
    if not review_row:
        raise HTTPException(status_code=404, detail="Review not found for this document")

    w_row = await db.fetchrow("SELECT * FROM workflows WHERE review_id=$1", review_row["id"])
    if not w_row:
        raise HTTPException(status_code=404, detail="Workflow not found")

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.execute("UPDATE workflows SET assigned_to=$1, assigned_role=$2, updated_at=$3 WHERE id=$4", assignee_id, assigned_role or w_row.get("assigned_role"), now_utc, w_row["id"])

    step_order = await _next_step_order(db, w_row["id"])
    user_id = (current_user or {}).get("id")
    await db.execute(
        "INSERT INTO workflow_steps (id, workflow_id, stage, action, comment, previous_stage, step_order, completed_by, completed_at, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$9)",
        str(uuid.uuid4()), w_row["id"], w_row.get("current_stage"), "assigned", None, w_row.get("current_stage"), step_order, user_id, now_utc
    )

    await _notify_workflow_transition(
        db=db,
        background_tasks=background_tasks,
        doc_id=doc_id,
        review_id=str(review_row["id"]),
        from_stage=str(w_row.get("current_stage") or ""),
        to_stage=str(w_row.get("current_stage") or ""),
        assigned_role=assigned_role or w_row.get("assigned_role"),
        assigned_to=assignee_id,
        organization_id=tenant_ctx["organization_id"],
        org_slug=tenant_ctx.get("organization_slug"),
    )

    await _publish_workflow_event(str(review_row["id"]), doc_id, "assign", str(w_row.get("current_stage") or ""), str(w_row.get("current_stage") or ""))

    return {"ok": True}


@router.post("/{doc_id}/claim")
async def claim_document(
    doc_id: str,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    roles = set((current_user or {}).get("roles") or [])

    user_id = (current_user or {}).get("id")
    doc_row = await db.fetchrow(
        "SELECT current_version_id FROM documents WHERE id=$1 AND organization_id=$2",
        doc_id,
        tenant_ctx["organization_id"],
    )
    if not doc_row or not doc_row["current_version_id"]:
        raise HTTPException(status_code=404, detail="Document/version not found")

    await _require_document_in_org_for_user(db, doc_id, current_user, tenant_ctx)

    version_id = doc_row["current_version_id"]
    review_row = await db.fetchrow("SELECT * FROM content_reviews WHERE document_version_id=$1 ORDER BY created_at DESC LIMIT 1", version_id)
    if not review_row:
        raise HTTPException(status_code=404, detail="Review not found for this document")

    w_row = await db.fetchrow("SELECT * FROM workflows WHERE review_id=$1", review_row["id"])
    if not w_row:
        raise HTTPException(status_code=404, detail="Workflow not found")

    stage = str(w_row.get("current_stage") or "")
    if stage == "sme_review":
        if "sme" not in roles:
            raise HTTPException(status_code=403, detail="Only SME can claim documents in SME stage")
    elif stage == "compliance_review":
        if "compliance" not in roles:
            raise HTTPException(status_code=403, detail="Only compliance can claim documents in compliance stage")
    else:
        raise HTTPException(status_code=409, detail=f"Claim is not allowed in stage '{stage}'")

    # Only allow claim if currently unassigned
    if w_row.get("assigned_to"):
        raise HTTPException(status_code=409, detail="Document already assigned")

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.execute("UPDATE workflows SET assigned_to=$1, updated_at=$2 WHERE id=$3", user_id, now_utc, w_row["id"])
    step_order = await _next_step_order(db, w_row["id"])
    await db.execute(
        "INSERT INTO workflow_steps (id, workflow_id, stage, action, comment, previous_stage, step_order, claimed_by, claimed_at, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$9)",
        str(uuid.uuid4()), w_row["id"], w_row.get("current_stage"), "claimed", None, w_row.get("current_stage"), step_order, user_id, now_utc
    )

    await _publish_workflow_event(str(review_row["id"]), doc_id, "claim", str(w_row.get("current_stage") or ""), str(w_row.get("current_stage") or ""))

    return {"ok": True}


async def _analyze_document_bg(doc_id: str, triggered_by_user_id: Optional[str] = None):
    try:
        await _analyze_document_pipeline(doc_id, triggered_by_user_id)
    except Exception as e:
        logger.error("Background AI analysis failed doc_id=%s: %s", doc_id, e, exc_info=True)
        try:
            from apis.core.database import db_pool as _pool

            if _pool:
                async with _pool.acquire() as db:
                    row = await db.fetchrow(
                        """
                        SELECT cr.id AS review_id
                        FROM content_reviews cr
                        JOIN document_versions dv ON cr.document_version_id = dv.id
                        JOIN documents d ON d.current_version_id = dv.id
                        WHERE d.id = $1
                        ORDER BY cr.created_at DESC
                        LIMIT 1
                        """,
                        doc_id,
                    )
                    if row:
                        await log_audit_event(
                            db,
                            review_id=str(row["review_id"]),
                            event_type="ai_analysis_failed",
                            description="AI compliance analysis failed",
                            is_ai=True,
                            details=str(e)[:2000],
                            triggered_by_user_id=triggered_by_user_id,
                        )
            _publish_phase(doc_id, "failed", 0, 1)
        except Exception as log_err:
            logger.error("Could not log ai_analysis_failed: %s", log_err)
            _publish_phase(doc_id, "failed", 0, 1)

@router.post("/{doc_id}/sme-approve")
async def sme_approve_document(
    doc_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    roles = set((current_user or {}).get("roles") or [])
    if "sme" not in roles:
        raise HTTPException(status_code=403, detail="Only SME can approve at this stage")

    user_id = (current_user or {}).get("id")
    # [Branch 1] Also fetches submitted_by to re-assign to original uploader after SME approval
    doc_row = await db.fetchrow(
        "SELECT current_version_id, submitted_by FROM documents WHERE id=$1 AND organization_id=$2",
        doc_id,
        tenant_ctx["organization_id"],
    )
    if not doc_row or not doc_row["current_version_id"]:
        raise HTTPException(status_code=404, detail="Document/version not found")

    version_id = doc_row["current_version_id"]
    submitted_by = doc_row["submitted_by"]
    review_row = await db.fetchrow("SELECT * FROM content_reviews WHERE document_version_id=$1 ORDER BY created_at DESC LIMIT 1", version_id)
    if not review_row:
        raise HTTPException(status_code=404, detail="Review not found for this document")

    w_row = await db.fetchrow("SELECT * FROM workflows WHERE review_id=$1", review_row["id"])
    if not w_row:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if str(w_row.get("current_stage") or "") != "sme_review":
        raise HTTPException(status_code=409, detail="Document is not in SME review stage")

    if w_row.get("assigned_to") and str(w_row.get("assigned_to")) != str(user_id):
        raise HTTPException(status_code=403, detail="You are not the assigned SME for this document")

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    # [Branch 1] Re-assigns to submitted_by (original uploader) when moving to marketing_review
    await db.execute(
        "UPDATE workflows SET current_stage='marketing_review', assigned_to=$1, assigned_role='marketing', updated_at=$2 WHERE id=$3",
        submitted_by, now_utc, w_row["id"]
    )
    step_order = await _next_step_order(db, w_row["id"])
    await db.execute(
        "INSERT INTO workflow_steps (id, workflow_id, stage, action, comment, previous_stage, step_order, completed_by, completed_at, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$9)",
        str(uuid.uuid4()), w_row["id"], 'marketing_review', 'approve', None, w_row.get("current_stage"), step_order, user_id, now_utc
    )

    await _notify_workflow_transition(
        db=db,
        background_tasks=background_tasks,
        doc_id=doc_id,
        review_id=str(review_row["id"]),
        from_stage="sme_review",
        to_stage="marketing_review",
        assigned_role="marketing",
        assigned_to=str(submitted_by) if submitted_by else None,
        organization_id=tenant_ctx["organization_id"],
        org_slug=tenant_ctx.get("organization_slug"),
        workflow_action="approve",
        actor_user_id=str(user_id),
    )

    # Trigger AI analysis once on SME -> marketing transition.
    await _queue_ai_analysis_if_needed(
        db=db,
        background_tasks=background_tasks,
        doc_id=doc_id,
        current_user=current_user,
        trigger_source="sme_approve_marketing_review",
        organization_id=tenant_ctx["organization_id"],
    )

    await _publish_workflow_event(str(review_row["id"]), doc_id, "approve", "sme_review", "marketing_review")

    return {"ok": True}


@router.post("/{doc_id}/sme-reject")
async def sme_reject_document(
    doc_id: str,
    comment: Optional[str] = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    roles = set((current_user or {}).get("roles") or [])
    if "sme" not in roles:
        raise HTTPException(status_code=403, detail="Only SME can reject at this stage")

    user_id = (current_user or {}).get("id")
    # [Branch 1] Fetches submitted_by to re-assign on rejection
    doc_row = await db.fetchrow(
        "SELECT current_version_id, submitted_by FROM documents WHERE id=$1 AND organization_id=$2",
        doc_id,
        tenant_ctx["organization_id"],
    )
    if not doc_row or not doc_row["current_version_id"]:
        raise HTTPException(status_code=404, detail="Document/version not found")

    version_id = doc_row["current_version_id"]
    submitted_by = doc_row["submitted_by"]
    review_row = await db.fetchrow("SELECT * FROM content_reviews WHERE document_version_id=$1 ORDER BY created_at DESC LIMIT 1", version_id)
    if not review_row:
        raise HTTPException(status_code=404, detail="Review not found for this document")

    w_row = await db.fetchrow("SELECT * FROM workflows WHERE review_id=$1", review_row["id"])
    if not w_row:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if str(w_row.get("current_stage") or "") != "sme_review":
        raise HTTPException(status_code=409, detail="Document is not in SME review stage")

    if w_row.get("assigned_to") and str(w_row.get("assigned_to")) != str(user_id):
        raise HTTPException(status_code=403, detail="You are not the assigned SME for this document")

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    # [Branch 1] Re-assigns to submitted_by on rejection so they know to resubmit
    await db.execute(
        "UPDATE workflows SET current_stage='rejected', assigned_role='marketing', assigned_to=$1, updated_at=$2 WHERE id=$3",
        submitted_by, now_utc, w_row["id"]
    )
    await db.execute("UPDATE content_reviews SET review_status='rejected', updated_at=$1 WHERE id=$2", now_utc, review_row["id"])
    step_order = await _next_step_order(db, w_row["id"])
    await db.execute(
        "INSERT INTO workflow_steps (id, workflow_id, stage, action, comment, previous_stage, step_order, completed_by, completed_at, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$9)",
        str(uuid.uuid4()), w_row["id"], 'rejected', 'reject', comment, w_row.get("current_stage"), step_order, user_id, now_utc
    )

    await _notify_workflow_transition(
        db=db,
        background_tasks=background_tasks,
        doc_id=doc_id,
        review_id=str(review_row["id"]),
        from_stage="sme_review",
        to_stage="rejected",
        assigned_role="marketing",
        assigned_to=str(submitted_by) if submitted_by else None,
        organization_id=tenant_ctx["organization_id"],
        org_slug=tenant_ctx.get("organization_slug"),
        workflow_action="reject",
        actor_user_id=str(user_id),
        reviewer_note=comment,
    )

    await _publish_workflow_event(str(review_row["id"]), doc_id, "reject", "sme_review", "rejected")

    return {"ok": True}


@router.post("/{doc_id}/sme-request-changes")
async def sme_request_changes(
    doc_id: str,
    comment: Optional[str] = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    roles = set((current_user or {}).get("roles") or [])
    if "sme" not in roles:
        raise HTTPException(status_code=403, detail="Only SME can request changes at this stage")

    user_id = (current_user or {}).get("id")
    # [Branch 1] Fetches submitted_by to re-assign when requesting changes
    doc_row = await db.fetchrow(
        "SELECT current_version_id, submitted_by FROM documents WHERE id=$1 AND organization_id=$2",
        doc_id,
        tenant_ctx["organization_id"],
    )
    if not doc_row or not doc_row["current_version_id"]:
        raise HTTPException(status_code=404, detail="Document/version not found")

    version_id = doc_row["current_version_id"]
    submitted_by = doc_row["submitted_by"]
    review_row = await db.fetchrow("SELECT * FROM content_reviews WHERE document_version_id=$1 ORDER BY created_at DESC LIMIT 1", version_id)
    if not review_row:
        raise HTTPException(status_code=404, detail="Review not found for this document")

    w_row = await db.fetchrow("SELECT * FROM workflows WHERE review_id=$1", review_row["id"])
    if not w_row:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if str(w_row.get("current_stage") or "") != "sme_review":
        raise HTTPException(status_code=409, detail="Document is not in SME review stage")

    assigned_to = w_row.get("assigned_to")
    if not assigned_to:
        raise HTTPException(status_code=409, detail="You must claim this review before taking action")
    if str(assigned_to) != str(user_id):
        raise HTTPException(status_code=403, detail="This review is assigned to another reviewer. You must claim it first.")

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    # [Branch 1] Re-assigns to submitted_by so the uploader sees the changes request
    await db.execute(
        "UPDATE workflows SET current_stage='marketing_review', assigned_role='marketing', assigned_to=$1, updated_at=$2 WHERE id=$3",
        submitted_by, now_utc, w_row["id"]
    )
    step_order = await _next_step_order(db, w_row["id"])
    await db.execute(
        "INSERT INTO workflow_steps (id, workflow_id, stage, action, comment, previous_stage, step_order, completed_by, completed_at, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$9)",
        str(uuid.uuid4()), w_row["id"], 'marketing_review', 'request_changes', comment, w_row.get("current_stage"), step_order, user_id, now_utc
    )

    await _notify_workflow_transition(
        db=db,
        background_tasks=background_tasks,
        doc_id=doc_id,
        review_id=str(review_row["id"]),
        from_stage="sme_review",
        to_stage="marketing_review",
        assigned_role="marketing",
        assigned_to=str(submitted_by) if submitted_by else None,
        organization_id=tenant_ctx["organization_id"],
        org_slug=tenant_ctx.get("organization_slug"),
        workflow_action="request_changes",
        actor_user_id=str(user_id),
        reviewer_note=comment,
    )

    await _publish_workflow_event(str(review_row["id"]), doc_id, "request_changes", "sme_review", "marketing_review")

    return {"ok": True}


@router.post("/{doc_id}/marketing-approve")
async def marketing_approve_document(
    doc_id: str,
    compliance_reviewer_id: Optional[str] = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    roles = set((current_user or {}).get("roles") or [])
    if "marketing" not in roles:
        raise HTTPException(status_code=403, detail="Only marketing can approve at this stage")

    doc_row = await db.fetchrow(
        "SELECT current_version_id FROM documents WHERE id=$1 AND organization_id=$2",
        doc_id,
        tenant_ctx["organization_id"],
    )
    if not doc_row or not doc_row["current_version_id"]:
        raise HTTPException(status_code=404, detail="Document/version not found")

    version_id = doc_row["current_version_id"]
    review_row = await db.fetchrow("SELECT * FROM content_reviews WHERE document_version_id=$1 ORDER BY created_at DESC LIMIT 1", version_id)
    if not review_row:
        raise HTTPException(status_code=404, detail="Review not found for this document")

    w_row = await db.fetchrow("SELECT * FROM workflows WHERE review_id=$1", review_row["id"])
    if not w_row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if str(w_row.get("current_stage") or "") != "marketing_review":
        raise HTTPException(status_code=409, detail="Document is not in marketing review stage")

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    user_id = (current_user or {}).get("id")
    await db.execute(
        "UPDATE workflows SET current_stage='compliance_review', assigned_role='compliance', assigned_to=$1, updated_at=$2 WHERE id=$3",
        compliance_reviewer_id, now_utc, w_row["id"]
    )
    step_order = await _next_step_order(db, w_row["id"])
    await db.execute(
        "INSERT INTO workflow_steps (id, workflow_id, stage, action, comment, previous_stage, step_order, completed_by, completed_at, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$9)",
        str(uuid.uuid4()), w_row["id"], 'compliance_review', 'submit_to_compliance', None, w_row.get("current_stage"), step_order, user_id, now_utc
    )

    await _notify_workflow_transition(
        db=db,
        background_tasks=background_tasks,
        doc_id=doc_id,
        review_id=str(review_row["id"]),
        from_stage="marketing_review",
        to_stage="compliance_review",
        assigned_role="compliance",
        assigned_to=compliance_reviewer_id,
        organization_id=tenant_ctx["organization_id"],
        org_slug=tenant_ctx.get("organization_slug"),
    )

    await _publish_workflow_event(str(review_row["id"]), doc_id, "approve", "marketing_review", "compliance_review")

    return {"ok": True}


@router.post("/{doc_id}/compliance-approve")
async def compliance_approve_document(
    doc_id: str,
    lock: bool = True,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    roles = set((current_user or {}).get("roles") or [])
    if "compliance" not in roles:
        raise HTTPException(status_code=403, detail="Only compliance can perform this action")

    user_id = (current_user or {}).get("id")
    # [Branch 1] Fetches submitted_by to re-assign after compliance approval
    doc_row = await db.fetchrow(
        "SELECT current_version_id, submitted_by FROM documents WHERE id=$1 AND organization_id=$2",
        doc_id,
        tenant_ctx["organization_id"],
    )
    if not doc_row or not doc_row["current_version_id"]:
        raise HTTPException(status_code=404, detail="Document/version not found")

    version_id = doc_row["current_version_id"]
    submitted_by = doc_row["submitted_by"]
    review_row = await db.fetchrow("SELECT * FROM content_reviews WHERE document_version_id=$1 ORDER BY created_at DESC LIMIT 1", version_id)
    if not review_row:
        raise HTTPException(status_code=404, detail="Review not found for this document")

    w_row = await db.fetchrow("SELECT * FROM workflows WHERE review_id=$1", review_row["id"])
    if not w_row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if str(w_row.get("current_stage") or "") != "compliance_review":
        raise HTTPException(status_code=409, detail="Document is not in compliance review stage")

    assigned_to = w_row.get("assigned_to")
    if not assigned_to:
        raise HTTPException(status_code=409, detail="You must claim this review before taking action")
    if str(assigned_to) != str(user_id):
        raise HTTPException(status_code=403, detail="This review is assigned to another reviewer. You must claim it first.")

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    if lock:
        # [Branch 1] Re-assigns to submitted_by and sets compliance_status='compliant'
        await db.execute(
            "UPDATE workflows SET current_stage='approved', assigned_role='marketing', assigned_to=$1, updated_at=$2 WHERE id=$3",
            submitted_by, now_utc, w_row["id"]
        )
        await db.execute(
            "UPDATE content_reviews SET compliance_status='compliant', is_locked=TRUE, locked_at=$1, locked_by=$2, updated_at=$1 WHERE id=$3",
            now_utc, user_id, review_row["id"]
        )
    else:
        await db.execute(
            "UPDATE workflows SET current_stage='approved', assigned_role='marketing', assigned_to=$1, updated_at=$2 WHERE id=$3",
            submitted_by, now_utc, w_row["id"]
        )
        # [Branch 1] Sets compliance_status='compliant' even without lock
        await db.execute(
            "UPDATE content_reviews SET compliance_status='compliant', updated_at=$1 WHERE id=$2",
            now_utc, review_row["id"]
        )

    step_order = await _next_step_order(db, w_row["id"])
    await db.execute(
        "INSERT INTO workflow_steps (id, workflow_id, stage, action, comment, previous_stage, step_order, completed_by, completed_at, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$9)",
        str(uuid.uuid4()), w_row["id"], 'approved', 'approve_and_lock', None, w_row.get("current_stage"), step_order, user_id, now_utc
    )

    await _notify_workflow_transition(
        db=db,
        background_tasks=background_tasks,
        doc_id=doc_id,
        review_id=str(review_row["id"]),
        from_stage="compliance_review",
        to_stage="approved",
        assigned_role="marketing",
        assigned_to=str(submitted_by) if submitted_by else None,
        organization_id=tenant_ctx["organization_id"],
        org_slug=tenant_ctx.get("organization_slug"),
        workflow_action="approve",
        actor_user_id=str(user_id),
    )

    # [Branch 1] Generate or update the compliance report on approval
    role_name = next(iter(roles), "compliance")
    await generate_compliance_report(db, str(review_row["id"]), str(user_id), role_name)

    await _publish_workflow_event(str(review_row["id"]), doc_id, "approve", "compliance_review", "approved")

    return {"ok": True}


@router.post("/{doc_id}/compliance-reject")
async def compliance_reject_document(
    doc_id: str,
    comment: Optional[str] = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    roles = set((current_user or {}).get("roles") or [])
    if "compliance" not in roles:
        raise HTTPException(status_code=403, detail="Only compliance can reject at this stage")

    user_id = (current_user or {}).get("id")
    # [Branch 1] Fetches submitted_by to re-assign on rejection
    doc_row = await db.fetchrow(
        "SELECT current_version_id, submitted_by FROM documents WHERE id=$1 AND organization_id=$2",
        doc_id,
        tenant_ctx["organization_id"],
    )
    if not doc_row or not doc_row["current_version_id"]:
        raise HTTPException(status_code=404, detail="Document/version not found")

    version_id = doc_row["current_version_id"]
    submitted_by = doc_row["submitted_by"]
    review_row = await db.fetchrow("SELECT * FROM content_reviews WHERE document_version_id=$1 ORDER BY created_at DESC LIMIT 1", version_id)
    if not review_row:
        raise HTTPException(status_code=404, detail="Review not found for this document")

    w_row = await db.fetchrow("SELECT * FROM workflows WHERE review_id=$1", review_row["id"])
    if not w_row:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if str(w_row.get("current_stage") or "") != "compliance_review":
        raise HTTPException(status_code=409, detail="Document is not in compliance review stage")

    if w_row.get("assigned_to") and str(w_row.get("assigned_to")) != str(user_id):
        raise HTTPException(status_code=403, detail="You are not the assigned compliance reviewer for this document")

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    # [Branch 1] Re-assigns to submitted_by and sets compliance_status='non_compliant'
    await db.execute(
        "UPDATE workflows SET current_stage='rejected', assigned_role='marketing', assigned_to=$1, updated_at=$2 WHERE id=$3",
        submitted_by, now_utc, w_row["id"]
    )
    await db.execute(
        "UPDATE content_reviews SET compliance_status='non_compliant', review_status='rejected', updated_at=$1 WHERE id=$2",
        now_utc, review_row["id"]
    )
    step_order = await _next_step_order(db, w_row["id"])
    await db.execute(
        "INSERT INTO workflow_steps (id, workflow_id, stage, action, comment, previous_stage, step_order, completed_by, completed_at, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$9)",
        str(uuid.uuid4()), w_row["id"], 'rejected', 'reject', comment, w_row.get("current_stage"), step_order, user_id, now_utc
    )

    await _notify_workflow_transition(
        db=db,
        background_tasks=background_tasks,
        doc_id=doc_id,
        review_id=str(review_row["id"]),
        from_stage="compliance_review",
        to_stage="rejected",
        assigned_role="marketing",
        assigned_to=str(submitted_by) if submitted_by else None,
        organization_id=tenant_ctx["organization_id"],
        org_slug=tenant_ctx.get("organization_slug"),
        workflow_action="reject",
        actor_user_id=str(user_id),
        reviewer_note=comment,
    )

    # [Branch 1] Generate or update the compliance report on rejection too
    role_name = next(iter(roles), "compliance")
    await generate_compliance_report(db, str(review_row["id"]), str(user_id), role_name)

    await _publish_workflow_event(str(review_row["id"]), doc_id, "reject", "compliance_review", "rejected")

    return {"ok": True}


@router.post("/{doc_id}/compliance-request-changes")
async def compliance_request_changes(
    doc_id: str,
    comment: Optional[str] = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    roles = set((current_user or {}).get("roles") or [])
    if "compliance" not in roles:
        raise HTTPException(status_code=403, detail="Only compliance can request changes at this stage")

    user_id = (current_user or {}).get("id")
    # [Branch 1] Fetches submitted_by to re-assign when requesting changes
    doc_row = await db.fetchrow(
        "SELECT current_version_id, submitted_by FROM documents WHERE id=$1 AND organization_id=$2",
        doc_id,
        tenant_ctx["organization_id"],
    )
    if not doc_row or not doc_row["current_version_id"]:
        raise HTTPException(status_code=404, detail="Document/version not found")

    version_id = doc_row["current_version_id"]
    submitted_by = doc_row["submitted_by"]
    review_row = await db.fetchrow("SELECT * FROM content_reviews WHERE document_version_id=$1 ORDER BY created_at DESC LIMIT 1", version_id)
    if not review_row:
        raise HTTPException(status_code=404, detail="Review not found for this document")

    w_row = await db.fetchrow("SELECT * FROM workflows WHERE review_id=$1", review_row["id"])
    if not w_row:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if str(w_row.get("current_stage") or "") != "compliance_review":
        raise HTTPException(status_code=409, detail="Document is not in compliance review stage")

    if w_row.get("assigned_to") and str(w_row.get("assigned_to")) != str(user_id):
        raise HTTPException(status_code=403, detail="You are not the assigned compliance reviewer for this document")

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    # [Branch 1] Re-assigns to submitted_by so the uploader sees the changes request
    await db.execute(
        "UPDATE workflows SET current_stage='marketing_review', assigned_role='marketing', assigned_to=$1, updated_at=$2 WHERE id=$3",
        submitted_by, now_utc, w_row["id"]
    )
    step_order = await _next_step_order(db, w_row["id"])
    await db.execute(
        "INSERT INTO workflow_steps (id, workflow_id, stage, action, comment, previous_stage, step_order, completed_by, completed_at, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$9)",
        str(uuid.uuid4()), w_row["id"], 'marketing_review', 'request_changes', comment, w_row.get("current_stage"), step_order, user_id, now_utc
    )

    await _notify_workflow_transition(
        db=db,
        background_tasks=background_tasks,
        doc_id=doc_id,
        review_id=str(review_row["id"]),
        from_stage="compliance_review",
        to_stage="marketing_review",
        assigned_role="marketing",
        assigned_to=str(submitted_by) if submitted_by else None,
        organization_id=tenant_ctx["organization_id"],
        org_slug=tenant_ctx.get("organization_slug"),
        workflow_action="request_changes",
        actor_user_id=str(user_id),
        reviewer_note=comment,
    )

    await _publish_workflow_event(str(review_row["id"]), doc_id, "request_changes", "compliance_review", "marketing_review")

    return {"ok": True}


@router.post("/{doc_id}/publish")
async def publish_document(
    doc_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    roles = set((current_user or {}).get("roles") or [])
    if "marketing" not in roles:
        raise HTTPException(status_code=403, detail="Only marketing can publish documents")

    user_id = (current_user or {}).get("id")
    doc_row = await db.fetchrow(
        "SELECT current_version_id FROM documents WHERE id=$1 AND organization_id=$2",
        doc_id,
        tenant_ctx["organization_id"],
    )
    if not doc_row or not doc_row["current_version_id"]:
        raise HTTPException(status_code=404, detail="Document/version not found")

    version_id = doc_row["current_version_id"]
    review_row = await db.fetchrow("SELECT * FROM content_reviews WHERE document_version_id=$1 ORDER BY created_at DESC LIMIT 1", version_id)
    if not review_row:
        raise HTTPException(status_code=404, detail="Review not found for this document")

    w_row = await db.fetchrow("SELECT * FROM workflows WHERE review_id=$1", review_row["id"])
    if not w_row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    stage = str(w_row.get("current_stage") or "")
    if stage not in {"approved", "published"}:
        raise HTTPException(status_code=409, detail="Document is not in approved stage")

    assigned_to = w_row.get("assigned_to")
    if not assigned_to:
        raise HTTPException(status_code=409, detail="This document must be assigned to you before you can publish it")
    if str(assigned_to) != str(user_id):
        raise HTTPException(status_code=403, detail="Only the assigned marketing user can publish this document")

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        await db.execute("UPDATE workflows SET current_stage='published', published=TRUE, published_by=$1, published_at=$2, updated_at=$2 WHERE id=$3", user_id, now_utc, w_row["id"])
    except Exception:
        await db.execute("UPDATE workflows SET current_stage='published', updated_at=$1 WHERE id=$2", now_utc, w_row["id"])
    await db.execute("UPDATE content_reviews SET review_status='approved', updated_at=$1 WHERE id=$2", now_utc, review_row["id"])
    step_order = await _next_step_order(db, w_row["id"])
    await db.execute(
        "INSERT INTO workflow_steps (id, workflow_id, stage, action, comment, previous_stage, step_order, completed_by, completed_at, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$9)",
        str(uuid.uuid4()), w_row["id"], 'published', 'publish', None, w_row.get("current_stage"), step_order, user_id, now_utc
    )

    meta_row = await db.fetchrow(
        """
        SELECT d.name AS document_name, d.submitted_by, dv.version_label,
               up.email, up.full_name
        FROM documents d
        JOIN document_versions dv ON d.current_version_id = dv.id
        LEFT JOIN user_profiles up ON up.id = d.submitted_by
        WHERE d.id = $1
        """,
        doc_id,
    )
    if meta_row and meta_row.get("email"):
        author_email = (meta_row.get("email") or "").strip()
        author_name = (meta_row.get("full_name") or "").strip() or author_email.split("@")[0]
        background_tasks.add_task(
            _send_document_published_email_background,
            author_email,
            author_name,
            meta_row.get("document_name") or "Document",
            doc_id,
            str(meta_row.get("version_label") or "1.0"),
            tenant_ctx.get("organization_slug"),
            now_utc,
        )

    await _publish_workflow_event(str(review_row["id"]), doc_id, "publish", str(w_row.get("current_stage") or ""), "published")

    return {"ok": True}


@router.post("/{doc_id}/reupload", response_model=Document)
async def reupload_document(
    doc_id: str,
    file: UploadFile = File(...),
    routing: Optional[str] = Form(None),
    sme_reviewer_id: Optional[str] = Form(None),
    compliance_reviewer_id: Optional[str] = Form(None),
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db=Depends(get_db),
):
    roles = set((current_user or {}).get("roles") or [])
    if "marketing" not in roles:
        raise HTTPException(status_code=403, detail="Only marketing can reupload documents")

    user_id = (current_user or {}).get("id")
    doc_row = await db.fetchrow(
        "SELECT id, name, type FROM documents WHERE id=$1 AND organization_id=$2",
        doc_id,
        tenant_ctx["organization_id"],
    )
    if not doc_row:
        raise HTTPException(status_code=404, detail="Document not found")

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    uploaded_file_name = file.filename or "uploaded.pdf"
    content = await file.read()
    file_size = len(content)
    content_type = _validate_marketing_upload(uploaded_file_name, content)

    quota_precheck = await evaluate_upload_quota_change(
        db,
        str(tenant_ctx["organization_id"]),
        incoming_upload_count=1,
        incoming_upload_bytes=file_size,
    )
    if quota_precheck["should_block"]:
        _raise_upload_quota_exceeded(quota_precheck)
    
    def get_next_version_label(current_label: Optional[str]) -> str:
        if not current_label:
            return "1.0"
        
        current_label = str(current_label).strip()
        
        if current_label.lower().startswith("v"):
            try:
                old_version = int(current_label[1:])
                if old_version <= 9:
                    return f"1.{old_version}"
                major = old_version // 10
                minor = old_version % 10
                return f"{major}.{minor}"
            except ValueError:
                return "1.0"
        
        try:
            parts = current_label.split(".")
            if len(parts) == 2:
                major = int(parts[0])
                minor = int(parts[1])
                if minor < 9:
                    return f"{major}.{minor + 1}"
                return f"{major + 1}.0"
            else:
                return "1.0"
        except (ValueError, IndexError):
            return "1.0"
    
    # Automatically determine routing based on previous request_changes step
    last_rejection_step = await db.fetchrow(
        """
        SELECT ws.previous_stage, ws.completed_by
        FROM workflow_steps ws
        JOIN workflows w ON ws.workflow_id = w.id
        JOIN content_reviews cr ON w.review_id = cr.id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        WHERE dv.document_id = $1
          AND ws.action = 'request_changes'
        ORDER BY ws.created_at DESC
        LIMIT 1
        """,
        doc_id
    )

    if last_rejection_step:
        prev_stage = last_rejection_step["previous_stage"]
        completed_by = last_rejection_step["completed_by"]
        
        if prev_stage == "sme_review":
            initial_stage = "sme_review"
            assigned_role = "sme"
            assignee_id = completed_by
        elif prev_stage == "compliance_review":
            initial_stage = "marketing_review"
            assigned_role = "marketing"
            assignee_id = user_id
        else:
            initial_stage = "sme_review"
            assigned_role = "sme"
            assignee_id = None
    else:
        # Fallback to default if no history found
        initial_stage = "sme_review"
        assigned_role = "sme"
        assignee_id = None

    # Always create a new version linked to the existing doc_id
    last_label = await db.fetchval(
        "SELECT version_label FROM document_versions WHERE document_id=$1 ORDER BY uploaded_at DESC LIMIT 1",
        doc_id,
    )
    next_version_label = get_next_version_label(last_label)
    version_id = str(uuid.uuid4())
    review_id = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())

    try:
        s3_key = save_marketing_doc_versioned(
            document_id=doc_id,
            file_name=uploaded_file_name,
            file_bytes=content,
            content_type=content_type,
        )
    except Exception:
        s3_key = f"marketing_docs/{doc_id}/{uploaded_file_name}"

    async with db.transaction():
        await acquire_upload_quota_lock(db, str(tenant_ctx["organization_id"]))
        quota_locked_check = await evaluate_upload_quota_change(
            db,
            str(tenant_ctx["organization_id"]),
            incoming_upload_count=1,
            incoming_upload_bytes=file_size,
        )
        if quota_locked_check["should_block"]:
            _raise_upload_quota_exceeded(quota_locked_check)

        await db.execute(
            """
            INSERT INTO document_versions (
                id, document_id, version_label, uploaded_at, status, s3_bucket, s3_key, extracted_text, file_size_bytes
            )
            VALUES ($1, $2, $3, $4, 'processing', $5, $6, NULL, $7)
            """,
            version_id, doc_id, next_version_label, now_utc,
            ai_config.AWS_S3_BUCKET or "demo-bucket", s3_key, file_size,
        )

        # Update document metadata, but DO NOT change the document name per Lead's request
        await db.execute(
            "UPDATE documents SET current_version_id=$1, updated_at=$2 WHERE id=$3",
            version_id, now_utc, doc_id,
        )

        try:
            await db.execute(
                """
                INSERT INTO content_reviews (id, content_type, document_version_id, compliance_status, review_status, created_at, updated_at)
                VALUES ($1, 'marketing_material', $2, 'conditional', 'pending', $3, $3)
                """,
                review_id, version_id, now_utc,
            )
        except asyncpg.UndefinedColumnError:
            await db.execute(
                """
                INSERT INTO content_reviews (id, content_type, document_version_id, review_status, created_at, updated_at)
                VALUES ($1, 'marketing_material', $2, 'pending', $3, $3)
                """,
                review_id, version_id, now_utc,
            )

        await db.execute(
            """
            INSERT INTO workflows (id, review_id, current_stage, assigned_to, assigned_role, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $6)
            """,
            workflow_id, review_id, initial_stage, assignee_id, assigned_role, now_utc,
        )

        await db.execute(
            """
            INSERT INTO workflow_steps (
                id, workflow_id, stage, action, comment, previous_stage, step_order, completed_by, completed_at, created_at
            ) VALUES ($1, $2, 'marketing_review', 'reuploaded', NULL, NULL, 1, $3, $4, $4)
            """,
            str(uuid.uuid4()), workflow_id, user_id, now_utc,
        )

    result_doc_id = doc_id

    # Classification and pre-extraction now handled fully in background via Celery worker.
    try:
        from apis.services.celery_tasks import classify_document_task
        classify_document_task.delay(
            doc_id=result_doc_id,
            version_id=version_id,
            bucket=ai_config.AWS_S3_BUCKET or "demo-bucket",
            s3_key=s3_key,
            user_id=user_id,
            initial_stage=initial_stage,
            organization_id=tenant_ctx.get("organization_id")
        )
        logger.info("Classification and pre-extraction queued via Celery for reupload doc_id=%s version_id=%s", result_doc_id, version_id)
    except Exception as class_err:
        logger.warning(
            "REUPLOAD_CLASSIFICATION_DISPATCH_FAILED doc_id=%s version_id=%s err=%s",
            result_doc_id, version_id, str(class_err)
        )

    # Reviewer notifications deferred until Celery classification confirms in-scope
    # (same path as first upload via _classify_document_bg).

    # Warm Office preview cache in background on reupload.
    source_ext = _extension_from_filename(file.filename or Path(s3_key).name)
    if source_ext in _OFFICE_PREVIEW_EXTENSIONS:
        from apis.services.celery_tasks import warm_office_preview_task
        warm_office_preview_task.delay(
            result_doc_id,
            version_id,
            ai_config.AWS_S3_BUCKET or "demo-bucket",
            s3_key,
        )
        logger.info("Office preview warmup queued via Celery for reupload doc_id=%s version_id=%s", result_doc_id, version_id)

    return await _document_model_for_user(db, result_doc_id, current_user, tenant_ctx)

@router.get("/{document_id}/comments")
async def get_document_comments(
    document_id: str,
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    query = """
        SELECT
            c.id, c.review_id, c.author_id, c.content, c.workflow_stage, c.created_at,
            u.full_name as author_name,
            dv.version_label,
            (SELECT string_agg(r.name, ', ' ORDER BY r.name) FROM user_roles ur JOIN roles r ON ur.role_id = r.id WHERE ur.user_id = u.id) as author_role
        FROM content_comments c
        JOIN content_reviews cr ON c.review_id = cr.id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        JOIN documents d ON d.id = dv.document_id
        LEFT JOIN user_profiles u ON c.author_id = u.id
        WHERE dv.document_id = $1 AND d.organization_id = $2
        ORDER BY c.created_at ASC
    """
    rows = await db.fetch(query, document_id, tenant_ctx["organization_id"])
    return [dict(r) for r in rows]

@router.get("/{document_id}/workflow-steps")
async def get_document_workflow_steps(
    document_id: str,
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    query = """
        SELECT
            ws.*,
            cb.full_name as completed_by_name,
            clb.full_name as claimed_by_name,
            dv.version_label
        FROM workflow_steps ws
        JOIN workflows w ON ws.workflow_id = w.id
        JOIN content_reviews cr ON w.review_id = cr.id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        JOIN documents d ON d.id = dv.document_id
        LEFT JOIN user_profiles cb ON ws.completed_by = cb.id
        LEFT JOIN user_profiles clb ON ws.claimed_by = clb.id
        WHERE dv.document_id = $1 AND d.organization_id = $2
        ORDER BY ws.created_at ASC
    """
    rows = await db.fetch(query, document_id, tenant_ctx["organization_id"])
    steps = []
    for step in rows:
        sd = dict(step)
        sd["user_name"] = sd.get("completed_by_name") or sd.get("claimed_by_name") or "System"
        steps.append(sd)
    return steps

@router.get("/{document_id}/audit-trail-unified")
async def get_document_audit_trail_unified(
    document_id: str,
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    # 1. Query workflow_steps
    workflow_query = """
        SELECT
            ws.id,
            'workflow_step' as event_source,
            ws.action as event_type,
            COALESCE(ws.completed_at, ws.claimed_at, ws.created_at) as timestamp,
            ws.stage as workflow_stage,
            ws.previous_stage,
            ws.comment,
            u.full_name as user_name,
            u.id as user_id,
            (SELECT string_agg(r.name, ', ' ORDER BY r.name) FROM user_roles ur JOIN roles r ON ur.role_id = r.id WHERE ur.user_id = COALESCE(ws.completed_by, ws.claimed_by)) as user_role,
            dv.version_label
        FROM workflow_steps ws
        JOIN workflows w ON ws.workflow_id = w.id
        JOIN content_reviews cr ON w.review_id = cr.id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        JOIN documents d ON d.id = dv.document_id
        LEFT JOIN user_profiles u ON COALESCE(ws.completed_by, ws.claimed_by) = u.id
        WHERE dv.document_id = $1 AND d.organization_id = $2
    """
    workflow_rows = await db.fetch(workflow_query, document_id, tenant_ctx["organization_id"])
    
    # 2. Query audit_events
    audit_query = '''
        SELECT 
            ae.id,
            'audit_event' as event_source,
            ae.event_type,
            ae.created_at as timestamp,
            ae.workflow_stage,
            NULL::varchar as previous_stage,
            ae.details as raw_details,
            u.full_name as user_name,
            ae.user_id,
            ae.user_role,
            ae.description,
            ae.is_ai,
            ae.triggered_by_user_id,
            triggered_by_user.full_name as triggered_by_user_name,
            dv.version_label,
            CASE 
                WHEN ae.event_type IN ('finding_accepted', 'finding_accepted_global', 'finding_accepted_local', 'finding_rejected', 'finding_rejected_global', 'finding_dismissed', 'finding_comment_added', 'finding_suggestion_added')
                AND ae.details IS NOT NULL
                AND ae.details ~ '^[[:space:]]*\{'
                THEN NULLIF(ae.details::json->>'finding_code', '')
                ELSE NULL
            END as json_finding_code,
            CASE 
                WHEN ae.event_type IN ('finding_accepted', 'finding_accepted_global', 'finding_accepted_local', 'finding_rejected', 'finding_rejected_global', 'finding_dismissed', 'finding_comment_added', 'finding_suggestion_added')
                AND ae.details IS NOT NULL
                AND ae.details ~ '^[[:space:]]*\{'
                THEN (
                    SELECT json_build_object(
                        'finding_id', COALESCE((ae.details::json->>'finding_id'), af.id::text),
                        'finding_code', COALESCE(NULLIF(ae.details::json->>'finding_code', ''), NULLIF(ae.details::json->>'finding_code', 'null'), NULLIF(ae.details::json->>'finding_code', 'None'), af.finding_code, 'N/A'),
                        'finding_title', COALESCE(NULLIF(ae.details::json->>'finding_title', ''), af.title),
                        'finding_description', COALESCE(NULLIF(ae.details::json->>'finding_description', ''), af.description),
                        'risk_level', COALESCE(NULLIF(ae.details::json->>'risk_level', ''), af.risk_level),
                        'location', COALESCE(NULLIF(ae.details::json->>'location', ''), af.location, 'N/A')
                    )
                    FROM ai_findings af
                    WHERE af.id::text = (ae.details::json->>'finding_id')
                    LIMIT 1
                )
                ELSE NULL
            END as finding_details,
            CASE 
                WHEN ae.event_type = 'finding_comment_added' AND ae.details IS NOT NULL
                THEN COALESCE(
                    CASE WHEN ae.details ~ '^[[:space:]]*\{' THEN (ae.details::json->>'comment_content') ELSE NULL END,
                    (SELECT fc.content FROM finding_comments fc WHERE fc.id::text = (CASE WHEN ae.details ~ '^[[:space:]]*\{' THEN (ae.details::json->>'comment_id') ELSE NULL END) LIMIT 1)
                )
                ELSE NULL
            END as finding_comment_content,
            CASE 
                WHEN ae.event_type = 'finding_suggestion_added' AND ae.details IS NOT NULL
                THEN COALESCE(
                    CASE WHEN ae.details ~ '^[[:space:]]*\{' THEN (ae.details::json->>'suggestion_text') ELSE NULL END,
                    (SELECT fs.text FROM finding_suggestions fs WHERE fs.id::text = (CASE WHEN ae.details ~ '^[[:space:]]*\{' THEN (ae.details::json->>'suggestion_id') ELSE NULL END) LIMIT 1)
                )
                ELSE NULL
            END as finding_suggestion_text
        FROM audit_events ae
        JOIN content_reviews cr ON ae.review_id = cr.id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        JOIN documents d ON d.id = dv.document_id
        LEFT JOIN user_profiles u ON ae.user_id = u.id
        LEFT JOIN user_profiles triggered_by_user ON ae.triggered_by_user_id = triggered_by_user.id
        WHERE dv.document_id = $1 AND d.organization_id = $2
        AND ae.event_type != 'version_created'
        AND ae.event_type NOT IN (
            'ai_phase_parsing_document',
            'ai_phase_classifying_document',
            'ai_phase_analysing_document',
            'ai_phase_performing_analysis',
            'ai_phase_consolidating_result'
        )
    '''
    audit_rows = await db.fetch(audit_query, document_id, tenant_ctx["organization_id"])
    
    # 3. Query content_comments
    content_comments_query = '''
        SELECT 
            cc.id,
            'content_comment' as event_source,
            'comment_added' as event_type,
            cc.created_at as timestamp,
            cc.workflow_stage,
            NULL::varchar as previous_stage,
            cc.content as comment,
            u.full_name as user_name,
            cc.author_id as user_id,
            (SELECT string_agg(r.name, ', ' ORDER BY r.name) FROM user_roles ur JOIN roles r ON ur.role_id = r.id WHERE ur.user_id = cc.author_id) as user_role,
            dv.version_label
        FROM content_comments cc
        JOIN content_reviews cr ON cc.review_id = cr.id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        JOIN documents d ON d.id = dv.document_id
        LEFT JOIN user_profiles u ON cc.author_id = u.id
        WHERE dv.document_id = $1 AND d.organization_id = $2
    '''
    content_comment_rows = await db.fetch(content_comments_query, document_id, tenant_ctx["organization_id"])
    
    # 4. Combine and normalize all events
    all_events = []
    
    for row in workflow_rows:
        timestamp = row["timestamp"]
        event_type = row["event_type"] or ""
        if event_type in ("uploaded", "reuploaded"):
            stage = "document_upload"
        else:
            stage = row["workflow_stage"] or ""
        user_id = str(row["user_id"]) if row["user_id"] else None
        all_events.append({
            "id": str(row["id"]),
            "source": "workflow_step",
            "event_type": event_type,
            "timestamp": timestamp.isoformat() if timestamp else "",
            "time": timestamp.strftime("%I:%M %p") if timestamp else "",
            "date": timestamp.strftime("%d %b, %Y") if timestamp else "",
            "workflow_stage": _standardize_stage_name(stage),
            "previous_stage": _standardize_stage_name(row["previous_stage"]) if row["previous_stage"] else None,
            "user": row["user_name"] or "System",
            "user_role": row["user_role"] or "unknown",
            "user_id": user_id,
            "is_ai": False,
            "description": f"Workflow action: {event_type}",
            "details": None,
            "comment": row["comment"],
            "finding": None,
            "finding_comment": None,
            "finding_suggestion": None,
            "grouping_user_id": user_id,
            "grouping_user_name": row["user_name"] or "System",
            "version_label": row["version_label"]
        })
    
    for row in audit_rows:
        timestamp = row["timestamp"]
        finding_details = row.get("finding_details")
        json_finding_code = row.get("json_finding_code")
        finding_obj = None
        if finding_details:
            if isinstance(finding_details, dict):
                finding_obj = finding_details
                if "finding_id" in finding_obj:
                    del finding_obj["finding_id"]
                if json_finding_code and json_finding_code not in ("null", "None", "", None):
                    finding_obj["finding_code"] = json_finding_code
                elif not finding_obj.get("finding_code") or finding_obj.get("finding_code") in ("null", "None", "", None):
                    finding_obj["finding_code"] = "N/A"
            elif isinstance(finding_details, str):
                try:
                    finding_obj = json.loads(finding_details)
                    if json_finding_code and json_finding_code not in ("null", "None", "", None):
                        finding_obj["finding_code"] = json_finding_code
                    elif not finding_obj.get("finding_code") or finding_obj.get("finding_code") in ("null", "None", "", None):
                        finding_obj["finding_code"] = "N/A"
                except:
                    finding_obj = None
        elif json_finding_code and json_finding_code not in ("null", "None", "", None):
            finding_obj = {
                "finding_code": json_finding_code,
                "finding_title": None,
                "finding_description": None,
                "risk_level": None,
                "location": "N/A"
            }
        else:
            if row.get("event_type") in ("finding_accepted", "finding_accepted_global", "finding_accepted_local", "finding_rejected", "finding_rejected_global", "finding_dismissed", "finding_comment_added", "finding_suggestion_added"):
                try:
                    raw_details = row.get("raw_details")
                    if raw_details:
                        details_dict = json.loads(raw_details) if isinstance(raw_details, str) else raw_details
                        if isinstance(details_dict, dict):
                            finding_id = details_dict.get("finding_id")
                            if finding_id:
                                finding_row = await db.fetchrow("SELECT finding_code, title FROM ai_findings WHERE id::text = $1", finding_id)
                                if finding_row and finding_row.get("finding_code"):
                                    finding_obj = {
                                        "finding_code": finding_row["finding_code"],
                                        "finding_title": finding_row.get("title"),
                                        "finding_description": None,
                                        "risk_level": None,
                                        "location": "N/A"
                                    }
                except Exception:
                    pass
        
        stage = row["workflow_stage"] or ""
        triggered_by_user_id = str(row["triggered_by_user_id"]) if row.get("triggered_by_user_id") else None
        triggered_by_user_name = row.get("triggered_by_user_name")
        user_id = str(row["user_id"]) if row["user_id"] else None
        
        if row["is_ai"]:
            grouping_user_id = triggered_by_user_id or user_id
            grouping_user_name = triggered_by_user_name or row["user_name"] or "System"
        else:
            grouping_user_id = user_id
            grouping_user_name = row["user_name"] or "Unknown"
        
        raw_details = row.get("raw_details")
        filtered_details = None
        if raw_details:
            try:
                details_json = json.loads(raw_details) if isinstance(raw_details, str) else raw_details
                if isinstance(details_json, dict):
                    for tk in ["finding_id", "finding_uuid", "comment_id", "suggestion_id", "user_id"]:
                        details_json.pop(tk, None)
                    filtered_details = json.dumps(details_json)
                else:
                    filtered_details = raw_details
            except:
                filtered_details = raw_details

        all_events.append({
            "id": str(row["id"]),
            "source": "audit_event",
            "event_type": row["event_type"] or "",
            "timestamp": timestamp.isoformat() if timestamp else "",
            "time": timestamp.strftime("%I:%M %p") if timestamp else "",
            "date": timestamp.strftime("%d %b, %Y") if timestamp else "",
            "workflow_stage": _standardize_stage_name(stage),
            "previous_stage": _standardize_stage_name(row["previous_stage"]) if row["previous_stage"] else None,
            "user": row["user_name"] or ("System" if row["is_ai"] else "Unknown"),
            "user_role": row["user_role"] or ("ai" if row["is_ai"] else "unknown"),
            "user_id": user_id,
            "is_ai": row["is_ai"] or False,
            "description": row["description"] or "",
            "details": filtered_details,
            "comment": None,
            "finding": finding_obj,
            "finding_comment": row.get("finding_comment_content"),
            "finding_suggestion": row.get("finding_suggestion_text"),
            "triggered_by_user_id": triggered_by_user_id,
            "grouping_user_id": grouping_user_id,
            "grouping_user_name": grouping_user_name,
            "version_label": row["version_label"]
        })
    
    for row in content_comment_rows:
        timestamp = row["timestamp"]
        stage = row["workflow_stage"] or ""
        user_id = str(row["user_id"]) if row["user_id"] else None
        all_events.append({
            "id": str(row["id"]),
            "source": "content_comment",
            "event_type": "comment_added",
            "timestamp": timestamp.isoformat() if timestamp else "",
            "time": timestamp.strftime("%I:%M %p") if timestamp else "",
            "date": timestamp.strftime("%d %b, %Y") if timestamp else "",
            "workflow_stage": _standardize_stage_name(stage),
            "previous_stage": None,
            "user": row["user_name"] or "Unknown",
            "user_role": row["user_role"] or "unknown",
            "user_id": user_id,
            "is_ai": False,
            "description": "Comment added",
            "details": None,
            "comment": row["comment"],
            "finding": None,
            "finding_comment": None,
            "finding_suggestion": None,
            "grouping_user_id": user_id,
            "grouping_user_name": row["user_name"] or "Unknown",
            "version_label": row["version_label"]
        })
    
    all_events.sort(key=lambda x: x["timestamp"] or "")
    
    seen_document_upload = set()
    filtered_events = []
    for event in all_events:
        is_upload_event = (
            event["event_type"] == "document_upload" or
            (event.get("source") == "workflow_step" and event["event_type"] in ("uploaded", "reuploaded"))
        )
        version_key = event["version_label"]
        if is_upload_event:
            if version_key not in seen_document_upload:
                seen_document_upload.add(version_key)
                filtered_events.append(event)
        else:
            filtered_events.append(event)
    
    for i, event in enumerate(filtered_events):
        if event.get("is_ai") and not event.get("grouping_user_id"):
            for j in range(i - 1, -1, -1):
                prev_event = filtered_events[j]
                if prev_event.get("grouping_user_id") and not prev_event.get("is_ai") and prev_event.get("version_label") == event.get("version_label"):
                    event["grouping_user_id"] = prev_event["grouping_user_id"]
                    event["grouping_user_name"] = prev_event["grouping_user_name"]
                    break
    
    # We will group by version_label
    version_groups = []
    current_group = None
    
    # Actually, we don't need to group here in backend (since frontend expects flat list and groups it itself)
    # But wait, original backend grouped by user_id and returned user_groups!
    # Let's just group by version_label
    
    for event in filtered_events:
        v_label = event.get("version_label") or "Unknown"
        
        if current_group is None or current_group["version_label"] != v_label:
            if current_group:
                version_groups.append(current_group)
            current_group = {
                "version_id": v_label, # frontend expects version_id or something, we'll use version_label
                "version_label": v_label,
                "events": []
            }
        current_group["events"].append(event)
        
    if current_group:
        version_groups.append(current_group)
        
    return {
        "events": filtered_events,
        "version_groups": version_groups,
    }

