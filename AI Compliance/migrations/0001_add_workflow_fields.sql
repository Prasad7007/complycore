-- Migration: add locking and publishing fields to workflows
-- Adds flags/metadata required for compliance publish/lock operations
BEGIN;

ALTER TABLE workflows
    ADD COLUMN IF NOT EXISTS locked boolean DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS locked_by uuid NULL,
    ADD COLUMN IF NOT EXISTS locked_at timestamp NULL,
    ADD COLUMN IF NOT EXISTS published boolean DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS published_by uuid NULL,
    ADD COLUMN IF NOT EXISTS published_at timestamp NULL;

CREATE INDEX IF NOT EXISTS idx_workflows_locked ON workflows(locked);
CREATE INDEX IF NOT EXISTS idx_workflows_published ON workflows(published);

COMMIT;
