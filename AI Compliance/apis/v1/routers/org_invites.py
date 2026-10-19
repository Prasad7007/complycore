import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from apis.core.database import get_db
from apis.core.security import get_current_user, require_app_access_ready, require_tenant_context

router = APIRouter(prefix="/invites", tags=["org-invites"])

accept_router = APIRouter(prefix="/invites", tags=["invites-accept"])


class OrgInviteCreate(BaseModel):
    email: EmailStr
    role_in_org: str = Field(default="marketing", max_length=80)


class OrgInviteCreateResponse(BaseModel):
    invite_id: str
    token: str
    email: str
    role_in_org: str


class OrgInviteAcceptRequest(BaseModel):
    token: str


@router.post("", response_model=OrgInviteCreateResponse)
async def create_organization_invite(
    body: OrgInviteCreate,
    tenant_ctx: dict = Depends(require_tenant_context),
    current_user: dict = Depends(require_app_access_ready),
    db=Depends(get_db),
):
    if (tenant_ctx.get("role_in_org") or "").strip().lower() != "super_admin":
        raise HTTPException(status_code=403, detail="Only organization super_admin can create invites.")

    org_id = tenant_ctx["organization_id"]
    email_norm = str(body.email).strip().lower()
    role = (body.role_in_org or "marketing").strip() or "marketing"

    existing_member = await db.fetchval(
        """
        SELECT 1 FROM organization_users ou
        JOIN user_profiles up ON up.id = ou.user_id
        WHERE ou.organization_id = $1::uuid AND lower(up.email) = lower($2)
        LIMIT 1
        """,
        org_id,
        email_norm,
    )
    if existing_member:
        raise HTTPException(status_code=409, detail="User is already a member of this organization.")

    invite_id = str(uuid.uuid4())
    token = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expires = now + timedelta(days=14)

    await db.execute(
        """
        INSERT INTO organization_invites (id, organization_id, email, token, role_in_org, created_at, expires_at)
        VALUES ($1, $2::uuid, $3, $4::uuid, $5, $6, $7)
        """,
        invite_id,
        org_id,
        email_norm,
        str(token),
        role,
        now,
        expires,
    )

    return OrgInviteCreateResponse(
        invite_id=invite_id,
        token=str(token),
        email=email_norm,
        role_in_org=role,
    )


@accept_router.post("/accept")
async def accept_organization_invite(
    body: OrgInviteAcceptRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    user_id = str((current_user or {}).get("id") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = (body.token or "").strip()
    try:
        token_uuid = uuid.UUID(token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid invite token.") from e

    profile = await db.fetchrow("SELECT id, email FROM user_profiles WHERE id = $1::uuid", user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    invite = await db.fetchrow(
        """
        SELECT id, organization_id, email, role_in_org, expires_at, accepted_at
        FROM organization_invites
        WHERE token = $1::uuid
        LIMIT 1
        """,
        str(token_uuid),
    )
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")

    if invite.get("accepted_at"):
        raise HTTPException(status_code=409, detail="Invite already used.")

    exp: Optional[datetime] = invite.get("expires_at")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if exp and exp < now:
        raise HTTPException(status_code=410, detail="Invite expired.")

    invite_email = (invite.get("email") or "").strip().lower()
    user_email = (profile.get("email") or "").strip().lower()
    if invite_email != user_email:
        raise HTTPException(status_code=403, detail="Invite email does not match your account.")

    has_org = await db.fetchval("SELECT 1 FROM organization_users WHERE user_id = $1::uuid LIMIT 1", user_id)
    if has_org:
        raise HTTPException(status_code=409, detail="You already belong to an organization.")

    link_id = str(uuid.uuid4())
    async with db.transaction():
        await db.execute(
            """
            INSERT INTO organization_users (id, organization_id, user_id, role_in_org, is_owner)
            VALUES ($1, $2::uuid, $3::uuid, $4, FALSE)
            """,
            link_id,
            str(invite["organization_id"]),
            user_id,
            invite["role_in_org"] or "marketing",
        )
        await db.execute(
            "UPDATE organization_invites SET accepted_at = $1 WHERE id = $2::uuid",
            now,
            str(invite["id"]),
        )

    return {"ok": True, "organization_id": str(invite["organization_id"])}
