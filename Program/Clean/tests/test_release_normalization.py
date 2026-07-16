import importlib.util
import copy
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


CLEAN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLEAN_DIR))
SCRIPT = CLEAN_DIR / "260714_build_release.py"
SPEC = importlib.util.spec_from_file_location("build_release", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ReleaseNormalizationTests(unittest.TestCase):
    def test_dependency_digest_failure_precedes_release_directory_creation(self):
        global_names = (
            "ADD_INTERIM",
            "DATE_DIR",
            "DEPENDENCY_INTERIM",
            "MYCOTOXIN_INTERIM",
            "PESTICIDE_INTERIM",
            "POLLUTANT_INTERIM",
            "REL",
            "TIMELINE",
            "VETDRUG_INTERIM",
        )
        original_globals = {name: getattr(MODULE, name) for name in global_names}
        try:
            with tempfile.TemporaryDirectory() as directory:
                directory = Path(directory)
                dependencies = directory / "dependencies"
                dependencies.mkdir()
                for filename in MODULE.verify_release_dependencies(
                    MODULE.DEPENDENCY_INTERIM
                ):
                    shutil.copyfile(
                        Path(MODULE.DEPENDENCY_INTERIM) / filename,
                        dependencies / filename,
                    )
                alias = dependencies / "category_alias.csv"
                alias.write_bytes(alias.read_bytes() + b"\n")
                release = directory / "release"

                with self.assertRaisesRegex(ValueError, "digest differs"):
                    MODULE.main(
                        [
                            "--dependency-interim",
                            str(dependencies),
                            "--release-dir",
                            str(release),
                        ]
                    )

                self.assertFalse(release.exists())
        finally:
            for name, value in original_globals.items():
                setattr(MODULE, name, value)

    def test_mg_per_kg_is_retained(self):
        self.assertEqual(
            MODULE.normalize_mass_per_mass("2", "mg/kg"),
            (2.0, "already_mg_per_kg"),
        )

    def test_micrograms_per_kg_are_converted(self):
        self.assertEqual(
            MODULE.normalize_mass_per_mass("100", "μg/kg"),
            (0.1, "converted_mass_per_mass"),
        )

    def test_grams_per_kg_are_converted(self):
        self.assertEqual(
            MODULE.normalize_mass_per_mass("0.2", "g/kg"),
            (200.0, "converted_mass_per_mass"),
        )

    def test_mg_per_litre_requires_density(self):
        self.assertEqual(
            MODULE.normalize_mass_per_mass("0.005", "mg/L"),
            ("", "density_required"),
        )

    def test_unknown_unit_stops_the_build(self):
        with self.assertRaisesRegex(ValueError, "unsupported limit unit"):
            MODULE.normalize_mass_per_mass("1", "ppm")

    def test_missing_unit_stops_the_build(self):
        with self.assertRaisesRegex(ValueError, "missing unit"):
            MODULE.normalize_mass_per_mass("1", "")

    def test_source_lineage_drops_private_absolute_prefix(self):
        self.assertEqual(
            MODULE.portable_source_label(
                "/Volumes/private/source/pollutant_old_path.csv"
            ),
            "pollutant_old_path.csv",
        )

    def test_release_builder_defaults_to_project_interim_inputs(self):
        args = MODULE.parse_args([])

        expected = MODULE.PROJECT_ROOT
        self.assertEqual(
            Path(args.pesticide_interim),
            Path(expected) / "Data/Interim/pesticide_textlayer_scans",
        )
        self.assertEqual(
            Path(args.mycotoxin_interim),
            Path(expected) / "Data/Interim/mycotoxin_rebuild",
        )
        self.assertEqual(
            Path(args.vetdrug_interim),
            Path(expected) / "Data/Interim/vetdrug_rebuild",
        )
        self.assertEqual(
            Path(args.dependency_interim),
            Path(expected) / "Data/Interim/release_dependencies",
        )
        self.assertEqual(
            Path(args.date_dir),
            Path(expected) / "Data/Interim/standard_timeline",
        )

    def test_rule_preserving_ids_keep_distinct_same_key_rows(self):
        rows = [
            {
                "year": "2021",
                "pesticide": "甲",
                "food": "苹果",
                "value": "1",
                "qualifier": "",
            },
            {
                "year": "2021",
                "pesticide": "甲",
                "food": "苹果",
                "value": "0.5",
                "qualifier": "仅限鲜果",
            },
        ]

        output, removed, conflicts = MODULE.preserve_rules_and_id(
            rows,
            ["year", "pesticide", "food"],
            ["year", "pesticide", "food", "value", "qualifier"],
            "PES",
        )

        self.assertEqual(len(output), 2)
        self.assertEqual(removed, 0)
        self.assertEqual(conflicts, 2)
        self.assertEqual({row["conflict"] for row in output}, {"1"})
        self.assertEqual(len({row["record_id"] for row in output}), 2)
        self.assertTrue(all(row["record_id"].startswith("PES") for row in output))

    def test_generic_release_ids_are_input_order_invariant(self):
        rows = [
            {"year": "2021", "entity": "甲", "value": "1"},
            {"year": "2019", "entity": "甲", "value": "2"},
        ]

        first, removed, _ = MODULE.dedup_and_id(
            [dict(row) for row in rows], ["year", "entity"], "GEN"
        )
        second, _, _ = MODULE.dedup_and_id(
            [dict(row) for row in reversed(rows)], ["year", "entity"], "GEN"
        )

        self.assertEqual(removed, 0)
        self.assertEqual(
            {row["value"]: row["record_id"] for row in first},
            {row["value"]: row["record_id"] for row in second},
        )

    def test_generic_release_rows_reject_exact_duplicates(self):
        row = {"year": "2021", "entity": "甲", "value": "1"}

        with self.assertRaisesRegex(ValueError, "duplicate release row"):
            MODULE.dedup_and_id(
                [dict(row), dict(row)], ["year", "entity"], "GEN"
            )

    def test_rule_preserving_ids_reject_semantic_duplicates(self):
        rows = [
            {"year": "2021", "pesticide": "甲", "food": "苹果", "value": "1"},
            {"year": "2021", "pesticide": "甲", "food": "苹果", "value": "1"},
        ]

        with self.assertRaisesRegex(ValueError, "duplicate semantic rule"):
            MODULE.preserve_rules_and_id(
                rows,
                ["year", "pesticide", "food"],
                ["year", "pesticide", "food", "value"],
                "PES",
            )

    def test_rule_identifiers_are_input_order_invariant(self):
        rows = [
            {"year": "2021", "pesticide": "甲", "food": "苹果", "value": "1"},
            {"year": "2019", "pesticide": "甲", "food": "苹果", "value": "2"},
        ]
        reversed_rows = [dict(row) for row in reversed(rows)]

        first, _, _ = MODULE.preserve_rules_and_id(
            [dict(row) for row in rows],
            ["year", "pesticide", "food"],
            ["year", "pesticide", "food", "value"],
            "PES",
        )
        second, _, _ = MODULE.preserve_rules_and_id(
            reversed_rows,
            ["year", "pesticide", "food"],
            ["year", "pesticide", "food", "value"],
            "PES",
        )

        by_value_first = {row["value"]: row["record_id"] for row in first}
        by_value_second = {row["value"]: row["record_id"] for row in second}
        self.assertEqual(by_value_first, by_value_second)

    def test_vetdrug_locators_follow_canonicalized_release_rows(self):
        release = [
            {
                "year": "2002",
                "drug": "药物甲",
                "english": "drug a",
                "animal_raw": "猪",
                "tissue": "皮+脂",
                "limit_value": "50",
            }
        ]
        replay = [
            {
                **release[0],
                "tissue": "皮+脂肪",
            }
        ]
        locators = [
            {
                "output_row": "1",
                "drug": "药物甲",
                "english": "drug a",
                "animal_raw": "猪",
                "tissue": "皮+脂肪",
                "limit_value": "50",
                "source_table_index": "1",
                "source_table_row": "2",
            }
        ]

        queues = MODULE.vetdrug_2002_locator_queues(release, replay, locators)

        key = ("药物甲", "drug a", "猪", "皮+脂", "50")
        self.assertEqual(queues[key][0]["source_table_row"], "2")

    def test_vetdrug_locator_order_mismatch_fails(self):
        release = [
            {
                "year": "2002",
                "drug": "药物甲",
                "english": "drug a",
                "animal_raw": "猪",
                "tissue": "肌肉",
                "limit_value": "50",
            }
        ]
        replay = [dict(release[0])]
        locator = [{**release[0], "output_row": "2"}]

        with self.assertRaisesRegex(ValueError, "non-sequential"):
            MODULE.vetdrug_2002_locator_queues(release, replay, locator)

    def test_analyte_lookup_uses_only_released_bilingual_pairs(self):
        pollutant_rows = [
            {
                "analyte_zh": "3-氯-1,2-丙二醇",
                "analyte_en": "3-chloro-1,2-propanediol",
            }
        ]

        entities = MODULE.build_analyte_lookup_entities(pollutant_rows, [])

        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]["name_zh"], "3-氯-1,2-丙二醇")
        self.assertEqual(
            entities[0]["entity_key"],
            MODULE.lookup_entity_key("ANL", "3-chloro-1,2-propanediol"),
        )

    def test_analyte_lookup_rejects_one_english_identity_with_two_chinese_names(self):
        pollutant_rows = [
            {"analyte_zh": "指标甲", "analyte_en": "Test analyte"},
            {"analyte_zh": "指标乙", "analyte_en": "test analyte"},
        ]

        with self.assertRaisesRegex(ValueError, "bilingual identity collision"):
            MODULE.build_analyte_lookup_entities(pollutant_rows, [])

    def test_vetdrug_summary_panel_ignores_2022_only_groups_without_mutating_long(self):
        long_rows = [
            {
                "record_id": "VET-2002",
                "version_year": "2002",
                "drug_zh": "药物甲",
                "drug_en": "Drug-A",
                "tissue_zh": "肌肉",
                "limit_value": "100",
            },
            {
                "record_id": "VET-2019",
                "version_year": "2019",
                "drug_zh": "药物甲",
                "drug_en": "Drug A",
                "tissue_zh": "肌肉",
                "limit_value": "50",
            },
            {
                "record_id": "VET-2022",
                "version_year": "2022",
                "drug_zh": "药物乙",
                "drug_en": "Drug B",
                "tissue_zh": "蛋",
                "limit_value": "10",
            },
        ]
        original = copy.deepcopy(long_rows)

        panel = MODULE.build_vetdrug_summary_panel(long_rows)

        self.assertEqual(long_rows, original)
        self.assertEqual(
            panel,
            [
                {
                    "standard": "GB 31650",
                    "drug_zh": "药物甲",
                    "drug_en": "druga",
                    "tissue_zh": "肌肉",
                    "v2002": "100",
                    "v2019": "50",
                    "unit": "μg/kg",
                    "trend": "tightened",
                }
            ],
        )
        self.assertEqual(
            [row["record_id"] for row in long_rows if row["version_year"] == "2022"],
            ["VET-2022"],
        )

    def test_vetdrug_summary_panel_rejects_non_numeric_limits(self):
        long_rows = [
            {
                "record_id": "VET-bad",
                "version_year": "2019",
                "drug_zh": "药物甲",
                "drug_en": "Drug A",
                "tissue_zh": "肌肉",
                "limit_value": "pending",
            }
        ]

        with self.assertRaisesRegex(ValueError, "non-numeric veterinary-drug limit"):
            MODULE.build_vetdrug_summary_panel(long_rows)


if __name__ == "__main__":
    unittest.main()
