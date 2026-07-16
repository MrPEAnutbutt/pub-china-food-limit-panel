#!/usr/bin/env python3
"""Extract the four text-layer editions of GB 2763 from source PDFs.

The 2012, 2014 and 2016 editions are parsed from ``pdftotext -layout``.
The 2026 edition is parsed from word coordinates because its value and food
columns do not have a stable line order.  A section roster is generated from
the 2026 body headings and confirmed by the following ``主要用途`` line.

All default outputs are derived data under ``Data/Interim/pesticide_text``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import NamedTuple
import xml.etree.ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "Data" / "Interim" / "pesticide_text"

LEGACY_YEARS = ("2012", "2014", "2016")
EXPECTED = {
    "2012": {"rows": 2165, "entities": 307, "sections": 307},
    "2014": {"rows": 3462, "entities": 370, "sections": 371},
    "2016": {"rows": 3940, "entities": 416, "sections": 417},
    "2026": {"rows": 10612, "entities": 568, "sections": 568},
}
LEGACY_TEMPORARY_COUNTS = {
    "2012": 280,
    "2014": 507,
    "2016": 604,
}
OFFICIAL_2026_MRL_COUNT = 10_749
OFFICIAL_2026_PESTICIDE_COUNT = 585
APPENDIX_B_2026_ENTRY_COUNT = 44

NS = "{http://www.w3.org/1999/xhtml}"
HEADER_GAP_LIMIT = 20
CAT_X = 320.0

PARENTS = {
    "谷物",
    "油料和油脂",
    "油料",
    "油脂",
    "蔬菜",
    "水果",
    "糖料",
    "饮料类",
    "食用菌",
    "调味料",
    "药用植物",
    "坚果",
    "坚果及籽类",
    "哺乳动物肉类",
    "哺乳动物肉类（除海洋哺乳动物）",
    "哺乳动物肉类(除海洋哺乳动物)",
    "哺乳动物肉类(海洋哺乳动物除外)",
    "哺乳动物肉类(海洋哺乳动物除外),以脂肪中的残留量计",
    "哺乳动物肉类(牛肉除外)",
    "禽肉类",
    "禽肉类,以脂肪中的残留量计",
    "禽类脂肪",
    "蛋类",
    "生乳",
    "生乳(牛乳除外)",
    "水产品",
    "哺乳动物内脏",
    "哺乳动物内脏(海洋哺乳动物除外)",
    "哺乳动物内脏(牛肝、牛肾除外)",
    "哺乳动物脂肪",
    "哺乳动物脂肪(海洋哺乳动物除外)",
    "哺乳动物脂肪(乳脂肪除外)",
    "禽类内脏",
    "茶叶",
    "动物源性食品",
    "干制水果",
}

ANIMAL_PARENT_PREFIXES = {
    "mammal_meat": (
        {"猪肉", "牛肉", "绵羊肉", "山羊肉", "马肉"},
        "哺乳动物肉类",
    ),
    "mammal_offal": (
        {
            "猪肝",
            "牛肝",
            "绵羊肝",
            "山羊肝",
            "猪肾",
            "牛肾",
            "绵羊肾",
            "山羊肾",
            "猪内脏",
            "牛内脏",
            "绵羊内脏",
            "山羊内脏",
            "马内脏",
        },
        "哺乳动物内脏",
    ),
    "mammal_fat": (
        {"猪脂肪", "牛脂肪", "绵羊脂肪", "山羊脂肪", "马脂肪"},
        "哺乳动物脂肪",
    ),
    "milk": ({"牛乳"}, "生乳"),
}

LEGACY_VALUE = re.compile(
    r"^\s*(?P<food>\S.*?\S)\s{2,}"
    r"(?P<value_raw>(?P<limit_value>\d+(?:\.\d+)?)"
    r"(?:\s*(?P<limit_qualifier>[*∗](?:[a-z])?|[a-z]))?)\s*$"
)
VALUE_CELL_2026 = re.compile(
    r"^(?P<limit_value>\d+(?:\.\d+)?)"
    r"(?P<limit_qualifier>.*)$"
)
VALID_2026_QUALIFIER = re.compile(
    r"^(?:[*∗](?:[a-z])?|[a-z]|[(（]以(?:脂肪|原样)计[)）])?$"
)
NOISE_2026 = re.compile(
    r"GB|食品类别|最大残留限量|检测方法|主要用途|残留物|ADI|该限量|^表$|索引|附录"
)

# These glyphs are visible in the rendered source but absent from the 2026
# text layer.  The English name and section number make every correction
# independently checkable and prevent a correction from drifting to a new
# heading after a source change.
SECTION_NAME_FIXES = {
    64: ("丙炔噁草酮", "oxadiargyl"),
    118: ("啶菌噁唑", "pyrisoxazole"),
    133: ("噁草酸", "propaquizafop"),
    134: ("噁草酮", "oxadiazon"),
    135: ("噁霉灵", "hymexazol"),
    136: ("噁嗪草酮", "oxaziclomefone"),
    137: ("噁霜灵", "oxadixyl"),
    138: ("噁唑菌酮", "famoxadone"),
    139: ("噁唑酰草胺", "metamifop"),
    245: ("甲哌鎓", "mepiquatchloride"),
    529: ("异噁草酮", "clomazone"),
}

Word = tuple[float, float, float, str]


@dataclass(frozen=True)
class LimitCell:
    limit_value: str
    value_raw: str
    limit_qualifier: str
    is_temporary: int


class LimitRow(NamedTuple):
    year: str
    pesticide_zh: str
    parent_category: str
    food: str
    limit_value: str
    value_raw: str
    limit_qualifier: str
    is_temporary: int
    unit: str
    section_number: int
    source_page: int
    source_y: float | None


@dataclass(frozen=True)
class SectionHeader:
    section_number: int
    pesticide_zh: str
    pesticide_en: str
    source_page: int
    header_text: str
    serial: int
    evidence: str


def run_pdftotext(arguments: list[str], timeout: int = 900) -> bytes:
    """Run Poppler and fail with a useful diagnostic."""

    try:
        completed = subprocess.run(
            ["pdftotext", *arguments],
            check=True,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        stderr = getattr(error, "stderr", b"")
        detail = stderr.decode("utf-8", "replace") if stderr else str(error)
        raise RuntimeError(f"pdftotext failed: {detail}") from error
    return completed.stdout


def normalize_2026(text: str) -> str:
    """Normalize the two documented PUA glyphs and full-width ASCII."""

    output: list[str] = []
    for char in text:
        codepoint = ord(char)
        if 0xFF10 <= codepoint <= 0xFF19:
            output.append(chr(codepoint - 0xFF10 + 0x30))
        elif 0xFF21 <= codepoint <= 0xFF3A:
            output.append(chr(codepoint - 0xFF21 + 0x41))
        elif 0xFF41 <= codepoint <= 0xFF5A:
            output.append(chr(codepoint - 0xFF41 + 0x61))
        elif codepoint == 0x1001B0:
            output.append(".")
        elif codepoint != 0x1001BA:
            output.append(char)
    return "".join(output)


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def make_limit_cell(limit_value: str, value_raw: str, qualifier: str) -> LimitCell:
    """Create a source-faithful value cell and derive temporary status."""

    compact_raw = compact(value_raw)
    if compact_raw != f"{limit_value}{qualifier}":
        raise RuntimeError(
            "limit value components do not reconstruct the source cell: "
            f"{limit_value!r}, {qualifier!r}, {compact_raw!r}"
        )
    return LimitCell(
        limit_value=limit_value,
        value_raw=compact_raw,
        limit_qualifier=qualifier,
        is_temporary=int("*" in qualifier or "∗" in qualifier),
    )


def limit_cell_from_legacy_match(match: re.Match[str]) -> LimitCell:
    """Recover the numeric value and its printed suffix from a legacy row."""

    qualifier = match.group("limit_qualifier") or ""
    return make_limit_cell(
        match.group("limit_value"),
        match.group("value_raw"),
        qualifier,
    )


def parse_2026_limit_cell(value_text: str) -> LimitCell | None:
    """Parse the complete normalized 2026 value cell without dropping suffixes."""

    value_raw = compact(value_text)
    match = VALUE_CELL_2026.fullmatch(value_raw)
    if match is None:
        return None
    qualifier = match.group("limit_qualifier")
    if VALID_2026_QUALIFIER.fullmatch(qualifier) is None:
        raise RuntimeError(f"unrecognised 2026 limit qualifier: {value_raw!r}")
    return make_limit_cell(
        match.group("limit_value"),
        value_raw,
        qualifier,
    )


def normalize_pesticide_name(text: str) -> str:
    name = compact(text)
    return re.sub(r"(?<=[0-9A-Z])G(?=[0-9A-Z一-鿿])", "-", name)


def english_key(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def split_header_payload(payload: str) -> tuple[str, str] | None:
    """Split a compact Chinese-name/English-name heading payload."""

    for index, char in enumerate(payload):
        if char not in "([（［" or index + 1 >= len(payload):
            continue
        if not re.match(r"[A-Za-z0-9]", payload[index + 1]):
            continue
        name = normalize_pesticide_name(payload[:index])
        if not name or not re.search(r"[一-鿿]", name):
            return None
        english = payload[index + 1 :].rstrip(")]）］")
        return name, english
    return None


def parse_expected_header(
    text: str,
    expected_section: int,
    *,
    source_page: int,
    serial: int,
    apply_2026_fixes: bool = False,
    evidence: str = "body_header",
) -> SectionHeader | None:
    """Parse only the next expected heading, including digit-led names."""

    compact_text = compact(text)
    prefix = f"4.{expected_section}"
    if not compact_text.startswith(prefix):
        return None
    payload = compact_text[len(prefix) :]
    if not payload or payload.startswith("."):
        return None
    split = split_header_payload(payload)
    if split is None:
        return None
    pesticide_zh, pesticide_en = split
    if apply_2026_fixes and expected_section in SECTION_NAME_FIXES:
        corrected_name, expected_english = SECTION_NAME_FIXES[expected_section]
        if english_key(pesticide_en) != expected_english:
            raise RuntimeError(
                f"section {expected_section} English name changed: {pesticide_en}"
            )
        pesticide_zh = corrected_name
    return SectionHeader(
        section_number=expected_section,
        pesticide_zh=pesticide_zh,
        pesticide_en=pesticide_en,
        source_page=source_page,
        header_text=compact_text,
        serial=serial,
        evidence=evidence,
    )


def locate_source(source_root: Path, year: str) -> Path:
    matches = sorted(source_root.rglob(f"GB 2763-{year}*.pdf"))
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one GB 2763-{year} source PDF, found {len(matches)}"
        )
    return matches[0]


def confirm_header(
    pending: SectionHeader | None,
    *,
    expected_section: int,
    serial: int,
) -> SectionHeader:
    if pending is None:
        raise RuntimeError(f"section {expected_section} has no parsed heading")
    if pending.section_number != expected_section:
        raise RuntimeError(
            f"expected section {expected_section}, got {pending.section_number}"
        )
    if serial - pending.serial > HEADER_GAP_LIMIT:
        raise RuntimeError(
            f"section {expected_section} heading is stale by "
            f"{serial - pending.serial} lines"
        )
    return pending


def paginate_layout_text(text: str) -> list[tuple[int, str]]:
    """Preserve one-based PDF page numbers from Poppler form-feed markers."""

    return [
        (page_number, line)
        for page_number, page_text in enumerate(text.split("\f"), start=1)
        for line in page_text.splitlines()
    ]


def extract_legacy_toc_headers(
    lines: list[tuple[int, str]],
) -> dict[int, SectionHeader]:
    """Read body-heading fallbacks from the edition's own contents pages."""

    headers: dict[int, SectionHeader] = {}
    for serial, (source_page, line) in enumerate(lines):
        if "每种农药" in line:
            break
        match = re.match(r"^\s*4\.(\d+)\s+", line)
        if match is None:
            continue
        section_number = int(match.group(1))
        heading_text = re.sub(r"[.·…]{4,}.*$", "", line)
        header = parse_expected_header(
            heading_text,
            section_number,
            source_page=source_page,
            serial=serial,
            evidence="toc_fallback",
        )
        if header is not None:
            headers[section_number] = header
    return headers


