import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
import asyncpg

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
_AI_COMPLIANCE_DIR = _REPO_ROOT / "AI Compliance"

load_dotenv(_AI_COMPLIANCE_DIR / ".env")
load_dotenv(_REPO_ROOT / ".env")
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")

# Lower number means higher priority
PRIORITY_MAP = {
    "super_admin": 1,
    "marketing": 2,
    "compliance": 3,
    "sme": 4
}

def _normalize_database_url(url: str) -> str:
    if "+asyncpg" in url:
        return url.replace("+asyncpg", "")
    return url

async def main():
    if not DATABASE_URL:
        print("Error: DATABASE_URL is required in .env")
        return

    conn = await asyncpg.connect(_normalize_database_url(DATABASE_URL))
    
    try:
        # Find all users who exceed their allowed role limits (2 for super_admin, 1 for others)
        users_with_many_roles = await conn.fetch("""
            SELECT ur.user_id
            FROM user_roles ur
            JOIN roles r ON ur.role_id = r.id
            GROUP BY ur.user_id
            HAVING 
                (bool_or(r.name = 'super_admin') AND COUNT(ur.role_id) > 2)
                OR 
                (NOT bool_or(r.name = 'super_admin') AND COUNT(ur.role_id) > 1)
        """)
        
        if not users_with_many_roles:
            print("No users found exceeding their role limits. Everything is already clean!")
            return
            
        print(f"Found {len(users_with_many_roles)} users exceeding role limits. Trimming...")

        for user_row in users_with_many_roles:
            user_id = user_row['user_id']
            
            # Fetch the actual role details for this user
            roles = await conn.fetch("""
                SELECT ur.id as user_role_id, r.name, r.id as role_id 
                FROM user_roles ur
                JOIN roles r ON ur.role_id = r.id
                WHERE ur.user_id = $1
            """, user_id)
            
            # Sort roles by priority
            # If a role is not in PRIORITY_MAP, it gets a default low priority (e.g., 99)
            sorted_roles = sorted(roles, key=lambda r: PRIORITY_MAP.get(r['name'], 99))
            
            # Determine limit: 2 if super_admin is present, otherwise 1
            has_super_admin = any(r['name'] == 'super_admin' for r in sorted_roles)
            limit = 2 if has_super_admin else 1
            
            # Keep the top roles, remove the rest
            roles_to_keep = sorted_roles[:limit]
            roles_to_remove = sorted_roles[limit:]
            
            keep_names = [r['name'] for r in roles_to_keep]
            remove_names = [r['name'] for r in roles_to_remove]
            
            print(f"User {user_id}: Keeping {keep_names}, Removing {remove_names}")
            
            # Execute DELETE query for the lower priority roles
            for r in roles_to_remove:
                await conn.execute("DELETE FROM user_roles WHERE id = $1", r['user_role_id'])
                
        print("Cleanup complete!")
            
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
