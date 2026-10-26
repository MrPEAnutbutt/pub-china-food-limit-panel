"""Row-level source references and extraction methods added in revision A5."""

import importlib.util
import sys
import unittest
from pathlib import Path


CLEAN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLEAN_DIR))
SCRIPT = CLEAN_DIR / "260714_build_release.py"
SPEC = importlib.util.spec_from_file_location("build_release_sources", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def vet(record_id, year, source, extraction_source_id, **extra):
    return {"record_id": record_id, "standard": "GB 31650", "version_year": year,
            "source": source, "extraction_source_id": extraction_source_id, **extra}


class SourceColumnsTest(unittest.TestCase):
    def test_mixed_vetdrug_edition_splits_methods_by_row(self):
        rows = [vet("V1", "2019", "text", "SRC0016"), vet("V2", "2019", "manual", "SRC0016")]
        MODULE.add_source_columns(
            rows, row_method=lambda row, mode: MODULE.VETDRUG_ROW_METHODS[row["source"]])
        self.assertEqual([row["extraction_method"] for row in rows],
                         ["pdf_text_layer", "manual_page_image_transcription"])

    def test_file_mode_without_row_split_is_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.add_source_columns([vet("V1", "2019", "text", "SRC0016")])

    def test_direct_file_link_only_for_byte_exact_copies(self):
        rows = [
            {"record_id": "P1", "standard": "GB 2763", "version_year": "2019",
             "extraction_source_id": "SRC0024", "edition_source_id": "SRC0009",
             "source_page": "21"},
            vet("V1", "2019", "text", "SRC0016"),
        ]
        MODULE.add_source_columns(rows[:1], locate=lambda row: f"PDF p. {row['source_page']}")
        MODULE.add_source_columns(
            rows[1:], row_method=lambda row, mode: MODULE.VETDRUG_ROW_METHODS[row["source"]])
        self.assertTrue(rows[0]["source_reference"].startswith("GB 2763-2019; PDF p. 21; "))
        self.assertTrue(rows[0]["source_reference"].endswith(".pdf"))
        self.assertTrue(rows[1]["source_reference"].endswith(".html"))

    def test_manual_locators_require_each_row_to_match_its_seed(self):
        tasks = [{"construction_seed_row": "2", "pdf_page": "4", "printed_table": "3",
                  "printed_row": "1"},
                 {"construction_seed_row": "1", "pdf_page": "3", "printed_table": "1",
                  "printed_row": "1"}]
        released = [{"record_id": "M1", "toxin_zh": "A"}, {"record_id": "M2", "toxin_zh": "B"}]
        fields = (("toxin_zh", "toxin"),)
        located = MODULE.manual_row_locators(tasks, released, [{"toxin": "A"}, {"toxin": "B"}], fields)
        self.assertEqual(located, {"M1": "PDF p. 3, table 1, row 1", "M2": "PDF p. 4, table 3, row 1"})
        with self.assertRaises(ValueError):
            MODULE.manual_row_locators(tasks, released, [{"toxin": "B"}, {"toxin": "A"}], fields)

    def test_method_summary_counts_every_record_once(self):
        rows = [{"standard": "S", "version_year": "2020", "extraction_method": method}
                for method in ("pdf_text_layer", "pdf_text_layer", "word_table_stream")]
        summary = MODULE.extraction_method_summary((("f1", rows[:2]), ("f2", rows[2:])))
        self.assertEqual([(row["family"], row["records"], row["share_of_family_pct"],
                           row["share_of_release_pct"]) for row in summary],
                         [("f1", "2", "100.00", "66.67"), ("f2", "1", "100.00", "33.33")])


if __name__ == "__main__":
    unittest.main()
