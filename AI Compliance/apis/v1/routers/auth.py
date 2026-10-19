import logging
import uuid
import datetime
import hmac
import hashlib
import base64
import os
import asyncio
import secrets
import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Depends, Request, Response
from pydantic import BaseModel, Field
from typing import Any

from apis.core.database import get_db
from apis.core.mail import (
    OTP_EXPIRE_MINUTES,
    send_mfa_otp_email_sync,
    send_password_changed_email_sync,
    send_welcome_email_sync,
)
from apis.core.security import (
    get_current_user,
    get_session_token,
    set_access_token_cookie,
    clear_access_token_cookie,
    set_refresh_token_cookie,
    clear_refresh_token_cookie,
    ACCESS_REFRESH_TOKEN_COOKIE_NAME,
    COGNITO_USER_POOL_ID,
    COGNITO_APP_CLIENT_ID,
    AWS_REGION,
    DEMO_LOGIN_ENABLED,
    DEMO_LOGIN_EMAILS,
    DEMO_LOGIN_PASSWORD,
    create_demo_access_token,
    try_decode_demo_token,
)
from apis.models.auth import (
    UserSignup,
    UserLogin,
    VerifyEmailRequest,
    ForgotPasswordRequest,
    ConfirmForgotPasswordRequest,
    PasswordChange,
)

