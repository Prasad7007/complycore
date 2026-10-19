"""Build historical sparkline series for dashboard stat cards.

Stat-card sparklines always use a rolling 30-day daily window. Trend comparison
is independent from Review Status filters:

- first 30 active org days → today vs yesterday
- after first 30 active org days → current month vs previous month
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, List, Literal, Optional

from apis.core.dashboard_period import ResolvedDashboardPeriod
from apis.schemas.dashboard_stat_cards import (
    DashboardStatCardsResponse,
    StatCard,
    StatCardSeries,
    StatCardTrend,
    StatSeriesPoint,
)


# Card trend semantics — controls how period-over-period change is computed
# from the sparkline series we already build.
SNAPSHOT_TREND_CARDS = {"total_documents", "active_users", "high_risk", "compliance", "my_review_queue"}
RATE_TREND_CARDS = {
    "approval_rate",
    "avg_time_to_approval",
    "processing",
    "avg_time",
    "iterations",
}
COUNT_TREND_CARDS = {
    "pending_items",
    "linkedin_posts_monitored",
    "compliance_queue",
}
# Cards we cannot reliably compute period-over-period for.
SKIP_TREND_CARDS: set[str] = set()


BucketType = Literal["day", "month"]


@dataclass(frozen=True)
class SeriesBuckets:
    bucket: BucketType
    starts: List[date]      # inclusive start of each bucket
    ends: List[date]        # exclusive end of each bucket
    labels: List[str]       # human-friendly labels


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _start_of_month(d: date) -> date:
    return d.replace(day=1)


def _add_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _format_day_label(d: date) -> str:
    return d.strftime("%b %d")


def _format_month_label(d: date) -> str:
    return d.strftime("%b %Y")


def compute_buckets(resolved: ResolvedDashboardPeriod) -> SeriesBuckets:
    today = _today_utc()
    if resolved.key == "custom" and resolved.custom_from and resolved.custom_to:
        df, dt = resolved.custom_from, resolved.custom_to
        span_days = (dt - df).days + 1
        if span_days <= 31:
            return _daily_buckets(df, dt)
        return _monthly_buckets(_start_of_month(df), _start_of_month(dt))

    if resolved.key == "week":
        end = today
        start = end - timedelta(days=6)
        return _daily_buckets(start, end)

    if resolved.key == "ytd":
        start = date(today.year, 1, 1)
        return _monthly_buckets(start, _start_of_month(today))

    # default: month → 30 daily buckets
    end = today
    start = end - timedelta(days=29)
    return _daily_buckets(start, end)


def compute_stat_card_graph_buckets() -> SeriesBuckets:
    """Stat-card sparklines are always a rolling 30-day daily history."""
    today = _today_utc()
    return _daily_buckets(today - timedelta(days=29), today)


def _previous_month_start(d: date) -> date:
    if d.month == 1:
        return date(d.year - 1, 12, 1)
    return date(d.year, d.month - 1, 1)


async def _org_first_activity_date(db, organization_id: str) -> date:
    """Earliest known org activity used to choose day-vs-month trend mode."""
    row = await db.fetchrow(
        """
        WITH firsts AS (
          SELECT MIN(d.created_at)::date AS first_date
          FROM documents d
          WHERE d.organization_id = $1::uuid

          UNION ALL

          SELECT MIN(ae.created_at)::date AS first_date
          FROM audit_events ae
          JOIN content_reviews cr ON cr.id = ae.review_id
          JOIN document_versions dv ON cr.document_version_id = dv.id
          JOIN documents d ON dv.document_id = d.id
          WHERE d.organization_id = $1::uuid
        )
        SELECT MIN(first_date)::date AS first_date
        FROM firsts
        WHERE first_date IS NOT NULL
        """,
        organization_id,
    )
    first_date = row["first_date"] if row else None
    if isinstance(first_date, datetime):
        return first_date.date()
    return first_date or _today_utc()


async def _trend_comparison_buckets(db, organization_id: str) -> SeriesBuckets:
    """Two buckets: previous comparison window, then current comparison window."""
    today = _today_utc()
    first_activity = await _org_first_activity_date(db, organization_id)
    org_age_days = max(0, (today - first_activity).days)

    if org_age_days < 30:
        yesterday = today - timedelta(days=1)
        return SeriesBuckets(
            bucket="day",
            starts=[yesterday, today],
            ends=[today, today + timedelta(days=1)],
            labels=[_format_day_label(yesterday), _format_day_label(today)],
        )

    current_month = _start_of_month(today)
    previous_month = _previous_month_start(today)
    return SeriesBuckets(
        bucket="month",
        starts=[previous_month, current_month],
        ends=[current_month, _add_month(current_month)],
        labels=[_format_month_label(previous_month), _format_month_label(current_month)],
    )


def _daily_buckets(start: date, end: date) -> SeriesBuckets:
    starts: List[date] = []
    ends: List[date] = []
    labels: List[str] = []
    cursor = start
    while cursor <= end:
        starts.append(cursor)
        ends.append(cursor + timedelta(days=1))
        labels.append(_format_day_label(cursor))
        cursor += timedelta(days=1)
    return SeriesBuckets(bucket="day", starts=starts, ends=ends, labels=labels)


def _monthly_buckets(start: date, end_first_of_month: date) -> SeriesBuckets:
    starts: List[date] = []
    ends: List[date] = []
    labels: List[str] = []
    cursor = _start_of_month(start)
    while cursor <= end_first_of_month:
        starts.append(cursor)
        ends.append(_add_month(cursor))
        labels.append(_format_month_label(cursor))
        cursor = _add_month(cursor)
    return SeriesBuckets(bucket="month", starts=starts, ends=ends, labels=labels)


def _series_from_values(buckets: SeriesBuckets, values: Iterable[float]) -> StatCardSeries:
    pts: List[StatSeriesPoint] = []
    vals = list(values)
    for i, start in enumerate(buckets.starts):
        v = float(vals[i]) if i < len(vals) else 0.0
        pts.append(StatSeriesPoint(label=buckets.labels[i], value=v, date=start.isoformat()))
    return StatCardSeries(bucket=buckets.bucket, points=pts)


def _empty_series(buckets: SeriesBuckets) -> StatCardSeries:
    return _series_from_values(buckets, [0.0] * len(buckets.starts))


def _flat_series(buckets: SeriesBuckets, value: float) -> StatCardSeries:
    return _series_from_values(buckets, [value] * len(buckets.starts))


# ────────────────────────── per-card SQL helpers ──────────────────────────

async def _cumulative_count_series(
    db,
    *,
    sql: str,
    args: list,
    buckets: SeriesBuckets,
    column_alias: str = "value",
) -> StatCardSeries:
    """Run a single SQL with $N::date bucket boundary placeholders.

    Expected ``sql`` shape: "SELECT (subquery returning count up to $X::date) AS value"
    is **not** how this works; instead we use a single ``generate_series`` style query.
    """
    rows = await db.fetch(sql, *args)
    by_date: dict[date, float] = {}
    for r in rows:
        bd = r["bucket_date"]
        if isinstance(bd, datetime):
            bd = bd.date()
        by_date[bd] = float(r[column_alias] or 0)
    values = [by_date.get(s, 0.0) for s in buckets.starts]
    return _series_from_values(buckets, values)


async def _series_total_documents(
    db, organization_id: str, buckets: SeriesBuckets
) -> StatCardSeries:
    bucket_sql = _bucket_generate_series_sql(buckets)
    sql = f"""
        WITH bd AS (
          {bucket_sql}
        )
        SELECT
          bd.bucket_date::date AS bucket_date,
          COALESCE((
            SELECT COUNT(*)::int
            FROM documents d
            JOIN document_versions v ON d.current_version_id = v.id
            WHERE d.organization_id = $1::uuid
              AND v.status <> 'skipped'
              AND d.created_at < bd.next_bucket_date
          ), 0) AS value
        FROM bd
        ORDER BY bd.bucket_date
    """
    return await _cumulative_count_series(
        db, sql=sql, args=[organization_id], buckets=buckets
    )


async def _series_active_users_30d_trailing(
    db, organization_id: str, buckets: SeriesBuckets
) -> StatCardSeries:
    """For each bucket, count distinct users with audit activity in the trailing 30 days
    ending at the bucket's right edge. Mirrors the live "Active Users" metric."""
    bucket_sql = _bucket_generate_series_sql(buckets)
    sql = f"""
        WITH bd AS (
          {bucket_sql}
        )
        SELECT
          bd.bucket_date::date AS bucket_date,
          COALESCE((
            SELECT COUNT(DISTINCT ae.user_id)::int
            FROM audit_events ae
            JOIN content_reviews cr ON cr.id = ae.review_id
            JOIN document_versions dv ON cr.document_version_id = dv.id
            JOIN documents d ON dv.document_id = d.id
            WHERE ae.user_id IS NOT NULL
              AND ae.created_at >= bd.next_bucket_date - INTERVAL '30 days'
              AND ae.created_at < bd.next_bucket_date
              AND dv.status <> 'skipped'
              AND d.organization_id = $1::uuid
          ), 0) AS value
        FROM bd
        ORDER BY bd.bucket_date
    """
    return await _cumulative_count_series(
        db, sql=sql, args=[organization_id], buckets=buckets
    )


