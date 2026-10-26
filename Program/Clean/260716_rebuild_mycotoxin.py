#!/usr/bin/env python3
"""Rebuild the frozen GB 2761 long table and category-level panel."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import re
import unicodedata

from legacy_family_replay import (
    ACQUISITION_FIELDS,
    CSVSpec,
    file_metadata,
    load_locked_csv,
    python_environment,
    read_manifest,
    tool_version,
    validate_source_acquisition,
    verify_manifest_source,
    write_csv_atomic,
    write_json_atomic,
)
from legacy_pdf_limit_tables import parse_version as parse_text_version


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "Data" / "Interim" / "mycotoxin_rebuild"
DEFAULT_MANIFEST = (
    PROJECT_ROOT / "Data" / "Final" / "china_food_limit_panel_v1" / "source_manifest.csv"
)
YEARS = ("2005", "2011", "2017")
TOXINS = (
    "黄曲霉毒素B1",
    "黄曲霉毒素M1",
    "脱氧雪腐镰刀菌烯醇",
    "展青霉素",
    "赭曲霉毒素A",
    "玉米赤霉烯酮",
)
MANUAL_2005_SPEC = CSVSpec(
    fields=("toxin", "food_category", "limit_value", "unit"),
    rows=9,
    unique_key=("toxin", "food_category"),
    sha256="209d99250e4555a2cf68addb22a49549e0edfb158f43f3cc94601f92d1883b9d",
)
SOURCE_ACQUISITION_SPEC = CSVSpec(
    fields=ACQUISITION_FIELDS,
    rows=3,
    unique_key=("family", "version_year"),
    sha256="9a98d09b401677f85055d93a849f90fceb0c50f680520a74c4a91919ee5f253e",
)
OUTPUT_IDENTITIES = {
    "mycotoxin_limits_by_version.csv": (
        61,
        "1191fe47dbb3b036e880e7944ae9d0d72a27f19ccac6b138c596d5e74d16a0c6",
    ),
    "mycotoxin_strictness_change.csv": (
        40,
        "52de1ec46c2819afbbbeebd189cef8fcec1ea910a723a28924d1505dd8c85e61",
    ),
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-2005", type=Path, required=True)
    parser.add_argument("--source-2011", type=Path, required=True)
    parser.add_argument("--source-2017", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--manual-2005",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "myco2005_manual.csv",
    )
    parser.add_argument(
        "--source-acquisition",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "source_acquisition.csv",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--pdftotext", default="pdftotext")
    return parser.parse_args(argv)


def canonical_toxin(value: str) -> str | None:
    compact = re.sub(r"\s+", "", value)
    for toxin in TOXINS:
        core = toxin.replace("黄曲霉毒素", "").replace("毒素", "")
        if toxin in compact or (core and core in compact):
            return toxin
    return None


def canonical_food(value: str) -> str:
    value = re.sub(r"[\(（].*?[\)）]", "", value)
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[a-zA-Z]+$", "", value).replace("P", "")
    value = value.strip("、,.")
    return value.strip()


def scope_text(category: str) -> str:
    """Printed category with typography and list separators removed."""

    return re.sub(r"[\s、,，]", "", unicodedata.normalize("NFKC", category))


def numeric(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def build_long_rows(
    sources: dict[str, Path],
    manual_rows: list[dict[str, str]],
    *,
    pdftotext: str,
) -> tuple[list[tuple[str, ...]], Counter[str]]:
    long_rows: list[tuple[str, ...]] = []
    per_version: Counter[str] = Counter()
    for year in YEARS:
        if year == "2005":
            parsed = [
                (
                    canonical_toxin(row["toxin"]) or row["toxin"],
                    row["food_category"],
                    row["limit_value"],
                    row["unit"],
                    "manual",
                )
                for row in manual_rows
            ]
        else:
            parsed = []
            for analyte, category, value, unit, confidence in parse_text_version(
                sources[year], pdftotext=pdftotext
            ):
                toxin = canonical_toxin(analyte)
                if toxin:
                    parsed.append((toxin, category, value, unit, confidence))
        per_version[year] = len(parsed)
        long_rows.extend((year, *row) for row in parsed)
    return long_rows, per_version


def build_panel_rows(long_rows: list[tuple[str, ...]]) -> list[list[str]]:
    panel: defaultdict[tuple[str, str], dict[str, tuple[str, str, str]]] = defaultdict(
        dict
    )
    rules: Counter[tuple[str, str, str]] = Counter()
    for year, toxin, category, value, _unit, confidence in long_rows:
        food_key = canonical_food(category)
        if food_key:
            rules[(toxin, food_key, year)] += 1
        if food_key and year not in panel[(toxin, food_key)]:
            panel[(toxin, food_key)][year] = (value, category, confidence)

    change_rows: list[list[str]] = []
    for (toxin, food_key), year_values in panel.items():
        present = [year for year in YEARS if year in year_values]
        cells = {year: year_values[year][0] for year in present}
        raw_category = year_values[present[0]][1]
        text_values = [
            (year, numeric(cells[year]))
            for year in present
            if year != "2005" and numeric(cells[year]) is not None
        ]
        compared = [year for year, _ in text_values]
        if len(present) == 1:
            trend = "单版本"
        elif len(text_values) >= 2 and any(
            rules[(toxin, food_key, year)] > 1 for year in compared
        ):
            trend = "不可比(同版多规则)"
        elif len(text_values) >= 2 and len(
            {scope_text(year_values[year][1]) for year in compared}
        ) > 1:
            trend = "不可比(范围文字不同)"
        elif len(text_values) >= 2:
            first = text_values[0][1]
            last = text_values[-1][1]
            trend = (
                "稳定"
                if first == last
                else ("收紧(变严)" if last < first else "放松(变松)")
            )
        else:
            trend = "仅部分版本"
        note_2005 = "review" if "2005" in present else ""
        change_rows.append(
            [
                toxin,
                raw_category,
                food_key,
                cells.get("2005", ""),
                cells.get("2011", ""),
                cells.get("2017", ""),
                trend,
                note_2005,
                *(year_values[year][1] if year in year_values else "" for year in YEARS),
            ]
        )

    order = {
        "收紧(变严)": 0,
        "放松(变松)": 1,
        "稳定": 2,
        "仅部分版本": 3,
        "单版本": 4,
    }
    change_rows.sort(key=lambda row: (order.get(row[6], 9), row[0], row[2]))
    return change_rows


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    manifest_rows = read_manifest(args.source_manifest)
    sources = {
        "2005": args.source_2005,
        "2011": args.source_2011,
        "2017": args.source_2017,
    }
    source_metadata = [
        verify_manifest_source(
            sources[year], manifest_rows, family="mycotoxin", version_year=year
        )
        for year in YEARS
    ]
    acquisition_rows = load_locked_csv(
        args.source_acquisition, SOURCE_ACQUISITION_SPEC
    )
    validate_source_acquisition(acquisition_rows, source_metadata)
    manual_rows = load_locked_csv(args.manual_2005, MANUAL_2005_SPEC)
    long_rows, per_version = build_long_rows(
        sources, manual_rows, pdftotext=args.pdftotext
    )
    panel_rows = build_panel_rows(long_rows)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    limits_name = "mycotoxin_limits_by_version.csv"
    limits_rows, limits_digest = OUTPUT_IDENTITIES[limits_name]
    limits_metadata = write_csv_atomic(
        args.output_dir / limits_name,
        ("year", "toxin", "food_category", "limit_value", "unit", "confidence"),
        long_rows,
        expected_rows=limits_rows,
        expected_sha256=limits_digest,
    )
    panel_name = "mycotoxin_strictness_change.csv"
    panel_count, panel_digest = OUTPUT_IDENTITIES[panel_name]
    panel_metadata = write_csv_atomic(
        args.output_dir / panel_name,
        (
            "toxin",
            "food_raw",
            "food_canon",
            "v2005",
            "v2011",
            "v2017",
            "trend",
            "note2005",
            "raw2005",
            "raw2011",
            "raw2017",
        ),
        panel_rows,
        expected_rows=panel_count,
        expected_sha256=panel_digest,
    )

    report = {
        "schema_version": 1,
        "pipeline": "mycotoxin_rebuild",
        "status": "pass",
        "environment": {
            **python_environment(),
            "pdftotext": tool_version([args.pdftotext, "-v"]),
        },
        "source_manifest": file_metadata(args.source_manifest),
        "sources": source_metadata,
        "source_acquisition": {
            **file_metadata(args.source_acquisition),
            "rows": len(acquisition_rows),
            "identity_verified": True,
        },
        "frozen_inputs": [
            {
                **file_metadata(args.manual_2005),
                "rows": len(manual_rows),
                "role": "manual_transcription_seed",
            }
        ],
        "checks": {
            "rows_per_version": dict(per_version),
            "manual_seed_required": True,
            "source_identity_verified": True,
            "output_identity_verified": True,
        },
        "outputs": [limits_metadata, panel_metadata],
        "replay_scope": {
            "manual_seed_replay": True,
            "downstream_rebuild": True,
            "manual_seed_reextraction": False,
            "independent_retranscription": False,
            "description": (
                "The replay verifies source identities, reuses the locked 2005 "
                "manual seed, reparses text-layer editions, and rebuilds the "
                "long table and panel. It does not recreate or independently "
                "retranscribe the 2005 seed from page images."
            ),
        },
        "provenance_gap": {
            "status": "open",
            "records": 9,
            "description": (
                "The 2005 manual seed is a single-author construction pass and "
                "does not contain an independent second transcription."
            ),
            "missing_fields": [
                "source_page",
                "source_table",
                "printed_row",
                "independent_reviewer",
                "review_date",
            ],
        },
    }
    write_json_atomic(args.output_dir / "mycotoxin_replay_report.json", report)
    print(
        f"mycotoxin replay passed: {len(long_rows)} limits, "
        f"{len(panel_rows)} aligned categories"
    )


if __name__ == "__main__":
    main()
