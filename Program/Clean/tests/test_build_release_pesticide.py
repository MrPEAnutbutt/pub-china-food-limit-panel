import importlib.util
import json
import sys
import unittest
from pathlib import Path


CLEAN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLEAN_DIR))
SCRIPT = CLEAN_DIR / "260714_build_release.py"
SPEC = importlib.util.spec_from_file_location("build_release_pesticide", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


SOURCE_IDS = {
    year: {
        "edition_source_id": f"edition-{year}",
        "extraction_source_id": f"extraction-{year}",
    }
    for year in MODULE.PESTICIDE_YEARS
}


def extracted_row(year="2021", value="1", food="苹果", qualifier=""):
    return {
        "edition": f"GB 2763-{year}",
        "year": year,
        "section_number": "10",
        "pesticide_zh": "测试农药",
        "pesticide_en": "test pesticide",
        "pesticide_zh_raw": "测试农药",
        "pesticide_en_raw": "test pesticide",
        "parent_category": "水果",
        "parent_category_raw": "水果",
        "food": food,
        "food_raw": food,
        "limit_value": value,
        "unit": "mg/kg",
        "limit_qualifier": qualifier,
        "is_temporary": "false",
        "value_raw": value,
        "source_page": "20",
        "source_y": "100.5",
        "food_x": "50",
        "parent_assignment_method": "same_page",
        "table_open_method": "section_header",
        "source_copy_role": "edition_source",
        "review_status": "text_layer_auto_extracted",
    }


class BuildReleasePesticideTests(unittest.TestCase):
    def test_long_rows_receive_stable_ids_and_source_relations(self):
        first, conflicts = MODULE.prepare_pesticide_limits(
            [extracted_row()], SOURCE_IDS
        )
        second, _ = MODULE.prepare_pesticide_limits(
            [extracted_row()], SOURCE_IDS
        )

        self.assertEqual(first, second)
        self.assertEqual(conflicts, 0)
        row = first[0]
        self.assertRegex(row["record_id"], r"^PES[0-9A-F]{16}$")
        self.assertRegex(row["pesticide_key"], r"^PST-[0-9a-f]{16}$")
        self.assertRegex(row["food_key"], r"^FOD-[0-9a-f]{16}$")
        self.assertEqual(row["edition_source_id"], "edition-2021")
        self.assertEqual(row["extraction_source_id"], "extraction-2021")

    def test_distinct_scope_rules_are_preserved(self):
        rows, conflicts = MODULE.prepare_pesticide_limits(
            [
                extracted_row(value="1", food="苹果"),
                extracted_row(value="0.5", food="苹果(仅限鲜果)", qualifier="only"),
            ],
            SOURCE_IDS,
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(conflicts, 2)
        self.assertEqual(len({row["food_key"] for row in rows}), 1)
        panel = MODULE.build_pesticide_panel_v2(rows)
        self.assertEqual(len(panel), 1)
        self.assertEqual(panel[0]["status_2021"], "multiple_rules_distinct_values")
        self.assertEqual(panel[0]["trend"], "incomparable_multiple_rules")

    def test_duplicate_semantic_rules_fail(self):
        with self.assertRaisesRegex(ValueError, "duplicate semantic rule"):
            MODULE.prepare_pesticide_limits(
                [extracted_row(), extracted_row()], SOURCE_IDS
            )

    def test_reconciliation_rows_require_all_six_editions(self):
        with self.assertRaisesRegex(ValueError, "does not cover all release years"):
            MODULE.pesticide_reconciliation_rows(
                {"visible_rule_reconciliation": {"2021": {}}}
            )

    def test_reconciliation_preserves_aggregate_differences(self):
        report = {"visible_rule_reconciliation": {}}
        for year in MODULE.PESTICIDE_YEARS:
            report["visible_rule_reconciliation"][year] = {
                "standard_declared_mrl_items": 10,
                "coordinate_extracted_visible_rules": 10,
                "visible_rules_minus_declared": 0,
                "declared_section_roster": 2,
                "extracted_section_headers": 2,
                "section_roster_complete": True,
                "qualifier_counts": {"temporary": 1},
                "status": "exact_aggregate_match",
                "interpretation_boundary": "aggregate check only",
            }
        report["visible_rule_reconciliation"]["2016"][
            "visible_rules_minus_declared"
        ] = -8

        rows = MODULE.pesticide_reconciliation_rows(report)

        self.assertEqual(len(rows), 6)
        row_2016 = next(row for row in rows if row["version_year"] == "2016")
        self.assertEqual(row_2016["visible_rules_minus_declared"], -8)
        self.assertEqual(json.loads(row_2016["qualifier_counts"]), {"temporary": 1})

    def test_panel_header_covers_lineage_fields(self):
        columns = MODULE.pesticide_panel_output_columns()

        self.assertEqual(len(columns), len(set(columns)))
        for year in MODULE.PESTICIDE_YEARS:
            self.assertIn(f"rules_{year}", columns)
            self.assertIn(f"edition_source_ids_{year}", columns)
            self.assertIn(f"extraction_source_ids_{year}", columns)


if __name__ == "__main__":
    unittest.main()
