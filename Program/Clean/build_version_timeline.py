#!/usr/bin/env python3
"""构建标准版本沿革时间线。

数据源（0 次 PDF 内容解析）：
  1) ``--catalog-csv`` 提供 GB 标准版本目录；
  2) ``--official-xlsx`` 提供发布日期、实施日期和官方分类；
  3) ``--anchor-dir`` 界定卫健委分类目录中的 GB 号范围；
  4) 可选 ``--coverage-manifest`` 用 ``edition_source`` 身份补入数据集已覆盖、
     但目录或锚定范围遗漏的版本事件；
  5) 可选 ``--date-corrections-csv`` 以官方原文证据、旧值和 SHA-256
     绑定修正官方清单导出中已核实的日期错误。

覆盖清单只用于来源身份与版本覆盖补充，脚本不读取发布数据的限量值。
``identity_audit_copy`` 不会生成版本事件。已确认为“误命名为修改单的全文”
的本地附件不参与目录回退；官方清单仍可独立建立真实的修改单事件。

输出（UTF-8-BOM）：
  standard_versions_long.csv  一行 = 一个正式版或修改单事件
  standard_timeline.csv       一行 = 一个标准身份的版本沿革汇总
  standard_timeline_conflicts.csv  同键正式版元数据冲突审计
  coverage_version_dates.csv  可选；一行 = 覆盖清单中的一个 edition_source
"""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

import openpyxl


PAT = re.compile(r"GB\s*([0-9]+(?:\.[0-9]+)*)\s*[-—–]\s*(\d{4})")
GB_STANDARD = re.compile(r"^GB\s+([0-9]+(?:\.[0-9]+)*)$")
MOA_STANDARD = re.compile(r"^MOA Announcement\s+(\d+)$")
AMENDMENT_NUMBER = re.compile(r"第(\d+)号")

MANIFEST_REQUIRED_COLUMNS = {
    "source_id",
    "family",
    "standard",
    "version_year",
    "source_role",
    "release_status",
    "source_filename",
    "document_identity",
}

COVER_DATE_REQUIRED_COLUMNS = {
    "number",
    "version_year",
    "issue_date",
    "effective_date",
    "date_source",
    "cross_check_official_register",
}

DATE_CORRECTION_REQUIRED_COLUMNS = {
    "standard",
    "version_year",
    "event_type",
    "observed_issue_date",
    "observed_effective_date",
    "corrected_issue_date",
    "corrected_effective_date",
    "evidence_url",
    "evidence_file",
    "evidence_sha256",
    "verification_note",
}

DATE_CORRECTION_EVENT_TYPES = {"official_version", "amendment"}

FROZEN_LONG_COLUMNS = [
    "std_id",
    "number",
    "event_type",
    "year",
    "amend_no",
    "发布日期",
    "实施日期",
    "卫健委类目",
    "官方分类",
    "title",
    "在新目录",
    "path",
]

FROZEN_WIDE_COLUMNS = [
    "std_id",
    "title",
    "卫健委类目",
    "n_正式版本",
    "版本年份",
    "首版年",
    "现行版年",
    "现行版发布日期",
    "现行版实施日期",
    "n_修改单",
    "修改单年份",
    "有历史沿革",
]

COVERAGE_DATE_COLUMNS = [
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
]

FAMILY_CATEGORIES = {
    "contaminant": "污染物限量",
    "pesticide": "农药残留限量",
    "mycotoxin": "真菌毒素限量",
    "veterinary_drug": "兽药残留限量",
    "additive": "食品添加剂",
}

CONFLICT_COLUMNS = [
    "conflict_id",
    "std_id",
    "number",
    "version_year",
    "conflict_type",
    "candidate_rank",
    "selected",
    "equivalent_row_count",
    "timeline_title_match",
    "anchor_category_match",
    "issue_date",
    "effective_date",
    "official_category",
    "title_zh",
    "normalized_title",
    "timeline_title",
    "anchor_category",
    "raw_titles",
    "selection_reason",
]


def d10(value: object) -> str:
    """日期规整为 YYYY-MM-DD 文本。"""
    if value is None:
        return ""
    return str(value)[:10]


def normalize_text(value: str) -> str:
    """统一 Unicode 与空白，用于身份比较和稳定排序。"""
    return " ".join(unicodedata.normalize("NFKC", value).split())


def portable_locator(value: str) -> str:
    """将目录路径收敛为不泄漏本机目录的文件名定位符。"""
    return normalize_text(value.replace("\\", "/").rsplit("/", maxsplit=1)[-1])


def normalize_cover_date_source(value: str) -> str:
    """将封面日期读取方式规整为发布接口使用的稳定枚举。"""
    normalized = normalize_text(value)
    if normalized.startswith("cover "):
        return normalized.removeprefix("cover ")
    if normalized == "no date on cover":
        return "not printed"
    return normalized


def clean_title(value: str) -> str:
    """去掉通用前缀，保留标准的中文标题。"""
    without_prefix = value.replace("食品安全国家标准", "").strip(" 《》-_")
    return normalize_text(without_prefix)


def standard_number(standard: str) -> str:
    """从受支持的标准身份中取出数字组件。"""
    match = GB_STANDARD.fullmatch(standard)
    if match:
        return match.group(1)
    match = MOA_STANDARD.fullmatch(standard)
    if match:
        return match.group(1)
    raise ValueError(f"unsupported standard identity in coverage manifest: {standard!r}")


