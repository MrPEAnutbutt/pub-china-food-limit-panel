import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


PROGRAM = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PROGRAM.parents[1]
sys.path.insert(0, str(PROGRAM))
SPEC = importlib.util.spec_from_file_location(
    "parse_pesticide_ocr", PROGRAM / "260716_parse_pesticide_ocr.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


class _FakeAdjudications:
    def __init__(self, count):
        self.items = {index: {} for index in range(count)}


class PesticideOCRParserUnitTests(unittest.TestCase):
    def test_portable_report_path_hides_external_directories(self):
        internal = MODULE.PROJECT_ROOT / "Data/Interim/pesticide_text"
        self.assertEqual(
            MODULE.portable_report_path(internal, "text_inputs"),
            "Data/Interim/pesticide_text",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            external = Path(temp_dir) / "private_inputs" / "roster.csv"
            label = MODULE.portable_report_path(external, "identity resolver")
            self.assertEqual(label, "external/identity_resolver/roster.csv")
            self.assertNotIn(temp_dir, label)

    def test_manifest_is_the_first_build_gate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaisesRegex(ValueError, "completion manifest"):
                MODULE.build(root / "ocr", root / "text", root / "output")

    def test_strict_table_signals_do_not_accept_footer_numbers(self):
        self.assertEqual(
            MODULE.structural_signal("4.520.4 最大残留限量", 548), (520, 4)
        )
        self.assertEqual(MODULE.structural_signal("4 520 5 检测方法", 548), (520, 5))
        self.assertIsNone(MODULE.structural_signal("45", 548))
        self.assertEqual(MODULE.table_number("表 520", 548), 520)

    def test_parent_column_uses_contiguous_cluster_across_x_threshold(self):
        words = [
            MODULE.Word(258, 20, 100, 20, "干", 80, 0),
            MODULE.Word(287, 20, 100, 20, "制", 90, 0),
            MODULE.Word(313, 20, 100, 20, "水", 90, 0),
            MODULE.Word(337, 20, 100, 20, "果", 90, 0),
            MODULE.Word(1250, 40, 100, 20, "0.01", 90, 0),
        ]
        parent, child = MODULE.split_category_columns(words, 300, 900, 1600)
        self.assertEqual("".join(word.text for word in parent), "干制水果")
        self.assertEqual(child, [])

    def test_adjudication_count_gates_reject_missing_rows(self):
        identities = {
            ("2019", index): {}
            for index in range(MODULE.EXPECTED_IDENTITY_ADJUDICATIONS)
        }
        with self.assertRaisesRegex(
            MODULE.ParserValidationError, "identity adjudication"
        ):
            MODULE.validate_adjudication_input_counts(
                dict(list(identities.items())[:-1]),
                _FakeAdjudications(MODULE.EXPECTED_SOURCE_IMAGE_ADJUDICATIONS),
            )
        with self.assertRaisesRegex(
            MODULE.ParserValidationError, "source-image adjudication"
        ):
            MODULE.validate_adjudication_input_counts(
                identities,
                _FakeAdjudications(MODULE.EXPECTED_SOURCE_IMAGE_ADJUDICATIONS - 1),
            )

    def test_bad_parent_in_source_adjudication_is_rejected(self):
        food_resolver = MODULE.FoodResolver(MODULE.DEFAULT_TEXT_DIR)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    [
                        "adjudication_id",
                        "year",
                        "source_page",
                        "section",
                        "pesticide_zh",
                        "raw_parent",
                        "raw_food",
                        "raw_value",
                        "corrected_parent",
                        "corrected_food",
                        "corrected_value",
                        "source_conclusion",
                    ]
                )
                writer.writerow(
                    [
                        "BAD",
                        "2019",
                        "27",
                        "15",
                        "百草枯",
                        "蔬菜",
                        "豆类蔬菜",
                        "1",
                        "错误父类",
                        "豆类蔬菜",
                        "0.05",
                        "fixture",
                    ]
                )
            with self.assertRaisesRegex(
                MODULE.ParserValidationError, "corrected parent"
            ):
                MODULE.RowAdjudications(path, food_resolver)

    def test_out_of_range_identity_adjudication_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad_identity.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    ["year", "section", "pesticide_zh", "source_page", "evidence"]
                )
                writer.writerow(
                    ["2019", "999", "错误节号", "1", "source_transcription"]
                )
            with self.assertRaisesRegex(
                MODULE.ParserValidationError, "section out of range"
            ):
                MODULE.load_identity_adjudications(path)


