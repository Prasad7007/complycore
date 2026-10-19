import datetime
import json
import uuid
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
import asyncio
from apis.services.realtime_streams import publish_notification, publish_review_comment
from apis.core.mail import send_mention_notification_email
from apis.core.email_links import get_document_review_url
from pydantic import BaseModel

from apis.core.database import get_db
from apis.core.security import require_app_access_ready, require_tenant_context
from apis.models.findings import (
    AIFeedback,
    AIFeedbackCreate,
    FindingComment,
    FindingCommentCreate,
    FindingSuggestion,
    FindingSuggestionCreate,
    FindingSuggestionUpdate,
)
from apis.v1.routers.audit import log_audit_event

# Import error logger
from apis.core.error_logger import (
    log_error, log_db_error, log_permission_error, log_validation_error,
    ErrorCategory, ErrorSeverity
)

router = APIRouter(prefix="/findings", tags=["findings"])
logger = logging.getLogger(__name__)

_ALLOWED_AI_ROLES = {"marketing", "compliance", "super_admin"}


async def _dispatch_finding_comment_notifications(
    recipients_info: list,
    finding_id: str,
    finding_title: str,
    author_name: str,
    comment_content: str,
    doc_id: str,
    doc_name: str,
    org_slug: Optional[str],
):
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    open_url = get_document_review_url(doc_id, org_slug=org_slug)

    for rec in recipients_info:
        uid = rec["id"]
        email = rec["email"]
        name = rec["name"]

        await publish_notification(
            uid,
            {
                "event": "notification_created",
                "notification": {
                    "id": rec["notif_id"],
                    "user_id": uid,
                    "type": "finding_comment_added",
                    "title": rec["notif_title"],
                    "message": rec["notif_message"],
                    "reference_type": "document",
                    "reference_id": doc_id,
                    "is_read": False,
                    "created_at": rec["created_at"],
                },
            },
        )
        if email:
            await asyncio.to_thread(
                send_mention_notification_email,
                to_email=email,
                recipient_name=name,
                author_name=author_name,
                document_title=doc_name,
                comment_preview=comment_content,
                doc_id=doc_id,
                org_slug=org_slug,
                open_url=open_url,
            )

def _org_super_admin(role_in_org: str | None) -> bool:
    return (role_in_org or "").strip().lower() == "super_admin"


