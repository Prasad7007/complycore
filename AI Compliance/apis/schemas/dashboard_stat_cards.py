"""Response models for GET /audit-trail/stat-cards."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class StatCardTrend(BaseModel):
    """Period-over-period hint for UI (badge / arrow)."""

    display: Optional[str] = Field(None, description="e.g. +12% vs prior window")
    direction: Literal["up", "down", "neutral"] = "neutral"


class StatCardInfo(BaseModel):
    """Info-button content shown in the card tooltip."""

    title: str
    desc: str
    calc: str


class StatSeriesPoint(BaseModel):
    """One bucket in the sparkline history of a stat card."""

    label: str = Field(..., description="Display label, e.g. 'Mar 15' or 'Mar 2026'")
    value: float = Field(..., description="Bucket value (count, percent, days, etc.)")
    date: str = Field(..., description="ISO date for the bucket (start of bucket)")


class StatCardSeries(BaseModel):
    """Historical sparkline data for one stat card."""

    bucket: Literal["day", "month"] = "day"
    points: List[StatSeriesPoint] = Field(default_factory=list)


class StatCard(BaseModel):
    """One dashboard tile."""

    id: str = Field(..., description="Stable key for frontend mapping")
    label: str
    value: str = Field(..., description="Pre-formatted main number for display")
    unit: Optional[str] = None
    description: str
    info: Optional[StatCardInfo] = None
    trend: Optional[StatCardTrend] = None
    series: Optional[StatCardSeries] = None


class DashboardStatCardsResponse(BaseModel):
    role: str
    period: str
    cards: List[StatCard]
