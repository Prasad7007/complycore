"""Role-specific stat card queries (marketing, SME, compliance, org superadmin)."""

from typing import Any, Optional

from apis.core.dashboard_period import ResolvedDashboardPeriod


def _build_date_filter(column_name: str, resolved: ResolvedDashboardPeriod, param_offset: int) -> tuple[str, list[Any]]:
    if resolved.key == "week":
        return f"{column_name} >= NOW() - INTERVAL '7 days'", []
    if resolved.key == "month":
        return f"{column_name} >= NOW() - INTERVAL '30 days'", []
    if resolved.key == "ytd":
        return f"{column_name} >= date_trunc('year', CURRENT_TIMESTAMP)", []
    if resolved.key == "custom":
        return f"{column_name}::date >= ${param_offset}::date AND {column_name}::date <= ${param_offset + 1}::date", [resolved.custom_from, resolved.custom_to]
    # Fallback to month (30 days)
    return f"{column_name} >= NOW() - INTERVAL '30 days'", []


async def count_marketing_pending_submissions(
    db, organization_id: str, user_id: str, roles: list[str]
) -> int:
    """
    Documents the user submitted, or that are in the marketing review queue for their role/user,
    and are not yet approved, published, or rejected.
    Uses the same stage bucketing as /review-status-stats.
    """
    row = await db.fetchrow(
        """
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
            SELECT id FROM content_reviews
            WHERE document_version_id = v.id
            ORDER BY created_at DESC LIMIT 1
          ) cr_lat ON TRUE
          LEFT JOIN content_reviews cr ON cr.id = cr_lat.id
          LEFT JOIN workflows w ON w.review_id = cr.id
          WHERE d.organization_id = $1::uuid
            AND v.status <> 'skipped'
            AND (
              d.submitted_by = $2::uuid
              OR w.assigned_to = $2::uuid
              OR (w.assigned_to IS NULL AND w.assigned_role = ANY(COALESCE($3::text[], ARRAY[]::text[])))
              OR EXISTS (
                SELECT 1 FROM workflow_steps ws 
                WHERE ws.workflow_id = w.id 
                AND (ws.claimed_by = $2::uuid OR ws.completed_by = $2::uuid)
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
        ),
        bucketed AS (
          SELECT id,
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
        SELECT COUNT(*)::int AS c FROM bucketed
        WHERE bucket = 'marketing_review'
        """,
        organization_id,
        user_id,
        roles if roles else [],
    )
    return int(row["c"] or 0) if row else 0


async def count_sme_review_queue(
    db,
    organization_id: str,
    user_id: str,
    roles: list[str],
    is_org_super_admin: bool,
) -> int:
    """
    Items in SME review stage visible to the user (same visibility rules as list_documents).
    """
    row = await db.fetchrow(
        """
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
            SELECT id FROM content_reviews
            WHERE document_version_id = v.id
            ORDER BY created_at DESC LIMIT 1
          ) cr_lat ON TRUE
          LEFT JOIN content_reviews cr ON cr.id = cr_lat.id
          LEFT JOIN workflows w ON w.review_id = cr.id
          WHERE d.organization_id = $1::uuid
            AND v.status <> 'skipped'
            AND (
              $2::bool IS TRUE
              OR (
                d.submitted_by = $3::uuid
                OR w.assigned_to = $3::uuid
                OR (w.assigned_to IS NULL AND w.assigned_role = ANY(COALESCE($4::text[], ARRAY[]::text[])))
                OR EXISTS (
                  SELECT 1 FROM workflow_steps ws
                  WHERE ws.workflow_id = w.id
                    AND (ws.claimed_by = $3::uuid OR ws.completed_by = $3::uuid)
                )
              )
            )
        ),
        bucketed AS (
          SELECT id,
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
        SELECT COUNT(*)::int AS c FROM bucketed
        WHERE bucket = 'sme_review'
        """,
        organization_id,
        is_org_super_admin,
        user_id,
        roles if roles else [],
    )
    return int(row["c"] or 0) if row else 0


async def count_org_documents(db, organization_id: str) -> int:
    row = await db.fetchrow(
        """
        SELECT COUNT(*)::int AS c
        FROM documents d
        JOIN document_versions v ON d.current_version_id = v.id
        WHERE d.organization_id = $1::uuid
          AND v.status <> 'skipped'
        """,
        organization_id,
    )
    return int(row["c"] or 0) if row else 0


