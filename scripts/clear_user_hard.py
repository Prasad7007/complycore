#!/usr/bin/env python3
"""
Hard-delete a single user from the local database and Cognito.

This script is intentionally conservative:
- Resolves the user by email
- Supports --dry-run preview
- Refuses hard deletion when the user still owns blocking records such as
  submitted documents, compliance approvals, or monitored profiles

Usage:
    python "scripts/clear_user_hard.py" --email user@example.com --dry-run
    python "scripts/clear_user_hard.py" --email user@example.com
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import asyncpg
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
load_dotenv(_REPO_ROOT / ".env")
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
AWS_REGION = os.getenv("AWS_REGION", "").strip()
COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "").strip()


def _normalize_database_url(url: str) -> str:
    if "+asyncpg" in url:
        return url.replace("+asyncpg", "")
    return url


def _get_attr(user: dict, name: str) -> str | None:
    for attr in user.get("Attributes") or []:
        if attr.get("Name") == name:
            value = attr.get("Value")
            return str(value) if value is not None else None
    return None


def _get_cognito_users_by_email(cognito_client, email: str) -> list[dict]:
    response = cognito_client.list_users(
        UserPoolId=COGNITO_USER_POOL_ID,
        Filter=f'email = "{email}"',
        Limit=20,
    )
    matched: list[dict] = []
    for user in response.get("Users") or []:
        attr_email = (_get_attr(user, "email") or "").strip().lower()
        if attr_email == email:
            matched.append(user)
    return matched


async def _fetch_db_user(conn, email: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT
            u.id::text AS user_id,
            u.email,
            u.full_name,
            u.cognito_sub,
            u.department,
            u.is_active,
            o.slug AS org_slug,
            ou.role_in_org,
            COALESCE(array_agg(DISTINCT r.name) FILTER (WHERE r.name IS NOT NULL), ARRAY[]::varchar[]) AS roles
        FROM user_profiles u
        LEFT JOIN organization_users ou ON ou.user_id = u.id
        LEFT JOIN organizations o ON o.id = ou.organization_id
        LEFT JOIN user_roles ur ON ur.user_id = u.id
        LEFT JOIN roles r ON r.id = ur.role_id
        WHERE lower(u.email) = lower($1)
        GROUP BY u.id, u.email, u.full_name, u.cognito_sub, u.department, u.is_active, o.slug, ou.role_in_org
        LIMIT 1
        """,
        email,
    )


async def _fetch_db_usage_summary(conn, user_id: str) -> asyncpg.Record:
    return await conn.fetchrow(
        """
        SELECT
            (SELECT COUNT(*)::int FROM organization_users WHERE user_id = $1::uuid) AS organization_links,
            (SELECT COUNT(*)::int FROM user_roles WHERE user_id = $1::uuid) AS role_links,
            (SELECT COUNT(*)::int FROM notifications WHERE user_id = $1::uuid) AS notifications,
            (SELECT COUNT(*)::int FROM content_comments WHERE author_id = $1::uuid) AS comments_authored,
            (SELECT COUNT(*)::int FROM ai_feedback WHERE user_id = $1::uuid) AS ai_feedback_rows,
            (SELECT COUNT(*)::int FROM workflow_steps WHERE claimed_by = $1::uuid OR completed_by = $1::uuid) AS workflow_step_refs,
            (SELECT COUNT(*)::int FROM audit_events WHERE user_id = $1::uuid) AS audit_event_refs,
            (SELECT COUNT(*)::int FROM workflows WHERE assigned_to = $1::uuid) AS assigned_workflows,
            (SELECT COUNT(*)::int FROM documents WHERE submitted_by = $1::uuid) AS submitted_documents,
            (SELECT COUNT(*)::int FROM compliance_reports WHERE approval_authority = $1::uuid) AS compliance_reports,
            (SELECT COUNT(*)::int FROM monitored_profiles WHERE added_by = $1::uuid) AS monitored_profiles
        """,
        user_id,
    )


def _print_db_user(row: asyncpg.Record | None) -> None:
    if not row:
        print("db_user status=not_found")
        return
    print(
        "db_user status=found "
        f"user_id={row['user_id']} "
        f"email={row['email']} "
        f"full_name={row['full_name']!r} "
        f"department={row['department']!r} "
        f"is_active={bool(row['is_active'])} "
        f"org_slug={row['org_slug']!r} "
        f"role_in_org={row['role_in_org']!r} "
        f"roles={list(row['roles'] or [])}"
    )


def _print_cognito_users(users: list[dict]) -> None:
    if not users:
        print("cognito_users status=not_found")
        return
    print(f"cognito_users status=found count={len(users)}")
    for user in users:
        print(
            "  cognito_user "
            f"username={user.get('Username')} "
            f"status={user.get('UserStatus')} "
            f"email={_get_attr(user, 'email')!r} "
            f"sub={_get_attr(user, 'sub')!r}"
        )


