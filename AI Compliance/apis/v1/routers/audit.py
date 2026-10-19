import uuid
import json
import re
from pathlib import PurePosixPath
from typing import List, Optional, Any, Dict
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException, Depends, Query

from apis.core.database import get_db
from apis.core.dashboard_period import resolve_dashboard_period
from apis.core.encrypted_fields import decode_extracted_text
from apis.core.security import require_app_access_ready, require_tenant_context
from apis.core.tenant_resources import assert_review_in_organization
from apis.schemas.dashboard_stat_cards import DashboardStatCardsResponse
from apis.services.dashboard_stat_cards import (
    build_compliance_stat_cards,
    build_marketing_stat_cards,
    build_sme_stat_cards,
    build_superadmin_stat_cards,
)
from apis.services.dashboard_stat_card_series import attach_series_to_response
from apis.services.stat_cards_role_metrics import (
    count_active_users_in_org,
    count_marketing_pending_submissions,
    count_org_documents,
    count_sme_review_queue,
    fetch_compliance_analytics,
    fetch_marketing_submitter_analytics,
    fetch_superadmin_analytics,
)
from apis.services.tenant_dashboard_aggregates import fetch_tenant_dashboard_aggregates


def _ensure_name_has_extension(name: Optional[str], s3_key: Optional[str]) -> str:
    """If `name` lacks a file extension, derive it from the S3 key."""
    if not name:
        return "Untitled Document"
    if "." in name:
        return name
    if s3_key:
        ext = PurePosixPath(s3_key).suffix.lower()
        if ext:
            return f"{name}{ext}"
    return name

router = APIRouter(prefix="/reviews", tags=["audit"])
global_audit_router = APIRouter(prefix="/audit-trail", tags=["audit"])


def _standardize_stage_name(stage: Optional[str]) -> str:
    """Convert internal stage names to standardized display names."""
    if not stage:
        return ""
    
    stage_lower = stage.lower()
    stage_mapping = {
        "document_upload": "Document Upload",
        "sme_review": "SME Review",
        "marketing_review": "Marketing Review",
        "compliance_review": "Compliance Review",
        "approved": "Approved",
        "published": "Published",
        "rejected": "Rejected",
        "needs_revision": "Needs Revision",
    }
    
    return stage_mapping.get(stage_lower, stage.replace("_", " ").title())


async def _generate_event_code(db) -> str:
    """Generate a sequential event code like AE-001 using a DB sequence.

    Uses audit_event_code_seq (created by migration 007) which is inherently
    atomic and non-blocking — no advisory lock required.
    """
    next_num = await db.fetchval("SELECT nextval('audit_event_code_seq')")
    return f"AE-{next_num:03d}"


async def log_audit_event(
    db,
    *,
    review_id: str,
    event_type: str,
    description: str,
    user_id: Optional[str] = None,
    user_role: Optional[str] = None,
    workflow_stage: Optional[str] = None,
    details: Optional[str] = None,
    is_ai: bool = False,
    triggered_by_user_id: Optional[str] = None,
) -> str:
    """Log an audit event and return the event ID"""
    event_id = str(uuid.uuid4())
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    
    # Get current workflow stage if not provided
    if not workflow_stage:
        w_row = await db.fetchrow("SELECT current_stage FROM workflows WHERE review_id=$1", review_id)
        if w_row:
            workflow_stage = w_row["current_stage"]
    
    # nextval() is atomic — no advisory lock needed.
    # Each call returns a unique integer without blocking concurrent callers.
    event_code = await _generate_event_code(db)

    await db.execute(
        """
        INSERT INTO audit_events (
            id, event_code, review_id, workflow_stage, event_type, description,
            user_id, user_role, is_ai, details, triggered_by_user_id, created_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        """,
        event_id,
        event_code,
        review_id,
        workflow_stage,
        event_type,
        description,
        user_id,
        user_role,
        is_ai,
        details,
        triggered_by_user_id,
        now_utc,
    )
    return event_id