# Import error logger
from apis.core.error_logger import (
    log_auth_error, log_db_error, log_api_error, log_validation_error,
    ErrorSeverity, ErrorCategory
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


# Token-bearing keys that must never appear in JSON response bodies; we put the
# access token in an httpOnly cookie and only expose ``token_in_cookie: true``.
_RAW_TOKEN_KEYS = ("access_token", "id_token", "refresh_token")


def _issue_session_cookie_and_strip(
    response: Response,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Move ``access_token`` from a dict body into an httpOnly cookie on ``response``.

    Returns a sanitized copy of ``payload`` with raw tokens removed and a
    ``token_in_cookie`` flag added when a token was present.
    """
    if not isinstance(payload, dict):
        return payload
    access = payload.get("access_token")
    refresh = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    sanitized = {k: v for k, v in payload.items() if k not in _RAW_TOKEN_KEYS}
    if isinstance(access, str) and access:
        set_access_token_cookie(response, access, expires_in=expires_in if isinstance(expires_in, int) else None)
        sanitized["token_in_cookie"] = True
    if isinstance(refresh, str) and refresh:
        set_refresh_token_cookie(response, refresh)
    return sanitized

# ✅ ADD HERE (no confusion)
@router.get("/check-email")
async def check_email(email: str, db=Depends(get_db)):
    email_norm = (email or "").strip().lower()

    if await _active_profile_exists_for_email(db, email_norm):
        raise HTTPException(
            status_code=400,
            detail="This email is already registered. Please sign in.",
        )

    if await _email_exists_in_cognito(email_norm):
        raise HTTPException(
            status_code=400,
            detail="This email is already registered. Please sign in.",
        )

    return {"message": "Email available"}

# Cognito Client
cognito_client = boto3.client("cognito-idp", region_name=AWS_REGION)
COGNITO_APP_CLIENT_SECRET = os.getenv("COGNITO_APP_CLIENT_SECRET")

# In-memory stores to enforce MFA when Cognito doesn't require it.
# Notes:
# - Dev-only MVP: this is not persisted across restarts / multiple workers.
_CUSTOM_EMAIL_MFA_PREFIX = "email-mfa-"
_CUSTOM_EMAIL_MFA_STORE: dict[str, dict[str, Any]] = {}
_COGNITO_MFA_CHALLENGE_STORE: dict[str, str] = {}

_ADMIN_CREATE_USER_PREFIX = "admin-create-"
_ADMIN_CREATE_USER_STORE: dict[str, dict[str, Any]] = {}

_FORGOT_PASSWORD_STORE: dict[str, dict[str, Any]] = {}


def _require_super_admin_only(current_user: dict = Depends(get_current_user)) -> dict:
    roles = set((current_user or {}).get("roles") or [])
    if "super_admin" not in roles:
        raise HTTPException(
            status_code=403,
            detail="Only super_admin can create users with this flow.",
        )
    return current_user


async def _resolve_target_role_row(db, role_label: str) -> dict[str, Any] | None:
    """Map CreateUserModal labels to roles.name (matches superAdmin.tsx)."""
    label = (role_label or "").strip()
    modal_to_name = {
        "Owner": "owner",
        "Marketing": "marketing",
        "SME Reviewer": "sme",
        "Compliance": "compliance",
        "Super Admin": "super_admin",
    }
    name = modal_to_name.get(label)
    if name:
        return await db.fetchrow("SELECT id, name FROM roles WHERE name = $1", name)
    return await db.fetchrow(
        "SELECT id, name FROM roles WHERE name = $1 OR display_name = $1",
        label,
    )


def _cognito_sub_from_user_response(user: dict[str, Any], username: str) -> str:
    for attr in user.get("Attributes") or user.get("UserAttributes") or []:
        if attr.get("Name") == "sub" and attr.get("Value"):
            return str(attr["Value"])
    try:
        gu = cognito_client.admin_get_user(UserPoolId=COGNITO_USER_POOL_ID, Username=username)
        for attr in gu.get("UserAttributes") or []:
            if attr.get("Name") == "sub" and attr.get("Value"):
                return str(attr["Value"])
    except ClientError:
        pass
    raise HTTPException(status_code=500, detail="Cognito user missing sub attribute")


async def _email_exists_in_db(db, email: str) -> bool:
    n = await db.fetchval(
        "SELECT 1 FROM user_profiles WHERE lower(email)=lower($1) LIMIT 1",
        email,
    )
    return n is not None


def _cognito_list_users_filter_value(value: str) -> str:
    """Escape double quotes and backslashes for Cognito ListUsers Filter attribute values."""
    return (value or "").replace("\\", "\\\\").replace('"', '\\"')


async def _email_exists_in_cognito(email: str) -> bool:
    """
    True only if some pool user has standard attribute email equal to this address (case-insensitive).

    We verify UserAttributes on each returned user: ListUsers filters are pool-dependent and can
    occasionally return unrelated users, which previously caused false positives for duplicate email.
    """
    email_norm = (email or "").strip().lower()
    if not email_norm:
        return False
    raw = (email or "").strip()
    candidates: list[str] = []
    for c in (email_norm, raw):
        if c and c not in candidates:
            candidates.append(c)
    try:
        seen_usernames: set[str] = set()
        for cand in candidates:
            safe = _cognito_list_users_filter_value(cand)
            r = cognito_client.list_users(
                UserPoolId=COGNITO_USER_POOL_ID,
                Filter=f'email = "{safe}"',
                Limit=25,
            )
            for u in r.get("Users") or []:
                un = str(u.get("Username") or "")
                if un in seen_usernames:
                    continue
                seen_usernames.add(un)
                for attr in u.get("Attributes") or u.get("UserAttributes") or []:
                    if attr.get("Name") != "email":
                        continue
                    if (attr.get("Value") or "").strip().lower() == email_norm:
                        return True
        return False
    except ClientError as e:
        logger.warning("list_users (email exists check) failed for %s: %s", email_norm, e)
        return False


def _signup_block_message_for_existing_cognito_email(email: str) -> str | None:
    """
    Signup uses a random Cognito username, so duplicate-email cases may not surface as
    UsernameExistsException. If any pool user already claims this email, block signup
    (no verification OTP) and return a user-facing message.
    """
    email_lower = (email or "").strip().lower()
    if not email_lower:
        return None
    try:
        response = cognito_client.list_users(
            UserPoolId=COGNITO_USER_POOL_ID,
            Filter=f'email = "{email_lower}"',
            Limit=10,
        )
        users = response.get("Users") or []
        if not users:
            response = cognito_client.list_users(
                UserPoolId=COGNITO_USER_POOL_ID,
                Filter=f'email = "{email}"',
                Limit=10,
            )
            users = response.get("Users") or []
        if not users:
            return None

        confirmed = [u for u in users if u.get("UserStatus") == "CONFIRMED"]
        selected = confirmed[0] if confirmed else users[0]
        status = str(selected.get("UserStatus") or "")

        if status == "CONFIRMED":
            return "This email is already registered. Please sign in."
        if status == "UNCONFIRMED":
            return (
                "This email already has a pending registration. "
                "Use Resend code on the verification page, or sign in if you already verified."
            )
        return "This email is already associated with an account. Please sign in."
    except ClientError as e:
        logger.warning("signup precheck list_users failed for %s: %s", email_lower, e)
        return None


async def _get_cognito_user_status(email: str) -> str | None:
    """Helper to check Cognito status (CONFIRMED, UNCONFIRMED, etc) for an email."""
    email_lower = (email or "").strip().lower()
    if not email_lower:
        return None
    try:
        # Note: list_users is synchronous in boto3
        response = cognito_client.list_users(
            UserPoolId=COGNITO_USER_POOL_ID,
            Filter=f'email = "{email_lower}"',
            Limit=1,
        )
        users = response.get("Users") or []
        if not users:
            return None
        return str(users[0].get("UserStatus") or "")
    except ClientError:
        return None


async def _active_profile_exists_for_email(db, email: str) -> bool:
    row = await db.fetchval(
        "SELECT 1 FROM user_profiles WHERE lower(email)=lower($1) AND is_active = TRUE LIMIT 1",
        email,
    )
    return row is not None


def get_secret_hash(username: str):
    if not COGNITO_APP_CLIENT_SECRET:
        return None
    msg = username + COGNITO_APP_CLIENT_ID
    dig = hmac.new(
        str(COGNITO_APP_CLIENT_SECRET).encode("utf-8"),
        msg=str(msg).encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(dig).decode()


def resolve_cognito_username(email: str) -> str | None:
    """Resolve email to Cognito username. Returns None if user doesn't exist."""
    try:
        email_lower = (email or "").strip().lower()
        logger.info("Searching for user with email: %s", email_lower)
        
        response = cognito_client.list_users(
            UserPoolId=COGNITO_USER_POOL_ID,
            Filter=f'email = "{email_lower}"',
            Limit=10,
        )
        
        users = response.get("Users") or []
        logger.info("Found %d users matching email %s", len(users), email_lower)
        
        if not users:
            # Try alternative search - sometimes Cognito is case-sensitive
            logger.info("Trying case-insensitive search for email: %s", email_lower)
            response = cognito_client.list_users(
                UserPoolId=COGNITO_USER_POOL_ID,
                Filter=f'email = "{email}"',
                Limit=10,
            )
            users = response.get("Users") or []
            logger.info("Alternative search found %d users", len(users))
        
        if not users:
            logger.warning("No users found for email: %s", email_lower)
            return None
        
        # Log user details for debugging
        for idx, user in enumerate(users):
            logger.info("User %d: Username=%s, Status=%s", idx, user.get("Username"), user.get("UserStatus"))
        
        # Prefer confirmed users over unconfirmed ones (handles duplicate signup edge case)
        confirmed = [u for u in users if u.get("UserStatus") == "CONFIRMED"]
        selected_user = confirmed[0] if confirmed else users[0]
        username = selected_user["Username"]
        logger.info("Resolved email %s to username: %s", email_lower, username)
        return username
    except ClientError as e:
        logger.error("ClientError looking up user by email %s: %s", email, e)
        return None
    except Exception as e:
        logger.exception("Unexpected error looking up user by email %s: %s", email, e)
        return None


def _attributes_to_dict(attributes: list[dict]) -> dict[str, str]:
    result: dict[str, str] = {}
    for attr in attributes or []:
        name = attr.get("Name")
        value = attr.get("Value")
        if name and value is not None:
            result[name] = value
    return result


def _friendly_cognito_error_message(e: ClientError, *, context: str = "generic") -> str:
    """
    Convert Cognito error payloads to concise user-facing messages.
    """
    err = e.response.get("Error", {}) if isinstance(e.response, dict) else {}
    code = str(err.get("Code") or "").strip()
    raw_message = str(err.get("Message") or "").strip()
    message_lower = raw_message.lower()

    if context == "verify_email":
        if code == "CodeMismatchException":
            return "Invalid verification code. Please check the code and try again."
        if code == "ExpiredCodeException":
            return "Your verification code has expired. Please request a new code."
        if "current status is confirmed" in message_lower:
            return "Your email is already verified. Please sign in."

    if context in {"resend_code", "forgot_password", "confirm_forgot_password"}:
        if code == "UserNotFoundException":
            return "No account found for this email."
        if code == "CodeMismatchException":
            return "Invalid code. Please check the code and try again."
        if code == "ExpiredCodeException":
            return "This code has expired. Please request a new one."

    if context == "verify_otp":
        if code == "CodeMismatchException":
            return "Invalid OTP. Please enter the latest code and try again."
        if code == "ExpiredCodeException":
            return "OTP expired. Please request a new OTP."

    if code == "UsernameExistsException":
        return "An account with this email already exists."
    if code == "InvalidPasswordException":
        return "Password does not meet security requirements."
    if code == "LimitExceededException":
        return "Too many attempts. Please wait a moment and try again."
    if code == "TooManyRequestsException":
        return "Too many requests. Please wait a moment and try again."
    if code == "NotAuthorizedException":
        return "Authentication failed. Please check your credentials and try again."
    if code == "UserNotConfirmedException":
        return "Your email is not verified. Please verify your email first."
    if code == "UserNotFoundException":
        return "No account found for this email."

    # Fallback: sanitize known confusing Cognito text
    if "current status is confirmed" in message_lower:
        return "Your email is already verified. Please sign in."

    return raw_message or "Unable to complete the request. Please try again."


def _get_cognito_profile_from_access_token(access_token: str) -> dict[str, str]:
    user_resp = cognito_client.get_user(AccessToken=access_token)
    attrs = _attributes_to_dict(user_resp.get("UserAttributes", []))
    return {
        "sub": attrs.get("sub", ""),
        "email": attrs.get("email", ""),
        "full_name": attrs.get("name", ""),
    }


async def _ensure_local_profile(
    db,
    *,
    cognito_sub: str,
    email: str,
    full_name: str,
):
    """Upsert local user_profiles from Cognito identity. Roles are assigned only by Super Admin."""
    if not email:
        return

    now_db = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    async with db.transaction():
        await db.execute("SELECT pg_advisory_xact_lock(913247)")

        profile_row = await db.fetchrow(
            "SELECT id FROM user_profiles WHERE email=$1 OR cognito_sub=$2 LIMIT 1",
            email,
            cognito_sub,
        )

        if profile_row:
            await db.execute(
                """
                UPDATE user_profiles
                SET cognito_sub = $1,
                    email = $2,
                    full_name = COALESCE(NULLIF($3, ''), full_name),
                    updated_at = $4
                WHERE id = $5
                """,
                cognito_sub,
                email,
                full_name,
                now_db,
                profile_row["id"],
            )
        else:
            new_id = str(uuid.uuid4())
            await db.execute(
                """
                INSERT INTO user_profiles (id, cognito_sub, email, full_name, is_active, created_at, updated_at)
                VALUES ($1, $2, $3, $4, TRUE, $5, $5)
                """,
                new_id,
                cognito_sub,
                email,
                full_name or email.split("@")[0],
                now_db,
            )


@router.post("/signup")
async def signup(user: UserSignup, db=Depends(get_db)):
    """Create Cognito user + pending local profile. Department and roles stay unset until an admin assigns them."""
    email_norm = (str(user.email) if user.email is not None else "").strip().lower()

    # Block deactivated users from re-registering
    profile = await db.fetchrow("SELECT is_active FROM user_profiles WHERE lower(email)=lower($1)", email_norm)
    if profile and not profile["is_active"]:
        # Only block if they are already confirmed in Cognito (meaning they were once active)
        # Unconfirmed users are just in the middle of signup.
        cognito_status = await _get_cognito_user_status(email_norm)
        if cognito_status == "CONFIRMED":
            raise HTTPException(
                status_code=403,
                detail="Your account has been deactivated. Please contact your Super Admin to restore access."
            )

    if await _active_profile_exists_for_email(db, email_norm):
        raise HTTPException(
            status_code=400,
            detail="This email is already registered. Please sign in.",
        )
    cognito_block = _signup_block_message_for_existing_cognito_email(email_norm)
    if cognito_block:
        raise HTTPException(status_code=400, detail=cognito_block)

    cognito_username = str(uuid.uuid4())
    secret_hash = get_secret_hash(cognito_username)

    try:
        kwargs = {
            "ClientId": COGNITO_APP_CLIENT_ID,
            "Username": cognito_username,
            "Password": user.password,
            "UserAttributes": [
                {"Name": "email", "Value": email_norm},
                {"Name": "name", "Value": user.full_name},
            ],
        }
        if secret_hash:
            kwargs["SecretHash"] = secret_hash

        response = cognito_client.sign_up(**kwargs)
        user_sub = response["UserSub"]

        now_db = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

        async with db.transaction():
            await db.execute("SELECT pg_advisory_xact_lock(913247)")

            await db.fetchval(
                """
                INSERT INTO user_profiles (id, cognito_sub, email, full_name, avatar_url, is_active, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, FALSE, $6, $6)
                ON CONFLICT (email)
                DO UPDATE SET
                    cognito_sub = EXCLUDED.cognito_sub,
                    full_name = EXCLUDED.full_name,
                    avatar_url = EXCLUDED.avatar_url,
                    updated_at = EXCLUDED.updated_at
                RETURNING id
                """,
                str(uuid.uuid4()),
                user_sub,
                email_norm,
                user.full_name,
                user.avatar_url,
                now_db,
            )

        return {"message": "User created in Cognito. Please verify your email.", "userSub": user_sub}

    except ClientError as e:
        logger.error("Cognito Signup Error: %s", e)
        error_code = e.response["Error"]["Code"]
        if error_code in ("UsernameExistsException", "AliasExistsException"):
            raise HTTPException(
                status_code=400,
                detail="This email is already registered. Please sign in.",
            )
        raise HTTPException(status_code=400, detail=_friendly_cognito_error_message(e, context="signup"))
    except Exception as e:
        logger.error("Signup Error: %s", e)
        raise HTTPException(status_code=500, detail="Internal Server Error")


async def _issue_tokens_after_verify_skip_custom_mfa(
    db,
    *,
    email: str,
    password: str,
) -> dict[str, Any]:
    """
    Issue Cognito tokens after email confirmation without the custom email MFA step.
    Used for register → email OTP → dashboard. Normal /auth/login still enforces custom MFA.
    """
    email_norm = (email or "").strip().lower()
    cognito_username = resolve_cognito_username(email_norm)
    if not cognito_username:
        raise HTTPException(
            status_code=400,
            detail="Username or Email not found"
        )
    secret_hash = get_secret_hash(cognito_username)
    kwargs = {
        "ClientId": COGNITO_APP_CLIENT_ID,
        "AuthFlow": "USER_PASSWORD_AUTH",
        "AuthParameters": {
            "USERNAME": cognito_username,
            "PASSWORD": password,
        },
    }
    if secret_hash:
        kwargs["AuthParameters"]["SECRET_HASH"] = secret_hash

    try:
        response = cognito_client.initiate_auth(**kwargs)
    except ClientError as e:
        logger.error("Post-verify password auth failed: %s", e)
        raise HTTPException(
            status_code=400,
            detail=e.response.get("Error", {}).get("Message", "Sign-in failed after verification."),
        ) from e

    if "ChallengeName" in response:
        session = response.get("Session")
        if session:
            _COGNITO_MFA_CHALLENGE_STORE[str(session)] = str(response["ChallengeName"])
        return {
            "mfa_required": True,
            "challenge": response["ChallengeName"],
            "session": session,
            "message": "Email verified. Additional authentication is required.",
        }

    auth_result = response["AuthenticationResult"]
    cognito_profile = _get_cognito_profile_from_access_token(auth_result["AccessToken"])
    await _ensure_local_profile(
        db,
        cognito_sub=cognito_profile.get("sub") or cognito_username,
        email=cognito_profile.get("email") or email_norm,
        full_name=cognito_profile.get("full_name") or "",
    )
    return {
        "mfa_required": False,
        "access_token": auth_result["AccessToken"],
        "id_token": auth_result["IdToken"],
        "refresh_token": auth_result.get("RefreshToken"),
        "expires_in": auth_result["ExpiresIn"],
    }


@router.post("/verify-email")
async def verify_email(data: VerifyEmailRequest, response: Response, db=Depends(get_db)):
    try:
        cognito_username = resolve_cognito_username(data.email)
        if not cognito_username:
            raise HTTPException(
                status_code=400,
                detail="Username or Email not found"
            )
        secret_hash = get_secret_hash(cognito_username)

        kwargs = {
            "ClientId": COGNITO_APP_CLIENT_ID,
            "Username": cognito_username,
            "ConfirmationCode": data.code,
        }
        if secret_hash:
            kwargs["SecretHash"] = secret_hash

        cognito_client.confirm_sign_up(**kwargs)
        await db.execute("UPDATE user_profiles SET is_active=TRUE WHERE email=$1", data.email)

        base = {"message": "Email verified successfully."}
        pwd = (data.password or "").strip()
        if pwd:
            try:
                extra = await _issue_tokens_after_verify_skip_custom_mfa(
                    db,
                    email=str(data.email),
                    password=pwd,
                )
                merged = {**base, **extra}
                # Only the non-MFA branch carries real tokens; the MFA branch returns
                # a challenge dict without ``access_token`` so the helper is a no-op.
                return _issue_session_cookie_and_strip(response, merged)
            except HTTPException as exc:
                # Email is already confirmed; client can go to manual login.
                detail = exc.detail if isinstance(exc.detail, str) else "Sign-in failed."
                return {
                    **base,
                    "auto_login_failed": True,
                    "detail": detail,
                }

        return base

    except ClientError as e:
        logger.error("Cognito Verify Error: %s", e)
        raise HTTPException(status_code=400, detail=_friendly_cognito_error_message(e, context="verify_email"))


@router.post("/login")
async def login(user: UserLogin, db=Depends(get_db)):
    email = (user.email or "").strip().lower()

    # Block deactivated users from logging in
    profile = await db.fetchrow("SELECT is_active FROM user_profiles WHERE lower(email)=lower($1)", email)
    if profile and not profile["is_active"]:
        # Only block if they are already confirmed in Cognito.
        # If they are UNCONFIRMED, we let the normal login flow handle the "verify your email" message.
        cognito_status = await _get_cognito_user_status(email)
        if cognito_status == "CONFIRMED":
            raise HTTPException(
                status_code=403, 
                detail="Your account has been deactivated. Please contact your Super Admin to restore access."
            )

    if (
        DEMO_LOGIN_ENABLED
        and user.password == DEMO_LOGIN_PASSWORD
        and email in DEMO_LOGIN_EMAILS
    ):
        profile = await db.fetchrow(
            "SELECT id, is_active FROM user_profiles WHERE lower(email)=lower($1)",
            email,
        )
        if not profile:
            raise HTTPException(
                status_code=401,
                detail="User not found.",
            )
        if not profile["is_active"]:
            raise HTTPException(status_code=401, detail="User is deactivated")

        # Simulate OTP flow for demo by returning a challenge
        return {
            "mfa_required": True,
            "challenge": "SOFTWARE_TOKEN_MFA",
            "session": f"demo-session-{email}",
            "message": "OTP sent",
        }

    try:
        # First, check if user exists by email
        logger.info("Login attempt for email: %s", user.email)
        cognito_username = resolve_cognito_username(user.email)
        if not cognito_username:
            logger.warning("User not found for email: %s", user.email)
            raise HTTPException(
                status_code=400, 
                detail="Username or Email not found"
            )
        
        logger.info("User found, attempting authentication for: %s", cognito_username)
        secret_hash = get_secret_hash(cognito_username)

        kwargs = {
            "ClientId": COGNITO_APP_CLIENT_ID,
            "AuthFlow": "USER_PASSWORD_AUTH",
            "AuthParameters": {
                "USERNAME": cognito_username,
                "PASSWORD": user.password,
            },
        }

        if secret_hash:
            kwargs["AuthParameters"]["SECRET_HASH"] = secret_hash

        response = cognito_client.initiate_auth(**kwargs)
        logger.debug("Cognito initiate_auth response: %s", response)

        if "ChallengeName" in response:
            logger.info(
                "MFA challenge returned: %s, Session present: %s",
                response.get("ChallengeName"),
                bool(response.get("Session")),
            )
            session = response.get("Session")
            if session:
                _COGNITO_MFA_CHALLENGE_STORE[str(session)] = str(response["ChallengeName"])
            return {
                "mfa_required": True,
                "challenge": response["ChallengeName"],
                "session": session,
                "message": "OTP sent",
            }

        auth_result = response["AuthenticationResult"]
        cognito_profile = _get_cognito_profile_from_access_token(auth_result["AccessToken"])

        await _ensure_local_profile(
            db,
            cognito_sub=cognito_profile.get("sub") or cognito_username,
            email=cognito_profile.get("email") or user.email,
            full_name=cognito_profile.get("full_name") or "",
        )

        # Enforce MFA/OTP for every login attempt.
        otp = f"{secrets.randbelow(1000000):06d}"
        custom_session = f"{_CUSTOM_EMAIL_MFA_PREFIX}{uuid.uuid4()}"
        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            minutes=OTP_EXPIRE_MINUTES
        )

        tokens = {
            "access_token": auth_result["AccessToken"],
            "id_token": auth_result["IdToken"],
            "refresh_token": auth_result.get("RefreshToken"),
            "expires_in": auth_result["ExpiresIn"],
        }

        recipient_name = cognito_profile.get("full_name") or email.split("@")[0]
        _CUSTOM_EMAIL_MFA_STORE[str(custom_session)] = {
            "email": email,
            "otp": otp,
            "expires_at": expires_at,
            "tokens": tokens,
            "recipient_name": recipient_name,
        }
        try:
            await asyncio.to_thread(
                send_mfa_otp_email_sync,
                to_email=email,
                recipient_name=recipient_name,
                otp=otp,
            )
        except Exception:
            logger.exception("Failed to send custom MFA OTP email")

        return {
            "mfa_required": True,
            "challenge": "CUSTOM_EMAIL_MFA",
            "session": str(custom_session),
            "message": "OTP sent",
        }

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"]["Message"]
        logger.error("Cognito Login Error Code: %s, Message: %s", error_code, error_message)
        
        # Check for invalid password/authentication error
        # Cognito returns NotAuthorizedException for wrong password
        if error_code == "NotAuthorizedException":
            logger.warning("Authentication failed for email %s - wrong password", user.email)
            raise HTTPException(
                status_code=400,
                detail="Wrong password"
            )
        
        if error_code == "UserNotConfirmedException":
            # Auto-resend confirmation code so the user can verify their email
            try:
                unconfirmed_username = resolve_cognito_username(user.email)
                if unconfirmed_username:
                    secret_hash = get_secret_hash(unconfirmed_username)
                    resend_kwargs = {
                        "ClientId": COGNITO_APP_CLIENT_ID,
                        "Username": unconfirmed_username,
                    }
                    if secret_hash:
                        resend_kwargs["SecretHash"] = secret_hash
                    cognito_client.resend_confirmation_code(**resend_kwargs)
                    logger.info("Resent confirmation code to %s", user.email)
            except Exception as resend_err:
                logger.warning("Could not resend confirmation code: %s", resend_err)
            raise HTTPException(
                status_code=400,
                detail="Your email is not verified. A new verification code has been sent to your email. Please check your inbox and verify before logging in.",
            )
        raise HTTPException(status_code=400, detail=_friendly_cognito_error_message(e, context="login"))
    
    except HTTPException:
        # Re-raise HTTP exceptions as-is (these are our intentional error responses)
        raise
    
    except Exception as e:
        # Catch any other unexpected errors
        logger.exception("Unexpected error during login: %s", e)
        raise HTTPException(
            status_code=400,
            detail="An error occurred during login. Please try again."
        )


class VerifyOtpBody(BaseModel):
    email: str
    otp: str
    session: str


@router.post("/verify-otp")
async def verify_otp(payload: VerifyOtpBody, response: Response, db=Depends(get_db)):
    # Check if this is a demo session
    if payload.session.startswith("demo-session-"):
        email = payload.session.replace("demo-session-", "")
        # For demo, any 6-digit OTP will work, but let's just accept it
        demo_token = create_demo_access_token(email=email)
        return _issue_session_cookie_and_strip(
            response,
            {
                "access_token": demo_token,
                "id_token": demo_token,
                "refresh_token": None,
                "expires_in": 43200,
            },
        )

    # Custom email MFA flow (generated in /auth/login).
    # Important: do not pop the session until OTP succeeds. Popping before validation
    # would drop the entry on a wrong OTP and break /auth/resend-otp (in-memory store).
    if payload.session.startswith(_CUSTOM_EMAIL_MFA_PREFIX):
        entry = _CUSTOM_EMAIL_MFA_STORE.get(payload.session)
        if not entry:
            raise HTTPException(status_code=400, detail="Invalid or expired OTP session")

        expected_email = str(entry.get("email") or "").strip().lower()
        actual_email = str(payload.email or "").strip().lower()
        if not expected_email or expected_email != actual_email:
            raise HTTPException(status_code=400, detail="OTP session email mismatch")

        now = datetime.datetime.now(datetime.timezone.utc)
        expires_at = entry.get("expires_at")
        if not expires_at or expires_at <= now:
            logger.warning(
                "VERIFY_OTP_EXPIRED session=%s email=%s (session kept for resend)",
                payload.session,
                actual_email,
            )
            raise HTTPException(status_code=400, detail="OTP expired. Please click Resend OTP for a new code.")

        expected_otp = str(entry.get("otp") or "").strip()
        actual_otp = str(payload.otp or "").strip()
        if expected_otp != actual_otp:
            # Do not remove the session — user can retry or use /auth/resend-otp.
            logger.warning(
                "VERIFY_OTP_WRONG_CODE session=%s email=%s (session kept for retry/resend)",
                payload.session,
                actual_email,
            )
            raise HTTPException(
                status_code=400,
                detail="Invalid OTP. Try again, or use Resend OTP for a new code.",
            )

        tokens = entry["tokens"]
        _CUSTOM_EMAIL_MFA_STORE.pop(payload.session, None)
        return _issue_session_cookie_and_strip(response, dict(tokens))

    try:
        cognito_username = resolve_cognito_username(payload.email)
        if not cognito_username:
            raise HTTPException(
                status_code=400,
                detail="Username or Email not found"
            )
        secret_hash = get_secret_hash(cognito_username)

        challenge_name = _COGNITO_MFA_CHALLENGE_STORE.get(payload.session)
        if not challenge_name:
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired OTP session. Please login again.",
            )
        otp_param_by_challenge = {
            "SMS_MFA": "SMS_MFA_CODE",
            "SOFTWARE_TOKEN_MFA": "SOFTWARE_TOKEN_MFA_CODE",
            "EMAIL_OTP": "EMAIL_OTP_CODE",
        }
        otp_param = otp_param_by_challenge.get(str(challenge_name))
        if not otp_param:
            raise HTTPException(
                status_code=400,
                detail="Unsupported authentication challenge. Please login again.",
            )

        challenge_responses = {
            "USERNAME": cognito_username,
            otp_param: payload.otp,
        }
        if secret_hash:
            challenge_responses["SECRET_HASH"] = secret_hash

        response = cognito_client.respond_to_auth_challenge(
            ClientId=COGNITO_APP_CLIENT_ID,
            ChallengeName=str(challenge_name),
            Session=payload.session,
            ChallengeResponses=challenge_responses,
        )

        _COGNITO_MFA_CHALLENGE_STORE.pop(payload.session, None)

        auth_result = response["AuthenticationResult"]
        cognito_profile = _get_cognito_profile_from_access_token(auth_result["AccessToken"])

        await _ensure_local_profile(
            db,
            cognito_sub=cognito_profile.get("sub") or cognito_username,
            email=cognito_profile.get("email") or payload.email,
            full_name=cognito_profile.get("full_name") or "",
        )

        return _issue_session_cookie_and_strip(
            response,
            {
                "access_token": auth_result["AccessToken"],
                "id_token": auth_result["IdToken"],
                "refresh_token": auth_result.get("RefreshToken"),
                "expires_in": auth_result["ExpiresIn"],
            },
        )

    except ClientError as e:
        logger.error("Cognito Verify OTP Error: %s", e)
        raise HTTPException(status_code=400, detail=_friendly_cognito_error_message(e, context="verify_otp"))


