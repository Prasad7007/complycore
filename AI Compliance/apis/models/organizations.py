import datetime

from pydantic import BaseModel, Field
from typing import Optional


class OrganizationBootstrapRequest(BaseModel):
    organization_name: str = Field(..., min_length=2, max_length=120)
    organization_slug: str = Field(..., min_length=2, max_length=80)
    superadmin_email: str
    superadmin_full_name: str = Field(..., min_length=2, max_length=120)
    superadmin_password: str = Field(..., min_length=8)
    superadmin_department: str = Field(..., min_length=1, max_length=200)
    superadmin_phone: Optional[str] = Field(None, max_length=20)


class OrganizationBootstrapResponse(BaseModel):
    organization_id: str
    organization_slug: str
    superadmin_user_id: str
    superadmin_email: str
    message: str


class OrganizationListItem(BaseModel):
    id: str
    name: str
    slug: str
    status: str
    created_at: datetime.datetime


class OrganizationUploadQuotaDefaults(BaseModel):
    quota_enabled: bool
    upload_limit_count: int = Field(..., gt=0)
    upload_limit_bytes: int = Field(..., gt=0)
    rollout_starts_at: datetime.datetime


class EffectiveUploadQuotaSettingsSummary(BaseModel):
    quota_enabled: bool
    upload_limit_count: int = Field(..., gt=0)
    upload_limit_bytes: int = Field(..., gt=0)
    rollout_starts_at: datetime.datetime
    rolling_window_days: int = Field(..., gt=0)


class OrganizationUploadQuotaSettingsResponse(BaseModel):
    organization_id: str
    organization_slug: str
    organization_name: str
    org_created_at: datetime.datetime
    quota_settings_id: Optional[str] = None
    quota_enabled: bool
    upload_limit_count: int = Field(..., gt=0)
    upload_limit_bytes: int = Field(..., gt=0)
    rollout_starts_at: datetime.datetime
    rolling_window_days: int = Field(..., gt=0)
    defaults: OrganizationUploadQuotaDefaults
    effective_quota: EffectiveUploadQuotaSettingsSummary
    updated_at: Optional[datetime.datetime] = None
    updated_by: Optional[str] = None
    bypass_active: bool
    bypass_reason: Optional[str] = None


class OrganizationUploadQuotaSettingsUpdate(BaseModel):
    quota_enabled: bool
    upload_limit_count: int = Field(..., gt=0)
    upload_limit_bytes: int = Field(..., gt=0)
    rollout_starts_at: datetime.datetime


class SuperAdminCreateRequest(BaseModel):
    email: str
    full_name: str = Field(..., min_length=2, max_length=120)
    password: str = Field(..., min_length=8)
    phone_number: Optional[str] = Field(None, max_length=20)


class SuperAdminResponse(BaseModel):
    user_id: str
    email: str
    full_name: str
    department: str
    phone_number: Optional[str]
    created_at: datetime.datetime
    is_active: bool = True
