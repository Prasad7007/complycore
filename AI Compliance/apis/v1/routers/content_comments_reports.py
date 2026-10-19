import os
import logging
import asyncio
import json
import datetime
import uuid
from typing import List, Tuple
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
from fastapi.responses import Response
import uuid
import datetime
from starlette.responses import StreamingResponse

from apis.core.database import get_db
from apis.core.security import (
    require_app_access_ready,
    get_current_user,
    assert_app_access_ready,
    require_tenant_context,
    build_tenant_context,
    get_session_token,
    resolve_user_from_token,
)
from apis.core.tenant_resources import assert_review_in_organization
from apis.core.email_links import get_document_comment_url
from apis.core.mail import send_mention_notification_email
from apis.models.content_comments import ContentComment, ContentCommentCreate, ComplianceReport
from apis.services.mention_utils import resolve_mentioned_user_ids
from apis.services.reports import generate_compliance_report
from apis.services.realtime_streams import (
    subscribe_review_comments,
    unsubscribe_review_comments,
    publish_review_comment,
    publish_notification,
    check_recent_notification_exists,
)

router = APIRouter(prefix="/reviews", tags=["content-comments"])
logger = logging.getLogger(__name__)


class _SseEncoder(json.JSONEncoder):
    """Serialize asyncpg/Python types that the default encoder cannot handle."""
    def default(self, obj):
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        if isinstance(obj, uuid.UUID):
            return str(obj)
        return super().default(obj)


def _sse_dumps(data) -> str:
    return json.dumps(data, cls=_SseEncoder)

async def _require_assigned_or_claimed_for_comments(
    db,
    review_id: str,
    user_id: str,
    roles: set[str],
):
    """Ensure SME/compliance users are assigned or have claimed the review before adding comments."""
    # Super admin can always act
    if "super_admin" in roles:
        return
    
    # Marketing users don't need assignment/claim check
    if "marketing" in roles and "compliance" not in roles and "sme" not in roles:
        return
    
    # Get workflow info
    workflow_row = await db.fetchrow(
        "SELECT current_stage, assigned_to FROM workflows WHERE review_id=$1",
        review_id,
    )
    if not workflow_row:
        # If no workflow exists, allow comment (might be edge case)
        return
    
    current_stage = workflow_row.get("current_stage") or ""
    assigned_to = workflow_row.get("assigned_to")

    # If the user was tagged/mentioned in this review previously, they are granted
    # limited comment access regardless of their formal assignment.
    was_mentioned = await db.fetchval(
        """
        SELECT 1 FROM comment_mentions cm
        JOIN content_comments cc ON cc.id = cm.comment_id
        WHERE cc.review_id = $1 AND cm.mentioned_user_id = $2::uuid
        """,
        review_id, user_id
    )
    if was_mentioned:
        return
    
    # Check if user is SME and workflow is in SME review stage
    if "sme" in roles and current_stage == "sme_review":
        if not assigned_to:
            raise HTTPException(
                status_code=409,
                detail="You must claim this review before adding comments"
            )
        if str(assigned_to) != str(user_id):
            raise HTTPException(
                status_code=403,
                detail="This review is assigned to another reviewer. You must claim it first."
            )
    
    # Check if user is compliance and workflow is in compliance review stage
    if "compliance" in roles and current_stage == "compliance_review":
        if not assigned_to:
            raise HTTPException(
                status_code=409,
                detail="You must claim this review before adding comments"
            )
        if str(assigned_to) != str(user_id):
            raise HTTPException(
                status_code=403,
                detail="This review is assigned to another reviewer. You must claim it first."
            )
    
async def _review_context_for_mention(db, review_id: str):
    row = await db.fetchrow(
        """
        SELECT
            d.id AS document_id,
            d.name AS document_name,
            sp.id AS social_post_id,
            sp.preview AS social_preview
        FROM content_reviews cr
        LEFT JOIN document_versions dv ON cr.document_version_id = dv.id
        LEFT JOIN documents d ON dv.document_id = d.id
        LEFT JOIN social_posts sp ON cr.social_post_id = sp.id
        WHERE cr.id = $1
        """,
        review_id,
    )
    return dict(row) if row else None


