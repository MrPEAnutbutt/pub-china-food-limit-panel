#!/usr/bin/env python3
"""Draw the independent-reading sample for GB 2763-2019 and GB 2763-2021.

The 17,200 released rows of the two editions come from government-hosted
text-layer copies. The release compares them with an OCR reading of the issuing
authority's scans in groups (`pesticide_ocr_crosscheck.csv`). This script links
every group back to its released row, stratifies the rows by edition and
comparison status, and writes a value-free reading template for an independent
reviewer who reads the scans.

With `--redraw-of`, the script draws round 2 instead: the strata where round 1
found one error type twice or more are drawn again from a release rebuilt
after the extraction rule was corrected, taking the next-ranked rows the
reviewer has not read.

Usage:
    python3 Program/Clean/261024_pesticide_audit_sample.py
    python3 Program/Clean/261024_pesticide_audit_sample.py --output-dir <empty-dir>
    python3 Program/Clean/261024_pesticide_audit_sample.py \\
        --release-dir <rebuilt-release> --redraw-of Data/Interim/pesticide_audit \\
        --first-release-dir <release-drawn-in-round-1> --output-dir <empty-dir>
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RELEASE = PROJECT_ROOT / "Data" / "Final" / "china_food_limit_panel_v1"
DEFAULT_OUTPUT = PROJECT_ROOT / "Data" / "Interim" / "pesticide_audit"

PROTOCOL_VERSION = "1.0"
SEED = "GB2763-audit-20261024"
RANDOM_SAMPLE_SIZE = 288
EDITIONS = ("2019", "2021")
RANDOM_STATUSES = ("consistent", "text_only")
CENSUS_STATUSES = ("conflict", "ocr_only")
# Scan PDF page = text-layer PDF page - 1 for 3,649 of the 3,710 groups both
# readings place on a page; the rest differ by one more page either way.
SCAN_PAGE_OFFSET = -1
# Round 1 found foods filed under a long food label instead of their category
# in these strata (Data/Interim/pesticide_audit/comparison, 7 of 288 rows).
REDRAW_STRATA = (("2019", "consistent"), ("2019", "text_only"), ("2021", "text_only"))
# The printed position and text of a row; stable when only its category changes.
ROW_LOCATION = ["version_year", "section_number", "source_page", "source_y",
                "food_zh", "value_raw"]

TEMPLATE_FIELDS = (
    "blind_id",
    "edition",
    "section_number",
    "pesticide_zh",
    "parent_category_zh",
    "food_zh",
    "reference_scan_pdf_page",
    "entry_status",
    "limit_value_raw",
    "reviewer_note",
)
KEY_FIELDS = (
    "blind_id",
    "edition",
    "stratum",
    "selection",
    "record_id",
    "section_number",
    "parent_category_zh",
    "food_zh",
    "rank_digest",
    "population_rows",
    "sample_rows",
    "weight",
)


class AuditError(RuntimeError):
    """Raised when the linkage or the sampling contract is violated."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--redraw-of", type=Path)
    parser.add_argument("--first-release-dir", type=Path, default=DEFAULT_RELEASE)
    return parser.parse_args(argv)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rank_digest(key: str) -> str:
    return hashlib.sha256(f"{SEED}:{key}".encode("utf-8")).hexdigest()


