# Infra benchmark — YYYY-MM-DD

## Environment

| Item | Value |
|------|--------|
| UAT URL | |
| EC2 instance type(s) | |
| Worker containers | |
| Celery `--concurrency` | |
| Worker memory limit | |
| RDS class | |
| `LOAD_TEST_STUB_LLM` delay | source: manual run / default |

## Results

| Run | Workers | Concurrency | Locust users | Error % | p95 analysis complete (s) | Docs/hour (sustained) | Notes |
|-----|---------|-------------|--------------|---------|---------------------------|------------------------|-------|
| R0 | 1 | 2 | | | | | |
| R1 | 2 | 2 | | | | | |

## Max capacity

- Max stable concurrent analyses:
- Bottleneck (worker / RDS / API / Redis):

## Scaling & cost (infra only)

| Config | Throughput (docs/hr) | Est. monthly EC2 | Est. monthly RDS |
|--------|----------------------|------------------|------------------|
| 1× | | | |
| 2× | | | |

## LLM cost (separate)

- Assumed docs/month:
- $/doc from prod sampling:
- Est. monthly Vertex:

## Recommendations

## Assumptions & limits
