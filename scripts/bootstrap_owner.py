import argparse
import asyncio
import datetime
import os
import uuid
from pathlib import Path

import asyncpg
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
_AI_COMPLIANCE_DIR = _REPO_ROOT / "AI Compliance"

load_dotenv(_AI_COMPLIANCE_DIR / ".env")
load_dotenv(_REPO_ROOT / ".env")
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
AWS_REGION = os.getenv("AWS_REGION")
COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID")


def _normalize_database_url(url: str) -> str:
    if "+asyncpg" in url:
        return url.replace("+asyncpg", "")
    return url


async def _ensure_owner_role(conn, *, dry_run: bool) -> str:
    existing = await conn.fetchrow("SELECT id FROM roles WHERE name='owner' LIMIT 1")
    if existing:
        print("role=owner status=already_exists")
        return str(existing["id"])

    role_id = str(uuid.uuid4())
    if dry_run:
        print("role=owner status=created(dry_run)")
        return role_id

    await conn.execute(
        """
        INSERT INTO roles (id, name, display_name, description)
        VALUES ($1, 'owner', 'Owner', 'Platform owner for multitenancy operations')
        """,
        role_id,
    )
    print("role=owner status=created")
    return role_id


def _get_cognito_user_by_email(cognito_client, email: str):
    response = cognito_client.list_users(
        UserPoolId=COGNITO_USER_POOL_ID,
        Filter=f'email = "{email}"',
        Limit=1,
    )
    users = response.get("Users") or []
    return users[0] if users else None


def _get_attr(user: dict, name: str) -> str | None:
    for attr in user.get("Attributes") or []:
        if attr.get("Name") == name:
            return str(attr.get("Value"))
    return None


def _ensure_cognito_owner(
    cognito_client,
    *,
    email: str,
    full_name: str,
    password: str,
    dry_run: bool,
) -> tuple[str, str, str]:
    existing = _get_cognito_user_by_email(cognito_client, email)
    if existing:
        username = str(existing.get("Username"))
        sub = _get_attr(existing, "sub")
        if not sub:
            detail = cognito_client.admin_get_user(UserPoolId=COGNITO_USER_POOL_ID, Username=username)
            sub = _get_attr({"Attributes": detail.get("UserAttributes") or []}, "sub")
        if not sub:
            raise RuntimeError("Existing Cognito owner is missing sub.")
        # Always update the password to the one provided, even for existing users.
        if not dry_run:
            cognito_client.admin_set_user_password(
                UserPoolId=COGNITO_USER_POOL_ID,
                Username=username,
                Password=password,
                Permanent=True,
            )
            print(f"cognito_user status=already_exists username={username} password=updated")
        else:
            print(f"cognito_user status=already_exists username={username} password=would_update(dry_run)")
        return username, sub, "already_exists"

    username = str(uuid.uuid4())
    if dry_run:
        print(f"cognito_user status=created(dry_run) username={username}")
        return username, f"dry-run-sub-{username}", "created"

    create_resp = cognito_client.admin_create_user(
        UserPoolId=COGNITO_USER_POOL_ID,
        Username=username,
        UserAttributes=[
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
            {"Name": "name", "Value": full_name},
        ],
        MessageAction="SUPPRESS",
        TemporaryPassword=password,
    )
    cognito_client.admin_set_user_password(
        UserPoolId=COGNITO_USER_POOL_ID,
        Username=username,
        Password=password,
        Permanent=True,
    )
    user = create_resp.get("User") or {}
    sub = _get_attr(user, "sub")
    if not sub:
        detail = cognito_client.admin_get_user(UserPoolId=COGNITO_USER_POOL_ID, Username=username)
        sub = _get_attr({"Attributes": detail.get("UserAttributes") or []}, "sub")
    if not sub:
        raise RuntimeError("Created Cognito owner is missing sub.")
    print(f"cognito_user status=created username={username}")
    return username, sub, "created"


