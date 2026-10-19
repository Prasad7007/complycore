"""Helpers for resolving effective upload quota settings and rolling-window usage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


ROLLING_WINDOW_DAYS = 30
DEFAULT_UPLOAD_LIMIT_COUNT = 50
DEFAULT_UPLOAD_LIMIT_BYTES = 2 * 1024 * 1024 * 1024
QUOTA_BYPASS_ORG_SLUGS = {"legacy-default"}


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def organization_default_upload_quota(org_created_at: datetime | None) -> dict[str, Any]:
    rollout_starts_at = org_created_at or _utc_naive_now()
    return {
        "quota_enabled": True,
        "upload_limit_count": DEFAULT_UPLOAD_LIMIT_COUNT,
        "upload_limit_bytes": DEFAULT_UPLOAD_LIMIT_BYTES,
        "rollout_starts_at": rollout_starts_at,
    }


def _resolve_rollout_start(
    org_created_at: datetime | None,
    rollout_starts_at: datetime | None,
) -> datetime:
    default_rollout = organization_default_upload_quota(org_created_at)["rollout_starts_at"]
    configured_rollout = rollout_starts_at or default_rollout
    if org_created_at is None:
        return configured_rollout
    return max(org_created_at, configured_rollout)


def _coerce_window_start(
    as_of: datetime,
    org_created_at: datetime | None,
    rollout_starts_at: datetime | None,
) -> datetime | None:
    """Return the active rolling-window start, respecting org creation and rollout."""
    effective_rollout_start = _resolve_rollout_start(org_created_at, rollout_starts_at)
    if effective_rollout_start > as_of:
        return None
    return max(as_of - timedelta(days=ROLLING_WINDOW_DAYS), effective_rollout_start)


async def acquire_upload_quota_lock(db, organization_id: str) -> None:
    """Serialize quota-sensitive writes per organization."""
    await db.execute(
        "SELECT pg_advisory_xact_lock(hashtext('upload_quota'), hashtext($1))",
        organization_id,
    )


async def fetch_effective_upload_quota(db, organization_id: str) -> dict[str, Any]:
    """Return the effective upload quota config for an organization."""
    settings_row = await db.fetchrow(
        """
        SELECT
            org.slug AS organization_slug,
            org.created_at AS organization_created_at,
            s.id::text AS quota_settings_id,
            s.quota_enabled,
            s.upload_limit_count,
            s.upload_limit_bytes,
            s.rollout_starts_at,
            s.updated_at,
            s.updated_by
        FROM organizations org
        LEFT JOIN organization_upload_quota_settings s
            ON s.organization_id = org.id
        WHERE org.id = $1::uuid
        LIMIT 1
        """,
        organization_id,
    )
    if not settings_row:
        raise RuntimeError("organization is missing.")

    org_created_at = settings_row["organization_created_at"]
    defaults = organization_default_upload_quota(org_created_at)
    quota_enabled = (
        settings_row["quota_enabled"]
        if settings_row["quota_enabled"] is not None
        else defaults["quota_enabled"]
    )
    upload_limit_count = (
        settings_row["upload_limit_count"]
        if settings_row["upload_limit_count"] is not None
        else defaults["upload_limit_count"]
    )
    upload_limit_bytes = (
        settings_row["upload_limit_bytes"]
        if settings_row["upload_limit_bytes"] is not None
        else defaults["upload_limit_bytes"]
    )
    effective_rollout_start = _resolve_rollout_start(
        org_created_at,
        settings_row["rollout_starts_at"],
    )
    organization_slug = str(settings_row["organization_slug"] or "").strip().lower()
    bypass_active = organization_slug in QUOTA_BYPASS_ORG_SLUGS

    return {
        "organization_id": organization_id,
        "organization_slug": organization_slug,
        "organization_created_at": org_created_at,
        "quota_settings_id": settings_row["quota_settings_id"],
        "quota_enabled": bool(quota_enabled),
        "upload_limit_count": int(upload_limit_count),
        "upload_limit_bytes": int(upload_limit_bytes),
        "rolling_window_days": ROLLING_WINDOW_DAYS,
        "rollout_starts_at": effective_rollout_start,
        "updated_at": settings_row["updated_at"],
        "updated_by": str(settings_row["updated_by"]) if settings_row["updated_by"] else None,
        "bypass_active": bypass_active,
        "bypass_reason": "legacy_default_org" if bypass_active else None,
        "default_values": defaults,
    }


async def fetch_upload_quota_usage(
    db,
    organization_id: str,
    *,
    as_of: datetime | None = None,
    resolved_quota: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return rolling 30-day upload usage for an organization."""
    effective = resolved_quota or await fetch_effective_upload_quota(db, organization_id)
    point_in_time = as_of or _utc_naive_now()
    window_start = _coerce_window_start(
        point_in_time,
        effective.get("organization_created_at"),
        effective.get("rollout_starts_at"),
    )

    if window_start is None:
        return {
            "organization_id": organization_id,
            "organization_slug": effective.get("organization_slug"),
            "as_of": point_in_time,
            "window_start": None,
            "window_days": ROLLING_WINDOW_DAYS,
            "rollout_active": False,
            "bypass_active": bool(effective.get("bypass_active")),
            "upload_count_used": 0,
            "upload_bytes_used": 0,
        }

    usage_row = await db.fetchrow(
        """
        SELECT
            COUNT(*)::int AS upload_count_used,
            COALESCE(SUM(COALESCE(dv.file_size_bytes, 0)), 0)::bigint AS upload_bytes_used
        FROM document_versions dv
        JOIN documents d ON d.id = dv.document_id
        WHERE d.organization_id = $1::uuid
          AND dv.uploaded_at >= $2
          AND dv.uploaded_at <= $3
        """,
        organization_id,
        window_start,
        point_in_time,
    )

    return {
        "organization_id": organization_id,
        "organization_slug": effective.get("organization_slug"),
        "as_of": point_in_time,
        "window_start": window_start,
        "window_days": ROLLING_WINDOW_DAYS,
        "rollout_active": True,
        "bypass_active": bool(effective.get("bypass_active")),
        "upload_count_used": int(usage_row["upload_count_used"] or 0),
        "upload_bytes_used": int(usage_row["upload_bytes_used"] or 0),
    }


