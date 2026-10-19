-- Remove profile_handler (Social Media Handler) role only.
-- user_roles and role_permissions for this role are removed via ON DELETE CASCADE.
-- Does not modify any other role, permission, or organization_users rows.

BEGIN;

DELETE FROM roles WHERE name = 'profile_handler';

COMMIT;
