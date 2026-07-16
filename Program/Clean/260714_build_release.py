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
import json
import os
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
    build_vetdrug_summary_panel,
    food_entity_id,
    panel_columns,
    pesticide_entity_id,
)
from source_manifest_utils import source_ids_by_edition

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
    columns.extend(["n_versions", "trend"])
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


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", default=REL)
    parser.add_argument("--additive-interim", default=ADD_INTERIM)
    parser.add_argument("--pollutant-interim", default=POLLUTANT_INTERIM)
    parser.add_argument("--pesticide-interim", default=PESTICIDE_INTERIM)
    parser.add_argument("--mycotoxin-interim", default=MYCOTOXIN_INTERIM)
    parser.add_argument("--vetdrug-interim", default=VETDRUG_INTERIM)
    parser.add_argument("--dependency-interim", default=DEPENDENCY_INTERIM)
    parser.add_argument("--timeline-dir", default=TIMELINE)
    parser.add_argument("--date-dir", default=DATE_DIR)
    return parser.parse_args(argv)


def main(argv=None):
    global ADD_INTERIM, DATE_DIR, DEPENDENCY_INTERIM, MYCOTOXIN_INTERIM
    global PESTICIDE_INTERIM, POLLUTANT_INTERIM, REL, TIMELINE, VETDRUG_INTERIM

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
    stats["pollutant_limits"] = {"rows": write("pollutant_limits_long.csv", rows,
        ["record_id", "standard", "version_year", "analyte_zh", "analyte_en", "food_category_zh",
         "limit_value", "unit", "limit_mgkg", "normalization_status", "limit_basis", "note",
         "confidence", "extraction_path", "edition_source_id", "extraction_source_id",
         "conflict"]),
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
    stats["pollutant_category_panel"] = {"rows": write("pollutant_category_panel.csv", rows,
        ["record_id", "standard", "analyte_zh", "analyte_en", "food_category_zh",
         "v2012", "v2017", "v2022", "v2025",
         "unit_2012", "unit_2017", "unit_2022", "unit_2025",
         "basis_2012", "basis_2017", "basis_2022", "basis_2025",
         "cell_status_2012", "cell_status_2017", "cell_status_2022", "cell_status_2025",
         "source_category_2012", "source_category_2017", "source_category_2022",
         "source_category_2025", "unit_summary", "n_versions", "coverage_status", "trend"]),
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
    stats["pollutant_member_panel"] = {"rows": write("pollutant_member_panel.csv", rows,
        ["record_id", "standard", "analyte_zh", "analyte_en", "food_member_zh",
         "v2012", "v2017", "v2022", "v2025",
         "unit_2012", "unit_2017", "unit_2022", "unit_2025",
         "basis_2012", "basis_2017", "basis_2022", "basis_2025",
         "limit_basis", "trend", "category_restructured",
         "host_category_2012", "host_category_2017", "host_category_2022", "host_category_2025", "note"]),
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
    stats["pesticide_limits"] = {"rows": write("pesticide_limits_long.csv", rows,
        ["record_id", "standard", "version_year", "section_number",
         "pesticide_key", "pesticide_zh", "pesticide_en", "pesticide_zh_raw",
         "pesticide_en_raw", "parent_category_zh", "parent_category_raw",
         "food_key", "food_zh", "food_raw", "limit_value", "unit",
         "limit_qualifier", "is_temporary", "value_raw", "source_page", "source_y",
         "food_x", "parent_assignment_method", "table_open_method", "review_status",
         "edition_source_id", "extraction_source_id", "source_copy_role", "conflict"]),
        "exact_dups_removed": 0, "rows_with_conflicting_key": nc}

    rows = build_pesticide_panel_v2(rows)
    rows, nx, nc = preserve_rules_and_id(
        rows,
        ["pesticide_key", "food_key"],
        ["pesticide_key", "food_key"],
        "PSP",
    )
    stats["pesticide_panel"] = {"rows": write("pesticide_panel.csv", rows,
        pesticide_panel_output_columns()),
        "exact_dups_removed": nx}

    with open(
        os.path.join(PESTICIDE_INTERIM, "pesticide_textlayer_extraction_report.json"),
        encoding="utf-8",
    ) as handle:
        pesticide_report = json.load(handle)
    if pesticide_report.get("validation_passed") is not True:
        raise ValueError("pesticide text-layer report did not pass validation gates")
    reconciliation_rows = pesticide_reconciliation_rows(pesticide_report)
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
    ocr_crosscheck = read(
        "pesticide_textlayer_ocr_crosscheck.csv", base=PESTICIDE_INTERIM
    )
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
    stats["mycotoxin_limits"] = {"rows": write("mycotoxin_limits_long.csv", rows,
        ["record_id", "standard", "version_year", "toxin_zh", "toxin_en", "food_category_zh",
         "limit_value", "unit", "confidence", "edition_source_id", "extraction_source_id",
         "conflict"]), "exact_dups_removed": nx}

    rows = []
    for r in read("mycotoxin_strictness_change.csv", base=MYCOTOXIN_INTERIM):
        rows.append({
            "standard": "GB 2761", "toxin_zh": r["toxin"], "toxin_en": ANALYTE_EN.get(r["toxin"], ""),
            "food_zh": r["food_canon"], "v2005": r["v2005"], "v2011": r["v2011"], "v2017": r["v2017"],
            "unit": "μg/kg", "trend": coded(r["trend"], TREND_CODES, "trend"),
            "note": r.get("note2005", ""),
        })
    rows, nx, nc = dedup_and_id(rows, ["toxin_zh", "food_zh"], "MSP")
    stats["mycotoxin_panel"] = {"rows": write("mycotoxin_panel.csv", rows,
        ["record_id", "standard", "toxin_zh", "toxin_en", "food_zh",
         "v2005", "v2011", "v2017", "unit", "trend", "note"]), "exact_dups_removed": nx}

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
    stats["vetdrug_limits"] = {"rows": write("vetdrug_limits_long.csv", rows,
        ["record_id", "standard", "version_year", "drug_zh", "drug_en", "animal", "animal_raw",
         "tissue_zh", "limit_value", "unit", "source", "source_table_index",
         "source_table_row", "animal_block_index", "tissue_index", "edition_source_id",
         "extraction_source_id", "conflict"]),
        "exact_dups_removed": nx, "rows_with_conflicting_key": nc}

    rows = build_vetdrug_summary_panel(
        read("vetdrug_limits_long.csv", base=REL)
    )
    rows, nx, nc = dedup_and_id(rows, ["drug_en", "tissue_zh"], "VSP")
    stats["vetdrug_panel"] = {"rows": write("vetdrug_panel.csv", rows,
        ["record_id", "standard", "drug_zh", "drug_en", "tissue_zh",
         "v2002", "v2019", "unit", "trend"]), "exact_dups_removed": nx}

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
    stats["additive_limits"] = {"rows": write("additive_limits_long.csv", rows,
        ["record_id", "standard", "version_year", "additive_zh", "cns_code", "ins_code", "food_code",
         "food_zh", "max_use", "unit", "note", "edition_source_id",
         "extraction_source_id", "conflict"]),
        "exact_dups_removed": nx, "rows_with_conflicting_key": nc}

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
    for r in dependency_rows["member_crosswalk_vetdrug.csv"]:
        rows.append({
            "standard": "GB 31650", "drug_zh": r["drug"], "drug_en": r["english"],
            "animal": r["animal"], "tissue_zh": r["tissue"],
            "v2002": r["v2002"], "v2019": r["v2019"], "v2022": r["v2022"],
            "unit": "mg/kg", "trend": coded(r["trend"], TREND_CODES, "trend"),
        })
    rows, nx, nc = dedup_and_id(rows, ["drug_en", "animal", "tissue_zh"], "VMP")
    stats["vetdrug_member_panel"] = {"rows": write("vetdrug_member_panel.csv", rows,
        ["record_id", "standard", "drug_zh", "drug_en", "animal", "tissue_zh",
         "v2002", "v2019", "v2022", "unit", "trend"]), "exact_dups_removed": nx}

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
    stats["mycotoxin_member_panel"] = {"rows": write("mycotoxin_member_panel.csv", rows,
        ["record_id", "standard", "toxin_zh", "food_member_zh", "v2005", "v2011", "v2017",
         "unit", "trend", "category_restructured",
         "host_category_2005", "host_category_2011", "host_category_2017"]),
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
