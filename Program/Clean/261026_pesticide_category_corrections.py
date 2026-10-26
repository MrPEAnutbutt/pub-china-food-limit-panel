#!/usr/bin/env python3
"""Freeze the v1.0 to v1.1 pesticide category corrections as audit evidence.

Round 1 of the independent reading found foods filed under a long food label
instead of their category, and the extraction rule was corrected in all six
GB 2763 editions.  This script pairs the pesticide rows of the two releases on
their natural key, fails unless the only changes are the parent category (with
its assignment method) and the six temporary-limit marks corrected to the
issuing-authority scan, and writes one row per changed category.

Usage:
    python3 Program/Clean/261026_pesticide_category_corrections.py \\
        --previous-release Data/Interim/release_snapshots/v1.0
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RELEASE = PROJECT_ROOT / "Data" / "Final" / "china_food_limit_panel_v1"
DEFAULT_OUTPUT = (PROJECT_ROOT / "Data" / "Interim" / "pesticide_audit_round2"
                  / "category_corrections.csv")
TABLE = "pesticide_limits_long.csv"
KEY = ("version_year", "section_number", "source_page", "source_y")
CATEGORY = {"parent_category_zh", "parent_category_raw", "parent_assignment_method"}
ASTERISK = {"limit_qualifier", "is_temporary", "review_status"}
# Fields first released in v1.1 have no previous value to compare.
ADDED = {"source_reference", "extraction_method", "verification_status", "verification_basis"}
FIELDS = KEY + ("pesticide_zh", "food_zh", "limit_value", "parent_category_previous",
                "parent_category_current", "record_id_previous", "record_id_current")


def read_rows(path: Path) -> dict[tuple[str, ...], dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {tuple(row[c] for c in KEY): row for row in csv.DictReader(handle)}


def corrections(previous, current):
    if previous.keys() != current.keys():
        raise ValueError("the two releases do not hold the same pesticide rules")
    changed = []
    for key, old in previous.items():
        new = current[key]
        fields = {c for c in old if c != "record_id" and old[c] != new[c]}
        asterisk = "scan_temporary_mark_correction" in new["review_status"].split(";")
        allowed = CATEGORY | (ASTERISK if asterisk else set())
        if fields - allowed:
            raise ValueError(f"unexpected change at {key}: {sorted(fields - allowed)}")
        if old["parent_category_zh"] != new["parent_category_zh"]:
            changed.append(dict(zip(KEY, key), pesticide_zh=new["pesticide_zh"],
                                food_zh=new["food_zh"], limit_value=new["limit_value"],
                                parent_category_previous=old["parent_category_zh"],
                                parent_category_current=new["parent_category_zh"],
                                record_id_previous=old["record_id"],
                                record_id_current=new["record_id"]))
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-release", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    previous = read_rows(args.previous_release / TABLE)
    current = read_rows(args.release_dir / TABLE)
    for row in current.values():
        for column in ADDED:
            del row[column]
    changed = corrections(previous, current)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(changed)
    by_year = Counter(row["version_year"] for row in changed)
    print(f"wrote {args.output}: {len(changed)} of {len(current)} rows changed category "
          f"({dict(sorted(by_year.items()))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
