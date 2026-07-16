#!/usr/bin/env python3
"""Parse frozen 2019/2021 GB 2763 OCR tables into auditable interim records."""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import os
from pathlib import Path
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any

from pesticide_ocr_integrity import sha256_file, verify_completion_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OCR_DIR = PROJECT_ROOT / "Data/Interim/pesticide_ocr"
DEFAULT_TEXT_DIR = PROJECT_ROOT / "Data/Interim/pesticide_text"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "Data/Interim/pesticide_ocr_parsed"
REQUIRED_YEARS = ("2019", "2021")
EXPECTED_IDENTITY_ADJUDICATIONS = 45
EXPECTED_SOURCE_IMAGE_ADJUDICATIONS = 11
CONFIG = {
    "2019": {"toc": (2, 12), "body": (19, 306), "last_section": 467},
    "2021": {"toc": (2, 14), "body": (21, 391), "last_section": 548},
}
CONF_MIN = 70.0
OCC_MAX = 0.25
NAME_OCC_MAX = 0.40
NAME_CONF_MIN = 50.0
MRL_MAX = 200.0
PROSE = re.compile(r"[;;::。]|GB|按照|规定|测定|方法|参照|符合|残留物|用途")
NUM = re.compile(r"^\d+(?:[.,]\d+)?$|^\d+[.,]$|^\d+$")
DECIMAL_SEP = re.compile(r"^[.,。．·，]$")


class ParserValidationError(ValueError):
    """Raised when a formal parser gate fails."""


def portable_report_path(path: Path, role: str) -> str:
    """Return a project-relative path or a non-identifying external label."""

    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        safe_role = re.sub(r"[^a-z0-9_-]", "_", role.lower()).strip("_")
        basename = resolved.name or "root"
        return f"external/{safe_role or 'input'}/{basename}"


@dataclass(frozen=True)
class Word:
    x: int
    width: int
    y: int
    height: int
    text: str
    confidence: float
    occlusion: float


@dataclass
class Evidence:
    year: str
    section: int
    source: str
    source_page: int
    raw_line: str
    english_raw: str = ""
    chinese_raw: str = ""
    proposed_name: str = ""
    proposed_english: str = ""
    method: str = ""
    score: float = 0.0
    margin: float = 0.0