def load(release: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    groups = pd.read_csv(
        release / "pesticide_ocr_crosscheck.csv", dtype=str, keep_default_na=False
    )
    rows = pd.read_csv(
        release / "pesticide_limits_long.csv", dtype=str, keep_default_na=False
    )
    rows = rows[rows["version_year"].isin(EDITIONS)].copy()
    return groups, rows


def link_rows(groups: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    """Attach each text-layer group to exactly one released row."""
    text_groups = groups[groups["status"] != "ocr_only"]
    if not (text_groups["text_row_count"] == "1").all():
        raise AuditError("a text-layer group does not hold exactly one row")
    keys = {
        "strict_scope": ["section_number", "parent_category_zh", "food_zh"],
        "unique_section_food": ["section_number", "food_zh"],
    }
    linked = []
    for level, columns in keys.items():
        subset = text_groups[text_groups["key_level"] == level].rename(
            columns={"year": "version_year", "parent_category": "parent_category_zh",
                     "food": "food_zh"}
        )
        merged = subset.merge(
            rows, on=["version_year", *columns], how="left", suffixes=("_group", "")
        )
        if len(merged) != len(subset):
            raise AuditError(f"a {level} group matches more than one row")
        if merged["record_id"].isna().any() or (merged["record_id"] == "").any():
            raise AuditError(f"unlinked {level} groups")
        linked.append(merged)
    out = pd.concat(linked, ignore_index=True)
    if out["record_id"].duplicated().any():
        raise AuditError("a released row is linked to two groups")
    if set(out["record_id"]) != set(rows["record_id"]):
        raise AuditError("linked rows differ from the released 2019 and 2021 rows")
    if not (out["text_source_pages"] == out["source_page"]).all():
        raise AuditError("group page differs from the released row page")
    return out.rename(columns={"status": "crosscheck_status"})


def allocate(population: dict[tuple[str, str], int], total: int) -> dict:
    """Proportional allocation with largest-remainder rounding."""
    size = sum(population.values())
    quotas = {key: total * count / size for key, count in population.items()}
    sample = {key: int(quota) for key, quota in quotas.items()}
    order = sorted(quotas, key=lambda key: (sample[key] - quotas[key], key))
    for key in order[: total - sum(sample.values())]:
        sample[key] += 1
    return sample


def draw(linked: pd.DataFrame, groups: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    linked = linked.copy()
    linked["rank_digest"] = linked["record_id"].map(rank_digest)
    population = {
        (edition, status): int(
            ((linked["version_year"] == edition)
             & (linked["crosscheck_status"] == status)).sum()
        )
        for edition in EDITIONS
        for status in RANDOM_STATUSES
    }
    allocation = allocate(population, RANDOM_SAMPLE_SIZE)
    picks, strata = [], []
    for (edition, status), n in allocation.items():
        stratum = linked[(linked["version_year"] == edition)
                         & (linked["crosscheck_status"] == status)]
        chosen = stratum.sort_values("rank_digest").head(n).assign(
            selection="proportional_random",
            population_rows=len(stratum), sample_rows=n,
        )
        picks.append(chosen)
        strata.append((edition, status, "proportional_random", len(stratum), n))
    for edition in EDITIONS:
        conflict = linked[(linked["version_year"] == edition)
                          & (linked["crosscheck_status"] == "conflict")]
        picks.append(conflict.assign(
            selection="census", population_rows=len(conflict),
            sample_rows=len(conflict),
        ))
        strata.append((edition, "conflict", "census", len(conflict), len(conflict)))
    sample = pd.concat(picks, ignore_index=True)

    ocr_only = groups[groups["status"] == "ocr_only"].copy()
    names = linked.drop_duplicates(["version_year", "section_number"]).set_index(
        ["version_year", "section_number"]
    )["pesticide_zh"]
    omission = pd.DataFrame({
        "version_year": ocr_only["year"],
        "section_number": ocr_only["section_number"],
        "pesticide_zh": [names[(y, s)] for y, s in
                         zip(ocr_only["year"], ocr_only["section_number"])],
        "parent_category_zh": ocr_only["parent_category"],
        "food_zh": ocr_only["food"],
        "crosscheck_status": "ocr_only",
        "record_id": "",
        "scan_page": ocr_only["ocr_source_pages"].astype(int),
        "source_y": "",
        "selection": "census",
    })
    omission["rank_digest"] = [
        rank_digest(f"{y}|{s}|{p}|{f}") for y, s, p, f in zip(
            omission["version_year"], omission["section_number"],
            omission["parent_category_zh"], omission["food_zh"])
    ]
    for edition in EDITIONS:
        count = int((omission["version_year"] == edition).sum())
        strata.append((edition, "ocr_only", "census", count, count))
    omission["population_rows"] = omission["version_year"].map(
        omission["version_year"].value_counts())
    omission["sample_rows"] = omission["population_rows"]

    sample["scan_page"] = sample["source_page"].astype(int) + SCAN_PAGE_OFFSET
    sample = pd.concat([sample, omission], ignore_index=True)
    return number_rows(sample, "PA"), strata


def redraw(linked: pd.DataFrame, first_dir: Path, first_release: Path
           ) -> tuple[pd.DataFrame, list]:
    """Draw REDRAW_STRATA again, skipping the rows read in round 1."""
    manifest = json.loads((first_dir / "audit_manifest.json").read_text())
    key_path = first_dir / manifest["outputs"]["key"]["filename"]
    rows_path = first_release / "pesticide_limits_long.csv"
    if sha256(key_path) != manifest["outputs"]["key"]["sha256"]:
        raise AuditError("round-1 key differs from its manifest")
    if sha256(rows_path) != manifest["inputs"]["pesticide_limits_long.csv"]["sha256"]:
        raise AuditError("first release differs from the one drawn in round 1")
    first = pd.read_csv(key_path, dtype=str, keep_default_na=False)
    first = first[first["record_id"] != ""][["record_id", "edition", "stratum",
                                             "sample_rows"]]
    old_rows = pd.read_csv(rows_path, dtype=str, keep_default_na=False)
    located = first.merge(old_rows[["record_id", *ROW_LOCATION]], on="record_id")
    read = located.merge(linked[[*ROW_LOCATION, "record_id", "crosscheck_status"]],
                         on=ROW_LOCATION, suffixes=("_old", ""))
    if len(read) != len(first):
        raise AuditError("a round-1 row cannot be located in the rebuilt release")
    if (read["crosscheck_status"] != read["stratum"]).any():
        raise AuditError("a round-1 row changed stratum in the rebuilt release")

    linked = linked.copy()
    linked["rank_digest"] = linked["record_id"].map(rank_digest)
    picks, strata = [], []
    for edition, status in REDRAW_STRATA:
        stratum = linked[(linked["version_year"] == edition)
                         & (linked["crosscheck_status"] == status)]
        n = int(first[(first["edition"] == edition)
                      & (first["stratum"] == status)]["sample_rows"].iloc[0])
        unread = stratum[~stratum["record_id"].isin(read["record_id"])]
        picks.append(unread.sort_values("rank_digest").head(n).assign(
            selection="redraw_random", population_rows=len(stratum), sample_rows=n,
        ))
        strata.append((edition, status, "redraw_random", len(stratum), n))
    sample = pd.concat(picks, ignore_index=True)
    sample["scan_page"] = sample["source_page"].astype(int) + SCAN_PAGE_OFFSET
    return number_rows(sample, "PB"), strata


def number_rows(sample: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """Weight the rows, put them in document order and assign blind IDs."""
    sample["weight"] = (
        sample["population_rows"].astype(int) / sample["sample_rows"].astype(int)
    ).round(6)
    sample["_y"] = pd.to_numeric(sample["source_y"], errors="coerce")
    sample = sample.sort_values(
        ["version_year", "section_number", "scan_page", "_y", "food_zh"],
        key=lambda col: (col.astype(int) if col.name == "section_number" else col),
        na_position="last",
    ).reset_index(drop=True)
    sample["blind_id"] = [
        f"{prefix}{edition}-{index:03d}" for edition, index in zip(
            sample["version_year"],
            sample.groupby("version_year").cumcount() + 1)
    ]
    return sample


def write_csv(path: Path, fields, rows) -> dict[str, object]:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return {"filename": path.name, "rows": len(rows), "sha256": sha256(path)}


def protocol_text(strata: list, total: int) -> str:
    lines = "\n".join(
        f"| {edition} | {status} | {selection} | {population:,} | {sample} |"
        for edition, status, selection, population, sample in strata
    )
    return f"""# Independent reading of GB 2763-2019 and GB 2763-2021

- Protocol version: `{PROTOCOL_VERSION}`
- Seed: `{SEED}`
- Status: awaiting a real independent reviewer

## Population and strata

The released rows for the two editions (7,108 and 10,092, together 17,200) come
from government-hosted text-layer copies (SRC0024, SRC0025). Each row is linked
to its group in `pesticide_ocr_crosscheck.csv`, which compares the text layer
with an OCR reading of the issuing authority's scans (SRC0009, SRC0010). The
linkage is one row per text-layer group; `pesticide_row_crosscheck_status.csv`
lists the status of all 17,200 rows.

{RANDOM_SAMPLE_SIZE} rows are drawn with probability proportional to stratum size
from the `consistent` and `text_only` strata of each edition (largest-remainder
rounding). Within a stratum, rows are ranked by SHA-256 of
`{SEED}:<record_id>` and the lowest ranks are taken, so the draw does not depend
on software versions. All 9 `conflict` rows are included, and the 3 `ocr_only`
groups, which have no released row, are included to check for omissions.
{total} template rows in all.

| Edition | Stratum | Selection | Population | Sample |
|---|---|---|---:|---:|
{lines}

## Blindness boundary

The reviewer receives `pesticide_blind_read_template.csv` (or the workbook built
from it by `261024_reviewer_handoff.py`) and the two scans, whose SHA-256 digests
the custodian checks against `source_manifest.csv` before handoff. The template
gives the edition, section, pesticide, food category, food and a reference scan
page; it gives no value, comparison status or record ID. Rows are in document
order, so the strata cannot be read from the order.
`pesticide_audit_sample_key.csv` links blind IDs to record IDs and strata and is
held by the custodian until the completed template is frozen.

## Reviewer instructions

For each row, find the section and the food in the scan and record:

- `entry_status`: `transcribed`, `illegible` or `not_found` (the food is not
  printed in that section under that category).
- `limit_value_raw`: the printed limit exactly as shown, including any asterisk
  and any printed qualifier. Leave it blank for `illegible` and `not_found`.
- `reviewer_note`: required for `illegible` and `not_found`; also used when the
  printed food or category wording differs from the template.

## Pre-declared comparison

Comparison starts only after the custodian has recorded the SHA-256 digest of the
returned file. Both strings are normalised with Unicode NFKC and whitespace
removal. The printed asterisk sets the temporary-limit flag and is compared with
`is_temporary`; the remaining number is compared with `limit_value` by Decimal
equality. A sampled released row is in error when the value or the asterisk
differs, or when it is `not_found`. For an `ocr_only` group, `transcribed`
confirms a row missing from the text layer. `illegible` rows leave the denominator, are
reported separately and are replaced by the next-ranked row of the same stratum.

Each error is adjudicated by the author against the scan page and classified as
a text-layer error, an extraction error or a reviewer misreading. Error rates
are reported per stratum with Clopper-Pearson 95% intervals. The proportional
allocation makes the {RANDOM_SAMPLE_SIZE}-row random sample self-weighting up to
rounding, so the overall rate is the pooled rate over those rows with its
Clopper-Pearson interval; `weight` in the key file supports the weighted check.
The 9 `conflict` rows and 3 `ocr_only` groups are reported as targeted findings,
not as part of the random-sample rate. If one error type occurs twice or more,
the extraction rule is traced, corrected across all rows and the affected
stratum is drawn again.
"""


def redraw_text(strata: list, total: int, first_dir: Path) -> str:
    lines = "\n".join(
        f"| {edition} | {status} | {population:,} | {sample} |"
        for edition, status, _, population, sample in strata
    )
    return f"""# Independent reading of GB 2763-2019 and GB 2763-2021, round 2

- Protocol version: `{PROTOCOL_VERSION}`, redraw step
- Seed: `{SEED}`
- Round 1: `{first_dir.name}`
- Status: awaiting the independent reviewer

## Why a second round

In round 1, 7 of the 288 random rows filed a food under a long food label such
as 豆类蔬菜(食荚豌豆、豌豆(鲜)、菜豆和菜用大豆除外) instead of its category; the
limit values of those rows were correct. The protocol traces an error type found
twice or more, corrects it across all rows and draws the affected strata again.
The extraction rule was corrected in `260716_extract_pesticide_textlayer_scans.py`
(`PARENT_HEADINGS`), which changed the category of 1,019 of the 38,024 pesticide
rows and nothing else, and the release was rebuilt before this draw.

## Draw

The strata with a category error in round 1 are drawn again with the same seed
and the same sample sizes. Rows of the rebuilt release are ranked by SHA-256 of
`{SEED}:<record_id>`; the rows read in round 1 are located by edition, section,
page, position, food and printed value and skipped; the lowest-ranked remaining
rows are taken. The 2021 `consistent` stratum had no error and is not drawn
again. {total} template rows in all.

| Edition | Stratum | Population | Sample |
|---|---|---:|---:|
{lines}

## Reading and comparison

The template, the blindness boundary, the reviewer instructions and the
pre-declared comparison are those of round 1 (`{first_dir.name}/README.md`).
Error rates are reported per stratum with Clopper-Pearson 95% intervals and
pooled over the round-2 rows.
"""


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = args.output_dir
    if output.exists() and any(output.iterdir()):
        print(f"output directory must be empty: {output}", file=sys.stderr)
        return 2
    output.mkdir(parents=True, exist_ok=True)
    try:
        groups, rows = load(args.release_dir)
        linked = link_rows(groups, rows)
        if args.redraw_of:
            sample, strata = redraw(linked, args.redraw_of, args.first_release_dir)
        else:
            sample, strata = draw(linked, groups)
    except AuditError as error:
        print(f"pesticide audit error: {error}", file=sys.stderr)
        return 2

    outputs = {}
    status_rows = linked.sort_values(["version_year", "record_id"])[
        ["record_id", "version_year", "section_number", "crosscheck_status",
         "key_level"]
    ].rename(columns={"version_year": "edition"})
    outputs["status"] = write_csv(
        output / "pesticide_row_crosscheck_status.csv",
        tuple(status_rows.columns), status_rows.to_dict("records"))
    outputs["strata"] = write_csv(
        output / "pesticide_audit_strata.csv",
        ("edition", "stratum", "selection", "population_rows", "sample_rows"),
        [dict(zip(("edition", "stratum", "selection", "population_rows",
                   "sample_rows"), item)) for item in strata])
    sample = sample.rename(columns={"version_year": "edition",
                                    "crosscheck_status": "stratum"})
    outputs["key"] = write_csv(
        output / "pesticide_audit_sample_key.csv", KEY_FIELDS,
        sample[list(KEY_FIELDS)].to_dict("records"))
    template = sample.assign(
        reference_scan_pdf_page=sample["scan_page"].astype(str),
        entry_status="", limit_value_raw="", reviewer_note="",
    )[list(TEMPLATE_FIELDS)]
    outputs["template"] = write_csv(
        output / "pesticide_blind_read_template.csv", TEMPLATE_FIELDS,
        template.to_dict("records"))
    readme = (redraw_text(strata, len(sample), args.redraw_of) if args.redraw_of
              else protocol_text(strata, len(sample)))
    (output / "README.md").write_text(readme, encoding="utf-8")
    manifest = {
        "protocol_version": PROTOCOL_VERSION,
        "seed": SEED,
        "random_sample_size": len(sample) if args.redraw_of else RANDOM_SAMPLE_SIZE,
        "template_rows": len(sample),
        "inputs": {
            name: {"filename": name, "sha256": sha256(args.release_dir / name)}
            for name in ("pesticide_ocr_crosscheck.csv", "pesticide_limits_long.csv")
        },
        "outputs": outputs,
        "readme_sha256": sha256(output / "README.md"),
    }
    if args.redraw_of:
        first = json.loads((args.redraw_of / "audit_manifest.json").read_text())
        manifest["redraw_of"] = {
            "audit_manifest_sha256": sha256(args.redraw_of / "audit_manifest.json"),
            "first_release_pesticide_limits_sha256":
                first["inputs"]["pesticide_limits_long.csv"]["sha256"],
            "strata": [f"{edition}/{status}" for edition, status in REDRAW_STRATA],
        }
    (output / "audit_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"linked {len(linked):,} rows; wrote {len(sample)} template rows: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