async def _assert_review_in_tenant_org(db, review_id: str, organization_id: str) -> None:
    ok = await db.fetchval(
        """
        SELECT 1
        FROM content_reviews cr
        JOIN document_versions dv ON cr.document_version_id = dv.id
        JOIN documents d ON d.id = dv.document_id
        WHERE cr.id = $1::uuid AND d.organization_id = $2::uuid
        LIMIT 1
        """,
        review_id,
        organization_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Review not found")


async def _fetch_finding_in_tenant_org(db, finding_id: str, organization_id: str):
    finding = await db.fetchrow(
        """
        SELECT af.id, af.review_id, af.finding_code, af.title
        FROM ai_findings af
        JOIN content_reviews cr ON cr.id = af.review_id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        JOIN documents d ON d.id = dv.document_id
        WHERE af.id = $1::uuid AND d.organization_id = $2::uuid
        LIMIT 1
        """,
        finding_id,
        organization_id,
    )
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    return finding


def _require_ai_access(roles: set[str], user_id: str = None):
    if not roles.intersection(_ALLOWED_AI_ROLES):
        log_permission_error(
            ValueError("User lacks AI access roles"),
            "access_ai_findings",
            requiredRole="marketing|compliance|super_admin",
            userId=user_id
        )
        logger.warning(f"[FINDINGS] Access denied for user {user_id}. Roles: {roles}")
        raise HTTPException(status_code=403, detail="You do not have access to AI findings")


async def _require_assigned_or_claimed_for_findings(
    db,
    review_id: str,
    user_id: str,
    roles: set[str],
    role_in_org: str | None = None,
):
    """Ensure SME/compliance users are assigned or have claimed the review before acting on findings."""
    # Marketing users (and super_admin / org super_admin, treated as marketing for workflow) don't need assignment/claim check
    if (
        "marketing" in roles or "super_admin" in roles or _org_super_admin(role_in_org)
    ) and "compliance" not in roles and "sme" not in roles:
        return
    
    # Get workflow info
    try:
        workflow_row = await db.fetchrow(
            "SELECT current_stage, assigned_to, assigned_role FROM workflows WHERE review_id=$1",
            review_id,
        )
        if not workflow_row:
            log_db_error(
                ValueError(f"Workflow not found for review {review_id}"),
                "fetch_workflow_for_findings",
                user_id=user_id
            )
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        current_stage = workflow_row.get("current_stage") or ""
        assigned_to = workflow_row.get("assigned_to")
        
        # Check if user is SME and workflow is in SME review stage
        if "sme" in roles and current_stage == "sme_review":
            if not assigned_to:
                logger.warning(f"[FINDINGS] SME user {user_id} attempted to act on unassigned review {review_id}")
                raise HTTPException(
                    status_code=409,
                    detail="You must claim this review before taking action on findings"
                )
            if str(assigned_to) != str(user_id):
                logger.warning(f"[FINDINGS] SME user {user_id} attempted to act on review assigned to {assigned_to}")
                raise HTTPException(
                    status_code=403,
                    detail="This review is assigned to another reviewer. You must claim it first."
                )
        
        # Check if user is compliance and workflow is in compliance review stage
        if "compliance" in roles and current_stage == "compliance_review":
            if not assigned_to:
                logger.warning(f"[FINDINGS] Compliance user {user_id} attempted to act on unassigned review {review_id}")
                raise HTTPException(
                    status_code=409,
                    detail="You must claim this review before taking action on findings"
                )
            if str(assigned_to) != str(user_id):
                logger.warning(f"[FINDINGS] Compliance user {user_id} attempted to act on review assigned to {assigned_to}")
                raise HTTPException(
                    status_code=403,
                    detail="This review is assigned to another reviewer. You must claim it first."
                )
    except HTTPException:
        raise
    except Exception as e:
        log_db_error(
            e,
            "check_assignment_for_findings",
            context={"review_id": review_id},
            user_id=user_id
        )
        logger.error(f"[FINDINGS] Error checking assignment for review {review_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to check assignment permissions")


@router.get("/reviews/{review_id}/findings")
async def get_findings_for_review(
    review_id: str,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    user_id = (current_user or {}).get("id")
    roles = set((current_user or {}).get("roles") or [])

    logger.info(f"[FINDINGS] Fetching findings for review {review_id}, user: {user_id}")

    try:
        _require_ai_access(roles, user_id)
        await _assert_review_in_tenant_org(db, review_id, tenant_ctx["organization_id"])

        rows = await db.fetch(
            """
            SELECT f.*, fs.text as accepted_suggestion_text 
            FROM ai_findings f 
            LEFT JOIN finding_suggestions fs ON f.accepted_suggestion_id = fs.id
            WHERE f.review_id=$1 
            ORDER BY f.created_at ASC, f.finding_code ASC
            """, 
            review_id
        )
        
        findings_count = len(rows) if rows else 0
        logger.info(f"[FINDINGS] Retrieved {findings_count} findings for review {review_id}")
        
        return [dict(row) for row in rows]
    except HTTPException:
        raise
    except Exception as e:
        log_db_error(
            e,
            "fetch_findings_for_review",
            context={"review_id": review_id},
            user_id=user_id
        )
        logger.error(f"[FINDINGS] Error fetching findings for review {review_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch findings")


class FindingStatusUpdate(BaseModel):
    status: str
    suggestion_id: Optional[str] = None
    reason: Optional[str] = None


@router.put("/{finding_id}/status")
async def update_finding_status(
    finding_id: str,
    payload: FindingStatusUpdate,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    user_id = (current_user or {}).get("id")
    roles = set((current_user or {}).get("roles") or [])
    
    logger.info(f"[FINDINGS] Updating finding status. Finding: {finding_id}, New Status: {payload.status}, User: {user_id}")
    
    try:
        _require_ai_access(roles, user_id)

        status_value = (payload.status or "").strip().lower()
        allowed_statuses = {"pending", "accepted", "rejected", "dismissed"}
        
        if status_value not in allowed_statuses:
            log_validation_error(
                ValueError(f"Invalid status: {payload.status}"),
                operation="update_finding_status",
                field="status",
                value=payload.status
            )
            logger.warning(f"[FINDINGS] Invalid status '{payload.status}' attempted for finding {finding_id}")
            raise HTTPException(status_code=400, detail=f"Invalid finding status '{payload.status}'")

        if status_value == "rejected" and not roles.intersection({"compliance"}):
            log_permission_error(
                ValueError("User lacks permission to reject findings"),
                "reject_finding",
                requiredRole="compliance",
                userId=user_id
            )
            logger.warning(f"[FINDINGS] User {user_id} attempted to reject finding without required role")
            raise HTTPException(status_code=403, detail="Only compliance reviewers can reject AI findings")

        if status_value == "dismissed" and not roles.intersection({"compliance"}):
            log_permission_error(
                ValueError("User lacks permission to dismiss findings"),
                "dismiss_finding",
                requiredRole="compliance",
                userId=user_id
            )
            logger.warning(f"[FINDINGS] User {user_id} attempted to dismiss finding without required role")
            raise HTTPException(status_code=403, detail="Only compliance reviewers can dismiss AI findings")

        if status_value == "pending" and not roles.intersection({"compliance"}):
            log_permission_error(
                ValueError("User lacks permission to reset findings"),
                "reset_finding",
                requiredRole="compliance",
                userId=user_id
            )
            logger.warning(f"[FINDINGS] User {user_id} attempted to reset finding without required role")
            raise HTTPException(status_code=403, detail="Only compliance reviewers can reset finding status")

        # Get finding details before update (scoped to tenant)
        try:
            finding_row = await _fetch_finding_in_tenant_org(db, finding_id, tenant_ctx["organization_id"])
            review_id = str(finding_row["review_id"])
        except HTTPException:
            raise
        except Exception as e:
            log_db_error(e, "fetch_finding_details", context={"finding_id": finding_id}, user_id=user_id)
            raise HTTPException(status_code=500, detail="Failed to fetch finding details")

        # Check if user is assigned/claimed (for SME and compliance users)
        await _require_assigned_or_claimed_for_findings(
            db, review_id, user_id, roles, tenant_ctx.get("role_in_org")
        )

        suggestion_id_value = (payload.suggestion_id or "").strip() or None
        if suggestion_id_value and status_value != "accepted":
            raise HTTPException(
                status_code=400,
                detail="suggestion_id is only allowed when status is 'accepted'",
            )
        if suggestion_id_value:
            suggestion_ok = await db.fetchval(
                """
                SELECT 1 FROM finding_suggestions
                WHERE id = $1::uuid AND finding_id = $2::uuid
                LIMIT 1
                """,
                suggestion_id_value,
                finding_id,
            )
            if not suggestion_ok:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid suggestion_id for this finding",
                )
        
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        terminal_statuses = {"accepted", "rejected", "dismissed"}
        resolved_by = user_id if status_value in terminal_statuses else None
        resolved_at = now if status_value in terminal_statuses else None
        accepted_suggestion_id = suggestion_id_value if status_value == "accepted" else None
        finding_title = finding_row["title"]
        finding_code = finding_row.get("finding_code")

        dismissal_reason = payload.reason if status_value == "dismissed" else None
        reject_reason = payload.reason if status_value == "rejected" else None

        try:
            row = await db.fetchrow(
                """
                UPDATE ai_findings
                SET status=$1, resolved_by=$2, resolved_at=$3, accepted_suggestion_id=$4, dismissal_reason=$5, reject_reason=$6
                WHERE id=$7 AND status = 'pending'
                RETURNING *
                """,
                status_value,
                resolved_by,
                resolved_at,
                accepted_suggestion_id,
                dismissal_reason,
                reject_reason,
                finding_id,
            )
            if not row:
                # Either finding doesn't exist, or it's already in a terminal state.
                # Fetch current row to distinguish the two cases.
                existing = await db.fetchrow(
                    "SELECT id, status FROM ai_findings WHERE id=$1",
                    finding_id,
                )
                if not existing:
                    logger.error(f"[FINDINGS] Finding {finding_id} not found")
                    raise HTTPException(status_code=404, detail="Finding not found")
                logger.info(
                    f"[FINDINGS] Finding {finding_id} already resolved (status={existing['status']}), skipping duplicate update"
                )
                # Return the existing row without creating a duplicate audit event
                return dict(existing)
            
            logger.info(f"[FINDINGS] Finding status updated successfully. Finding: {finding_id}, Status: {status_value}")
        except HTTPException:
            raise
        except Exception as e:
            log_db_error(
                e,
                "update_finding_status_db",
                context={"finding_id": finding_id, "new_status": status_value},
                user_id=user_id
            )
            logger.error(f"[FINDINGS] Error updating finding status: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to update finding status")
        
        # Log audit event for finding acceptance/rejection/dismissal
        if status_value in terminal_statuses:
            try:
                # Get user role
                role_row = await db.fetchrow(
                    "SELECT string_agg(r.name, ', ' ORDER BY r.name) as names FROM user_roles ur JOIN roles r ON ur.role_id = r.id WHERE ur.user_id = $1",
                    user_id,
                )
                user_role = role_row["names"] if role_row and role_row["names"] else "unknown"
                
                if status_value == "accepted":
                    # Local accept: a specific suggestion was chosen
                    if accepted_suggestion_id:
                        event_type = "finding_accepted_local"
                        # Determine accepted_type: look up whether it's an AI or user suggestion
                        sugg_row = await db.fetchrow(
                            "SELECT type FROM finding_suggestions WHERE id=$1::uuid",
                            str(accepted_suggestion_id),
                        )
                        accepted_type = "marketing_suggestion" if sugg_row and sugg_row["type"] == "user" else "ai_suggestion"
                        description = f"AI finding '{finding_title}' accepted with {accepted_type.replace('_', ' ')}"
                    else:
                        # Global accept: no specific suggestion chosen
                        event_type = "finding_accepted_global"
                        accepted_type = None
                        description = f"AI finding '{finding_title}' accepted (global)"
                elif status_value == "dismissed":
                    event_type = "finding_dismissed"
                    accepted_type = None
                    description = f"AI finding '{finding_title}' dismissed"
                else:
                    # Reject is always global (no local reject action exists)
                    event_type = "finding_rejected_global"
                    accepted_type = None
                    description = f"AI finding '{finding_title}' rejected (global)"

                details_payload = {
                    "finding_id": finding_id,
                    "finding_code": finding_code,
                    "finding_title": finding_title,
                    "status": status_value,
                }
                if accepted_suggestion_id:
                    details_payload["suggestion_id"] = str(accepted_suggestion_id)
                if accepted_type:
                    details_payload["accepted_type"] = accepted_type
                if dismissal_reason:
                    details_payload["dismissal_reason"] = dismissal_reason
                if reject_reason:
                    details_payload["reject_reason"] = reject_reason
                details = json.dumps(details_payload)
                
                await log_audit_event(
                    db,
                    review_id=review_id,
                    event_type=event_type,
                    description=description,
                    user_id=user_id,
                    user_role=user_role,
                    details=details,
                )
                logger.debug(f"[FINDINGS] Audit event logged for finding {finding_id} status change: {event_type}")
            except Exception as e:
                log_db_error(
                    e,
                    "log_finding_audit_event",
                    context={"finding_id": finding_id, "event_type": "finding_status_change"},
                    user_id=user_id
                )
                logger.error(f"[FINDINGS] Failed to log audit event for finding {finding_id}: {str(e)}")
        try:
            await publish_review_comment(
                review_id,
                {
                    "event": "finding_status_updated",
                    "finding_id": finding_id,
                },
            )
        except Exception:
            logger.exception("Failed to publish finding status update")
        
        return dict(row)
    
    except HTTPException:
        raise
    except Exception as e:
        log_error(
            e,
            ErrorCategory.AI_SERVICE,
            "update_finding_status",
            ErrorSeverity.ERROR,
            context={"finding_id": finding_id, "status": payload.status},
            user_id=user_id
        )
        logger.error(f"[FINDINGS] Unexpected error updating finding status: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update finding status")


@router.post("/{finding_id}/comments", response_model=FindingComment)
async def add_finding_comment(
    finding_id: str,
    comment: FindingCommentCreate,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    user_id = (current_user or {}).get("id")
    roles = set((current_user or {}).get("roles") or [])
    
    logger.info(f"[FINDINGS] Adding comment to finding {finding_id}, user: {user_id}")
    
    try:
        _require_ai_access(roles, user_id)

        try:
            finding = await _fetch_finding_in_tenant_org(db, finding_id, tenant_ctx["organization_id"])
        except HTTPException:
            raise
        except Exception as e:
            log_db_error(e, "fetch_finding_for_comment", context={"finding_id": finding_id}, user_id=user_id)
            logger.error(f"[FINDINGS] Error fetching finding {finding_id}: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to fetch finding")

        review_id = str(finding["review_id"])

        # Check if user is assigned/claimed (for SME and compliance users)
        await _require_assigned_or_claimed_for_findings(
            db, review_id, user_id, roles, tenant_ctx.get("role_in_org")
        )

        comment_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

        role_row = await db.fetchrow(
            "SELECT string_agg(r.name, ', ' ORDER BY r.name) as names FROM user_roles ur JOIN roles r ON ur.role_id = r.id WHERE ur.user_id = $1",
            user_id,
        )
        role_name = role_row["names"] if role_row and role_row["names"] else "unknown"

        await db.execute(
            """
            INSERT INTO finding_comments (id, finding_id, author_id, role, content, created_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            comment_id,
            finding_id,
            user_id,
            role_name,
            comment.content,
            now,
        )

        # Log audit event for finding comment
        finding_title = finding["title"]
        finding_code = finding.get("finding_code")
        details = json.dumps({
            "finding_id": finding_id,
            "finding_code": finding_code,
            "finding_title": finding_title,
            "comment_id": comment_id,
            "comment_content": comment.content
        })
        await log_audit_event(
            db,
            review_id=review_id,
            event_type="finding_comment_added",
            description=f"Comment added on AI finding '{finding_title}'",
            user_id=user_id,
            user_role=role_name,
            details=details,
        )

        row = await db.fetchrow("SELECT * FROM finding_comments WHERE id=$1", comment_id)
        
        try:
            doc_row = await db.fetchrow(
                """
                SELECT d.id AS doc_id, d.name AS document_name, d.submitted_by,
                       w.assigned_to, w.assigned_role, w.current_stage
                FROM content_reviews cr
                JOIN document_versions dv ON cr.document_version_id = dv.id
                JOIN documents d ON dv.document_id = d.id
                LEFT JOIN workflows w ON w.review_id = cr.id
                WHERE cr.id = $1
                """,
                review_id,
            )
            if doc_row:
                doc_id = str(doc_row["doc_id"])
                doc_name = doc_row["document_name"] or "Document"
                submitted_by = str(doc_row["submitted_by"]) if doc_row["submitted_by"] else None
                assigned_to = str(doc_row["assigned_to"]) if doc_row["assigned_to"] else None
                org_id = tenant_ctx["organization_id"]
                org_slug = tenant_ctx.get("organization_slug")

                recipient_ids = []
                if "compliance" in role_name.lower():
                    if submitted_by:
                        recipient_ids.append(submitted_by)
                else:
                    if assigned_to:
                        recipient_ids.append(assigned_to)
                    else:
                        recip_rows = await db.fetch(
                            """
                            SELECT DISTINCT up.id
                            FROM user_profiles up
                            JOIN organization_users ou ON ou.user_id = up.id AND ou.organization_id = $2::uuid
                            JOIN user_roles ur ON ur.user_id = up.id
                            JOIN roles r ON r.id = ur.role_id
                            WHERE up.is_active = TRUE
                              AND lower(r.name) = $1
                            """,
                            "compliance",
                            org_id,
                        )
                        recipient_ids.extend([str(r["id"]) for r in recip_rows])
                
                recipient_ids = [uid for uid in set(recipient_ids) if uid != user_id]

                if recipient_ids:
                    recipients_info_rows = await db.fetch(
                        "SELECT id, email, full_name FROM user_profiles WHERE id = ANY($1::uuid[])",
                        recipient_ids,
                    )
                    
                    author_profile = await db.fetchrow("SELECT full_name, email FROM user_profiles WHERE id=$1", user_id)
                    author_name = "Someone"
                    if author_profile:
                        author_name = (author_profile.get("full_name") or author_profile.get("email") or "").strip() or "Someone"

                    recipients_info = []
                    for rec_row in recipients_info_rows:
                        uid = str(rec_row["id"])
                        email = (rec_row.get("email") or "").strip()
                        name = (rec_row.get("full_name") or "").strip() or (email.split("@")[0] if email else "Reviewer")

                        notif_id = str(uuid.uuid4())
                        notif_title = "New Feedback Message"
                        notif_message = f"{author_name} added a message to '{finding_title}'"

                        await db.execute(
                            """
                            INSERT INTO notifications (id, user_id, type, title, message, reference_type, reference_id, is_read, created_at)
                            VALUES ($1, $2, $3, $4, $5, $6, $7::uuid, $8, $9)
                            """,
                            notif_id, uid, "finding_comment_added", notif_title, notif_message, "document", uuid.UUID(doc_id), False, now
                        )
                        recipients_info.append({
                            "id": uid,
                            "email": email,
                            "name": name,
                            "notif_id": notif_id,
                            "notif_title": notif_title,
                            "notif_message": notif_message,
                            "created_at": now.isoformat()
                        })

                    background_tasks.add_task(
                        _dispatch_finding_comment_notifications,
                        recipients_info,
                        finding_id,
                        finding_title,
                        author_name,
                        comment.content,
                        doc_id,
                        doc_name,
                        org_slug
                    )
        except Exception as notify_err:
            logger.error(f"[FINDINGS] Failed to send feedback notifications: {str(notify_err)}")
        
        try:
            await publish_review_comment(
                review_id,
                {
                    "event": "finding_comment_added",
                    "finding_id": finding_id,
                    "comment": dict(row),
                },
            )
        except Exception:
            logger.exception("Failed to publish finding comment real-time update")

        return FindingComment(**dict(row))
    except HTTPException:
        raise
    except Exception as e:
        log_error(e, "finding_comment_error", "add_finding_comment", context={"finding_id": finding_id}, user_id=user_id)
        logger.error(f"[FINDINGS] Error adding comment to finding: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to add comment")


@router.post("/{finding_id}/suggestions", response_model=FindingSuggestion)
async def add_finding_suggestion(
    finding_id: str,
    suggestion: FindingSuggestionCreate,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    roles = set((current_user or {}).get("roles") or [])
    _require_ai_access(roles)

    finding = await _fetch_finding_in_tenant_org(db, finding_id, tenant_ctx["organization_id"])

    user_id = (current_user or {}).get("id")
    review_id = str(finding["review_id"])

    # Check if user is assigned/claimed (for SME and compliance users)
    await _require_assigned_or_claimed_for_findings(
        db, review_id, user_id, roles, tenant_ctx.get("role_in_org")
    )

    suggestion_id = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    role_row = await db.fetchrow(
        "SELECT string_agg(r.name, ', ' ORDER BY r.name) as names FROM user_roles ur JOIN roles r ON ur.role_id = r.id WHERE ur.user_id = $1",
        user_id,
    )
    role_name = role_row["names"] if role_row and role_row["names"] else "unknown"

    await db.execute(
        """
        INSERT INTO finding_suggestions (id, finding_id, text, type, created_by, created_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        suggestion_id,
        finding_id,
        suggestion.text,
        "user",
        user_id,
        now,
    )

    # Log audit event for finding suggestion
    finding_title = finding["title"]
    finding_code = finding.get("finding_code")
    details = json.dumps({
        "finding_id": finding_id,
        "finding_code": finding_code,
        "finding_title": finding_title,
        "suggestion_id": suggestion_id,
        "suggestion_text": suggestion.text
    })
    await log_audit_event(
        db,
        review_id=review_id,
        event_type="finding_suggestion_added",
        description=f"Added alternate suggestion for AI finding '{finding_title}'",
        user_id=user_id,
        user_role=role_name,
        details=details,
    )

    row = await db.fetchrow("SELECT * FROM finding_suggestions WHERE id=$1", suggestion_id)

    try:
        await publish_review_comment(
            review_id,
            {
                "event": "finding_suggestion_added",
                "finding_id": finding_id,
            },
        )
    except Exception:
        logger.exception("Failed to publish finding suggestion real-time update")

    return FindingSuggestion(**dict(row))


@router.put("/{finding_id}/suggestions/{suggestion_id}", response_model=FindingSuggestion)
async def edit_finding_suggestion(
    finding_id: str,
    suggestion_id: str,
    payload: FindingSuggestionUpdate,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    """Edit an existing marketing suggestion text and log the change in the audit trail."""
    roles = set((current_user or {}).get("roles") or [])
    _require_ai_access(roles)

    finding = await _fetch_finding_in_tenant_org(db, finding_id, tenant_ctx["organization_id"])
    user_id = (current_user or {}).get("id")
    review_id = str(finding["review_id"])

    # Check if user is assigned/claimed
    await _require_assigned_or_claimed_for_findings(
        db, review_id, user_id, roles, tenant_ctx.get("role_in_org")
    )

    # Fetch existing suggestion (must belong to this finding)
    existing = await db.fetchrow(
        "SELECT * FROM finding_suggestions WHERE id=$1::uuid AND finding_id=$2::uuid",
        suggestion_id,
        finding_id,
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Suggestion not found for this finding")

    old_text = existing["text"]
    new_text = payload.text.strip()

    if not new_text:
        raise HTTPException(status_code=400, detail="Suggestion text cannot be empty")

    # Update the suggestion text
    row = await db.fetchrow(
        "UPDATE finding_suggestions SET text=$1 WHERE id=$2::uuid RETURNING *",
        new_text,
        suggestion_id,
    )
    if not row:
        raise HTTPException(status_code=500, detail="Failed to update suggestion")

    # Log audit event
    role_row = await db.fetchrow(
        "SELECT string_agg(r.name, ', ' ORDER BY r.name) as names FROM user_roles ur JOIN roles r ON ur.role_id = r.id WHERE ur.user_id = $1",
        user_id,
    )
    role_name = role_row["names"] if role_row and role_row["names"] else "unknown"

    finding_title = finding["title"]
    finding_code = finding.get("finding_code")
    details = json.dumps({
        "finding_id": finding_id,
        "finding_code": finding_code,
        "finding_title": finding_title,
        "suggestion_id": suggestion_id,
        "old_text": old_text,
        "new_text": new_text,
    })
    await log_audit_event(
        db,
        review_id=review_id,
        event_type="finding_suggestion_edited",
        description=f"Edited alternate suggestion for AI finding '{finding_title}'",
        user_id=user_id,
        user_role=role_name,
        details=details,
    )
    logger.info(f"[FINDINGS] Suggestion {suggestion_id} edited for finding {finding_id} by user {user_id}")

    try:
        await publish_review_comment(
            review_id,
            {
                "event": "finding_suggestion_edited",
                "finding_id": finding_id,
            },
        )
    except Exception:
        logger.exception("Failed to publish finding suggestion edit real-time update")

    return FindingSuggestion(**dict(row))


@router.get("/{finding_id}/comments", response_model=List[FindingComment])
async def list_finding_comments(
    finding_id: str,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    roles = set((current_user or {}).get("roles") or [])
    _require_ai_access(roles)
    await _fetch_finding_in_tenant_org(db, finding_id, tenant_ctx["organization_id"])

    rows = await db.fetch(
        """
        SELECT 
            fc.*,
            up.full_name as author_name
        FROM finding_comments fc
        LEFT JOIN user_profiles up ON fc.author_id = up.id
        WHERE fc.finding_id=$1 
        ORDER BY fc.created_at ASC
        """,
        finding_id
    )
    return [FindingComment(**dict(row)) for row in rows]


@router.get("/{finding_id}/suggestions", response_model=List[FindingSuggestion])
async def list_finding_suggestions(
    finding_id: str,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    roles = set((current_user or {}).get("roles") or [])
    _require_ai_access(roles)
    await _fetch_finding_in_tenant_org(db, finding_id, tenant_ctx["organization_id"])

    rows = await db.fetch("SELECT * FROM finding_suggestions WHERE finding_id=$1 ORDER BY created_at DESC", finding_id)
    return [FindingSuggestion(**dict(row)) for row in rows]


# Feedback Route on reviews
reviews_feedback_router = APIRouter(prefix="/reviews", tags=["reviews-feedback"])


@reviews_feedback_router.post("/{review_id}/feedback", response_model=AIFeedback)
async def submit_ai_feedback(
    review_id: str,
    feedback: AIFeedbackCreate,
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    roles = set((current_user or {}).get("roles") or [])
    _require_ai_access(roles)

    user_id = (current_user or {}).get("id")
    feedback_id = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    await _assert_review_in_tenant_org(db, review_id, tenant_ctx["organization_id"])
    review = await db.fetchrow("SELECT id FROM content_reviews WHERE id=$1", review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    await db.execute(
        """
        INSERT INTO ai_feedback (id, review_id, user_id, is_liked, feedback_text, submitted_at, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $6)
        """,
        feedback_id,
        review_id,
        user_id,
        feedback.is_liked,
        feedback.feedback_text,
        now,
    )

    row = await db.fetchrow("SELECT * FROM ai_feedback WHERE id=$1", feedback_id)
    return AIFeedback(**dict(row))