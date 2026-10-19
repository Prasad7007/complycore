-- Migration: add triggered_by_user_id column to audit_events table
-- This allows tracking which user triggered AI events (e.g., SME who clicked approve button)
BEGIN;

ALTER TABLE audit_events
    ADD COLUMN IF NOT EXISTS triggered_by_user_id UUID NULL REFERENCES user_profiles(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_audit_events_triggered_by_user_id ON audit_events(triggered_by_user_id);

-- Optional backfill: For AI events, find the most recent user action before them
-- This is a best-effort backfill and may not catch all cases
UPDATE audit_events ae
SET triggered_by_user_id = (
    SELECT ae2.user_id
    FROM audit_events ae2
    WHERE ae2.review_id = ae.review_id
      AND ae2.is_ai = false
      AND ae2.user_id IS NOT NULL
      AND ae2.created_at < ae.created_at
    ORDER BY ae2.created_at DESC
    LIMIT 1
)
WHERE ae.is_ai = true
  AND ae.triggered_by_user_id IS NULL
  AND EXISTS (
    SELECT 1
    FROM audit_events ae2
    WHERE ae2.review_id = ae.review_id
      AND ae2.is_ai = false
      AND ae2.user_id IS NOT NULL
      AND ae2.created_at < ae.created_at
  );

COMMIT;