def confirm_legacy_header(
    pending: SectionHeader | None,
    fallback: SectionHeader | None,
    *,
    expected_section: int,
    serial: int,
) -> SectionHeader:
    """Prefer a nearby body heading and use the source TOC if it is mangled."""

    if (
        pending is not None
        and pending.section_number == expected_section
        and serial - pending.serial <= HEADER_GAP_LIMIT
    ):
        return pending
    if fallback is not None and fallback.section_number == expected_section:
        return fallback
    return confirm_header(
        pending,
        expected_section=expected_section,
        serial=serial,
    )


def extract_legacy(pdf_path: Path, year: str) -> tuple[list[LimitRow], list[SectionHeader]]:
    text = run_pdftotext(["-layout", str(pdf_path), "-"]).decode(
        "utf-8", "replace"
    )
    raw_lines = paginate_layout_text(text)
    toc_headers = extract_legacy_toc_headers(raw_lines)
    lines = [
        (source_page, line)
        for source_page, line in raw_lines
        if ".........." not in line and "……" not in line
    ]
    rows: list[LimitRow] = []
    roster: list[SectionHeader] = []
    pending: SectionHeader | None = None
    current: SectionHeader | None = None
    parent = ""
    in_table = False
    started = False

    for serial, (source_page, line) in enumerate(lines):
        stripped = line.rstrip()
        if started and re.match(r"^\s*(资料性)?附\s*录", stripped):
            break
        expected_section = len(roster) + 1
        candidate = parse_expected_header(
            stripped,
            expected_section,
            source_page=source_page,
            serial=serial,
        )
        if candidate is not None:
            pending = candidate
        if "主要用途" in stripped:
            compact_use = compact(stripped)
            valid_main_use = {
                f"4.{expected_section}.1主要用途",
                f"4.{expected_section}1主要用途",
            }
            if not any(compact_use.startswith(prefix) for prefix in valid_main_use):
                raise RuntimeError(
                    f"expected section {expected_section} main-use marker: {stripped}"
                )
            current = confirm_legacy_header(
                pending,
                toc_headers.get(expected_section),
                expected_section=expected_section,
                serial=serial,
            )
            roster.append(current)
            pending = None
            parent = ""
            in_table = False
            started = True
            continue
        if current is None:
            continue
        if re.match(r"^\s*表\s*\d+\s*$", stripped) or "食品类别" in stripped:
            in_table = True
            continue
        if not in_table:
            continue
        if re.match(r"^\s*\d+\s*$", stripped) or any(
            marker in stripped
            for marker in ("GB 2763", "食品安全国家标准")
        ):
            continue
        match = LEGACY_VALUE.match(stripped)
        if match:
            food = compact(match.group("food"))
            if re.search(r"[一-鿿]", food):
                cell = limit_cell_from_legacy_match(match)
                rows.append(
                    LimitRow(
                        year=year,
                        pesticide_zh=current.pesticide_zh,
                        parent_category=parent,
                        food=food,
                        limit_value=cell.limit_value,
                        value_raw=cell.value_raw,
                        limit_qualifier=cell.limit_qualifier,
                        is_temporary=cell.is_temporary,
                        unit="mg/kg",
                        section_number=current.section_number,
                        source_page=source_page,
                        source_y=None,
                    )
                )
            continue
        category = compact(stripped)
        if category in PARENTS:
            parent = category

    validate_counts(year, rows, roster)
    return rows, roster


