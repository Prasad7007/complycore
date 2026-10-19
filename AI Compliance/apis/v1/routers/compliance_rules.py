from typing import List
from uuid import UUID, uuid4
from fastapi import APIRouter, HTTPException, Depends

from apis.core.database import get_db
from apis.models.compliance_rules import (
    ComplianceRuleCreate,
    ComplianceRuleUpdate,
    ComplianceRuleOut
)

router = APIRouter(prefix="/rules", tags=["compliance_rules"])

@router.post("", response_model=ComplianceRuleOut, status_code=201)
async def create_rule(rule: ComplianceRuleCreate, db=Depends(get_db)):
    # Assuming role checking is handled via security dependencies in a real scenario
    # e.g., db=Depends(get_db), current_user=Depends(require_role("admin"))
    
    rule_id = uuid4()
    
    try:
        query = """
            INSERT INTO compliance_rules (id, rule_code, name, description, category)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
        """
        row = await db.fetchrow(
            query, 
            rule_id, 
            rule.rule_code, 
            rule.name, 
            rule.description, 
            rule.category
        )
        return ComplianceRuleOut(**dict(row))
    except Exception as e:
        # Simplistic error handling for asyncpg unique constraint violations
        if "unique constraint" in str(e).lower():
            raise HTTPException(status_code=400, detail="Rule with this code already exists")
        raise HTTPException(status_code=500, detail="Failed to create compliance rule")

@router.get("", response_model=List[ComplianceRuleOut])
async def list_rules(skip: int = 0, limit: int = 100, db=Depends(get_db)):
    query = """
        SELECT * FROM compliance_rules
        ORDER BY rule_code ASC
        OFFSET $1 LIMIT $2
    """
    rows = await db.fetch(query, skip, limit)
    return [ComplianceRuleOut(**dict(r)) for r in rows]

@router.get("/{rule_id}", response_model=ComplianceRuleOut)
async def get_rule(rule_id: UUID, db=Depends(get_db)):
    query = "SELECT * FROM compliance_rules WHERE id = $1"
    row = await db.fetchrow(query, rule_id)
    if not row:
        raise HTTPException(status_code=404, detail="Compliance rule not found")
    return ComplianceRuleOut(**dict(row))

@router.put("/{rule_id}", response_model=ComplianceRuleOut)
async def update_rule(rule_id: UUID, update_data: ComplianceRuleUpdate, db=Depends(get_db)):
    # 1. Verify existence
    existing = await db.fetchrow("SELECT 1 FROM compliance_rules WHERE id = $1", rule_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Compliance rule not found")

    # 2. Build dynamic update query
    updates = update_data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided for update")

    fields = []
    values = []
    idx = 1
    for key, value in updates.items():
        fields.append(f"{key} = ${idx}")
        values.append(value)
        idx += 1

    values.append(rule_id)
    set_clause = ", ".join(fields)
    
    query = f"""
        UPDATE compliance_rules
        SET {set_clause}
        WHERE id = ${idx}
        RETURNING *
    """
    
    try:
        row = await db.fetchrow(query, *values)
        return ComplianceRuleOut(**dict(row))
    except Exception as e:
        if "unique constraint" in str(e).lower():
            raise HTTPException(status_code=400, detail="Rule with this code already exists")
        raise HTTPException(status_code=500, detail="Failed to update compliance rule")

@router.delete("/{rule_id}")
async def delete_rule(rule_id: UUID, db=Depends(get_db)):
    query = "DELETE FROM compliance_rules WHERE id = $1 RETURNING id"
    deleted_id = await db.fetchval(query, rule_id)
    if not deleted_id:
        raise HTTPException(status_code=404, detail="Compliance rule not found")
    
    return {"ok": True, "message": "Rule deleted successfully"}
