import csv
import importlib.util
import re
import sys
import unittest
from collections import Counter
from pathlib import Path


CLEAN_DIR = Path(__file__).resolve().parents[1]
SCRIPT = CLEAN_DIR / "260714_build_release.py"
SPEC = importlib.util.spec_from_file_location("build_release_state_codes", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.path.insert(0, str(CLEAN_DIR))
SPEC.loader.exec_module(MODULE)
RELEASE = CLEAN_DIR.parents[1] / "Data" / "Final" / "china_food_limit_panel_v1"
CJK = re.compile(r"[\u3400-\u9fff]")


def read_csv(filename):
    with (RELEASE / filename).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class StableReleaseStateCodeTests(unittest.TestCase):
    def test_unknown_derived_label_stops_the_build(self):
        with self.assertRaisesRegex(ValueError, "unknown trend label"):
            MODULE.coded("未登记状态", MODULE.TREND_CODES, "trend")

    def test_machine_state_fields_have_no_chinese_display_labels(self):
        fields_by_file = {
            "pollutant_category_panel.csv": ("coverage_status", "trend"),
            "pollutant_member_panel.csv": ("trend",),
            "pesticide_limits_long.csv": (
                "limit_qualifier",
                "is_temporary",
                "parent_assignment_method",
                "table_open_method",
                "review_status",
                "source_copy_role",
                "conflict",
            ),
            "pesticide_panel.csv": (
                "trend",
                *(f"status_{year}" for year in MODULE.PESTICIDE_YEARS),
            ),
            "pesticide_ocr_crosscheck.csv": ("status", "key_level"),
            "mycotoxin_panel.csv": ("trend",),
            "mycotoxin_member_panel.csv": ("trend",),
            "vetdrug_panel.csv": ("trend",),
            "vetdrug_member_panel.csv": ("trend",),
            "additive_panel.csv": ("trend",),
        }
        violations = []
        for filename, fields in fields_by_file.items():
            for row_number, row in enumerate(read_csv(filename), start=2):
                for field in fields:
                    if CJK.search(row[field]):
                        violations.append((filename, row_number, field, row[field]))

        self.assertEqual(violations, [])

    def test_current_review_and_ocr_status_distributions_are_explicit(self):
        long_rows = read_csv("pesticide_limits_long.csv")
        panel_rows = read_csv("pesticide_panel.csv")
        crosscheck_rows = read_csv("pesticide_ocr_crosscheck.csv")

        self.assertEqual(
            Counter(row["review_status"] for row in long_rows),
            Counter(
                {
                    "text_layer_auto_extracted": 36122,
                    "text_layer_auto_extracted;source_structure_exception": 1652,
                    "text_layer_auto_extracted;source_glyph_correction": 234,
                    "text_layer_auto_extracted;food_label_continuation_joined": 8,
                    "text_layer_auto_extracted;food_value_multiline_joined": 6,
                    "text_layer_auto_extracted;margin_header_overlap_removed": 1,
                    "text_layer_auto_extracted;source_qualifier_unresolved_c": 1,
                }
            ),
        )
        self.assertEqual(
            Counter(row["status"] for row in crosscheck_rows),
            Counter(
                {
                    "text_only": 13490,
                    "consistent": 3701,
                    "conflict": 9,
                    "ocr_only": 3,
                }
            ),
        )
        self.assertEqual(
            Counter(row["trend"] for row in panel_rows)[
                "incomparable_unresolved_review_or_source_qualifier"
            ],
            1,
        )


if __name__ == "__main__":
    unittest.main()
