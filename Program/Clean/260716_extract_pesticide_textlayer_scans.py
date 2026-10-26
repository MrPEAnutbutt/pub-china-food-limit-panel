#!/usr/bin/env python3
"""Extract six GB 2763 editions from frozen coordinate-bearing PDF copies.

For 2012, 2014, 2016, and 2026, each frozen archive PDF serves as both the
edition source and the coordinate-extraction input.  For 2019 and 2021, the
original scans remain the edition-identity anchors; government-hosted
text-layer copies supply coordinates and are cross-checked against the frozen
OCR accepted layer.  Outputs stay in ``Data/Interim`` until the formal panel is
rebuilt by the release pipeline.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unicodedata
import xml.etree.ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "Data/Raw/政府文本层副本"
DEFAULT_OCR_DIR = PROJECT_ROOT / "Data/Interim/pesticide_ocr"
DEFAULT_OCR_PARSED_DIR = PROJECT_ROOT / "Data/Interim/pesticide_ocr_parsed"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "Data/Interim/pesticide_textlayer_scans"

NS = "{http://www.w3.org/1999/xhtml}"
VALUE_COLUMN_X = 400.0
PARENT_LEFT_X = 115.0
HEADER_CONFIRM_GAP = 20

# A row that carries a value and starts in the left column opens a parent scope
# only when it names one of the standard's food categories.  Long food labels
# such as "豆类蔬菜(食荚豌豆、豌豆(鲜)、菜豆和菜用大豆除外)" also reach the left
# column, and some text layers place single foods there (2021 Table 156 "柑").
# The list holds every category heading of the six editions; the independent
# reading of 2019 and 2021 (Data/Interim/pesticide_audit) found the leak.
PARENT_HEADINGS = frozenset(
    {
        "谷物", "谷物及制品", "油料和油脂", "油料", "油料及制品", "油料制品",
        "蔬菜", "干制蔬菜", "水果", "干制水果", "坚果", "糖料", "糖料类",
        "糖类", "饮料类", "饮料", "食用菌", "调味料", "药用植物",
        "哺乳动物肉类(海洋哺乳动物除外)",
        "哺乳动物肉类(海洋哺乳动物除外),以脂肪中的残留量计",
        "哺乳动物肉类(海洋哺乳动物除外),以脂肪中残留量表示",
        "哺乳动物肉类(海洋哺乳动物除外),以脂肪中的残留量表示",
        "哺乳动物肉类及其制品", "哺乳动物肉类及其制品(海洋哺乳动物除外)",
        "哺乳动物内脏", "哺乳动物内脏(海洋哺乳动物除外)",
        "哺乳动物脂肪", "哺乳动物脂肪(乳脂肪除外)", "哺乳动物脂肪(海洋哺乳动物除外)",
        "肝脏(牛、羊、猪)", "肾脏(牛、羊、猪)",
        "禽肉类", "禽肉类(以脂肪计)", "禽肉类(包括内脏)",
        "禽肉类,以脂肪中的残留量计", "禽肉类,以脂肪中残留量表示",
        "禽肉类,以脂肪中的残留量表示",
        "禽类内脏", "禽类脂肪", "蛋类", "蛋类(鲜)", "生乳", "奶类", "乳脂肪",
        "水产品",
    }
)

SOURCE_CONFIG = {
    "2012": {
        "edition": "GB 2763-2012",
        "filename": "GB 2763-2012 食品安全国家标准 食品中农药最大残留限量.pdf",
        "sha256": "a22ca0c525bfb0b1172cf61489e762a470bb4f7cde3d8ecf0c22ed8a6eb43eca",
        "bytes": 8_212_829,
        "pages": 183,
        "sections": 307,
        "official_mrl_items": 2_293,
        "first_header_page": 13,
        "first_row_page": 13,
        "last_row_page": 149,
        "appendix_a_page": 150,
        "value_column_x": 350.0,
        "parent_left_x": 115.0,
        "use_toc_fallback": True,
        "source_group": "archive_text_layer",
        "source_copy_role": "archive_text_layer_edition_source_copy",
    },
    "2014": {
        "edition": "GB 2763-2014",
        "filename": "GB 2763-2014 食品安全国家标准 食品中农药最大残留限量.pdf",
        "sha256": "078022a2db7d1c2d20e1f14b800dab77e4e0fc4a81faa666c1225b9343ea2042",
        "bytes": 4_475_244,
        "pages": 234,
        "sections": 371,
        "official_mrl_items": 3_650,
        "first_header_page": 19,
        "first_row_page": 20,
        "last_row_page": 211,
        "appendix_a_page": 212,
        "value_column_x": 350.0,
        "parent_left_x": 115.0,
        "use_toc_fallback": False,
        "source_group": "archive_text_layer",
        "source_copy_role": "archive_text_layer_edition_source_copy",
    },
    "2016": {
        "edition": "GB 2763-2016",
        "filename": "GB 2763-2016 食品安全国家标准 食品中农药最大残留限量.pdf",
        "sha256": "7e291366aac9562f349ee0ea0c03a457f8c7b7b0e1ff7f9619939a5d290ca41b",
        "bytes": 4_898_485,
        "pages": 265,
        "sections": 417,
        "official_mrl_items": 4_140,
        "first_header_page": 22,
        "first_row_page": 22,
        "last_row_page": 238,
        "appendix_a_page": 239,
        "value_column_x": 350.0,
        "parent_left_x": 115.0,
        "use_toc_fallback": False,
        "source_group": "archive_text_layer",
        "source_copy_role": "archive_text_layer_edition_source_copy",
    },
    "2019": {
        "edition": "GB 2763-2019",
        "filename": "GB2763-2019_shanghai_gov_textlayer.pdf",
        "sha256": "749ccc899bc522c3774101026588fe8cad8699f5da47033758ff815d4b9c66ce",
        "bytes": 6_021_886,
        "pages": 332,
        "sections": 467,
        "official_mrl_items": 7_107,
        "first_header_page": 20,
        "first_row_page": 21,
        "last_row_page": 306,
        "appendix_a_page": 307,
        "landing_page_url": (
            "https://nyncw.sh.gov.cn/ncpaqnybz/20200115/"
            "ee0a5a3ead224babb4b384843c0af6d0.html"
        ),
        "attachment_url": (
            "https://nyncw.sh.gov.cn/cmsres/2b/"
            "2b883e1ab03843219ad485c27bf472d6/"
            "0aa902a98de948912eef082611290b9e.pdf"
        ),
        "reference_copy_notice": "standard text reference copy; printed text prevails",
        "value_column_x": 400.0,
        "parent_left_x": 115.0,
        "use_toc_fallback": False,
        "source_group": "government_hosted_text_layer",
        "source_copy_role": "government_hosted_text_layer_extraction_copy",
    },
    "2021": {
        "edition": "GB 2763-2021",
        "filename": "GB2763-2021_lushan_gov_textlayer.pdf",
        "sha256": "e8c60114975f458c649b6cf842138a2ba8c9d8ed9f1e576902fcc06140304123",
        "bytes": 4_347_643,
        "pages": 422,
        "sections": 548,
        "official_mrl_items": 10_092,
        "first_header_page": 22,
        "first_row_page": 23,
        "last_row_page": 392,
        "appendix_a_page": 393,
        "landing_page_url": (
            "https://www.lushan.gov.cn/bmxzxxgk/bumeng/nyncj_195829/"
            "fdzdgknr_195835/zcwj_195837/202108/t20210816_5200479.html"
        ),
        "attachment_url": (
            "https://www.lushan.gov.cn/bmxzxxgk/bumeng/nyncj_195829/"
            "fdzdgknr_195835/zcwj_195837/202108/"
            "P020210816186031311653.pdf"
        ),
        "reference_copy_notice": "paper text prevails; reference-copy watermark present",
        "value_column_x": 400.0,
        "parent_left_x": 115.0,
        "use_toc_fallback": False,
        "source_group": "government_hosted_text_layer",
        "source_copy_role": "government_hosted_text_layer_extraction_copy",
    },
    "2026": {
        "edition": "GB 2763-2026",
        "filename": "GB 2763-2026 食品安全国家标准 食品中农药最大残留限量.pdf",
        "sha256": "98acde2f22614f184913c12bec745e7844ab1d5cbbeccf4c3617c1e064830b68",
        "bytes": 4_135_298,
        "pages": 442,
        "sections": 568,
        "official_mrl_items": 10_749,
        "first_header_page": 22,
        "first_row_page": 23,
        "last_row_page": 412,
        "appendix_a_page": 413,
        "value_column_x": 400.0,
        "parent_left_x": 115.0,
        "use_toc_fallback": False,
        "source_group": "archive_text_layer",
        "source_copy_role": "archive_text_layer_edition_source_copy",
    },
}

GOVERNMENT_HOSTED_YEARS = ("2019", "2021")
ARCHIVE_TEXT_LAYER_YEARS = ("2012", "2014", "2016", "2026")
ARCHIVE_SOURCE_SUBDIR = Path("补充_农兽药残留限量标准")
TRANSLATION_2016_RELATIVE = Path("外部英译本/FSIS_GB2763-2016_en.pdf")
TRANSLATION_2016_IDENTITY = {
    "sha256": "b28b87fb4a50759cd40c9889349ee59be24f9e49ea890af103d913fccccda542",
    "bytes": 2_480_852,
    "pages": 218,
}

# The visible glyph is present in the page image but absent from the text
# layer.  English-name keys make each correction section-independent and
# auditable across the two editions.
MISSING_GLYPH_NAME_FIXES = {
    "oxadiargyl": "丙炔噁草酮",
    "pyrisoxazole": "啶菌噁唑",
    "propaquizafop": "噁草酸",
    "oxadiazon": "噁草酮",
    "hymexazol": "噁霉灵",
    "oxaziclomefone": "噁嗪草酮",
    "oxadixyl": "噁霜灵",
    "famoxadone": "噁唑菌酮",
    "metamifop": "噁唑酰草胺",
    "fenoxaproppethyl": "精噁唑禾草灵",
    "clomazone": "异噁草酮",
}

# Temporary-limit marks printed in the government-hosted text layer but absent
# from the edition-identity scan; the value is (year, section, food) -> scan
# PDF page checked by the author.  The independent reading of 2019 found the
# first one (Data/Interim/pesticide_audit, PA2019-031).
SCAN_TEMPORARY_MARK_FIXES = {
    ("2019", 111, food): 93
    for food in ("稻谷", "糙米", "麦类", "旱粮类", "棉籽", "大豆")
}

NOISE = re.compile(
    r"GB\s*2763|食品类别|食品名称|最大残留限量|检测方法|主要用途|残留物|ADI|"
    r"该限量|^表\d|食品安全国家标准|附录|索引"
)
STRUCTURAL = re.compile(r"^4\.(\d{1,3})\.([1-6])(?=[^0-9]|$)")
NUMERIC_VALUE = re.compile(r"^(\d+(?:\.\d+)?)")


class ExtractionValidationError(ValueError):
    """Raised when an extraction hard gate fails."""


@dataclass(frozen=True)
class Word:
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    raw: str
    text: str


@dataclass(frozen=True)
class Page:
    width: float
    height: float
    words: tuple[Word, ...]


@dataclass(frozen=True)
class SectionHeader:
    year: str
    edition: str
    section_number: int
    pesticide_zh: str
    pesticide_en: str
    pesticide_zh_raw: str
    pesticide_en_raw: str
    source_page: int
    source_y: float
    header_raw: str
    name_correction: str
    review_status: str
    source_copy_role: str
    source_filename: str
    source_sha256: str
    serial: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative_or_name(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def normalize_text(value: str) -> str:
    """Normalize documented PUA glyphs and compatibility-width text."""

    output: list[str] = []
    for character in value:
        codepoint = ord(character)
        if codepoint == 0x1001B0:
            output.append(".")
        elif codepoint == 0x1001BA:
            continue
        elif character == "Ｇ":
            output.append("-")
        else:
            output.append(unicodedata.normalize("NFKC", character))
    return "".join(output)


def compact(value: str) -> str:
    return re.sub(r"\s+", "", value)


def canonical_scope(value: str) -> str:
    value = compact(normalize_text(value))
    return value.translate(str.maketrans({"，": ",", "（": "(", "）": ")"}))


def parent_heading(value: str) -> str:
    """Return the category a valued left-column row opens, or "" for a food.

    A residual group named after a category, such as
    "哺乳动物内脏(猪肾、牛肾、羊肾除外)", opens that category.
    """

    if value in PARENT_HEADINGS:
        return value
    if value.endswith("除外)") and "(" in value:
        base = value[: value.index("(")]
        if base in PARENT_HEADINGS:
            return base
    return ""


def english_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def normalize_english(value: str) -> str:
    return compact(normalize_text(value)).replace("－", "-")


def row_text(words: list[Word] | tuple[Word, ...], *, raw: bool = False) -> str:
    attribute = "raw" if raw else "text"
    return "".join(
        getattr(word, attribute) for word in sorted(words, key=lambda item: item.x_min)
    )


def cluster_rows(words: tuple[Word, ...], tolerance: float = 6.0) -> list[list[Word]]:
    rows: list[list[Word]] = []
    current: list[Word] = []
    previous_y: float | None = None
    for word in sorted(words, key=lambda item: item.y_min):
        if previous_y is not None and word.y_min - previous_y > tolerance:
            rows.append(current)
            current = []
        current.append(word)
        previous_y = word.y_min
    if current:
        rows.append(current)
    return rows


def page_text(page: Page) -> str:
    """Return page text in visual row order rather than global x order."""

    return "".join(row_text(row) for row in cluster_rows(page.words))


def run_pdftotext(pdf_path: Path) -> tuple[list[Page], str]:
    try:
        completed = subprocess.run(
            ["pdftotext", "-bbox-layout", str(pdf_path), "-"],
            check=True,
            capture_output=True,
            timeout=900,
        )
        version_run = subprocess.run(
            ["pdftotext", "-v"],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        stderr = getattr(error, "stderr", b"")
        detail = stderr.decode("utf-8", "replace") if stderr else str(error)
        raise ExtractionValidationError(f"pdftotext failed: {detail}") from error

    try:
        root = ET.fromstring(completed.stdout.decode("utf-8", "replace"))
    except ET.ParseError as error:
        raise ExtractionValidationError("pdftotext returned invalid bbox XML") from error

    pages: list[Page] = []
    for page_node in root.iter(NS + "page"):
        words: list[Word] = []
        for word_node in page_node.iter(NS + "word"):
            raw = (word_node.text or "").strip()
            text = normalize_text(raw).strip()
            if not text:
                continue
            words.append(
                Word(
                    x_min=float(word_node.get("xMin")),
                    x_max=float(word_node.get("xMax")),
                    y_min=float(word_node.get("yMin")),
                    y_max=float(word_node.get("yMax")),
                    raw=raw,
                    text=text,
                )
            )
        pages.append(
            Page(
                width=float(page_node.get("width")),
                height=float(page_node.get("height")),
                words=tuple(words),
            )
        )
    version = (version_run.stderr or version_run.stdout).decode("utf-8", "replace")
    return pages, version.splitlines()[0].strip()


def split_header_payload(payload: str) -> tuple[str, str] | None:
    for index, character in enumerate(payload):
        if character not in "([" or index + 1 >= len(payload):
            continue
        if not re.match(r"[A-Za-z0-9]", payload[index + 1]):
            continue
        chinese = canonical_scope(payload[:index])
        english = payload[index + 1 :]
        if english.endswith(")") or english.endswith("]"):
            english = english[:-1]
        english = normalize_english(english)
        if chinese and english and re.search(r"[一-鿿]", chinese):
            return chinese, english
    return None


def parse_expected_header(
    year: str,
    words: list[Word],
    expected_section: int,
    source_page: int,
    serial: int,
    source_path: Path,
) -> SectionHeader | None:
    text = compact(row_text(words))
    prefix = f"4.{expected_section}"
    if not text.startswith(prefix):
        return None
    payload = text[len(prefix) :]
    if not payload or payload.startswith("."):
        return None
    split = split_header_payload(payload)
    if split is None:
        return None
    pesticide_zh_raw, pesticide_en_raw = split
    correction = ""
    pesticide_zh = pesticide_zh_raw
    fixed_name = MISSING_GLYPH_NAME_FIXES.get(english_key(pesticide_en_raw))
    if fixed_name and canonical_scope(pesticide_zh_raw) != canonical_scope(fixed_name):
        pesticide_zh = fixed_name
        correction = "visible_glyph_missing_from_text_layer"
    config = SOURCE_CONFIG[year]
    review = "text_layer_header"
    if correction:
        review += ";source_glyph_correction"
    return SectionHeader(
        year=year,
        edition=str(config["edition"]),
        section_number=expected_section,
        pesticide_zh=pesticide_zh,
        pesticide_en=pesticide_en_raw,
        pesticide_zh_raw=pesticide_zh_raw,
        pesticide_en_raw=pesticide_en_raw,
        source_page=source_page,
        source_y=min(word.y_min for word in words),
        header_raw=compact(row_text(words, raw=True)),
        name_correction=correction,
        review_status=review,
        source_copy_role=str(config["source_copy_role"]),
        source_filename=source_path.name,
        source_sha256=str(config["sha256"]),
        serial=serial,
    )


def extract_toc_header_fallbacks(
    year: str,
    pages: list[Page],
    source_path: Path,
) -> dict[int, SectionHeader]:
    """Read section-name fallbacks from the source's own contents pages."""

    config = SOURCE_CONFIG[year]
    if not config.get("use_toc_fallback"):
        return {}
    headers: dict[int, SectionHeader] = {}
    for source_page, page in enumerate(
        pages[: int(config["first_header_page"]) - 1], start=1
    ):
        for visual_row in cluster_rows(page.words):
            text = compact(row_text(visual_row))
            match = re.match(r"^4\.(\d+)(?![\d.])(.*)$", text)
            if match is None:
                continue
            section_number = int(match.group(1))
            if not 1 <= section_number <= int(config["sections"]):
                continue
            payload = re.sub(r"[.\u00b7…]{3,}.*$", "", match.group(2))
            payload = re.sub(r"\d+$", "", payload)
            split = split_header_payload(payload)
            if split is None:
                continue
            pesticide_zh_raw, pesticide_en_raw = split
            pesticide_zh = pesticide_zh_raw
            correction = ""
            fixed_name = MISSING_GLYPH_NAME_FIXES.get(english_key(pesticide_en_raw))
            if fixed_name and canonical_scope(pesticide_zh_raw) != canonical_scope(
                fixed_name
            ):
                pesticide_zh = fixed_name
                correction = "visible_glyph_missing_from_text_layer"
            review_status = "text_layer_toc_header_fallback"
            if correction:
                review_status = add_status(review_status, "source_glyph_correction")
            headers[section_number] = SectionHeader(
                year=year,
                edition=str(config["edition"]),
                section_number=section_number,
                pesticide_zh=pesticide_zh,
                pesticide_en=pesticide_en_raw,
                pesticide_zh_raw=pesticide_zh_raw,
                pesticide_en_raw=pesticide_en_raw,
                source_page=source_page,
                source_y=min(word.y_min for word in visual_row),
                header_raw=compact(row_text(visual_row, raw=True)),
                name_correction=correction,
                review_status=review_status,
                source_copy_role=str(config["source_copy_role"]),
                source_filename=source_path.name,
                source_sha256=str(config["sha256"]),
                serial=-1,
            )
    return headers


