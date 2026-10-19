-- Migration: fix super admin spelling typo in department catalog
-- Normalizes 'Supre Admin' and 'super_admin' to 'Super Admin'
BEGIN;

-- 1. Insert 'Super Admin' into catalog
INSERT INTO department_catalog (name) VALUES ('Super Admin') ON CONFLICT (name) DO NOTHING;

-- 2. Update existing users to 'Super Admin'
UPDATE user_profiles SET department = 'Super Admin' WHERE department IN ('Supre Admin', 'super_admin');

-- 3. Delete 'Supre Admin' from catalog
DELETE FROM department_catalog WHERE name = 'Supre Admin';

COMMIT;