def bbox_pages(pdf_path: Path) -> list[list[Word]]:
    xml = run_pdftotext(["-bbox-layout", str(pdf_path), "-"]).decode(
        "utf-8", "replace"
    )
    root = ET.fromstring(xml)
    pages: list[list[Word]] = []
    for page in root.iter(NS + "page"):
        words: list[Word] = []
        for word in page.iter(NS + "word"):
            value = normalize_2026((word.text or "").strip())
            if value:
                words.append(
                    (
                        float(word.get("xMin")),
                        float(word.get("xMax")),
                        float(word.get("yMin")),
                        value,
                    )
                )
        pages.append(words)
    return pages


def cluster_rows(words: list[Word], tolerance: float = 6.0) -> list[list[Word]]:
    rows: list[list[Word]] = []
    current: list[Word] = []
    last_y: float | None = None
    for word in sorted(words, key=lambda item: item[2]):
        if last_y is not None and word[2] - last_y > tolerance:
            rows.append(current)
            current = []
        current.append(word)
        last_y = word[2]
    if current:
        rows.append(current)
    return rows


def row_text(words: list[Word]) -> str:
    return "".join(word[3] for word in sorted(words, key=lambda item: item[0]))


def validate_unique_2026_rules(rows: list[LimitRow]) -> list[LimitRow]:
    """Reject exact duplicate rules; retain same-food rules with distinct scope."""

    seen: dict[tuple[str, str, str, str, str, str, int], LimitRow] = {}
    for row in rows:
        validate_limit_row(row)
        key = (
            row.pesticide_zh,
            row.parent_category,
            row.food,
            row.limit_value,
            row.unit,
            row.limit_qualifier,
            row.is_temporary,
        )
        previous = seen.get(key)
        if previous is not None:
            raise RuntimeError(
                "exact duplicate 2026 rule without verified continuation: "
                f"{key}; pages {previous.source_page} and {row.source_page}"
            )
        seen[key] = row
    return rows


