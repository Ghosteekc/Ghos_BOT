#!/usr/bin/env python3
"""Проверка целостности и свежести локальной базы контров.

Usage:
    python scripts/check_local_counter_data.py
    python scripts/check_local_counter_data.py --max-age 14
    python scripts/check_local_counter_data.py --json

Exit codes:
    0 — snapshot OK и не устарел
    1 — snapshot устарел (stale)
    2 — snapshot missing / corrupt / empty
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.services.local_counter_data import (  # noqa: E402
    check_local_counter_snapshot,
    format_local_counter_status,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local counter database")
    parser.add_argument(
        "--max-age",
        type=int,
        default=30,
        help="Max snapshot age in days before marking stale (default: 30)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    args = parser.parse_args()

    status = check_local_counter_snapshot(max_age_days=args.max_age)
    if args.json:
        print(json.dumps(status.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_local_counter_status(status))

    if status.status in {"missing", "corrupt", "empty"}:
        return 2
    if status.stale:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
