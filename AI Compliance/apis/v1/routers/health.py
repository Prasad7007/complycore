import time
import logging
import os
import asyncio
from fastapi import APIRouter, Response, status
import redis.asyncio as aioredis
from apis.core import database as db_module
from apis.core.migrations_check import check_database_migrations
from apis.services.celery_app import celery_app

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["System"])

@router.get("")
async def health_check(response: Response):
    health_status = {
        "status": "healthy",
        "timestamp": time.time(),
        "checks": {}
    }
    has_error = False

    # 1. Database Connection + Migration Version Check
    try:
        if not db_module.db_pool:
            raise Exception("Database pool not initialized")

        async with db_module.db_pool.acquire() as conn:
            # Check DB ping
            start_time = time.time()
            await conn.fetchval("SELECT 1")
            latency = (time.time() - start_time) * 1000

            # Check DB migration alignment
            migration_info = await check_database_migrations(conn)
            health_status["checks"]["database"] = {
                "status": "healthy",
                "latency_ms": round(latency, 2)
            }
            health_status["checks"]["migrations"] = migration_info

            if not migration_info.get("synced", False):
                has_error = True

    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        health_status["checks"]["database"] = {"status": "unhealthy", "error": str(e)}
        has_error = True

    # 2. Redis Connection Check
    try:
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        start_time = time.time()
        # Set a low connection/socket timeout so we fail quickly if Redis is completely dead
        redis_client = aioredis.from_url(redis_url, socket_timeout=2.0, socket_connect_timeout=2.0)
        await redis_client.ping()
        await redis_client.aclose()
        latency = (time.time() - start_time) * 1000
        health_status["checks"]["redis"] = {
            "status": "healthy",
            "latency_ms": round(latency, 2)
        }
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        health_status["checks"]["redis"] = {"status": "unhealthy", "error": str(e)}
        has_error = True

    # 3. Celery Worker Check
    try:
        start_time = time.time()
        # Query Celery worker ping asynchronously using to_thread to avoid blocking event loop
        def _ping_workers():
            try:
                # Returns something like [{'celery@worker-name': {'ok': 'pong'}}] or empty list/None
                return celery_app.control.ping(timeout=1.5)
            except Exception as e:
                logger.warning(f"Error querying Celery workers: {e}")
                return None

        workers = await asyncio.to_thread(_ping_workers)
        latency = (time.time() - start_time) * 1000

        if not workers:
            health_status["checks"]["celery"] = {
                "status": "unhealthy",
                "error": "No active Celery workers responded to ping",
                "latency_ms": round(latency, 2)
            }
            has_error = True
        else:
            health_status["checks"]["celery"] = {
                "status": "healthy",
                "workers_online": len(workers),
                "workers": [list(w.keys())[0] for w in workers if w],
                "latency_ms": round(latency, 2)
            }
    except Exception as e:
        logger.error(f"Celery health check failed: {e}")
        health_status["checks"]["celery"] = {"status": "unhealthy", "error": str(e)}
        has_error = True

    if has_error:
        health_status["status"] = "unhealthy"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return health_status