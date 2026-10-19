"""
Celery tasks for background document processing.

Broker payload rule
-------------------
Only pass JSON-serializable scalars and coordinates through ``.delay()`` / ``apply_async``:
  - document IDs, version IDs, user UUID strings
  - S3 ``bucket`` + ``s3_key`` (worker downloads bytes locally)

Never queue: file bytes, HTML/PDF content, presigned URLs with huge query strings,
or full ``current_user`` / JWT claim dicts.
"""
import asyncio
import json
import logging
import os
from typing import Any, Optional

from apis.services.celery_app import celery_app

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
DOC_UPDATES_CHANNEL = "doc_updates"


def _normalize_triggered_by_user_id(value: Any) -> Optional[str]:
    """
    Accept user id string from the broker, or a legacy full-user dict from in-flight jobs.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        uid = value.get("id")
        return str(uid) if uid else None
    text = str(value).strip()
    return text or None


def _redis_publish(doc_id: str, payload: dict):
    """
    Synchronously publish a message to the Redis 'doc_updates' channel.
    This is called from the Celery worker (sync context) after analysis completes.
    The API SSE endpoint subscribes to this channel and forwards events to browsers.
    """
    try:
        import redis as redis_lib
        r = redis_lib.from_url(REDIS_URL)
        message = json.dumps({"doc_id": doc_id, **payload})
        r.publish(DOC_UPDATES_CHANNEL, message)
        r.close()
        logger.info(f"REDIS_PUBLISH doc_id={doc_id} payload={payload}")
    except Exception as e:
        # Non-fatal — browser will fall back to manual refresh
        logger.warning(f"REDIS_PUBLISH_FAIL doc_id={doc_id} err={e}")


@celery_app.task(
    name="analyze_document_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    time_limit=int(os.getenv("CELERY_TASK_TIME_LIMIT", "1800")),       # 30 minutes hard kill
    soft_time_limit=int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "1500")) # 25 minutes soft timeout
)
def analyze_document_task(doc_id: str, triggered_by_user_id: Optional[str] = None):
    """
    Celery worker task that handles the heavy AI document processing.
    On completion (success or failure), publishes to Redis so the API
    can push a real-time SSE event to the browser.
    """
    triggered_by_user_id = _normalize_triggered_by_user_id(triggered_by_user_id)

    # We import locally so the main API doesn't need to load the heavy libraries
    from apis.v1.routers.documents import _analyze_document_bg
    import apis.core.database as db_module
    import asyncpg

    from apis.services.ai.llm.load_test_stub import reset_stub_sleep_state

    reset_stub_sleep_state()

    logger.info(
        "CELERY_WORKER: Starting analysis doc_id=%s triggered_by=%s",
        doc_id,
        triggered_by_user_id,
    )

    async def _run_with_db():
        pool = None
        try:
            # Initialize a temporary connection pool for this task's event loop
            pool = await asyncpg.create_pool(db_module.DATABASE_URL, min_size=1, max_size=5)
            db_module.db_pool = pool
            await _analyze_document_bg(doc_id, triggered_by_user_id)
        finally:
            if pool:
                await pool.close()
            db_module.db_pool = None

    async def _mark_doc_failed_in_db(target_doc_id: str):
        pool = None
        try:
            pool = await asyncpg.create_pool(db_module.DATABASE_URL, min_size=1, max_size=2)
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE document_versions SET status = 'failed' WHERE document_id = $1 AND status = 'processing'",
                    target_doc_id
                )
        except Exception:
            pass
        finally:
            if pool:
                await pool.close()

    try:
        # Run the wrapper in a new event loop
        asyncio.run(_run_with_db())
        # Only log 'Completed' if no exception was raised
        logger.info(f"CELERY_WORKER: Completed analysis for doc_id={doc_id}")
        # Notify the API — browser will auto-refresh results + fetch annotated PDF
        _redis_publish(doc_id, {"phase": "completed", "rules_checked": 0, "rules_total": 0})
    except BaseException as e:
        err_msg = str(e) or type(e).__name__
        logger.error(f"CELERY_WORKER: Failed analysis for doc_id={doc_id} - {err_msg}", exc_info=True)
        # Notify the API of failure so the browser can show an error state
        _redis_publish(doc_id, {"phase": "failed", "error": err_msg})
        try:
            asyncio.run(_mark_doc_failed_in_db(doc_id))
        except Exception:
            pass
        # Re-raise so Celery marks the task as FAILURE, not SUCCESS
        raise





@celery_app.task(
    name="pre_extract_document_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=2,
    time_limit=300,
    soft_time_limit=240
)
def pre_extract_document_task(doc_id: str, version_id: str, bucket: str, s3_key: str):
    """Parse document to HTML via Docling; payload is S3 coordinates only."""
    from apis.v1.routers.documents import _pre_extract_text_bg
    import apis.core.database as db_module
    import asyncpg

    logger.info(f"CELERY_WORKER: Starting pre-extraction for doc_id={doc_id}")

    async def _run():
        pool = None
        try:
            pool = await asyncpg.create_pool(db_module.DATABASE_URL, min_size=1, max_size=3)
            db_module.db_pool = pool
            await _pre_extract_text_bg(doc_id, version_id, bucket, s3_key)
        finally:
            if pool:
                await pool.close()
            db_module.db_pool = None

    try:
        asyncio.run(_run())
    except Exception as e:
        logger.error(f"CELERY_WORKER: Failed pre-extraction for doc_id={doc_id} - {e}", exc_info=True)
        raise


@celery_app.task(
    name="warm_office_preview_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=2,
    time_limit=300,
    soft_time_limit=240
)
def warm_office_preview_task(doc_id: str, version_id: str, bucket: str, s3_key: str):
    """Convert Office upload to cached PDF preview; payload is S3 coordinates only."""
    from apis.v1.routers.documents import _warm_office_preview_cache_bg
    import apis.core.database as db_module
    import asyncpg

    logger.info(f"CELERY_WORKER: Starting office preview warmup for doc_id={doc_id}")

    async def _run():
        pool = None
        try:
            pool = await asyncpg.create_pool(db_module.DATABASE_URL, min_size=1, max_size=3)
            db_module.db_pool = pool
            await _warm_office_preview_cache_bg(doc_id, version_id, bucket, s3_key)
        finally:
            if pool:
                await pool.close()
            db_module.db_pool = None

    try:
        asyncio.run(_run())
    except Exception as e:
        logger.error(f"CELERY_WORKER: Failed office preview warmup for doc_id={doc_id} - {e}", exc_info=True)
        raise

@celery_app.task(
    name="classify_document_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=2,
    time_limit=300,
    soft_time_limit=240
)
def classify_document_task(
    doc_id: str,
    version_id: str,
    bucket: str,
    s3_key: str,
    user_id: str,
    initial_stage: str,
    organization_id: str = None
):
    """Run document classification (Docling parsing + AI classification) in background."""
    from apis.v1.routers.documents import _classify_document_bg
    from apis.services.ai.llm.load_test_stub import reset_stub_sleep_state
    import apis.core.database as db_module
    import asyncpg

    reset_stub_sleep_state()

    logger.info(f"CELERY_WORKER: Starting classification for doc_id={doc_id} version_id={version_id}")

    async def _run():
        pool = None
        try:
            pool = await asyncpg.create_pool(db_module.DATABASE_URL, min_size=1, max_size=3)
            db_module.db_pool = pool
            await _classify_document_bg(
                doc_id=doc_id,
                version_id=version_id,
                bucket=bucket,
                s3_key=s3_key,
                user_id=user_id,
                initial_stage=initial_stage,
                organization_id=organization_id,
            )
        finally:
            if pool:
                await pool.close()
            db_module.db_pool = None

    try:
        asyncio.run(_run())
    except Exception as e:
        logger.error(f"CELERY_WORKER: Failed classification for doc_id={doc_id} - {e}", exc_info=True)
        raise
