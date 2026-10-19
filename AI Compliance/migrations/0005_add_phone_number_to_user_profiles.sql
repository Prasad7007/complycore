-- Migration: Add phone_number to user_profiles
BEGIN;

ALTER TABLE user_profiles ADD COLUMN phone_number VARCHAR;

COMMIT;
