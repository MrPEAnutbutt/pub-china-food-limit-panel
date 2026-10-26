import csv
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "260715_rebuild_pollutant.py"
PROJECT_ROOT = SCRIPT.parents[2]
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("rebuild_pollutant", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def canon(text):
    return (
        text.replace("（", "(")
        .replace("）", ")")
        .replace("［", "[")
        .replace("］", "]")
        .replace(" ", "")
    )


class CategoryParserTests(unittest.TestCase):
    def test_nested_exclusion_uses_outer_bracket(self):
        base, excluded = MODULE.split_category(
            "谷物碾磨加工品[糙米、大米(粉)除外]", {}
        )

        self.assertEqual(base, "谷物碾磨加工品")
        self.assertEqual(excluded, ["糙米", "大米(粉)"])

    def test_enumeration_splits_only_at_top_level(self):
        self.assertEqual(
            MODULE.split_top_level("稻谷、糙米、大米(粉)、玉米糁(渣)"),
            ["稻谷", "糙米", "大米(粉)", "玉米糁(渣)"],
        )

    def test_unbalanced_category_is_rejected(self):
        self.assertEqual(
            MODULE.category_error(
                "特殊医学用途配方食品(特殊医学用途婴儿配方食品涉及的"
            ),
            "unclosed_bracket",
        )

    def test_mixed_blank_and_named_bases_have_explicit_summary(self):
        self.assertEqual(
            MODULE.summarize_basis({"", "干重计"}),
            "varies_by_version",
        )


class AliasAdjudicationTests(unittest.TestCase):
    def write_aliases(self, path, rows):
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=MODULE.ALIAS_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def test_only_confirmed_aliases_enter_formal_derivation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "category_alias.csv"
            self.write_aliases(
                path,
                [
                    {
                        "异名": "已核异名",
                        "规范名": "已核规范名",
                        "status": "已确认",
                        "说明": "",
                    },
                    {
                        "异名": "待核异名",
                        "规范名": "待核规范名",
                        "status": "待核",
                        "说明": "",
                    },
                ],
            )

            aliases = MODULE.load_aliases(path)

            self.assertEqual(aliases, {"已核异名": "已核规范名"})
            self.assertEqual(MODULE.clean_member("待核异名", aliases), "待核异名")

    def test_unknown_status_and_duplicate_source_fail_closed(self):
        cases = (
            (
                [
                    {
                        "异名": "A",
                        "规范名": "B",
                        "status": "unknown",
                        "说明": "",
                    }
                ],
                "unsupported alias adjudication status",
            ),
            (
                [
                    {"异名": "A", "规范名": "B", "status": "已确认", "说明": ""},
                    {"异名": "A", "规范名": "C", "status": "待核", "说明": ""},
                ],
                "duplicate source label",
            ),
        )
        for rows, message in cases:
            with self.subTest(message=message):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "category_alias.csv"
                    self.write_aliases(path, rows)
                    with self.assertRaisesRegex(ValueError, message):
                        MODULE.load_aliases(path)

    def test_cli_defaults_to_project_local_release_dependencies(self):
        args = MODULE.parse_args(["--source-dir", "/tmp/gb2762"])

        self.assertEqual(
            args.legacy_path,
            MODULE.DEFAULT_DEPENDENCY_DIR / "pollutant_old_path.csv",
        )
        self.assertEqual(
            args.taxonomy_path,
            MODULE.DEFAULT_DEPENDENCY_DIR / "food_taxonomy.csv",
        )
        self.assertEqual(
            args.alias_path,
            MODULE.DEFAULT_DEPENDENCY_DIR / "category_alias.csv",
        )
        self.assertEqual(
            args.containment_path,
            MODULE.DEFAULT_DEPENDENCY_DIR / "category_containment.csv",
        )

    def test_formal_rebuild_rejects_mutated_dependency_before_source_read(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            alias = directory / "category_alias.csv"
            alias.write_bytes(
                (MODULE.DEFAULT_DEPENDENCY_DIR / "category_alias.csv").read_bytes()
                + b"\n"
            )

            with self.assertRaisesRegex(ValueError, "digest differs"):
                MODULE.rebuild(
                    source_dir=directory / "missing-source",
                    legacy_path=(
                        MODULE.DEFAULT_DEPENDENCY_DIR / "pollutant_old_path.csv"
                    ),
                    taxonomy_path=(
                        MODULE.DEFAULT_DEPENDENCY_DIR / "food_taxonomy.csv"
                    ),
                    alias_path=alias,
                    containment_path=(
                        MODULE.DEFAULT_DEPENDENCY_DIR / "category_containment.csv"
                    ),
                    output_dir=directory / "output",
                )

            self.assertFalse((directory / "output").exists())

    def test_missing_taxonomy_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "taxonomy file is missing"):
                MODULE.load_taxonomy(Path(directory) / "missing.csv", {})


class PollutantRebuildIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source_value = os.environ.get("FOOD_STANDARD_POLLUTANT_SOURCE_DIR")
        processing_value = os.environ.get(
            "FOOD_LIMIT_PROCESSING_DIR",
            str(PROJECT_ROOT / "Data" / "Interim" / "release_dependencies"),
        )
        if not source_value:
            raise unittest.SkipTest(
                "Set FOOD_STANDARD_POLLUTANT_SOURCE_DIR for source-dependent tests"
            )
        source_dir = Path(source_value)
        processing_dir = Path(processing_value)
        required = [
            source_dir,
            processing_dir / "pollutant_old_path.csv",
            processing_dir / "food_taxonomy.csv",
            processing_dir / "category_alias.csv",
            processing_dir / "category_containment.csv",
        ]
        if not all(path.exists() for path in required):
            raise unittest.SkipTest("The local GB 2762 source bundle is unavailable")
        cls.temp = tempfile.TemporaryDirectory()
        cls.output_dir = Path(cls.temp.name)
        cls.report = MODULE.rebuild(
            source_dir=source_dir,
            legacy_path=processing_dir / "pollutant_old_path.csv",
            taxonomy_path=processing_dir / "food_taxonomy.csv",
            alias_path=processing_dir / "category_alias.csv",
            containment_path=processing_dir / "category_containment.csv",
            output_dir=cls.output_dir,
        )
        cls.long_rows = read_csv(cls.output_dir / "pollutant_limits_long.csv")
        cls.quarantine = read_csv(cls.output_dir / "pollutant_quarantine.csv")
        cls.members = read_csv(cls.output_dir / "pollutant_member_panel.csv")
        cls.compatible_members = read_csv(cls.output_dir / "member_crosswalk.csv")
        cls.categories = read_csv(cls.output_dir / "category_crosswalk.csv")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "temp"):
            cls.temp.cleanup()

    def find_long(self, year, analyte, category):
        matches = [
            row
            for row in self.long_rows
            if row["year"] == year
            and row["analyte"] == analyte
            and canon(row["food_category"]) == canon(category)
        ]
        self.assertEqual(len(matches), 1, (year, analyte, category, matches))
        return matches[0]

    def test_eight_continuation_rows_are_recovered(self):
        expected = [
            ("2017", "铅", "1岁~10岁人群的产品", "0.15", "mg/kg", "固态产品计"),
            ("2022", "铅", "婴幼儿配方食品", "0.08", "mg/kg", "固态产品计"),
            ("2022", "铅", "10岁以上人群的产品", "0.5", "mg/kg", "固态产品计"),
            ("2022", "铅", "1岁~10岁人群的产品", "0.15", "mg/kg", "固态产品计"),
            ("2012", "镉", "包装饮用水(矿泉水除外)", "0.005", "mg/L", ""),
            ("2012", "镉", "矿泉水", "0.003", "mg/L", ""),
            (
                "2022",
                "镉",
                "包装饮用水(饮用天然矿泉水除外)",
                "0.005",
                "mg/L",
                "",
            ),
            ("2022", "镉", "饮用天然矿泉水", "0.003", "mg/L", ""),
        ]
        for year, analyte, category, value, unit, basis in expected:
            with self.subTest(year=year, analyte=analyte, category=category):
                row = self.find_long(year, analyte, category)
                self.assertEqual(float(row["limit_value"]), float(value))
                self.assertEqual(row["unit"], unit)
                self.assertEqual(row["basis"], basis)

    def test_split_nitrate_basis_is_attached_to_its_row(self):
        row = self.find_long(
            "2012", "硝酸盐", "较大婴儿和幼儿配方食品"
        )

        self.assertEqual(float(row["limit_value"]), 100.0)
        self.assertEqual(row["basis"], "粉状产品计")

    def test_basis_context_does_not_leak_from_the_next_row(self):
        row = self.find_long("2012", "铅", "豆浆")

        self.assertEqual(row["basis"], "")

    def test_five_known_bad_hosts_are_quarantined(self):
        bad_hosts = {
            "、稻谷糙米、大米",
            "、粉)、渣)、稻谷糙米、大米(玉米、玉米粉、玉米糁(小麦、小麦粉",
            "特殊医学用途配方食品(特殊医学用途婴儿配方食品涉及的",
        }
        bad_keys = {
            ("2017", "无机砷", "、稻谷糙米、大米"),
            (
                "2022",
                "总汞",
                "、粉)、渣)、稻谷糙米、大米(玉米、玉米粉、玉米糁(小麦、小麦粉",
            ),
            (
                "2025",
                "总汞",
                "、粉)、渣)、稻谷糙米、大米(玉米、玉米粉、玉米糁(小麦、小麦粉",
            ),
            (
                "2025",
                "亚硝酸盐",
                "特殊医学用途配方食品(特殊医学用途婴儿配方食品涉及的",
            ),
            (
                "2025",
                "硝酸盐",
                "特殊医学用途配方食品(特殊医学用途婴儿配方食品涉及的",
            ),
        }
        long_keys = {
            (row["year"], row["analyte"], row["food_category"])
            for row in self.long_rows
        }
        quarantine_keys = {
            (row["year"], row["analyte"], row["food_category"])
            for row in self.quarantine
        }

        self.assertTrue(bad_keys.isdisjoint(long_keys))
        self.assertTrue(bad_keys.issubset(quarantine_keys))
        self.assertFalse(
            any(row["food_category"] in bad_hosts for row in self.long_rows)
        )

    def test_quarantine_source_labels_are_portable(self):
        self.assertTrue(self.quarantine)
        self.assertTrue(
            all(
                not Path(row["source_path"]).is_absolute()
                for row in self.quarantine
            )
        )

    def test_member_basis_summary_has_no_empty_delimited_token(self):
        self.assertFalse(
            any(
                row["limit_basis"].startswith(";")
                or row["limit_basis"].endswith(";")
                or ";;" in row["limit_basis"]
                for row in self.members
            )
        )

    def test_correct_source_categories_replace_bad_hosts(self):
        expected = [
            ("2017", "无机砷", "稻谷、糙米、大米", "0.2"),
            (
                "2022",
                "总汞",
                "稻谷、糙米、大米(粉)、玉米、玉米粉、玉米糁(渣)、小麦、小麦粉",
                "0.02",
            ),
            (
                "2025",
                "总汞",
                "稻谷、糙米、大米(粉)、玉米、玉米粉、玉米糁(渣)、小麦、小麦粉",
                "0.02",
            ),
            (
                "2025",
                "亚硝酸盐",
                "特殊医学用途配方食品(特殊医学用途婴儿配方食品涉及的品种除外)",
                "2.0",
            ),
            (
                "2025",
                "硝酸盐",
                "特殊医学用途配方食品(特殊医学用途婴儿配方食品涉及的品种除外)",
                "100",
            ),
        ]
        for year, analyte, category, value in expected:
            with self.subTest(year=year, analyte=analyte, category=category):
                row = self.find_long(year, analyte, category)
                self.assertEqual(float(row["limit_value"]), float(value))

    def test_fifteen_bad_member_derivations_do_not_survive(self):
        bad_hosts = {
            "、稻谷糙米、大米",
            "、粉)、渣)、稻谷糙米、大米(玉米、玉米粉、玉米糁(小麦、小麦粉",
        }
        bad_host_members = {
            ("总汞", "大米(玉米"),
            ("总汞", "小麦粉"),
            ("总汞", "渣)"),
            ("总汞", "玉米粉"),
            ("总汞", "玉米糁(小麦"),
            ("总汞", "稻谷糙米"),
            ("总汞", "粉)"),
            (
                "总汞",
                "粉)、渣)、稻谷糙米、大米(玉米、玉米粉、玉米糁(小麦、小麦粉",
            ),
            ("无机砷", "大米"),
        }
        nested_residues = {
            ("总砷", "大米除外]"),
            ("铅", "水果制品[果酱"),
            ("铅", "水果干类除外]"),
            ("铅", "浓缩果蔬汁除外]"),
            ("铅", "香辛料类[花椒"),
            ("镉", "大米除外]"),
        }
        member_keys = {
            (row["analyte"], row["food_member"]): row for row in self.members
        }

        self.assertEqual(len(bad_host_members | nested_residues), 15)
        self.assertTrue(nested_residues.isdisjoint(member_keys))
        for key in bad_host_members:
            row = member_keys.get(key)
            if not row:
                continue
            hosts = {row[f"host_category_{year}"] for year in MODULE.YEARS}
            self.assertTrue(hosts.isdisjoint(bad_hosts), key)

    def test_mg_per_litre_remains_a_raw_unit(self):
        liquid_rows = [row for row in self.long_rows if row["unit"] == "mg/L"]

        self.assertGreater(len(liquid_rows), 0)
        self.assertNotIn("limit_mgkg", self.long_rows[0])
        for row in liquid_rows:
            self.assertEqual(row["unit"], "mg/L")

    def test_build_release_compatibility_files_have_expected_fields(self):
        long_compatible = read_csv(
            self.output_dir / "pollutant_limits_by_version.csv"
        )
        member_fields = set(self.compatible_members[0])
        category_fields = set(self.categories[0])

        self.assertEqual(len(long_compatible), len(self.long_rows))
        self.assertTrue(
            {
                "analyte",
                "member",
                "v2012",
                "v2017",
                "v2022",
                "v2025",
                "basis",
                "trend",
                "类别重组",
                "归属类别2012",
                "归属类别2017",
                "归属类别2022",
                "归属类别2025",
                "note",
            }.issubset(member_fields)
        )
        self.assertTrue(
            {
                "analyte",
                "canonical",
                "v2012",
                "v2017",
                "v2022",
                "v2025",
                "unit",
                "n_versions",
                "状态",
                "trend",
            }.issubset(category_fields)
        )

    def test_confirmed_relations_fix_misassigned_hosts(self):
        members = {
            (row["analyte"], row["food_member"]): row for row in self.members
        }

        def values(analyte, member):
            row = members[(analyte, member)]
            return [row[f"v{year}"] for year in MODULE.YEARS], row["trend"]

        stable = [
            ("铅", "白酒", "0.5"),
            ("铅", "八宝粥罐头", "0.5"),
            ("铅", "蔓越莓", "0.2"),
            ("铅", "醋栗", "0.2"),
            ("铅", "带馅(料)面米制品", "0.5"),
            ("铅", "多种香辛料混合的香辛料", "3.0"),
            ("镉", "肝脏制品", "0.5"),
            ("镉", "肾脏制品", "1.0"),
            ("镉", "大米", "0.2"),
        ]
        for analyte, member, value in stable:
            with self.subTest(analyte=analyte, member=member):
                observed, trend = values(analyte, member)
                self.assertEqual([float(item) for item in observed], [float(value)] * 4)
                self.assertEqual(trend, "stable")
        self.assertEqual(values("铅", "蒸馏酒")[0], ["0.5", "0.5", "", ""])
        self.assertIn("spans two printed rules", members[("铅", "蒸馏酒")]["note"])
        self.assertEqual(values("镉", "姬松茸")[0][:2], ["", ""])
        self.assertEqual(values("苯并[a]芘", "大米"), (["5.0", "5.0", "2.0", "2.0"], "tightened"))
        # Renamed categories merge into one row.
        self.assertNotIn(("镉", "矿泉水"), members)
        self.assertNotIn(("铅", "咖啡豆"), members)
        # Total arsenic leaves husked and milled rice to inorganic arsenic.
        for member in ("大米", "糙米", "大米(粉)"):
            self.assertNotIn(("总砷", member), members)

    def test_pending_aliases_are_excluded_and_reported(self):
        self.assertEqual(
            self.report["alias_adjudications"],
            {
                "confirmed_applied": 5,
                "pending_review_excluded": 5,
                "pending_review_sources": [
                    "麦片、面筋、粥类罐头、带馅面米制品",
                    "肉及肉制品",
                    "畜禽肝脏及其制品",
                    "畜禽肾脏及其制品",
                    "谷物碾磨加工品除外]",
                ],
            },
        )
        self.assertTrue(
            all(not Path(label).is_absolute() for label in self.report["inputs"])
        )
        self.assertTrue(
            all(not Path(label).is_absolute() for label in self.report["outputs"])
        )


if __name__ == "__main__":
    unittest.main()
