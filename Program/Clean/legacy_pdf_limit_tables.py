#!/usr/bin/env python3
"""Legacy GB 2761/2762 text-layer table parser used by frozen rebuilds."""

from __future__ import annotations

from pathlib import Path
import re

from legacy_family_replay import pdftotext_layout


DOUBLE = {"汞", "砷", "亚硝酸盐、硝酸盐", "亚硝酸盐", "硝酸盐"}
VAL_SPLIT = re.compile(r"^(.*\S)\s{2,}(\d+)\.\s*$")
VAL_WHOLE_DEC = re.compile(r"^(.*\S)\s{2,}(\d+\.\d+)\s*$")
VAL_WHOLE_INT = re.compile(r"^(.*\S)\s{2,}(\d+)\s*$")
FRAC = re.compile(r"^\s*(\d+)\s*$")
NOISE = re.compile(
    r"GB \d|限量|mg/kg|μg|食品类别|^\s*表 |采样方案|第\s*\d+\s*号|发布|实施|页$"
)
ANALYTE_ALIAS = {
    "3-丙二醇": "3-氯-1,2-丙二醇",
    "3-氯-丙二醇": "3-氯-1,2-丙二醇",
    "苯并[a]芘": "苯并[a]芘",
}


def clean_category(category: str) -> str:
    category = re.sub(r"\s+", "", category)
    category = re.sub(r"^[0-9.]+$", "", category)
    return category.strip()


def find_fraction(segment: list[str], index: int) -> str:
    for candidate in (index + 1, index + 2):
        if candidate >= len(segment):
            break
        if not segment[candidate].strip():
            continue
        match = FRAC.match(segment[candidate])
        return match.group(1) if match else ""
    return ""


def split_dash(category: str) -> tuple[str, int]:
    if "—" in category:
        return category.replace("—", "").strip(), 1
    return category, 0


def parse_table(
    segment: list[str],
    analyte: str,
    unit: str,
    is_double: bool,
) -> list[tuple[str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str]] = []
    for index, line in enumerate(segment):
        line = line.rstrip()
        if not line.strip():
            continue
        if (
            NOISE.search(line)
            and not VAL_SPLIT.match(line)
            and not VAL_WHOLE_DEC.match(line)
        ):
            continue
        whole_decimal = VAL_WHOLE_DEC.match(line)
        if whole_decimal:
            category, dash = split_dash(clean_category(whole_decimal.group(1)))
            if category:
                confidence = "review" if is_double or dash else "high"
                rows.append(
                    (analyte, category, whole_decimal.group(2), unit, confidence)
                )
            continue
        split_decimal = VAL_SPLIT.match(line)
        if split_decimal:
            category, dash = split_dash(clean_category(split_decimal.group(1)))
            fraction = find_fraction(segment, index)
            if category:
                value = (
                    f"{split_decimal.group(2)}.{fraction}"
                    if fraction
                    else f"{split_decimal.group(2)}.?"
                )
                confidence = "review" if is_double or dash or not fraction else "high"
                rows.append((analyte, category, value, unit, confidence))
            continue
        whole_integer = VAL_WHOLE_INT.match(line)
        if whole_integer:
            category, dash = split_dash(clean_category(whole_integer.group(1)))
            has_fraction = index + 1 < len(segment) and FRAC.match(
                segment[index + 1]
            )
            if category and not has_fraction:
                confidence = "review" if is_double or dash else "high"
                rows.append(
                    (analyte, category, whole_integer.group(2), unit, confidence)
                )
    return rows


def parse_version(
    source_path: str | Path,
    *,
    pdftotext: str = "pdftotext",
) -> list[tuple[str, str, str, str, str]]:
    """Parse printed analyte/category/value rows from one text-layer edition."""

    lines = pdftotext_layout(source_path, executable=pdftotext).split("\n")
    headings: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = re.search(r"表\s*\d+\s*食品中(.+?)限量", line)
        if not match:
            split_heading = re.search(r"表\s*\d+\s*食品中(\S*)$", line.rstrip())
            if split_heading:
                for candidate in (index - 1, index + 1, index + 2, index + 3):
                    if not 0 <= candidate < len(lines):
                        continue
                    continuation = re.match(
                        r"^(\S*?)限量", lines[candidate].strip()
                    )
                    if continuation:
                        headings.append(
                            (
                                index,
                                (
                                    split_heading.group(1) + continuation.group(1)
                                ).strip(),
                            )
                        )
                        break
                continue
        if match:
            headings.append((index, match.group(1).strip()))

    rows: list[tuple[str, str, str, str, str]] = []
    for heading_index, (start, analyte) in enumerate(headings):
        end = (
            headings[heading_index + 1][0]
            if heading_index + 1 < len(headings)
            else len(lines)
        )
        segment = lines[start:end]
        unit = "μg/kg" if any("μg" in line for line in segment) else "mg/kg"
        analyte = re.sub(r"\s+", "", analyte)
        analyte = ANALYTE_ALIAS.get(analyte, analyte)
        is_double = any(analyte == name or name in analyte for name in DOUBLE)
        rows.extend(parse_table(segment, analyte, unit, is_double))
    return rows
