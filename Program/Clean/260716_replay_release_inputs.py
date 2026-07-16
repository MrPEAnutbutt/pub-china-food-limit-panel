#!/usr/bin/env python3
"""Verify and replay the frozen inputs used by the release builder.

The published release previously depended on CSV files in a private processing
directory.  This module locks those inputs by schema, row count, business key,
and SHA-256 digest.  Two member crosswalks can be regenerated exactly from the
project-local long tables.  The legacy GB 2762 recall table can also be
regenerated when the four source PDFs are supplied explicitly.

The taxonomy and alias snapshots have different evidential status:

* ``food_taxonomy.csv`` is a parser-derived representation of normative GB 2762
  Appendix A tables; its source replay lives in
  ``260716_rebuild_food_taxonomy.py``.
* ``category_alias.csv`` contains eight human-authored adjudications, including
  five entries that remain marked ``待核``.  Verification preserves those labels
  and does not promote them to confirmed mappings.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Iterable, Sequence

from release_dependency_utils import (
    DependencyContractError,
    POLLUTANT_FIELDS,
    RELEASE_DEPENDENCY_SPECS,
    read_locked_csv,
    sha256_file,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "Data" / "Interim" / "release_dependencies"
DEFAULT_MYCOTOXIN_LONG = (
    PROJECT_ROOT
    / "Data"
    / "Interim"
    / "mycotoxin_rebuild"
    / "mycotoxin_limits_by_version.csv"
)
DEFAULT_VETDRUG_LONG = (
    PROJECT_ROOT
    / "Data"
    / "Interim"
    / "vetdrug_rebuild"
    / "vetdrug_limits_by_version.csv"
)


ReplayError = DependencyContractError
INPUT_SPECS = RELEASE_DEPENDENCY_SPECS

UPSTREAM_LONG_DIGESTS = {
    "mycotoxin_limits_by_version.csv": (
        "1191fe47dbb3b036e880e7944ae9d0d72a27f19ccac6b138c596d5e74d16a0c6"
    ),
    "vetdrug_limits_by_version.csv": (
        "90c9211355751f1fc90d35562b6a00f89ee95bcb91b133e96938860c73de96d0"
    ),
}

POLLUTANT_SOURCE_DIGESTS = {
    "2012": "8ebbcf11896b5a2684414e6f8d63de8bf4595b3547629a947d4eeda37bfe8647",
    "2017": "3d03a0d9488bfc100d0d6830d370f1607a18a620852c7927a4db289305ce7ade",
    "2022": "7ce8442362405a2b6381811ee6dca5aab75ee0b6613ea11888c2facc60d1ea39",
    "2025": "a8cad4d17354ef28c7dc6dae3dc3c0bde0b1d9315260f8e630b531f0d19966b4",
}

PENDING_ALIAS_IMPACT_AUDIT = {
    "audit_basis": (
        "locked source PDFs and dependencies; each pending row was promoted "
        "alone over the confirmed-only baseline"
    ),
    "confirmed_only_counts": {"category_rows": 260, "member_rows": 390},
    "all_pending_applied_counts": {"category_rows": 256, "member_rows": 390},
    "rows": [
        {
            "source": "麦片、面筋、粥类罐头、带馅面米制品",
            "target": "麦片、面筋、八宝粥罐头、带馅面米制品",
            "category_affected_keys": [
                "铅|麦片面筋粥类罐头带馅面米制品",
                "铅|麦片面筋八宝粥罐头带馅面米制品",
            ],
            "member_affected_keys": [],
            "effect": "two two-edition categories merge into one four-edition stable row",
        },
        {
            "source": "肉及肉制品",
            "target": "肉制品",
            "category_affected_keys": [
                "总砷|肉及肉制品",
                "总砷|肉制品",
                "铬|肉及肉制品",
                "铬|肉制品",
                "镉|肉及肉制品",
                "镉|肉制品",
            ],
            "member_affected_keys": [
                "总砷|肉及肉制品",
                "总砷|肉制品",
                "铬|肉及肉制品",
                "铬|肉制品",
                "镉|肉及肉制品",
                "镉|畜禽内脏",
            ],
            "effect": "renames or merges total-arsenic, chromium, and cadmium keys",
        },
        {
            "source": "畜禽肝脏及其制品",
            "target": "畜禽肝脏",
            "category_affected_keys": ["镉|畜禽肝脏", "镉|畜禽肝脏及其制品"],
            "member_affected_keys": [],
            "effect": "two two-edition categories merge into one four-edition stable row",
        },
        {
            "source": "畜禽肾脏及其制品",
            "target": "畜禽肾脏",
            "category_affected_keys": ["镉|畜禽肾脏", "镉|畜禽肾脏及其制品"],
            "member_affected_keys": [],
            "effect": "two two-edition categories merge into one four-edition stable row",
        },
        {
            "source": "谷物碾磨加工品除外]",
            "target": "谷物碾磨加工品",
            "category_affected_keys": [],
            "member_affected_keys": [],
            "effect": "no effect on the current category or member crosswalk",
        },
    ],
}

YEARS_MYCOTOXIN = ("2005", "2011", "2017")
YEARS_VETDRUG = ("2002", "2019", "2022")
YEARS_POLLUTANT = ("2012", "2017", "2022", "2025")
UNIT_FACTOR = {
    "mg/kg": 1.0,
    "μg/kg": 0.001,
    "µg/kg": 0.001,
    "g/kg": 1000.0,
}
BRACKET = re.compile(r"[\(（\[［]([^\(（\[［\)）\]］]*)[\)）\]］]")


def read_csv(path: str | Path) -> list[dict[str, str]]:
    """Read a UTF-8 CSV while accepting an optional byte-order mark."""

    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv_atomic(
    path: str | Path,
    rows: Iterable[dict[str, object]],
    fields: Sequence[str],
) -> None:
    """Write a deterministic UTF-8-BOM CSV and replace the target atomically."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        with temporary_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=fields, lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def clean(text: str) -> str:
    """Remove layout whitespace from a category or entity label."""

    return re.sub(r"\s+", "", text or "").strip("、,，. ")