def validate_limit_row(row: LimitRow) -> None:
    """Reject a qualifier, raw cell and temporary flag that disagree."""

    expected_raw = f"{row.limit_value}{row.limit_qualifier}"
    expected_temporary = int(
        "*" in row.limit_qualifier or "∗" in row.limit_qualifier
    )
    if row.value_raw != expected_raw or row.is_temporary != expected_temporary:
        raise RuntimeError(
            "inconsistent limit qualifier fields: "
            f"{row.value_raw!r}, {row.limit_qualifier!r}, {row.is_temporary!r}"
        )


def validate_2026_parent_scopes(rows: list[LimitRow]) -> dict[str, object]:
    """Reject stale plant-parent carry-over for explicit animal foods."""

    checked: dict[str, int] = {}
    violations: list[dict[str, object]] = []
    for group, (foods, parent_prefix) in ANIMAL_PARENT_PREFIXES.items():
        candidates = [row for row in rows if row.food in foods]
        checked[group] = len(candidates)
        for row in candidates:
            if not row.parent_category.startswith(parent_prefix):
                violations.append(
                    {
                        "group": group,
                        "pesticide": row.pesticide_zh,
                        "food": row.food,
                        "parent": row.parent_category,
                        "source_page": row.source_page,
                    }
                )
    if violations:
        raise RuntimeError(
            "2026 animal-food parent scope regression: "
            + json.dumps(violations[:10], ensure_ascii=False, sort_keys=True)
        )
    return {"checked_rows": checked, "violations": 0}