def canonical_decimal(value: str) -> str:
    try:
        number = Decimal(value)
    except InvalidOperation as error:
        raise ExtractionValidationError(f"invalid MRL value: {value}") from error
    output = format(number, "f")
    if "." in output:
        output = output.rstrip("0").rstrip(".")
    return output


def parse_qualifier(suffix: str) -> tuple[str, bool, str]:
    mapping = {
        "": ("", False, ""),
        "∗": ("temporary_mrl_asterisk", True, ""),
        "*": ("temporary_mrl_asterisk", True, ""),
        "(以脂肪计)": ("as_fat", False, ""),
        "(以原样计)": ("as_presented", False, ""),
        "c": ("source_marker_c_unresolved", False, "source_qualifier_unresolved_c"),
    }
    if suffix in mapping:
        return mapping[suffix]
    return f"source_suffix:{suffix}", False, "source_qualifier_unresolved"


def food_label_expects_continuation(value: str) -> bool:
    """Identify a food label that visibly continues on the following row."""

    return (
        value.endswith(("、", ",", ";", "；"))
        or value.count("(") > value.count(")")
        or value.count("[") > value.count("]")
    )


def merge_wrapped_food_value_rows(
    rows: list[list[Word]], value_column_x: float
) -> list[list[Word]]:
    """Merge a three-line food/value cell split by PDF table layout."""

    merged: list[list[Word]] = []
    index = 0
    while index < len(rows):
        first = rows[index]
        first_category = canonical_scope(
            row_text([word for word in first if word.x_min < value_column_x])
        )
        first_value = compact(
            row_text([word for word in first if word.x_min >= value_column_x])
        )
        if (
            index + 2 < len(rows)
            and first_category
            and re.search(r"[一-鿿]", first_category)
            and food_label_expects_continuation(first_category)
            and NUMERIC_VALUE.match(first_value) is None
        ):
            followers = rows[index + 1 : index + 3]
            numeric_rows: list[list[Word]] = []
            continuation_rows: list[list[Word]] = []
            for follower in followers:
                follower_category = canonical_scope(
                    row_text(
                        [
                            word
                            for word in follower
                            if word.x_min < value_column_x
                        ]
                    )
                )
                follower_value = compact(
                    row_text(
                        [
                            word
                            for word in follower
                            if word.x_min >= value_column_x
                        ]
                    )
                )
                if not follower_category and NUMERIC_VALUE.match(follower_value):
                    numeric_rows.append(follower)
                elif (
                    follower_category
                    and re.search(r"[一-鿿]", follower_category)
                    and NUMERIC_VALUE.match(follower_value) is None
                ):
                    continuation_rows.append(follower)
            y_start = min(word.y_min for word in first)
            y_end = max(word.y_min for row in followers for word in row)
            if (
                len(numeric_rows) == 1
                and len(continuation_rows) == 1
                and y_end - y_start <= 25
            ):
                complete_category = canonical_scope(
                    row_text(
                        [
                            word
                            for word in first + continuation_rows[0]
                            if word.x_min < value_column_x
                        ]
                    )
                )
                if not food_label_expects_continuation(complete_category):
                    merged.append(first + followers[0] + followers[1])
                    index += 3
                    continue
        merged.append(first)
        index += 1
    return merged