def _print_usage_summary(summary: asyncpg.Record) -> None:
    print(
        "db_refs "
        f"organization_links={summary['organization_links']} "
        f"role_links={summary['role_links']} "
        f"notifications={summary['notifications']} "
        f"comments_authored={summary['comments_authored']} "
        f"ai_feedback_rows={summary['ai_feedback_rows']} "
        f"workflow_step_refs={summary['workflow_step_refs']} "
        f"audit_event_refs={summary['audit_event_refs']} "
        f"assigned_workflows={summary['assigned_workflows']} "
        f"submitted_documents={summary['submitted_documents']} "
        f"compliance_reports={summary['compliance_reports']} "
        f"monitored_profiles={summary['monitored_profiles']}"
    )


def _blocking_reasons(summary: asyncpg.Record) -> list[str]:
    blockers: list[str] = []
    if summary["submitted_documents"]:
        blockers.append(f"submitted_documents={summary['submitted_documents']}")
    if summary["monitored_profiles"]:
        blockers.append(f"monitored_profiles={summary['monitored_profiles']}")
    return blockers


async def main() -> int:
    parser = argparse.ArgumentParser(description="Hard-delete a single user from DB and Cognito.")
    parser.add_argument("--email", required=True, help="User email to delete.")
    parser.add_argument("--dry-run", action="store_true", help="Preview actions without deleting anything.")
    parser.add_argument(
        "--include-documents",
        action="store_true",
        help="Delete documents, compliance reports, and monitored profiles owned/added by the user rather than blocking.",
    )
    args = parser.parse_args()

    if not DATABASE_URL:
        print("ERROR: DATABASE_URL is required.", file=sys.stderr)
        return 1
    if not AWS_REGION or not COGNITO_USER_POOL_ID:
        print("ERROR: AWS_REGION and COGNITO_USER_POOL_ID are required.", file=sys.stderr)
        return 1

    email = args.email.strip().lower()
    dry_run = bool(args.dry_run)

    cognito_client = boto3.client("cognito-idp", region_name=AWS_REGION)
    conn = await asyncpg.connect(_normalize_database_url(DATABASE_URL))
    try:
        db_user = await _fetch_db_user(conn, email)
        cognito_users = _get_cognito_users_by_email(cognito_client, email)

        _print_db_user(db_user)
        _print_cognito_users(cognito_users)

        if not db_user and not cognito_users:
            print(f"clear_user_hard status=noop email={email} reason=not_found")
            return 0

        if not db_user:
            if dry_run:
                print(
                    f"clear_user_hard status=preview email={email} "
                    f"delete_db=False delete_cognito={bool(cognito_users)}"
                )
                return 0
            for user in cognito_users:
                username = str(user["Username"])
                cognito_client.admin_delete_user(UserPoolId=COGNITO_USER_POOL_ID, Username=username)
                print(f"cognito_user status=deleted username={username}")
            print(
                f"clear_user_hard status=success email={email} "
                f"delete_db=False delete_cognito={bool(cognito_users)}"
            )
            return 0

        summary = await _fetch_db_usage_summary(conn, str(db_user["user_id"]))
        _print_usage_summary(summary)

        blockers = _blocking_reasons(summary)
        if blockers and not args.include_documents:
            print(
                "clear_user_hard status=blocked "
                f"email={email} "
                f"reason={' '.join(blockers)}"
            )
            print(
                "hint=This user still owns data that prevents a safe hard delete. "
                "Use --include-documents to delete their documents and other blocking records, "
                "or use move_user_to_org.py if your goal is to free the login for another org."
            )
            return 2

        if dry_run:
            print(
                f"clear_user_hard status=preview email={email} "
                f"delete_db=True delete_cognito={bool(cognito_users)}"
            )
            if blockers:
                print(f"  [DRY-RUN] Will delete blocking records: {', '.join(blockers)}")
            return 0

        async with conn.transaction():
            if blockers and args.include_documents:
                # Delete monitored profiles added by user
                if summary["monitored_profiles"]:
                    deleted_monitored = await conn.execute(
                        "DELETE FROM monitored_profiles WHERE added_by = $1::uuid",
                        str(db_user["user_id"]),
                    )
                    print(f"monitored_profiles status=deleted count={summary['monitored_profiles']} info={deleted_monitored}")

                # Delete documents submitted by user (cascades automatically to document_versions, reviews, findings, workflows, audit_events)
                if summary["submitted_documents"]:
                    deleted_docs = await conn.execute(
                        "DELETE FROM documents WHERE submitted_by = $1::uuid",
                        str(db_user["user_id"]),
                    )
                    print(f"documents status=deleted count={summary['submitted_documents']} info={deleted_docs}")

            await conn.execute("DELETE FROM user_profiles WHERE id = $1::uuid", str(db_user["user_id"]))
            print(f"user_profile status=deleted user_id={db_user['user_id']}")

        for user in cognito_users:
            username = str(user["Username"])
            try:
                cognito_client.admin_delete_user(UserPoolId=COGNITO_USER_POOL_ID, Username=username)
                print(f"cognito_user status=deleted username={username}")
            except ClientError as exc:
                print(f"cognito_user status=delete_failed username={username} error={exc}")
                return 3

        print(
            f"clear_user_hard status=success email={email} "
            f"delete_db=True delete_cognito={bool(cognito_users)}"
        )
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
