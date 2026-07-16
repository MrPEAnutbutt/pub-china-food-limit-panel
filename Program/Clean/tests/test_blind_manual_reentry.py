from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CLEAN_DIR = PROJECT_ROOT / "Program" / "Clean"
if str(CLEAN_DIR) not in sys.path:
    sys.path.insert(0, str(CLEAN_DIR))
MODULE_PATH = CLEAN_DIR / "260716_blind_manual_reentry.py"
SPEC = importlib.util.spec_from_file_location("blind_manual_reentry", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

SOURCE_MANIFEST = (
    PROJECT_ROOT
    / "Data"
    / "Final"
    / "china_food_limit_panel_v1"
    / "source_manifest.csv"
)
MYCO_SEED = (
    PROJECT_ROOT / "Data" / "Interim" / "mycotoxin_rebuild" / "myco2005_manual.csv"
)
VET2019_SEED = (
    PROJECT_ROOT / "Data" / "Interim" / "vetdrug_rebuild" / "vetdrug_2019_manual.csv"
)
VET2022_SEED = (
    PROJECT_ROOT / "Data" / "Interim" / "vetdrug_rebuild" / "vetdrug_2022_manual.csv"
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BlindManualReentryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.packet = self.root / "packet"

    def tearDown(self):
        self.temporary.cleanup()

    def prepare(self) -> dict[str, object]:
        return MODULE.prepare_packet(SOURCE_MANIFEST, self.packet)

    def fill_entries(self, *, reverse: bool = False) -> Path:
        self.prepare()
        seeds = {
            "MYC2005": read_csv(MYCO_SEED),
            "VET2019": read_csv(VET2019_SEED),
            "VET2022": read_csv(VET2022_SEED),
        }
        mappings = {
            "MYC2005": {
                "toxin_raw": "toxin",
                "food_category_raw": "food_category",
                "limit_value_raw": "limit_value",
                "unit_raw": "unit",
            },
            "VET2019": {
                "drug_zh_raw": "drug",
                "drug_en_raw": "english",
                "animal_raw": "animal",
                "tissue_raw": "tissue",
                "limit_value_raw": "limit_value",
                "unit_raw": "unit",
            },
            "VET2022": {
                "drug_zh_raw": "drug",
                "drug_en_raw": "english",
                "animal_raw": "animal",
                "tissue_raw": "tissue",
                "limit_value_raw": "limit_value",
                "unit_raw": "unit",
            },
        }
        for batch_id in ("MYC2005", "VET2019", "VET2022"):
            contract = MODULE.CONTRACT_BY_BATCH[batch_id]
            path = self.packet / contract.template_filename
            rows = read_csv(path)
            seed_by_row = {
                str(row_number): seed
                for row_number, seed in enumerate(seeds[batch_id], start=1)
            }
            for row in rows:
                seed = seed_by_row[row["source_order"]]
                row["entry_status"] = "transcribed"
                for entry_field, seed_field in mappings[batch_id].items():
                    row[entry_field] = seed[seed_field]
            if reverse:
                rows.reverse()
            fields = (
                MODULE.MYCO_TEMPLATE_FIELDS
                if batch_id == "MYC2005"
                else MODULE.VET_TEMPLATE_FIELDS
            )
            write_csv(path, fields, rows)
        attestation_path = self.packet / "reviewer_attestation.json"
        attestation = json.loads(attestation_path.read_text())
        attestation.update(
            {
                "reviewer_id": "independent-reviewer-01",
                "reviewer_role": "independent source transcriber",
                "review_date": "2026-07-16",
                "independent_person": True,
                "no_access_to_construction_seeds": True,
                "no_access_to_release_values": True,
                "source_files_verified_against_manifest": True,
                "confirmation": MODULE.CONFIRMATION,
            }
        )
        attestation["completed_entry_sha256"] = {
            contract.template_filename: file_hash(
                self.packet / contract.template_filename
            )
            for contract in MODULE.SOURCE_CONTRACTS
        }
        attestation_path.write_text(
            json.dumps(attestation, ensure_ascii=False, indent=2) + "\n"
        )
        return attestation_path

    def reconcile(
        self,
        attestation: Path,
        output: Path | None = None,
        adjudication: Path | None = None,
    ):
        return MODULE.reconcile_packet(
            source_manifest=SOURCE_MANIFEST,
            entry_dir=self.packet,
            attestation_path=attestation,
            manual_2005=MYCO_SEED,
            manual_2019=VET2019_SEED,
            manual_2022=VET2022_SEED,
            adjudication_path=adjudication,
            output_dir=output or self.root / "reconciliation",
        )

    def test_prepare_is_value_free_and_does_not_read_seed_files(self):
        with mock.patch.object(
            MODULE, "load_locked_csv", side_effect=AssertionError("seed read")
        ):
            manifest = self.prepare()
        self.assertFalse(manifest["blindness"]["construction_seed_files_read"])
        self.assertFalse(manifest["blindness"]["release_tables_read"])
        self.assertEqual(
            {path.name for path in self.packet.iterdir()},
            {
                "README.md",
                "batch_manifest.csv",
                "mycotoxin_2005_blind_entry.csv",
                "packet_manifest.json",
                "reviewer_attestation.json",
                "vetdrug_2019_blind_entry.csv",
                "vetdrug_2022_blind_entry.csv",
            },
        )
        counts = {}
        for contract in MODULE.SOURCE_CONTRACTS:
            rows = read_csv(self.packet / contract.template_filename)
            counts[contract.batch_id] = len(rows)
            entry_fields = (
                MODULE.MYCO_ENTRY_FIELDS
                if contract.batch_id == "MYC2005"
                else MODULE.VET_ENTRY_FIELDS
            )
            self.assertTrue(
                all(
                    row["entry_status"] == ""
                    and row["reviewer_note"] == ""
                    and all(row[field] == "" for field in entry_fields)
                    for row in rows
                )
            )
        self.assertEqual(counts, {"MYC2005": 9, "VET2019": 13, "VET2022": 122})
        packet_text = "\n".join(
            path.read_text(encoding="utf-8-sig")
            for path in self.packet.iterdir()
            if path.suffix in {".csv", ".json", ".md"}
        )
        for digest in (
            "209d99250e4555a2cf68addb22a49549e0edfb158f43f3cc94601f92d1883b9d",
            "58d8907398b9c0059b04cbec22c3d184bc3bd578eb47bf3e855eabbe96f69fcb",
            "6d5e25a2455157ce6a26452b8cb4fb380698173babf52ae9656d4e780b6d82f8",
        ):
            self.assertNotIn(digest, packet_text)

    def test_locator_contract_covers_all_17_pages_and_47_tables(self):
        tasks = MODULE.build_tasks()
        self.assertEqual(
            MODULE._locator_contract_sha256(tasks), MODULE.LOCATOR_CONTRACT_SHA256
        )
        myco = tasks["MYC2005"]
        self.assertEqual(
            [(row["pdf_page"], row["printed_table"]) for row in myco],
            [("3", "1")] * 4 + [("4", "2")] * 2 + [("4", "3")] * 2 + [("4", "4")],
        )
        vet2019 = tasks["VET2019"]
        self.assertEqual(
            [row["pdf_page"] for row in vet2019],
            ["19"] * 5 + ["20"] * 2 + ["23"] * 3 + ["24"] * 3,
        )
        self.assertEqual(
            [row["continued_from_previous_page"] for row in vet2019],
            ["false"] * 5 + ["true"] * 2 + ["false"] * 3 + ["true"] * 3,
        )
        vet2022 = tasks["VET2022"]
        self.assertEqual(len(vet2022), 122)
        self.assertEqual(
            {int(row["printed_table"]) for row in vet2022}, set(range(1, 42))
        )
        self.assertEqual({int(row["pdf_page"]) for row in vet2022}, set(range(5, 16)))
        all_pages = {
            (row["source_id"], row["pdf_page"])
            for rows in tasks.values()
            for row in rows
        }
        self.assertEqual(len(all_pages), 17)

    def test_prepare_is_byte_deterministic(self):
        first = self.prepare()
        first_hashes = {path.name: file_hash(path) for path in self.packet.iterdir()}
        second_dir = self.root / "second"
        second = MODULE.prepare_packet(SOURCE_MANIFEST, second_dir)
        second_hashes = {path.name: file_hash(path) for path in second_dir.iterdir()}
        self.assertEqual(first["packet_id"], second["packet_id"])
        self.assertEqual(first_hashes, second_hashes)

    def test_prepare_rejects_nonempty_output_directory(self):
        self.packet.mkdir(parents=True)
        secret = self.packet / "construction_seed.csv"
        secret.write_text("must-not-reach-reviewer\n")
        with self.assertRaisesRegex(MODULE.AuditError, "must be empty"):
            self.prepare()
        self.assertEqual(secret.read_text(), "must-not-reach-reviewer\n")

    def test_reconcile_rejects_nonempty_output_directory(self):
        attestation = self.fill_entries()
        output = self.root / "occupied-reconciliation"
        output.mkdir()
        marker = output / "earlier-audit.txt"
        marker.write_text("preserve this run\n")
        with self.assertRaisesRegex(MODULE.AuditError, "must be empty"):
            self.reconcile(attestation, output=output)
        self.assertEqual(marker.read_text(), "preserve this run\n")

    def test_packet_id_binds_material_contract(self):
        original = MODULE.packet_id()
        manifest = self.prepare()
        self.assertEqual(
            manifest["packet_contract_sha256"], MODULE.packet_contract_sha256()
        )
        with mock.patch.object(
            MODULE,
            "MYCO_TEMPLATE_FIELDS",
            MODULE.MYCO_TEMPLATE_FIELDS + ("unexpected_field",),
        ):
            self.assertNotEqual(MODULE.packet_id(), original)

    def test_reconcile_passes_complete_shuffled_entries(self):
        attestation = self.fill_entries(reverse=True)
        report = self.reconcile(attestation)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["provenance_gap"]["status"], "closed")
        self.assertEqual(report["comparison_counts"]["exact_match"], 846)
        self.assertEqual(report["comparison_counts"]["disagreement"], 0)

    def test_normalised_match_preserves_raw_values(self):
        attestation = self.fill_entries()
        path = self.packet / "mycotoxin_2005_blind_entry.csv"
        rows = read_csv(path)
        rows[0]["limit_value_raw"] = "20.0"
        rows[0]["unit_raw"] = "µg/kg"
        write_csv(path, MODULE.MYCO_TEMPLATE_FIELDS, rows)
        payload = json.loads(attestation.read_text())
        payload["completed_entry_sha256"][path.name] = file_hash(path)
        attestation.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        report = self.reconcile(attestation)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["comparison_counts"]["normalised_match"], 2)
        comparison = read_csv(
            self.root / "reconciliation" / "blind_reentry_field_comparison.csv"
        )
        changed = [
            row
            for row in comparison
            if row["blind_record_id"] == "BR-MYC2005-001"
            and row["comparison_status"] == "normalised_match"
        ]
        self.assertEqual(
            {(row["construction_raw"], row["reentry_raw"]) for row in changed},
            {("20", "20.0"), ("μg/kg", "µg/kg")},
        )

    def test_disagreement_fails_closed_without_mutating_seed(self):
        attestation = self.fill_entries()
        path = self.packet / "vetdrug_2022_blind_entry.csv"
        rows = read_csv(path)
        rows[0]["limit_value_raw"] = "999"
        write_csv(path, MODULE.VET_TEMPLATE_FIELDS, rows)
        payload = json.loads(attestation.read_text())
        payload["completed_entry_sha256"][path.name] = file_hash(path)
        attestation.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        before = file_hash(VET2022_SEED)
        report = self.reconcile(attestation)
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["provenance_gap"]["status"], "open")
        self.assertEqual(report["comparison_counts"]["disagreement"], 1)
        self.assertEqual(file_hash(VET2022_SEED), before)
        adjudication = read_csv(
            self.root / "reconciliation" / "blind_reentry_adjudication_template.csv"
        )
        self.assertEqual(len(adjudication), 1)
        self.assertEqual(adjudication[0]["blind_record_id"], "BR-VET2022-001")

    def test_illegible_status_cannot_hide_transcribed_values(self):
        attestation = self.fill_entries()
        path = self.packet / "mycotoxin_2005_blind_entry.csv"
        rows = read_csv(path)
        rows[0]["entry_status"] = "illegible"
        rows[0]["reviewer_note"] = "Source row could not be read."
        write_csv(path, MODULE.MYCO_TEMPLATE_FIELDS, rows)
        payload = json.loads(attestation.read_text())
        payload["completed_entry_sha256"][path.name] = file_hash(path)
        attestation.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        with self.assertRaisesRegex(MODULE.AuditError, "contains transcribed values"):
            self.reconcile(attestation)

    def test_illegible_row_keeps_gap_open(self):
        attestation = self.fill_entries()
        path = self.packet / "mycotoxin_2005_blind_entry.csv"
        rows = read_csv(path)
        rows[0]["entry_status"] = "illegible"
        rows[0]["reviewer_note"] = "Source row could not be read."
        for field in MODULE.MYCO_ENTRY_FIELDS:
            rows[0][field] = ""
        write_csv(path, MODULE.MYCO_TEMPLATE_FIELDS, rows)
        payload = json.loads(attestation.read_text())
        payload["completed_entry_sha256"][path.name] = file_hash(path)
        attestation.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        report = self.reconcile(attestation)
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["provenance_gap"]["status"], "open")
        self.assertEqual(report["comparison_counts"]["missing"], 4)

    def test_adjudication_must_preserve_confirmed_raw_value(self):
        attestation = self.fill_entries()
        path = self.packet / "vetdrug_2022_blind_entry.csv"
        rows = read_csv(path)
        rows[0]["limit_value_raw"] = "999"
        write_csv(path, MODULE.VET_TEMPLATE_FIELDS, rows)
        payload = json.loads(attestation.read_text())
        payload["completed_entry_sha256"][path.name] = file_hash(path)
        attestation.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        initial_output = self.root / "initial-reconciliation"
        self.reconcile(attestation, output=initial_output)
        adjudication = initial_output / "blind_reentry_adjudication_template.csv"
        adjudication_rows = read_csv(adjudication)
        adjudication_rows[0].update(
            {
                "adjudication_status": "construction_confirmed",
                "adjudicated_raw": "not-the-construction-value",
                "error_source": "reentry",
                "adjudicator_id": "adjudicator-01",
                "adjudication_date": "2026-07-16",
                "adjudication_note": "Checked against the printed source.",
            }
        )
        write_csv(adjudication, MODULE.ADJUDICATION_FIELDS, adjudication_rows)
        with self.assertRaisesRegex(MODULE.AuditError, "confirmed side"):
            self.reconcile(attestation, adjudication=adjudication)

    def test_valid_construction_confirmation_closes_disagreement(self):
        attestation = self.fill_entries()
        path = self.packet / "vetdrug_2022_blind_entry.csv"
        rows = read_csv(path)
        rows[0]["limit_value_raw"] = "999"
        write_csv(path, MODULE.VET_TEMPLATE_FIELDS, rows)
        payload = json.loads(attestation.read_text())
        payload["completed_entry_sha256"][path.name] = file_hash(path)
        attestation.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        initial_output = self.root / "initial-reconciliation"
        self.reconcile(attestation, output=initial_output)
        adjudication = initial_output / "blind_reentry_adjudication_template.csv"
        adjudication_rows = read_csv(adjudication)
        adjudication_rows[0].update(
            {
                "adjudication_status": "construction_confirmed",
                "adjudicated_raw": "1",
                "error_source": "reentry",
                "adjudicator_id": "adjudicator-01",
                "adjudication_date": "2026-07-16",
                "adjudication_note": "Checked against the printed source.",
            }
        )
        write_csv(adjudication, MODULE.ADJUDICATION_FIELDS, adjudication_rows)
        report = self.reconcile(attestation, adjudication=adjudication)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["provenance_gap"]["status"], "closed")

    def test_initial_transcriber_cannot_adjudicate_disagreement(self):
        attestation = self.fill_entries()
        path = self.packet / "vetdrug_2022_blind_entry.csv"
        rows = read_csv(path)
        rows[0]["limit_value_raw"] = "999"
        write_csv(path, MODULE.VET_TEMPLATE_FIELDS, rows)
        payload = json.loads(attestation.read_text())
        payload["completed_entry_sha256"][path.name] = file_hash(path)
        attestation.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        initial_output = self.root / "initial-reconciliation"
        self.reconcile(attestation, output=initial_output)
        adjudication = initial_output / "blind_reentry_adjudication_template.csv"
        adjudication_rows = read_csv(adjudication)
        adjudication_rows[0].update(
            {
                "adjudication_status": "construction_confirmed",
                "adjudicated_raw": "1",
                "error_source": "reentry",
                "adjudicator_id": MODULE.INITIAL_TRANSCRIBER_ID,
                "adjudication_date": "2026-07-16",
                "adjudication_note": "Checked against the printed source.",
            }
        )
        write_csv(adjudication, MODULE.ADJUDICATION_FIELDS, adjudication_rows)
        with self.assertRaisesRegex(MODULE.AuditError, "must be independent"):
            self.reconcile(attestation, adjudication=adjudication)
        adjudication_rows[0]["adjudicator_id"] = "independent-reviewer-01"
        write_csv(adjudication, MODULE.ADJUDICATION_FIELDS, adjudication_rows)
        with self.assertRaisesRegex(MODULE.AuditError, "must be independent"):
            self.reconcile(attestation, adjudication=adjudication)

    def test_invalid_attestation_is_rejected(self):
        attestation = self.fill_entries()
        payload = json.loads(attestation.read_text())
        payload["reviewer_id"] = MODULE.INITIAL_TRANSCRIBER_ID
        attestation.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        with self.assertRaisesRegex(MODULE.AuditError, "reviewer must differ"):
            self.reconcile(attestation)

    def test_modified_confirmation_statement_is_rejected(self):
        attestation = self.fill_entries()
        payload = json.loads(attestation.read_text())
        payload["confirmation_statement"] = "Changed after review."
        attestation.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        with self.assertRaisesRegex(MODULE.AuditError, "statement differs"):
            self.reconcile(attestation)

    def test_completed_entry_bytes_must_match_attested_digest(self):
        attestation = self.fill_entries()
        path = self.packet / "mycotoxin_2005_blind_entry.csv"
        rows = read_csv(path)
        rows[0]["reviewer_note"] = "Changed after the files were frozen."
        write_csv(path, MODULE.MYCO_TEMPLATE_FIELDS, rows)
        with self.assertRaisesRegex(MODULE.AuditError, "attested entry digest"):
            self.reconcile(attestation)


if __name__ == "__main__":
    unittest.main()
