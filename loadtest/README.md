# UAT infrastructure load test (Locust)

Measures end-to-end document throughput: **upload → Celery → Docling → pipeline (stub LLM in UAT) → Postgres**.

## EC2 worker capacity (fully local; no secrets, auth, or supplied PDF)

Use this mode to measure document-analysis worker capacity on EC2. It runs an isolated test stack containing PostgreSQL, Redis, MinIO (local S3-compatible storage), and a worker. It does not use the normal application stack, AWS resources, credentials, API auth, a `loadtest/.env`, or a supplied PDF. It does not measure HTTP upload/auth capacity.

The runner initializes a fresh local test database, creates a synthetic test organization/member and a small PDF, uploads it to the local MinIO container, and dispatches analysis directly to Celery. The LLM stub is always enabled and uses a fixed 1.5-second delay per call. On successful completion, generated rows, local S3 objects, and the isolated stack are removed; the JSON report remains under `loadtest/reports/`.

From the repo root on EC2:

```bash
# Defaults to 2, 4, 6, and 8 documents dispatched together.
bash loadtest/run_worker_capacity.sh

# Or choose batch sizes:
bash loadtest/run_worker_capacity.sh 2 4 6 8 10
```

No `.env` file or pre-existing application/database/S3 stack is required. Docker and Compose are the only host prerequisites. The test uses the existing worker Dockerfile, with the fake LLM guaranteed on for the isolated worker. Results are written to `loadtest/reports/worker-capacity-<run-id>.json`.

If the run exits nonzero, the isolated services are left running, and there are no real-provider credentials configured. Inspect the run ID and worker logs, wait for any queued jobs to finish, then remove the test data and isolated containers:

```bash
docker compose -f docker-compose.worker-loadtest.yml run --rm worker-capacity \
  python /loadtest/worker_capacity.py --cleanup-run-id <run-id>
docker compose -f docker-compose.worker-loadtest.yml down
```

This isolated stack is independent of production data. It exercises document analysis and its LLM stub, not HTTP uploads, authentication, or the upload-time classification task.

## 1. Enable stub LLM on UAT worker only

In the worker environment (e.g. `AI Compliance/.env.docker` on the server), **not** in production:

```bash
LOAD_TEST_STUB_LLM=true
# Pick one delay mode:
LOAD_TEST_STUB_LLM_DELAY_SEC=1.5
# or one sleep per document (closer to prod wall-clock if you measured a single real run):
# LOAD_TEST_STUB_LLM_DELAY_PER_DOC_SEC=120
```

Restart the worker. Logs must show: `LOAD_TEST_STUB_LLM ACTIVE`.

Calibrate delay without Langfuse: run **one** real analysis on UAT (stub off), note wall-clock time, then set `LOAD_TEST_STUB_LLM_DELAY_PER_DOC_SEC` to that value.

## 2. Configure

```bash
cp loadtest/.env.example loadtest/.env
# Edit: AUTH_TOKEN, ORG_SLUG, UAT_BASE_URL, FIXTURE_PDF_PATH
```

Copy a representative PDF to `loadtest/fixtures/` (e.g. `sample.pdf`).

**No Python on EC2 is fine.** The app stub runs inside the **worker** container via `AI Compliance/.env.docker`. Locust is only the HTTP client — run it from your laptop **or** from a small Docker container on EC2 (do **not** `docker exec` into the worker for Locust; that would skew CPU/memory on the box you are measuring).

### Option A — Laptop → UAT URL

Install Python locally, or use Docker:

```bash
cd loadtest && pip install -r requirements.txt
```

Set `UAT_BASE_URL` to the public UAT HTTPS URL.

### Option B — EC2, everything via Docker (recommended if no host Python)

From the **repo root** on the server (after `git pull`):

```bash
# 1) Stub + restart worker (same compose you already use)
#    Add LOAD_TEST_STUB_LLM=true to AI Compliance/.env.docker, then:
docker compose restart worker
docker compose logs worker | grep LOAD_TEST_STUB_LLM

# 2) One-off Locust image (host network → API on localhost:8052)
docker build -t compliance-loadtest ./loadtest
docker run --rm -it --network host \
  -v "$(pwd)/loadtest/fixtures:/loadtest/fixtures:ro" \
  -v "$(pwd)/loadtest/reports:/loadtest/reports" \
  --env-file loadtest/.env \
  -e UAT_BASE_URL=http://127.0.0.1:8052/api/v1 \
  -e FIXTURE_PDF_PATH=/loadtest/fixtures/sample.pdf \
  -p 8089:8089 \
  compliance-loadtest \
  locust -f locustfile.py --host=http://127.0.0.1:8052/api/v1
```

Or attach to the **compose network** (no host networking):

```bash
docker compose --profile loadtest -f docker-compose.yml -f docker-compose.loadtest.yml run --rm --service-ports loadtest
```

In `loadtest/.env` use `UAT_BASE_URL=http://api:8052/api/v1` and `FIXTURE_PDF_PATH=/loadtest/fixtures/sample.pdf`.

Headless on EC2 (no UI):

```bash
docker run --rm --network host \
  -v "$(pwd)/loadtest/fixtures:/loadtest/fixtures:ro" \
  -v "$(pwd)/loadtest/reports:/loadtest/reports" \
  --env-file loadtest/.env \
  -e UAT_BASE_URL=http://127.0.0.1:8052/api/v1 \
  compliance-loadtest \
  locust -f locustfile.py --host=http://127.0.0.1:8052/api/v1 \
  --headless --users 8 --spawn-rate 1 --run-time 12m \
  --csv=/loadtest/reports/run-$(date +%Y%m%d-%H%M)
```

## 3. Run Locust (native Python, if you have it)

Web UI:

```bash
set -a && source .env && set +a
locust -f locustfile.py --host="$UAT_BASE_URL"
# Open http://localhost:8089 — staged ramp 1 → 2 → 4 → 8 users, hold 10–15 min each
```

Headless example (8 users, 12 minutes — tuned for ~3 min p95 analysis on UAT):

```bash
set -a && source .env && set +a
locust -f locustfile.py --host="$UAT_BASE_URL" \
  --headless --users 8 --spawn-rate 1 --run-time 12m \
  --csv=reports/run-$(date +%Y%m%d-%H%M)
```

Custom metrics in Locust: `upload_to_doc_id`, `analysis_complete (completed|failed|timeout)`.

End of each run prints a **`LOAD TEST SUMMARY`** and writes `reports/last-run-summary.json`. For stepped capacity (max concurrent scans on current infra), see **`RUNBOOK.md`** → `capacity_ladder.sh`.

## 4. While tests run

On UAT host:

```bash
docker stats
docker compose logs -f worker
# Optional Redis queue depth:
docker compose exec redis redis-cli LLEN celery
```

## 5. Report

Fill `reports/infra-benchmark-YYYY-MM-DD.md` with instance types, worker count, concurrency, stub delay source, max stable users, docs/hour, bottleneck, and EC2/RDS cost table.