@global_audit_router.get("")
async def get_global_audit_trail(
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    """Fetch document reviews for the current organization as high-level audit events."""
    organization_id = tenant_ctx["organization_id"]
    user_id = (current_user or {}).get("id")
    roles = set((current_user or {}).get("roles") or [])
    roles_lower = {
        r.lower().strip() if isinstance(r, str) else str(r).lower().strip()
        for r in roles
    }
    is_super_admin = "super_admin" in roles_lower

    query = """
        SELECT 
            cr.id as review_id,
            d.id as document_id,
            d.name as document_name,
            dv.s3_key as version_s3_key,
            d.document_code,
            COALESCE(w.current_stage, dv.status) as workflow_stage,
            w.assigned_role,
            u.full_name as performed_by,
            u.department as performed_by_department,
            (
                SELECT STRING_AGG(r_role.name, ',')
                FROM user_roles ur_role
                JOIN roles r_role ON ur_role.role_id = r_role.id
                WHERE ur_role.user_id = u.id
            ) as performed_by_roles,
            cr.created_at,
            dv.version_label,
            dv.uploaded_at,
            GREATEST(cr.updated_at, w.updated_at, dv.uploaded_at) AS latest_activity,
            COALESCE(vagg.version_list, dv.version_label) AS version_list,
            COALESCE(vagg.version_count, 1) AS version_count,
            COALESCE(vagg.latest_version_label, dv.version_label) AS latest_version_label
        FROM content_reviews cr
        LEFT JOIN workflows w ON w.review_id = cr.id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        JOIN documents d ON dv.document_id = d.id
        LEFT JOIN LATERAL (
            SELECT
                STRING_AGG(dv_all.version_label, ', ' ORDER BY dv_all.uploaded_at DESC) AS version_list,
                COUNT(*)::int AS version_count,
                (ARRAY_AGG(dv_all.version_label ORDER BY dv_all.uploaded_at DESC))[1] AS latest_version_label
            FROM document_versions dv_all
            WHERE dv_all.document_id = d.id
        ) vagg ON TRUE
        LEFT JOIN user_profiles u ON d.submitted_by = u.id
        WHERE cr.document_version_id = d.current_version_id
          AND d.organization_id = $1::uuid
          AND (dv.status IS NULL OR dv.status != 'failed')
    """
    params: list[Any] = [organization_id]
    if not is_super_admin:
        if not user_id:
            return []
        query += """
          AND (
              w.assigned_to = $2
              OR dv.status = 'skipped'
              OR EXISTS (
                  SELECT 1
                  FROM workflow_steps ws_hist
                  WHERE ws_hist.workflow_id = w.id
                    AND (
                        ws_hist.claimed_by = $2
                        OR ws_hist.completed_by = $2
                    )
              )
              OR EXISTS (
                  SELECT 1 FROM comment_mentions cm
                  JOIN content_comments cc ON cc.id = cm.comment_id
                  JOIN content_reviews cr_ment ON cr_ment.id = cc.review_id
                  JOIN document_versions dv_ment ON cr_ment.document_version_id = dv_ment.id
                  WHERE dv_ment.document_id = d.id
                    AND cm.mentioned_user_id = $2::uuid
              )
          )
        """
        params.append(user_id)

    query += "\nORDER BY dv.uploaded_at DESC"

    rows = await db.fetch(query, *params)
    
    audit_data = []
    for idx, r in enumerate(rows):
        # Format step using document_code if available, otherwise use sequential number
        doc_code = r.get("document_code") or ""
        if doc_code and doc_code.startswith("DOC-"):
            step = doc_code.replace("DOC-", "")
        elif doc_code:
            step = doc_code
        else:
            # Fallback to sequential number
            step = str(idx + 1).zfill(3)
        
        stage = r["workflow_stage"] or "skipped"
        action_text = "Out of Scope" if stage == "skipped" else f"Currently in {stage}"
        
        audit_data.append({
            "step": step,
            "reviewId": str(r["review_id"]),
            "documentId": str(r["document_id"]),
            "document": _ensure_name_has_extension(r["document_name"], r.get("version_s3_key")),
            "workflowStage": stage,
            "status": stage,
            "riskLevel": "Low", # Can be calculated based on findings
            "action": action_text,
            "performedBy": r["performed_by"] or "System",
            "department": r["performed_by_department"] or "",
            "roles": [x.strip() for x in (r["performed_by_roles"] or "").split(",") if x.strip()] if r["performed_by_roles"] else [],
            "versions": r.get("version_list") or r.get("version_label") or "",
            "latestVersion": r.get("latest_version_label") or r.get("version_label") or "",
            "versionCount": int(r.get("version_count") or 1),
            "notes": "",
            "timestamp": r["uploaded_at"].isoformat() if r.get("uploaded_at") else (r["created_at"].isoformat() if r.get("created_at") else None)
        })
    return audit_data


@router.get("/{review_id}/versions")
async def get_review_versions(
    review_id: str,
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    """
    Return all document versions for the document linked to a content review.
    Sorted newest first, with text payload for version compare in frontend.
    """
    await assert_review_in_organization(db, review_id, tenant_ctx["organization_id"])
    review_row = await db.fetchrow(
        """
        SELECT dv.document_id
        FROM content_reviews cr
        JOIN document_versions dv ON cr.document_version_id = dv.id
        WHERE cr.id = $1
        """,
        review_id,
    )
    if not review_row or not review_row.get("document_id"):
        raise HTTPException(status_code=404, detail="Review or document not found")

    rows = await db.fetch(
        """
        SELECT
            dv.id,
            dv.version_label,
            dv.uploaded_at,
            dv.status,
            dv.change_summary,
            dv.extracted_text,
            cr.id AS review_id
        FROM document_versions dv
        LEFT JOIN content_reviews cr ON cr.document_version_id = dv.id
        WHERE dv.document_id = $1
        ORDER BY dv.uploaded_at DESC, dv.version_label DESC
        """,
        review_row["document_id"],
    )

    versions = []
    for r in rows:
        text = decode_extracted_text(r.get("extracted_text")) or ""
        # If it looks like HTML, clean it up for the frontend comparison view
        if text.strip().startswith("<") and ("</" in text or "/>" in text):
            try:
                soup = BeautifulSoup(text, "html.parser")
                # Using separator="\n" to preserve basic paragraph structure
                text = soup.get_text(separator="\n").strip()
                # Clean up excessive newlines
                text = re.sub(r'\n{3,}', '\n\n', text)
            except Exception:
                # Fallback to raw text if parsing fails
                pass

        versions.append({
            "id": str(r["id"]),
            "label": r.get("version_label") or "",
            "uploadedAt": r["uploaded_at"].isoformat() if r.get("uploaded_at") else None,
            "status": r.get("status") or "",
            "changeSummary": r.get("change_summary") or "",
            "text": text,
            "reviewId": str(r["review_id"]) if r.get("review_id") else None,
        })
    return {"reviewId": review_id, "versions": versions}


@global_audit_router.get("/dashboard-stats")
async def get_dashboard_stats(
    period: str = Query("month", description="Trend window: week | month | ytd | custom"),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD when period=custom"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD when period=custom"),
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    """
    Aggregate counts for dashboard StatCards (documents, social, findings).

    Snapshot fields are not filtered by period. ``trends`` compare activity in the
    selected window vs an equal-length comparison window immediately before it
    (for ytd: same elapsed window in the prior calendar year).
    """
    organization_id = tenant_ctx["organization_id"]
    _ = current_user  # auth + tenant membership
    resolved = resolve_dashboard_period(period, date_from, date_to)
    agg = await fetch_tenant_dashboard_aggregates(db, organization_id, resolved)
    t = agg["trends"]
    return {
        "highRiskFlags": agg["high_risk_flags"],
        "linkedinPostsMonitored": agg["linkedin_posts_monitored_total"],
        "documentsUnderReview": agg["documents_under_review"],
        "pendingActions": agg["pending_document_findings"],
        "trends": {
            "linkedinPostsMonitored": t["linkedin_posts_monitored"],
            "documentsUnderReview": t["documents_under_review"],
            "pendingActions": t["pending_document_findings"],
            "highRiskFlags": t["high_risk_flags"],
        },
    }


@global_audit_router.get("/stat-cards", response_model=DashboardStatCardsResponse)
async def get_dashboard_stat_cards(
    role: str = Query(
        "compliance",
        description="Dashboard persona: compliance | marketing | sme | superadmin",
    ),
    period: str = Query("month", description="Trend window: week | month | ytd | custom"),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD when period=custom"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD when period=custom"),
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    """
    Structured stat tiles for the ComplyCore-style dashboard.

    Roles: ``compliance`` (org aggregates), ``marketing`` (my submissions + 30d report stats),
    ``sme`` (SME-stage queue), ``superadmin`` (org-wide totals; requires org super_admin).
    """
    organization_id = tenant_ctx["organization_id"]
    user_id = str(current_user.get("id") or "")
    roles = list(current_user.get("roles") or [])
    roles_lower = {r.lower() for r in roles}
    is_org_super_admin = (tenant_ctx.get("role_in_org") or "").strip().lower() == "super_admin" or "super_admin" in roles_lower

    resolved = resolve_dashboard_period(period, date_from, date_to)
    role_key = (role or "").strip().lower()

    if role_key == "superadmin" and not is_org_super_admin:
        raise HTTPException(
            status_code=403,
            detail="Stat cards for role=superadmin require organization super_admin.",
        )

    if role_key == "compliance":
        agg = await fetch_tenant_dashboard_aggregates(db, organization_id, resolved)
        compliance_metrics = await fetch_compliance_analytics(db, organization_id, resolved)
        response = build_compliance_stat_cards(agg, compliance_metrics, period=resolved.key)
        return await attach_series_to_response(
            db, response=response, resolved=resolved,
            organization_id=organization_id, user_id=user_id,
            roles=roles, is_org_super_admin=is_org_super_admin,
        )

    if role_key == "marketing":
        pending = await count_marketing_pending_submissions(db, organization_id, user_id, roles)
        submitter_metrics = await fetch_marketing_submitter_analytics(db, organization_id, user_id)
        response = build_marketing_stat_cards(
            pending,
            submitter_metrics,
            period=resolved.key,
        )
        return await attach_series_to_response(
            db, response=response, resolved=resolved,
            organization_id=organization_id, user_id=user_id,
            roles=roles, is_org_super_admin=is_org_super_admin,
        )

    if role_key == "sme":
        queue_n = await count_sme_review_queue(
            db,
            organization_id,
            user_id,
            roles,
            is_org_super_admin,
        )
        response = build_sme_stat_cards(queue_n, period=resolved.key)
        return await attach_series_to_response(
            db, response=response, resolved=resolved,
            organization_id=organization_id, user_id=user_id,
            roles=roles, is_org_super_admin=is_org_super_admin,
        )

    if role_key == "superadmin":
        agg = await fetch_tenant_dashboard_aggregates(db, organization_id, resolved)
        total_docs = await count_org_documents(db, organization_id)
        active_u = await count_active_users_in_org(db, organization_id)
        superadmin_metrics = await fetch_superadmin_analytics(db, organization_id)
        response = build_superadmin_stat_cards(
            agg,
            total_documents=total_docs,
            active_users_30d=active_u,
            superadmin_metrics=superadmin_metrics,
            period=resolved.key,
        )
        return await attach_series_to_response(
            db, response=response, resolved=resolved,
            organization_id=organization_id, user_id=user_id,
            roles=roles, is_org_super_admin=is_org_super_admin,
        )

    raise HTTPException(
        status_code=400,
        detail="Invalid role. Use compliance, marketing, sme, or superadmin.",
    )


@global_audit_router.get("/review-status-stats")
async def get_review_status_stats(
    period: str = Query("all"),
    date_from: Optional[str] = Query(None, description="ISO date YYYY-MM-DD (required when period=custom)"),
    date_to: Optional[str] = Query(None, description="ISO date YYYY-MM-DD (required when period=custom)"),
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    """
    Per-document counts for the dashboard "Review Status" chart.

    Each document is counted exactly once using its current version's latest
    content_review + workflow (same basis as the document list). Buckets are
    mutually exclusive; totalDocuments is COUNT(documents).

    period: all | week | month | ytd | custom
    For period=custom, date_from and date_to are required (inclusive on calendar dates).
    """
    organization_id = tenant_ctx["organization_id"]
    _ = current_user
    period_key = (period or "all").strip().lower()
    date_cond = "TRUE"
    query_params: list[Any] = [organization_id]

    if period_key == "month":
        date_cond = "d.created_at >= NOW() - INTERVAL '30 days'"
    elif period_key == "week":
        date_cond = "d.created_at >= NOW() - INTERVAL '7 days'"
    elif period_key == "ytd":
        date_cond = "d.created_at >= date_trunc('year', NOW()::timestamp)"
    elif period_key == "custom":
        if not (date_from and date_to):
            raise HTTPException(
                status_code=400,
                detail="date_from and date_to are required when period=custom (format YYYY-MM-DD).",
            )
        try:
            df = datetime.strptime(date_from.strip(), "%Y-%m-%d").date()
            dt = datetime.strptime(date_to.strip(), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from or date_to; use YYYY-MM-DD.")
        if df > dt:
            raise HTTPException(status_code=400, detail="date_from must be on or before date_to.")
        if (dt - df).days > 366 * 5:
            raise HTTPException(status_code=400, detail="Custom date range cannot exceed 5 years.")
        date_cond = "d.created_at::date >= $2::date AND d.created_at::date <= $3::date"
        query_params.extend([df, dt])
    elif period_key not in ("all", ""):
        raise HTTPException(
            status_code=400,
            detail="Invalid period. Use all, week, month, ytd, or custom.",
        )

    query = f"""
        WITH dw AS (
          SELECT
            d.id,
            cr.review_status AS rs,
              CASE WHEN COALESCE(w.current_stage, '') = 'sme_approved' THEN 'marketing_review'
                   WHEN COALESCE(w.current_stage, '') = 'compliance_approved' THEN 'approved'
                   ELSE w.current_stage
              END AS st
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
          WHERE d.organization_id = $1::uuid
            AND v.status <> 'skipped'
            AND (
              COALESCE(w.current_stage, '') <> 'published'
              OR ({date_cond})
            )
        ),
        bucketed AS (
          SELECT
            id,
            CASE
              WHEN rs = 'rejected' OR st = 'rejected' THEN 'rejected'
              WHEN st = 'published' THEN 'published'
              WHEN st = 'compliance_review' THEN 'compliance_review'
              WHEN st = 'marketing_review' THEN 'marketing_review'
              WHEN st = 'sme_review' THEN 'sme_review'
              WHEN rs = 'approved' OR st = 'approved' THEN 'approved'
              ELSE 'not_started'
            END AS bucket
          FROM dw
        )
        SELECT
          (SELECT COUNT(*) FROM dw)::int AS total_documents,
          COUNT(*) FILTER (WHERE bucket = 'rejected')::int AS rejected,
          COUNT(*) FILTER (WHERE bucket = 'published')::int AS published,
          COUNT(*) FILTER (WHERE bucket = 'compliance_review')::int AS compliance_review,
          COUNT(*) FILTER (WHERE bucket = 'marketing_review')::int AS marketing_review,
          COUNT(*) FILTER (WHERE bucket = 'sme_review')::int AS sme_review,
          COUNT(*) FILTER (WHERE bucket = 'approved')::int AS approved,
          COUNT(*) FILTER (WHERE bucket = 'not_started')::int AS not_started
        FROM bucketed
    """
    if query_params:
        row = await db.fetchrow(query, *query_params)
    else:
        row = await db.fetchrow(query)

    return {
        "totalDocuments": row["total_documents"],
        "marketingReview": row["marketing_review"],
        "complianceReview": row["compliance_review"],
        "pendingSmeReview": row["sme_review"],
        "approved": row["approved"],
        "rejected": row["rejected"],
        "published": row["published"],
        "notStarted": row["not_started"],
    }


def _content_display_name(
    *,
    document_name: Optional[str],
    social_preview: Optional[str],
    social_post_code: Optional[str],
    s3_key: Optional[str] = None,
) -> str:
    if document_name:
        return _ensure_name_has_extension(document_name, s3_key)
    if social_preview:
        text = social_preview.strip()
        return text if len(text) <= 80 else text[:77] + "..."
    if social_post_code:
        return social_post_code
    return "Content review"


@global_audit_router.get("/recent-activity")
async def get_recent_activity_feed(
    limit: int = Query(30, ge=1, le=100),
    current_user: dict = Depends(require_app_access_ready),
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    """Recent audit events and AI findings for the dashboard activity feed."""
    organization_id = tenant_ctx["organization_id"]
    _ = current_user
    # Rolling ~1 month window for the dashboard feed (calendar-agnostic; 30 days).
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff_utc = now_utc - timedelta(days=30)
    findings_query = """
        SELECT
            af.id AS finding_id,
            af.title AS finding_title,
            af.description AS finding_description,
            af.finding_code,
            af.risk_level,
            af.created_at,
            cr.id AS review_id,
            cr.content_type,
            d.id AS document_id,
            d.name AS document_name,
            d.document_code,
            NULL::uuid AS social_post_id,
            NULL::text AS social_post_code,
            NULL::text AS social_preview,
            r.name AS rule_name,
            dv.id AS version_id,
            dv.s3_key AS version_s3_key
        FROM ai_findings af
        JOIN content_reviews cr ON af.review_id = cr.id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        JOIN documents d ON dv.document_id = d.id
        JOIN compliance_rules r ON af.rule_id = r.id
        WHERE af.created_at >= $1
          AND dv.status != 'failed'
          AND d.organization_id = $2::uuid
        ORDER BY af.created_at DESC
        LIMIT 40
    """
    finding_rows = await db.fetch(findings_query, cutoff_utc, organization_id)

    findings_by_review_times: Dict[str, List[datetime]] = {}
    finding_items: List[Dict[str, Any]] = []
    for r in finding_rows:
        rid = str(r["review_id"])
        created = r["created_at"]
        if created:
            findings_by_review_times.setdefault(rid, []).append(created)
        doc_id = str(r["document_id"]) if r.get("document_id") else None
        sp_id = str(r["social_post_id"]) if r.get("social_post_id") else None
        label = _content_display_name(
            document_name=r.get("document_name"),
            social_preview=r.get("social_preview"),
            social_post_code=r.get("social_post_code"),
            s3_key=r.get("version_s3_key"),
        )
        finding_items.append(
            {
                "id": str(r["finding_id"]),
                "feedSource": "finding",
                "eventType": "ai_finding",
                "createdAt": created.isoformat() if created else "",
                "reviewId": rid,
                "contentType": r.get("content_type") or "",
                "documentId": doc_id,
                "socialPostId": sp_id,
                "contentLabel": label,
                "documentCode": r.get("document_code"),
                "description": None,
                "title": r.get("finding_title") or "",
                "detailText": r.get("finding_description") or "",
                "ruleCode": r.get("rule_code"),
                "ruleName": r.get("rule_name"),
                "findingCode": r.get("finding_code"),
                "riskLevel": (r.get("risk_level") or "").upper() or None,
                "userName": None,
                "userRole": None,
                "isAi": True,
                "workflowStage": r.get("workflow_stage"),
                "versionId": str(r["version_id"]) if r.get("version_id") else None,
            }
        )

    audit_query = """
        SELECT
            ae.id AS event_id,
            ae.event_type,
            ae.description,
            ae.details,
            ae.workflow_stage,
            ae.created_at,
            ae.is_ai,
            u.full_name AS user_name,
            ae.user_role,
            cr.id AS review_id,
            cr.content_type,
            d.id AS document_id,
            d.name AS document_name,
            d.document_code,
            NULL::uuid AS social_post_id,
            NULL::text AS social_preview,
            dv.id AS version_id,
            dv.s3_key AS version_s3_key
        FROM audit_events ae
        JOIN content_reviews cr ON ae.review_id = cr.id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        JOIN documents d ON dv.document_id = d.id
        LEFT JOIN user_profiles u ON ae.user_id = u.id
        WHERE ae.event_type NOT IN (
            'ai_analysis_started', 'version_created',
            'ai_phase_parsing_document', 'ai_phase_classifying_document',
            'ai_phase_analysing_document', 'ai_phase_performing_analysis',
            'ai_phase_consolidating_result'
        )
          AND dv.status != 'failed'
          AND ae.created_at >= $1
          AND d.organization_id = $2::uuid
        ORDER BY ae.created_at DESC
        LIMIT 80
    """
    audit_rows = await db.fetch(audit_query, cutoff_utc, organization_id)

    audit_items: List[Dict[str, Any]] = []
    for r in audit_rows:
        et = r.get("event_type") or ""
        rid = str(r["review_id"])
        created = r["created_at"]
        if et == "ai_analysis_completed" and rid in findings_by_review_times and created:
            if any(ft <= created for ft in findings_by_review_times[rid]):
                continue
        doc_id = str(r["document_id"]) if r.get("document_id") else None
        sp_id = str(r["social_post_id"]) if r.get("social_post_id") else None
        label = _content_display_name(
            document_name=r.get("document_name"),
            social_preview=r.get("social_preview"),
            social_post_code=r.get("social_post_code"),
            s3_key=r.get("version_s3_key"),
        )
        actor = r.get("user_name") or ("AI" if r.get("is_ai") else "System")
        # Format details JSON for human-readable display on dashboard
        raw_details = r.get("details")
        detail_text = None
        if raw_details:
            try:
                details_json = json.loads(raw_details)
                # Remove UUIDs and technical IDs from display
                for technical_key in ["finding_id", "comment_id", "suggestion_id", "user_id"]:
                    if technical_key in details_json:
                        del details_json[technical_key]
                
                # Format remaining keys as human-readable
                items = []
                for k, v in details_json.items():
                    if v and str(v).strip():
                        label = k.replace("_", " ").title()
                        items.append(f"{label}: {v}")
                detail_text = ", ".join(items) if items else None
            except:
                detail_text = raw_details

        audit_items.append(
            {
                "id": str(r["event_id"]),
                "feedSource": "audit",
                "eventType": et,
                "createdAt": created.isoformat() if created else "",
                "reviewId": rid,
                "contentType": r.get("content_type") or "",
                "documentId": doc_id,
                "socialPostId": sp_id,
                "contentLabel": label,
                "documentCode": r.get("document_code"),
                "description": r.get("description") or "",
                "title": None,
                "detailText": detail_text,
                "ruleCode": None,
                "ruleName": None,
                "findingCode": None,
                "riskLevel": None,
                "userName": actor,
                "userRole": r.get("user_role"),
                "isAi": bool(r.get("is_ai")),
                "workflowStage": r.get("workflow_stage"),
                "versionId": str(r["version_id"]) if r.get("version_id") else None,
            }
        )

    combined = finding_items + audit_items
    combined.sort(key=lambda x: x.get("createdAt") or "", reverse=True)
    return {"items": combined[:limit]}


@router.get("/{review_id}/audit-trail")
async def get_audit_trail(
    review_id: str,
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    """Fetch the audit trail events for a review.
    Returns workflow steps with audit events grouped under their respective stages.
    """
    await assert_review_in_organization(db, review_id, tenant_ctx["organization_id"])
    # Fetch workflow steps (first level)
    workflow_query = """
        SELECT 
            ws.id as step_id,
            ws.stage as workflow_stage,
            ws.action,
            u.full_name as performed_by,
            cb.full_name as completed_by_name,
            clb.full_name as claimed_by_name,
            ws.comment as notes,
            ws.completed_at,
            ws.claimed_at,
            ws.created_at,
            ws.step_order,
            ws.previous_stage
        FROM workflow_steps ws
        JOIN workflows w ON ws.workflow_id = w.id
        LEFT JOIN user_profiles u ON COALESCE(ws.completed_by, ws.claimed_by) = u.id
        LEFT JOIN user_profiles cb ON ws.completed_by = cb.id
        LEFT JOIN user_profiles clb ON ws.claimed_by = clb.id
        WHERE w.review_id = $1
        ORDER BY COALESCE(ws.completed_at, ws.claimed_at, ws.created_at) ASC
    """
    workflow_rows = await db.fetch(workflow_query, review_id)
    
    # Fetch audit events for AI finding actions (second level)
    audit_query = """
        SELECT 
            ae.id as event_id,
            ae.event_type,
            ae.description,
            ae.details,
            ae.created_at,
            ae.workflow_stage,
            u.full_name as user_name,
            ae.user_role
        FROM audit_events ae
        LEFT JOIN user_profiles u ON ae.user_id = u.id
        WHERE ae.review_id = $1
        AND ae.event_type IN ('finding_accepted', 'finding_accepted_global', 'finding_accepted_local', 'finding_rejected', 'finding_rejected_global', 'finding_dismissed', 'finding_comment_added', 'finding_suggestion_added')
        ORDER BY ae.created_at ASC
    """
    audit_rows = await db.fetch(audit_query, review_id)
    
    # Fetch content comments (general comments not tied to workflow steps)
    content_comments_query = """
        SELECT 
            cc.id as comment_id,
            cc.content,
            cc.created_at,
            u.full_name as author_name,
            (SELECT string_agg(r.name, ', ' ORDER BY r.name) FROM user_roles ur JOIN roles r ON ur.role_id = r.id WHERE ur.user_id = cc.author_id) as author_role
        FROM content_comments cc
        LEFT JOIN user_profiles u ON cc.author_id = u.id
        WHERE cc.review_id = $1
        ORDER BY cc.created_at ASC
    """
    content_comment_rows = await db.fetch(content_comments_query, review_id)
    
    # Fetch workflow metadata including published_by info
    workflow_meta_query = """
        SELECT 
            w.published,
            w.published_by,
            w.published_at,
            up.full_name as published_by_name
        FROM workflows w
        LEFT JOIN user_profiles up ON w.published_by = up.id
        WHERE w.review_id = $1
    """
    workflow_meta_row = await db.fetchrow(workflow_meta_query, review_id)
    
    # Create a map of workflow_stage -> list of events
    # Group events by workflow_stage and assign to the first matching step
    events_by_stage: dict[str, list] = {}
    for r in audit_rows:
        stage = r["workflow_stage"] or ""
        if stage not in events_by_stage:
            events_by_stage[stage] = []
        
        event_time = r["created_at"]
        # Format event name based on event_type
        event_name = ""
        if r["event_type"] in ("finding_accepted", "finding_accepted_global", "finding_accepted_local"):
            event_name = "Accepted AI finding"
        elif r["event_type"] in ("finding_rejected", "finding_rejected_global"):
            event_name = "Rejected AI finding"
        elif r["event_type"] == "finding_dismissed":
            event_name = "Dismissed AI finding"
        elif r["event_type"] == "finding_comment_added":
            event_name = "Commented on AI finding"
        elif r["event_type"] == "finding_suggestion_added":
            event_name = "Added alternate suggestion"
        
        # Format details JSON for human-readable display in audit trail
        raw_details = r["details"] or ""
        details_text = ""
        if raw_details:
            try:
                details_json = json.loads(raw_details)
                # Remove UUIDs and technical IDs from display
                for technical_key in ["finding_id", "comment_id", "suggestion_id", "user_id"]:
                    if technical_key in details_json:
                        del details_json[technical_key]
                
                # Format remaining keys as human-readable
                items = []
                for k, v in details_json.items():
                    if v and str(v).strip():
                        label = k.replace("_", " ").title()
                        items.append(f"{label}: {v}")
                details_text = ", ".join(items) if items else ""
            except:
                details_text = raw_details
        
        events_by_stage[stage].append({
            "type": "audit_event",
            "time": event_time.isoformat() + "Z" if event_time else "",
            "date": event_time.isoformat() + "Z" if event_time else "",
            "user": r["user_name"] or "System",
            "event": event_name,
            "details": details_text,
            "event_type": r["event_type"],
            "created_at": event_time.isoformat() + "Z" if event_time else "",
        })
    
    # Map workflow steps (first level) with events grouped under them
    workflow_data = []
    seen_events = set()  # Track events to prevent duplicates across steps
    
    # Associate content comments with workflow stages based on timestamp
    # Find the active workflow stage when each content comment was created
    # Use a more precise matching: find the most recent workflow step BEFORE the comment
    content_comments_by_stage: dict[str, list] = {}
    seen_comment_ids = set()  # Track comments to prevent duplicates
    
    for cc_row in content_comment_rows:
        comment_id = str(cc_row["comment_id"])
        if comment_id in seen_comment_ids:
            continue  # Skip if already assigned
        
        comment_time = cc_row["created_at"]
        # Find the most recent workflow step that occurred BEFORE the comment time
        # This ensures comments are only associated with the stage that was active when they were created
        # Special handling: Don't associate comments with upload steps if there are other steps of the same stage after upload
        active_stage = None
        most_recent_step_time = None
        most_recent_step_action = None
        
        for ws_row in workflow_rows:
            step_time = ws_row["completed_at"] or ws_row["claimed_at"] or ws_row["created_at"]
            step_action = (ws_row.get("action") or "").lower()
            step_stage = ws_row.get("workflow_stage")
            
            if step_time and comment_time >= step_time:
                # This step occurred before or at the comment time
                # Keep track of the most recent one
                if most_recent_step_time is None or step_time > most_recent_step_time:
                    most_recent_step_time = step_time
                    active_stage = step_stage
                    most_recent_step_action = step_action
            elif step_time and comment_time < step_time:
                # We've gone past the comment time, stop searching
                break
        
        # Special handling: If we matched an upload step, but there are other steps of the same stage after it,
        # and the comment was created after the upload step, prefer the next non-upload step
        if most_recent_step_action in ("uploaded", "reuploaded") and most_recent_step_time and comment_time > most_recent_step_time:
            # Check if there are other steps of the same stage after the upload step
            for ws_row in workflow_rows:
                step_time = ws_row["completed_at"] or ws_row["claimed_at"] or ws_row["created_at"]
                step_action = (ws_row.get("action") or "").lower()
                step_stage = ws_row.get("workflow_stage")
                
                if (step_time and step_time > most_recent_step_time 
                    and step_stage == active_stage 
                    and step_action not in ("uploaded", "reuploaded")
                    and comment_time >= step_time):
                    # Found a non-upload step of the same stage after upload, use this instead
                    active_stage = step_stage
                    most_recent_step_action = step_action
                    break
        
        # If no stage found (comment was before any workflow step), use the first workflow stage as fallback
        if not active_stage and workflow_rows:
            active_stage = workflow_rows[0]["workflow_stage"]
        
        if active_stage:
            if active_stage not in content_comments_by_stage:
                content_comments_by_stage[active_stage] = []
            content_comments_by_stage[active_stage].append({
                "type": "general_comment",
                "id": comment_id,
                "content": cc_row["content"],
                "time": comment_time.isoformat() + "Z" if comment_time else "",
                "date": comment_time.isoformat() + "Z" if comment_time else "",
                "author": cc_row["author_name"] or "Unknown",
                "author_role": cc_row["author_role"] or "unknown",
                "created_at": comment_time.isoformat() + "Z" if comment_time else "",
            })
            seen_comment_ids.add(comment_id)
    
    # Detect if document went through SME or directly to marketing
    # Check if any workflow step has SME approval action
    went_through_sme = any(
        (r.get("action") or "").lower() in ("sme_approve", "approve")
        and r.get("previous_stage") == "sme_review"
        for r in workflow_rows
    )
    
    for r in workflow_rows:
        action_time = r["completed_at"] or r["claimed_at"] or r["created_at"]
        stage = r["workflow_stage"]
        action = (r["action"] or "").lower()
        previous_stage = r.get("previous_stage") or ""
        
        # Get events for this stage, but only if they haven't been assigned to another step yet
        stage_events = []
        
        # Determine which events to check based on workflow path
        events_to_check = []
        if stage == "marketing_review" and not went_through_sme:
            # Direct-to-marketing path: show events under initial marketing_review upload step
            if action in ("uploaded", "reuploaded"):
                # Events are stored with workflow_stage='marketing_review'
                events_to_check = events_by_stage.get("marketing_review", [])
        elif stage == "compliance_review" and went_through_sme:
            # Through-SME path: show events under compliance_review step with submit_to_compliance action
            if action == "submit_to_compliance" and previous_stage == "marketing_review":
                # Events are created during marketing_review but should appear under compliance_review step
                events_to_check = events_by_stage.get("marketing_review", [])
        elif stage == "approved" and action == "approve_and_lock" and previous_stage == "compliance_review":
            # Compliance reviewer actions: show events under "Approve & Lock" step
            # Events are created during compliance_review stage
            events_to_check = events_by_stage.get("compliance_review", [])
        elif stage == "rejected" and action == "reject" and previous_stage == "compliance_review":
            # Compliance reviewer actions: show events under "Reject" step
            # Events are created during compliance_review stage
            events_to_check = events_by_stage.get("compliance_review", [])
        elif stage == "marketing_review" and action == "request_changes" and previous_stage == "compliance_review":
            # Compliance reviewer actions: show events under "Request Changes" step
            # Events are created during compliance_review stage
            events_to_check = events_by_stage.get("compliance_review", [])
        
        # Process events and add to stage_events
        for event in events_to_check:
            # Create unique event ID to prevent duplicates
            event_id = f"{event.get('created_at', '')}_{event.get('user', '')}_{event.get('event', '')}"
            if event_id not in seen_events:
                stage_events.append(event)
                seen_events.add(event_id)
        
        # Use previous_stage for display like document-right-panel
        # Special handling: if action is uploaded/reuploaded, use "document_upload" as display stage
        if action in ("uploaded", "reuploaded"):
            display_stage = "document_upload"
        else:
            display_stage = previous_stage if previous_stage else stage
        
        # Get general comments for this workflow stage
        general_comments = []
        if stage in content_comments_by_stage:
            general_comments = content_comments_by_stage[stage]
        
        # Mark workflow step comment with type
        workflow_comment = None
        if r["notes"]:
            workflow_comment = {
                "type": "workflow_comment",
                "content": r["notes"],
                "time": action_time.isoformat() + "Z" if action_time else "",
                "date": action_time.isoformat() + "Z" if action_time else "",
                "author": r["performed_by"] or "System",
            }
        
        workflow_data.append({
            "type": "workflow_step",
            "time": action_time.isoformat() + "Z" if action_time else "",
            "date": action_time.isoformat() + "Z" if action_time else "",
            "user": r["performed_by"] or "System",
            "event": f"Status: {display_stage}",
            "details": r["notes"] or f"Action: {r['action']}" if r["action"] else "Workflow step",
            "stage": display_stage,  # Use previous_stage for display
            "action": r["action"],
            "step_order": r["step_order"],
            "previous_stage": previous_stage,
            "workflow_stage": stage,  # Keep original stage for filtering
            "audit_events": stage_events,  # Include events grouped under this step
            "workflow_comment": workflow_comment,  # Workflow step comment (tied to action)
            "general_comments": general_comments,  # General content comments (not tied to action)
            "completed_by_name": r.get("completed_by_name"),
            "claimed_by_name": r.get("claimed_by_name"),
            "user_name": r.get("completed_by_name") or r.get("claimed_by_name") or "System",
        })
    
    # Add synthetic "publish" step if document is published
    if workflow_meta_row and workflow_meta_row["published"]:
        published_by_name = workflow_meta_row.get("published_by_name") or "System"
        published_at = workflow_meta_row.get("published_at")
        
        publish_step = {
            "type": "workflow_step",
            "time": published_at.isoformat() + "Z" if published_at else "",
            "date": published_at.isoformat() + "Z" if published_at else "",
            "user": published_by_name,
            "event": "Status: published",
            "details": "Action: publish",
            "stage": "published",
            "action": "publish",
            "step_order": len(workflow_data),
            "previous_stage": "approved",
            "workflow_stage": "published",
            "audit_events": [],
            "workflow_comment": None,
            "general_comments": [],
            # Include both completed_by_name and user_name for frontend compatibility
            "completed_by_name": published_by_name,
            "user_name": published_by_name,
        }
        workflow_data.append(publish_step)
    
    return {
        "workflow_steps": workflow_data,
    }

@router.get("/{review_id}/audit-trail-unified")
async def get_unified_audit_trail(
    review_id: str,
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    """Fetch unified audit trail with all events sorted chronologically by timestamp."""
    await assert_review_in_organization(db, review_id, tenant_ctx["organization_id"])

    # 1. Get document_id
    doc_row = await db.fetchrow(
        "SELECT dv.document_id FROM content_reviews cr JOIN document_versions dv ON cr.document_version_id = dv.id WHERE cr.id = $1::uuid",
        review_id
    )
    if not doc_row:
        return {"workflow_steps": [], "events": []}
    
    document_id = str(doc_row["document_id"])

    # 2. Query workflow_steps using document_id
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
            (SELECT string_agg(r.name, ', ' ORDER BY r.name) FROM user_roles ur JOIN roles r ON ur.role_id = r.id WHERE ur.user_id = COALESCE(ws.completed_by, ws.claimed_by)) as user_role
        FROM workflow_steps ws
        JOIN workflows w ON ws.workflow_id = w.id
        JOIN content_reviews cr ON w.review_id = cr.id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        LEFT JOIN user_profiles u ON COALESCE(ws.completed_by, ws.claimed_by) = u.id
        WHERE dv.document_id = $1::uuid
    """
    workflow_rows = await db.fetch(workflow_query, document_id)
    
    # 3. Query audit_events with AI finding details (exclude version_created events)
    audit_query = """
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
            -- Extract finding_code directly from JSON first (stored when event was created)
            CASE 
                WHEN ae.event_type IN ('finding_accepted', 'finding_accepted_global', 'finding_accepted_local', 'finding_rejected', 'finding_rejected_global', 'finding_dismissed', 'finding_comment_added', 'finding_suggestion_added')
                AND ae.details IS NOT NULL
                AND ae.details ~ '^[[:space:]]*\{'
                THEN NULLIF(ae.details::json->>'finding_code', '')
                ELSE NULL
            END as json_finding_code,
            -- Parse finding details from JSON in details field, using JSON finding_code first, then fallback to DB
            -- CRITICAL: finding_code is NOT NULL in ai_findings table, so we MUST get it from DB if JSON doesn't have it
            CASE 
                WHEN ae.event_type IN ('finding_accepted', 'finding_accepted_global', 'finding_accepted_local', 'finding_rejected', 'finding_rejected_global', 'finding_dismissed', 'finding_comment_added', 'finding_suggestion_added')
                AND ae.details IS NOT NULL
                AND ae.details ~ '^[[:space:]]*\{'
                THEN (
                    SELECT json_build_object(
                        'finding_id', COALESCE(
                            (ae.details::json->>'finding_id'),
                            af.id::text
                        ),
                        'finding_code', COALESCE(
                            NULLIF(ae.details::json->>'finding_code', ''),
                            NULLIF(ae.details::json->>'finding_code', 'null'),
                            NULLIF(ae.details::json->>'finding_code', 'None'),
                            af.finding_code,  -- This should always exist since finding_code is NOT NULL
                            'N/A'
                        ),
                        'finding_title', COALESCE(
                            NULLIF(ae.details::json->>'finding_title', ''),
                            af.title
                        ),
                        'finding_description', COALESCE(
                            NULLIF(ae.details::json->>'finding_description', ''),
                            af.description
                        ),
                        'risk_level', COALESCE(
                            NULLIF(ae.details::json->>'risk_level', ''),
                            af.risk_level
                        ),
                        'location', COALESCE(
                            NULLIF(ae.details::json->>'location', ''),
                            af.location,
                            'N/A'
                        ),
                        'claim_id', af.claim_id,
                        'claim_text', af.claim_text,
                        'canonical_claim_hash', (SELECT afa.normalized_claim_hash FROM ai_finding_anchors afa WHERE afa.finding_id = af.id LIMIT 1)
                    )
                    FROM ai_findings af
                    WHERE af.id::text = (ae.details::json->>'finding_id')
                    LIMIT 1
                )
                ELSE NULL
            END as finding_details,
            -- For finding comments, get the actual comment content from details JSON or join
            CASE 
                WHEN ae.event_type = 'finding_comment_added'
                AND ae.details IS NOT NULL
                THEN COALESCE(
                    CASE 
                        WHEN ae.details ~ '^[[:space:]]*\{' THEN (ae.details::json->>'comment_content')
                        ELSE NULL
                    END,
                    (
                        SELECT fc.content
                        FROM finding_comments fc
                        WHERE fc.id::text = (
                            CASE 
                                WHEN ae.details ~ '^[[:space:]]*\{' THEN (ae.details::json->>'comment_id')
                                ELSE NULL
                            END
                        )
                        LIMIT 1
                    )
                )
                ELSE NULL
            END as finding_comment_content,
            -- For finding suggestions, get the actual suggestion text from details JSON or join
            CASE 
                WHEN ae.event_type = 'finding_suggestion_added'
                AND ae.details IS NOT NULL
                THEN COALESCE(
                    CASE 
                        WHEN ae.details ~ '^[[:space:]]*\{' THEN (ae.details::json->>'suggestion_text')
                        ELSE NULL
                    END,
                    (
                        SELECT fs.text
                        FROM finding_suggestions fs
                        WHERE fs.id::text = (
                            CASE 
                                WHEN ae.details ~ '^[[:space:]]*\{' THEN (ae.details::json->>'suggestion_id')
                                ELSE NULL
                            END
                        )
                        LIMIT 1
                    )
                )
                ELSE NULL
            END as finding_suggestion_text
        FROM audit_events ae
        JOIN content_reviews cr ON ae.review_id = cr.id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        LEFT JOIN user_profiles u ON ae.user_id = u.id
        LEFT JOIN user_profiles triggered_by_user ON ae.triggered_by_user_id = triggered_by_user.id
        WHERE dv.document_id = $1::uuid
        AND ae.event_type != 'version_created'
        AND ae.event_type NOT IN (
            'ai_phase_parsing_document',
            'ai_phase_classifying_document',
            'ai_phase_analysing_document',
            'ai_phase_performing_analysis',
            'ai_phase_consolidating_result'
        )
    """
    audit_rows = await db.fetch(audit_query, document_id)
    
    # 4. Query content_comments (use stored workflow_stage instead of current stage)
    content_comments_query = """
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
            (SELECT string_agg(r.name, ', ' ORDER BY r.name) FROM user_roles ur JOIN roles r ON ur.role_id = r.id WHERE ur.user_id = cc.author_id) as user_role
        FROM content_comments cc
        JOIN content_reviews cr ON cc.review_id = cr.id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        LEFT JOIN user_profiles u ON cc.author_id = u.id
        WHERE dv.document_id = $1::uuid
    """
    content_comment_rows = await db.fetch(content_comments_query, document_id)
    
    # 4. Combine and normalize all events
    all_events = []
    
    # Process workflow steps
    for row in workflow_rows:
        timestamp = row["timestamp"]
        event_type = row["event_type"] or ""
        # Special handling: uploaded/reuploaded actions should map to "Document Upload" stage
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
            "time": "",
            "date": "",
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
        })
    
    # Process audit events
    for row in audit_rows:
        timestamp = row["timestamp"]
        finding_details = row.get("finding_details")
        json_finding_code = row.get("json_finding_code")  # Extract finding_code directly from JSON
        finding_obj = None
        if finding_details:
            # finding_details is already a dict from json_build_object, but handle both cases
            if isinstance(finding_details, dict):
                finding_obj = finding_details
                # Remove UUID from finding object
                if "finding_id" in finding_obj:
                    del finding_obj["finding_id"]
                
                # Priority: JSON finding_code > DB finding_code from join > "N/A"
                # Use JSON finding_code if it's valid, otherwise trust the DB join result
                if json_finding_code and json_finding_code not in ("null", "None", "", None):
                    finding_obj["finding_code"] = json_finding_code
                # If finding_code from DB join is missing or invalid, set to "N/A"
                elif not finding_obj.get("finding_code") or finding_obj.get("finding_code") in ("null", "None", "", None):
                    finding_obj["finding_code"] = "N/A"
            elif isinstance(finding_details, str):
                try:
                    finding_obj = json.loads(finding_details)
                    # Override finding_code with the one from JSON if available
                    if json_finding_code and json_finding_code not in ("null", "None", "", None):
                        finding_obj["finding_code"] = json_finding_code
                    elif not finding_obj.get("finding_code") or finding_obj.get("finding_code") in ("null", "None", "", None):
                        finding_obj["finding_code"] = "N/A"
                except:
                    finding_obj = None
        elif json_finding_code and json_finding_code not in ("null", "None", "", None):
            # If finding_details is NULL but we have finding_code from JSON, create a minimal finding object
            # This handles cases where the join failed but JSON has the code
            finding_obj = {
                "finding_code": json_finding_code,
                "finding_id": None,
                "finding_title": None,
                "finding_description": None,
                "risk_level": None,
                "location": "N/A"
            }
        else:
            # If finding_details is NULL and no JSON finding_code, try to get finding_code directly from DB
            # This handles cases where the join in SQL failed but we have finding_id
            # Note: This is a fallback - the SQL join should normally work
            if row.get("event_type") in ("finding_accepted", "finding_accepted_global", "finding_accepted_local", "finding_rejected", "finding_rejected_global", "finding_dismissed", "finding_comment_added", "finding_suggestion_added"):
                try:
                    raw_details = row.get("raw_details")
                    if raw_details:
                        if isinstance(raw_details, str):
                            details_dict = json.loads(raw_details)
                        elif isinstance(raw_details, dict):
                            details_dict = raw_details
                        else:
                            details_dict = None
                        
                        if details_dict:
                            finding_id = details_dict.get("finding_id")
                            if finding_id:
                                # Direct DB query to get finding_code as fallback
                                finding_row = await db.fetchrow(
                                    "SELECT finding_code, title FROM ai_findings WHERE id::text = $1",
                                    finding_id
                                )
                                if finding_row and finding_row.get("finding_code"):
                                    finding_obj = {
                                        "finding_code": finding_row["finding_code"],
                                        "finding_title": finding_row.get("title"),
                                        "finding_description": None,
                                        "risk_level": None,
                                        "location": "N/A"
                                    }
                except Exception:
                    # If all else fails, leave finding_obj as None
                    pass
        
        stage = row["workflow_stage"] or ""
        # Determine grouping user: for AI events, use triggered_by_user_id if available
        triggered_by_user_id = str(row["triggered_by_user_id"]) if row.get("triggered_by_user_id") else None
        triggered_by_user_name = row.get("triggered_by_user_name")
        user_id = str(row["user_id"]) if row["user_id"] else None
        
        # For AI events, use triggered_by_user_id if available, otherwise use regular user_id
        if row["is_ai"]:
            grouping_user_id = triggered_by_user_id or user_id
            grouping_user_name = triggered_by_user_name or row["user_name"] or "System"
        else:
            grouping_user_id = user_id
            grouping_user_name = row["user_name"] or "Unknown"
        
        # Format details JSON for human-readable display by removing technical IDs
        raw_details = row.get("raw_details")
        filtered_details = None
        if raw_details:
            try:
                details_json = json.loads(raw_details) if isinstance(raw_details, str) else raw_details
                if isinstance(details_json, dict):
                    for technical_key in ["finding_id", "finding_uuid", "comment_id", "suggestion_id", "user_id"]:
                        if technical_key in details_json:
                            del details_json[technical_key]
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
            "time": "",
            "date": "",
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
        })
    
    # Process content comments
    for row in content_comment_rows:
        timestamp = row["timestamp"]
        stage = row["workflow_stage"] or ""
        user_id = str(row["user_id"]) if row["user_id"] else None
        all_events.append({
            "id": str(row["id"]),
            "source": "content_comment",
            "event_type": "comment_added",
            "timestamp": timestamp.isoformat() if timestamp else "",
            "time": "",
            "date": "",
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
        })
    
    # 5. Sort by timestamp (oldest first)
    all_events.sort(key=lambda x: x["timestamp"] or "")
    
    # 6. Filter out duplicate document_upload events, keeping only the first one chronologically
    # Track if we've seen a document_upload event for this review (since all events share the same review_id)
    seen_document_upload = False
    filtered_events = []
    for event in all_events:
        # Check if this is a document upload event
        is_upload_event = (
            event["event_type"] == "document_upload" or
            (event.get("source") == "workflow_step" and event["event_type"] == "uploaded")
        )
        
        if is_upload_event:
            if not seen_document_upload:
                # Keep the first document upload event
                seen_document_upload = True
                filtered_events.append(event)
            # Skip all subsequent document upload events
        else:
            # Keep all non-upload events
            filtered_events.append(event)
    
    # 7. For AI events without triggered_by_user_id, attribute to most recent user action before them
    for i, event in enumerate(filtered_events):
        if event.get("is_ai") and not event.get("grouping_user_id"):
            # Find the most recent user action before this AI event
            for j in range(i - 1, -1, -1):
                prev_event = filtered_events[j]
                if prev_event.get("grouping_user_id") and not prev_event.get("is_ai"):
                    event["grouping_user_id"] = prev_event["grouping_user_id"]
                    event["grouping_user_name"] = prev_event["grouping_user_name"]
                    break
    
    # 8. Group events by grouping_user_id while maintaining chronological order
    user_groups = []
    current_group = None
    
    for event in filtered_events:
        grouping_user_id = event.get("grouping_user_id") or "system"
        grouping_user_name = event.get("grouping_user_name") or "System"
        grouping_user_role = event.get("user_role") or "unknown"
        
        # Start a new group if this is the first event or if the user changed
        if current_group is None or current_group["user_id"] != grouping_user_id:
            # Save previous group if it exists
            if current_group:
                user_groups.append(current_group)
            # Start new group
            current_group = {
                "user_id": grouping_user_id,
                "user_name": grouping_user_name,
                "user_role": grouping_user_role,
                "events": []
            }
        
        # Add event to current group
        current_group["events"].append(event)
    
    # Don't forget to add the last group
    if current_group:
        user_groups.append(current_group)
    
    return {
        "events": filtered_events,  # Keep flat list for backward compatibility
        "user_groups": user_groups,  # Add grouped structure
    }

@router.get("/{review_id}/reports")
async def get_compliance_reports(
    review_id: str,
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    """Fetch the compliance reports generated for a review."""
    await assert_review_in_organization(db, review_id, tenant_ctx["organization_id"])
    query = "SELECT * FROM compliance_reports WHERE review_id=$1 ORDER BY created_at DESC"
    rows = await db.fetch(query, review_id)
    return [dict(r) for r in rows]

@router.post("/{review_id}/reports")
async def generate_compliance_report(
    review_id: str,
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    """Generate a compliance report snapshot (mock logic for PoC)"""
    await assert_review_in_organization(db, review_id, tenant_ctx["organization_id"])
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    report_id = str(uuid.uuid4())
    
    count_row = await db.fetchrow("SELECT COUNT(*) FROM compliance_reports")
    next_num = count_row["count"] + 1
    report_code = f"RPT-{next_num:03d}"
    
    review = await db.fetchrow("SELECT * FROM content_reviews WHERE id=$1", review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
        
    # Get arbitrary user as approval authority for PoC
    user = await db.fetchrow("SELECT id FROM user_profiles LIMIT 1")
    
    await db.execute(
        """
        INSERT INTO compliance_reports (
            id, report_code, review_id, review_type, compliance_status, 
            approval_authority, approval_role, approval_timestamp, created_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8)
        """,
        report_id, report_code, review_id, review['content_type'], review['compliance_status'],
        user['id'], 'compliance', now_utc
    )
    
    row = await db.fetchrow("SELECT * FROM compliance_reports WHERE id=$1", report_id)
    return dict(row)
