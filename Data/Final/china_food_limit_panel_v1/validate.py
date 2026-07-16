#!/usr/bin/env python3
"""Validate the released China food-limit panel.

The default run is portable: it reads the package containing this script and
writes ``validation_report.json`` beside it. Checks are split into two layers:

``self_contained``
    Uses only files shipped in the release package.

``source_dependent``
    Uses source standards, translations, or generated manuscript tables when
    those artefacts are supplied or discovered. Unavailable inputs are reported
    as ``not_run`` or ``skip``; they never masquerade as passing checks.
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import hashlib
import json
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import unicodedata
from collections.abc import Iterable
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPORT_NAME = "validation_report.json"
VALID_STATUSES = {"pass", "fail", "skip", "not_run"}
RANDOM_SEED = 20260714

CSV_FILES = (
    "additive_limits_long.csv",
    "additive_names_en.csv",
    "additive_panel.csv",
    "data_dictionary.csv",
    "entity_names_en.csv",
    "food_category_names_en.csv",
    "mycotoxin_limits_long.csv",
    "mycotoxin_member_panel.csv",
    "mycotoxin_panel.csv",
    "pesticide_edition_reconciliation.csv",
    "pesticide_limits_long.csv",
    "pesticide_ocr_crosscheck.csv",
    "pesticide_panel.csv",
    "pollutant_category_panel.csv",
    "pollutant_limits_long.csv",
    "pollutant_member_panel.csv",
    "quarantined_rows.csv",
    "source_manifest.csv",
    "standard_timeline_conflicts.csv",
    "standard_version_timeline.csv",
    "version_dates.csv",
    "vetdrug_limits_long.csv",
    "vetdrug_member_panel.csv",
    "vetdrug_panel.csv",
)

PESTICIDE_YEARS = ("2012", "2014", "2016", "2019", "2021", "2026")


def _pesticide_panel_header() -> tuple[str, ...]:
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
    return tuple(columns)


EXPECTED_HEADERS = {
    "additive_limits_long.csv": tuple("record_id,standard,version_year,additive_zh,cns_code,ins_code,food_code,food_zh,max_use,unit,note,edition_source_id,extraction_source_id,conflict".split(",")),
    "additive_names_en.csv": tuple("entity_type,name_zh,name_en,cns_code,source_standard,source_doc".split(",")),
    "additive_panel.csv": tuple("record_id,standard,additive_zh,additive_names_zh,cns_code,ins_codes,food_code,food_zh,food_names_zh,v2011,v2014,v2024,status_2011,status_2014,status_2024,values_2011,values_2014,values_2024,units_2011,units_2014,units_2024,source_record_ids_2011,source_record_ids_2014,source_record_ids_2024,rules_2011,rules_2014,rules_2024,candidate_count_2011,candidate_count_2014,candidate_count_2024,distinct_value_count_2011,distinct_value_count_2014,distinct_value_count_2024,trend".split(",")),
    "data_dictionary.csv": tuple("table,column,type,nullable,missing_value,allowed_values,key_role,description_en,description_zh,notes".split(",")),
    "entity_names_en.csv": tuple("record_id,entity_key,entity_type,name_zh,name_en,source_standard".split(",")),
    "food_category_names_en.csv": tuple("family,food_key,food_zh,food_en,match_method,evidence,source_doc".split(",")),
    "mycotoxin_limits_long.csv": tuple("record_id,standard,version_year,toxin_zh,toxin_en,food_category_zh,limit_value,unit,confidence,edition_source_id,extraction_source_id,conflict".split(",")),
    "mycotoxin_member_panel.csv": tuple("record_id,standard,toxin_zh,food_member_zh,v2005,v2011,v2017,unit,trend,category_restructured,host_category_2005,host_category_2011,host_category_2017".split(",")),
    "mycotoxin_panel.csv": tuple("record_id,standard,toxin_zh,toxin_en,food_zh,v2005,v2011,v2017,unit,trend,note".split(",")),
    "pesticide_edition_reconciliation.csv": tuple("standard,version_year,declared_mrl_items,coordinate_extracted_visible_rules,visible_rules_minus_declared,declared_section_roster,extracted_section_headers,section_roster_complete,qualifier_counts,status,interpretation_boundary".split(",")),
    "pesticide_limits_long.csv": tuple("record_id,standard,version_year,section_number,pesticide_key,pesticide_zh,pesticide_en,pesticide_zh_raw,pesticide_en_raw,parent_category_zh,parent_category_raw,food_key,food_zh,food_raw,limit_value,unit,limit_qualifier,is_temporary,value_raw,source_page,source_y,food_x,parent_assignment_method,table_open_method,review_status,edition_source_id,extraction_source_id,source_copy_role,conflict".split(",")),
    "pesticide_ocr_crosscheck.csv": tuple("year,section_number,parent_category,food,text_values,ocr_values,status,key_level,text_row_count,ocr_row_count,text_source_pages,ocr_source_pages".split(",")),
    "pesticide_panel.csv": _pesticide_panel_header(),
    "pollutant_category_panel.csv": tuple("record_id,standard,analyte_zh,analyte_en,food_category_zh,v2012,v2017,v2022,v2025,unit_2012,unit_2017,unit_2022,unit_2025,basis_2012,basis_2017,basis_2022,basis_2025,cell_status_2012,cell_status_2017,cell_status_2022,cell_status_2025,source_category_2012,source_category_2017,source_category_2022,source_category_2025,unit_summary,n_versions,coverage_status,trend".split(",")),
    "pollutant_limits_long.csv": tuple("record_id,standard,version_year,analyte_zh,analyte_en,food_category_zh,limit_value,unit,limit_mgkg,normalization_status,limit_basis,note,confidence,extraction_path,edition_source_id,extraction_source_id,conflict".split(",")),
    "pollutant_member_panel.csv": tuple("record_id,standard,analyte_zh,analyte_en,food_member_zh,v2012,v2017,v2022,v2025,unit_2012,unit_2017,unit_2022,unit_2025,basis_2012,basis_2017,basis_2022,basis_2025,limit_basis,trend,category_restructured,host_category_2012,host_category_2017,host_category_2022,host_category_2025,note".split(",")),
    "quarantined_rows.csv": tuple("record_id,standard,version_year,analyte_zh,additive_zh,food_code,food_zh,parsed_value,unit,reject_reason,raw_text,source_path".split(",")),
    "source_manifest.csv": tuple("source_id,family,standard,version_year,source_role,release_status,released_limit_rows,source_filename,source_format,file_size_bytes,sha256,extraction_mode,document_identity,notes,related_source_id,acquisition_landing_url,acquisition_file_url,retrieved_date,page_count".split(",")),
    "standard_timeline_conflicts.csv": tuple("conflict_id,std_id,number,version_year,conflict_type,candidate_rank,selected,equivalent_row_count,timeline_title_match,anchor_category_match,issue_date,effective_date,official_category,title_zh,normalized_title,timeline_title,anchor_category,raw_titles,selection_reason".split(",")),
    "standard_version_timeline.csv": tuple("record_id,std_id,number,event_type,version_year,amendment_no,issue_date,effective_date,title_zh".split(",")),
    "version_dates.csv": tuple("record_id,source_id,family,standard,version_year,issue_date,effective_date,date_source,official_register_issue_date,official_register_effective_date,cross_check_official_register,date_status,date_resolution,source_filename".split(",")),
    "vetdrug_limits_long.csv": tuple("record_id,standard,version_year,drug_zh,drug_en,animal,animal_raw,tissue_zh,limit_value,unit,source,source_table_index,source_table_row,animal_block_index,tissue_index,edition_source_id,extraction_source_id,conflict".split(",")),
    "vetdrug_member_panel.csv": tuple("record_id,standard,drug_zh,drug_en,animal,tissue_zh,v2002,v2019,v2022,unit,trend".split(",")),
    "vetdrug_panel.csv": tuple("record_id,standard,drug_zh,drug_en,tissue_zh,v2002,v2019,unit,trend".split(",")),
}

REQUIRED_FILES = CSV_FILES + (
    "_build_stats.json",
    "LICENSE.md",
    "README.md",
    "SOURCE_ACQUISITION.md",
    "validate.py",
)

BUILD_STATS_FILES = {
    "pollutant_limits": "pollutant_limits_long.csv",
    "pollutant_category_panel": "pollutant_category_panel.csv",
    "pollutant_member_panel": "pollutant_member_panel.csv",
    "pesticide_limits": "pesticide_limits_long.csv",
    "pesticide_panel": "pesticide_panel.csv",
    "pesticide_edition_reconciliation": "pesticide_edition_reconciliation.csv",
    "pesticide_ocr_crosscheck": "pesticide_ocr_crosscheck.csv",
    "mycotoxin_limits": "mycotoxin_limits_long.csv",
    "mycotoxin_panel": "mycotoxin_panel.csv",
    "vetdrug_limits": "vetdrug_limits_long.csv",
    "vetdrug_panel": "vetdrug_panel.csv",
    "additive_limits": "additive_limits_long.csv",
    "additive_panel": "additive_panel.csv",
    "standard_timeline": "standard_version_timeline.csv",
    "standard_timeline_conflicts": "standard_timeline_conflicts.csv",
    "vetdrug_member_panel": "vetdrug_member_panel.csv",
    "mycotoxin_member_panel": "mycotoxin_member_panel.csv",
    "quarantined_rows": "quarantined_rows.csv",
    "entity_names_en": "entity_names_en.csv",
    "version_dates": "version_dates.csv",
}

FAMILY_VERSIONS = {
    "pollutant_limits_long.csv": ("2012", "2017", "2022", "2025"),
    "pesticide_limits_long.csv": ("2012", "2014", "2016", "2019", "2021", "2026"),
    "mycotoxin_limits_long.csv": ("2005", "2011", "2017"),
    "vetdrug_limits_long.csv": ("2002", "2019", "2022"),
    "additive_limits_long.csv": ("2011", "2014", "2024"),
}

PESTICIDE_REVIEW_STATUS_COMPONENTS = {
    "text_layer_auto_extracted",
    "source_structure_exception",
    "source_glyph_correction",
    "food_label_continuation_joined",
    "food_value_multiline_joined",
    "margin_header_overlap_removed",
    "source_qualifier_unresolved_c",
}

PRIMARY_KEYS = {
    "additive_names_en.csv": ("cns_code",),
    "food_category_names_en.csv": ("family", "food_key"),
    "data_dictionary.csv": ("table", "column"),
    "pesticide_edition_reconciliation.csv": ("standard", "version_year"),
    "pesticide_ocr_crosscheck.csv": (
        "year",
        "section_number",
        "parent_category",
        "food",
        "key_level",
    ),
    "source_manifest.csv": ("source_id",),
    "standard_timeline_conflicts.csv": ("conflict_id", "candidate_rank"),
}

NULLABLE_PRIMARY_KEY_COLUMNS = {
    ("pesticide_ocr_crosscheck.csv", "parent_category"),
}

CONFLICT_KEYS = {
    "pollutant_limits_long.csv": ("version_year", "analyte_zh", "food_category_zh"),
    "pesticide_limits_long.csv": ("version_year", "pesticide_key", "food_key"),
    "mycotoxin_limits_long.csv": ("version_year", "toxin_zh", "food_category_zh"),
    "vetdrug_limits_long.csv": ("version_year", "drug_en", "animal", "tissue_zh"),
    "additive_limits_long.csv": ("version_year", "cns_code", "food_code"),
}

PANEL_LINEAGE = {
    "pesticide_panel.csv": {
        "long_file": "pesticide_limits_long.csv",
        "years": PESTICIDE_YEARS,
        "panel_key": ("pesticide_key", "food_key"),
        "long_key": ("pesticide_key", "food_key"),
        "value_column": "limit_value",
        "rule_columns": (
            "record_id",
            "version_year",
            "limit_value",
            "unit",
            "pesticide_key",
            "pesticide_zh",
            "pesticide_en",
            "pesticide_zh_raw",
            "pesticide_en_raw",
            "parent_category_zh",
            "parent_category_raw",
            "food_key",
            "food_zh",
            "food_raw",
            "limit_qualifier",
            "is_temporary",
            "value_raw",
            "review_status",
            "edition_source_id",
            "extraction_source_id",
            "source_copy_role",
            "source_page",
            "source_y",
            "food_x",
            "parent_assignment_method",
            "table_open_method",
        ),
    },
    "additive_panel.csv": {
        "long_file": "additive_limits_long.csv",
        "years": ("2011", "2014", "2024"),
        "panel_key": ("cns_code", "food_code"),
        "long_key": ("cns_code", "food_code"),
        "value_column": "max_use",
        "rule_columns": (
            "record_id",
            "additive_zh",
            "cns_code",
            "ins_code",
            "food_zh",
            "max_use",
            "unit",
            "note",
            "edition_source_id",
            "extraction_source_id",
        ),
        "scope_columns": ("food_zh", "note"),
    },
}

POLLUTANT_PDFS = {
    year: f"GB 2762-{year} 食品安全国家标准 食品中污染物限量.pdf"
    for year in ("2012", "2017", "2022", "2025")
}

POLLUTANT_SOURCE_EXPECTATIONS = (
    {
        "year": "2012",
        "page": 10,
        "printed_page": "8",
        "analyte": "硝酸盐",
        "food": "较大婴儿和幼儿配方食品",
        "value": "100",
        "unit": "mg/kg",
        "basis": "粉状产品计",
    },
    {
        "year": "2012",
        "page": 7,
        "printed_page": "5",
        "analyte": "镉",
        "food": "包装饮用水（矿泉水除外）",
        "value": "0.005",
        "unit": "mg/L",
        "basis": "",
    },
    {
        "year": "2012",
        "page": 7,
        "printed_page": "5",
        "analyte": "镉",
        "food": "矿泉水",
        "value": "0.003",
        "unit": "mg/L",
        "basis": "",
    },
    {
        "year": "2017",
        "page": 6,
        "printed_page": "4",
        "analyte": "铅",
        "food": "1岁~10岁人群的产品",
        "value": "0.15",
        "unit": "mg/kg",
        "basis": "固态产品计",
    },
    {
        "year": "2022",
        "page": 6,
        "printed_page": "4",
        "analyte": "铅",
        "food": "婴幼儿配方食品",
        "value": "0.08",
        "unit": "mg/kg",
        "basis": "固态产品计",
    },
    {
        "year": "2022",
        "page": 6,
        "printed_page": "4",
        "analyte": "铅",
        "food": "10岁以上人群的产品",
        "value": "0.5",
        "unit": "mg/kg",
        "basis": "固态产品计",
    },
    {
        "year": "2022",
        "page": 6,
        "printed_page": "4",
        "analyte": "铅",
        "food": "1岁~10岁人群的产品",
        "value": "0.15",
        "unit": "mg/kg",
        "basis": "固态产品计",
    },
    {
        "year": "2022",
        "page": 8,
        "printed_page": "6",
        "analyte": "镉",
        "food": "包装饮用水（饮用天然矿泉水除外）",
        "value": "0.005",
        "unit": "mg/L",
        "basis": "",
    },
    {
        "year": "2022",
        "page": 8,
        "printed_page": "6",
        "analyte": "镉",
        "food": "饮用天然矿泉水",
        "value": "0.003",
        "unit": "mg/L",
        "basis": "",
    },
)

BASIS_RE = re.compile(r"[（(](?:以)?(?:干重|鲜重|固态产品|粉状产品|即食状态)[^）)]{0,4}计[）)]")

ENTITY_COUNT_CASES = (
    {
        "id": "additive.2024",
        "file": "additive_limits_long.csv",
        "year": "2024",
        "entity": "additive_zh",
        "pattern": "GB 2760-2024*.pdf",
        "kind": "cns",
    },
    {
        "id": "additive.2014",
        "file": "additive_limits_long.csv",
        "year": "2014",
        "entity": "additive_zh",
        "pattern": "GB 2760-2014*.pdf",
        "kind": "cns",
    },
    {
        "id": "vetdrug.2019",
        "file": "vetdrug_limits_long.csv",
        "year": "2019",
        "entity": "drug_zh",
        "pattern": "GB 31650-2019*.pdf",
        "kind": "vet",
    },
    *(
        {
            "id": f"pesticide.{year}",
            "file": "pesticide_limits_long.csv",
            "year": year,
            "entity": "pesticide_zh",
            "pattern": f"GB 2763-{year}*.pdf",
            "kind": "pesticide",
        }
        for year in ("2012", "2014", "2016")
    ),
)

ENTITY_COUNT_MIN_COVERAGE = Decimal("0.95")
ENTITY_COUNT_MAX_COVERAGE = Decimal("1")

POSITIONAL_CASES = (
    ("pollutant.2022", "pollutant_limits_long.csv", "2022", "analyte_zh", "food_category_zh", "limit_value", 4000, "GB 2762-2022*.pdf"),
    ("pesticide.2016", "pesticide_limits_long.csv", "2016", "pesticide_zh", "food_zh", "limit_value", 3000, "GB 2763-2016*.pdf"),
    ("vetdrug.2019", "vetdrug_limits_long.csv", "2019", "drug_zh", "tissue_zh", "limit_value", 500, "GB 31650-2019*.pdf"),
    ("additive.2024", "additive_limits_long.csv", "2024", "additive_zh", "food_zh", "max_use", 3000, "GB 2760-2024*.pdf"),
)

POLLUTANT_POSITIONAL_EXCLUSIONS = frozenset(
    {"总汞", "甲基汞", "总砷", "无机砷", "亚硝酸盐", "硝酸盐"}
)

ENGLISH_SOURCE_CASES = (
    ("additive_names", "additive_names_en.csv", "name_en", "GAIN_GB2760-2014_en.pdf"),
    ("additive_food_names", "food_category_names_en.csv", "food_en", "GAIN_GB2760-2014_en.pdf"),
    ("pesticide_food_names", "food_category_names_en.csv", "food_en", "FSIS_GB2763-2016_en.pdf"),
)

TRANSLATION_SOURCE_LOCKS = {
    "FSIS_GB2763-2016_en.pdf": (
        2_480_852,
        "b28b87fb4a50759cd40c9889349ee59be24f9e49ea890af103d913fccccda542",
    ),
    "GAIN_CH2019-0170_GB2763-2019_en.pdf": (
        4_073_400,
        "8f333e72aafa92140c9992fac61957efe686ce8d232a67d2b668f58560955730",
    ),
    "GAIN_CH2023-0040_GB2762-2022_en.pdf": (
        639_722,
        "c8bccdb20f30b3f6246b18167af26dab16b09cc639621e98c9c16294b76c10a7",
    ),
    "GAIN_GB2760-2014_en.pdf": (
        2_335_051,
        "69d7d767b7c8c995f1dfd1b8bc828ced40a7d8f755a495ab977328e12665903f",
    ),
}


def result(check_id: str, status: str, message: str, **details: Any) -> dict[str, Any]:
    """Create one explicit-status validation result."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Unknown validation status: {status}")
    item: dict[str, Any] = {"id": check_id, "status": status, "message": message}
    if details:
        item["details"] = details
    return item


