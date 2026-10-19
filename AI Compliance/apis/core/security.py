import os
import logging
import datetime
from typing import Optional
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from dotenv import load_dotenv
import httpx
from .database import get_db

load_dotenv()
logger = logging.getLogger(__name__)

AWS_REGION = os.getenv("AWS_REGION")
COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID")
COGNITO_APP_CLIENT_ID = os.getenv("COGNITO_APP_CLIENT_ID")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
APP_ENV = os.getenv("APP_ENV", "development")

# Session cookie configuration. Default name kept short and non-revealing.
ACCESS_TOKEN_COOKIE_NAME = os.getenv("ACCESS_TOKEN_COOKIE_NAME", "ac_session")
# Cookie path - scoped to API so it isn't sent on static asset requests.
ACCESS_TOKEN_COOKIE_PATH = os.getenv("ACCESS_TOKEN_COOKIE_PATH", "/api/v1")
# SameSite policy: "lax" works for same-site SPA + API behind one origin (nginx).
# Switch to "none" only when SPA and API live on different registrable domains
# (requires Secure=True and a CSRF strategy).
ACCESS_TOKEN_COOKIE_SAMESITE = (os.getenv("ACCESS_TOKEN_COOKIE_SAMESITE", "lax") or "lax").lower()
# Secure flag default: True in production, False otherwise so plain HTTP localhost dev works.
_secure_env = os.getenv("COOKIE_SECURE")
if _secure_env is None:
    ACCESS_TOKEN_COOKIE_SECURE = APP_ENV == "production"
else:
    ACCESS_TOKEN_COOKIE_SECURE = _secure_env.strip().lower() in {"1", "true", "yes", "on"}
# Optional fixed Domain for the cookie (e.g. ".example.com"). Empty = host-only cookie.
ACCESS_TOKEN_COOKIE_DOMAIN = (os.getenv("ACCESS_TOKEN_COOKIE_DOMAIN") or "").strip() or None

ACCESS_REFRESH_TOKEN_COOKIE_NAME = os.getenv("ACCESS_REFRESH_TOKEN_COOKIE_NAME", "ac_refresh")

DEMO_LOGIN_ENABLED = os.getenv("DEMO_LOGIN_ENABLED", "false").lower() == "true" and APP_ENV != "production"
DEMO_LOGIN_PASSWORD = os.getenv("DEMO_LOGIN_PASSWORD", "password123")
DEMO_LOGIN_EMAILS = {
    email.strip().lower()
    for email in os.getenv(
        "DEMO_LOGIN_EMAILS",
        "marketing@company.com,sme@company.com,compliance@company.com,superadmin@company.com,profile@company.com",
    ).split(",")
    if email.strip()
}
DEMO_JWT_SECRET = os.getenv("DEMO_JWT_SECRET", SECRET_KEY)


def is_demo_seed_email(email: str | None) -> bool:
    """True for emails in DEMO_LOGIN_EMAILS (default seed accounts). Used to relax org-gating in /users/me."""
    if not email or not str(email).strip():
        return False
    return str(email).strip().lower() in DEMO_LOGIN_EMAILS


# auto_error=False so we can fall back to httpOnly cookie when Authorization is absent.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def _extract_bearer_from_header(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if not auth:
        return None
    parts = auth.strip().split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        value = parts[1].strip()
        return value or None
    return None


def get_session_token(request: Request) -> Optional[str]:
    """Resolve the access token from the httpOnly cookie, then Authorization header.

    Returns ``None`` if neither source has a value (caller decides on 401).
    """
    cookie_token = (request.cookies.get(ACCESS_TOKEN_COOKIE_NAME) or "").strip()
    if cookie_token:
        return cookie_token
    return _extract_bearer_from_header(request)


def set_access_token_cookie(
    response: Response,
    token: str,
    *,
    expires_in: Optional[int] = None,
) -> None:
    """Attach the session cookie to ``response`` using configured policy."""
    if not token:
        return
    
    import datetime
    max_age_val = int(expires_in) if expires_in and int(expires_in) > 0 else None
    expires_val = None
    if max_age_val is not None:
        expires_val = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=max_age_val)

    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE_NAME,
        value=token,
        max_age=max_age_val,
        expires=expires_val,
        path=ACCESS_TOKEN_COOKIE_PATH,
        domain=ACCESS_TOKEN_COOKIE_DOMAIN,
        secure=ACCESS_TOKEN_COOKIE_SECURE,
        httponly=True,
        samesite=ACCESS_TOKEN_COOKIE_SAMESITE,
    )


