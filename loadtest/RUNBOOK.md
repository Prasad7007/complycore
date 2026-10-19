# Locust load test — start & stop (UAT / EC2)

Run all commands from the **repo root**: `~/compliance_ai`

## Worker-only benchmark (no token or supplied PDF)

For an EC2 worker-capacity test that does not call the HTTP API, use:

```bash
bash loadtest/run_worker_capacity.sh
```

It generates its own small PDF, selects an active organization/member from the configured DB, inserts temporary test records, dispatches analysis tasks directly to Celery, and removes the records and S3 objects after the tasks drain. No API token, UAT URL, `loadtest/.env`, or user-supplied PDF is needed. The existing stack's database and S3 configuration are still required.

`APP_ENV` must be explicitly set to a non-production value in `AI Compliance/.env.docker`; production is refused. The script briefly recreates the worker with the fake LLM enabled, keeps it running through the benchmark, and restores normal Compose configuration after a successful run. Defaults are batch sizes `2 4 6 8`, 12 minutes per step, and 1.5 seconds per stub LLM call. Pass custom batch sizes as arguments, e.g. `bash loadtest/run_worker_capacity.sh 2 4 6 8 10`.

The test reports the largest batch size that completed successfully within the step limit. This is **worker/document-analysis capacity only**; it does not measure upload/API/auth throughput. See `loadtest/README.md` for recovery instructions if the runner exits nonzero.

**Prerequisites**

- `loadtest/.env` configured (`AUTH_TOKEN`, `ORG_SLUG=etai`, etc.)
- `loadtest/fixtures/sample.pdf` exists
- `AI Compliance/.env.docker` — stub vars only during benchmark

---

## A. Before you start (each benchmark window)

### 1. Enable stub LLM on worker (UAT only — not production)

Edit `AI Compliance/.env.docker` and add:

```env
LOAD_TEST_STUB_LLM=true
LOAD_TEST_STUB_LLM_DELAY_SEC=1.5
```

Apply env to worker (`restart` does **not** reload `env_file`):

```bash
cd ~/compliance_ai
docker compose up -d --force-recreate worker
```

Verify:

```bash
docker compose exec worker env | grep -i LOAD_TEST
docker compose logs worker 2>&1 | grep -i LOAD_TEST_STUB | tail -5
```

### 2. Auth smoke test

```bash
cd ~/compliance_ai
set -a && source loadtest/.env && set +a
curl -s -o /dev/null -w "users/me HTTP %{http_code}\n" \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  "http://127.0.0.1:8052/api/v1/users/me"
```

Expect `HTTP 200`. If 401, refresh `AUTH_TOKEN` from browser cookie `ac_session`.

Locust uploads with `routing=marketing` so analysis starts (default SME routing never queues a scan).

After changing worker LLM stub code, **rebuild** the worker image (`docker compose build worker`) then `--force-recreate`. Confirm logs: `LOAD_TEST_STUB_LLM ACTIVE` and `get_llm_client STUB ONLY` — **no** `vertexai_invoke_start`.

### 3. Build Locust image (after pull or loadtest code changes)

```bash
cd ~/compliance_ai
docker build -t compliance-loadtest ./loadtest
```

---

## B. Start Locust

### Smoke (2 users, 10 minutes) — recommended first run

```bash
cd ~/compliance_ai

docker run --rm --network host \
  -v "$(pwd)/loadtest/fixtures:/loadtest/fixtures:ro" \
  -v "$(pwd)/loadtest/reports:/loadtest/reports" \
  --env-file loadtest/.env \
  -e UAT_BASE_URL=http://127.0.0.1:8052/api/v1 \
  -e FIXTURE_PDF_PATH=/loadtest/fixtures/sample.pdf \
  compliance-loadtest \
  locust -f locustfile.py --host=http://127.0.0.1:8052/api/v1 \
  --headless --users 2 --spawn-rate 1 --run-time 10m \
  --csv=/loadtest/reports/smoke-$(date +%Y%m%d-%H%M) \
  --html=/loadtest/reports/smoke-$(date +%Y%m%d-%H%M).html
```

After the run, read the printed **`LOAD TEST SUMMARY`** block and:

- `loadtest/reports/last-run-summary.json` (latest metrics)
- `loadtest/reports/run-summary-<timestamp>.json` (archive copy)

### Sizing run (example: 8 users, 12 minutes — matches ~3 min p95 scan time)