class Package:
    """Small cached reader for one release package."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self._rows: dict[str, list[dict[str, str]]] = {}
        self._headers: dict[str, list[str]] = {}

    def path(self, name: str) -> Path:
        return self.root / name

    def rows(self, name: str) -> list[dict[str, str]]:
        if name not in self._rows:
            with self.path(name).open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                self._headers[name] = list(reader.fieldnames or [])
                self._rows[name] = list(reader)
        return self._rows[name]

    def header(self, name: str) -> list[str]:
        self.rows(name)
        return self._headers[name]


def _normalise_source_roots(
    roots: Path | Iterable[Path] | None,
) -> tuple[Path, ...]:
    """Return de-duplicated, resolved source roots while preserving CLI order."""
    if roots is None:
        return ()
    candidates = (roots,) if isinstance(roots, Path) else tuple(roots)
    resolved: list[Path] = []
    for candidate in candidates:
        path = Path(candidate).resolve()
        if path not in resolved:
            resolved.append(path)
    return tuple(resolved)


class SourceIndex:
    """Union basename index for one or more user-supplied source trees."""

    def __init__(
        self,
        roots: Path | Iterable[Path],
        manifest: list[dict[str, str]] | None = None,
    ):
        self.roots = _normalise_source_roots(roots)
        if not self.roots:
            raise ValueError("SourceIndex requires at least one source root")
        root_name_counts = Counter(root.name or "source" for root in self.roots)
        used_names: Counter[str] = Counter()
        self.root_labels: dict[Path, str] = {}
        for root in self.roots:
            base = root.name or "source"
            used_names[base] += 1
            self.root_labels[root] = (
                base
                if root_name_counts[base] == 1
                else f"{base}-{used_names[base]}"
            )
        self.by_name: dict[str, list[Path]] = defaultdict(list)
        self.expected: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in manifest or []:
            self.expected[row["source_filename"]].append(
                {
                    "sha256": row["sha256"],
                    "bytes": int(row["file_size_bytes"]),
                }
            )
        self._fingerprints: dict[Path, tuple[str, int]] = {}
        self.selections: list[dict[str, Any]] = []
        self.by_label: dict[str, Path] = {}
        for root in self.roots:
            for current, _, files in os.walk(root):
                for name in files:
                    path = Path(current) / name
                    self.by_name[name].append(path)
                    self.by_label[self.label(path)] = path

    def label(self, path: Path) -> str:
        resolved = path.resolve()
        for root in self.roots:
            try:
                relative = resolved.relative_to(root).as_posix()
            except ValueError:
                continue
            return f"{self.root_labels[root]}/{relative}"
        return path.name

    def path_for_label(self, label: str) -> Path | None:
        return self.by_label.get(Path(label).as_posix())

    def fingerprint(self, path: Path) -> tuple[str, int]:
        path = path.resolve()
        if path not in self._fingerprints:
            self._fingerprints[path] = (_sha256(path), path.stat().st_size)
        return self._fingerprints[path]

    def _select(self, query: str, hits: list[Path], prefer: str | None = None) -> Path | None:
        if not hits:
            return None
        matching_manifest = []
        manifest_named = [path for path in hits if path.name in self.expected]
        for path in manifest_named:
            digest, size = self.fingerprint(path)
            if any(
                digest == expected["sha256"] and size == expected["bytes"]
                for expected in self.expected[path.name]
            ):
                matching_manifest.append(path)
        if matching_manifest:
            eligible = matching_manifest
        else:
            preferred = [path for path in hits if prefer and prefer in str(path)]
            eligible = preferred or hits
        ordered = sorted(eligible, key=lambda path: (len(str(path)), str(path)))
        chosen = ordered[0]
        signatures = {self.fingerprint(path) for path in eligible}
        self.selections.append(
            {
                "query": query,
                "chosen": self.label(chosen),
                "candidates": [self.label(path) for path in sorted(hits)],
                "manifest_hash_matched": bool(matching_manifest),
                "manifest_hash_mismatch": bool(manifest_named and not matching_manifest),
                "ambiguous_distinct_files": len(signatures) > 1,
            }
        )
        return chosen

    def exact(self, name: str, prefer: str | None = None) -> Path | None:
        return self._select(f"exact:{name}", self.by_name.get(name, []), prefer=prefer)

    def matching(self, pattern: str, exclude: str | None = None) -> Path | None:
        hits = [
            path
            for name, paths in self.by_name.items()
            if fnmatch.fnmatch(name, pattern) and (exclude is None or exclude not in name)
            for path in paths
        ]
        return self._select(f"pattern:{pattern}", hits)


def _normalise_text(value: str) -> str:
    return (
        re.sub(r"\s+", "", value)
        .replace("（", "(")
        .replace("）", ")")
        .replace("～", "~")
        .replace("－", "-")
        .replace("—", "-")
    )


def _normalise_food(value: str) -> str:
    value = _normalise_text(value)
    value = re.sub(r"(?<=[\u4e00-\u9fff）)])(?:[a-eP])$", "", value)
    return value


def _normalise_decimal(value: str) -> str:
    try:
        number = Decimal(value)
    except InvalidOperation:
        return value.strip()
    normalised = format(number.normalize(), "f")
    return "0" if normalised in {"-0", ""} else normalised


def _normalise_cns(value: str) -> str:
    return ",".join(sorted(part.strip() for part in value.split(",") if part.strip()))


def _normalise_scope_text(value: str) -> str:
    """Normalise typography while retaining scope-bearing words and symbols."""
    text = unicodedata.normalize("NFKC", value or "")
    text = re.sub(r"\s+", "", text)
    text = (
        text.replace("≦", "≤")
        .replace("⩽", "≤")
        .replace("≧", "≥")
        .replace("⩾", "≥")
    )
    text = re.sub(r"[,、;:。]", "", text)
    return re.sub(r"(?<!\d)\.|\.(?!\d)", "", text)


def _normalise_crosscheck_scope(value: str) -> str:
    """Reproduce the conservative key normalisation used by the OCR audit."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\s+", "", text)
    return text.translate(str.maketrans({"，": ",", "（": "(", "）": ")"}))


def _normalise_crosscheck_value(value: str) -> str:
    """Reproduce the decimal rendering stored in the OCR crosscheck table."""
    try:
        parsed = Decimal(str(value).strip())
    except InvalidOperation:
        return str(value).strip()
    output = format(parsed, "f")
    if "." in output:
        output = output.rstrip("0").rstrip(".")
    return output


def _normalise_english_entity(value: str) -> str:
    """Return the punctuation-insensitive English identity used for joins."""
    return re.sub(r"[^0-9a-z]+", "", str(value or "").casefold())


def _lookup_entity_key(prefix: str, identity: str) -> str:
    """Recompute a deterministic key from a released bilingual identity."""
    canonical = str(identity or "").strip().casefold()
    if not canonical:
        return ""
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _normalise_pesticide_key_text(value: str) -> str:
    """Mirror the release builder's scope-preserving identifier normalisation."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.translate(
        str.maketrans(
            {
                "、": ",",
                "，": ",",
                "﹐": ",",
                "；": ";",
                "﹔": ";",
                "：": ":",
                "﹕": ":",
                "。": ".",
                "．": ".",
                "﹒": ".",
                "‐": "-",
                "‑": "-",
                "‒": "-",
                "–": "-",
                "—": "-",
                "−": "-",
                "≦": "≤",
                "⩽": "≤",
                "≧": "≥",
                "⩾": "≥",
                "“": '"',
                "”": '"',
                "‘": "'",
                "’": "'",
                "【": "[",
                "】": "]",
                "•": "·",
                "‧": "·",
            }
        )
    )
    text = re.sub(r"[\s\u200b\u200c\u200d\ufeff]+", "", text)
    text = text.replace('"', "").replace("'", "")
    kept: list[str] = []
    for index, character in enumerate(text):
        previous = text[index - 1] if index else ""
        following = text[index + 1] if index + 1 < len(text) else ""
        between_digits = previous.isdigit() and following.isdigit()
        if character in {",", ";"}:
            if between_digits:
                kept.append(",")
            continue
        if character in {":", "."}:
            if between_digits:
                kept.append(character)
            continue
        kept.append(character)
    return "".join(kept)


def _stable_release_key(prefix: str, canonical_key: str) -> str:
    digest = hashlib.sha256(canonical_key.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _expected_pesticide_key(pesticide_en: str, pesticide_zh: str) -> str:
    english = _normalise_pesticide_key_text(pesticide_en).casefold()
    if english:
        return _stable_release_key("PST", f"en:{english}")
    chinese = _normalise_pesticide_key_text(pesticide_zh).casefold()
    return _stable_release_key("PST", f"zh:{chinese}") if chinese else ""


def _expected_pesticide_food_key(food_zh: str) -> str:
    full = _normalise_pesticide_key_text(food_zh).casefold()
    if not full:
        return ""
    base = full
    previous = None
    while base != previous:
        previous = base
        base = re.sub(r"\([^()]*\)|\[[^\[\]]*\]", "", base)
    base = base.strip("-_/.,;:")
    return _stable_release_key("FOD", f"zh:{base or full}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _command_output(args: list[str], cwd: Path | None = None) -> str | None:
    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or completed.stderr.strip()


def git_metadata(package_root: Path) -> dict[str, Any]:
    repo = _command_output(["git", "rev-parse", "--show-toplevel"], cwd=package_root)
    if not repo:
        return {"available": False, "commit": None, "dirty": None, "root": None}
    commit = _command_output(["git", "rev-parse", "HEAD"], cwd=package_root)
    try:
        status_run = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=package_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        dirty = bool(status_run.stdout.strip()) if status_run.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        dirty = None
    return {
        "available": True,
        "commit": commit,
        "dirty": dirty,
        "root": Path(repo).name,
    }


def file_hashes(package_root: Path, output: Path) -> dict[str, dict[str, Any]]:
    hashes: dict[str, dict[str, Any]] = {}
    for path in sorted(package_root.iterdir()):
        if (
            not path.is_file()
            or path.resolve() == output.resolve()
            or path.name == REPORT_NAME
            or path.name.startswith(".")
        ):
            continue
        hashes[path.name] = {"sha256": _sha256(path), "bytes": path.stat().st_size}
    return hashes


def external_input_hashes(
    source_checks: list[dict[str, Any]],
    source_root: Path | Iterable[Path] | None,
    results_tab: Path | None,
) -> dict[str, dict[str, Any]]:
    inputs: dict[str, Path] = {}
    valid_roots = tuple(
        root for root in _normalise_source_roots(source_root) if root.is_dir()
    )
    source_index = SourceIndex(valid_roots) if valid_roots else None
    for item in source_checks:
        details = item.get("details", {})
        source = details.get("source")
        if source_index is not None and isinstance(source, str):
            path = source_index.path_for_label(source)
            if path is not None and path.is_file():
                inputs[f"source_roots/{Path(source).as_posix()}"] = path
        if item["id"].startswith("external_tables.") and results_tab is not None:
            name = details.get("path")
            if isinstance(name, str):
                path = results_tab / name
                if path.is_file():
                    inputs[f"results_tab/{Path(name).name}"] = path
        if source_index is not None:
            for verified in details.get("verified", []):
                relative = verified.get("path")
                if isinstance(relative, str):
                    path = source_index.path_for_label(relative)
                    if path is not None and path.is_file():
                        inputs[f"source_roots/{Path(relative).as_posix()}"] = path
    return {
        label: {"sha256": _sha256(path), "bytes": path.stat().st_size}
        for label, path in sorted(inputs.items())
    }


def check_required_files(package: Package) -> list[dict[str, Any]]:
    missing = [name for name in REQUIRED_FILES if not package.path(name).is_file()]
    return [
        result(
            "package.required_files",
            "pass" if not missing else "fail",
            "All required release files are present." if not missing else "Required release files are missing.",
            missing=missing,
            required=len(REQUIRED_FILES),
        )
    ]


def check_csv_integrity(package: Package) -> list[dict[str, Any]]:
    malformed: list[dict[str, Any]] = []
    inventory: dict[str, dict[str, Any]] = {}
    for name in CSV_FILES:
        path = package.path(name)
        if not path.is_file():
            continue
        try:
            rows = package.rows(name)
            header = package.header(name)
        except (OSError, csv.Error, UnicodeError) as exc:
            malformed.append({"file": name, "error": str(exc)})
            continue
        duplicate_headers = sorted({column for column in header if header.count(column) > 1})
        overflow_rows = [index for index, row in enumerate(rows, 2) if None in row]
        short_rows = [
            index
            for index, row in enumerate(rows, 2)
            if any(value is None for value in row.values())
        ]
        expected_header = list(EXPECTED_HEADERS[name])
        header_mismatch = header != expected_header
        if not header or duplicate_headers or overflow_rows or short_rows or header_mismatch:
            malformed.append(
                {
                    "file": name,
                    "empty_header": not header,
                    "duplicate_headers": duplicate_headers,
                    "overflow_rows": overflow_rows[:10],
                    "short_rows": short_rows[:10],
                    "missing_columns": sorted(set(expected_header) - set(header)),
                    "unexpected_columns": sorted(set(header) - set(expected_header)),
                    "column_order_matches": not header_mismatch,
                }
            )
        inventory[name] = {"rows": len(rows), "columns": len(header)}
    return [
        result(
            "package.csv_integrity",
            "pass" if not malformed else "fail",
            "All CSV files are readable and rectangular." if not malformed else "CSV integrity errors were found.",
            inventory=inventory,
            malformed=malformed,
        )
    ]


def check_build_stats(package: Package) -> list[dict[str, Any]]:
    path = package.path("_build_stats.json")
    if not path.is_file():
        return [result("package.build_stats", "fail", "_build_stats.json is missing.")]
    try:
        stats = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [result("package.build_stats", "fail", "_build_stats.json is unreadable.", error=str(exc))]
    mismatches = []
    missing_keys = []
    for key, filename in BUILD_STATS_FILES.items():
        if key not in stats or "rows" not in stats[key]:
            missing_keys.append(key)
            continue
        actual = len(package.rows(filename))
        declared = stats[key]["rows"]
        if actual != declared:
            mismatches.append({"key": key, "file": filename, "declared": declared, "actual": actual})
    status = "pass" if not mismatches and not missing_keys else "fail"
    return [
        result(
            "package.build_stats",
            status,
            "Build manifest row counts match the released tables." if status == "pass" else "Build manifest drift was detected.",
            mismatches=mismatches,
            missing_keys=missing_keys,
        )
    ]


def check_primary_keys(package: Package) -> list[dict[str, Any]]:
    problems = []
    checked = {}
    for name in CSV_FILES:
        rows = package.rows(name)
        header = package.header(name)
        if "record_id" in header:
            keys = ("record_id",)
        else:
            keys = PRIMARY_KEYS.get(name)
        if not keys:
            problems.append({"file": name, "problem": "no primary key declared"})
            continue
        values = [tuple(row.get(column, "") for column in keys) for row in rows]
        blank = sum(
            any(
                not part and (name, column) not in NULLABLE_PRIMARY_KEY_COLUMNS
                for column, part in zip(keys, value)
            )
            for value in values
        )
        duplicates = len(values) - len(set(values))
        checked[name] = {"key": list(keys), "rows": len(values), "blank": blank, "duplicates": duplicates}
        if blank or duplicates:
            problems.append({"file": name, **checked[name]})
    return [
        result(
            "package.primary_keys",
            "pass" if not problems else "fail",
            "Every released table has a declared, nonblank, unique primary key." if not problems else "Primary-key problems were found.",
            checked=checked,
            problems=problems,
        )
    ]


def check_version_coverage(package: Package) -> list[dict[str, Any]]:
    problems = []
    coverage = {}
    for filename, expected in FAMILY_VERSIONS.items():
        rows = package.rows(filename)
        actual = sorted({row["version_year"] for row in rows})
        per_version = Counter(row["version_year"] for row in rows)
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        coverage[filename] = {
            "expected": list(expected),
            "actual": actual,
            "rows_per_version": dict(sorted(per_version.items())),
        }
        if missing or unexpected:
            problems.append({"file": filename, "missing": missing, "unexpected": unexpected})
    return [
        result(
            "package.version_coverage",
            "pass" if not problems else "fail",
            "The five long tables contain exactly the declared editions." if not problems else "Version coverage differs from the declared editions.",
            coverage=coverage,
            problems=problems,
        )
    ]


def check_conflict_flags(package: Package) -> list[dict[str, Any]]:
    problems = []
    summaries = {}
    for filename, key_columns in CONFLICT_KEYS.items():
        rows = package.rows(filename)
        counts = Counter(tuple(row[column] for column in key_columns) for row in rows)
        expected = ["1" if counts[tuple(row[column] for column in key_columns)] > 1 else "0" for row in rows]
        bad = [
            row["record_id"]
            for row, want in zip(rows, expected)
            if row.get("conflict") != want
        ]
        summaries[filename] = {
            "business_key": list(key_columns),
            "rows_flagged": sum(value == "1" for value in expected),
            "duplicate_groups": sum(count > 1 for count in counts.values()),
        }
        if bad:
            problems.append({"file": filename, "record_ids": bad[:20], "count": len(bad)})
    return [
        result(
            "package.conflict_flags",
            "pass" if not problems else "fail",
            "Conflict flags agree with repeated business keys." if not problems else "Conflict flags do not agree with repeated business keys.",
            summaries=summaries,
            problems=problems,
        )
    ]


def _schema_matches(table: str, column: str, row: dict[str, str]) -> bool:
    table_match = row["table"] == table or row["table"] == "_ALL"
    return table_match and fnmatch.fnmatchcase(column, row["column"])


def _schema_specificity(table: str, column: str, row: dict[str, str]) -> tuple[int, int]:
    table_score = 1 if row["table"] == table else 0
    literal_score = len(row["column"].replace("*", "").replace("?", ""))
    exact_score = 1 if row["column"] == column else 0
    return table_score + exact_score, literal_score


def _valid_type(value: str, declared_type: str) -> bool:
    if declared_type in {"string", "enum"}:
        return True
    if declared_type == "integer":
        try:
            int(value)
        except ValueError:
            return False
        return True
    if declared_type == "number":
        try:
            parsed = Decimal(value)
        except InvalidOperation:
            return False
        return parsed.is_finite()
    if declared_type == "number_or_gmp":
        if value == "GMP":
            return True
        try:
            parsed = Decimal(value)
        except InvalidOperation:
            return False
        return parsed.is_finite()
    if declared_type == "boolean01":
        return value in {"0", "1"}
    if declared_type == "boolean":
        return value.casefold() in {"0", "1", "false", "true"}
    if declared_type == "date":
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return False
        return True
    if declared_type in {"json_array", "json_array_object"}:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return False
        if not isinstance(parsed, list):
            return False
        return declared_type != "json_array_object" or all(isinstance(item, dict) for item in parsed)
    if declared_type == "json_object":
        try:
            return isinstance(json.loads(value), dict)
        except json.JSONDecodeError:
            return False
    return False


def check_data_dictionary(package: Package) -> list[dict[str, Any]]:
    required_columns = {
        "table",
        "column",
        "type",
        "nullable",
        "missing_value",
        "allowed_values",
        "key_role",
        "description_en",
        "description_zh",
        "notes",
    }
    header = set(package.header("data_dictionary.csv"))
    if not required_columns.issubset(header):
        return [
            result(
                "package.data_dictionary",
                "fail",
                "The data dictionary lacks required schema columns.",
                missing_columns=sorted(required_columns - header),
            )
        ]

    dictionary = package.rows("data_dictionary.csv")
    uncovered = []
    unmatched_patterns = []
    type_errors = []
    nullability_errors = []
    enum_errors = []
    schema_meta_errors = []
    ambiguity_errors = []
    valid_types = {
        "string",
        "enum",
        "integer",
        "number",
        "number_or_gmp",
        "boolean01",
        "boolean",
        "date",
        "json_array",
        "json_array_object",
        "json_object",
    }
    valid_key_roles = {"", "primary", "business_component", "foreign"}
    for row_index, schema in enumerate(dictionary, 2):
        errors = []
        if schema["table"] not in {*CSV_FILES, "_ALL"}:
            errors.append("unknown table")
        if not schema["column"]:
            errors.append("blank column pattern")
        if schema["type"] not in valid_types:
            errors.append("unknown type")
        if schema["nullable"] not in {"yes", "no"}:
            errors.append("nullable must be yes or no")
        if schema["key_role"] not in valid_key_roles:
            errors.append("unknown key_role")
        if schema["type"] == "enum" and not schema["allowed_values"]:
            errors.append("enum lacks allowed_values")
        if not schema["missing_value"]:
            errors.append("missing_value is blank")
        if not schema["description_en"] or not schema["description_zh"]:
            errors.append("bilingual description is incomplete")
        if errors:
            schema_meta_errors.append({"row": row_index, "errors": errors})
    actual_fields = {
        (name, column)
        for name in CSV_FILES
        if name != "data_dictionary.csv"
        for column in package.header(name)
    }
    for table, column in sorted(actual_fields):
        matches = [row for row in dictionary if _schema_matches(table, column, row)]
        if not matches:
            uncovered.append({"table": table, "column": column})
            continue
        best_rank = max(_schema_specificity(table, column, row) for row in matches)
        winners = [
            row
            for row in matches
            if _schema_specificity(table, column, row) == best_rank
        ]
        if len(winners) > 1:
            ambiguity_errors.append(
                {
                    "table": table,
                    "column": column,
                    "patterns": [row["column"] for row in winners],
                }
            )
        schema = winners[0]
        allowed = {part for part in schema["allowed_values"].split(";") if part}
        nullable = schema["nullable"].lower() == "yes"
        for row_index, row in enumerate(package.rows(table), 2):
            value = row.get(column, "")
            if value == "":
                if not nullable:
                    nullability_errors.append({"table": table, "column": column, "row": row_index})
                continue
            if not _valid_type(value, schema["type"]):
                type_errors.append(
                    {"table": table, "column": column, "row": row_index, "value": value[:80], "type": schema["type"]}
                )
            if allowed and value not in allowed:
                enum_errors.append({"table": table, "column": column, "row": row_index, "value": value[:80]})

    for schema in dictionary:
        matched = [
            (table, column)
            for table, column in actual_fields
            if _schema_matches(table, column, schema)
        ]
        if not matched:
            unmatched_patterns.append({"table": schema["table"], "column": schema["column"]})

    problems = (
        uncovered
        or unmatched_patterns
        or type_errors
        or nullability_errors
        or enum_errors
        or schema_meta_errors
        or ambiguity_errors
    )
    return [
        result(
            "package.data_dictionary",
            "fail" if problems else "pass",
            "Every released field is documented and conforms to its declared type." if not problems else "Schema coverage or field conformance problems were found.",
            documented_fields=len(actual_fields) - len(uncovered),
            actual_fields=len(actual_fields),
            uncovered=uncovered[:50],
            unmatched_patterns=unmatched_patterns[:50],
            type_errors=type_errors[:50],
            nullability_errors=nullability_errors[:50],
            enum_errors=enum_errors[:50],
            schema_meta_errors=schema_meta_errors[:50],
            ambiguity_errors=ambiguity_errors[:50],
            truncated=any(
                len(items) > 50
                for items in (
                    uncovered,
                    unmatched_patterns,
                    type_errors,
                    nullability_errors,
                    enum_errors,
                    schema_meta_errors,
                    ambiguity_errors,
                )
            ),
        )
    ]


def check_lookup_integrity(package: Package) -> list[dict[str, Any]]:
    """Validate stable lookup keys and their Chinese-side release joins."""
    problems: list[dict[str, Any]] = []

    pesticide_rows = package.rows("pesticide_limits_long.csv")
    pesticide_by_key: dict[str, set[tuple[str, str]]] = defaultdict(set)
    pesticide_foods: dict[str, set[str]] = defaultdict(set)
    for row in pesticide_rows:
        expected_pesticide_key = _expected_pesticide_key(
            row["pesticide_en"], row["pesticide_zh"]
        )
        expected_food_key = _expected_pesticide_food_key(row["food_zh"])
        if row["pesticide_key"] != expected_pesticide_key:
            problems.append(
                {
                    "file": "pesticide_limits_long.csv",
                    "record_id": row["record_id"],
                    "problem": "pesticide key is not reproducible from the released identity",
                    "expected": expected_pesticide_key,
                    "actual": row["pesticide_key"],
                }
            )
        if row["food_key"] != expected_food_key:
            problems.append(
                {
                    "file": "pesticide_limits_long.csv",
                    "record_id": row["record_id"],
                    "problem": "food key is not reproducible from the released Chinese label",
                    "expected": expected_food_key,
                    "actual": row["food_key"],
                }
            )
        pesticide_by_key[row["pesticide_key"]].add(
            (row["pesticide_zh"], row["pesticide_en"])
        )
        pesticide_foods[row["food_key"]].add(row["food_zh"])

    vet_pairs = {
        (row["drug_zh"], row["drug_en"])
        for row in package.rows("vetdrug_limits_long.csv")
        if row["drug_zh"] and row["drug_en"]
    }
    analyte_pairs = {
        (row["analyte_zh"], row["analyte_en"])
        for row in package.rows("pollutant_limits_long.csv")
        if row["analyte_en"]
    } | {
        (row["toxin_zh"], row["toxin_en"])
        for row in package.rows("mycotoxin_limits_long.csv")
        if row["toxin_en"]
    }
    analyte_english = {english for _, english in analyte_pairs}

    entity_rows = package.rows("entity_names_en.csv")
    entity_business_keys: list[tuple[str, str]] = []
    observed_pesticide_keys: set[str] = set()
    observed_vet_keys: set[str] = set()
    observed_analyte_keys: set[str] = set()
    for row in entity_rows:
        entity_type = row["entity_type"]
        entity_key = row["entity_key"]
        entity_business_keys.append((entity_type, entity_key))
        if entity_type == "pesticide":
            observed_pesticide_keys.add(entity_key)
            if (
                entity_key not in pesticide_by_key
                or (row["name_zh"], row["name_en"])
                not in pesticide_by_key[entity_key]
                or row["source_standard"] != "GB 2763"
            ):
                problems.append(
                    {
                        "file": "entity_names_en.csv",
                        "record_id": row["record_id"],
                        "problem": "pesticide entity key and bilingual names do not join to the same released entity",
                    }
                )
        elif entity_type == "veterinary_drug":
            expected_key = _lookup_entity_key("VDR", row["name_en"])
            observed_vet_keys.add(entity_key)
            if (
                entity_key != expected_key
                or (row["name_zh"], row["name_en"]) not in vet_pairs
                or row["source_standard"]
                not in {"MOA Announcement 235", "GB 31650", "GB 31650.1"}
            ):
                problems.append(
                    {
                        "file": "entity_names_en.csv",
                        "record_id": row["record_id"],
                        "problem": "veterinary-drug stable key or bilingual pair is not reproducible from the long table",
                    }
                )
        elif entity_type == "contaminant_or_mycotoxin":
            expected_key = _lookup_entity_key("ANL", row["name_en"])
            observed_analyte_keys.add(entity_key)
            if (
                entity_key != expected_key
                or (row["name_zh"], row["name_en"]) not in analyte_pairs
                or row["source_standard"] != "GB 2762 / GB 2761"
            ):
                problems.append(
                    {
                        "file": "entity_names_en.csv",
                        "record_id": row["record_id"],
                        "problem": "analyte stable key or bilingual pair is not reproducible from the long tables",
                    }
                )
        else:
            problems.append(
                {
                    "file": "entity_names_en.csv",
                    "record_id": row["record_id"],
                    "problem": "unknown entity_type",
                    "entity_type": entity_type,
                }
            )
    duplicate_entity_keys = len(entity_business_keys) - len(set(entity_business_keys))
    if duplicate_entity_keys:
        problems.append(
            {
                "file": "entity_names_en.csv",
                "problem": "entity_type/entity_key is not unique",
                "duplicates": duplicate_entity_keys,
            }
        )

    expected_vet_keys = {
        _lookup_entity_key("VDR", english)
        for _, english in vet_pairs
    }
    expected_analyte_keys = {
        _lookup_entity_key("ANL", english) for english in analyte_english
    }
    coverage_differences = {
        "pesticide": (
            set(pesticide_by_key) - observed_pesticide_keys,
            observed_pesticide_keys - set(pesticide_by_key),
        ),
        "veterinary_drug": (
            expected_vet_keys - observed_vet_keys,
            observed_vet_keys - expected_vet_keys,
        ),
        "contaminant_or_mycotoxin": (
            expected_analyte_keys - observed_analyte_keys,
            observed_analyte_keys - expected_analyte_keys,
        ),
    }
    for entity_type, (missing, unexpected) in coverage_differences.items():
        if missing or unexpected:
            problems.append(
                {
                    "file": "entity_names_en.csv",
                    "problem": "entity lookup coverage differs from released long-table identities",
                    "entity_type": entity_type,
                    "missing": sorted(missing)[:20],
                    "unexpected": sorted(unexpected)[:20],
                }
            )

    additive_rows = package.rows("additive_limits_long.csv")
    additives_by_cns: dict[str, set[str]] = defaultdict(set)
    additive_foods: dict[str, set[str]] = defaultdict(set)
    for row in additive_rows:
        additives_by_cns[row["cns_code"]].add(row["additive_zh"])
        additive_foods[row["food_code"]].add(row["food_zh"])
    for row in package.rows("additive_names_en.csv"):
        code = row["cns_code"]
        if (
            not re.fullmatch(r"\d{2}\.\d{3}", code)
            or row["entity_type"] != "food_additive"
            or row["source_standard"] != "GB 2760"
            or row["name_zh"] not in additives_by_cns.get(code, set())
            or not row["name_en"]
            or not row["source_doc"]
        ):
            problems.append(
                {
                    "file": "additive_names_en.csv",
                    "cns_code": code,
                    "problem": "CNS code structure or Chinese-name join is invalid",
                }
            )

    food_business_keys: list[tuple[str, str]] = []
    for row in package.rows("food_category_names_en.csv"):
        family = row["family"]
        food_key = row["food_key"]
        food_business_keys.append((family, food_key))
        if family == "additive":
            valid_join = row["food_zh"] in additive_foods.get(food_key, set())
        elif family == "pesticide":
            valid_join = (
                bool(re.fullmatch(r"FOD-[0-9a-f]{16}", food_key))
                and row["food_zh"] in pesticide_foods.get(food_key, set())
            )
        else:
            valid_join = False
        if (
            not valid_join
            or not row["food_en"]
            or not row["match_method"]
            or not row["evidence"]
            or not row["source_doc"]
        ):
            problems.append(
                {
                    "file": "food_category_names_en.csv",
                    "family": family,
                    "food_key": food_key,
                    "problem": "food lookup key and Chinese label do not join to the same released food entity",
                }
            )
    duplicate_food_keys = len(food_business_keys) - len(set(food_business_keys))
    if duplicate_food_keys:
        problems.append(
            {
                "file": "food_category_names_en.csv",
                "problem": "family/food_key is not unique",
                "duplicates": duplicate_food_keys,
            }
        )

    return [
        result(
            "package.lookup_integrity",
            "pass" if not problems else "fail",
            "Stable lookup keys and Chinese-side release joins are internally consistent."
            if not problems
            else "Lookup keys, CNS structure, or Chinese-side joins are inconsistent.",
            entity_rows=len(entity_rows),
            food_rows=len(food_business_keys),
            additive_name_rows=len(package.rows("additive_names_en.csv")),
            problems=problems[:50],
            problem_count=len(problems),
            interpretation_boundary=(
                "This self-contained check validates stable-key derivation and "
                "Chinese-side joins. English-label pairing remains generation-audit "
                "evidence; source-PDF vocabulary occurrence does not validate it."
            ),
        )
    ]


def _sorted_unique_strings(values: list[str]) -> list[str]:
    unique = {value for value in values if value != ""}

    def sort_key(value: str) -> tuple[bool, Decimal | str]:
        try:
            return False, Decimal(value)
        except InvalidOperation:
            return True, value

    return sorted(unique, key=sort_key)


def _expected_panel_cell(
    rows: list[dict[str, str]],
    value_column: str,
    rule_columns: tuple[str, ...],
) -> dict[str, Any]:
    rows = sorted(rows, key=lambda row: row["record_id"])
    values = _sorted_unique_strings([row[value_column] for row in rows])
    units = _sorted_unique_strings([row.get("unit", "") for row in rows])
    if not rows:
        status = "missing"
        scalar = ""
    elif len(rows) == 1:
        status = "single"
        scalar = rows[0][value_column]
    elif len(values) > 1 or len(units) > 1:
        status = "multiple_distinct_values"
        scalar = ""
    else:
        status = "multiple_same_value"
        scalar = ""
    return {
        "status": status,
        "scalar": scalar,
        "values": values,
        "units": units,
        "source_ids": [row["record_id"] for row in rows],
        "rules": [
            {column: row.get(column, "") for column in rule_columns}
            for row in rows
        ],
    }


PESTICIDE_SCOPE_COLUMNS = (
    "pesticide_zh_raw",
    "parent_category_zh",
    "food_raw",
    "limit_qualifier",
    "is_temporary",
)


def _normalise_pesticide_scope_text(value: str) -> str:
    """Canonicalise typography while retaining scope-bearing content."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.translate(
        str.maketrans(
            {
                "、": ",",
                "，": ",",
                "﹐": ",",
                "；": ";",
                "﹔": ";",
                "：": ":",
                "﹕": ":",
                "。": ".",
                "．": ".",
                "﹒": ".",
                "‐": "-",
                "‑": "-",
                "‒": "-",
                "–": "-",
                "—": "-",
                "−": "-",
                "≦": "≤",
                "⩽": "≤",
                "≧": "≥",
                "⩾": "≥",
                "“": '"',
                "”": '"',
                "‘": "'",
                "’": "'",
                "【": "[",
                "】": "]",
                "•": "·",
                "‧": "·",
            }
        )
    )
    text = re.sub(r"[\s\u200b\u200c\u200d\ufeff]+", "", text)
    text = text.replace('"', "").replace("'", "")
    kept = []
    for index, character in enumerate(text):
        previous = text[index - 1] if index else ""
        following = text[index + 1] if index + 1 < len(text) else ""
        between_digits = previous.isdigit() and following.isdigit()
        if character in {",", ";"}:
            if between_digits:
                kept.append(",")
            continue
        if character in {":", "."}:
            if between_digits:
                kept.append(character)
            continue
        kept.append(character)
    return "".join(kept).casefold()


