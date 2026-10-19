#!/usr/bin/env python3
import asyncio
import os
from dotenv import load_dotenv
import asyncpg

load_dotenv()

SQL = """
SELECT
    o.name AS org_name,
    o.slug AS org_slug,
    COUNT(dv.id)::int AS upload_count,
    COALESCE(SUM(dv.file_size_bytes), 0)::bigint AS total_bytes
FROM organizations o
LEFT JOIN documents d ON o.id = d.organization_id
LEFT JOIN document_versions dv ON d.id = dv.document_id
GROUP BY o.id, o.name, o.slug
ORDER BY o.name;
"""

async def main():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise SystemExit("Missing DB URL. Set DATABASE_URL in .env")

    conn = await asyncpg.connect(db_url)
    try:
        rows = await conn.fetch(SQL)
    finally:
        await conn.close()

    print(f"{'Organization Name':<30} | {'Slug':<20} | {'Uploads':<10} | {'Total Size (MB)':<15}")
    print("-" * 85)
    for row in rows:
        org_name = row['org_name']
        org_slug = row['org_slug']
        count = row['upload_count']
        mb_size = row['total_bytes'] / (1024 * 1024)
        print(f"{org_name:<30} | {org_slug:<20} | {count:<10} | {mb_size:<15.2f}")

if __name__ == "__main__":
    asyncio.run(main())
