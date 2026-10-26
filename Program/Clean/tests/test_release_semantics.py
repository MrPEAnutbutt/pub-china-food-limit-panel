import csv
import importlib.util
import json
import random
import unittest
from collections import Counter
from collections import defaultdict
from pathlib import Path


REL = (
    Path(__file__).resolve().parents[3]
    / "Data"
    / "Final"
    / "china_food_limit_panel_v1"
)
UTILS_PATH = Path(__file__).resolve().parents[1] / "release_panel_utils.py"
SPEC = importlib.util.spec_from_file_location("release_panel_utils", UTILS_PATH)
UTILS = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(UTILS)


def read_csv(name):
    with (REL / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sorted_unique(values):
    unique = {str(value) for value in values if value not in (None, "")}

    def sort_key(value):
        try:
            return False, float(value)
        except ValueError:
            return True, value

    return sorted(unique, key=sort_key)


def additive_row(
    record_id,
    year,
    *,
    food="食品甲",
    note="",
    value="1.0",
    unit="g/kg",
):
    return {
        "record_id": record_id,
        "standard": "GB 2760",
        "version_year": year,
        "additive_zh": "测试剂",
        "cns_code": "01.001",
        "ins_code": "100",
        "food_code": "01.0",
        "food_zh": food,
        "max_use": value,
        "unit": unit,
        "note": note,
        "conflict": "0",
    }


class MultiValuePanelTests(unittest.TestCase):
    def test_scope_text_normalizer_removes_only_equivalent_typography(self):
        left = " 饮料（14.01）；残留量≦0.5 mg/kg。 "
        right = "饮料(14.01),残留量≤0.5mg/kg"

        self.assertEqual(
            UTILS._normalise_scope_text(left),
            UTILS._normalise_scope_text(right),
        )
        self.assertNotEqual(
            UTILS._normalise_scope_text("饮料14.01"),
            UTILS._normalise_scope_text("饮料1401"),
        )
        self.assertNotEqual(
            UTILS._normalise_scope_text("残留量≤0.5"),
            UTILS._normalise_scope_text("残留量<0.5"),
        )

    def test_additive_scope_mismatch_precedes_scalar_and_gmp_trends(self):
        food_change = UTILS.build_additive_panel(
            [
                additive_row("ADD00001", "2011", food="食品甲"),
                additive_row("ADD00002", "2014", food="食品甲(仅限固体)"),
            ]
        )[0]
        note_change = UTILS.build_additive_panel(
            [
                additive_row("ADD00001", "2011", value="GMP", unit=""),
                additive_row(
                    "ADD00002",
                    "2014",
                    note="按稀释倍数增加使用量",
                    value="GMP",
                    unit="",
                ),
            ]
        )[0]
        punctuation_only = UTILS.build_additive_panel(
            [
                additive_row("ADD00001", "2011", food="食品甲（如：乙、丙）"),
                additive_row("ADD00002", "2014", food="食品甲(如乙,丙)"),
            ]
        )[0]

        self.assertEqual(food_change["trend"], "incomparable_scope_text")
        self.assertEqual(note_change["trend"], "incomparable_scope_text")
        self.assertEqual(punctuation_only["trend"], "stable")

    def test_multi_rule_and_unit_gates_precede_scope_text_gate(self):
        multiple = UTILS.build_additive_panel(
            [
                additive_row("ADD00001", "2011", food="食品甲"),
                additive_row("ADD00002", "2011", food="食品甲", value="2.0"),
                additive_row("ADD00003", "2014", food="食品乙"),
            ]
        )[0]
        units = UTILS.build_additive_panel(
            [
                additive_row("ADD00001", "2011", food="食品甲", unit="g/kg"),
                additive_row("ADD00002", "2014", food="食品乙", unit="g/L"),
            ]
        )[0]

        self.assertEqual(multiple["trend"], "incomparable_multiple_rules")
        self.assertEqual(units["trend"], "incomparable_units")

    def assert_panel_truth_table(
        self,
        long_rows,
        panel_rows,
        years,
        key_fields,
        *,
        family,
    ):
        grouped = defaultdict(list)
        for row in long_rows:
            key = tuple(row[field] for field in key_fields) + (row["version_year"],)
            grouped[key].append(row)

        referenced = []
        for row in panel_rows:
            for year in years:
                key = tuple(row[field] for field in key_fields) + (year,)
                candidates = grouped.get(key, [])
                source_ids = json.loads(row[f"source_record_ids_{year}"])
                expected_source_ids = sorted(
                    candidate["record_id"] for candidate in candidates
                )
                referenced.extend(source_ids)
                self.assertEqual(source_ids, expected_source_ids)
                self.assertEqual(
                    [
                        rule["record_id"]
                        for rule in json.loads(row[f"rules_{year}"])
                    ],
                    expected_source_ids,
                )
                self.assertEqual(int(row[f"candidate_count_{year}"]), len(candidates))
                values = sorted_unique(
                    candidate["limit_value"] for candidate in candidates
                )
                units = sorted_unique(candidate["unit"] for candidate in candidates)
                self.assertEqual(
                    int(row[f"distinct_value_count_{year}"]),
                    len(values),
                )
                self.assertEqual(json.loads(row[f"values_{year}"]), values)
                self.assertEqual(json.loads(row[f"units_{year}"]), units)

                if family == "pesticide":
                    if not candidates:
                        expected_status = "missing"
                    elif len(candidates) == 1:
                        expected_status = "single_rule"
                    elif len(values) <= 1:
                        expected_status = "multiple_rules_same_value"
                    else:
                        expected_status = "multiple_rules_distinct_values"
                elif family == "additive":
                    if not candidates:
                        expected_status = "missing"
                    elif len(candidates) == 1:
                        expected_status = "single"
                    elif len(values) > 1 or len(units) > 1:
                        expected_status = "multiple_distinct_values"
                    else:
                        expected_status = "multiple_same_value"
                else:
                    raise AssertionError(f"unsupported panel family: {family}")

                self.assertEqual(row[f"status_{year}"], expected_status)
                if len(candidates) == 1:
                    self.assertEqual(row[f"v{year}"], candidates[0]["limit_value"])
                else:
                    self.assertEqual(row[f"v{year}"], "")
                if len(candidates) > 1:
                    self.assertEqual(row["trend"], "incomparable_multiple_rules")

        self.assertEqual(Counter(referenced), Counter(row["record_id"] for row in long_rows))

    def test_pesticide_multi_rule_cell_cannot_receive_scalar_trend(self):
        row = next(
            row
            for row in read_csv("pesticide_panel.csv")
            if row["pesticide_zh"] == "硫丹" and row["food_zh"] == "禽肉类"
        )

        self.assertEqual(row["status_2012"], "multiple_rules_distinct_values")
        self.assertEqual(row["trend"], "incomparable_multiple_rules")
        self.assertEqual(row["v2012"], "")
        self.assertEqual(json.loads(row["values_2012"]), ["0.03", "0.2"])

    def test_additive_mixed_unit_cell_cannot_receive_scalar_value(self):
        row = next(
            row
            for row in read_csv("additive_panel.csv")
            if row["additive_zh"] == "二氧化钛"
            and row["cns_code"] == "08.011"
            and row["food_code"] == "16.07"
        )

        self.assertEqual(row["status_2011"], "multiple_distinct_values")
        self.assertEqual(row["trend"], "incomparable_multiple_rules")
        self.assertEqual(row["v2011"], "")
        self.assertEqual(json.loads(row["units_2011"]), ["g/L", "g/kg"])

    def test_every_pesticide_scalar_cell_maps_to_one_long_record(self):
        long_groups = defaultdict(list)
        for row in read_csv("pesticide_limits_long.csv"):
            key = (row["pesticide_key"], row["food_key"], row["version_year"])
            long_groups[key].append(row)

        for row in read_csv("pesticide_panel.csv"):
            for year in ("2012", "2014", "2016", "2019", "2021", "2026"):
                key = (row["pesticide_key"], row["food_key"], year)
                source_rows = long_groups.get(key, [])
                source_ids = json.loads(row[f"source_record_ids_{year}"])
                self.assertEqual(
                    source_ids,
                    sorted(item["record_id"] for item in source_rows),
                )
                if row[f"v{year}"]:
                    self.assertEqual(row[f"status_{year}"], "single_rule")
                    self.assertEqual(len(source_rows), 1)
                if len(source_rows) > 1:
                    self.assertTrue(
                        row[f"status_{year}"].startswith("multiple_rules_")
                    )
                    self.assertEqual(row["trend"], "incomparable_multiple_rules")

    def test_every_additive_scalar_cell_maps_to_one_long_record(self):
        long_groups = defaultdict(list)
        for row in read_csv("additive_limits_long.csv"):
            cns = ",".join(
                sorted(part.strip() for part in row["cns_code"].split(",") if part.strip())
            )
            key = (cns, row["food_code"], row["version_year"])
            long_groups[key].append(row)

        for row in read_csv("additive_panel.csv"):
            for year in ("2011", "2014", "2024"):
                key = (row["cns_code"], row["food_code"], year)
                source_rows = long_groups.get(key, [])
                source_ids = json.loads(row[f"source_record_ids_{year}"])
                self.assertEqual(
                    source_ids,
                    sorted(item["record_id"] for item in source_rows),
                )
                if row[f"v{year}"]:
                    self.assertEqual(row[f"status_{year}"], "single")
                    self.assertEqual(len(source_rows), 1)
                if len(source_rows) > 1:
                    self.assertTrue(row[f"status_{year}"].startswith("multiple_"))
                    self.assertEqual(row["trend"], "incomparable_multiple_rules")

    def test_panel_builders_are_invariant_to_long_row_order(self):
        pesticide_long = read_csv("pesticide_limits_long.csv")
        additive_long = read_csv("additive_limits_long.csv")
        shuffled_pesticide = pesticide_long.copy()
        shuffled_additive = additive_long.copy()
        rng = random.Random(20260715)
        rng.shuffle(shuffled_pesticide)
        rng.shuffle(shuffled_additive)

        self.assertEqual(
            UTILS.build_pesticide_panel_v2(pesticide_long),
            UTILS.build_pesticide_panel_v2(shuffled_pesticide),
        )
        self.assertEqual(
            UTILS.build_additive_panel(additive_long),
            UTILS.build_additive_panel(shuffled_additive),
        )

    def test_pesticide_panel_truth_table_and_record_conservation(self):
        long_rows = read_csv("pesticide_limits_long.csv")
        panel_rows = UTILS.build_pesticide_panel_v2(long_rows)
        self.assert_panel_truth_table(
            long_rows,
            panel_rows,
            UTILS.PESTICIDE_YEARS,
            ("pesticide_key", "food_key"),
            family="pesticide",
        )

    def test_additive_panel_truth_table_and_record_conservation(self):
        long_rows = read_csv("additive_limits_long.csv")
        for row in long_rows:
            row["cns_code"] = ",".join(
                sorted(part.strip() for part in row["cns_code"].split(",") if part.strip())
            )
            row["limit_value"] = row["max_use"]
        panel_rows = UTILS.build_additive_panel(long_rows)
        self.assert_panel_truth_table(
            long_rows,
            panel_rows,
            UTILS.ADDITIVE_YEARS,
            ("cns_code", "food_code"),
            family="additive",
        )

    def test_additive_scope_gate_distribution_is_frozen(self):
        rows = read_csv("additive_panel.csv")
        counts = Counter(row["trend"] for row in rows)

        self.assertEqual(
            counts,
            Counter(
                {
                    "stable": 1097,
                    "single_version": 732,
                    "incomparable_scope_text": 605,
                    "stable_gmp": 256,
                    "incomparable_units": 47,
                    "incomparable_multiple_rules": 18,
                    "relaxed": 5,
                    "fluctuation": 1,
                    "incomparable_edition_gap": 1,
                }
            ),
        )
        by_key = {
            (row["cns_code"], row["food_code"]): row["trend"] for row in rows
        }
        expected_examples = {
            ("05.001,05.002,05.003,05.004,05.005,05.006", "11.01.01"): (
                "incomparable_scope_text"
            ),
            ("05.007", "11.01.01"): "incomparable_scope_text",
            ("19.004", "12.10.03"): "incomparable_scope_text",
            ("19.006,19.023", "09.02.03"): "incomparable_scope_text",
            ("19.019", "04.01.02.08"): "incomparable_scope_text",
            ("08.006", "05.03"): "relaxed",
            ("19.002", "04.02.02.03"): "relaxed",
            ("19.002", "07.01"): "relaxed",
            ("19.002", "07.02"): "relaxed",
            ("19.016", "06.04.02.02"): "relaxed",
            ("17.009(i),17.009(ii)", "04.02.02.03"): "fluctuation",
        }
        for key, expected in expected_examples.items():
            with self.subTest(key=key):
                self.assertEqual(by_key[key], expected)


if __name__ == "__main__":
    unittest.main()