async def _series_documents_created_per_bucket(
    db,
    organization_id: str,
    buckets: SeriesBuckets,
    *,
    submitter_id: Optional[str] = None,
) -> StatCardSeries:
    """Documents *newly* created in each bucket window."""
    bucket_sql = _bucket_generate_series_sql(buckets)
    submitter_clause = "AND d.submitted_by = $2::uuid" if submitter_id else ""
    args: list = [organization_id]
    if submitter_id:
        args.append(submitter_id)
    sql = f"""
        WITH bd AS (
          {bucket_sql}
        )
        SELECT
          bd.bucket_date::date AS bucket_date,
          COALESCE((
            SELECT COUNT(*)::int
            FROM documents d
            JOIN document_versions v ON d.current_version_id = v.id
            WHERE d.organization_id = $1::uuid
              AND v.status <> 'skipped'
              {submitter_clause}
              AND d.created_at >= bd.bucket_date
              AND d.created_at < bd.next_bucket_date
          ), 0) AS value
        FROM bd
        ORDER BY bd.bucket_date
    """
    return await _cumulative_count_series(
        db, sql=sql, args=args, buckets=buckets
    )


async def _series_high_risk_active(
    db, organization_id: str, buckets: SeriesBuckets
) -> StatCardSeries:
    """Active high-risk findings (cumulative open at end of bucket)."""
    bucket_sql = _bucket_generate_series_sql(buckets)
    sql = f"""
        WITH bd AS (
          {bucket_sql}
        )
        SELECT
          bd.bucket_date::date AS bucket_date,
          COALESCE((
            SELECT COUNT(*)::int
            FROM ai_findings af
            JOIN content_reviews cr ON cr.id = af.review_id
            JOIN document_versions dv ON cr.document_version_id = dv.id
            JOIN documents d ON dv.document_id = d.id
            WHERE d.organization_id = $1::uuid
              AND LOWER(COALESCE(af.risk_level, '')) = 'high'
              AND dv.status <> 'skipped'
              AND af.created_at < bd.next_bucket_date
              AND (af.resolved_at IS NULL OR af.resolved_at >= bd.next_bucket_date)
          ), 0) AS value
        FROM bd
        ORDER BY bd.bucket_date
    """
    try:
        return await _cumulative_count_series(
            db, sql=sql, args=[organization_id], buckets=buckets
        )
    except Exception:
        # Fallback if ai_findings has no resolved_at or risk_level column.
        return _empty_series(buckets)


