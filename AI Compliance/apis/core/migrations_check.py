import os
import logging
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory
import asyncpg

logger = logging.getLogger(__name__)

def get_filesystem_head_revision() -> str | None:
    """
    Reads the latest migration revision number directly from the local files in alembic/versions.
    """
    try:
        # Resolve path to alembic.ini relative to this file
        here = Path(__file__).resolve()
        # Navigate up to AI Compliance/ folder where alembic.ini sits
        ai_compliance_dir = here.parents[2] 
        ini_path = ai_compliance_dir / "alembic.ini"

        if not ini_path.exists():
            logger.warning(f"alembic.ini not found at {ini_path}")
            return None

        # Load Alembic Config and read current head from script directory
        alembic_cfg = Config(str(ini_path))
        # Ensure script_location is absolute so it can be resolved anywhere
        alembic_cfg.set_main_option("script_location", str(ai_compliance_dir / "alembic"))

        script = ScriptDirectory.from_config(alembic_cfg)
        head_rev = script.get_current_head()
        return head_rev
    except Exception as e:
        logger.error(f"Failed to read migration head from filesystem: {e}")
        return None

async def check_database_migrations(conn: asyncpg.Connection) -> dict:
    """
    Compares the filesystem's latest migration head with what is active in the database.
    """
    fs_head = get_filesystem_head_revision()

    if not fs_head:
        return {
            "status": "unknown",
            "message": "Could not determine local migration head from filesystem."
        }

    try:
        # Query Alembic's version tracking table
        db_current = await conn.fetchval("SELECT version_num FROM alembic_version LIMIT 1")
    except asyncpg.exceptions.UndefinedTableError:
        # Table doesn't exist yet (e.g. fresh DB before first migration)
        db_current = None
    except Exception as e:
        logger.error(f"Failed to query alembic_version table: {e}")
        return {
            "status": "unhealthy",
            "message": f"Error querying migrations table: {str(e)}"
        }

    # Compare
    if db_current == fs_head:
        return {
            "status": "healthy",
            "synced": True,
            "filesystem_head": fs_head,
            "db_current": db_current
        }
    else:
        return {
            "status": "unhealthy",
            "synced": False,
            "filesystem_head": fs_head,
            "db_current": db_current,
            "message": f"Database is out of sync. DB is at '{db_current}', but code expects '{fs_head}'."
        }