async def fetch_upload_quota_state(
    db,
    organization_id: str,
    *,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Return effective quota config plus current rolling-window usage."""
    effective = await fetch_effective_upload_quota(db, organization_id)
    usage = await fetch_upload_quota_usage(
        db,
        organization_id,
        as_of=as_of,
        resolved_quota=effective,
    )
    rollout_active = bool(usage["rollout_active"])

    count_remaining = max(0, int(effective["upload_limit_count"]) - int(usage["upload_count_used"]))
    bytes_remaining = max(0, int(effective["upload_limit_bytes"]) - int(usage["upload_bytes_used"]))

    return {
        "effective_quota": effective,
        "usage": usage,
        "enforcement": {
            "bypass_active": bool(effective.get("bypass_active")),
            "quota_enabled": bool(effective.get("quota_enabled")),
            "rollout_active": rollout_active,
            "should_enforce": (
                bool(effective.get("quota_enabled"))
                and rollout_active
                and not bool(effective.get("bypass_active"))
            ),
        },
        "remaining": {
            "upload_count_remaining": count_remaining,
            "upload_bytes_remaining": bytes_remaining,
        },
    }


async def evaluate_upload_quota_change(
    db,
    organization_id: str,
    *,
    incoming_upload_count: int = 0,
    incoming_upload_bytes: int = 0,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Return quota state plus projected usage after an incoming upload."""
    state = await fetch_upload_quota_state(db, organization_id, as_of=as_of)
    usage = state["usage"]
    effective = state["effective_quota"]
    should_enforce = bool(state["enforcement"]["should_enforce"])

    projected_upload_count = int(usage["upload_count_used"]) + max(0, int(incoming_upload_count))
    projected_upload_bytes = int(usage["upload_bytes_used"]) + max(0, int(incoming_upload_bytes))

    exceeds_count = projected_upload_count > int(effective["upload_limit_count"])
    exceeds_bytes = projected_upload_bytes > int(effective["upload_limit_bytes"])
    should_block = should_enforce and (exceeds_count or exceeds_bytes)

    return {
        **state,
        "incoming": {
            "upload_count": max(0, int(incoming_upload_count)),
            "upload_bytes": max(0, int(incoming_upload_bytes)),
        },
        "projected": {
            "upload_count_used": projected_upload_count,
            "upload_bytes_used": projected_upload_bytes,
        },
        "would_exceed": {
            "count": exceeds_count,
            "bytes": exceeds_bytes,
            "either": exceeds_count or exceeds_bytes,
        },
        "should_block": should_block,
    }