async def count_active_users_in_org(db, organization_id: str) -> int:
    """Distinct users with audit activity in the last 30 days (org-scoped reviews)."""
    row = await db.fetchrow(
        """
        SELECT COUNT(DISTINCT ae.user_id)::int AS c
        FROM audit_events ae
        JOIN content_reviews cr ON cr.id = ae.review_id
        LEFT JOIN document_versions dv ON cr.document_version_id = dv.id
        LEFT JOIN documents d ON dv.document_id = d.id
        WHERE ae.user_id IS NOT NULL
          AND ae.created_at >= NOW() - INTERVAL '30 days'
          AND COALESCE(dv.status, '') <> 'skipped'
          AND d.organization_id = $1::uuid
        """,
        organization_id,
    )
    return int(row["c"] or 0) if row else 0


async def fetch_marketing_submitter_analytics(
    db, organization_id: str, user_id: str
) -> dict[str, Any]:
    """
    Metrics for documents submitted by the user, based on compliance_reports in the last 30 days.
    """
    avg_row = await db.fetchrow(
        """
        SELECT
          COALESCE(
            AVG(EXTRACT(EPOCH FROM (rep.approval_timestamp - cr.created_at)) / 86400.0),
            0.0
          ) AS avg_days,
          COUNT(*)::int AS n_reports
        FROM compliance_reports rep
        JOIN content_reviews cr ON cr.id = rep.review_id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        JOIN documents d ON dv.document_id = d.id
        WHERE d.organization_id = $1::uuid
          AND d.submitted_by = $2::uuid
          AND rep.approval_timestamp >= NOW() - INTERVAL '30 days'
          AND dv.status <> 'skipped'
        """,
        organization_id,
        user_id,
    )
    n_reports = int(avg_row["n_reports"] or 0) if avg_row else 0
    avg_days = float(avg_row["avg_days"] or 0) if avg_row else 0.0

    iter_row = await db.fetchrow(
        """
        SELECT COALESCE(AVG(step_cnt), 0.0) AS avg_steps
        FROM (
          SELECT d.id, COUNT(v2.id)::int AS step_cnt
          FROM compliance_reports rep
          JOIN content_reviews cr ON cr.id = rep.review_id
          JOIN document_versions dv ON cr.document_version_id = dv.id
          JOIN documents d ON dv.document_id = d.id
          JOIN document_versions v2 ON v2.document_id = d.id
          WHERE d.organization_id = $1::uuid
            AND d.submitted_by = $2::uuid
            AND rep.approval_timestamp >= NOW() - INTERVAL '30 days'
            AND v2.status <> 'skipped'
          GROUP BY d.id
        ) sub
        """,
        organization_id,
        user_id,
    )
    avg_iterations = float(iter_row["avg_steps"] or 0) if iter_row else 0.0

    rate_row = await db.fetchrow(
        """
        SELECT
          COUNT(*) FILTER (
            WHERE LOWER(TRIM(COALESCE(rep.compliance_status, ''))) IN ('pass', 'compliant')
          )::int AS passed,
          COUNT(*)::int AS total
        FROM compliance_reports rep
        JOIN content_reviews cr ON cr.id = rep.review_id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        JOIN documents d ON dv.document_id = d.id
        WHERE d.organization_id = $1::uuid
          AND d.submitted_by = $2::uuid
          AND rep.approval_timestamp >= NOW() - INTERVAL '30 days'
          AND dv.status <> 'skipped'
        """,
        organization_id,
        user_id,
    )
    passed = int(rate_row["passed"] or 0) if rate_row else 0
    total = int(rate_row["total"] or 0) if rate_row else 0
    approval_pct: Optional[float] = None
    if total > 0:
        approval_pct = round(100.0 * passed / total, 1)

    # First-time approval: first submission approved and no later versions for that document.
    # Denominator = total documents submitted in last 30 days by this user.
    first_time_row = await db.fetchrow(
        """
        WITH submitted_docs AS (
          SELECT d.id
          FROM documents d
          JOIN document_versions v ON d.current_version_id = v.id
          WHERE d.organization_id = $1::uuid
            AND d.submitted_by = $2::uuid
            AND d.created_at >= NOW() - INTERVAL '30 days'
            AND v.status <> 'skipped'
        ),
        doc_first_version AS (
          SELECT dv.document_id, MIN(dv.uploaded_at) AS first_uploaded_at
          FROM document_versions dv
          JOIN submitted_docs sd ON sd.id = dv.document_id
          GROUP BY dv.document_id
        ),
        first_versions AS (
          SELECT dv.document_id, dv.id AS version_id
          FROM document_versions dv
          JOIN doc_first_version fv
            ON fv.document_id = dv.document_id
           AND fv.first_uploaded_at = dv.uploaded_at
        ),
        first_version_reports AS (
          SELECT
            fv.document_id,
            rep.compliance_status,
            NOT EXISTS (
              SELECT 1
              FROM document_versions dv2
              WHERE dv2.document_id = fv.document_id
                AND dv2.id <> fv.version_id
                AND dv2.uploaded_at > (
                  SELECT uploaded_at FROM document_versions WHERE id = fv.version_id
                )
            ) AS no_newer_versions
          FROM first_versions fv
          JOIN content_reviews cr ON cr.document_version_id = fv.version_id
          JOIN compliance_reports rep ON rep.review_id = cr.id
          WHERE rep.approval_timestamp >= NOW() - INTERVAL '30 days'
        ),
        first_time_approved AS (
          SELECT DISTINCT fvr.document_id
          FROM first_version_reports fvr
          WHERE fvr.no_newer_versions
            AND LOWER(TRIM(COALESCE(fvr.compliance_status, ''))) IN ('pass', 'compliant')
        ),
        submitted_total AS (
          SELECT COUNT(*)::int AS total_submitted FROM submitted_docs
        )
        SELECT
          st.total_submitted::int AS total,
          (SELECT COUNT(*)::int FROM first_time_approved) AS first_time_approved
        FROM submitted_total st
        """,
        organization_id,
        user_id,
    )
    ft_total = int(first_time_row["total"] or 0) if first_time_row else 0
    ft_approved = int(first_time_row["first_time_approved"] or 0) if first_time_row else 0
    first_time_approval_rate_pct: Optional[float] = None
    if ft_total > 0:
        first_time_approval_rate_pct = round(100.0 * ft_approved / ft_total, 1)

    return {
        "avg_days_to_approval": avg_days,
        "avg_workflow_steps": avg_iterations,
        "approval_pass_rate_pct": approval_pct,
        "first_time_approval_rate_pct": first_time_approval_rate_pct,
        "reports_in_window": n_reports,
    }





