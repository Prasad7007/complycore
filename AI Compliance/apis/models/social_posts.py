from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime
from uuid import UUID

class SocialPostBase(BaseModel):
    platform: str
    content_type: str
    preview: Optional[str] = None
    full_content: str
    url: Optional[str] = None

class SocialPostCreate(SocialPostBase):
    pass

class SocialPost(SocialPostBase):
    id: UUID
    post_code: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)