def standard_sort_key(standard: str) -> tuple[object, ...]:
    """为 GB 与农业部公告身份生成稳定排序键。"""
    match = GB_STANDARD.fullmatch(standard)
    if match:
        components = tuple(int(part) for part in match.group(1).split("."))
        return (0, components, standard)
    match = MOA_STANDARD.fullmatch(standard)
    if match:
        return (1, (int(match.group(1)),), standard)
    return (2, (), standard)


def title_from_manifest(row: dict[str, str]) -> str:
    """从可移植文件名生成回退标题。"""
    stem = Path(row["source_filename"]).stem.strip()
    year = row["version_year"]
    if year in stem:
        stem = stem.split(year, maxsplit=1)[1].lstrip(" -_—–")
    return clean_title(stem) or row["standard"]


def load_coverage_manifest(
    path: Path | None,
) -> tuple[dict[tuple[str, str], dict[str, str]], set[tuple[str, str]]]:
    """读取覆盖身份，并返回已审计的误命名附件键。"""
    if path is None:
        return {}, set()
    if not path.is_file():
        raise FileNotFoundError(f"coverage manifest does not exist: {path}")

    editions: dict[tuple[str, str], dict[str, str]] = {}
    misnamed_copy_keys: set[tuple[str, str]] = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = MANIFEST_REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                "coverage manifest is missing required columns: "
                + ", ".join(sorted(missing))
            )
        for line_number, source_row in enumerate(reader, start=2):
            row = {key: (value or "").strip() for key, value in source_row.items()}
            standard = row["standard"]
            year = row["version_year"]
            if not re.fullmatch(r"\d{4}", year):
                raise ValueError(
                    f"invalid version_year at coverage manifest line {line_number}: {year!r}"
                )
            standard_number(standard)
            key = (standard, year)
            role = row["source_role"]
            if role == "edition_source":
                if key in editions:
                    raise ValueError(
                        "duplicate edition_source identity in coverage manifest: "
                        f"{standard} {year}"
                    )
                editions[key] = row
            elif (
                role == "identity_audit_copy"
                and row["document_identity"]
                == "full_standard_text_misnamed_as_amendment"
            ):
                misnamed_copy_keys.add(key)
    return editions, misnamed_copy_keys