def _normalise_temporary_flag(value: str) -> str:
    text = _normalise_pesticide_scope_text(value)
    if text in {"", "0", "false", "no", "n", "否"}:
        return "0"
    if text in {"1", "true", "yes", "y", "是"}:
        return "1"
    return text


def _pesticide_scope_signature(rule: dict[str, str]) -> tuple[str, ...]:
    signature = []
    for column in PESTICIDE_SCOPE_COLUMNS:
        value = rule.get(column, "")
        signature.append(
            _normalise_temporary_flag(value)
            if column == "is_temporary"
            else _normalise_pesticide_scope_text(value)
        )
    return tuple(signature)


def _pesticide_has_unresolved_scope(rule: dict[str, str]) -> bool:
    raw_review_status = unicodedata.normalize(
        "NFKC", str(rule.get("review_status", "") or "")
    ).casefold()
    review_status = _normalise_pesticide_scope_text(raw_review_status)
    qualifier = _normalise_pesticide_scope_text(rule.get("limit_qualifier", ""))
    unresolved_words = (
        "unresolved",
        "uncertain",
        "ambiguous",
        "pending",
        "quarantin",
        "待核",
        "需核",
        "需复核",
        "不可靠",
        "存疑",
    )
    if any(word in review_status or word in qualifier for word in unresolved_words):
        return True
    if re.fullmatch(r"[*∗]?[a-z]", qualifier, flags=re.IGNORECASE):
        return True
    return bool(re.search(r"(?:^|[;,|])\s*review_", raw_review_status))


def _expected_pesticide_cell(
    rows: list[dict[str, str]],
    rule_columns: tuple[str, ...],
) -> dict[str, Any]:
    rows = sorted(rows, key=lambda row: row["record_id"])
    values = _sorted_unique_strings([row.get("limit_value", "") for row in rows])
    units = _sorted_unique_strings([row.get("unit", "") for row in rows])
    if not rows:
        status = "missing"
        scalar = ""
    elif len(rows) == 1:
        status = "single_rule"
        scalar = rows[0].get("limit_value", "")
    elif len(values) <= 1:
        status = "multiple_rules_same_value"
        scalar = ""
    else:
        status = "multiple_rules_distinct_values"
        scalar = ""
    edition_source_ids = _sorted_unique_strings(
        [row.get("edition_source_id", "") for row in rows]
    )
    extraction_source_ids = _sorted_unique_strings(
        [row.get("extraction_source_id", "") for row in rows]
    )
    return {
        "status": status,
        "scalar": scalar,
        "values": values,
        "units": units,
        "source_ids": _sorted_unique_strings(
            edition_source_ids + extraction_source_ids
        ),
        "edition_source_ids": edition_source_ids,
        "extraction_source_ids": extraction_source_ids,
        "source_record_ids": [row["record_id"] for row in rows],
        "rules": [
            {column: row.get(column, "") for column in rule_columns}
            for row in rows
        ],
        "candidate_count": len(rows),
        "distinct_value_count": len(values),
    }


def _expected_pesticide_trend(cells: list[dict[str, Any]]) -> str:
    present = [cell for cell in cells if cell["status"] != "missing"]
    if any(cell["candidate_count"] > 1 for cell in present):
        return "incomparable_multiple_rules"
    if len(present) == 1:
        return "single_version"
    units = {
        _normalise_pesticide_scope_text(cell["rules"][0].get("unit", ""))
        for cell in present
    }
    if len(units) > 1:
        return "incomparable_units"
    if any(_pesticide_has_unresolved_scope(cell["rules"][0]) for cell in present):
        return "incomparable_unresolved_review_or_source_qualifier"
    if len({_pesticide_scope_signature(cell["rules"][0]) for cell in present}) > 1:
        return "incomparable_scope_text"
    numbers = []
    for cell in present:
        try:
            number = Decimal(cell["scalar"])
        except InvalidOperation:
            return "incomparable_non_numeric"
        if not number.is_finite():
            return "incomparable_non_numeric"
        numbers.append(number)
    if len(set(numbers)) == 1:
        return "stable"
    nonincreasing = all(left >= right for left, right in zip(numbers, numbers[1:]))
    nondecreasing = all(left <= right for left, right in zip(numbers, numbers[1:]))
    if nonincreasing and numbers[-1] < numbers[0]:
        return "tightened"
    if nondecreasing and numbers[-1] > numbers[0]:
        return "relaxed"
    return "fluctuation"


def _expected_panel_trend(
    cells: list[dict[str, Any]],
    scope_columns: tuple[str, ...] = (),
) -> str:
    present = [cell for cell in cells if cell["status"] != "missing"]
    if not present:
        return "no_records"
    if any(cell["status"] != "single" for cell in present):
        return "incomparable_multiple_rules"
    if len(present) == 1:
        return "single_version"
    units = {cell["units"][0] if cell["units"] else "" for cell in present}
    if len(units) > 1:
        return "incomparable_units"
    if scope_columns:
        scope_signatures = {
            tuple(
                _normalise_scope_text(cell["rules"][0].get(column, ""))
                for column in scope_columns
            )
            for cell in present
        }
        if len(scope_signatures) > 1:
            return "incomparable_scope_text"
    values = [cell["scalar"] for cell in present]
    if values and all(value == "GMP" for value in values):
        return "stable_gmp"
    numbers = []
    for value in values:
        try:
            number = Decimal(value)
        except InvalidOperation:
            return "incomparable_non_numeric"
        if not number.is_finite():
            return "incomparable_non_numeric"
        numbers.append(number)
    if len(set(numbers)) == 1:
        return "stable"
    nonincreasing = all(left >= right for left, right in zip(numbers, numbers[1:]))
    nondecreasing = all(left <= right for left, right in zip(numbers, numbers[1:]))
    if nonincreasing and numbers[-1] < numbers[0]:
        return "tightened"
    if nondecreasing and numbers[-1] > numbers[0]:
        return "relaxed"
    return "fluctuation"


