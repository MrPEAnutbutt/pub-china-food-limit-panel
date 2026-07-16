import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


CLEAN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLEAN_DIR))
SCRIPT = CLEAN_DIR / "260715_rebuild_additive_release.py"
SPEC = importlib.util.spec_from_file_location("rebuild_additive_release", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def write_csv(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class AdditiveReleaseRebuildTests(unittest.TestCase):
    def test_targeted_rebuild_updates_only_declared_release_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            additive = root / "additive"
            pollutant = root / "pollutant"
            release = root / "release"
            write_csv(
                additive / "additive_raw_long.csv",
                ("year", "additive", "cns", "ins", "food_code", "food", "max_use", "unit", "note"),
                [
                    {
                        "year": "2011",
                        "additive": "测试剂",
                        "cns": "01.001",
                        "ins": "100",
                        "food_code": "01.0",
                        "food": "食品甲",
                        "max_use": "1.0",
                        "unit": "g/kg",
                        "note": "",
                    },
                    {
                        "year": "2014",
                        "additive": "测试剂",
                        "cns": "01.001",
                        "ins": "100",
                        "food_code": "01.0",
                        "food": "食品甲",
                        "max_use": "0.5",
                        "unit": "g/kg",
                        "note": "",
                    },
                ],
            )
            write_csv(
                additive / "additive_quarantine.csv",
                ("year", "additive", "cns", "food_code", "food", "max_use", "unit", "reject", "raw_chunk"),
                [
                    {
                        "year": "2011",
                        "additive": "待核剂",
                        "cns": "",
                        "food_code": "02.0",
                        "food": "食品乙",
                        "max_use": "GMP",
                        "unit": "",
                        "reject": "CNS号缺失或格式异常",
                        "raw_chunk": "source fragment",
                    }
                ],
            )
            write_csv(
                pollutant / "pollutant_quarantine.csv",
                ("source_path", "year", "analyte", "food_category", "limit_value", "unit", "reason"),
                [
                    {
                        "source_path": "/private/input.csv",
                        "year": "2022",
                        "analyte": "铅",
                        "food_category": "食品丙",
                        "limit_value": "0.1",
                        "unit": "mg/kg",
                        "reason": "test",
                    }
                ],
            )
            release.mkdir()
            (release / "_build_stats.json").write_text(
                json.dumps({"pesticide_limits": {"rows": 7}}), encoding="utf-8"
            )
            untouched = release / "pesticide_limits_long.csv"
            untouched.write_text("sentinel\n", encoding="utf-8")

            stats = MODULE.rebuild(additive, pollutant, release)

            self.assertEqual(untouched.read_text(encoding="utf-8"), "sentinel\n")
            self.assertEqual(stats["additive_limits"]["rows"], 2)
            self.assertEqual(stats["additive_panel"]["rows"], 1)
            self.assertEqual(stats["quarantined_rows"]["rows"], 2)
            long_rows = read_csv(release / "additive_limits_long.csv")
            self.assertEqual([row["record_id"] for row in long_rows], ["ADD00001", "ADD00002"])
            panel = read_csv(release / "additive_panel.csv")[0]
            self.assertEqual(panel["trend"], "tightened")
            quarantine = read_csv(release / "quarantined_rows.csv")
            self.assertEqual(quarantine[1]["source_path"], "input.csv")
            build_stats = json.loads((release / "_build_stats.json").read_text(encoding="utf-8"))
            self.assertEqual(build_stats["pesticide_limits"], {"rows": 7})


if __name__ == "__main__":
    unittest.main()
