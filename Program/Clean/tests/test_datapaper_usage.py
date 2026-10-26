import importlib.util
import json
import unittest
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[2] / "Analysis" / "DatapaperUsage.py"
SPEC = importlib.util.spec_from_file_location("datapaper_usage", SCRIPT)
USAGE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(USAGE)


def member(record_id, trend, v2017, unit_2017, v2022, unit_2022, host_2017="H", host_2022="H"):
    return {"record_id": record_id, "trend": trend,
            "v2017": v2017, "unit_2017": unit_2017, "host_category_2017": host_2017,
            "v2022": v2022, "unit_2022": unit_2022, "host_category_2022": host_2022,
            "source_record_ids_2017": json.dumps([f"{record_id}-17"] if v2017 else []),
            "source_record_ids_2022": json.dumps([f"{record_id}-22"] if v2022 else [])}


class PairCountTest(unittest.TestCase):
    def test_units_are_converted_and_incomparable_rows_are_not_compared(self):
        panel = pd.DataFrame([
            member("M1", "tightened", "0.5", "mg/kg", "20", "μg/kg"),
            member("M2", "relaxed", "0.2", "mg/kg", "0.35", "mg/kg", "A", "B"),
            member("M3", "stable", "0.003", "mg/L", "0.003", "mg/L"),
            member("M4", "incomparable_basis_unit_or_value", "0.5", "mg/L", "0.5", "mg/kg"),
            member("M5", "stable", "", "", "0.1", "mg/kg"),
        ])
        self.assertEqual(USAGE.pair_counts(panel, "2017", "2022"), {
            "both": 4, "incomparable": 1, "tightened": 1, "relaxed": 1, "unchanged": 1,
            "host changed": 1})


class LinkCellsTest(unittest.TestCase):
    def tables(self):
        panel = pd.DataFrame([member("M1", "stable", "0.1", "mg/kg", "0.1", "mg/kg")])
        long = pd.DataFrame([{"record_id": f"M1-{y}", "extraction_source_id": f"S{y}",
                              "limit_value": "0.1"} for y in ("17", "22")])
        manifest = pd.DataFrame([{"source_id": f"S{y}", "source_filename": f"f{y}.pdf",
                                  "sha256": y} for y in ("17", "22")])
        return panel, long, manifest

    def test_each_cell_reaches_its_record_and_source_file(self):
        cells = USAGE.link_cells(*self.tables())
        self.assertEqual(sorted(cells["source_filename"]), ["f17.pdf", "f22.pdf"])
        self.assertEqual(sorted(cells["edition"]), ["2017", "2022"])

    def test_an_unresolved_lineage_identifier_fails(self):
        panel, long, manifest = self.tables()
        with self.assertRaises(AssertionError):
            USAGE.link_cells(panel, long.iloc[:1], manifest)


if __name__ == "__main__":
    unittest.main()
