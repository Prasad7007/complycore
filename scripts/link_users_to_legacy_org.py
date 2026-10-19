#!/usr/bin/env python3
"""
Link users without organization_users to the legacy-default org (migration 0009).

- DATABASE_URL from env (loads .env from AI Compliance folder).
- Does not modify user_roles.
- One organization_users row per user; role_in_org derived from user_roles via priority.

  cd "AI Compliance"
  export DATABASE_URL="postgresql://user:pass@host:5432/dbname"
  DRY_RUN=1 python scripts/link_users_to_legacy_org.py   # preview
  python scripts/link_users_to_legacy_org.py             # apply

Env: LEGACY_ORG_SLUG (default legacy-default), SKIP_OWNER_ONLY (default 1),
     INCLUDE_OWNER_ONLY, DEFAULT_ROLE_IN_ORG (default marketing), DRY_RUN.
"""
from __future__ import annotations

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
LEGACY_ORG_SLUG = os.getenv("LEGACY_ORG_SLUG", "legacy-default").strip()
DRY_RUN = os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes")
SKIP_OWNER_ONLY = os.getenv("SKIP_OWNER_ONLY", "1").lower() in ("1", "true", "yes")
INCLUDE_OWNER_ONLY = os.getenv("INCLUDE_OWNER_ONLY", "").lower() in ("1", "true", "yes")
DEFAULT_ROLE_IN_ORG = os.getenv("DEFAULT_ROLE_IN_ORG", "marketing").strip()

_ROLE_PRIORITY: tuple[str, ...] = (
    "super_admin",
    "compliance",
    "sme",
    "marketing",
    # NOTE: 'owner' is a platform-level role only — never an org role.
)


def _pick_role_in_org(role_names: set[str]) -> tuple[str, bool]:
    # 'owner' is a platform role only — exclude it from org role assignment
    org_role_names = role_names - {"owner"}
    for name in _ROLE_PRIORITY:
        if name in org_role_names:
            return name, False
    if org_role_names:
        first = sorted(org_role_names)[0]
        return first, False
    return DEFAULT_ROLE_IN_ORG, False


async def main() -> int:
    if not DATABASE_URL:
        print("ERROR: Set DATABASE_URL", file=sys.stderr)
        return 1

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        org = await conn.fetchrow(
            "SELECT id, name, slug FROM organizations WHERE lower(slug) = lower($1) LIMIT 1",
            LEGACY_ORG_SLUG,
        )
        if not org:
            print(f"ERROR: No org slug={LEGACY_ORG_SLUG!r}. Run migration 0009 first.", file=sys.stderr)
            return 1

        org_id = org["id"]
        print(f"Target org: {org['name']}  slug={org['slug']}  id={org_id}")
        if DRY_RUN:
            print("DRY_RUN=1 — no inserts.\n")

        rows = await conn.fetch(
            """
            SELECT u.id AS user_id, u.email, u.full_name,
                   COALESCE(array_agg(r.name) FILTER (WHERE r.name IS NOT NULL), ARRAY[]::varchar[]) AS role_names
            FROM user_profiles u
            LEFT JOIN organization_users ou ON ou.user_id = u.id
            LEFT JOIN user_roles ur ON ur.user_id = u.id
            LEFT JOIN roles r ON r.id = ur.role_id
            WHERE ou.user_id IS NULL
            GROUP BY u.id, u.email, u.full_name
            ORDER BY lower(u.email)
            """
        )

        if not rows:
            print("No users without org membership.")
            return 0

        inserted = 0
        skipped = 0

        for row in rows:
            user_id = row["user_id"]
            email = row["email"]
            role_names = set(row["role_names"] or [])

            if SKIP_OWNER_ONLY and not INCLUDE_OWNER_ONLY:
                if role_names and role_names <= {"owner"}:
                    print(f"SKIP owner-only: {email}  user_id={user_id}")
                    skipped += 1
                    continue

            role_in_org, is_owner = _pick_role_in_org(role_names)

            if DRY_RUN:
                print(
                    f"Would insert: {email}  user_id={user_id}  "
                    f"role_names={sorted(role_names)} -> role_in_org={role_in_org!r}  is_owner={is_owner}"
                )
                inserted += 1
                continue

            await conn.execute(
                """
                INSERT INTO organization_users (id, organization_id, user_id, role_in_org, is_owner, created_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
                """,
                uuid.uuid4(),
                org_id,
                user_id,
                role_in_org,
                is_owner,
            )
            print(f"INSERTED: {email}  role_in_org={role_in_org!r}  is_owner={is_owner}")
            inserted += 1

        print(f"\nDone. inserted={inserted}  skipped={skipped}  dry_run={DRY_RUN}")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))