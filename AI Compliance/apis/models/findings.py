from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID

# Existing AI Finding model (may belong to another file, but defined here for completeness)
class AIFindingBase(BaseModel):
    rule_id: UUID
    title: str
    risk_level: str
    description: str
    why_risky: str
    rationale: str
    ai_suggestion: str
    location: Optional[str] = None
    status: str = "pending"
    reviewer_comment: Optional[str] = None
    accepted_suggestion_id: Optional[UUID] = None

class AIFinding(AIFindingBase):
    id: UUID
    finding_code: str
    review_id: UUID
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[UUID] = None
    accepted_suggestion_id: Optional[UUID] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class FindingCommentCreate(BaseModel):
    content: str
    # Author ID and Role are extracted from the current user

class FindingComment(BaseModel):
    id: UUID
    finding_id: UUID
    author_id: UUID
    role: str
    content: str
    created_at: datetime
    author_name: Optional[str] = None  # User's full name from users table
    
    model_config = ConfigDict(from_attributes=True)

class FindingSuggestionCreate(BaseModel):
    text: str
    type: str = "user"

class FindingSuggestionUpdate(BaseModel):
    text: str

class FindingSuggestion(BaseModel):
    id: UUID
    finding_id: UUID
    text: str
    type: str
    created_by: Optional[UUID] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

# -----------------
# AI Feedback Models
# -----------------
class AIFeedbackCreate(BaseModel):
    is_liked: bool = Field(..., description="True if the user liked the AI review, False otherwise")
    feedback_text: Optional[str] = Field(None, description="Optional text context, usually required if is_liked is False")

class AIFeedback(AIFeedbackCreate):
    id: UUID
    review_id: UUID
    user_id: UUID
    submitted_at: datetime
    created_at: datetime
    
    class Config:
        from_attributes = True