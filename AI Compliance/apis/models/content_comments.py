from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime
from uuid import UUID

class ContentCommentCreate(BaseModel):
    content: str
    mentioned_user_ids: Optional[List[str]] = None

class ContentComment(BaseModel):
    id: UUID
    review_id: UUID
    author_id: UUID
    content: str
    workflow_stage: Optional[str] = None
    created_at: datetime
    author_name: Optional[str] = None
    author_role: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

class ComplianceReportCreate(BaseModel):
    # This is often auto-generated on "Approve & Lock", but exposing for completeness
    review_id: UUID

class ComplianceReport(BaseModel):
    id: UUID
    report_code: str
    review_id: UUID
    review_type: str
    compliance_status: str
    total_flags: int
    high_risk_flags: int
    medium_risk_flags: int
    low_risk_flags: int
    approval_authority: UUID
    approval_role: str
    approval_timestamp: datetime
    ai_summary: Optional[str] = None
    created_at: datetime
    
    # Human readable fields populated via JOIN
    document_name: Optional[str] = None
    approval_authority_name: Optional[str] = None
    # From document_versions via content_reviews (marketing docs); null for social-only reviews
    version_label: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