def to_mg(value: str, unit: str = "mg/kg") -> float | None:
    """Convert a numeric value to the historical crosswalk comparison scale."""

    if unit not in UNIT_FACTOR:
        raise ReplayError(
            f"member crosswalk cannot convert non-mass-per-mass unit: {unit}"
        )
    try:
        return float(value) * UNIT_FACTOR[unit]
    except (TypeError, ValueError):
        return None


def trend_of(values: Sequence[float | None], bases: set[str]) -> str:
    """Return the historical display label used by the frozen crosswalks."""

    if None in values or len(bases) > 1:
        return "不可比(基准/单位不一致)"
    if len(set(values)) == 1:
        return "稳定"
    return "收紧(变严)" if values[-1] < values[0] else "放松(变松)"


POULTRY = ("鸡", "火鸡", "鸭", "鹅")
MAMMALS = ("牛", "羊", "绵羊", "山羊", "猪", "马", "兔", "鹿")
ANIMAL_PARENT = {animal: "家禽" for animal in POULTRY}
ANIMAL_PARENT.update(
    {
        "家禽": "所有食品动物",
        "鱼": "所有食品动物",
        "虾": "所有食品动物",
        "蜜蜂": "所有食品动物",
        "其他动物": "所有食品动物",
    }
)
ANIMAL_PARENT.update({animal: "所有食品动物" for animal in MAMMALS})
ANIMAL_PARENT["绵羊"] = "羊"
ANIMAL_PARENT["山羊"] = "羊"
ANIMAL_LEAVES = (
    "牛",
    "羊",
    "猪",
    "马",
    "兔",
    "鹿",
    "鸡",
    "火鸡",
    "鸭",
    "鹅",
    "鱼",
    "虾",
    "蜜蜂",
)


