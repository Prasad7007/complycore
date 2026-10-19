import logging
import datetime
import uuid
import asyncpg
import asyncio
from typing import List
from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form

from apis.core.database import get_db
from apis.core.security import get_current_user, is_demo_seed_email
from apis.models.users import UserProfile, UserUpdate, AppUser, OrganizationSummary
from apis.services.department_list import fetch_all_department_names
from apis.core.mail import send_support_email_sync

router = APIRouter(prefix="/users", tags=["users"])
logger = logging.getLogger(__name__)


async def _require_current_user_org_id(current_user: dict, db) -> str:
    user_id = str((current_user or {}).get("id") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    org_id = await db.fetchval(
        """
        SELECT organization_id::text
        FROM organization_users
        WHERE user_id = $1::uuid
        LIMIT 1
        """,
        user_id,
    )
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization membership")
    return str(org_id)


async def _assert_user_in_org(db, user_id: str, organization_id: str) -> None:
    in_org = await db.fetchval(
        """
        SELECT 1
        FROM organization_users
        WHERE user_id = $1::uuid
          AND organization_id = $2::uuid
        """,
        user_id,
        organization_id,
    )
    if not in_org:
        raise HTTPException(status_code=404, detail="User not found")

@router.get("/departments", response_model=List[str])
async def list_departments(db=Depends(get_db)):
    """
    Return all department names from the database (catalog + distinct values on user profiles).
    """
    return await fetch_all_department_names(db)

@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    """
    Return the currently authenticated user's profile + roles.
    Roles come only from user_roles in the database (admin-assigned).
    """
    user_id = (current_user or {}).get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    row = await db.fetchrow(
        "SELECT id, cognito_sub, email, full_name, avatar_url, department, phone_number, is_active, created_at, updated_at FROM user_profiles WHERE id=$1",
        user_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")

    data = dict(row)
    data["id"] = str(data.get("id")) if data.get("id") else None

    db_role_rows = await db.fetch(
        """
        SELECT r.name FROM user_roles ur
        JOIN roles r ON ur.role_id = r.id
        WHERE ur.user_id = $1
        """,
        user_id,
    )
    db_roles = [r["name"] for r in db_role_rows]

    # App RBAC is DB-only. Self-service signups have no user_roles until an admin assigns them.
    data["roles"] = db_roles
    role_cnt = await db.fetchval(
        "SELECT COUNT(*)::int FROM user_roles WHERE user_id = $1",
        user_id,
    )
    dept_raw = row["department"]
    dept_ok = bool(dept_raw is not None and str(dept_raw).strip() != "")
    data["access_ready"] = (role_cnt or 0) >= 1 and dept_ok

    org_row = await db.fetchrow(
        """
        SELECT o.id, o.slug, o.name, ou.role_in_org
        FROM organization_users ou
        JOIN organizations o ON o.id = ou.organization_id
        WHERE ou.user_id = $1::uuid
        LIMIT 1
        """,
        user_id,
    )
    is_platform_owner = "owner" in db_roles
    is_demo_seed = is_demo_seed_email(row.get("email"))
    if is_demo_seed and not org_row and not is_platform_owner:
        default_org = await db.fetchrow(
            """
            SELECT id, slug, name
            FROM organizations
            ORDER BY created_at ASC NULLS LAST, name ASC
            LIMIT 1
            """
        )
        if default_org:
            demo_role_in_org = "marketing"
            if "super_admin" in db_roles:
                demo_role_in_org = "super_admin"
            elif "compliance" in db_roles:
                demo_role_in_org = "compliance"
            elif "sme" in db_roles:
                demo_role_in_org = "sme"
            await db.execute(
                """
                INSERT INTO organization_users (id, organization_id, user_id, role_in_org, is_owner)
                VALUES ($1, $2::uuid, $3::uuid, $4, FALSE)
                ON CONFLICT (user_id) DO NOTHING
                """,
                str(uuid.uuid4()),
                str(default_org["id"]),
                user_id,
                demo_role_in_org,
            )
            org_row = await db.fetchrow(
                """
                SELECT o.id, o.slug, o.name, ou.role_in_org
                FROM organization_users ou
                JOIN organizations o ON o.id = ou.organization_id
                WHERE ou.user_id = $1::uuid
                LIMIT 1
                """,
                user_id,
            )
    if org_row:
        data["organization"] = OrganizationSummary(
            id=str(org_row["id"]),
            slug=org_row["slug"],
            name=org_row["name"],
        ).model_dump()
        data["role_in_org"] = org_row["role_in_org"]
        data["pending_org_invite"] = False
    else:
        data["organization"] = None
        data["role_in_org"] = None
        # Awaiting org assignment (invite). Platform owner without a tenant row is not "pending invite".
        data["pending_org_invite"] = not is_platform_owner

    # Local/seed demo accounts (DEMO_LOGIN_EMAILS) are not org-gated so dev login works without organization_users.
    if is_demo_seed:
        data["pending_org_invite"] = False
        data["access_ready"] = True

    # access_state helps the frontend route without inferring from multiple flags.
    if is_demo_seed:
        if org_row:
            data["access_state"] = "tenant_ready"
        elif is_platform_owner:
            data["access_state"] = "platform_owner"
        else:
            data["access_state"] = "global_ready"
    elif is_platform_owner and not org_row:
        data["access_state"] = "platform_owner"
    elif not org_row and data["pending_org_invite"]:
        data["access_state"] = "pending_org_invite"
    elif org_row and not data["access_ready"]:
        data["access_state"] = "profile_incomplete"
    elif org_row and data["access_ready"]:
        data["access_state"] = "tenant_ready"
    elif not org_row and data["access_ready"]:
        data["access_state"] = "global_ready"
    else:
        data["access_state"] = "profile_incomplete"

    return data


@router.post("/{user_id}/deactivate")
async def deactivate_user(
    user_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    if user_id == str((current_user or {}).get("id") or ""):
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account.")

    organization_id = await _require_current_user_org_id(current_user, db)
    await _assert_user_in_org(db, user_id, organization_id)
    await db.execute("UPDATE user_profiles SET is_active=FALSE, updated_at=$1 WHERE id=$2", datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None), user_id)
    return {"ok": True}

@router.post("/{user_id}/reactivate")
async def reactivate_user(
    user_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    organization_id = await _require_current_user_org_id(current_user, db)
    await _assert_user_in_org(db, user_id, organization_id)
    await db.execute("UPDATE user_profiles SET is_active=TRUE, updated_at=$1 WHERE id=$2", datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None), user_id)
    return {"ok": True}

@router.get("/{user_id}/pending-tasks")
async def get_user_pending_tasks(
    user_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    organization_id = await _require_current_user_org_id(current_user, db)
    await _assert_user_in_org(db, user_id, organization_id)
    
    # Check for assigned workflows that are not in terminal states
    pending_workflows = await db.fetch(
        """
        SELECT w.id, w.current_stage, d.name as document_name
        FROM workflows w
        JOIN content_reviews cr ON w.review_id = cr.id
        JOIN document_versions dv ON cr.document_version_id = dv.id
        JOIN documents d ON dv.document_id = d.id
        WHERE w.assigned_to = $1 AND w.current_stage NOT IN ('published', 'rejected', 'approved')
        """,
        user_id
    )
    
    tasks = []
    for wf in pending_workflows:
        tasks.append({
            "id": str(wf["id"]),
            "type": "workflow",
            "document_name": wf["document_name"],
            "stage": wf["current_stage"]
        })
        
    return {"tasks": tasks}

@router.get("/{user_id}/profile", response_model=UserProfile)
async def get_user_profile(
    user_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    organization_id = await _require_current_user_org_id(current_user, db)
    await _assert_user_in_org(db, user_id, organization_id)
    row = await db.fetchrow("SELECT * FROM user_profiles WHERE id=$1", user_id)
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")
    return UserProfile(**dict(row))

@router.put("/{user_id}/profile", response_model=UserProfile)
async def update_user_profile(
    user_id: str,
    update: UserUpdate,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    organization_id = await _require_current_user_org_id(current_user, db)
    await _assert_user_in_org(db, user_id, organization_id)
    # Verify user exists
    user_exists = await db.fetchval("SELECT 1 FROM user_profiles WHERE id=$1", user_id)
    if not user_exists:
        raise HTTPException(status_code=404, detail="User not found")

    # Build update query dynamically
    fields = []
    values = []
    idx = 1
    
    if update.full_name is not None:
        fields.append(f"full_name=${idx}")
        values.append(update.full_name)
        idx += 1
    
    if update.department is not None:
        fields.append(f"department=${idx}")
        values.append(update.department)
        idx += 1
        
    if update.avatar_url is not None:
        fields.append(f"avatar_url=${idx}")
        values.append(update.avatar_url)
        idx += 1

    if update.phone_number is not None:
        fields.append(f"phone_number=${idx}")
        values.append(update.phone_number)
        idx += 1
        
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
        
    fields.append(f"updated_at=${idx}")
    values.append(datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))
    idx += 1
    
    values.append(user_id) # Last arg is ID
    
    query = f"""
        UPDATE user_profiles 
        SET {", ".join(fields)}
        WHERE id=${idx}
        RETURNING *
    """
    
    row = await db.fetchrow(query, *values)
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")
        
    return UserProfile(**dict(row))

@router.get("", response_model=List[AppUser])
async def list_users(
    role: str = None,
    query: str = None,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    organization_id = await _require_current_user_org_id(current_user, db)
    # Fetch profiles directly, optionally filtered by role name and search query
    sql_parts = [
        "ou.organization_id = $1::uuid",
        """
        NOT EXISTS (
            SELECT 1
            FROM user_roles ur_owner
            JOIN roles r_owner ON r_owner.id = ur_owner.role_id
            WHERE ur_owner.user_id = up.id
              AND r_owner.name = 'owner'
        )
        """.strip(),
    ]
    sql_args = []
    sql_args.append(organization_id)
    
    if role:
        sql_parts.append(f"r.name = ${len(sql_args) + 1}")
        sql_args.append(role)
        sql_parts.append("up.is_active = TRUE")
    
    if query:
        search_pattern = f"%{query}%"
        sql_parts.append(f"(up.full_name ILIKE ${len(sql_args) + 1} OR up.email ILIKE ${len(sql_args) + 1})")
        sql_args.append(search_pattern)

    where_clause = " AND ".join(sql_parts)
    
    if role:
        sql = f"""
            SELECT
                up.id,
                up.email,
                up.full_name as name,
                up.department,
                up.phone_number,
                up.is_active,
                up.created_at
            FROM user_profiles up
            JOIN organization_users ou ON ou.user_id = up.id
            JOIN user_roles ur ON ur.user_id = up.id
            JOIN roles r ON ur.role_id = r.id
            WHERE {where_clause}
            ORDER BY up.created_at DESC
        """
    else:
        sql = f"""
            SELECT
                up.id,
                up.email,
                up.full_name as name,
                up.department,
                up.phone_number,
                up.is_active,
                up.created_at
            FROM user_profiles up
            JOIN organization_users ou ON ou.user_id = up.id
            WHERE {where_clause}
            ORDER BY up.created_at DESC
        """
    user_rows = await db.fetch(sql, *sql_args)
    
    # Fetch roles for all users
    role_rows = await db.fetch(
        """
        SELECT ur.user_id, r.name as role_name
        FROM organization_users ou
        JOIN user_roles ur ON ur.user_id = ou.user_id
        JOIN roles r ON ur.role_id = r.id
        WHERE ou.organization_id = $1::uuid
        """,
        organization_id,
    )
    
    # Build roles map: user_id -> list of role names
    roles_map = {}
    for rr in role_rows:
        uid = str(rr["user_id"])
        if uid not in roles_map:
            roles_map[uid] = []
        roles_map[uid].append(rr["role_name"])
    
    results = []
    for row in user_rows:
        uid = str(row["id"])
        status = "active" if row["is_active"] else "inactive"
        # assigned_date proxy: created_at formatted YYYY-MM-DD
        assigned = row["created_at"].strftime("%Y-%m-%d") if row["created_at"] else None
        
        results.append(AppUser(
            id=uid,
            name=row["name"] or "Unknown",
            email=row["email"],
            department=row["department"] or "Unassigned",
            phone_number=row["phone_number"],
            roles=roles_map.get(uid, []),
            status=status,
            assigned_date=assigned
        ))
        
    return results

@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    if user_id == str((current_user or {}).get("id") or ""):
        raise HTTPException(status_code=400, detail="Cannot delete your own account.")

    organization_id = await _require_current_user_org_id(current_user, db)
    await _assert_user_in_org(db, user_id, organization_id)
    
    # Check if target is a super admin
    target_roles_rows = await db.fetch(
        """
        SELECT r.name FROM user_roles ur
        JOIN roles r ON ur.role_id = r.id
        WHERE ur.user_id = $1
        """,
        user_id,
    )
    target_roles = [r["name"] for r in target_roles_rows]

    if "super_admin" in target_roles:
        # Check if current user is an owner
        current_user_id = str((current_user or {}).get("id") or "")
        current_roles_rows = await db.fetch(
            """
            SELECT r.name FROM user_roles ur
            JOIN roles r ON ur.role_id = r.id
            WHERE ur.user_id = $1
            """,
            current_user_id,
        )
        current_roles = [r["name"] for r in current_roles_rows]
        
        if "owner" not in current_roles:
            raise HTTPException(status_code=403, detail="Super Admins can only be deleted by Platform Owners.")

    # Soft delete user profile to prevent foreign key errors with documents/audit trails
    try:
        await db.execute("UPDATE user_profiles SET is_active = False WHERE id=$1", user_id)
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete user profile or it is referenced elsewhere.")

    return {"ok": True}


@router.post("/report-issue")
async def report_issue(
    description: str = Form(...),
    file: UploadFile = File(None),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Report an issue/submit support request.
    Auto-captures user name, email, organization/tenant, and current timestamp.
    Sends email to info@complycore.ca.
    """
    user_id = (current_user or {}).get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Fetch user profile
    user_row = await db.fetchrow(
        "SELECT full_name, email FROM user_profiles WHERE id=$1",
        user_id,
    )
    if not user_row:
        raise HTTPException(status_code=404, detail="User profile not found")

    user_name = user_row["full_name"] or user_row["email"] or "Unknown User"
    user_email = user_row["email"] or "unknown@complycore.ca"

    # Fetch organization info
    org_row = await db.fetchrow(
        """
        SELECT o.name 
        FROM organization_users ou
        JOIN organizations o ON o.id = ou.organization_id
        WHERE ou.user_id = $1::uuid
        LIMIT 1
        """,
        user_id,
    )
    tenant_name = org_row["name"] if org_row else "No Organization/Tenant"
    
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    file_bytes = None
    file_name = None
    if file:
        file_bytes = await file.read()
        file_name = file.filename

    try:
        await asyncio.to_thread(
            send_support_email_sync,
            user_name=user_name,
            user_email=user_email,
            tenant_name=tenant_name,
            timestamp=timestamp,
            description=description,
            file_bytes=file_bytes,
            file_name=file_name,
        )
    except Exception as e:
        logger.exception("Failed to send support email")
        raise HTTPException(status_code=500, detail="Failed to send support email request. Please try again.")

    return {"message": "Issue reported successfully."}
