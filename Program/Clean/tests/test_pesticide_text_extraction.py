import csv
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest


PROGRAM = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "extract_pesticide_text", PROGRAM / "260716_extract_pesticide_text.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PesticideTextHeaderTests(unittest.TestCase):
    def parse(self, text, section, *, apply_2026_fixes=False):
        return MODULE.parse_expected_header(
            text,
            section,
            source_page=1,
            serial=1,
            apply_2026_fixes=apply_2026_fixes,
        )

    def test_digit_led_legacy_header_uses_the_pesticide_name(self):
        header = self.parse(
            "4.1 2,4-滴和 2,4-滴钠盐（2,4-D 和 2,4-D Na）",
            1,
        )

        self.assertIsNotNone(header)
        self.assertEqual(header.pesticide_zh, "2,4-滴和2,4-滴钠盐")

    def test_digit_led_bbox_header_does_not_extend_the_section_number(self):
        header = self.parse(
            "4.12,4G滴丁酸和2,4G滴丁酸钠盐(2,4GDBand2,4GDdichlorophenoxybutyricacidsalt)",
            1,
        )

        self.assertIsNotNone(header)
        self.assertEqual(header.section_number, 1)
        self.assertEqual(header.pesticide_zh, "2,4-滴丁酸和2,4-滴丁酸钠盐")

    def test_chinese_qualifier_is_kept_before_the_english_name(self):
        header = self.parse("4.72甲4氯(钠)[MCPA(sodium)]", 7)

        self.assertIsNotNone(header)
        self.assertEqual(header.pesticide_zh, "2甲4氯(钠)")
        self.assertEqual(header.pesticide_en, "MCPA(sodium")

    def test_square_bracket_header_is_recognised(self):
        header = self.parse(
            "4.423双胍三辛烷基苯磺酸盐[iminoctadinetris(albesilate)]",
            423,
        )

        self.assertIsNotNone(header)
        self.assertEqual(header.pesticide_zh, "双胍三辛烷基苯磺酸盐")

    def test_internal_s_hyphen_is_normalised(self):
        header = self.parse(
            "4.362氰戊菊酯和SG氰戊菊酯(fenvalerateandesfenvalerate)",
            362,
        )

        self.assertIsNotNone(header)
        self.assertEqual(header.pesticide_zh, "氰戊菊酯和S-氰戊菊酯")

    def test_rendered_glyph_correction_is_guarded_by_english_name(self):
        header = self.parse(
            "4.136嗪草酮(oxaziclomefone)",
            136,
            apply_2026_fixes=True,
        )

        self.assertIsNotNone(header)
        self.assertEqual(header.pesticide_zh, "噁嗪草酮")
        with self.assertRaisesRegex(RuntimeError, "English name changed"):
            self.parse(
                "4.136嗪草酮(metribuzin)",
                136,
                apply_2026_fixes=True,
            )

    def test_2026_glyph_corrections_do_not_apply_to_legacy_editions(self):
        header = self.parse("4.64多菌灵(carbendazim)", 64)

        self.assertIsNotNone(header)
        self.assertEqual(header.pesticide_zh, "多菌灵")

    def test_stale_table_of_contents_header_is_rejected(self):
        pending = self.parse("4.568异狄氏剂(endrin)", 568)

        with self.assertRaisesRegex(RuntimeError, "stale"):
            MODULE.confirm_header(
                pending,
                expected_section=568,
                serial=MODULE.HEADER_GAP_LIMIT + 2,
            )

    def test_legacy_toc_header_recovers_a_mangled_body_heading(self):
        toc = MODULE.extract_legacy_toc_headers(
            [
                (3, "4.178 灭瘟素（blasticidin-S）........82"),
                (3, "4.179 灭线磷（ethoprophos）........83"),
                (4, "每种农药的最大残留限量规定如下。"),
            ]
        )

        header = MODULE.confirm_legacy_header(
            None,
            toc.get(179),
            expected_section=179,
            serial=5000,
        )

        self.assertEqual(header.pesticide_zh, "灭线磷")
        self.assertEqual(header.source_page, 3)
        self.assertEqual(header.evidence, "toc_fallback")

    def test_layout_form_feeds_preserve_pdf_page_numbers(self):
        lines = MODULE.paginate_layout_text("first page\n\fsecond page\n")

        self.assertEqual(lines, [(1, "first page"), (2, "second page")])

    def test_legacy_value_regex_preserves_temporary_and_footnote_suffix(self):
        match = MODULE.LEGACY_VALUE.match("          小麦          0.05 *a")

        self.assertIsNotNone(match)
        cell = MODULE.limit_cell_from_legacy_match(match)
        self.assertEqual(cell.limit_value, "0.05")
        self.assertEqual(cell.value_raw, "0.05*a")
        self.assertEqual(cell.limit_qualifier, "*a")
        self.assertEqual(cell.is_temporary, 1)

    def test_legacy_value_regex_preserves_non_temporary_footnote_suffix(self):
        match = MODULE.LEGACY_VALUE.match("          苹果          1 b")

        self.assertIsNotNone(match)
        cell = MODULE.limit_cell_from_legacy_match(match)
        self.assertEqual(cell.value_raw, "1b")
        self.assertEqual(cell.limit_qualifier, "b")
        self.assertEqual(cell.is_temporary, 0)

    def test_2026_value_cell_preserves_source_suffixes(self):
        temporary = MODULE.parse_2026_limit_cell("0.2∗")
        scope = MODULE.parse_2026_limit_cell("0.2(以脂肪计)")
        plain = MODULE.parse_2026_limit_cell("0.2")

        self.assertEqual(temporary.value_raw, "0.2∗")
        self.assertEqual(temporary.limit_qualifier, "∗")
        self.assertEqual(temporary.is_temporary, 1)
        self.assertEqual(scope.limit_qualifier, "(以脂肪计)")
        self.assertEqual(scope.is_temporary, 0)
        self.assertEqual(plain.limit_qualifier, "")
        self.assertEqual(plain.is_temporary, 0)

    def make_limit_row(
        self,
        *,
        parent="水果",
        food="苹果",
        value="0.1",
        qualifier="",
        temporary=0,
        page=10,
        source_y=700.0,
    ):
        return MODULE.LimitRow(
            year="2026",
            pesticide_zh="示例",
            parent_category=parent,
            food=food,
            limit_value=value,
            value_raw=f"{value}{qualifier}",
            limit_qualifier=qualifier,
            is_temporary=temporary,
            unit="mg/kg",
            section_number=1,
            source_page=page,
            source_y=source_y,
        )

    def test_same_food_rules_with_different_scope_are_preserved(self):
        rows = [
            self.make_limit_row(parent="谷物", food="蚕豆", page=54),
            self.make_limit_row(
                parent="蔬菜", food="蚕豆", value="0.5", page=55
            ),
        ]

        self.assertEqual(MODULE.validate_unique_2026_rules(rows), rows)

    def test_same_numeric_rule_with_different_qualifier_is_preserved(self):
        rows = [
            self.make_limit_row(),
            self.make_limit_row(qualifier="∗", temporary=1),
        ]

        self.assertEqual(MODULE.validate_unique_2026_rules(rows), rows)

    def test_unverified_exact_duplicate_rule_is_rejected(self):
        row = self.make_limit_row(value="1")

        with self.assertRaisesRegex(RuntimeError, "exact duplicate"):
            MODULE.validate_unique_2026_rules([row, row])

    def test_qualified_animal_group_labels_open_parent_scopes(self):
        expected = {
            "哺乳动物肉类(海洋哺乳动物除外)",
            "哺乳动物肉类(海洋哺乳动物除外),以脂肪中的残留量计",
            "哺乳动物内脏(海洋哺乳动物除外)",
            "哺乳动物脂肪",
            "哺乳动物脂肪(海洋哺乳动物除外)",
            "哺乳动物脂肪(乳脂肪除外)",
            "生乳(牛乳除外)",
        }

        self.assertTrue(expected.issubset(MODULE.PARENTS))

    def test_stale_parent_scope_for_animal_food_is_rejected(self):
        stale = [
            self.make_limit_row(parent="药用植物", food="猪肝")
        ]

        with self.assertRaisesRegex(RuntimeError, "parent scope regression"):
            MODULE.validate_2026_parent_scopes(stale)

    def test_explicit_animal_parent_scope_passes(self):
        valid = [
            self.make_limit_row(
                parent="哺乳动物内脏(海洋哺乳动物除外)",
                food="猪肝",
            )
        ]

        result = MODULE.validate_2026_parent_scopes(valid)

        self.assertEqual(result["checked_rows"]["mammal_offal"], 1)
        self.assertEqual(result["violations"], 0)


