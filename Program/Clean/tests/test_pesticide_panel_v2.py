import importlib.util
import json
import random
import unittest
from collections import Counter
from pathlib import Path


UTILS_PATH = Path(__file__).resolve().parents[1] / "release_panel_utils.py"
SPEC = importlib.util.spec_from_file_location("release_panel_utils_v2", UTILS_PATH)
UTILS = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(UTILS)


def pesticide_rule(
    record_id,
    year,
    value,
    *,
    pesticide_key="pesticide-key",
    food_key="food-key",
    pesticide_zh="测试农药",
    food_zh="测试食品",
    pesticide_raw="测试农药",
    parent_category_zh="食品大类",
    food_raw="测试食品",
    unit="mg/kg",
    limit_qualifier="",
    is_temporary=0,
    review_status="text_layer_auto_extracted",
    edition_source_id="gb2763-edition",
    extraction_source_id="gb2763-extraction",
    source_id="",
):
    return {
        "record_id": record_id,
        "standard": "GB 2763",
        "version_year": year,
        "pesticide_key": pesticide_key,
        "food_key": food_key,
        "pesticide_zh": pesticide_zh,
        "food_zh": food_zh,
        "pesticide_zh_raw": pesticide_raw,
        "parent_category_zh": parent_category_zh,
        "food_raw": food_raw,
        "limit_value": value,
        "unit": unit,
        "limit_qualifier": limit_qualifier,
        "is_temporary": is_temporary,
        "review_status": review_status,
        "edition_source_id": edition_source_id,
        "extraction_source_id": extraction_source_id,
        "source_id": source_id,
        "source_page": "10",
    }


def trend_for(rows):
    panel = UTILS.build_pesticide_panel_v2(rows)
    if len(panel) != 1:
        raise AssertionError(f"expected one panel row, got {len(panel)}")
    return panel[0]["trend"]