def enkey(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def cnkey(value: str) -> str:
    value = value.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    return re.sub(r"[^0-9一-鿿]", "", value)


def load_words(path: Path) -> dict[int, list[Word]]:
    pages: dict[int, list[Word]] = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        for line_number, row in enumerate(reader, start=2):
            try:
                pages[int(row["page"])].append(
                    Word(
                        x=int(row["x"]),
                        width=int(row["w"]),
                        y=int(row["y"]),
                        height=int(row["h"]),
                        text=row["text"],
                        confidence=float(row["conf"]),
                        occlusion=float(row["occ"]),
                    )
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ParserValidationError(
                    f"invalid frozen OCR row in {path.name}:{line_number}"
                ) from error
    return dict(pages)


def rows_of(words: list[Word], tolerance: float = 12) -> list[list[Word]]:
    ordered = sorted(words, key=lambda word: word.y + word.height / 2)
    output: list[list[Word]] = []
    current: list[Word] = []
    previous: float | None = None
    for word in ordered:
        center = word.y + word.height / 2
        if previous is not None and center - previous > tolerance:
            output.append(sorted(current, key=lambda item: item.x))
            current = []
        current.append(word)
        previous = center
    if current:
        output.append(sorted(current, key=lambda item: item.x))
    return output


def leading_section(text: str, maximum: int) -> int | None:
    value = re.sub(r"^[，。、”\"“’‘_\-|]+\s*", "", text.strip())
    patterns = (
        r"^4\s*[.,]\s*(\d{1,3})(?=\s|[^\d])",
        r"^4\s+(\d{1,3})(?=\s|[^\d])",
        r"^4(\d{2,3})(?=\s|[^\d])",
    )
    for pattern in patterns:
        match = re.match(pattern, value)
        if match:
            section = int(match.group(1))
            return section if 1 <= section <= maximum else None
    return None


def labeled_signal(text: str, maximum: int) -> tuple[int, int] | None:
    compact = re.sub(r"\s+", "", text).replace(",", ".")
    compact = re.sub(r"^[，。、”\"“’‘|]+", "", compact)
    labels = (
        (1, "主要用途"),
        (2, "ADI"),
        (3, "残留物"),
        (4, "最大残留限"),
        (5, "检测方法"),
    )
    for item, label in labels:
        if label not in compact:
            continue
        prefix = compact[: compact.index(label)]
        match = re.match(r"^4([0-9.,]+)", prefix)
        if not match:
            continue
        digits = "".join(re.findall(r"\d", match.group(1)))
        if len(digits) > 1 and digits.endswith(str(item)):
            section = int(digits[:-1])
            if 1 <= section <= maximum:
                return section, item
    return None


def structural_signal(text: str, maximum: int) -> tuple[int, int] | None:
    """Read explicit 4.N.k markers while rejecting bare footer numbers."""

    value = re.sub(r"^[，。、”\"“’‘_\-|]+\s*", "", text.strip())
    patterns = (
        r"^4\s*[.,，．。/]\s*(\d{1,3})\s*[.,，．。/]\s*([1-5])(?=\s|[^\d])",
        r"^4\s+(\d{1,3})\s*[.,，．。/]\s*([1-5])(?=\s|[^\d])",
        r"^4\s+(\d{1,3})\s+([1-5])(?=\s|[^\d])",
    )
    for pattern in patterns:
        match = re.match(pattern, value)
        if match:
            section, item = int(match.group(1)), int(match.group(2))
            if 1 <= section <= maximum:
                return section, item
    return None


def table_number(text: str, maximum: int) -> int | None:
    compact = re.sub(r"\s+", "", text)
    match = re.match(r"^[，。、”\"“’‘|_\-]*表(\d{1,3})(?:\(|（|$)", compact)
    if not match:
        return None
    number = int(match.group(1))
    return number if 1 <= number <= maximum else None


def header_parts(text: str, maximum: int) -> tuple[int, str, str] | None:
    section = leading_section(text, maximum)
    if section is None or not re.search(r"[一-鿿]", text):
        return None
    compact = re.sub(r"\s+", "", text)
    labels = ("主要用途", "ADI", "残留物", "最大残留", "检测方法")
    if any(label in compact for label in labels):
        return None
    groups = re.findall(r"[（(\[{!]\s*([^）)\]}]*[A-Za-z][^）)\]}]*)[）)\]}]?", text)
    english = groups[-1].strip() if groups else ""
    if not english:
        return None
    english_start = text.rfind(english)
    opening = max(text.rfind(mark, 0, english_start + 1) for mark in "（([{!")
    prefix = text[:opening] if opening >= 0 else text
    prefix = re.sub(r"^[，。、”\"“’‘_\-|\s]*4\s*[.,]?\s*\d{1,3}\s*", "", prefix)
    chinese = "".join(re.findall(r"[0-9一-鿿,，.、\-（）()]+", prefix))
    return section, english, chinese


def value_fragments(line: list[Word], value_x: float, max_gap: int = 16) -> list[Word]:
    right = sorted(
        (word for word in line if word.x >= value_x), key=lambda word: word.x
    )
    output: list[Word] = []
    for index, word in enumerate(right):
        if NUM.match(word.text):
            output.append(word)
            continue
        if not DECIMAL_SEP.match(word.text) or index + 1 >= len(right):
            continue
        following = right[index + 1]
        gap = following.x - (word.x + word.width)
        if NUM.match(following.text) and gap <= max_gap:
            output.append(word)
    return output


def stitch(words: list[Word]) -> str | None:
    value = "".join(word.text for word in words)
    value = re.sub(r"[,，。．·]", ".", value)
    value = re.sub(r"\.+", ".", value).strip()
    if value.startswith("."):
        value = "0" + value
    value = value.rstrip(".")
    try:
        float(value)
    except ValueError:
        return None
    return value


class Resolver:
    """Resolve OCR identities from repository-owned text-edition rosters."""

    def __init__(self, roster_path: Path):
        en_candidates: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)
        cn_candidates: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)
        with roster_path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {"pesticide_zh", "pesticide_en"}
            if not required.issubset(reader.fieldnames or []):
                raise ParserValidationError(
                    f"missing resolver fields in {roster_path.name}: {sorted(required)}"
                )
            for row in reader:
                chinese = row["pesticide_zh"].strip()
                english = row["pesticide_en"].strip()
                english_key = enkey(english)
                chinese_key = cnkey(chinese)
                if len(english_key) >= 3:
                    en_candidates[english_key][(chinese, english)] += 1
                if len(chinese_key) >= 2:
                    cn_candidates[chinese_key][(chinese, english)] += 1
        if not en_candidates or not cn_candidates:
            raise ParserValidationError(
                "repository text roster produced an empty resolver"
            )
        self.en_to_identity = {
            key: counts.most_common(1)[0][0] for key, counts in en_candidates.items()
        }
        self.cn_to_identity = {
            key: counts.most_common(1)[0][0] for key, counts in cn_candidates.items()
        }
        self.en_keys = list(self.en_to_identity)
        self.cn_keys = list(self.cn_to_identity)

    @staticmethod
    def _best(key: str, options: list[str]) -> tuple[str, float, float]:
        scores = sorted(
            (
                (difflib.SequenceMatcher(None, key, option).ratio(), option)
                for option in options
            ),
            reverse=True,
        )
        if not scores:
            return "", 0.0, 0.0
        best_score, best = scores[0]
        second = scores[1][0] if len(scores) > 1 else 0.0
        return best, best_score, best_score - second

    def resolve(self, english: str, chinese: str) -> tuple[str, str, str, float, float]:
        english_key = enkey(english)
        if len(english_key) >= 3 and english_key in self.en_to_identity:
            name, canonical_english = self.en_to_identity[english_key]
            return name, canonical_english, "english_exact", 1.0, 1.0
        if len(english_key) >= 4:
            best, score, margin = self._best(english_key, self.en_keys)
            if score >= 0.78 and (margin >= 0.025 or score >= 0.90):
                name, canonical_english = self.en_to_identity[best]
                return name, canonical_english, "english_fuzzy", score, margin

        chinese_key = cnkey(chinese)
        if len(chinese_key) >= 2 and chinese_key in self.cn_to_identity:
            name, canonical_english = self.cn_to_identity[chinese_key]
            return name, canonical_english, "chinese_exact", 1.0, 1.0
        if len(chinese_key) >= 2:
            best, score, margin = self._best(chinese_key, self.cn_keys)
            if score >= 0.78 and (margin >= 0.05 or score >= 0.90):
                name, canonical_english = self.cn_to_identity[best]
                return name, canonical_english, "chinese_fuzzy", score, margin
        return "", "", "unresolved", 0.0, 0.0

    def english_for(self, chinese: str) -> str:
        identity = self.cn_to_identity.get(cnkey(chinese))
        return identity[1] if identity else ""


