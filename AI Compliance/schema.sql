-- Drop everything to restart clean
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;

-- 1. USER MANAGEMENT
CREATE TABLE user_profiles (
  id UUID PRIMARY KEY,
  cognito_sub VARCHAR UNIQUE NOT NULL,
  email VARCHAR UNIQUE NOT NULL,
  full_name VARCHAR NOT NULL,
  avatar_url VARCHAR,
  department VARCHAR,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE roles (
  id UUID PRIMARY KEY,
  name VARCHAR UNIQUE NOT NULL,
  display_name VARCHAR NOT NULL,
  description TEXT,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE permissions (
  id UUID PRIMARY KEY,
  key VARCHAR UNIQUE NOT NULL,
  display_name VARCHAR NOT NULL,
  description TEXT,
  category VARCHAR,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE role_permissions (
  id UUID PRIMARY KEY,
  role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
  granted BOOLEAN DEFAULT TRUE,
  UNIQUE(role_id, permission_id)
);

CREATE TABLE user_roles (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  assigned_by UUID REFERENCES user_profiles(id) ON DELETE SET NULL,
  assigned_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
  UNIQUE(user_id, role_id)
);

-- 1b. ORGANIZATIONS (multitenancy; see migrations 0008, 0009)
CREATE TABLE organizations (
  id UUID PRIMARY KEY,
  name VARCHAR NOT NULL,
  slug VARCHAR UNIQUE NOT NULL,
  status VARCHAR NOT NULL DEFAULT 'active',
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE organization_users (
  id UUID PRIMARY KEY,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  role_in_org VARCHAR NOT NULL,
  is_owner BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
  CONSTRAINT organization_users_user_id_key UNIQUE (user_id)
);

CREATE TABLE organization_invites (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  email VARCHAR NOT NULL,
  token UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  role_in_org VARCHAR NOT NULL DEFAULT 'marketing',
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
  expires_at TIMESTAMP WITHOUT TIME ZONE,
  accepted_at TIMESTAMP WITHOUT TIME ZONE
);

CREATE INDEX organization_invites_org_id_idx ON organization_invites (organization_id);

CREATE TABLE platform_upload_quota_settings (
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

CREATE TABLE organization_upload_quota_overrides (
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

CREATE TABLE organization_upload_quota_settings (
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

-- Department dropdown whitelist (Marketing, Compliance, Super Admin, SME Department; see migrations 0011–0012, 0017)
CREATE TABLE department_catalog (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(200) NOT NULL UNIQUE,
  created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

-- 2. COMPLIANCE RULES
CREATE TABLE compliance_rules (
  id UUID PRIMARY KEY,
  rule_code VARCHAR UNIQUE NOT NULL,
  name VARCHAR NOT NULL,
  description TEXT NOT NULL,
  category VARCHAR NOT NULL
);

-- 3. DOCUMENTS
CREATE TABLE documents (
  id UUID PRIMARY KEY,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
  document_code VARCHAR NOT NULL,
  name VARCHAR NOT NULL,
  type VARCHAR NOT NULL,
  current_version_id UUID, -- Circular reference, created later via alter table
  submitted_by UUID NOT NULL REFERENCES user_profiles(id),
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
  CONSTRAINT documents_organization_id_document_code_key UNIQUE (organization_id, document_code)
);

CREATE TABLE document_versions (
  id UUID PRIMARY KEY,
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  version_label VARCHAR NOT NULL,
  uploaded_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
  change_summary TEXT,
  status VARCHAR NOT NULL DEFAULT 'processing',
  s3_bucket VARCHAR NOT NULL,
  s3_key VARCHAR NOT NULL,
  file_hash VARCHAR,
  extracted_text TEXT,
  file_size_bytes BIGINT,
  UNIQUE(document_id, version_label)
);

-- Add foreign key now that version table exists
ALTER TABLE documents
  ADD CONSTRAINT fk_documents_current_version
  FOREIGN KEY (current_version_id) REFERENCES document_versions(id) ON DELETE SET NULL;

-- 4. SOCIAL POSTS
CREATE TABLE social_posts (
  id UUID PRIMARY KEY,
  post_code VARCHAR UNIQUE NOT NULL,
  platform VARCHAR NOT NULL,
  content_type VARCHAR NOT NULL,
  preview TEXT,
  full_content TEXT NOT NULL,
  url VARCHAR,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

-- 5. CONTENT REVIEWS
CREATE TABLE content_reviews (
  id UUID PRIMARY KEY,
  content_type VARCHAR NOT NULL,
  document_version_id UUID REFERENCES document_versions(id) ON DELETE CASCADE,
  social_post_id UUID REFERENCES social_posts(id) ON DELETE CASCADE,
  compliance_status VARCHAR NOT NULL DEFAULT 'conditional',
  review_status VARCHAR NOT NULL DEFAULT 'pending',
  is_locked BOOLEAN DEFAULT FALSE,
  locked_at TIMESTAMP WITHOUT TIME ZONE,
  locked_by UUID REFERENCES user_profiles(id) ON DELETE SET NULL,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

-- 6. AI FINDINGS & RELATED
CREATE TABLE ai_findings (
  id UUID PRIMARY KEY,
  finding_code VARCHAR UNIQUE NOT NULL,
  review_id UUID NOT NULL REFERENCES content_reviews(id) ON DELETE CASCADE,
  rule_id UUID NOT NULL REFERENCES compliance_rules(id),
  title VARCHAR NOT NULL,
  risk_level VARCHAR NOT NULL,
  description TEXT NOT NULL,
  why_risky TEXT NOT NULL,
  rationale TEXT NOT NULL,
  ai_suggestion TEXT NOT NULL,
  location VARCHAR,
  status VARCHAR NOT NULL DEFAULT 'pending',
  resolved_at TIMESTAMP WITHOUT TIME ZONE,
  resolved_by UUID REFERENCES user_profiles(id) ON DELETE SET NULL,
  -- accepted_suggestion_id and dismissal_reason added via ALTER TABLE below
  -- (after finding_suggestions is created, to avoid forward-reference error)
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE finding_suggestions (
  id UUID PRIMARY KEY,
  finding_id UUID NOT NULL REFERENCES ai_findings(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  type VARCHAR NOT NULL,
  created_by UUID REFERENCES user_profiles(id) ON DELETE SET NULL,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

-- Add columns that reference finding_suggestions now that the table exists
-- (mirrors the deferred-FK pattern used for documents/document_versions above)
ALTER TABLE ai_findings
  ADD COLUMN IF NOT EXISTS accepted_suggestion_id UUID REFERENCES finding_suggestions(id) ON DELETE SET NULL;

ALTER TABLE ai_findings
  ADD COLUMN IF NOT EXISTS dismissal_reason TEXT;

ALTER TABLE ai_findings
  ADD COLUMN IF NOT EXISTS reject_reason TEXT;

CREATE TABLE finding_comments (
  id UUID PRIMARY KEY,
  finding_id UUID NOT NULL REFERENCES ai_findings(id) ON DELETE CASCADE,
  author_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  role VARCHAR NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

-- 7. RULES TRIGGERED
CREATE TABLE document_version_rules_triggered (
  id UUID PRIMARY KEY,
  document_version_id UUID NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
  rule_id UUID NOT NULL REFERENCES compliance_rules(id) ON DELETE CASCADE,
  UNIQUE(document_version_id, rule_id)
);

CREATE TABLE social_post_rules_triggered (
  id UUID PRIMARY KEY,
  social_post_id UUID NOT NULL REFERENCES social_posts(id) ON DELETE CASCADE,
  rule_id UUID NOT NULL REFERENCES compliance_rules(id) ON DELETE CASCADE,
  UNIQUE(social_post_id, rule_id)
);

-- 8. WORKFLOW ENGINE
CREATE TABLE workflows (
  id UUID PRIMARY KEY,
  review_id UUID UNIQUE NOT NULL REFERENCES content_reviews(id) ON DELETE CASCADE,
  current_stage VARCHAR NOT NULL DEFAULT 'sme_review',
  assigned_to UUID REFERENCES user_profiles(id) ON DELETE SET NULL,
  assigned_role VARCHAR,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE workflow_steps (
  id UUID PRIMARY KEY,
  workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
  stage VARCHAR NOT NULL,
  action VARCHAR,
  claimed_by UUID REFERENCES user_profiles(id) ON DELETE SET NULL,
  claimed_at TIMESTAMP WITHOUT TIME ZONE,
  completed_by UUID REFERENCES user_profiles(id) ON DELETE SET NULL,
  completed_at TIMESTAMP WITHOUT TIME ZONE,
  comment TEXT,
  previous_stage VARCHAR,
  step_order INT NOT NULL,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

-- 9. GENERAL COMMENTS
CREATE TABLE content_comments (
  id UUID PRIMARY KEY,
  review_id UUID NOT NULL REFERENCES content_reviews(id) ON DELETE CASCADE,
  author_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE comment_mentions (
  id UUID PRIMARY KEY,
  comment_id UUID NOT NULL REFERENCES content_comments(id) ON DELETE CASCADE,
  mentioned_user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  UNIQUE(comment_id, mentioned_user_id)
);

-- 10. AUDIT TRAIL
CREATE TABLE audit_events (
  id UUID PRIMARY KEY,
  event_code VARCHAR UNIQUE NOT NULL,
  review_id UUID NOT NULL REFERENCES content_reviews(id) ON DELETE CASCADE,
  workflow_stage VARCHAR,
  event_type VARCHAR NOT NULL,
  description TEXT NOT NULL,
  user_id UUID REFERENCES user_profiles(id) ON DELETE SET NULL,
  user_role VARCHAR,
  is_ai BOOLEAN DEFAULT FALSE,
  details TEXT,
  status_from VARCHAR,
  status_to VARCHAR,
  workflow_stage_from VARCHAR,
  workflow_stage_to VARCHAR,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE audit_sub_events (
  id UUID PRIMARY KEY,
  audit_event_id UUID NOT NULL REFERENCES audit_events(id) ON DELETE CASCADE,
  type VARCHAR NOT NULL,
  title VARCHAR NOT NULL,
  description TEXT NOT NULL,
  risk_level VARCHAR,
  rule_id UUID REFERENCES compliance_rules(id) ON DELETE SET NULL,
  finding_id UUID REFERENCES ai_findings(id) ON DELETE SET NULL,
  status VARCHAR,
  suggestion_type VARCHAR,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE audit_event_rules (
  id UUID PRIMARY KEY,
  audit_event_id UUID NOT NULL REFERENCES audit_events(id) ON DELETE CASCADE,
  rule_id UUID NOT NULL REFERENCES compliance_rules(id) ON DELETE CASCADE,
  UNIQUE(audit_event_id, rule_id)
);

-- 11. COMPLIANCE REPORTS
CREATE TABLE compliance_reports (
  id UUID PRIMARY KEY,
  report_code VARCHAR UNIQUE NOT NULL,
  review_id UUID NOT NULL REFERENCES content_reviews(id) ON DELETE CASCADE,
  review_type VARCHAR NOT NULL,
  compliance_status VARCHAR NOT NULL,
  total_flags INT DEFAULT 0,
  high_risk_flags INT DEFAULT 0,
  medium_risk_flags INT DEFAULT 0,
  low_risk_flags INT DEFAULT 0,
  approval_authority UUID REFERENCES user_profiles(id) ON DELETE SET NULL,
  approval_role VARCHAR NOT NULL,
  approval_timestamp TIMESTAMP WITHOUT TIME ZONE NOT NULL,
  ai_summary TEXT,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE compliance_report_findings (
  id UUID PRIMARY KEY,
  report_id UUID NOT NULL REFERENCES compliance_reports(id) ON DELETE CASCADE,
  finding_id UUID NOT NULL REFERENCES ai_findings(id) ON DELETE CASCADE,
  finding_status VARCHAR NOT NULL,
  reviewer_decision TEXT,
  UNIQUE(report_id, finding_id)
);

CREATE TABLE compliance_report_audit_refs (
  id UUID PRIMARY KEY,
  report_id UUID NOT NULL REFERENCES compliance_reports(id) ON DELETE CASCADE,
  audit_event_id UUID NOT NULL REFERENCES audit_events(id) ON DELETE CASCADE,
  UNIQUE(report_id, audit_event_id)
);

-- 12. AI FEEDBACK
CREATE TABLE ai_feedback (
  id UUID PRIMARY KEY,
  review_id UUID NOT NULL REFERENCES content_reviews(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  is_liked BOOLEAN NOT NULL,
  feedback_text TEXT,
  submitted_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

-- 13. SOCIAL MEDIA SETTINGS & MONITORING
CREATE TABLE monitored_profiles (
  id UUID PRIMARY KEY,
  url VARCHAR NOT NULL,
  display_name VARCHAR NOT NULL,
  status VARCHAR NOT NULL DEFAULT 'active',
  check_frequency VARCHAR NOT NULL DEFAULT 'daily',
  check_time TIME DEFAULT '09:00',
  last_checked_at TIMESTAMP WITHOUT TIME ZONE,
  posts_reviewed INT DEFAULT 0,
  flagged_posts INT DEFAULT 0,
  added_by UUID NOT NULL REFERENCES user_profiles(id),
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE email_digest_settings (
  id UUID PRIMARY KEY,
  digest_time TIME NOT NULL DEFAULT '08:00',
  is_enabled BOOLEAN DEFAULT TRUE,
  updated_by UUID REFERENCES user_profiles(id) ON DELETE SET NULL,
  updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE email_digest_recipients (
  id UUID PRIMARY KEY,
  settings_id UUID NOT NULL REFERENCES email_digest_settings(id) ON DELETE CASCADE,
  email VARCHAR NOT NULL,
  UNIQUE(settings_id, email)
);

CREATE TABLE email_digests (
  id UUID PRIMARY KEY,
  sent_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
  period VARCHAR NOT NULL,
  posts_reviewed INT DEFAULT 0,
  high_risk_flags INT DEFAULT 0,
  medium_risk_flags INT DEFAULT 0,
  low_risk_flags INT DEFAULT 0,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE email_digest_sent_recipients (
  id UUID PRIMARY KEY,
  digest_id UUID NOT NULL REFERENCES email_digests(id) ON DELETE CASCADE,
  email VARCHAR NOT NULL,
  UNIQUE(digest_id, email)
);

-- 14. NOTIFICATIONS
CREATE TABLE notifications (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
  type VARCHAR NOT NULL,
  title VARCHAR NOT NULL,
  message TEXT,
  reference_type VARCHAR,
  reference_id UUID,
  is_read BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);
