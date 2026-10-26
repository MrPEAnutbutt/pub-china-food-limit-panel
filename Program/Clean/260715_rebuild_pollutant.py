#!/usr/bin/env python3
"""Rebuild the GB 2762 long table and member panel with parser safeguards.

The source PDFs have two layouts that defeat line-oriented extraction:

* a continued table can share a page with the title of the next table;
* category, value, unit, and basis text can occupy different visual lines.

This script keeps the validated legacy text extraction as a recall backstop,
re-runs a coordinate-based parser from the source PDFs, rejects malformed
categories before the two paths are merged, and derives members with a
bracket-depth parser.  All outputs are derived data and therefore go only to
``Data/Interim/pollutant_rebuild`` by default.
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import re
import subprocess
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from release_dependency_utils import (
    RELEASE_DEPENDENCY_SPECS,
    read_locked_csv,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "Data" / "Interim" / "pollutant_rebuild"
DEFAULT_DEPENDENCY_DIR = (
    PROJECT_ROOT / "Data" / "Interim" / "release_dependencies"
)

YEARS = ("2012", "2017", "2022", "2025")
NS = "{http://www.w3.org/1999/xhtml}"
TWOCOL = (
    ("总汞", "甲基汞", True),
    ("总砷", "无机砷", True),
    ("亚硝酸盐", "硝酸盐", False),
)
ANALYTE_ALIAS = {
    "3-丙二醇": "3-氯-1,2-丙二醇",
    "3-氯-丙二醇": "3-氯-1,2-丙二醇",
}
BASIS_PATTERNS = (
    ("干重计", "干重计"),
    ("固态产品计", "固态产品计"),
    ("粉状产品计", "粉状产品计"),
    ("以脂肪计", "以脂肪计"),
    ("即食状态计", "即食状态计"),
)
BRACKETS = {"(": ")", "（": "）", "[": "]", "［": "］"}
CLOSERS = set(BRACKETS.values())
DASH = re.compile(r"^[—–\-]+$")
HAS_NUMBER = re.compile(r"\d")
NOISE = re.compile(
    r"GB\s*\d{4}|食品类别|限量指标|见表|检验方法|^\d+\.\d|^表\s*\d|注:|^[a-z]$"
)
UNIT_ALIASES = (
    ("μg/kg", "μg/kg"),
    ("ug/kg", "μg/kg"),
    ("mg/kg", "mg/kg"),
    ("mg/L", "mg/L"),
)
MASS_FACTORS = {"mg/kg": 1.0, "μg/kg": 0.001, "g/kg": 1000.0}
ALIAS_FIELDS = ("异名", "规范名", "status", "说明")
ALIAS_STATUSES = {"已确认", "待核"}
CONTAINMENT_FIELDS = ("成员", "上级", "status", "说明")
CONTAINMENT_STATUSES = {"已确认", "待核", "否决"}

Word = tuple[float, float, float, float, str]


@dataclass(frozen=True)
class TableState:
    """Geometry that can be carried to a title-less continuation page."""

    analyte: str
    kind: str = ""
    unit: str = ""
    category_boundary: float | None = None
    split_x: float | None = None
    left_name: str = ""
    right_name: str = ""
    exclusive: bool = False


def word_center(word: Word) -> float:
    return (word[0] + word[1]) / 2.0


def cluster_rows(
    words: list[Word], tol: float = 9.0, maxspan: float | None = None
) -> list[list[Word]]:
    words = sorted(words, key=lambda word: word[2])
    rows: list[list[Word]] = []
    current: list[Word] = []
    last_y: float | None = None
    for word in words:
        if last_y is not None and (
            word[2] - last_y > tol
            or (maxspan is not None and word[2] - current[0][2] > maxspan)
        ):
            rows.append(current)
            current = []
        current.append(word)
        last_y = word[2]
    if current:
        rows.append(current)
    return rows


def line_text(words: list[Word]) -> str:
    return "".join(word[4] for word in sorted(words, key=lambda word: word[0]))


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def clean_category(text: str) -> str:
    text = compact(text).replace("P", "")
    text = re.sub(r"(?<![A-Za-z])[a-e](?![A-Za-z])", "", text)
    return text.strip()


def bracket_error(text: str) -> str:
    stack: list[str] = []
    for char in text:
        if char in BRACKETS:
            stack.append(BRACKETS[char])
        elif char in CLOSERS:
            if not stack:
                return "leading_or_unmatched_closing_bracket"
            if stack.pop() != char:
                return "mismatched_brackets"
    return "unclosed_bracket" if stack else ""


def category_error(category: str) -> str:
    if not category:
        return "empty_category"
    if category[0] in "、,，.;；:：" or category[0] in CLOSERS:
        return "leading_separator_or_closing_bracket"
    if category[0] in BRACKETS:
        return "missing_category_head"
    error = bracket_error(category)
    if error:
        return error
    if not re.search(r"[一-鿿]", category):
        return "category_without_chinese_text"
    if NOISE.search(category):
        return "header_or_note_text"
    return ""


def bracket_depth(text: str) -> int | None:
    stack: list[str] = []
    for char in text:
        if char in BRACKETS:
            stack.append(BRACKETS[char])
        elif char in CLOSERS:
            if not stack or stack.pop() != char:
                return None
    return len(stack)


def merge_continued_category_rows(
    rows: list[list[Word]], max_gap: float = 24.0
) -> list[list[Word]]:
    """Join adjacent visual lines while an outer category bracket is open."""

    merged: list[list[Word]] = []
    index = 0
    while index < len(rows):
        block = list(rows[index])
        index += 1
        depth = bracket_depth(clean_category(line_text(block)))
        while depth and index < len(rows):
            last_y = max(word[2] for word in block)
            next_y = min(word[2] for word in rows[index])
            if next_y - last_y > max_gap:
                break
            block.extend(rows[index])
            index += 1
            depth = bracket_depth(clean_category(_visual_text(block)))
        merged.append(block)
    return merged


def _visual_text(words: list[Word]) -> str:
    return "".join(
        line_text(row) for row in cluster_rows(words, tol=6.0)
    )


def bbox_pages(path: Path) -> list[list[Word]]:
    completed = subprocess.run(
        ["pdftotext", "-bbox-layout", str(path), "-"],
        capture_output=True,
        check=True,
        timeout=300,
    )
    root = ET.fromstring(completed.stdout.decode("utf-8", "replace"))
    pages: list[list[Word]] = []
    for page in root.iter(NS + "page"):
        words = [
            (
                float(word.get("xMin")),
                float(word.get("xMax")),
                float(word.get("yMin")),
                float(word.get("yMax")),
                (word.text or "").strip(),
            )
            for word in page.iter(NS + "word")
            if (word.text or "").strip()
        ]
        pages.append(words)
    return pages


def find_tables(words: list[Word]) -> list[tuple[str, float, float]]:
    rows = cluster_rows(words)
    marks: list[tuple[float, str]] = []
    for index, row in enumerate(rows):
        text = line_text(row)
        match = re.search(r"表\s*\d+\s*食品中(.+?)限量", text)
        if match:
            marks.append((min(word[2] for word in row), match.group(1).strip()))
            continue
        broken = re.search(r"表\s*\d+\s*食品中(\S*)$", text)
        if not broken:
            continue
        for neighbour in (index - 1, index + 1, index + 2):
            if not 0 <= neighbour < len(rows):
                continue
            suffix = re.match(r"^(\S*?)限量", line_text(rows[neighbour]))
            if suffix:
                marks.append(
                    (
                        min(word[2] for word in row),
                        (broken.group(1) + suffix.group(1)).strip(),
                    )
                )
                break
    marks.sort()
    tables: list[tuple[str, float, float]] = []
    for index, (start_y, analyte) in enumerate(marks):
        end_y = marks[index + 1][0] if index + 1 < len(marks) else float("inf")
        analyte = ANALYTE_ALIAS.get(compact(analyte), compact(analyte))
        tables.append((analyte, start_y, end_y))
    return tables


def find_two_column_header(
    words: list[Word],
) -> tuple[Word, Word, str, str, bool] | None:
    for left_name, right_name, exclusive in TWOCOL:
        for left in (word for word in words if word[4] == left_name):
            right_words = [
                word
                for word in words
                if word[4] == right_name
                and abs(word[2] - left[2]) < 6
                and word[0] > left[1]
            ]
            if right_words:
                right = min(right_words, key=lambda word: word[0])
                return left, right, left_name, right_name, exclusive
    return None


def canonical_unit(text: str) -> str:
    text = compact(text)
    for spelling, canonical in UNIT_ALIASES:
        if spelling in text:
            return canonical
    return ""


def find_unit_header(words: list[Word]) -> tuple[str, float, float] | None:
    candidates: list[tuple[float, str, float, float]] = []
    for row in cluster_rows(words, tol=4.0):
        text = compact(line_text(row))
        unit = canonical_unit(text)
        if not unit:
            continue
        unit_words = [
            word
            for word in row
            if re.search(r"[mμugk/L]", compact(word[4]), flags=re.IGNORECASE)
        ]
        if not unit_words:
            continue
        center = sum(word_center(word) for word in unit_words) / len(unit_words)
        header_y = min(word[2] for word in row)
        # Some GB 2762 header glyph boxes extend into the first data row.
        # Cutting at yMax drops that row (for example, 2017 lead 0.15).
        candidates.append((header_y, unit, center, header_y + 4.0))
    if not candidates:
        return None
    start_y, unit, center, end_y = min(candidates, key=lambda item: item[0])
    return unit, center, end_y


def has_continuation_header(words: list[Word]) -> bool:
    text = compact("".join(line_text(row) for row in cluster_rows(words)))
    return "续" in text and bool(find_unit_header(words) or find_two_column_header(words))


def basis_from_text(text: str) -> str:
    text = compact(text).replace("P", "").replace("R", "")
    for pattern, label in BASIS_PATTERNS:
        if pattern in text:
            return label
    return ""


def parse_value(text: str) -> str:
    text = compact(text).replace("—", "")
    match = re.match(r"^(\d+(?:\.\d+)?)", text)
    return match.group(1) if match else ""


def rows_from(
    words: list[Word], category_boundary: float
) -> list[tuple[str, list[Word], float]]:
    value_words = [
        word
        for word in words
        if word_center(word) >= category_boundary
        and not re.fullmatch(r"[A-Za-z]", word[4])
    ]
    category_words = [word for word in words if word_center(word) < category_boundary]
    value_rows: list[tuple[list[Word], float]] = []
    for row in cluster_rows(value_words, maxspan=12.0):
        ys = sorted(word[2] for word in row)
        value_rows.append((row, ys[len(ys) // 2]))

    buckets: dict[int, list[Word]] = {index: [] for index in range(len(value_rows))}
    taken: set[int] = set()
    category_rows = merge_continued_category_rows(cluster_rows(category_words))
    for pass_index, tolerance in ((0, 10.0), (1, 18.0)):
        for category_index, category_row in enumerate(category_rows):
            if category_index in taken or not value_rows:
                continue
            anchor = min(word[2] for word in category_row)
            value_index = min(
                range(len(value_rows)),
                key=lambda index: abs(anchor - value_rows[index][1]),
            )
            if abs(anchor - value_rows[value_index][1]) > tolerance:
                continue
            if pass_index == 1 and buckets[value_index]:
                continue
            buckets[value_index].extend(category_row)
            taken.add(category_index)

    output: list[tuple[str, list[Word], float]] = []
    for index, (value_row, anchor) in enumerate(value_rows):
        category = clean_category(_visual_text(buckets[index]))
        if not category or NOISE.search(category):
            continue
        output.append((category, value_row, anchor))
    return output


def cell_context(
    words: list[Word], lower_y: float, upper_y: float, lower_x: float, upper_x: float
) -> str:
    context = [
        word
        for word in words
        if lower_y <= word[2] < upper_y
        and lower_x <= word_center(word) <= upper_x
    ]
    return _visual_text(context)


def parse_segment(
    words: list[Word], year: str, analyte: str, prior: TableState | None
) -> tuple[list[dict[str, str]], TableState]:
    rows: list[dict[str, str]] = []
    pair = find_two_column_header(words)
    if pair:
        left, right, left_name, right_name, exclusive = pair
        split_x = (left[1] + right[0]) / 2.0
        category_boundary = 2 * word_center(left) - split_x
        body_start = max(left[3], right[3]) + 1.0
        state = TableState(
            analyte=analyte,
            kind="two-column",
            unit="mg/kg",
            category_boundary=category_boundary,
            split_x=split_x,
            left_name=left_name,
            right_name=right_name,
            exclusive=exclusive,
        )
    elif prior and prior.analyte == analyte and prior.kind == "two-column":
        state = prior
        body_start = 0.0
    else:
        header = find_unit_header(words)
        if header:
            unit, unit_center, body_start = header
            state = TableState(
                analyte=analyte,
                kind="single-column",
                unit=unit,
                category_boundary=unit_center - 70.0,
            )
        elif prior and prior.analyte == analyte and prior.kind == "single-column":
            state = prior
            body_start = 0.0
        else:
            return rows, TableState(analyte=analyte)

    body = [word for word in words if word[2] > body_start]
    if state.category_boundary is None:
        return rows, state
    aligned_rows = rows_from(body, state.category_boundary)
    for row_index, (category, value_row, anchor) in enumerate(aligned_rows):
        previous_anchor = aligned_rows[row_index - 1][2] if row_index else None
        next_anchor = (
            aligned_rows[row_index + 1][2]
            if row_index + 1 < len(aligned_rows)
            else None
        )
        lower_y = (
            (previous_anchor + anchor) / 2.0
            if previous_anchor is not None
            else anchor - 8.0
        )
        upper_y = (
            (anchor + next_anchor) / 2.0
            if next_anchor is not None
            else anchor + 22.0
        )
        if state.kind == "two-column":
            assert state.split_x is not None
            columns = (
                (
                    state.left_name,
                    state.category_boundary,
                    state.split_x,
                    [
                        word
                        for word in value_row
                        if state.category_boundary <= word_center(word) <= state.split_x
                    ],
                ),
                (
                    state.right_name,
                    state.split_x,
                    float("inf"),
                    [word for word in value_row if word_center(word) > state.split_x],
                ),
            )
            rendered = {
                name: compact(line_text(sorted(column_words, key=lambda word: word[0])))
                for name, _, _, column_words in columns
            }
            for name, lower_x, upper_x, column_words in columns:
                text = compact(line_text(sorted(column_words, key=lambda word: word[0])))
                if not text or DASH.fullmatch(text) or not HAS_NUMBER.search(text):
                    continue
                other_name = state.right_name if name == state.left_name else state.left_name
                other_dash = bool(DASH.fullmatch(rendered.get(other_name, "")))
                value = parse_value(text)
                if not value:
                    continue
                context = cell_context(body, lower_y, upper_y, lower_x, upper_x)
                unit = canonical_unit(text) or state.unit or "mg/kg"
                confidence = "high" if (other_dash or not state.exclusive) else "review_col"
                rows.append(
                    {
                        "year": year,
                        "analyte": name,
                        "food_category": category,
                        "limit_value": value,
                        "unit": unit,
                        "basis": basis_from_text(text + context + category),
                        "confidence": confidence,
                        "extraction_path": "bbox",
                    }
                )
        else:
            text = compact(line_text(sorted(value_row, key=lambda word: word[0])))
            if DASH.fullmatch(text) or not HAS_NUMBER.search(text):
                continue
            value = parse_value(text)
            if not value:
                continue
            context = cell_context(
                body,
                lower_y,
                upper_y,
                state.category_boundary,
                float("inf"),
            )
            rows.append(
                {
                    "year": year,
                    "analyte": analyte,
                    "food_category": category,
                    "limit_value": value,
                    "unit": canonical_unit(text) or state.unit,
                    "basis": basis_from_text(text + context + category),
                    "confidence": "high",
                    "extraction_path": "bbox",
                }
            )
    return rows, state


def parse_page(
    words: list[Word], year: str, state: TableState | None
) -> tuple[list[dict[str, str]], TableState | None]:
    tables = find_tables(words)
    segments: list[tuple[str, float, float, bool]] = []
    if tables:
        first_start = tables[0][1]
        prefix = [word for word in words if word[2] < first_start]
        if state and has_continuation_header(prefix):
            segments.append((state.analyte, 0.0, first_start, True))
        segments.extend((analyte, start, end, False) for analyte, start, end in tables)
    elif state:
        segments.append((state.analyte, 0.0, float("inf"), True))
    else:
        return [], state

    output: list[dict[str, str]] = []
    current_state = state
    for analyte, start, end, continuation in segments:
        segment_words = [word for word in words if start - 2.0 < word[2] < end]
        prior = current_state if continuation else None
        parsed, new_state = parse_segment(segment_words, year, analyte, prior)
        output.extend(parsed)
        current_state = new_state
    return output, current_state


def find_source_pdf(source_dir: Path, year: str) -> Path:
    matches = [
        Path(path)
        for path in glob.glob(str(source_dir / f"GB 2762-{year}*.pdf"))
        if "修改单" not in Path(path).name
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one GB 2762-{year} source PDF; found {matches}")
    return matches[0]


def parse_bbox_sources(source_dir: Path) -> tuple[list[dict[str, str]], list[Path]]:
    rows: list[dict[str, str]] = []
    source_paths: list[Path] = []
    for year in YEARS:
        source_path = find_source_pdf(source_dir, year)
        source_paths.append(source_path)
        state: TableState | None = None
        for words in bbox_pages(source_path):
            parsed, state = parse_page(words, year, state)
            rows.extend(parsed)
    unique: dict[tuple[str, ...], dict[str, str]] = {}
    for row in rows:
        signature = tuple(
            row[column]
            for column in (
                "year",
                "analyte",
                "food_category",
                "limit_value",
                "unit",
                "basis",
            )
        )
        unique.setdefault(signature, row)
    return list(unique.values()), source_paths


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_legacy_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for source in read_csv(path):
        category = clean_category(source["food_category"])
        rows.append(
            {
                "year": source["year"],
                "analyte": ANALYTE_ALIAS.get(source["analyte"], source["analyte"]),
                "food_category": category,
                "limit_value": source["limit_value"],
                "unit": source.get("unit", ""),
                "basis": source.get("basis", "")
                or basis_from_text(source.get("note", "") + category),
                "confidence": source.get("confidence", ""),
                "extraction_path": "text-regex",
            }
        )
    return rows


def weak_category_key(category: str) -> str:
    previous = None
    category = clean_category(category)
    inner = re.compile(r"[\(（\[［][^\(（\[［\)）\]］]*[\)）\]］]")
    while previous != category:
        previous = category
        category = inner.sub("", category)
    category = re.sub(r"[\(（\[［][^\)）\]］]*$", "", category)
    category = re.sub(r"[、,，]", "", category)
    return category.strip()


def numeric_equal(left: str, right: str) -> bool:
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return left == right


def quarantine_invalid(
    rows: list[dict[str, str]], source_name: str
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    valid: list[dict[str, str]] = []
    quarantine: list[dict[str, str]] = []
    for row in rows:
        reason = category_error(row["food_category"])
        if not reason:
            valid.append(row)
            continue
        quarantine.append(
            {
                "source_path": source_name,
                "year": row["year"],
                "analyte": row["analyte"],
                "food_category": row["food_category"],
                "limit_value": row["limit_value"],
                "unit": row["unit"],
                "reason": reason,
            }
        )
    return valid, quarantine


def merge_paths(
    legacy_rows: list[dict[str, str]], bbox_rows: list[dict[str, str]]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    output: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []
    exact_seen: set[tuple[str, ...]] = set()
    for row in legacy_rows:
        signature = (
            row["year"],
            row["analyte"],
            row["food_category"],
            row["limit_value"],
            row["unit"],
        )
        if signature not in exact_seen:
            output.append(dict(row))
            exact_seen.add(signature)

    for bbox in bbox_rows:
        weak = weak_category_key(bbox["food_category"])
        candidates = [
            row
            for row in output
            if row["year"] == bbox["year"]
            and row["analyte"] == bbox["analyte"]
            and weak_category_key(row["food_category"]) == weak
        ]
        same = [
            row
            for row in candidates
            if numeric_equal(row["limit_value"], bbox["limit_value"])
            and row["unit"] == bbox["unit"]
        ]
        if same:
            chosen = same[0]
            chosen["food_category"] = bbox["food_category"]
            if bbox["basis"]:
                chosen["basis"] = bbox["basis"]
            chosen["confidence"] = bbox["confidence"]
            chosen["extraction_path"] = "text-regex+bbox"
            continue
        if candidates:
            conflicts.append(
                {
                    "source_path": "merge",
                    "year": bbox["year"],
                    "analyte": bbox["analyte"],
                    "food_category": bbox["food_category"],
                    "limit_value": bbox["limit_value"],
                    "unit": bbox["unit"],
                    "reason": "cross_path_value_or_unit_conflict",
                }
            )
            continue
        output.append(dict(bbox))

    output.sort(
        key=lambda row: (
            row["year"],
            row["analyte"],
            row["food_category"],
            float(row["limit_value"]),
        )
    )
    return output, conflicts


def split_top_level(text: str, separators: str = "、,，") -> list[str]:
    pieces: list[str] = []
    current: list[str] = []
    stack: list[str] = []
    for char in text:
        if char in BRACKETS:
            stack.append(BRACKETS[char])
            current.append(char)
        elif char in CLOSERS:
            if not stack or stack.pop() != char:
                return [text]
            current.append(char)
        elif char in separators and not stack:
            pieces.append("".join(current))
            current = []
        else:
            current.append(char)
    pieces.append("".join(current))
    return pieces


def clean_member(text: str, aliases: dict[str, str]) -> str:
    text = clean_category(text)
    text = re.sub(r"及以上.*?制品$", "", text)
    text = text.strip("、,，. ")
    return aliases.get(text, text)


def split_category(
    raw: str, aliases: dict[str, str]
) -> tuple[str, list[str]]:
    """Return the category head and exclusions using an outer-bracket stack."""

    stack: list[tuple[str, int]] = []
    spans: list[tuple[int, int, str]] = []
    for index, char in enumerate(raw):
        if char in BRACKETS:
            stack.append((BRACKETS[char], index))
        elif char in CLOSERS:
            if not stack:
                return "", []
            expected, start = stack.pop()
            if expected != char:
                return "", []
            if not stack:
                spans.append((start, index, raw[start + 1 : index]))
    if stack:
        return "", []

    exclusions: list[str] = []
    removed: list[tuple[int, int]] = []
    for start, end, inner in spans:
        if "除外" not in inner:
            continue
        body = inner.split("除外", 1)[0]
        exclusions.extend(
            clean_member(part, aliases)
            for part in split_top_level(body)
            if clean_member(part, aliases)
        )
        removed.append((start, end))

    base_parts: list[str] = []
    cursor = 0
    for start, end in removed:
        base_parts.append(raw[cursor:start])
        cursor = end + 1
    base_parts.append(raw[cursor:])
    base = clean_member("".join(base_parts), aliases)
    return base, exclusions


def read_alias_adjudications(path: Path) -> list[dict[str, str]]:
    """Read the human alias seed and validate every adjudication state."""

    if not path.is_file():
        raise ValueError(f"required alias adjudication file is missing: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != ALIAS_FIELDS:
            raise ValueError(f"unexpected alias schema: {reader.fieldnames}")
        rows = list(reader)
    keys: list[str] = []
    for row in rows:
        source = row["异名"].strip()
        target = row["规范名"].strip()
        status = row["status"].strip()
        if not source or not target:
            raise ValueError("blank source or target in alias adjudication")
        if status not in ALIAS_STATUSES:
            raise ValueError(f"unsupported alias adjudication status: {status}")
        keys.append(source)
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate source label in alias adjudication")
    return rows


def load_aliases(path: Path) -> dict[str, str]:
    """Load only confirmed aliases for formal category and member derivation."""

    return {
        row["异名"].strip(): row["规范名"].strip()
        for row in read_alias_adjudications(path)
        if row["status"].strip() == "已确认"
    }


def load_containment(path: Path | None, aliases: dict[str, str]) -> dict[str, str]:
    """Load confirmed "member lies within" links from the human seed."""

    if path is None:
        return {}
    if not path.is_file():
        raise ValueError(f"required containment adjudication file is missing: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CONTAINMENT_FIELDS:
            raise ValueError(f"unexpected containment schema: {reader.fieldnames}")
        rows = list(reader)
    links: dict[str, str] = {}
    seen: set[str] = set()
    for row in rows:
        child = match_key(row["成员"], aliases)
        parent = match_key(row["上级"], aliases)
        status = row["status"].strip()
        if not child or not parent or child == parent:
            raise ValueError(f"blank or circular containment row: {row}")
        if status not in CONTAINMENT_STATUSES:
            raise ValueError(f"unsupported containment status: {status}")
        if child in seen:
            raise ValueError(f"duplicate member in containment seed: {child}")
        seen.add(child)
        if status == "已确认":
            links[child] = parent
    return links


def match_key(text: str, aliases: dict[str, str]) -> str:
    """Width-folded member name used only for matching, never for output."""

    return clean_member(unicodedata.normalize("NFKC", text), aliases)


def load_taxonomy(path: Path, aliases: dict[str, str]) -> dict[str, dict[str, str]]:
    taxonomy: dict[str, dict[str, str]] = defaultdict(dict)
    if not path.exists():
        raise ValueError(f"required taxonomy file is missing: {path}")
    for row in read_csv(path):
        taxonomy[row["src_year"]][clean_member(row["child"], aliases)] = clean_member(
            row["parent"], aliases
        )
    return taxonomy


def comparable_value(value: str, unit: str) -> tuple[str, float] | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if unit in MASS_FACTORS:
        return "mass/mass", number * MASS_FACTORS[unit]
    if unit == "mg/L":
        return "mass/volume", number
    return None


def summarize_basis(bases: set[str]) -> str:
    """Summarize per-edition measurement bases without creating empty tokens."""

    if not bases:
        return ""
    if len(bases) > 1:
        return "varies_by_version"
    return next(iter(bases))


def edition_gap(present: list[str]) -> bool:
    """True when the compared editions skip an edition in between."""

    positions = [YEARS.index(year) for year in present]
    return positions != list(range(positions[0], positions[-1] + 1))


def category_scope(
    raw: str, aliases: dict[str, str], canonical_aliases: dict[str, str]
) -> tuple[str, ...]:
    """Printed head and exclusions, equal across a confirmed rename."""

    base, exclusions = split_category(raw, aliases)
    if not base:
        return (compact(unicodedata.normalize("NFKC", raw)),)
    key = weak_category_key(base)
    if key in canonical_aliases or key in canonical_aliases.values():
        head = canonical_aliases.get(key, key)
    else:
        head = re.sub(r"[、,，\s]", "", unicodedata.normalize("NFKC", base))
    return (head, *sorted({unicodedata.normalize("NFKC", item) for item in exclusions}))


def build_category_panel(
    rows: list[dict[str, str]], alias_path: Path
) -> list[dict[str, str]]:
    """Build a conservative category panel compatible with build_release."""

    aliases = load_aliases(alias_path)
    canonical_aliases = {
        weak_category_key(source): weak_category_key(target)
        for source, target in aliases.items()
    }
    grouped: dict[
        tuple[str, str, str], dict[str, list[dict[str, str]]]
    ] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row["confidence"] != "high":
            continue
        canonical = weak_category_key(row["food_category"])
        canonical = canonical_aliases.get(canonical, canonical)
        grouped[(row["analyte"], canonical, row["basis"])][row["year"]].append(row)

    output: list[dict[str, str]] = []
    for (analyte, canonical, basis), by_year in sorted(grouped.items()):
        present = [year for year in YEARS if by_year.get(year)]
        scalar: dict[str, dict[str, str] | None] = {}
        statuses: dict[str, str] = {}
        for year in YEARS:
            candidates = by_year.get(year, [])
            if not candidates:
                statuses[year] = "missing"
                scalar[year] = None
            elif len(candidates) == 1:
                statuses[year] = "single"
                scalar[year] = candidates[0]
            else:
                statuses[year] = "multiple_rules"
                scalar[year] = None

        if len(present) == len(YEARS):
            status = "全齐"
        elif present and present[0] != YEARS[0] and present[-1] == YEARS[-1]:
            status = f"新增于{present[0]}"
        elif present and present[0] == YEARS[0] and present[-1] != YEARS[-1]:
            status = f"止于{present[-1]}(后删/改名)"
        else:
            status = "中段缺(待核)"

        comparable = [
            comparable_value(scalar[year]["limit_value"], scalar[year]["unit"])
            for year in present
            if scalar[year]
        ]
        dimensions = {item[0] for item in comparable if item is not None}
        values = [item[1] for item in comparable if item is not None]
        if any(statuses[year] == "multiple_rules" for year in present):
            trend = "不可比(同版多规则)"
        elif "止于" in status:
            trend = "不可比(类别消失,见成员级面板)"
        elif len(comparable) != len(present) or len(dimensions) > 1:
            trend = "不可比(单位维度或值缺失)"
        elif len(values) == 1:
            trend = "单版本"
        elif edition_gap(present):
            trend = "不可比(跨过缺失版本)"
        elif len({
            category_scope(scalar[year]["food_category"], aliases, canonical_aliases)
            for year in present
        }) > 1:
            trend = "不可比(范围文字不同)"
        elif len(set(values)) == 1:
            trend = "稳定"
        elif values[-1] < values[0]:
            trend = "收紧(变严)"
        elif values[-1] > values[0]:
            trend = "放松(变松)"
        else:
            trend = "波动"

        unit_sequence = [
            scalar[year]["unit"] for year in present if scalar[year]
        ]
        distinct_units = set(unit_sequence)
        unit_note = (
            next(iter(distinct_units))
            if len(distinct_units) == 1
            else "跨版单位变化:" + "→".join(unit_sequence)
        )
        panel_row = {
            "analyte": analyte,
            "canonical": canonical,
            "basis": basis,
            "unit": unit_note,
            "n_versions": str(len(present)),
            "状态": status,
            "trend": trend,
        }
        for year in YEARS:
            candidate = scalar[year]
            panel_row[f"v{year}"] = candidate["limit_value"] if candidate else ""
            panel_row[f"unit{year}"] = candidate["unit"] if candidate else ""
            panel_row[f"basis{year}"] = candidate["basis"] if candidate else ""
            panel_row[f"cell_status{year}"] = statuses[year]
            panel_row[f"原始名{year}"] = (
                candidate["food_category"] if candidate else ""
            )
        output.append(panel_row)
    return output


def build_member_panel(
    rows: list[dict[str, str]],
    taxonomy_path: Path,
    alias_path: Path,
    containment_path: Path | None = None,
) -> list[dict[str, str]]:
    aliases = load_aliases(alias_path)
    match_aliases = {
        unicodedata.normalize("NFKC", source): unicodedata.normalize("NFKC", target)
        for source, target in aliases.items()
    }

    def key(text: str) -> str:
        return match_key(text, match_aliases)

    taxonomy = {
        year: {key(child): key(parent) for child, parent in edges.items()}
        for year, edges in load_taxonomy(taxonomy_path, aliases).items()
    }
    contained_in = load_containment(containment_path, match_aliases)
    table: dict[str, dict[str, dict[str, list[tuple[str, ...]]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    parents: dict[str, dict[str, str]] = defaultdict(dict)
    members: dict[str, set[str]] = defaultdict(set)
    # Printed exclusion lists by analyte and edition, as sets of matching keys.
    printed_lists: dict[str, dict[str, list[set[str]]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for row in rows:
        if row["confidence"] != "high":
            continue
        base, exclusions = split_category(row["food_category"], aliases)
        if not base:
            continue
        cell = (
            row["limit_value"],
            row["unit"],
            row["basis"],
            json.dumps(exclusions, ensure_ascii=False),
            row["food_category"],
        )
        table[row["analyte"]][row["year"]][key(base)].append(cell)
        members[row["analyte"]].add(base)
        top_parts = split_top_level(base)
        if len(top_parts) > 1 and len(base) > 4:
            for part in top_parts:
                part = clean_member(part, aliases)
                if len(part) > 1:
                    # Long names are looked up but do not start a member row.
                    table[row["analyte"]][row["year"]][key(part)].append(cell)
                if part and 1 < len(part) <= 8:
                    members[row["analyte"]].add(part)
        for excluded in exclusions:
            members[row["analyte"]].add(excluded)
            parents[row["analyte"]][key(excluded)] = key(base)
        if exclusions:
            printed_lists[row["analyte"]][row["year"]].append(
                {key(item) for item in exclusions}
            )

    def variants(member: str, printed: dict[str, list] | None = None) -> tuple[str, ...]:
        # A printed "X及其Y", such as 果蔬汁类及其饮料, is a rule for the member X.
        wider = [name for name in sorted(printed or {}) if name.startswith(member + "及其")]
        if member.endswith("及其制品"):
            return member, member[:-4]
        if member.endswith("制品"):
            # A printed "X及其制品" covers the member "X制品".
            return tuple(dict.fromkeys(
                [member, member + "及其制品", member[:-2] + "及其制品", *wider]))
        return tuple(dict.fromkeys([member, member + "及其制品", *wider]))

    def taxonomy_parent(year: str, node: str) -> str | None:
        if node in taxonomy.get(year, {}):
            return taxonomy[year][node]
        for other_year in YEARS:
            if node in taxonomy.get(other_year, {}):
                return taxonomy[other_year][node]
        return None

    def parent_of(analyte: str, year: str, node: str) -> str | None:
        return (
            contained_in.get(node)
            or parents[analyte].get(node)
            or taxonomy_parent(year, node)
        )

    def within(node: str) -> set[str]:
        """The node and every confirmed category that contains it."""

        chain = {node}
        while node in contained_in and contained_in[node] not in chain:
            node = contained_in[node]
            chain.add(node)
        return chain

    def covered(items: list[str]) -> set[str]:
        """Names an exclusion list removes: "A和B" removes A and B,
        "X及其制品" removes X and X制品, and any "X及其Y" removes X."""

        names: set[str] = set()
        for item in items:
            item = key(item)
            for part in {item, *split_top_level(item, "和")}:
                part = part.strip()
                if not part:
                    continue
                names.add(part)
                if part.endswith("及其制品"):
                    names.update({part[:-4], part[:-4] + "制品"})
                elif "及其" in part:
                    names.add(part[: part.index("及其")])
        return names

    def one_rule(candidates: list[tuple[str, ...]]) -> tuple[str, ...] | None:
        if not candidates:
            return None
        distinct = {candidate[:3] for candidate in candidates}
        if len(distinct) != 1:
            return None
        return sorted(candidates)[0]

    def judge(rule: tuple[str, ...], path: list[str]) -> str:
        """Whether an inherited rule reaches the member at path[0]."""

        removed = covered(json.loads(rule[3]))
        if any(within(node) & removed for node in path):
            return "excluded"
        member = path[0]
        if any(member in within(name) and name != member for name in removed):
            return "spans_two_rules"
        parts = [part for part in split_top_level(member, "、和") if part]
        if len(parts) > 1 and any(part in removed for part in parts):
            return "excluded" if all(part in removed for part in parts) else "spans_two_rules"
        return "applies"

    def rewritten(analyte: str, year: str, member: str, rule: tuple[str, ...]) -> str:
        """An edition that names the member among its exclusions vouches that
        the member is disjoint from its siblings in that list.  When no such
        list covers this edition's exclusions, the inherited host is not
        determinable from the printed text."""

        removed = {key(item) for item in json.loads(rule[3])}
        if not removed:
            return ""
        lists = [
            (other_year, printed)
            for other_year in YEARS
            if other_year != year
            for printed in printed_lists[analyte].get(other_year, [])
            if member in printed
        ]
        if not lists or any(removed <= printed for _, printed in lists):
            return ""
        return lists[0][0]

    def applies(analyte: str, year: str, member: str) -> tuple[str, tuple[str, ...] | None, str]:
        year_table = table[analyte].get(year, {})
        member = key(member)
        for variant in variants(member, year_table):
            rule = one_rule(year_table.get(variant, []))
            if rule:
                return "applies", rule, ""
        path = [member]
        seen: set[str] = set()
        parent = parent_of(analyte, year, member)
        while parent and parent not in seen:
            seen.add(parent)
            for variant in variants(parent, year_table):
                rule = one_rule(year_table.get(variant, []))
                if not rule:
                    continue
                verdict = judge(rule, path)
                if verdict != "applies":
                    return verdict, rule, ""
                since = rewritten(analyte, year, member, rule)
                if since:
                    return "host_not_determinable", rule, since
                return "applies", rule, ""
            path.append(parent)
            parent = parent_of(analyte, year, parent)
        return "no_rule", None, ""

    def blank_note(reasons: dict[str, tuple[str, tuple[str, ...], str]]) -> str:
        grouped: dict[str, list[str]] = defaultdict(list)
        for year in YEARS:
            if year not in reasons:
                continue
            verdict, rule, since = reasons[year]
            host = rule[4]
            if verdict == "excluded":
                text = f"excluded by {host}; no separate limit for this analyte located"
            elif verdict == "spans_two_rules":
                text = f"spans two printed rules; {host} excludes part of it"
            else:
                text = f"host not determinable; exclusion list of {host} differs from {since}"
            grouped[text].append(year)
        return " | ".join(
            f"{', '.join(years)}: {text}" for text, years in grouped.items()
        )

    output: list[dict[str, str]] = []
    for analyte in sorted(table):
        by_key: dict[str, set[str]] = defaultdict(set)
        for member in members[analyte]:
            by_key[key(member)].add(member)
        # One row per member; a width variant keeps its folded spelling.
        names = {
            member_key: member_key if member_key in spellings else sorted(spellings)[0]
            for member_key, spellings in by_key.items()
        }
        analyte_members = {
            name
            for member_key, name in names.items()
            if not (member_key.endswith("及其制品") and member_key[:-4] in names)
        }
        for member in sorted(analyte_members):
            verdicts = {year: applies(analyte, year, member) for year in YEARS}
            cells = {
                year: verdict[1] if verdict[0] == "applies" else None
                for year, verdict in verdicts.items()
            }
            blanked = {
                year: verdict
                for year, verdict in verdicts.items()
                if verdict[0] in {"excluded", "spans_two_rules", "host_not_determinable"}
            }
            present = [year for year in YEARS if cells[year]]
            if len(present) < 2:
                continue
            bases = {cells[year][2] for year in present}
            comparable = [
                comparable_value(cells[year][0], cells[year][1]) for year in present
            ]
            dimensions = {item[0] for item in comparable if item is not None}
            values = [item[1] for item in comparable if item is not None]
            hosts = {
                year: cells[year][4] if cells[year] else "" for year in YEARS
            }
            # Editions in which the member is its host's own head: the member
            # then stands for that head minus the printed exclusions.
            residual = {
                tuple(sorted({unicodedata.normalize("NFKC", item)
                              for item in json.loads(cells[year][3])}))
                for year in present
                if key(split_category(cells[year][4], aliases)[0])
                in variants(key(member), table[analyte].get(year, {}))
            }
            if len(comparable) != len(present) or len(bases) > 1 or len(dimensions) > 1:
                trend = "incomparable_basis_unit_or_value"
            elif edition_gap(present):
                trend = "incomparable_edition_gap"
            elif len(residual) > 1:
                trend = "incomparable_scope_text"
            elif len(set(values)) == 1:
                trend = "stable"
            elif values[-1] < values[0]:
                trend = "tightened"
            elif values[-1] > values[0]:
                trend = "relaxed"
            else:
                trend = "fluctuation"
            row = {
                "analyte": analyte,
                "food_member": member,
                "limit_basis": summarize_basis(bases),
                "trend": trend,
                "category_restructured": "yes"
                if len({hosts[year] for year in present}) > 1
                else "no",
                "note": blank_note(blanked),
            }
            for year in YEARS:
                cell = cells[year]
                row[f"v{year}"] = cell[0] if cell else ""
                row[f"unit_{year}"] = cell[1] if cell else ""
                row[f"basis_{year}"] = cell[2] if cell else ""
                row[f"host_category_{year}"] = hosts[year]
            output.append(row)
    output.sort(key=lambda row: (row["analyte"], row["food_member"]))
    return output


def write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=columns,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rebuild(
    source_dir: Path,
    legacy_path: Path,
    taxonomy_path: Path,
    alias_path: Path,
    containment_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    dependency_paths = {
        "pollutant_old_path.csv": legacy_path,
        "food_taxonomy.csv": taxonomy_path,
        "category_alias.csv": alias_path,
        "category_containment.csv": containment_path,
    }
    for filename, path in dependency_paths.items():
        read_locked_csv(path, RELEASE_DEPENDENCY_SPECS[filename])
    alias_adjudications = read_alias_adjudications(alias_path)
    confirmed_aliases = [
        row for row in alias_adjudications if row["status"].strip() == "已确认"
    ]
    pending_aliases = [
        row for row in alias_adjudications if row["status"].strip() == "待核"
    ]
    bbox_rows, source_paths = parse_bbox_sources(source_dir)
    legacy_rows = load_legacy_rows(legacy_path)
    valid_legacy, legacy_quarantine = quarantine_invalid(
        legacy_rows, legacy_path.name
    )
    valid_bbox, bbox_quarantine = quarantine_invalid(bbox_rows, "bbox-parser")
    long_rows, conflicts = merge_paths(valid_legacy, valid_bbox)
    quarantine = legacy_quarantine + bbox_quarantine + conflicts
    quarantine = list(
        {
            tuple(row.get(column, "") for column in sorted(row)): row
            for row in quarantine
        }.values()
    )
    quarantine.sort(
        key=lambda row: (
            row["year"],
            row["analyte"],
            row["food_category"],
            row["reason"],
        )
    )
    members = build_member_panel(
        long_rows, taxonomy_path, alias_path, containment_path
    )
    categories = build_category_panel(long_rows, alias_path)

    long_path = output_dir / "pollutant_limits_long.csv"
    quarantine_path = output_dir / "pollutant_quarantine.csv"
    member_path = output_dir / "pollutant_member_panel.csv"
    compatible_long_path = output_dir / "pollutant_limits_by_version.csv"
    compatible_member_path = output_dir / "member_crosswalk.csv"
    category_path = output_dir / "category_crosswalk.csv"
    write_csv(
        long_path,
        long_rows,
        [
            "year",
            "analyte",
            "food_category",
            "limit_value",
            "unit",
            "basis",
            "confidence",
            "extraction_path",
        ],
    )
    write_csv(
        quarantine_path,
        quarantine,
        [
            "source_path",
            "year",
            "analyte",
            "food_category",
            "limit_value",
            "unit",
            "reason",
        ],
    )
    member_columns = ["analyte", "food_member"]
    member_columns.extend(f"v{year}" for year in YEARS)
    member_columns.extend(f"unit_{year}" for year in YEARS)
    member_columns.extend(f"basis_{year}" for year in YEARS)
    member_columns.extend(
        ["limit_basis", "trend", "category_restructured"]
    )
    member_columns.extend(f"host_category_{year}" for year in YEARS)
    member_columns.append("note")
    write_csv(member_path, members, member_columns)
    write_csv(
        compatible_long_path,
        long_rows,
        [
            "year",
            "analyte",
            "food_category",
            "limit_value",
            "unit",
            "basis",
            "confidence",
            "extraction_path",
        ],
    )
    compatible_members = []
    trend_labels = {
        "stable": "稳定",
        "tightened": "收紧(变严)",
        "relaxed": "放松(变松)",
        "fluctuation": "波动",
        "incomparable_basis_unit_or_value": "不可比(基准、单位或值缺失)",
        "incomparable_edition_gap": "不可比(跨过缺失版本)",
        "incomparable_scope_text": "不可比(范围文字不同)",
    }
    for member in members:
        compatible = {
            "analyte": member["analyte"],
            "member": member["food_member"],
            "basis": member["limit_basis"],
            "trend": trend_labels[member["trend"]],
            "类别重组": "是" if member["category_restructured"] == "yes" else "否",
            "note": member["note"],
        }
        for year in YEARS:
            compatible[f"v{year}"] = member[f"v{year}"]
            compatible[f"unit{year}"] = member[f"unit_{year}"]
            compatible[f"basis{year}"] = member[f"basis_{year}"]
            compatible[f"归属类别{year}"] = member[f"host_category_{year}"]
        compatible_members.append(compatible)
    compatible_member_columns = ["analyte", "member"]
    compatible_member_columns.extend(f"v{year}" for year in YEARS)
    compatible_member_columns.extend(f"unit{year}" for year in YEARS)
    compatible_member_columns.extend(f"basis{year}" for year in YEARS)
    compatible_member_columns.extend(["basis", "trend", "类别重组"])
    compatible_member_columns.extend(f"归属类别{year}" for year in YEARS)
    compatible_member_columns.append("note")
    write_csv(
        compatible_member_path,
        compatible_members,
        compatible_member_columns,
    )
    category_columns = ["analyte", "canonical", "basis"]
    category_columns.extend(f"v{year}" for year in YEARS)
    category_columns.extend(f"unit{year}" for year in YEARS)
    category_columns.extend(f"basis{year}" for year in YEARS)
    category_columns.extend(f"cell_status{year}" for year in YEARS)
    category_columns.extend(
        ["unit", "n_versions", "状态", "trend"]
    )
    category_columns.extend(f"原始名{year}" for year in YEARS)
    write_csv(category_path, categories, category_columns)

    report: dict[str, object] = {
        "inputs": {
            path.name: sha256(path)
            for path in [
                *source_paths,
                legacy_path,
                taxonomy_path,
                alias_path,
                containment_path,
            ]
            if path.exists()
        },
        "counts": {
            "bbox_rows_before_gate": len(bbox_rows),
            "legacy_rows_before_gate": len(legacy_rows),
            "long_rows": len(long_rows),
            "quarantined_rows": len(quarantine),
            "member_rows": len(members),
            "category_rows": len(categories),
            "mg_per_litre_rows": sum(row["unit"] == "mg/L" for row in long_rows),
            "basis_rows": sum(bool(row["basis"]) for row in long_rows),
        },
        "alias_adjudications": {
            "confirmed_applied": len(confirmed_aliases),
            "pending_review_excluded": len(pending_aliases),
            "pending_review_sources": [row["异名"] for row in pending_aliases],
        },
        "quarantine_reasons": dict(Counter(row["reason"] for row in quarantine)),
        "outputs": {
            path.name: sha256(path)
            for path in (
                long_path,
                quarantine_path,
                member_path,
                compatible_long_path,
                compatible_member_path,
                category_path,
            )
        },
    }
    report_path = output_dir / "pollutant_rebuild_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument(
        "--legacy-path",
        type=Path,
        default=DEFAULT_DEPENDENCY_DIR / "pollutant_old_path.csv",
    )
    parser.add_argument(
        "--taxonomy-path",
        type=Path,
        default=DEFAULT_DEPENDENCY_DIR / "food_taxonomy.csv",
    )
    parser.add_argument(
        "--alias-path",
        type=Path,
        default=DEFAULT_DEPENDENCY_DIR / "category_alias.csv",
    )
    parser.add_argument(
        "--containment-path",
        type=Path,
        default=DEFAULT_DEPENDENCY_DIR / "category_containment.csv",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = rebuild(
        source_dir=args.source_dir,
        legacy_path=args.legacy_path,
        taxonomy_path=args.taxonomy_path,
        alias_path=args.alias_path,
        containment_path=args.containment_path,
        output_dir=args.output_dir,
    )
    print(json.dumps(report["counts"], ensure_ascii=False, indent=2))
    print(f"Wrote {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