def check_panel_lineage(package: Package) -> list[dict[str, Any]]:
    problems = []
    summaries = {}
    for panel_file, spec in PANEL_LINEAGE.items():
        long_rows = package.rows(spec["long_file"])
        normalise = _normalise_cns if panel_file == "additive_panel.csv" else lambda value: value
        long_index: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
        for row in long_rows:
            key_parts = [normalise(row[column]) if column == "cns_code" else row[column] for column in spec["long_key"]]
            long_index[tuple(key_parts + [row["version_year"]])].append(row)
        checked_cells = 0
        panel_rows = package.rows(panel_file)
        panel_keys = set()
        referenced_long_ids: list[str] = []
        for panel_row in panel_rows:
            panel_key = [
                normalise(panel_row[column]) if column == "cns_code" else panel_row[column]
                for column in spec["panel_key"]
            ]
            if tuple(panel_key) in panel_keys:
                problems.append(
                    {
                        "file": panel_file,
                        "record_id": panel_row["record_id"],
                        "problem": "duplicate panel business key",
                    }
                )
            panel_keys.add(tuple(panel_key))
            expected_cells = []
            for year in spec["years"]:
                checked_cells += 1
                expected_rows = long_index.get(tuple(panel_key + [year]), [])
                if panel_file == "pesticide_panel.csv":
                    expected = _expected_pesticide_cell(
                        expected_rows,
                        spec["rule_columns"],
                    )
                    json_fields = (
                        "values",
                        "units",
                        "source_record_ids",
                        "source_ids",
                        "edition_source_ids",
                        "extraction_source_ids",
                        "rules",
                    )
                else:
                    expected = _expected_panel_cell(
                        expected_rows,
                        spec["value_column"],
                        spec["rule_columns"],
                    )
                    source_record_ids = expected.pop("source_ids")
                    expected = {
                        **expected,
                        "source_record_ids": source_record_ids,
                        "candidate_count": len(expected_rows),
                        "distinct_value_count": len(expected["values"]),
                    }
                    json_fields = (
                        "values",
                        "units",
                        "source_record_ids",
                        "rules",
                    )
                expected_cells.append(expected)
                try:
                    decoded = {
                        field: json.loads(panel_row[f"{field}_{year}"])
                        for field in json_fields
                    }
                except (json.JSONDecodeError, TypeError):
                    problems.append({"file": panel_file, "record_id": panel_row["record_id"], "year": year, "problem": "invalid JSON"})
                    continue
                try:
                    candidate_count = int(panel_row[f"candidate_count_{year}"])
                except (TypeError, ValueError):
                    candidate_count = None
                try:
                    distinct_count = int(panel_row[f"distinct_value_count_{year}"])
                except (TypeError, ValueError):
                    distinct_count = None
                actual = {
                    "status": panel_row[f"status_{year}"],
                    "scalar": panel_row[f"v{year}"],
                    **decoded,
                    "candidate_count": candidate_count,
                    "distinct_value_count": distinct_count,
                }
                mismatched_fields = [
                    field
                    for field, expected_value in expected.items()
                    if actual[field] != expected_value
                ]
                if mismatched_fields:
                    problems.append(
                        {
                            "file": panel_file,
                            "record_id": panel_row["record_id"],
                            "year": year,
                            "problem": "panel cell does not reproduce its long-table rules",
                            "mismatched_fields": mismatched_fields,
                        }
                    )
                if panel_file == "pesticide_panel.csv":
                    referenced_long_ids.extend(decoded["source_record_ids"])
            expected_trend = (
                _expected_pesticide_trend(expected_cells)
                if panel_file == "pesticide_panel.csv"
                else _expected_panel_trend(
                    expected_cells,
                    spec.get("scope_columns", ()),
                )
            )
            if panel_row["trend"] != expected_trend:
                problems.append(
                    {
                        "file": panel_file,
                        "record_id": panel_row["record_id"],
                        "problem": "trend does not reproduce the edition cells",
                        "expected": expected_trend,
                        "actual": panel_row["trend"],
                    }
                )
            if panel_file == "pesticide_panel.csv":
                expected_versions = sum(cell["status"] != "missing" for cell in expected_cells)
                try:
                    actual_versions = int(panel_row["n_versions"])
                except (TypeError, ValueError):
                    actual_versions = None
                if actual_versions != expected_versions:
                    problems.append(
                        {
                            "file": panel_file,
                            "record_id": panel_row["record_id"],
                            "problem": "n_versions does not reproduce edition cells",
                        }
                    )
                all_rows = [
                    row
                    for year in spec["years"]
                    for row in long_index.get(tuple(panel_key + [year]), [])
                ]
                if all_rows:
                    year_rank = {
                        year: index for index, year in enumerate(spec["years"])
                    }
                    display = max(
                        all_rows,
                        key=lambda row: (
                            year_rank[row["version_year"]],
                            row["record_id"],
                        ),
                    )
                    pesticide_expected = {
                        "pesticide_zh": display["pesticide_zh"],
                        "pesticide_names_zh": _sorted_unique_strings(
                            [row["pesticide_zh"] for row in all_rows]
                        ),
                        "food_zh": display["food_zh"],
                        "food_names_zh": _sorted_unique_strings(
                            [row["food_zh"] for row in all_rows]
                        ),
                    }
                    try:
                        pesticide_actual = {
                            "pesticide_zh": panel_row["pesticide_zh"],
                            "pesticide_names_zh": json.loads(
                                panel_row["pesticide_names_zh"]
                            ),
                            "food_zh": panel_row["food_zh"],
                            "food_names_zh": json.loads(
                                panel_row["food_names_zh"]
                            ),
                        }
                    except (json.JSONDecodeError, TypeError):
                        pesticide_actual = {}
                    if pesticide_actual != pesticide_expected:
                        problems.append(
                            {
                                "file": panel_file,
                                "record_id": panel_row["record_id"],
                                "problem": "pesticide display and name arrays do not reproduce long-table rows",
                            }
                        )
            else:
                all_rows = [
                    row
                    for year in spec["years"]
                    for row in long_index.get(tuple(panel_key + [year]), [])
                ]
                display = sorted(
                    all_rows,
                    key=lambda row: (row["version_year"], row["record_id"]),
                    reverse=True,
                )[0]
                additive_expected = {
                    "additive_zh": display["additive_zh"],
                    "additive_names_zh": _sorted_unique_strings(
                        [row["additive_zh"] for row in all_rows]
                    ),
                    "ins_codes": _sorted_unique_strings(
                        [row["ins_code"] for row in all_rows]
                    ),
                    "food_zh": display["food_zh"],
                    "food_names_zh": _sorted_unique_strings(
                        [row["food_zh"] for row in all_rows]
                    ),
                }
                additive_actual = {
                    "additive_zh": panel_row["additive_zh"],
                    "additive_names_zh": json.loads(panel_row["additive_names_zh"]),
                    "ins_codes": json.loads(panel_row["ins_codes"]),
                    "food_zh": panel_row["food_zh"],
                    "food_names_zh": json.loads(panel_row["food_names_zh"]),
                }
                if additive_actual != additive_expected:
                    problems.append(
                        {
                            "file": panel_file,
                            "record_id": panel_row["record_id"],
                            "problem": "additive display and name arrays do not reproduce long-table rows",
                        }
                    )
        long_keys = {key[:-1] for key in long_index}
        if panel_keys != long_keys:
            problems.append(
                {
                    "file": panel_file,
                    "problem": "panel keys do not cover exactly the long-table groups",
                    "missing_key_count": len(long_keys - panel_keys),
                    "unexpected_key_count": len(panel_keys - long_keys),
                }
            )
        if panel_file == "pesticide_panel.csv":
            actual_lineage = Counter(referenced_long_ids)
            expected_lineage = Counter(row["record_id"] for row in long_rows)
            if actual_lineage != expected_lineage:
                problems.append(
                    {
                        "file": panel_file,
                        "problem": "panel record lineage does not conserve the long table exactly once",
                        "missing_reference_count": sum(
                            (expected_lineage - actual_lineage).values()
                        ),
                        "duplicate_or_unknown_reference_count": sum(
                            (actual_lineage - expected_lineage).values()
                        ),
                    }
                )
        summaries[panel_file] = {"rows": len(panel_rows), "cells_checked": checked_cells}
    return [
        result(
            "package.panel_lineage",
            "pass" if not problems else "fail",
            "Multi-value panel cells preserve long-record lineage and comparability." if not problems else "Panel lineage or comparability problems were found.",
            summaries=summaries,
            problems=problems[:50],
            problem_count=len(problems),
        )
    ]


def check_missing_value_contract(package: Package) -> list[dict[str, Any]]:
    placeholders = {"NA", "N/A", "null", "NULL", "None", ".", "-"}
    unexpected = []
    for name in CSV_FILES:
        if name == "data_dictionary.csv":
            continue
        for row_index, row in enumerate(package.rows(name), 2):
            for column, value in row.items():
                if value in placeholders:
                    unexpected.append({"file": name, "row": row_index, "column": column, "value": value})
    additive = package.rows("additive_limits_long.csv")
    additive_errors = [
        row["record_id"]
        for row in additive
        if (row["max_use"] == "GMP" and row["unit"] != "")
        or (row["max_use"] != "GMP" and row["unit"] == "")
    ]
    problems = unexpected or additive_errors
    return [
        result(
            "package.missing_values",
            "fail" if problems else "pass",
            "Blank fields and the GMP sentinel follow the documented missing-value contract." if not problems else "Undocumented placeholders or GMP/unit inconsistencies were found.",
            unexpected_placeholders=unexpected[:50],
            additive_gmp_unit_errors=additive_errors[:50],
        )
    ]


def check_pollutant_normalization(package: Package) -> list[dict[str, Any]]:
    rows = package.rows("pollutant_limits_long.csv")
    if "normalization_status" not in package.header("pollutant_limits_long.csv"):
        return [
            result(
                "package.pollutant_normalization",
                "fail",
                "pollutant_limits_long.csv lacks the required normalization_status field.",
            )
        ]
    problems = []
    for row in rows:
        unit = row["unit"]
        raw = row["limit_value"]
        normalised = row["limit_mgkg"]
        status = row["normalization_status"]
        if unit == "mg/kg":
            expected_status = "already_mg_per_kg"
            expected_value = _normalise_decimal(raw)
        elif unit == "μg/kg":
            expected_status = "converted_mass_per_mass"
            expected_value = _normalise_decimal(str(Decimal(raw) * Decimal("0.001")))
        elif unit == "mg/L":
            expected_status = "density_required"
            expected_value = ""
        else:
            problems.append(
                {
                    "record_id": row["record_id"],
                    "problem": "unsupported or missing unit",
                    "unit": unit,
                }
            )
            continue
        if status != expected_status or _normalise_decimal(normalised) != expected_value:
            problems.append(
                {
                    "record_id": row["record_id"],
                    "unit": unit,
                    "limit_value": raw,
                    "limit_mgkg": normalised,
                    "normalization_status": status,
                    "expected_limit_mgkg": expected_value,
                    "expected_status": expected_status,
                }
            )
    return [
        result(
            "package.pollutant_normalization",
            "pass" if not problems else "fail",
            "Pollutant mass-per-mass conversions and density-required records follow the declared contract."
            if not problems
            else "Pollutant normalisation values or statuses violate the declared contract.",
            problems=problems[:50],
            problem_count=len(problems),
        )
    ]


def _comparable_regulatory_value(
    value: str, unit: str
) -> tuple[str, Decimal] | None:
    factors = {
        "mg/kg": ("mass_per_mass", Decimal("1")),
        "μg/kg": ("mass_per_mass", Decimal("0.001")),
        "µg/kg": ("mass_per_mass", Decimal("0.001")),
        "g/kg": ("mass_per_mass", Decimal("1000")),
        "mg/L": ("mass_per_volume", Decimal("1")),
        "μg/L": ("mass_per_volume", Decimal("0.001")),
        "µg/L": ("mass_per_volume", Decimal("0.001")),
        "g/L": ("mass_per_volume", Decimal("1000")),
    }
    if unit not in factors:
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    dimension, factor = factors[unit]
    return dimension, number * factor


def _ordered_numeric_trend(
    values: list[Decimal], *, single_status: str
) -> str:
    if not values:
        return "no_records"
    if len(values) == 1:
        return single_status
    if len(set(values)) == 1:
        return "stable"
    nonincreasing = all(
        left >= right for left, right in zip(values, values[1:])
    )
    nondecreasing = all(
        left <= right for left, right in zip(values, values[1:])
    )
    if nonincreasing and values[-1] < values[0]:
        return "tightened"
    if nondecreasing and values[-1] > values[0]:
        return "relaxed"
    return "fluctuation"


def _expected_pollutant_coverage(present: tuple[bool, bool, bool, bool]) -> str:
    coverage_by_pattern = {
        (True, True, True, True): "all_editions",
        (False, True, True, True): "introduced_2017",
        (False, False, True, True): "introduced_2022",
        (False, False, False, True): "introduced_2025",
        (True, False, False, False): "ended_2012_or_renamed",
        (True, True, False, False): "ended_2017_or_renamed",
    }
    return coverage_by_pattern.get(present, "internal_gap_review")


def check_pollutant_panel_contract(package: Package) -> list[dict[str, Any]]:
    years = ("2012", "2017", "2022", "2025")
    long_index: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    long_rows = package.rows("pollutant_limits_long.csv")
    analyte_pairs = {
        (row["analyte_zh"], row["analyte_en"]) for row in long_rows
    }
    for row in long_rows:
        long_index[(row["version_year"], row["analyte_zh"], row["food_category_zh"])].append(row)

    problems: list[dict[str, Any]] = []
    category_rows = package.rows("pollutant_category_panel.csv")
    for row in category_rows:
        present = 0
        represented_units = []
        represented_bases = []
        comparable_values: list[tuple[str, Decimal] | None] = []
        presence_pattern: list[bool] = []
        if (
            row["standard"] != "GB 2762"
            or (row["analyte_zh"], row["analyte_en"]) not in analyte_pairs
        ):
            problems.append(
                {
                    "file": "pollutant_category_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "panel standard or analyte bilingual identity is inconsistent",
                }
            )
        for year in years:
            status = row[f"cell_status_{year}"]
            value = row[f"v{year}"]
            unit = row[f"unit_{year}"]
            basis = row[f"basis_{year}"]
            source_category = row[f"source_category_{year}"]
            if status == "missing":
                presence_pattern.append(False)
                if any((value, unit, basis, source_category)):
                    problems.append(
                        {
                            "file": "pollutant_category_panel.csv",
                            "record_id": row["record_id"],
                            "year": year,
                            "problem": "missing cell carries a value, unit, basis, or source category",
                        }
                    )
                continue
            presence_pattern.append(True)
            if status != "single" or not value or not unit or not source_category:
                problems.append(
                    {
                        "file": "pollutant_category_panel.csv",
                        "record_id": row["record_id"],
                        "year": year,
                        "problem": "populated cell violates the single-cell contract",
                    }
                )
                continue
            present += 1
            represented_units.append(unit)
            represented_bases.append(basis)
            comparable_values.append(_comparable_regulatory_value(value, unit))
            matches = long_index[(year, row["analyte_zh"], source_category)]
            exact = [
                candidate
                for candidate in matches
                if _normalise_decimal(candidate["limit_value"]) == _normalise_decimal(value)
                and candidate["unit"] == unit
                and candidate["limit_basis"] == basis
            ]
            if len(exact) != 1:
                problems.append(
                    {
                        "file": "pollutant_category_panel.csv",
                        "record_id": row["record_id"],
                        "year": year,
                        "problem": "edition cell does not trace to exactly one long-table rule",
                        "matching_long_rows": len(exact),
                    }
                )
        if int(row["n_versions"]) != present:
            problems.append(
                {
                    "file": "pollutant_category_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "n_versions does not equal populated edition cells",
                }
            )
        expected_summary = (
            represented_units[0]
            if represented_units and len(set(represented_units)) == 1
            else "跨版单位变化:" + "→".join(represented_units)
        )
        if row["unit_summary"] != expected_summary:
            problems.append(
                {
                    "file": "pollutant_category_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "unit_summary does not reproduce edition units",
                    "expected": expected_summary,
                    "actual": row["unit_summary"],
                }
            )
        expected_coverage = _expected_pollutant_coverage(
            tuple(presence_pattern)
        )
        if row["coverage_status"] != expected_coverage:
            problems.append(
                {
                    "file": "pollutant_category_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "coverage_status does not reproduce populated edition cells",
                    "expected": expected_coverage,
                    "actual": row["coverage_status"],
                }
            )
        unique_bases = set(represented_bases)
        dimensions = {
            comparable[0]
            for comparable in comparable_values
            if comparable is not None
        }
        numeric_values = [
            comparable[1]
            for comparable in comparable_values
            if comparable is not None
        ]
        if expected_coverage in {
            "ended_2012_or_renamed",
            "ended_2017_or_renamed",
        }:
            expected_trend = "incomparable_category_disappeared"
        elif (
            len(comparable_values) != len(numeric_values)
            or len(unique_bases) > 1
            or len(dimensions) > 1
        ):
            expected_trend = "incomparable_unit_dimension_or_value"
        else:
            expected_trend = _ordered_numeric_trend(
                numeric_values,
                single_status="single_version",
            )
        if row["trend"] != expected_trend:
            problems.append(
                {
                    "file": "pollutant_category_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "trend does not reproduce edition values, units, bases, and coverage",
                    "expected": expected_trend,
                    "actual": row["trend"],
                }
            )

    member_rows = package.rows("pollutant_member_panel.csv")
    member_keys: list[tuple[str, str]] = []
    for row in member_rows:
        member_keys.append((row["analyte_zh"], row["food_member_zh"]))
        represented_bases = []
        represented_units = []
        comparable_values: list[tuple[str, Decimal] | None] = []
        represented_hosts = []
        if (
            row["standard"] != "GB 2762"
            or (row["analyte_zh"], row["analyte_en"]) not in analyte_pairs
        ):
            problems.append(
                {
                    "file": "pollutant_member_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "member standard or analyte bilingual identity is inconsistent",
                }
            )
        for year in years:
            value = row[f"v{year}"]
            unit = row[f"unit_{year}"]
            basis = row[f"basis_{year}"]
            host = row[f"host_category_{year}"]
            if value:
                represented_bases.append(basis)
                represented_units.append(unit)
                represented_hosts.append(host)
                comparable_values.append(
                    _comparable_regulatory_value(value, unit)
                )
                if not unit or not host:
                    problems.append(
                        {
                            "file": "pollutant_member_panel.csv",
                            "record_id": row["record_id"],
                            "year": year,
                            "problem": "member value lacks unit or host category",
                        }
                    )
                matches = long_index[(year, row["analyte_zh"], host)]
                exact = [
                    candidate
                    for candidate in matches
                    if _normalise_decimal(candidate["limit_value"])
                    == _normalise_decimal(value)
                    and candidate["unit"] == unit
                    and candidate["limit_basis"] == basis
                ]
                if len(exact) != 1:
                    problems.append(
                        {
                            "file": "pollutant_member_panel.csv",
                            "record_id": row["record_id"],
                            "year": year,
                            "problem": "member cell does not trace to exactly one long-table host rule",
                            "matching_long_rows": len(exact),
                        }
                    )
            elif any((unit, basis, host)):
                problems.append(
                    {
                        "file": "pollutant_member_panel.csv",
                        "record_id": row["record_id"],
                        "year": year,
                        "problem": "empty member value carries unit, basis, or host category",
                    }
                )
        unique_bases = set(represented_bases)
        if not unique_bases or unique_bases == {""}:
            expected_basis = ""
        elif len(unique_bases) == 1:
            expected_basis = next(iter(unique_bases))
        else:
            expected_basis = "varies_by_version"
        summary_basis = row["limit_basis"]
        malformed_separator = (
            summary_basis.startswith(";")
            or summary_basis.endswith(";")
            or ";;" in summary_basis
        )
        if summary_basis != expected_basis or malformed_separator:
            problems.append(
                {
                    "file": "pollutant_member_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "limit_basis does not reproduce the edition basis states",
                    "expected": expected_basis,
                    "actual": summary_basis,
                }
            )
        unit_set = set(represented_units)
        density_mismatch = "mg/L" in unit_set and len(unit_set) > 1
        if (density_mismatch or len(unique_bases) > 1) and not row["trend"].startswith("incomparable_"):
            problems.append(
                {
                    "file": "pollutant_member_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "unit- or basis-changing member received a scalar trend",
                }
            )
        dimensions = {
            comparable[0]
            for comparable in comparable_values
            if comparable is not None
        }
        numeric_values = [
            comparable[1]
            for comparable in comparable_values
            if comparable is not None
        ]
        if (
            len(comparable_values) != len(numeric_values)
            or len(unique_bases) > 1
            or len(dimensions) > 1
        ):
            expected_trend = "incomparable_basis_unit_or_value"
        else:
            expected_trend = _ordered_numeric_trend(
                numeric_values,
                single_status="single_version",
            )
        if row["trend"] != expected_trend:
            problems.append(
                {
                    "file": "pollutant_member_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "member trend does not reproduce edition values, units, and bases",
                    "expected": expected_trend,
                    "actual": row["trend"],
                }
            )
        expected_restructured = "yes" if len(set(represented_hosts)) > 1 else "no"
        if row["category_restructured"] != expected_restructured:
            problems.append(
                {
                    "file": "pollutant_member_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "category_restructured does not reproduce edition host categories",
                    "expected": expected_restructured,
                    "actual": row["category_restructured"],
                }
            )

    duplicate_member_keys = len(member_keys) - len(set(member_keys))
    if duplicate_member_keys:
        problems.append(
            {
                "file": "pollutant_member_panel.csv",
                "problem": "member panel business keys are duplicated",
                "duplicates": duplicate_member_keys,
            }
        )

    return [
        result(
            "package.pollutant_panels",
            "pass" if not problems else "fail",
            "Pollutant category and member cells preserve edition units, bases, and long-table lineage."
            if not problems
            else "Pollutant panel lineage or comparability contracts were violated.",
            category_rows=len(category_rows),
            member_rows=len(member_rows),
            problems=problems[:50],
            problem_count=len(problems),
            interpretation_boundary=(
                "Edition host/value cells are linked to released long-table rules; "
                "canonical category labels and member-to-host expansion are supplied "
                "by frozen crosswalks that are not revalidated from this package alone."
            ),
        )
    ]


