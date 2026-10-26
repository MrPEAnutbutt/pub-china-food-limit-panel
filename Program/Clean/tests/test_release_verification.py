"""Row-level verification status added in revision A6."""

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


CLEAN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLEAN_DIR))
SCRIPT = CLEAN_DIR / "260714_build_release.py"
SPEC = importlib.util.spec_from_file_location("build_release_verification", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

READING_FIELDS = ("blind_id", "edition", "record_id", "section_number", "parent_category_zh",
                  "food_zh", "released_limit_value", "released_is_temporary", "outcome", "verdict")


def pesticide(record_id, food, category="谷物", temporary="false", year="2019"):
    return {"record_id": record_id, "version_year": year, "section_number": "111",
            "parent_category_zh": category, "food_zh": food, "limit_value": "1",
            "is_temporary": temporary, "source_page": "94"}


class VerificationStatusTest(unittest.TestCase):
    def test_a_source_reading_settles_an_ocr_conflict(self):
        rows = [{"record_id": "A"}, {"record_id": "B"}, {"record_id": "C"}]
        MODULE.add_verification_columns(rows, {
            "A": [("ocr_crosscheck", "disagree"), ("independent_audit_reading", "agree")],
            "B": [("ocr_crosscheck", "disagree")],
        })
        self.assertEqual([(row["verification_status"], row["verification_basis"]) for row in rows], [
            ("confirmed_agreement", "ocr_crosscheck;independent_audit_reading"),
            ("unresolved_disagreement", "ocr_crosscheck"),
            ("no_cross_source_comparison", "none"),
        ])

    def test_each_ocr_group_links_to_exactly_one_row(self):
        rows = [pesticide("A", "稻谷"), pesticide("B", "糙米")]
        groups = [
            {"year": "2019", "section_number": "111", "parent_category": "谷物", "food": "稻谷",
             "status": "consistent", "key_level": "strict_scope", "text_row_count": "1",
             "text_source_pages": "94"},
            {"year": "2019", "section_number": "111", "parent_category": "", "food": "糙米",
             "status": "text_only", "key_level": "unique_section_food", "text_row_count": "1",
             "text_source_pages": "94"},
        ]
        self.assertEqual(MODULE.pesticide_ocr_evidence(groups, rows),
                         {"A": [("ocr_crosscheck", "agree")]})
        with self.assertRaises(ValueError):
            MODULE.pesticide_ocr_evidence(groups[:1], rows)


class AuditEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.original = MODULE.AUDIT_INTERIM
        MODULE.AUDIT_INTERIM = self.directory.name

    def tearDown(self):
        MODULE.AUDIT_INTERIM = self.original
        self.directory.cleanup()

    def write_readings(self, readings):
        for position, round_dir in enumerate(MODULE.PESTICIDE_AUDIT_ROUNDS):
            folder = Path(self.directory.name) / round_dir / "comparison"
            folder.mkdir(parents=True)
            with (folder / "pesticide_audit_comparison.csv").open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, READING_FIELDS)
                writer.writeheader()
                writer.writerows(readings if position == 0 else [])

    @staticmethod
    def reading(blind_id, food, outcome, verdict="", category="谷物", temporary="false"):
        return {"blind_id": blind_id, "edition": "2019", "record_id": "old", "section_number": "111",
                "parent_category_zh": category, "food_zh": food, "released_limit_value": "1",
                "released_is_temporary": temporary, "outcome": outcome, "verdict": verdict}

    def test_release_errors_count_as_settled_only_once_fixed(self):
        self.write_readings([
            self.reading("R1", "稻谷", "agree"),
            self.reading("R2", "麦类", "not_found", "extraction_error", category="麦类"),
            self.reading("R3", "大豆", "asterisk_differs", "text_layer_error", temporary="true"),
            self.reading("R4", "棉籽", "asterisk_differs", "text_layer_error", temporary="true"),
        ])
        rows = [pesticide("A", "稻谷"), pesticide("B", "麦类"), pesticide("C", "大豆"),
                pesticide("D", "棉籽", temporary="true")]
        evidence = MODULE.pesticide_audit_evidence(rows)
        self.assertEqual({key: value[0][1] for key, value in evidence.items()},
                         {"A": "agree", "B": "agree", "C": "agree", "D": "disagree"})

    def test_a_reading_of_a_row_that_later_changed_fails(self):
        self.write_readings([self.reading("R1", "稻谷", "agree", temporary="true")])
        with self.assertRaises(ValueError):
            MODULE.pesticide_audit_evidence([pesticide("A", "稻谷")])

    def test_blind_reentry_must_cover_the_current_seeds(self):
        seed = Path(self.directory.name) / "seed.csv"
        seed.write_text("drug\n", encoding="utf-8")
        report = Path(self.directory.name) / MODULE.BLIND_REENTRY_REPORT
        report.parent.mkdir(parents=True)
        digest = hashlib.sha256(seed.read_bytes()).hexdigest()
        report.write_text(json.dumps({
            "status": "pass", "provenance_gap": {"status": "closed"},
            "inputs": {"construction_seeds": {"VET2022": {"sha256": digest}}},
        }), encoding="utf-8")
        MODULE.check_blind_reentry({"VET2022": seed})
        seed.write_text("drug\nchanged\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            MODULE.check_blind_reentry({"VET2022": seed})


if __name__ == "__main__":
    unittest.main()
