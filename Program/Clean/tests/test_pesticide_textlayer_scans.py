import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


PROGRAM = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "extract_pesticide_textlayer_scans",
    PROGRAM / "260716_extract_pesticide_textlayer_scans.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class PesticideTextLayerUnitTests(unittest.TestCase):
    def word(self, raw, x_min=100.0, x_max=200.0, y=10.0):
        return MODULE.Word(
            x_min=x_min,
            x_max=x_max,
            y_min=y,
            y_max=y + 10,
            raw=raw,
            text=MODULE.normalize_text(raw),
        )

    def test_documented_private_use_glyphs_and_fullwidth_g_are_normalized(self):
        self.assertEqual(
            MODULE.normalize_text("0\U001001b005\U001001baＧD"),
            "0.05-D",
        )

    def test_nested_english_parentheses_remain_inside_header_name(self):
        words = [self.word("4.7"), self.word("2甲4氯(钠)[MCPA(sodium)]", 210, 400)]

        header = MODULE.parse_expected_header(
            "2019",
            words,
            expected_section=7,
            source_page=1,
            serial=1,
            source_path=Path("fixture.pdf"),
        )

        self.assertIsNotNone(header)
        self.assertEqual(header.pesticide_zh, "2甲4氯(钠)")
        self.assertEqual(header.pesticide_en, "MCPA(sodium)")

    def test_missing_text_layer_glyph_is_recovered_from_english_key(self):
        words = [self.word("4.1丙炔草酮(oxadiargyl)")]

        header = MODULE.parse_expected_header(
            "2019",
            words,
            expected_section=1,
            source_page=1,
            serial=1,
            source_path=Path("fixture.pdf"),
        )

        self.assertEqual(header.pesticide_zh, "丙炔噁草酮")
        self.assertEqual(
            header.name_correction,
            "visible_glyph_missing_from_text_layer",
        )

    def test_limit_qualifiers_preserve_scope_and_temporary_status(self):
        self.assertEqual(
            MODULE.parse_qualifier("∗"),
            ("temporary_mrl_asterisk", True, ""),
        )
        self.assertEqual(
            MODULE.parse_qualifier("(以脂肪计)"),
            ("as_fat", False, ""),
        )
        self.assertEqual(
            MODULE.parse_qualifier("c"),
            (
                "source_marker_c_unresolved",
                False,
                "source_qualifier_unresolved_c",
            ),
        )

    def test_wrapped_food_detection_does_not_capture_a_new_parent_heading(self):
        self.assertTrue(
            MODULE.food_label_expects_continuation("叶菜类蔬菜(菠菜、普通白菜、")
        )
        self.assertFalse(MODULE.food_label_expects_continuation("油料和油脂"))

    def test_only_category_names_open_a_valued_parent_scope(self):
        for heading in (
            "蔬菜",
            "生乳",
            "哺乳动物肉类(海洋哺乳动物除外),以脂肪中的残留量计",
            "肝脏(牛、羊、猪)",
        ):
            self.assertEqual(MODULE.parent_heading(heading), heading)
        self.assertEqual(
            MODULE.parent_heading("哺乳动物内脏(猪肾、牛肾、羊肾除外)"), "哺乳动物内脏"
        )
        self.assertEqual(
            MODULE.parent_heading("水果(苹果、梨、桃、樱桃、油桃、李子、蓝莓、越橘、西瓜、甜瓜类水果、除外)"),
            "水果",
        )
        for food in (
            "豆类蔬菜(食荚豌豆、豌豆(鲜)、菜豆和菜用大豆除外)",
            "浆果和其他小型水果[醋栗(红、黑)、葡萄、草莓除外]",
            "叶菜类蔬菜(菠菜、普通白菜、叶芥菜、萝卜叶、",
            "柑",
            "棉籽",
        ):
            self.assertEqual(MODULE.parent_heading(food), "")

    def test_semantic_table_boundaries_allow_source_numbering_exceptions(self):
        self.assertEqual(
            MODULE.structural_transition("4.191.3 最大残留限量", 191),
            ("open", "semantic_maximum_limit_item_3"),
        )
        self.assertEqual(
            MODULE.structural_transition("4.191.4 检测方法", 191),
            ("close", "semantic_testing_method_item_4"),
        )
        self.assertEqual(
            MODULE.structural_transition("4.90.4 检测方法", 90),
            ("close", "semantic_testing_method_item_4"),
        )

    def test_source_hash_gate_rejects_an_unrecognised_copy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / str(MODULE.SOURCE_CONFIG["2019"]["filename"])
            source.write_bytes(b"not the frozen source")
            with self.assertRaisesRegex(
                MODULE.ExtractionValidationError,
                "source identity mismatch",
            ):
                MODULE.verify_source(source, "2019")

    def test_three_visual_rows_can_form_one_food_value_rule(self):
        rows = [
            [self.word("叶菜类蔬菜(", x_min=100, x_max=180, y=10)],
            [self.word("菠菜)", x_min=100, x_max=150, y=18)],
            [self.word("0.1*", x_min=400, x_max=430, y=26)],
        ]

        merged = MODULE.merge_wrapped_food_value_rows(rows, 350.0)

        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0]), 3)

    def test_running_header_after_value_can_be_removed(self):
        value_words = [
            self.word("0.1*", x_min=400, x_max=430, y=10),
            self.word("食品安全国家标准", x_min=440, x_max=540, y=10),
        ]

        salvaged = MODULE.salvage_margin_overlapped_value_words(value_words)

        self.assertIsNotNone(salvaged)
        self.assertEqual(MODULE.row_text(salvaged), "0.1*")


