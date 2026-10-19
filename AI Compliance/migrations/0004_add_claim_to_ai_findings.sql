-- Migration: add claim_id and claim_text to ai_findings for claim-wise grouping in UI
-- Enables frontend to group findings by claim and show one card per claim with one suggestion
BEGIN;

ALTER TABLE ai_findings
    ADD COLUMN IF NOT EXISTS claim_id VARCHAR NULL,
    ADD COLUMN IF NOT EXISTS claim_text TEXT NULL;

COMMIT;
