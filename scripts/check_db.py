import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv("AI Compliance/.env")

async def main():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("No DATABASE_URL")
        return
        
    db_url = db_url.replace("+asyncpg", "")
    conn = await asyncpg.connect(db_url)
    
    # Check all users
    users = await conn.fetch("SELECT id, email, is_active FROM user_profiles")
    print("All users:")
    for u in users:
        print(f"  {u['email']} (active: {u['is_active']})")
        
    # Check roles
    roles = await conn.fetch("SELECT id, name FROM roles")
    roles_map = {r['id']: r['name'] for r in roles}
    print("\nRoles:")
    for r in roles:
        print(f"  {r['name']}")
        
    # Check user_roles
    user_roles = await conn.fetch("""
        SELECT u.email, r.name 
        FROM user_roles ur
        JOIN user_profiles u ON ur.user_id = u.id
        JOIN roles r ON ur.role_id = r.id
    """)
    print("\nUser Roles:")
    for ur in user_roles:
        print(f"  {ur['email']} -> {ur['name']}")
        
    # Check organization_users
    org_users = await conn.fetch("""
        SELECT u.email, o.name as org_name, o.id as org_id
        FROM organization_users ou
        JOIN user_profiles u ON ou.user_id = u.id
        JOIN organizations o ON ou.organization_id = o.id
    """)
    print("\nOrganization Users:")
    for ou in org_users:
        print(f"  {ou['email']} -> {ou['org_name']} ({ou['org_id']})")
        
    # Run the exact query for SME
    if org_users:
        org_id = org_users[0]['org_id']
        print(f"\nRunning exact query for SME in org {org_id}...")
        recipient_rows = await conn.fetch(
            """
            SELECT DISTINCT up.id, up.email, up.full_name
            FROM user_profiles up
            JOIN organization_users ou ON ou.user_id = up.id AND ou.organization_id = $2::uuid
            JOIN user_roles ur ON ur.user_id = up.id
            JOIN roles r ON r.id = ur.role_id
            WHERE up.is_active = TRUE
              AND lower(r.name) = $1
            """,
            'sme',
            org_id,
        )
        print(f"Found {len(recipient_rows)} SME recipients:")
        for r in recipient_rows:
            print(f"  {r['email']}")
            
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())