def _decimal_value(value: str) -> Decimal | None:
    try:
        parsed = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _slash_decimal_set(value: str) -> set[Decimal] | None:
    if not value:
        return set()
    parsed = {_decimal_value(part) for part in value.split("/")}
    if None in parsed:
        return None
    return {item for item in parsed if item is not None}


def check_mycotoxin_panel_lineage(package: Package) -> list[dict[str, Any]]:
    """Recompute mycotoxin panel values, trends, and member host lineage."""
    years = ("2005", "2011", "2017")
    long_rows = package.rows("mycotoxin_limits_long.csv")
    long_index: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    long_value_counter: Counter[tuple[str, str, Decimal]] = Counter()
    toxin_pairs = {(row["toxin_zh"], row["toxin_en"]) for row in long_rows}
    for row in long_rows:
        long_index[
            (row["version_year"], row["toxin_zh"], row["food_category_zh"])
        ].append(row)
        parsed = _decimal_value(row["limit_value"])
        if parsed is not None:
            long_value_counter[(row["version_year"], row["toxin_zh"], parsed)] += 1

    problems: list[dict[str, Any]] = []
    panel_rows = package.rows("mycotoxin_panel.csv")
    panel_keys: list[tuple[str, str]] = []
    panel_value_counter: Counter[tuple[str, str, Decimal]] = Counter()
    for row in panel_rows:
        panel_keys.append((row["toxin_zh"], row["food_zh"]))
        values: list[Decimal] = []
        if (
            row["standard"] != "GB 2761"
            or row["unit"] != "μg/kg"
            or (row["toxin_zh"], row["toxin_en"]) not in toxin_pairs
        ):
            problems.append(
                {
                    "file": "mycotoxin_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "panel standard, unit, or toxin bilingual identity is inconsistent",
                }
            )
        for year in years:
            value = row[f"v{year}"]
            if not value:
                continue
            parsed = _decimal_value(value)
            if parsed is None:
                problems.append(
                    {
                        "file": "mycotoxin_panel.csv",
                        "record_id": row["record_id"],
                        "year": year,
                        "problem": "panel value is not a finite number",
                    }
                )
                continue
            values.append(parsed)
            panel_value_counter[(year, row["toxin_zh"], parsed)] += 1
        expected_trend = _ordered_numeric_trend(
            values, single_status="single_version"
        )
        if row["trend"] != expected_trend:
            problems.append(
                {
                    "file": "mycotoxin_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "trend does not reproduce edition values",
                    "expected": expected_trend,
                    "actual": row["trend"],
                }
            )
    if len(panel_keys) != len(set(panel_keys)):
        problems.append(
            {
                "file": "mycotoxin_panel.csv",
                "problem": "panel business keys are duplicated",
            }
        )
    if panel_value_counter != long_value_counter:
        problems.append(
            {
                "file": "mycotoxin_panel.csv",
                "problem": "panel cells do not conserve the long-table year/toxin/value multiset",
                "missing_values": sum((long_value_counter - panel_value_counter).values()),
                "unexpected_values": sum((panel_value_counter - long_value_counter).values()),
            }
        )

    member_rows = package.rows("mycotoxin_member_panel.csv")
    member_keys: list[tuple[str, str]] = []
    for row in member_rows:
        member_keys.append((row["toxin_zh"], row["food_member_zh"]))
        values: list[Decimal] = []
        hosts: list[str] = []
        if row["standard"] != "GB 2761" or row["unit"] != "mg/kg":
            problems.append(
                {
                    "file": "mycotoxin_member_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "member standard or unit is inconsistent",
                }
            )
        for year in years:
            value = row[f"v{year}"]
            host = row[f"host_category_{year}"]
            if not value:
                if host:
                    problems.append(
                        {
                            "file": "mycotoxin_member_panel.csv",
                            "record_id": row["record_id"],
                            "year": year,
                            "problem": "empty member value carries a host category",
                        }
                    )
                continue
            parsed = _decimal_value(value)
            if parsed is None or not host:
                problems.append(
                    {
                        "file": "mycotoxin_member_panel.csv",
                        "record_id": row["record_id"],
                        "year": year,
                        "problem": "member value is nonnumeric or lacks a host category",
                    }
                )
                continue
            values.append(parsed)
            hosts.append(host)
            matches = [
                candidate
                for candidate in long_index[(year, row["toxin_zh"], host)]
                if _decimal_value(candidate["limit_value"])
                == parsed * Decimal("1000")
                and candidate["unit"] in {"μg/kg", "µg/kg"}
            ]
            if len(matches) != 1:
                problems.append(
                    {
                        "file": "mycotoxin_member_panel.csv",
                        "record_id": row["record_id"],
                        "year": year,
                        "problem": "member value does not trace to exactly one long-table host rule",
                        "matching_long_rows": len(matches),
                    }
                )
        expected_trend = _ordered_numeric_trend(
            values, single_status="single_version_unmatched"
        )
        if row["trend"] != expected_trend:
            problems.append(
                {
                    "file": "mycotoxin_member_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "member trend does not reproduce edition values",
                    "expected": expected_trend,
                    "actual": row["trend"],
                }
            )
        expected_restructured = "yes" if len(set(hosts)) > 1 else "no"
        if row["category_restructured"] != expected_restructured:
            problems.append(
                {
                    "file": "mycotoxin_member_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "category_restructured does not reproduce host categories",
                    "expected": expected_restructured,
                    "actual": row["category_restructured"],
                }
            )
    if len(member_keys) != len(set(member_keys)):
        problems.append(
            {
                "file": "mycotoxin_member_panel.csv",
                "problem": "member business keys are duplicated",
            }
        )

    return [
        result(
            "package.mycotoxin_panel_lineage",
            "pass" if not problems else "fail",
            "Mycotoxin summary value multisets and trends, plus member host-rule values, reproduce the long table."
            if not problems
            else "Mycotoxin panel or member lineage is inconsistent.",
            panel_rows=len(panel_rows),
            member_rows=len(member_rows),
            long_rows=len(long_rows),
            problems=problems[:50],
            problem_count=len(problems),
            interpretation_boundary=(
                "The strictness panel conserves the year/toxin/value multiset, while "
                "summary food alignment and member expansion are supplied by frozen "
                "crosswalks that are not revalidated from this package alone."
            ),
        )
    ]


def _expected_vet_panel_trend(
    values_2002: set[Decimal], values_2019: set[Decimal]
) -> str:
    if values_2002 and not values_2019:
        return "single_2002_unmatched"
    if values_2019 and not values_2002:
        return "single_2019_unmatched"
    if not values_2002 and not values_2019:
        return "no_records"
    if len(values_2002) != 1 or len(values_2019) != 1:
        return "unresolved_multiple_animals"
    old_value = next(iter(values_2002))
    new_value = next(iter(values_2019))
    if old_value == new_value:
        return "stable"
    return "tightened" if new_value < old_value else "relaxed"


def check_vetdrug_panel_lineage(package: Package) -> list[dict[str, Any]]:
    """Recompute veterinary-drug summary and member values from long rules."""
    long_rows = package.rows("vetdrug_limits_long.csv")
    panel_long_values: dict[tuple[str, str, str], set[Decimal]] = defaultdict(set)
    member_long_values: dict[tuple[str, str, str], set[Decimal]] = defaultdict(set)
    long_identity_pairs: set[tuple[str, str]] = set()
    for row in long_rows:
        parsed = _decimal_value(row["limit_value"])
        if parsed is None:
            continue
        long_identity_pairs.add(
            (row["drug_zh"], _normalise_english_entity(row["drug_en"]))
        )
        if row["version_year"] in {"2002", "2019"}:
            english_identity = _normalise_english_entity(row["drug_en"])
            panel_long_values[
                (
                    row["version_year"],
                    english_identity,
                    row["tissue_zh"],
                )
            ].add(parsed)
        member_long_values[
            (
                row["version_year"],
                row["drug_zh"],
                row["tissue_zh"],
            )
        ].add(parsed * Decimal("0.001"))

    problems: list[dict[str, Any]] = []
    panel_rows = package.rows("vetdrug_panel.csv")
    panel_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in panel_rows:
        key = (_normalise_english_entity(row["drug_en"]), row["tissue_zh"])
        if key in panel_by_key:
            problems.append(
                {
                    "file": "vetdrug_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "panel business key is duplicated",
                }
            )
        panel_by_key[key] = row
        if row["standard"] != "GB 31650" or row["unit"] != "μg/kg":
            problems.append(
                {
                    "file": "vetdrug_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "panel standard or unit is inconsistent",
                }
            )
        if (row["drug_zh"], key[0]) not in long_identity_pairs:
            problems.append(
                {
                    "file": "vetdrug_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "panel Chinese and English drug identities do not join to the same long-table group",
                }
            )
        actual_2002 = _slash_decimal_set(row["v2002"])
        actual_2019 = _slash_decimal_set(row["v2019"])
        expected_2002 = panel_long_values.get(("2002", *key), set())
        expected_2019 = panel_long_values.get(("2019", *key), set())
        if actual_2002 is None or actual_2019 is None:
            problems.append(
                {
                    "file": "vetdrug_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "slash-delimited panel value is not numeric",
                }
            )
            continue
        if actual_2002 != expected_2002 or actual_2019 != expected_2019:
            problems.append(
                {
                    "file": "vetdrug_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "panel values do not reproduce all animal-level long rules",
                    "expected_2002": sorted(str(value) for value in expected_2002),
                    "expected_2019": sorted(str(value) for value in expected_2019),
                }
            )
        expected_trend = _expected_vet_panel_trend(
            expected_2002, expected_2019
        )
        if row["trend"] != expected_trend:
            problems.append(
                {
                    "file": "vetdrug_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "panel trend does not reproduce long-table values",
                    "expected": expected_trend,
                    "actual": row["trend"],
                }
            )
    expected_panel_keys = {
        (english_key, tissue)
        for _, english_key, tissue in panel_long_values
    }
    actual_panel_keys = set(panel_by_key)
    if actual_panel_keys != expected_panel_keys:
        problems.append(
            {
                "file": "vetdrug_panel.csv",
                "problem": "panel keys do not cover exactly the 2002/2019 long-table groups",
                "missing_key_count": len(expected_panel_keys - actual_panel_keys),
                "unexpected_key_count": len(actual_panel_keys - expected_panel_keys),
            }
        )

    member_rows = package.rows("vetdrug_member_panel.csv")
    member_keys: list[tuple[str, str, str]] = []
    for row in member_rows:
        english_identity = _normalise_english_entity(row["drug_en"])
        member_keys.append((english_identity, row["animal"], row["tissue_zh"]))
        values: list[Decimal] = []
        if row["standard"] != "GB 31650" or row["unit"] != "mg/kg":
            problems.append(
                {
                    "file": "vetdrug_member_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "member standard or unit is inconsistent",
                }
            )
        if (row["drug_zh"], english_identity) not in long_identity_pairs:
            problems.append(
                {
                    "file": "vetdrug_member_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "member Chinese and English drug identities do not form a released long-table pair",
                }
            )
        for year in ("2002", "2019", "2022"):
            value = row[f"v{year}"]
            if not value:
                continue
            parsed = _decimal_value(value)
            if parsed is None:
                problems.append(
                    {
                        "file": "vetdrug_member_panel.csv",
                        "record_id": row["record_id"],
                        "year": year,
                        "problem": "member value is not a finite number",
                    }
                )
                continue
            values.append(parsed)
            candidates = member_long_values.get(
                (year, row["drug_zh"], row["tissue_zh"]),
                set(),
            )
            if not any(abs(candidate - parsed) <= Decimal("1e-12") for candidate in candidates):
                problems.append(
                    {
                        "file": "vetdrug_member_panel.csv",
                        "record_id": row["record_id"],
                        "year": year,
                        "problem": "member value does not trace to a long-table drug/tissue rule",
                    }
                )
        expected_trend = _ordered_numeric_trend(
            values, single_status="single_version"
        )
        if row["trend"] != expected_trend:
            problems.append(
                {
                    "file": "vetdrug_member_panel.csv",
                    "record_id": row["record_id"],
                    "problem": "member trend does not reproduce edition values",
                    "expected": expected_trend,
                    "actual": row["trend"],
                }
            )
    if len(member_keys) != len(set(member_keys)):
        problems.append(
            {
                "file": "vetdrug_member_panel.csv",
                "problem": "member business keys are duplicated",
            }
        )

    return [
        result(
            "package.vetdrug_panel_lineage",
            "pass" if not problems else "fail",
            "Veterinary-drug summary and member values reproduce released long-table rules."
            if not problems
            else "Veterinary-drug panel or member lineage is inconsistent.",
            panel_rows=len(panel_rows),
            member_rows=len(member_rows),
            long_rows=len(long_rows),
            problems=problems[:50],
            problem_count=len(problems),
            interpretation_boundary=(
                "Member values are linked to a bilingual drug/tissue rule; expansion "
                "from grouped animal scopes is supplied by a frozen member crosswalk "
                "that is not revalidated from this package alone."
            ),
        )
    ]


def check_quarantine_contract(package: Package) -> list[dict[str, Any]]:
    problems = []
    private_path = re.compile(r"(?:^|[/\\])(?:Users|Volumes)(?:[/\\])|^[A-Za-z]:[/\\]")
    rows = package.rows("quarantined_rows.csv")
    per_family = Counter()
    for row in rows:
        standard = row["standard"]
        per_family[standard] += 1
        if standard == "GB 2760":
            valid_family_fields = (
                bool(row["additive_zh"])
                and bool(row["food_code"])
                and not row["analyte_zh"]
            )
        elif standard == "GB 2762":
            valid_family_fields = (
                bool(row["analyte_zh"])
                and bool(row["unit"])
                and not row["additive_zh"]
                and not row["food_code"]
            )
        else:
            valid_family_fields = False
        if not valid_family_fields:
            problems.append(
                {
                    "record_id": row["record_id"],
                    "problem": "family-specific entity, food-code, or unit fields are inconsistent",
                    "standard": standard,
                }
            )
        source_path = row["source_path"]
        if Path(source_path).is_absolute() or private_path.search(source_path):
            problems.append(
                {
                    "record_id": row["record_id"],
                    "problem": "source_path contains a private or absolute filesystem path",
                    "source_path": source_path,
                }
            )
    return [
        result(
            "package.quarantine_contract",
            "pass" if not problems else "fail",
            "Quarantine rows use portable provenance and family-conditional missing fields."
            if not problems
            else "Quarantine provenance or conditional missing fields violate the release contract.",
            rows=len(rows),
            rows_per_standard=dict(sorted(per_family.items())),
            problems=problems[:50],
            problem_count=len(problems),
        )
    ]


def check_vetdrug_provenance(package: Package) -> list[dict[str, Any]]:
    rows = package.rows("vetdrug_limits_long.csv")
    standards = {
        "2002": "MOA Announcement 235",
        "2019": "GB 31650",
        "2022": "GB 31650.1",
    }
    locator_columns = (
        "source_table_index",
        "source_table_row",
        "animal_block_index",
        "tissue_index",
    )
    problems = []
    locator_owners: dict[tuple[int, int, int, int], str] = {}
    for row in rows:
        record_id = row["record_id"]
        year = row["version_year"]
        if row["standard"] != standards.get(year):
            problems.append(
                {
                    "record_id": record_id,
                    "problem": "veterinary-drug standard identity does not match its edition",
                    "expected": standards.get(year),
                    "actual": row["standard"],
                }
            )
        locator_values = [row[column] for column in locator_columns]
        if year == "2002":
            try:
                locator = tuple(int(value) for value in locator_values)
                valid_locators = all(value > 0 for value in locator)
            except (TypeError, ValueError):
                locator = ()
                valid_locators = False
            if not valid_locators:
                problems.append(
                    {
                        "record_id": record_id,
                        "problem": "2002 announcement row lacks positive table and block locators",
                    }
                )
            elif locator in locator_owners:
                problems.append(
                    {
                        "record_id": record_id,
                        "problem": "2002 announcement locator tuple is duplicated",
                        "first_record_id": locator_owners[locator],
                        "locator": list(locator),
                    }
                )
            else:
                locator_owners[locator] = record_id
        elif any(locator_values):
            problems.append(
                {
                    "record_id": record_id,
                    "problem": "PDF-derived veterinary-drug row contains 2002-only table locators",
                }
            )
    return [
        result(
            "package.vetdrug_provenance",
            "pass" if not problems else "fail",
            "Veterinary-drug edition identities and 2002 Word-table locators are explicit."
            if not problems
            else "Veterinary-drug edition identities or row locators are inconsistent.",
            rows=len(rows),
            rows_with_table_locators=sum(
                row["version_year"] == "2002" for row in rows
            ),
            unique_table_locators=len(locator_owners),
            problems=problems[:50],
            problem_count=len(problems),
        )
    ]