class ResendOtpBody(BaseModel):
    email: str
    session: str


@router.post("/resend-otp")
async def resend_otp(payload: ResendOtpBody):
    """
    Resend OTP for the enforced custom email MFA session.
    If Cognito MFA challenge sessions are used, this MVP currently asks user to login again.
    """
    logger.info(
        "RESEND_OTP_REQUEST session=%s email=%s",
        payload.session,
        payload.email,
    )

    # Demo sessions accept any OTP; no real resend needed.
    if payload.session.startswith("demo-session-"):
        return {"session": payload.session, "message": "OTP ready (demo)." }

    if payload.session.startswith(_CUSTOM_EMAIL_MFA_PREFIX):
        entry = _CUSTOM_EMAIL_MFA_STORE.get(payload.session)
        if not entry:
            logger.warning(
                "RESEND_OTP_INVALID_SESSION session=%s store_missing=True",
                payload.session,
            )
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired OTP session (server restarted or session expired). Please login again.",
            )

        expected_email = str(entry.get("email") or "").strip().lower()
        actual_email = str(payload.email or "").strip().lower()
        if not expected_email or expected_email != actual_email:
            logger.warning(
                "RESEND_OTP_EMAIL_MISMATCH session=%s expected=%s actual=%s",
                payload.session,
                expected_email,
                actual_email,
            )
            raise HTTPException(
                status_code=400,
                detail="OTP session email mismatch. Please login again.",
            )

        otp = f"{secrets.randbelow(1000000):06d}"
        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            minutes=OTP_EXPIRE_MINUTES
        )
        entry["otp"] = otp
        entry["expires_at"] = expires_at

        recipient_name = entry.get("recipient_name") or str(entry.get("email") or "").split("@")[0]
        # Send synchronously via helper, but call it in a thread to avoid blocking.
        await asyncio.to_thread(
            send_mfa_otp_email_sync,
            to_email=payload.email,
            recipient_name=recipient_name,
            otp=otp,
        )
        logger.info("RESEND_OTP_SENT session=%s email=%s", payload.session, payload.email)
        return {"session": payload.session, "message": "OTP resent"}

    raise HTTPException(
        status_code=400,
        detail="Resend is only supported for email-MFA sessions. Please login again to get a new OTP.",
    )


