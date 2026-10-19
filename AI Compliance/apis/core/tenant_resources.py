"""Helpers to verify reviews and related rows belong to the resolved tenant organization."""

from fastapi import HTTPException


async def review_belongs_to_organization(db, review_id: str, organization_id: str) -> bool:
    row = await db.fetchrow(
        """
        SELECT 1
        FROM content_reviews cr
        LEFT JOIN document_versions dv ON cr.document_version_id = dv.id
        LEFT JOIN documents d ON dv.document_id = d.id
        LEFT JOIN social_posts sp ON cr.social_post_id = sp.id
        WHERE cr.id = $1::uuid
          AND (
            d.organization_id = $2::uuid
            OR sp.organization_id = $2::uuid
          )
        LIMIT 1
        """,
        review_id,
        organization_id,
    )
    return row is not None


async def assert_review_in_organization(db, review_id: str, organization_id: str) -> None:
    if not await review_belongs_to_organization(db, review_id, organization_id):
        raise HTTPException(status_code=404, detail="Review not found")
