import os
import uuid
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from apis.main import app
from apis.v1.routers.rbac import require_super_admin
from apis.core.security import get_current_user

def test_require_super_admin_dependency():
    """
    Directly unit tests the require_super_admin dependency function.
    """
    # 1. Super Admin user -> should pass and return the user dict
    super_admin_user = {"id": str(uuid.uuid4()), "roles": ["super_admin"]}
    res = require_super_admin(current_user=super_admin_user)
    assert res == super_admin_user

    # 2. Member user -> should raise 403 HTTPException
    member_user = {"id": str(uuid.uuid4()), "roles": ["marketing"]}
    with pytest.raises(HTTPException) as exc_info:
        require_super_admin(current_user=member_user)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Only super admin can modify roles and permissions"

    # 3. User with no roles -> should raise 403 HTTPException
    no_role_user = {"id": str(uuid.uuid4()), "roles": []}
    with pytest.raises(HTTPException) as exc_info:
        require_super_admin(current_user=no_role_user)
    assert exc_info.value.status_code == 403

    # 4. Empty/None user -> should raise 403 HTTPException
    with pytest.raises(HTTPException) as exc_info:
        require_super_admin(current_user=None)
    assert exc_info.value.status_code == 403

def test_rbac_super_admin_endpoints_lifecycle():
    """
    Overrides authentication dependencies to represent a Super Admin session,
    and executes a full CRUD management lifecycle for roles and permissions.
    """
    mock_super_admin = {
        "id": "782f2f7d-8f2f-4f68-b0a5-c1d5a2ea7d19",
        "roles": ["super_admin"]
    }

    # Set override
    app.dependency_overrides[get_current_user] = lambda: mock_super_admin

    try:
        with TestClient(app) as client:
            role_name = f"test_role_{uuid.uuid4().hex[:8]}"
            perm_key = f"test_perm_{uuid.uuid4().hex[:8]}"

            # 1. Create Role
            role_payload = {
                "name": role_name,
                "display_name": "Test Role",
                "description": "Seeded via unit test"
            }
            response = client.post("/api/v1/roles", json=role_payload)
            assert response.status_code == 200, f"Failed to create role: {response.text}"
            role_data = response.json()
            role_id = role_data.get("id")
            assert role_id is not None
            assert role_data.get("name") == role_name

            # 2. Get Role
            response = client.get(f"/api/v1/roles/{role_id}")
            assert response.status_code == 200
            assert response.json().get("name") == role_name

            # 3. List Roles
            response = client.get("/api/v1/roles")
            assert response.status_code == 200
            roles_list = [r.get("id") for r in response.json()]
            assert role_id in roles_list

            # 4. Create Permission
            perm_payload = {
                "key": perm_key,
                "display_name": "Test Permission",
                "description": "Seeded via unit test",
                "category": "Test"
            }
            response = client.post("/api/v1/permissions", json=perm_payload)
            assert response.status_code == 200, f"Failed to create permission: {response.text}"
            perm_data = response.json()
            perm_id = perm_data.get("id")
            assert perm_id is not None
            assert perm_data.get("key") == perm_key

            # 5. Get Permission
            response = client.get(f"/api/v1/permissions/{perm_id}")
            assert response.status_code == 200
            assert response.json().get("key") == perm_key

            # 6. List Permissions
            response = client.get("/api/v1/permissions")
            assert response.status_code == 200
            perms_list = [p.get("id") for p in response.json()]
            assert perm_id in perms_list

            # 7. Assign Permission to Role
            assign_payload = {
                "role_id": role_id,
                "permission_id": perm_id,
                "granted": True
            }
            response = client.post("/api/v1/role-permissions", json=assign_payload)
            assert response.status_code == 200

            # 8. Get Role Permissions
            response = client.get(f"/api/v1/role-permissions/{role_id}")
            assert response.status_code == 200
            role_perms = response.json().get("permissions")
            assert perm_id in role_perms

            # 9. Clean up: Delete Permission
            response = client.delete(f"/api/v1/permissions/{perm_id}")
            assert response.status_code == 200

            # 10. Clean up: Delete Role
            response = client.delete(f"/api/v1/roles/{role_id}")
            assert response.status_code == 200

    finally:
        # Keep app overrides clean for other tests
        app.dependency_overrides.pop(get_current_user, None)

def test_rbac_endpoints_member_blocked():
    """
    Overrides authentication to represent a standard Member session,
    and asserts that all role and permission modification requests are blocked with 403 Forbidden.
    """
    mock_member = {
        "id": "892f2f7d-8f2f-4f68-b0a5-c1d5a2ea7d19",
        "roles": ["marketing"]
    }

    # Set override
    app.dependency_overrides[get_current_user] = lambda: mock_member

    try:
        with TestClient(app) as client:
            # 1. Blocked from creating roles
            response = client.post("/api/v1/roles", json={
                "name": "hacker_role",
                "display_name": "Hacker Role",
                "description": "Should fail"
            })
            assert response.status_code == 403
            assert "Only super admin" in response.json().get("detail")

            # 2. Blocked from creating permissions
            response = client.post("/api/v1/permissions", json={
                "key": "canHackSystem",
                "display_name": "Hack System",
                "description": "Should fail",
                "category": "Admin"
            })
            assert response.status_code == 403
            assert "Only super admin" in response.json().get("detail")

            # 3. Blocked from assigning permissions
            response = client.post("/api/v1/role-permissions", json={
                "role_id": str(uuid.uuid4()),
                "permission_id": str(uuid.uuid4()),
                "granted": True
            })
            assert response.status_code == 403

            # 4. Blocked from deleting roles
            response = client.delete(f"/api/v1/roles/{uuid.uuid4()}")
            assert response.status_code == 403

            # 5. Blocked from deleting permissions
            response = client.delete(f"/api/v1/permissions/{uuid.uuid4()}")
            assert response.status_code == 403

    finally:
        app.dependency_overrides.pop(get_current_user, None)