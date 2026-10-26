#!/usr/bin/env python3
"""限量标准 Data Paper · 发布包构建(04_Release)

分层原则:03_Results 是加工产物(忠实于抽取结果,不动);04_Release 是发布版(清理 + 英文 schema)。

发布层做三件加工层不做的事:
  1. 去 exact duplicates(解析器跨页/重复抽取produced的完全相同行——纯 bug,发布不该带)
  2. 每行给 record_id(主键唯一,可被引用);业务键(year+物质+食品)可能对应多行,
     用 conflict 列如实标出(主要来自 OCR 段把同一行读出两个值,以及同分类号下的不同限定条件)
  3. 英文字段名 + analyte 双语列 + 可判定的质量比单位归一列

产物: Data/Final/china_food_limit_panel_v1/
"""
import argparse
import csv
import hashlib
import importlib.util
import json
import os
import sys
from collections import Counter, defaultdict, deque

from release_dependency_utils import (
    verify_pollutant_rebuild_report,
    verify_release_dependencies,
)
from release_panel_utils import (
    ADDITIVE_YEARS,
    PESTICIDE_YEARS,
    build_additive_panel,
    build_pesticide_panel_v2,
    VETDRUG_SUMMARY_YEARS,
    _normalise_vetdrug_english,
    build_vetdrug_summary_panel,
    food_entity_id,
    link_source_records,
    panel_columns,
    pesticide_entity_id,
)
from source_acquisition_metadata import source_locators_by_id
from source_manifest_utils import source_documents_by_id, source_ids_by_edition

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REL = os.path.join(PROJECT_ROOT, "Data/Final/china_food_limit_panel_v1")
ADD_INTERIM = os.path.join(PROJECT_ROOT, "Data/Interim/additive_extraction")
POLLUTANT_INTERIM = os.path.join(PROJECT_ROOT, "Data/Interim/pollutant_rebuild")
PESTICIDE_INTERIM = os.path.join(
    PROJECT_ROOT, "Data/Interim/pesticide_textlayer_scans"
)
MYCOTOXIN_INTERIM = os.path.join(PROJECT_ROOT, "Data/Interim/mycotoxin_rebuild")
VETDRUG_INTERIM = os.path.join(PROJECT_ROOT, "Data/Interim/vetdrug_rebuild")
DEPENDENCY_INTERIM = os.path.join(PROJECT_ROOT, "Data/Interim/release_dependencies")
AUDIT_INTERIM = os.path.join(PROJECT_ROOT, "Data/Interim")
PESTICIDE_AUDIT_ROUNDS = ("pesticide_audit", "pesticide_audit_round2")
BLIND_REENTRY_REPORT = "manual_reentry/reconciliation/04_attested/blind_reentry_report.json"
TIMELINE = os.path.join(PROJECT_ROOT, "Data/Interim/standard_timeline")
DATE_DIR = TIMELINE

# 污染物中英对照(GB2762 指标,含形态细分)
ANALYTE_EN = {
    "铅": "Lead", "镉": "Cadmium", "铬": "Chromium", "锡": "Tin", "镍": "Nickel",
    "总汞": "Total mercury", "甲基汞": "Methylmercury",
    "总砷": "Total arsenic", "无机砷": "Inorganic arsenic",
    "亚硝酸盐": "Nitrite", "硝酸盐": "Nitrate",
    "苯并[a]芘": "Benzo[a]pyrene", "多氯联苯": "Polychlorinated biphenyls",
    "N-二甲基亚硝胺": "N-nitrosodimethylamine",
    "3-氯-1,2-丙二醇": "3-chloro-1,2-propanediol", "3-丙二醇": "3-chloro-1,2-propanediol",
    # GB2761 真菌毒素
    "黄曲霉毒素B1": "Aflatoxin B1", "黄曲霉毒素M1": "Aflatoxin M1",
    "脱氧雪腐镰刀菌烯醇": "Deoxynivalenol", "展青霉素": "Patulin",
    "赭曲霉毒素A": "Ochratoxin A", "玉米赤霉烯酮": "Zearalenone",
}
POLLUTANT_YEARS = ("2012", "2017", "2022", "2025")
MYCOTOXIN_YEARS = ("2005", "2011", "2017")
VETDRUG_MEMBER_YEARS = ("2002", "2019", "2022")
MASS_PER_MASS_FACTOR = {"mg/kg": 1.0, "μg/kg": 0.001, "µg/kg": 0.001, "g/kg": 1000.0}
LIQUID_UNITS = {"mg/L", "μg/L", "µg/L", "g/L"}

TREND_CODES = {
    "稳定": "stable",
    "收紧(变严)": "tightened",
    "放松(变松)": "relaxed",
    "波动": "fluctuation",
    "单版本": "single_version",
    "含GMP(不判数值)": "incomparable_gmp",
    "不可比(类别消失,见成员级面板)": "incomparable_category_disappeared",
    "不可比(单位维度或值缺失)": "incomparable_unit_dimension_or_value",
    "不可比(基准、单位或值缺失)": "incomparable_basis_unit_or_value",
    "不可比(范围文字不同)": "incomparable_scope_text",
    "不可比(同版多规则)": "incomparable_multiple_rules",
    "不可比(跨过缺失版本)": "incomparable_edition_gap",
    "仅2005版(无跨版对应:该类别被删除或新增)": "single_version_unmatched",
    "仅2011版(无跨版对应:该类别被删除或新增)": "single_version_unmatched",
    "仅2017版(无跨版对应:该类别被删除或新增)": "single_version_unmatched",
    "仅2002(2019删/未对上)": "single_2002_unmatched",
    "仅2019(新增/2002无)": "single_2019_unmatched",
    "多动物待核": "unresolved_multiple_animals",
}

COVERAGE_CODES = {
    "全齐": "all_editions",
    "新增于2017": "introduced_2017",
    "新增于2022": "introduced_2022",
    "新增于2025": "introduced_2025",
    "止于2012(后删/改名)": "ended_2012_or_renamed",
    "止于2017(后删/改名)": "ended_2017_or_renamed",
    "中段缺(待核)": "internal_gap_review",
}