def load_cover_dates(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    """读取封面日期表，并对覆盖身份键、日期成对性做封闭校验。"""
    if not path.is_file():
        raise FileNotFoundError(f"cover-date CSV does not exist: {path}")

    rows: dict[tuple[str, str], dict[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = COVER_DATE_REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                "cover-date CSV is missing required columns: "
                + ", ".join(sorted(missing))
            )
        for line_number, source_row in enumerate(reader, start=2):
            row = {key: (value or "").strip() for key, value in source_row.items()}
            standard = row["number"]
            year = row["version_year"]
            standard_number(standard)
            if not re.fullmatch(r"\d{4}", year):
                raise ValueError(
                    f"invalid version_year at cover-date line {line_number}: {year!r}"
                )
            key = (standard, year)
            if key in rows:
                raise ValueError(
                    "duplicate edition identity in cover-date CSV: "
                    f"{standard} {year}"
                )
            if bool(row["issue_date"]) != bool(row["effective_date"]):
                raise ValueError(
                    "cover-date issue/effective dates must be both filled or both blank: "
                    f"{standard} {year}"
                )
            rows[key] = row
    return rows


def parse_iso_date(value: str, *, context: str) -> date:
    """解析严格 ISO 日期，拒绝模糊或无效值。"""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{context} must use YYYY-MM-DD: {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{context} is not a valid calendar date: {value!r}") from error


def load_date_corrections(
    path: Path | None,
) -> dict[tuple[str, str, str], dict[str, str]]:
    """读取有旧值和官方原文证据绑定的日期修正。"""
    if path is None:
        return {}
    if not path.is_file():
        raise FileNotFoundError(f"date-correction CSV does not exist: {path}")

    corrections: dict[tuple[str, str, str], dict[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = DATE_CORRECTION_REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                "date-correction CSV is missing required columns: "
                + ", ".join(sorted(missing))
            )
        for line_number, source_row in enumerate(reader, start=2):
            row = {key: (value or "").strip() for key, value in source_row.items()}
            standard = row["standard"]
            year = row["version_year"]
            event_type = row["event_type"]
            standard_number(standard)
            if not re.fullmatch(r"\d{4}", year):
                raise ValueError(
                    f"invalid version_year at date-correction line {line_number}: "
                    f"{year!r}"
                )
            if event_type not in DATE_CORRECTION_EVENT_TYPES:
                raise ValueError(
                    f"invalid event_type at date-correction line {line_number}: "
                    f"{event_type!r}"
                )
            for column in (
                "observed_issue_date",
                "observed_effective_date",
                "corrected_issue_date",
                "corrected_effective_date",
            ):
                parse_iso_date(
                    row[column],
                    context=f"date-correction line {line_number} {column}",
                )
            if row["corrected_issue_date"] > row["corrected_effective_date"]:
                raise ValueError(
                    "corrected issue date is later than effective date at "
                    f"date-correction line {line_number}"
                )
            if not row["evidence_url"].startswith("https://"):
                raise ValueError(
                    "date-correction evidence_url must use HTTPS at line "
                    f"{line_number}"
                )
            if not row["evidence_file"] or not row["verification_note"]:
                raise ValueError(
                    "date-correction evidence_file and verification_note must be "
                    f"filled at line {line_number}"
                )
            if not re.fullmatch(r"[0-9a-f]{64}", row["evidence_sha256"]):
                raise ValueError(
                    "date-correction evidence_sha256 must be lowercase SHA-256 at "
                    f"line {line_number}"
                )
            key = (standard, year, event_type)
            if key in corrections:
                raise ValueError(f"duplicate date-correction identity: {key}")
            corrections[key] = row
    return corrections


def apply_date_corrections(
    corrections: dict[tuple[str, str, str], dict[str, str]],
    official_versions: dict[tuple[str, str], list[dict[str, str]]],
    official_amendments: dict[tuple[str, str], list[dict[str, str]]],
    version_scope: set[tuple[str, str]],
) -> int:
    """在解冲突前修正与旧值精确匹配的官方清单记录。"""
    applied = 0
    for (standard, year, event_type), correction in sorted(corrections.items()):
        identity = (standard, year)
        if identity not in version_scope:
            raise ValueError(
                "date correction targets an identity outside the timeline scope: "
                f"{standard} {year}"
            )
        target = (
            official_versions if event_type == "official_version" else official_amendments
        )
        observed_pair = (
            correction["observed_issue_date"],
            correction["observed_effective_date"],
        )
        matches = [
            row
            for row in target.get(identity, [])
            if (row["发布日期"], row["实施日期"]) == observed_pair
        ]
        if not matches:
            available_pairs = sorted(
                {
                    (row["发布日期"], row["实施日期"])
                    for row in target.get(identity, [])
                }
            )
            raise ValueError(
                "date correction no longer matches the declared observed values for "
                f"{standard} {year} {event_type}: expected={observed_pair}, "
                f"available={available_pairs}"
            )
        for row in matches:
            row["发布日期"] = correction["corrected_issue_date"]
            row["实施日期"] = correction["corrected_effective_date"]
        applied += 1
    return applied


def validate_event_date_chronology(rows: list[dict[str, object]]) -> None:
    """在写出前保证所有时间线事件的日期成对且有序。"""
    for row in rows:
        issue_date = str(row["发布日期"])
        effective_date = str(row["实施日期"])
        identity = (
            f"{row['std_id']} {row['year']} {row['event_type']} "
            f"{row['amend_no']}"
        ).strip()
        if bool(issue_date) != bool(effective_date):
            raise ValueError(
                f"timeline event has a partial date pair for {identity}: "
                f"issue={issue_date!r}, effective={effective_date!r}"
            )
        if not issue_date:
            continue
        issue = parse_iso_date(issue_date, context=f"{identity} issue date")
        effective = parse_iso_date(
            effective_date, context=f"{identity} effective date"
        )
        if issue > effective:
            raise ValueError(
                f"timeline issue date is later than effective date for {identity}: "
                f"issue={issue_date}, effective={effective_date}"
            )


def read_frozen_csv(path: Path, expected_columns: list[str]) -> list[dict[str, str]]:
    """读取冻结时间线表并锁定表头。"""
    if not path.is_file():
        raise FileNotFoundError(f"frozen timeline CSV does not exist: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if list(reader.fieldnames or []) != expected_columns:
            raise ValueError(
                f"unexpected frozen timeline header for {path.name}: "
                f"{reader.fieldnames}"
            )
        return [
            {key: (value or "") for key, value in source_row.items()}
            for source_row in reader
        ]


def replay_frozen_date_corrections(
    input_dir: Path,
    output_dir: Path,
    corrections: dict[tuple[str, str, str], dict[str, str]],
) -> int:
    """对冻结长表和宽表做旧值绑定的可重放日期修正。"""
    if not corrections:
        raise ValueError("frozen correction replay requires at least one correction")
    long_rows = read_frozen_csv(
        input_dir / "standard_versions_long.csv", FROZEN_LONG_COLUMNS
    )
    wide_rows = read_frozen_csv(
        input_dir / "standard_timeline.csv", FROZEN_WIDE_COLUMNS
    )
    wide_by_standard: dict[str, dict[str, str]] = {}
    for row in wide_rows:
        standard = row["std_id"]
        if standard in wide_by_standard:
            raise ValueError(f"duplicate frozen wide timeline identity: {standard}")
        wide_by_standard[standard] = row

    event_labels = {"official_version": "正式版", "amendment": "修改单"}
    for (standard, year, event_type), correction in sorted(corrections.items()):
        observed_pair = (
            correction["observed_issue_date"],
            correction["observed_effective_date"],
        )
        identity_rows = [
            row
            for row in long_rows
            if row["std_id"] == standard
            and row["year"] == year
            and row["event_type"] == event_labels[event_type]
        ]
        matches = [
            row
            for row in identity_rows
            if (row["发布日期"], row["实施日期"]) == observed_pair
        ]
        if len(matches) != 1:
            available_pairs = sorted(
                {(row["发布日期"], row["实施日期"]) for row in identity_rows}
            )
            raise ValueError(
                "frozen date correction must match exactly one declared old value "
                f"for {standard} {year} {event_type}: matches={len(matches)}, "
                f"expected={observed_pair}, available={available_pairs}"
            )
        matches[0]["发布日期"] = correction["corrected_issue_date"]
        matches[0]["实施日期"] = correction["corrected_effective_date"]

        wide_row = wide_by_standard.get(standard)
        if wide_row is None:
            raise ValueError(f"frozen wide timeline is missing {standard}")
        if event_type == "official_version" and wide_row["现行版年"] == year:
            wide_observed_pair = (
                wide_row["现行版发布日期"],
                wide_row["现行版实施日期"],
            )
            if wide_observed_pair != observed_pair:
                raise ValueError(
                    "frozen wide timeline no longer matches the declared old values "
                    f"for {standard} {year}: expected={observed_pair}, "
                    f"available={wide_observed_pair}"
                )
            wide_row["现行版发布日期"] = correction["corrected_issue_date"]
            wide_row["现行版实施日期"] = correction["corrected_effective_date"]

    validate_event_date_chronology(long_rows)
    formal_by_standard: dict[str, list[dict[str, str]]] = defaultdict(list)
    long_standards: set[str] = set()
    for row in long_rows:
        long_standards.add(row["std_id"])
        if row["event_type"] == "正式版":
            formal_by_standard[row["std_id"]].append(row)
    if long_standards != set(wide_by_standard):
        raise ValueError(
            "frozen long/wide standard identities differ: "
            f"long_only={sorted(long_standards - set(wide_by_standard))}, "
            f"wide_only={sorted(set(wide_by_standard) - long_standards)}"
        )
    for standard, wide_row in wide_by_standard.items():
        rows = formal_by_standard.get(standard, [])
        if not rows:
            actual = (
                wide_row["n_正式版本"],
                wide_row["现行版年"],
                wide_row["现行版发布日期"],
                wide_row["现行版实施日期"],
            )
            if actual != ("0", "", "", ""):
                raise ValueError(
                    "frozen amendment-only wide timeline has formal-version "
                    f"metadata for {standard}: {actual}"
                )
            continue
        latest = max(rows, key=lambda row: int(row["year"]))
        actual = (
            wide_row["现行版年"],
            wide_row["现行版发布日期"],
            wide_row["现行版实施日期"],
        )
        expected = (latest["year"], latest["发布日期"], latest["实施日期"])
        if actual != expected:
            raise ValueError(
                f"frozen wide timeline disagrees with latest formal event for "
                f"{standard}: expected={expected}, actual={actual}"
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    prepared: list[tuple[Path, Path]] = []
    for filename, columns, rows in (
        ("standard_versions_long.csv", FROZEN_LONG_COLUMNS, long_rows),
        ("standard_timeline.csv", FROZEN_WIDE_COLUMNS, wide_rows),
    ):
        target = output_dir / filename
        temporary = output_dir / f".{filename}.correction-replay.tmp"
        with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=columns, lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(rows)
        prepared.append((temporary, target))
    for temporary, target in prepared:
        temporary.replace(target)
    print(f"冻结时间线日期修正 {len(corrections)} 项 → {output_dir}")
    return 0


def build_coverage_date_rows(
    manifest_editions: dict[tuple[str, str], dict[str, str]],
    cover_dates: dict[tuple[str, str], dict[str, str]],
    long_rows: list[dict[str, object]],
) -> list[dict[str, str]]:
    """合并封面日期与官方登记日期，保留覆盖清单的全部版本身份。"""
    if not manifest_editions:
        raise ValueError(
            "--cover-dates-csv requires --coverage-manifest with edition_source rows"
        )

    manifest_keys = set(manifest_editions)
    cover_keys = set(cover_dates)
    if manifest_keys != cover_keys:
        missing = sorted(manifest_keys - cover_keys)
        extra = sorted(cover_keys - manifest_keys)
        raise ValueError(
            "cover-date identities must exactly match manifest edition_source rows; "
            f"missing={missing}, extra={extra}"
        )

    timeline_editions = {
        (str(row["std_id"]), str(row["year"])): row
        for row in long_rows
        if row["event_type"] == "正式版"
    }
    missing_timeline = sorted(manifest_keys - set(timeline_editions))
    if missing_timeline:
        raise ValueError(
            "timeline is missing manifest edition_source identities: "
            f"{missing_timeline}"
        )

    output_rows: list[dict[str, str]] = []
    ordered_editions = sorted(
        manifest_editions.items(),
        key=lambda item: (item[1]["source_id"], item[0]),
    )
    for index, (key, manifest_row) in enumerate(ordered_editions, start=1):
        cover_row = cover_dates[key]
        timeline_row = timeline_editions[key]
        cover_pair = (cover_row["issue_date"], cover_row["effective_date"])
        official_pair = (
            str(timeline_row["发布日期"]),
            str(timeline_row["实施日期"]),
        )
        if any(official_pair) and cover_pair != official_pair:
            raise ValueError(
                "cover-date and official-register dates conflict for "
                f"{key[0]} {key[1]}: cover={cover_pair}, official={official_pair}"
            )

        if not any(cover_pair):
            date_status = "not_printed"
            date_resolution = "not_printed_on_cover_and_absent_from_register"
        elif any(official_pair):
            date_status = "complete"
            date_resolution = "cover_and_official_register_agree"
        else:
            date_status = "complete"
            date_resolution = "source_document_only"

        output_rows.append(
            {
                "record_id": f"VER{index:05d}",
                "source_id": manifest_row["source_id"],
                "family": manifest_row["family"],
                "standard": key[0],
                "version_year": key[1],
                "issue_date": cover_pair[0],
                "effective_date": cover_pair[1],
                "date_source": normalize_cover_date_source(
                    cover_row["date_source"]
                ),
                "official_register_issue_date": official_pair[0],
                "official_register_effective_date": official_pair[1],
                "cross_check_official_register": (
                    "agrees" if any(official_pair) else ""
                ),
                "date_status": date_status,
                "date_resolution": date_resolution,
                "source_filename": portable_locator(manifest_row["source_filename"]),
            }
        )
    return output_rows


def official_metadata_key(record: dict[str, str]) -> tuple[str, str, str, str]:
    """官方正式版元数据的等价判定键。"""
    return (
        clean_title(record["名称"]),
        record["发布日期"],
        record["实施日期"],
        normalize_text(record["官方分类"]),
    )


def resolve_official_version_candidates(
    candidates: dict[tuple[str, str], list[dict[str, str]]],
    versions: dict[str, dict[str, dict[str, object]]],
    category_of: dict[tuple[str, str], str],
) -> tuple[
    dict[tuple[str, str], dict[str, str]],
    list[dict[str, object]],
]:
    """合并等价重复，并将真冲突以稳定排名与审计行解决。"""
    resolved: dict[tuple[str, str], dict[str, str]] = {}
    audit_rows: list[dict[str, object]] = []
    conflict_index = 0

    ordered_keys = sorted(
        candidates,
        key=lambda key: (standard_sort_key(key[0]), int(key[1])),
    )
    for standard, year in ordered_keys:
        if year not in versions.get(standard, {}):
            continue
        grouped: dict[tuple[str, str, str, str], list[dict[str, str]]] = (
            defaultdict(list)
        )
        for record in candidates[(standard, year)]:
            grouped[official_metadata_key(record)].append(record)

        canonical_groups: list[dict[str, object]] = []
        for canonical_key, records in sorted(grouped.items()):
            representative = min(
                records,
                key=lambda record: tuple(
                    normalize_text(record[column])
                    for column in ("名称", "发布日期", "实施日期", "官方分类")
                ),
            )
            canonical_groups.append(
                {
                    "canonical_key": canonical_key,
                    "records": records,
                    "representative": representative,
                }
            )

        if len(canonical_groups) == 1:
            resolved[(standard, year)] = canonical_groups[0]["representative"]
            continue

        timeline_title = clean_title(str(versions[standard][year]["title"]))
        anchor_category = normalize_text(category_of.get((standard, year), ""))

        def selection_key(group: dict[str, object]) -> tuple[object, ...]:
            normalized_title, issue_date, effective_date, official_category = group[
                "canonical_key"
            ]
            metadata_completeness = sum(
                bool(value)
                for value in (
                    normalized_title,
                    issue_date,
                    effective_date,
                    official_category,
                )
            )
            return (
                normalized_title != timeline_title,
                bool(anchor_category) and official_category != anchor_category,
                -metadata_completeness,
                normalized_title,
                issue_date,
                effective_date,
                official_category,
            )

        ranked = sorted(canonical_groups, key=selection_key)
        resolved[(standard, year)] = ranked[0]["representative"]
        conflict_index += 1
        conflict_id = f"TLC{conflict_index:04d}"
        reason_basis = (
            "stable_rank: timeline_title_match, anchor_category_match, "
            "metadata_completeness, lexical_metadata"
        )
        for rank, group in enumerate(ranked, start=1):
            normalized_title, issue_date, effective_date, official_category = group[
                "canonical_key"
            ]
            selected = rank == 1
            records = group["records"]
            representative = group["representative"]
            audit_rows.append(
                {
                    "conflict_id": conflict_id,
                    "std_id": standard,
                    "number": standard_number(standard),
                    "version_year": year,
                    "conflict_type": "official_version_metadata_conflict",
                    "candidate_rank": rank,
                    "selected": int(selected),
                    "equivalent_row_count": len(records),
                    "timeline_title_match": int(normalized_title == timeline_title),
                    "anchor_category_match": int(
                        bool(anchor_category)
                        and official_category == anchor_category
                    ),
                    "issue_date": issue_date,
                    "effective_date": effective_date,
                    "official_category": official_category,
                    "title_zh": representative["名称"],
                    "normalized_title": normalized_title,
                    "timeline_title": timeline_title,
                    "anchor_category": anchor_category,
                    "raw_titles": " | ".join(
                        sorted({record["名称"] for record in records})
                    ),
                    "selection_reason": (
                        "selected_by_" if selected else "rejected_by_"
                    )
                    + reason_basis,
                }
            )

    return resolved, audit_rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the standard-version timeline from explicit source paths.",
    )
    parser.add_argument(
        "--catalog-csv",
        type=Path,
        help="Standards catalog CSV containing code, number, year, title, and path.",
    )
    parser.add_argument(
        "--official-xlsx",
        type=Path,
        help="Official standards workbook containing the 全量汇总 worksheet.",
    )
    parser.add_argument(
        "--anchor-dir",
        type=Path,
        help="Categorized PDF directory whose GB numbers define the base scope.",
    )
    parser.add_argument(
        "--coverage-manifest",
        type=Path,
        help=(
            "Optional source_manifest.csv whose edition_source rows supplement "
            "catalogue coverage and whose identity audits exclude misnamed copies."
        ),
    )
    parser.add_argument(
        "--cover-dates-csv",
        type=Path,
        help=(
            "Optional cover-date CSV. Requires --coverage-manifest and writes a "
            "coverage-complete, reconciled coverage_version_dates.csv."
        ),
    )
    parser.add_argument(
        "--date-corrections-csv",
        type=Path,
        help=(
            "Optional source-backed corrections for verified date errors in the "
            "official-register export."
        ),
    )
    parser.add_argument(
        "--frozen-input-dir",
        type=Path,
        help=(
            "Replay verified corrections against frozen standard_versions_long.csv "
            "and standard_timeline.csv without rebuilding from the broad source tree."
        ),
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help=(
            "Directory receiving the long timeline, wide timeline, and metadata-"
            "conflict audit CSV files."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = args.output_dir.expanduser()
    date_corrections_csv = (
        args.date_corrections_csv.expanduser()
        if args.date_corrections_csv
        else None
    )
    date_corrections = load_date_corrections(date_corrections_csv)
    if args.frozen_input_dir:
        forbidden_raw_inputs = {
            "--catalog-csv": args.catalog_csv,
            "--official-xlsx": args.official_xlsx,
            "--anchor-dir": args.anchor_dir,
            "--coverage-manifest": args.coverage_manifest,
            "--cover-dates-csv": args.cover_dates_csv,
        }
        supplied = sorted(
            name for name, value in forbidden_raw_inputs.items() if value is not None
        )
        if supplied:
            raise ValueError(
                "--frozen-input-dir cannot be combined with broad-source inputs: "
                + ", ".join(supplied)
            )
        return replay_frozen_date_corrections(
            args.frozen_input_dir.expanduser(), output_dir, date_corrections
        )

    missing_raw_inputs = [
        name
        for name, value in (
            ("--catalog-csv", args.catalog_csv),
            ("--official-xlsx", args.official_xlsx),
            ("--anchor-dir", args.anchor_dir),
        )
        if value is None
    ]
    if missing_raw_inputs:
        raise ValueError(
            "broad-source rebuild requires: " + ", ".join(missing_raw_inputs)
        )
    catalog_csv = args.catalog_csv.expanduser()
    official_xlsx = args.official_xlsx.expanduser()
    anchor_dir = args.anchor_dir.expanduser()
    coverage_manifest = (
        args.coverage_manifest.expanduser() if args.coverage_manifest else None
    )
    cover_dates_csv = (
        args.cover_dates_csv.expanduser() if args.cover_dates_csv else None
    )

    if not catalog_csv.is_file():
        raise FileNotFoundError(f"catalog CSV does not exist: {catalog_csv}")
    if not official_xlsx.is_file():
        raise FileNotFoundError(f"official workbook does not exist: {official_xlsx}")
    if not anchor_dir.is_dir():
        raise FileNotFoundError(f"anchor directory does not exist: {anchor_dir}")

    manifest_editions, misnamed_copy_keys = load_coverage_manifest(coverage_manifest)
    cover_dates = load_cover_dates(cover_dates_csv) if cover_dates_csv else None
    if cover_dates is not None and not manifest_editions:
        raise ValueError(
            "--cover-dates-csv requires --coverage-manifest with edition_source rows"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 卫健委分类目录提供基础范围与类目。
    scope_standards: set[str] = set()
    category_of: dict[tuple[str, str], str] = {}
    for category_dir in sorted(anchor_dir.iterdir(), key=lambda path: path.name):
        if not category_dir.is_dir():
            continue
        for source_file in sorted(category_dir.iterdir(), key=lambda path: path.name):
            filename = source_file.name
            if not filename.lower().endswith(".pdf") or filename.startswith("."):
                continue
            match = PAT.match(filename.strip())
            if not match:
                continue
            number, year = match.group(1), match.group(2)
            standard = f"GB {number}"
            scope_standards.add(standard)
            category_of.setdefault((standard, year), category_dir.name)

    # edition_source 只补充身份与覆盖。
    scope_standards.update(standard for standard, _year in manifest_editions)

    # 2. 官方清单提供日期和分类。
    workbook = openpyxl.load_workbook(
        official_xlsx,
        read_only=True,
        data_only=True,
    )
    worksheet = workbook["全量汇总"]
    official_version_candidates: dict[
        tuple[str, str], list[dict[str, str]]
    ] = defaultdict(list)
    official_amendments: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(
        list
    )
    for source_row in worksheet.iter_rows(min_row=2, values_only=True):
        stdno, name, published, effective, category = source_row[:5]
        if not stdno:
            continue
        match = PAT.search(str(stdno))
        if not match:
            continue
        number, year = match.group(1), match.group(2)
        standard = f"GB {number}"
        key = (standard, year)
        record = {
            "发布日期": d10(published),
            "实施日期": d10(effective),
            "官方分类": str(category or ""),
            "名称": str(name or ""),
        }
        if "修改单" in record["名称"]:
            official_amendments[key].append(record)
            continue
        official_version_candidates[key].append(record)
    workbook.close()

    # 3. 目录候选按“正文优先，再按路径与标题”稳定合并。
    catalog_candidates: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(
        list
    )
    with catalog_csv.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"code", "number", "year", "title", "path"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                "catalog CSV is missing required columns: "
                + ", ".join(sorted(missing))
            )
        for source_row in reader:
            if source_row["code"] != "GB":
                continue
            standard = f"GB {source_row['number']}"
            if standard not in scope_standards:
                continue
            year = source_row["year"].strip()
            if not year:
                continue
            title = source_row["title"].strip()
            is_amendment = "修改单" in title
            if is_amendment and (standard, year) in misnamed_copy_keys:
                continue
            catalog_candidates[(standard, year)].append(
                {
                    "title": clean_title(title),
                    "is_amendment": is_amendment,
                    "path": source_row["path"].strip(),
                    "in_anchor": anchor_dir.name in source_row["path"],
                    "family": "",
                }
            )

    versions: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    for (standard, year), candidates in sorted(catalog_candidates.items()):
        selected = min(
            candidates,
            key=lambda row: (
                bool(row["is_amendment"]),
                str(row["path"]),
                str(row["title"]),
            ),
        )
        versions[standard][year] = selected

    # 4. 覆盖清单中的 edition_source 将同键目录候选合并为单一正式版事件。
    for (standard, year), source_row in sorted(manifest_editions.items()):
        current = versions[standard].get(year)
        if current is None or bool(current["is_amendment"]):
            versions[standard][year] = {
                "title": title_from_manifest(source_row),
                "is_amendment": False,
                "path": source_row["source_filename"],
                "in_anchor": False,
                "family": source_row["family"],
            }
        else:
            current["family"] = source_row["family"]

    correction_count = apply_date_corrections(
        date_corrections,
        official_version_candidates,
        official_amendments,
        {
            (standard, year)
            for standard, version_rows in versions.items()
            for year in version_rows
        },
    )

    official_versions, conflict_audit_rows = resolve_official_version_candidates(
        official_version_candidates,
        versions,
        category_of,
    )

    # 5. 组装事件长表，事件键冲突时立即失败。
    events: dict[tuple[str, str, str, str], dict[str, object]] = {}

    def add_event(row: dict[str, object]) -> None:
        key = (
            str(row["std_id"]),
            str(row["year"]),
            str(row["event_type"]),
            str(row["amend_no"]),
        )
        previous = events.get(key)
        if previous is not None and previous != row:
            raise ValueError(f"conflicting duplicate timeline event: {key}")
        events[key] = row

    wide_rows: list[dict[str, object]] = []
    for standard in sorted(versions, key=standard_sort_key):
        years = sorted(versions[standard], key=int)
        official_years = [
            year
            for year in years
            if not bool(versions[standard][year]["is_amendment"])
        ]
        latest_title = ""
        for year in reversed(official_years or years):
            latest_title = str(versions[standard][year]["title"])
            if latest_title:
                break

        category = ""
        for year in reversed(years):
            category = category_of.get((standard, year), "")
            if category:
                break
        if not category:
            for year in reversed(years):
                family = str(versions[standard][year].get("family", ""))
                category = FAMILY_CATEGORIES.get(family, "")
                if category:
                    break
        if not category and years:
            category = official_versions.get((standard, years[-1]), {}).get(
                "官方分类", ""
            )

        for year in official_years:
            version = versions[standard][year]
            metadata = official_versions.get((standard, year), {})
            title = str(version["title"]) or clean_title(metadata.get("名称", ""))
            add_event(
                {
                    "std_id": standard,
                    "number": standard_number(standard),
                    "event_type": "正式版",
                    "year": year,
                    "amend_no": "",
                    "发布日期": metadata.get("发布日期", ""),
                    "实施日期": metadata.get("实施日期", ""),
                    "卫健委类目": category_of.get((standard, year), ""),
                    "官方分类": metadata.get("官方分类", ""),
                    "title": title,
                    "在新目录": int(bool(version["in_anchor"])),
                    "path": portable_locator(str(version["path"])),
                }
            )

        amendment_events: list[tuple[str, str]] = []
        for year in years:
            amendment_rows = {
                tuple(record[column] for column in ("名称", "发布日期", "实施日期", "官方分类")): record
                for record in official_amendments.get((standard, year), [])
            }
            ordered_amendments = [
                amendment_rows[key] for key in sorted(amendment_rows)
            ]
            for index, amendment in enumerate(ordered_amendments, start=1):
                match = AMENDMENT_NUMBER.search(amendment["名称"])
                amendment_no = match.group(0) if match else f"第{index}号"
                amendment_events.append((year, amendment_no))
                add_event(
                    {
                        "std_id": standard,
                        "number": standard_number(standard),
                        "event_type": "修改单",
                        "year": year,
                        "amend_no": amendment_no,
                        "发布日期": amendment["发布日期"],
                        "实施日期": amendment["实施日期"],
                        "卫健委类目": category_of.get(
                            (standard, year), "修改单"
                        ),
                        "官方分类": amendment["官方分类"],
                        "title": amendment["名称"],
                        "在新目录": "",
                        "path": "",
                    }
                )

        for year in years:
            version = versions[standard][year]
            if (
                bool(version["is_amendment"])
                and not official_amendments.get((standard, year))
                and (standard, year) not in misnamed_copy_keys
            ):
                amendment_events.append((year, ""))
                add_event(
                    {
                        "std_id": standard,
                        "number": standard_number(standard),
                        "event_type": "修改单",
                        "year": year,
                        "amend_no": "",
                        "发布日期": "",
                        "实施日期": "",
                        "卫健委类目": category_of.get(
                            (standard, year), "修改单"
                        ),
                        "官方分类": "",
                        "title": version["title"],
                        "在新目录": int(bool(version["in_anchor"])),
                        "path": portable_locator(str(version["path"])),
                    }
                )

        latest_metadata = (
            official_versions.get((standard, official_years[-1]), {})
            if official_years
            else {}
        )
        wide_rows.append(
            {
                "std_id": standard,
                "title": latest_title,
                "卫健委类目": category,
                "n_正式版本": len(official_years),
                "版本年份": ";".join(official_years),
                "首版年": official_years[0] if official_years else "",
                "现行版年": official_years[-1] if official_years else "",
                "现行版发布日期": latest_metadata.get("发布日期", ""),
                "现行版实施日期": latest_metadata.get("实施日期", ""),
                "n_修改单": len(amendment_events),
                "修改单年份": ";".join(year for year, _number in amendment_events),
                "有历史沿革": int(
                    len(official_years) >= 2 or len(amendment_events) >= 1
                ),
            }
        )

    long_rows = list(events.values())
    long_rows.sort(
        key=lambda row: (
            standard_sort_key(str(row["std_id"])),
            int(str(row["year"])),
            str(row["event_type"]) != "正式版",
            str(row["amend_no"]),
        )
    )
    validate_event_date_chronology(long_rows)

    coverage_date_rows = (
        build_coverage_date_rows(manifest_editions, cover_dates, long_rows)
        if cover_dates is not None
        else None
    )

    # 6. 写出。
    long_columns = [
        "std_id",
        "number",
        "event_type",
        "year",
        "amend_no",
        "发布日期",
        "实施日期",
        "卫健委类目",
        "官方分类",
        "title",
        "在新目录",
        "path",
    ]
    with (output_dir / "standard_versions_long.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=long_columns, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(long_rows)

    wide_columns = [
        "std_id",
        "title",
        "卫健委类目",
        "n_正式版本",
        "版本年份",
        "首版年",
        "现行版年",
        "现行版发布日期",
        "现行版实施日期",
        "n_修改单",
        "修改单年份",
        "有历史沿革",
    ]
    wide_rows.sort(
        key=lambda row: (
            -int(row["n_正式版本"]) - int(row["n_修改单"]),
            standard_sort_key(str(row["std_id"])),
        )
    )
    with (output_dir / "standard_timeline.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=wide_columns, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(wide_rows)

    with (output_dir / "standard_timeline_conflicts.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=CONFLICT_COLUMNS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(conflict_audit_rows)

    if coverage_date_rows is not None:
        with (output_dir / "coverage_version_dates.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=COVERAGE_DATE_COLUMNS,
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(coverage_date_rows)
        complete_dates = sum(
            row["date_status"] == "complete" for row in coverage_date_rows
        )
        print(
            f"覆盖版本日期 {len(coverage_date_rows)} 行 | "
            f"完整日期 {complete_dates} | 未印日期 "
            f"{len(coverage_date_rows) - complete_dates}"
        )

    n_standards = len(wide_rows)
    n_history = sum(int(row["有历史沿革"]) for row in wide_rows)
    n_multiple = sum(int(row["n_正式版本"]) >= 2 for row in wide_rows)
    n_amended = sum(int(row["n_修改单"]) >= 1 for row in wide_rows)
    n_official = sum(row["event_type"] == "正式版" for row in long_rows)
    n_dated = sum(
        row["event_type"] == "正式版" and bool(row["发布日期"])
        for row in long_rows
    )
    dated_rate = n_dated / n_official * 100 if n_official else 0
    print(
        f"标准身份 {n_standards} | 有历史沿革 {n_history} | "
        f"多正式版本 {n_multiple} | 有修改单 {n_amended}"
    )
    print(
        f"版本事件长表 {len(long_rows)} 行（正式版 {n_official} / "
        f"修改单 {len(long_rows) - n_official}）"
    )
    print(
        f"正式版事件中已匹配发布日期 {n_dated}/{n_official} "
        f"({dated_rate:.0f}%)"
    )
    print(
        f"官方正式版元数据冲突 "
        f"{len({row['conflict_id'] for row in conflict_audit_rows})} 组 / "
        f"{len(conflict_audit_rows)} 条候选"
    )
    if correction_count:
        print(f"已应用有官方原文证据的日期修正 {correction_count} 项")
    print("多版本 TOP10:")
    for row in wide_rows[:10]:
        print(
            f"  {row['std_id']} {str(row['title'])[:22]} | "
            f"正式版 {row['版本年份']} | 修改单 {row['n_修改单']}"
        )
    print("→", output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
