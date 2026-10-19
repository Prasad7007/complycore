-- Replace department catalog with the fixed four options (environments that already ran 0011).

BEGIN;

DELETE FROM department_catalog;

INSERT INTO department_catalog (name) VALUES
  ('Marketing'),
  ('Compliance'),
  ('Supre Admin'),
  ('SME Department');

COMMIT;