async def _series_findings_pending_active(
    db, organization_id: str, buckets: SeriesBuckets
) -> StatCardSeries:
    """Distinct documents with open findings (pending) at the end of each bucket."""
    bucket_sql = _bucket_generate_series_sql(buckets)
    sql = f"""
        WITH bd AS (
          {bucket_sql}
        )
        SELECT
          bd.bucket_date::date AS bucket_date,
          COALESCE((
            SELECT COUNT(DISTINCT d.id)::int
            FROM ai_findings af
            JOIN content_reviews cr ON cr.id = af.review_id
            JOIN document_versions dv ON cr.document_version_id = dv.id
            JOIN documents d ON dv.document_id = d.id
            WHERE d.organization_id = $1::uuid
              AND dv.status <> 'skipped'
              AND af.created_at < bd.next_bucket_date
              AND af.status = 'pending'
          ), 0) AS value
        FROM bd
        ORDER BY bd.bucket_date
    """
    try:
        return await _cumulative_count_series(
            db, sql=sql, args=[organization_id], buckets=buckets
        )
    except Exception:
        return _empty_series(buckets)


async def _series_linkedin_posts_per_bucket(
    db, organization_id: str, buckets: SeriesBuckets
) -> StatCardSeries:
    """LinkedIn monitoring removed — empty series for API compatibility."""
    _ = (db, organization_id)
    return _empty_series(buckets)


