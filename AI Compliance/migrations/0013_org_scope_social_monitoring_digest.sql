-- Scope social posts, LinkedIn monitoring, and email digest settings per organization.

BEGIN;

-- social_posts: per-tenant rows; post_code unique within org
ALTER TABLE social_posts ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE;

UPDATE social_posts
SET organization_id = sub.id
FROM (SELECT id FROM organizations ORDER BY created_at NULLS LAST LIMIT 1) AS sub
WHERE social_posts.organization_id IS NULL;

ALTER TABLE social_posts ALTER COLUMN organization_id SET NOT NULL;

ALTER TABLE social_posts DROP CONSTRAINT IF EXISTS social_posts_post_code_key;
ALTER TABLE social_posts ADD CONSTRAINT social_posts_org_post_code_key UNIQUE (organization_id, post_code);
CREATE INDEX IF NOT EXISTS social_posts_organization_id_idx ON social_posts(organization_id);

-- monitored_profiles
ALTER TABLE monitored_profiles ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE;

UPDATE monitored_profiles
SET organization_id = sub.id
FROM (SELECT id FROM organizations ORDER BY created_at NULLS LAST LIMIT 1) AS sub
WHERE monitored_profiles.organization_id IS NULL;

ALTER TABLE monitored_profiles ALTER COLUMN organization_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS monitored_profiles_organization_id_idx ON monitored_profiles(organization_id);

-- email_digest_settings: one row per org
ALTER TABLE email_digest_settings ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE;

UPDATE email_digest_settings
SET organization_id = sub.id
FROM (SELECT id FROM organizations ORDER BY created_at NULLS LAST LIMIT 1) AS sub
WHERE email_digest_settings.organization_id IS NULL;

INSERT INTO email_digest_settings (id, digest_time, is_enabled, updated_at, organization_id)
SELECT gen_random_uuid(), '08:00'::time, TRUE, NOW(), o.id
FROM organizations o
WHERE NOT EXISTS (
  SELECT 1 FROM email_digest_settings e WHERE e.organization_id = o.id
);

ALTER TABLE email_digest_settings ALTER COLUMN organization_id SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS email_digest_settings_organization_id_uidx ON email_digest_settings(organization_id);

COMMIT;
