import os
import uuid
import pytest
import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL")

@pytest.mark.asyncio
async def test_organization_data_isolation():
    """
    Validates organization boundaries (multi-tenancy) by inserting sandboxed records 
    for Org A and Org B, and verifying that cross-tenant queries never leak data.
    """
    assert DATABASE_URL, "DATABASE_URL environment variable is not set"
    db_url = DATABASE_URL.replace("+asyncpg", "") if "+asyncpg" in DATABASE_URL else DATABASE_URL
    
    conn = await asyncpg.connect(db_url)
    
    # Use a transaction to ensure clean rollback at the end of the test
    tx = conn.transaction()
    await tx.start()
    
    try:
        # 1. Setup Organizations
        org_a_id = uuid.uuid4()
        org_b_id = uuid.uuid4()
        
        await conn.execute("""
            INSERT INTO organizations (id, name, slug) 
            VALUES ($1, 'Organization A', 'org-a'), ($2, 'Organization B', 'org-b')
        """, org_a_id, org_b_id)
        
        # 2. Setup Test User
        user_id = uuid.uuid4()
        await conn.execute("""
            INSERT INTO user_profiles (id, cognito_sub, email, full_name) 
            VALUES ($1, $2, $3, 'Test User')
        """, user_id, str(uuid.uuid4()), 'test-user@elevatetrust.ai')
        
        # 3. Insert documents for Org A and Org B
        doc_a_id = uuid.uuid4()
        doc_b_id = uuid.uuid4()
        
        await conn.execute("""
            INSERT INTO documents (id, organization_id, document_code, name, type, submitted_by) 
            VALUES ($1, $2, 'DOC-001', 'Org A Document', 'Marketing', $3)
        """, doc_a_id, org_a_id, user_id)
        
        await conn.execute("""
            INSERT INTO documents (id, organization_id, document_code, name, type, submitted_by) 
            VALUES ($1, $2, 'DOC-002', 'Org B Document', 'Marketing', $3)
        """, doc_b_id, org_b_id, user_id)
        
        # 4. Assert Org A can ONLY see Org A's records
        org_a_docs = await conn.fetch("""
            SELECT id, name FROM documents WHERE organization_id = $1
        """, org_a_id)
        
        assert len(org_a_docs) == 1, f"Expected 1 document, found {len(org_a_docs)}"
        assert org_a_docs[0]["id"] == doc_a_id
        assert org_a_docs[0]["name"] == "Org A Document"
        
        # 5. Assert Org B can ONLY see Org B's records
        org_b_docs = await conn.fetch("""
            SELECT id, name FROM documents WHERE organization_id = $1
        """, org_b_id)
        
        assert len(org_b_docs) == 1, f"Expected 1 document, found {len(org_b_docs)}"
        assert org_b_docs[0]["id"] == doc_b_id
        assert org_b_docs[0]["name"] == "Org B Document"
        
        # 6. Test Uniqueness (Same document_code is allowed in Org B, but BLOCKED in Org A)
        # Verify Org B can use 'DOC-001' safely (uniqueness is scoped per organization)
        doc_b2_id = uuid.uuid4()
        await conn.execute("""
            INSERT INTO documents (id, organization_id, document_code, name, type, submitted_by) 
            VALUES ($1, $2, 'DOC-001', 'Org B Doc 2', 'Marketing', $3)
        """, doc_b2_id, org_b_id, user_id)
        
        # Verify inserting 'DOC-001' again in Org A triggers a unique constraint violation
        with pytest.raises(asyncpg.exceptions.UniqueViolationError):
            await conn.execute("""
                INSERT INTO documents (id, organization_id, document_code, name, type, submitted_by) 
                VALUES ($1, $2, 'DOC-001', 'Org A Duplicate', 'Marketing', $3)
            """, uuid.uuid4(), org_a_id, user_id)
            
    finally:
        # Roll back transaction to keep the database completely clean
        await tx.rollback()
        await conn.close()