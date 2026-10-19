import asyncio
import datetime
import logging
import re
import uuid

from apis.core.mail import send_welcome_email_sync

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException
from typing import List

from apis.core.database import get_db
from apis.services.department_list import fetch_all_department_names
from apis.core.security import require_owner_only, COGNITO_USER_POOL_ID
from apis.models.organizations import (
    EffectiveUploadQuotaSettingsSummary,
    OrganizationBootstrapRequest,
    OrganizationBootstrapResponse,
    OrganizationListItem,
    OrganizationUploadQuotaDefaults,
    OrganizationUploadQuotaSettingsResponse,
    OrganizationUploadQuotaSettingsUpdate,
    SuperAdminCreateRequest,
    SuperAdminResponse,
)
from apis.services.upload_quota import (
    fetch_effective_upload_quota,
    organization_default_upload_quota,
)
from apis.v1.routers.auth import (
    _cognito_sub_from_user_response,
    _email_exists_in_cognito,
    _email_exists_in_db,
    cognito_client,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])
logger = logging.getLogger(__name__)


def _as_utc_naive(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value
    return value.astimezone(datetime.timezone.utc).replace(tzinfo=None)


async def _fetch_organization_or_404(db, organization_id: str):
    row = await db.fetchrow(
        """
        SELECT id::text AS id, name, slug, created_at
        FROM organizations
        WHERE id = $1::uuid
        LIMIT 1
        """,
        organization_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Organization not found.")
    return row


def _normalized_rollout_starts_at(org_created_at: datetime.datetime, rollout_starts_at: datetime.datetime) -> datetime.datetime:
    normalized_org_created_at = _as_utc_naive(org_created_at)
    normalized_rollout_starts_at = _as_utc_naive(rollout_starts_at)
    return max(normalized_org_created_at, normalized_rollout_starts_at)


async def _organization_upload_quota_settings_response(
    db,
    organization_id: str,
) -> OrganizationUploadQuotaSettingsResponse:
    org_row = await _fetch_organization_or_404(db, organization_id)
    settings_row = await db.fetchrow(
        """
        SELECT
            id::text AS quota_settings_id,
            quota_enabled,
            upload_limit_count,
            upload_limit_bytes,
            rollout_starts_at,
            updated_at,
            updated_by
        FROM organization_upload_quota_settings
        WHERE organization_id = $1::uuid
        LIMIT 1
        """,
        organization_id,
    )
    effective = await fetch_effective_upload_quota(db, organization_id)
    defaults = organization_default_upload_quota(org_row["created_at"])

    return OrganizationUploadQuotaSettingsResponse(
        organization_id=str(org_row["id"]),
        organization_slug=org_row["slug"],
        organization_name=org_row["name"],
        org_created_at=org_row["created_at"],
        quota_settings_id=(
            settings_row["quota_settings_id"]
            if settings_row
            else effective.get("quota_settings_id")
        ),
        quota_enabled=bool(effective["quota_enabled"]),
        upload_limit_count=int(effective["upload_limit_count"]),
        upload_limit_bytes=int(effective["upload_limit_bytes"]),
        rollout_starts_at=effective["rollout_starts_at"],
        rolling_window_days=int(effective["rolling_window_days"]),
        defaults=OrganizationUploadQuotaDefaults(
            quota_enabled=bool(defaults["quota_enabled"]),
            upload_limit_count=int(defaults["upload_limit_count"]),
            upload_limit_bytes=int(defaults["upload_limit_bytes"]),
            rollout_starts_at=defaults["rollout_starts_at"],
        ),
        effective_quota=EffectiveUploadQuotaSettingsSummary(
            quota_enabled=bool(effective["quota_enabled"]),
            upload_limit_count=int(effective["upload_limit_count"]),
            upload_limit_bytes=int(effective["upload_limit_bytes"]),
            rollout_starts_at=effective["rollout_starts_at"],
            rolling_window_days=int(effective["rolling_window_days"]),
        ),
        updated_at=settings_row["updated_at"] if settings_row else None,
        updated_by=str(settings_row["updated_by"]) if settings_row and settings_row["updated_by"] else None,
        bypass_active=bool(effective["bypass_active"]),
        bypass_reason=effective["bypass_reason"],
    )


@router.get("", response_model=list[OrganizationListItem])
async def list_organizations_for_owner(
    _current_user: dict = Depends(require_owner_only),
    db=Depends(get_db),
):
    """All organizations (owner console only)."""
    rows = await db.fetch(
        """
        SELECT id, name, slug, COALESCE(status, 'active') AS status, created_at
        FROM organizations
        ORDER BY created_at DESC NULLS LAST, name ASC
        """
    )
    return [
        OrganizationListItem(
            id=str(r["id"]),
            name=r["name"],
            slug=r["slug"],
            status=r["status"] or "active",
            created_at=r["created_at"],
        )
        for r in rows
    ]


@router.get("/departments", response_model=List[str])
async def list_departments_for_owner(
    _current_user: dict = Depends(require_owner_only),
    db=Depends(get_db),
):
    """All department names from the database (catalog + any used on user profiles)."""
    return await fetch_all_department_names(db)


@router.get("/{organization_id}/upload-quota", response_model=OrganizationUploadQuotaSettingsResponse)
async def get_organization_upload_quota_settings(
    organization_id: str,
    _current_user: dict = Depends(require_owner_only),
    db=Depends(get_db),
):
    return await _organization_upload_quota_settings_response(db, organization_id)


@router.put("/{organization_id}/upload-quota", response_model=OrganizationUploadQuotaSettingsResponse)
async def upsert_organization_upload_quota_settings(
    organization_id: str,
    body: OrganizationUploadQuotaSettingsUpdate,
    current_user: dict = Depends(require_owner_only),
    db=Depends(get_db),
):
    owner_user_id = str((current_user or {}).get("id") or "")
    if not owner_user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    org_row = await _fetch_organization_or_404(db, organization_id)
    normalized_rollout_starts_at = _normalized_rollout_starts_at(
        org_row["created_at"],
        body.rollout_starts_at,
    )

    await db.execute(
        """
        INSERT INTO organization_upload_quota_settings (
            id,
            organization_id,
            quota_enabled,
            upload_limit_count,
            upload_limit_bytes,
            rollout_starts_at,
            created_at,
            updated_at,
            updated_by
        )
        VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, NOW(), NOW(), $7::uuid)
        ON CONFLICT (organization_id) DO UPDATE SET
            quota_enabled = EXCLUDED.quota_enabled,
            upload_limit_count = EXCLUDED.upload_limit_count,
            upload_limit_bytes = EXCLUDED.upload_limit_bytes,
            rollout_starts_at = EXCLUDED.rollout_starts_at,
            updated_at = NOW(),
            updated_by = EXCLUDED.updated_by
        """,
        str(uuid.uuid4()),
        organization_id,
        body.quota_enabled,
        body.upload_limit_count,
        body.upload_limit_bytes,
        normalized_rollout_starts_at,
        owner_user_id,
    )
    return await _organization_upload_quota_settings_response(db, organization_id)


@router.post("/{organization_id}/upload-quota/reset", response_model=OrganizationUploadQuotaSettingsResponse)
async def reset_organization_upload_quota_settings(
    organization_id: str,
    current_user: dict = Depends(require_owner_only),
    db=Depends(get_db),
):
    owner_user_id = str((current_user or {}).get("id") or "")
    if not owner_user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    org_row = await _fetch_organization_or_404(db, organization_id)
    defaults = organization_default_upload_quota(org_row["created_at"])
    await db.execute(
        """
        INSERT INTO organization_upload_quota_settings (
            id,
            organization_id,
            quota_enabled,
            upload_limit_count,
            upload_limit_bytes,
            rollout_starts_at,
            created_at,
            updated_at,
            updated_by
        )
        VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, NOW(), NOW(), $7::uuid)
        ON CONFLICT (organization_id) DO UPDATE SET
            quota_enabled = EXCLUDED.quota_enabled,
            upload_limit_count = EXCLUDED.upload_limit_count,
            upload_limit_bytes = EXCLUDED.upload_limit_bytes,
            rollout_starts_at = EXCLUDED.rollout_starts_at,
            updated_at = NOW(),
            updated_by = EXCLUDED.updated_by
        """,
        str(uuid.uuid4()),
        organization_id,
        bool(defaults["quota_enabled"]),
        int(defaults["upload_limit_count"]),
        int(defaults["upload_limit_bytes"]),
        defaults["rollout_starts_at"],
        owner_user_id,
    )
    return await _organization_upload_quota_settings_response(db, organization_id)


def _normalize_slug(raw_slug: str) -> str:
    slug = (raw_slug or "").strip().lower()
    slug = re.sub(r"[^a-z0-9-]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if len(slug) < 2:
        raise HTTPException(status_code=400, detail="organization_slug must contain at least 2 valid characters.")
    return slug


@router.post("/bootstrap", response_model=OrganizationBootstrapResponse)
async def bootstrap_organization(
    body: OrganizationBootstrapRequest,
    current_user: dict = Depends(require_owner_only),
    db=Depends(get_db),
):
    owner_user_id = str((current_user or {}).get("id") or "")
    if not owner_user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    org_name = (body.organization_name or "").strip()
    org_slug = _normalize_slug(body.organization_slug)
    superadmin_email = (body.superadmin_email or "").strip().lower()
    superadmin_name = (body.superadmin_full_name or "").strip()
    superadmin_password = body.superadmin_password
    superadmin_department = (body.superadmin_department or "").strip()
    superadmin_phone = (body.superadmin_phone or "").strip() or None

    if not org_name:
        raise HTTPException(status_code=400, detail="organization_name is required.")
    if not superadmin_email:
        raise HTTPException(status_code=400, detail="superadmin_email is required.")
    if not superadmin_name:
        raise HTTPException(status_code=400, detail="superadmin_full_name is required.")
    if not superadmin_department:
        raise HTTPException(status_code=400, detail="superadmin_department is required.")

    existing_org = await db.fetchrow(
        "SELECT id FROM organizations WHERE lower(name)=lower($1) OR lower(slug)=lower($2) LIMIT 1",
        org_name,
        org_slug,
    )
    if existing_org:
        raise HTTPException(status_code=409, detail="Organization with this name or slug already exists.")

    if await _email_exists_in_db(db, superadmin_email):
        raise HTTPException(
            status_code=409,
            detail="This superadmin email already exists in the application database.",
        )
    if await _email_exists_in_cognito(superadmin_email):
        raise HTTPException(
            status_code=409,
            detail=(
                "This superadmin email is already registered in Cognito. "
                "Remove that Cognito user or pick a different email (leftover users can remain after a failed bootstrap)."
            ),
        )

    owner_has_org_membership = await db.fetchval(
        "SELECT EXISTS(SELECT 1 FROM organization_users WHERE user_id = $1::uuid)",
        owner_user_id,
    )

    super_admin_role = await db.fetchrow("SELECT id FROM roles WHERE name='super_admin' LIMIT 1")
    if not super_admin_role:
        raise HTTPException(status_code=500, detail="Role super_admin is not configured.")

    cognito_username = str(uuid.uuid4())
    user_attrs = [
        {"Name": "email", "Value": superadmin_email},
        {"Name": "email_verified", "Value": "true"},
        {"Name": "name", "Value": superadmin_name},
    ]
    # Cognito only accepts E.164; store any string up to 20 chars in DB regardless.
    if superadmin_phone and re.fullmatch(r"\+[1-9]\d{6,14}", superadmin_phone):
        user_attrs.append({"Name": "phone_number", "Value": superadmin_phone})

    try:
        create_resp = cognito_client.admin_create_user(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=cognito_username,
            UserAttributes=user_attrs,
            MessageAction="SUPPRESS",
            TemporaryPassword=superadmin_password,
        )
        cognito_client.admin_set_user_password(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=cognito_username,
            Password=superadmin_password,
            Permanent=True,
        )
    except ClientError as e:
        logger.error("Failed to provision Cognito superadmin for org bootstrap: %s", e)
        raise HTTPException(status_code=400, detail="Failed to create superadmin in Cognito.")

    user_obj = create_resp.get("User") or {}
    user_sub = _cognito_sub_from_user_response(user_obj, cognito_username)

    org_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())
    owner_link_id = str(uuid.uuid4())
    superadmin_link_id = str(uuid.uuid4())
    quota_settings_id = str(uuid.uuid4())
    now_db = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    try:
        async with db.transaction():
            await db.execute(
                """
                INSERT INTO organizations (id, name, slug, status, created_at, updated_at)
                VALUES ($1, $2, $3, 'active', $4, $4)
                """,
                org_id,
                org_name,
                org_slug,
                now_db,
            )

            quota_defaults = organization_default_upload_quota(now_db)
            await db.execute(
                """
                INSERT INTO organization_upload_quota_settings (
                    id,
                    organization_id,
                    quota_enabled,
                    upload_limit_count,
                    upload_limit_bytes,
                    rollout_starts_at,
                    created_at,
                    updated_at,
                    updated_by
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $7, $8::uuid)
                """,
                quota_settings_id,
                org_id,
                bool(quota_defaults["quota_enabled"]),
                int(quota_defaults["upload_limit_count"]),
                int(quota_defaults["upload_limit_bytes"]),
                quota_defaults["rollout_starts_at"],
                now_db,
                owner_user_id,
            )

            await db.execute(
                """
                INSERT INTO user_profiles (
                    id, cognito_sub, email, full_name, department, phone_number, is_active, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, TRUE, $7, $7)
                """,
                profile_id,
                user_sub,
                superadmin_email,
                superadmin_name,
                superadmin_department,
                superadmin_phone,
                now_db,
            )

            await db.execute(
                """
                INSERT INTO user_roles (id, user_id, role_id, assigned_by)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id, role_id) DO NOTHING
                """,
                str(uuid.uuid4()),
                profile_id,
                str(super_admin_role["id"]),
                owner_user_id,
            )

            # organization_users has UNIQUE(user_id): link the platform owner at most once globally.
            if not owner_has_org_membership:
                await db.execute(
                    """
                    INSERT INTO organization_users (id, organization_id, user_id, role_in_org, is_owner)
                    VALUES ($1, $2, $3, 'owner', TRUE)
                    """,
                    owner_link_id,
                    org_id,
                    owner_user_id,
                )

            await db.execute(
                """
                INSERT INTO organization_users (id, organization_id, user_id, role_in_org, is_owner)
                VALUES ($1, $2, $3, 'super_admin', FALSE)
                """,
                superadmin_link_id,
                org_id,
                profile_id,
            )
    except Exception as db_err:
        logger.exception("Organization bootstrap DB transaction failed, rolling back Cognito user")
        try:
            cognito_client.admin_delete_user(
                UserPoolId=COGNITO_USER_POOL_ID,
                Username=cognito_username,
            )
        except ClientError:
            logger.exception("Failed to rollback Cognito user after DB failure")
        raise HTTPException(status_code=500, detail="Failed to persist organization bootstrap.") from db_err

    try:
        await asyncio.to_thread(
            send_welcome_email_sync,
            to_email=superadmin_email,
            recipient_name=superadmin_name,
            temp_password=superadmin_password,
            role_name="Super Admin",
        )
    except Exception:
        logger.exception("Failed to send welcome email to %s", superadmin_email)

    return OrganizationBootstrapResponse(
        organization_id=org_id,
        organization_slug=org_slug,
        superadmin_user_id=profile_id,
        superadmin_email=superadmin_email,
        message="Organization and superadmin created successfully.",
    )


@router.get("/{organization_id}/superadmins", response_model=List[SuperAdminResponse])
async def list_organization_superadmins(
    organization_id: str,
    _current_user: dict = Depends(require_owner_only),
    db=Depends(get_db),
):
    """List all super admins for a given organization."""
    await _fetch_organization_or_404(db, organization_id)
    
    rows = await db.fetch(
        """
        SELECT 
            up.id as user_id, 
            up.email, 
            up.full_name, 
            up.department, 
            up.phone_number, 
            up.created_at,
            up.is_active
        FROM organization_users ou
        JOIN user_profiles up ON ou.user_id = up.id
        JOIN user_roles ur ON ur.user_id = up.id
        JOIN roles r ON r.id = ur.role_id
        WHERE ou.organization_id = $1::uuid 
          AND r.name = 'super_admin'
        ORDER BY up.created_at DESC
        """,
        organization_id
    )
    
    return [
        SuperAdminResponse(
            user_id=str(r["user_id"]),
            email=r["email"],
            full_name=r["full_name"],
            department=r["department"],
            phone_number=r["phone_number"],
            created_at=r["created_at"],
            is_active=r["is_active"],
        )
        for r in rows
    ]


@router.post("/{organization_id}/superadmins", response_model=SuperAdminResponse)
async def create_organization_superadmin(
    organization_id: str,
    body: SuperAdminCreateRequest,
    current_user: dict = Depends(require_owner_only),
    db=Depends(get_db),
):
    """Add a new super admin to an existing organization."""
    owner_user_id = str((current_user or {}).get("id") or "")
    if not owner_user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    await _fetch_organization_or_404(db, organization_id)

    superadmin_email = body.email.strip().lower()
    superadmin_name = body.full_name.strip()
    superadmin_password = body.password
    superadmin_phone = (body.phone_number or "").strip() or None
    # Hardcode department for new super admins as per requirement
    superadmin_department = "Super Admin"

    if await _email_exists_in_db(db, superadmin_email):
        raise HTTPException(
            status_code=409,
            detail="This email already exists in the application database.",
        )
    if await _email_exists_in_cognito(superadmin_email):
        raise HTTPException(
            status_code=409,
            detail=(
                "This email is already registered in Cognito. "
                "Remove that Cognito user or pick a different email."
            ),
        )

    super_admin_role = await db.fetchrow("SELECT id FROM roles WHERE name='super_admin' LIMIT 1")
    if not super_admin_role:
        raise HTTPException(status_code=500, detail="Role super_admin is not configured.")

    cognito_username = str(uuid.uuid4())
    user_attrs = [
        {"Name": "email", "Value": superadmin_email},
        {"Name": "email_verified", "Value": "true"},
        {"Name": "name", "Value": superadmin_name},
    ]
    if superadmin_phone and re.fullmatch(r"\+[1-9]\d{6,14}", superadmin_phone):
        user_attrs.append({"Name": "phone_number", "Value": superadmin_phone})

    try:
        create_resp = cognito_client.admin_create_user(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=cognito_username,
            UserAttributes=user_attrs,
            MessageAction="SUPPRESS",
            TemporaryPassword=superadmin_password,
        )
        try:
            cognito_client.admin_set_user_password(
                UserPoolId=COGNITO_USER_POOL_ID,
                Username=cognito_username,
                Password=superadmin_password,
                Permanent=True,
            )
        except ClientError as pwd_err:
            logger.exception("Failed to set permanent password for new superadmin, rolling back Cognito user")
            try:
                cognito_client.admin_delete_user(
                    UserPoolId=COGNITO_USER_POOL_ID,
                    Username=cognito_username,
                )
            except ClientError:
                pass
            raise HTTPException(status_code=400, detail="Failed to configure superadmin password (may not meet complexity requirements).") from pwd_err
    except ClientError as e:
        logger.error("Failed to provision Cognito superadmin for org: %s", e)
        raise HTTPException(status_code=400, detail="Failed to create superadmin in Cognito.")

    user_obj = create_resp.get("User") or {}
    user_sub = _cognito_sub_from_user_response(user_obj, cognito_username)

    profile_id = str(uuid.uuid4())
    superadmin_link_id = str(uuid.uuid4())
    now_db = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    try:
        async with db.transaction():
            await db.execute(
                """
                INSERT INTO user_profiles (
                    id, cognito_sub, email, full_name, department, phone_number, is_active, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, TRUE, $7, $7)
                """,
                profile_id,
                user_sub,
                superadmin_email,
                superadmin_name,
                superadmin_department,
                superadmin_phone,
                now_db,
            )

            await db.execute(
                """
                INSERT INTO user_roles (id, user_id, role_id, assigned_by)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id, role_id) DO NOTHING
                """,
                str(uuid.uuid4()),
                profile_id,
                str(super_admin_role["id"]),
                owner_user_id,
            )

            await db.execute(
                """
                INSERT INTO organization_users (id, organization_id, user_id, role_in_org, is_owner)
                VALUES ($1, $2, $3, 'super_admin', FALSE)
                """,
                superadmin_link_id,
                organization_id,
                profile_id,
            )
    except Exception as db_err:
        logger.exception("Failed to link new super admin, rolling back Cognito user")
        try:
            cognito_client.admin_delete_user(
                UserPoolId=COGNITO_USER_POOL_ID,
                Username=cognito_username,
            )
        except ClientError:
            logger.exception("Failed to rollback Cognito user after DB failure")
        raise HTTPException(status_code=500, detail="Failed to persist new super admin.") from db_err

    try:
        await asyncio.to_thread(
            send_welcome_email_sync,
            to_email=superadmin_email,
            recipient_name=superadmin_name,
            temp_password=superadmin_password,
            role_name="Super Admin",
        )
    except Exception:
        logger.exception("Failed to send welcome email to %s", superadmin_email)

    return SuperAdminResponse(
        user_id=profile_id,
        email=superadmin_email,
        full_name=superadmin_name,
        department=superadmin_department,
        phone_number=superadmin_phone,
        created_at=now_db,
        is_active=True,
    )


@router.delete("/{organization_id}/superadmins/{user_id}")
async def delete_organization_superadmin(
    organization_id: str,
    user_id: str,
    _current_user: dict = Depends(require_owner_only),
    db=Depends(get_db),
):
    """Remove a super admin from an organization. Also deletes them entirely from Cognito & platform."""
    await _fetch_organization_or_404(db, organization_id)

    # Make sure this user actually is a super admin for this org
    link = await db.fetchrow(
        """
        SELECT is_owner, user_id 
        FROM organization_users 
        WHERE organization_id = $1::uuid AND user_id = $2::uuid AND role_in_org = 'super_admin'
        LIMIT 1
        """,
        organization_id, user_id
    )
    if not link:
        raise HTTPException(status_code=404, detail="Super admin not found in this organization.")
        
    if link["is_owner"]:
        raise HTTPException(status_code=400, detail="Cannot delete the platform owner via this endpoint.")

    # Soft delete from database (hard delete crashes on FKs like uploaded documents)
    try:
        await db.execute("UPDATE user_profiles SET is_active = FALSE WHERE id = $1::uuid", user_id)
    except Exception as e:
        logger.exception("Failed to soft-delete super admin from database")
        raise HTTPException(status_code=500, detail="Failed to delete user records.") from e
        
    return {"message": "Super admin deleted successfully"}

@router.post("/{organization_id}/superadmins/{user_id}/reactivate")
async def reactivate_organization_superadmin(
    organization_id: str,
    user_id: str,
    _current_user: dict = Depends(require_owner_only),
    db=Depends(get_db),
):
    """Reactivate a super admin from an organization."""
    await _fetch_organization_or_404(db, organization_id)

    link = await db.fetchrow(
        """
        SELECT is_owner, user_id 
        FROM organization_users 
        WHERE organization_id = $1::uuid AND user_id = $2::uuid AND role_in_org = 'super_admin'
        LIMIT 1
        """,
        organization_id, user_id
    )
    if not link:
        raise HTTPException(status_code=404, detail="Super admin not found in this organization.")

    try:
        await db.execute("UPDATE user_profiles SET is_active = TRUE WHERE id = $1::uuid", user_id)
    except Exception as e:
        logger.exception("Failed to reactivate super admin in database")
        raise HTTPException(status_code=500, detail="Failed to reactivate user.") from e
        
    return {"message": "Super admin reactivated successfully"}
