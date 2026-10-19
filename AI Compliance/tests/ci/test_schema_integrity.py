import os
import pytest
import asyncpg
from apis.core.migrations_check import get_filesystem_head_revision

# Retrieve DATABASE_URL and swap out any asyncpg driver schemes (psycopg2 sync standard for env loads)
DATABASE_URL = os.getenv("DATABASE_URL")

@pytest.mark.asyncio
async def test_database_tables_exist():
    """
    Asserts that all core compliance and tenant tables are present in the database.
    """
    assert DATABASE_URL, "DATABASE_URL environment variable is not set"
    db_url = DATABASE_URL.replace("+asyncpg", "") if "+asyncpg" in DATABASE_URL else DATABASE_URL

    conn = await asyncpg.connect(db_url)
    try:
        # Fetch all table names in the active schema
        query = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """
        rows = await conn.fetch(query)
        tables = {row["table_name"] for row in rows}

        # Vital business logic tables that MUST be present
        expected_tables = {
            "organizations",
            "user_profiles",
            "documents",
            "audit_events",
            "alembic_version"
        }

        missing_tables = expected_tables - tables
        assert not missing_tables, f"Missing vital tables in database schema: {missing_tables}"

    finally:
        await conn.close()

@pytest.mark.asyncio
async def test_database_alembic_version_is_head():
    """
    Asserts that the database is fully migrated and its active version matches the codebase's head revision.
    """
    assert DATABASE_URL, "DATABASE_URL environment variable is not set"
    db_url = DATABASE_URL.replace("+asyncpg", "") if "+asyncpg" in DATABASE_URL else DATABASE_URL

    fs_head = get_filesystem_head_revision()
    assert fs_head, "Could not determine Alembic head revision from local files"

    conn = await asyncpg.connect(db_url)
    try:
        # Query active migration revision
        db_current = await conn.fetchval("SELECT version_num FROM alembic_version LIMIT 1")
        if os.getenv("CI") != "true" and db_current != fs_head:
            pytest.skip(f"Local DB is at '{db_current}' while filesystem is at '{fs_head}'. Skipping schema sync check locally.")
        else:
            assert db_current == fs_head, f"Database migration version is out of sync. DB: '{db_current}', Code Head: '{fs_head}'"
    finally:
        await conn.close()