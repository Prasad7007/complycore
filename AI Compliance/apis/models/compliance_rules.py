from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID

class ComplianceRuleBase(BaseModel):
    rule_code: str = Field(..., description="Unique code for the rule (e.g., FIN-001)")
    name: str = Field(..., description="Human-readable name for the rule")
    description: str = Field(..., description="Detailed description of what the rule enforces")
    category: str = Field(..., description="Category of the rule (e.g., Financial, Privacy, Marketing)")

class ComplianceRuleCreate(ComplianceRuleBase):
    pass

class ComplianceRuleUpdate(BaseModel):
    rule_code: Optional[str] = Field(None, description="Unique code for the rule")
    name: Optional[str] = Field(None, description="Human-readable name for the rule")
    description: Optional[str] = Field(None, description="Detailed description of what the rule enforces")
    category: Optional[str] = Field(None, description="Category of the rule")

class ComplianceRuleOut(ComplianceRuleBase):
    id: UUID
    
    class Config:
        from_attributes = True
