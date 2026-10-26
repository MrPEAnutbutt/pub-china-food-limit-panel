import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "261024_panel_trend_audit.py"
SPEC = importlib.util.spec_from_file_location("panel_trend_audit", SCRIPT)
AUDIT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(AUDIT)

YEARS = ("2012", "2017", "2022", "2025")
ALIASES = {"双壳贝类": "双壳类"}


def category_row(record_id, trend, categories, values):
    row = {"record_id": record_id, "trend": trend, "analyte_zh": "铅",
           "food_category_zh": categories[0]}
    for year, category, value in zip(YEARS, categories, values):
        row.update({f"v{year}": value, f"unit_{year}": "mg/kg", f"basis_{year}": "",
                    f"cell_status_{year}": "single", f"source_category_{year}": category})
    return row


def long_rows(prefix, categories, values):
    return [{"record_id": f"{prefix}{year}", "version_year": year, "analyte_zh": "铅",
             "food_category_zh": category, "limit_basis": "", "limit_value": value,
             "unit": "mg/kg"}
            for year, category, value in zip(YEARS, categories, values)]


def flags_of(cell, years=YEARS):
    AUDIT.generic_flags(cell, years)
    return {flag for flag, _ in cell["flags"]}


class PollutantCategoryTest(unittest.TestCase):
    def audit(self, categories, values, trend="stable", long_values=None):
        row = category_row("PCP1", trend, categories, values)
        rows = long_rows("POL", categories, long_values or values)
        (cell,) = AUDIT.pollutant_category_cells([row], rows, ALIASES)
        return flags_of(cell)

    def test_changed_exclusion_list_blocks_the_comparison(self):
        flags = self.audit(["肉制品", "肉制品", "肉制品(畜禽内脏制品除外)",
                            "肉制品(畜禽内脏制品除外)"], ["0.5"] * 4)
        self.assertIn("scope_text_differs", flags)

    def test_confirmed_rename_is_not_a_scope_change(self):
        flags = self.audit(["双壳类", "双壳类", "双壳贝类", "双壳贝类"], ["1.5"] * 4)
        self.assertNotIn("scope_text_differs", flags)
        flags = self.audit(["鲜、冻水产动物(鱼类、双壳类除外)"] * 2
                           + ["鲜、冻水产动物(鱼类、双壳贝类除外)"] * 2, ["0.5"] * 4)
        self.assertNotIn("scope_text_differs", flags)

    def test_direction_label_must_follow_a_monotonic_sequence(self):
        flags = self.audit(["谷物"] * 4, ["1.0", "0.5", "0.8", "0.8"], trend="tightened")
        self.assertIn("label_not_reproduced_by_monotonic_rule", flags)
        flags = self.audit(["谷物"] * 4, ["1.0", "0.5", "0.5", "0.5"], trend="tightened")
        self.assertNotIn("label_not_reproduced_by_monotonic_rule", flags)

    def test_panel_value_must_match_its_long_row(self):
        flags = self.audit(["谷物"] * 4, ["0.2"] * 4, long_values=["0.2", "0.2", "0.3", "0.2"])
        self.assertIn("link_failure", flags)


