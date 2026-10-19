-- Migration: persist which marketing suggestion compliance accepted (NULL = AI alternative chosen)
ALTER TABLE ai_findings
  ADD COLUMN IF NOT EXISTS accepted_suggestion_id UUID REFERENCES finding_suggestions(id) ON DELETE SET NULL;
