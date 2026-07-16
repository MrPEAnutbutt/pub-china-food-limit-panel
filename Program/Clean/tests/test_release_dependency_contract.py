import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


CLEAN = Path(__file__).resolve().parents[1]
PROJECT_ROOT = CLEAN.parents[1]
DEPENDENCIES = PROJECT_ROOT / "Data" / "Interim" / "release_dependencies"
SCRIPT = CLEAN / "release_dependency_utils.py"
SPEC = importlib.util.spec_from_file_location("release_dependency_utils", SCRIPT)
CONTRACT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = CONTRACT
SPEC.loader.exec_module(CONTRACT)


class ReleaseDependencyContractTests(unittest.TestCase):
    def test_complete_bundle_is_locked(self):
        loaded = CONTRACT.verify_release_dependencies(DEPENDENCIES)

        self.assertEqual(set(loaded), set(CONTRACT.RELEASE_DEPENDENCY_SPECS))
        self.assertEqual(len(loaded["food_taxonomy.csv"]), 798)

    def test_stale_pollutant_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            interim = Path(directory)
            outputs = {}
            for filename in CONTRACT.POLLUTANT_RELEASE_OUTPUTS:
                path = interim / filename
                path.write_text(filename + "\n", encoding="utf-8")
                outputs[filename] = CONTRACT.sha256_file(path)
            report = {
                "inputs": {
                    filename: CONTRACT.RELEASE_DEPENDENCY_SPECS[filename].sha256
                    for filename in CONTRACT.POLLUTANT_REBUILD_DEPENDENCIES
                },
                "outputs": outputs,
                "alias_adjudications": CONTRACT.REVIEWED_ALIAS_AUDIT,
            }
            (interim / "pollutant_rebuild_report.json").write_text(
                json.dumps(report, ensure_ascii=False), encoding="utf-8"
            )
            CONTRACT.verify_pollutant_rebuild_report(interim, DEPENDENCIES)

            (interim / CONTRACT.POLLUTANT_RELEASE_OUTPUTS[0]).write_text(
                "mutated\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(
                CONTRACT.DependencyContractError, "differs from its report"
            ):
                CONTRACT.verify_pollutant_rebuild_report(interim, DEPENDENCIES)


if __name__ == "__main__":
    unittest.main()
