# Dev & database setup

## Local app (Python on your machine)

From the repo root:

```bash
# 1. Activate venv
source .venv/bin/activate

# 2. Redis (once)
docker run -d --name redis-server -p 6379:6379 redis:7-alpine

# 3. API
cd "AI Compliance"
uvicorn apis.main:app --reload --port 8052

# 4. Celery worker (new terminal, venv on)
cd "AI Compliance"
python -m celery -A apis.services.celery_app worker --loglevel=info --concurrency=1

# 5. Frontend (new terminal)
cd full-frontend
npm run dev
```

Put day-to-day secrets in `AI Compliance/.env` for this local uvicorn/celery flow.

---

## Full stack via Docker Compose

From the repo root. Configure `AI Compliance/.env.docker` first (Compose injects it into `api` / `worker`).

```bash
# Newer Docker (Compose V2 plugin)
docker compose up -d --build

# Older Docker / standalone Compose binary
docker-compose up -d --build
```

That builds and starts **redis**, **api** (`:8052`), **worker**, and **frontend** (`:8054`).

**Database URL tip**

| Where Postgres runs | Use in `.env.docker` |
|---------------------|----------------------|
| On your Mac/Windows host | `…@host.docker.internal:5432/…` (containers reach the host) |
| RDS / remote | RDS hostname (+ `?sslmode=require` if needed) |
| Host Python / Alembic on laptop | `localhost` works; Alembic also rewrites `host.docker.internal` → `localhost` |

Stop with `docker compose down` (or `docker-compose down`).

For a brand-new empty DB, run migrate + seed after the stack (or before) — see below.

---

## Fresh database (migrate + seed)

Use this on an **empty** Postgres database (local Docker Postgres, or RDS).  
The script does **not** create the Postgres instance or the database name — create those first, then point `DATABASE_URL` at them.

**What it does:** Alembic → head, then seed roles / permissions / compliance rules.  
**What it does not:** create Cognito users or the first org admin (use app bootstrap or `scripts/bootstrap_owner.py` after).

### Config

Set `DATABASE_URL` in `AI Compliance/.env.docker` (Compose and the init script both use this file).

Examples:

```text
# Local Docker Postgres
DATABASE_URL=postgresql://comply:comply@localhost:5433/ai_compliance

# RDS (SSL usually required)
DATABASE_URL=postgresql://user:password@your-db.region.rds.amazonaws.com:5432/ai_compliance?sslmode=require
```

### Run with host Python

```bash
cd "AI Compliance"
python init_database.py
```

No flags = migrate **and** seed. Optional: `--migrate-only` or `--seed-only`.

### Run with Docker only (EC2 / no host Python)

Needs Docker + Compose and a built API image. No Python install on the host.

```bash
# One-shot (preferred for first init)
docker-compose run --no-deps --rm api python init_database.py

# Or if the API container is already running
docker exec -it ai-compliance-api python init_database.py
```

Compose injects `AI Compliance/.env.docker` into the container, so `DATABASE_URL` there must reach the DB (RDS security group / network, etc.).

### After success

Create the first organization admin via the app bootstrap flow, or:

```bash
python scripts/bootstrap_owner.py --email admin@example.com
```

(from repo root; needs Cognito env vars).

---

## Where things live

| Path | Purpose |
|------|---------|
| `AI Compliance/init_database.py` | **Only** entrypoint for fresh DB (migrate + seed) |
| `AI Compliance/seed_db.py` | Seed data (called by `init_database.py`) |
| `AI Compliance/alembic/` + `schema.sql` + `migrations/*.sql` | Schema history (Alembic baseline uses these) |
| `AI Compliance/apis/` | Application code |
| `AI Compliance/tests/` | Tests (`tests/ci/` runs in GitHub Actions) |
| `scripts/` | Ops utilities (bootstrap, trim roles, clear user, email preview, …) — mounted into the API container at `/app/scripts` |

Do **not** use old one-off scripts (`setup_db.py`, `run_migration.py`, root `test_*.py`); they were removed in favor of Alembic + `init_database.py`.