def animal_members(label: str) -> set[str]:
    """Expand a target-animal label to covered leaf animals."""

    output: set[str] = set()
    for token in (token for token in label.split("/") if token):
        if token == "所有食品动物":
            output.update(ANIMAL_LEAVES)
        elif token in {"家禽", "禽"}:
            output.update(POULTRY)
        elif token == "其他动物":
            continue
        elif token in {"绵羊", "山羊"}:
            output.add("羊")
        else:
            output.add(token)
    return output


def build_vetdrug_member_crosswalk(
    rows: Sequence[dict[str, str]],
) -> list[dict[str, object]]:
    """Rebuild the veterinary-drug leaf-animal crosswalk."""

    specificity = {
        animal: (
            0
            if animal == "所有食品动物"
            else 1
            if animal in {"家禽", "禽"}
            else 2
        )
        for animal in set(ANIMAL_PARENT) | {"所有食品动物"}
    }
    table: dict[
        tuple[str, str, str], dict[str, tuple[float, str, str]]
    ] = defaultdict(dict)
    seen_specificity: dict[tuple[tuple[str, str, str], str], int] = {}
    for row in rows:
        value = to_mg(row["limit_value"], row["unit"])
        if value is None:
            continue
        tokens = [token for token in row["animal"].split("/") if token]
        row_specificity = min(
            (specificity.get(token, 2) for token in tokens), default=2
        )
        for member in animal_members(row["animal"]):
            key = (row["drug"], member, row["tissue"])
            previous = seen_specificity.get((key, row["year"]), -1)
            if row_specificity >= previous:
                table[key][row["year"]] = (
                    value,
                    row["unit"],
                    row["english"],
                )
                seen_specificity[(key, row["year"])] = row_specificity

    output: list[dict[str, object]] = []
    for (drug, animal, tissue), year_values in sorted(table.items()):
        present = [year for year in YEARS_VETDRUG if year in year_values]
        if len(present) < 2:
            continue
        values = [year_values[year][0] for year in present]
        output.append(
            {
                "drug": drug,
                "english": year_values[present[0]][2],
                "animal": animal,
                "tissue": tissue,
                **{
                    f"v{year}": year_values[year][0] if year in year_values else ""
                    for year in YEARS_VETDRUG
                },
                "unit": "mg/kg(已折算)",
                "trend": trend_of(values, {"—"}),
            }
        )
    order = {"收紧(变严)": 0, "放松(变松)": 1, "稳定": 2}
    output.sort(
        key=lambda row: (
            order.get(str(row["trend"]), 9),
            str(row["drug"]),
            str(row["animal"]),
            str(row["tissue"]),
        )
    )
    return output


