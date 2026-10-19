import logging
import os
from pathlib import Path

from celery import Celery
from celery.signals import worker_process_init

logger = logging.getLogger(__name__)
from dotenv import dotenv_values, load_dotenv

# Match mail.py: backend .env for local DB/Redis, repo root wins for SES sender.
_CELERY_DIR = Path(__file__).resolve().parent
_AI_ENV = _CELERY_DIR.parents[1] / ".env"
_REPO_ENV = _CELERY_DIR.parents[2] / ".env"
if _AI_ENV.exists():
    load_dotenv(_AI_ENV, override=False)
if _REPO_ENV.exists():
    load_dotenv(_REPO_ENV, override=False)
    repo_ses = (dotenv_values(_REPO_ENV).get("SES_SOURCE_EMAIL") or "").strip()
    if repo_ses:
        os.environ["SES_SOURCE_EMAIL"] = repo_ses

# Redis URL from environment or default to local (for docker, it will be 'redis')
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "compliance_ai",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["apis.services.celery_tasks"]
)

# Broker payload rule (see apis/services/celery_tasks.py):
# Pass only IDs and S3 object coordinates — never file bytes, HTML, or full user JWT dicts.
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_ignore_result=True,
    # Long-running Docling/LLM tasks: fetch one job at a time per child process.
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=int(os.getenv("CELERY_MAX_TASKS_PER_CHILD", "10")),
    # Redis: visibility timeout must exceed longest task time_limit (300s).
    broker_transport_options={
        "visibility_timeout": int(os.getenv("CELERY_VISIBILITY_TIMEOUT", "3600")),
    },
)

@worker_process_init.connect
def _log_load_test_stub_on_worker_start(**_kwargs):
    from apis.services.ai.llm.load_test_stub import log_stub_startup

    log_stub_startup()


if __name__ == "__main__":
    celery_app.start()
