"""
Diagnostic script to check and fix user role assignments.
Run this to verify that marketing users have the correct roles assigned.
"""
import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ai_compliance")
if "+asyncpg" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("+asyncpg", "")

async def check_and_fix_roles():
    print(f"Connecting to database at {DATABASE_URL}...")
    try:
        conn = await asyncpg.connect(DATABASE_URL)
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return

    # Check all users and their roles
    print("\n=== Current User Roles ===")
    users = await conn.fetch("""
        SELECT 
            up.id,
            up.email,
            up.full_name,
            COALESCE(STRING_AGG(r.name, ', '), 'NO ROLES') as roles
        FROM user_profiles up
        LEFT JOIN user_roles ur ON up.id = ur.user_id
        LEFT JOIN roles r ON ur.role_id = r.id
        GROUP BY up.id, up.email, up.full_name
        ORDER BY up.email
    """)
    
    for user in users:
        print(f"  {user['email']} ({user['full_name']}): {user['roles']}")
    
    # Check if marketing@company.com has marketing role
    print("\n=== Checking marketing@company.com ===")
    marketing_user = await conn.fetchrow("""
        SELECT id, email, full_name FROM user_profiles WHERE lower(email) = lower('marketing@company.com')
    """)
    
    if not marketing_user:
        print("  ❌ marketing@company.com not found in database!")
        print("  Initialize the database to create demo users.")
        await conn.close()
        return
    
    print(f"  [OK] Found user: {marketing_user['email']} (ID: {marketing_user['id']})")
    
    # Check roles
    user_roles = await conn.fetch("""
        SELECT r.name, r.id
        FROM user_roles ur
        JOIN roles r ON ur.role_id = r.id
        WHERE ur.user_id = $1
    """, marketing_user['id'])
    
    role_names = [r['name'] for r in user_roles]
    print(f"  Current roles: {role_names if role_names else 'NO ROLES'}")
    
    # Check if marketing role exists
    marketing_role = await conn.fetchrow("SELECT id, name FROM roles WHERE lower(name) = 'marketing'")
    if not marketing_role:
        print("  [ERROR] 'marketing' role not found in roles table!")
        print("  Initialize the database to create roles.")
        await conn.close()
        return
    
    print(f"  [OK] 'marketing' role exists (ID: {marketing_role['id']})")
    
    # Check if user has marketing role
    has_marketing = any(r['name'].lower() == 'marketing' for r in user_roles)
    
    if not has_marketing:
        print("  [ERROR] User does NOT have 'marketing' role assigned!")
        print("  Fixing by assigning marketing role...")
        
        # Assign marketing role
        await conn.execute("""
            INSERT INTO user_roles (id, user_id, role_id)
            VALUES (gen_random_uuid(), $1, $2)
            ON CONFLICT (user_id, role_id) DO NOTHING
        """, marketing_user['id'], marketing_role['id'])
        
        print("  [OK] Marketing role assigned!")
    else:
        print("  [OK] User already has 'marketing' role")
    
    # Verify fix
    user_roles_after = await conn.fetch("""
        SELECT r.name
        FROM user_roles ur
        JOIN roles r ON ur.role_id = r.id
        WHERE ur.user_id = $1
    """, marketing_user['id'])
    
    role_names_after = [r['name'] for r in user_roles_after]
    print(f"  Updated roles: {role_names_after}")
    
    await conn.close()
    print("\n=== Done ===")

if __name__ == "__main__":
    asyncio.run(check_and_fix_roles())