def read(fn, base=None):
    if base is None:
        raise ValueError("input directory has not been configured")
    with open(os.path.join(base, fn), encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write(fn, rows, cols):
    os.makedirs(REL, exist_ok=True)
    with open(os.path.join(REL, fn), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=cols, extrasaction="ignore", lineterminator="\n"
        )
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def dedup_and_id(rows, bizkey, prefix):
    """Assign content-stable IDs and fail on exact duplicate release rows."""

    signatures = {}
    identifiers = set()
    business_counts = Counter(
        tuple(row.get(column, "") for column in bizkey) for row in rows
    )
    for position, row in enumerate(rows, start=1):
        encoded = json.dumps(
            row, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        signature = hashlib.sha256(encoded).hexdigest()
        if signature in signatures:
            raise ValueError(
                "duplicate release row at input rows "
                f"{signatures[signature]} and {position}"
            )
        signatures[signature] = position
        record_id = f"{prefix}{signature[:16].upper()}"
        if record_id in identifiers:
            raise RuntimeError(f"record-id digest collision: {record_id}")
        identifiers.add(record_id)
        row["record_id"] = record_id
        key = tuple(row.get(column, "") for column in bizkey)
        row["conflict"] = "1" if business_counts[key] > 1 else "0"
    return rows, 0, sum(row["conflict"] == "1" for row in rows)


def preserve_rules_and_id(rows, bizkey, signature_columns, prefix):
    """Assign stable IDs while rejecting duplicated semantic rules.

    Multiple rows sharing a business key can encode distinct values or scope
    qualifiers and are therefore retained.  A repeated semantic signature is
    an upstream extraction defect; failing here keeps it visible.
    """
    seen = {}
    business_counts = Counter(
        tuple(row.get(column, "") for column in bizkey) for row in rows
    )
    identifiers = set()
    for position, row in enumerate(rows, start=1):
        signature = tuple(row.get(column, "") for column in signature_columns)
        if signature in seen:
            raise ValueError(
                "duplicate semantic rule at input rows "
                f"{seen[signature]} and {position}: {signature}"
            )
        seen[signature] = position
        encoded = json.dumps(
            signature, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        record_id = f"{prefix}{hashlib.sha256(encoded).hexdigest()[:16].upper()}"
        if record_id in identifiers:
            raise RuntimeError(f"record-id digest collision: {record_id}")
        identifiers.add(record_id)
        row["record_id"] = record_id
        key = tuple(row.get(column, "") for column in bizkey)
        row["conflict"] = "1" if business_counts[key] > 1 else "0"
    return rows, 0, sum(row["conflict"] == "1" for row in rows)


def normalize_mass_per_mass(value, unit):
    """Return an mg/kg value only for dimensionally compatible units."""
    unit = (unit or "").strip()
    if not unit:
        raise ValueError("cannot normalise a limit with a missing unit")
    if unit in LIQUID_UNITS:
        return "", "density_required"
    if unit not in MASS_PER_MASS_FACTOR:
        raise ValueError(f"unsupported limit unit: {unit}")
    try:
        normalised = round(float(value) * MASS_PER_MASS_FACTOR[unit], 6)
    except (ValueError, TypeError) as error:
        raise ValueError(f"non-numeric limit value: {value}") from error
    status = "already_mg_per_kg" if unit == "mg/kg" else "converted_mass_per_mass"
    return normalised, status


def portable_source_label(value):
    """Reduce source paths to a package-safe lineage label."""

    return os.path.basename((value or "").replace("\\", "/"))


def coded(value, mapping, field):
    """Translate a derived display label into a stable release code."""

    if value not in mapping:
        raise ValueError(f"unknown {field} label: {value}")
    return mapping[value]


def lookup_entity_key(prefix, identity):
    """Return a stable ASCII key for a bilingual lookup entity."""
    canonical = str(identity or "").strip().casefold()
    if not canonical:
        raise ValueError(f"empty lookup identity for {prefix}")
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def build_analyte_lookup_entities(pollutant_rows, mycotoxin_rows):
    """Build analyte lookup rows only from bilingual pairs in released tables."""
    entities = {}
    inputs = (
        (pollutant_rows, "analyte_zh", "analyte_en"),
        (mycotoxin_rows, "toxin_zh", "toxin_en"),
    )
    for rows, chinese_column, english_column in inputs:
        for row in rows:
            chinese = str(row.get(chinese_column, "") or "").strip()
            english = str(row.get(english_column, "") or "").strip()
            if not chinese or not english:
                continue
            entity_key = lookup_entity_key("ANL", english)
            candidate = {
                "entity_key": entity_key,
                "entity_type": "contaminant_or_mycotoxin",
                "name_zh": chinese,
                "name_en": english,
                "source_standard": "GB 2762 / GB 2761",
            }
            existing = entities.get(entity_key)
            if existing is not None and (
                existing["name_zh"] != candidate["name_zh"]
                or existing["name_en"].casefold() != candidate["name_en"].casefold()
            ):
                raise ValueError(
                    "analyte bilingual identity collision for "
                    f"{entity_key}: "
                    f"{existing['name_zh']} / {existing['name_en']} versus "
                    f"{candidate['name_zh']} / {candidate['name_en']}"
                )
            entities[entity_key] = candidate
    return [entities[key] for key in sorted(entities)]


def _number_sort_key(value):
    text = str(value or "").strip()
    try:
        return 0, float(text)
    except ValueError:
        return 1, text


def prepare_pesticide_limits(extracted_rows, source_ids_by_year):
    """Convert six-edition coordinate rows into the released rule schema."""
    expected_years = set(PESTICIDE_YEARS)
    if set(source_ids_by_year) != expected_years:
        raise ValueError(
            "pesticide source-id years differ from release years: "
            f"expected={sorted(expected_years)}, got={sorted(source_ids_by_year)}"
        )

    rows = []
    for extracted in extracted_rows:
        year = str(extracted.get("year", "")).strip()
        if year not in expected_years:
            raise ValueError(f"unsupported pesticide extraction year: {year}")
        pesticide_zh = extracted.get("pesticide_zh", "").strip()
        pesticide_en = extracted.get("pesticide_en", "").strip()
        food_zh = extracted.get("food", "").strip()
        source_ids = source_ids_by_year[year]
        row = {
            "standard": "GB 2763",
            "version_year": year,
            "section_number": extracted.get("section_number", ""),
            "pesticide_key": pesticide_entity_id(pesticide_en, pesticide_zh),
            "pesticide_zh": pesticide_zh,
            "pesticide_en": pesticide_en,
            "pesticide_zh_raw": extracted.get("pesticide_zh_raw", ""),
            "pesticide_en_raw": extracted.get("pesticide_en_raw", ""),
            "parent_category_zh": extracted.get("parent_category", ""),
            "parent_category_raw": extracted.get("parent_category_raw", ""),
            "food_key": food_entity_id(food_zh),
            "food_zh": food_zh,
            "food_raw": extracted.get("food_raw", ""),
            "limit_value": extracted.get("limit_value", ""),
            "unit": extracted.get("unit", ""),
            "limit_qualifier": extracted.get("limit_qualifier", ""),
            "is_temporary": extracted.get("is_temporary", ""),
            "value_raw": extracted.get("value_raw", ""),
            "source_page": extracted.get("source_page", ""),
            "source_y": extracted.get("source_y", ""),
            "food_x": extracted.get("food_x", ""),
            "parent_assignment_method": extracted.get(
                "parent_assignment_method", ""
            ),
            "table_open_method": extracted.get("table_open_method", ""),
            "review_status": extracted.get("review_status", ""),
            "edition_source_id": source_ids["edition_source_id"],
            "extraction_source_id": source_ids["extraction_source_id"],
            "source_copy_role": extracted.get("source_copy_role", ""),
        }
        if not row["limit_value"] or not row["unit"]:
            raise ValueError(
                "pesticide release row lacks value or unit: "
                f"year={year}, section={row['section_number']}"
            )
        rows.append(row)

    rows.sort(
        key=lambda row: (
            int(row["version_year"]),
            _number_sort_key(row["section_number"]),
            _number_sort_key(row["source_page"]),
            _number_sort_key(row["source_y"]),
            row["food_raw"],
            row["limit_value"],
        )
    )
    signature_columns = (
        "version_year",
        "pesticide_zh_raw",
        "pesticide_en_raw",
        "parent_category_raw",
        "food_raw",
        "limit_value",
        "unit",
        "limit_qualifier",
        "is_temporary",
    )
    rows, _, conflicts = preserve_rules_and_id(
        rows,
        ["version_year", "pesticide_key", "food_key"],
        signature_columns,
        "PES",
    )
    return rows, conflicts


def pesticide_panel_output_columns():
    columns = [
        "record_id",
        "standard",
        "pesticide_key",
        "food_key",
        "pesticide_zh",
        "pesticide_names_zh",
        "food_zh",
        "food_names_zh",
    ]
    for year in PESTICIDE_YEARS:
        columns.extend(
            [
                f"v{year}",
                f"status_{year}",
                f"values_{year}",
                f"units_{year}",
                f"source_record_ids_{year}",
                f"source_ids_{year}",
                f"edition_source_ids_{year}",
                f"extraction_source_ids_{year}",
                f"rules_{year}",
                f"candidate_count_{year}",
                f"distinct_value_count_{year}",
            ]
        )
    columns.extend(["n_versions", "trend", "count_mismatch_editions"])
    return columns


def pesticide_reconciliation_rows(report):
    reconciliation = report.get("visible_rule_reconciliation", {})
    if set(reconciliation) != set(PESTICIDE_YEARS):
        raise ValueError(
            "pesticide reconciliation does not cover all release years: "
            f"{sorted(reconciliation)}"
        )
    rows = []
    for year in PESTICIDE_YEARS:
        item = reconciliation[year]
        rows.append(
            {
                "standard": "GB 2763",
                "version_year": year,
                "declared_mrl_items": item["standard_declared_mrl_items"],
                "coordinate_extracted_visible_rules": item[
                    "coordinate_extracted_visible_rules"
                ],
                "visible_rules_minus_declared": item["visible_rules_minus_declared"],
                "declared_section_roster": item["declared_section_roster"],
                "extracted_section_headers": item["extracted_section_headers"],
                "section_roster_complete": item["section_roster_complete"],
                "qualifier_counts": json.dumps(
                    item["qualifier_counts"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "status": item["status"],
                "interpretation_boundary": item["interpretation_boundary"],
            }
        )
    return rows


def vetdrug_2002_locator_queues(release_rows, replay_rows, locator_rows):
    """Align canonical released rows with raw Word-table locators by row order."""
    release_2002 = [row for row in release_rows if row.get("year") == "2002"]
    if not (
        len(release_2002) == len(replay_rows) == len(locator_rows)
        and len(release_2002) > 0
    ):
        raise ValueError(
            "2002 veterinary-drug locator inputs differ in length: "
            f"release={len(release_2002)}, replay={len(replay_rows)}, "
            f"locators={len(locator_rows)}"
        )
    queues = defaultdict(deque)
    identity_fields = ("drug", "english", "animal_raw", "limit_value")
    for output_row, (released, replayed, locator) in enumerate(
        zip(release_2002, replay_rows, locator_rows), start=1
    ):
        if locator.get("output_row") != str(output_row):
            raise ValueError(f"non-sequential 2002 locator row: {locator}")
        if any(locator.get(field) != replayed.get(field) for field in identity_fields):
            raise ValueError(f"2002 locator differs from replay row {output_row}")
        if locator.get("tissue") != replayed.get("tissue"):
            raise ValueError(f"2002 locator tissue differs at row {output_row}")
        if any(released.get(field) != replayed.get(field) for field in identity_fields):
            raise ValueError(f"2002 release row order differs at row {output_row}")
        key = (
            released["drug"],
            released["english"],
            released["animal_raw"],
            released["tissue"],
            released["limit_value"],
        )
        queues[key].append(locator)
    return queues


ROW_EXTRACTION_METHODS = (
    "pdf_text_and_coordinate_parser",
    "pdf_text_layer",
    "word_table_stream",
    "manual_page_image_transcription",
)
BYTE_EXACT_LOCATORS = {"byte_exact_official_file", "recorded_acquisition_url"}
# GB 31650-2019 的文件级方法是文本层加跨页手录，逐行按上游 source 列拆开。
VETDRUG_ROW_METHODS = {
    "text": "pdf_text_layer",
    "docx-block": "word_table_stream",
    "manual": "manual_page_image_transcription",
}


def load_blind_tasks():
    """Return the blind re-entry task contract that locates the manual rows."""

    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "260716_blind_manual_reentry.py"
    )
    spec = importlib.util.spec_from_file_location("blind_manual_reentry_release", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_tasks()


def manual_row_locators(tasks, released, seeds, fields):
    """Map record_id to PDF page, table and row for one manual batch.

    Tasks name their construction seed row; each released row is first checked
    against that seed row, so order alone never places a locator.
    """
    if len(released) != len(seeds) or len(tasks) != len(seeds):
        raise ValueError("manual rows, seed rows and blind tasks differ in number")
    for position, (row, seed) in enumerate(zip(released, seeds), start=1):
        if any(row[ours].casefold() != seed[theirs].casefold() for ours, theirs in fields):
            raise ValueError(f"manual row {position} differs from its seed row")
    by_seed_row = {int(task["construction_seed_row"]): task for task in tasks}
    return {
        row["record_id"]: (
            f"PDF p. {by_seed_row[position]['pdf_page']}, "
            f"table {by_seed_row[position]['printed_table']}, "
            f"row {by_seed_row[position]['printed_row']}"
        )
        for position, row in enumerate(released, start=1)
    }


def add_source_columns(rows, locate=None, row_method=None):
    """Append source_reference and extraction_method after record IDs exist."""

    documents = source_documents_by_id()
    locators = source_locators_by_id()
    for row in rows:
        source_id = row["extraction_source_id"]
        method = documents[source_id].extraction_mode
        if row_method is not None:
            method = row_method(row, method)
        if method not in ROW_EXTRACTION_METHODS:
            raise ValueError(f"no row-level extraction method for {row['record_id']}: {method}")
        standard, year = row["standard"], row["version_year"]
        citation = f"{standard}-{year}" if standard.startswith("GB") else f"{standard} ({year})"
        locator = locators[source_id]
        # 文件直链只给字节一致的副本；其余给标准身份页，字节状态见 SOURCE_ACQUISITION.md。
        if locator.locator_status in BYTE_EXACT_LOCATORS and locator.file_url:
            url = locator.file_url
        else:
            url = locator.landing_url or locator.file_url
        parts = (citation, locate(row) if locate else "", url)
        row["source_reference"] = "; ".join(part for part in parts if part)
        row["extraction_method"] = method


def extraction_method_summary(tables):
    """Count released records by family, edition and row-level extraction method."""

    counts = Counter()
    for family, rows in tables:
        for row in rows:
            counts[(family, row["standard"], row["version_year"], row["extraction_method"])] += 1
    total = sum(len(rows) for _, rows in tables)
    if sum(counts.values()) != total:
        raise ValueError("extraction-method counts differ from released records")
    family_totals = Counter()
    for (family, *_), count in counts.items():
        family_totals[family] += count
    order = {family: position for position, (family, _) in enumerate(tables)}
    return [
        {
            "family": family, "standard": standard, "version_year": year,
            "extraction_method": method, "records": str(count),
            "share_of_family_pct": f"{100 * count / family_totals[family]:.2f}",
            "share_of_release_pct": f"{100 * count / total:.2f}",
        }
        for (family, standard, year, method), count in sorted(
            counts.items(), key=lambda item: (order[item[0][0]], item[0][2], item[0][3])
        )
    ]


VERIFICATION_BASES = (
    "ocr_crosscheck",
    "independent_audit_reading",
    "independent_blind_reentry",
    "author_scan_check",
)


def pesticide_ocr_evidence(groups, rows):
    """Link each text-layer OCR group to its one released 2019/2021 row."""

    keys = {
        "strict_scope": ("section_number", "parent_category", "food"),
        "unique_section_food": ("section_number", "food"),
    }
    row_columns = {"section_number": "section_number", "parent_category": "parent_category_zh",
                   "food": "food_zh"}
    audited = [row for row in rows if row["version_year"] in ("2019", "2021")]
    indexes = {level: defaultdict(list) for level in keys}
    for row in audited:
        for level, columns in keys.items():
            key = (row["version_year"], *(row[row_columns[column]] for column in columns))
            indexes[level][key].append(row)
    evidence = {}
    outcomes = {"consistent": "agree", "conflict": "disagree"}
    for group in groups:
        if group["status"] == "ocr_only":
            continue
        columns = keys[group["key_level"]]
        matches = indexes[group["key_level"]][(group["year"], *(group[c] for c in columns))]
        if len(matches) != 1 or group["text_row_count"] != "1":
            raise ValueError(f"OCR group does not link to one row: {group}")
        row = matches[0]
        if row["record_id"] in evidence or group["text_source_pages"] != row["source_page"]:
            raise ValueError(f"OCR group links inconsistently: {row['record_id']}")
        evidence[row["record_id"]] = (
            [("ocr_crosscheck", outcomes[group["status"]])] if group["status"] in outcomes else []
        )
    if set(evidence) != {row["record_id"] for row in audited}:
        raise ValueError("OCR groups do not cover every 2019/2021 pesticide row")
    return {record_id: items for record_id, items in evidence.items() if items}


def pesticide_audit_evidence(rows):
    """Adjudicated outcome of each 2019/2021 pesticide row read independently.

    A reading still settles its row only if the fields it saw are unchanged,
    or, for an adjudicated release error, if the release has since been fixed.
    """

    index = defaultdict(list)
    for row in rows:
        index[(row["version_year"], row["section_number"], row["food_zh"], row["limit_value"])].append(row)
    evidence = defaultdict(list)
    for round_dir in PESTICIDE_AUDIT_ROUNDS:
        base = os.path.join(AUDIT_INTERIM, round_dir, "comparison")
        for reading in read("pesticide_audit_comparison.csv", base=base):
            if not reading["record_id"]:
                continue  # OCR-only group: no released row exists
            key = (reading["edition"], reading["section_number"], reading["food_zh"],
                   reading["released_limit_value"])
            if len(index[key]) != 1:
                raise ValueError(f"audited row is not unique in the release: {reading['blind_id']}")
            row = index[key][0]
            same_category = row["parent_category_zh"] == reading["parent_category_zh"]
            same_mark = row["is_temporary"] == reading["released_is_temporary"]
            outcome = (reading["outcome"], reading["verdict"])
            if outcome in (("agree", ""), ("value_differs", "reviewer_misreading")):
                if not (same_category and same_mark):
                    raise ValueError(f"audited row changed after it was read: {reading['blind_id']}")
                settled = True
            elif outcome == ("not_found", "extraction_error"):
                if not same_mark:
                    raise ValueError(f"audited row changed after it was read: {reading['blind_id']}")
                settled = not same_category
            elif outcome == ("asterisk_differs", "text_layer_error"):
                settled = not same_mark
            else:
                raise ValueError(f"unknown audit outcome for {reading['blind_id']}: {outcome}")
            evidence[row["record_id"]].append(
                ("independent_audit_reading", "agree" if settled else "disagree"))
    return evidence


def check_blind_reentry(seed_paths):
    """Require a passed blind re-entry audit of the current construction seeds."""

    with open(os.path.join(AUDIT_INTERIM, BLIND_REENTRY_REPORT), encoding="utf-8") as handle:
        report = json.load(handle)
    if report["status"] != "pass" or report["provenance_gap"]["status"] != "closed":
        raise ValueError("blind re-entry audit has not passed")
    for batch, path in seed_paths.items():
        with open(path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        if digest != report["inputs"]["construction_seeds"][batch]["sha256"]:
            raise ValueError(f"{batch} seed changed after the blind re-entry audit")


def add_verification_columns(rows, evidence=None):
    """Append verification_status and verification_basis after record IDs exist.

    A reading against the source (independent or by the author) settles a row;
    the automated OCR comparison decides only rows that no one read.
    """
    evidence = evidence or {}
    for row in rows:
        items = evidence.get(row["record_id"], [])
        readings = [outcome for basis, outcome in items if basis != "ocr_crosscheck"]
        decisive = readings or [outcome for _, outcome in items]
        if not decisive:
            status = "no_cross_source_comparison"
        elif "disagree" in decisive:
            status = "unresolved_disagreement"
        else:
            status = "confirmed_agreement"
        bases = [basis for basis in VERIFICATION_BASES if any(b == basis for b, _ in items)]
        row["verification_status"] = status
        row["verification_basis"] = ";".join(bases) or "none"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", default=REL)
    parser.add_argument("--additive-interim", default=ADD_INTERIM)
    parser.add_argument("--pollutant-interim", default=POLLUTANT_INTERIM)
    parser.add_argument("--pesticide-interim", default=PESTICIDE_INTERIM)
    parser.add_argument("--mycotoxin-interim", default=MYCOTOXIN_INTERIM)
    parser.add_argument("--vetdrug-interim", default=VETDRUG_INTERIM)
    parser.add_argument("--dependency-interim", default=DEPENDENCY_INTERIM)
    parser.add_argument("--audit-interim", default=AUDIT_INTERIM)
    parser.add_argument("--timeline-dir", default=TIMELINE)
    parser.add_argument("--date-dir", default=DATE_DIR)
    return parser.parse_args(argv)


def main(argv=None):
    global ADD_INTERIM, DATE_DIR, DEPENDENCY_INTERIM, MYCOTOXIN_INTERIM
    global PESTICIDE_INTERIM, POLLUTANT_INTERIM, REL, TIMELINE, VETDRUG_INTERIM
    global AUDIT_INTERIM

    args = parse_args(argv)
    TIMELINE = os.path.abspath(args.timeline_dir)
    DATE_DIR = os.path.abspath(args.date_dir)
    REL = os.path.abspath(args.release_dir)
    ADD_INTERIM = os.path.abspath(args.additive_interim)
    POLLUTANT_INTERIM = os.path.abspath(args.pollutant_interim)
    PESTICIDE_INTERIM = os.path.abspath(args.pesticide_interim)
    MYCOTOXIN_INTERIM = os.path.abspath(args.mycotoxin_interim)
    VETDRUG_INTERIM = os.path.abspath(args.vetdrug_interim)
    DEPENDENCY_INTERIM = os.path.abspath(args.dependency_interim)
    AUDIT_INTERIM = os.path.abspath(args.audit_interim)
    required_inputs = {
        ADD_INTERIM: (
            "additive_raw_long.csv",
            "additive_quarantine.csv",
        ),
        POLLUTANT_INTERIM: (
            "pollutant_limits_by_version.csv",
            "category_crosswalk.csv",
            "member_crosswalk.csv",
            "pollutant_quarantine.csv",
            "pollutant_rebuild_report.json",
        ),
        PESTICIDE_INTERIM: (
            "pesticide_textlayer_limits.csv",
            "pesticide_textlayer_ocr_crosscheck.csv",
            "pesticide_textlayer_extraction_report.json",
        ),
        MYCOTOXIN_INTERIM: (
            "mycotoxin_limits_by_version.csv",
            "mycotoxin_strictness_change.csv",
        ),
        VETDRUG_INTERIM: (
            "vetdrug_limits_by_version.csv",
            "vetdrug_2002_long.csv",
            "vetdrug_2002_row_locators.csv",
        ),
        DEPENDENCY_INTERIM: (
            "food_taxonomy.csv",
            "category_alias.csv",
            "category_containment.csv",
            "pollutant_old_path.csv",
            "pollutant_doublecol_long.csv",
            "member_crosswalk_mycotoxin.csv",
            "member_crosswalk_vetdrug.csv",
        ),
        TIMELINE: (
            "standard_versions_long.csv",
            "standard_timeline_conflicts.csv",
        ),
        DATE_DIR: ("coverage_version_dates.csv",),
        AUDIT_INTERIM: (
            *(f"{round_dir}/comparison/pesticide_audit_comparison.csv"
              for round_dir in PESTICIDE_AUDIT_ROUNDS),
            BLIND_REENTRY_REPORT,
        ),
    }
    missing_inputs = []
    for directory, filenames in required_inputs.items():
        for filename in filenames:
            if not os.path.isfile(os.path.join(directory, filename)):
                missing_inputs.append(
                    os.path.relpath(os.path.join(directory, filename), PROJECT_ROOT)
                )
    if missing_inputs:
        raise SystemExit(
            "发布构建缺少项目内中间层文件：" + ", ".join(sorted(missing_inputs))
        )

    dependency_rows = verify_release_dependencies(DEPENDENCY_INTERIM)
    verify_pollutant_rebuild_report(POLLUTANT_INTERIM, DEPENDENCY_INTERIM)
    os.makedirs(REL, exist_ok=True)

    source_relations = source_ids_by_edition()

    def source_relation(family, standard, year):
        key = (family, standard, str(year))
        if key not in source_relations:
            raise ValueError(f"source manifest has no edition relation: {key}")
        return source_relations[key]

    stats = {}

    # ---------- 1. 污染物 GB2762 长表 ----------
    rows = []
    for r in read("pollutant_limits_by_version.csv", base=POLLUTANT_INTERIM):
        limit_mgkg, normalization_status = normalize_mass_per_mass(
            r["limit_value"], r["unit"]
        )
        relation = source_relation("contaminant", "GB 2762", r["year"])
        rows.append({
            "standard": "GB 2762", "version_year": r["year"],
            "analyte_zh": r["analyte"], "analyte_en": ANALYTE_EN.get(r["analyte"], ""),
            "food_category_zh": r["food_category"],
            "limit_value": r["limit_value"], "unit": r["unit"],
            "limit_mgkg": limit_mgkg,
            "normalization_status": normalization_status,
            # 计量基准:限量不是一个数,是「数 + 它相对的基准」。木耳的甲基汞 0.1(干重计)
            # 与其父类食用菌的 0.1(以售出状态计)数字相同却【不可通约】。
            # 这一列上游一直有,是发布打包时漏带了 —— 漏掉它,读者就只能拿两个不可比的数去相减。
            "limit_basis": r.get("basis", ""),
            "note": r.get("note", ""), "confidence": r["confidence"],
            "extraction_path": r.get("extraction_path", ""),
            **relation,
        })
    rows, nx, nc = dedup_and_id(rows, ["version_year", "analyte_zh", "food_category_zh"], "POL")
    add_source_columns(rows)
    add_verification_columns(rows)
    pollutant_long = rows
    stats["pollutant_limits"] = {"rows": write("pollutant_limits_long.csv", rows,
        ["record_id", "standard", "version_year", "analyte_zh", "analyte_en", "food_category_zh",
         "limit_value", "unit", "limit_mgkg", "normalization_status", "limit_basis", "note",
         "confidence", "extraction_path", "edition_source_id", "extraction_source_id",
         "conflict", "source_reference", "extraction_method", "verification_status",
         "verification_basis"]),
        "exact_dups_removed": nx, "rows_with_conflicting_key": nc}

    # ---------- 2. 污染物 类别级面板 ----------
    rows = []
    for r in read("category_crosswalk.csv", base=POLLUTANT_INTERIM):
        rows.append({
            "standard": "GB 2762", "analyte_zh": r["analyte"],
            "analyte_en": ANALYTE_EN.get(r["analyte"], ""),
            "food_category_zh": r["canonical"],
            "v2012": r["v2012"], "v2017": r["v2017"], "v2022": r["v2022"], "v2025": r["v2025"],
            "unit_summary": r["unit"], "n_versions": r["n_versions"],
            "coverage_status": coded(r["状态"], COVERAGE_CODES, "coverage status"),
            "trend": coded(r["trend"], TREND_CODES, "trend"),
            **{f"unit_{year}": r[f"unit{year}"] for year in ("2012", "2017", "2022", "2025")},
            **{f"basis_{year}": r[f"basis{year}"] for year in ("2012", "2017", "2022", "2025")},
            **{
                f"cell_status_{year}": r[f"cell_status{year}"]
                for year in ("2012", "2017", "2022", "2025")
            },
            **{
                f"source_category_{year}": r[f"原始名{year}"]
                for year in ("2012", "2017", "2022", "2025")
            },
        })
    rows, nx, nc = dedup_and_id(rows, ["analyte_zh", "food_category_zh"], "PCP")
    # Back-links are added after the IDs so that unchanged rows keep their IDs.
    link_source_records(
        rows, pollutant_long, POLLUTANT_YEARS,
        lambda row, year: [] if row[f"cell_status_{year}"] == "missing" else [
            (year, row["analyte_zh"], row[f"source_category_{year}"], row[f"basis_{year}"])
        ],
        lambda r: (r["version_year"], r["analyte_zh"], r["food_category_zh"], r["limit_basis"]),
    )
    stats["pollutant_category_panel"] = {"rows": write("pollutant_category_panel.csv", rows,
        ["record_id", "standard", "analyte_zh", "analyte_en", "food_category_zh",
         "v2012", "v2017", "v2022", "v2025",
         "unit_2012", "unit_2017", "unit_2022", "unit_2025",
         "basis_2012", "basis_2017", "basis_2022", "basis_2025",
         "cell_status_2012", "cell_status_2017", "cell_status_2022", "cell_status_2025",
         "source_category_2012", "source_category_2017", "source_category_2022",
         "source_category_2025", "unit_summary", "n_versions", "coverage_status", "trend",
         *(f"source_record_ids_{year}" for year in POLLUTANT_YEARS)]),
        "exact_dups_removed": nx}

    # ---------- 3. 污染物 成员级面板(★核心贡献) ----------
    rows = []
    for r in read("member_crosswalk.csv", base=POLLUTANT_INTERIM):
        rows.append({
            "standard": "GB 2762", "analyte_zh": r["analyte"],
            "analyte_en": ANALYTE_EN.get(r["analyte"], ""),
            "food_member_zh": r["member"],
            "v2012": r["v2012"], "v2017": r["v2017"], "v2022": r["v2022"], "v2025": r["v2025"],
            # 基准不一致的成员 trend 判为「不可比」—— 没有这一列,读者看到 2.0/2.0/2.0/2.0
            # 只会觉得我们把一行明明"稳定"的记录判错了。
            "limit_basis": r.get("basis", ""),
            **{f"unit_{year}": r[f"unit{year}"] for year in ("2012", "2017", "2022", "2025")},
            **{f"basis_{year}": r[f"basis{year}"] for year in ("2012", "2017", "2022", "2025")},
            "trend": coded(r["trend"], TREND_CODES, "trend"),
            "category_restructured": "yes" if r["类别重组"] == "是" else "no",
            "host_category_2012": r["归属类别2012"], "host_category_2017": r["归属类别2017"],
            "host_category_2022": r["归属类别2022"], "host_category_2025": r["归属类别2025"],
            "note": r.get("note", ""),
        })
    rows, nx, nc = dedup_and_id(rows, ["analyte_zh", "food_member_zh"], "PMP")
    link_source_records(
        rows, pollutant_long, POLLUTANT_YEARS,
        lambda row, year: [(
            year, row["analyte_zh"], row[f"host_category_{year}"], row[f"v{year}"],
            row[f"unit_{year}"], row[f"basis_{year}"],
        )] if row[f"v{year}"] else [],
        lambda r: (r["version_year"], r["analyte_zh"], r["food_category_zh"],
                   r["limit_value"], r["unit"], r["limit_basis"]),
    )
    stats["pollutant_member_panel"] = {"rows": write("pollutant_member_panel.csv", rows,
        ["record_id", "standard", "analyte_zh", "analyte_en", "food_member_zh",
         "v2012", "v2017", "v2022", "v2025",
         "unit_2012", "unit_2017", "unit_2022", "unit_2025",
         "basis_2012", "basis_2017", "basis_2022", "basis_2025",
         "limit_basis", "trend", "category_restructured",
         "host_category_2012", "host_category_2017", "host_category_2022", "host_category_2025", "note",
         *(f"source_record_ids_{year}" for year in POLLUTANT_YEARS)]),
        "exact_dups_removed": nx}

    # ---------- 4. 农残 GB2763 ----------
    pesticide_source_ids = {
        year: source_relation("pesticide", "GB 2763", year)
        for year in PESTICIDE_YEARS
    }
    rows, nc = prepare_pesticide_limits(
        read("pesticide_textlayer_limits.csv", base=PESTICIDE_INTERIM),
        pesticide_source_ids,
    )
    add_source_columns(rows, locate=lambda row: (
        "government-hosted copy, "
        if row["extraction_source_id"] != row["edition_source_id"] else ""
    ) + f"PDF p. {row['source_page']}")
    ocr_crosscheck = read(
        "pesticide_textlayer_ocr_crosscheck.csv", base=PESTICIDE_INTERIM
    )
    evidence = pesticide_ocr_evidence(ocr_crosscheck, rows)
    for record_id, items in pesticide_audit_evidence(rows).items():
        evidence.setdefault(record_id, []).extend(items)
    for row in rows:
        if "scan_temporary_mark_correction" in row["review_status"].split(";"):
            evidence.setdefault(row["record_id"], []).append(("author_scan_check", "agree"))
    add_verification_columns(rows, evidence)
    pesticide_long = rows
    stats["pesticide_limits"] = {"rows": write("pesticide_limits_long.csv", rows,
        ["record_id", "standard", "version_year", "section_number",
         "pesticide_key", "pesticide_zh", "pesticide_en", "pesticide_zh_raw",
         "pesticide_en_raw", "parent_category_zh", "parent_category_raw",
         "food_key", "food_zh", "food_raw", "limit_value", "unit",
         "limit_qualifier", "is_temporary", "value_raw", "source_page", "source_y",
         "food_x", "parent_assignment_method", "table_open_method", "review_status",
         "edition_source_id", "extraction_source_id", "source_copy_role", "conflict",
         "source_reference", "extraction_method", "verification_status",
         "verification_basis"]),
        "exact_dups_removed": 0, "rows_with_conflicting_key": nc}

    with open(
        os.path.join(PESTICIDE_INTERIM, "pesticide_textlayer_extraction_report.json"),
        encoding="utf-8",
    ) as handle:
        pesticide_report = json.load(handle)
    if pesticide_report.get("validation_passed") is not True:
        raise ValueError("pesticide text-layer report did not pass validation gates")
    reconciliation_rows = pesticide_reconciliation_rows(pesticide_report)
    mismatch_years = [
        row["version_year"] for row in reconciliation_rows
        if int(row["visible_rules_minus_declared"]) != 0
    ]

    rows = build_pesticide_panel_v2(rows)
    rows, nx, nc = preserve_rules_and_id(
        rows,
        ["pesticide_key", "food_key"],
        ["pesticide_key", "food_key"],
        "PSP",
    )
    # Editions whose visible rule count differs from the declared count; added
    # after the IDs so that unchanged rows keep their IDs.
    for row in rows:
        row["count_mismatch_editions"] = json.dumps(
            [year for year in mismatch_years if row[f"status_{year}"] != "missing"],
            separators=(",", ":"),
        )
    stats["pesticide_panel"] = {"rows": write("pesticide_panel.csv", rows,
        pesticide_panel_output_columns()),
        "exact_dups_removed": nx}

    stats["pesticide_edition_reconciliation"] = {
        "rows": write(
            "pesticide_edition_reconciliation.csv",
            reconciliation_rows,
            [
                "standard",
                "version_year",
                "declared_mrl_items",
                "coordinate_extracted_visible_rules",
                "visible_rules_minus_declared",
                "declared_section_roster",
                "extracted_section_headers",
                "section_roster_complete",
                "qualifier_counts",
                "status",
                "interpretation_boundary",
            ],
        ),
        "exact_dups_removed": 0,
    }
    crosscheck_columns = list(ocr_crosscheck[0]) if ocr_crosscheck else []
    if not crosscheck_columns:
        raise ValueError("pesticide OCR crosscheck is empty")
    stats["pesticide_ocr_crosscheck"] = {
        "rows": write(
            "pesticide_ocr_crosscheck.csv", ocr_crosscheck, crosscheck_columns
        ),
        "exact_dups_removed": 0,
    }

    # ---------- 5. 真菌毒素 GB2761 ----------
    rows = []
    for r in read("mycotoxin_limits_by_version.csv", base=MYCOTOXIN_INTERIM):
        relation = source_relation("mycotoxin", "GB 2761", r["year"])
        rows.append({
            "standard": "GB 2761", "version_year": r["year"],
            "toxin_zh": r["toxin"], "toxin_en": ANALYTE_EN.get(r["toxin"], ""),
            "food_category_zh": r["food_category"],
            "limit_value": r["limit_value"], "unit": r["unit"], "confidence": r["confidence"],
            **relation,
        })
    rows, nx, nc = dedup_and_id(rows, ["version_year", "toxin_zh", "food_category_zh"], "MYC")
    check_blind_reentry({
        "MYC2005": os.path.join(MYCOTOXIN_INTERIM, "myco2005_manual.csv"),
        "VET2019": os.path.join(VETDRUG_INTERIM, "vetdrug_2019_manual.csv"),
        "VET2022": os.path.join(VETDRUG_INTERIM, "vetdrug_2022_manual.csv"),
    })
    blind_tasks = load_blind_tasks()
    manual_locators = manual_row_locators(
        blind_tasks["MYC2005"],
        [row for row in rows if row["version_year"] == "2005"],
        read("myco2005_manual.csv", base=MYCOTOXIN_INTERIM),
        (("toxin_zh", "toxin"), ("food_category_zh", "food_category"),
         ("limit_value", "limit_value"), ("unit", "unit")),
    )

    def mycotoxin_method(row, mode):
        if (row["confidence"] == "manual") != (mode == "manual_page_image_transcription"):
            raise ValueError(f"mycotoxin confidence differs from source mode: {row['record_id']}")
        return mode

    add_source_columns(rows, locate=lambda row: manual_locators.get(row["record_id"], ""),
                       row_method=mycotoxin_method)
    reentered = {record_id: [("independent_blind_reentry", "agree")] for record_id in manual_locators}
    add_verification_columns(rows, reentered)
    mycotoxin_long = rows
    stats["mycotoxin_limits"] = {"rows": write("mycotoxin_limits_long.csv", rows,
        ["record_id", "standard", "version_year", "toxin_zh", "toxin_en", "food_category_zh",
         "limit_value", "unit", "confidence", "edition_source_id", "extraction_source_id",
         "conflict", "source_reference", "extraction_method", "verification_status",
         "verification_basis"]), "exact_dups_removed": nx}

    rows = []
    mycotoxin_printed = {}
    for r in read("mycotoxin_strictness_change.csv", base=MYCOTOXIN_INTERIM):
        mycotoxin_printed[(r["toxin"], r["food_canon"])] = r
        rows.append({
            "standard": "GB 2761", "toxin_zh": r["toxin"], "toxin_en": ANALYTE_EN.get(r["toxin"], ""),
            "food_zh": r["food_canon"], "v2005": r["v2005"], "v2011": r["v2011"], "v2017": r["v2017"],
            "unit": "μg/kg", "trend": coded(r["trend"], TREND_CODES, "trend"),
            "note": r.get("note2005", ""),
        })
    rows, nx, nc = dedup_and_id(rows, ["toxin_zh", "food_zh"], "MSP")

    def mycotoxin_printed_rule(row, year):
        printed = mycotoxin_printed[(row["toxin_zh"], row["food_zh"])][f"raw{year}"]
        return [(year, row["toxin_zh"], printed)] if printed else []

    link_source_records(
        rows, mycotoxin_long, MYCOTOXIN_YEARS, mycotoxin_printed_rule,
        lambda r: (r["version_year"], r["toxin_zh"], r["food_category_zh"]),
    )
    stats["mycotoxin_panel"] = {"rows": write("mycotoxin_panel.csv", rows,
        ["record_id", "standard", "toxin_zh", "toxin_en", "food_zh",
         "v2005", "v2011", "v2017", "unit", "trend", "note",
         *(f"source_record_ids_{year}" for year in MYCOTOXIN_YEARS)]), "exact_dups_removed": nx}

    # ---------- 6. 兽残 GB31650 ----------
    vetdrug_long_input = read("vetdrug_limits_by_version.csv", base=VETDRUG_INTERIM)
    locator_queues = vetdrug_2002_locator_queues(
        vetdrug_long_input,
        read("vetdrug_2002_long.csv", base=VETDRUG_INTERIM),
        read("vetdrug_2002_row_locators.csv", base=VETDRUG_INTERIM),
    )
    rows = []
    vet_standard = {
        "2002": "MOA Announcement 235",
        "2019": "GB 31650",
        "2022": "GB 31650.1",
    }
    for r in vetdrug_long_input:
        year = r["year"]
        standard = vet_standard[year]
        relation = source_relation("veterinary_drug", standard, year)
        locator = {}
        if year == "2002":
            locator_key = (
                r["drug"],
                r["english"],
                r["animal_raw"],
                r["tissue"],
                r["limit_value"],
            )
            if not locator_queues[locator_key]:
                raise ValueError(f"missing 2002 veterinary-drug locator: {locator_key}")
            locator = locator_queues[locator_key].popleft()
        rows.append({
            "standard": standard, "version_year": year,
            "drug_zh": r["drug"], "drug_en": r["english"],
            "animal": r.get("animal", ""), "animal_raw": r.get("animal_raw", ""),
            "tissue_zh": r["tissue"],
            "limit_value": r["limit_value"], "unit": r["unit"], "source": r["source"],
            "source_table_index": locator.get("source_table_index", ""),
            "source_table_row": locator.get("source_table_row", ""),
            "animal_block_index": locator.get("animal_block_index", ""),
            "tissue_index": locator.get("tissue_index", ""),
            **relation,
        })
    leftover_locators = sum(len(queue) for queue in locator_queues.values())
    if leftover_locators:
        raise ValueError(f"unused 2002 veterinary-drug locators: {leftover_locators}")
    rows, nx, nc = dedup_and_id(rows, ["version_year", "drug_en", "animal", "tissue_zh"], "VET")
    vet_manual_fields = (("drug_zh", "drug"), ("drug_en", "english"), ("animal_raw", "animal"),
                         ("limit_value", "limit_value"), ("unit", "unit"))
    for batch, year, seed in (("VET2019", "2019", "vetdrug_2019_manual.csv"),
                              ("VET2022", "2022", "vetdrug_2022_manual.csv")):
        manual_locators.update(manual_row_locators(
            blind_tasks[batch],
            [row for row in rows if row["version_year"] == year and row["source"] == "manual"],
            read(seed, base=VETDRUG_INTERIM),
            vet_manual_fields,
        ))

    def vetdrug_method(row, mode):
        method = VETDRUG_ROW_METHODS[row["source"]]
        if mode not in (method, "pdf_text_with_manual_page_break_rows"):
            raise ValueError(f"veterinary-drug row source differs from source mode: {row['record_id']}")
        return method

    def vetdrug_locate(row):
        if row["source_table_index"]:
            return f"Word table {row['source_table_index']}, row {row['source_table_row']}"
        return manual_locators.get(row["record_id"], "")

    add_source_columns(rows, locate=vetdrug_locate, row_method=vetdrug_method)
    reentered = {record_id: [("independent_blind_reentry", "agree")] for record_id in manual_locators}
    add_verification_columns(rows, reentered)
    vetdrug_long = rows
    stats["vetdrug_limits"] = {"rows": write("vetdrug_limits_long.csv", rows,
        ["record_id", "standard", "version_year", "drug_zh", "drug_en", "animal", "animal_raw",
         "tissue_zh", "limit_value", "unit", "source", "source_table_index",
         "source_table_row", "animal_block_index", "tissue_index", "edition_source_id",
         "extraction_source_id", "conflict", "source_reference", "extraction_method", "verification_status",
         "verification_basis"]),
        "exact_dups_removed": nx, "rows_with_conflicting_key": nc}

    rows = build_vetdrug_summary_panel(
        read("vetdrug_limits_long.csv", base=REL)
    )
    rows, nx, nc = dedup_and_id(rows, ["drug_en", "tissue_zh"], "VSP")
    link_source_records(
        rows, vetdrug_long, VETDRUG_SUMMARY_YEARS,
        lambda row, year: [(year, row["drug_en"], row["tissue_zh"])] if row[f"v{year}"] else [],
        lambda r: (r["version_year"], _normalise_vetdrug_english(r["drug_en"]), r["tissue_zh"]),
        unique=False,
    )
    stats["vetdrug_panel"] = {"rows": write("vetdrug_panel.csv", rows,
        ["record_id", "standard", "drug_zh", "drug_en", "tissue_zh",
         "v2002", "v2019", "unit", "trend",
         *(f"source_record_ids_{year}" for year in VETDRUG_SUMMARY_YEARS)]),
        "exact_dups_removed": nx}

    # ---------- 7. 添加剂 GB2760 ----------
    rows = []
    for r in read("additive_raw_long.csv", base=ADD_INTERIM):
        relation = source_relation("additive", "GB 2760", r["year"])
        rows.append({
            "standard": "GB 2760", "version_year": r["year"],
            "additive_zh": r["additive"], "cns_code": r["cns"], "ins_code": r.get("ins", ""),
            "food_code": r["food_code"], "food_zh": r["food"],
            "max_use": r["max_use"], "unit": r["unit"], "note": r.get("note", ""),
            **relation,
        })
    rows, nx, nc = dedup_and_id(rows, ["version_year", "cns_code", "food_code"], "ADD")
    add_source_columns(rows)
    add_verification_columns(rows)
    additive_long = rows
    stats["additive_limits"] = {"rows": write("additive_limits_long.csv", rows,
        ["record_id", "standard", "version_year", "additive_zh", "cns_code", "ins_code", "food_code",
         "food_zh", "max_use", "unit", "note", "edition_source_id",
         "extraction_source_id", "conflict", "source_reference", "extraction_method", "verification_status",
         "verification_basis"]),
        "exact_dups_removed": nx, "rows_with_conflicting_key": nc}

    method_rows = extraction_method_summary((
        ("contaminant", pollutant_long), ("pesticide", pesticide_long),
        ("mycotoxin", mycotoxin_long), ("veterinary_drug", vetdrug_long),
        ("additive", additive_long),
    ))
    stats["extraction_method_summary"] = {"rows": write("extraction_method_summary.csv", method_rows,
        ["family", "standard", "version_year", "extraction_method", "records",
         "share_of_family_pct", "share_of_release_pct"])}

    rows = build_additive_panel(rows)
    rows, nx, nc = dedup_and_id(rows, ["cns_code", "food_code"], "ASP")
    stats["additive_panel"] = {"rows": write("additive_panel.csv", rows,
        panel_columns(
            ["record_id", "standard", "additive_zh", "additive_names_zh", "cns_code",
             "ins_codes", "food_code", "food_zh", "food_names_zh"],
            ADDITIVE_YEARS,
            ["trend"],
        )), "exact_dups_removed": nx}

    # ---------- 8. 版本沿革 ----------
    rows = []
    for r in read("standard_versions_long.csv", base=TIMELINE):
        rows.append({
            "std_id": r["std_id"], "number": r["number"],
            "event_type": "official_version" if r["event_type"] == "正式版" else "amendment",
            "version_year": r["year"], "amendment_no": r.get("amend_no", ""),
            "issue_date": r.get("发布日期", ""), "effective_date": r.get("实施日期", ""),
            "title_zh": r.get("title", ""),
        })
    rows, nx, nc = dedup_and_id(rows, ["std_id", "version_year", "event_type", "amendment_no"], "TML")
    stats["standard_timeline"] = {"rows": write("standard_version_timeline.csv", rows,
        ["record_id", "std_id", "number", "event_type", "version_year", "amendment_no",
         "issue_date", "effective_date", "title_zh"]), "exact_dups_removed": nx}
    timeline_conflicts = read("standard_timeline_conflicts.csv", base=TIMELINE)
    conflict_columns = list(timeline_conflicts[0]) if timeline_conflicts else []
    if not conflict_columns:
        raise ValueError("standard timeline conflict audit is empty")
    stats["standard_timeline_conflicts"] = {
        "rows": write(
            "standard_timeline_conflicts.csv",
            timeline_conflicts,
            conflict_columns,
        ),
        "exact_dups_removed": 0,
    }

    # ---------- 9. 成员级面板:兽残 / 真菌毒素 ----------
    rows = []
    vetdrug_hosts = {}
    for r in dependency_rows["member_crosswalk_vetdrug.csv"]:
        vetdrug_hosts[(r["drug"], r["animal"], r["tissue"])] = r
        rows.append({
            "standard": "GB 31650", "drug_zh": r["drug"], "drug_en": r["english"],
            "animal": r["animal"], "tissue_zh": r["tissue"],
            "v2002": r["v2002"], "v2019": r["v2019"], "v2022": r["v2022"],
            "unit": "mg/kg", "trend": coded(r["trend"], TREND_CODES, "trend"),
        })
    rows, nx, nc = dedup_and_id(rows, ["drug_en", "animal", "tissue_zh"], "VMP")
    link_source_records(
        rows, vetdrug_long, VETDRUG_MEMBER_YEARS,
        lambda row, year: [
            (year, row["drug_zh"], row["tissue_zh"], label)
            for label in vetdrug_hosts[(row["drug_zh"], row["animal"], row["tissue_zh"])][
                f"归属{year}"
            ].split("；")
        ] if row[f"v{year}"] else [],
        lambda r: (r["version_year"], r["drug_zh"], r["tissue_zh"], r["animal"]),
    )
    stats["vetdrug_member_panel"] = {"rows": write("vetdrug_member_panel.csv", rows,
        ["record_id", "standard", "drug_zh", "drug_en", "animal", "tissue_zh",
         "v2002", "v2019", "v2022", "unit", "trend",
         *(f"source_record_ids_{year}" for year in VETDRUG_MEMBER_YEARS)]),
        "exact_dups_removed": nx}

    rows = []
    for r in dependency_rows["member_crosswalk_mycotoxin.csv"]:
        rows.append({
            "standard": "GB 2761", "toxin_zh": r["toxin"], "food_member_zh": r["member"],
            "v2005": r["v2005"], "v2011": r["v2011"], "v2017": r["v2017"],
            "unit": "mg/kg", "trend": coded(r["trend"], TREND_CODES, "trend"),
            "category_restructured": "yes" if r["类别重组"] == "是" else "no",
            "host_category_2005": r["归属2005"], "host_category_2011": r["归属2011"],
            "host_category_2017": r["归属2017"],
        })
    rows, nx, nc = dedup_and_id(rows, ["toxin_zh", "food_member_zh"], "MMP")
    link_source_records(
        rows, mycotoxin_long, MYCOTOXIN_YEARS,
        lambda row, year: [(year, row["toxin_zh"], row[f"host_category_{year}"])]
        if row[f"v{year}"] else [],
        lambda r: (r["version_year"], r["toxin_zh"], r["food_category_zh"]),
    )
    stats["mycotoxin_member_panel"] = {"rows": write("mycotoxin_member_panel.csv", rows,
        ["record_id", "standard", "toxin_zh", "food_member_zh", "v2005", "v2011", "v2017",
         "unit", "trend", "category_restructured",
         "host_category_2005", "host_category_2011", "host_category_2017",
         *(f"source_record_ids_{year}" for year in MYCOTOXIN_YEARS)]),
        "exact_dups_removed": nx}

    # ---------- 10. 隔离表(★随数据发布,不静默丢弃) ----------
    # 隔离量本身是数据质量的一部分。把它藏起来,读者就无从判断这份数据漏了什么、为什么漏。
    rows = []
    for r in read("additive_quarantine.csv", base=ADD_INTERIM):
        rows.append({
            "standard": "GB 2760", "version_year": r["year"], "additive_zh": r["additive"],
            "food_code": r["food_code"], "food_zh": r["food"], "parsed_value": r["max_use"],
            "unit": r.get("unit", ""), "reject_reason": r["reject"],
            "raw_text": r["raw_chunk"], "source_path": "GB 2760 source PDF",
        })
    for r in read("pollutant_quarantine.csv", base=POLLUTANT_INTERIM):
        rows.append({
            "standard": "GB 2762", "version_year": r["year"], "analyte_zh": r["analyte"],
            "food_zh": r["food_category"], "parsed_value": r["limit_value"],
            "unit": r["unit"], "reject_reason": r["reason"], "raw_text": r["food_category"],
            "source_path": portable_source_label(r["source_path"]),
        })
    rows, nx, nc = dedup_and_id(
        rows,
        ["standard", "version_year", "analyte_zh", "additive_zh", "food_code", "food_zh"],
        "QUA",
    )
    stats["quarantined_rows"] = {"rows": write("quarantined_rows.csv", rows,
        ["record_id", "standard", "version_year", "analyte_zh", "additive_zh", "food_code",
         "food_zh", "parsed_value", "unit", "reject_reason", "raw_text", "source_path"]),
        "exact_dups_removed": nx}

    # ---------- 11. 双语实体名册 ----------
    # 仅发布标准原文中的英文名或项目内经核对的有限指标对照；不生成机器译名。
    entities = {}
    for r in read("pesticide_limits_long.csv", base=REL):
        if r.get("pesticide_zh") and r.get("pesticide_en"):
            key = ("pesticide", r["pesticide_key"])
            candidate = {
                "entity_key": r["pesticide_key"],
                "entity_type": "pesticide",
                "name_zh": r["pesticide_zh"],
                "name_en": r["pesticide_en"],
                "source_standard": "GB 2763",
                "version_year": r["version_year"],
            }
            if key not in entities or candidate["version_year"] > entities[key]["version_year"]:
                entities[key] = candidate
    for r in read("vetdrug_limits_long.csv", base=REL):
        if r.get("drug_zh") and r.get("drug_en"):
            entity_key = lookup_entity_key("VDR", r["drug_en"])
            key = ("veterinary_drug", entity_key)
            candidate = {
                "entity_key": entity_key,
                "entity_type": "veterinary_drug",
                "name_zh": r["drug_zh"],
                "name_en": r["drug_en"],
                "source_standard": r["standard"],
                "version_year": r["version_year"],
            }
            if key not in entities or candidate["version_year"] > entities[key]["version_year"]:
                entities[key] = candidate
    for candidate in build_analyte_lookup_entities(
        read("pollutant_limits_long.csv", base=REL),
        read("mycotoxin_limits_long.csv", base=REL),
    ):
        key = (candidate["entity_type"], candidate["entity_key"])
        entities[key] = candidate
    entity_rows = sorted(
        entities.values(), key=lambda row: (row["entity_type"], row["entity_key"])
    )
    entity_rows, nx, nc = dedup_and_id(
        entity_rows, ["entity_type", "entity_key"], "ENT"
    )
    stats["entity_names_en"] = {"rows": write("entity_names_en.csv", entity_rows,
        ["record_id", "entity_key", "entity_type", "name_zh", "name_en",
         "source_standard"]),
        "exact_dups_removed": nx}

    # 12. 覆盖版本日期：保留 21 个 edition_source 身份及明确的空日期。
    version_dates = read("coverage_version_dates.csv", base=DATE_DIR)
    if len(version_dates) != 21:
        raise ValueError(
            f"coverage version-date interface must contain 21 rows, got {len(version_dates)}"
        )
    if len({(row["standard"], row["version_year"]) for row in version_dates}) != 21:
        raise ValueError("coverage version-date interface has duplicate edition identities")
    stats["version_dates"] = {
        "rows": write(
            "version_dates.csv",
            version_dates,
            [
                "record_id",
                "source_id",
                "family",
                "standard",
                "version_year",
                "issue_date",
                "effective_date",
                "date_source",
                "official_register_issue_date",
                "official_register_effective_date",
                "cross_check_official_register",
                "date_status",
                "date_resolution",
                "source_filename",
            ],
        ),
        "exact_dups_removed": 0,
    }

    with open(os.path.join(REL, "_build_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"发布包 → {REL}\n")
    for k, v in stats.items():
        extra = ""
        if v.get("exact_dups_removed"):
            extra += f"  去重 -{v['exact_dups_removed']}"
        if v.get("rows_with_conflicting_key"):
            extra += f"  同键多值 {v['rows_with_conflicting_key']} 行(已标 conflict=1)"
        print(f"  {k:28s} {v['rows']:6d} 行{extra}")


if __name__ == "__main__":
    main()