async def fetch_compliance_analytics(
    db,
    organization_id: str,
    resolved: ResolvedDashboardPeriod,
) -> dict[str, Any]:
    """Compliance-card metrics for the last 30 days where applicable."""
    queue_row = await db.fetchrow(
        """
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
            SELECT id FROM content_reviews
            WHERE document_version_id = v.id
            ORDER BY created_at DESC LIMIT 1
          ) cr_lat ON TRUE
          LEFT JOIN content_reviews cr ON cr.id = cr_lat.id
          LEFT JOIN workflows w ON w.review_id = cr.id
          WHERE d.organization_id = $1::uuid
            AND v.status <> 'skipped'
        ),
        bucketed AS (
          SELECT id,
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
        SELECT COUNT(*)::int AS c FROM bucketed WHERE bucket = 'compliance_review'
        """,
        organization_id,
    )
    compliance_queue = int(queue_row["c"] or 0) if queue_row else 0

    avg_time_row = await db.fetchrow(
        """
        WITH start_steps AS (
          SELECT
            ws.workflow_id,
            ws.claimed_at AS start_time
          FROM workflow_steps ws
          WHERE ws.stage = 'compliance_review'
            AND ws.action = 'claimed'
            AND ws.claimed_at IS NOT NULL
          UNION ALL
          SELECT
            ws.workflow_id,
            ws.completed_at AS start_time
          FROM workflow_steps ws
          WHERE ws.stage = 'compliance_review'
            AND ws.action = 'submit_to_compliance'
            AND ws.completed_at IS NOT NULL
            AND NOT EXISTS (
              SELECT 1 FROM workflow_steps ws2
              WHERE ws2.workflow_id = ws.workflow_id
                AND ws2.stage = 'compliance_review'
                AND ws2.action = 'claimed'
            )
        ),
        step_pairs AS (
          SELECT
            ss.workflow_id,
            ss.start_time,
            (
              SELECT MIN(ws2.completed_at)
              FROM workflow_steps ws2
              WHERE ws2.workflow_id = ss.workflow_id
                AND ws2.completed_at > ss.start_time
            ) AS completed_at
          FROM start_steps ss
        )
        SELECT COALESCE(AVG(EXTRACT(EPOCH FROM (sp.completed_at - sp.start_time)) / 86400.0), 0.0) AS avg_days
        FROM step_pairs sp
        JOIN workflows wf ON wf.id = sp.workflow_id
        JOIN content_reviews cr ON cr.id = wf.review_id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        JOIN documents d ON d.id = dv.document_id
        WHERE d.organization_id = $1::uuid
          AND sp.completed_at >= NOW() - INTERVAL '30 days'
          AND sp.completed_at IS NOT NULL
          AND dv.status <> 'skipped'
        """,
        organization_id,
    )
    avg_review_days = float(avg_time_row["avg_days"] or 0) if avg_time_row else 0.0

    first_time_row = await db.fetchrow(
        """
        WITH submitted_docs AS (
          SELECT d.id
          FROM documents d
          JOIN document_versions v ON d.current_version_id = v.id
          WHERE d.organization_id = $1::uuid
            AND d.created_at >= NOW() - INTERVAL '30 days'
            AND v.status <> 'skipped'
        ),
        doc_first_version AS (
          SELECT dv.document_id, MIN(dv.uploaded_at) AS first_uploaded_at
          FROM document_versions dv
          JOIN submitted_docs sd ON sd.id = dv.document_id
          GROUP BY dv.document_id
        ),
        first_versions AS (
          SELECT dv.document_id, dv.id AS version_id
          FROM document_versions dv
          JOIN doc_first_version fv
            ON fv.document_id = dv.document_id
           AND fv.first_uploaded_at = dv.uploaded_at
        ),
        first_version_reports AS (
          SELECT
            fv.document_id,
            rep.compliance_status,
            NOT EXISTS (
              SELECT 1
              FROM document_versions dv2
              WHERE dv2.document_id = fv.document_id
                AND dv2.id <> fv.version_id
                AND dv2.uploaded_at > (
                  SELECT uploaded_at FROM document_versions WHERE id = fv.version_id
                )
            ) AS no_newer_versions
          FROM first_versions fv
          JOIN content_reviews cr ON cr.document_version_id = fv.version_id
          JOIN compliance_reports rep ON rep.review_id = cr.id
          WHERE rep.approval_timestamp >= NOW() - INTERVAL '30 days'
        ),
        first_time_approved AS (
          SELECT DISTINCT fvr.document_id
          FROM first_version_reports fvr
          WHERE fvr.no_newer_versions
            AND LOWER(TRIM(COALESCE(fvr.compliance_status, ''))) IN ('pass', 'compliant')
        ),
        submitted_total AS (
          SELECT COUNT(*)::int AS total_submitted FROM submitted_docs
        )
        SELECT
          st.total_submitted::int AS total,
          (SELECT COUNT(*)::int FROM first_time_approved) AS first_time_approved
        FROM submitted_total st
        """,
        organization_id,
    )
    ft_total = int(first_time_row["total"] or 0) if first_time_row else 0
    ft_approved = int(first_time_row["first_time_approved"] or 0) if first_time_row else 0
    approval_rate_pct: Optional[float] = None
    if ft_total > 0:
        approval_rate_pct = round(100.0 * ft_approved / ft_total, 1)

    li_current, li_previous = 0, 0
    linkedin_trend_pct: Optional[float] = None

    iter_row = await db.fetchrow(
        """
        SELECT COALESCE(AVG(step_cnt), 0.0) AS avg_steps
        FROM (
          SELECT d.id, COUNT(v2.id)::int AS step_cnt
          FROM compliance_reports rep
          JOIN content_reviews cr ON cr.id = rep.review_id
          JOIN document_versions dv ON cr.document_version_id = dv.id
          JOIN documents d ON dv.document_id = d.id
          JOIN document_versions v2 ON v2.document_id = d.id
          WHERE d.organization_id = $1::uuid
            AND rep.approval_timestamp >= NOW() - INTERVAL '30 days'
            AND v2.status <> 'skipped'
          GROUP BY d.id
        ) sub
        """,
        organization_id,
    )
    avg_iterations = float(iter_row["avg_steps"] or 0) if iter_row else 0.0

    return {
        "compliance_queue": compliance_queue,
        "linkedin_posts_in_window": li_current,
        "linkedin_trend_pct": linkedin_trend_pct,
        "avg_review_days": avg_review_days,
        "approval_rate_pct": approval_rate_pct,
        "avg_iterations": avg_iterations,
    }