def check_source_manifest(package: Package) -> list[dict[str, Any]]:
    rows = package.rows("source_manifest.csv")
    role_counts = Counter(row["source_role"] for row in rows)
    status_counts = Counter(row["release_status"] for row in rows)
    problems: list[dict[str, Any]] = []
    guide_path = package.path("SOURCE_ACQUISITION.md")
    guide_text = (
        guide_path.read_text(encoding="utf-8") if guide_path.is_file() else ""
    )

    expected_role_counts = {
        "edition_source": 21,
        "extraction_copy": 2,
        "identity_audit_copy": 2,
    }
    expected_status_counts = {
        "extracted": 19,
        "identity_anchor_crosscheck": 2,
        "archived_unextracted": 2,
        "excluded_from_extraction": 2,
    }
    if dict(role_counts) != expected_role_counts:
        problems.append(
            {
                "problem": "source_role counts differ from the declared corpus",
                "expected": expected_role_counts,
                "actual": dict(role_counts),
            }
        )
    if dict(status_counts) != expected_status_counts:
        problems.append(
            {
                "problem": "release_status counts differ from the declared corpus",
                "expected": expected_status_counts,
                "actual": dict(status_counts),
            }
        )

    long_files = {
        "contaminant": "pollutant_limits_long.csv",
        "pesticide": "pesticide_limits_long.csv",
        "mycotoxin": "mycotoxin_limits_long.csv",
        "veterinary_drug": "vetdrug_limits_long.csv",
        "additive": "additive_limits_long.csv",
    }
    manifest_by_id = {row["source_id"]: row for row in rows}
    if not guide_text:
        problems.append({"problem": "SOURCE_ACQUISITION.md is missing or empty"})
    else:
        for row in rows:
            missing_tokens = [
                token
                for token in (
                    row["source_id"],
                    row["source_filename"],
                    row["file_size_bytes"],
                    row["sha256"],
                )
                if token not in guide_text
            ]
            if missing_tokens:
                problems.append(
                    {
                        "source_id": row["source_id"],
                        "problem": "source-acquisition guide omits an exact source identity",
                        "missing_tokens": missing_tokens,
                    }
                )
        for filename, (size, digest) in TRANSLATION_SOURCE_LOCKS.items():
            missing_tokens = [
                token
                for token in (filename, str(size), digest)
                if token not in guide_text
            ]
            if missing_tokens:
                problems.append(
                    {
                        "translation": filename,
                        "problem": "source-acquisition guide omits a translation byte lock",
                        "missing_tokens": missing_tokens,
                    }
                )
        for boundary in (
            "byte_exact_official_file",
            "official_reference_copy_differs",
            "Original retrieval",
            "unrecorded",
        ):
            if boundary not in guide_text:
                problems.append(
                    {
                        "problem": "source-acquisition guide omits a locator boundary",
                        "missing_token": boundary,
                    }
                )
    actual_rows: Counter[tuple[str, str]] = Counter()
    extraction_lineage_counts: Counter[str] = Counter()
    for family, filename in long_files.items():
        for long_row in package.rows(filename):
            year = long_row["version_year"]
            actual_rows[(family, year)] += 1
            edition_id = long_row.get("edition_source_id", "")
            extraction_id = long_row.get("extraction_source_id", "")
            extraction_lineage_counts[extraction_id] += 1
            edition = manifest_by_id.get(edition_id)
            extraction = manifest_by_id.get(extraction_id)
            if edition is None or extraction is None:
                problems.append(
                    {
                        "file": filename,
                        "record_id": long_row["record_id"],
                        "problem": "long-table source lineage references an unknown source_id",
                        "edition_source_id": edition_id,
                        "extraction_source_id": extraction_id,
                    }
                )
                continue
            if (
                edition["source_role"] != "edition_source"
                or edition["family"] != family
                or edition["version_year"] != year
            ):
                problems.append(
                    {
                        "file": filename,
                        "record_id": long_row["record_id"],
                        "problem": "edition_source_id has the wrong role, family, or year",
                    }
                )
            if (
                extraction["source_role"] not in {"edition_source", "extraction_copy"}
                or extraction["family"] != family
                or extraction["version_year"] != year
            ):
                problems.append(
                    {
                        "file": filename,
                        "record_id": long_row["record_id"],
                        "problem": "extraction_source_id has the wrong role, family, or year",
                    }
                )
            if extraction["source_role"] == "extraction_copy":
                if extraction["related_source_id"] != edition_id:
                    problems.append(
                        {
                            "file": filename,
                            "record_id": long_row["record_id"],
                            "problem": "extraction copy is not related to the row's edition source",
                        }
                    )
            elif extraction_id != edition_id:
                problems.append(
                    {
                        "file": filename,
                        "record_id": long_row["record_id"],
                        "problem": "edition-source extraction must use the same source_id",
                    }
                )

    released_edition_keys = set()
    manifest_total = 0
    for row in rows:
        source_id = row["source_id"]
        filename = row["source_filename"]
        if Path(filename).name != filename or "/" in filename or "\\" in filename:
            problems.append({"source_id": source_id, "problem": "source_filename is not a basename"})
        if not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
            problems.append({"source_id": source_id, "problem": "sha256 is not 64 lower-case hexadecimal characters"})
        try:
            size = int(row["file_size_bytes"])
        except ValueError:
            size = 0
        if size <= 0:
            problems.append({"source_id": source_id, "problem": "file_size_bytes is not positive"})

        related_id = row["related_source_id"]
        if related_id:
            related = manifest_by_id.get(related_id)
            if related is None or related_id == source_id:
                problems.append(
                    {
                        "source_id": source_id,
                        "problem": "related_source_id is missing or self-referential",
                    }
                )
            elif (
                related["family"] != row["family"]
                or related["standard"] != row["standard"]
                or related["version_year"] != row["version_year"]
            ):
                problems.append(
                    {
                        "source_id": source_id,
                        "problem": "related source metadata differs by family, standard, or year",
                    }
                )
        if row["retrieved_date"]:
            try:
                datetime.strptime(row["retrieved_date"], "%Y-%m-%d")
            except ValueError:
                problems.append(
                    {
                        "source_id": source_id,
                        "problem": "retrieved_date is not YYYY-MM-DD",
                    }
                )
        if row["page_count"]:
            try:
                page_count = int(row["page_count"])
            except ValueError:
                page_count = 0
            if page_count <= 0:
                problems.append(
                    {"source_id": source_id, "problem": "page_count is not positive"}
                )

        role = row["source_role"]
        status = row["release_status"]
        released = row["released_limit_rows"]
        key = (row["family"], row["version_year"])
        if status == "extracted":
            try:
                declared_rows = int(released)
            except ValueError:
                declared_rows = -1
            actual = extraction_lineage_counts[source_id]
            manifest_total += max(declared_rows, 0)
            if (
                role not in {"edition_source", "extraction_copy"}
                or declared_rows != actual
                or actual <= 0
            ):
                problems.append(
                    {
                        "source_id": source_id,
                        "problem": "extracted manifest row does not match the released long-table count",
                        "declared": declared_rows,
                        "actual": actual,
                    }
                )
            if role == "edition_source":
                released_edition_keys.add(key)
            else:
                if not related_id or not row["acquisition_landing_url"].startswith(
                    "https://"
                ) or not row["acquisition_file_url"].startswith("https://"):
                    problems.append(
                        {
                            "source_id": source_id,
                            "problem": "extraction copy lacks its edition relation or HTTPS acquisition URLs",
                        }
                    )
                released_edition_keys.add(key)
        elif status == "identity_anchor_crosscheck":
            released_edition_keys.add(key)
            if role != "edition_source" or released:
                problems.append(
                    {
                        "source_id": source_id,
                        "problem": "identity anchor must be an edition source with a blank released row count",
                    }
                )
            if extraction_lineage_counts[source_id]:
                problems.append(
                    {
                        "source_id": source_id,
                        "problem": "identity anchor is incorrectly used as an extraction source",
                    }
                )
        elif status == "archived_unextracted":
            if role != "edition_source" or released != "0":
                problems.append(
                    {
                        "source_id": source_id,
                        "problem": "archived_unextracted edition source must declare zero released rows",
                    }
                )
        elif status == "excluded_from_extraction":
            if (
                role != "identity_audit_copy"
                or released
                or row["document_identity"] != "full_standard_text_misnamed_as_amendment"
            ):
                problems.append(
                    {
                        "source_id": source_id,
                        "problem": "identity audit copy has inconsistent exclusion or document identity",
                    }
                )
        else:
            problems.append(
                {"source_id": source_id, "problem": "unknown release_status"}
            )

    expected_released_editions = set(actual_rows)
    if released_edition_keys != expected_released_editions:
        problems.append(
            {
                "problem": "manifest edition coverage does not match released long-table editions",
                "missing": sorted(expected_released_editions - released_edition_keys),
                "unexpected": sorted(released_edition_keys - expected_released_editions),
            }
        )
    special_relations = {
        "SRC0009": ("edition_source", "identity_anchor_crosscheck", ""),
        "SRC0010": ("edition_source", "identity_anchor_crosscheck", ""),
        "SRC0024": ("extraction_copy", "extracted", "SRC0009"),
        "SRC0025": ("extraction_copy", "extracted", "SRC0010"),
    }
    for source_id, expected in special_relations.items():
        row = manifest_by_id.get(source_id)
        actual = (
            row["source_role"],
            row["release_status"],
            row["related_source_id"],
        ) if row else None
        if actual != expected:
            problems.append(
                {
                    "source_id": source_id,
                    "problem": "pesticide identity/extraction source relation is incorrect",
                    "expected": expected,
                    "actual": actual,
                }
            )
    released_total = sum(actual_rows.values())
    if manifest_total != released_total:
        problems.append(
            {
                "problem": "manifest released_limit_rows do not sum to the five long tables",
                "manifest": manifest_total,
                "long_tables": released_total,
            }
        )

    return [
        result(
            "package.source_manifest",
            "pass" if not problems else "fail",
            "The source manifest fingerprints edition identities, extraction copies, and excluded identity-audit copies with complete row lineage."
            if not problems
            else "Source-manifest roles, fingerprints, or released-row counts are inconsistent.",
            rows=len(rows),
            role_counts=dict(sorted(role_counts.items())),
            release_status_counts=dict(sorted(status_counts.items())),
            released_limit_rows=released_total,
            source_acquisition_guide=(
                {
                    "documented_source_rows": guide_text.count("| SRC"),
                    "translation_locks": len(TRANSLATION_SOURCE_LOCKS),
                }
                if guide_text
                else None
            ),
            problems=problems[:50],
            problem_count=len(problems),
        )
    ]


PESTICIDE_RECONCILIATION_EXPECTED = {
    "2012": (2293, 2293, 0, 307, "exact_visible_rule_count_reconciliation"),
    "2014": (3650, 3650, 0, 371, "exact_visible_rule_count_reconciliation"),
    "2016": (
        4140,
        4132,
        -8,
        417,
        "unresolved_aggregate_difference_keep_all_visible_rows",
    ),
    "2019": (
        7107,
        7108,
        1,
        467,
        "unresolved_aggregate_difference_keep_all_visible_rows",
    ),
    "2021": (10092, 10092, 0, 548, "exact_visible_rule_count_reconciliation"),
    "2026": (10749, 10749, 0, 568, "exact_visible_rule_count_reconciliation"),
}

EXPECTED_TIMELINE_CONFLICTS = {
    "TLC0001": (
        (
            "GB 14936",
            "14936",
            "2012",
            "1",
            "1",
            "食品添加剂硅藻土",
            "2012-12-25",
            "2013-01-25",
        ),
        (
            "GB 14936",
            "14936",
            "2012",
            "2",
            "0",
            "硅藻土",
            "2012-05-17",
            "2012-11-17",
        ),
    )
}


def _parse_release_boolean(value: str) -> bool | None:
    normalised = str(value).strip().casefold()
    if normalised in {"1", "true", "yes"}:
        return True
    if normalised in {"0", "false", "no"}:
        return False
    return None


def check_pesticide_release_contract(package: Package) -> list[dict[str, Any]]:
    long_rows = package.rows("pesticide_limits_long.csv")
    reconciliation_rows = package.rows("pesticide_edition_reconciliation.csv")
    crosscheck_rows = package.rows("pesticide_ocr_crosscheck.csv")
    long_by_year = {
        year: [row for row in long_rows if row["version_year"] == year]
        for year in PESTICIDE_YEARS
    }
    reconciliation_by_year = {
        row["version_year"]: row for row in reconciliation_rows
    }
    problems: list[dict[str, Any]] = []

    if set(reconciliation_by_year) != set(PESTICIDE_YEARS):
        problems.append(
            {
                "problem": "pesticide reconciliation does not cover exactly six editions",
                "actual_years": sorted(reconciliation_by_year),
            }
        )
    for year, expected in PESTICIDE_RECONCILIATION_EXPECTED.items():
        row = reconciliation_by_year.get(year)
        if row is None:
            continue
        declared, visible, delta, sections, expected_status = expected
        try:
            actual = (
                int(row["declared_mrl_items"]),
                int(row["coordinate_extracted_visible_rules"]),
                int(row["visible_rules_minus_declared"]),
                int(row["declared_section_roster"]),
                int(row["extracted_section_headers"]),
            )
        except ValueError:
            actual = None
        expected_values = (declared, visible, delta, sections, sections)
        if (
            row["standard"] != "GB 2763"
            or actual != expected_values
            or _parse_release_boolean(row["section_roster_complete"]) is not True
            or row["status"] != expected_status
            or not row["interpretation_boundary"]
        ):
            problems.append(
                {
                    "year": year,
                    "problem": "edition reconciliation differs from the documented visible-rule audit",
                    "expected": expected_values,
                    "actual": actual,
                }
            )
        if len(long_by_year[year]) != visible:
            problems.append(
                {
                    "year": year,
                    "problem": "released pesticide rows differ from the visible-rule reconciliation",
                    "expected": visible,
                    "actual": len(long_by_year[year]),
                }
            )
        try:
            qualifier_counts = json.loads(row["qualifier_counts"])
        except (json.JSONDecodeError, TypeError):
            qualifier_counts = None
        actual_qualifiers = Counter(
            long_row["limit_qualifier"] or "none"
            for long_row in long_by_year[year]
        )
        if (
            not isinstance(qualifier_counts, dict)
            or any(
                not isinstance(key, str)
                or not isinstance(value, int)
                or value < 0
                for key, value in (qualifier_counts or {}).items()
            )
            or qualifier_counts != dict(actual_qualifiers)
            or sum((qualifier_counts or {}).values()) != visible
        ):
            problems.append(
                {
                    "year": year,
                    "problem": "qualifier_counts do not reproduce the released long rows",
                    "expected": dict(actual_qualifiers),
                    "actual": qualifier_counts,
                }
            )

    expected_copy_roles = {
        "2012": "archive_text_layer_edition_source_copy",
        "2014": "archive_text_layer_edition_source_copy",
        "2016": "archive_text_layer_edition_source_copy",
        "2019": "government_hosted_text_layer_extraction_copy",
        "2021": "government_hosted_text_layer_extraction_copy",
        "2026": "archive_text_layer_edition_source_copy",
    }
    for row in long_rows:
        temporary = _parse_release_boolean(row["is_temporary"])
        expected_temporary = row["limit_qualifier"] == "temporary_mrl_asterisk"
        review_components = row["review_status"].split(";")
        unknown_review_components = sorted(
            set(review_components) - PESTICIDE_REVIEW_STATUS_COMPONENTS
        )
        missing_trace = [
            column
            for column in (
                "record_id",
                "section_number",
                "pesticide_key",
                "pesticide_zh",
                "parent_category_zh",
                "food_key",
                "food_zh",
                "limit_value",
                "unit",
                "source_page",
                "edition_source_id",
                "extraction_source_id",
            )
            if not row[column]
        ]
        if temporary is None or temporary != expected_temporary:
            problems.append(
                {
                    "record_id": row["record_id"],
                    "problem": "temporary flag and limit qualifier disagree",
                }
            )
        if (
            not review_components
            or any(not component for component in review_components)
            or "text_layer_auto_extracted" not in review_components
            or unknown_review_components
        ):
            problems.append(
                {
                    "record_id": row["record_id"],
                    "problem": "pesticide review_status violates the component contract",
                    "actual": row["review_status"],
                    "unknown_components": unknown_review_components,
                }
            )
        if missing_trace:
            problems.append(
                {
                    "record_id": row["record_id"],
                    "problem": "pesticide row lacks required identity or coordinate lineage",
                    "missing": missing_trace,
                }
            )
        expected_role = expected_copy_roles.get(row["version_year"])
        if row["source_copy_role"] != expected_role:
            problems.append(
                {
                    "record_id": row["record_id"],
                    "problem": "source_copy_role differs from the edition extraction design",
                    "expected": expected_role,
                    "actual": row["source_copy_role"],
                }
            )

    crosscheck_years = Counter(row["year"] for row in crosscheck_rows)
    if set(crosscheck_years) != {"2019", "2021"}:
        problems.append(
            {
                "problem": "OCR crosscheck must cover only the two original-scan editions",
                "actual_years": sorted(crosscheck_years),
            }
        )
    text_rows_by_year: Counter[str] = Counter()
    allowed_key_levels = {"strict_scope", "unique_section_food"}
    status_counts = Counter()
    text_groups: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for long_row in long_rows:
        if long_row["version_year"] not in {"2019", "2021"}:
            continue
        try:
            section_number = str(int(long_row["section_number"]))
        except (TypeError, ValueError):
            section_number = long_row["section_number"]
        key = (
            long_row["version_year"],
            section_number,
            _normalise_crosscheck_scope(long_row["parent_category_zh"]),
            _normalise_crosscheck_scope(long_row["food_zh"]),
        )
        text_groups[key].append(long_row)
    audit_key_counts: Counter[tuple[str, str, str, str]] = Counter()
    for row_index, row in enumerate(crosscheck_rows, 2):
        try:
            text_count = int(row["text_row_count"])
            ocr_count = int(row["ocr_row_count"])
            section_number = str(int(row["section_number"]))
        except (TypeError, ValueError):
            problems.append(
                {
                    "row": row_index,
                    "problem": "OCR crosscheck row counts or section number are not integers",
                }
            )
            continue
        audit_key = (
            row["year"],
            section_number,
            _normalise_crosscheck_scope(row["parent_category"]),
            _normalise_crosscheck_scope(row["food"]),
        )
        audit_key_counts[audit_key] += 1
        expected_text_rows = text_groups.get(audit_key, [])
        expected_text_values = ";".join(
            sorted(
                _normalise_crosscheck_value(item["limit_value"])
                for item in expected_text_rows
            )
        )
        expected_text_pages = ";".join(
            str(page)
            for page in sorted(
                {int(item["source_page"]) for item in expected_text_rows}
            )
        )
        text_rows_by_year[row["year"]] += text_count
        status = row["status"]
        status_counts[status] += 1
        expected_presence = {
            "consistent": (True, True),
            "conflict": (True, True),
            "text_only": (True, False),
            "ocr_only": (False, True),
        }.get(status)
        actual_presence = (text_count > 0, ocr_count > 0)
        text_value_count = (
            len(row["text_values"].split(";")) if row["text_values"] else 0
        )
        ocr_value_count = (
            len(row["ocr_values"].split(";")) if row["ocr_values"] else 0
        )
        value_counts_consistent = (
            text_value_count == text_count and ocr_value_count == ocr_count
        )
        values_consistent = (
            row["text_values"] == row["ocr_values"]
            if status == "consistent"
            else row["text_values"] != row["ocr_values"]
            if status == "conflict"
            else True
        )
        pages_consistent = bool(row["text_source_pages"]) == (text_count > 0) and bool(
            row["ocr_source_pages"]
        ) == (ocr_count > 0)
        text_side_reproduces_release = (
            text_count == len(expected_text_rows)
            and row["text_values"] == expected_text_values
            and row["text_source_pages"] == expected_text_pages
        )
        if (
            expected_presence is None
            or actual_presence != expected_presence
            or not value_counts_consistent
            or not values_consistent
            or not pages_consistent
            or row["key_level"] not in allowed_key_levels
            or not text_side_reproduces_release
        ):
            problems.append(
                {
                    "row": row_index,
                    "problem": "OCR crosscheck status or text-side long-table lineage is inconsistent",
                    "expected_text_row_count": len(expected_text_rows),
                    "expected_text_values": expected_text_values,
                    "expected_text_source_pages": expected_text_pages,
                    "text_value_count": text_value_count,
                    "ocr_value_count": ocr_value_count,
                }
            )
    missing_text_groups = sorted(set(text_groups) - set(audit_key_counts))
    duplicate_audit_groups = [
        key for key, count in audit_key_counts.items() if count != 1
    ]
    if missing_text_groups or duplicate_audit_groups:
        problems.append(
            {
                "problem": "OCR crosscheck keys do not cover each released text group exactly once",
                "missing_group_count": len(missing_text_groups),
                "duplicate_group_count": len(duplicate_audit_groups),
                "missing_examples": missing_text_groups[:10],
                "duplicate_examples": duplicate_audit_groups[:10],
            }
        )
    for year in ("2019", "2021"):
        if text_rows_by_year[year] != len(long_by_year[year]):
            problems.append(
                {
                    "year": year,
                    "problem": "OCR crosscheck text-row lineage does not conserve released rows",
                    "crosscheck": text_rows_by_year[year],
                    "released": len(long_by_year[year]),
                }
            )

    return [
        result(
            "package.pesticide_release_contract",
            "pass" if not problems else "fail",
            "Six-edition visible-rule reconciliation, qualifiers, coordinates, and OCR crosschecks agree with the released pesticide tables."
            if not problems
            else "Pesticide reconciliation, qualifier, coordinate, or OCR-crosscheck drift was found.",
            released_rows_by_year={
                year: len(long_by_year[year]) for year in PESTICIDE_YEARS
            },
            ocr_crosscheck_rows_by_year=dict(sorted(crosscheck_years.items())),
            ocr_crosscheck_statuses=dict(sorted(status_counts.items())),
            released_text_groups=len(text_groups),
            problems=problems[:50],
            problem_count=len(problems),
            interpretation_boundary=(
                "Text-side keys, values, counts, and pages are recomputed from the "
                "released long table. OCR-side values, counts, and pages are frozen "
                "upstream audit evidence; this package checks their internal structure only."
            ),
        )
    ]


def check_pesticide_quality_states(package: Package) -> list[dict[str, Any]]:
    """Backward-compatible callable for the superseded tier-based check name."""
    return check_pesticide_release_contract(package)


