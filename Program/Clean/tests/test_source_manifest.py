import csv
import importlib.util
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "260715_build_source_manifest.py"
sys.path.insert(0, str(SCRIPT.parent))
import source_acquisition_metadata as ACQUISITION  # noqa: E402
import source_manifest_utils as UTILS  # noqa: E402

SPEC = importlib.util.spec_from_file_location("build_source_manifest", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SourceManifestContractTests(unittest.TestCase):
    def acquisition_guide_rows(self):
        """Build portable synthetic rows with the two verified exact digests."""

        locators = ACQUISITION.source_locators_by_id()
        rows = []
        for index, document in enumerate(MODULE.SOURCE_DOCUMENTS, start=1):
            locator = locators[document.source_id]
            digest = locator.expected_sha256 or f"{index:064x}"
            rows.append(
                {
                    "source_id": document.source_id,
                    "standard": document.standard,
                    "version_year": document.version_year,
                    "source_filename": document.relative_path.name,
                    "file_size_bytes": str(index),
                    "sha256": digest,
                    "acquisition_landing_url": (
                        document.acquisition_landing_url
                    ),
                    "acquisition_file_url": document.acquisition_file_url,
                    "retrieved_date": document.retrieved_date,
                }
            )
        return rows

    def test_source_role_and_release_status_counts_are_explicit(self):
        roles = Counter(document.source_role for document in MODULE.SOURCE_DOCUMENTS)
        statuses = Counter(
            document.release_status for document in MODULE.SOURCE_DOCUMENTS
        )

        self.assertEqual(roles["edition_source"], 21)
        self.assertEqual(roles["identity_audit_copy"], 2)
        self.assertEqual(roles["extraction_copy"], 2)
        self.assertEqual(statuses["extracted"], 19)
        self.assertEqual(statuses["archived_unextracted"], 2)
        self.assertEqual(statuses["identity_anchor_crosscheck"], 2)
        self.assertEqual(statuses["excluded_from_extraction"], 2)

    def test_source_ids_are_explicit_and_existing_ids_remain_stable(self):
        documents = UTILS.source_documents_by_id()

        self.assertEqual(list(documents), [f"SRC{index:04d}" for index in range(1, 26)])
        self.assertEqual(documents["SRC0009"].version_year, "2019")
        self.assertEqual(documents["SRC0010"].version_year, "2021")
        self.assertEqual(documents["SRC0022"].source_role, "identity_audit_copy")
        self.assertEqual(documents["SRC0023"].source_role, "identity_audit_copy")
        self.assertEqual(documents["SRC0024"].source_role, "extraction_copy")
        self.assertEqual(documents["SRC0025"].source_role, "extraction_copy")

    def test_source_locators_are_relative_and_unique(self):
        paths = [document.relative_path for document in MODULE.SOURCE_DOCUMENTS]

        self.assertTrue(all(not path.is_absolute() for path in paths))
        self.assertEqual(len(paths), len(set(paths)))

    def test_edition_lookup_separates_identity_and_extraction_sources(self):
        relations = UTILS.source_ids_by_edition()

        self.assertEqual(
            relations[("pesticide", "GB 2763", "2019")],
            {
                "edition_source_id": "SRC0009",
                "extraction_source_id": "SRC0024",
            },
        )
        self.assertEqual(
            relations[("pesticide", "GB 2763", "2021")],
            {
                "edition_source_id": "SRC0010",
                "extraction_source_id": "SRC0025",
            },
        )
        self.assertEqual(
            relations[("pesticide", "GB 2763", "2016")],
            {
                "edition_source_id": "SRC0008",
                "extraction_source_id": "SRC0008",
            },
        )

    def test_misnamed_amendment_files_are_excluded(self):
        audit_copies = [
            document
            for document in MODULE.SOURCE_DOCUMENTS
            if document.source_role == "identity_audit_copy"
        ]

        self.assertTrue(
            all(
                document.document_identity
                == "full_standard_text_misnamed_as_amendment"
                and document.release_status == "excluded_from_extraction"
                for document in audit_copies
            )
        )
        self.assertEqual(
            {document.related_source_id for document in audit_copies},
            {"SRC0003", "SRC0004"},
        )

    def test_extraction_copy_urls_pages_and_unknown_dates_are_explicit(self):
        copies = [
            document
            for document in MODULE.SOURCE_DOCUMENTS
            if document.source_role == "extraction_copy"
        ]

        self.assertEqual(
            {(document.source_id, document.related_source_id) for document in copies},
            {("SRC0024", "SRC0009"), ("SRC0025", "SRC0010")},
        )
        self.assertEqual({document.page_count for document in copies}, {332, 422})
        self.assertTrue(
            all(
                document.acquisition_landing_url.startswith("https://")
                and document.acquisition_file_url.startswith("https://")
                and document.retrieved_date == ""
                for document in copies
            )
        )

    def test_public_locator_metadata_covers_every_stable_source_id(self):
        locators = ACQUISITION.source_locators_by_id()
        source_ids = [document.source_id for document in MODULE.SOURCE_DOCUMENTS]

        self.assertEqual(list(locators), source_ids)
        self.assertEqual(len(ACQUISITION.TRANSLATION_SOURCES), 4)
        for locator in locators.values():
            for url in (locator.landing_url, locator.file_url):
                if url:
                    self.assertTrue(url.startswith("https://"), url)
            if locator.locator_status == "byte_exact_official_file":
                self.assertRegex(locator.expected_sha256, r"^[0-9a-f]{64}$")
                self.assertTrue(locator.file_url)

    def test_translation_digest_locks_share_one_metadata_source(self):
        self.assertEqual(
            ACQUISITION.TRANSLATION_PDFS,
            {
                source.filename: source.sha256
                for source in ACQUISITION.TRANSLATION_SOURCES
            },
        )
        self.assertEqual(
            set(ACQUISITION.TRANSLATION_PDFS),
            {
                "FSIS_GB2763-2016_en.pdf",
                "GAIN_CH2019-0170_GB2763-2019_en.pdf",
                "GAIN_CH2023-0040_GB2762-2022_en.pdf",
                "GAIN_GB2760-2014_en.pdf",
            },
        )

    def test_guide_contains_exact_identities_and_no_private_paths(self):
        rows = self.acquisition_guide_rows()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "SOURCE_ACQUISITION.md"
            MODULE.write_source_acquisition_guide(rows, output)
            guide = output.read_text(encoding="utf-8")

        for row in rows:
            self.assertIn(row["source_id"], guide)
            self.assertIn(row["sha256"], guide)
        for source in ACQUISITION.TRANSLATION_SOURCES:
            self.assertIn(source.filename, guide)
            self.assertIn(source.sha256, guide)
        self.assertIn("original retrieval date was unrecorded", guide)
        self.assertNotIn("/Users/", guide)
        self.assertNotIn("/Volumes/", guide)

    def test_guide_rejects_exact_locator_digest_mismatch(self):
        rows = self.acquisition_guide_rows()
        by_id = {row["source_id"]: row for row in rows}
        by_id["SRC0002"]["sha256"] = "0" * 64

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "SOURCE_ACQUISITION.md"
            with self.assertRaisesRegex(
                ValueError, "exact-byte locator digest differs"
            ):
                MODULE.write_source_acquisition_guide(rows, output)
            self.assertFalse(output.exists())

    def test_veterinary_sources_keep_distinct_standard_identities(self):
        identities = {
            (document.standard, document.version_year, document.document_identity)
            for document in MODULE.SOURCE_DOCUMENTS
            if document.family == "veterinary_drug"
            and document.source_role == "edition_source"
        }

        self.assertEqual(
            identities,
            {
                ("MOA Announcement 235", "2002", "official_announcement"),
                ("GB 31650", "2019", "full_standard"),
                ("GB 31650.1", "2022", "supplementary_standard"),
            },
        )

    def test_builder_resolves_two_roots_and_writes_relationship_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_root = root / "archive"
            extraction_root = root / "extraction"
            release_dir = root / "release"
            release_dir.mkdir()

            for document in MODULE.SOURCE_DOCUMENTS:
                source_path = MODULE.resolve_source_path(
                    document, archive_root, extraction_root
                )
                source_path.parent.mkdir(parents=True, exist_ok=True)
                source_path.write_bytes(f"{document.source_id}\n".encode())

            extracted = [
                document
                for document in MODULE.SOURCE_DOCUMENTS
                if document.release_status == "extracted"
            ]
            for family, filename in MODULE.LONG_TABLES.items():
                with (release_dir / filename).open(
                    "w", encoding="utf-8-sig", newline=""
                ) as stream:
                    writer = csv.DictWriter(stream, fieldnames=("version_year",))
                    writer.writeheader()
                    writer.writerows(
                        {"version_year": document.version_year}
                        for document in extracted
                        if document.family == family
                    )

            output = root / "source_manifest.csv"
            rows = MODULE.build_manifest(
                archive_root,
                release_dir,
                output,
                extraction_root,
            )

            self.assertEqual(len(rows), 25)
            self.assertEqual(tuple(rows[0]), MODULE.OUTPUT_COLUMNS)
            by_id = {row["source_id"]: row for row in rows}
            self.assertEqual(by_id["SRC0024"]["source_filename"], "GB2763-2019_shanghai_gov_textlayer.pdf")
            self.assertEqual(by_id["SRC0024"]["related_source_id"], "SRC0009")
            self.assertEqual(by_id["SRC0024"]["released_limit_rows"], "1")
            self.assertEqual(by_id["SRC0009"]["released_limit_rows"], "")
            self.assertEqual(
                by_id["SRC0009"]["release_status"],
                "identity_anchor_crosscheck",
            )
            self.assertEqual(by_id["SRC0025"]["page_count"], "422")
            self.assertEqual(by_id["SRC0015"]["page_count"], "")
            with output.open(encoding="utf-8-sig", newline="") as stream:
                self.assertEqual(
                    tuple(csv.DictReader(stream).fieldnames or ()),
                    MODULE.OUTPUT_COLUMNS,
                )
            output_bytes = output.read_bytes()
            self.assertNotIn(b"\r\n", output_bytes)
            self.assertTrue(output_bytes.endswith(b"\n"))


if __name__ == "__main__":
    unittest.main()
