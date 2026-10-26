import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest


CLEAN = Path(__file__).resolve().parents[1]
PROJECT_ROOT = CLEAN.parents[1]
DEPENDENCIES = PROJECT_ROOT / "Data" / "Interim" / "release_dependencies"
sys.path.insert(0, str(CLEAN))


def load_script(module_name, filename):
    spec = importlib.util.spec_from_file_location(module_name, CLEAN / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


REPLAY = load_script(
    "replay_release_inputs", "260716_replay_release_inputs.py"
)
TAXONOMY = load_script(
    "rebuild_food_taxonomy", "260716_rebuild_food_taxonomy.py"
)


class FrozenDependencyTests(unittest.TestCase):
    def test_member_crosswalk_unit_conversion_is_dimension_safe(self):
        self.assertEqual(REPLAY.to_mg("1", "g/kg"), 1000.0)
        with self.assertRaisesRegex(
            REPLAY.ReplayError, "non-mass-per-mass unit"
        ):
            REPLAY.to_mg("1", "mg/L")

    def test_bundle_identity_and_manual_boundaries_are_locked(self):
        report = REPLAY.verify_bundle(DEPENDENCIES)

        self.assertEqual(len(report["files"]), 7)
        self.assertEqual(
            report["manual_boundaries"]["category_alias_confirmed"], 5
        )
        self.assertEqual(
            report["manual_boundaries"]["category_containment_confirmed"], 7
        )
        self.assertEqual(
            report["manual_boundaries"]["category_alias_pending_review"], 5
        )
        self.assertEqual(
            report["files"]["member_crosswalk_vetdrug.csv"]["rows"], 1157
        )

    def test_member_crosswalks_replay_byte_identically(self):
        with tempfile.TemporaryDirectory() as first_directory:
            with tempfile.TemporaryDirectory() as second_directory:
                first = REPLAY.rebuild_member_crosswalks(
                    input_dir=DEPENDENCIES,
                    mycotoxin_long=REPLAY.DEFAULT_MYCOTOXIN_LONG,
                    vetdrug_long=REPLAY.DEFAULT_VETDRUG_LONG,
                    output_dir=Path(first_directory),
                )
                second = REPLAY.rebuild_member_crosswalks(
                    input_dir=DEPENDENCIES,
                    mycotoxin_long=REPLAY.DEFAULT_MYCOTOXIN_LONG,
                    vetdrug_long=REPLAY.DEFAULT_VETDRUG_LONG,
                    output_dir=Path(second_directory),
                )

                self.assertEqual(first, second)
                for filename in (
                    "member_crosswalk_mycotoxin.csv",
                    "member_crosswalk_vetdrug.csv",
                ):
                    self.assertEqual(
                        (Path(first_directory) / filename).read_bytes(),
                        (DEPENDENCIES / filename).read_bytes(),
                    )

    def test_frozen_input_mutation_fails_before_use(self):
        with tempfile.TemporaryDirectory() as directory:
            mutated = Path(directory) / "category_alias.csv"
            mutated.write_bytes(
                (DEPENDENCIES / "category_alias.csv").read_bytes() + b"\n"
            )

            with self.assertRaisesRegex(REPLAY.ReplayError, "digest differs"):
                REPLAY.read_locked_csv(
                    mutated, REPLAY.INPUT_SPECS["category_alias.csv"]
                )

    def test_scripts_and_report_have_no_private_absolute_paths(self):
        for filename in (
            "260716_replay_release_inputs.py",
            "260716_rebuild_food_taxonomy.py",
        ):
            source = (CLEAN / filename).read_text()
            self.assertNotIn("/Volumes/", source)
            self.assertNotIn("/Users/", source)

        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "report.json"
            REPLAY.main(
                [
                    "verify",
                    "--input-dir",
                    str(DEPENDENCIES),
                    "--report",
                    str(report_path),
                ]
            )
            report = report_path.read_text()
            self.assertNotIn("/Volumes/", report)
            self.assertNotIn("/Users/", report)


class SourceReplayIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = os.environ.get("FOOD_STANDARD_POLLUTANT_SOURCE_DIR")
        if not source:
            raise unittest.SkipTest(
                "Set FOOD_STANDARD_POLLUTANT_SOURCE_DIR for source replay tests"
            )
        cls.source_dir = Path(source)

    def test_pollutant_legacy_replay_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "pollutant_old_path.csv"
            report = REPLAY.rebuild_pollutant_legacy(
                source_dir=self.source_dir,
                double_column_path=DEPENDENCIES / "pollutant_doublecol_long.csv",
                output_path=output,
            )

            self.assertEqual(report["rows"], 677)
            self.assertEqual(
                output.read_bytes(),
                (DEPENDENCIES / "pollutant_old_path.csv").read_bytes(),
            )

    def test_food_taxonomy_source_replay_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "food_taxonomy.csv"
            report = TAXONOMY.rebuild(
                source_dir=self.source_dir,
                known_categories_path=DEPENDENCIES / "pollutant_old_path.csv",
                output_path=output,
            )

            self.assertEqual(report["rows"], 798)
            self.assertFalse(report["unresolved_major_cells"])
            self.assertEqual(
                output.read_bytes(),
                (DEPENDENCIES / "food_taxonomy.csv").read_bytes(),
            )


if __name__ == "__main__":
    unittest.main()
