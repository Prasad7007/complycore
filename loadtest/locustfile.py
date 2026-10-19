"""
Locust harness for UAT infra benchmarking.

Upload → poll GET /orgs/{slug}/documents/{id}/review until ai_analysis_state is terminal.

Run (from repo root):
  cd loadtest && pip install -r requirements.txt
  export $(grep -v '^#' .env | xargs)   # or set vars manually
  locust -f locustfile.py --host="$UAT_BASE_URL"
"""

from __future__ import annotations

import time
import uuid

from locust import HttpUser, between, events, task

from config import (
    analysis_timeout_sec,
    auth_headers,
    document_type,
    fixture_pdf_path,
    org_slug,
    poll_interval_sec,
    upload_routing,
)
from stats import RUN_STATS, print_summary, write_summary

TERMINAL_AI_STATES = frozenset({"completed", "failed"})


def _upload_path() -> str:
    return f"/orgs/{org_slug()}/documents/upload"


def _review_path(doc_id: str) -> str:
    return f"/orgs/{org_slug()}/documents/{doc_id}/review"


@events.init.add_listener
def on_locust_init(environment, **_kwargs):
    pdf = fixture_pdf_path()
    if not pdf.is_file():
        print(
            f"WARNING: FIXTURE_PDF_PATH not found: {pdf}\n"
            "Upload tasks will fail until you copy a PDF to loadtest/fixtures/ or set FIXTURE_PDF_PATH."
        )
    if not auth_headers():
        print("WARNING: AUTH_TOKEN is empty — requests will be unauthorized.")


@events.test_start.add_listener
def on_test_start(environment, **_kwargs):
    users = None
    runner = getattr(environment, "runner", None)
    if runner is not None:
        users = getattr(runner, "target_user_count", None) or getattr(runner, "user_count", None)
    RUN_STATS.mark_test_start(users)


@events.test_stop.add_listener
def on_test_stop(environment, **_kwargs):
    if write_summary(environment):
        print_summary(environment)


@events.quitting.add_listener
def on_quitting(environment, **_kwargs):
    if RUN_STATS.test_started_at is not None:
        if write_summary(environment):
            print_summary(environment)


class DocumentAnalysisUser(HttpUser):
    """One virtual user: upload a document and wait for AI analysis to finish."""

    wait_time = between(2, 5)

    def on_start(self):
        headers = auth_headers()
        if headers:
            self.client.headers.update(headers)
        with self.client.get("/users/me", name="/users/me", catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"auth check failed: HTTP {resp.status_code}")

    @task
    def upload_and_wait_for_analysis(self):
        pdf_path = fixture_pdf_path()
        if not pdf_path.is_file():
            raise RuntimeError(f"Missing fixture PDF: {pdf_path}")

        unique = uuid.uuid4().hex[:8]
        doc_name = f"locust-load-{unique}"
        upload_started = time.perf_counter()

        with open(pdf_path, "rb") as f:
            files = {"file": (pdf_path.name, f, "application/pdf")}
            data = {
                "document_name": doc_name,
                "document_type": document_type(),
                # Skip SME queue — same path as in-app "direct to marketing" so analysis starts.
                "routing": upload_routing(),
            }
            with self.client.post(
                _upload_path(),
                data=data,
                files=files,
                name="POST /documents/upload",
                catch_response=True,
            ) as resp:
                if resp.status_code not in (200, 201):
                    resp.failure(f"upload HTTP {resp.status_code}: {resp.text[:500]}")
                    RUN_STATS.record_upload_failed()
                    return
                try:
                    body = resp.json()
                    doc_id = body["id"]
                except Exception as exc:
                    resp.failure(f"upload response missing id: {exc}")
                    RUN_STATS.record_upload_failed()
                    return
                resp.success()

        RUN_STATS.record_upload_success()

        upload_elapsed = time.perf_counter() - upload_started
        events.request.fire(
            request_type="CUSTOM",
            name="upload_to_doc_id",
            response_time=upload_elapsed * 1000,
            response_length=0,
            exception=None,
            context={},
        )

        deadline = time.perf_counter() + analysis_timeout_sec()
        analysis_start = time.perf_counter()
        final_state = "timeout"

        while time.perf_counter() < deadline:
            with self.client.get(
                _review_path(doc_id),
                name="GET /documents/{id}/review",
                catch_response=True,
            ) as poll_resp:
                if poll_resp.status_code != 200:
                    poll_resp.failure(f"review HTTP {poll_resp.status_code}")
                    time.sleep(poll_interval_sec())
                    continue
                try:
                    review = poll_resp.json()
                    state = review.get("ai_analysis_state") or "unknown"
                except Exception as exc:
                    poll_resp.failure(str(exc))
                    time.sleep(poll_interval_sec())
                    continue

                if state in TERMINAL_AI_STATES:
                    final_state = state
                    poll_resp.success()
                    break
                poll_resp.success()

            time.sleep(poll_interval_sec())

        analysis_elapsed = time.perf_counter() - analysis_start
        RUN_STATS.record_analysis_end(final_state, analysis_elapsed)

        exc = None if final_state in TERMINAL_AI_STATES else Exception(f"timeout ai_state={final_state}")

        events.request.fire(
            request_type="CUSTOM",
            name=f"analysis_complete ({final_state})",
            response_time=analysis_elapsed * 1000,
            response_length=0,
            exception=exc,
            context={"doc_id": doc_id},
        )