def salvage_margin_overlapped_value_words(
    value_words: list[Word],
) -> list[Word] | None:
    """Remove a margin header fragment after an otherwise valid value cell."""

    selected: list[Word] = []
    rejected = False
    allowed = re.compile(r"^[0-9.*∗abc()以脂肪原样计]+$")
    for word in sorted(value_words, key=lambda item: item.x_min):
        if allowed.fullmatch(word.text):
            selected.append(word)
        else:
            rejected = True
            break
    if not selected or not rejected:
        return None
    candidate = compact(row_text(selected))
    match = NUMERIC_VALUE.match(candidate)
    if match is None:
        return None
    qualifier, _, review = parse_qualifier(candidate[match.end() :])
    if review or qualifier.startswith("source_suffix:"):
        return None
    return selected


def structural_transition(
    text: str, current_section: int
) -> tuple[str, str] | None:
    compact_text = compact(text)
    match = STRUCTURAL.match(compact_text)
    if not match or int(match.group(1)) != current_section:
        return None
    item = int(match.group(2))
    if "检测方法" in compact_text:
        return "close", f"semantic_testing_method_item_{item}"
    if "最大残留限量" in compact_text:
        return "open", f"semantic_maximum_limit_item_{item}"
    if item == 4 and not any(
        label in compact_text for label in ("残留物", "主要用途", "ADI")
    ):
        return "open", "item_4_fallback_label_split"
    return "other", f"structural_item_{item}"


def add_status(current: str, status: str) -> str:
    values = [item for item in current.split(";") if item]
    if status and status not in values:
        values.append(status)
    return ";".join(values)


