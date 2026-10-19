import asyncio
import asyncpg
import os
import uuid
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Add it to AI Compliance/.env or export it in the shell."
    )

# asyncpg does not support +asyncpg in the DSN scheme; strip it if present.
if "+asyncpg" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("+asyncpg", "")

async def seed(conn=None, skip_schema=False):
    """
    Seed roles, permissions, and compliance rules.

    Prefer: `python init_database.py` (Alembic migrate + seed with skip_schema=True).
    If skip_schema is False, also runs schema.sql (legacy; do not use for new DBs).

    Bootstrap: self-service signup does not grant roles. Create the first admin via
    app bootstrap / scripts/bootstrap_owner.py, or an existing super_admin session.
    """
    should_close = False
    if not conn:
        print(f"Connecting to database at {DATABASE_URL}...")
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            should_close = True
        except Exception as e:
            print(f"Error connecting to database: {e}")
            return

    if not skip_schema:
        # 1. Execute schema.sql to recreate tables from scratch
        print("Executing schema.sql to create normalized tables...")
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        try:
            await conn.execute(schema_sql)
            print("Schema created successfully.")
        except Exception as e:
            print(f"Error executing schema: {e}")
            if should_close:
                await conn.close()
            return
    else:
        print("Skipping schema creation (already initialized by orchestrator).")

    # 2. Define Roles
    roles = [
        {"name": "owner", "display_name": "Owner", "description": "Platform owner for multitenancy operations"},
        {"name": "marketing", "display_name": "Marketing User", "description": "Admin - Upload, create/edit content, submit to SME/Compliance"},
        {"name": "sme", "display_name": "Subject Matter Expert", "description": "Review content technically, add comments, approve/reject technically"},
        {"name": "compliance", "display_name": "Compliance Officer", "description": "Final review, approve/reject/lock, export audit trail"},
        {"name": "super_admin", "display_name": "Super Admin", "description": "Full system access (upload, manage users, override workflow)"},
    ]

    print("Seeding Roles...")
    role_map = {} # name -> id
    for r in roles:
        role_id = str(uuid.uuid4())
        try:
            row = await conn.fetchrow("""
                INSERT INTO roles (id, name, display_name, description)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (name) DO UPDATE SET display_name = $3
                RETURNING id
            """, role_id, r["name"], r["display_name"], r["description"])
            role_map[r["name"]] = row["id"]
            print(f"  Role '{r['name']}' ready.")
        except Exception as e:
            print(f"  Error seeding role {r['name']}: {e}")

    # 3. Define Permissions (Based on AuthContext.tsx)
    permissions = [
        # Marketing
        {"key": "canUploadDocuments", "display_name": "Upload Documents", "category": "Document"},
        {"key": "canEditContent", "display_name": "Edit Content", "category": "Content"},
        {"key": "canSelectContentType", "display_name": "Select Content Type", "category": "Content"},
        {"key": "canViewAIFlags", "display_name": "View AI Flags", "category": "AI"},
        {"key": "canViewRewriteSuggestions", "display_name": "View Rewrite Suggestions", "category": "AI"},
        {"key": "canAcceptAISuggestions", "display_name": "Accept AI Suggestions", "category": "AI"},
        {"key": "canMakeCustomEdits", "display_name": "Make Custom Edits", "category": "Content"},
        {"key": "canSubmitToSME", "display_name": "Submit to SME", "category": "Workflow"},
        {"key": "canSubmitToCompliance", "display_name": "Submit to Compliance", "category": "Workflow"},
        {"key": "canViewStatusDashboard", "display_name": "View Status Dashboard", "category": "Dashboard"},
        {"key": "canPublish", "display_name": "Publish Content", "category": "Workflow"},
        {"key": "canOverrideCompliance", "display_name": "Override Compliance", "category": "Workflow"},
        {"key": "canApproveDocuments", "display_name": "Approve Documents", "category": "Workflow"},
        {"key": "canEditComplianceLogs", "display_name": "Edit Compliance Logs", "category": "Compliance"},
        {"key": "canRejectAIFlags", "display_name": "Reject AI Flags", "category": "AI"},
        {"key": "canAccessAuditTrail", "display_name": "Access Audit Trail", "category": "Audit"},
        {"key": "canExportAuditTrail", "display_name": "Export Audit Trail", "category": "Audit"},
        {"key": "canLockDocument", "display_name": "Lock Document", "category": "Document"},
        {"key": "canAddComplianceNotes", "display_name": "Add Compliance Notes", "category": "Compliance"},
        {"key": "canManageUsers", "display_name": "Manage Users", "category": "Admin"},
        {"key": "canAccessSocialMediaSettings", "display_name": "Access Social Media Settings", "category": "Social"},
        {"key": "canAccessSocialMedia", "display_name": "Access Social Media", "category": "Social"},
        {"key": "canAddComments", "display_name": "Add Comments", "category": "Collaboration"},
        {"key": "canRejectDocuments", "display_name": "Reject Documents", "category": "Workflow"},
        {"key": "canRequestChanges", "display_name": "Request Changes", "category": "Workflow"},
        {"key": "canViewAllComments", "display_name": "View All Comments", "category": "Collaboration"},
        {"key": "canViewRulesTriggered", "display_name": "View Rules Triggered", "category": "Compliance"},
    ]

    print("Seeding Permissions...")
    perm_map = {} # key -> id
    for p in permissions:
        perm_id = str(uuid.uuid4())
        try:
            row = await conn.fetchrow("""
                INSERT INTO permissions (id, key, display_name, category)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (key) DO UPDATE SET display_name = $3
                RETURNING id
            """, perm_id, p["key"], p["display_name"], p["category"])
            perm_map[p["key"]] = row["id"]
        except Exception as e:
             print(f"  Error seeding permission {p['key']}: {e}")

    # 4. Assign Permissions to Roles (Based on AuthContext.tsx)
    role_perms = {
        # Owner is intentionally excluded from regular app permissions and UI routes.
        "owner": [],
        "marketing": [
            "canUploadDocuments", "canEditContent", "canSelectContentType", "canViewAIFlags",
            "canViewRewriteSuggestions", "canAcceptAISuggestions", "canMakeCustomEdits",
            "canSubmitToSME", "canSubmitToCompliance", "canViewStatusDashboard", "canPublish",
            "canAccessAuditTrail", "canAccessSocialMediaSettings"
        ],
        "sme": [
             "canViewStatusDashboard", "canApproveDocuments", "canAccessAuditTrail",
             "canAddComments", "canRejectDocuments", "canRequestChanges"
        ],
        "compliance": [
            "canViewAIFlags", "canViewRewriteSuggestions", "canAcceptAISuggestions", "canViewStatusDashboard",
            "canApproveDocuments", "canRejectAIFlags", "canAccessAuditTrail", "canExportAuditTrail",
            "canLockDocument", "canAddComplianceNotes", "canRejectDocuments", "canViewAllComments",
            "canViewRulesTriggered"
        ],
        # Super admin gets all permissions
        "super_admin": list(perm_map.keys()),
    }

    print("Assigning Permissions to Roles...")
    for role_name, perms in role_perms.items():
        rid = role_map.get(role_name)
        if not rid: continue
        
        for pkey in perms:
            pid = perm_map.get(pkey)
            if not pid:
                print(f"  Warning: Permission '{pkey}' not found for role '{role_name}'")
                continue
            
            await conn.execute("""
                INSERT INTO role_permissions (id, role_id, permission_id, granted)
                VALUES ($1, $2, $3, TRUE)
                ON CONFLICT (role_id, permission_id) DO NOTHING
            """, str(uuid.uuid4()), rid, pid)

    # 5. Create Default User Profiles (One for each role) - Skipped as requested
    print("Skipping default demo users seeding as requested.")

    
    # 6. Seed Compliance Rules (R1-R8)
    print("Seeding Compliance Rules...")
    compliance_rules = [
        {"rule_code": "RULE-1", "name": "Marketing content must not be false or misleading", "description": "All marketing materials must be truthful. Claims that are factually incorrect, intentionally deceptive, or likely to mislead investors are prohibited.", "category": "Accuracy"},
        {"rule_code": "RULE-2", "name": "Statements must be factually accurate and supportable", "description": "Every factual claim in marketing content must be supportable by evidence. Unsubstantiated statistics, cherry-picked data, or unsupported comparisons violate this rule.", "category": "Accuracy"},
        {"rule_code": "RULE-3", "name": "Language must not exaggerate benefits or minimize risks", "description": "Marketing must not overstate potential returns, understate risks, or use language that creates an unrealistic expectation of investment performance.", "category": "Balance"},
        {"rule_code": "RULE-4", "name": "Marketing must present fair and balanced information", "description": "Content must give equal prominence to risks and rewards. One-sided presentations that focus only on upside without adequately disclosing risk are prohibited.", "category": "Balance"},
        {"rule_code": "RULE-5", "name": "Disclaimers must be clearly visible and readable", "description": "Risk disclaimers and important information must be presented in a font size and location that ensures investors can easily read and understand them.", "category": "Presentation"},
        {"rule_code": "RULE-6", "name": "Promotional or absolute language", "description": "Marketing must avoid absolute or promotional language such as 'guaranteed', 'risk-free', or 'always' that cannot be substantiated.", "category": "Presentation"},
        {"rule_code": "RULE-7", "name": "Emotional or manipulative language", "description": "Content must not use emotional manipulation, fear tactics, or language designed to pressure investors into making quick decisions.", "category": "Presentation"},
        {"rule_code": "RULE-8", "name": "Forward-looking statements require disclaimers", "description": "Any forward-looking statements or projections must include appropriate disclaimers about the inherent uncertainty of future performance.", "category": "Disclosure"},
    ]
    
    rules_map = {}  # rule_code -> id
    for rule in compliance_rules:
        rule_id = str(uuid.uuid4())
        try:
            row = await conn.fetchrow("""
                INSERT INTO compliance_rules (id, rule_code, name, description, category)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (rule_code) DO UPDATE SET name = $3, description = $4, category = $5
                RETURNING id
            """, rule_id, rule["rule_code"], rule["name"], rule["description"], rule["category"])
            rules_map[rule["rule_code"]] = row["id"]
            print(f"  Rule '{rule['rule_code']}' ready.")
        except Exception as e:
            print(f"  Error seeding rule {rule['rule_code']}: {e}")

    # Social/LinkedIn sample data removed with monitoring feature.
    if should_close:
        await conn.close()
    print("Database seeding completed successfully!")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Seed database")
    parser.add_argument("--skip-schema", action="store_true", help="Skip schema creation")
    args = parser.parse_args()
    asyncio.run(seed(skip_schema=args.skip_schema))

