import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "261026_pesticide_category_corrections.py"
SPEC = importlib.util.spec_from_file_location("pesticide_category_corrections", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def rule(record_id, category, value="0.1", review="text_layer_auto_extracted"):
    row = {"record_id": record_id, "version_year": "2019", "section_number": "4.1",
           "source_page": "10", "source_y": "100.0", "pesticide_zh": "甲", "food_zh": "梨",
           "parent_category_zh": category, "parent_category_raw": category,
           "parent_assignment_method": "inherited_from_left_column_scope",
           "limit_value": value, "limit_qualifier": "", "is_temporary": "false",
           "review_status": review}
    return {tuple(row[c] for c in MODULE.KEY): row}


class CategoryCorrectionsTest(unittest.TestCase):
    def test_a_category_change_is_listed(self):
        changed = MODULE.corrections(rule("P1", "仁果类水果(苹果除外)"), rule("P2", "水果"))
        self.assertEqual([(r["parent_category_previous"], r["parent_category_current"])
                          for r in changed], [("仁果类水果(苹果除外)", "水果")])

    def test_any_other_change_fails(self):
        with self.assertRaises(ValueError):
            MODULE.corrections(rule("P1", "水果"), rule("P2", "水果", value="0.2"))

    def test_an_asterisk_change_needs_the_scan_correction_flag(self):
        previous = rule("P1", "水果")
        current = rule("P2", "水果")
        next(iter(current.values()))["is_temporary"] = "true"
        with self.assertRaises(ValueError):
            MODULE.corrections(previous, current)


if __name__ == "__main__":
    unittest.main()
