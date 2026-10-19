-- V1 quota model:
-- one quota settings row per organization, initialized at org creation time.

BEGIN;

CREATE TABLE IF NOT EXISTS organization_upload_quota_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL UNIQUE REFERENCES organizations(id) ON DELETE CASCADE,
    quota_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    upload_limit_count INT NOT NULL DEFAULT 50 CHECK (upload_limit_count > 0),
    upload_limit_bytes BIGINT NOT NULL DEFAULT 2147483648 CHECK (upload_limit_bytes > 0),
    rollout_starts_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_by UUID REFERENCES user_profiles(id) ON DELETE SET NULL
);

INSERT INTO organization_upload_quota_settings (
    id,
    organization_id,
    quota_enabled,
    upload_limit_count,
    upload_limit_bytes,
    rollout_starts_at,
    created_at,
    updated_at,
    updated_by
)
SELECT
    gen_random_uuid(),
    org.id,
    COALESCE(o.quota_enabled, p.quota_enabled, TRUE),
    COALESCE(o.upload_limit_count, p.upload_limit_count, 50),
    COALESCE(o.upload_limit_bytes, p.upload_limit_bytes, 2147483648),
    CASE
        WHEN p.rollout_starts_at IS NOT NULL AND p.rollout_starts_at > COALESCE(org.created_at, NOW())
            THEN p.rollout_starts_at
        ELSE COALESCE(org.created_at, NOW())
    END,
    NOW(),
    NOW(),
    COALESCE(o.updated_by, p.updated_by)
FROM organizations org
LEFT JOIN organization_upload_quota_overrides o
    ON o.organization_id = org.id
LEFT JOIN platform_upload_quota_settings p
    ON p.singleton_key = 'default'
ON CONFLICT (organization_id) DO NOTHING;

COMMIT;