def clear_access_token_cookie(response: Response) -> None:
    """Delete the session cookie using the same scope it was set with."""
    response.delete_cookie(
        key=ACCESS_TOKEN_COOKIE_NAME,
        path=ACCESS_TOKEN_COOKIE_PATH,
        domain=ACCESS_TOKEN_COOKIE_DOMAIN,
        secure=ACCESS_TOKEN_COOKIE_SECURE,
        httponly=True,
        samesite=ACCESS_TOKEN_COOKIE_SAMESITE,
    )


def set_refresh_token_cookie(
    response: Response,
    token: str,
    *,
    expires_in: Optional[int] = 3 * 60 * 60, # 3 hours default (10800 seconds)
) -> None:
    """Attach the refresh token cookie to ``response`` using configured policy."""
    if not token:
        return

    import datetime
    max_age_val = int(expires_in) if expires_in and int(expires_in) > 0 else None
    expires_val = None
    if max_age_val is not None:
        expires_val = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=max_age_val)

    response.set_cookie(
        key=ACCESS_REFRESH_TOKEN_COOKIE_NAME,
        value=token,
        max_age=max_age_val,
        expires=expires_val,
        path=ACCESS_TOKEN_COOKIE_PATH,
        domain=ACCESS_TOKEN_COOKIE_DOMAIN,
        secure=ACCESS_TOKEN_COOKIE_SECURE,
        httponly=True,
        samesite=ACCESS_TOKEN_COOKIE_SAMESITE,
    )


def clear_refresh_token_cookie(response: Response) -> None:
    """Delete the refresh token cookie using the same scope it was set with."""
    response.delete_cookie(
        key=ACCESS_REFRESH_TOKEN_COOKIE_NAME,
        path=ACCESS_TOKEN_COOKIE_PATH,
        domain=ACCESS_TOKEN_COOKIE_DOMAIN,
        secure=ACCESS_TOKEN_COOKIE_SECURE,
        httponly=True,
        samesite=ACCESS_TOKEN_COOKIE_SAMESITE,
    )

class CognitoVerifier:
    def __init__(self):
        self.jwks = None
        self.jwks_url = f"https://cognito-idp.{AWS_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}/.well-known/jwks.json"

    async def get_jwks(self):
        if self.jwks:
            return self.jwks
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.jwks_url)
                response.raise_for_status()
                self.jwks = response.json()
        except Exception as e:
            logger.error(f"Failed to fetch JWKS: {e}")
            raise HTTPException(status_code=500, detail="Internal Auth Error")
        return self.jwks

    async def verify_token(self, token: str) -> str:
        try:
            # Get headers to find kid
            headers = jwt.get_unverified_headers(token)
            kid = headers.get("kid")
            if not kid:
                raise HTTPException(status_code=401, detail="Invalid token headers")

            jwks = await self.get_jwks()
            key = next((k for k in jwks.get("keys", []) if k["kid"] == kid), None)
            
            if not key:
                # Refresh JWKS once if key not found
                self.jwks = None
                jwks = await self.get_jwks()
                key = next((k for k in jwks.get("keys", []) if k["kid"] == kid), None)
                if not key:
                    raise HTTPException(status_code=401, detail="Invalid token key")

            # Construct public key from JWK
            # python-jose handles JWK dicts directly if passed as 'key'? 
            # No, usually need to construct it or pass the key dict if library supports it.
            # python-jose supports JWK dicts in jwt.decode/jwt.verify/construct_public_key usually?
            # actually python-jose decode accepts the key dict.
            
            payload = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=COGNITO_APP_CLIENT_ID,
                issuer=f"https://cognito-idp.{AWS_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}"
            )
            return payload.get("sub")
        except JWTError as e:
            logger.error(f"Token verification failed: {e}")
            raise HTTPException(status_code=401, detail="Invalid token")

verifier = CognitoVerifier()


def create_demo_access_token(email: str, expires_hours: int = 12) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": f"demo:{email.lower()}",
        "email": email.lower(),
        "token_use": "demo_access",
        "iat": int(now.timestamp()),
        "exp": int((now + datetime.timedelta(hours=expires_hours)).timestamp()),
    }
    return jwt.encode(payload, DEMO_JWT_SECRET, algorithm="HS256")


def try_decode_demo_token(token: str) -> str | None:
    if not DEMO_LOGIN_ENABLED:
        return None
    try:
        payload = jwt.decode(token, DEMO_JWT_SECRET, algorithms=["HS256"])
    except JWTError:
        return None
    if payload.get("token_use") != "demo_access":
        return None
    email = (payload.get("email") or "").strip().lower()
    return email or None

