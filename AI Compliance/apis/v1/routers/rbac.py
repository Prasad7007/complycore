import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from apis.core.database import get_db
from apis.core.security import get_current_user
from apis.models.rbac import (
    Permission,
    PermissionCreate,
    PermissionsResponse,
    Role,
    RoleCreate,
    RolePermissionAssign,
    UserRoleAssign,
)

router = APIRouter(tags=["rbac"])


def require_super_admin(current_user: dict = Depends(get_current_user)):
    roles = set((current_user or {}).get("roles") or [])
    if "super_admin" not in roles:
        raise HTTPException(
            status_code=403,
            detail="Only super admin can modify roles and permissions",
        )
    return current_user


async def _current_user_org_id(current_user: dict, db) -> str:
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


async def _assert_user_belongs_to_org(db, user_id: str, org_id: str) -> None:
    in_org = await db.fetchval(
        """
        SELECT 1
        FROM organization_users
        WHERE user_id = $1::uuid
          AND organization_id = $2::uuid
        """,
        user_id,
        org_id,
    )
    if not in_org:
        raise HTTPException(status_code=404, detail="User not found")


@router.post("/roles", response_model=Role)
async def create_role(role: RoleCreate, _=Depends(require_super_admin), db=Depends(get_db)):
    role_id = str(uuid.uuid4())
    row = await db.fetchrow(
        """
        INSERT INTO roles (id, name, display_name, description)
        VALUES ($1, $2, $3, $4)
        RETURNING id, name, display_name, description, created_at
        """,
        role_id,
        role.name,
        role.display_name,
        role.description,
    )
    return Role(**row)


@router.get("/roles", response_model=List[Role])
async def list_roles(db=Depends(get_db)):
    rows = await db.fetch("SELECT id, name, display_name, description, created_at FROM roles")
    return [Role(**dict(row)) for row in rows]


@router.get("/roles/{role_id}", response_model=Role)
async def get_role(role_id: str, db=Depends(get_db)):
    row = await db.fetchrow("SELECT id, name, display_name, description, created_at FROM roles WHERE id=$1", role_id)
    if not row:
        raise HTTPException(status_code=404, detail="Role not found")
    return Role(**row)


@router.delete("/roles/{role_id}")
async def delete_role(role_id: str, _=Depends(require_super_admin), db=Depends(get_db)):
    result = await db.execute("DELETE FROM roles WHERE id=$1", role_id)
    return {"ok": result.startswith("DELETE")}


@router.post("/permissions", response_model=Permission)
async def create_permission(permission: PermissionCreate, _=Depends(require_super_admin), db=Depends(get_db)):
    perm_id = str(uuid.uuid4())
    row = await db.fetchrow(
        """
        INSERT INTO permissions (id, key, display_name, description, category)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, key, display_name, description, category
        """,
        perm_id,
        permission.key,
        permission.display_name,
        permission.description,
        permission.category,
    )
    return Permission(**row)


@router.get("/permissions", response_model=List[Permission])
async def list_permissions(db=Depends(get_db)):
    rows = await db.fetch("SELECT id, key, display_name, description, category FROM permissions")
    return [Permission(**dict(row)) for row in rows]


@router.get("/permissions/{perm_id}", response_model=Permission)
async def get_permission(perm_id: str, db=Depends(get_db)):
    row = await db.fetchrow("SELECT id, key, display_name, description, category FROM permissions WHERE id=$1", perm_id)
    if not row:
        raise HTTPException(status_code=404, detail="Permission not found")
    return Permission(**row)


@router.delete("/permissions/{perm_id}")
async def delete_permission(perm_id: str, _=Depends(require_super_admin), db=Depends(get_db)):
    result = await db.execute("DELETE FROM permissions WHERE id=$1", perm_id)
    return {"ok": result.startswith("DELETE")}


@router.post("/role-permissions")
async def assign_permission_to_role(assign: RolePermissionAssign, _=Depends(require_super_admin), db=Depends(get_db)):
    await db.execute(
        """
        INSERT INTO role_permissions (id, role_id, permission_id, granted)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (role_id, permission_id) DO UPDATE SET granted = $4
        """,
        str(uuid.uuid4()),
        assign.role_id,
        assign.permission_id,
        assign.granted,
    )
    return {"ok": True}


