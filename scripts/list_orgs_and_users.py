#!/usr/bin/env python3
"""
List all organizations and their members (from organization_users).

Also prints users with no org membership and, optionally, pending invites.

Usage:
    python scripts/list_orgs_and_users.py
    python scripts/list_orgs_and_users.py --include-invites
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
load_dotenv(_REPO_ROOT / ".env")
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def _normalize_database_url(url: str) -> str:
    if "+asyncpg" in url:
        return url.replace("+asyncpg", "")
    return url


def _global_roles_subquery() -> str:
    return """
        (
            SELECT COALESCE(STRING_AGG(r.name, ', ' ORDER BY r.name), '')
            FROM user_roles ur
            JOIN roles r ON ur.role_id = r.id
            WHERE ur.user_id = up.id
        )
    """


async def _list_orgs(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT id, name, slug, status, created_at
        FROM organizations
        ORDER BY name
        """
    )


async def _list_org_users(conn: asyncpg.Connection, org_id) -> list[asyncpg.Record]:
    return await conn.fetch(
        f"""
        SELECT
            up.email,
            up.full_name,
            up.is_active,
            ou.role_in_org,
            ou.is_owner,
            {_global_roles_subquery()} AS global_roles
        FROM organization_users ou
        JOIN user_profiles up ON ou.user_id = up.id
        WHERE ou.organization_id = $1
        ORDER BY up.email
        """,
        org_id,
    )


async def _list_users_without_org(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        f"""
        SELECT
            up.email,
            up.full_name,
            up.is_active,
            {_global_roles_subquery()} AS global_roles
        FROM user_profiles up
        WHERE NOT EXISTS (
            SELECT 1 FROM organization_users ou WHERE ou.user_id = up.id
        )
        ORDER BY up.email
        """
    )


async def _list_pending_invites(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT
            o.name AS org_name,
            o.slug AS org_slug,
            i.email,
            i.role_in_org,
            i.created_at,
            i.expires_at
        FROM organization_invites i
        JOIN organizations o ON i.organization_id = o.id
        WHERE i.accepted_at IS NULL
        ORDER BY o.name, i.email
        """
    )


def _print_user_line(
    *,
    email: str,
    full_name: str,
    is_active: bool,
    role_in_org: str | None,
    is_owner: bool | None,
    global_roles: str,
) -> None:
    active = "active" if is_active else "inactive"
    org_bits = []
    if role_in_org:
        org_bits.append(f"role_in_org={role_in_org}")
    if is_owner:
        org_bits.append("owner")
    org_part = f" ({', '.join(org_bits)})" if org_bits else ""
    roles_part = f" [global: {global_roles}]" if global_roles else ""
    print(f"    - {email} — {full_name} [{active}]{org_part}{roles_part}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="List organizations and their users.")
    parser.add_argument(
        "--include-invites",
        action="store_true",
        help="Also list pending organization invites (not yet accepted).",
    )
    args = parser.parse_args()

    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL is required (set it in .env).")

    conn = await asyncpg.connect(_normalize_database_url(DATABASE_URL))
    try:
        orgs = await _list_orgs(conn)
        print(f"=== Organizations ({len(orgs)}) ===\n")

        total_members = 0
        for org in orgs:
            users = await _list_org_users(conn, org["id"])
            total_members += len(users)
            created = org["created_at"].strftime("%Y-%m-%d") if org["created_at"] else "—"
            print(f"{org['name']} (slug={org['slug']}, status={org['status']}, created={created})")
            print(f"  members: {len(users)}")
            if not users:
                print("    (none)")
            else:
                for u in users:
                    _print_user_line(
                        email=u["email"],
                        full_name=u["full_name"],
                        is_active=u["is_active"],
                        role_in_org=u["role_in_org"],
                        is_owner=u["is_owner"],
                        global_roles=u["global_roles"] or "",
                    )
            print()

        unassigned = await _list_users_without_org(conn)
        print(f"=== Users without an organization ({len(unassigned)}) ===\n")
        if not unassigned:
            print("  (none)\n")
        else:
            for u in unassigned:
                _print_user_line(
                    email=u["email"],
                    full_name=u["full_name"],
                    is_active=u["is_active"],
                    role_in_org=None,
                    is_owner=None,
                    global_roles=u["global_roles"] or "",
                )
            print()

        if args.include_invites:
            invites = await _list_pending_invites(conn)
            print(f"=== Pending invites ({len(invites)}) ===\n")
            if not invites:
                print("  (none)\n")
            else:
                for inv in invites:
                    exp = (
                        inv["expires_at"].strftime("%Y-%m-%d")
                        if inv["expires_at"]
                        else "no expiry"
                    )
                    print(
                        f"  {inv['org_slug']} ({inv['org_name']}): "
                        f"{inv['email']} role={inv['role_in_org']} expires={exp}"
                    )
                print()

        print(
            f"Summary: {len(orgs)} org(s), {total_members} org membership(s), "
            f"{len(unassigned)} user(s) without org"
        )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
