#!/usr/bin/env python3
"""
Initialize a fresh Postgres database for ComplyCore (client / prod handover).

What it does
------------
1. Reads DATABASE_URL from AI Compliance/.env.docker
2. Runs Alembic migrations to head (creates/updates schema)
3. Seeds roles, permissions, role_permissions, and compliance rules

What it does NOT do
-------------------
- Create Cognito users or the first org admin
  (use POST /orgs/bootstrap or scripts/bootstrap_owner.py after this)
- Drop or wipe an existing database

Usage
-----
From the AI Compliance directory (local):

  # Set DATABASE_URL in AI Compliance/.env.docker
  python init_database.py

  python init_database.py --migrate-only
  python init_database.py --seed-only

Via Docker Compose (Compose injects .env.docker via env_file):

  docker-compose run --no-deps --rm api python init_database.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

_AI_ROOT = Path(__file__).resolve().parent
_ENV_DOCKER = _AI_ROOT / ".env.docker"

if not (os.getenv("DATABASE_URL") or "").strip():
    if not _ENV_DOCKER.exists():
        print(f"ERROR: Missing {_ENV_DOCKER}")
        print("Create it with DATABASE_URL=postgresql://user:password@host:5432/dbname")
        sys.exit(1)
    load_dotenv(_ENV_DOCKER, override=True)


def _get_database_url() -> str:
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        print(
            "ERROR: DATABASE_URL is not set.\n"
            f"Add it to {_ENV_DOCKER}, for example:\n"
            "  DATABASE_URL=postgresql://user:password@host:5432/ai_compliance?sslmode=require"
        )
        sys.exit(1)
    return url.replace("postgresql+asyncpg://", "postgresql://").replace("+asyncpg", "")


def _redact_url(url: str) -> str:
    """Hide password in logs."""
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" not in rest:
        return url
    creds, hostpart = rest.rsplit("@", 1)
    if ":" in creds:
        user = creds.split(":", 1)[0]
        return f"{scheme}://{user}:***@{hostpart}"
    return f"{scheme}://***@{hostpart}"


def run_migrations() -> None:
    print("\n=== 1/2 Alembic migrations (upgrade head) ===")
    env = os.environ.copy()
    env["DATABASE_URL"] = _get_database_url()
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(_AI_ROOT),
        env=env,
        check=False,
    )
    if result.returncode != 0:
        print("ERROR: alembic upgrade head failed.")
        sys.exit(result.returncode)
    print("Migrations applied successfully.")


async def run_seed() -> None:
    print("\n=== 2/2 Seed reference data ===")
    os.environ["DATABASE_URL"] = _get_database_url()
    from seed_db import seed

    # Schema comes from Alembic — never re-run schema.sql here.
    await seed(skip_schema=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate + seed a ComplyCore database (safe for a new empty DB)."
    )
    parser.add_argument(
        "--migrate-only",
        action="store_true",
        help="Only run alembic upgrade head",
    )
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help="Only seed roles/permissions/rules (schema must already exist)",
    )
    args = parser.parse_args()
    if args.migrate_only and args.seed_only:
        print("ERROR: use only one of --migrate-only or --seed-only")
        sys.exit(2)

    url = _get_database_url()
    print(f"Source: {_ENV_DOCKER.name} (or Compose env_file)")
    print(f"Target database: {_redact_url(url)}")
    print(f"Working directory: {_AI_ROOT}")

    if not args.seed_only:
        run_migrations()
    if not args.migrate_only:
        asyncio.run(run_seed())

    print("\n[SUCCESS] Database is ready.")
    print("Next steps:")
    print("  - Create the first organization admin via the app bootstrap flow, or")
    print("  - Run: python scripts/bootstrap_owner.py --email admin@example.com")
    print("    (from the repo root; requires Cognito env vars)")


if __name__ == "__main__":
    main()