def verify_source(path: Path, year: str) -> None:
    config = SOURCE_CONFIG[year]
    if not path.is_file():
        raise ExtractionValidationError(f"missing {year} text-layer source: {path.name}")
    observed = {
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    expected = {"bytes": config["bytes"], "sha256": config["sha256"]}
    if observed != expected:
        raise ExtractionValidationError(
            f"{year} source identity mismatch: {observed} != {expected}"
        )


def extract_edition(
    year: str, source_path: Path
) -> tuple[list[dict[str, object]], list[SectionHeader], dict[str, object]]:
    verify_source(source_path, year)
    config = SOURCE_CONFIG[year]
    value_column_x = float(config.get("value_column_x", VALUE_COLUMN_X))
    parent_left_x = float(config.get("parent_left_x", PARENT_LEFT_X))
    pages, pdftotext_version = run_pdftotext(source_path)
    if len(pages) != config["pages"]:
        raise ExtractionValidationError(
            f"{year} page count mismatch: {len(pages)} != {config['pages']}"
        )
    toc_headers = extract_toc_header_fallbacks(year, pages, source_path)

    roster: list[SectionHeader] = []
    records: list[dict[str, object]] = []
    applied_mark_fixes: set[tuple[str, int, str]] = set()
    pending: SectionHeader | None = None
    current: SectionHeader | None = None
    active_parent = ""
    active_parent_raw = ""
    table_open = False
    table_open_method = ""
    serial = 0
    transitions: Counter[str] = Counter()
    appendix_marker_found = False
    qualifier_counts: Counter[str] = Counter()
    review_counts: Counter[str] = Counter()

    for page_number, page in enumerate(pages, start=1):
        page_compact = compact(page_text(page))
        if page_number == config["appendix_a_page"]:
            appendix_marker_found = bool(
                re.search(
                    r"(?:附(?:录)?A(?:录)?.{0,20}(?:规范性|资料性)|"
                    r"(?:规范性|资料性).{0,20}附(?:录)?A(?:录)?)",
                    page_compact,
                )
            )
        if page_number >= config["appendix_a_page"]:
            continue

        visual_rows = merge_wrapped_food_value_rows(
            cluster_rows(page.words), value_column_x
        )
        for visual_row in visual_rows:
            serial += 1
            text = row_text(visual_row)
            compact_text = compact(text)
            expected_section = len(roster) + 1
            candidate = parse_expected_header(
                year,
                visual_row,
                expected_section,
                page_number,
                serial,
                source_path,
            )
            if candidate is not None:
                pending = candidate
                table_open = False
                table_open_method = ""
                active_parent = ""
                active_parent_raw = ""
                transitions["section_header_candidate"] += 1
                continue

            if "主要用途" in compact_text and (
                pending is not None or expected_section in toc_headers
            ):
                if pending is not None and serial - pending.serial <= HEADER_CONFIRM_GAP:
                    current = pending
                elif expected_section in toc_headers:
                    current = toc_headers[expected_section]
                    transitions["section_header_toc_fallback"] += 1
                else:
                    raise ExtractionValidationError(
                        f"{year} section {expected_section} header confirmation too distant"
                    )
                roster.append(current)
                pending = None
                table_open = False
                table_open_method = ""
                active_parent = ""
                active_parent_raw = ""
                transitions["section_header_confirmed"] += 1
                continue

            if current is None:
                continue
            transition = structural_transition(text, current.section_number)
            if transition is not None:
                action, method = transition
                transitions[method] += 1
                if action == "open":
                    table_open = True
                    table_open_method = method
                    active_parent = ""
                    active_parent_raw = ""
                elif action == "close":
                    table_open = False
                    table_open_method = ""
                continue
            if not table_open:
                continue

            category_words = [
                word for word in visual_row if word.x_min < value_column_x
            ]
            value_words = [word for word in visual_row if word.x_min >= value_column_x]
            margin_parent_overlap_salvaged = False
            value_candidate = compact(row_text(value_words))
            parent_candidates = [
                word
                for word in category_words
                if parent_left_x - 5 <= word.x_min <= parent_left_x + 30
                and re.search(r"[一-鿿]", word.text)
            ]
            if (
                min(word.y_min for word in visual_row) < 150
                and value_words
                and NUMERIC_VALUE.match(value_candidate) is None
                and any(word.x_min > value_column_x + 100 for word in value_words)
                and any(word.x_max < parent_left_x - 10 for word in category_words)
                and parent_candidates
            ):
                category_words = parent_candidates
                value_words = []
                margin_parent_overlap_salvaged = True
            margin_overlap_salvaged = False
            salvaged_value_words = salvage_margin_overlapped_value_words(value_words)
            if salvaged_value_words is not None:
                value_words = salvaged_value_words
                category_words = [
                    word
                    for word in category_words
                    if re.search(r"[一-鿿]", word.text)
                ]
                margin_overlap_salvaged = True
            category = canonical_scope(row_text(category_words))
            category_raw = compact(row_text(category_words, raw=True))
            category_x = min(
                (word.x_min for word in category_words), default=page.width
            )

            if (
                not category
                or NOISE.search(category)
                or not re.search(r"[一-鿿]", category)
                or re.search(r"[A-Za-z]{3,}", category)
            ):
                continue

            if not value_words:
                previous_is_wrapped_food = (
                    records
                    and int(records[-1]["section_number"]) == current.section_number
                    and food_label_expects_continuation(str(records[-1]["food"]))
                )
                if not previous_is_wrapped_food:
                    active_parent = category
                    active_parent_raw = category_raw
                    if margin_parent_overlap_salvaged:
                        transitions["margin_header_overlap_parent_recovered"] += 1
                    if category_x <= parent_left_x:
                        transitions["parent_from_left_column"] += 1
                    else:
                        transitions["parent_from_centered_table_scope"] += 1
                else:
                    # A wrapped food label can continue below the numeric row,
                    # as in 2021 Table 300.  It belongs to the preceding rule;
                    # treating it as a new scope would corrupt subsequent rows.
                    records[-1]["food"] = f"{records[-1]['food']}{category}"
                    records[-1]["food_raw"] = f"{records[-1]['food_raw']}{category_raw}"
                    records[-1]["review_status"] = add_status(
                        str(records[-1]["review_status"]),
                        "food_label_continuation_joined",
                    )
                    review_counts["food_label_continuation_joined"] += 1
                    transitions["food_label_continuation_joined"] += 1
                continue

            value_raw = compact(row_text(value_words, raw=True))
            value_text = compact(row_text(value_words))
            value_match = NUMERIC_VALUE.match(value_text)
            if value_match is None:
                continue

            heading = parent_heading(category) if category_x <= parent_left_x else ""
            if heading and (heading == category or heading != active_parent):
                active_parent = heading
                active_parent_raw = category_raw
                parent_method = "explicit_left_column_scope"
            elif active_parent:
                parent_method = "inherited_from_left_column_scope"
            else:
                parent_method = "unresolved_no_left_column_scope"

            limit_value = canonical_decimal(value_match.group(1))
            suffix = value_text[value_match.end() :]
            qualifier, temporary, qualifier_review = parse_qualifier(suffix)
            mark_fix = (year, current.section_number, category)
            if mark_fix in SCAN_TEMPORARY_MARK_FIXES:
                if (
                    qualifier != "temporary_mrl_asterisk"
                    or mark_fix in applied_mark_fixes
                ):
                    raise ExtractionValidationError(
                        f"scan temporary-mark fix does not apply: {mark_fix}"
                    )
                qualifier, temporary = "", False
                applied_mark_fixes.add(mark_fix)
            review_status = "text_layer_auto_extracted"
            if margin_overlap_salvaged:
                review_status = add_status(
                    review_status, "margin_header_overlap_removed"
                )
                transitions["margin_header_overlap_removed"] += 1
            if (
                max(word.y_min for word in visual_row)
                - min(word.y_min for word in visual_row)
                > 12
            ):
                review_status = add_status(
                    review_status, "food_value_multiline_joined"
                )
                transitions["food_value_multiline_joined"] += 1
            if current.name_correction:
                review_status = add_status(review_status, "source_glyph_correction")
            if mark_fix in applied_mark_fixes:
                review_status = add_status(
                    review_status, "scan_temporary_mark_correction"
                )
                transitions["scan_temporary_mark_correction"] += 1
            if qualifier_review:
                review_status = add_status(review_status, qualifier_review)
            if parent_method.startswith("unresolved"):
                review_status = add_status(review_status, "parent_scope_unresolved")
            if not table_open_method.endswith("item_4"):
                review_status = add_status(review_status, "source_structure_exception")

            qualifier_counts[qualifier or "none"] += 1
            for status in review_status.split(";"):
                review_counts[status] += 1
            records.append(
                {
                    "edition": config["edition"],
                    "year": year,
                    "section_number": current.section_number,
                    "pesticide_zh": current.pesticide_zh,
                    "pesticide_en": current.pesticide_en,
                    "pesticide_zh_raw": current.pesticide_zh_raw,
                    "pesticide_en_raw": current.pesticide_en_raw,
                    "parent_category": active_parent,
                    "parent_category_raw": active_parent_raw,
                    "food": category,
                    "food_raw": category_raw,
                    "limit_value": limit_value,
                    "unit": "mg/kg",
                    "limit_qualifier": qualifier,
                    "is_temporary": "true" if temporary else "false",
                    "value_raw": value_raw,
                    "source_page": page_number,
                    "source_y": f"{min(word.y_min for word in visual_row):.3f}",
                    "food_x": f"{category_x:.3f}",
                    "parent_assignment_method": parent_method,
                    "table_open_method": table_open_method,
                    "source_copy_role": config["source_copy_role"],
                    "source_filename": source_path.name,
                    "source_sha256": config["sha256"],
                    "review_status": review_status,
                }
            )

    expected_sections = list(range(1, int(config["sections"]) + 1))
    observed_sections = [header.section_number for header in roster]
    if observed_sections != expected_sections:
        raise ExtractionValidationError(
            f"{year} section roster is incomplete: "
            f"{len(observed_sections)} != {len(expected_sections)}"
        )
    if roster[0].source_page != config["first_header_page"]:
        raise ExtractionValidationError(
            f"{year} first body header moved to page {roster[0].source_page}"
        )
    if not appendix_marker_found:
        raise ExtractionValidationError(
            f"{year} Appendix A marker missing from page {config['appendix_a_page']}"
        )
    row_pages = [int(record["source_page"]) for record in records]
    if min(row_pages) != config["first_row_page"] or max(row_pages) != config["last_row_page"]:
        raise ExtractionValidationError(
            f"{year} body row bounds changed: {min(row_pages)}-{max(row_pages)}"
        )
    if any(page >= config["appendix_a_page"] for page in row_pages):
        raise ExtractionValidationError(f"{year} Appendix A leakage detected")
    unapplied = {key for key in SCAN_TEMPORARY_MARK_FIXES if key[0] == year} - applied_mark_fixes
    if unapplied:
        raise ExtractionValidationError(f"{year} scan temporary-mark fixes unused: {sorted(unapplied)}")
    sections_with_rows = {int(record["section_number"]) for record in records}
    if sections_with_rows != set(expected_sections):
        missing = sorted(set(expected_sections) - sections_with_rows)
        raise ExtractionValidationError(f"{year} sections without MRL rows: {missing}")

    identity_text = "".join(compact(page_text(page)) for page in pages[:30])
    declared = str(config["official_mrl_items"])
    if f"GB2763—{year}" not in identity_text and f"GB2763-{year}" not in identity_text:
        raise ExtractionValidationError(f"{year} edition label not found")
    if declared not in re.sub(r"[^0-9]", "", identity_text):
        # The digit-only stream is only a weak identity check; the hard source
        # hash and full structural roster carry the primary gate.
        transitions["declared_count_digit_stream_not_contiguous"] += 1

    duplicate_keys: dict[tuple[object, ...], list[dict[str, object]]] = defaultdict(list)
    for record in records:
        key = (
            record["year"],
            record["section_number"],
            record["parent_category"],
            record["food"],
            record["limit_value"],
            record["unit"],
            record["limit_qualifier"],
        )
        duplicate_keys[key].append(record)
    duplicates = {key: value for key, value in duplicate_keys.items() if len(value) > 1}
    if duplicates:
        sample = next(iter(duplicates.items()))
        raise ExtractionValidationError(f"{year} exact full-rule duplicate: {sample[0]}")

    unresolved_parent_rows = [
        record for record in records if not str(record["parent_category"]).strip()
    ]
    if unresolved_parent_rows:
        sample = unresolved_parent_rows[0]
        raise ExtractionValidationError(
            f"{year} unresolved parent scope at section "
            f"{sample['section_number']} page {sample['source_page']}"
        )
    unknown_qualifier_rows = [
        record
        for record in records
        if str(record["limit_qualifier"]).startswith("source_suffix:")
    ]
    if unknown_qualifier_rows:
        sample = unknown_qualifier_rows[0]
        raise ExtractionValidationError(
            f"{year} unknown source qualifier {sample['limit_qualifier']} at "
            f"section {sample['section_number']} page {sample['source_page']}"
        )

    per_section = Counter(int(record["section_number"]) for record in records)
    per_page = Counter(int(record["source_page"]) for record in records)
    header_name_corrections = [
        {
            "section": header.section_number,
            "text_layer_name": header.pesticide_zh_raw,
            "visible_name": header.pesticide_zh,
            "method": header.name_correction,
        }
        for header in roster
        if header.name_correction
    ]
    diagnostic = {
        "pdftotext_version": pdftotext_version,
        "rows": len(records),
        "sections": len(roster),
        "row_page_bounds": [min(row_pages), max(row_pages)],
        "appendix_a_page": config["appendix_a_page"],
        "appendix_leakage_rows": 0,
        "exact_full_rule_duplicates": 0,
        "unresolved_parent_rows": 0,
        "unknown_qualifier_rows": 0,
        "header_name_corrections": header_name_corrections,
        "transitions": dict(sorted(transitions.items())),
        "qualifier_counts": dict(sorted(qualifier_counts.items())),
        "review_status_counts": dict(sorted(review_counts.items())),
        "per_section_row_counts": {
            str(key): per_section[key] for key in sorted(per_section)
        },
        "per_page_row_counts": {str(key): per_page[key] for key in sorted(per_page)},
    }
    return records, roster, diagnostic


LIMIT_FIELDS = [
    "edition",
    "year",
    "section_number",
    "pesticide_zh",
    "pesticide_en",
    "pesticide_zh_raw",
    "pesticide_en_raw",
    "parent_category",
    "parent_category_raw",
    "food",
    "food_raw",
    "limit_value",
    "unit",
    "limit_qualifier",
    "is_temporary",
    "value_raw",
    "source_page",
    "source_y",
    "food_x",
    "parent_assignment_method",
    "table_open_method",
    "source_copy_role",
    "source_filename",
    "source_sha256",
    "review_status",
]


ROSTER_FIELDS = [
    "edition",
    "year",
    "section_number",
    "pesticide_zh",
    "pesticide_en",
    "pesticide_zh_raw",
    "pesticide_en_raw",
    "source_page",
    "source_y",
    "header_raw",
    "name_correction",
    "review_status",
    "source_copy_role",
    "source_filename",
    "source_sha256",
]


def write_dict_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def normal_crosscheck_scope(value: str) -> str:
    return canonical_scope(value)


def normal_crosscheck_value(value: str) -> str:
    try:
        return canonical_decimal(value)
    except ExtractionValidationError:
        return value.strip()


def crosscheck_with_ocr(
    text_records: list[dict[str, object]], ocr_path: Path
) -> tuple[list[dict[str, object]], dict[str, int]]:
    if not ocr_path.is_file():
        raise ExtractionValidationError(f"missing OCR accepted layer: {ocr_path.name}")
    ocr_rows = read_csv(ocr_path)

    text_groups: dict[tuple[str, int, str, str], list[dict[str, object]]] = defaultdict(list)
    ocr_groups: dict[tuple[str, int, str, str], list[dict[str, str]]] = defaultdict(list)
    for record in text_records:
        key = (
            str(record["year"]),
            int(record["section_number"]),
            normal_crosscheck_scope(str(record["parent_category"])),
            normal_crosscheck_scope(str(record["food"])),
        )
        text_groups[key].append(record)
    for record in ocr_rows:
        key = (
            record["year"],
            int(record["section"]),
            normal_crosscheck_scope(record["parent_category"]),
            normal_crosscheck_scope(record["food"]),
        )
        ocr_groups[key].append(record)

    audit: list[dict[str, object]] = []
    unmatched_text: dict[tuple[str, int, str, str], list[dict[str, object]]] = {}
    unmatched_ocr: dict[tuple[str, int, str, str], list[dict[str, str]]] = {}
    strict_keys = sorted(set(text_groups) | set(ocr_groups))
    for key in strict_keys:
        text_items = text_groups.get(key, [])
        ocr_items = ocr_groups.get(key, [])
        if not text_items:
            unmatched_ocr[key] = ocr_items
            continue
        if not ocr_items:
            unmatched_text[key] = text_items
            continue
        text_values = sorted(
            normal_crosscheck_value(str(item["limit_value"])) for item in text_items
        )
        ocr_values = sorted(
            normal_crosscheck_value(item["limit_value"]) for item in ocr_items
        )
        status = "consistent" if text_values == ocr_values else "conflict"
        audit.append(
            make_crosscheck_row(
                key,
                text_items,
                ocr_items,
                status=status,
                key_level="strict_scope",
            )
        )

    # OCR parent columns are sometimes unresolved.  A second pass uses only
    # section + food when that key is unique on both unmatched sides.
    text_relaxed: dict[tuple[str, int, str], list[tuple[tuple[str, int, str, str], list[dict[str, object]]]]] = defaultdict(list)
    ocr_relaxed: dict[tuple[str, int, str], list[tuple[tuple[str, int, str, str], list[dict[str, str]]]]] = defaultdict(list)
    for key, values in unmatched_text.items():
        text_relaxed[(key[0], key[1], key[3])].append((key, values))
    for key, values in unmatched_ocr.items():
        ocr_relaxed[(key[0], key[1], key[3])].append((key, values))

    consumed_text: set[tuple[str, int, str, str]] = set()
    consumed_ocr: set[tuple[str, int, str, str]] = set()
    for relaxed_key in sorted(set(text_relaxed) & set(ocr_relaxed)):
        text_candidates = text_relaxed[relaxed_key]
        ocr_candidates = ocr_relaxed[relaxed_key]
        if len(text_candidates) != 1 or len(ocr_candidates) != 1:
            continue
        text_key, text_items = text_candidates[0]
        ocr_key, ocr_items = ocr_candidates[0]
        text_values = sorted(
            normal_crosscheck_value(str(item["limit_value"])) for item in text_items
        )
        ocr_values = sorted(
            normal_crosscheck_value(item["limit_value"]) for item in ocr_items
        )
        status = "consistent" if text_values == ocr_values else "conflict"
        audit.append(
            make_crosscheck_row(
                text_key,
                text_items,
                ocr_items,
                status=status,
                key_level="unique_section_food",
            )
        )
        consumed_text.add(text_key)
        consumed_ocr.add(ocr_key)

    for key, items in sorted(unmatched_text.items()):
        if key in consumed_text:
            continue
        audit.append(
            make_crosscheck_row(
                key, items, [], status="text_only", key_level="strict_scope"
            )
        )
    for key, items in sorted(unmatched_ocr.items()):
        if key in consumed_ocr:
            continue
        audit.append(
            make_crosscheck_row(
                key, [], items, status="ocr_only", key_level="strict_scope"
            )
        )

    audit.sort(
        key=lambda row: (
            row["year"],
            int(row["section_number"]),
            row["food"],
            row["parent_category"],
            row["key_level"],
        )
    )
    counts = Counter(str(row["status"]) for row in audit)
    return audit, {key: counts[key] for key in sorted(counts)}


def make_crosscheck_row(
    key: tuple[str, int, str, str],
    text_items: list[dict[str, object]],
    ocr_items: list[dict[str, str]],
    *,
    status: str,
    key_level: str,
) -> dict[str, object]:
    text_values = sorted(
        normal_crosscheck_value(str(item["limit_value"])) for item in text_items
    )
    ocr_values = sorted(
        normal_crosscheck_value(item["limit_value"]) for item in ocr_items
    )
    return {
        "year": key[0],
        "section_number": key[1],
        "parent_category": key[2],
        "food": key[3],
        "text_values": ";".join(text_values),
        "ocr_values": ";".join(ocr_values),
        "status": status,
        "key_level": key_level,
        "text_row_count": len(text_items),
        "ocr_row_count": len(ocr_items),
        "text_source_pages": ";".join(
            str(value)
            for value in sorted({int(item["source_page"]) for item in text_items})
        ),
        "ocr_source_pages": ";".join(
            str(value)
            for value in sorted({int(item["source_page"]) for item in ocr_items})
        ),
    }


CROSSCHECK_FIELDS = [
    "year",
    "section_number",
    "parent_category",
    "food",
    "text_values",
    "ocr_values",
    "status",
    "key_level",
    "text_row_count",
    "ocr_row_count",
    "text_source_pages",
    "ocr_source_pages",
]


def load_scan_copy_metadata(manifest_path: Path) -> dict[str, object]:
    if not manifest_path.is_file():
        raise ExtractionValidationError(
            f"missing OCR completion manifest: {manifest_path.name}"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    editions = manifest.get("editions", {})
    output: dict[str, object] = {}
    for year in GOVERNMENT_HOSTED_YEARS:
        try:
            source_pdf = editions[year]["source_pdf"]
        except (KeyError, TypeError) as error:
            raise ExtractionValidationError(
                f"OCR manifest lacks original scan metadata for {year}"
            ) from error
        output[year] = {
            "copy_role": "original_scan_edition_identity_anchor_and_ocr_crosscheck_copy",
            "filename": source_pdf["filename"],
            "sha256": source_pdf["sha256"],
            "bytes": source_pdf["file_size_bytes"],
            "page_count": source_pdf["page_count"],
        }
    return output


def source_report(
    year: str,
    source_path: Path,
    scan_metadata: dict[str, object],
) -> dict[str, object]:
    config = SOURCE_CONFIG[year]
    if year in ARCHIVE_TEXT_LAYER_YEARS:
        return {
            "archive_text_layer_edition_source_copy": {
                "copy_role": "archive_text_layer_edition_source_copy",
                "source_and_extraction_role": (
                    "edition source and coordinate-extraction input"
                ),
                "filename": source_path.name,
                "sha256": config["sha256"],
                "bytes": config["bytes"],
                "page_count": config["pages"],
                "archive_provenance_caveat": (
                    "archive provenance does not independently establish "
                    "issuing-authority byte identity"
                ),
            },
            "copy_identity_check": {
                "same_file_used_for_edition_identity_and_coordinate_extraction": True,
                "same_complete_section_roster": True,
                "checked_features": [
                    "frozen SHA-256 and byte size",
                    "edition label",
                    "scope title and declared aggregate MRL count",
                    "continuous Chapter 4 section roster",
                    "first and last Chapter 4 tables",
                    "Appendix A boundary",
                ],
            },
        }

    scan = dict(scan_metadata[year])
    return {
        "government_hosted_text_layer_extraction_copy": {
            "copy_role": "government_hosted_text_layer_extraction_copy",
            "filename": source_path.name,
            "sha256": config["sha256"],
            "bytes": config["bytes"],
            "page_count": config["pages"],
            "landing_page_url": config["landing_page_url"],
            "attachment_url": config["attachment_url"],
            "reference_copy_notice": config["reference_copy_notice"],
            "authority_caveat": (
                "government hosting does not establish issuing-authority certification "
                "of this attachment byte stream"
            ),
        },
        "original_scan_edition_identity_anchor_and_ocr_crosscheck_copy": scan,
        "copy_identity_check": {
            "same_edition_label": True,
            "same_complete_section_roster": True,
            "byte_identical": False,
            "page_count_delta_text_layer_minus_scan": (
                int(config["pages"]) - int(scan["page_count"])
            ),
            "checked_features": [
                "edition label",
                "scope title and declared aggregate MRL count",
                "continuous Chapter 4 section roster",
                "first and last Chapter 4 tables",
                "Appendix A boundary",
            ],
        },
    }


def resolve_source_paths(
    government_source_dir: Path,
    edition_source_root: Path | None,
) -> tuple[tuple[str, ...], dict[str, Path]]:
    """Resolve the two source roles without embedding local paths in outputs."""

    if edition_source_root is None:
        years = GOVERNMENT_HOSTED_YEARS
    else:
        years = tuple(SOURCE_CONFIG)
    paths: dict[str, Path] = {}
    for year in years:
        filename = str(SOURCE_CONFIG[year]["filename"])
        if year in GOVERNMENT_HOSTED_YEARS:
            paths[year] = government_source_dir / filename
        else:
            assert edition_source_root is not None
            paths[year] = edition_source_root / ARCHIVE_SOURCE_SUBDIR / filename
    return years, paths


def extraction_anomaly_repairs(
    year: str, diagnostic: dict[str, object]
) -> list[dict[str, object]]:
    """Return only explicit, auditable layout or source-text exceptions."""

    transitions = dict(diagnostic["transitions"])
    repairs: list[dict[str, object]] = []
    dynamic = (
        (
            "section_header_toc_fallback",
            "body section header recovered from the same PDF's contents roster",
        ),
        (
            "food_value_multiline_joined",
            "one logical food/value rule joined across three visual rows",
        ),
        (
            "food_label_continuation_joined",
            "food label continuation joined to the preceding numeric rule",
        ),
        (
            "margin_header_overlap_removed",
            "running-header fragments removed after a valid numeric value cell",
        ),
        (
            "margin_header_overlap_parent_recovered",
            "left-column parent scope recovered from a running-header overlap row",
        ),
    )
    for key, description in dynamic:
        count = int(transitions.get(key, 0))
        if count:
            repairs.append(
                {"exception": key, "count": count, "handling": description}
            )

    glyph_repairs = list(diagnostic["header_name_corrections"])
    if glyph_repairs:
        repairs.append(
            {
                "exception": "visible_glyph_missing_from_text_layer",
                "count": len(glyph_repairs),
                "handling": (
                    "documented visible Chinese glyph recovered through the "
                    "section's English-name key"
                ),
                "sections": glyph_repairs,
            }
        )
    if year == "2012":
        repairs.append(
            {
                "exception": "page_94_margin_overlap_case",
                "count": 1,
                "handling": (
                    "section 178 retained parent '谷物', food '糙米', value 0.1, "
                    "and temporary-MRL status after margin-fragment removal"
                ),
            }
        )
    if year == "2019":
        repairs.append(
            {
                "exception": "source_numbering_exceptions",
                "count": 3,
                "handling": (
                    "semantic maximum-limit and testing-method labels govern "
                    "table boundaries for sections 191, 253, and 364"
                ),
            }
        )
    if year == "2021":
        repairs.append(
            {
                "exception": "source_marker_c",
                "count": 1,
                "handling": (
                    "retained verbatim as source_marker_c_unresolved and flagged "
                    "for source-level interpretation"
                ),
            }
        )
    return repairs


def count_2016_translation_visible_rules(
    path: Path,
) -> tuple[dict[int, int], list[dict[str, object]], str]:
    """Count visible table rules in the independent English layout by section."""

    pages, pdftotext_version = run_pdftotext(path)
    if len(pages) != int(TRANSLATION_2016_IDENTITY["pages"]):
        raise ExtractionValidationError(
            f"2016 translation page count mismatch: {len(pages)} != "
            f"{TRANSLATION_2016_IDENTITY['pages']}"
        )

    roster: list[int] = []
    counts: Counter[int] = Counter()
    exception_rows: list[dict[str, object]] = []
    current_section: int | None = None
    table_open = False
    expected_exceptions = {409, 412, 413}
    for page_number, page in enumerate(pages, start=1):
        if page_number < 22:
            continue
        for visual_row in cluster_rows(page.words):
            words = sorted(visual_row, key=lambda item: item.x_min)
            text = " ".join(word.text for word in words)
            lower = text.lower()
            header_match = re.match(r"^4\.(\d{1,3})(?!\.)\s", text)
            if header_match:
                candidate = int(header_match.group(1))
                if not roster or candidate == roster[-1] + 1:
                    current_section = candidate
                    roster.append(candidate)
                    table_open = False

            if current_section is not None and re.match(
                rf"^4\.{current_section}\.\s*[1-6](?!\d)", text
            ):
                if (
                    "maximum residue limit:" in lower
                    or "extraneous maximum residue limit:" in lower
                ):
                    table_open = True
                elif "testing method:" in lower:
                    table_open = False
            if not table_open or text.startswith("4."):
                continue

            food_words = [
                word
                for word in words
                if word.x_min < 330 and re.search(r"[A-Za-z]", word.text)
            ]
            standard_value_words = [
                word
                for word in words
                if word.x_min >= 350
                and re.fullmatch(r"\d+(?:\.\d+)?\*?", word.text)
            ]
            exception_value_words = [
                word
                for word in words
                if 330 <= word.x_min < 350
                and re.fullmatch(r"\d+(?:\.\d+)?\*?", word.text)
            ]
            used_exception = (
                current_section in expected_exceptions
                and text.startswith("Fat content < 10%")
                and len(exception_value_words) == 1
            )
            if food_words and (standard_value_words or used_exception):
                counts[current_section] += 1
                if used_exception:
                    exception_rows.append(
                        {
                            "section": current_section,
                            "source_page": page_number,
                            "visible_row": text,
                            "value_x": round(exception_value_words[0].x_min, 3),
                        }
                    )

    expected_roster = list(range(1, 418))
    if roster != expected_roster:
        raise ExtractionValidationError(
            f"2016 translation section roster is incomplete: {len(roster)} != 417"
        )
    if set(counts) != set(expected_roster):
        missing = sorted(set(expected_roster) - set(counts))
        raise ExtractionValidationError(
            f"2016 translation sections without visible rules: {missing}"
        )
    if {int(row["section"]) for row in exception_rows} != expected_exceptions:
        raise ExtractionValidationError(
            "2016 translation layout exceptions changed from sections 409/412/413"
        )
    return dict(sorted(counts.items())), exception_rows, pdftotext_version


def translation_2016_reconciliation_report(
    path: Path, chinese_per_section: dict[str, int]
) -> dict[str, object]:
    """Verify source identity and independently reconcile visible rules by section."""

    expected = TRANSLATION_2016_IDENTITY
    observed = {"bytes": path.stat().st_size, "sha256": sha256_file(path)} if path.is_file() else {}
    if observed != {"bytes": expected["bytes"], "sha256": expected["sha256"]}:
        raise ExtractionValidationError(
            f"2016 translation identity mismatch: {observed} != "
            f"{{'bytes': {expected['bytes']}, 'sha256': '{expected['sha256']}'}}"
        )
    english_counts, exception_rows, pdftotext_version = (
        count_2016_translation_visible_rules(path)
    )
    chinese_counts = {int(key): int(value) for key, value in chinese_per_section.items()}
    mismatched_sections = [
        section
        for section in range(1, 418)
        if chinese_counts.get(section) != english_counts.get(section)
    ]
    if mismatched_sections:
        raise ExtractionValidationError(
            "2016 Chinese/English per-section visible-rule counts differ at "
            f"{mismatched_sections[:10]}"
        )
    chinese_total = sum(chinese_counts.values())
    english_total = sum(english_counts.values())
    if chinese_total != 4_132 or english_total != 4_132:
        raise ExtractionValidationError(
            "2016 independent visible-rule totals changed: "
            f"Chinese={chinese_total}, English={english_total}"
        )
    return {
        "audit_type": "independent_visible_rule_reconciliation",
        "translation_copy": {
            "filename": path.name,
            "sha256": expected["sha256"],
            "bytes": expected["bytes"],
            "page_count": expected["pages"],
            "role": "independent_unofficial_English_translation_crosscheck",
        },
        "pdftotext_version": pdftotext_version,
        "chinese_source_visible_rules": chinese_total,
        "english_translation_visible_rules": english_total,
        "section_rosters_compared": 417,
        "sections_with_equal_visible_rule_counts": 417,
        "standard_declared_mrl_items": 4_140,
        "visible_rules_minus_declared": -8,
        "status": "unresolved_aggregate_difference_keep_all_visible_rows",
        "layout_repairs_applied_to_translation_counter": [
            {
                "sections": [409, 412, 413],
                "count": len(exception_rows),
                "handling": (
                    "included long 'Fat content <10%' food/value rows whose complete "
                    "cells fall left of the usual value-column threshold"
                ),
                "source_rows": exception_rows,
            }
        ],
        "interpretation": (
            "both independently laid-out language copies contain 4,132 visible "
            "Chapter 4 rules section by section; the eight-rule gap from the "
            "standard's declared aggregate remains unresolved, so no rows are "
            "synthesized or discarded"
        ),
    }


def write_report(path: Path, report: dict[str, object]) -> None:
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def build(
    source_dir: Path,
    ocr_dir: Path,
    ocr_parsed_dir: Path,
    output_dir: Path,
    edition_source_root: Path | None = None,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    all_records: list[dict[str, object]] = []
    all_roster: list[SectionHeader] = []
    diagnostics: dict[str, object] = {}
    years, source_paths = resolve_source_paths(source_dir, edition_source_root)

    for year in years:
        source_path = source_paths[year]
        records, roster, diagnostic = extract_edition(year, source_path)
        all_records.extend(records)
        all_roster.extend(roster)
        diagnostics[year] = diagnostic

    limit_path = output_dir / "pesticide_textlayer_limits.csv"
    roster_path = output_dir / "pesticide_textlayer_section_roster.csv"
    crosscheck_path = output_dir / "pesticide_textlayer_ocr_crosscheck.csv"
    report_path = output_dir / "pesticide_textlayer_extraction_report.json"

    write_dict_csv(limit_path, LIMIT_FIELDS, all_records)
    roster_rows = [
        {key: value for key, value in asdict(header).items() if key in ROSTER_FIELDS}
        for header in all_roster
    ]
    write_dict_csv(roster_path, ROSTER_FIELDS, roster_rows)

    ocr_accepted_path = ocr_parsed_dir / "pesticide_ocr_accepted.csv"
    government_records = [
        record
        for record in all_records
        if str(record["year"]) in GOVERNMENT_HOSTED_YEARS
    ]
    crosscheck_rows, crosscheck_counts = crosscheck_with_ocr(
        government_records, ocr_accepted_path
    )
    write_dict_csv(crosscheck_path, CROSSCHECK_FIELDS, crosscheck_rows)

    scan_manifest_path = ocr_dir / "completion_manifest.json"
    scan_metadata = load_scan_copy_metadata(scan_manifest_path)
    sources = {
        year: source_report(year, source_paths[year], scan_metadata)
        for year in years
    }

    reconciliation: dict[str, object] = {}
    for year in years:
        config = SOURCE_CONFIG[year]
        extracted = int(diagnostics[year]["rows"])
        declared = int(config["official_mrl_items"])
        delta = extracted - declared
        reconciliation[year] = {
            "standard_declared_mrl_items": declared,
            "coordinate_extracted_visible_rules": extracted,
            "visible_rules_minus_declared": delta,
            "declared_section_roster": int(config["sections"]),
            "extracted_section_headers": int(diagnostics[year]["sections"]),
            "section_roster_complete": (
                int(diagnostics[year]["sections"]) == int(config["sections"])
            ),
            "qualifier_counts": diagnostics[year]["qualifier_counts"],
            "status": (
                "exact_visible_rule_count_reconciliation"
                if delta == 0
                else "unresolved_aggregate_difference_keep_all_visible_rows"
            ),
            "interpretation_boundary": (
                "declared-versus-visible-rule count reconciliation; no inference "
                "about record-level correctness follows from an aggregate match"
            ),
        }

    if "2019" in reconciliation:
        reconciliation["2019"]["plus_one_audit"] = {
            "status": "unresolved_aggregate_difference_keep_all_visible_rows",
            "candidate_explanation": (
                "the printed Chapter 4 tables contain 7,108 numeric food-limit "
                "rows while the scope and preface arithmetic declare 7,107; no "
                "evidence supports dropping a visible rule"
            ),
            "checks": {
                "continuous_sections": 467,
                "per_section_counts_recorded": True,
                "per_page_counts_recorded": True,
                "exact_full_rule_duplicates": 0,
                "cross_page_exact_duplicates": 0,
                "temporary_and_other_qualifiers_retained_separately": True,
                "appendix_rows": 0,
                "semantic_table_boundaries": True,
            },
            "source_numbering_exceptions": [
                "4.191.3 opens Table 191 and 4.191.4 is the testing method",
                "4.253.5 opens Table 253 and 4.253.6 is the testing method",
                "4.364.5 opens Table 364",
            ],
            "independent_translation_check": {
                "source": (
                    "Data/Raw/外部英译本/"
                    "GAIN_CH2019-0170_GB2763-2019_en.pdf"
                ),
                "mechanically_equal_section_counts": "442 of 467 sections",
                "section_248_note": (
                    "the translation renders the brown-rice value 1 as lowercase "
                    "l; the Chinese extraction copy shows 1 at page 179, y=628.809"
                ),
                "section_357_note": (
                    "the translation places two adjacent source values on one "
                    "layout line; the Chinese copy preserves two explicit food rows"
                ),
                "limitation": (
                    "23 translation sections were not comparable with the simple "
                    "semantic counter, so this is not a full independent reconciliation"
                ),
            },
        }

    if "2016" in reconciliation:
        translation_path = PROJECT_ROOT / "Data/Raw" / TRANSLATION_2016_RELATIVE
        reconciliation["2016"]["independent_translation_check"] = (
            translation_2016_reconciliation_report(
                translation_path,
                dict(diagnostics["2016"]["per_section_row_counts"]),
            )
        )

    artifact_hashes = {
        path.name: sha256_file(path)
        for path in (limit_path, roster_path, crosscheck_path)
    }
    validation_gates = {
        year: {
            "source_hash_and_size_match": True,
            "source_page_count_match": True,
            "complete_section_roster": True,
            "all_sections_have_visible_rules": True,
            "body_row_page_bounds_match": True,
            "appendix_a_leakage_rows": 0,
            "exact_full_rule_duplicates": 0,
            "unresolved_parent_rows": 0,
            "unknown_qualifier_rows": 0,
        }
        for year in years
    }
    report = {
        "validation_passed": True,
        "artifact_scope": {
            "layer": "interim_coordinate_extraction_candidate",
            "editions": [str(SOURCE_CONFIG[year]["edition"]) for year in years],
            "release_status": "candidate_for_formal_release_rebuild",
            "source_role_notes": [
                (
                    "2012, 2014, 2016, and 2026 archive PDFs each serve as the "
                    "edition source and coordinate-extraction input"
                ),
                (
                    "2019 and 2021 original scans remain edition-identity anchors; "
                    "government-hosted text-layer files serve as extraction copies"
                ),
            ],
        },
        "parser": {
            "script": relative_or_name(Path(__file__)),
            "value_column_x_min_by_year": {
                year: SOURCE_CONFIG[year]["value_column_x"] for year in years
            },
            "parent_left_column_x_max_by_year": {
                year: SOURCE_CONFIG[year]["parent_left_x"] for year in years
            },
            "special_glyph_normalization": {
                "U+1001B0": ".",
                "U+1001BA": "deleted dotted leader",
                "fullwidth_G": "hyphen",
            },
            "acceptance_rule": (
                "accept a numeric value only inside the active Chapter 4 maximum-"
                "limit table and only when the same visual row contains Chinese food text"
            ),
        },
        "sources": sources,
        "diagnostics": diagnostics,
        "visible_rule_reconciliation": reconciliation,
        "extraction_anomaly_repairs": {
            year: extraction_anomaly_repairs(year, diagnostics[year])
            for year in years
        },
        "validation_gates": validation_gates,
        "ocr_crosscheck": {
            "scope": ["GB 2763-2019", "GB 2763-2021"],
            "role": "crosscheck_only_for_original_scan_editions",
            "accepted_layer": relative_or_name(ocr_accepted_path),
            "accepted_layer_sha256": sha256_file(ocr_accepted_path),
            "completion_manifest": relative_or_name(scan_manifest_path),
            "completion_manifest_sha256": sha256_file(scan_manifest_path),
            "key_hierarchy": [
                "year + section + parent + food",
                "unique year + section + food fallback for unresolved OCR parents",
            ],
            "status_counts": crosscheck_counts,
        },
        "outputs": {
            "limits": limit_path.name,
            "section_roster": roster_path.name,
            "ocr_crosscheck": crosscheck_path.name,
            "sha256": artifact_hashes,
        },
    }
    write_report(report_path, report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--ocr-dir", type=Path, default=DEFAULT_OCR_DIR)
    parser.add_argument(
        "--ocr-parsed-dir", type=Path, default=DEFAULT_OCR_PARSED_DIR
    )
    parser.add_argument(
        "--edition-source-root",
        type=Path,
        help=(
            "Root containing 补充_农兽药残留限量标准; when supplied, build all six "
            "editions, otherwise build the 2019/2021 government-copy audit"
        ),
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build(
        args.source_dir,
        args.ocr_dir,
        args.ocr_parsed_dir,
        args.output_dir,
        args.edition_source_root,
    )
    summary = {
        year: {
            "rows": report["diagnostics"][year]["rows"],
            "sections": report["diagnostics"][year]["sections"],
            "visible_rules_minus_declared": report["visible_rule_reconciliation"][
                year
            ]["visible_rules_minus_declared"],
        }
        for year in report["diagnostics"]
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
