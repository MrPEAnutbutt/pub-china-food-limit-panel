"""Trend rules added in revision round 1 (A4): scope, multiple rules, gaps."""

import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


CLEAN_DIR = Path(__file__).resolve().parents[1]
if str(CLEAN_DIR) not in sys.path:
    sys.path.insert(0, str(CLEAN_DIR))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, CLEAN_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


UTILS = load("release_panel_utils_rules", "release_panel_utils.py")
POLLUTANT = load("rebuild_pollutant_rules", "260715_rebuild_pollutant.py")
MYCOTOXIN = load("rebuild_mycotoxin_rules", "260716_rebuild_mycotoxin.py")
REPLAY = load("replay_release_inputs_rules", "260716_replay_release_inputs.py")


def pesticide(record_id, year, value="1"):
    return {
        "record_id": record_id, "version_year": year, "pesticide_key": "PST1",
        "food_key": "FOD1", "pesticide_zh": "农药", "food_zh": "苹果",
        "pesticide_zh_raw": "农药", "parent_category_zh": "水果", "food_raw": "苹果",
        "limit_qualifier": "", "is_temporary": "false", "limit_value": value,
        "unit": "mg/kg", "review_status": "text_layer_auto_extracted",
    }


def additive(record_id, year, value="0.5"):
    return {
        "record_id": record_id, "version_year": year, "additive_zh": "添加剂",
        "cns_code": "01.001", "ins_code": "", "food_code": "11.01", "food_zh": "食糖",
        "max_use": value, "unit": "g/kg", "note": "",
        "edition_source_id": "E", "extraction_source_id": "X",
    }


def vet(record_id, year, animal, value="100", tissue="肌肉"):
    return {"record_id": record_id, "version_year": year, "drug_zh": "阿苯达唑",
            "drug_en": "Albendazole", "animal": animal, "tissue_zh": tissue,
            "limit_value": value}


class ReleasePanelRulesTest(unittest.TestCase):
    def test_pesticide_trend_across_a_missing_edition_is_not_judged(self):
        (row,) = UTILS.build_pesticide_panel_v2(
            [pesticide("P1", "2012"), pesticide("P2", "2021"), pesticide("P3", "2026")])
        self.assertEqual(row["trend"], "incomparable_edition_gap")
        (row,) = UTILS.build_pesticide_panel_v2(
            [pesticide("P1", "2019"), pesticide("P2", "2021"), pesticide("P3", "2026")])
        self.assertEqual(row["trend"], "stable")

    def test_additive_trend_across_a_missing_edition_is_not_judged(self):
        (row,) = UTILS.build_additive_panel([additive("A1", "2011"), additive("A2", "2024")])
        self.assertEqual(row["trend"], "incomparable_edition_gap")
        (row,) = UTILS.build_additive_panel([additive("A1", "2014"), additive("A2", "2024")])
        self.assertEqual(row["trend"], "stable")

    def test_vetdrug_summary_needs_the_same_covered_animals(self):
        (row,) = UTILS.build_vetdrug_summary_panel(
            [vet("V1", "2002", "牛/羊"), vet("V2", "2019", "所有食品动物")])
        self.assertEqual(row["trend"], "incomparable_scope_text")
        (row,) = UTILS.build_vetdrug_summary_panel(
            [vet("V1", "2002", "牛"), vet("V2", "2002", "猪"), vet("V3", "2019", "牛/猪")])
        self.assertEqual(row["trend"], "stable")

    def test_back_links_fail_when_a_cell_names_no_long_row(self):
        rows = [{"record_id": "X1", "v2012": "1"}]
        long_rows = [{"record_id": "L1", "key": "a"}]
        UTILS.link_source_records(rows, long_rows, ("2012",),
                                  lambda row, year: ["a"], lambda r: r["key"])
        self.assertEqual(rows[0]["source_record_ids_2012"], '["L1"]')
        with self.assertRaises(ValueError):
            UTILS.link_source_records(rows, long_rows, ("2012",),
                                      lambda row, year: ["b"], lambda r: r["key"])


class PollutantRulesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.alias = root / "category_alias.csv"
        with self.alias.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(POLLUTANT.ALIAS_FIELDS)
            writer.writerow(["双壳贝类", "双壳类", "已确认", "同物改名"])
        self.taxonomy = root / "food_taxonomy.csv"
        with self.taxonomy.open("w", encoding="utf-8-sig", newline="") as handle:
            csv.writer(handle).writerow(["child", "parent", "level", "src_year"])

    def tearDown(self):
        self.directory.cleanup()

    @staticmethod
    def rows(categories, value="0.5"):
        return [{"year": year, "analyte": "铅", "food_category": category,
                 "limit_value": value, "unit": "mg/kg", "basis": "", "confidence": "high"}
                for year, category in zip(POLLUTANT.YEARS, categories)]

    def test_category_with_changed_exclusions_is_not_judged(self):
        rows = self.rows(["肉制品", "肉制品", "肉制品(畜禽内脏制品除外)", "肉制品(畜禽内脏制品除外)"])
        (row,) = POLLUTANT.build_category_panel(rows, self.alias)
        self.assertEqual(row["trend"], "不可比(范围文字不同)")
        rows = self.rows(["双壳类", "双壳类", "双壳贝类", "双壳贝类"])
        (row,) = POLLUTANT.build_category_panel(rows, self.alias)
        self.assertEqual(row["trend"], "稳定")

    def test_residual_member_with_changed_exclusions_is_not_judged(self):
        rows = self.rows(["肉制品", "肉制品", "肉制品(畜禽内脏制品除外)", "肉制品(畜禽内脏制品除外)"])
        members = POLLUTANT.build_member_panel(rows, self.taxonomy, self.alias)
        (row,) = [m for m in members if m["food_member"] == "肉制品"]
        self.assertEqual(row["trend"], "incomparable_scope_text")
        rows = self.rows(["肉制品(畜禽内脏制品除外)"] * 4)
        members = POLLUTANT.build_member_panel(rows, self.taxonomy, self.alias)
        (row,) = [m for m in members if m["food_member"] == "肉制品"]
        self.assertEqual(row["trend"], "stable")


