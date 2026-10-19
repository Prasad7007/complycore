-- Pending org invites (token-based accept). Only org super_admin creates rows (enforced in API).

BEGIN;

CREATE TABLE IF NOT EXISTS organization_invites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email VARCHAR NOT NULL,
    token UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    role_in_org VARCHAR NOT NULL DEFAULT 'marketing',
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITHOUT TIME ZONE,
    accepted_at TIMESTAMP WITHOUT TIME ZONE
);

CREATE INDEX IF NOT EXISTS organization_invites_org_id_idx
    ON organization_invites (organization_id);

COMMIT;