async def _upsert_owner_profile(
    conn,
    *,
    cognito_sub: str,
    email: str,
    full_name: str,
    department: str | None,
    dry_run: bool,
) -> tuple[str, str]:
    existing = await conn.fetchrow(
        "SELECT id FROM user_profiles WHERE lower(email)=lower($1) OR cognito_sub=$2 LIMIT 1",
        email,
        cognito_sub,
    )
    now_db = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    if existing:
        user_id = str(existing["id"])
        if not dry_run:
            await conn.execute(
                """
                UPDATE user_profiles
                SET cognito_sub=$1, email=$2, full_name=$3, department=$4, is_active=TRUE, updated_at=$5
                WHERE id=$6
                """,
                cognito_sub,
                email,
                full_name,
                department,
                now_db,
                user_id,
            )
        print(f"user_profile status=updated user_id={user_id}")
        return user_id, "updated"

    user_id = str(uuid.uuid4())
    if not dry_run:
        await conn.execute(
            """
            INSERT INTO user_profiles (id, cognito_sub, email, full_name, department, is_active, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, TRUE, $6, $6)
            """,
            user_id,
            cognito_sub,
            email,
            full_name,
            department,
            now_db,
        )
    print(f"user_profile status=created user_id={user_id}")
    return user_id, "created"


async def _ensure_owner_user_role(conn, *, user_id: str, owner_role_id: str, dry_run: bool) -> str:
    existing = await conn.fetchval(
        "SELECT 1 FROM user_roles WHERE user_id=$1 AND role_id=$2 LIMIT 1",
        user_id,
        owner_role_id,
    )
    if existing:
        print("user_role status=already_exists")
        return "already_exists"

    if not dry_run:
        await conn.execute(
            """
            INSERT INTO user_roles (id, user_id, role_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, role_id) DO NOTHING
            """,
            str(uuid.uuid4()),
            user_id,
            owner_role_id,
        )
    print("user_role status=created")
    return "created"


async def main():
    parser = argparse.ArgumentParser(description="Bootstrap an owner user in Cognito and DB.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--full-name", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--department", default="Owner")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required.")
    if not AWS_REGION or not COGNITO_USER_POOL_ID:
        raise RuntimeError("AWS_REGION and COGNITO_USER_POOL_ID are required.")

    email = args.email.strip().lower()
    full_name = args.full_name.strip()
    password = args.password
    department = args.department.strip() or None
    dry_run = bool(args.dry_run)

    if len(password) < 8:
        raise RuntimeError("Password must be at least 8 characters long.")

    cognito_client = boto3.client("cognito-idp", region_name=AWS_REGION)
    conn = await asyncpg.connect(_normalize_database_url(DATABASE_URL))

    created_cognito_username: str | None = None
    cognito_created = False
    try:
        owner_role_id = await _ensure_owner_role(conn, dry_run=dry_run)

        username, cognito_sub, cognito_state = _ensure_cognito_owner(
            cognito_client,
            email=email,
            full_name=full_name,
            password=password,
            dry_run=dry_run,
        )
        created_cognito_username = username
        cognito_created = cognito_state == "created" and not dry_run

        user_id, _ = await _upsert_owner_profile(
            conn,
            cognito_sub=cognito_sub,
            email=email,
            full_name=full_name,
            department=department,
            dry_run=dry_run,
        )
        await _ensure_owner_user_role(
            conn,
            user_id=user_id,
            owner_role_id=owner_role_id,
            dry_run=dry_run,
        )
        print(f"owner_bootstrap status=success user_id={user_id} email={email} dry_run={dry_run}")
    except Exception:
        if cognito_created and created_cognito_username:
            try:
                cognito_client.admin_delete_user(
                    UserPoolId=COGNITO_USER_POOL_ID,
                    Username=created_cognito_username,
                )
                print(f"cognito_user rollback=deleted username={created_cognito_username}")
            except ClientError:
                print(f"cognito_user rollback=failed username={created_cognito_username}")
        raise
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())