async def _series_compliance_reviews_entered(
    db, organization_id: str, buckets: SeriesBuckets
) -> StatCardSeries:
    """Workflow steps that *entered* compliance_review per bucket window."""
    bucket_sql = _bucket_generate_series_sql(buckets)
    sql = f"""
        WITH bd AS (
          {bucket_sql}
        )
        SELECT
          bd.bucket_date::date AS bucket_date,
          COALESCE((
            SELECT COUNT(*)::int
            FROM workflow_steps ws
            JOIN workflows wf ON wf.id = ws.workflow_id
            JOIN content_reviews cr ON cr.id = wf.review_id
            JOIN document_versions dv ON cr.document_version_id = dv.id
            JOIN documents d ON dv.document_id = d.id
            WHERE d.organization_id = $1::uuid
              AND dv.status <> 'skipped'
              AND ws.stage = 'compliance_review'
              AND ws.claimed_at IS NOT NULL
              AND ws.claimed_at >= bd.bucket_date
              AND ws.claimed_at < bd.next_bucket_date
          ), 0) AS value
        FROM bd
        ORDER BY bd.bucket_date
    """
    try:
        return await _cumulative_count_series(
            db, sql=sql, args=[organization_id], buckets=buckets
        )
    except Exception:
        return _empty_series(buckets)


async def _series_sme_review_queue_snapshot(
    db,
    organization_id: str,
    user_id: Optional[str],
    roles: list[str],
    is_org_super_admin: bool,
    buckets: SeriesBuckets,
) -> StatCardSeries:
    """SME queue size at each bucket end.

    This reconstructs the workflow stage at each point in time from workflow_steps.
    A document counts for a bucket if its latest known stage before that bucket's
    right edge is ``sme_review``.
    """
    role_list = [str(r).lower() for r in roles if r]
    can_see_sme_queue = is_org_super_admin or "sme" in role_list
    if not can_see_sme_queue and not user_id:
        return _empty_series(buckets)

    bucket_sql = _bucket_generate_series_sql(buckets)
    sql = f"""
        WITH bd AS (
          {bucket_sql}
        )
        SELECT
          bd.bucket_date::date AS bucket_date,
          COALESCE((
            SELECT COUNT(DISTINCT d.id)::int
            FROM workflows wf
            JOIN content_reviews cr ON cr.id = wf.review_id
            JOIN document_versions dv ON cr.document_version_id = dv.id
            JOIN documents d ON dv.document_id = d.id
            LEFT JOIN LATERAL (
              SELECT ws.stage, ws.claimed_by, ws.completed_by
              FROM workflow_steps ws
              WHERE ws.workflow_id = wf.id
                AND ws.created_at < bd.next_bucket_date
              ORDER BY ws.created_at DESC, ws.step_order DESC
              LIMIT 1
            ) latest ON TRUE
            WHERE d.organization_id = $1::uuid
              AND dv.status <> 'skipped'
              AND wf.created_at < bd.next_bucket_date
              AND COALESCE(latest.stage, 'sme_review') = 'sme_review'
              AND (
                $3::bool IS TRUE
                OR $4::bool IS TRUE
                OR d.submitted_by = $2::uuid
                OR latest.claimed_by = $2::uuid
                OR latest.completed_by = $2::uuid
              )
          ), 0) AS value
        FROM bd
        ORDER BY bd.bucket_date
    """
    return await _cumulative_count_series(
        db,
        sql=sql,
        args=[organization_id, user_id, is_org_super_admin, can_see_sme_queue],
        buckets=buckets,
    )


