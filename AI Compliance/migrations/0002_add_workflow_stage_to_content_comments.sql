-- Migration: add workflow_stage column to content_comments table
-- This allows tracking which workflow stage a comment was made in
BEGIN;

ALTER TABLE content_comments
    ADD COLUMN IF NOT EXISTS workflow_stage VARCHAR NULL;

-- Backfill existing comments by attempting to match with workflow history
-- For comments without a clear match, leave as NULL
UPDATE content_comments cc
SET workflow_stage = (
    SELECT w.current_stage
    FROM workflows w
    WHERE w.review_id = cc.review_id
    LIMIT 1
)
WHERE workflow_stage IS NULL;

COMMIT;
