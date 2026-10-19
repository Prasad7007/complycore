from pydantic import BaseModel, EmailStr
from typing import List, Optional
import datetime
from uuid import UUID

class UserProfile(BaseModel):
    id: UUID | str
    cognito_sub: str
    email: EmailStr
    full_name: str
    avatar_url: Optional[str] = None
    department: Optional[str] = None
    phone_number: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    department: Optional[str] = None
    avatar_url: Optional[str] = None
    phone_number: Optional[str] = None

class AppUser(BaseModel):
    id: str
    name: str
    email: EmailStr
    department: Optional[str] = None
    phone_number: Optional[str] = None
    roles: List[str] = []
    status: str
    assigned_date: Optional[str] = None


class OrganizationSummary(BaseModel):
    id: str
    slug: str
    name: str
