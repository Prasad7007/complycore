"""Map raw dashboard aggregates into role-specific stat card lists."""

from typing import Any, Literal, Optional

from apis.schemas.dashboard_stat_cards import (
    DashboardStatCardsResponse,
    StatCard,
    StatCardInfo,
    StatCardTrend,
)


def _trend_from_pct(pct: Optional[str]) -> Optional[StatCardTrend]:
    if pct is None:
        return None
    p = pct.strip()
    if p.startswith("+"):
        direction: Literal["up", "down", "neutral"] = "up"
    elif p.startswith("-"):
        direction = "down"
    else:
        direction = "neutral"
    return StatCardTrend(display=pct, direction=direction)


def _trend_from_pct_number(pct: Optional[float]) -> Optional[StatCardTrend]:
    if pct is None:
        return None
    sign = "+" if pct >= 0 else ""
    rendered = f"{sign}{int(pct)}%" if pct == int(pct) else f"{sign}{pct}%"
    direction: Literal["up", "down", "neutral"] = "neutral"
    if pct > 0:
        direction = "up"
    elif pct < 0:
        direction = "down"
    return StatCardTrend(display=rendered, direction=direction)


def _fmt_float_1(x: float) -> str:
    return f"{x:.1f}"


def _fmt_days(x: float) -> str:
    if x <= 0:
        return "0.0"
    if x < 0.1:
        # Show 2 decimal places for very small numbers
        val = f"{x:.2f}"
        if val == "0.00":
            return f"{x:.3f}" if x >= 0.001 else "0.001"
        return val
    return f"{x:.1f}"


def build_marketing_stat_cards(
    pending_count: int,
    submitter_metrics: dict[str, Any],
    *,
    period: str,
) -> DashboardStatCardsResponse:
    """Marketing persona cards (aligned with HTML mock labels)."""
    n = int(submitter_metrics.get("reports_in_window") or 0)
    avg_days = float(submitter_metrics.get("avg_days_to_approval") or 0.0)
    avg_steps = float(submitter_metrics.get("avg_workflow_steps") or 0.0)
    rate = submitter_metrics.get("first_time_approval_rate_pct")

    cards = [
        StatCard(
            id="pending_items",
            label="Pending Items",
            value=str(pending_count),
            description="Documents awaiting review",
            info=StatCardInfo(
                title="Pending Items",
                desc="Total number of documents currently in your queue awaiting submission or approval.",
                calc="Count of all documents with status: Draft, In Review, or Pending Approval",
            ),
            trend=None,
        ),
        StatCard(
            id="avg_time_to_approval",
            label="Avg Time to Approval",
            value=_fmt_days(avg_days) if n else "—",
            unit="days",
            description="Submission to approval",
            info=StatCardInfo(
                title="Average Time to Approval",
                desc="The average number of days from document submission to final approval.",
                calc="Sum of (Approval Date - Submission Date) / Total Documents Approved (Last 30 Days)",
            ),
            trend=None,
        ),
        StatCard(
            id="iterations",
            label="Iterations",
            value=_fmt_float_1(avg_steps) if n else "—",
            description="Revision cycles",
            info=StatCardInfo(
                title="Iterations per Document",
                desc="Average number of revision rounds required before final approval.",
                calc="Total Review Cycles / Total Documents Approved (Last 30 Days)",
            ),
            trend=None,
        ),
        StatCard(
            id="approval_rate",
            label="Approval Rate",
            value=str(rate) if rate is not None else "—",
            unit="%" if rate is not None else None,
            description="First-time approvals",
            info=StatCardInfo(
                title="First-Time Approval Rate",
                desc="Percentage of documents approved on the first submission without revisions.",
                calc="(Documents Approved First Time / Total Documents Submitted) × 100",
            ),
            trend=None,
        ),
    ]
    return DashboardStatCardsResponse(role="marketing", period=period, cards=cards)


def build_sme_stat_cards(queue_count: int, *, period: str) -> DashboardStatCardsResponse:
    cards = [
        StatCard(
            id="my_review_queue",
            label="My Review Queue",
            value=str(queue_count),
            description="Documents assigned to you",
            info=StatCardInfo(
                title="My Review Queue",
                desc="Documents currently assigned to you for subject matter expert review.",
                calc="Count of documents with status: Assigned to You & Pending Review",
            ),
            trend=None,
        ),
    ]
    return DashboardStatCardsResponse(role="sme", period=period, cards=cards)