class PesticidePanelV2Tests(unittest.TestCase):
    def test_numeric_trend_states_are_explicit(self):
        cases = {
            "single_version": [
                pesticide_rule("P001", "2012", "1"),
            ],
            "stable": [
                pesticide_rule("P001", "2012", "1.0"),
                pesticide_rule("P002", "2014", "1"),
            ],
            "tightened": [
                pesticide_rule("P001", "2012", "1"),
                pesticide_rule("P002", "2014", "0.5"),
            ],
            "relaxed": [
                pesticide_rule("P001", "2012", "0.5"),
                pesticide_rule("P002", "2014", "1"),
            ],
            "fluctuation": [
                pesticide_rule("P001", "2012", "1"),
                pesticide_rule("P002", "2014", "0.5"),
                pesticide_rule("P003", "2016", "0.8"),
            ],
        }

        for expected, rows in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(trend_for(rows), expected)

    def test_gate_precedence_is_multiple_unit_unresolved_scope_non_numeric(self):
        multiple = [
            pesticide_rule("P001", "2012", "1", unit="mg/kg"),
            pesticide_rule(
                "P002",
                "2012",
                "1",
                unit="mg/L",
                review_status="parent_scope_unresolved",
                food_raw="另一食品",
            ),
            pesticide_rule("P003", "2014", "GMP"),
        ]
        units = [
            pesticide_rule("P001", "2012", "1", unit="mg/kg"),
            pesticide_rule(
                "P002",
                "2014",
                "1",
                unit="mg/L",
                review_status="parent_scope_unresolved",
                food_raw="另一食品",
            ),
        ]
        unresolved = [
            pesticide_rule("P001", "2012", "1"),
            pesticide_rule(
                "P002",
                "2014",
                "1",
                limit_qualifier="source_marker_c_unresolved",
                food_raw="另一食品",
            ),
        ]
        scope = [
            pesticide_rule("P001", "2012", "1", food_raw="食品甲"),
            pesticide_rule("P002", "2014", "GMP", food_raw="食品乙"),
        ]
        non_numeric = [
            pesticide_rule("P001", "2012", "GMP"),
            pesticide_rule("P002", "2014", "GMP"),
        ]

        self.assertEqual(
            trend_for(multiple),
            "incomparable_multiple_rules",
        )
        self.assertEqual(trend_for(units), "incomparable_units")
        self.assertEqual(
            trend_for(unresolved),
            "incomparable_unresolved_review_or_source_qualifier",
        )
        self.assertEqual(trend_for(scope), "incomparable_scope_text")
        self.assertEqual(trend_for(non_numeric), "incomparable_non_numeric")

        review_token = [
            pesticide_rule("P001", "2012", "1"),
            pesticide_rule(
                "P002",
                "2014",
                "1",
                review_status="text_layer_auto_extracted;review_name_conf_30_49",
            ),
        ]
        self.assertEqual(
            trend_for(review_token),
            "incomparable_unresolved_review_or_source_qualifier",
        )

        documented_structure_exception = [
            pesticide_rule(
                "P001",
                "2012",
                "1",
                review_status="text_layer_auto_extracted;source_structure_exception",
            ),
            pesticide_rule("P002", "2014", "1"),
        ]
        self.assertEqual(trend_for(documented_structure_exception), "stable")

        unresolved_footnote = [
            pesticide_rule("P001", "2012", "1", limit_qualifier="b"),
            pesticide_rule("P002", "2014", "1", limit_qualifier="b"),
        ]
        self.assertEqual(
            trend_for(unresolved_footnote),
            "incomparable_unresolved_review_or_source_qualifier",
        )

    def test_each_scope_bearing_change_blocks_numeric_trend(self):
        changes = {
            "parenthetical_exclusion": {
                "food_raw": ("水果(柠檬除外)", "水果"),
            },
            "parenthetical_only": {
                "food_raw": ("水果(仅限柑橘)", "水果"),
            },
            "temporary": {"is_temporary": (1, 0)},
            "fat_basis": {"limit_qualifier": ("(以脂肪计)", "")},
            "as_sampled_basis": {"limit_qualifier": ("(以原样计)", "")},
            "chemical_form": {
                "pesticide_raw": ("glyphosate (ammonium salt)", "glyphosate"),
            },
            "parent_category": {
                "parent_category_zh": ("新鲜水果", "水果制品"),
            },
        }

        for label, fields in changes.items():
            first = {name: pair[0] for name, pair in fields.items()}
            second = {name: pair[1] for name, pair in fields.items()}
            rows = [
                pesticide_rule("P001", "2012", "1", **first),
                pesticide_rule("P002", "2014", "0.5", **second),
            ]
            with self.subTest(label=label):
                self.assertEqual(trend_for(rows), "incomparable_scope_text")

    def test_equivalent_unicode_whitespace_and_punctuation_do_not_block(self):
        rows = [
            pesticide_rule(
                "P001",
                "2012",
                "1.0",
                pesticide_raw="glyphosate（ammonium salt；free acid only）",
                parent_category_zh="果 类",
                food_raw="柑橘类（柠檬除外；代码 1．2）",
                unit="ｍｇ／ｋｇ",
                limit_qualifier="（以脂肪计）",
                is_temporary=0,
            ),
            pesticide_rule(
                "P002",
                "2014",
                "1",
                pesticide_raw=" glyphosate(ammonium salt, free acid only) ",
                parent_category_zh="果　类",
                food_raw="柑橘类(柠檬除外,代码1.2)",
                unit="mg/kg",
                limit_qualifier="(以脂肪计)",
                is_temporary="false",
            ),
        ]

        self.assertEqual(trend_for(rows), "stable")

    def test_scope_normalizer_retains_semantic_content(self):
        normalise = UTILS._normalise_pesticide_scope_text
        base = normalise("水果(柠檬除外;仅限浆果;0.5-1.0 mg/kg)")

        self.assertNotEqual(base, normalise("水果(柠檬;仅限浆果;0.5-1.0 mg/kg)"))
        self.assertNotEqual(base, normalise("水果(柠檬除外;浆果;0.5-1.0 mg/kg)"))
        self.assertNotEqual(base, normalise("水果(柠檬除外;仅限浆果;0.5-10 mg/kg)"))
        self.assertNotEqual(base, normalise("水果柠檬除外;仅限浆果;0.5-1.0 mg/kg"))

    def test_rules_counts_and_source_ids_preserve_every_record(self):
        rows = [
            pesticide_rule(
                "P003",
                "2014",
                "0.5",
                edition_source_id="edition-2014",
                extraction_source_id="copy-2014",
            ),
            pesticide_rule(
                "P001",
                "2012",
                "1",
                edition_source_id="edition-2012",
                extraction_source_id="copy-2012",
                source_id="generic-2012",
            ),
            pesticide_rule(
                "P002",
                "2014",
                "0.5",
                edition_source_id="edition-2014",
                extraction_source_id="copy-2014",
            ),
        ]
        panel = UTILS.build_pesticide_panel_v2(rows)[0]

        self.assertEqual(panel["status_2012"], "single_rule")
        self.assertEqual(panel["status_2014"], "multiple_rules_same_value")
        self.assertEqual(panel["status_2016"], "missing")
        self.assertEqual(panel["candidate_count_2014"], 2)
        self.assertEqual(panel["distinct_value_count_2014"], 1)
        self.assertEqual(json.loads(panel["values_2014"]), ["0.5"])
        self.assertEqual(json.loads(panel["units_2014"]), ["mg/kg"])
        self.assertEqual(
            json.loads(panel["source_ids_2012"]),
            ["copy-2012", "edition-2012", "generic-2012"],
        )
        self.assertEqual(
            json.loads(panel["edition_source_ids_2014"]),
            ["edition-2014"],
        )
        self.assertEqual(
            json.loads(panel["extraction_source_ids_2014"]),
            ["copy-2014"],
        )
        rules_2014 = json.loads(panel["rules_2014"])
        self.assertEqual([rule["record_id"] for rule in rules_2014], ["P002", "P003"])
        self.assertTrue(
            {
                "record_id",
                "limit_value",
                "unit",
                "pesticide_zh_raw",
                "parent_category_zh",
                "food_raw",
                "limit_qualifier",
                "is_temporary",
                "review_status",
            }.issubset(rules_2014[0])
        )

        referenced = []
        for year in UTILS.PESTICIDE_YEARS:
            referenced.extend(json.loads(panel[f"source_record_ids_{year}"]))
        self.assertEqual(Counter(referenced), Counter(row["record_id"] for row in rows))

    def test_key_fallback_and_input_order_invariance(self):
        rows = [
            pesticide_rule(
                "P001",
                "2012",
                "1",
                pesticide_key="",
                food_key="",
                pesticide_zh="百菌清",
                food_zh="番茄",
                pesticide_raw="百菌清",
                food_raw="番茄",
            ),
            pesticide_rule(
                "P002",
                "2014",
                "1",
                pesticide_key="",
                food_key="",
                pesticide_zh="百菌清",
                food_zh="番茄",
                pesticide_raw="百菌清",
                food_raw="番茄",
            ),
        ]
        shuffled = rows.copy()
        random.Random(20260716).shuffle(shuffled)

        expected = UTILS.build_pesticide_panel_v2(rows)
        self.assertEqual(expected, UTILS.build_pesticide_panel_v2(shuffled))
        self.assertEqual(len(expected), 1)
        self.assertEqual(expected[0]["pesticide_key"], "百菌清")
        self.assertEqual(expected[0]["food_key"], "番茄")

    def test_invalid_identifiers_fail_before_records_can_be_lost(self):
        duplicate = [
            pesticide_rule("P001", "2012", "1"),
            pesticide_rule("P001", "2014", "1"),
        ]
        unsupported_year = [pesticide_rule("P001", "2020", "1")]
        missing_keys = [
            pesticide_rule(
                "P001",
                "2012",
                "1",
                pesticide_key="",
                food_key="",
                pesticide_zh="",
                food_zh="",
            )
        ]

        with self.assertRaisesRegex(ValueError, "duplicate pesticide record_id"):
            UTILS.build_pesticide_panel_v2(duplicate)
        with self.assertRaisesRegex(ValueError, "unsupported pesticide version_year"):
            UTILS.build_pesticide_panel_v2(unsupported_year)
        with self.assertRaisesRegex(ValueError, "requires pesticide_key"):
            UTILS.build_pesticide_panel_v2(missing_keys)


if __name__ == "__main__":
    unittest.main()