@unittest.skipUnless(
    (MODULE.DEFAULT_OCR_DIR / "completion_manifest.json").exists(),
    "frozen OCR completion manifest is unavailable",
)
class PesticideOCRParserIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.output_dir = Path(cls.temp_dir.name)
        cls.report = MODULE.build(
            MODULE.DEFAULT_OCR_DIR,
            MODULE.DEFAULT_TEXT_DIR,
            cls.output_dir,
        )
        cls.accepted = read_csv(cls.output_dir / "pesticide_ocr_accepted.csv")
        cls.quarantine = read_csv(cls.output_dir / "pesticide_ocr_quarantine.csv")
        cls.roster = read_csv(cls.output_dir / "pesticide_ocr_section_roster.csv")
        cls.evidence = read_csv(cls.output_dir / "pesticide_ocr_roster_evidence.csv")
        cls.report_file = json.loads(
            (cls.output_dir / "pesticide_ocr_report.json").read_text(encoding="utf-8")
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_frozen_formal_counts(self):
        self.assertEqual(
            self.report["totals"],
            {
                "accepted": 3713,
                "quarantine": 8551,
                "candidates": 12264,
                "section_roster": 1015,
                "roster_evidence": 2167,
            },
        )
        self.assertFalse(
            self.report_file["artifact_scope"]["complete_edition_representation"]
        )
        self.assertEqual(
            self.report_file["artifact_scope"]["layer"],
            "conservative_ocr_candidate_layer",
        )

    def test_complete_resolved_year_section_rosters(self):
        by_year = {
            year: [row for row in self.roster if row["year"] == year]
            for year in MODULE.REQUIRED_YEARS
        }
        self.assertEqual(len(by_year["2019"]), 467)
        self.assertEqual(len(by_year["2021"]), 548)
        self.assertTrue(all(row["status"] == "resolved" for row in self.roster))

    def test_manual_identity_evidence_is_explicit_and_hashed(self):
        manual = [
            row for row in self.evidence if row["method"] == "source_transcription"
        ]
        self.assertEqual(len(manual), MODULE.EXPECTED_IDENTITY_ADJUDICATIONS)
        self.assertTrue(all(row["source"] == "source_transcription" for row in manual))
        identity = self.report_file["identity_adjudications"]
        self.assertEqual(identity["rows"], 45)
        self.assertEqual(len(identity["sha256"]), 64)
        self.assertFalse(self.report_file["resolver"]["external_english_roster_used"])

    def test_source_adjudications_each_hit_once_and_are_accepted(self):
        items = self.report_file["source_image_adjudications"]["rows"]
        self.assertEqual(len(items), MODULE.EXPECTED_SOURCE_IMAGE_ADJUDICATIONS)
        self.assertTrue(all(item["hits"] == 1 for item in items))
        self.assertEqual(
            len(self.report_file["source_image_adjudications"]["sha256"]), 64
        )
        accepted_ids = {
            row["adjudication_id"] for row in self.accepted if row["adjudication_id"]
        }
        self.assertEqual(accepted_ids, {f"A{index:03d}" for index in range(1, 12)})

    def test_exact_food_composite_and_body_bounds(self):
        self.assertTrue(all(row["food_match"] == "exact" for row in self.accepted))
        self.assertTrue(
            any(
                row["review_status"] == "review_name_conf_lt30" for row in self.accepted
            )
        )
        combined = self.accepted + self.quarantine
        self.assertFalse(
            any(
                row["year"] == "2021" and int(row["source_page"]) >= 392
                for row in combined
            )
        )

    def test_page_390_is_unique_and_parent_category_is_in_the_key(self):
        rows = [
            row
            for row in self.accepted
            if row["year"] == "2021" and row["source_page"] == "390"
        ]
        keys = {
            (
                row["year"],
                row["section"],
                row["pesticide"],
                row["parent_category"],
                row["food"],
                row["limit_value"],
            )
            for row in rows
        }
        self.assertEqual(len(rows), 7)
        self.assertEqual(len(keys), 7)

    def test_tebuconazole_dried_chili_parent_correction(self):
        rows = [
            row
            for row in self.accepted
            if row["year"] == "2019"
            and row["section"] == "373"
            and row["pesticide"] == "戊唑醇"
            and row["food"] in {"辣椒", "干辣椒"}
        ]
        observed = {
            (row["parent_category"], row["food"], row["limit_value"]) for row in rows
        }
        self.assertEqual(
            observed,
            {("蔬菜", "辣椒", "2"), ("调味料", "干辣椒", "10")},
        )
        corrected = next(row for row in rows if row["food"] == "干辣椒")
        self.assertEqual(corrected["parent_category_ocr_raw"], "饮料类")
        self.assertEqual(corrected["food_ocr_raw"], "辣椒")

    def test_layout_parent_recovers_p55_vegetable_block(self):
        targets = {"结球甘蓝", "花椰菜", "普通白菜", "番茄", "萝卜", "甘薯"}
        rows = [
            row
            for row in self.accepted + self.quarantine
            if row["year"] == "2019"
            and row["source_page"] == "55"
            and row["section"] == "57"
            and row["food"] in targets
        ]
        self.assertEqual({row["food"] for row in rows}, targets)
        self.assertTrue(all(row["parent_category"] == "蔬菜" for row in rows))
        self.assertTrue(all(row["parent_category_ocr_raw"] == "菠菜" for row in rows))
        self.assertTrue(all(row["parent_method"] == "layout_fuzzy" for row in rows))

    def test_unresolved_layout_parent_is_empty_and_reviewed(self):
        rows = [row for row in self.accepted if row["parent_match"] == "unresolved"]
        self.assertTrue(rows)
        self.assertTrue(all(not row["parent_category"] for row in rows))
        self.assertTrue(
            all("review_parent_unresolved" in row["review_status"] for row in rows)
        )


if __name__ == "__main__":
    unittest.main()