class PollutantMemberHostTest(unittest.TestCase):
    """A8: a member takes the first ancestor rule that does not exclude it."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.alias = root / "category_alias.csv"
        with self.alias.open("w", encoding="utf-8-sig", newline="") as handle:
            csv.writer(handle).writerow(POLLUTANT.ALIAS_FIELDS)
        self.taxonomy = root / "food_taxonomy.csv"
        self.containment = root / "category_containment.csv"
        self.write_taxonomy([])
        self.write_containment([])

    def tearDown(self):
        self.directory.cleanup()

    def write_taxonomy(self, edges):
        with self.taxonomy.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["child", "parent", "level", "src_year"])
            writer.writerows((child, parent, "2", "2012") for child, parent in edges)

    def write_containment(self, rows):
        with self.containment.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(POLLUTANT.CONTAINMENT_FIELDS)
            writer.writerows(rows)

    @staticmethod
    def rules(*specs):
        """specs: (years, category, value) with years like "2012,2017"."""
        return [{"year": year, "analyte": "铅", "food_category": category,
                 "limit_value": value, "unit": "mg/kg", "basis": "", "confidence": "high"}
                for years, category, value in specs for year in years.split(",")]

    def members(self, rows, containment=None):
        built = POLLUTANT.build_member_panel(
            rows, self.taxonomy, self.alias, containment)
        return {row["food_member"]: row for row in built}

    @staticmethod
    def values(row):
        return [row[f"v{year}"] for year in POLLUTANT.YEARS]

    def test_items_joined_by_he_are_each_excluded(self):
        self.write_taxonomy([("姬松茸", "新鲜食用菌")])
        rows = self.rules(("2012,2017,2022,2025", "新鲜食用菌(香菇和姬松茸除外)", "0.2"),
                          ("2022,2025", "姬松茸", "0.5"))
        row = self.members(rows)["姬松茸"]
        self.assertEqual(self.values(row), ["", "", "0.5", "0.5"])
        self.assertEqual(row["host_category_2012"], "")
        self.assertEqual(row["trend"], "stable")
        self.assertTrue(row["note"].startswith("2012, 2017: excluded by 新鲜食用菌"))

    def test_x_and_its_products_covers_x_products(self):
        self.write_taxonomy([("螺旋藻制品", "藻类及其制品")])
        rows = self.rules(("2012,2017,2022,2025", "藻类及其制品(螺旋藻及其制品除外)", "1.0"),
                          ("2017,2022,2025", "螺旋藻制品", "2.0"))
        row = self.members(rows)["螺旋藻制品"]
        self.assertEqual(self.values(row), ["", "2.0", "2.0", "2.0"])
        self.assertIn("2012: excluded by", row["note"])

    def test_x_and_its_beverages_is_a_rule_for_x(self):
        self.write_taxonomy([("果蔬汁类", "饮料类")])
        rows = self.rules(("2012", "果蔬汁类(浓缩果蔬汁(浆)除外)", "0.05"),
                          ("2017,2022", "果蔬汁类及其饮料[浓缩果蔬汁(浆)除外]", "0.03"),
                          ("2012,2017,2022", "饮料类(果蔬汁类及其饮料除外)", "0.3"))
        row = self.members(rows)["果蔬汁类"]
        self.assertEqual(self.values(row), ["0.05", "0.03", "0.03", ""])
        self.assertTrue(row["host_category_2017"].startswith("果蔬汁类及其饮料"))
        # Without its own rule, the member is still excluded from 饮料类.
        rows = [row for row in rows if "浆" not in row["food_category"]]
        self.assertNotIn("果蔬汁类", self.members(rows))

    def test_walk_stops_at_the_rule_that_excludes_the_member(self):
        rows = self.rules(("2012,2017,2022,2025", "调味品(香辛料类除外)", "1.0"),
                          ("2012,2017,2022,2025", "香辛料类(多种香辛料混合的香辛料除外)", "0.5"),
                          ("2017,2022,2025", "花椒、多种香辛料混合的香辛料", "3.0"))
        row = self.members(rows)["多种香辛料混合的香辛料"]
        # The long name is found in its merged row, and 2012 is not handed to
        # the grandparent 调味品.
        self.assertEqual(self.values(row), ["", "3.0", "3.0", "3.0"])
        self.assertIn("2012: excluded by 香辛料类", row["note"])

    def test_full_and_half_width_brackets_name_one_member(self):
        rows = self.rules(("2012", "带馅（料）面米制品", "0.5"),
                          ("2017,2022,2025", "带馅(料)面米制品", "0.5"))
        members = self.members(rows)
        self.assertNotIn("带馅（料）面米制品", members)
        row = members["带馅(料)面米制品"]
        self.assertEqual(self.values(row), ["0.5"] * 4)
        self.assertEqual(row["trend"], "stable")

    def spirits(self):
        return self.rules(("2012,2017", "蒸馏酒、黄酒", "0.5"),
                          ("2012,2017", "酒类(蒸馏酒、黄酒除外)", "0.2"),
                          ("2022,2025", "白酒、黄酒", "0.5"),
                          ("2022,2025", "酒类(白酒、黄酒除外)", "0.2"))

    def test_rewritten_exclusion_list_leaves_the_host_undetermined(self):
        row = self.members(self.spirits())["白酒"]
        self.assertEqual(self.values(row), ["", "", "0.5", "0.5"])
        self.assertEqual(
            row["note"],
            "2012, 2017: host not determinable; exclusion list of "
            "酒类(蒸馏酒、黄酒除外) differs from 2022")

    def test_confirmed_containment_fixes_the_host_and_blanks_split_categories(self):
        self.write_containment([["白酒", "蒸馏酒", "已确认", ""]])
        members = self.members(self.spirits(), self.containment)
        self.assertEqual(self.values(members["白酒"]), ["0.5"] * 4)
        self.assertEqual(members["白酒"]["host_category_2012"], "蒸馏酒、黄酒")
        self.assertEqual(members["白酒"]["note"], "")
        row = members["蒸馏酒"]
        self.assertEqual(self.values(row), ["0.5", "0.5", "", ""])
        self.assertEqual(
            row["note"],
            "2022, 2025: spans two printed rules; 酒类(白酒、黄酒除外) excludes part of it")

    def test_only_confirmed_containment_is_applied_and_bad_seeds_fail(self):
        self.write_containment([["白酒", "蒸馏酒", "待核", ""]])
        self.assertEqual(self.values(self.members(self.spirits(), self.containment)["白酒"]),
                         ["", "", "0.5", "0.5"])
        for rows, message in (([["白酒", "蒸馏酒", "unknown", ""]], "unsupported containment"),
                              ([["白酒", "蒸馏酒", "已确认", ""],
                                ["白酒", "酒类", "否决", ""]], "duplicate member"),
                              ([["白酒", "白酒", "已确认", ""]], "circular")):
            with self.subTest(message=message):
                self.write_containment(rows)
                with self.assertRaisesRegex(ValueError, message):
                    POLLUTANT.load_containment(self.containment, {})


class MycotoxinRulesTest(unittest.TestCase):
    def test_changed_scope_or_two_rules_block_the_category_trend(self):
        rows = [("2011", "黄曲霉毒素B1", "酱油、醋、酿造酱（以粮食为主要原料）", "5", "μg/kg", "high"),
                ("2017", "黄曲霉毒素B1", "酱油、醋、酿造酱", "5", "μg/kg", "high"),
                ("2011", "展青霉素", "水果制品（果丹皮除外）", "50", "μg/kg", "high"),
                ("2011", "展青霉素", "水果制品", "50", "μg/kg", "high"),
                ("2017", "展青霉素", "水果制品", "50", "μg/kg", "high"),
                ("2011", "展青霉素", "酒类", "50", "μg/kg", "high"),
                ("2017", "展青霉素", "酒类", "50", "μg/kg", "high")]
        trends = {(row[0], row[2]): row[6] for row in MYCOTOXIN.build_panel_rows(rows)}
        self.assertEqual(trends[("黄曲霉毒素B1", "酱油、醋、酿造酱")], "不可比(范围文字不同)")
        self.assertEqual(trends[("展青霉素", "水果制品")], "不可比(同版多规则)")
        self.assertEqual(trends[("展青霉素", "酒类")], "稳定")

    def test_member_whose_own_exclusions_change_is_not_judged(self):
        rows = [{"year": "2005", "toxin": "黄曲霉毒素B1", "food_category": "植物油脂（玉米油、花生油除外）",
                 "limit_value": "10", "unit": "μg/kg"},
                {"year": "2011", "toxin": "黄曲霉毒素B1", "food_category": "植物油脂",
                 "limit_value": "10", "unit": "μg/kg"}]
        members = REPLAY.build_mycotoxin_member_crosswalk(rows, [])
        (row,) = [m for m in members if m["member"] == "植物油脂"]
        self.assertEqual(row["trend"], "不可比(范围文字不同)")

    def test_an_exclusion_bracket_qualifies_only_its_listed_item(self):
        rows = [{"year": "2005", "toxin": "黄曲霉毒素B1", "food_category": "大米、植物油(除玉米油、花生油)",
                 "limit_value": "10", "unit": "μg/kg"},
                {"year": "2011", "toxin": "黄曲霉毒素B1", "food_category": "大米",
                 "limit_value": "10", "unit": "μg/kg"},
                {"year": "2011", "toxin": "黄曲霉毒素B1", "food_category": "植物油脂",
                 "limit_value": "10", "unit": "μg/kg"}]
        trends = {m["member"]: m["trend"] for m in REPLAY.build_mycotoxin_member_crosswalk(rows, [])}
        self.assertEqual(trends["大米"], "稳定")
        self.assertEqual(trends["植物油脂"], "不可比(范围文字不同)")


class VetdrugMemberRulesTest(unittest.TestCase):
    @staticmethod
    def rule(year, animal, value):
        return {"year": year, "drug": "双甲脒", "english": "amitraz", "animal": animal,
                "tissue": "脂肪", "limit_value": value, "unit": "μg/kg"}

    def test_two_equally_specific_rules_for_a_member_are_not_judged(self):
        rows = [self.rule("2002", "羊", "400"), self.rule("2019", "绵羊", "400"),
                self.rule("2019", "山羊", "200")]
        (row,) = REPLAY.build_vetdrug_member_crosswalk(rows)
        self.assertEqual(row["trend"], "不可比(同版多规则)")
        self.assertEqual(row["归属2019"], "绵羊；山羊")

    def test_specific_label_overrides_a_general_one(self):
        rows = [self.rule("2002", "羊", "400"), self.rule("2019", "所有食品动物", "100"),
                self.rule("2019", "羊", "200")]
        (row,) = [r for r in REPLAY.build_vetdrug_member_crosswalk(rows) if r["animal"] == "羊"]
        self.assertEqual(row["trend"], "收紧(变严)")
        self.assertEqual(row["归属2019"], "羊")

    def test_trend_across_a_missing_edition_is_not_judged(self):
        rows = [self.rule("2002", "羊", "400"), self.rule("2022", "羊", "200")]
        (row,) = REPLAY.build_vetdrug_member_crosswalk(rows)
        self.assertEqual(row["trend"], "不可比(跨过缺失版本)")


if __name__ == "__main__":
    unittest.main()
