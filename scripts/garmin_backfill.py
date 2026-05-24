"""Backfill Garmin sync for a date range.

Usage:
    uv run python ../scripts/garmin_backfill.py --start 2026-05-01 --end 2026-05-21
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta

from claude_coach.db.session import SessionLocal
from claude_coach.services.garmin_sync import service


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True, type=parse_date)
    p.add_argument("--end", required=True, type=parse_date)
    p.add_argument("--sleep", type=float, default=1.0, help="seconds between days (rate-limit)")
    args = p.parse_args()

    if args.end < args.start:
        print("end must be >= start", file=sys.stderr)
        return 1

    days = (args.end - args.start).days + 1
    print(f"Backfilling {days} day(s): {args.start} → {args.end}")

    ok = 0
    err = 0
    db = SessionLocal()
    try:
        d = args.start
        while d <= args.end:
            result = service.sync_day(db, day=d)
            if result.status == "ok":
                ok += 1
                print(
                    f"  {d}  ok  activities={result.activities} daily={result.daily} body={result.body}"
                )
            else:
                err += 1
                print(f"  {d}  ERR  {result.error}")
            d += timedelta(days=1)
            if d <= args.end and args.sleep > 0:
                time.sleep(args.sleep)
    finally:
        db.close()

    print(f"\nDone: {ok} ok, {err} errors.")
    return 0 if err == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
