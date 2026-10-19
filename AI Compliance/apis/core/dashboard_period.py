"""Parse and validate dashboard time windows (week / month / ytd / custom)."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import HTTPException


@dataclass(frozen=True)
class ResolvedDashboardPeriod:
    key: str
    custom_from: Optional[date] = None
    custom_to: Optional[date] = None
    custom_prev_from: Optional[date] = None
    custom_prev_to: Optional[date] = None


def resolve_dashboard_period(
    period: str,
    date_from: Optional[str],
    date_to: Optional[str],
) -> ResolvedDashboardPeriod:
    """
    Returns normalized period key and optional custom date bounds.
    For custom, also returns the comparison window of equal length immediately before date_from.
    """
    period_key = (period or "month").strip().lower()
    if period_key == "custom":
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
        n_days = (dt - df).days + 1
        prev_to = df - timedelta(days=1)
        prev_from = prev_to - timedelta(days=n_days - 1)
        return ResolvedDashboardPeriod(
            key="custom",
            custom_from=df,
            custom_to=dt,
            custom_prev_from=prev_from,
            custom_prev_to=prev_to,
        )
    if period_key not in ("week", "month", "ytd"):
        raise HTTPException(
            status_code=400,
            detail="Invalid period. Use week, month, ytd, or custom.",
        )
    return ResolvedDashboardPeriod(key=period_key)
