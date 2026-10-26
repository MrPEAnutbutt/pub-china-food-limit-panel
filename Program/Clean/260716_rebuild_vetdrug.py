#!/usr/bin/env python3
"""Rebuild the frozen 2002/2019/2022 veterinary-drug version panel."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import re

from legacy_family_replay import (
    ACQUISITION_FIELDS,
    CSVSpec,
    file_metadata,
    load_locked_csv,
    pdftotext_layout,
    python_environment,
    read_manifest,
    tool_version,
    validate_source_acquisition,
    verify_manifest_source,
    write_csv_atomic,
    write_json_atomic,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "Data" / "Interim" / "vetdrug_rebuild"
DEFAULT_MANIFEST = (
    PROJECT_ROOT / "Data" / "Final" / "china_food_limit_panel_v1" / "source_manifest.csv"
)
MANUAL_2019_SPEC = CSVSpec(
    fields=("drug", "english", "animal", "tissue", "limit_value", "unit", "note"),
    rows=13,
    unique_key=("english", "animal", "tissue"),
    sha256="58d8907398b9c0059b04cbec22c3d184bc3bd578eb47bf3e855eabbe96f69fcb",
)
MANUAL_2022_SPEC = CSVSpec(
    fields=("drug", "english", "animal", "tissue", "limit_value", "unit"),
    rows=122,
    unique_key=("english", "animal", "tissue"),
    sha256="9c12d1a4ee1e198621d4380bb6df09c60705a5985bba2efa345e6aec32d2c628",
)
VETDRUG_2002_SPEC = CSVSpec(
    fields=(
        "year",
        "drug",
        "english",
        "animal_raw",
        "animal",
        "tissue",
        "limit_value",
        "unit",
        "source",
    ),
    rows=551,
    unique_key=("english", "animal", "tissue"),
    sha256="eb846756b187405a430425d25954f7dd68e708f8944d7e82a2aad7ecd142fa78",
)
VETDRUG_2002_QUARANTINE_SPEC = CSVSpec(
    fields=(
        "drug",
        "english",
        "reject",
        "animal_paras",
        "tissue_paras",
        "value_paras",
    ),
    rows=0,
    unique_key=("drug",),
    sha256="b40e78bb867c90976d324d7f6971ca59c86ab36939af1f005f7c337b638bca6b",
)
SOURCE_ACQUISITION_SPEC = CSVSpec(
    fields=ACQUISITION_FIELDS,
    rows=3,
    unique_key=("family", "version_year"),
    sha256="a5e35c1f90b3995cc8fa3f18ddb7fe0377dc21cf868a40b99aeb229f58277ffc",
)
OUTPUT_IDENTITIES = {
    "vetdrug_limits_by_version.csv": (
        1365,
        "c682b212c6ec2f7d1677d582ac8250067953d71edc71aa4403bbaab72d686c60",
    ),
    "vetdrug_strictness_change.csv": (
        657,
        "0d78a6af21539497f35b50dbea0ffe35f452db22d7e3aa89193d949841d61e76",
    ),
}
TISSUE_ALIAS = {
    "可食性组织": "可食组织",
    "其他可食组织": "可食组织",
    "脂": "脂肪",
    "皮+脂肪": "皮+脂",
    "皮/脂": "皮+脂",
    "脂肪/皮": "皮+脂",
    "脂肪+皮": "皮+脂",
    "肌肉+皮": "皮+肉",
    "肉+皮": "皮+肉",
}
ANIMAL_ALIAS = {"其他": "其他动物", "所有动物": "所有食品动物", "禽": "家禽"}
NOTATION = {"＋": "+", "：": ":", "／": "/"}
ANIMAL_VOCAB = {
    "牛",
    "羊",
    "绵羊",
    "山羊",
    "猪",
    "马",
    "兔",
    "鹿",
    "禽",
    "家禽",
    "鸡",
    "火鸡",
    "鸭",
    "鹅",
    "鱼",
    "虾",
    "鲑鱼",
    "鳟鱼",
    "蜜蜂",
    "所有食品动物",
    "其他动物",
    "所有动物",
    "其他",
}
SECTION_2019 = re.compile(r"^\s*(4\.\d+\.\d+)\s+(.+?)\s*（([A-Za-z][^）]*)）")
Row = tuple[str, str, str, str, str, str, str, str, str]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-2002", type=Path, required=True)
    parser.add_argument("--source-2019", type=Path, required=True)
    parser.add_argument("--source-2022", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--vetdrug-2002-long",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "vetdrug_2002_long.csv",
    )
    parser.add_argument(
        "--vetdrug-2002-quarantine",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "vetdrug_2002_quarantine.csv",
    )
    parser.add_argument(
        "--manual-2019",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "vetdrug_2019_manual.csv",
    )
    parser.add_argument(
        "--manual-2022",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "vetdrug_2022_manual.csv",
    )
    parser.add_argument(
        "--source-acquisition",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "source_acquisition.csv",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--pdftotext", default="pdftotext")
    return parser.parse_args(argv)


def normalize_tissue(value: str) -> str:
    for source, replacement in NOTATION.items():
        value = value.replace(source, replacement)
    value = re.sub(r"\s+", "", value)
    return TISSUE_ALIAS.get(value, value)


def normalize_animal(value: str) -> str:
    value = re.sub(r"[（(].*?[)）]", "", re.sub(r"\s+", "", value))
    return "/".join(
        ANIMAL_ALIAS.get(token, token) for token in value.split("/") if token
    )


def is_animal(value: str) -> bool:
    tokens = [
        token
        for token in re.sub(
            r"[（(].*?[)）]", "", re.sub(r"\s+", "", value)
        ).split("/")
        if token
    ]
    return bool(tokens) and all(token in ANIMAL_VOCAB for token in tokens)


def assign_animals(
    drug: str,
    buffer: list[tuple[str, str, str]],
    labels: list[tuple[int, str]],
    quarantine: list[tuple[str, str]],
) -> list[tuple[str, str, str]]:
    row_count = len(buffer)
    markers = sorted(
        [(index, animal, "inline") for index, (animal, _, _) in enumerate(buffer) if animal]
        + [(index, animal, "center") for index, animal in labels],
        key=lambda marker: marker[0],
    )
    if not markers:
        quarantine.append((drug, "表内无任何靶动物"))
        return []
    solutions: list[list[tuple[int, int]]] = []

    def search(marker_index: int, start: int, cuts: list[tuple[int, int]]) -> None:
        if len(solutions) > 1:
            return
        if marker_index == len(markers):
            if start == row_count:
                solutions.append(list(cuts))
            return
        position, _animal, kind = markers[marker_index]
        for end in range(start + 1, row_count + 1):
            size = end - start
            if kind == "inline":
                valid = position == start or (
                    size % 2 == 1 and position == start + size // 2
                )
            else:
                valid = size % 2 == 0 and position == start + size // 2
            if not valid:
                continue
            tissues = [buffer[index][1] for index in range(start, end)]
            if len(set(tissues)) != len(tissues):
                continue
            cuts.append((start, end - 1))
            search(marker_index + 1, end, cuts)
            cuts.pop()

    search(0, 0, [])
    if len(solutions) != 1:
        quarantine.append((drug, f"块切分不唯一({len(solutions)} 解)"))
        return []
    output: list[tuple[str, str, str]] = []
    for (start, end), (_position, animal, _kind) in zip(solutions[0], markers):
        for index in range(start, end + 1):
            output.append((animal, buffer[index][1], buffer[index][2]))
    return output


def extract_2019(
    source_path: Path,
    *,
    pdftotext: str,
) -> tuple[list[Row], list[tuple[str, str]]]:
    lines = [
        line
        for line in pdftotext_layout(
            source_path, executable=pdftotext
        ).split("\n")
        if "....." not in line and "……" not in line
    ]
    rows: list[Row] = []
    quarantine: list[tuple[str, str]] = []
    current_drug: str | None = None
    current_english: str | None = None
    buffer: list[tuple[str, str, str]] = []
    labels: list[tuple[int, str]] = []
    in_table = False
    started = False

    def flush() -> None:
        if current_drug is None or current_english is None:
            return
        for animal, tissue, value in assign_animals(
            current_drug, buffer, labels, quarantine
        ):
            rows.append(
                (
                    "2019",
                    current_drug,
                    current_english,
                    animal,
                    animal,
                    tissue,
                    value,
                    "μg/kg",
                    "text",
                )
            )

    for raw_line in lines:
        line = raw_line.rstrip()
        compact = re.sub(r"\s+", "", line)
        section = SECTION_2019.match(line)
        if section and not re.match(r"^\s*4\.\d+\.\d+\.\d", line):
            if buffer:
                flush()
            buffer = []
            labels = []
            current_drug = re.sub(r"\s+", "", section.group(2))
            current_english = re.sub(r"\s+", "", section.group(3)).lower()
            in_table = False
            started = True
            continue
        if not started:
            continue
        if "靶组织" in compact or ("残留限量" in compact and "应符合" not in compact):
            in_table = True
            continue
        if not in_table:
            continue
        if re.match(r"^\s*4\.\d+\.\d+", line):
            in_table = False
            continue
        value_match = re.search(r"(\d+(?:\.\d+)?)\s*$", line)
        if not value_match:
            if compact and is_animal(compact):
                labels.append((len(buffer), compact))
            continue
        value = value_match.group(1)
        parts = [
            part.strip()
            for part in re.split(r"\s{2,}", line[: value_match.start()].strip())
            if part.strip()
        ]
        if not parts:
            continue
        tissue = re.sub(r"\s+", "", parts[-1])
        animal = re.sub(r"\s+", "", parts[0]) if len(parts) >= 2 else ""
        if not re.search(r"[一-鿿]", tissue):
            continue
        previous = next(
            (buffer[index][0] for index in range(len(buffer) - 1, -1, -1) if buffer[index][0]),
            "",
        )
        # A label wrapped inside its cell, or across a page break, leaves the
        # previous label with an unclosed bracket; the next row carries the rest.
        unclosed = previous.count("（") + previous.count("(") > (
            previous.count("）") + previous.count(")")
        )
        if animal.startswith(("（", "(")) or (animal and unclosed):
            for index in range(len(buffer) - 1, -1, -1):
                if buffer[index][0]:
                    buffer[index] = (
                        buffer[index][0] + animal,
                        buffer[index][1],
                        buffer[index][2],
                    )
                    break
            animal = ""
        buffer.append((animal, tissue, value))
    if buffer:
        flush()
    return rows, quarantine


def build_rows(
    automatic_2019: list[Row],
    manual_2019: list[dict[str, str]],
    manual_2022: list[dict[str, str]],
    rows_2002: list[dict[str, str]],
) -> list[Row]:
    rows = list(automatic_2019)
    rows.extend(
        (
            "2019",
            row["drug"],
            row["english"].lower(),
            row["animal"],
            row["animal"],
            row["tissue"],
            row["limit_value"],
            row["unit"],
            "manual",
        )
        for row in manual_2019
    )
    rows.extend(
        (
            "2002",
            row["drug"],
            row["english"],
            row["animal_raw"],
            row["animal"],
            row["tissue"],
            row["limit_value"],
            row["unit"],
            "docx-block",
        )
        for row in rows_2002
    )
    rows.extend(
        (
            "2022",
            row["drug"],
            row["english"].lower(),
            row["animal"],
            row["animal"],
            row["tissue"],
            row["limit_value"],
            row["unit"],
            "manual",
        )
        for row in manual_2022
    )
    return [
        (
            year,
            chinese,
            english,
            animal_raw,
            normalize_animal(animal),
            normalize_tissue(tissue),
            value,
            unit,
            source,
        )
        for year, chinese, english, animal_raw, animal, tissue, value, unit, source in rows
    ]


def build_panel(rows: list[Row]) -> list[list[str]]:
    panel: defaultdict[tuple[str, str], defaultdict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    display_name: dict[str, str] = {}

    def english_key(value: str) -> str:
        return re.sub(r"[^a-z]", "", value.lower())

    for year, chinese, english, _raw, _animal, tissue, value, _unit, _source in rows:
        key = (english_key(english), tissue)
        panel[key][year].add(value)
        display_name.setdefault(key[0], chinese)

    output: list[list[str]] = []
    for (english, tissue), year_values in panel.items():
        if not english:
            continue
        values_2002 = sorted(year_values.get("2002", []), key=float)
        values_2019 = sorted(year_values.get("2019", []), key=float)
        if values_2002 and values_2019:
            if len(values_2002) == 1 and len(values_2019) == 1:
                first = float(values_2002[0])
                last = float(values_2019[0])
                trend = (
                    "稳定"
                    if first == last
                    else ("收紧(变严)" if last < first else "放松(变松)")
                )
            else:
                trend = "多动物待核"
        elif values_2019:
            trend = "仅2019(新增/2002无)"
        else:
            trend = "仅2002(2019删/未对上)"
        output.append(
            [
                display_name.get(english, english),
                english,
                tissue,
                "/".join(values_2002),
                "/".join(values_2019),
                trend,
            ]
        )
    order = {
        "收紧(变严)": 0,
        "放松(变松)": 1,
        "多动物待核": 2,
        "稳定": 3,
        "仅2019(新增/2002无)": 4,
        "仅2002(2019删/未对上)": 5,
    }
    output.sort(key=lambda row: (order.get(row[5], 9), row[1]))
    return output


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    manifest_rows = read_manifest(args.source_manifest)
    source_paths = {
        "2002": args.source_2002,
        "2019": args.source_2019,
        "2022": args.source_2022,
    }
    source_metadata = [
        verify_manifest_source(
            source_paths[year],
            manifest_rows,
            family="veterinary_drug",
            version_year=year,
        )
        for year in ("2002", "2019", "2022")
    ]
    acquisition_rows = load_locked_csv(
        args.source_acquisition, SOURCE_ACQUISITION_SPEC
    )
    validate_source_acquisition(acquisition_rows, source_metadata)
    manual_2019 = load_locked_csv(args.manual_2019, MANUAL_2019_SPEC)
    manual_2022 = load_locked_csv(args.manual_2022, MANUAL_2022_SPEC)
    rows_2002 = load_locked_csv(args.vetdrug_2002_long, VETDRUG_2002_SPEC)
    quarantine_2002 = load_locked_csv(
        args.vetdrug_2002_quarantine, VETDRUG_2002_QUARANTINE_SPEC
    )
    automatic_2019, quarantine_2019 = extract_2019(
        args.source_2019, pdftotext=args.pdftotext
    )
    if len(quarantine_2019) != 2 or {drug for drug, _reason in quarantine_2019} != {
        "环丙氨嗪",
        "二硝托胺",
    }:
        raise ValueError(f"unexpected 2019 quarantine: {quarantine_2019}")
    rows = build_rows(automatic_2019, manual_2019, manual_2022, rows_2002)
    panel_rows = build_panel(rows)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    limits_name = "vetdrug_limits_by_version.csv"
    limits_count, limits_digest = OUTPUT_IDENTITIES[limits_name]
    limits_metadata = write_csv_atomic(
        args.output_dir / limits_name,
        (
            "year",
            "drug",
            "english",
            "animal_raw",
            "animal",
            "tissue",
            "limit_value",
            "unit",
            "source",
        ),
        rows,
        expected_rows=limits_count,
        expected_sha256=limits_digest,
    )
    panel_name = "vetdrug_strictness_change.csv"
    panel_count, panel_digest = OUTPUT_IDENTITIES[panel_name]
    panel_metadata = write_csv_atomic(
        args.output_dir / panel_name,
        ("drug", "english", "tissue", "v2002", "v2019", "trend"),
        panel_rows,
        expected_rows=panel_count,
        expected_sha256=panel_digest,
    )

    report = {
        "schema_version": 1,
        "pipeline": "vetdrug_rebuild",
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
                **file_metadata(args.vetdrug_2002_long),
                "rows": len(rows_2002),
                "role": "word_table_rebuild",
            },
            {
                **file_metadata(args.vetdrug_2002_quarantine),
                "rows": len(quarantine_2002),
                "role": "word_table_quarantine",
            },
            {
                **file_metadata(args.manual_2019),
                "rows": len(manual_2019),
                "role": "manual_page_break_seed",
            },
            {
                **file_metadata(args.manual_2022),
                "rows": len(manual_2022),
                "role": "manual_scan_transcription_seed",
            },
        ],
        "checks": {
            "rows_per_version": dict(Counter(row[0] for row in rows)),
            "rows_per_source": dict(Counter(row[8] for row in rows)),
            "drugs_per_version": {
                year: len({row[1] for row in rows if row[0] == year})
                for year in ("2002", "2019", "2022")
            },
            "blank_animal_rows": sum(not row[4] for row in rows),
            "automatic_2019_quarantine": [
                {"drug": drug, "reason": reason}
                for drug, reason in quarantine_2019
            ],
            "manual_seeds_required": True,
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
                "The replay verifies the three source identities, reuses the "
                "locked 2019 and 2022 manual seeds plus the deterministic 2002 "
                "Word-table output, and rebuilds the family long table and panel. "
                "It does not independently recreate the manual seeds from the PDFs."
            ),
        },
        "provenance_gap": {
            "status": "open",
            "records": len(manual_2019) + len(manual_2022),
            "description": (
                "The 2019 page-break and 2022 scan seeds are single-author "
                "construction passes without an independent second transcription."
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
    write_json_atomic(args.output_dir / "vetdrug_replay_report.json", report)
    print(
        f"veterinary-drug replay passed: {len(rows)} limits, "
        f"{len(panel_rows)} category-level groups"
    )


if __name__ == "__main__":
    main()