SOURCES_AVAILABLE = all(
    (
        MODULE.DEFAULT_SOURCE_DIR
        / str(MODULE.SOURCE_CONFIG[year]["filename"])
    ).is_file()
    for year in MODULE.GOVERNMENT_HOSTED_YEARS
)
OCR_INPUTS_AVAILABLE = (
    MODULE.DEFAULT_OCR_DIR / "completion_manifest.json"
).is_file() and (
    MODULE.DEFAULT_OCR_PARSED_DIR / "pesticide_ocr_accepted.csv"
).is_file()
ARCHIVE_EDITION_SOURCE_ROOT = Path(
    "/Volumes/LeoXu4TB/Database/15_食品安全标准数据库/01_RawData"
)
ARCHIVE_SOURCES_AVAILABLE = all(
    (
        ARCHIVE_EDITION_SOURCE_ROOT
        / MODULE.ARCHIVE_SOURCE_SUBDIR
        / str(MODULE.SOURCE_CONFIG[year]["filename"])
    ).is_file()
    for year in MODULE.ARCHIVE_TEXT_LAYER_YEARS
) and (
    MODULE.PROJECT_ROOT / "Data/Raw" / MODULE.TRANSLATION_2016_RELATIVE
).is_file()


@unittest.skipUnless(
    SOURCES_AVAILABLE and OCR_INPUTS_AVAILABLE,
    "frozen text-layer and OCR crosscheck inputs are unavailable",
)
class PesticideTextLayerSourceIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.output_dir = Path(cls.temp_dir.name)
        cls.report = MODULE.build(
            MODULE.DEFAULT_SOURCE_DIR,
            MODULE.DEFAULT_OCR_DIR,
            MODULE.DEFAULT_OCR_PARSED_DIR,
            cls.output_dir,
        )
        cls.limits = read_csv(cls.output_dir / "pesticide_textlayer_limits.csv")
        cls.roster = read_csv(
            cls.output_dir / "pesticide_textlayer_section_roster.csv"
        )
        cls.crosscheck = read_csv(
            cls.output_dir / "pesticide_textlayer_ocr_crosscheck.csv"
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_complete_rosters_and_frozen_row_counts(self):
        rows_by_year = {
            year: [row for row in self.limits if row["year"] == year]
            for year in MODULE.GOVERNMENT_HOSTED_YEARS
        }
        roster_by_year = {
            year: [row for row in self.roster if row["year"] == year]
            for year in MODULE.GOVERNMENT_HOSTED_YEARS
        }

        self.assertEqual(len(rows_by_year["2019"]), 7108)
        self.assertEqual(len(rows_by_year["2021"]), 10092)
        self.assertEqual(len(roster_by_year["2019"]), 467)
        self.assertEqual(len(roster_by_year["2021"]), 548)
        self.assertEqual(
            [int(row["section_number"]) for row in roster_by_year["2019"]],
            list(range(1, 468)),
        )
        self.assertEqual(
            [int(row["section_number"]) for row in roster_by_year["2021"]],
            list(range(1, 549)),
        )

    def test_page_annex_duplicate_and_parent_gates(self):
        for year, expected_bounds in {"2019": [21, 306], "2021": [23, 392]}.items():
            diagnostic = self.report["diagnostics"][year]
            self.assertEqual(diagnostic["row_page_bounds"], expected_bounds)
            self.assertEqual(diagnostic["appendix_leakage_rows"], 0)
            self.assertEqual(diagnostic["exact_full_rule_duplicates"], 0)
        self.assertTrue(all(row["parent_category"] for row in self.limits))

    def test_frozen_qualifier_counts_and_unresolved_source_marker(self):
        self.assertEqual(
            self.report["diagnostics"]["2019"]["qualifier_counts"],
            {
                "as_fat": 10,
                "as_presented": 3,
                "none": 5404,
                "temporary_mrl_asterisk": 1691,
            },
        )
        self.assertEqual(
            self.report["diagnostics"]["2021"]["qualifier_counts"],
            {
                "as_fat": 7,
                "as_presented": 3,
                "none": 7137,
                "source_marker_c_unresolved": 1,
                "temporary_mrl_asterisk": 2944,
            },
        )
        unresolved = [
            row
            for row in self.limits
            if row["limit_qualifier"] == "source_marker_c_unresolved"
        ]
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["year"], "2021")
        self.assertIn("source_qualifier_unresolved_c", unresolved[0]["review_status"])

    def test_scan_temporary_marks_follow_the_edition_scan(self):
        fixed = [
            row for row in self.limits
            if "scan_temporary_mark_correction" in row["review_status"]
        ]
        self.assertEqual(
            sorted(row["food"] for row in fixed),
            sorted(("稻谷", "糙米", "麦类", "旱粮类", "棉籽", "大豆")),
        )
        for row in fixed:
            self.assertEqual((row["year"], row["section_number"]), ("2019", "111"))
            self.assertEqual((row["is_temporary"], row["limit_qualifier"]), ("false", ""))
            self.assertTrue(row["value_raw"].endswith("∗"))

    def test_coordinate_scope_and_wrapped_food_are_preserved(self):
        centered_parent = next(
            row
            for row in self.limits
            if row["year"] == "2019"
            and row["section_number"] == "156"
            and row["food"] == "棉籽"
        )
        wrapped_food = next(
            row
            for row in self.limits
            if row["year"] == "2021"
            and row["section_number"] == "300"
            and "茎用莴苣叶" in row["food"]
        )

        self.assertEqual(centered_parent["parent_category"], "油料和油脂")
        # Rows the independent reading found under a long food label, and two
        # text-layer cases that place a food in the category column.
        expected_parents = {
            ("2019", "83", "棉籽"): "油料和油脂",
            ("2019", "136", "豌豆(鲜)"): "蔬菜",
            ("2019", "272", "醋栗(红、黑)"): "水果",
            ("2019", "363", "山药"): "蔬菜",
            ("2021", "21", "梨"): "水果",
            ("2021", "291", "茎用莴苣"): "蔬菜",
            ("2021", "298", "瓜类蔬菜(黄瓜、腌制用小黄瓜、西葫芦、笋瓜除外)"): "蔬菜",
            ("2021", "156", "柑"): "水果",
            ("2021", "284", "猪肾"): "哺乳动物内脏",
        }
        for (year, section, food), parent in expected_parents.items():
            row = next(
                row
                for row in self.limits
                if (row["year"], row["section_number"], row["food"])
                == (year, section, food)
            )
            self.assertEqual(row["parent_category"], parent, (year, section, food))
        self.assertEqual(
            wrapped_food["food"],
            "叶菜类蔬菜(菠菜、普通白菜、苋菜、茼蒿、叶用莴苣、油麦菜、"
            "茎用莴苣叶、芹菜、大白菜除外)",
        )
        self.assertIn("food_label_continuation_joined", wrapped_food["review_status"])

    def test_source_roles_hashes_and_2019_count_difference_are_explicit(self):
        for year in MODULE.GOVERNMENT_HOSTED_YEARS:
            config = MODULE.SOURCE_CONFIG[year]
            text_copy = self.report["sources"][year][
                "government_hosted_text_layer_extraction_copy"
            ]
            scan_copy = self.report["sources"][year][
                "original_scan_edition_identity_anchor_and_ocr_crosscheck_copy"
            ]
            self.assertEqual(text_copy["sha256"], config["sha256"])
            self.assertEqual(
                text_copy["copy_role"],
                "government_hosted_text_layer_extraction_copy",
            )
            self.assertEqual(
                scan_copy["copy_role"],
                "original_scan_edition_identity_anchor_and_ocr_crosscheck_copy",
            )
        reconciliation = self.report["visible_rule_reconciliation"]["2019"]
        self.assertEqual(reconciliation["visible_rules_minus_declared"], 1)
        self.assertEqual(
            reconciliation["plus_one_audit"]["status"],
            "unresolved_aggregate_difference_keep_all_visible_rows",
        )
        self.assertIn(
            "no inference about record-level correctness",
            reconciliation["interpretation_boundary"],
        )

    def test_ocr_crosscheck_differences_are_retained(self):
        self.assertEqual(
            self.report["ocr_crosscheck"]["status_counts"],
            {
                "conflict": 9,
                "consistent": 3701,
                "ocr_only": 3,
                "text_only": 13490,
            },
        )
        nonmatching = [
            row
            for row in self.crosscheck
            if row["status"] in {"conflict", "ocr_only"}
        ]
        self.assertEqual(len(nonmatching), 12)
        self.assertTrue(all(row["text_source_pages"] or row["ocr_source_pages"] for row in nonmatching))

    def test_outputs_are_portable_lf_and_deterministic(self):
        report_text = (
            self.output_dir / "pesticide_textlayer_extraction_report.json"
        ).read_text(encoding="utf-8")
        self.assertNotIn("/Users/", report_text)
        self.assertNotIn("/private/", report_text)

        artifact_names = (
            "pesticide_textlayer_limits.csv",
            "pesticide_textlayer_section_roster.csv",
            "pesticide_textlayer_ocr_crosscheck.csv",
            "pesticide_textlayer_extraction_report.json",
        )
        for name in artifact_names:
            self.assertNotIn(b"\r\n", (self.output_dir / name).read_bytes())

        with tempfile.TemporaryDirectory() as second_temp_dir:
            second_output = Path(second_temp_dir)
            MODULE.build(
                MODULE.DEFAULT_SOURCE_DIR,
                MODULE.DEFAULT_OCR_DIR,
                MODULE.DEFAULT_OCR_PARSED_DIR,
                second_output,
            )
            self.assertEqual(
                {name: sha256(self.output_dir / name) for name in artifact_names},
                {name: sha256(second_output / name) for name in artifact_names},
            )

    def test_report_is_the_serialized_build_result(self):
        report_file = json.loads(
            (self.output_dir / "pesticide_textlayer_extraction_report.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report_file, self.report)
        self.assertTrue(report_file["validation_passed"])


@unittest.skipUnless(
    SOURCES_AVAILABLE and OCR_INPUTS_AVAILABLE and ARCHIVE_SOURCES_AVAILABLE,
    "six frozen edition sources or OCR crosscheck inputs are unavailable",
)
class PesticideTextLayerSixEditionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.output_dir = Path(cls.temp_dir.name)
        cls.report = MODULE.build(
            MODULE.DEFAULT_SOURCE_DIR,
            MODULE.DEFAULT_OCR_DIR,
            MODULE.DEFAULT_OCR_PARSED_DIR,
            cls.output_dir,
            ARCHIVE_EDITION_SOURCE_ROOT,
        )
        cls.limits = read_csv(cls.output_dir / "pesticide_textlayer_limits.csv")
        cls.roster = read_csv(
            cls.output_dir / "pesticide_textlayer_section_roster.csv"
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_all_six_visible_rule_counts_and_rosters_are_frozen(self):
        expected_rows = {
            "2012": 2293,
            "2014": 3650,
            "2016": 4132,
            "2019": 7108,
            "2021": 10092,
            "2026": 10749,
        }
        expected_sections = {
            year: int(config["sections"])
            for year, config in MODULE.SOURCE_CONFIG.items()
        }
        self.assertEqual(len(self.limits), sum(expected_rows.values()))
        for year in MODULE.SOURCE_CONFIG:
            rows = [row for row in self.limits if row["year"] == year]
            headers = [row for row in self.roster if row["year"] == year]
            self.assertEqual(len(rows), expected_rows[year])
            self.assertEqual(len(headers), expected_sections[year])
            self.assertEqual(
                [int(row["section_number"]) for row in headers],
                list(range(1, expected_sections[year] + 1)),
            )
            self.assertTrue(all(row["parent_category"] for row in rows))
            self.assertLessEqual(
                {row["parent_category"] for row in rows}, MODULE.PARENT_HEADINGS
            )

    def test_declared_visible_deltas_and_qualifiers_are_explicit(self):
        expected_deltas = {
            "2012": 0,
            "2014": 0,
            "2016": -8,
            "2019": 1,
            "2021": 0,
            "2026": 0,
        }
        expected_qualifiers = {
            "2012": {
                "as_fat": 9,
                "as_presented": 2,
                "none": 1991,
                "temporary_mrl_asterisk": 291,
            },
            "2014": {
                "as_fat": 10,
                "as_presented": 3,
                "none": 3114,
                "temporary_mrl_asterisk": 523,
            },
            "2016": {
                "as_fat": 10,
                "as_presented": 3,
                "none": 3497,
                "temporary_mrl_asterisk": 622,
            },
            "2026": {
                "as_fat": 7,
                "as_presented": 3,
                "none": 8815,
                "temporary_mrl_asterisk": 1924,
            },
        }
        reconciliation = self.report["visible_rule_reconciliation"]
        self.assertEqual(
            {
                year: values["visible_rules_minus_declared"]
                for year, values in reconciliation.items()
            },
            expected_deltas,
        )
        for year, counts in expected_qualifiers.items():
            self.assertEqual(
                self.report["diagnostics"][year]["qualifier_counts"], counts
            )

    def test_2012_margin_overlap_rule_is_preserved(self):
        row = next(
            row
            for row in self.limits
            if row["year"] == "2012"
            and row["section_number"] == "178"
            and row["source_page"] == "94"
            and row["food"] == "糙米"
        )
        self.assertEqual(row["parent_category"], "谷物")
        self.assertEqual(row["limit_value"], "0.1")
        self.assertEqual(row["limit_qualifier"], "temporary_mrl_asterisk")
        self.assertIn("margin_header_overlap_removed", row["review_status"])

    def test_2016_is_a_visible_rule_reconciliation(self):
        audit = self.report["visible_rule_reconciliation"]["2016"][
            "independent_translation_check"
        ]
        self.assertEqual(audit["audit_type"], "independent_visible_rule_reconciliation")
        self.assertEqual(audit["chinese_source_visible_rules"], 4132)
        self.assertEqual(audit["english_translation_visible_rules"], 4132)
        self.assertEqual(audit["sections_with_equal_visible_rule_counts"], 417)
        self.assertEqual(audit["standard_declared_mrl_items"], 4140)
        self.assertEqual(audit["visible_rules_minus_declared"], -8)
        self.assertIn("unresolved", audit["status"])
        serialized = json.dumps(audit, ensure_ascii=False).lower()
        self.assertNotIn("recall", serialized)
        self.assertNotIn("precision", serialized)

    def test_source_roles_follow_the_two_provenance_models(self):
        for year in MODULE.ARCHIVE_TEXT_LAYER_YEARS:
            source = self.report["sources"][year][
                "archive_text_layer_edition_source_copy"
            ]
            self.assertEqual(
                source["copy_role"], "archive_text_layer_edition_source_copy"
            )
            self.assertIn("edition source", source["source_and_extraction_role"])
        for year in MODULE.GOVERNMENT_HOSTED_YEARS:
            source = self.report["sources"][year]
            self.assertIn("government_hosted_text_layer_extraction_copy", source)
            self.assertIn(
                "original_scan_edition_identity_anchor_and_ocr_crosscheck_copy",
                source,
            )

    def test_six_edition_outputs_are_lf_portable_and_deterministic(self):
        artifact_names = (
            "pesticide_textlayer_limits.csv",
            "pesticide_textlayer_section_roster.csv",
            "pesticide_textlayer_ocr_crosscheck.csv",
            "pesticide_textlayer_extraction_report.json",
        )
        report_text = (
            self.output_dir / "pesticide_textlayer_extraction_report.json"
        ).read_text(encoding="utf-8")
        self.assertNotIn("/Users/", report_text)
        self.assertNotIn("/Volumes/", report_text)
        self.assertNotIn("/private/", report_text)
        for name in artifact_names:
            self.assertNotIn(b"\r\n", (self.output_dir / name).read_bytes())

        with tempfile.TemporaryDirectory() as second_temp_dir:
            second_output = Path(second_temp_dir)
            MODULE.build(
                MODULE.DEFAULT_SOURCE_DIR,
                MODULE.DEFAULT_OCR_DIR,
                MODULE.DEFAULT_OCR_PARSED_DIR,
                second_output,
                ARCHIVE_EDITION_SOURCE_ROOT,
            )
            self.assertEqual(
                {name: sha256(self.output_dir / name) for name in artifact_names},
                {name: sha256(second_output / name) for name in artifact_names},
            )


if __name__ == "__main__":
    unittest.main()