def extract_2026(pdf_path: Path) -> tuple[list[LimitRow], list[SectionHeader]]:
    rows: list[LimitRow] = []
    roster: list[SectionHeader] = []
    pending: SectionHeader | None = None
    current: SectionHeader | None = None
    parent = ""
    serial = 0
    in_backmatter = False

    for page_number, words in enumerate(bbox_pages(pdf_path), start=1):
        for visual_row in cluster_rows(words):
            serial += 1
            text = row_text(visual_row)
            if roster and re.search(r"通用名称索引|^附录[A-Z]", text):
                in_backmatter = True
            if in_backmatter:
                continue
            expected_section = len(roster) + 1
            candidate = parse_expected_header(
                text,
                expected_section,
                source_page=page_number,
                serial=serial,
                apply_2026_fixes=True,
            )
            if candidate is not None:
                pending = candidate
                continue
            if "主要用途" in text:
                current = confirm_header(
                    pending,
                    expected_section=expected_section,
                    serial=serial,
                )
                roster.append(current)
                pending = None
                parent = ""
                continue
            if current is None:
                continue
            categories = [word for word in visual_row if word[1] < CAT_X]
            values = [word for word in visual_row if word[0] >= CAT_X]
            category = compact(row_text(categories))
            if (
                not category
                or NOISE_2026.search(category)
                or not re.search(r"[一-鿿]", category)
            ):
                continue
            if category in PARENTS:
                parent = category
                if not values:
                    continue
            value_text = row_text(values)
            if re.search(r"[A-Za-z]{3,}", category) or len(category) > 16:
                continue
            cell = parse_2026_limit_cell(value_text)
            if cell is None:
                continue
            rows.append(
                LimitRow(
                    year="2026",
                    pesticide_zh=current.pesticide_zh,
                    parent_category=parent,
                    food=category,
                    limit_value=cell.limit_value,
                    value_raw=cell.value_raw,
                    limit_qualifier=cell.limit_qualifier,
                    is_temporary=cell.is_temporary,
                    unit="mg/kg",
                    section_number=current.section_number,
                    source_page=page_number,
                    source_y=min(word[2] for word in visual_row),
                )
            )

    rows = validate_unique_2026_rules(rows)
    validate_2026_parent_scopes(rows)
    validate_counts("2026", rows, roster)
    return rows, roster


