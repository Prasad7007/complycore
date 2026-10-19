#!/usr/bin/env bash
# Find max stable concurrent scans on current infra (stepped Locust runs).
# Prereqs: stub LLM on worker, loadtest/.env, sample.pdf, compliance-loadtest image.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

# Default 12m/step: audit_events p95 analysis ~200s (~3.3 min) on UAT — allows one full
# concurrent wave + a second cycle per user with margin (override via LOADTEST_LADDER_RUN_TIME).
RUN_TIME="${LOADTEST_LADDER_RUN_TIME:-12m}"
SPAWN_RATE="${LOADTEST_LADDER_SPAWN_RATE:-1}"
MIN_COMPLETION_PCT="${LOADTEST_LADDER_MIN_COMPLETION_PCT:-95}"
USER_STEPS="${LOADTEST_LADDER_USERS:-2 4 6 8 10 12}"
REPORT_DIR="${ROOT}/loadtest/reports"
SUMMARY="${REPORT_DIR}/last-run-summary.json"
THRESHOLD_UPLOAD_FAILS="${LOADTEST_LADDER_MAX_UPLOAD_FAILS:-0}"

if [[ ! -f loadtest/.env ]]; then
  echo "Missing loadtest/.env — copy from loadtest/.env.example"
  exit 1
fi

if [[ ! -f loadtest/fixtures/sample.pdf ]]; then
  echo "Missing loadtest/fixtures/sample.pdf"
  exit 1
fi

docker build -t compliance-loadtest ./loadtest

echo "=== Capacity ladder: steps=${USER_STEPS} run_time=${RUN_TIME} min_completion=${MIN_COMPLETION_PCT}% ==="
"${ROOT}/loadtest/snapshot_env.sh" || true

MAX_STABLE=""
LADDER_LOG="${REPORT_DIR}/capacity-ladder-$(date +%Y%m%d-%H%M).log"
: >"${LADDER_LOG}"

for N in ${USER_STEPS}; do
  STAMP="$(date +%Y%m%d-%H%M%S)"
  echo "--- Run: users=${N} ---" | tee -a "${LADDER_LOG}"

  docker run --rm --network host \
    -v "${ROOT}/loadtest/fixtures:/loadtest/fixtures:ro" \
    -v "${REPORT_DIR}:/loadtest/reports" \
    --env-file loadtest/.env \
    -e UAT_BASE_URL=http://127.0.0.1:8052/api/v1 \
    -e FIXTURE_PDF_PATH=/loadtest/fixtures/sample.pdf \
    -e LOADTEST_REPORT_DIR=/loadtest/reports \
    compliance-loadtest \
    locust -f locustfile.py --host=http://127.0.0.1:8052/api/v1 \
    --headless --users "${N}" --spawn-rate "${SPAWN_RATE}" --run-time "${RUN_TIME}" \
    --csv="/loadtest/reports/ladder-${STAMP}-u${N}" \
    --html="/loadtest/reports/ladder-${STAMP}-u${N}.html" \
    2>&1 | tee -a "${LADDER_LOG}"

  if [[ ! -f "${SUMMARY}" ]]; then
    echo "No ${SUMMARY} after users=${N}; stopping ladder." | tee -a "${LADDER_LOG}"
    break
  fi

  read -r COMPLETED FAILED TIMEOUT IN_FLIGHT UP_FAIL RATE <<<"$(python3 - "${SUMMARY}" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    s = json.load(f)
rate = s.get("analysis_completion_rate_pct")
print(
    s.get("analysis_completed", 0),
    s.get("analysis_failed", 0),
    s.get("analysis_timeout", 0),
    s.get("analysis_in_flight_at_stop", 0),
    s.get("uploads_failed", 0),
    rate if rate is not None else -1,
)
PY
)"

  echo "users=${N} completed=${COMPLETED} failed=${FAILED} timeout=${TIMEOUT} in_flight=${IN_FLIGHT} upload_fail=${UP_FAIL} completion_pct=${RATE}" | tee -a "${LADDER_LOG}"

  OK=1
  if [[ "${UP_FAIL}" -gt "${THRESHOLD_UPLOAD_FAILS}" ]]; then OK=0; fi
  if [[ "${FAILED}" -gt 0 ]] || [[ "${TIMEOUT}" -gt 0 ]]; then OK=0; fi
  if [[ "${RATE}" == "-1" ]] || [[ "${RATE}" -lt "${MIN_COMPLETION_PCT}" ]]; then OK=0; fi
  if [[ "${IN_FLIGHT}" -gt 0 ]]; then
    echo "Warning: ${IN_FLIGHT} analyses still in-flight — run-time may be too short for users=${N}" | tee -a "${LADDER_LOG}"
    OK=0
  fi

  if [[ "${OK}" -eq 1 ]]; then
    MAX_STABLE="${N}"
  else
    echo "Stopping ladder: users=${N} did not meet stability criteria." | tee -a "${LADDER_LOG}"
    break
  fi
done

RESULT="${REPORT_DIR}/capacity-ladder-result.json"
python3 - <<PY
import json
from datetime import datetime, timezone
out = {
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "max_stable_concurrent_scans": "${MAX_STABLE}" or None,
    "interpretation": "Highest --users step where completion >= ${MIN_COMPLETION_PCT}%, no failed/timeout analyses, no upload failures, and zero in-flight at stop.",
    "ladder_log": "${LADDER_LOG}",
}
with open("${RESULT}", "w") as f:
    json.dump(out, f, indent=2)
    f.write("\n")
print(json.dumps(out, indent=2))
PY

echo ""
echo "========== CAPACITY LADDER RESULT =========="
if [[ -n "${MAX_STABLE}" ]]; then
  echo "Max stable concurrent scans (current infra): ${MAX_STABLE}"
else
  echo "No step passed stability checks — try longer LOADTEST_LADDER_RUN_TIME or fix failures."
fi
echo "Details: ${RESULT}"
echo "==========================================="
