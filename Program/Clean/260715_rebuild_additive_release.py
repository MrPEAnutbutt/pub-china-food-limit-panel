#!/usr/bin/env python3
"""Rebuild the released GB 2760 tables from the additive extraction outputs.

This targeted builder is intentionally limited to the additive long table,
the exact-code additive panel, the shared quarantine table, and their entries
in ``_build_stats.json``.  It lets an additive-parser correction be promoted
without rebuilding unrelated families from external intermediate directories.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

from release_panel_utils import ADDITIVE_YEARS, build_additive_panel, panel_columns


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ADDITIVE_INTERIM = PROJECT_ROOT / "Data" / "Interim" / "additive_extraction"
DEFAULT_POLLUTANT_INTERIM = PROJECT_ROOT / "Data" / "Interim" / "pollutant_rebuild"
DEFAULT_RELEASE_DIR = PROJECT_ROOT / "Data" / "Final" / "china_food_limit_panel_v1"

ADDITIVE_COLUMNS = (
    "record_id",
    "standard",
    "version_year",
    "additive_zh",
    "cns_code",
    "ins_code",
    "food_code",
    "food_zh",
    "max_use",
    "unit",
    "note",
    "conflict",
)
QUARANTINE_COLUMNS = (
    "record_id",
    "standard",
    "version_year",
    "analyte_zh",
    "additive_zh",
    "food_code",
    "food_zh",
    "parsed_value",
    "unit",
    "reject_reason",
    "raw_text",
    "source_path",
)
ADDITIVE_PANEL_COLUMNS = tuple(
    panel_columns(
        [
            "record_id",
            "standard",
            "additive_zh",
            "additive_names_zh",
            "cns_code",
            "ins_codes",
            "food_code",
            "food_zh",
            "food_names_zh",
        ],
        ADDITIVE_YEARS,
        ["trend"],
    )
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def atomic_write_csv(path: Path, rows: list[dict[str, object]], columns: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def deduplicate_and_identify(
    rows: list[dict[str, str]], business_key: tuple[str, ...], prefix: str
) -> tuple[list[dict[str, str]], int, int]:
    """Match the release builder's exact-deduplication and identifier contract."""

    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    exact_duplicates = 0
    for row in rows:
        signature = hashlib.md5(
            json.dumps(row, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        if signature in seen:
            exact_duplicates += 1
            continue
        seen.add(signature)
        unique.append(row)

    counts = Counter(tuple(row.get(column, "") for column in business_key) for row in unique)
    for index, row in enumerate(unique, start=1):
        row["record_id"] = f"{prefix}{index:05d}"
        key = tuple(row.get(column, "") for column in business_key)
        row["conflict"] = "1" if counts[key] > 1 else "0"
    conflicting_rows = sum(row["conflict"] == "1" for row in unique)
    return unique, exact_duplicates, conflicting_rows


def build_additive_long(source_rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], dict[str, int]]:
    rows = [
        {
            "standard": "GB 2760",
            "version_year": row["year"],
            "additive_zh": row["additive"],
            "cns_code": row["cns"],
            "ins_code": row.get("ins", ""),
            "food_code": row["food_code"],
            "food_zh": row["food"],
            "max_use": row["max_use"],
            "unit": row["unit"],
            "note": row.get("note", ""),
        }
        for row in source_rows
    ]
    rows, exact_duplicates, conflicting_rows = deduplicate_and_identify(
        rows, ("version_year", "cns_code", "food_code"), "ADD"
    )
    return rows, {
        "rows": len(rows),
        "exact_dups_removed": exact_duplicates,
        "rows_with_conflicting_key": conflicting_rows,
    }


def build_quarantine(
    additive_rows: list[dict[str, str]], pollutant_rows: list[dict[str, str]]
) -> tuple[list[dict[str, str]], dict[str, int]]:
    rows = [
        {
            "standard": "GB 2760",
            "version_year": row["year"],
            "additive_zh": row["additive"],
            "food_code": row["food_code"],
            "food_zh": row["food"],
            "parsed_value": row["max_use"],
            "unit": row.get("unit", ""),
            "reject_reason": row["reject"],
            "raw_text": row["raw_chunk"],
            "source_path": "GB 2760 source PDF",
        }
        for row in additive_rows
    ]
    rows.extend(
        {
            "standard": "GB 2762",
            "version_year": row["year"],
            "analyte_zh": row["analyte"],
            "food_zh": row["food_category"],
            "parsed_value": row["limit_value"],
            "unit": row["unit"],
            "reject_reason": row["reason"],
            "raw_text": row["food_category"],
            "source_path": Path(row.get("source_path", "").replace("\\", "/")).name,
        }
        for row in pollutant_rows
    )
    rows, exact_duplicates, _ = deduplicate_and_identify(
        rows,
        (
            "standard",
            "version_year",
            "analyte_zh",
            "additive_zh",
            "food_code",
            "food_zh",
        ),
        "QUA",
    )
    return rows, {"rows": len(rows), "exact_dups_removed": exact_duplicates}


def rebuild(
    additive_interim: Path,
    pollutant_interim: Path,
    release_dir: Path,
) -> dict[str, dict[str, int]]:
    additive_source = read_csv(additive_interim / "additive_raw_long.csv")
    additive_quarantine = read_csv(additive_interim / "additive_quarantine.csv")
    pollutant_quarantine = read_csv(pollutant_interim / "pollutant_quarantine.csv")

    long_rows, long_stats = build_additive_long(additive_source)
    panel_rows = build_additive_panel(long_rows)
    panel_rows, panel_duplicates, _ = deduplicate_and_identify(
        panel_rows, ("cns_code", "food_code"), "ASP"
    )
    quarantine_rows, quarantine_stats = build_quarantine(
        additive_quarantine, pollutant_quarantine
    )

    stats_path = release_dir / "_build_stats.json"
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    stats["additive_limits"] = long_stats
    stats["additive_panel"] = {
        "rows": len(panel_rows),
        "exact_dups_removed": panel_duplicates,
    }
    stats["quarantined_rows"] = quarantine_stats

    atomic_write_csv(release_dir / "additive_limits_long.csv", long_rows, ADDITIVE_COLUMNS)
    atomic_write_csv(release_dir / "additive_panel.csv", panel_rows, ADDITIVE_PANEL_COLUMNS)
    atomic_write_csv(
        release_dir / "quarantined_rows.csv", quarantine_rows, QUARANTINE_COLUMNS
    )
    atomic_write_json(stats_path, stats)
    return {
        "additive_limits": long_stats,
        "additive_panel": stats["additive_panel"],
        "quarantined_rows": quarantine_stats,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--additive-interim", type=Path, default=DEFAULT_ADDITIVE_INTERIM)
    parser.add_argument("--pollutant-interim", type=Path, default=DEFAULT_POLLUTANT_INTERIM)
    parser.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    stats = rebuild(args.additive_interim, args.pollutant_interim, args.release_dir)
    for name, values in stats.items():
        print(f"{name}: {values['rows']:,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
