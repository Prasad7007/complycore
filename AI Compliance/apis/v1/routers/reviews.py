import uuid
from typing import List
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends

from apis.core.database import get_db
from apis.core.security import require_tenant_context
from apis.core.tenant_resources import assert_review_in_organization
from apis.models.reviews import ContentReviewCreate, ContentReviewOut, WorkflowOut

router = APIRouter(prefix="/reviews", tags=["reviews"])

@router.post("", response_model=ContentReviewOut, status_code=201)
async def create_review(
    payload: ContentReviewCreate,
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    """
    Creates a new Content Review for either a document version or social post.
    Automatically initializes the Workflow engine attached to it.
    """
    if not payload.document_version_id and not payload.social_post_id:
        raise HTTPException(status_code=400, detail="Must provide either document_version_id or social_post_id")

    org_id = tenant_ctx["organization_id"]
    if payload.document_version_id:
        ok = await db.fetchval(
            """
            SELECT 1 FROM document_versions dv
            JOIN documents d ON d.id = dv.document_id
            WHERE dv.id = $1::uuid AND d.organization_id = $2::uuid
            LIMIT 1
            """,
            payload.document_version_id,
            org_id,
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Document version not found")
    if payload.social_post_id:
        ok = await db.fetchval(
            """
            SELECT 1 FROM social_posts
            WHERE id = $1::uuid AND organization_id = $2::uuid
            LIMIT 1
            """,
            payload.social_post_id,
            org_id,
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Social post not found")

    review_id = str(uuid.uuid4())
    workflow_id = str(uuid.uuid4())
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    
    # 1. Start Transaction
    async with db.transaction():
        # Insert Review
        await db.execute(
            """
            INSERT INTO content_reviews (id, content_type, document_version_id, social_post_id, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $5)
            """,
            review_id,
            payload.content_type,
            payload.document_version_id,
            payload.social_post_id,
            now_utc
        )
        
        # Insert initial workflow container
        await db.execute(
            """
            INSERT INTO workflows (id, review_id, current_stage, created_at, updated_at)
            VALUES ($1, $2, 'sme_review', $3, $3)
            """,
            workflow_id,
            review_id,
            now_utc
        )
        
    # 2. Fetch resulting review to return
    row = await db.fetchrow("SELECT * FROM content_reviews WHERE id=$1", review_id)
    return ContentReviewOut(**dict(row))

@router.get("", response_model=List[ContentReviewOut])
async def list_reviews(
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    org_id = tenant_ctx["organization_id"]
    rows = await db.fetch(
        """
        SELECT cr.*
        FROM content_reviews cr
        LEFT JOIN document_versions dv ON cr.document_version_id = dv.id
        LEFT JOIN documents d ON dv.document_id = d.id
        LEFT JOIN social_posts sp ON cr.social_post_id = sp.id
        WHERE d.organization_id = $1::uuid OR sp.organization_id = $1::uuid
        ORDER BY cr.created_at DESC
        """,
        org_id,
    )
    return [ContentReviewOut(**dict(r)) for r in rows]

@router.get("/{review_id}", response_model=ContentReviewOut)
async def get_review(
    review_id: str,
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    await assert_review_in_organization(db, review_id, tenant_ctx["organization_id"])
    r_row = await db.fetchrow("SELECT * FROM content_reviews WHERE id=$1", review_id)
    if not r_row:
        raise HTTPException(status_code=404, detail="Review not found")
        
    result = dict(r_row)
    
    # Merge Workflow context if needed by frontend
    w_row = await db.fetchrow("SELECT * FROM workflows WHERE review_id=$1", review_id)
    if w_row:
        result["workflow"] = dict(w_row)
        
    return ContentReviewOut(**result)

@router.post("/{review_id}/lock", response_model=ContentReviewOut)
async def lock_review(
    review_id: str,
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    await assert_review_in_organization(db, review_id, tenant_ctx["organization_id"])
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    exists = await db.fetchval("SELECT 1 FROM content_reviews WHERE id=$1", review_id)
    if not exists:
        raise HTTPException(status_code=404, detail="Review not found")
        
    row = await db.fetchrow(
        """
        UPDATE content_reviews 
        SET is_locked = True, locked_at = $1, updated_at = $1
        WHERE id = $2
        RETURNING *
        """, 
        now_utc, review_id
    )
    return ContentReviewOut(**dict(row))

@router.post("/{review_id}/unlock", response_model=ContentReviewOut)
async def unlock_review(
    review_id: str,
    tenant_ctx: dict = Depends(require_tenant_context),
    db=Depends(get_db),
):
    await assert_review_in_organization(db, review_id, tenant_ctx["organization_id"])
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    row = await db.fetchrow(
        """
        UPDATE content_reviews 
        SET is_locked = False, locked_at = NULL, locked_by = NULL, updated_at = $1
        WHERE id = $2
        RETURNING *
        """, 
        now_utc, review_id
    )
    if not row:
         raise HTTPException(status_code=404, detail="Review not found")
         
    return ContentReviewOut(**dict(row))