@router.get("/role-permissions/{role_id}")
async def get_permissions_for_role(role_id: str, db=Depends(get_db)):
    rows = await db.fetch("SELECT permission_id FROM role_permissions WHERE role_id=$1 AND granted=TRUE", role_id)
    permissions = [row["permission_id"] for row in rows]
    return {"role_id": role_id, "permissions": permissions}


@router.delete("/role-permissions")
async def remove_permission_from_role(assign: RolePermissionAssign, _=Depends(require_super_admin), db=Depends(get_db)):
    await db.execute(
        "DELETE FROM role_permissions WHERE role_id=$1 AND permission_id=$2",
        assign.role_id,
        assign.permission_id,
    )
    return {"ok": True}


@router.post("/user-roles")
async def assign_role_to_user(assign: UserRoleAssign, current_user: dict = Depends(require_super_admin), db=Depends(get_db)):
    org_id = await _current_user_org_id(current_user, db)
    await _assert_user_belongs_to_org(db, str(assign.user_id), org_id)
    role_name = await db.fetchval("SELECT name FROM roles WHERE id=$1", assign.role_id)
    if role_name == "owner":
        raise HTTPException(status_code=403, detail="Owner role can only be assigned via owner bootstrap flow.")
    await db.execute(
        """
        INSERT INTO user_roles (id, user_id, role_id, assigned_by)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (user_id, role_id) DO NOTHING
        """,
        str(uuid.uuid4()),
        assign.user_id,
        assign.role_id,
        assign.assigned_by,
    )
    return {"ok": True}


@router.get("/user-roles/{user_id}")
async def get_roles_for_user(user_id: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    org_id = await _current_user_org_id(current_user, db)
    await _assert_user_belongs_to_org(db, user_id, org_id)
    rows = await db.fetch("SELECT role_id FROM user_roles WHERE user_id=$1", user_id)
    role_ids = [row["role_id"] for row in rows]
    return {"user_id": user_id, "roles": role_ids}


@router.delete("/user-roles")
async def remove_role_from_user(assign: UserRoleAssign, current_user: dict = Depends(require_super_admin), db=Depends(get_db)):
    role_name = await db.fetchval("SELECT name FROM roles WHERE id=$1", assign.role_id)
    if str(assign.user_id) == str((current_user or {}).get("id") or ""):
        if role_name in ["super_admin", "owner"]:
            raise HTTPException(status_code=400, detail="Cannot remove super_admin or owner roles from your own account.")

    org_id = await _current_user_org_id(current_user, db)
    await _assert_user_belongs_to_org(db, str(assign.user_id), org_id)
    await db.execute(
        "DELETE FROM user_roles WHERE user_id=$1 AND role_id=$2",
        assign.user_id,
        assign.role_id,
    )
    return {"ok": True}


@router.get("/rbac/check")
async def check_user_permission(user_id: str, permission_key: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    org_id = await _current_user_org_id(current_user, db)
    await _assert_user_belongs_to_org(db, user_id, org_id)
    query = """
        SELECT 1
        FROM user_roles ur
        JOIN role_permissions rp ON ur.role_id = rp.role_id
        JOIN permissions p ON rp.permission_id = p.id
        WHERE ur.user_id = $1
          AND p.key = $2
          AND rp.granted = TRUE
        LIMIT 1;
    """
    result = await db.fetchval(query, user_id, permission_key)

    if result:
        return {"allowed": True}
    return {"allowed": False, "reason": "Permission denied"}


@router.get("/users/{user_id}/permissions", response_model=PermissionsResponse)
async def get_user_all_permissions(user_id: str, current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    """Fetch all unique permission keys granted to the user via their roles."""
    org_id = await _current_user_org_id(current_user, db)
    await _assert_user_belongs_to_org(db, user_id, org_id)
    query = """
        SELECT DISTINCT p.key
        FROM user_roles ur
        JOIN role_permissions rp ON ur.role_id = rp.role_id
        JOIN permissions p ON rp.permission_id = p.id
        WHERE ur.user_id = $1
          AND rp.granted = TRUE
    """
    rows = await db.fetch(query, user_id)
    perms = [row["key"] for row in rows]
    return PermissionsResponse(user_id=user_id, permissions=perms)