def build_mycotoxin_member_crosswalk(
    rows: Sequence[dict[str, str]],
    taxonomy_rows: Sequence[dict[str, str]],
) -> list[dict[str, object]]:
    """Rebuild the mycotoxin member crosswalk from the frozen taxonomy."""

    taxonomy = {
        clean(row["child"]): clean(row["parent"]) for row in taxonomy_rows
    }
    rename = {"植物油": "植物油脂"}
    values: dict[
        tuple[str, str], dict[str, tuple[float | None, list[str], str]]
    ] = defaultdict(dict)
    members: set[tuple[str, str]] = set()
    for row in rows:
        raw = row["food_category"]
        excluded: list[str] = []
        for match in BRACKET.finditer(raw):
            inner = match.group(1)
            if "除" in inner:
                cleaned = re.sub(r"除外?|除", "", inner)
                excluded.extend(
                    clean(part)
                    for part in re.split(r"[、,，]", cleaned)
                    if clean(part)
                )
        base = clean(BRACKET.sub("", raw))
        value = to_mg(row["limit_value"], row["unit"])
        for part in (clean(part) for part in base.split("、")):
            if not part:
                continue
            part = rename.get(part, part)
            values[(row["toxin"], part)][row["year"]] = (
                value,
                excluded,
                raw,
            )
            members.add((row["toxin"], part))
        for excluded_member in excluded:
            members.add((row["toxin"], rename.get(excluded_member, excluded_member)))

    def applies(
        toxin: str, year: str, member: str
    ) -> tuple[float | None, list[str], str] | None:
        cell = values.get((toxin, member), {}).get(year)
        if cell:
            return cell
        node = taxonomy.get(member)
        seen: set[str] = set()
        while node and node not in seen:
            seen.add(node)
            cell = values.get((toxin, node), {}).get(year)
            if cell and member not in cell[1]:
                return cell
            node = taxonomy.get(node)
        return None

    output: list[dict[str, object]] = []
    for toxin, member in sorted(members):
        cells = {
            year: applies(toxin, year, member) for year in YEARS_MYCOTOXIN
        }
        present = [year for year in YEARS_MYCOTOXIN if cells[year]]
        if not present:
            continue
        hosts = {cells[year][2] for year in present if cells[year]}
        numeric_values = [cells[year][0] for year in present if cells[year]]
        if len(present) < 2:
            trend = f"仅{present[0]}版(无跨版对应:该类别被删除或新增)"
        else:
            trend = trend_of(numeric_values, {"—"})
        output.append(
            {
                "toxin": toxin,
                "member": member,
                **{
                    f"v{year}": cells[year][0] if cells[year] else ""
                    for year in YEARS_MYCOTOXIN
                },
                "unit": "mg/kg(已折算)",
                "trend": trend,
                "类别重组": "是" if len(hosts) > 1 else "否",
                **{
                    f"归属{year}": cells[year][2] if cells[year] else ""
                    for year in YEARS_MYCOTOXIN
                },
            }
        )
    order = {"收紧(变严)": 0, "放松(变松)": 1}
    output.sort(
        key=lambda row: (
            order.get(str(row["trend"]), 9),
            str(row["toxin"]),
            str(row["member"]),
        )
    )
    return output


def _verify_upstream_long(path: Path, expected_name: str) -> None:
    if path.name != expected_name:
        raise ReplayError(
            f"upstream long-table filename differs: expected {expected_name}, got {path.name}"
        )
    expected_digest = UPSTREAM_LONG_DIGESTS[expected_name]
    observed_digest = sha256_file(path)
    if observed_digest != expected_digest:
        raise ReplayError(
            f"upstream long-table digest differs for {expected_name}: "
            f"expected {expected_digest}, got {observed_digest}"
        )


def rebuild_member_crosswalks(
    input_dir: Path,
    mycotoxin_long: Path,
    vetdrug_long: Path,
    output_dir: Path,
) -> dict[str, dict[str, object]]:
    """Regenerate both member crosswalks and require byte-identical outputs."""

    taxonomy = read_locked_csv(
        input_dir / "food_taxonomy.csv", INPUT_SPECS["food_taxonomy.csv"]
    )
    _verify_upstream_long(mycotoxin_long, "mycotoxin_limits_by_version.csv")
    _verify_upstream_long(vetdrug_long, "vetdrug_limits_by_version.csv")
    mycotoxin_rows = build_mycotoxin_member_crosswalk(
        read_csv(mycotoxin_long), taxonomy
    )
    vetdrug_rows = build_vetdrug_member_crosswalk(read_csv(vetdrug_long))
    payloads = {
        "member_crosswalk_mycotoxin.csv": mycotoxin_rows,
        "member_crosswalk_vetdrug.csv": vetdrug_rows,
    }
    report: dict[str, dict[str, object]] = {}
    for filename, rows in payloads.items():
        spec = INPUT_SPECS[filename]
        output_path = output_dir / filename
        write_csv_atomic(output_path, rows, spec.fields)
        digest = sha256_file(output_path)
        if digest != spec.sha256:
            raise ReplayError(
                f"replayed output digest differs for {filename}: "
                f"expected {spec.sha256}, got {digest}"
            )
        report[filename] = {"rows": len(rows), "sha256": digest}
    return report


