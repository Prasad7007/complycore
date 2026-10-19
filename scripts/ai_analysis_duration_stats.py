#!/usr/bin/env python3
"""Compute AI analysis duration stats from audit_events (started → terminal)."""

import argparse
import asyncio
import os
from typing import Optional

from dotenv import load_dotenv
import asyncpg

load_dotenv()

SQL = """
WITH runs AS (
  SELECT
    s.review_id,
    s.created_at AS started_at,
    t.event_type AS end_event_type,
    t.created_at AS ended_at,
    EXTRACT(EPOCH FROM (t.created_at - s.created_at)) AS duration_sec
  FROM audit_events s
  JOIN LATERAL (
    SELECT e.event_type, e.created_at
    FROM audit_events e
    WHERE e.review_id = s.review_id
      AND e.created_at > s.created_at
      AND e.event_type IN ('ai_analysis_completed', 'ai_analysis_skipped', 'ai_analysis_failed')
    ORDER BY e.created_at ASC
    LIMIT 1
  ) t ON TRUE
  WHERE s.event_type = 'ai_analysis_started'
    AND ($1::timestamptz IS NULL OR s.created_at >= $1)
    AND ($2::timestamptz IS NULL OR s.created_at < $2)
),
filtered AS (
  SELECT *
  FROM runs
  WHERE
    CASE
      WHEN $3 = 'completed_only' THEN end_event_type = 'ai_analysis_completed'
      WHEN $3 = 'exclude_failed' THEN end_event_type IN ('ai_analysis_completed', 'ai_analysis_skipped')
      ELSE end_event_type IN ('ai_analysis_completed', 'ai_analysis_skipped', 'ai_analysis_failed')
    END
)
SELECT
  COUNT(*)::int AS run_count,
  ROUND(AVG(duration_sec)::numeric, 2) AS avg_sec,
  ROUND(MIN(duration_sec)::numeric, 2) AS min_sec,
  ROUND(MAX(duration_sec)::numeric, 2) AS max_sec,
  ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_sec)::numeric, 2) AS p50_sec,
  ROUND(percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_sec)::numeric, 2) AS p95_sec
FROM filtered;
"""


async def main() -> None:
    parser = argparse.ArgumentParser(description="Compute AI analysis duration stats from audit_events")
    parser.add_argument("--db-url", default=os.getenv("DATABASE_URL"), help="Postgres DSN (or set DATABASE_URL)")
    parser.add_argument("--from", dest="from_ts", default=None, help="Start timestamp (inclusive), e.g. 2026-04-01")
    parser.add_argument("--to", dest="to_ts", default=None, help="End timestamp (exclusive), e.g. 2026-05-01")
    parser.add_argument(
        "--mode",
        choices=["completed_only", "exclude_failed", "include_failed"],
        default="exclude_failed",
        help="Which terminal outcomes to include",
    )
    args = parser.parse_args()

    if not args.db_url:
        raise SystemExit("Missing DB URL. Pass --db-url or set DATABASE_URL")

    conn = await asyncpg.connect(args.db_url)
    try:
        row = await conn.fetchrow(SQL, args.from_ts, args.to_ts, args.mode)
    finally:
        await conn.close()

    print("\nAI Analysis Duration Stats")
    print("==========================")
    print(f"mode      : {args.mode}")
    print(f"from      : {args.from_ts or 'ALL'}")
    print(f"to        : {args.to_ts or 'ALL'}")
    print(f"run_count : {row['run_count']}")
    print(f"avg_sec   : {row['avg_sec']}")
    print(f"min_sec   : {row['min_sec']}")
    print(f"max_sec   : {row['max_sec']}")
    print(f"p50_sec   : {row['p50_sec']}")
    print(f"p95_sec   : {row['p95_sec']}\n")


if __name__ == "__main__":
    asyncio.run(main())
