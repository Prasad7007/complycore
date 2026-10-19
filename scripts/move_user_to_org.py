#!/usr/bin/env python3
"""
Move a user to a different organization by updating organization_users.

This is the safer alternative to deleting/recreating the user when the goal is
simply to place the same login in another org. It does not touch Cognito,
user_profiles, or user_roles.

Usage:
    python "scripts/move_user_to_org.py" --email user@example.com --org-slug other-org --dry-run
    python "scripts/move_user_to_org.py" --email user@example.com --org-slug other-org
    python "scripts/move_user_to_org.py" --email user@example.com --clear-org --dry-run
    python "scripts/move_user_to_org.py" --email user@example.com --clear-org

Optional:
    --role-in-org marketing|sme|compliance|super_admin|owner
    If omitted, the script keeps the current role_in_org when possible, else
    derives it from the user's DB roles.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
load_dotenv(_REPO_ROOT / ".env")
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# NOTE: 'owner' is a platform-level role only — never a valid org role.
ROLE_PRIORITY: tuple[str, ...] = (
    "super_admin",
    "compliance",
    "sme",
    "marketing",
)
VALID_ROLE_IN_ORG = set(ROLE_PRIORITY)


def _normalize_database_url(url: str) -> str:
    if "+asyncpg" in url:
        return url.replace("+asyncpg", "")
    return url


def _derive_role_in_org(db_roles: list[str], current_role_in_org: str | None) -> str:
    current = (current_role_in_org or "").strip().lower()
    if current in VALID_ROLE_IN_ORG:  # 'owner' is already excluded from VALID_ROLE_IN_ORG
        return current
    # Exclude platform 'owner' role from org role derivation
    lowered = {str(r).strip().lower() for r in db_roles if str(r).strip()} - {"owner"}
    for role_name in ROLE_PRIORITY:
        if role_name in lowered:
            return role_name
    return "marketing"


async def _fetch_user(conn, email: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT
            u.id::text AS user_id,
            u.email,
            u.full_name,
            u.is_active,
            ou.id::text AS organization_user_id,
            ou.organization_id::text AS current_org_id,
            o.slug AS current_org_slug,
            ou.role_in_org,
            ou.is_owner,
            COALESCE(array_agg(DISTINCT r.name) FILTER (WHERE r.name IS NOT NULL), ARRAY[]::varchar[]) AS db_roles
        FROM user_profiles u
        LEFT JOIN organization_users ou ON ou.user_id = u.id
        LEFT JOIN organizations o ON o.id = ou.organization_id
        LEFT JOIN user_roles ur ON ur.user_id = u.id
        LEFT JOIN roles r ON r.id = ur.role_id
        WHERE lower(u.email) = lower($1)
        GROUP BY
            u.id, u.email, u.full_name, u.is_active,
            ou.id, ou.organization_id, o.slug, ou.role_in_org, ou.is_owner
        LIMIT 1
        """,
        email,
    )


async def _fetch_target_org(conn, org_slug: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT id::text AS org_id, slug, name
        FROM organizations
        WHERE lower(slug) = lower($1)
        LIMIT 1
        """,
        org_slug,
    )


async def _fetch_activity_summary(conn, user_id: str) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        SELECT
            (SELECT COUNT(*)::int FROM documents WHERE submitted_by = $1::uuid) AS submitted_documents,
            (SELECT COUNT(*)::int FROM workflows WHERE assigned_to = $1::uuid) AS assigned_workflows,
            (SELECT COUNT(*)::int FROM workflow_steps WHERE claimed_by = $1::uuid OR completed_by = $1::uuid) AS workflow_step_refs,
            (SELECT COUNT(*)::int FROM content_comments WHERE author_id = $1::uuid) AS comments_authored,
            (SELECT COUNT(*)::int FROM audit_events WHERE user_id = $1::uuid) AS audit_event_refs,
            (SELECT COUNT(*)::int FROM compliance_reports WHERE approval_authority = $1::uuid) AS compliance_reports
        """,
        user_id,
    )