# Historical GB 2762 text parser.  It is retained only to replay the frozen
# recall-backstop table consumed by the coordinate-based pollutant rebuild.
VALUE_SPLIT = re.compile(r"^(.*\S)\s{2,}(\d+)\.\s*$")
VALUE_WHOLE_DECIMAL = re.compile(r"^(.*\S)\s{2,}(\d+\.\d+)\s*$")
VALUE_WHOLE_INTEGER = re.compile(r"^(.*\S)\s{2,}(\d+)\s*$")
FRACTION = re.compile(r"^\s*(\d+)\s*$")
POLLUTANT_NOISE = re.compile(
    r"GB \d|限量|mg/kg|μg|食品类别|^\s*表 |采样方案|第\s*\d+\s*号|发布|实施|页$"
)
DOUBLE_ANALYTES = {"汞", "砷", "亚硝酸盐、硝酸盐", "亚硝酸盐", "硝酸盐"}
ANALYTE_ALIASES = {
    "3-丙二醇": "3-氯-1,2-丙二醇",
    "3-氯-丙二醇": "3-氯-1,2-丙二醇",
    "苯并[a]苘": "苯并[a]苘",
}


def _pdf_text(path: Path) -> list[str]:
    completed = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        capture_output=True,
        check=True,
        timeout=120,
    )
    return completed.stdout.decode("utf-8", "replace").split("\n")


def _clean_pollutant_category(value: str) -> str:
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"^[0-9.]+$", "", value)
    return value.strip()


def _find_fraction(segment: Sequence[str], index: int) -> str:
    for candidate in (index + 1, index + 2):
        if candidate >= len(segment):
            break
        if not segment[candidate].strip():
            continue
        match = FRACTION.match(segment[candidate])
        return match.group(1) if match else ""
    return ""


def _split_dash(category: str) -> tuple[str, bool]:
    if "—" in category:
        return category.replace("—", "").strip(), True
    return category, False


def _parse_pollutant_table(
    segment: Sequence[str], analyte: str, unit: str, is_double: bool
) -> list[tuple[str, str, str, str, str]]:
    output: list[tuple[str, str, str, str, str]] = []
    for index, raw_line in enumerate(segment):
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if (
            POLLUTANT_NOISE.search(line)
            and not VALUE_SPLIT.match(line)
            and not VALUE_WHOLE_DECIMAL.match(line)
        ):
            continue
        decimal = VALUE_WHOLE_DECIMAL.match(line)
        if decimal:
            category, has_dash = _split_dash(
                _clean_pollutant_category(decimal.group(1))
            )
            if category:
                confidence = "review" if is_double or has_dash else "high"
                output.append((analyte, category, decimal.group(2), unit, confidence))
            continue
        split = VALUE_SPLIT.match(line)
        if split:
            category, has_dash = _split_dash(
                _clean_pollutant_category(split.group(1))
            )
            fraction = _find_fraction(segment, index)
            if category:
                if fraction:
                    value = f"{split.group(2)}.{fraction}"
                    confidence = "review" if is_double or has_dash else "high"
                else:
                    value = f"{split.group(2)}.?"
                    confidence = "review"
                output.append((analyte, category, value, unit, confidence))
            continue
        integer = VALUE_WHOLE_INTEGER.match(line)
        if integer:
            category, has_dash = _split_dash(
                _clean_pollutant_category(integer.group(1))
            )
            next_is_fraction = (
                index + 1 < len(segment)
                and FRACTION.match(segment[index + 1]) is not None
            )
            if category and not next_is_fraction:
                confidence = "review" if is_double or has_dash else "high"
                output.append((analyte, category, integer.group(2), unit, confidence))
    return output