def validate_counts(
    year: str,
    rows: list[LimitRow],
    roster: list[SectionHeader],
) -> None:
    expected = EXPECTED[year]
    for row in rows:
        validate_limit_row(row)
    entities = {row.pesticide_zh for row in rows}
    observed = {
        "rows": len(rows),
        "entities": len(entities),
        "sections": len(roster),
    }
    if observed != expected:
        raise RuntimeError(f"{year} extraction count mismatch: {observed} != {expected}")
    if year in LEGACY_TEMPORARY_COUNTS:
        temporary_rows = sum(row.is_temporary for row in rows)
        expected_temporary = LEGACY_TEMPORARY_COUNTS[year]
        if temporary_rows != expected_temporary:
            raise RuntimeError(
                f"{year} temporary-limit count mismatch: "
                f"{temporary_rows} != {expected_temporary}"
            )
    if year == "2026":
        sections = [header.section_number for header in roster]
        if sections != list(range(1, expected["sections"] + 1)):
            raise RuntimeError("2026 section roster is not complete and sequential")
        if len({header.pesticide_zh for header in roster}) != expected["entities"]:
            raise RuntimeError("2026 section roster contains duplicate pesticide names")


def write_csv(path: Path, header: list[str], rows: list[tuple[object, ...]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def summarize_qualifiers(rows: list[LimitRow]) -> dict[str, object]:
    """Report printed qualifiers separately from the numeric row count."""

    by_qualifier: dict[str, int] = {}
    for row in rows:
        if row.limit_qualifier:
            by_qualifier[row.limit_qualifier] = (
                by_qualifier.get(row.limit_qualifier, 0) + 1
            )
    return {
        "qualified_rows": sum(by_qualifier.values()),
        "temporary_rows": sum(row.is_temporary for row in rows),
        "by_qualifier": dict(sorted(by_qualifier.items())),
    }


def build(source_root: Path, output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    legacy_rows: list[LimitRow] = []
    sources: dict[str, dict[str, object]] = {}
    counts: dict[str, dict[str, int]] = {}
    qualifier_counts: dict[str, dict[str, object]] = {}
    section_roster: list[tuple[str, SectionHeader]] = []

    for year in LEGACY_YEARS:
        source = locate_source(source_root, year)
        rows, roster = extract_legacy(source, year)
        legacy_rows.extend(rows)
        section_roster.extend((year, header) for header in roster)
        sources[year] = {
            "filename": source.name,
            "sha256": sha256_file(source),
        }
        counts[year] = {
            "rows": len(rows),
            "entities": len({row.pesticide_zh for row in rows}),
            "sections": len(roster),
        }
        qualifier_counts[year] = summarize_qualifiers(rows)

    source_2026 = locate_source(source_root, "2026")
    rows_2026, roster_2026 = extract_2026(source_2026)
    parent_scope_validation = validate_2026_parent_scopes(rows_2026)
    section_roster.extend(("2026", header) for header in roster_2026)
    sources["2026"] = {
        "filename": source_2026.name,
        "sha256": sha256_file(source_2026),
    }
    counts["2026"] = {
        "rows": len(rows_2026),
        "entities": len({row.pesticide_zh for row in rows_2026}),
        "sections": len(roster_2026),
    }
    qualifier_counts["2026"] = summarize_qualifiers(rows_2026)

    write_csv(
        output_dir / "pesticide_limits_2012_2016.csv",
        [
            "year",
            "农药",
            "parent_category",
            "food",
            "limit_value",
            "value_raw",
            "limit_qualifier",
            "is_temporary",
            "unit",
            "section_number",
            "source_page",
            "source_y",
        ],
        legacy_rows,
    )
    write_csv(
        output_dir / "pesticide_2026_long.csv",
        [
            "year",
            "农药",
            "parent_category",
            "food",
            "limit_value",
            "value_raw",
            "limit_qualifier",
            "is_temporary",
            "unit",
            "section_number",
            "source_page",
            "source_y",
        ],
        rows_2026,
    )
    write_csv(
        output_dir / "pesticide_2026_section_roster.csv",
        [
            "section_number",
            "pesticide_zh",
            "pesticide_en",
            "source_page",
            "evidence",
            "header_text",
        ],
        [
            (
                header.section_number,
                header.pesticide_zh,
                header.pesticide_en,
                header.source_page,
                header.evidence,
                header.header_text,
            )
            for header in roster_2026
        ],
    )
    write_csv(
        output_dir / "pesticide_text_section_roster.csv",
        [
            "year",
            "section_number",
            "pesticide_zh",
            "pesticide_en",
            "source_page",
            "evidence",
            "header_text",
        ],
        [
            (
                year,
                header.section_number,
                header.pesticide_zh,
                header.pesticide_en,
                header.source_page,
                header.evidence,
                header.header_text,
            )
            for year, header in section_roster
        ],
    )

    expected_roster_rows = sum(item["sections"] for item in EXPECTED.values())
    if len(section_roster) != expected_roster_rows:
        raise RuntimeError(
            f"section roster count mismatch: {len(section_roster)} != "
            f"{expected_roster_rows}"
        )
    if any(header.source_page <= 0 for _, header in section_roster):
        raise RuntimeError("section roster contains a non-positive source page")

    report: dict[str, object] = {
        "sources": sources,
        "counts": counts,
        "qualifier_counts": qualifier_counts,
        "outputs": {
            "legacy": "pesticide_limits_2012_2016.csv",
            "edition_2026": "pesticide_2026_long.csv",
            "section_roster_2026": "pesticide_2026_section_roster.csv",
            "section_roster_text_editions": "pesticide_text_section_roster.csv",
        },
        "edition_2026_reference": {
            "official_mrl_count": OFFICIAL_2026_MRL_COUNT,
            "official_pesticide_count": OFFICIAL_2026_PESTICIDE_COUNT,
            "extracted_value_rows": len(rows_2026),
            "row_count_coverage_proxy": len(rows_2026) / OFFICIAL_2026_MRL_COUNT,
            "proxy_note": (
                "Extracted-row count divided by the official MRL count; "
                "this is a row-count coverage proxy, not recall or precision."
            ),
            "unrecovered_value_count": OFFICIAL_2026_MRL_COUNT - len(rows_2026),
            "limited_pesticide_sections": len(roster_2026),
            "official_pesticide_minus_numbered_sections": (
                OFFICIAL_2026_PESTICIDE_COUNT - len(roster_2026)
            ),
            "appendix_b_exempt_list_entries": APPENDIX_B_2026_ENTRY_COUNT,
        },
        "edition_2026_parent_scope_validation": parent_scope_validation,
    }
    (output_dir / "pesticide_text_extraction_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build(args.source_root.resolve(), args.output_dir.resolve())
    print(json.dumps(report["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