class PollutantMemberHostTest(unittest.TestCase):
    RULES = (("2012", "蒸馏酒、黄酒", "0.5"), ("2012", "酒类(蒸馏酒、黄酒除外)", "0.2"),
             ("2022", "白酒、黄酒", "0.5"), ("2022", "酒类(白酒、黄酒除外)", "0.2"))

    def audit(self, host_2012, value_2012, contained_in):
        rows = [{"record_id": f"P{i}", "version_year": year, "analyte_zh": "铅",
                 "food_category_zh": category, "limit_basis": "", "limit_value": value,
                 "unit": "mg/kg", "confidence": "high"}
                for i, (year, category, value) in enumerate(self.RULES)]
        member = {"record_id": "PMP1", "trend": "stable", "analyte_zh": "铅",
                  "food_member_zh": "白酒"}
        for year in YEARS:
            member.update({f"v{year}": "", f"unit_{year}": "", f"basis_{year}": "",
                           f"host_category_{year}": ""})
        member.update({"v2012": value_2012, "unit_2012": "mg/kg", "host_category_2012": host_2012,
                       "v2022": "0.5", "unit_2022": "mg/kg", "host_category_2022": "白酒、黄酒"})
        (cell,) = AUDIT.pollutant_member_cells([member], rows, {}, contained_in)
        return [detail for flag, detail in cell["flags"]
                if flag == "host_rule_does_not_cover_member"]

    def test_host_that_excludes_the_member_is_flagged(self):
        details = self.audit("酒类(蒸馏酒、黄酒除外)", "0.2", {"白酒": "蒸馏酒"})
        self.assertEqual(details, ["2012: excluded; host 酒类(蒸馏酒、黄酒除外)"])
        self.assertEqual(self.audit("蒸馏酒、黄酒", "0.5", {"白酒": "蒸馏酒"}), [])

    def test_host_behind_a_rewritten_exclusion_list_is_flagged(self):
        details = self.audit("酒类(蒸馏酒、黄酒除外)", "0.2", {})
        self.assertEqual(details, ["2012: rewritten exclusion list; host 酒类(蒸馏酒、黄酒除外)"])

    def test_x_and_its_beverages_excludes_x(self):
        def fold(text):
            return text
        host = "饮料类(包装饮用水、果蔬汁类及其饮料除外)"
        self.assertEqual(AUDIT.host_coverage("果蔬汁类", host, "2017", {}, fold, {}), "excluded")
        self.assertEqual(AUDIT.host_coverage("果蔬汁类", "果蔬汁类及其饮料[浓缩果蔬汁(浆)除外]",
                                             "2017", {}, fold, {}), "")


class VetdrugMemberTest(unittest.TestCase):
    @staticmethod
    def rule(record_id, year, animal, value, source="text"):
        return {"record_id": record_id, "version_year": year, "drug_zh": "双甲脒",
                "animal": animal, "tissue_zh": "脂肪", "limit_value": value,
                "source": source}

    @staticmethod
    def member(v2002, v2019, v2022, trend):
        return {"record_id": "VMP1", "trend": trend, "drug_zh": "双甲脒", "animal": "羊",
                "tissue_zh": "脂肪", "v2002": v2002, "v2019": v2019, "v2022": v2022}

    def test_two_equally_specific_rules_for_one_member_are_masked(self):
        rows = [self.rule("V1", "2002", "羊", "400"),
                self.rule("V2", "2019", "绵羊", "400"),
                self.rule("V3", "2019", "山羊", "200")]
        (cell,) = AUDIT.vetdrug_member_cells([self.member("0.4", "0.2", "", "tightened")], rows)
        self.assertIn("masked_multiple_rules", flags_of(cell, ("2002", "2019", "2022")))

    def test_specific_rule_overrides_general_without_masking(self):
        rows = [self.rule("V1", "2002", "羊", "400"),
                self.rule("V2", "2019", "所有食品动物", "100"),
                self.rule("V3", "2019", "羊", "200")]
        (cell,) = AUDIT.vetdrug_member_cells([self.member("0.4", "0.2", "", "tightened")], rows)
        flags = flags_of(cell, ("2002", "2019", "2022"))
        self.assertNotIn("masked_multiple_rules", flags)
        self.assertNotIn("link_failure", flags)

    def test_skipped_edition_and_manual_entry_are_flagged(self):
        rows = [self.rule("V1", "2002", "羊", "400"),
                self.rule("V2", "2022", "羊", "200", source="manual")]
        (cell,) = AUDIT.vetdrug_member_cells([self.member("0.4", "", "0.2", "tightened")], rows)
        flags = flags_of(cell, ("2002", "2019", "2022"))
        self.assertIn("edition_gap", flags)
        self.assertIn("manual_entry_vetdrug_2022", flags)


if __name__ == "__main__":
    unittest.main()