def check_timeline_conflicts(package: Package) -> list[dict[str, Any]]:
    rows = package.rows("standard_timeline_conflicts.csv")
    timeline = package.rows("standard_version_timeline.csv")
    official_versions = {
        (row["std_id"], row["version_year"]): row
        for row in timeline
        if row["event_type"] == "official_version"
    }
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["conflict_id"]].append(row)
    problems = []
    observed_candidates = {
        conflict_id: tuple(
            sorted(
                (
                    row["std_id"],
                    row["number"],
                    row["version_year"],
                    row["candidate_rank"],
                    row["selected"],
                    row["normalized_title"],
                    row["issue_date"],
                    row["effective_date"],
                )
                for row in candidates
            )
        )
        for conflict_id, candidates in sorted(grouped.items())
    }
    if observed_candidates != EXPECTED_TIMELINE_CONFLICTS:
        problems.append(
            {
                "problem": "timeline conflict audit does not retain the frozen candidate set",
                "expected": EXPECTED_TIMELINE_CONFLICTS,
                "actual": observed_candidates,
            }
        )
    for conflict_id, candidates in sorted(grouped.items()):
        try:
            ranks = sorted(int(row["candidate_rank"]) for row in candidates)
            equivalent_counts = [
                int(row["equivalent_row_count"]) for row in candidates
            ]
        except ValueError:
            ranks = []
            equivalent_counts = []
        selected = [row for row in candidates if row["selected"] == "1"]
        shared_keys = {
            (row["std_id"], row["number"], row["version_year"])
            for row in candidates
        }
        booleans_valid = all(
            row[column] in {"0", "1"}
            for row in candidates
            for column in (
                "selected",
                "timeline_title_match",
                "anchor_category_match",
            )
        )
        valid_group = (
            len(candidates) >= 2
            and len(selected) == 1
            and len(shared_keys) == 1
            and ranks == list(range(1, len(candidates) + 1))
            and all(count > 0 for count in equivalent_counts)
            and booleans_valid
            and all(
                row["conflict_type"] == "official_version_metadata_conflict"
                and row["selection_reason"]
                for row in candidates
            )
        )
        timeline_row = official_versions.get(
            (selected[0]["std_id"], selected[0]["version_year"])
        ) if selected else None
        selected_matches = bool(
            timeline_row
            and selected[0]["normalized_title"] == timeline_row["title_zh"]
            and selected[0]["issue_date"] == timeline_row["issue_date"]
            and selected[0]["effective_date"] == timeline_row["effective_date"]
        )
        if not valid_group or not selected_matches:
            problems.append(
                {
                    "conflict_id": conflict_id,
                    "problem": "timeline conflict candidates or selected metadata are inconsistent",
                }
            )
    return [
        result(
            "package.timeline_conflicts",
            "pass" if not problems else "fail",
            "Timeline metadata conflicts retain every candidate and exactly one reproducible selection."
            if not problems
            else "Timeline conflict audit rows are structurally inconsistent.",
            conflict_groups=len(grouped),
            candidates=len(rows),
            problems=problems[:50],
            problem_count=len(problems),
        )
    ]


def check_version_dates(package: Package) -> list[dict[str, Any]]:
    dates = package.rows("version_dates.csv")
    timeline = package.rows("standard_version_timeline.csv")
    problems = []
    official_timeline: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for timeline_row in timeline:
        timeline_dates = (
            timeline_row["issue_date"],
            timeline_row["effective_date"],
        )
        if any(timeline_dates) != all(timeline_dates):
            problems.append(
                {
                    "record_id": timeline_row["record_id"],
                    "problem": "timeline issue/effective dates are only partially populated",
                }
            )
        elif all(timeline_dates):
            if not all(_valid_type(value, "date") for value in timeline_dates):
                problems.append(
                    {
                        "record_id": timeline_row["record_id"],
                        "problem": "timeline issue/effective date is malformed",
                    }
                )
            elif datetime.strptime(
                timeline_dates[0], "%Y-%m-%d"
            ).date() > datetime.strptime(timeline_dates[1], "%Y-%m-%d").date():
                problems.append(
                    {
                        "record_id": timeline_row["record_id"],
                        "problem": "timeline issue_date is later than effective_date",
                    }
                )
        if timeline_row["event_type"] == "official_version":
            official_timeline[
                (timeline_row["std_id"], timeline_row["version_year"])
            ].append(timeline_row)
    edition_sources = {
        row["source_id"]: row
        for row in package.rows("source_manifest.csv")
        if row["source_role"] == "edition_source"
    }
    date_by_source = {row["source_id"]: row for row in dates}
    expected = {
        (row["standard"], row["version_year"])
        for row in edition_sources.values()
    }
    keys = {(row["standard"], row["version_year"]) for row in dates}
    missing = sorted(expected - keys)
    if set(date_by_source) != set(edition_sources) or len(dates) != len(
        edition_sources
    ):
        problems.append(
            {
                "problem": "version_dates must contain exactly one row per edition source",
                "missing_source_ids": sorted(set(edition_sources) - set(date_by_source)),
                "unexpected_source_ids": sorted(set(date_by_source) - set(edition_sources)),
            }
        )
    for source_id, row in date_by_source.items():
        source = edition_sources.get(source_id)
        if source is None:
            continue
        identity_fields = ("family", "standard", "version_year", "source_filename")
        if any(row[field] != source[field] for field in identity_fields):
            problems.append(
                {
                    "record_id": row["record_id"],
                    "problem": "version-date identity differs from source_manifest",
                }
            )
        dates_blank = not row["issue_date"] and not row["effective_date"]
        if source_id == "SRC0018":
            if (
                not dates_blank
                or row["date_status"] != "not_printed"
                or row["date_source"] != "not printed"
                or not row["date_resolution"]
            ):
                problems.append(
                    {
                        "record_id": row["record_id"],
                        "problem": "GB 2760-1996 must retain its explicit not-printed date state",
                    }
                )
        elif (
            dates_blank
            or row["date_status"] != "complete"
            or not row["date_source"]
            or not row["date_resolution"]
            or not _valid_type(row["issue_date"], "date")
            or not _valid_type(row["effective_date"], "date")
        ):
            problems.append(
                {
                    "record_id": row["record_id"],
                    "problem": "edition dates or their resolution metadata are incomplete",
                }
            )
        if (
            row["issue_date"]
            and row["effective_date"]
            and _valid_type(row["issue_date"], "date")
            and _valid_type(row["effective_date"], "date")
        ):
            issue_date = datetime.strptime(row["issue_date"], "%Y-%m-%d").date()
            effective_date = datetime.strptime(
                row["effective_date"], "%Y-%m-%d"
            ).date()
            if issue_date > effective_date:
                problems.append(
                    {
                        "record_id": row["record_id"],
                        "problem": "issue_date is later than effective_date",
                    }
                )
        register_dates = (
            row["official_register_issue_date"],
            row["official_register_effective_date"],
        )
        if any(register_dates) != all(register_dates):
            problems.append(
                {
                    "record_id": row["record_id"],
                    "problem": "official-register dates are only partially populated",
                }
            )
        elif all(register_dates) and (
            row["cross_check_official_register"] != "agrees"
            or register_dates != (row["issue_date"], row["effective_date"])
        ):
            problems.append(
                {
                    "record_id": row["record_id"],
                    "problem": "official-register crosscheck does not reproduce the selected dates",
                }
            )
        if all(register_dates):
            timeline_candidates = official_timeline.get(
                (row["standard"], row["version_year"]), []
            )
            timeline_dates = [
                (candidate["issue_date"], candidate["effective_date"])
                for candidate in timeline_candidates
            ]
            if len(timeline_candidates) != 1 or timeline_dates[0] != register_dates:
                problems.append(
                    {
                        "record_id": row["record_id"],
                        "problem": "official-register dates do not match exactly one official timeline row",
                        "timeline_dates": timeline_dates,
                        "register_dates": list(register_dates),
                    }
                )
        elif not any(register_dates) and row["cross_check_official_register"]:
            problems.append(
                {
                    "record_id": row["record_id"],
                    "problem": "official-register status is populated without register dates",
                }
            )
    timeline_versions = {
        (row["std_id"], row["version_year"])
        for row in timeline
        if row["event_type"] == "official_version"
    }
    missing_timeline = sorted(expected - timeline_versions)
    expected_amendments = {
        ("GB 2762", "2017", "第1号"),
        ("GB 2762", "2022", "第1号"),
    }
    actual_amendments = {
        (row["std_id"], row["version_year"], row["amendment_no"])
        for row in timeline
        if row["event_type"] == "amendment"
    }
    missing_amendments = sorted(expected_amendments - actual_amendments)
    status = (
        "pass"
        if not missing
        and not missing_timeline
        and not missing_amendments
        and not problems
        else "fail"
    )
    return [
        result(
            "package.version_dates",
            status,
            "Every extracted edition has issue/effective dates with a recorded read path." if status == "pass" else "Edition date coverage is incomplete.",
            missing=[{"standard": standard, "version_year": year} for standard, year in missing],
            missing_timeline_versions=[
                {"standard": standard, "version_year": year}
                for standard, year in missing_timeline
            ],
            missing_timeline_amendments=[
                {
                    "standard": standard,
                    "version_year": year,
                    "amendment_no": amendment,
                }
                for standard, year, amendment in missing_amendments
            ],
            date_problems=problems[:50],
            date_problem_count=len(problems),
            extra_archived_entries=len(keys - expected),
        )
    ]


def check_readme_contract(package: Package) -> list[dict[str, Any]]:
    text = package.path("README.md").read_text(encoding="utf-8")
    required_phrases = (
        "status_YYYY",
        "values_YYYY",
        "source_record_ids_YYYY",
        "source_ids_YYYY",
        "edition_source_id",
        "extraction_source_id",
        "pesticide_edition_reconciliation.csv",
        "limit_qualifier",
        "is_temporary",
        "incomparable_scope_text",
        "GMP",
        "not_run",
        "--source-root",
        "SOURCE_ACQUISITION.md",
    )
    missing = [phrase for phrase in required_phrases if phrase not in text]
    stale_row_cells = re.findall(r"\|\s*`[^`]+\.csv`[^|]*\|\s*[\d,]+(?:\s*/\s*[\d,]+)*\s*\|", text)
    status = "pass" if not missing and not stale_row_cells else "fail"
    return [
        result(
            "package.readme_contract",
            status,
            "README documents multi-value, missing-value, and validation-status semantics without frozen row counts." if status == "pass" else "README contract documentation is incomplete or contains frozen row counts.",
            missing_phrases=missing,
            frozen_row_count_rows=stale_row_cells[:20],
        )
    ]


def self_contained_check_specs() -> tuple[tuple[str, Any], ...]:
    """Return the stable self-contained check catalog and implementations."""
    return (
        ("package.required_files", check_required_files),
        ("package.csv_integrity", check_csv_integrity),
        ("package.build_stats", check_build_stats),
        ("package.primary_keys", check_primary_keys),
        ("package.version_coverage", check_version_coverage),
        ("package.conflict_flags", check_conflict_flags),
        ("package.data_dictionary", check_data_dictionary),
        ("package.lookup_integrity", check_lookup_integrity),
        ("package.panel_lineage", check_panel_lineage),
        ("package.missing_values", check_missing_value_contract),
        ("package.pollutant_normalization", check_pollutant_normalization),
        ("package.pollutant_panels", check_pollutant_panel_contract),
        ("package.mycotoxin_panel_lineage", check_mycotoxin_panel_lineage),
        ("package.vetdrug_panel_lineage", check_vetdrug_panel_lineage),
        ("package.quarantine_contract", check_quarantine_contract),
        ("package.vetdrug_provenance", check_vetdrug_provenance),
        ("package.source_manifest", check_source_manifest),
        ("package.pesticide_release_contract", check_pesticide_release_contract),
        ("package.timeline_conflicts", check_timeline_conflicts),
        ("package.version_dates", check_version_dates),
        ("package.readme_contract", check_readme_contract),
    )


