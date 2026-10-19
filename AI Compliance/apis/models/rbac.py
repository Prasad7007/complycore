from pydantic import BaseModel
from typing import List, Optional
import datetime
from uuid import UUID

class RoleCreate(BaseModel):
    name: str
    display_name: str
    description: Optional[str] = None

class Role(RoleCreate):
    id: UUID | str
    created_at: Optional[datetime.datetime] = None

class PermissionCreate(BaseModel):
    key: str
    display_name: str
    description: Optional[str] = None
    category: Optional[str] = None

class Permission(PermissionCreate):
    id: UUID | str

class RolePermissionAssign(BaseModel):
    role_id: UUID | str
    permission_id: UUID | str
    granted: bool = True

class UserRoleAssign(BaseModel):
    user_id: UUID | str
    role_id: UUID | str
    assigned_by: Optional[UUID | str] = None

class PermissionsResponse(BaseModel):
    user_id: str
    permissions: List[str]
