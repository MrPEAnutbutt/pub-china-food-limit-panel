#!/usr/bin/env python3
"""List record identifiers that changed between two releases.

A record_id is a digest of the row's fields as built (for pesticide rules, the
printed rule fields), so it changes whenever one of those fields changes.  For
every table with a record_id this
script compares the previous and the current release, pairs a vanished and a
new identifier when exactly one of each shares the table's natural key, and
reports the rest as removed or added.  Unchanged rows are not listed.

Usage:
    python3 Program/Clean/261025_release_id_changes.py \\
        --previous-release Data/Interim/release_snapshots/v1.0 \\
        --release-dir Data/Final/china_food_limit_panel_v1
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RELEASE = PROJECT_ROOT / "Data" / "Final" / "china_food_limit_panel_v1"
OUTPUT = "record_id_changes.csv"
FIELDS = ("table", "change", "record_id_previous", "record_id_current", "natural_key")

# Keys that identify the same released fact across releases; README lists them
# as the keys for longitudinal use.
NATURAL_KEYS = {
    "pollutant_limits_long.csv": ("version_year", "analyte_zh", "food_category_zh", "limit_basis"),
    "pesticide_limits_long.csv": ("version_year", "section_number", "source_page", "source_y"),
    "mycotoxin_limits_long.csv": ("version_year", "toxin_zh", "food_category_zh"),
    "vetdrug_limits_long.csv": ("version_year", "drug_zh", "animal_raw", "tissue_zh"),
    "additive_limits_long.csv": ("version_year", "cns_code", "food_code"),
    "pollutant_category_panel.csv": ("analyte_zh", "food_category_zh"),
    "pollutant_member_panel.csv": ("analyte_zh", "food_member_zh"),
    "pesticide_panel.csv": ("pesticide_key", "food_key"),
    "mycotoxin_panel.csv": ("toxin_zh", "food_zh"),
    "mycotoxin_member_panel.csv": ("toxin_zh", "food_member_zh"),
    "vetdrug_panel.csv": ("drug_en", "tissue_zh"),
    "vetdrug_member_panel.csv": ("drug_zh", "animal", "tissue_zh"),
    "additive_panel.csv": ("cns_code", "food_code"),
    "entity_names_en.csv": ("entity_type", "name_zh", "source_standard"),
    "standard_version_timeline.csv": ("std_id", "version_year", "event_type", "amendment_no"),
    "version_dates.csv": ("family", "standard", "version_year"),
    "quarantined_rows.csv": ("standard", "version_year", "raw_text"),
}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def table_changes(name: str, previous: list[dict[str, str]], current: list[dict[str, str]]):
    columns = NATURAL_KEYS[name]
    previous_ids = {row["record_id"] for row in previous}
    current_ids = {row["record_id"] for row in current}
    gone = defaultdict(list)
    new = defaultdict(list)
    for row in previous:
        if row["record_id"] not in current_ids:
            gone[tuple(row[column] for column in columns)].append(row)
    for row in current:
        if row["record_id"] not in previous_ids:
            new[tuple(row[column] for column in columns)].append(row)

    def key_text(key):
        return json.dumps(dict(zip(columns, key)), ensure_ascii=False, separators=(",", ":"))

    changes = []
    for key in sorted(set(gone) | set(new)):
        if len(gone[key]) == 1 and len(new[key]) == 1:
            changes.append((name, "replaced", gone[key][0]["record_id"], new[key][0]["record_id"], key_text(key)))
            continue
        changes.extend((name, "removed", row["record_id"], "", key_text(key)) for row in gone[key])
        changes.extend((name, "added", "", row["record_id"], key_text(key)) for row in new[key])
    return changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-release", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE)
    args = parser.parse_args(argv)
    changes = []
    for name in sorted(NATURAL_KEYS):
        changes.extend(table_changes(
            name, read_rows(args.previous_release / name), read_rows(args.release_dir / name)))
    with (args.release_dir / OUTPUT).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(FIELDS)
        writer.writerows(changes)
    counts = defaultdict(int)
    for name, change, *_ in changes:
        counts[(name, change)] += 1
    for (name, change), count in sorted(counts.items()):
        print(f"{name}\t{change}\t{count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
