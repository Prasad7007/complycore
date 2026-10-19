#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

COMPOSE=(docker compose --profile worker-loadtest -f docker-compose.yml -f docker-compose.worker-loadtest.yml)
BASE_COMPOSE=(docker compose -f docker-compose.yml)
if [[ $# -eq 0 ]]; then
  STEPS=(2 4 6 8)
else
  STEPS=("$@")
fi
KEEP_STUB_WORKER=0

if [[ ! -f "AI Compliance/.env.docker" ]]; then
  echo "Missing AI Compliance/.env.docker; start/configure the existing app stack first." >&2
  exit 1
fi

worker_id="$("${BASE_COMPOSE[@]}" ps -q worker)"
if [[ -z "${worker_id}" ]] || [[ "$(docker inspect -f '{{.State.Running}}' "${worker_id}")" != "true" ]]; then
  echo "The existing worker must be running before the benchmark starts." >&2
  exit 1
fi

app_env="$("${BASE_COMPOSE[@]}" exec -T worker python -c 'import os; print(os.getenv("APP_ENV", "").strip().lower())')"
if [[ -z "${app_env}" ]] || [[ "${app_env}" == "production" || "${app_env}" == "prod" ]]; then
  echo "Refusing to enable the LLM stub: APP_ENV must be explicitly set to a non-production value." >&2
  exit 1
fi

restore_worker() {
  status=$?
  trap - EXIT
  if [[ "${KEEP_STUB_WORKER}" == "1" ]]; then
    echo "Automatic worker restore skipped to avoid real-provider calls from possibly queued tasks." >&2
    echo "Check the Celery queue and worker state before restoring normal configuration." >&2
    echo "After the queue drains, restore normal worker configuration with:" >&2
    echo "  docker compose up -d --no-deps --force-recreate worker" >&2
    exit "${status}"
  fi
  echo "Restoring the worker without the temporary load-test Compose override..."
  if ! "${BASE_COMPOSE[@]}" up -d --no-deps --force-recreate worker; then
    echo "Could not restore the worker automatically. Check its environment before continuing." >&2
    exit 1
  fi
  exit "${status}"
}
mkdir -p loadtest/reports
"${COMPOSE[@]}" build worker worker-capacity
trap restore_worker EXIT
"${COMPOSE[@]}" up -d --no-deps --force-recreate worker

stub_active=0
for _ in $(seq 1 30); do
  if "${COMPOSE[@]}" logs --no-color --since=2m worker 2>&1 | grep -Fq "LOAD_TEST_STUB_LLM ACTIVE"; then
    stub_active=1
    break
  fi
  sleep 2
done
if [[ "${stub_active}" != "1" ]]; then
  echo "Worker did not confirm the LLM stub in its startup logs; refusing to enqueue load." >&2
  exit 1
fi

set +e
"${COMPOSE[@]}" run --rm --no-deps worker-capacity --steps "${STEPS[@]}"
status=$?
set -e
if [[ "${status}" != "0" ]]; then
  KEEP_STUB_WORKER=1
fi
exit "${status}"
