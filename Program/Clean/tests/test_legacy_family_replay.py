import csv
from contextlib import redirect_stderr
import io
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from collections import Counter


CLEAN = Path(__file__).resolve().parents[1]
PROJECT_ROOT = CLEAN.parents[1]
sys.path.insert(0, str(CLEAN))

from legacy_family_replay import (  # noqa: E402
    CSVSpec,
    load_locked_csv,
    read_manifest,
    ReplayError,
    sha256_file,
    validate_source_acquisition,
    verify_manifest_source,
    write_csv_atomic,
)


def load_script(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, CLEAN / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


MYCOTOXIN = load_script("rebuild_mycotoxin", "260716_rebuild_mycotoxin.py")
VETDRUG = load_script("rebuild_vetdrug", "260716_rebuild_vetdrug.py")
VETDRUG_2002 = load_script(
    "rebuild_vetdrug_2002", "260716_rebuild_vetdrug_2002.py"
)
MYCO_DIR = PROJECT_ROOT / "Data" / "Interim" / "mycotoxin_rebuild"
VET_DIR = PROJECT_ROOT / "Data" / "Interim" / "vetdrug_rebuild"
MANIFEST_FIELDS = (
    "source_id",
    "family",
    "standard",
    "version_year",
    "source_role",
    "release_status",
    "released_limit_rows",
    "source_filename",
    "source_format",
    "file_size_bytes",
    "sha256",
    "extraction_mode",
    "document_identity",
    "notes",
)
ACQUISITION_FIELDS = (
    "family",
    "version_year",
    "source_filename",
    "sha256",
    "official_landing_url",
    "official_download_url",
    "url_verified_date",
    "original_retrieval_date",
    "byte_identity_status",
    "access_notes",
)


def write_fixture_csv(path: Path, fields: tuple[str, ...], rows: list[tuple[str, ...]]):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(fields)
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def manifest_row(**overrides: str) -> dict[str, str]:
    row = {
        "source_id": "SRC0014",
        "family": "mycotoxin",
        "standard": "GB 2761",
        "version_year": "2017",
        "source_role": "edition_source",
        "release_status": "extracted",
        "released_limit_rows": "30",
        "source_filename": "source.pdf",
        "source_format": "pdf",
        "file_size_bytes": "12",
        "sha256": "0" * 64,
        "extraction_mode": "pdf_text_layer",
        "document_identity": "full_standard",
        "notes": "",
    }
    row.update(overrides)
    return row


def write_manifest(
    path: Path,
    rows: list[dict[str, str]],
    fields: tuple[str, ...] = MANIFEST_FIELDS,
) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class LockedCSVTests(unittest.TestCase):
    def test_missing_seed_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.csv"
            with self.assertRaisesRegex(ReplayError, "required frozen CSV is missing"):
                load_locked_csv(missing, MYCOTOXIN.MANUAL_2005_SPEC)

    def test_wrong_seed_hash_fails_before_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "seed.csv"
            write_fixture_csv(path, ("id", "value"), [("A", "1")])
            spec = CSVSpec(
                fields=("id", "value"),
                rows=1,
                unique_key=("id",),
                sha256="0" * 64,
            )
            with self.assertRaisesRegex(ReplayError, "digest differs"):
                load_locked_csv(path, spec)

    def test_schema_row_count_and_unique_key_are_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            schema_path = root / "schema.csv"
            write_fixture_csv(schema_path, ("wrong", "value"), [("A", "1")])
            schema_spec = CSVSpec(
                fields=("id", "value"),
                rows=1,
                unique_key=("id",),
                sha256=sha256_file(schema_path),
            )
            with self.assertRaisesRegex(ReplayError, "unexpected CSV schema"):
                load_locked_csv(schema_path, schema_spec)

            count_path = root / "count.csv"
            write_fixture_csv(count_path, ("id", "value"), [("A", "1")])
            count_spec = CSVSpec(
                fields=("id", "value"),
                rows=2,
                unique_key=("id",),
                sha256=sha256_file(count_path),
            )
            with self.assertRaisesRegex(ReplayError, "unexpected row count"):
                load_locked_csv(count_path, count_spec)

            duplicate_path = root / "duplicate.csv"
            write_fixture_csv(
                duplicate_path,
                ("id", "value"),
                [("A", "1"), ("A", "2")],
            )
            duplicate_spec = CSVSpec(
                fields=("id", "value"),
                rows=2,
                unique_key=("id",),
                sha256=sha256_file(duplicate_path),
            )
            with self.assertRaisesRegex(ReplayError, "duplicate business key"):
                load_locked_csv(duplicate_path, duplicate_spec)


class SourceIdentityTests(unittest.TestCase):
    def test_rebuild_clis_require_explicit_sources_and_have_no_private_paths(self):
        modules = (
            (MYCOTOXIN, "260716_rebuild_mycotoxin.py"),
            (VETDRUG, "260716_rebuild_vetdrug.py"),
            (VETDRUG_2002, "260716_rebuild_vetdrug_2002.py"),
        )
        for module, filename in modules:
            with self.subTest(filename=filename):
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        module.parse_args([])
                source = (CLEAN / filename).read_text()
                self.assertNotIn("/Volumes/", source)
                self.assertNotIn("/Users/", source)

    def test_wrong_source_hash_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pdf"
            source.write_bytes(b"source bytes")
            manifest_row = {
                "source_id": "SRC1",
                "family": "mycotoxin",
                "standard": "GB 2761",
                "version_year": "2017",
                "source_role": "edition_source",
                "release_status": "extracted",
                "released_limit_rows": "30",
                "source_filename": source.name,
                "source_format": "pdf",
                "file_size_bytes": str(source.stat().st_size),
                "sha256": "f" * 64,
                "extraction_mode": "pdf_text_layer",
                "document_identity": "full_standard",
                "notes": "",
            }
            self.assertEqual(tuple(manifest_row), MANIFEST_FIELDS)
            with self.assertRaisesRegex(ReplayError, "source digest differs"):
                verify_manifest_source(
                    source,
                    [manifest_row],
                    family="mycotoxin",
                    version_year="2017",
                )

    def test_manifest_reader_rejects_duplicate_rows_filenames_and_bad_sizes(self):
        cases = {
            "duplicate source-manifest row": [manifest_row(), manifest_row()],
            "duplicate source_id": [
                manifest_row(),
                manifest_row(source_filename="other.pdf"),
            ],
            "duplicate source_filename": [
                manifest_row(),
                manifest_row(source_id="SRC9999"),
            ],
            "source_filename is not a basename": [
                manifest_row(source_filename="nested/source.pdf")
            ],
            "file_size_bytes must be positive": [manifest_row(file_size_bytes="0")],
        }
        for message, rows in cases.items():
            with self.subTest(message=message):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "source_manifest.csv"
                    write_manifest(path, rows)
                    with self.assertRaisesRegex(ReplayError, message):
                        read_manifest(path)

    def test_manifest_reader_accepts_relationship_and_future_columns(self):
        extra_fields = (
            "related_source_id",
            "acquisition_landing_url",
            "acquisition_file_url",
            "retrieved_date",
            "page_count",
            "future_optional_field",
        )
        anchor = {
            **manifest_row(),
            **dict.fromkeys(extra_fields, ""),
        }
        extraction_copy = {
            **manifest_row(
                source_id="SRC0025",
                source_role="extraction_copy",
                source_filename="extraction.pdf",
            ),
            **dict.fromkeys(extra_fields, ""),
            "related_source_id": "SRC0014",
            "acquisition_landing_url": "https://example.gov.cn/landing",
            "acquisition_file_url": "https://example.gov.cn/source.pdf",
            "page_count": "10",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source_manifest.csv"
            write_manifest(
                path,
                [anchor, extraction_copy],
                MANIFEST_FIELDS + extra_fields,
            )

            rows = read_manifest(path)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["related_source_id"], "SRC0014")
        self.assertIn("future_optional_field", rows[1])

    def test_manifest_reader_accepts_identity_anchor_crosscheck_status(self):
        row = manifest_row(
            source_id="SRC0009",
            release_status="identity_anchor_crosscheck",
            released_limit_rows="",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source_manifest.csv"
            write_manifest(path, [row])

            rows = read_manifest(path)

        self.assertEqual(rows[0]["release_status"], "identity_anchor_crosscheck")

    def test_manifest_reader_still_requires_every_core_field(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source_manifest.csv"
            fields = tuple(field for field in MANIFEST_FIELDS if field != "sha256")
            row = manifest_row()
            write_manifest(path, [{field: row[field] for field in fields}], fields)

            with self.assertRaisesRegex(
                ReplayError, "unexpected source-manifest schema"
            ):
                read_manifest(path)

    def test_legacy_edition_semantics_are_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pdf"
            source.write_bytes(b"source bytes")
            base = manifest_row(
                file_size_bytes=str(source.stat().st_size),
                sha256=sha256_file(source),
            )
            cases = {
                "standard": {"standard": "GB 9999"},
                "source_format": {"source_format": "doc"},
                "release_status": {"release_status": "archived_unextracted"},
                "document_identity": {"document_identity": "official_announcement"},
                "released_limit_rows": {"released_limit_rows": "29"},
            }
            for field, changes in cases.items():
                with self.subTest(field=field):
                    row = {**base, **changes}
                    with self.assertRaisesRegex(ReplayError, field):
                        verify_manifest_source(
                            source,
                            [row],
                            family="mycotoxin",
                            version_year="2017",
                        )


class AcquisitionMetadataTests(unittest.TestCase):
    def test_frozen_acquisition_tables_have_locked_identity_and_semantics(self):
        for path, spec in (
            (
                MYCO_DIR / "source_acquisition.csv",
                MYCOTOXIN.SOURCE_ACQUISITION_SPEC,
            ),
            (
                VET_DIR / "source_acquisition.csv",
                VETDRUG.SOURCE_ACQUISITION_SPEC,
            ),
        ):
            with self.subTest(path=path):
                rows = load_locked_csv(path, spec)
                self.assertEqual(tuple(rows[0]), ACQUISITION_FIELDS)
                source_metadata = [
                    {
                        "family": row["family"],
                        "version_year": row["version_year"],
                        "filename": row["source_filename"],
                        "sha256": row["sha256"],
                    }
                    for row in rows
                ]
                validate_source_acquisition(rows, source_metadata)

    def test_acquisition_metadata_rejects_hash_and_nonofficial_url_drift(self):
        rows = read_csv(MYCO_DIR / "source_acquisition.csv")
        source_metadata = [
            {
                "family": row["family"],
                "version_year": row["version_year"],
                "filename": row["source_filename"],
                "sha256": row["sha256"],
            }
            for row in rows
        ]
        hash_drift = [{**row} for row in rows]
        hash_drift[0]["sha256"] = "f" * 64
        with self.assertRaisesRegex(ReplayError, "acquisition sha256"):
            validate_source_acquisition(hash_drift, source_metadata)

        url_drift = [{**row} for row in rows]
        url_drift[1]["official_landing_url"] = "https://example.com/not-official"
        with self.assertRaisesRegex(ReplayError, "official government URL"):
            validate_source_acquisition(url_drift, source_metadata)


class FrozenReplayTests(unittest.TestCase):
    def test_all_frozen_inputs_pass_locked_identity_checks(self):
        self.assertEqual(
            len(
                load_locked_csv(
                    MYCO_DIR / "myco2005_manual.csv",
                    MYCOTOXIN.MANUAL_2005_SPEC,
                )
            ),
            9,
        )
        self.assertEqual(
            len(
                load_locked_csv(
                    VET_DIR / "vetdrug_2019_manual.csv",
                    VETDRUG.MANUAL_2019_SPEC,
                )
            ),
            13,
        )
        self.assertEqual(
            len(
                load_locked_csv(
                    VET_DIR / "vetdrug_2022_manual.csv",
                    VETDRUG.MANUAL_2022_SPEC,
                )
            ),
            122,
        )
        self.assertEqual(
            len(
                load_locked_csv(
                    VET_DIR / "vetdrug_2002_long.csv",
                    VETDRUG.VETDRUG_2002_SPEC,
                )
            ),
            551,
        )

    def test_frozen_long_tables_and_panels_have_exact_identities(self):
        expected = {
            MYCO_DIR / "mycotoxin_limits_by_version.csv": (
                61,
                MYCOTOXIN.OUTPUT_IDENTITIES["mycotoxin_limits_by_version.csv"][1],
            ),
            MYCO_DIR / "mycotoxin_strictness_change.csv": (
                40,
                MYCOTOXIN.OUTPUT_IDENTITIES["mycotoxin_strictness_change.csv"][1],
            ),
            VET_DIR / "vetdrug_limits_by_version.csv": (
                1365,
                VETDRUG.OUTPUT_IDENTITIES["vetdrug_limits_by_version.csv"][1],
            ),
            VET_DIR / "vetdrug_strictness_change.csv": (
                657,
                VETDRUG.OUTPUT_IDENTITIES["vetdrug_strictness_change.csv"][1],
            ),
        }
        for path, (row_count, digest) in expected.items():
            with self.subTest(path=path.name):
                self.assertEqual(len(read_csv(path)), row_count)
                self.assertEqual(sha256_file(path), digest)

    def test_category_panels_replay_exactly_from_frozen_long_tables(self):
        myco_rows = [
            (
                row["year"],
                row["toxin"],
                row["food_category"],
                row["limit_value"],
                row["unit"],
                row["confidence"],
            )
            for row in read_csv(MYCO_DIR / "mycotoxin_limits_by_version.csv")
        ]
        vet_rows = [
            (
                row["year"],
                row["drug"],
                row["english"],
                row["animal_raw"],
                row["animal"],
                row["tissue"],
                row["limit_value"],
                row["unit"],
                row["source"],
            )
            for row in read_csv(VET_DIR / "vetdrug_limits_by_version.csv")
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            myco_output = write_csv_atomic(
                root / "mycotoxin_strictness_change.csv",
                (
                    "toxin",
                    "food_raw",
                    "food_canon",
                    "v2005",
                    "v2011",
                    "v2017",
                    "trend",
                    "note2005",
                    "raw2005",
                    "raw2011",
                    "raw2017",
                ),
                MYCOTOXIN.build_panel_rows(myco_rows),
                expected_rows=40,
                expected_sha256=MYCOTOXIN.OUTPUT_IDENTITIES[
                    "mycotoxin_strictness_change.csv"
                ][1],
            )
            vet_output = write_csv_atomic(
                root / "vetdrug_strictness_change.csv",
                ("drug", "english", "tissue", "v2002", "v2019", "trend"),
                VETDRUG.build_panel(vet_rows),
                expected_rows=657,
                expected_sha256=VETDRUG.OUTPUT_IDENTITIES[
                    "vetdrug_strictness_change.csv"
                ][1],
            )
        self.assertEqual(myco_output["rows"], 40)
        self.assertEqual(vet_output["rows"], 657)

    def test_reports_keep_the_manual_provenance_gap_open(self):
        myco_report = json.loads(
            (MYCO_DIR / "mycotoxin_replay_report.json").read_text()
        )
        vet_report = json.loads(
            (VET_DIR / "vetdrug_replay_report.json").read_text()
        )
        self.assertEqual(myco_report["provenance_gap"]["status"], "open")
        self.assertEqual(myco_report["provenance_gap"]["records"], 9)
        self.assertEqual(vet_report["provenance_gap"]["status"], "open")
        self.assertEqual(vet_report["provenance_gap"]["records"], 135)

    def test_reports_define_the_replay_scope_without_claiming_retranscription(self):
        for path in (
            MYCO_DIR / "mycotoxin_replay_report.json",
            VET_DIR / "vetdrug_replay_report.json",
        ):
            with self.subTest(path=path):
                scope = json.loads(path.read_text())["replay_scope"]
                self.assertTrue(scope["manual_seed_replay"])
                self.assertTrue(scope["downstream_rebuild"])
                self.assertFalse(scope["manual_seed_reextraction"])
                self.assertFalse(scope["independent_retranscription"])

    def test_2002_report_separates_transcription_and_row_locator_gaps(self):
        report = json.loads(
            (VET_DIR / "vetdrug_2002_replay_report.json").read_text()
        )
        self.assertEqual(report["manual_transcription_gap"]["status"], "none")
        self.assertEqual(report["row_locator_gap"]["status"], "open")
        self.assertIn("source_table_row", report["row_locator_gap"]["available_fields"])

    def test_rebuild_archive_does_not_unignore_source_documents(self):
        for archive in ("mycotoxin_rebuild", "vetdrug_rebuild"):
            for suffix in ("pdf", "PDF", "doc", "DOC", "docx", "DOCX"):
                path = f"Data/Interim/{archive}/source.{suffix}"
                with self.subTest(path=path):
                    completed = subprocess.run(
                        ["git", "check-ignore", "--no-index", "--quiet", path],
                        cwd=PROJECT_ROOT,
                        check=False,
                    )
                    self.assertEqual(completed.returncode, 0, path)


class RealSourceIntegrationTests(unittest.TestCase):
    """Optional end-to-end replay against the byte-identified source tree."""

    @classmethod
    def setUpClass(cls):
        configured = os.environ.get("LEGACY_FAMILY_SOURCE_ROOT")
        if not configured:
            raise unittest.SkipTest(
                "LEGACY_FAMILY_SOURCE_ROOT is unset; real legacy sources are optional"
            )
        cls.source_root = Path(configured)
        if not cls.source_root.is_dir():
            raise unittest.SkipTest(
                f"LEGACY_FAMILY_SOURCE_ROOT is unavailable: {cls.source_root}"
            )
        expected = {
            "GB 2761-2005 食品中真菌毒素限量.pdf": (
                "08419d4ca6eb01bafac3b8dbd84e4af1e515d11b7ac9cd78e7860be24f208045"
            ),
            "GB 2761-2011 食品安全国家标准 食品中真菌毒素限量.pdf": (
                "3baaee973294fb0c34ed349e61b9a387a09cb4a226ae7186922e1c5aef5fe4f0"
            ),
            "GB 2761-2017 食品安全国家标准 食品中真菌毒素限量.pdf": (
                "301bf80484b36d097985a4b9b3a6145f31042941064869a130072767636d1dee"
            ),
            "农业部235号公告-2002 动物性食品中兽药最高残留限量.doc": (
                "053802726b5b377bcb074987c72ec69318af7e91e74f2cc859d98747f92ce992"
            ),
            "GB 31650-2019 食品安全国家标准 食品中兽药最大残留限量.pdf": (
                "cfc745f1ac1567a6e59c50b3b119916a619573b833685158a7b0942dc22c5273"
            ),
            "GB 31650.1-2022 食品安全国家标准 食品中兽药最大残留限量增补.pdf": (
                "f65065dfae6450f1495de7921176b08d0058165b89479b16e297f484f151a27e"
            ),
        }
        cls.sources = {}
        missing = []
        for filename, digest in expected.items():
            matches = [
                path
                for path in cls.source_root.rglob(filename)
                if path.is_file() and sha256_file(path) == digest
            ]
            if not matches:
                missing.append(filename)
            else:
                cls.sources[filename] = sorted(matches)[0]
        if missing:
            raise unittest.SkipTest(
                "real source tree lacks byte-identified files: " + ", ".join(missing)
            )

        cls.temporary = tempfile.TemporaryDirectory()
        root = Path(cls.temporary.name)
        cls.myco_output = root / "mycotoxin"
        cls.vet2002_output = root / "vetdrug_2002"
        cls.vet_output = root / "vetdrug"
        manifest = (
            PROJECT_ROOT
            / "Data"
            / "Final"
            / "china_food_limit_panel_v1"
            / "source_manifest.csv"
        )
        VETDRUG_2002.main(
            [
                "--source-doc",
                str(cls.sources["农业部235号公告-2002 动物性食品中兽药最高残留限量.doc"]),
                "--source-manifest",
                str(manifest),
                "--output-dir",
                str(cls.vet2002_output),
                "--soffice",
                os.environ.get("LEGACY_SOFFICE", "soffice"),
            ]
        )
        MYCOTOXIN.main(
            [
                "--source-2005",
                str(cls.sources["GB 2761-2005 食品中真菌毒素限量.pdf"]),
                "--source-2011",
                str(cls.sources["GB 2761-2011 食品安全国家标准 食品中真菌毒素限量.pdf"]),
                "--source-2017",
                str(cls.sources["GB 2761-2017 食品安全国家标准 食品中真菌毒素限量.pdf"]),
                "--source-manifest",
                str(manifest),
                "--output-dir",
                str(cls.myco_output),
            ]
        )
        VETDRUG.main(
            [
                "--source-2002",
                str(cls.sources["农业部235号公告-2002 动物性食品中兽药最高残留限量.doc"]),
                "--source-2019",
                str(cls.sources["GB 31650-2019 食品安全国家标准 食品中兽药最大残留限量.pdf"]),
                "--source-2022",
                str(cls.sources["GB 31650.1-2022 食品安全国家标准 食品中兽药最大残留限量增补.pdf"]),
                "--source-manifest",
                str(manifest),
                "--vetdrug-2002-long",
                str(cls.vet2002_output / "vetdrug_2002_long.csv"),
                "--vetdrug-2002-quarantine",
                str(cls.vet2002_output / "vetdrug_2002_quarantine.csv"),
                "--output-dir",
                str(cls.vet_output),
            ]
        )

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "temporary"):
            cls.temporary.cleanup()

    def test_three_reports_and_frozen_output_identities(self):
        reports = (
            self.vet2002_output / "vetdrug_2002_replay_report.json",
            self.myco_output / "mycotoxin_replay_report.json",
            self.vet_output / "vetdrug_replay_report.json",
        )
        for path in reports:
            with self.subTest(path=path.name):
                self.assertEqual(json.loads(path.read_text())["status"], "pass")
        for directory, identities in (
            (self.myco_output, MYCOTOXIN.OUTPUT_IDENTITIES),
            (self.vet2002_output, VETDRUG_2002.EXPECTED_OUTPUTS),
            (self.vet_output, VETDRUG.OUTPUT_IDENTITIES),
        ):
            for filename, (count, digest) in identities.items():
                with self.subTest(filename=filename):
                    path = directory / filename
                    self.assertEqual(len(read_csv(path)), count)
                    self.assertEqual(sha256_file(path), digest)

    def test_rebuilt_long_tables_map_exactly_to_final_release(self):
        release = PROJECT_ROOT / "Data" / "Final" / "china_food_limit_panel_v1"
        rebuilt_myco = Counter(
            (
                row["year"],
                row["toxin"],
                row["food_category"],
                row["limit_value"],
                row["unit"],
                row["confidence"],
            )
            for row in read_csv(self.myco_output / "mycotoxin_limits_by_version.csv")
        )
        final_myco = Counter(
            (
                row["version_year"],
                row["toxin_zh"],
                row["food_category_zh"],
                row["limit_value"],
                row["unit"],
                row["confidence"],
            )
            for row in read_csv(release / "mycotoxin_limits_long.csv")
        )
        self.assertEqual(rebuilt_myco, final_myco)

        rebuilt_vet = Counter(
            (
                row["year"],
                row["drug"],
                row["english"],
                row["animal"],
                row["animal_raw"],
                row["tissue"],
                row["limit_value"],
                row["unit"],
                row["source"],
            )
            for row in read_csv(self.vet_output / "vetdrug_limits_by_version.csv")
        )
        final_vet = Counter(
            (
                row["version_year"],
                row["drug_zh"],
                row["drug_en"],
                row["animal"],
                row["animal_raw"],
                row["tissue_zh"],
                row["limit_value"],
                row["unit"],
                row["source"],
            )
            for row in read_csv(release / "vetdrug_limits_long.csv")
        )
        self.assertEqual(rebuilt_vet, final_vet)


if __name__ == "__main__":
    unittest.main()
