#!/usr/bin/env bash
# Capture host/Docker context before a benchmark (run from repo root).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${ROOT}/loadtest/reports/env-snapshot.json"
mkdir -p "${ROOT}/loadtest/reports"

INSTANCE_TYPE="unknown"
if curl -sf --max-time 2 http://169.254.169.254/latest/meta-data/instance-type >/dev/null 2>&1; then
  INSTANCE_TYPE="$(curl -sf --max-time 2 http://169.254.169.254/latest/meta-data/instance-type)"
fi

WORKER_MEM_LIMIT=""
if [[ -f "${ROOT}/docker-compose.yml" ]]; then
  WORKER_MEM_LIMIT="$(grep -A20 '^  worker:' "${ROOT}/docker-compose.yml" | grep -E 'memory:' | head -1 | tr -d ' ' || true)"
fi

GIT_SHA="$(git -C "${ROOT}" rev-parse HEAD 2>/dev/null || echo unknown)"

cat >"${OUT}" <<EOF
{
  "captured_at_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "hostname": "$(hostname)",
  "ec2_instance_type": "${INSTANCE_TYPE}",
  "git_sha": "${GIT_SHA}",
  "worker_compose_memory_line": "${WORKER_MEM_LIMIT}",
  "note": "Run ./loadtest/snapshot_env.sh before Locust; attach env-snapshot.json to benchmark report."
}
EOF

echo "Wrote ${OUT}"
