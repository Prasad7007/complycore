-- Upload quota foundations:
-- 1) document_versions.file_size_bytes for per-upload byte accounting
-- 2) global platform upload quota defaults
-- 3) per-organization upload quota overrides

BEGIN;

ALTER TABLE document_versions
    ADD COLUMN IF NOT EXISTS file_size_bytes BIGINT;

CREATE TABLE IF NOT EXISTS platform_upload_quota_settings (
    singleton_key VARCHAR PRIMARY KEY DEFAULT 'default',
    quota_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    upload_limit_count INT NOT NULL DEFAULT 50 CHECK (upload_limit_count > 0),
    upload_limit_bytes BIGINT NOT NULL DEFAULT 2147483648 CHECK (upload_limit_bytes > 0),
    rollout_starts_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_by UUID REFERENCES user_profiles(id) ON DELETE SET NULL,
    CONSTRAINT platform_upload_quota_settings_singleton_key_check CHECK (singleton_key = 'default')
);

INSERT INTO platform_upload_quota_settings (
    singleton_key,
    quota_enabled,
    upload_limit_count,
    upload_limit_bytes,
    rollout_starts_at,
    created_at,
    updated_at
)
VALUES (
    'default',
    TRUE,
    50,
    2147483648,
    NULL,
    NOW(),
    NOW()
)
ON CONFLICT (singleton_key) DO NOTHING;

CREATE TABLE IF NOT EXISTS organization_upload_quota_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL UNIQUE REFERENCES organizations(id) ON DELETE CASCADE,
    quota_enabled BOOLEAN,
    upload_limit_count INT CHECK (upload_limit_count > 0),
    upload_limit_bytes BIGINT CHECK (upload_limit_bytes > 0),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_by UUID REFERENCES user_profiles(id) ON DELETE SET NULL,
    CONSTRAINT organization_upload_quota_overrides_nonempty_check CHECK (
        quota_enabled IS NOT NULL
        OR upload_limit_count IS NOT NULL
        OR upload_limit_bytes IS NOT NULL
    )
);

COMMIT;
