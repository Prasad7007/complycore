import os
import logging
from contextlib import asynccontextmanager
import asyncpg
from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ai_compliance")
# AI analysis used to hold a connection for minutes (S3 + LLM); a tiny pool starved login and other APIs.
POOL_MIN = int(os.getenv("DATABASE_POOL_MIN", "2"))
POOL_MAX = int(os.getenv("DATABASE_POOL_MAX", "50"))
db_pool = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=POOL_MIN, max_size=POOL_MAX)
        logger.info("Database pool created min_size=%s max_size=%s", POOL_MIN, POOL_MAX)
        yield
    finally:
        if db_pool:
            await db_pool.close()
            logger.info("Database pool closed")

async def get_db():
    if not db_pool:
        raise HTTPException(status_code=500, detail="Database not initialized")
    async with db_pool.acquire() as conn:
        yield conn