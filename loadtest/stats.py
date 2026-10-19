"""Thread-safe run counters and end-of-test summary for Locust."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import api_base_url, org_slug, report_dir


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


@dataclass
class RunStats:
    lock: threading.Lock = field(default_factory=threading.Lock)
    test_started_at: float | None = None
    configured_users: int | None = None

    uploads_success: int = 0
    uploads_failed: int = 0

    analysis_completed: int = 0
    analysis_failed: int = 0
    analysis_timeout: int = 0
    analysis_in_flight: int = 0

    analysis_durations_sec: list[float] = field(default_factory=list)

    def mark_test_start(self, configured_users: int | None) -> None:
        with self.lock:
            self.test_started_at = time.perf_counter()
            self.configured_users = configured_users

    def record_upload_success(self) -> None:
        with self.lock:
            self.uploads_success += 1
            self.analysis_in_flight += 1

    def record_upload_failed(self) -> None:
        with self.lock:
            self.uploads_failed += 1

    def record_analysis_end(self, final_state: str, duration_sec: float) -> None:
        with self.lock:
            if self.analysis_in_flight > 0:
                self.analysis_in_flight -= 1
            self.analysis_durations_sec.append(duration_sec)
            if final_state == "completed":
                self.analysis_completed += 1
            elif final_state == "failed":
                self.analysis_failed += 1
            else:
                self.analysis_timeout += 1

    def snapshot(self, environment: Any | None = None) -> dict[str, Any]:
        with self.lock:
            uploads_ok = self.uploads_success
            uploads_fail = self.uploads_failed
            completed = self.analysis_completed
            failed = self.analysis_failed
            timeout = self.analysis_timeout
            in_flight = self.analysis_in_flight
            durations = list(self.analysis_durations_sec)
            started = self.test_started_at
            users = self.configured_users

        wall_sec = (time.perf_counter() - started) if started else 0.0
        finished = completed + failed + timeout
        completion_rate = (100.0 * completed / finished) if finished else None

        sorted_d = sorted(durations)
        p50 = _percentile(sorted_d, 50)
        p95 = _percentile(sorted_d, 95)

        docs_per_hour = (completed / wall_sec * 3600.0) if wall_sec > 0 and completed else None

        locust_fail_ratio = None
        locust_total_requests = None
        if environment is not None and getattr(environment, "stats", None):
            total = environment.stats.total
            locust_total_requests = total.num_requests
            locust_fail_ratio = total.fail_ratio

        return {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "uat_base_url": api_base_url(),
            "org_slug": org_slug(),
            "configured_concurrent_users": users,
            "wall_clock_sec": round(wall_sec, 2),
            "uploads_success": uploads_ok,
            "uploads_failed": uploads_fail,
            "analysis_completed": completed,
            "analysis_failed": failed,
            "analysis_timeout": timeout,
            "analysis_in_flight_at_stop": in_flight,
            "analysis_finished_total": finished,
            "analysis_completion_rate_pct": round(completion_rate, 2) if completion_rate is not None else None,
            "analysis_duration_sec_p50": round(p50, 2) if p50 is not None else None,
            "analysis_duration_sec_p95": round(p95, 2) if p95 is not None else None,
            "docs_per_hour_completed": round(docs_per_hour, 2) if docs_per_hour is not None else None,
            "locust_total_requests": locust_total_requests,
            "locust_fail_ratio": locust_fail_ratio,
            "interpretation": {
                "concurrent_scans": (
                    "Each Locust user = one upload + wait until scan completes (not passive browsing)."
                ),
                "in_flight_at_stop": (
                    "Analyses still running when the run ended (--run-time or Ctrl+C); "
                    "not counted as timeout unless the poll loop timed out."
                ),
            },
        }


RUN_STATS = RunStats()
_summary_written = False
_summary_lock = threading.Lock()


def write_summary(environment: Any | None = None) -> Path | None:
    global _summary_written
    with _summary_lock:
        if _summary_written:
            return None
        _summary_written = True
    out_dir = report_dir()
    payload = RUN_STATS.snapshot(environment)

    latest = out_dir / "last-run-summary.json"
    latest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    stamped = out_dir / f"run-summary-{stamp}.json"
    stamped.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    return latest


def print_summary(environment: Any | None = None) -> None:
    s = RUN_STATS.snapshot(environment)
    lines = [
        "",
        "=" * 60,
        "LOAD TEST SUMMARY",
        "=" * 60,
        f"  UAT base URL:              {s['uat_base_url']}",
        f"  Org slug:                  {s['org_slug']}",
        f"  Configured concurrent users: {s['configured_concurrent_users']}",
        f"  Wall clock (sec):          {s['wall_clock_sec']}",
        "",
        f"  Uploads OK / failed:       {s['uploads_success']} / {s['uploads_failed']}",
        f"  Analysis completed:        {s['analysis_completed']}",
        f"  Analysis failed:           {s['analysis_failed']}",
        f"  Analysis timeout:          {s['analysis_timeout']}",
        f"  In-flight at stop:         {s['analysis_in_flight_at_stop']}",
        f"  Completion rate:           {s['analysis_completion_rate_pct']}%",
        f"  Analysis p50 / p95 (sec):  {s['analysis_duration_sec_p50']} / {s['analysis_duration_sec_p95']}",
        f"  Docs/hour (completed):     {s['docs_per_hour_completed']}",
        "",
        f"  Locust requests / fail%:   {s['locust_total_requests']} / {s['locust_fail_ratio']}",
        "=" * 60,
        f"  JSON: {report_dir() / 'last-run-summary.json'}",
        "=" * 60,
        "",
    ]
    print("\n".join(lines), flush=True)
