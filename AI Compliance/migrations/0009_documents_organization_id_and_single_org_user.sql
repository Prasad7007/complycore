-- Organization isolation (data model foundation)
-- 1) documents.organization_id + per-org unique document_code
-- 2) organization_users: at most one org per user (UNIQUE user_id)
--
-- Requires: migrations through 0008 (organizations, organization_users).
-- Backfill: assigns all existing documents to a dedicated legacy org (slug: legacy-default).

BEGIN;

-- ---------------------------------------------------------------------------
-- 1) Legacy org for existing rows (idempotent)
-- ---------------------------------------------------------------------------
INSERT INTO organizations (id, name, slug, status, created_at, updated_at)
VALUES (
    'a0000001-0001-4001-8001-0000000def01'::uuid,
    'Default (pre-organization isolation)',
    'legacy-default',
    'active',
    NOW(),
    NOW()
)
ON CONFLICT (slug) DO NOTHING;

-- Target org for backfill: prefer migration org, else oldest org by created_at
DO $$
DECLARE
    legacy_org uuid;
BEGIN
    SELECT id INTO legacy_org FROM organizations WHERE slug = 'legacy-default' LIMIT 1;
    IF legacy_org IS NULL THEN
        SELECT id INTO legacy_org FROM organizations ORDER BY created_at ASC NULLS LAST LIMIT 1;
    END IF;
    IF legacy_org IS NULL THEN
        RAISE EXCEPTION '0009 migration: no organization row found; run 0008 or insert an organization first.';
    END IF;

    -- ---------------------------------------------------------------------------
    -- 2) documents.organization_id
    -- ---------------------------------------------------------------------------
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'documents' AND column_name = 'organization_id'
    ) THEN
        ALTER TABLE documents
            ADD COLUMN organization_id uuid REFERENCES organizations(id) ON DELETE RESTRICT;
    END IF;

    UPDATE documents SET organization_id = legacy_org WHERE organization_id IS NULL;

    ALTER TABLE documents ALTER COLUMN organization_id SET NOT NULL;

    -- Replace global unique(document_code) with per-tenant uniqueness
    ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_document_code_key;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'documents_organization_id_document_code_key'
    ) THEN
        ALTER TABLE documents
            ADD CONSTRAINT documents_organization_id_document_code_key
            UNIQUE (organization_id, document_code);
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 3) Single org per user: drop composite unique, add UNIQUE(user_id)
-- ---------------------------------------------------------------------------
-- Resolve duplicates by keeping the row with the smallest id per user_id.
DELETE FROM organization_users ou_del
WHERE EXISTS (
    SELECT 1
    FROM organization_users ou_keep
    WHERE ou_keep.user_id = ou_del.user_id
      AND ou_keep.id < ou_del.id
);

ALTER TABLE organization_users
    DROP CONSTRAINT IF EXISTS organization_users_organization_id_user_id_key;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'organization_users_user_id_key'
    ) THEN
        ALTER TABLE organization_users
            ADD CONSTRAINT organization_users_user_id_key UNIQUE (user_id);
    END IF;
END $$;

COMMIT;
