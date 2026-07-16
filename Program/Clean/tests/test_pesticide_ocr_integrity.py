import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


PROGRAM = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "pesticide_ocr_integrity", PROGRAM / "pesticide_ocr_integrity.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def write_tsv(path: Path, pages: tuple[int, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(MODULE.TSV_COLUMNS)
        for page in pages:
            writer.writerow([page, f"word-{page}", 1, 2, 3, 4, 90, "0.000"])


def write_manifest(path: Path, tsv: Path, pages: int) -> None:
    metadata = MODULE.inspect_tsv(tsv, expected_pages=pages)
    path.write_text(
        json.dumps(
            {
                "schema_version": MODULE.MANIFEST_SCHEMA_VERSION,
                "editions": {
                    "2021": {
                        "source_pdf": {
                            "filename": "GB 2763-2021.pdf",
                            "file_size_bytes": 1,
                            "sha256": "0" * 64,
                            "page_count": pages,
                        },
                        "ocr_tsv": metadata,
                    }
                },
            }
        ),
        encoding="utf-8",
    )


class PesticideOCRIntegrityTests(unittest.TestCase):
    def test_complete_tsv_and_matching_manifest_pass(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tsv = root / "ocr_words_2021.tsv"
            manifest = root / MODULE.MANIFEST_NAME
            write_tsv(tsv, (1, 2, 3))
            write_manifest(manifest, tsv, 3)

            verified = MODULE.verify_completion_manifest(manifest)

            self.assertEqual(verified["editions"]["2021"]["ocr_tsv"]["word_count"], 3)

    def test_truncated_page_set_hard_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tsv = Path(temp_dir) / "ocr_words_2021.tsv"
            write_tsv(tsv, (1, 2))

            with self.assertRaisesRegex(MODULE.OCRIntegrityError, "missing pages"):
                MODULE.inspect_tsv(tsv, expected_pages=3)

    def test_changed_tsv_hard_fails_manifest_digest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tsv = root / "ocr_words_2021.tsv"
            manifest = root / MODULE.MANIFEST_NAME
            write_tsv(tsv, (1, 2, 3))
            write_manifest(manifest, tsv, 3)
            with tsv.open("a", encoding="utf-8", newline="") as stream:
                csv.writer(stream, delimiter="\t").writerow(
                    [3, "changed", 1, 2, 3, 4, 90, "0.000"]
                )

            with self.assertRaisesRegex(MODULE.OCRIntegrityError, "differs"):
                MODULE.verify_completion_manifest(manifest)

    def test_non_monotonic_pages_hard_fail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tsv = Path(temp_dir) / "ocr_words_2021.tsv"
            write_tsv(tsv, (1, 3, 2))

            with self.assertRaisesRegex(MODULE.OCRIntegrityError, "non-monotonic"):
                MODULE.inspect_tsv(tsv)


if __name__ == "__main__":
    unittest.main()
