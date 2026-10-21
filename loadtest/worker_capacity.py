"""Benchmark Celery document-analysis capacity without API auth or a supplied PDF."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, "/app")

import asyncpg
import fitz

from apis.core.database import DATABASE_URL
from apis.services.ai.core import config as ai_config
from apis.services.ai.core.s3_client import s3_client
from apis.services.ai.llm.load_test_stub import assert_stub_allowed, load_test_stub_enabled
from apis.services.celery_tasks import analyze_document_task

logger = logging.getLogger("worker_capacity")
TERMINAL_EVENTS = {"ai_analysis_completed": "completed", "ai_analysis_failed": "failed"}
REPORT_DIR = Path("/loadtest/reports")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Queue synthetic document analyses directly to Celery and report worker capacity."
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Maximum simultaneous Celery document tasks for this run (default: 1).",
    )
    parser.add_argument(
        "--steps",
        nargs="+",
        type=int,
        default=[4, 8, 12],
        help="Documents to dispatch together at each capacity step (default: 4 8 12).",
    )
    parser.add_argument(
        "--max-wait-minutes",
        type=float,
        default=12,
        help="A step passes only if all its analyses finish within this time (default: 12).",
    )
    parser.add_argument(
        "--drain-timeout-minutes",
        type=float,
        default=60,
        help="After a step exceeds its max wait, allow this long to drain queued work safely.",
    )
    parser.add_argument("--poll-interval-seconds", type=float, default=5)
    parser.add_argument(
        "--cleanup-run-id",
        help="Remove synthetic records from a prior run after confirming its Celery tasks have drained.",
    )
    return parser.parse_args()


def _synthetic_pdf() -> bytes:
    document = fitz.open()
    try:
        page = document.new_page()
        page.insert_text(
            (54, 72),
            "Synthetic compliance load test document. "
            "This document contains no real customer or marketing data.",
            fontsize=12,
        )
        return document.tobytes()
    finally:
        document.close()


async def _create_test_owner(
    pool: asyncpg.Pool,
    run_id: str,
) -> tuple[uuid.UUID, uuid.UUID]:
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    created_at = datetime.now(timezone.utc).replace(tzinfo=None)
    async with pool.acquire() as db:
        async with db.transaction():
            await db.execute(
                """
                INSERT INTO organizations (id, name, slug, status, created_at, updated_at)
                VALUES ($1, $2, $3, 'active', $4, $4)
                """,
                organization_id,
                f"Worker capacity test {run_id[:8]}",
                f"loadtest-{run_id}",
                created_at,
            )
            await db.execute(
                """
                INSERT INTO user_profiles (id, cognito_sub, email, full_name, is_active, created_at, updated_at)
                VALUES ($1, $2, $3, $4, TRUE, $5, $5)
                """,
                user_id,
                f"loadtest:{run_id}",
                f"loadtest-{run_id}@invalid.example",
                f"Worker Load Test {run_id[:8]}",
                created_at,
            )
            await db.execute(
                """
                INSERT INTO organization_users (id, organization_id, user_id, role_in_org, is_owner, created_at)
                VALUES ($1, $2, $3, 'marketing', TRUE, $4)
                """,
                uuid.uuid4(),
                organization_id,
                user_id,
                created_at,
            )
            role_id = await db.fetchval("SELECT id FROM roles WHERE name = 'marketing'")
            if not role_id:
                raise RuntimeError("Marketing role is missing; initialize and seed the test database first.")
            await db.execute(
                """
                INSERT INTO user_roles (id, user_id, role_id, assigned_at)
                VALUES ($1, $2, $3, $4)
                """,
                uuid.uuid4(),
                user_id,
                role_id,
                created_at,
            )
    return organization_id, user_id


async def _create_batch(
    pool: asyncpg.Pool,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    run_id: str,
    first_index: int,
    count: int,
    pdf_bytes: bytes,
) -> list[dict[str, Any]]:
    bucket = (ai_config.AWS_S3_BUCKET or "").strip()
    if not bucket:
        raise RuntimeError("AWS_S3_BUCKET is not configured in the running app environment.")

    created_at = datetime.now(timezone.utc).replace(tzinfo=None)
    docs: list[dict[str, Any]] = []
    uploaded_keys: list[str] = []
    for index in range(first_index, first_index + count):
        doc_id = uuid.uuid4()
        version_id = uuid.uuid4()
        review_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        key = f"loadtest/{run_id}/{doc_id}.pdf"
        docs.append(
            {
                "id": doc_id,
                "version_id": version_id,
                "review_id": review_id,
                "workflow_id": workflow_id,
                "key": key,
                "index": index,
                "queued_at": time.monotonic(),
                "state": "pending",
                "started_at": None,
                "finished_at": None,
            }
        )

    try:
        for doc in docs:
            await asyncio.to_thread(
                s3_client.put_object,
                Bucket=bucket,
                Key=doc["key"],
                Body=pdf_bytes,
                ContentType="application/pdf",
            )
            uploaded_keys.append(doc["key"])

        async with pool.acquire() as db:
            async with db.transaction():
                for doc in docs:
                    doc_id = doc["id"]
                    version_id = doc["version_id"]
                    review_id = doc["review_id"]
                    workflow_id = doc["workflow_id"]
                    index = doc["index"]
                    await db.execute(
                        """
                        INSERT INTO documents (
                            id, organization_id, document_code, name, type,
                            submitted_by, created_at, updated_at
                        ) VALUES ($1, $2, $3, $4, 'client_communications', $5, $6, $6)
                        """,
                        doc_id,
                        organization_id,
                        f"LT-{run_id}-{index:04d}",
                        f"Load test {run_id[:8]}-{index:04d}.pdf",
                        user_id,
                        created_at,
                    )
                    await db.execute(
                        """
                        INSERT INTO document_versions (
                            id, document_id, version_label, uploaded_at, status,
                            s3_bucket, s3_key, extracted_text, file_size_bytes
                        ) VALUES ($1, $2, '1.0', $3, 'processing', $4, $5, NULL, $6)
                        """,
                        version_id,
                        doc_id,
                        created_at,
                        bucket,
                        doc["key"],
                        len(pdf_bytes),
                    )
                    await db.execute(
                        "UPDATE documents SET current_version_id = $1 WHERE id = $2",
                        version_id,
                        doc_id,
                    )
                    await db.execute(
                        """
                        INSERT INTO content_reviews (
                            id, content_type, document_version_id, compliance_status,
                            review_status, created_at, updated_at
                        ) VALUES ($1, 'marketing_material', $2, 'conditional', 'pending', $3, $3)
                        """,
                        review_id,
                        version_id,
                        created_at,
                    )
                    await db.execute(
                        """
                        INSERT INTO workflows (
                            id, review_id, current_stage, assigned_to, assigned_role,
                            created_at, updated_at
                        ) VALUES ($1, $2, 'marketing_review', $3, 'marketing', $4, $4)
                        """,
                        workflow_id,
                        review_id,
                        user_id,
                        created_at,
                    )
                    await db.execute(
                        """
                        INSERT INTO workflow_steps (
                            id, workflow_id, stage, action, comment, previous_stage,
                            step_order, completed_by, completed_at, created_at
                        ) VALUES ($1, $2, 'marketing_review', 'uploaded', NULL, NULL, 1, $3, $4, $4)
                        """,
                        uuid.uuid4(),
                        workflow_id,
                        user_id,
                        created_at,
                    )
    except Exception:
        if uploaded_keys:
            await _delete_s3_keys(bucket, uploaded_keys)
        raise

    for doc in docs:
        doc["queued_at"] = time.monotonic()
    return docs


async def _delete_s3_keys(bucket: str, keys: list[str]) -> None:
    for offset in range(0, len(keys), 1000):
        batch = keys[offset : offset + 1000]
        response = await asyncio.to_thread(
            s3_client.delete_objects,
            Bucket=bucket,
            Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
        )
        errors = response.get("Errors") or []
        if errors:
            raise RuntimeError(f"Failed to remove {len(errors)} synthetic S3 objects.")


async def _refresh_states(pool: asyncpg.Pool, docs: list[dict[str, Any]]) -> None:
    if not docs:
        return
    review_ids = [doc["review_id"] for doc in docs]
    if not review_ids:
        return
    async with pool.acquire() as db:
        events = await db.fetch(
            """
            SELECT review_id, event_type, created_at
            FROM audit_events
            WHERE review_id = ANY($1::uuid[])
              AND event_type IN ('ai_analysis_started', 'ai_analysis_completed', 'ai_analysis_failed')
            ORDER BY created_at
            """,
            review_ids,
        )

    by_review: dict[uuid.UUID, list[asyncpg.Record]] = {}
    for event in events:
        by_review.setdefault(event["review_id"], []).append(event)

    for doc in docs:
        records = by_review.get(doc["review_id"], [])
        starts = [e["created_at"] for e in records if e["event_type"] == "ai_analysis_started"]
        terminals = [e for e in records if e["event_type"] in TERMINAL_EVENTS]
        intervals: list[tuple[datetime, datetime | None]] = []
        active_start = None
        for event in records:
            if event["event_type"] == "ai_analysis_started" and active_start is None:
                active_start = event["created_at"]
            elif event["event_type"] in TERMINAL_EVENTS and active_start is not None:
                intervals.append((active_start, event["created_at"]))
                active_start = None
        if active_start is not None:
            intervals.append((active_start, None))
        doc["analysis_intervals"] = intervals
        if starts:
            doc["started_at"] = starts[0]
        if terminals:
            terminal = terminals[-1]
            doc["state"] = TERMINAL_EVENTS[terminal["event_type"]]
            doc["finished_at"] = terminal["created_at"]


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * pct / 100
    lower = math.floor(index)
    upper = math.ceil(index)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


async def _wait_for_batch(
    pool: asyncpg.Pool,
    docs: list[dict[str, Any]],
    *,
    max_wait_seconds: float,
    drain_timeout_seconds: float,
    poll_interval_seconds: float,
    step: int,
) -> tuple[float, bool]:
    started = time.monotonic()
    deadline = started + max_wait_seconds
    while True:
        await _refresh_states(pool, docs)
        pending = [doc for doc in docs if doc["state"] not in {"completed", "failed"}]
        if not pending:
            elapsed = time.monotonic() - started
            return elapsed, elapsed <= max_wait_seconds
        now = time.monotonic()
        if now >= deadline:
            print(
                f"Step {step}: {len(pending)} document(s) still processing after "
                f"{max_wait_seconds / 60:g} minutes; stopping the ladder and draining queued work.",
                flush=True,
            )
            break
        print(
            f"Step {step}: completed {len(docs) - len(pending)}/{len(docs)}; "
            f"{len(pending)} still processing.",
            flush=True,
        )
        await asyncio.sleep(min(poll_interval_seconds, deadline - now))

    drain_deadline = time.monotonic() + drain_timeout_seconds
    while time.monotonic() < drain_deadline:
        await _refresh_states(pool, docs)
        pending = [doc for doc in docs if doc["state"] not in {"completed", "failed"}]
        if not pending:
            return time.monotonic() - started, False
        await asyncio.sleep(poll_interval_seconds)

    await _refresh_states(pool, docs)
    pending = [doc for doc in docs if doc["state"] not in {"completed", "failed"}]
    if pending:
        print(
            "Drain timed out. Synthetic DB/S3 records are intentionally retained while "
            f"{len(pending)} Celery task(s) may still be active. run_id={docs[0]['run_id']}",
            file=sys.stderr,
            flush=True,
        )
        return time.monotonic() - started, False
    return time.monotonic() - started, False


def _peak_parallel_docs(docs: list[dict[str, Any]]) -> int:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    events: list[tuple[datetime, int]] = []
    for doc in docs:
        for started_at, finished_at in doc.get("analysis_intervals", []):
            finished_at = finished_at or now
            if finished_at <= started_at:
                continue
            events.append((started_at, 1))
            events.append((finished_at, -1))

    active = 0
    peak = 0
    for _, change in sorted(events, key=lambda event: (event[0], event[1])):
        active += change
        peak = max(peak, active)
    return peak


def _step_summary(step: int, docs: list[dict[str, Any]], elapsed: float, within_limit: bool) -> dict[str, Any]:
    completed = [doc for doc in docs if doc["state"] == "completed"]
    failed = [doc for doc in docs if doc["state"] in {"failed", "dispatch_failed"}]
    pending = len(
        [doc for doc in docs if doc["state"] not in {"completed", "failed", "dispatch_failed"}]
    )
    durations = [
        (doc["finished_at"] - doc["started_at"]).total_seconds()
        for doc in completed + failed
        if doc["finished_at"] and doc["started_at"]
    ]
    stable = within_limit and not failed and pending == 0 and len(completed) == len(docs)
    p50 = _percentile(durations, 50)
    p95 = _percentile(durations, 95)
    return {
        "batch_documents": step,
        "completed": len(completed),
        "failed": len(failed),
        "still_processing": pending,
        "completed_within_limit": within_limit,
        "elapsed_seconds": round(elapsed, 2),
        "docs_per_hour": round(len(completed) / elapsed * 3600, 2) if elapsed and completed else 0,
        "analysis_duration_p50_seconds": round(p50, 2) if p50 is not None else None,
        "analysis_duration_p95_seconds": round(p95, 2) if p95 is not None else None,
        "max_observed_parallel_docs": _peak_parallel_docs(docs),
        "stable": stable,
    }


async def _cleanup(
    pool: asyncpg.Pool,
    docs: list[dict[str, Any]],
    bucket: str,
    run_id: str,
) -> None:
    keys = [doc["key"] for doc in docs]
    if keys:
        await _delete_s3_keys(bucket, keys)
    async with pool.acquire() as db:
        if docs:
            ids = [doc["id"] for doc in docs]
            await db.execute("DELETE FROM documents WHERE id = ANY($1::uuid[])", ids)
        await db.execute("DELETE FROM organizations WHERE slug = $1", f"loadtest-{run_id}")
        await db.execute(
            "DELETE FROM user_profiles WHERE cognito_sub = $1",
            f"loadtest:{run_id}",
        )


async def _cleanup_run(pool: asyncpg.Pool, run_id: str) -> None:
    if len(run_id) != 32 or any(char not in "0123456789abcdef" for char in run_id.lower()):
        raise ValueError("--cleanup-run-id must be the 32-character run ID printed by the test.")
    run_id = run_id.lower()
    async with pool.acquire() as db:
        rows = await db.fetch(
            """
            SELECT d.id, dv.s3_bucket, dv.s3_key
            FROM documents d
            LEFT JOIN document_versions dv ON dv.document_id = d.id
            WHERE d.document_code LIKE $1
            """,
            f"LT-{run_id}-%",
        )
    keys_by_bucket: dict[str, list[str]] = {}
    for row in rows:
        if row["s3_bucket"] and row["s3_key"]:
            keys_by_bucket.setdefault(row["s3_bucket"], []).append(row["s3_key"])
    for bucket, keys in keys_by_bucket.items():
        await _delete_s3_keys(bucket, keys)
    async with pool.acquire() as db:
        if rows:
            await db.execute("DELETE FROM documents WHERE id = ANY($1::uuid[])", [row["id"] for row in rows])
        await db.execute("DELETE FROM organizations WHERE slug = $1", f"loadtest-{run_id}")
        await db.execute("DELETE FROM user_profiles WHERE cognito_sub = $1", f"loadtest:{run_id}")
    print(f"Removed {len(rows)} synthetic document(s) and test identity for run_id={run_id}.", flush=True)


async def _run(args: argparse.Namespace) -> int:
    app_env = os.getenv("APP_ENV", "").strip().lower()
    if not app_env or app_env in {"prod", "production"}:
        raise RuntimeError("Worker load tests require APP_ENV explicitly set to a non-production value.")
    if not load_test_stub_enabled():
        raise RuntimeError("The load-test runner requires LOAD_TEST_STUB_LLM=true.")
    assert_stub_allowed()
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is missing from the running application environment.")
    if args.concurrency < 1:
        raise ValueError("--concurrency must be a positive integer.")
    if any(step < 1 for step in args.steps):
        raise ValueError("Every --steps value must be a positive integer.")
    if args.max_wait_minutes <= 0 or args.drain_timeout_minutes <= 0 or args.poll_interval_seconds <= 0:
        raise ValueError("Wait and polling durations must be positive.")

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=4)
    if args.cleanup_run_id:
        try:
            await _cleanup_run(pool, args.cleanup_run_id)
        finally:
            await pool.close()
        return 0

    run_id = uuid.uuid4().hex
    print(
        f"Worker-only load test run_id={run_id}; no HTTP, token, or supplied PDF. "
        f"configured maximum parallel tasks={args.concurrency}; "
        f"stub delay=1.5s per LLM call; batch steps={args.steps}",
        flush=True,
    )
    all_docs: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    stable_parallelism = 0
    exceeded = False
    bucket = (ai_config.AWS_S3_BUCKET or "").strip()
    try:
        organization_id, user_id = await _create_test_owner(pool, run_id)
        pdf_bytes = _synthetic_pdf()

        next_index = 1
        for step in args.steps:
            docs = await _create_batch(
                pool,
                organization_id=organization_id,
                user_id=user_id,
                run_id=run_id,
                first_index=next_index,
                count=step,
                pdf_bytes=pdf_bytes,
            )
            for doc in docs:
                doc["run_id"] = run_id
            all_docs.extend(docs)
            next_index += len(docs)
            queue_error = False
            for doc in docs:
                try:
                    analyze_document_task.delay(str(doc["id"]), str(user_id))
                    doc["queued_at"] = time.monotonic()
                    doc["state"] = "queued"
                except Exception:
                    logger.exception("Could not queue load-test document %s", doc["id"])
                    doc["state"] = "dispatch_failed"
                    queue_error = True
                    break

            queued_docs = [doc for doc in docs if doc["state"] == "queued"]
            if queue_error and queued_docs:
                elapsed, drained = await _wait_for_batch(
                    pool,
                    queued_docs,
                    max_wait_seconds=args.max_wait_minutes * 60,
                    drain_timeout_seconds=args.drain_timeout_minutes * 60,
                    poll_interval_seconds=args.poll_interval_seconds,
                    step=step,
                )
                if not drained:
                    summaries.append(_step_summary(step, docs, elapsed, False))
                    exceeded = True
                    break
            if queue_error:
                summaries.append(_step_summary(step, docs, 0, False))
                break

            elapsed, within_limit = await _wait_for_batch(
                pool,
                docs,
                max_wait_seconds=args.max_wait_minutes * 60,
                drain_timeout_seconds=args.drain_timeout_minutes * 60,
                poll_interval_seconds=args.poll_interval_seconds,
                step=step,
            )
            summary = _step_summary(step, docs, elapsed, within_limit)
            summaries.append(summary)
            print(json.dumps(summary, indent=2), flush=True)
            if summary["stable"]:
                stable_parallelism = max(stable_parallelism, summary["max_observed_parallel_docs"])
            if summary["still_processing"]:
                exceeded = True
                break
            if not summary["stable"]:
                break

        if exceeded:
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            (REPORT_DIR / f"worker-capacity-{run_id}.json").write_text(
                json.dumps(
                    {
                        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                        "run_id": run_id,
                        "mode": "direct Celery document-analysis worker capacity",
                        "configured_max_parallel_tasks": args.concurrency,
                        "llm_mode": "stub",
                        "steps": summaries,
                        "max_stable_parallel_docs": stable_parallelism,
                        "cleanup": "deferred because Celery work may still be active",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            return 2

        report = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "mode": "direct Celery document-analysis worker capacity",
            "configured_max_parallel_tasks": args.concurrency,
            "llm_mode": "stub",
            "stub_delay_seconds_per_call": 1.5,
            "max_stable_parallel_docs": stable_parallelism,
            "steps": summaries,
        }
        await _cleanup(pool, all_docs, bucket, run_id)
        report["cleanup"] = "synthetic database rows and S3 files removed"
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = REPORT_DIR / f"worker-capacity-{run_id}.json"
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(
            f"Maximum observed parallel documents in a stable batch: {stable_parallelism} "
            f"(configured limit {args.concurrency})",
            flush=True,
        )
        print(f"Report: {report_path}", flush=True)
        print("Synthetic database records and S3 files cleaned up.", flush=True)
        return 0
    finally:
        await pool.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args()
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        logger.error("Interrupted. Do not disable the worker stub until queued test jobs have drained.")
        return 130
    except Exception:
        logger.exception("Worker capacity load test failed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
