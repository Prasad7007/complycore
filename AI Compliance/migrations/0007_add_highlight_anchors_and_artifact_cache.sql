-- Migration: add per-finding highlight anchors + annotated artifact cache
-- Supports fast S3 cached rendering and structured page/line metadata.
BEGIN;

CREATE TABLE IF NOT EXISTS ai_finding_anchors (
    id UUID PRIMARY KEY,
    finding_id UUID NOT NULL UNIQUE REFERENCES ai_findings(id) ON DELETE CASCADE,
    document_version_id UUID NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    page_no_start INT NULL,
    page_no_end INT NULL,
    line_no INT NULL,
    bbox_json JSONB NULL,
    match_method VARCHAR NOT NULL DEFAULT 'location_text',
    match_confidence NUMERIC(5, 4) NULL,
    normalized_claim_hash VARCHAR NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_finding_anchors_document_version
    ON ai_finding_anchors(document_version_id);

CREATE INDEX IF NOT EXISTS idx_ai_finding_anchors_page_start
    ON ai_finding_anchors(document_version_id, page_no_start);

CREATE TABLE IF NOT EXISTS ai_annotated_artifacts (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    document_version_id UUID NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    review_id UUID NULL REFERENCES content_reviews(id) ON DELETE SET NULL,
    findings_hash VARCHAR NOT NULL,
    s3_bucket VARCHAR NOT NULL,
    s3_key VARCHAR NOT NULL,
    engine_version VARCHAR NOT NULL DEFAULT 'hl_v2',
    generated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    last_accessed_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    UNIQUE(document_version_id, findings_hash, engine_version)
);

CREATE INDEX IF NOT EXISTS idx_ai_annotated_artifacts_document_version
    ON ai_annotated_artifacts(document_version_id);

COMMIT;