def parse_pollutant_version(
    source_path: Path,
) -> list[tuple[str, str, str, str, str]]:
    """Run the historical line-oriented parser for one GB 2762 edition."""

    lines = _pdf_text(source_path)
    headings: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = re.search(r"表\s*\d+\s*食品中(.+?)限量", line)
        if match:
            headings.append((index, match.group(1).strip()))
            continue
        broken = re.search(r"表\s*\d+\s*食品中(\S*)$", line.rstrip())
        if not broken:
            continue
        for neighbour in (index - 1, index + 1, index + 2, index + 3):
            if not 0 <= neighbour < len(lines):
                continue
            suffix = re.match(r"^(\S*?)限量", lines[neighbour].strip())
            if suffix:
                headings.append(
                    (index, (broken.group(1) + suffix.group(1)).strip())
                )
                break
    output: list[tuple[str, str, str, str, str]] = []
    for heading_index, (start, raw_analyte) in enumerate(headings):
        end = (
            headings[heading_index + 1][0]
            if heading_index + 1 < len(headings)
            else len(lines)
        )
        segment = lines[start:end]
        unit = "μg/kg" if any("μg" in line for line in segment) else "mg/kg"
        analyte = ANALYTE_ALIASES.get(
            re.sub(r"\s+", "", raw_analyte),
            re.sub(r"\s+", "", raw_analyte),
        )
        output.extend(
            _parse_pollutant_table(
                segment,
                analyte,
                unit,
                any(
                    analyte == candidate or candidate in analyte
                    for candidate in DOUBLE_ANALYTES
                ),
            )
        )
    return output


def _pollutant_source(source_dir: Path, year: str) -> Path:
    candidates = sorted(
        path
        for path in source_dir.glob(f"GB 2762-{year}*.pdf")
        if "修改单" not in path.name
    )
    if len(candidates) != 1:
        raise ReplayError(
            f"expected one full GB 2762-{year} source, found {len(candidates)}"
        )
    source = candidates[0]
    digest = sha256_file(source)
    expected = POLLUTANT_SOURCE_DIGESTS[year]
    if digest != expected:
        raise ReplayError(
            f"GB 2762-{year} source digest differs: expected {expected}, got {digest}"
        )
    return source


def rebuild_pollutant_legacy(
    source_dir: Path, double_column_path: Path, output_path: Path
) -> dict[str, object]:
    """Regenerate the historical GB 2762 recall-backstop table."""

    double_rows = read_locked_csv(
        double_column_path, INPUT_SPECS["pollutant_doublecol_long.csv"]
    )
    parsed: list[tuple[str, str, str, str, str, str, str]] = []
    for year in YEARS_POLLUTANT:
        source = _pollutant_source(source_dir, year)
        for analyte, category, value, unit, confidence in parse_pollutant_version(
            source
        ):
            parsed.append(
                (year, analyte, category, value, unit, confidence, "")
            )
    parsed = [row for row in parsed if row[1] not in DOUBLE_ANALYTES]
    parsed.extend(
        (
            row["year"],
            row["analyte"],
            row["food_category"],
            row["limit_value"],
            row["unit"],
            row["confidence"],
            row["note"],
        )
        for row in double_rows
    )
    parsed.sort(key=lambda row: (row[0], row[1]))
    rows = [dict(zip(POLLUTANT_FIELDS, row, strict=True)) for row in parsed]
    write_csv_atomic(output_path, rows, POLLUTANT_FIELDS)
    digest = sha256_file(output_path)
    spec = INPUT_SPECS["pollutant_old_path.csv"]
    if digest != spec.sha256:
        raise ReplayError(
            "replayed pollutant legacy digest differs: "
            f"expected {spec.sha256}, got {digest}"
        )
    return {
        "rows": len(rows),
        "sha256": digest,
        "rows_by_year": dict(Counter(row["year"] for row in rows)),
        "confidence": dict(Counter(row["confidence"] for row in rows)),
    }