@unittest.skipUnless(
    os.environ.get("GB2763_SOURCE_ROOT"),
    "set GB2763_SOURCE_ROOT to run source-PDF integration tests",
)
class PesticideTextSourceIntegrationTests(unittest.TestCase):
    def test_all_text_editions_match_frozen_counts(self):
        source_root = Path(os.environ["GB2763_SOURCE_ROOT"])
        with tempfile.TemporaryDirectory() as temp_dir:
            report = MODULE.build(source_root, Path(temp_dir))

            self.assertEqual(report["counts"], MODULE.EXPECTED)
            reference = report["edition_2026_reference"]
            self.assertEqual(reference["official_pesticide_count"], 585)
            self.assertEqual(reference["limited_pesticide_sections"], 568)
            self.assertEqual(reference["official_pesticide_minus_numbered_sections"], 17)
            self.assertEqual(reference["appendix_b_exempt_list_entries"], 44)
            self.assertNotIn("record_recall_proxy", reference)
            self.assertIn("row_count_coverage_proxy", reference)
            self.assertIn("not recall or precision", reference["proxy_note"])
            parent_scope = report["edition_2026_parent_scope_validation"]
            self.assertEqual(parent_scope["violations"], 0)
            roster = Path(temp_dir) / "pesticide_text_section_roster.csv"
            with roster.open(encoding="utf-8-sig", newline="") as stream:
                roster_rows = list(csv.DictReader(stream))
            self.assertEqual(len(roster_rows), 1663)
            self.assertTrue(all(int(row["source_page"]) > 0 for row in roster_rows))

            legacy = Path(temp_dir) / "pesticide_limits_2012_2016.csv"
            with legacy.open(encoding="utf-8-sig", newline="") as stream:
                legacy_rows = list(csv.DictReader(stream))
            self.assertTrue(all(int(row["source_page"]) > 0 for row in legacy_rows))
            self.assertTrue(all(row["source_y"] == "" for row in legacy_rows))
            temporary_by_year = {
                year: sum(
                    int(row["is_temporary"])
                    for row in legacy_rows
                    if row["year"] == year
                )
                for year in MODULE.LEGACY_YEARS
            }
            self.assertEqual(temporary_by_year, MODULE.LEGACY_TEMPORARY_COUNTS)

            edition_2026 = Path(temp_dir) / "pesticide_2026_long.csv"
            with edition_2026.open(encoding="utf-8-sig", newline="") as stream:
                rows_2026 = list(csv.DictReader(stream))
            pig_liver_parents = {
                row["parent_category"]
                for row in rows_2026
                if row["food"] == "猪肝"
            }
            self.assertEqual(
                pig_liver_parents,
                {"哺乳动物内脏(海洋哺乳动物除外)"},
            )
            self.assertEqual(
                sum(int(row["is_temporary"]) for row in rows_2026),
                1906,
            )
            self.assertEqual(
                sum(bool(row["limit_qualifier"]) for row in rows_2026),
                1916,
            )
            for output in Path(temp_dir).glob("*.csv"):
                self.assertNotIn(b"\r\n", output.read_bytes())


if __name__ == "__main__":
    unittest.main()