class AdminCreateUserChallengeBody(BaseModel):
    email: str
    password: str = Field(..., min_length=8)
    full_name: str
    department: str = ""
    phone: str = ""
    roles: list[str] = Field(default_factory=list)


class AdminCreateUserConfirmBody(BaseModel):
    session: str
    otp: str


class AdminCreateUserResendBody(BaseModel):
    session: str


@router.post("/admin/create-user/challenge")
async def admin_create_user_challenge(
    body: AdminCreateUserChallengeBody,
    current_user: dict = Depends(_require_super_admin_only),
    db=Depends(get_db),
):
    """
    Send a one-time code to the Super Admin's email to authorize creating a new user.
    """
    admin_id = str((current_user or {}).get("id") or "")
    admin_row = await db.fetchrow(
        "SELECT email, full_name FROM user_profiles WHERE id=$1",
        admin_id,
    )
    if not admin_row or not admin_row.get("email"):
        raise HTTPException(status_code=400, detail="Super Admin profile email not found.")

    new_email = (body.email or "").strip().lower()
    if not new_email:
        raise HTTPException(status_code=400, detail="Email is required.")

    role_keys = [str(x).strip() for x in (body.roles or []) if str(x).strip()]
    if not role_keys:
        raise HTTPException(status_code=400, detail="Select at least one role.")

    seen_role_ids: set[str] = set()
    role_ids: list[str] = []
    for key in role_keys:
        role_row = await _resolve_target_role_row(db, key)
        if not role_row:
            raise HTTPException(status_code=400, detail=f"Invalid role: {key}")
        if str(role_row.get("name") or "") == "owner":
            raise HTTPException(status_code=403, detail="Owner role can only be assigned via owner bootstrap flow.")
        rid = str(role_row["id"])
        if rid not in seen_role_ids:
            seen_role_ids.add(rid)
            role_ids.append(rid)

    if await _email_exists_in_db(db, new_email):
        raise HTTPException(status_code=400, detail="A user with this email already exists.")
    if await _email_exists_in_cognito(new_email):
        raise HTTPException(status_code=400, detail="A user with this email already exists.")

    otp = f"{secrets.randbelow(1000000):06d}"
    session_id = f"{_ADMIN_CREATE_USER_PREFIX}{uuid.uuid4()}"
    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=OTP_EXPIRE_MINUTES
    )

    pending = {
        "admin_user_id": admin_id,
        "new_email": new_email,
        "password": body.password,
        "full_name": (body.full_name or "").strip(),
        "department": (body.department or "").strip(),
        "phone": (body.phone or "").strip(),
        "role_ids": role_ids,
    }

    _ADMIN_CREATE_USER_STORE[session_id] = {
        "admin_user_id": admin_id,
        "otp": otp,
        "expires_at": expires_at,
        "pending": pending,
    }

    admin_email = str(admin_row["email"])
    recipient_name = str(admin_row.get("full_name") or admin_email.split("@")[0])
    try:
        await asyncio.to_thread(
            send_mfa_otp_email_sync,
            to_email=admin_email,
            recipient_name=recipient_name,
            otp=otp,
            subject="Confirm creating a new user account",
            intro_line="Use this code to confirm that you want to create a new user account.",
        )
    except Exception:
        logger.exception("Failed to send admin create-user OTP")
        _ADMIN_CREATE_USER_STORE.pop(session_id, None)
        raise HTTPException(status_code=500, detail="Failed to send verification email.")

    logger.info(
        "ADMIN_CREATE_USER_CHALLENGE admin_id=%s new_email=%s session=%s",
        admin_id,
        new_email,
        session_id,
    )

    return {
        "session": session_id,
        "expires_in_seconds": OTP_EXPIRE_MINUTES * 60,
        "message": f"Verification code sent to {admin_email}",
    }