def build_superadmin_stat_cards(
    aggregates: dict[str, Any],
    *,
    total_documents: int,
    active_users_30d: int,
    superadmin_metrics: dict[str, Any],
    period: str,
) -> DashboardStatCardsResponse:
    """Org-scoped superadmin cards aligned with HTML mock labels."""
    t = aggregates["trends"]
    approval_rate = superadmin_metrics.get("approval_rate_pct")
    processing_days = float(superadmin_metrics.get("processing_days") or 0.0)
    compliance_active_flags = int(superadmin_metrics.get("compliance_active_flags") or 0)
    cards = [
        StatCard(
            id="total_documents",
            label="Total Documents",
            value=str(total_documents),
            description="All documents across platform",
            info=StatCardInfo(
                title="Total Documents",
                desc="Complete count of all documents in the system across all teams and statuses.",
                calc="Sum of all documents: Draft + In Review + Approved + Archived",
            ),
            trend=None,
        ),
        StatCard(
            id="active_users",
            label="Active Users",
            value=str(active_users_30d),
            description="Last 30 days",
            info=StatCardInfo(
                title="Active Users",
                desc="Users who have logged in and performed actions in the last 30 days.",
                calc="Count of users with activity (login, review, approval, comment) in last 30 days",
            ),
            trend=None,
        ),
        StatCard(
            id="approval_rate",
            label="Approval Rate",
            value=str(approval_rate) if approval_rate is not None else "—",
            unit="%" if approval_rate is not None else None,
            description="First-time approvals",
            info=StatCardInfo(
                title="First-Time Approval Rate",
                desc="Percentage of documents approved on their first version across all teams.",
                calc="(First-time Approved Documents / Total Documents Submitted) × 100 (Last 30 Days)",
            ),
            trend=None,
        ),
        StatCard(
            id="processing",
            label="Processing",
            value=_fmt_days(processing_days),
            unit="days",
            description="Avg time",
            info=StatCardInfo(
                title="Average Processing Time",
                desc="Platform-wide average time from submission to final approval or rejection.",
                calc="Sum of (Final Status Date - Submission Date) / Total Processed Documents",
            ),
            trend=None,
        ),
        StatCard(
            id="compliance",
            label="Compliance",
            value=str(compliance_active_flags),
            description="Active flags",
            info=StatCardInfo(
                title="Active Compliance Flags",
                desc="Documents currently flagged for compliance issues requiring resolution.",
                calc="Count of distinct documents with open findings (Finding Status = Pending)",
            ),
            trend=None,
        ),
    ]
    return DashboardStatCardsResponse(role="superadmin", period=period, cards=cards)


def build_compliance_stat_cards(
    aggregates: dict[str, Any],
    compliance_metrics: dict[str, Any],
    *,
    period: str,
) -> DashboardStatCardsResponse:
    """Compliance cards aligned with HTML mock labels."""
    t = aggregates["trends"]
    approval_rate = compliance_metrics.get("approval_rate_pct")
    avg_days = float(compliance_metrics.get("avg_review_days") or 0.0)
    avg_iterations = float(compliance_metrics.get("avg_iterations") or 0.0)
    cards = [
        StatCard(
            id="compliance_queue",
            label="Compliance Queue",
            value=str(compliance_metrics["compliance_queue"]),
            description="Documents awaiting review",
            info=StatCardInfo(
                title="Compliance Queue",
                desc="Documents requiring compliance review for regulatory adherence and risk assessment.",
                calc="Count of documents flagged for compliance review across all risk levels",
            ),
            trend=_trend_from_pct(t.get("documents_under_review")),
        ),
#         StatCard(
#             id="linkedin_posts_monitored",
#             label="LinkedIn Monitoring",
#             value=str(compliance_metrics["linkedin_posts_in_window"]),
#             description="Posts monitored in selected period",
#             info=StatCardInfo(
#                 title="LinkedIn Monitoring",
#                 desc="Social media posts from company employees monitored for compliance with brand guidelines and regulations.",
#                 calc="Total posts tracked from connected LinkedIn accounts in the selected dashboard window",
#             ),
#             trend=_trend_from_pct_number(compliance_metrics.get("linkedin_trend_pct")),
#         ),
        StatCard(
            id="avg_time",
            label="Avg Time",
            value=_fmt_days(avg_days),
            unit="days",
            description="Review timeline",
            info=StatCardInfo(
                title="Average Review Time",
                desc="Average days to complete compliance review from assignment to decision.",
                calc="Sum of (Review Complete Date - Assignment Date) / Total Reviews (Last 30 Days)",
            ),
            trend=None,
        ),
        StatCard(
            id="approval_rate",
            label="Approval Rate",
            value=str(approval_rate) if approval_rate is not None else "—",
            unit="%" if approval_rate is not None else None,
            description="First-time",
            info=StatCardInfo(
                title="Compliance Approval Rate",
                desc="Percentage of documents approved on their first version without requiring a second review.",
                calc="(Documents Approved First Review / Total Documents Reviewed) × 100",
            ),
            trend=None,
        ),
        StatCard(
            id="high_risk",
            label="High Risk",
            value=str(aggregates["high_risk_flags"]),
            description="Active issues",
            info=StatCardInfo(
                title="High Risk Items",
                desc="Documents flagged as high risk requiring immediate attention and senior review.",
                calc="Count of documents with Risk Level = High & Status = Active",
            ),
            trend=_trend_from_pct(t.get("high_risk_flags")),
        ),
        StatCard(
            id="iterations",
            label="Iterations",
            value=_fmt_float_1(avg_iterations),
            description="Revision cycles",
            info=StatCardInfo(
                title="Compliance Iterations",
                desc="Average number of review cycles before compliance clearance.",
                calc="Total Compliance Review Cycles / Total Documents Cleared (Last 30 Days)",
            ),
            trend=None,
        ),
    ]
    return DashboardStatCardsResponse(role="compliance", period=period, cards=cards)
