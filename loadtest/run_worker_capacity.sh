#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

COMPOSE=(docker compose -f docker-compose.worker-loadtest.yml)
if [[ $# -eq 0 ]]; then
  STEPS=(2 4 6 8)
else
  STEPS=("$@")
fi

mkdir -p loadtest/reports

"${COMPOSE[@]}" build loadtest-worker worker-capacity
"${COMPOSE[@]}" up -d loadtest-db loadtest-redis loadtest-s3mock

echo "Creating the isolated S3Mock bucket..."
"${COMPOSE[@]}" run --rm worker-capacity \
  python -c "from apis.services.ai.core.s3_client import s3_client; bucket='complycore-loadtest'; buckets={item['Name'] for item in s3_client.list_buckets().get('Buckets', [])}; s3_client.create_bucket(Bucket=bucket) if bucket not in buckets else print(f'S3Mock bucket {bucket} already exists.')"

echo "Initializing the isolated load-test database..."
"${COMPOSE[@]}" run --rm worker-capacity python init_database.py

"${COMPOSE[@]}" up -d loadtest-worker

stub_active=0
for _ in $(seq 1 30); do
  if "${COMPOSE[@]}" logs --no-color --since=2m loadtest-worker 2>&1 \
    | grep -Fq "LOAD_TEST_STUB_LLM ACTIVE"; then
    stub_active=1
    break
  fi
  sleep 2
done
if [[ "${stub_active}" != "1" ]]; then
  echo "Worker did not confirm the LLM stub in its startup logs; refusing to enqueue load." >&2
  echo "The isolated stack is left running for inspection; no real AWS LLM credentials are configured." >&2
  exit 1
fi

set +e
"${COMPOSE[@]}" run --rm worker-capacity \
  python /loadtest/worker_capacity.py --steps "${STEPS[@]}"
status=$?
set -e

if [[ "${status}" == "0" ]]; then
  "${COMPOSE[@]}" down
  echo "Isolated test containers stopped and removed. Results remain in loadtest/reports/."
else
  echo "Test did not complete cleanly. The isolated services are left running for inspection/recovery." >&2
  echo "Check the worker queue before cleanup. After it drains, clean records with the run ID:" >&2
  echo "  docker compose -f docker-compose.worker-loadtest.yml run --rm worker-capacity python /loadtest/worker_capacity.py --cleanup-run-id <run-id>" >&2
  echo "Then remove the isolated stack with:" >&2
  echo "  docker compose -f docker-compose.worker-loadtest.yml down" >&2
fi

exit "${status}"