async def _series_approval_rate_per_bucket(
    db,
    organization_id: str,
    buckets: SeriesBuckets,
    *,
    submitter_id: Optional[str] = None,
) -> StatCardSeries:
    """First-pass compliance approval rate (%) per bucket. Optional submitter filter."""
    bucket_sql = _bucket_generate_series_sql(buckets)
    submitter_clause = "AND d.submitted_by = $2::uuid" if submitter_id else ""
    args: list = [organization_id]
    if submitter_id:
        args.append(submitter_id)
    sql = f"""
        WITH bd AS (
          {bucket_sql}
        )
        SELECT
          bd.bucket_date::date AS bucket_date,
          COALESCE((
            WITH submitted_docs AS (
              SELECT d.id
              FROM documents d
              JOIN document_versions v ON d.current_version_id = v.id
              WHERE d.organization_id = $1::uuid
                AND d.created_at >= bd.bucket_date
                AND d.created_at < bd.next_bucket_date
                AND v.status <> 'skipped'
                {submitter_clause}
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
              WHERE rep.approval_timestamp >= bd.bucket_date
                AND rep.approval_timestamp < bd.next_bucket_date
            ),
            first_time_approved AS (
              SELECT DISTINCT fvr.document_id
              FROM first_version_reports fvr
              WHERE fvr.no_newer_versions
                AND LOWER(TRIM(COALESCE(fvr.compliance_status, ''))) IN ('pass', 'compliant')
            )
            SELECT
              CASE
                WHEN COUNT(sd.id) = 0 THEN 0.0
                ELSE 100.0 * (SELECT COUNT(*) FROM first_time_approved)::float / COUNT(sd.id)::float
              END
            FROM submitted_docs sd
          ), 0.0) AS value
        FROM bd
        ORDER BY bd.bucket_date
    """
    return await _cumulative_count_series(db, sql=sql, args=args, buckets=buckets)


async def _series_avg_approval_days_per_bucket(
    db,
    organization_id: str,
    buckets: SeriesBuckets,
    *,
    submitter_id: Optional[str] = None,
) -> StatCardSeries:
    """Avg days from review creation to approval, per bucket. Optional submitter filter."""
    bucket_sql = _bucket_generate_series_sql(buckets)
    submitter_clause = "AND d.submitted_by = $2::uuid" if submitter_id else ""
    args: list = [organization_id]
    if submitter_id:
        args.append(submitter_id)
    sql = f"""
        WITH bd AS (
          {bucket_sql}
        )
        SELECT
          bd.bucket_date::date AS bucket_date,
          COALESCE((
            SELECT AVG(EXTRACT(EPOCH FROM (rep.approval_timestamp - cr.created_at)) / 86400.0)
            FROM compliance_reports rep
            JOIN content_reviews cr ON cr.id = rep.review_id
            JOIN document_versions dv ON cr.document_version_id = dv.id
            JOIN documents d ON dv.document_id = d.id
            WHERE d.organization_id = $1::uuid
              AND dv.status <> 'skipped'
              {submitter_clause}
              AND rep.approval_timestamp >= bd.bucket_date
              AND rep.approval_timestamp < bd.next_bucket_date
          ), 0.0) AS value
        FROM bd
        ORDER BY bd.bucket_date
    """
    return await _cumulative_count_series(db, sql=sql, args=args, buckets=buckets)


async def _series_avg_review_days_per_bucket(
    db, organization_id: str, buckets: SeriesBuckets
) -> StatCardSeries:
    """Avg compliance-review step duration (days) per bucket."""
    bucket_sql = _bucket_generate_series_sql(buckets)
    sql = f"""
        WITH bd AS (
          {bucket_sql}
        )
        SELECT
          bd.bucket_date::date AS bucket_date,
          COALESCE((
            SELECT AVG(EXTRACT(EPOCH FROM (ws.completed_at - ws.claimed_at)) / 86400.0)
            FROM workflow_steps ws
            JOIN workflows wf ON wf.id = ws.workflow_id
            JOIN content_reviews cr ON cr.id = wf.review_id
            JOIN document_versions dv ON cr.document_version_id = dv.id
            JOIN documents d ON dv.document_id = d.id
            WHERE d.organization_id = $1::uuid
              AND dv.status <> 'skipped'
              AND ws.stage = 'compliance_review'
              AND ws.claimed_at IS NOT NULL
              AND ws.completed_at IS NOT NULL
              AND ws.completed_at >= bd.bucket_date
              AND ws.completed_at < bd.next_bucket_date
          ), 0.0) AS value
        FROM bd
        ORDER BY bd.bucket_date
    """
    try:
        return await _cumulative_count_series(
            db, sql=sql, args=[organization_id], buckets=buckets
        )
    except Exception:
        return _empty_series(buckets)