async def _is_demo_seed_user(conn, email: str) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT 1
            FROM user_profiles
            WHERE lower(email) = lower($1)
              AND lower(email) IN (
                'marketing@company.com',
                'sme@company.com',
                'compliance@company.com',
                'superadmin@company.com',
                'profile@company.com'
              )
            LIMIT 1
            """,
            email,
        )
    )


def _print_user(row: asyncpg.Record) -> None:
    print(
        "user status=found "
        f"user_id={row['user_id']} "
        f"email={row['email']} "
        f"full_name={row['full_name']!r} "
        f"is_active={bool(row['is_active'])} "
        f"current_org_slug={row['current_org_slug']!r} "
        f"role_in_org={row['role_in_org']!r} "
        f"is_owner={bool(row['is_owner'])} "
        f"db_roles={list(row['db_roles'] or [])}"
    )


def _print_activity(summary: asyncpg.Record) -> None:
    print(
        "activity_summary "
        f"submitted_documents={summary['submitted_documents']} "
        f"assigned_workflows={summary['assigned_workflows']} "
        f"workflow_step_refs={summary['workflow_step_refs']} "
        f"comments_authored={summary['comments_authored']} "
        f"audit_event_refs={summary['audit_event_refs']} "
        f"compliance_reports={summary['compliance_reports']}"
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description="Move a user to a different org without deleting them.")
    parser.add_argument("--email", required=True, help="User email to move.")
    parser.add_argument("--org-slug", help="Target organization slug.")
    parser.add_argument(
        "--clear-org",
        action="store_true",
        help="Remove the user's org membership entirely so they can later accept an invite.",
    )
    parser.add_argument(
        "--role-in-org",
        help="Optional target role_in_org. Defaults to current role_in_org or derived DB role.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview only.")
    args = parser.parse_args()

    if not DATABASE_URL:
        print("ERROR: DATABASE_URL is required.", file=sys.stderr)
        return 1

    email = args.email.strip().lower()
    org_slug = (args.org_slug or "").strip().lower()
    clear_org = bool(args.clear_org)
    requested_role = (args.role_in_org or "").strip().lower()
    dry_run = bool(args.dry_run)

    if clear_org and org_slug:
        print("ERROR: Use either --org-slug or --clear-org, not both.", file=sys.stderr)
        return 1
    if not clear_org and not org_slug:
        print("ERROR: Provide --org-slug or use --clear-org.", file=sys.stderr)
        return 1

    if requested_role and requested_role not in VALID_ROLE_IN_ORG:
        print(
            "ERROR: --role-in-org must be one of "
            + ", ".join(sorted(VALID_ROLE_IN_ORG)),
            file=sys.stderr,
        )
        return 1

    conn = await asyncpg.connect(_normalize_database_url(DATABASE_URL))
    try:
        user = await _fetch_user(conn, email)
        if not user:
            print(f"user status=not_found email={email}")
            return 1
        _print_user(user)

        is_demo_seed = await _is_demo_seed_user(conn, email)
        if is_demo_seed:
            print(
                "warning=demo_seed_user "
                "detail=Seed demo emails may be auto-linked back to the default org by /users/me when no org row exists."
            )

        target_org = None
        derived_role = requested_role or _derive_role_in_org(list(user["db_roles"] or []), user["role_in_org"])
        target_is_owner = False  # 'owner' is a platform role only, never an org role
        if not clear_org:
            target_org = await _fetch_target_org(conn, org_slug)
            if not target_org:
                print(f"target_org status=not_found slug={org_slug}")
                return 1
            print(
                "target_org status=found "
                f"org_id={target_org['org_id']} "
                f"slug={target_org['slug']} "
                f"name={target_org['name']!r}"
            )

        summary = await _fetch_activity_summary(conn, str(user["user_id"]))
        _print_activity(summary)

        if clear_org and not user["organization_user_id"]:
            print(
                "move_user status=noop "
                f"email={email} reason=no_org_membership_to_clear"
            )
            return 0

        if not clear_org and user["current_org_slug"] and str(user["current_org_slug"]).strip().lower() == org_slug:
            print(
                "move_user status=noop "
                f"email={email} org_slug={org_slug} role_in_org={derived_role} reason=already_in_target_org"
            )
            return 0

        if clear_org:
            print(
                "move_user plan "
                f"email={email} "
                f"from_org={user['current_org_slug']!r} "
                "to_org=None "
                f"dry_run={dry_run}"
            )
        else:
            print(
                "move_user plan "
                f"email={email} "
                f"from_org={user['current_org_slug']!r} "
                f"to_org={target_org['slug']!r} "
                f"role_in_org={derived_role!r} "
                f"is_owner={target_is_owner} "
                f"dry_run={dry_run}"
            )

        if dry_run:
            if clear_org:
                print("hint=Historical rows remain as-is; only the organization_users row would be deleted.")
            else:
                print("hint=Historical documents/audit rows remain as-is; only organization_users is changed.")
            return 0

        async with conn.transaction():
            if clear_org:
                await conn.execute(
                    "DELETE FROM organization_users WHERE id = $1::uuid",
                    str(user["organization_user_id"]),
                )
                print(
                    "organization_user status=deleted "
                    f"id={user['organization_user_id']}"
                )
            elif user["organization_user_id"]:
                await conn.execute(
                    """
                    UPDATE organization_users
                    SET organization_id = $1::uuid, role_in_org = $2, is_owner = $3
                    WHERE id = $4::uuid
                    """,
                    str(target_org["org_id"]),
                    derived_role,
                    target_is_owner,
                    str(user["organization_user_id"]),
                )
                print(
                    "organization_user status=updated "
                    f"id={user['organization_user_id']} "
                    f"new_org_slug={target_org['slug']} "
                    f"role_in_org={derived_role!r}"
                )
            else:
                link_id = str(uuid.uuid4())
                await conn.execute(
                    """
                    INSERT INTO organization_users (id, organization_id, user_id, role_in_org, is_owner, created_at)
                    VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, NOW())
                    """,
                    link_id,
                    str(target_org["org_id"]),
                    str(user["user_id"]),
                    derived_role,
                    target_is_owner,
                )
                print(
                    "organization_user status=created "
                    f"id={link_id} "
                    f"new_org_slug={target_org['slug']} "
                    f"role_in_org={derived_role!r}"
                )

        if clear_org:
            print(
                "move_user status=success "
                f"email={email} "
                "org_slug=None"
            )
        else:
            print(
                "move_user status=success "
                f"email={email} "
                f"org_slug={target_org['slug']} "
                f"role_in_org={derived_role!r}"
            )
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
