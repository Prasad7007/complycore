from pydantic import BaseModel
from typing import Optional
import datetime
from enum import Enum

class DocumentType(str, Enum):
    educational_content = "educational_content"
    opinion = "opinion"
    product_feature = "product_feature"
    performance_related = "performance_related"
    disclosure = "disclosure"
    client_communications = "client_communications"
    other = "other"

class DocumentStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    in_review = "in_review"
    approved = "approved"
    rejected = "rejected"
    published = "published"
    skipped = "skipped"
    failed = "failed"

class Document(BaseModel):
    id: str
    document_code: str
    name: str
    type: DocumentType
    current_version_id: Optional[str] = None
    version_label: Optional[str] = "1.1"
    submitted_by: str
    status: DocumentStatus = DocumentStatus.pending
    review_id: Optional[str] = None
    workflow_stage: Optional[str] = None
    assigned_to: Optional[str] = None
    assigned_to_name: Optional[str] = None
    assigned_role: Optional[str] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

class DocumentVersion(BaseModel):
    id: str
    document_id: str
    version_label: str
    file_url: Optional[str] = None
    file_hash: Optional[str] = None
    uploaded_by: str
    uploaded_at: datetime.datetime
    status: DocumentStatus = DocumentStatus.processing