def run_self_contained_checks(package: Package) -> list[dict[str, Any]]:
    specs = self_contained_check_specs()
    checks: list[dict[str, Any]] = []
    unavailable_reason = ""
    for check_id, function in specs:
        if unavailable_reason:
            checks.append(
                result(
                    check_id,
                    "not_run",
                    f"Prerequisite package integrity failed: {unavailable_reason}",
                )
            )
            continue
        try:
            outcomes = function(package)
        except Exception as exc:  # noqa: BLE001 - validators must report malformed inputs
            outcomes = [
                result(
                    check_id,
                    "fail",
                    "The check raised an internal error while reading the supplied package.",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            ]
        checks.extend(outcomes)
        if check_id in {"package.required_files", "package.csv_integrity"} and any(
            item["status"] == "fail" for item in outcomes
        ):
            unavailable_reason = check_id
    return checks


@lru_cache(maxsize=None)
def _pdf_page_text(path: Path, page: int) -> str | None:
    if not shutil.which("pdftotext"):
        return None
    try:
        completed = subprocess.run(
            ["pdftotext", "-f", str(page), "-l", str(page), "-raw", str(path), "-"],
            check=False,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8", "replace")


@lru_cache(maxsize=None)
def _pdf_text(path: Path, layout: bool = True, raw: bool = False) -> str | None:
    if not shutil.which("pdftotext"):
        return None
    mode = ["-raw"] if raw else (["-layout"] if layout else [])
    args = ["pdftotext", *mode, str(path), "-"]
    try:
        completed = subprocess.run(args, check=False, capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8", "replace")


def _pollutant_source(index: SourceIndex, year: str) -> Path | None:
    preferred_directory = "补充_食安国标全文_卫健委分类/污染物"
    return index.exact(POLLUTANT_PDFS[year], prefer=preferred_directory) or index.matching(
        f"GB 2762-{year}*.pdf",
        exclude="修改单",
    )


def check_source_manifest_inputs(package: Package, index: SourceIndex) -> list[dict[str, Any]]:
    missing = []
    mismatched = []
    verified = []
    for row in package.rows("source_manifest.csv"):
        hits = index.by_name.get(row["source_filename"], [])
        if not hits:
            missing.append({"source_id": row["source_id"], "source_filename": row["source_filename"]})
            continue
        matching = []
        candidates = []
        for path in hits:
            digest, size = index.fingerprint(path)
            candidate = {
                "path": index.label(path),
                "sha256": digest,
                "bytes": size,
            }
            candidates.append(candidate)
            if digest == row["sha256"] and size == int(row["file_size_bytes"]):
                matching.append(candidate)
        if not matching:
            mismatched.append(
                {
                    "source_id": row["source_id"],
                    "source_filename": row["source_filename"],
                    "candidates": candidates,
                }
            )
        else:
            verified.append({"source_id": row["source_id"], **matching[0]})
    for filename, (expected_size, expected_digest) in TRANSLATION_SOURCE_LOCKS.items():
        hits = index.by_name.get(filename, [])
        if not hits:
            missing.append(
                {
                    "source_id": f"translation:{filename}",
                    "source_filename": filename,
                }
            )
            continue
        candidates = []
        matching = []
        for path in hits:
            digest, size = index.fingerprint(path)
            candidate = {
                "path": index.label(path),
                "sha256": digest,
                "bytes": size,
            }
            candidates.append(candidate)
            if digest == expected_digest and size == expected_size:
                matching.append(candidate)
        if not matching:
            mismatched.append(
                {
                    "source_id": f"translation:{filename}",
                    "source_filename": filename,
                    "candidates": candidates,
                }
            )
        else:
            verified.append(
                {"source_id": f"translation:{filename}", **matching[0]}
            )
    if mismatched:
        status = "fail"
        message = "One or more supplied source or translation files disagree with the declared byte lock."
    elif missing:
        status = "skip"
        message = "The supplied source tree does not contain every manifest source and locked translation."
    else:
        status = "pass"
        message = "Every source-manifest file and locked translation was found with the declared size and SHA-256 digest."
    return [
        result(
            "source.input_manifest",
            status,
            message,
            verified=verified,
            missing=missing,
            mismatched=mismatched,
        )
    ]


def check_source_selection(index: SourceIndex) -> list[dict[str, Any]]:
    problems = [
        selection
        for selection in index.selections
        if selection["manifest_hash_mismatch"] or selection["ambiguous_distinct_files"]
    ]
    return [
        result(
            "source.input_selection",
            "skip" if not index.selections else ("pass" if not problems else "fail"),
            "Every source query selected a manifest-matched or content-identical input."
            if index.selections and not problems
            else "No source query could select a file from the supplied source tree."
            if not index.selections
            else "A source query had a manifest mismatch or multiple content-distinct candidates.",
            selections=index.selections,
            problems=problems,
        )
    ]


def check_pollutant_source_expectations(package: Package, index: SourceIndex) -> list[dict[str, Any]]:
    released = package.rows("pollutant_limits_long.csv")
    outcomes = []
    for expected in POLLUTANT_SOURCE_EXPECTATIONS:
        year = expected["year"]
        source = _pollutant_source(index, year)
        check_id = f"source.pollutant_fixture.{year}.p{expected['page']}.{expected['analyte']}.{expected['food']}"
        if source is None:
            outcomes.append(result(check_id, "skip", "The required source PDF was not found in --source-root.", expected=expected))
            continue
        page_text = _pdf_page_text(source, int(expected["page"]))
        if page_text is None:
            outcomes.append(result(check_id, "not_run", "pdftotext could not render the required source page.", source=index.label(source), expected=expected))
            continue
        flat = _normalise_text(page_text)
        document_text = _pdf_text(source, layout=False, raw=True) or ""
        food_term = _normalise_text(expected["food"])
        value_pattern = re.compile(
            rf"(?<![\d.]){re.escape(_normalise_text(expected['value']))}(?![\d.])"
        )
        food_positions = [match.start() for match in re.finditer(re.escape(food_term), flat)]
        value_near_food = any(
            value_pattern.search(flat[position : position + len(food_term) + 180])
            for position in food_positions
        )
        analyte_found = _normalise_text(expected["analyte"]) in _normalise_text(document_text)
        unit_found = _normalise_text(expected["unit"]) in flat
        basis_found = not expected["basis"] or _normalise_text(expected["basis"]) in flat
        source_has_row = bool(food_positions) and value_near_food and analyte_found and unit_found and basis_found
        matches = [
            row
            for row in released
            if row["version_year"] == year
            and row["analyte_zh"] == expected["analyte"]
            and _normalise_food(row["food_category_zh"]) == _normalise_food(expected["food"])
            and _normalise_decimal(row["limit_value"]) == _normalise_decimal(expected["value"])
            and row["unit"] == expected["unit"]
        ]
        release_exact = len(matches) == 1 and matches[0]["limit_basis"] == expected["basis"]
        status = "pass" if source_has_row and release_exact else "fail"
        outcomes.append(
            result(
                check_id,
                status,
                "Source-page fixture maps to exactly one released row with the expected basis." if status == "pass" else "Source-page fixture and release do not agree.",
                source=index.label(source),
                expected=expected,
                source_terms_found=source_has_row,
                source_components={
                    "food": bool(food_positions),
                    "value_near_food": value_near_food,
                    "analyte_in_document": analyte_found,
                    "unit": unit_found,
                    "basis": basis_found,
                },
                release_matches=len(matches),
                released_basis=[row["limit_basis"] for row in matches],
                released_record_ids=[row["record_id"] for row in matches],
            )
        )
    return outcomes


def check_basis_source_coverage(package: Package, index: SourceIndex) -> list[dict[str, Any]]:
    rows = package.rows("pollutant_limits_long.csv")
    outcomes = []
    for year in ("2012", "2017", "2022", "2025"):
        source = _pollutant_source(index, year)
        check_id = f"source.pollutant_basis.{year}"
        if source is None:
            outcomes.append(result(check_id, "skip", "The required source PDF was not found in --source-root."))
            continue
        text = _pdf_text(source, layout=False, raw=True)
        if text is None:
            outcomes.append(result(check_id, "not_run", "pdftotext could not read the source PDF.", source=index.label(source)))
            continue
        source_count = len(BASIS_RE.findall(re.sub(r"\s+", "", text)))
        release_count = sum(row["version_year"] == year and bool(row["limit_basis"]) for row in rows)
        status = "pass" if source_count > 0 and release_count == source_count else "fail"
        outcomes.append(
            result(
                check_id,
                status,
                "The release and source PDF contain the same number of countable basis qualifiers."
                if status == "pass"
                else "The release and source PDF contain different numbers of basis qualifiers.",
                source=index.label(source),
                source_qualifiers=source_count,
                release_rows_with_basis=release_count,
            )
        )
    return outcomes


def _pesticide_section_denominator(text: str) -> int:
    numbers = sorted(
        {
            int(match.group(1))
            for line in text.splitlines()
            if (match := re.match(r"^\s*4\.\s?(\d+)\s+", line))
            and int(match.group(1)) < 1000
        }
    )
    consecutive = 0
    for number in numbers:
        if number == consecutive + 1:
            consecutive = number
        elif number > consecutive + 1:
            break
    return consecutive


def check_entity_count_coverage(package: Package, index: SourceIndex) -> list[dict[str, Any]]:
    outcomes = []
    for case in ENTITY_COUNT_CASES:
        source = index.matching(case["pattern"], exclude="修改单")
        check_id = f"source.entity_count_coverage.{case['id']}"
        if source is None:
            outcomes.append(result(check_id, "skip", "The required source PDF was not found in --source-root."))
            continue
        text = _pdf_text(source, layout=True)
        if text is None:
            outcomes.append(result(check_id, "not_run", "pdftotext could not read the source PDF.", source=index.label(source)))
            continue
        if case["kind"] == "cns":
            body = "\n".join(line for line in text.splitlines() if "……" not in line and "....." not in line)
            denominator = len(re.findall(r"C\s*N\s*S\s*号", body, re.I))
        elif case["kind"] == "vet":
            body = "\n".join(line for line in text.splitlines() if "……" not in line and "....." not in line)
            denominator = len(set(re.findall(r"^\s*(4\.1\.\d+)[^.]", body, re.M)))
        else:
            denominator = _pesticide_section_denominator(text)
        extracted = len(
            {
                row[case["entity"]]
                for row in package.rows(case["file"])
                if row["version_year"] == case["year"] and row[case["entity"]]
            }
        )
        coverage = extracted / denominator if denominator else None
        status = (
            "pass"
            if coverage is not None
            and ENTITY_COUNT_MIN_COVERAGE
            <= Decimal(str(coverage))
            <= ENTITY_COUNT_MAX_COVERAGE
            else "fail"
        )
        outcomes.append(
            result(
                check_id,
                status,
                "Released and source entity counts yield coverage between 95% and 100%."
                if status == "pass"
                else "Entity-count coverage is below 95%, above 100%, or has a zero source denominator.",
                source=index.label(source),
                released_unique_entities=extracted,
                independently_counted_source_entries=denominator,
                entity_count_coverage=round(coverage, 6) if coverage is not None else None,
                minimum_coverage=float(ENTITY_COUNT_MIN_COVERAGE),
                maximum_coverage=float(ENTITY_COUNT_MAX_COVERAGE),
                interpretation=(
                    "Count-based coverage proxy only; this check does not perform entity-name set matching."
                ),
            )
        )
    return outcomes


def _value_pattern(value: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![\d.]){re.escape(value)}(?=$|[^\d.]|\d{{2}}\.)"
    )


def _near(flat: str, entity: str, member: str, value: str, section: int, window: int = 150) -> bool | None:
    entity = re.split(r"[\[(（［]", entity)[0]
    if len(entity) < 2 or not member:
        return None
    start = flat.find(entity)
    value_pattern = _value_pattern(value)
    while start >= 0:
        segment = flat[start : start + section]
        member_pos = segment.find(member)
        while member_pos >= 0:
            if value_pattern.search(segment[member_pos : member_pos + window]):
                return True
            member_pos = segment.find(member, member_pos + 1)
        start = flat.find(entity, start + 1)
    return False


def _near_food(flat: str, member: str, value: str, window: int = 100) -> bool:
    value_pattern = _value_pattern(value)
    start = flat.find(member)
    while start >= 0:
        if value_pattern.search(flat[start : start + len(member) + window]):
            return True
        start = flat.find(member, start + 1)
    return False


def _select_positional_rows(
    rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], str]:
    """Evaluate every eligible row; the four current cases are tractable."""

    return rows, "eligible_row_census"


def check_positional_traceback(package: Package, index: SourceIndex) -> list[dict[str, Any]]:
    outcomes = []
    for case_id, filename, year, entity_col, name_col, value_col, section, pattern in POSITIONAL_CASES:
        source = index.matching(pattern, exclude="修改单")
        check_id = f"source.positional_traceback.{case_id}"
        if source is None:
            outcomes.append(result(check_id, "skip", "The required source PDF was not found in --source-root."))
            continue
        texts = [_pdf_text(source, layout=True), _pdf_text(source, layout=False)]
        if any(text is None for text in texts):
            outcomes.append(result(check_id, "not_run", "pdftotext could not read both source renderings.", source=index.label(source)))
            continue
        flat = re.sub(r"\s+", "", "\n".join(text for text in texts if text is not None))
        rows = sorted(
            (
                row
                for row in package.rows(filename)
                if row["version_year"] == year
                and row.get(value_col)
                and row[value_col] != "GMP"
                and row.get(name_col)
                and row.get(entity_col)
                and row[entity_col] not in POLLUTANT_POSITIONAL_EXCLUSIONS
            ),
            key=lambda row: row["record_id"],
        )
        rng = random.Random(RANDOM_SEED + sum(ord(char) for char in case_id))
        sample, sampling_scope = _select_positional_rows(rows)
        triples = [
            (
                re.sub(r"\s+", "", row[entity_col]),
                re.sub(r"\s+", "", row[name_col]),
                row[value_col].rstrip("*"),
            )
            for row in sample
        ]

        if case_id == "pollutant.2022":
            method = "food_value_global_census_with_shuffled_control"
        elif sampling_scope == "eligible_row_census":
            method = "entity_food_value_section_census_with_shuffled_control"
        else:
            method = "entity_food_value_section_with_shuffled_control"

        def score(items: list[tuple[str, str, str]]) -> tuple[int, int]:
            passed = decidable = 0
            for entity, member, value in items:
                verdict = (
                    _near_food(flat, member, value)
                    if case_id == "pollutant.2022"
                    else _near(flat, entity, member, value, section)
                )
                if verdict is None:
                    continue
                decidable += 1
                passed += bool(verdict)
            return passed, decidable

        true_passed, true_n = score(triples)
        shuffled_values = [value for _, _, value in triples]
        rng.shuffle(shuffled_values)
        shuffled = [(entity, member, value) for (entity, member, _), value in zip(triples, shuffled_values)]
        fake_passed, fake_n = score(shuffled)
        true_rate = true_passed / true_n if true_n else None
        fake_rate = fake_passed / fake_n if fake_n else None
        gap = true_rate - fake_rate if true_rate is not None and fake_rate is not None else None
        minimum_decidable = min(30, len(sample))
        minimum_true_rate = 0.85 if case_id == "additive.2024" else 0.9
        status = (
            "pass"
            if true_rate is not None
            and fake_rate is not None
            and true_n >= minimum_decidable
            and true_rate >= minimum_true_rate
            and gap >= 0.25
            else "fail"
        )
        outcomes.append(
            result(
                check_id,
                status,
                "True-row traceback clears both the accuracy and shuffled-control thresholds." if status == "pass" else "Positional traceback lacks the required accuracy or diagnostic gap.",
                source=index.label(source),
                sample=len(sample),
                eligible_rows=len(rows),
                evaluated_rows=len(sample),
                sampling_scope=sampling_scope,
                decidable=true_n,
                true_passed=true_passed,
                unmatched=true_n - true_passed,
                shuffled_passed=fake_passed,
                minimum_decidable=minimum_decidable,
                method=method,
                excluded_entities=(
                    sorted(POLLUTANT_POSITIONAL_EXCLUSIONS)
                    if case_id == "pollutant.2022"
                    else []
                ),
                exclusion_reason=(
                    "Paired value-column analytes require coordinate-aware assignment and are outside this text-rendering diagnostic."
                    if case_id == "pollutant.2022"
                    else None
                ),
                minimum_true_rate=minimum_true_rate,
                true_rate=round(true_rate, 6) if true_rate is not None else None,
                shuffled_rate=round(fake_rate, 6) if fake_rate is not None else None,
                diagnostic_gap=round(gap, 6) if gap is not None else None,
            )
        )
    return outcomes


def check_english_sources(package: Package, index: SourceIndex) -> list[dict[str, Any]]:
    outcomes = []
    for case_id, filename, column, source_filename in ENGLISH_SOURCE_CASES:
        source = index.exact(source_filename)
        check_id = f"source.english_provenance.{case_id}"
        if source is None:
            outcomes.append(result(check_id, "skip", "The cited translation PDF was not found in --source-root."))
            continue
        expected_size, expected_digest = TRANSLATION_SOURCE_LOCKS[source_filename]
        actual_digest, actual_size = index.fingerprint(source)
        if (actual_size, actual_digest) != (expected_size, expected_digest):
            outcomes.append(
                result(
                    check_id,
                    "fail",
                    "The cited translation PDF differs from its declared byte lock.",
                    source=index.label(source),
                    expected={"bytes": expected_size, "sha256": expected_digest},
                    actual={"bytes": actual_size, "sha256": actual_digest},
                )
            )
            continue
        text = _pdf_text(source, layout=False, raw=True)
        if text is None:
            outcomes.append(result(check_id, "not_run", "pdftotext could not read the cited translation.", source=index.label(source)))
            continue
        flat = re.sub(r"\s+", " ", text).lower()
        rows = package.rows(filename)
        if case_id == "additive_food_names":
            rows = [row for row in rows if row["family"] == "additive"]
        elif case_id == "pesticide_food_names":
            rows = [row for row in rows if row["family"] == "pesticide"]
        missing = [row[column] for row in rows if re.sub(r"\s+", " ", row[column]).lower() not in flat]
        status = "pass" if rows and not missing else "fail"
        outcomes.append(
            result(
                check_id,
                status,
                "Vocabulary-occurrence screen found every released English label in the cited translation."
                if status == "pass"
                else "Vocabulary-occurrence screen did not find every released English label in the cited translation.",
                source=index.label(source),
                labels=len(rows),
                not_found=len(missing),
                examples=missing[:20],
                interpretation_boundary=(
                    "Occurrence anywhere in the PDF does not validate a Chinese-English "
                    "row pairing; pairing evidence is retained in the lookup tables and "
                    "their generation audit."
                ),
            )
        )
    return outcomes


def _parse_extraction_table(path: Path) -> dict[tuple[str, str], int]:
    parsed = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "&" not in line or not line.rstrip().endswith("\\"):
            continue
        cells = [cell.strip() for cell in line.removesuffix("\\").split("&")]
        if len(cells) < 5 or not re.fullmatch(r"\d{4}", cells[2]):
            continue
        try:
            count = int(cells[3].replace(",", ""))
        except ValueError:
            continue
        parsed[(cells[1], cells[2])] = count
    return parsed


def check_results_tables(package: Package, results_tab: Path | None) -> list[dict[str, Any]]:
    check_ids = (
        "external_tables.alignment_failures",
        "external_tables.extraction_counts",
    )
    if results_tab is None:
        return [
            result(check_id, "not_run", "Results/tab was not supplied and could not be discovered.")
            for check_id in check_ids
        ]
    results_tab = results_tab.resolve()
    files = {
        "alignment": results_tab / "tab1AlignmentFailures.tex",
        "extraction": results_tab / "tab1ExtractionMethod.tex",
    }
    outcomes = []
    alignment = files["alignment"]
    if not alignment.is_file():
        outcomes.append(result(check_ids[0], "fail", "tab1AlignmentFailures.tex is missing.", path=alignment.name))
    else:
        text = alignment.read_text(encoding="utf-8")
        required = ("Basis of expression", "tab1AlignmentFailures", "Unit", "Species", "Category")
        missing = [value for value in required if value not in text]
        outcomes.append(
            result(
                check_ids[0],
                "pass" if not missing else "fail",
                "The alignment-failures table carries all four dimensions and the expected label." if not missing else "The alignment-failures table is incomplete.",
                path=alignment.name,
                missing=missing,
            )
        )

    extraction = files["extraction"]
    if not extraction.is_file():
        outcomes.append(result(check_ids[1], "fail", "tab1ExtractionMethod.tex is missing.", path=extraction.name))
    else:
        parsed = _parse_extraction_table(extraction)
        file_standard = {
            "pollutant_limits_long.csv": "GB 2762",
            "pesticide_limits_long.csv": "GB 2763",
            "mycotoxin_limits_long.csv": "GB 2761",
            "vetdrug_limits_long.csv": "GB 31650",
            "additive_limits_long.csv": "GB 2760",
        }
        mismatches = []
        for filename, standard in file_standard.items():
            counts = Counter(row["version_year"] for row in package.rows(filename))
            for year, expected in sorted(counts.items()):
                year_standard = (
                    {
                        "2002": "Ministry of Agriculture Announcement 235",
                        "2019": "GB 31650",
                        "2022": "GB 31650.1",
                    }[year]
                    if filename == "vetdrug_limits_long.csv"
                    else standard
                )
                actual = parsed.get((year_standard, year))
                if actual != expected:
                    mismatches.append({"standard": year_standard, "year": year, "table": actual, "data": expected})
        outcomes.append(
            result(
                check_ids[1],
                "pass" if not mismatches else "fail",
                "Extraction-method table row counts match the released long tables." if not mismatches else "Extraction-method table row counts have drifted from the release.",
                path=extraction.name,
                mismatches=mismatches,
            )
        )

    return outcomes


def discover_results_tab(package_root: Path) -> Path | None:
    for ancestor in (package_root, *package_root.parents):
        candidate = ancestor / "Results" / "tab"
        if candidate.is_dir():
            return candidate
    return None


def source_check_catalog() -> tuple[str, ...]:
    fixture_ids = tuple(
        f"source.pollutant_fixture.{item['year']}.p{item['page']}.{item['analyte']}.{item['food']}"
        for item in POLLUTANT_SOURCE_EXPECTATIONS
    )
    basis_ids = tuple(f"source.pollutant_basis.{year}" for year in ("2012", "2017", "2022", "2025"))
    count_ids = tuple(f"source.entity_count_coverage.{case['id']}" for case in ENTITY_COUNT_CASES)
    positional_ids = tuple(f"source.positional_traceback.{case[0]}" for case in POSITIONAL_CASES)
    english_ids = tuple(f"source.english_provenance.{case[0]}" for case in ENGLISH_SOURCE_CASES)
    return (
        "source.input_manifest",
        *fixture_ids,
        *basis_ids,
        *count_ids,
        *positional_ids,
        *english_ids,
        "source.input_selection",
    )


def _safe_source_group(
    expected_ids: tuple[str, ...],
    function: Any,
) -> list[dict[str, Any]]:
    try:
        outcomes = function()
    except Exception as exc:  # noqa: BLE001 - validators must report malformed inputs
        return [
            result(
                check_id,
                "fail",
                "The source-dependent check raised an internal error.",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            for check_id in expected_ids
        ]
    observed = {item["id"] for item in outcomes}
    missing = set(expected_ids) - observed
    outcomes.extend(
        result(check_id, "fail", "The check did not emit its catalogued result ID.")
        for check_id in sorted(missing)
    )
    return outcomes


def run_source_dependent_checks(
    package: Package,
    source_root: Path | Iterable[Path] | None,
    results_tab: Path | None,
) -> list[dict[str, Any]]:
    results_ids = (
        "external_tables.alignment_failures",
        "external_tables.extraction_counts",
    )
    checks = _safe_source_group(
        results_ids,
        lambda: check_results_tables(package, results_tab),
    )
    source_ids = source_check_catalog()
    source_roots = _normalise_source_roots(source_root)
    if not source_roots:
        checks.extend(
            result(check_id, "not_run", "--source-root was not supplied; source-dependent checks were not attempted.")
            for check_id in source_ids
        )
        return checks
    invalid_roots = [root.name for root in source_roots if not root.is_dir()]
    if invalid_roots:
        checks.extend(
            result(
                check_id,
                "not_run",
                "At least one --source-root does not exist or is not a directory.",
                invalid_roots=invalid_roots,
            )
            for check_id in source_ids
        )
        return checks
    index = SourceIndex(source_roots, manifest=package.rows("source_manifest.csv"))
    groups = (
        (("source.input_manifest",), lambda: check_source_manifest_inputs(package, index)),
        (source_ids[1:10], lambda: check_pollutant_source_expectations(package, index)),
        (source_ids[10:14], lambda: check_basis_source_coverage(package, index)),
        (source_ids[14:20], lambda: check_entity_count_coverage(package, index)),
        (source_ids[20:24], lambda: check_positional_traceback(package, index)),
        (source_ids[24:27], lambda: check_english_sources(package, index)),
    )
    for expected_ids, function in groups:
        checks.extend(_safe_source_group(tuple(expected_ids), function))
    checks.extend(_safe_source_group(("source.input_selection",), lambda: check_source_selection(index)))
    return checks


def build_report(
    package_root: Path,
    output: Path,
    source_root: Path | Iterable[Path] | None = None,
    results_tab: Path | None = None,
    auto_results_tab: bool = False,
) -> dict[str, Any]:
    package = Package(package_root)
    source_roots = _normalise_source_roots(source_root)
    resolved_results = results_tab
    if resolved_results is None and auto_results_tab:
        resolved_results = discover_results_tab(package.root)
    self_checks = run_self_contained_checks(package)
    source_checks = run_source_dependent_checks(package, source_roots, resolved_results)
    all_checks = self_checks + source_checks
    status_counts = Counter(item["status"] for item in all_checks)
    if status_counts["fail"]:
        overall = "fail"
    elif status_counts["skip"] or status_counts["not_run"]:
        overall = "partial"
    else:
        overall = "pass"
    return {
        "report_schema_version": "3.0",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "target": package.root.name,
        "inputs": {
            "package_root": ".",
            "source_root": source_roots[0].name if len(source_roots) == 1 else None,
            "source_roots": [root.name for root in source_roots],
            "results_tab": (
                f"{resolved_results.parent.name}/{resolved_results.name}"
                if resolved_results
                else None
            ),
        },
        "environment": {
            "python": sys.version,
            "python_executable": Path(sys.executable).name,
            "platform": platform.platform(),
            "pdftotext": _command_output(["pdftotext", "-v"]),
        },
        "git": git_metadata(package.root),
        "file_hashes": file_hashes(package.root, output),
        "external_input_hashes": external_input_hashes(
            source_checks,
            source_roots,
            resolved_results,
        ),
        "layers": {
            "self_contained": self_checks,
            "source_dependent": source_checks,
        },
        "summary": {
            "overall_status": overall,
            "status_counts": {status: status_counts.get(status, 0) for status in ("pass", "fail", "skip", "not_run")},
            "self_contained_complete": all(item["status"] == "pass" for item in self_checks),
            "source_dependent_complete": all(item["status"] == "pass" for item in source_checks),
            "interpretation": (
                "pass = check completed successfully; fail = completed and found a problem; "
                "skip = a supplied dependency lacked a required case; not_run = dependency or tool unavailable. "
                "skip and not_run are never counted as pass."
            ),
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package-dir",
        type=Path,
        default=SCRIPT_DIR,
        help="Release package to validate (default: directory containing validate.py).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Report path (default: <package-dir>/validation_report.json).",
    )
    parser.add_argument(
        "--source-root",
        dest="source_roots",
        type=Path,
        action="append",
        default=None,
        help=(
            "Optional root containing source standards, extraction copies, or cited "
            "translations. Repeat the option to validate a union of source trees."
        ),
    )
    parser.add_argument(
        "--results-tab",
        type=Path,
        default=None,
        help="Optional Results/tab directory containing the two generated LaTeX tables.",
    )
    parser.add_argument(
        "--auto-results-tab",
        action="store_true",
        help="Search parent directories for Results/tab (off by default for portability).",
    )
    parser.add_argument(
        "--no-auto-results-tab",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--require-source-checks",
        action="store_true",
        help="Exit nonzero when any source-dependent check is skipped or not run.",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress the console summary.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    package_root = args.package_dir.resolve()
    output = args.output.resolve() if args.output else package_root / REPORT_NAME
    report = build_report(
        package_root=package_root,
        output=output,
        source_root=(
            [root.resolve() for root in args.source_roots]
            if args.source_roots
            else None
        ),
        results_tab=args.results_tab.resolve() if args.results_tab else None,
        auto_results_tab=args.auto_results_tab and not args.no_auto_results_tab,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = report["summary"]
    if not args.quiet:
        counts = summary["status_counts"]
        print(
            f"validation {summary['overall_status']}: "
            f"pass={counts['pass']} fail={counts['fail']} "
            f"skip={counts['skip']} not_run={counts['not_run']}"
        )
        print(f"report: {output}")
    if counts := summary["status_counts"]:
        if counts["fail"]:
            return 1
        source_counts = Counter(
            item["status"] for item in report["layers"]["source_dependent"]
        )
        if args.require_source_checks and (
            source_counts["skip"] or source_counts["not_run"]
        ):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