def _send_mention_emails_background(
    recipients: List[Tuple[str, str]],
    author_name: str,
    document_title: str,
    comment_preview: str,
    doc_id: str,
    org_slug: str | None,
    comment_id: str,
) -> None:
    """Sync: send one SES email per recipient (runs in thread pool via BackgroundTasks)."""
    open_url = get_document_comment_url(doc_id, org_slug=org_slug, comment_id=comment_id)
    for to_email, recipient_name in recipients:
        send_mention_notification_email(
            to_email=to_email,
            recipient_name=recipient_name,
            author_name=author_name,
            document_title=document_title,
            comment_preview=comment_preview,
            doc_id=doc_id,
            org_slug=org_slug,
            comment_id=comment_id,
            open_url=open_url,
        )


@router.post("/{review_id}/comments", response_model=ContentComment)
async def add_content_comment(
    review_id: str,
    comment: ContentCommentCreate,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    await assert_review_in_organization(db, review_id, tenant_ctx["organization_id"])
    review = await db.fetchrow("SELECT id FROM content_reviews WHERE id=$1", review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    
    user_id = current_user.get("id")
    roles = set((current_user or {}).get("roles") or [])
    
    # Check if user is assigned/claimed (for SME and compliance users)
    await _require_assigned_or_claimed_for_comments(db, review_id, user_id, roles)
    
    # Get current workflow stage to store with comment
    workflow_row = await db.fetchrow(
        "SELECT current_stage FROM workflows WHERE review_id=$1",
        review_id
    )
    workflow_stage = workflow_row.get("current_stage") if workflow_row else None

    mentioned_ids = await resolve_mentioned_user_ids(
        db,
        content=comment.content,
        explicit_ids=comment.mentioned_user_ids,
        author_id=str(user_id),
    )
    logger.info(
        "MENTION_RESOLVE review_id=%s author_id=%s explicit_ids=%s resolved_ids=%s",
        review_id,
        user_id,
        comment.mentioned_user_ids or [],
        mentioned_ids,
    )

    comment_id = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    await db.execute(
        """
        INSERT INTO content_comments (id, review_id, author_id, content, workflow_stage, created_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        comment_id, review_id, user_id, comment.content, workflow_stage, now
    )

    ctx = await _review_context_for_mention(db, review_id)
    org_slug = tenant_ctx.get("organization_slug")
    doc_id_for_email: str | None = None
    if ctx and ctx.get("document_id"):
        doc_id_for_email = str(ctx["document_id"])
        doc_title = ctx.get("document_name") or "Document"
    elif ctx and ctx.get("social_post_id"):
        pv = (ctx.get("social_preview") or "").strip()
        doc_title = (pv[:60] + "…") if len(pv) > 60 else (pv or "Social post review")
    else:
        doc_title = "Review"

    author_row = await db.fetchrow(
        "SELECT full_name, email FROM user_profiles WHERE id = $1",
        user_id,
    )
    author_name = (author_row.get("full_name") if author_row else None) or (
        author_row.get("email") if author_row else None
    ) or "Someone"

    email_recipients: List[Tuple[str, str]] = []
    for mid in mentioned_ids:
        try:
            m_id = str(uuid.UUID(str(mid)))
        except (ValueError, TypeError):
            continue
        await db.execute(
            """
            INSERT INTO comment_mentions (id, comment_id, mentioned_user_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (comment_id, mentioned_user_id) DO NOTHING
            """,
            str(uuid.uuid4()),
            comment_id,
            m_id,
        )

        notif_title = f"{author_name} mentioned you in '{doc_title}'"
        
        # If we have a document_id, link directly to the document so the notification is clickable.
        # Otherwise fallback to the comment.
        ref_type = "document" if (ctx and ctx.get("document_id")) else "content_comment"
        ref_id = uuid.UUID(str(ctx["document_id"])) if (ctx and ctx.get("document_id")) else uuid.UUID(comment_id)

        notif_msg = comment.content[:500] if comment.content else ""
        if await check_recent_notification_exists(db, str(m_id), notif_title, notif_msg, str(ref_id), 5):
            logger.info("Skipping duplicate mention notification for user %s", m_id)
        else:
            notif_id = str(uuid.uuid4())
            await db.execute(
                """
                INSERT INTO notifications (id, user_id, type, title, message, reference_type, reference_id, is_read, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                notif_id,
                m_id,
                "mention",
                notif_title,
                notif_msg,
                ref_type,
                ref_id,
                False,
                now,
            )
            await publish_notification(
                str(m_id),
                {
                    "event": "notification_created",
                    "notification": {
                        "id": notif_id,
                        "user_id": str(m_id),
                        "type": "mention",
                        "title": notif_title,
                        "message": notif_msg,
                        "reference_type": ref_type,
                        "reference_id": str(ref_id),
                        "is_read": False,
                        "created_at": now.isoformat(),
                    },
                },
            )

        urow = await db.fetchrow(
            "SELECT email, full_name FROM user_profiles WHERE id = $1 AND is_active = TRUE",
            m_id,
        )
        if urow and urow.get("email"):
            to_email = urow["email"]
            rname = urow.get("full_name") or to_email.split("@")[0]
            email_recipients.append((to_email, rname))

    if email_recipients and doc_id_for_email:
        logger.info(
            "MENTION_EMAIL_QUEUE review_id=%s recipients=%s",
            review_id,
            [e for e, _ in email_recipients],
        )
        background_tasks.add_task(
            _send_mention_emails_background,
            email_recipients,
            author_name,
            doc_title,
            comment.content or "",
            doc_id_for_email,
            org_slug,
            comment_id,
        )
    elif email_recipients:
        logger.info(
            "MENTION_EMAIL_SKIP review_id=%s reason=no_document_id recipients=%s",
            review_id,
            [e for e, _ in email_recipients],
        )
    else:
        logger.info("MENTION_EMAIL_QUEUE review_id=%s recipients=[]", review_id)

    # Fetch the newly created comment with joined info
    query = """
        SELECT 
            c.id, c.review_id, c.author_id, c.content, c.workflow_stage, c.created_at,
            u.full_name as author_name,
            (SELECT string_agg(r.name, ', ' ORDER BY r.name) FROM user_roles ur JOIN roles r ON ur.role_id = r.id WHERE ur.user_id = u.id) as author_role
        FROM content_comments c
        LEFT JOIN user_profiles u ON c.author_id = u.id
        WHERE c.id=$1
    """
    row = await db.fetchrow(query, comment_id)
    created_comment = ContentComment(**dict(row))
    await publish_review_comment(
        review_id,
        {
            "event": "comment_created",
            "review_id": review_id,
            "comment": created_comment.model_dump(mode="json"),
        },
    )
    return created_comment


@router.get("/{review_id}/comments/stream")
async def stream_content_comments(
    org_slug: str,
    review_id: str,
    request: Request,
    token: str | None = None,
    db=Depends(get_db),
):
    # Cookie (preferred) -> Authorization header -> legacy ?token= query param.
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

    user_id = str(current.get("id"))
    await assert_app_access_ready(db, user_id)

    tenant_ctx = await build_tenant_context(org_slug, current, db)
    await assert_review_in_organization(db, review_id, tenant_ctx["organization_id"])

    async def _event_generator():
        queue = await subscribe_review_comments(review_id)
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {_sse_dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            await unsubscribe_review_comments(review_id, queue)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@router.get("/{review_id}/comments", response_model=List[ContentComment])
async def list_content_comments(
    review_id: str,
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    await assert_review_in_organization(db, review_id, tenant_ctx["organization_id"])
    query = """
        SELECT 
            c.id, c.review_id, c.author_id, c.content, c.workflow_stage, c.created_at,
            u.full_name as author_name,
            (SELECT string_agg(r.name, ', ' ORDER BY r.name) FROM user_roles ur JOIN roles r ON ur.role_id = r.id WHERE ur.user_id = u.id) as author_role
        FROM content_comments c
        LEFT JOIN user_profiles u ON c.author_id = u.id
        WHERE c.review_id=$1
        ORDER BY c.created_at ASC
    """
    rows = await db.fetch(query, review_id)
    return [ContentComment(**dict(r)) for r in rows]
@router.delete("/{comment_id}")
async def delete_content_comment(
    comment_id: str,
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    org_id = tenant_ctx["organization_id"]
    row = await db.fetchrow(
        """
        SELECT c.id FROM content_comments c
        JOIN content_reviews cr ON cr.id = c.review_id
        LEFT JOIN document_versions dv ON cr.document_version_id = dv.id
        LEFT JOIN documents d ON dv.document_id = d.id
        LEFT JOIN social_posts sp ON cr.social_post_id = sp.id
        WHERE c.id = $1::uuid
          AND (d.organization_id = $2::uuid OR sp.organization_id = $2::uuid)
        """,
        comment_id,
        org_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Comment not found")
    await db.execute("DELETE FROM content_comments WHERE id=$1", comment_id)
    return {"ok": True}

reports_router = APIRouter(prefix="/compliance-reports", tags=["compliance-reports"])

@reports_router.get("", response_model=List[ComplianceReport])
async def list_reports(
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    _ = current_user
    org_id = tenant_ctx["organization_id"]
    query = """
        SELECT 
            cr.*,
            COALESCE(d.name, sp.preview, sp.post_code) AS document_name,
            u.full_name AS approval_authority_name,
            dv.version_label AS version_label
        FROM compliance_reports cr
        LEFT JOIN content_reviews rv ON cr.review_id = rv.id
        LEFT JOIN document_versions dv ON rv.document_version_id = dv.id
        LEFT JOIN documents d ON dv.document_id = d.id
        LEFT JOIN social_posts sp ON rv.social_post_id = sp.id
        LEFT JOIN user_profiles u ON cr.approval_authority = u.id
        WHERE d.organization_id = $1::uuid OR sp.organization_id = $1::uuid
        ORDER BY cr.created_at DESC
    """
    rows = await db.fetch(query, org_id)
    return [ComplianceReport(**dict(r)) for r in rows]

@reports_router.get("/{report_id}", response_model=ComplianceReport)
async def get_report(
    report_id: str,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    _ = current_user
    org_id = tenant_ctx["organization_id"]
    query = """
        SELECT 
            cr.*,
            COALESCE(d.name, sp.preview, sp.post_code) AS document_name,
            u.full_name AS approval_authority_name,
            dv.version_label AS version_label
        FROM compliance_reports cr
        LEFT JOIN content_reviews rv ON cr.review_id = rv.id
        LEFT JOIN document_versions dv ON rv.document_version_id = dv.id
        LEFT JOIN documents d ON dv.document_id = d.id
        LEFT JOIN social_posts sp ON rv.social_post_id = sp.id
        LEFT JOIN user_profiles u ON cr.approval_authority = u.id
        WHERE cr.id=$1
          AND (d.organization_id = $2::uuid OR sp.organization_id = $2::uuid)
    """
    row = await db.fetchrow(query, report_id, org_id)
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    return ComplianceReport(**dict(row))

@router.post("/{review_id}/generate-report", response_model=ComplianceReport)
async def generate_report_manual(
    review_id: str,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    """
    Manual override endpoint to generate a report, simulating the backend behavior
    that usually happens automatically during the `Approve & Lock` workflow step.
    """
    await assert_review_in_organization(db, review_id, tenant_ctx["organization_id"])
    user_id = current_user.get("id")
    roles = current_user.get("roles", [])
    role_name = ", ".join(sorted(roles)) if roles else "user"

    report_id = await generate_compliance_report(db, review_id, str(user_id), role_name)
    if not report_id:
        raise HTTPException(status_code=404, detail="Could not generate report for review")

    return await get_report(report_id, current_user, tenant_ctx, db)

@reports_router.get("/{report_id}/pdf")
async def get_report_pdf(
    report_id: str,
    request: Request,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    from apis.services.report_pdf import generate_report_pdf

    org_id = tenant_ctx["organization_id"]
    
    # 1. Fetch the report
    report = await get_report(report_id, current_user, tenant_ctx, db)
    
    if not report.review_id:
        raise HTTPException(status_code=400, detail="Report does not have an associated review")

    review_id = str(report.review_id)

    # 2. Fetch findings directly from DB
    finding_rows = await db.fetch(
        """
        SELECT f.*, fs.text as accepted_suggestion_text, cr.name as rule_name,
               COALESCE(afa.normalized_claim_hash, '') AS canonical_claim_hash
        FROM ai_findings f
        LEFT JOIN finding_suggestions fs ON f.accepted_suggestion_id = fs.id
        LEFT JOIN compliance_rules cr ON f.rule_id = cr.id
        LEFT JOIN ai_finding_anchors afa ON afa.finding_id = f.id
        WHERE f.review_id=$1
        ORDER BY f.created_at ASC, f.finding_code ASC
        """,
        review_id,
    )
    findings = [dict(row) for row in finding_rows]

    # Fetch comments for findings
    if findings:
        finding_ids = [str(f["id"]) for f in findings]
        comments_rows = await db.fetch(
            """
            SELECT fc.*, u.full_name as author_name
            FROM finding_comments fc
            LEFT JOIN user_profiles u ON fc.author_id = u.id
            WHERE fc.finding_id::text = ANY($1)
            ORDER BY fc.created_at ASC
            """,
            finding_ids,
        )
        comments_by_finding = {}
        for row in comments_rows:
            fid = str(row["finding_id"])
            if fid not in comments_by_finding:
                comments_by_finding[fid] = []
            comments_by_finding[fid].append({
                "id": str(row["id"]),
                "content": row["content"],
                "author_name": row["author_name"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else "",
            })
        for f in findings:
            f["comments"] = comments_by_finding.get(str(f["id"]), [])

        # Fetch suggestions for findings
        suggestions_rows = await db.fetch(
            """
            SELECT fs.*, u.full_name as author_name
            FROM finding_suggestions fs
            LEFT JOIN user_profiles u ON fs.created_by = u.id
            WHERE fs.finding_id::text = ANY($1)
            ORDER BY fs.created_at ASC
            """,
            finding_ids,
        )
        suggestions_by_finding = {}
        for row in suggestions_rows:
            fid = str(row["finding_id"])
            if fid not in suggestions_by_finding:
                suggestions_by_finding[fid] = []
            suggestions_by_finding[fid].append({
                "id": str(row["id"]),
                "text": row["text"],
                "author_name": row["author_name"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else "",
            })
        for f in findings:
            f["suggestions"] = suggestions_by_finding.get(str(f["id"]), [])

    # 3. Fetch audit events directly from DB
    from apis.v1.routers.audit import get_unified_audit_trail
    audit_events_response = await get_unified_audit_trail(review_id, tenant_ctx, db)
    audit_events = audit_events_response.get("events", [])

    # 4. Generate the PDF
    # Read timezone from query params → header → cookie → default
    # Cookie is set by main.tsx on app load and sent automatically with every request
    tz_cookie = request.cookies.get("user-timezone")
    user_timezone = (
        request.query_params.get("timezone")
        or request.headers.get("x-timezone")
        or (tz_cookie and tz_cookie.replace("%2F", "/"))  # decode slash if needed
        or "UTC"
    )
    import logging
    logging.getLogger(__name__).warning(f"[PDF] user_timezone={user_timezone!r}  cookie={tz_cookie!r}  all_params={dict(request.query_params)}")
    
    pdf_bytes = generate_report_pdf(
        report=report.model_dump(),
        findings=findings,
        audit_events=audit_events,
        user_timezone=user_timezone,
    )

    download = request.query_params.get("download", "false").lower() == "true"
    disposition = "attachment" if download else "inline"

    headers = {
        "Content-Disposition": f'{disposition}; filename="ComplyCore-Report-{report.report_code}.pdf"'
    }

    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)

