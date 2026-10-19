"""
CI test fixtures — seeds the minimal database state required for the auth
integration tests to pass on a freshly-migrated blank database (as in GHA).
These fixtures do NOT conflict with local runs: asyncpg INSERT uses
ON CONFLICT DO NOTHING, so seeded local data is untouched.
"""
import os
import uuid
import asyncio
import pytest
import asyncpg

# The demo email used in test_auth_flow.py
DEMO_EMAIL = "compliance@company.com"

DATABASE_URL = os.getenv("DATABASE_URL")


@pytest.fixture(scope="session", autouse=True)
def seed_demo_user():
    """
    Session-scoped fixture that ensures the demo user profile exists in the
    database before any tests run.  Uses ON CONFLICT DO NOTHING so it is
    completely safe against local databases that already have the user seeded.
    """
    if not DATABASE_URL:
        return

    db_url = DATABASE_URL.replace("+asyncpg", "") if "+asyncpg" in DATABASE_URL else DATABASE_URL

    async def _seed():
        conn = await asyncpg.connect(db_url)
        try:
            # Insert the demo user profile required by test_auth_flow.py
            # ON CONFLICT DO NOTHING = safe to run on a local DB that already has this user
            await conn.execute(
                """
                INSERT INTO user_profiles (id, cognito_sub, email, full_name, department, is_active)
                VALUES ($1, $2, $3, 'Compliance User', 'Compliance', TRUE)
                ON CONFLICT (email) DO NOTHING
                """,
                str(uuid.uuid4()),
                f"ci-demo-sub-{uuid.uuid4()}",
                DEMO_EMAIL,
            )
        finally:
            await conn.close()

    asyncio.get_event_loop().run_until_complete(_seed())