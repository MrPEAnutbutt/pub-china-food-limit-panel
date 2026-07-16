import importlib.util
import hashlib
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = PROJECT_ROOT / "Data" / "Final" / "china_food_limit_panel_v1"
RESULTS_TAB = PROJECT_ROOT / "Results" / "tab"
SCRIPT = PACKAGE_ROOT / "validate.py"
SPEC = importlib.util.spec_from_file_location("release_validator_v2", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def mutable_package(*filenames):
    package = MODULE.Package(PACKAGE_ROOT)
    for filename in filenames:
        package._rows[filename] = [dict(row) for row in package.rows(filename)]
        package._headers[filename] = list(package.header(filename))
    return package


class FixturePackage:
    def __init__(self, tables):
        self._rows = {
            name: [dict(row) for row in rows] for name, rows in tables.items()
        }

    def rows(self, name):
        return self._rows[name]


def pesticide_long_row(record_id, year, **overrides):
    extraction_copy = year in {"2019", "2021"}
    source_suffix = {"2019": "24", "2021": "25"}.get(year, year[-2:])
    row = {
        "record_id": record_id,
        "standard": "GB 2763",
        "version_year": year,
        "section_number": "1",
        "pesticide_key": "PST-fixture",
        "pesticide_zh": "测试农药",
        "pesticide_en": "test pesticide",
        "pesticide_zh_raw": "测试农药",
        "pesticide_en_raw": "test pesticide",
        "parent_category_zh": "水果",
        "parent_category_raw": "水果",
        "food_key": "FOD-fixture",
        "food_zh": "苹果",
        "food_raw": "苹果",
        "limit_value": "1",
        "unit": "mg/kg",
        "limit_qualifier": "",
        "is_temporary": "false",
        "value_raw": "1",
        "source_page": "10",
        "source_y": "200.0",
        "food_x": "150.0",
        "parent_assignment_method": "inherited_from_left_column_scope",
        "table_open_method": "semantic_maximum_limit_item_4",
        "review_status": "text_layer_auto_extracted",
        "edition_source_id": f"SRC-{year}-edition",
        "extraction_source_id": (
            f"SRC00{source_suffix}" if extraction_copy else f"SRC-{year}-edition"
        ),
        "source_copy_role": (
            "government_hosted_text_layer_extraction_copy"
            if extraction_copy
            else "archive_text_layer_edition_source_copy"
        ),
        "conflict": "0",
    }
    row.update(overrides)
    return row


def pesticide_panel_package(rows):
    spec = MODULE.PANEL_LINEAGE["pesticide_panel.csv"]
    cells = []
    panel = {
        "record_id": "PSP00001",
        "standard": "GB 2763",
        "pesticide_key": rows[0]["pesticide_key"],
        "food_key": rows[0]["food_key"],
        "pesticide_zh": rows[-1]["pesticide_zh"],
        "pesticide_names_zh": json.dumps(
            sorted({row["pesticide_zh"] for row in rows}), ensure_ascii=False
        ),
        "food_zh": rows[-1]["food_zh"],
        "food_names_zh": json.dumps(
            sorted({row["food_zh"] for row in rows}), ensure_ascii=False
        ),
    }
    for year in MODULE.PESTICIDE_YEARS:
        cell = MODULE._expected_pesticide_cell(
            [row for row in rows if row["version_year"] == year],
            spec["rule_columns"],
        )
        cells.append(cell)
        panel[f"v{year}"] = cell["scalar"]
        panel[f"status_{year}"] = cell["status"]
        for field in (
            "values",
            "units",
            "source_record_ids",
            "source_ids",
            "edition_source_ids",
            "extraction_source_ids",
            "rules",
        ):
            panel[f"{field}_{year}"] = json.dumps(
                cell[field], ensure_ascii=False, separators=(",", ":")
            )
        panel[f"candidate_count_{year}"] = str(cell["candidate_count"])
        panel[f"distinct_value_count_{year}"] = str(
            cell["distinct_value_count"]
        )
    panel["n_versions"] = str(
        sum(cell["status"] != "missing" for cell in cells)
    )
    panel["trend"] = MODULE._expected_pesticide_trend(cells)
    return FixturePackage(
        {
            "pesticide_limits_long.csv": rows,
            "pesticide_panel.csv": [panel],
            "additive_limits_long.csv": [],
            "additive_panel.csv": [],
        }
    )


def pesticide_release_package():
    rows = [
        pesticide_long_row(f"PES{index:05d}", year)
        for index, year in enumerate(MODULE.PESTICIDE_YEARS, 1)
    ]
    reconciliation = [
        {
            "standard": "GB 2763",
            "version_year": year,
            "declared_mrl_items": "1",
            "coordinate_extracted_visible_rules": "1",
            "visible_rules_minus_declared": "0",
            "declared_section_roster": "1",
            "extracted_section_headers": "1",
            "section_roster_complete": "True",
            "qualifier_counts": '{"none":1}',
            "status": "exact_visible_rule_count_reconciliation",
            "interpretation_boundary": "aggregate reconciliation only",
        }
        for year in MODULE.PESTICIDE_YEARS
    ]
    crosscheck = [
        {
            "year": year,
            "section_number": "1",
            "parent_category": "水果",
            "food": "苹果",
            "text_values": "1",
            "ocr_values": "",
            "status": "text_only",
            "key_level": "strict_scope",
            "text_row_count": "1",
            "ocr_row_count": "0",
            "text_source_pages": "10",
            "ocr_source_pages": "",
        }
        for year in ("2019", "2021")
    ]
    expected = {
        year: (1, 1, 0, 1, "exact_visible_rule_count_reconciliation")
        for year in MODULE.PESTICIDE_YEARS
    }
    package = FixturePackage(
        {
            "pesticide_limits_long.csv": rows,
            "pesticide_edition_reconciliation.csv": reconciliation,
            "pesticide_ocr_crosscheck.csv": crosscheck,
        }
    )
    return package, expected


class ReleaseValidatorV2Tests(unittest.TestCase):
    def test_additive_panel_rule_contract_preserves_source_ids(self):
        columns = MODULE.PANEL_LINEAGE["additive_panel.csv"]["rule_columns"]

        self.assertIn("edition_source_id", columns)
        self.assertIn("extraction_source_id", columns)

    @classmethod
    def setUpClass(cls):
        cls.package = MODULE.Package(PACKAGE_ROOT)
        cls.report = MODULE.build_report(
            package_root=PACKAGE_ROOT,
            output=PACKAGE_ROOT / MODULE.REPORT_NAME,
            source_root=None,
            results_tab=None,
            auto_results_tab=False,
        )

    def require_v3_release(self):
        path = PACKAGE_ROOT / "pesticide_edition_reconciliation.csv"
        if not path.is_file():
            self.skipTest("release v3 package has not been rebuilt yet")
        if self.package.header("pesticide_panel.csv") != list(
            MODULE.EXPECTED_HEADERS["pesticide_panel.csv"]
        ):
            self.skipTest("release v3 package has not been rebuilt yet")

    def test_default_run_is_script_relative_and_package_only(self):
        args = MODULE.parse_args([])

        self.assertEqual(args.package_dir, SCRIPT.parent)
        self.assertFalse(args.auto_results_tab)
        self.assertIsNone(self.report["inputs"]["results_tab"])
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("/Volumes/", source)
        self.assertNotIn("/Users/", source)

    def test_all_self_contained_checks_pass(self):
        self.require_v3_release()
        failures = [
            item
            for item in self.report["layers"]["self_contained"]
            if item["status"] != "pass"
        ]

        self.assertEqual(failures, [])
        normalization = next(
            item
            for item in self.report["layers"]["self_contained"]
            if item["id"] == "package.pollutant_normalization"
        )
        self.assertEqual(normalization["status"], "pass")

    def test_missing_and_empty_source_trees_keep_fixed_catalog(self):
        absent = MODULE.run_source_dependent_checks(
            self.package,
            source_root=None,
            results_tab=None,
        )
        with tempfile.TemporaryDirectory() as directory:
            empty = MODULE.run_source_dependent_checks(
                self.package,
                source_root=Path(directory),
                results_tab=None,
            )

        absent_source = {item["id"] for item in absent if item["id"].startswith("source.")}
        empty_source = {item["id"] for item in empty if item["id"].startswith("source.")}
        self.assertEqual(absent_source, set(MODULE.source_check_catalog()))
        self.assertEqual(empty_source, absent_source)
        self.assertTrue(
            all(item["status"] == "not_run" for item in absent if item["id"].startswith("source."))
        )
        self.assertTrue(
            all(item["status"] == "skip" for item in empty if item["id"].startswith("source."))
        )
        self.assertFalse(any("pass" in item for item in absent + empty))

    def test_dictionary_and_exact_headers_cover_release(self):
        self.require_v3_release()
        outcome = MODULE.check_data_dictionary(self.package)[0]
        integrity = MODULE.check_csv_integrity(self.package)[0]

        self.assertEqual(outcome["status"], "pass", outcome)
        self.assertEqual(integrity["status"], "pass", integrity)
        self.assertEqual(
            outcome["details"]["documented_fields"],
            outcome["details"]["actual_fields"],
        )

    def test_unsafe_additive_prefix_member_panel_is_not_released(self):
        self.assertNotIn("additive_member_panel.csv", MODULE.CSV_FILES)
        self.assertFalse((PACKAGE_ROOT / "additive_member_panel.csv").exists())
        build_source = (
            PROJECT_ROOT / "Program" / "Clean" / "260714_build_release.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("member_crosswalk_additive.csv", build_source)

    def test_unexpected_year_column_fails_exact_header_contract(self):
        package = mutable_package("pesticide_panel.csv")
        package._headers["pesticide_panel.csv"].append("v2099")

        outcome = MODULE.check_csv_integrity(package)[0]

        self.assertEqual(outcome["status"], "fail")
        malformed = next(
            item
            for item in outcome["details"]["malformed"]
            if item["file"] == "pesticide_panel.csv"
        )
        self.assertIn("v2099", malformed["unexpected_columns"])

    def test_short_csv_row_is_detected(self):
        package = mutable_package("pollutant_limits_long.csv")
        package._rows["pollutant_limits_long.csv"][0]["unit"] = None

        outcome = MODULE.check_csv_integrity(package)[0]

        self.assertEqual(outcome["status"], "fail")
        malformed = next(
            item
            for item in outcome["details"]["malformed"]
            if item["file"] == "pollutant_limits_long.csv"
        )
        self.assertTrue(malformed["short_rows"])

    def test_nonfinite_number_is_rejected_by_dictionary(self):
        self.require_v3_release()
        package = mutable_package("pesticide_limits_long.csv")
        package._rows["pesticide_limits_long.csv"][0]["limit_value"] = "NaN"

        outcome = MODULE.check_data_dictionary(package)[0]

        self.assertEqual(outcome["status"], "fail")
        self.assertTrue(outcome["details"]["type_errors"])

    def test_panel_lineage_recomputes_every_derived_cell_field(self):
        self.require_v3_release()
        mutations = {
            "scalar": lambda row: row.__setitem__("v2024", "999"),
            "values": lambda row: row.__setitem__("values_2024", '["999"]'),
            "units": lambda row: row.__setitem__("units_2024", '["mg/L"]'),
            "status": lambda row: row.__setitem__("status_2024", "multiple_same_value"),
            "candidate_count": lambda row: row.__setitem__("candidate_count_2024", "99"),
        }
        for label, mutate in mutations.items():
            with self.subTest(field=label):
                package = mutable_package("additive_panel.csv")
                row = next(
                    item
                    for item in package._rows["additive_panel.csv"]
                    if item["status_2024"] == "single"
                )
                mutate(row)
                outcome = MODULE.check_panel_lineage(package)[0]
                self.assertEqual(outcome["status"], "fail", outcome)

        package = mutable_package("additive_panel.csv")
        row = next(
            item
            for item in package._rows["additive_panel.csv"]
            if item["status_2024"] == "single"
        )
        rules = json.loads(row["rules_2024"])
        rules[0]["max_use"] = "999"
        row["rules_2024"] = json.dumps(rules, ensure_ascii=False, separators=(",", ":"))
        outcome = MODULE.check_panel_lineage(package)[0]
        self.assertEqual(outcome["status"], "fail", outcome)

        package = mutable_package("additive_panel.csv")
        row = next(
            item
            for item in package._rows["additive_panel.csv"]
            if item["status_2024"] == "single"
        )
        rules = json.loads(row["rules_2024"])
        rules[0]["edition_source_id"] = "SRC-unknown"
        row["rules_2024"] = json.dumps(
            rules, ensure_ascii=False, separators=(",", ":")
        )
        outcome = MODULE.check_panel_lineage(package)[0]
        self.assertEqual(outcome["status"], "fail", outcome)

    def test_panel_lineage_recomputes_additive_scope_state(self):
        self.require_v3_release()
        package = mutable_package("additive_panel.csv")
        row = next(
            item
            for item in package._rows["additive_panel.csv"]
            if item["trend"] == "incomparable_scope_text"
        )
        row["trend"] = "stable"

        outcome = MODULE.check_panel_lineage(package)[0]

        self.assertEqual(outcome["status"], "fail", outcome)
        problem = next(
            item
            for item in outcome["details"]["problems"]
            if item.get("record_id") == row["record_id"]
            and item.get("problem") == "trend does not reproduce the edition cells"
        )
        self.assertEqual(problem["expected"], "incomparable_scope_text")

    def test_pesticide_panel_fixture_conserves_records_and_source_ids(self):
        rows = [
            pesticide_long_row("PES00001", "2012"),
            pesticide_long_row("PES00002", "2014"),
        ]
        package = pesticide_panel_package(rows)

        baseline = MODULE.check_panel_lineage(package)[0]
        self.assertEqual(baseline["status"], "pass", baseline)

        panel = package.rows("pesticide_panel.csv")[0]
        panel["source_record_ids_2014"] = "[]"
        mutated = MODULE.check_panel_lineage(package)[0]
        self.assertEqual(mutated["status"], "fail", mutated)
        self.assertTrue(
            any(
                problem["problem"]
                == "panel record lineage does not conserve the long table exactly once"
                for problem in mutated["details"]["problems"]
            )
        )

        package = pesticide_panel_package(rows)
        panel = package.rows("pesticide_panel.csv")[0]
        panel["extraction_source_ids_2014"] = '["SRC-unknown"]'
        mutated = MODULE.check_panel_lineage(package)[0]
        self.assertEqual(mutated["status"], "fail", mutated)
        cell_problem = next(
            problem
            for problem in mutated["details"]["problems"]
            if problem.get("year") == "2014"
        )
        self.assertIn("extraction_source_ids", cell_problem["mismatched_fields"])

    def test_pesticide_panel_scope_gates_detect_semantic_mutations(self):
        cases = {
            "qualifier": {
                "limit_qualifier": "as_fat",
            },
            "temporary": {
                "limit_qualifier": "temporary_mrl_asterisk",
                "is_temporary": "true",
            },
            "food_exclusion": {"food_raw": "苹果（青苹果除外）"},
            "chemical_form": {
                "pesticide_zh_raw": "测试农药（铵盐）",
                "pesticide_en_raw": "test pesticide ammonium salt",
            },
            "parent_category": {
                "parent_category_zh": "水果制品",
                "parent_category_raw": "水果制品",
            },
        }
        for label, overrides in cases.items():
            with self.subTest(label=label):
                rows = [
                    pesticide_long_row("PES00001", "2012", limit_value="1"),
                    pesticide_long_row(
                        "PES00002", "2014", limit_value="0.5", **overrides
                    ),
                ]
                package = pesticide_panel_package(rows)
                panel = package.rows("pesticide_panel.csv")[0]
                self.assertEqual(panel["trend"], "incomparable_scope_text")
                self.assertEqual(
                    MODULE.check_panel_lineage(package)[0]["status"], "pass"
                )

                panel["trend"] = "tightened"
                outcome = MODULE.check_panel_lineage(package)[0]
                self.assertEqual(outcome["status"], "fail", outcome)

        rows = [
            pesticide_long_row("PES00001", "2012"),
            pesticide_long_row(
                "PES00002",
                "2014",
                limit_qualifier="source_marker_c_unresolved",
            ),
        ]
        package = pesticide_panel_package(rows)
        self.assertEqual(
            package.rows("pesticide_panel.csv")[0]["trend"],
            "incomparable_unresolved_review_or_source_qualifier",
        )
        self.assertEqual(MODULE.check_panel_lineage(package)[0]["status"], "pass")

    def test_pesticide_release_fixture_detects_audit_mutations(self):
        mutations = {
            "reconciliation": lambda package: package.rows(
                "pesticide_edition_reconciliation.csv"
            )[0].__setitem__("coordinate_extracted_visible_rules", "2"),
            "qualifier_count": lambda package: package.rows(
                "pesticide_edition_reconciliation.csv"
            )[0].__setitem__("qualifier_counts", '{"none":2}'),
            "temporary_flag": lambda package: package.rows(
                "pesticide_limits_long.csv"
            )[0].__setitem__("is_temporary", "true"),
            "unknown_review_status": lambda package: package.rows(
                "pesticide_limits_long.csv"
            )[0].__setitem__(
                "review_status", "text_layer_auto_extracted;undocumented_flag"
            ),
            "ocr_status": lambda package: package.rows(
                "pesticide_ocr_crosscheck.csv"
            )[0].__setitem__("status", "consistent"),
            "ocr_text_group_key": lambda package: package.rows(
                "pesticide_ocr_crosscheck.csv"
            )[0].__setitem__("food", "不存在食品"),
            "ocr_text_value": lambda package: package.rows(
                "pesticide_ocr_crosscheck.csv"
            )[0].__setitem__("text_values", "999999"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                package, expected = pesticide_release_package()
                with mock.patch.object(
                    MODULE, "PESTICIDE_RECONCILIATION_EXPECTED", expected
                ):
                    baseline = MODULE.check_pesticide_release_contract(package)[0]
                    self.assertEqual(baseline["status"], "pass", baseline)
                    mutate(package)
                    outcome = MODULE.check_pesticide_release_contract(package)[0]
                self.assertEqual(outcome["status"], "fail", outcome)

    def test_ocr_audit_rejects_value_count_drift(self):
        package = mutable_package("pesticide_ocr_crosscheck.csv")
        baseline = MODULE.check_pesticide_release_contract(package)[0]
        self.assertEqual(baseline["status"], "pass", baseline)
        rows = package.rows("pesticide_ocr_crosscheck.csv")
        row_index, row = next(
            (index, item)
            for index, item in enumerate(rows, 2)
            if item["status"] == "conflict"
        )
        row["ocr_row_count"] = "999"
        row["ocr_values"] = "999999"

        outcome = MODULE.check_pesticide_release_contract(package)[0]

        self.assertEqual(outcome["status"], "fail", outcome)
        self.assertTrue(
            any(
                problem.get("row") == row_index
                and problem["problem"]
                == "OCR crosscheck status or text-side long-table lineage is inconsistent"
                for problem in outcome["details"]["problems"]
            ),
            outcome,
        )

    def test_timeline_conflict_fixture_requires_one_reproducible_selection(self):
        timeline = [
            {
                "record_id": "TML00001",
                "std_id": "GB 14936",
                "number": "14936",
                "event_type": "official_version",
                "version_year": "2012",
                "amendment_no": "",
                "issue_date": "2012-12-25",
                "effective_date": "2013-01-25",
                "title_zh": "食品添加剂硅藻土",
            }
        ]
        candidates = []
        for rank, selected, title, issue, effective in (
            (1, "1", "食品添加剂硅藻土", "2012-12-25", "2013-01-25"),
            (2, "0", "硅藻土", "2012-05-17", "2012-11-17"),
        ):
            candidates.append(
                {
                    "conflict_id": "TLC0001",
                    "std_id": "GB 14936",
                    "number": "14936",
                    "version_year": "2012",
                    "conflict_type": "official_version_metadata_conflict",
                    "candidate_rank": str(rank),
                    "selected": selected,
                    "equivalent_row_count": "1",
                    "timeline_title_match": "1" if rank == 1 else "0",
                    "anchor_category_match": "1" if rank == 1 else "0",
                    "issue_date": issue,
                    "effective_date": effective,
                    "official_category": "食品添加剂",
                    "title_zh": title,
                    "normalized_title": title,
                    "timeline_title": "食品添加剂硅藻土",
                    "anchor_category": "食品添加剂",
                    "raw_titles": title,
                    "selection_reason": "stable rank",
                }
            )
        package = FixturePackage(
            {
                "standard_version_timeline.csv": timeline,
                "standard_timeline_conflicts.csv": candidates,
            }
        )

        self.assertEqual(MODULE.check_timeline_conflicts(package)[0]["status"], "pass")

        empty_package = FixturePackage(
            {
                "standard_version_timeline.csv": timeline,
                "standard_timeline_conflicts.csv": [],
            }
        )
        self.assertEqual(
            MODULE.check_timeline_conflicts(empty_package)[0]["status"],
            "fail",
        )

        drifted_candidates = [dict(candidate) for candidate in candidates]
        drifted_candidates[1]["issue_date"] = "1900-01-01"
        drifted_package = FixturePackage(
            {
                "standard_version_timeline.csv": timeline,
                "standard_timeline_conflicts.csv": drifted_candidates,
            }
        )
        self.assertEqual(
            MODULE.check_timeline_conflicts(drifted_package)[0]["status"],
            "fail",
        )

        candidates[1]["selected"] = "1"
        package = FixturePackage(
            {
                "standard_version_timeline.csv": timeline,
                "standard_timeline_conflicts.csv": candidates,
            }
        )
        self.assertEqual(MODULE.check_timeline_conflicts(package)[0]["status"], "fail")

    def test_pollutant_and_quarantine_mutations_fail(self):
        package = mutable_package("pollutant_limits_long.csv")
        package._rows["pollutant_limits_long.csv"][0]["normalization_status"] = "density_required"
        self.assertEqual(MODULE.check_pollutant_normalization(package)[0]["status"], "fail")

        package = mutable_package("pollutant_member_panel.csv")
        member = next(
            row
            for row in package.rows("pollutant_member_panel.csv")
            if row["v2012"] and not row["trend"].startswith("incomparable_")
        )
        member["v2012"] = "999999"
        self.assertEqual(
            MODULE.check_pollutant_panel_contract(package)[0]["status"],
            "fail",
        )

        package = mutable_package("pollutant_category_panel.csv")
        category = next(
            row
            for row in package.rows("pollutant_category_panel.csv")
            if row["trend"] == "stable" and row["coverage_status"] == "all_editions"
        )
        category["trend"] = "relaxed"
        self.assertEqual(
            MODULE.check_pollutant_panel_contract(package)[0]["status"],
            "fail",
        )

        package = mutable_package("pollutant_category_panel.csv")
        category = package.rows("pollutant_category_panel.csv")[0]
        category["coverage_status"] = "internal_gap_review"
        category["analyte_en"] = "wrong analyte"
        self.assertEqual(
            MODULE.check_pollutant_panel_contract(package)[0]["status"],
            "fail",
        )

        package = mutable_package("quarantined_rows.csv")
        package._rows["quarantined_rows.csv"][0]["source_path"] = "/Volumes/private/source.pdf"
        self.assertEqual(MODULE.check_quarantine_contract(package)[0]["status"], "fail")

    def test_vetdrug_fixture_requires_edition_identity_and_2002_locator(self):
        row = {
            "record_id": "VET00001",
            "standard": "MOA Announcement 235",
            "version_year": "2002",
            "source_table_index": "1",
            "source_table_row": "2",
            "animal_block_index": "1",
            "tissue_index": "1",
        }
        package = FixturePackage({"vetdrug_limits_long.csv": [row]})
        self.assertEqual(MODULE.check_vetdrug_provenance(package)[0]["status"], "pass")

        duplicate_locator = {**row, "record_id": "VET00002"}
        package = FixturePackage(
            {"vetdrug_limits_long.csv": [row, duplicate_locator]}
        )
        self.assertEqual(
            MODULE.check_vetdrug_provenance(package)[0]["status"],
            "fail",
        )

        row["standard"] = "GB 31650"
        row["tissue_index"] = ""
        package = FixturePackage({"vetdrug_limits_long.csv": [row]})
        self.assertEqual(MODULE.check_vetdrug_provenance(package)[0]["status"], "fail")

    def test_version_dates_reject_reverse_chronology_and_timeline_drift(self):
        package = mutable_package("version_dates.csv")
        row = next(
            item
            for item in package.rows("version_dates.csv")
            if item["source_id"] != "SRC0018"
            and not item["official_register_issue_date"]
        )
        row["issue_date"] = "2026-12-31"
        row["effective_date"] = "2026-01-01"
        outcome = MODULE.check_version_dates(package)[0]
        self.assertEqual(outcome["status"], "fail", outcome)
        self.assertTrue(
            any(
                problem["record_id"] == row["record_id"]
                and problem["problem"] == "issue_date is later than effective_date"
                for problem in outcome["details"]["date_problems"]
            )
        )

        package = mutable_package(
            "version_dates.csv", "standard_version_timeline.csv"
        )
        date_row = next(
            item
            for item in package.rows("version_dates.csv")
            if item["official_register_issue_date"]
        )
        timeline_row = next(
            item
            for item in package.rows("standard_version_timeline.csv")
            if item["event_type"] == "official_version"
            and item["std_id"] == date_row["standard"]
            and item["version_year"] == date_row["version_year"]
        )
        timeline_row["issue_date"] = "1900-01-01"
        outcome = MODULE.check_version_dates(package)[0]
        self.assertEqual(outcome["status"], "fail", outcome)
        self.assertTrue(
            any(
                problem["record_id"] == date_row["record_id"]
                and problem["problem"]
                == "official-register dates do not match exactly one official timeline row"
                for problem in outcome["details"]["date_problems"]
            )
        )

        package = mutable_package("standard_version_timeline.csv")
        amendment = next(
            item
            for item in package.rows("standard_version_timeline.csv")
            if item["event_type"] == "amendment"
            and item["issue_date"]
            and item["effective_date"]
        )
        amendment["issue_date"] = "2025-12-31"
        amendment["effective_date"] = "2025-01-01"
        outcome = MODULE.check_version_dates(package)[0]
        self.assertEqual(outcome["status"], "fail", outcome)
        self.assertTrue(
            any(
                problem["record_id"] == amendment["record_id"]
                and problem["problem"]
                == "timeline issue_date is later than effective_date"
                for problem in outcome["details"]["date_problems"]
            )
        )

    def test_lookup_keys_and_chinese_side_joins_detect_mutations(self):
        package = mutable_package("entity_names_en.csv")
        row = next(
            item
            for item in package.rows("entity_names_en.csv")
            if item["entity_type"] == "pesticide"
        )
        row["entity_key"] = "PST-deadbeefdeadbeef"
        outcome = MODULE.check_lookup_integrity(package)[0]
        self.assertEqual(outcome["status"], "fail", outcome)

        package = mutable_package("entity_names_en.csv")
        row = next(
            item
            for item in package.rows("entity_names_en.csv")
            if item["entity_type"] == "contaminant_or_mycotoxin"
        )
        row["name_zh"] = "不存在分析物"
        outcome = MODULE.check_lookup_integrity(package)[0]
        self.assertTrue(
            any(
                problem.get("record_id") == row["record_id"]
                and "bilingual pair" in problem["problem"]
                for problem in outcome["details"]["problems"]
            ),
            outcome,
        )

        package = mutable_package("food_category_names_en.csv")
        row = next(
            item
            for item in package.rows("food_category_names_en.csv")
            if item["family"] == "pesticide"
        )
        row["food_zh"] = "不存在食品"
        outcome = MODULE.check_lookup_integrity(package)[0]
        self.assertEqual(outcome["status"], "fail", outcome)

        package = mutable_package(
            "pesticide_limits_long.csv", "entity_names_en.csv"
        )
        long_row = package.rows("pesticide_limits_long.csv")[0]
        original_key = long_row["pesticide_key"]
        corrupted_key = "PST-deadbeefdeadbeef"
        for item in package.rows("pesticide_limits_long.csv"):
            if item["pesticide_key"] == original_key:
                item["pesticide_key"] = corrupted_key
        lookup_row = next(
            item
            for item in package.rows("entity_names_en.csv")
            if item["entity_type"] == "pesticide"
            and item["entity_key"] == original_key
        )
        lookup_row["entity_key"] = corrupted_key
        outcome = MODULE.check_lookup_integrity(package)[0]
        self.assertTrue(
            any(
                problem["problem"]
                == "pesticide key is not reproducible from the released identity"
                for problem in outcome["details"]["problems"]
            ),
            outcome,
        )

        package = mutable_package(
            "pesticide_limits_long.csv", "food_category_names_en.csv"
        )
        long_row = package.rows("pesticide_limits_long.csv")[0]
        original_key = long_row["food_key"]
        corrupted_key = "FOD-deadbeefdeadbeef"
        for item in package.rows("pesticide_limits_long.csv"):
            if item["food_key"] == original_key:
                item["food_key"] = corrupted_key
        lookup_row = next(
            item
            for item in package.rows("food_category_names_en.csv")
            if item["family"] == "pesticide" and item["food_key"] == original_key
        )
        lookup_row["food_key"] = corrupted_key
        outcome = MODULE.check_lookup_integrity(package)[0]
        self.assertTrue(
            any(
                problem["problem"]
                == "food key is not reproducible from the released Chinese label"
                for problem in outcome["details"]["problems"]
            ),
            outcome,
        )

        package = mutable_package("additive_names_en.csv")
        package.rows("additive_names_en.csv")[0]["cns_code"] = "bad"
        outcome = MODULE.check_lookup_integrity(package)[0]
        self.assertEqual(outcome["status"], "fail", outcome)

    def test_english_pdf_check_is_explicitly_a_vocabulary_screen(self):
        package = FixturePackage(
            {
                "additive_names_en.csv": [{"name_en": "Glycine"}],
                "food_category_names_en.csv": [
                    {"family": "additive", "food_en": "Apple"},
                    {"family": "pesticide", "food_en": "Melon"},
                ],
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = b"fixture"
            fixture_lock = (len(fixture), hashlib.sha256(fixture).hexdigest())
            (root / "GAIN_GB2760-2014_en.pdf").write_bytes(fixture)
            (root / "FSIS_GB2763-2016_en.pdf").write_bytes(fixture)
            index = MODULE.SourceIndex(root)
            locks = dict(MODULE.TRANSLATION_SOURCE_LOCKS)
            locks["GAIN_GB2760-2014_en.pdf"] = fixture_lock
            locks["FSIS_GB2763-2016_en.pdf"] = fixture_lock
            with (
                mock.patch.object(MODULE, "TRANSLATION_SOURCE_LOCKS", locks),
                mock.patch.object(
                    MODULE,
                    "_pdf_text",
                    return_value="Glycine Apple Melon",
                ),
            ):
                outcomes = MODULE.check_english_sources(package, index)

        self.assertTrue(all(item["status"] == "pass" for item in outcomes))
        self.assertTrue(
            all("vocabulary-occurrence" in item["message"].lower() for item in outcomes)
        )
        self.assertTrue(
            all(
                "does not validate a Chinese-English row pairing"
                in item["details"]["interpretation_boundary"]
                for item in outcomes
            )
        )

    def test_mycotoxin_and_vetdrug_lineage_detect_value_mutations(self):
        package = mutable_package("mycotoxin_panel.csv")
        baseline = MODULE.check_mycotoxin_panel_lineage(package)[0]
        self.assertEqual(baseline["status"], "pass", baseline)
        panel_row = next(
            row
            for row in package.rows("mycotoxin_panel.csv")
            if any(row[f"v{year}"] for year in ("2005", "2011", "2017"))
        )
        year = next(
            year
            for year in ("2005", "2011", "2017")
            if panel_row[f"v{year}"]
        )
        panel_row[f"v{year}"] = "999999"
        outcome = MODULE.check_mycotoxin_panel_lineage(package)[0]
        self.assertEqual(outcome["status"], "fail", outcome)

        package = mutable_package("mycotoxin_member_panel.csv")
        baseline = MODULE.check_mycotoxin_panel_lineage(package)[0]
        self.assertEqual(baseline["status"], "pass", baseline)
        member_row = next(
            row
            for row in package.rows("mycotoxin_member_panel.csv")
            if any(row[f"v{year}"] for year in ("2005", "2011", "2017"))
        )
        year = next(
            year
            for year in ("2005", "2011", "2017")
            if member_row[f"v{year}"]
        )
        member_row[f"v{year}"] = "999999"
        outcome = MODULE.check_mycotoxin_panel_lineage(package)[0]
        self.assertEqual(outcome["status"], "fail", outcome)

        mycotoxin_long = [
            {
                "version_year": year,
                "toxin_zh": "测试毒素",
                "toxin_en": "test toxin",
                "food_category_zh": "测试食品",
                "limit_value": value,
                "unit": "μg/kg",
            }
            for year, value in (("2005", "1"), ("2011", "3"), ("2017", "2"))
        ]
        mycotoxin_summary = {
            "record_id": "MSP00001",
            "standard": "GB 2761",
            "toxin_zh": "测试毒素",
            "toxin_en": "test toxin",
            "food_zh": "测试食品",
            "v2005": "1",
            "v2011": "3",
            "v2017": "2",
            "unit": "μg/kg",
            "trend": "fluctuation",
        }
        package = FixturePackage(
            {
                "mycotoxin_limits_long.csv": mycotoxin_long,
                "mycotoxin_panel.csv": [mycotoxin_summary],
                "mycotoxin_member_panel.csv": [],
            }
        )
        baseline = MODULE.check_mycotoxin_panel_lineage(package)[0]
        self.assertEqual(baseline["status"], "pass", baseline)
        package.rows("mycotoxin_panel.csv")[0]["trend"] = "relaxed"
        outcome = MODULE.check_mycotoxin_panel_lineage(package)[0]
        self.assertEqual(outcome["status"], "fail", outcome)

        package = FixturePackage(
            {
                "mycotoxin_limits_long.csv": mycotoxin_long,
                "mycotoxin_panel.csv": [mycotoxin_summary],
                "mycotoxin_member_panel.csv": [],
            }
        )
        package.rows("mycotoxin_panel.csv")[0]["toxin_en"] = "wrong toxin"
        outcome = MODULE.check_mycotoxin_panel_lineage(package)[0]
        self.assertEqual(outcome["status"], "fail", outcome)

        long_rows = [
            {
                "record_id": "VET00001",
                "version_year": "2002",
                "drug_zh": "测试兽药",
                "drug_en": "test drug",
                "tissue_zh": "肌肉",
                "limit_value": "100",
            },
            {
                "record_id": "VET00002",
                "version_year": "2019",
                "drug_zh": "测试兽药",
                "drug_en": "test drug",
                "tissue_zh": "肌肉",
                "limit_value": "50",
            },
        ]
        summary_row = {
            "record_id": "VSP00001",
            "standard": "GB 31650",
            "drug_zh": "测试兽药",
            "drug_en": "test drug",
            "tissue_zh": "肌肉",
            "v2002": "100",
            "v2019": "50",
            "unit": "μg/kg",
            "trend": "tightened",
        }
        member_row = {
            "record_id": "VMP00001",
            "standard": "GB 31650",
            "drug_zh": "测试兽药",
            "drug_en": "test drug",
            "animal": "牛",
            "tissue_zh": "肌肉",
            "v2002": "0.1",
            "v2019": "0.05",
            "v2022": "",
            "unit": "mg/kg",
            "trend": "tightened",
        }

        def vet_fixture():
            return FixturePackage(
                {
                    "vetdrug_limits_long.csv": long_rows,
                    "vetdrug_panel.csv": [summary_row],
                    "vetdrug_member_panel.csv": [member_row],
                }
            )

        package = vet_fixture()
        baseline = MODULE.check_vetdrug_panel_lineage(package)[0]
        self.assertEqual(baseline["status"], "pass", baseline)
        package.rows("vetdrug_panel.csv")[0]["v2019"] = "999"
        outcome = MODULE.check_vetdrug_panel_lineage(package)[0]
        self.assertEqual(outcome["status"], "fail", outcome)

        package = vet_fixture()
        package.rows("vetdrug_member_panel.csv")[0]["v2019"] = "999"
        outcome = MODULE.check_vetdrug_panel_lineage(package)[0]
        self.assertEqual(outcome["status"], "fail", outcome)

        package = vet_fixture()
        package.rows("vetdrug_panel.csv")[0]["drug_zh"] = "错误中文名"
        outcome = MODULE.check_vetdrug_panel_lineage(package)[0]
        self.assertEqual(outcome["status"], "fail", outcome)

        package = vet_fixture()
        package.rows("vetdrug_member_panel.csv")[0]["drug_en"] = "wrong drug"
        outcome = MODULE.check_vetdrug_panel_lineage(package)[0]
        self.assertEqual(outcome["status"], "fail", outcome)

    def test_source_manifest_and_pesticide_release_contract_are_green(self):
        self.require_v3_release()
        manifest = MODULE.check_source_manifest(self.package)[0]
        pesticide = MODULE.check_pesticide_release_contract(self.package)[0]

        self.assertEqual(manifest["status"], "pass", manifest)
        expected_total = sum(
            len(self.package.rows(filename))
            for filename in MODULE.FAMILY_VERSIONS
        )
        self.assertEqual(
            manifest["details"]["released_limit_rows"], expected_total
        )
        self.assertEqual(
            manifest["details"]["role_counts"]["extraction_copy"], 2
        )
        self.assertEqual(pesticide["status"], "pass", pesticide)
        self.assertEqual(
            pesticide["details"]["released_rows_by_year"],
            {
                year: expected[1]
                for year, expected in MODULE.PESTICIDE_RECONCILIATION_EXPECTED.items()
            },
        )

    def test_manifest_digest_mutation_fails(self):
        self.require_v3_release()
        package = mutable_package("source_manifest.csv")
        package._rows["source_manifest.csv"][0]["sha256"] = "bad"

        outcome = MODULE.check_source_manifest(package)[0]

        self.assertEqual(outcome["status"], "fail")

    def test_source_acquisition_guide_drift_fails_manifest_contract(self):
        self.require_v3_release()
        package = mutable_package("source_manifest.csv")
        original_path = package.path
        with tempfile.TemporaryDirectory() as directory:
            broken_guide = Path(directory) / "SOURCE_ACQUISITION.md"
            broken_guide.write_text("# incomplete guide\n", encoding="utf-8")
            with mock.patch.object(
                package,
                "path",
                side_effect=lambda name: (
                    broken_guide
                    if name == "SOURCE_ACQUISITION.md"
                    else original_path(name)
                ),
            ):
                outcome = MODULE.check_source_manifest(package)[0]

        self.assertEqual(outcome["status"], "fail", outcome)
        self.assertTrue(
            any(
                "source-acquisition guide" in problem["problem"]
                for problem in outcome["details"]["problems"]
            ),
            outcome,
        )

    def test_translation_byte_lock_mismatch_fails_input_manifest(self):
        self.require_v3_release()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            filename = next(iter(MODULE.TRANSLATION_SOURCE_LOCKS))
            (root / filename).write_bytes(b"wrong translation bytes")
            index = MODULE.SourceIndex(root, self.package.rows("source_manifest.csv"))
            outcome = MODULE.check_source_manifest_inputs(self.package, index)[0]

        self.assertEqual(outcome["status"], "fail", outcome)
        self.assertTrue(
            any(
                item["source_id"] == f"translation:{filename}"
                for item in outcome["details"]["mismatched"]
            ),
            outcome,
        )

    def test_numeric_traceback_uses_value_boundaries(self):
        pattern = MODULE._value_pattern("0.1")

        self.assertIsNone(pattern.search("food0.15next"))
        self.assertIsNotNone(pattern.search("food0.1unit"))
        self.assertIsNotNone(pattern.search("food0.104.01next-row"))

    def test_pollutant_traceback_exclusions_are_explicit(self):
        self.assertEqual(
            MODULE.POLLUTANT_POSITIONAL_EXCLUSIONS,
            {"总汞", "甲基汞", "总砷", "无机砷", "亚硝酸盐", "硝酸盐"},
        )

    def test_traceback_uses_the_full_eligible_population(self):
        rows = [{"row": str(index)} for index in range(75)]

        selected, scope = MODULE._select_positional_rows(rows)

        self.assertEqual(selected, rows)
        self.assertEqual(scope, "eligible_row_census")

    def test_content_distinct_source_candidates_fail_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a").mkdir()
            (root / "b").mkdir()
            (root / "a" / "same.pdf").write_bytes(b"first")
            (root / "b" / "same.pdf").write_bytes(b"second")
            index = MODULE.SourceIndex(root)
            index.exact("same.pdf")
            outcome = MODULE.check_source_selection(index)[0]

        self.assertEqual(outcome["status"], "fail")
        self.assertTrue(outcome["details"]["problems"])

    def test_repeatable_source_root_builds_union_index_and_hashes_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive"
            supplemental = root / "supplemental"
            archive.mkdir()
            supplemental.mkdir()
            standard = archive / "standard.pdf"
            translation = supplemental / "translation.pdf"
            locked = supplemental / "locked.pdf"
            standard.write_bytes(b"standard")
            translation.write_bytes(b"translation")
            locked.write_bytes(b"locked")

            args = MODULE.parse_args(
                [
                    "--source-root",
                    str(archive),
                    "--source-root",
                    str(supplemental),
                ]
            )
            self.assertEqual(args.source_roots, [archive, supplemental])

            index = MODULE.SourceIndex(args.source_roots)
            self.assertEqual(index.exact("standard.pdf"), standard.resolve())
            self.assertEqual(index.exact("translation.pdf"), translation.resolve())
            checks = [
                {
                    "id": "source.standard",
                    "status": "pass",
                    "details": {"source": index.label(standard)},
                },
                {
                    "id": "source.translation",
                    "status": "pass",
                    "details": {
                        "source": index.label(translation),
                        "verified": [{"path": index.label(locked)}],
                    },
                },
            ]
            hashes = MODULE.external_input_hashes(
                checks,
                args.source_roots,
                results_tab=None,
            )

        self.assertEqual(len(hashes), 3)
        self.assertTrue(any("archive/standard.pdf" in key for key in hashes))
        self.assertTrue(any("supplemental/translation.pdf" in key for key in hashes))
        self.assertTrue(any("supplemental/locked.pdf" in key for key in hashes))

    def test_one_invalid_source_root_stops_union_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            valid = Path(directory)
            missing = valid / "missing"
            outcomes = MODULE.run_source_dependent_checks(
                self.package,
                source_root=[valid, missing],
                results_tab=None,
            )

        source_outcomes = [
            item for item in outcomes if item["id"].startswith("source.")
        ]
        self.assertTrue(source_outcomes)
        self.assertTrue(all(item["status"] == "not_run" for item in source_outcomes))
        self.assertTrue(
            all(item["details"]["invalid_roots"] == ["missing"] for item in source_outcomes)
        )

    def test_malformed_package_returns_the_declared_check_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = MODULE.build_report(
                package_root=root,
                output=root / "report.json",
                source_root=None,
                results_tab=None,
                auto_results_tab=False,
            )

        catalog = MODULE.self_contained_check_specs()
        self.assertEqual(
            [item["id"] for item in report["layers"]["self_contained"]],
            [check_id for check_id, _ in catalog],
        )
        statuses = Counter(item["status"] for item in report["layers"]["self_contained"])
        self.assertEqual(statuses["fail"], 1)
        self.assertEqual(statuses["not_run"], len(catalog) - 1)

    def test_current_latex_tables_match_release(self):
        self.require_v3_release()
        outcomes = MODULE.check_results_tables(self.package, RESULTS_TAB)

        self.assertTrue(all(item["status"] == "pass" for item in outcomes), outcomes)

    def test_latex_count_mutation_is_detected_without_broken_baseline(self):
        file_standard = {
            "pollutant_limits_long.csv": "GB 2762",
            "pesticide_limits_long.csv": "GB 2763",
            "mycotoxin_limits_long.csv": "GB 2761",
            "vetdrug_limits_long.csv": "GB 31650",
            "additive_limits_long.csv": "GB 2760",
        }
        lines = []
        changed = False
        for filename, standard in file_standard.items():
            counts = Counter(row["version_year"] for row in self.package.rows(filename))
            for year, count in sorted(counts.items()):
                if standard == "GB 2760" and not changed:
                    count += 1
                    changed = True
                lines.append(f"Family & {standard} & {year} & {count} & path \\")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tab1ExtractionMethod.tex").write_text("\n".join(lines), encoding="utf-8")
            outcomes = MODULE.check_results_tables(self.package, root)

        extraction = next(
            item for item in outcomes if item["id"] == "external_tables.extraction_counts"
        )
        self.assertEqual(extraction["status"], "fail")
        self.assertTrue(extraction["details"]["mismatches"])

    def test_report_hashes_external_inputs_without_private_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            report = MODULE.build_report(
                package_root=PACKAGE_ROOT,
                output=output,
                source_root=None,
                results_tab=RESULTS_TAB,
                auto_results_tab=False,
            )

        encoded = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("/Users/", encoded)
        self.assertNotIn("/Volumes/", encoded)
        self.assertIn("source_manifest.csv", report["file_hashes"])
        self.assertNotIn(MODULE.REPORT_NAME, report["file_hashes"])
        self.assertEqual(len(report["external_input_hashes"]), 2)


if __name__ == "__main__":
    unittest.main()