async def _series_avg_iterations_per_bucket(
    db,
    organization_id: str,
    buckets: SeriesBuckets,
    *,
    submitter_id: Optional[str] = None,
) -> StatCardSeries:
    """Avg workflow steps per cleared review, per bucket."""
    bucket_sql = _bucket_generate_series_sql(buckets)
    submitter_clause = "AND d.submitted_by = $2::uuid" if submitter_id else ""
    args: list = [organization_id]
    if submitter_id:
        args.append(submitter_id)
    sql = f"""
        WITH bd AS (
          {bucket_sql}
        )
        SELECT
          bd.bucket_date::date AS bucket_date,
          COALESCE((
            SELECT AVG(step_cnt)
            FROM (
              SELECT d.id, COUNT(v2.id)::int AS step_cnt
              FROM compliance_reports rep
              JOIN content_reviews cr ON cr.id = rep.review_id
              JOIN document_versions dv ON cr.document_version_id = dv.id
              JOIN documents d ON dv.document_id = d.id
              JOIN document_versions v2 ON v2.document_id = d.id
              WHERE d.organization_id = $1::uuid
                AND v2.status <> 'skipped'
                {submitter_clause}
                AND rep.approval_timestamp >= bd.bucket_date
                AND rep.approval_timestamp < bd.next_bucket_date
              GROUP BY d.id
            ) sub
          ), 0.0) AS value
        FROM bd
        ORDER BY bd.bucket_date
    """
    return await _cumulative_count_series(db, sql=sql, args=args, buckets=buckets)


def _bucket_generate_series_sql(buckets: SeriesBuckets) -> str:
    """Return a SQL fragment producing rows ``(bucket_date date, next_bucket_date date)``
    that align with the in-memory ``buckets`` (using a VALUES list for portability)."""
    rows = ", ".join(
        f"(DATE '{s.isoformat()}', DATE '{e.isoformat()}')"
        for s, e in zip(buckets.starts, buckets.ends)
    )
    if not rows:
        rows = "(DATE '1970-01-01', DATE '1970-01-02')"
    return (
        "SELECT bucket_date::date AS bucket_date, next_bucket_date::date AS next_bucket_date "
        f"FROM (VALUES {rows}) AS t(bucket_date, next_bucket_date)"
    )


# ────────────────────────── public API ──────────────────────────

async def attach_series_to_response(
    db,
    *,
    response: DashboardStatCardsResponse,
    resolved: ResolvedDashboardPeriod,
    organization_id: str,
    user_id: Optional[str] = None,
    roles: Optional[list[str]] = None,
    is_org_super_admin: bool = False,
) -> DashboardStatCardsResponse:
    """Mutate ``response`` in place: attach ``series`` to each card it knows about
    and synthesize a trend from the series when the role builder didn't provide one."""
    graph_buckets = compute_stat_card_graph_buckets()
    trend_buckets = await _trend_comparison_buckets(db, organization_id)
    role = (response.role or "").strip().lower()

    for card in response.cards:
        try:
            series = await _series_for_card(
                db,
                role=role,
                card=card,
                organization_id=organization_id,
                user_id=user_id,
                roles=roles or [],
                is_org_super_admin=is_org_super_admin,
                buckets=graph_buckets,
            )
        except Exception:
            series = None
        if series is None:
            # Fallback: flat at numeric value of card.value (or 0)
            series = _flat_series(graph_buckets, _safe_float(card.value))
        card.series = series

        try:
            trend_series = await _series_for_card(
                db,
                role=role,
                card=card,
                organization_id=organization_id,
                user_id=user_id,
                roles=roles or [],
                is_org_super_admin=is_org_super_admin,
                buckets=trend_buckets,
            )
        except Exception:
            trend_series = None
        if trend_series is None:
            trend_series = _flat_series(trend_buckets, _safe_float(card.value))
        computed = _compute_card_trend(card, trend_series)
        if computed is not None:
            card.trend = computed

    return response


def _compute_card_trend(card: StatCard, series: Optional[StatCardSeries] = None) -> Optional[StatCardTrend]:
    cid = (card.id or "").strip().lower()
    if cid in SKIP_TREND_CARDS:
        return None
    source = series or card.series
    if not source or not source.points:
        return None
    values = [p.value for p in source.points]
    if not values:
        return None

    if cid in SNAPSHOT_TREND_CARDS:
        baseline = values[0]
        current = values[-1]
    elif cid in COUNT_TREND_CARDS:
        baseline, current = _split_sum(values)
    elif cid in RATE_TREND_CARDS:
        baseline, current = _split_avg_nonzero(values)
    else:
        baseline, current = _split_avg_nonzero(values)

    pct = _pct_change(baseline, current)
    if pct is None:
        return None
    return _format_trend(pct)