async def resolve_user_from_token(token: str, db) -> dict:
    """Resolve a user dict from a raw bearer token (Cognito or demo JWT).

    Centralized so cookie auth, header auth, and SSE callers share one verifier.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Token missing")

    demo_email = try_decode_demo_token(token)
    if demo_email:
        user_row = await db.fetchrow(
            "SELECT id, is_active, cognito_sub FROM user_profiles WHERE lower(email)=lower($1)",
            demo_email,
        )
        cognito_sub = user_row["cognito_sub"] if user_row else f"demo:{demo_email}"
    else:
        cognito_sub = await verifier.verify_token(token)
        user_row = await db.fetchrow(
            "SELECT id, is_active, cognito_sub FROM user_profiles WHERE cognito_sub=$1",
            cognito_sub,
        )

    if not user_row:
        raise HTTPException(status_code=401, detail="User not found in local records")

    if not user_row["is_active"]:
        raise HTTPException(status_code=401, detail="User is deactivated")

    user_id = str(user_row["id"])

    role_rows = await db.fetch(
        """
        SELECT r.name
        FROM user_roles ur
        JOIN roles r ON ur.role_id = r.id
        WHERE ur.user_id = $1
        """,
        user_id,
    )
    roles = [r["name"] for r in role_rows]

    return {"id": user_id, "roles": roles, "cognito_sub": cognito_sub}


async def get_current_user(
    request: Request,
    header_token: Optional[str] = Depends(oauth2_scheme),
    db=Depends(get_db),
):
    """FastAPI dependency that resolves the current user.

    Token source order: httpOnly cookie (``ACCESS_TOKEN_COOKIE_NAME``), then
    ``Authorization: Bearer ...`` header (kept for tooling/CLI and migration).
    SSE handlers that have only a query token should call
    :func:`resolve_user_from_token` directly.
    """
    cookie_token = (request.cookies.get(ACCESS_TOKEN_COOKIE_NAME) or "").strip()
    token = cookie_token or (header_token if isinstance(header_token, str) and header_token else "")
    if not token:
        raise HTTPException(status_code=401, detail="Token missing")
    return await resolve_user_from_token(token, db)


PROFILE_INCOMPLETE_MESSAGE = (
    "PROFILE_INCOMPLETE: Your administrator must assign your department and at least one role "
    "before you can use this feature."
)


async def assert_app_access_ready(db, user_id: str) -> None:
    """Raise 403 unless the user has at least one DB role and a non-empty department."""
    row = await db.fetchrow(
        """
        SELECT
            (SELECT COUNT(*)::int FROM user_roles ur WHERE ur.user_id = u.id) AS role_cnt,
            NULLIF(TRIM(COALESCE(u.department, '')), '') AS dept
        FROM user_profiles u
        WHERE u.id = $1::uuid
        """,
        user_id,
    )
    if not row or (row["role_cnt"] or 0) < 1 or not row["dept"]:
        raise HTTPException(status_code=403, detail=PROFILE_INCOMPLETE_MESSAGE)


async def require_app_access_ready(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """Use as Depends(...) instead of get_current_user on app routes that require full onboarding."""
    user_id = str((current_user or {}).get("id") or "")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    await assert_app_access_ready(db, user_id)
    return current_user


def require_owner_only(current_user: dict = Depends(get_current_user)) -> dict:
    roles = set((current_user or {}).get("roles") or [])
    if "owner" not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owner can access this endpoint.",
        )
    return current_user


PENDING_ORG_INVITE_CODE = "PENDING_ORG_INVITE"
OWNER_NO_TENANT_ACCESS_CODE = "OWNER_NO_TENANT_ACCESS"


async def build_tenant_context(org_slug: str, current_user: dict, db) -> dict:
    """
    Resolve tenant from URL slug and verify membership (no FastAPI Depends).
    Used by require_tenant_context and by SSE routes that authenticate via ?token=.
    """
    user_id = str((current_user or {}).get("id") or "")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    roles = list((current_user or {}).get("roles") or [])
    roles_set = {str(r).lower() for r in roles}

    if "owner" in roles_set:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": OWNER_NO_TENANT_ACCESS_CODE,
                "message": "Platform owner cannot access tenant document routes.",
            },
        )

    ou = await db.fetchrow(
        """
        SELECT ou.organization_id, ou.role_in_org, o.slug, o.name
        FROM organization_users ou
        JOIN organizations o ON o.id = ou.organization_id
        WHERE ou.user_id = $1::uuid
        LIMIT 1
        """,
        user_id,
    )
    if not ou:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": PENDING_ORG_INVITE_CODE,
                "message": "No organization membership. Accept an invite or wait for assignment.",
            },
        )

    slug_norm = (org_slug or "").strip().lower()
    if (ou["slug"] or "").strip().lower() != slug_norm:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    return {
        "user_id": user_id,
        "organization_id": str(ou["organization_id"]),
        "organization_slug": ou["slug"],
        "organization_name": ou["name"],
        "role_in_org": ou["role_in_org"] or "",
        "roles": roles,
    }


async def require_tenant_context(
    org_slug: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """FastAPI Depends wrapper for build_tenant_context."""
    return await build_tenant_context(org_slug, current_user, db)