@router.post("/admin/create-user/confirm")
async def admin_create_user_confirm(
    body: AdminCreateUserConfirmBody,
    current_user: dict = Depends(_require_super_admin_only),
    db=Depends(get_db),
):
    """
    Verify OTP and provision the new Cognito user, profile, and role.
    """
    session_id = (body.session or "").strip()
    if not session_id.startswith(_ADMIN_CREATE_USER_PREFIX):
        raise HTTPException(status_code=400, detail="Invalid session.")

    admin_id = str((current_user or {}).get("id") or "")
    entry = _ADMIN_CREATE_USER_STORE.get(session_id)
    if not entry:
        raise HTTPException(status_code=400, detail="Invalid or expired session.")

    if str(entry.get("admin_user_id")) != admin_id:
        raise HTTPException(status_code=400, detail="Session does not match the current user.")

    now = datetime.datetime.now(datetime.timezone.utc)
    expires_at = entry.get("expires_at")
    if not expires_at or expires_at <= now:
        _ADMIN_CREATE_USER_STORE.pop(session_id, None)
        raise HTTPException(status_code=400, detail="Verification code expired.")

    expected_otp = str(entry.get("otp") or "").strip()
    actual_otp = str(body.otp or "").strip()
    if expected_otp != actual_otp:
        raise HTTPException(
            status_code=400,
            detail="Invalid verification code. Try again or request a new code.",
        )

    pending = entry.get("pending") or {}
    new_email = str(pending.get("new_email") or "").strip().lower()
    password = str(pending.get("password") or "")
    full_name = str(pending.get("full_name") or "").strip()
    department = str(pending.get("department") or "").strip()
    phone = str(pending.get("phone") or "").strip()
    raw_role_ids = pending.get("role_ids")
    if not isinstance(raw_role_ids, list) or not raw_role_ids:
        legacy = pending.get("role_id")
        raw_role_ids = [legacy] if legacy else []
    role_ids = [str(x) for x in raw_role_ids if x]

    if not new_email or not password or not full_name or not role_ids:
        _ADMIN_CREATE_USER_STORE.pop(session_id, None)
        raise HTTPException(status_code=400, detail="Invalid pending session payload.")

    # Final duplicate check
    if await _email_exists_in_db(db, new_email) or await _email_exists_in_cognito(new_email):
        _ADMIN_CREATE_USER_STORE.pop(session_id, None)
        raise HTTPException(status_code=400, detail="This email is already registered.")

    cognito_username = str(uuid.uuid4())
    user_attrs: list[dict[str, str]] = [
        {"Name": "email", "Value": new_email},
        {"Name": "email_verified", "Value": "true"},
        {"Name": "name", "Value": full_name},
    ]
    if phone:
        user_attrs.append({"Name": "phone_number", "Value": phone})

    try:
        create_resp = cognito_client.admin_create_user(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=cognito_username,
            UserAttributes=user_attrs,
            MessageAction="SUPPRESS",
            TemporaryPassword=password,
        )
    except ClientError as e:
        logger.error("AdminCreateUser failed: %s", e)
        raise HTTPException(
            status_code=400,
            detail=e.response.get("Error", {}).get("Message", "Failed to create Cognito user"),
        )

    user_obj = create_resp.get("User") or {}
    user_sub = _cognito_sub_from_user_response(user_obj, cognito_username)

    try:
        cognito_client.admin_set_user_password(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=cognito_username,
            Password=password,
            Permanent=True,
        )
    except ClientError as e:
        logger.error("AdminSetUserPassword failed, rolling back Cognito user: %s", e)
        try:
            cognito_client.admin_delete_user(
                UserPoolId=COGNITO_USER_POOL_ID,
                Username=cognito_username,
            )
        except ClientError:
            logger.exception("Could not delete Cognito user after password failure")
        raise HTTPException(
            status_code=400,
            detail=e.response.get("Error", {}).get("Message", "Failed to set password"),
        )

    profile_id = str(uuid.uuid4())
    now_db = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    # Fetch the creating admin's organization so the new user is linked to the same org
    admin_org_id = await db.fetchval(
        "SELECT organization_id::text FROM organization_users WHERE user_id = $1::uuid LIMIT 1",
        admin_id,
    )

    # Resolve the role name for role_in_org (use the first assigned role, fallback to 'member')
    role_in_org = "member"
    if role_ids:
        resolved_role_name = await db.fetchval(
            "SELECT name FROM roles WHERE id = $1::uuid LIMIT 1",
            role_ids[0],
        )
        if resolved_role_name:
            role_in_org = str(resolved_role_name)

    try:
        async with db.transaction():
            await db.execute(
                """
                INSERT INTO user_profiles (
                    id, cognito_sub, email, full_name, department, phone_number, is_active, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, TRUE, $7, $7)
                """,
                profile_id,
                user_sub,
                new_email,
                full_name,
                department or None,
                phone or None,
                now_db,
            )
            for rid in role_ids:
                await db.execute(
                    """
                    INSERT INTO user_roles (id, user_id, role_id, assigned_by)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (user_id, role_id) DO NOTHING
                    """,
                    str(uuid.uuid4()),
                    profile_id,
                    rid,
                    admin_id,
                )
            if admin_org_id:
                await db.execute(
                    """
                    INSERT INTO organization_users (id, organization_id, user_id, role_in_org, is_owner)
                    VALUES ($1, $2::uuid, $3::uuid, $4, FALSE)
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    str(uuid.uuid4()),
                    admin_org_id,
                    profile_id,
                    role_in_org,
                )
    except Exception as db_err:
        logger.exception("DB insert failed after Cognito user created; cleaning up Cognito")
        try:
            cognito_client.admin_delete_user(
                UserPoolId=COGNITO_USER_POOL_ID,
                Username=cognito_username,
            )
        except ClientError:
            logger.exception("Could not delete Cognito user after DB failure")
        raise HTTPException(status_code=500, detail="Failed to save user profile.") from db_err

    _ADMIN_CREATE_USER_STORE.pop(session_id, None)

    role_label = role_in_org
    if role_ids:
        aggregated = await db.fetchval(
            """
            SELECT string_agg(COALESCE(display_name, name), ', ' ORDER BY name)
            FROM roles WHERE id = ANY($1::uuid[])
            """,
            role_ids,
        )
        if aggregated:
            role_label = str(aggregated)

    try:
        await asyncio.to_thread(
            send_welcome_email_sync,
            to_email=new_email,
            recipient_name=full_name,
            temp_password=password,
            role_name=role_label,
        )
    except Exception:
        logger.exception("Failed to send welcome email to %s", new_email)

    logger.info(
        "ADMIN_CREATE_USER_OK admin_id=%s new_user_id=%s email=%s",
        admin_id,
        profile_id,
        new_email,
    )

    return {
        "message": "User created successfully.",
        "user_id": profile_id,
        "email": new_email,
    }


@router.post("/admin/create-user/resend")
async def admin_create_user_resend(
    body: AdminCreateUserResendBody,
    current_user: dict = Depends(_require_super_admin_only),
    db=Depends(get_db),
):
    session_id = (body.session or "").strip()
    if not session_id.startswith(_ADMIN_CREATE_USER_PREFIX):
        raise HTTPException(status_code=400, detail="Invalid session.")

    admin_id = str((current_user or {}).get("id") or "")
    entry = _ADMIN_CREATE_USER_STORE.get(session_id)
    if not entry:
        raise HTTPException(status_code=400, detail="Invalid or expired session.")

    if str(entry.get("admin_user_id")) != admin_id:
        raise HTTPException(status_code=400, detail="Session does not match the current user.")

    admin_row = await db.fetchrow(
        "SELECT email, full_name FROM user_profiles WHERE id=$1",
        admin_id,
    )
    if not admin_row or not admin_row.get("email"):
        raise HTTPException(status_code=400, detail="Super Admin profile email not found.")

    otp = f"{secrets.randbelow(1000000):06d}"
    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=OTP_EXPIRE_MINUTES
    )
    entry["otp"] = otp
    entry["expires_at"] = expires_at

    admin_email = str(admin_row["email"])
    recipient_name = str(admin_row.get("full_name") or admin_email.split("@")[0])
    try:
        await asyncio.to_thread(
            send_mfa_otp_email_sync,
            to_email=admin_email,
            recipient_name=recipient_name,
            otp=otp,
            subject="Confirm creating a new user account",
            intro_line="Use this code to confirm that you want to create a new user account.",
        )
    except Exception:
        logger.exception("Failed to resend admin create-user OTP")
        raise HTTPException(status_code=500, detail="Failed to send verification email.")

    return {"session": session_id, "message": "Verification code resent."}


@router.post("/resend-code")
async def resend_code(data: ForgotPasswordRequest):
    try:
        cognito_username = resolve_cognito_username(data.email)
        if not cognito_username:
            raise HTTPException(
                status_code=400,
                detail="Username or Email not found"
            )
        secret_hash = get_secret_hash(cognito_username)

        kwargs = {
            "ClientId": COGNITO_APP_CLIENT_ID,
            "Username": cognito_username,
        }
        if secret_hash:
            kwargs["SecretHash"] = secret_hash

        cognito_client.resend_confirmation_code(**kwargs)
        return {"message": "Code resent."}
    except ClientError as e:
        raise HTTPException(status_code=400, detail=_friendly_cognito_error_message(e, context="resend_code"))


@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordRequest):
    email_norm = (data.email or "").strip().lower()
    cognito_username = resolve_cognito_username(email_norm)
    if not cognito_username:
        raise HTTPException(
            status_code=400,
            detail="Username or Email not found"
        )
    
    otp = f"{secrets.randbelow(1000000):06d}"
    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=OTP_EXPIRE_MINUTES
    )

    _FORGOT_PASSWORD_STORE[email_norm] = {
        "otp": otp,
        "expires_at": expires_at,
        "cognito_username": cognito_username
    }

    try:
        await asyncio.to_thread(
            send_mfa_otp_email_sync,
            to_email=email_norm,
            recipient_name=email_norm.split("@")[0],
            otp=otp,
            template_id="password_reset",
            intro_line="You requested a password reset.",
        )
    except Exception:
        logger.exception("Failed to send forgot password OTP email")
        raise HTTPException(status_code=500, detail="Failed to send reset email.")

    return {"message": "Password reset code sent."}


@router.post("/confirm-forgot-password")
async def confirm_forgot_password(data: ConfirmForgotPasswordRequest):
    email_norm = (data.email or "").strip().lower()
    entry = _FORGOT_PASSWORD_STORE.get(email_norm)
    
    if not entry:
        raise HTTPException(status_code=400, detail="Invalid or expired reset session.")
        
    now = datetime.datetime.now(datetime.timezone.utc)
    expires_at = entry.get("expires_at")
    
    if not expires_at or expires_at <= now:
        _FORGOT_PASSWORD_STORE.pop(email_norm, None)
        raise HTTPException(status_code=400, detail="Reset code expired.")
        
    expected_otp = str(entry.get("otp") or "").strip()
    actual_otp = str(data.code or "").strip()
    
    if expected_otp != actual_otp:
        raise HTTPException(status_code=400, detail="Invalid verification code.")

    cognito_username = entry.get("cognito_username")
    
    try:
        cognito_client.admin_set_user_password(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=cognito_username,
            Password=data.new_password,
            Permanent=True,
        )
        # Clear the OTP entry after successful reset
        _FORGOT_PASSWORD_STORE.pop(email_norm, None)
        return {"message": "Password reset successfully."}
    except ClientError as e:
        raise HTTPException(status_code=400, detail=_friendly_cognito_error_message(e, context="confirm_forgot_password"))


@router.post("/change-password")
async def change_password(
    data: PasswordChange,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Change the password for the currently authenticated user in AWS Cognito.
    Requires the user's current valid Access Token (from session cookie or Authorization header).
    """
    token = get_session_token(request) or ""
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    user_id = str((current_user or {}).get("id") or "")
    profile_row = await db.fetchrow(
        "SELECT email, full_name FROM user_profiles WHERE id=$1",
        user_id,
    ) if user_id else None
    to_email = (profile_row.get("email") if profile_row else None) or ""
    recipient_name = (profile_row.get("full_name") if profile_row else None) or to_email
    org_slug = None
    if user_id:
        org_slug = await db.fetchval(
            """
            SELECT o.slug FROM organization_users ou
            JOIN organizations o ON o.id = ou.organization_id
            WHERE ou.user_id = $1::uuid LIMIT 1
            """,
            user_id,
        )

    # Bypass Cognito for demo tokens
    if try_decode_demo_token(token):
        logger.info("Demo user: skipping real Cognito change-password call.")
        if to_email:
            try:
                await asyncio.to_thread(
                    send_password_changed_email_sync,
                    to_email=to_email,
                    recipient_name=recipient_name,
                    org_slug=str(org_slug) if org_slug else None,
                )
            except Exception:
                logger.exception("Failed to send password-changed email to %s", to_email)
        return {"message": "Password changed successfully (Demo)."}

    if (data.old_password or "") == (data.new_password or ""):
        raise HTTPException(
            status_code=400,
            detail="New password cannot be the same as your current password.",
        )

    try:
        cognito_client.change_password(
            PreviousPassword=data.old_password,
            ProposedPassword=data.new_password,
            AccessToken=token,
        )
        if to_email:
            try:
                await asyncio.to_thread(
                    send_password_changed_email_sync,
                    to_email=to_email,
                    recipient_name=recipient_name,
                    org_slug=str(org_slug) if org_slug else None,
                )
            except Exception:
                logger.exception("Failed to send password-changed email to %s", to_email)
        return {"message": "Password changed successfully."}
    except ClientError as e:
        logger.error("Cognito Change Password Error: %s", e)
        raise HTTPException(
            status_code=400,
            detail=e.response.get("Error", {}).get("Message", "Failed to change password"),
        )


@router.post("/logout")
async def logout(request: Request, response: Response):
    """
    Globally sign out the user from all devices in AWS Cognito and clear the
    session cookie. Invalidates all Access/ID tokens issued so far.
    """
    token = get_session_token(request) or ""
    # Always clear the cookie so the SPA loses its session even if Cognito call fails.
    clear_access_token_cookie(response)
    clear_refresh_token_cookie(response)

    if not token or try_decode_demo_token(token):
        # Demo users have no Cognito session; cookie clear is enough.
        return {"message": "Successfully logged out."}

    try:
        cognito_client.global_sign_out(AccessToken=token)
        return {"message": "Successfully logged out."}
    except ClientError as e:
        logger.error("Cognito Logout Error: %s", e)
        # Cookie has already been cleared above; surface a soft success so the SPA can proceed.
        return {
            "message": "Logged out locally.",
            "warning": e.response.get("Error", {}).get("Message", "Failed to invalidate Cognito session"),
        }


@router.post("/refresh")
async def refresh_token(request: Request, response: Response, db=Depends(get_db)):
    """
    Use the refresh token cookie to get a new access token.
    """
    refresh_token = request.cookies.get(ACCESS_REFRESH_TOKEN_COOKIE_NAME)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token available")

    kwargs = {
        "ClientId": COGNITO_APP_CLIENT_ID,
        "AuthFlow": "REFRESH_TOKEN_AUTH",
        "AuthParameters": {
            "REFRESH_TOKEN": refresh_token,
        },
    }

    try:
        res = cognito_client.initiate_auth(**kwargs)
        auth_result = res.get("AuthenticationResult")
        if not auth_result:
            raise HTTPException(status_code=401, detail="Refresh failed")

        new_access_token = auth_result["AccessToken"]
        expires_in = auth_result["ExpiresIn"]
        
        # Sometimes Cognito returns a new refresh token, sometimes it doesn't.
        # If it does, we update it.
        new_refresh_token = auth_result.get("RefreshToken")

        set_access_token_cookie(response, new_access_token, expires_in=expires_in)
        if new_refresh_token:
            set_refresh_token_cookie(response, new_refresh_token)

        return {"message": "Token refreshed", "token_in_cookie": True}
    except ClientError as e:
        logger.error("Cognito Refresh Error: %s", e)
        clear_access_token_cookie(response)
        clear_refresh_token_cookie(response)
        raise HTTPException(status_code=401, detail="Refresh token expired or invalid")






