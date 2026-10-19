-- Canonical department options (unioned with distinct user_profiles.department in app queries).

BEGIN;

CREATE TABLE IF NOT EXISTS department_catalog (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(200) NOT NULL UNIQUE,
  created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

INSERT INTO department_catalog (name) VALUES
  ('Marketing'),
  ('Compliance'),
  ('Supre Admin'),
  ('SME Department')
ON CONFLICT (name) DO NOTHING;

COMMIT;
