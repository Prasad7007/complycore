#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

COMPOSE=(docker compose -f docker-compose.worker-loadtest.yml)
WORKER_COUNTS=(1 2 3)
CONCURRENCY_LEVELS=(1 2)
STEPS=(8 12 16)
MIN_AVAILABLE_MB=1536
WORKER_MEMORY_BUDGET_MB=3072
while [[ $# -gt 0 ]]; do
  case "$1" in
    --workers)
      shift
      WORKER_COUNTS=()
      while [[ $# -gt 0 && "$1" != --* ]]; do
        WORKER_COUNTS+=("$1")
        shift
      done
      if [[ ${#WORKER_COUNTS[@]} -eq 0 ]]; then
        echo "Usage: $0 [--workers COUNT [COUNT ...]] [--concurrency COUNT [COUNT ...]] [--steps DOCS [DOCS ...]] [--min-available-mb MB] [--worker-memory-budget-mb MB]" >&2
        exit 2
      fi
      ;;
    --concurrency)
      shift
      CONCURRENCY_LEVELS=()
      while [[ $# -gt 0 && "$1" != --* ]]; do
        CONCURRENCY_LEVELS+=("$1")
        shift
      done
      if [[ ${#CONCURRENCY_LEVELS[@]} -eq 0 ]]; then
        echo "Usage: $0 [--workers COUNT [COUNT ...]] [--concurrency COUNT [COUNT ...]] [--steps DOCS [DOCS ...]] [--min-available-mb MB] [--worker-memory-budget-mb MB]" >&2
        exit 2
      fi
      ;;
    --steps)
      shift
      STEPS=()
      while [[ $# -gt 0 && "$1" != --* ]]; do
        STEPS+=("$1")
        shift
      done
      if [[ ${#STEPS[@]} -eq 0 ]]; then
        echo "Usage: $0 [--workers COUNT [COUNT ...]] [--concurrency COUNT [COUNT ...]] [--steps DOCS [DOCS ...]] [--min-available-mb MB] [--worker-memory-budget-mb MB]" >&2
        exit 2
      fi
      ;;
    --min-available-mb)
      shift
      if [[ $# -eq 0 || ! "$1" =~ ^[1-9][0-9]*$ ]]; then
        echo "--min-available-mb requires a positive integer." >&2
        exit 2
      fi
      MIN_AVAILABLE_MB="$1"
      shift
      ;;
    --worker-memory-budget-mb)
      shift
      if [[ $# -eq 0 || ! "$1" =~ ^[1-9][0-9]*$ ]]; then
        echo "--worker-memory-budget-mb requires a positive integer." >&2
        exit 2
      fi
      WORKER_MEMORY_BUDGET_MB="$1"
      shift
      ;;
    -*)
      echo "Unknown option: $1" >&2
      echo "Usage: $0 [--workers COUNT [COUNT ...]] [--concurrency COUNT [COUNT ...]] [--steps DOCS [DOCS ...]] [--min-available-mb MB] [--worker-memory-budget-mb MB]" >&2
      exit 2
      ;;
    *)
      # Keep the previous positional form, where arguments selected batch sizes.
      STEPS=("$@")
      break
      ;;
  esac
done

previous_workers=0
for workers in "${WORKER_COUNTS[@]}"; do
  if [[ ! "${workers}" =~ ^[1-9][0-9]*$ ]] || ((workers <= previous_workers)); then
    echo "Worker counts must be positive integers in strictly increasing order." >&2
    exit 2
  fi
  previous_workers="${workers}"
done
previous_concurrency=0
for concurrency in "${CONCURRENCY_LEVELS[@]}"; do
  if [[ ! "${concurrency}" =~ ^[1-9][0-9]*$ ]] || ((concurrency <= previous_concurrency)); then
    echo "Concurrency values must be positive integers in strictly increasing order." >&2
    exit 2
  fi
  previous_concurrency="${concurrency}"
done
for step in "${STEPS[@]}"; do
  if [[ ! "${step}" =~ ^[1-9][0-9]*$ ]]; then
    echo "Document batch sizes must be positive integers." >&2
    exit 2
  fi
done
largest_step=0
for step in "${STEPS[@]}"; do
  if ((step > largest_step)); then
    largest_step="${step}"
  fi
done
if ((previous_workers * previous_concurrency > largest_step)); then
  echo "The largest document batch must be at least the highest total task-slot count." >&2
  exit 2
fi
if [[ ! -r /proc/meminfo ]]; then
  echo "Cannot read /proc/meminfo to enforce the worker memory safety check." >&2
  exit 1
fi

available_memory_mb() {
  awk '/^MemAvailable:/ { print int($2 / 1024); found=1 } END { if (!found) exit 1 }' /proc/meminfo
}

mkdir -p loadtest/reports

"${COMPOSE[@]}" build loadtest-worker worker-capacity
"${COMPOSE[@]}" up -d loadtest-db loadtest-redis loadtest-s3mock

echo "Creating the isolated S3Mock bucket..."
"${COMPOSE[@]}" run --rm worker-capacity \
  python -c "from apis.services.ai.core.s3_client import s3_client; bucket='complycore-loadtest'; buckets={item['Name'] for item in s3_client.list_buckets().get('Buckets', [])}; s3_client.create_bucket(Bucket=bucket) if bucket not in buckets else print(f'S3Mock bucket {bucket} already exists.')"

echo "Initializing the isolated load-test database..."
"${COMPOSE[@]}" run --rm worker-capacity python init_database.py

status=0
current_workers=0
last_tested_workers=0
last_tested_slots=0
safety_stop=0
for workers in "${WORKER_COUNTS[@]}"; do
  if ((workers > current_workers)); then
    required_memory_mb=$((MIN_AVAILABLE_MB + (workers - current_workers) * WORKER_MEMORY_BUDGET_MB))
    available_mb="$(available_memory_mb)"
    if ((available_mb < required_memory_mb)); then
      echo "Memory safety stop: ${available_mb} MiB available; need at least ${required_memory_mb} MiB before adding worker container(s)." >&2
      safety_stop=1
      break
    fi
  fi

  for concurrency in "${CONCURRENCY_LEVELS[@]}"; do
    total_slots=$((workers * concurrency))
    echo "Benchmarking ${workers} worker container(s) x concurrency ${concurrency} = ${total_slots} task slot(s); batches=${STEPS[*]}"
    WORKER_CONCURRENCY="${concurrency}" "${COMPOSE[@]}" up -d --force-recreate \
      --scale "loadtest-worker=${workers}" loadtest-worker
    current_workers="${workers}"

    available_mb="$(available_memory_mb)"
    if ((available_mb < MIN_AVAILABLE_MB)); then
      echo "Memory safety stop after starting workers: ${available_mb} MiB available (minimum ${MIN_AVAILABLE_MB} MiB)." >&2
      safety_stop=1
      break
    fi

    running_workers="$("${COMPOSE[@]}" ps --status running -q loadtest-worker | wc -l)"
    if ((running_workers != workers)); then
      echo "Expected ${workers} running worker containers, found ${running_workers}; stopping the sweep." >&2
      status=1
      break
    fi

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
      echo "Worker did not confirm the LLM stub at ${workers} container(s), concurrency=${concurrency}; refusing to enqueue load." >&2
      status=1
      break
    fi

    set +e
    "${COMPOSE[@]}" run --rm worker-capacity \
      python /loadtest/worker_capacity.py --workers "${workers}" --concurrency "${concurrency}" --steps "${STEPS[@]}"
    status=$?
    set -e

    if [[ "${status}" != "0" ]]; then
      echo "Capacity test failed at ${workers} worker(s) x concurrency ${concurrency}; inspect report and queue before continuing." >&2
      break
    fi
    last_tested_workers="${workers}"
    last_tested_slots="${total_slots}"
    available_mb="$(available_memory_mb)"
    if ((available_mb < MIN_AVAILABLE_MB)); then
      echo "Memory safety stop after test: ${available_mb} MiB available (minimum ${MIN_AVAILABLE_MB} MiB)." >&2
      safety_stop=1
      break
    fi
  done

  if [[ "${status}" != "0" || "${safety_stop}" == "1" ]]; then
    break
  fi
done

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

echo "Highest fully tested configuration: ${last_tested_workers} worker container(s), ${last_tested_slots} total task slot(s)."
if [[ "${safety_stop}" == "1" ]]; then
  echo "Sweep stopped safely by the host-memory guard; this is not proof of the machine's absolute maximum."
fi

exit "${status}"