```bash
cd ~/compliance_ai

docker run --rm --network host \
  -v "$(pwd)/loadtest/fixtures:/loadtest/fixtures:ro" \
  -v "$(pwd)/loadtest/reports:/loadtest/reports" \
  --env-file loadtest/.env \
  -e UAT_BASE_URL=http://127.0.0.1:8052/api/v1 \
  -e FIXTURE_PDF_PATH=/loadtest/fixtures/sample.pdf \
  compliance-loadtest \
  locust -f locustfile.py --host=http://127.0.0.1:8052/api/v1 \
  --headless --users 8 --spawn-rate 1 --run-time 12m \
  --csv=/loadtest/reports/bench-$(date +%Y%m%d-%H%M) \
  --html=/loadtest/reports/bench-$(date +%Y%m%d-%H%M).html
```

### Max concurrent scans (one command for your lead)

Steps **2 → 4 → 6 → 8 → …** until failures, timeouts, or in-flight cutoffs. Default **12 min per step** (from UAT audit stats: p95 analysis ≈ 200s). Writes **`loadtest/reports/capacity-ladder-result.json`**.

Recheck scan duration after prod-like load:

```bash
docker-compose run --no-deps --rm api python /app/scripts/ai_analysis_duration_stats.py --mode exclude_failed
```

```bash
cd ~/compliance_ai
./loadtest/snapshot_env.sh   # optional: EC2 type + git SHA
./loadtest/capacity_ladder.sh
```

Tune via env (optional):

```bash
export LOADTEST_LADDER_RUN_TIME=12m   # default; ~3 min p95 scan time in DB — see scripts/ai_analysis_duration_stats.py
export LOADTEST_LADDER_USERS="2 4 6 8"
export LOADTEST_LADDER_MIN_COMPLETION_PCT=95
./loadtest/capacity_ladder.sh
```

### Optional: compose profile (API on Docker network)

```bash
# loadtest/.env: UAT_BASE_URL=http://api:8052/api/v1
# FIXTURE_PDF_PATH=/loadtest/fixtures/sample.pdf
docker compose --profile loadtest \
  -f docker-compose.yml -f docker-compose.loadtest.yml \
  run --rm --service-ports loadtest
```

### While test runs (second terminal)

```bash
cd ~/compliance_ai
docker stats
docker compose logs -f worker
docker compose exec redis redis-cli LLEN celery
```

### Stop early

Press `Ctrl+C` in the Locust terminal (container exits; `--rm` removes it).

### Results

- **Summary JSON:** `loadtest/reports/last-run-summary.json` (completion %, p50/p95 analysis time, docs/hour)
- CSV: `loadtest/reports/smoke-*` or `bench-*` (`*_stats.csv`, `*_failures.csv`)
- HTML: matching `*.html` when `--html` is set
- Ladder: `loadtest/reports/capacity-ladder-result.json` → **`max_stable_concurrent_scans`**
- Human report: `loadtest/reports/infra-benchmark-TEMPLATE.md`

---

## C. After you finish (always)

### 1. Disable stub LLM

Remove from `AI Compliance/.env.docker`:

- `LOAD_TEST_STUB_LLM=...`
- `LOAD_TEST_STUB_LLM_DELAY_SEC=...`
- `LOAD_TEST_STUB_LLM_DELAY_PER_DOC_SEC=...` (if set)

```bash
cd ~/compliance_ai
docker compose up -d --force-recreate worker
docker compose exec worker env | grep -i LOAD_TEST
```

Should print nothing.

### 2. Confirm real AI works

Upload one document in UAT UI and confirm scan completes with real LLM.

### 3. Optional cleanup

- Delete `locust-load-*` documents in org `etai` (UI or approved script).
- Keep or archive `loadtest/reports/*.csv` for the benchmark write-up.

### 4. Secrets

- Do not commit `loadtest/.env`.
- Refresh JWT if it was shared or expired.

---

## D. `loadtest/.env` reference

```env
UAT_BASE_URL=https://app.complycore.ca/api/v1
AUTH_TOKEN=<from ac_session cookie, marketing user>
ORG_SLUG=etai
FIXTURE_PDF_PATH=./fixtures/sample.pdf
POLL_INTERVAL_SEC=5
ANALYSIS_TIMEOUT_SEC=1800
DOCUMENT_TYPE=Marketing Material
```

For Docker on the same EC2 host, override:

- `-e UAT_BASE_URL=http://127.0.0.1:8052/api/v1`
- `-e FIXTURE_PDF_PATH=/loadtest/fixtures/sample.pdf`

---

## E. What Locust `--users` means

Each virtual user = **upload PDF → poll until scan completes → repeat**.

`--users N` ≈ **N concurrent full document scans**, not “N people browsing the app.”

`--run-time 10m` = how long the **load generator** runs, not prod session length.

See also: `loadtest/README.md`
