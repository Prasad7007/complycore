"""Org-scoped dashboard aggregates shared by /dashboard-stats and /stat-cards."""

from datetime import date
from typing import Any, Optional

from apis.core.dashboard_period import ResolvedDashboardPeriod
from apis.core.stat_card_utils import format_pct_change_trend


async def fetch_tenant_dashboard_aggregates(
    db,
    organization_id: str,
    resolved: ResolvedDashboardPeriod,
) -> dict[str, Any]:
    """
    Same semantics as the legacy /audit-trail/dashboard-stats JSON (snapshot + trends).

    Snapshot fields are not filtered by period. ``trends`` compare activity in the
    selected window vs an equal-length window immediately before it.
    """
    period_key = resolved.key

    high_row = await db.fetchrow(
        """
        SELECT COUNT(DISTINCT 
            af.review_id::text || '_' || COALESCE(
                NULLIF(TRIM(afa.normalized_claim_hash), ''), 
                NULLIF(TRIM(af.claim_id), ''), 
                SUBSTRING(TRIM(COALESCE(af.claim_text, af.title, af.id::text)) FROM 1 FOR 200)
            )
        )::int AS c 
        FROM ai_findings af
        LEFT JOIN ai_finding_anchors afa ON afa.finding_id = af.id
        JOIN content_reviews cr ON cr.id = af.review_id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        JOIN documents d ON dv.document_id = d.id
        WHERE af.status = 'pending'
          AND UPPER(TRIM(COALESCE(af.risk_level, ''))) IN ('HIGH', 'CRITICAL')
          AND dv.status <> 'skipped'
          AND d.organization_id = $1::uuid
        """,
        organization_id,
    )
    pending_row = await db.fetchrow(
        """
        SELECT COUNT(DISTINCT 
            af.review_id::text || '_' || COALESCE(
                NULLIF(TRIM(afa.normalized_claim_hash), ''), 
                NULLIF(TRIM(af.claim_id), ''), 
                SUBSTRING(TRIM(COALESCE(af.claim_text, af.title, af.id::text)) FROM 1 FOR 200)
            )
        )::int AS c
        FROM ai_findings af
        LEFT JOIN ai_finding_anchors afa ON afa.finding_id = af.id
        JOIN content_reviews cr ON cr.id = af.review_id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        JOIN documents d ON dv.document_id = d.id
        WHERE af.status = 'pending'
          AND cr.document_version_id IS NOT NULL
          AND d.organization_id = $1::uuid
          AND dv.status <> 'skipped'
        """,
        organization_id,
    )

    doc_new_base = """
        SELECT COUNT(*)::int AS c FROM content_reviews cr
        JOIN document_versions dv ON cr.document_version_id = dv.id
        JOIN documents d ON dv.document_id = d.id
        WHERE cr.document_version_id IS NOT NULL
          AND d.organization_id = $1::uuid
          AND dv.status <> 'skipped'
    """
    pending_new_base = """
        SELECT COUNT(DISTINCT 
            af.review_id::text || '_' || COALESCE(
                NULLIF(TRIM(afa.normalized_claim_hash), ''), 
                NULLIF(TRIM(af.claim_id), ''), 
                SUBSTRING(TRIM(COALESCE(af.claim_text, af.title, af.id::text)) FROM 1 FOR 200)
            )
        )::int AS c
        FROM ai_findings af
        LEFT JOIN ai_finding_anchors afa ON afa.finding_id = af.id
        JOIN content_reviews cr ON cr.id = af.review_id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        JOIN documents d ON dv.document_id = d.id
        WHERE af.status = 'pending'
          AND cr.document_version_id IS NOT NULL
          AND d.organization_id = $1::uuid
          AND dv.status <> 'skipped'
    """

    custom_from: Optional[date] = resolved.custom_from
    custom_to: Optional[date] = resolved.custom_to
    custom_prev_from: Optional[date] = resolved.custom_prev_from
    custom_prev_to: Optional[date] = resolved.custom_prev_to

    if period_key == "week":
        doc_new_cur = await db.fetchrow(
            doc_new_base + " AND cr.created_at >= NOW() - INTERVAL '7 days'", organization_id
        )
        doc_new_prev = await db.fetchrow(
            doc_new_base + " AND cr.created_at >= NOW() - INTERVAL '14 days' AND cr.created_at < NOW() - INTERVAL '7 days'",
            organization_id,
        )
        pending_new_cur = await db.fetchrow(
            pending_new_base + " AND af.created_at >= NOW() - INTERVAL '7 days'", organization_id
        )
        pending_new_prev = await db.fetchrow(
            pending_new_base + " AND af.created_at >= NOW() - INTERVAL '14 days' AND af.created_at < NOW() - INTERVAL '7 days'",
            organization_id,
        )
    elif period_key == "month":
        doc_new_cur = await db.fetchrow(
            doc_new_base + " AND cr.created_at >= NOW() - INTERVAL '30 days'", organization_id
        )
        doc_new_prev = await db.fetchrow(
            doc_new_base + " AND cr.created_at >= NOW() - INTERVAL '60 days' AND cr.created_at < NOW() - INTERVAL '30 days'",
            organization_id,
        )
        pending_new_cur = await db.fetchrow(
            pending_new_base + " AND af.created_at >= NOW() - INTERVAL '30 days'", organization_id
        )
        pending_new_prev = await db.fetchrow(
            pending_new_base + " AND af.created_at >= NOW() - INTERVAL '60 days' AND af.created_at < NOW() - INTERVAL '30 days'",
            organization_id,
        )
    elif period_key == "ytd":
        ytd_prev = (
            " AND created_at >= date_trunc('year', CURRENT_TIMESTAMP) - INTERVAL '1 year'"
            " AND created_at <= date_trunc('year', CURRENT_TIMESTAMP) - INTERVAL '1 year'"
            " + (CURRENT_TIMESTAMP - date_trunc('year', CURRENT_TIMESTAMP))"
        )
        doc_new_cur = await db.fetchrow(
            doc_new_base + " AND cr.created_at >= date_trunc('year', CURRENT_TIMESTAMP)", organization_id
        )
        doc_new_prev = await db.fetchrow(
            doc_new_base + ytd_prev.replace("created_at", "cr.created_at"), organization_id
        )
        pending_new_cur = await db.fetchrow(
            pending_new_base + " AND af.created_at >= date_trunc('year', CURRENT_TIMESTAMP)", organization_id
        )
        pending_new_prev = await db.fetchrow(
            pending_new_base + ytd_prev.replace("created_at", "af.created_at"), organization_id
        )
    else:
        doc_new_cur = await db.fetchrow(
            doc_new_base + " AND cr.created_at::date >= $2::date AND cr.created_at::date <= $3::date",
            organization_id,
            custom_from,
            custom_to,
        )
        doc_new_prev = await db.fetchrow(
            doc_new_base + " AND cr.created_at::date >= $2::date AND cr.created_at::date <= $3::date",
            organization_id,
            custom_prev_from,
            custom_prev_to,
        )
        pending_new_cur = await db.fetchrow(
            pending_new_base + " AND af.created_at::date >= $2::date AND af.created_at::date <= $3::date",
            organization_id,
            custom_from,
            custom_to,
        )
        pending_new_prev = await db.fetchrow(
            pending_new_base + " AND af.created_at::date >= $2::date AND af.created_at::date <= $3::date",
            organization_id,
            custom_prev_from,
            custom_prev_to,
        )

    doc_review_row = await db.fetchrow(
        """
        SELECT COUNT(DISTINCT d.id)::int AS c
        FROM documents d
        INNER JOIN document_versions v ON d.current_version_id = v.id
        INNER JOIN content_reviews cr ON cr.document_version_id = v.id
        INNER JOIN workflows w ON w.review_id = cr.id
        WHERE d.organization_id = $1::uuid
          AND w.current_stage IS NOT NULL
          AND w.current_stage NOT IN ('published', 'rejected')
          AND v.status <> 'skipped'
        """,
        organization_id,
    )

    high = int(high_row["c"] or 0) if high_row else 0
    pending = int(pending_row["c"] or 0) if pending_row else 0
    doc_ur = int(doc_review_row["c"] or 0) if doc_review_row else 0

    dnc = int(doc_new_cur["c"] or 0) if doc_new_cur else 0
    dnp = int(doc_new_prev["c"] or 0) if doc_new_prev else 0
    pnc = int(pending_new_cur["c"] or 0) if pending_new_cur else 0
    pnp = int(pending_new_prev["c"] or 0) if pending_new_prev else 0

    return {
        "high_risk_flags": high,
        # Social/LinkedIn monitoring removed — keep keys for API compatibility.
        "linkedin_posts_monitored_total": 0,
        "documents_under_review": doc_ur,
        "pending_document_findings": pending,
        "trends": {
            "linkedin_posts_monitored": format_pct_change_trend(0, 0),
            "documents_under_review": format_pct_change_trend(dnc, dnp),
            "pending_document_findings": format_pct_change_trend(pnc, pnp),
            "high_risk_flags": None,
        },
    }
