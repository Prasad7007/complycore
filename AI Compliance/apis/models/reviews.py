from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID

# -----------------
# Workflows Models
# -----------------
class WorkflowStepOut(BaseModel):
    id: UUID
    workflow_id: UUID
    stage: str
    action: Optional[str] = None
    claimed_by: Optional[UUID] = None
    claimed_at: Optional[datetime] = None
    completed_by: Optional[UUID] = None
    completed_at: Optional[datetime] = None
    comment: Optional[str] = None
    previous_stage: Optional[str] = None
    step_order: int
    created_at: datetime
    # Human-readable names resolved via JOIN
    completed_by_name: Optional[str] = None
    claimed_by_name: Optional[str] = None
    user_name: Optional[str] = None

    class Config:
        from_attributes = True

class WorkflowOut(BaseModel):
    id: UUID
    review_id: UUID
    current_stage: str
    assigned_to: Optional[UUID] = None
    assigned_role: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    # We can nest the latest step or history if we want a rich response
    steps: Optional[List[WorkflowStepOut]] = None

    class Config:
        from_attributes = True

class WorkflowTransitionCreate(BaseModel):
    """Payload to push a review to the next workflow stage"""
    action: str = Field(..., description="E.g., approve, reject, submit_to_compliance")
    comment: Optional[str] = Field(None, description="Optional text context for the transition")
    assign_to: Optional[UUID] = Field(None, description="Optional assignee user_id for assign/route actions")

# -----------------
# Reviews Models
# -----------------
class ContentReviewCreate(BaseModel):
    content_type: str = Field(..., description="'document' or 'social_post'")
    document_version_id: Optional[UUID] = None
    social_post_id: Optional[UUID] = None

class ContentReviewOut(BaseModel):
    id: UUID
    content_type: str
    document_version_id: Optional[UUID] = None
    social_post_id: Optional[UUID] = None
    compliance_status: str
    review_status: str
    is_locked: bool
    locked_at: Optional[datetime] = None
    locked_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    
    # Attach nested objects via API layer if joined in SELECT
    workflow: Optional[WorkflowOut] = None

    class Config:
        from_attributes = True