def verify_bundle(input_dir: Path) -> dict[str, object]:
    """Verify every frozen input and summarize disclosed manual boundaries."""

    files: dict[str, dict[str, object]] = {}
    loaded: dict[str, list[dict[str, str]]] = {}
    for filename, spec in INPUT_SPECS.items():
        rows = read_locked_csv(input_dir / filename, spec)
        loaded[filename] = rows
        files[filename] = {
            "rows": len(rows),
            "sha256": spec.sha256,
            "derivation": spec.derivation,
        }
    alias_status = Counter(row["status"] for row in loaded["category_alias.csv"])
    if alias_status != Counter({"待核": 5, "已确认": 3}):
        raise ReplayError(f"unexpected alias adjudication states: {dict(alias_status)}")
    return {
        "files": files,
        "manual_boundaries": {
            "category_alias_rows": 8,
            "category_alias_confirmed": 3,
            "category_alias_pending_review": 5,
            "pollutant_double_column_sidecar_rows": 241,
            "pollutant_double_column_sidecar_status": (
                "frozen coordinate-parser output; the surviving upstream "
                "generator contains four later category-text repairs and does "
                "not reproduce this archived digest"
            ),
            "member_crosswalks": "fully replayed from locked project-local inputs",
        },
        "source_lineage": {
            "pollutant_source_pdf_sha256": POLLUTANT_SOURCE_DIGESTS,
            "member_crosswalk_upstream_sha256": UPSTREAM_LONG_DIGESTS,
            "archived_generator_sha256": {
                "build_food_taxonomy.py": (
                    "dede1bdf049eb02d2fb4d9e902e2ac716e913fed7e0f4f2ace373e0072fb3052"
                ),
                "build_member_panel_三族.py": (
                    "a4177fabde21d7025d1983dfaff641d9ead429a53e26366ccdbe083c7c923fa6"
                ),
                "build_pollutant_version_panel.py": (
                    "3b983e0f53c374679caca5d5e3887a90c4f6384cb7ee3773e669fce1f3675bc5"
                ),
                "build_pollutant_doublecol.py": (
                    "3d929a7783f99a22e2284df34cad2ec92225374b8b8a87a336eacf876dd1bdc7"
                ),
            },
        },
        "pending_alias_impact_audit": PENDING_ALIAS_IMPACT_AUDIT,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the verification and replay subcommands."""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify", help="verify the frozen input bundle")
    verify.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    verify.add_argument("--report", type=Path)

    members = subparsers.add_parser(
        "rebuild-members", help="rebuild both member crosswalks"
    )
    members.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    members.add_argument(
        "--mycotoxin-long", type=Path, default=DEFAULT_MYCOTOXIN_LONG
    )
    members.add_argument("--vetdrug-long", type=Path, default=DEFAULT_VETDRUG_LONG)
    members.add_argument("--output-dir", type=Path, required=True)

    pollutant = subparsers.add_parser(
        "rebuild-pollutant-legacy",
        help="rebuild the historical GB 2762 recall-backstop table",
    )
    pollutant.add_argument("--source-dir", type=Path, required=True)
    pollutant.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    pollutant.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one fail-closed portable-input operation."""

    args = parse_args(argv)
    if args.command == "verify":
        report = verify_bundle(args.input_dir)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    elif args.command == "rebuild-members":
        report = rebuild_member_crosswalks(
            input_dir=args.input_dir,
            mycotoxin_long=args.mycotoxin_long,
            vetdrug_long=args.vetdrug_long,
            output_dir=args.output_dir,
        )
    else:
        report = rebuild_pollutant_legacy(
            source_dir=args.source_dir,
            double_column_path=args.input_dir / "pollutant_doublecol_long.csv",
            output_path=args.output,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