def load_identity_adjudications(path: Path) -> dict[tuple[str, int], dict[str, str]]:
    output: dict[tuple[str, int], dict[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"year", "section", "pesticide_zh", "source_page", "evidence"}
        if not required.issubset(reader.fieldnames or []):
            raise ParserValidationError(f"invalid identity adjudication schema: {path}")
        for line_number, row in enumerate(reader, start=2):
            try:
                year = row["year"]
                section = int(row["section"])
                source_page = int(row["source_page"])
            except (TypeError, ValueError) as error:
                raise ParserValidationError(
                    f"invalid identity adjudication at {path.name}:{line_number}"
                ) from error
            if year not in REQUIRED_YEARS:
                raise ParserValidationError(f"unexpected identity year {year}")
            if not 1 <= section <= int(CONFIG[year]["last_section"]):
                raise ParserValidationError(
                    f"identity section out of range: {year}/{section}"
                )
            key = (year, section)
            if key in output:
                raise ParserValidationError(f"duplicate identity adjudication: {key}")
            if source_page < 1 or not row["pesticide_zh"].strip():
                raise ParserValidationError(f"incomplete identity adjudication: {key}")
            output[key] = dict(row)
    return output


def header_evidence(
    year: str,
    pages: dict[int, list[Word]],
    page_range: tuple[int, int],
    source: str,
    resolver: Resolver,
) -> list[Evidence]:
    maximum = int(CONFIG[year]["last_section"])
    output: list[Evidence] = []
    for page in range(page_range[0], page_range[1] + 1):
        for row in rows_of(pages.get(page, [])):
            line = " ".join(word.text for word in row)
            parts = header_parts(line, maximum)
            if not parts:
                continue
            section, english, chinese = parts
            name, canonical_english, method, score, margin = resolver.resolve(
                english, chinese
            )
            output.append(
                Evidence(
                    year=year,
                    section=section,
                    source=source,
                    source_page=page,
                    raw_line=line,
                    english_raw=english,
                    chinese_raw=chinese,
                    proposed_name=name,
                    proposed_english=canonical_english,
                    method=method,
                    score=score,
                    margin=margin,
                )
            )
    return output


def residue_fallbacks(
    year: str, pages: dict[int, list[Word]], resolver: Resolver
) -> list[Evidence]:
    start, end = CONFIG[year]["body"]
    maximum = int(CONFIG[year]["last_section"])
    output: list[Evidence] = []
    for page in range(start, end + 1):
        for row in rows_of(pages.get(page, [])):
            line = " ".join(word.text for word in row)
            signal = labeled_signal(line, maximum)
            if not signal or signal[1] != 3:
                continue
            compact = re.sub(r"\s+", "", line)
            tail = compact.split("残留物", 1)[1].lstrip("：:,，")
            tail = re.split(r"[。；;，,、及和与]", tail, maxsplit=1)[0]
            identity = resolver.cn_to_identity.get(cnkey(tail))
            if identity:
                output.append(
                    Evidence(
                        year=year,
                        section=signal[0],
                        source="body_residue_exact",
                        source_page=page,
                        raw_line=line,
                        chinese_raw=tail,
                        proposed_name=identity[0],
                        proposed_english=identity[1],
                        method="residue_chinese_exact",
                        score=0.90,
                        margin=1.0,
                    )
                )
    return output


def build_section_roster(
    year: str,
    pages: dict[int, list[Word]],
    resolver: Resolver,
    identity_inputs: dict[tuple[str, int], dict[str, str]],
) -> tuple[dict[int, dict[str, Any]], list[Evidence]]:
    evidence: list[Evidence] = []
    evidence.extend(
        header_evidence(year, pages, CONFIG[year]["toc"], "toc_header", resolver)
    )
    evidence.extend(
        header_evidence(year, pages, CONFIG[year]["body"], "body_header", resolver)
    )
    evidence.extend(residue_fallbacks(year, pages, resolver))
    for (input_year, section), item in identity_inputs.items():
        if input_year != year:
            continue
        name = item["pesticide_zh"].strip()
        evidence.append(
            Evidence(
                year=year,
                section=section,
                source=item["evidence"],
                source_page=int(item["source_page"]),
                raw_line=f"source transcription from PDF page {item['source_page']}",
                chinese_raw=name,
                proposed_name=name,
                proposed_english=resolver.english_for(name),
                method="source_transcription",
                score=1.0,
                margin=1.0,
            )
        )

    grouped: dict[int, list[Evidence]] = defaultdict(list)
    for item in evidence:
        grouped[item.section].append(item)

    roster: dict[int, dict[str, Any]] = {}
    maximum = int(CONFIG[year]["last_section"])
    for section in range(1, maximum + 1):
        items = grouped.get(section, [])
        proposals: dict[str, list[Evidence]] = defaultdict(list)
        for item in items:
            if item.proposed_name:
                proposals[item.proposed_name].append(item)
        ranked = sorted(
            (
                (
                    max(candidate.score for candidate in group)
                    + 0.12 * (len({candidate.source for candidate in group}) - 1)
                    + (
                        0.25
                        if any(
                            candidate.method == "source_transcription"
                            for candidate in group
                        )
                        else 0
                    ),
                    name,
                    group,
                )
                for name, group in proposals.items()
            ),
            reverse=True,
        )
        chosen = ""
        chosen_english = ""
        status = "unresolved"
        confidence = 0.0
        methods = ""
        transcribed = [item for item in items if item.method == "source_transcription"]
        if transcribed:
            selected = transcribed[-1]
            chosen = selected.proposed_name
            chosen_english = selected.proposed_english
            status = "resolved"
            confidence = 1.0
            methods = "source_transcription"
        elif ranked:
            top_score, top_name, top_group = ranked[0]
            runner = ranked[1][0] if len(ranked) > 1 else 0.0
            strong = any(
                item.method
                in {"english_exact", "residue_chinese_exact", "chinese_exact"}
                or (item.method == "english_fuzzy" and item.score >= 0.78)
                for item in top_group
            )
            conflict = len(ranked) > 1 and runner >= 0.85 and top_score - runner < 0.20
            if strong and not conflict:
                chosen = top_name
                chosen_english = next(
                    (
                        item.proposed_english
                        for item in top_group
                        if item.proposed_english
                    ),
                    "",
                )
                status = "resolved"
                confidence = min(1.0, top_score)
                methods = "+".join(sorted({item.method for item in top_group}))
            elif conflict:
                status = "conflict"
        roster[section] = {
            "year": year,
            "section": section,
            "pesticide": chosen,
            "pesticide_en": chosen_english,
            "status": status,
            "confidence": round(confidence, 4),
            "methods": methods,
            "evidence_count": len(items),
            "proposal_count": len(proposals),
            "evidence_pages": ";".join(
                str(page) for page in sorted({item.source_page for item in items})
            ),
        }
    return roster, evidence


class FoodResolver:
    """Closed food vocabulary sourced from repository text-edition outputs."""

    def __init__(self, text_dir: Path):
        self.vocabulary: set[str] = set()
        self.parent_vocabulary: set[str] = set()
        self.parent_food_pairs: set[tuple[str, str]] = set()
        for filename in (
            "pesticide_limits_2012_2016.csv",
            "pesticide_2026_long.csv",
        ):
            path = text_dir / filename
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                if "food" not in (reader.fieldnames or []):
                    raise ParserValidationError(f"missing food field in {path}")
                for row in reader:
                    food = re.sub(r"\s+", "", row["food"])
                    if food:
                        self.vocabulary.add(food)
                        parent = re.sub(r"\s+", "", row.get("parent_category", ""))
                        if parent:
                            self.parent_vocabulary.add(parent)
                            self.parent_food_pairs.add((parent, food))
        if not self.vocabulary:
            raise ParserValidationError("repository food vocabulary is empty")
        if not self.parent_vocabulary:
            raise ParserValidationError("repository parent vocabulary is empty")
        self.long_vocabulary = sorted(
            food for food in self.vocabulary if len(food) >= 4
        )

    def resolve(self, food: str) -> tuple[str, str]:
        if food in self.vocabulary:
            return food, "exact"
        if len(food) >= 4:
            matches = difflib.get_close_matches(
                food, self.long_vocabulary, n=1, cutoff=0.80
            )
            if matches:
                return matches[0], "fuzzy"
        return "", ""


def resolve_parent(
    raw_parent: str, parent_vocabulary: set[str]
) -> tuple[str, str, float]:
    if raw_parent in parent_vocabulary:
        return raw_parent, "exact", 1.0
    if len(raw_parent) < 2:
        return "", "unresolved", 0.0
    scores = sorted(
        (
            (difflib.SequenceMatcher(None, raw_parent, candidate).ratio(), candidate)
            for candidate in parent_vocabulary
        ),
        reverse=True,
    )
    best_score, best = scores[0]
    second = scores[1][0]
    if best_score >= 0.50 and best_score - second >= 0.15:
        return best, "fuzzy", best_score
    return "", "unresolved", best_score


def add_review_status(current: str, status: str) -> str:
    statuses = [item for item in current.split(";") if item]
    if status not in statuses:
        statuses.append(status)
    return ";".join(statuses)


def split_category_columns(
    line_words: list[Word],
    parent_x: float,
    value_x: float,
    page_width: float,
) -> tuple[list[Word], list[Word]]:
    """Split a row into parent-column and child-food word clusters."""

    categories = sorted(
        (
            word
            for word in line_words
            if word.x + word.width < value_x and re.search(r"[一-鿿]", word.text)
        ),
        key=lambda word: word.x,
    )
    if not categories or categories[0].x >= parent_x:
        return [], categories
    gap_threshold = 0.05 * page_width
    split_at = len(categories)
    for index in range(1, len(categories)):
        previous = categories[index - 1]
        gap = categories[index].x - (previous.x + previous.width)
        if gap > gap_threshold:
            split_at = index
            break
    return categories[:split_at], categories[split_at:]


class RowAdjudications:
    """Apply source-image corrections and prove each one matched once."""

    KEY_FIELDS = (
        "year",
        "source_page",
        "section",
        "pesticide_zh",
        "raw_parent",
        "raw_food",
        "raw_value",
    )

    def __init__(self, path: Path, food_resolver: FoodResolver):
        self.path = path
        self.items: dict[tuple[str, int, int, str, str, str, str], dict[str, str]] = {}
        self.hits: Counter[str] = Counter()
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {
                "adjudication_id",
                *self.KEY_FIELDS,
                "corrected_food",
                "corrected_parent",
                "corrected_value",
                "source_conclusion",
            }
            if not required.issubset(reader.fieldnames or []):
                raise ParserValidationError(f"invalid row adjudication schema: {path}")
            seen_ids: set[str] = set()
            for line_number, row in enumerate(reader, start=2):
                try:
                    key = (
                        row["year"],
                        int(row["source_page"]),
                        int(row["section"]),
                        row["pesticide_zh"],
                        row["raw_parent"],
                        row["raw_food"],
                        row["raw_value"],
                    )
                    corrected_value = float(row["corrected_value"])
                except (TypeError, ValueError) as error:
                    raise ParserValidationError(
                        f"invalid row adjudication at {path.name}:{line_number}"
                    ) from error
                adjudication_id = row["adjudication_id"]
                if adjudication_id in seen_ids or key in self.items:
                    raise ParserValidationError(
                        f"duplicate row adjudication at {path.name}:{line_number}"
                    )
                if row["year"] not in REQUIRED_YEARS:
                    raise ParserValidationError(f"unexpected adjudication year: {key}")
                if row["corrected_food"] not in food_resolver.vocabulary:
                    raise ParserValidationError(
                        f"corrected food is outside closed vocabulary: {adjudication_id}"
                    )
                if row["corrected_parent"] not in food_resolver.parent_vocabulary:
                    raise ParserValidationError(
                        f"corrected parent is outside closed categories: {adjudication_id}"
                    )
                if not 0 < corrected_value <= MRL_MAX:
                    raise ParserValidationError(
                        f"corrected value outside MRL range: {adjudication_id}"
                    )
                seen_ids.add(adjudication_id)
                self.items[key] = dict(row)

    def apply(self, record: dict[str, Any]) -> dict[str, str] | None:
        key = (
            str(record["year"]),
            int(record["source_page"]),
            int(record["section"]),
            str(record["pesticide"]),
            str(record["parent_category_ocr_raw"]),
            str(record["food_ocr_raw"]),
            str(record["limit_value_ocr_raw"]),
        )
        item = self.items.get(key)
        if item:
            self.hits[item["adjudication_id"]] += 1
        return item

    def assert_complete(self) -> None:
        failures = {
            item["adjudication_id"]: self.hits[item["adjudication_id"]]
            for item in self.items.values()
            if self.hits[item["adjudication_id"]] != 1
        }
        if failures:
            raise ParserValidationError(
                "source-image adjudications must each match exactly once: "
                + json.dumps(failures, ensure_ascii=False, sort_keys=True)
            )

    def report(self) -> list[dict[str, Any]]:
        return [
            {
                "adjudication_id": item["adjudication_id"],
                "year": item["year"],
                "source_page": int(item["source_page"]),
                "section": int(item["section"]),
                "pesticide": item["pesticide_zh"],
                "raw_food": item["raw_food"],
                "raw_value": item["raw_value"],
                "raw_parent": item["raw_parent"],
                "corrected_parent": item["corrected_parent"],
                "corrected_food": item["corrected_food"],
                "corrected_value": item["corrected_value"],
                "hits": self.hits[item["adjudication_id"]],
            }
            for item in sorted(
                self.items.values(), key=lambda row: row["adjudication_id"]
            )
        ]


ROW_FIELDS = [
    "year",
    "section",
    "pesticide",
    "pesticide_en",
    "parent_category",
    "parent_category_ocr_raw",
    "parent_match",
    "parent_method",
    "parent_confidence",
    "parent_resolver_score",
    "food",
    "food_ocr_raw",
    "limit_value",
    "limit_value_ocr_raw",
    "unit",
    "identity_status",
    "identity_methods",
    "food_match",
    "source_page",
    "ocr_conf",
    "wm_occlusion",
    "name_conf",
    "name_occlusion",
    "review_status",
    "adjudication_id",
    "adjudication_action",
    "adjudication_note",
    "reject_reason",
]


def parse_rows(
    year: str,
    pages: dict[int, list[Word]],
    roster: dict[int, dict[str, Any]],
    food_resolver: FoodResolver,
    adjudications: RowAdjudications,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    start, end = CONFIG[year]["body"]
    maximum = int(CONFIG[year]["last_section"])
    accepted: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    all_candidates: list[dict[str, Any]] = []
    active_section: int | None = None
    table_open = False
    parent = ""
    parent_raw = ""
    parent_match = "unresolved"
    parent_method = "no_parent_detected"
    parent_confidence = 0.0
    parent_resolver_score = 0.0
    transitions: Counter[str] = Counter()

    for page in range(start, end + 1):
        words = pages.get(page, [])
        if not words:
            continue
        page_width = max(word.x + word.width for word in words)
        parent_x = 0.20 * page_width
        value_x = 0.55 * page_width
        for line_words in rows_of(words):
            line = " ".join(word.text for word in line_words)
            signal = structural_signal(line, maximum) or labeled_signal(line, maximum)
            header = header_parts(line, maximum)
            table = table_number(line, maximum)
            if header:
                active_section = header[0]
                table_open = False
                parent = ""
                parent_raw = ""
                parent_match = "unresolved"
                parent_method = "no_parent_detected"
                parent_confidence = 0.0
                parent_resolver_score = 0.0
                transitions["header"] += 1
                continue
            if signal:
                active_section = signal[0]
                parent = ""
                parent_raw = ""
                parent_match = "unresolved"
                parent_method = "no_parent_detected"
                parent_confidence = 0.0
                parent_resolver_score = 0.0
                table_open = signal[1] == 4
                transitions[f"subitem_{signal[1]}"] += 1
                continue
            if table is not None:
                transitions["table_title_skipped"] += 1
                continue
            if active_section is None or not table_open:
                continue

            left_categories, child_categories = split_category_columns(
                line_words, parent_x, value_x, page_width
            )
            values = value_fragments(line_words, value_x)
            if left_categories:
                candidate_parent_raw = re.sub(
                    r"\s+", "", "".join(word.text for word in left_categories)
                )
                resolved_parent, resolved_match, resolver_score = resolve_parent(
                    candidate_parent_raw, food_resolver.parent_vocabulary
                )
                parent_raw = candidate_parent_raw
                parent_confidence = min(word.confidence for word in left_categories)
                parent_resolver_score = resolver_score
                if resolved_parent:
                    parent = resolved_parent
                    parent_match = resolved_match
                    parent_method = f"layout_{resolved_match}"
                    transitions[f"parent_{resolved_match}"] += 1
                else:
                    parent = ""
                    parent_match = "unresolved"
                    parent_method = "layout_unresolved"
                    transitions["parent_unresolved"] += 1
                categories = child_categories or left_categories
            else:
                categories = child_categories
            food_raw = re.sub(r"\s+", "", "".join(word.text for word in categories))
            if not food_raw:
                continue
            if not values:
                continue
            if re.search(r"[A-Za-z]{4,}", food_raw) or len(food_raw) > 16:
                continue

            value_candidate = stitch(values)
            value_ocr_raw = "".join(
                word.text for word in values if NUM.match(word.text)
            )
            value_confidence = min(word.confidence for word in values)
            value_occlusion = max(word.occlusion for word in values)
            name_confidence = min(word.confidence for word in categories)
            name_occlusion = max(word.occlusion for word in categories)
            food, food_match = food_resolver.resolve(food_raw)
            identity = roster[active_section]
            record: dict[str, Any] = {
                "year": year,
                "section": active_section,
                "pesticide": identity["pesticide"],
                "pesticide_en": identity["pesticide_en"],
                "parent_category": parent,
                "parent_category_ocr_raw": parent_raw,
                "parent_match": parent_match,
                "parent_method": parent_method,
                "parent_confidence": round(parent_confidence),
                "parent_resolver_score": f"{parent_resolver_score:.3f}",
                "food": food or food_raw,
                "food_ocr_raw": food_raw,
                "limit_value": value_candidate or "",
                "limit_value_ocr_raw": value_ocr_raw,
                "unit": "mg/kg",
                "identity_status": identity["status"],
                "identity_methods": identity["methods"],
                "food_match": food_match,
                "source_page": page,
                "ocr_conf": round(value_confidence),
                "wm_occlusion": f"{value_occlusion:.3f}",
                "name_conf": round(name_confidence),
                "name_occlusion": f"{name_occlusion:.3f}",
                "review_status": "",
                "adjudication_id": "",
                "adjudication_action": "",
                "adjudication_note": "",
                "reject_reason": "",
            }
            adjudication = adjudications.apply(record)
            value_corrected = False
            food_corrected = False
            parent_corrected = False
            if adjudication:
                corrected_food = adjudication["corrected_food"]
                corrected_parent = adjudication["corrected_parent"]
                corrected_value = adjudication["corrected_value"]
                food_corrected = corrected_food != food_raw
                parent_corrected = corrected_parent != record["parent_category"]
                value_corrected = corrected_value != value_ocr_raw
                record.update(
                    {
                        "food": corrected_food,
                        "parent_category": corrected_parent,
                        "food_match": "exact",
                        "limit_value": corrected_value,
                        "review_status": "source_image_corrected",
                        "adjudication_id": adjudication["adjudication_id"],
                        "adjudication_action": "source_image_corrected",
                        "adjudication_note": adjudication["source_conclusion"],
                    }
                )
                if parent_corrected:
                    record["parent_match"] = "source_image_corrected"
                    record["parent_method"] = "source_image_corrected"

            corrected_value_text = str(record["limit_value"])
            try:
                corrected_number = float(corrected_value_text)
            except ValueError:
                corrected_number = 0.0

            reason = ""
            if identity["status"] != "resolved":
                reason = "section_identity_unresolved"
            elif PROSE.search(food_raw):
                reason = "prose_row"
            elif value_candidate is None:
                reason = "invalid_number"
            elif not value_corrected and re.fullmatch(r"0\d+", value_ocr_raw):
                reason = "leading_zero_integer"
            elif corrected_number <= 0 or corrected_number > MRL_MAX:
                reason = "value_out_of_range"
            elif not value_corrected and value_occlusion > OCC_MAX:
                reason = "value_watermark_occlusion"
            elif not value_corrected and value_confidence < CONF_MIN:
                reason = "value_low_confidence"
            elif not food_corrected and name_occlusion > NAME_OCC_MAX:
                reason = "food_watermark_occlusion"
            elif record["food_match"] == "fuzzy":
                reason = "food_fuzzy_requires_review"
            elif not record["food_match"]:
                reason = "food_unresolved"

            if reason:
                record["reject_reason"] = reason
                if not record["review_status"]:
                    record["review_status"] = "quarantined"
                quarantine.append(record)
            else:
                if not record["parent_category"]:
                    record["review_status"] = add_review_status(
                        record["review_status"], "review_parent_unresolved"
                    )
                elif record["parent_match"] == "fuzzy":
                    record["review_status"] = add_review_status(
                        record["review_status"], "review_parent_fuzzy"
                    )
                if (
                    record["parent_category"]
                    and (str(record["parent_category"]), str(record["food"]))
                    not in food_resolver.parent_food_pairs
                ):
                    record["review_status"] = add_review_status(
                        record["review_status"], "review_parent_food_unseen"
                    )
                if not record["review_status"]:
                    if name_confidence < 30:
                        record["review_status"] = "review_name_conf_lt30"
                    elif name_confidence < NAME_CONF_MIN:
                        record["review_status"] = "review_name_conf_30_49"
                    else:
                        record["review_status"] = "auto_accepted"
                accepted.append(record)
            all_candidates.append(record)

    metrics = {
        "transitions": dict(sorted(transitions.items())),
        "accepted": len(accepted),
        "quarantine": len(quarantine),
        "candidates": len(all_candidates),
        "accepted_sections": len({row["section"] for row in accepted}),
        "accepted_pesticides": len({row["pesticide"] for row in accepted}),
        "review_status": dict(
            sorted(Counter(row["review_status"] for row in accepted).items())
        ),
        "parent_review": {
            "missing": sum(not row["parent_category"] for row in accepted),
            "fuzzy": sum(row["parent_match"] == "fuzzy" for row in accepted),
            "source_image_corrected": sum(
                row["parent_match"] == "source_image_corrected" for row in accepted
            ),
            "parent_food_unseen": sum(
                bool(row["parent_category"])
                and (str(row["parent_category"]), str(row["food"]))
                not in food_resolver.parent_food_pairs
                for row in accepted
            ),
        },
        "reject_reasons": dict(
            sorted(Counter(row["reject_reason"] for row in quarantine).items())
        ),
    }
    return accepted, quarantine, metrics


KNOWN_PAGE_IDENTITIES = {
    ("2019", 20, 1): "2,4-滴和2,4-滴钠盐",
    ("2019", 20, 2): "2,4-滴丁酯",
    ("2021", 22, 2): "2,4-滴丁酯",
    ("2021", 22, 3): "2,4-滴二甲胺盐",
    ("2021", 23, 4): "2,4-滴和2,4-滴钠盐",
    ("2021", 357, 487): "乙螨唑",
    ("2021", 362, 497): "乙氧氟草醚",
    ("2021", 366, 504): "异丙隆",
    ("2021", 367, 506): "异丙威",
    ("2021", 367, 508): "异稻瘟净",
}


def known_page_checks(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for (year, page, section), expected in KNOWN_PAGE_IDENTITIES.items():
        seen = {
            str(row["pesticide"])
            for row in rows
            if row["year"] == year
            and row["source_page"] == page
            and row["section"] == section
        }
        output[f"{year}_p{page}_s{section}"] = {
            "expected": expected,
            "seen": sorted(seen),
            "pass": seen == {expected},
        }
    return output


def verify_required_manifest(ocr_dir: Path) -> dict[str, Any]:
    manifest_path = ocr_dir / "completion_manifest.json"
    manifest = verify_completion_manifest(manifest_path)
    observed = tuple(sorted(manifest["editions"]))
    if observed != REQUIRED_YEARS:
        raise ParserValidationError(
            f"completion manifest must contain exactly {REQUIRED_YEARS}, got {observed}"
        )
    for year in REQUIRED_YEARS:
        expected_filename = f"ocr_words_{year}.tsv"
        actual = manifest["editions"][year]["ocr_tsv"]["filename"]
        if actual != expected_filename:
            raise ParserValidationError(
                f"unexpected frozen OCR filename for {year}: {actual}"
            )
    return manifest


def validate_adjudication_input_counts(
    identity_inputs: dict[tuple[str, int], dict[str, str]],
    row_adjudications: RowAdjudications,
) -> None:
    if len(identity_inputs) != EXPECTED_IDENTITY_ADJUDICATIONS:
        raise ParserValidationError(
            "identity adjudication row-count gate failed: "
            f"{len(identity_inputs)}/{EXPECTED_IDENTITY_ADJUDICATIONS}"
        )
    if len(row_adjudications.items) != EXPECTED_SOURCE_IMAGE_ADJUDICATIONS:
        raise ParserValidationError(
            "source-image adjudication row-count gate failed: "
            f"{len(row_adjudications.items)}/{EXPECTED_SOURCE_IMAGE_ADJUDICATIONS}"
        )


def validate_results(
    rosters: dict[str, dict[int, dict[str, Any]]],
    accepted: list[dict[str, Any]],
    quarantine: list[dict[str, Any]],
    adjudications: RowAdjudications,
) -> dict[str, Any]:
    adjudications.assert_complete()
    unresolved: dict[str, list[int]] = {}
    for year in REQUIRED_YEARS:
        expected = int(CONFIG[year]["last_section"])
        roster = rosters[year]
        if len(roster) != expected or set(roster) != set(range(1, expected + 1)):
            raise ParserValidationError(f"incomplete section roster for {year}")
        unresolved[year] = [
            section for section, item in roster.items() if item["status"] != "resolved"
        ]
    if any(unresolved.values()):
        raise ParserValidationError(
            "unresolved section identities: "
            + json.dumps(unresolved, ensure_ascii=False, sort_keys=True)
        )

    expected_titles = {
        ("2019", 225): "邻苯基苯酚",
        ("2021", 269): "邻苯基苯酚",
        ("2021", 303): "氯酞酸甲酯",
        ("2021", 350): "氰戊菊酯和S-氰戊菊酯",
        ("2021", 528): "种菌唑",
    }
    for (year, section), expected_name in expected_titles.items():
        actual = rosters[year][section]["pesticide"]
        if actual != expected_name:
            raise ParserValidationError(
                f"section identity regression {year}/{section}: {actual!r}"
            )

    combined = accepted + quarantine
    page_checks = known_page_checks(combined)
    failed_pages = {
        key: value for key, value in page_checks.items() if not value["pass"]
    }
    if failed_pages:
        raise ParserValidationError(
            "known page identity regression: "
            + json.dumps(failed_pages, ensure_ascii=False, sort_keys=True)
        )

    fuzzy_accepted = [row for row in accepted if row["food_match"] != "exact"]
    if fuzzy_accepted:
        raise ParserValidationError(
            f"accepted rows must use exact food identities: {len(fuzzy_accepted)}"
        )

    body_violations = [
        row
        for row in combined
        if not (
            CONFIG[str(row["year"])]["body"][0]
            <= int(row["source_page"])
            <= CONFIG[str(row["year"])]["body"][1]
        )
    ]
    if body_violations:
        raise ParserValidationError(f"rows outside body bounds: {len(body_violations)}")

    duplicate_key_fields = (
        "year",
        "section",
        "pesticide",
        "parent_category",
        "food",
        "limit_value",
        "unit",
    )
    key_counts = Counter(
        tuple(str(row[field]) for field in duplicate_key_fields) for row in accepted
    )
    duplicates = {key: count for key, count in key_counts.items() if count > 1}
    if duplicates:
        sample = list(duplicates.items())[:5]
        raise ParserValidationError(f"duplicate accepted regulatory keys: {sample}")

    p390 = [
        row for row in accepted if row["year"] == "2021" and row["source_page"] == 390
    ]
    p390_keys = {
        tuple(str(row[field]) for field in duplicate_key_fields) for row in p390
    }
    if len(p390) != 7 or len(p390_keys) != 7:
        raise ParserValidationError(
            f"2021 page 390 must contribute seven unique accepted rows, got {len(p390)}"
        )
    after_p391 = [
        row
        for row in combined
        if row["year"] == "2021" and int(row["source_page"]) >= 392
    ]
    if after_p391:
        raise ParserValidationError(
            f"body-bound regression accepted candidates at p392+: {len(after_p391)}"
        )

    adjudicated_accepted = [row for row in accepted if row["adjudication_id"]]
    if len(adjudicated_accepted) != len(adjudications.items):
        raise ParserValidationError(
            "all source-image adjudications must reach accepted output: "
            f"{len(adjudicated_accepted)}/{len(adjudications.items)}"
        )

    tebuconazole_chili = [
        row
        for row in accepted
        if row["year"] == "2019"
        and row["section"] == 373
        and row["pesticide"] == "戊唑醇"
        and row["food"] in {"辣椒", "干辣椒"}
    ]
    tebuconazole_rules = {
        (
            str(row["parent_category"]),
            str(row["food"]),
            str(row["limit_value"]),
        )
        for row in tebuconazole_chili
    }
    expected_tebuconazole_rules = {
        ("蔬菜", "辣椒", "2"),
        ("调味料", "干辣椒", "10"),
    }
    if (
        len(tebuconazole_chili) != 2
        or tebuconazole_rules != expected_tebuconazole_rules
    ):
        raise ParserValidationError(
            "tebuconazole chili source-adjudication regression: "
            f"{sorted(tebuconazole_rules)}"
        )

    p55_target_foods = {
        "结球甘蓝",
        "花椰菜",
        "普通白菜",
        "番茄",
        "辣椒",
        "萝卜",
        "甘薯",
    }
    p55_s57 = [
        row
        for row in combined
        if row["year"] == "2019"
        and row["source_page"] == 55
        and row["section"] == 57
        and row["food"] in p55_target_foods
    ]
    if len(p55_s57) < 5 or any(row["parent_category"] != "蔬菜" for row in p55_s57):
        observed = sorted(
            (str(row["parent_category"]), str(row["food"])) for row in p55_s57
        )
        raise ParserValidationError(f"2019 p55 s57 parent regression: {observed}")

    return {
        "roster_expected": {
            year: int(CONFIG[year]["last_section"]) for year in REQUIRED_YEARS
        },
        "unresolved_sections": unresolved,
        "known_page_checks": page_checks,
        "fuzzy_accepted": 0,
        "accepted_duplicate_keys": 0,
        "accepted_2021_p390": len(p390),
        "accepted_2021_p390_unique_keys": len(p390_keys),
        "candidates_2021_p392_plus": 0,
        "source_image_adjudications_accepted": len(adjudicated_accepted),
        "tebuconazole_chili_rules": sorted(tebuconazole_rules),
        "p55_s57_vegetable_parent_rows": len(p55_s57),
    }


def write_csv_atomic(
    path: Path, rows: list[dict[str, Any]], fieldnames: list[str]
) -> None:
    partial = path.with_name(path.name + ".partial")
    with partial.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(partial, path)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    partial = path.with_name(path.name + ".partial")
    partial.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with partial.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(partial, path)


def build(ocr_dir: Path, text_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Build formal outputs after every hard gate passes."""

    ocr_dir = ocr_dir.resolve()
    text_dir = text_dir.resolve()
    output_dir = output_dir.resolve()

    # This gate intentionally runs before any resolver or parser input is read.
    manifest = verify_required_manifest(ocr_dir)
    identity_path = ocr_dir / "pesticide_section_identity_adjudications.csv"
    row_adjudication_path = ocr_dir / "pesticide_source_image_adjudications.csv"
    resolver_path = text_dir / "pesticide_text_section_roster.csv"
    resolver = Resolver(resolver_path)
    food_resolver = FoodResolver(text_dir)
    identity_inputs = load_identity_adjudications(identity_path)
    adjudications = RowAdjudications(row_adjudication_path, food_resolver)
    validate_adjudication_input_counts(identity_inputs, adjudications)

    rosters: dict[str, dict[int, dict[str, Any]]] = {}
    all_roster: list[dict[str, Any]] = []
    all_evidence: list[dict[str, Any]] = []
    all_accepted: list[dict[str, Any]] = []
    all_quarantine: list[dict[str, Any]] = []
    year_metrics: dict[str, Any] = {}
    source_files: dict[str, Any] = {}

    for year in REQUIRED_YEARS:
        tsv_path = ocr_dir / manifest["editions"][year]["ocr_tsv"]["filename"]
        pages = load_words(tsv_path)
        roster, evidence = build_section_roster(year, pages, resolver, identity_inputs)
        accepted, quarantine, extraction_metrics = parse_rows(
            year, pages, roster, food_resolver, adjudications
        )
        rosters[year] = roster
        all_roster.extend(roster.values())
        all_evidence.extend(asdict(item) for item in evidence)
        all_accepted.extend(accepted)
        all_quarantine.extend(quarantine)
        year_metrics[year] = {
            "roster": {
                "total": len(roster),
                "statuses": dict(
                    sorted(Counter(item["status"] for item in roster.values()).items())
                ),
            },
            "extraction": extraction_metrics,
        }
        source_files[year] = {
            "filename": tsv_path.name,
            "sha256": sha256_file(tsv_path),
            "page_count": len(pages),
            "word_count": manifest["editions"][year]["ocr_tsv"]["word_count"],
        }

    validation = validate_results(rosters, all_accepted, all_quarantine, adjudications)
    report: dict[str, Any] = {
        "validation_passed": True,
        "artifact_scope": {
            "layer": "conservative_ocr_candidate_layer",
            "complete_edition_representation": False,
            "intended_use": (
                "cross-validation, disputed-row quarantine, and reproducible OCR evidence"
            ),
            "release_warning": (
                "accepted rows remain conservative OCR candidates and must not be described "
                "as complete 2019 or 2021 edition tables"
            ),
        },
        "manifest": {
            "filename": "completion_manifest.json",
            "sha256": sha256_file(ocr_dir / "completion_manifest.json"),
            "verified_years": list(REQUIRED_YEARS),
        },
        "source_files": source_files,
        "resolver": {
            "source": portable_report_path(resolver_path, "identity_resolver"),
            "english_keys": len(resolver.en_keys),
            "chinese_keys": len(resolver.cn_keys),
            "external_english_roster_used": False,
        },
        "food_vocabulary": {
            "source_directory": portable_report_path(text_dir, "text_inputs"),
            "terms": len(food_resolver.vocabulary),
        },
        "parent_resolution": {
            "method": "layout_column_cluster",
            "vocabulary_source": portable_report_path(text_dir, "parent_vocabulary"),
            "vocabulary_terms": len(food_resolver.parent_vocabulary),
            "parent_column_start_rule": "first Chinese token x < 0.20 * page_width",
            "cluster_split_rule": "horizontal gap > 0.05 * page_width",
            "unresolved_policy": "clear inherited parent and add explicit review status",
        },
        "identity_adjudications": {
            "source": portable_report_path(identity_path, "identity_adjudications"),
            "sha256": sha256_file(identity_path),
            "rows": len(identity_inputs),
            "evidence_type": "manual_source_transcription",
        },
        "source_image_adjudications": {
            "source": portable_report_path(
                row_adjudication_path, "source_image_adjudications"
            ),
            "sha256": sha256_file(row_adjudication_path),
            "rows": adjudications.report(),
        },
        "years": year_metrics,
        "totals": {
            "accepted": len(all_accepted),
            "quarantine": len(all_quarantine),
            "candidates": len(all_accepted) + len(all_quarantine),
            "section_roster": len(all_roster),
            "roster_evidence": len(all_evidence),
        },
        "validation": validation,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    roster_fields = list(all_roster[0])
    evidence_fields = list(all_evidence[0])
    write_csv_atomic(
        output_dir / "pesticide_ocr_accepted.csv", all_accepted, ROW_FIELDS
    )
    write_csv_atomic(
        output_dir / "pesticide_ocr_quarantine.csv", all_quarantine, ROW_FIELDS
    )
    write_csv_atomic(
        output_dir / "pesticide_ocr_section_roster.csv", all_roster, roster_fields
    )
    write_csv_atomic(
        output_dir / "pesticide_ocr_roster_evidence.csv",
        all_evidence,
        evidence_fields,
    )
    write_json_atomic(output_dir / "pesticide_ocr_report.json", report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocr-dir", type=Path, default=DEFAULT_OCR_DIR)
    parser.add_argument("--text-dir", type=Path, default=DEFAULT_TEXT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build(args.ocr_dir, args.text_dir, args.output_dir)
    print(json.dumps(report["totals"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