def _split_sum(values: List[float]) -> tuple[float, float]:
    n = len(values)
    if n < 2:
        return (0.0, float(values[0]) if values else 0.0)
    mid = n // 2
    return (sum(values[:mid]), sum(values[mid:]))


def _split_avg_nonzero(values: List[float]) -> tuple[float, float]:
    n = len(values)
    if n < 2:
        return (0.0, float(values[0]) if values else 0.0)
    mid = n // 2

    def avg(xs: List[float]) -> float:
        nz = [x for x in xs if x and x > 0]
        return (sum(nz) / len(nz)) if nz else 0.0

    return (avg(values[:mid]), avg(values[mid:]))


def _pct_change(prev: float, current: float) -> Optional[float]:
    if prev is None or current is None:
        return None
    if prev == 0 and current == 0:
        return 0.0
    if prev == 0:
        return 100.0 if current > 0 else -100.0
    return round(((current - prev) / abs(prev)) * 100.0, 1)


def _format_trend(pct: float) -> StatCardTrend:
    sign = "+" if pct > 0 else ""
    if pct == int(pct):
        display = f"{sign}{int(pct)}%"
    else:
        display = f"{sign}{pct}%"
    direction: Literal["up", "down", "neutral"] = (
        "up" if pct > 0 else "down" if pct < 0 else "neutral"
    )
    return StatCardTrend(display=display, direction=direction)


def _safe_float(s: Any) -> float:
    try:
        if s is None:
            return 0.0
        text = str(s).replace(",", "").strip()
        if not text or text == "—":
            return 0.0
        # strip non-numeric trailing chars
        n = ""
        for c in text:
            if c.isdigit() or c in (".", "-"):
                n += c
            else:
                break
        return float(n) if n else 0.0
    except Exception:
        return 0.0


async def _series_for_card(
    db,
    *,
    role: str,
    card: StatCard,
    organization_id: str,
    user_id: Optional[str],
    roles: list[str],
    is_org_super_admin: bool,
    buckets: SeriesBuckets,
) -> Optional[StatCardSeries]:
    cid = (card.id or "").strip().lower()

    # Counts that have meaningful historical reconstruction
    if cid == "total_documents":
        return await _series_total_documents(db, organization_id, buckets)
    if cid == "active_users":
        return await _series_active_users_30d_trailing(db, organization_id, buckets)
    if cid == "high_risk":
        return await _series_high_risk_active(db, organization_id, buckets)
    if cid == "compliance":
        return await _series_findings_pending_active(db, organization_id, buckets)
    if cid == "linkedin_posts_monitored":
        return await _series_linkedin_posts_per_bucket(db, organization_id, buckets)
    if cid == "compliance_queue":
        return await _series_compliance_reviews_entered(db, organization_id, buckets)
    if cid == "pending_items":
        # Proxy: documents created per bucket by this user (volume of incoming work).
        submitter = user_id if role == "marketing" else None
        return await _series_documents_created_per_bucket(db, organization_id, buckets, submitter_id=submitter)

    # Rates / averages
    if cid == "approval_rate":
        # Marketing card filters to the user; superadmin/compliance org-wide.
        submitter = user_id if role == "marketing" else None
        return await _series_approval_rate_per_bucket(
            db, organization_id, buckets, submitter_id=submitter
        )
    if cid in ("avg_time_to_approval", "processing"):
        submitter = user_id if role == "marketing" else None
        return await _series_avg_approval_days_per_bucket(
            db, organization_id, buckets, submitter_id=submitter
        )
    if cid == "avg_time":
        return await _series_avg_review_days_per_bucket(db, organization_id, buckets)
    if cid == "iterations":
        submitter = user_id if role == "marketing" else None
        return await _series_avg_iterations_per_bucket(
            db, organization_id, buckets, submitter_id=submitter
        )

    if cid == "my_review_queue":
        return await _series_sme_review_queue_snapshot(
            db,
            organization_id,
            user_id,
            roles,
            is_org_super_admin,
            buckets,
        )

    return None
