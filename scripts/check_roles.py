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

def _normalize_database_url(url: str) -> str:
    if "+asyncpg" in url:
        return url.replace("+asyncpg", "")
    return url

async def main():
    if not DATABASE_URL:
        print("Error: DATABASE_URL is required in .env")
        return

    conn = await asyncpg.connect(_normalize_database_url(DATABASE_URL))
    rows = await conn.fetch("""
        SELECT u.id, u.email, COUNT(ur.role_id) as role_count 
        FROM user_profiles u 
        JOIN user_roles ur ON u.id = ur.user_id 
        JOIN roles r ON ur.role_id = r.id
        GROUP BY u.id, u.email 
        HAVING 
            (bool_or(r.name = 'super_admin') AND COUNT(ur.role_id) > 2)
            OR 
            (NOT bool_or(r.name = 'super_admin') AND COUNT(ur.role_id) > 1)
    """)
    print(f"Users exceeding role limits: {len(rows)}")
    for r in rows:
        print(f"{r['email']}: {r['role_count']} roles")
    await conn.close()

asyncio.run(main())