async def fetch_superadmin_analytics(db, organization_id: str) -> dict[str, Any]:
    """Extra superadmin cards (approval rate + processing time) for last 30 days."""
    first_time_row = await db.fetchrow(
        """
        WITH submitted_docs AS (
          SELECT d.id
          FROM documents d
          JOIN document_versions v ON d.current_version_id = v.id
          WHERE d.organization_id = $1::uuid
            AND d.created_at >= NOW() - INTERVAL '30 days'
            AND v.status <> 'skipped'
        ),
        doc_first_version AS (
          SELECT dv.document_id, MIN(dv.uploaded_at) AS first_uploaded_at
          FROM document_versions dv
          JOIN submitted_docs sd ON sd.id = dv.document_id
          GROUP BY dv.document_id
        ),
        first_versions AS (
          SELECT dv.document_id, dv.id AS version_id
          FROM document_versions dv
          JOIN doc_first_version fv
            ON fv.document_id = dv.document_id
           AND fv.first_uploaded_at = dv.uploaded_at
        ),
        first_version_reports AS (
          SELECT
            fv.document_id,
            rep.compliance_status,
            NOT EXISTS (
              SELECT 1
              FROM document_versions dv2
              WHERE dv2.document_id = fv.document_id
                AND dv2.id <> fv.version_id
                AND dv2.uploaded_at > (
                  SELECT uploaded_at FROM document_versions WHERE id = fv.version_id
                )
            ) AS no_newer_versions
          FROM first_versions fv
          JOIN content_reviews cr ON cr.document_version_id = fv.version_id
          JOIN compliance_reports rep ON rep.review_id = cr.id
          WHERE rep.approval_timestamp >= NOW() - INTERVAL '30 days'
        ),
        first_time_approved AS (
          SELECT DISTINCT fvr.document_id
          FROM first_version_reports fvr
          WHERE fvr.no_newer_versions
            AND LOWER(TRIM(COALESCE(fvr.compliance_status, ''))) IN ('pass', 'compliant')
        ),
        submitted_total AS (
          SELECT COUNT(*)::int AS total_submitted FROM submitted_docs
        )
        SELECT
          st.total_submitted::int AS total,
          (SELECT COUNT(*)::int FROM first_time_approved) AS first_time_approved
        FROM submitted_total st
        """,
        organization_id,
    )
    ft_total = int(first_time_row["total"] or 0) if first_time_row else 0
    ft_approved = int(first_time_row["first_time_approved"] or 0) if first_time_row else 0
    approval_rate_pct: Optional[float] = None
    if ft_total > 0:
        approval_rate_pct = round(100.0 * ft_approved / ft_total, 1)

    processing_row = await db.fetchrow(
        """
        SELECT
          COALESCE(
            AVG(EXTRACT(EPOCH FROM (rep.approval_timestamp - cr.created_at)) / 86400.0),
            0.0
          ) AS avg_days
        FROM compliance_reports rep
        JOIN content_reviews cr ON cr.id = rep.review_id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        JOIN documents d ON dv.document_id = d.id
        WHERE d.organization_id = $1::uuid
          AND rep.approval_timestamp >= NOW() - INTERVAL '30 days'
          AND dv.status <> 'skipped'
        """,
        organization_id,
    )
    processing_days = float(processing_row["avg_days"] or 0) if processing_row else 0.0

    flagged_docs_row = await db.fetchrow(
        """
        SELECT COUNT(DISTINCT d.id)::int AS c
        FROM ai_findings af
        JOIN content_reviews cr ON cr.id = af.review_id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        JOIN documents d ON dv.document_id = d.id
        WHERE d.organization_id = $1::uuid
          AND af.status = 'pending'
          AND dv.status <> 'skipped'
        """,
        organization_id,
    )
    compliance_active_flags = int(flagged_docs_row["c"] or 0) if flagged_docs_row else 0

    return {
        "approval_rate_pct": approval_rate_pct,
        "processing_days": processing_days,
        "compliance_active_flags": compliance_active_flags,
    }
