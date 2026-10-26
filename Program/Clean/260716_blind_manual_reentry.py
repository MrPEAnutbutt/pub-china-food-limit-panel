#!/usr/bin/env python3
"""Prepare and reconcile a blind re-entry audit for 144 manual records."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
from io import StringIO
import json
from pathlib import Path
import re
import sys
import tempfile
import unicodedata

from legacy_family_replay import (
    ReplayError,
    file_metadata,
    load_locked_csv,
    write_json_atomic,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = (
    PROJECT_ROOT
    / "Data"
    / "Final"
    / "china_food_limit_panel_v1"
    / "source_manifest.csv"
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "Data" / "Interim" / "manual_reentry" / "blind_packet"
)
DEFAULT_MYCO_SEED = (
    PROJECT_ROOT / "Data" / "Interim" / "mycotoxin_rebuild" / "myco2005_manual.csv"
)
DEFAULT_VET2019_SEED = (
    PROJECT_ROOT / "Data" / "Interim" / "vetdrug_rebuild" / "vetdrug_2019_manual.csv"
)
DEFAULT_VET2022_SEED = (
    PROJECT_ROOT / "Data" / "Interim" / "vetdrug_rebuild" / "vetdrug_2022_manual.csv"
)

PROTOCOL_VERSION = "1.2"
INITIAL_TRANSCRIBER_ID = "Zilong Xu"
CONFIRMATION = "confirmed"
CONFIRMATION_STATEMENT = (
    "I independently transcribed the specified source rows without viewing the "
    "construction seeds or released values before the completed entry files were "
    "frozen."
)


class AuditError(RuntimeError):
    """Raised when the blind-audit contract is incomplete or inconsistent."""


@dataclass(frozen=True)
class SourceContract:
    batch_id: str
    source_id: str
    family: str
    standard: str
    version_year: str
    filename: str
    sha256: str
    page_count: int
    released_limit_rows: int
    template_filename: str


SOURCE_CONTRACTS = (
    SourceContract(
        batch_id="MYC2005",
        source_id="SRC0012",
        family="mycotoxin",
        standard="GB 2761",
        version_year="2005",
        filename="GB 2761-2005 食品中真菌毒素限量.pdf",
        sha256="08419d4ca6eb01bafac3b8dbd84e4af1e515d11b7ac9cd78e7860be24f208045",
        page_count=4,
        released_limit_rows=9,
        template_filename="mycotoxin_2005_blind_entry.csv",
    ),
    SourceContract(
        batch_id="VET2019",
        source_id="SRC0016",
        family="veterinary_drug",
        standard="GB 31650",
        version_year="2019",
        filename="GB 31650-2019 食品安全国家标准 食品中兽药最大残留限量.pdf",
        sha256="cfc745f1ac1567a6e59c50b3b119916a619573b833685158a7b0942dc22c5273",
        page_count=64,
        released_limit_rows=692,
        template_filename="vetdrug_2019_blind_entry.csv",
    ),
    SourceContract(
        batch_id="VET2022",
        source_id="SRC0017",
        family="veterinary_drug",
        standard="GB 31650.1",
        version_year="2022",
        filename="GB 31650.1-2022 食品安全国家标准 食品中兽药最大残留限量增补.pdf",
        sha256="f65065dfae6450f1495de7921176b08d0058165b89479b16e297f484f151a27e",
        page_count=18,
        released_limit_rows=122,
        template_filename="vetdrug_2022_blind_entry.csv",
    ),
)
CONTRACT_BY_BATCH = {contract.batch_id: contract for contract in SOURCE_CONTRACTS}

LOCATOR_FIELDS = (
    "blind_record_id",
    "source_order",
    "source_id",
    "section_number",
    "pdf_page",
    "printed_page",
    "printed_table",
    "printed_row",
    "continued_from_previous_page",
)
COMMON_TAIL_FIELDS = ("entry_status",)
MYCO_ENTRY_FIELDS = (
    "toxin_raw",
    "food_category_raw",
    "limit_value_raw",
    "unit_raw",
)
VET_ENTRY_FIELDS = (
    "drug_zh_raw",
    "drug_en_raw",
    "animal_raw",
    "tissue_raw",
    "limit_value_raw",
    "unit_raw",
)
TRAILING_FIELDS = ("reviewer_note",)
MYCO_TEMPLATE_FIELDS = (
    LOCATOR_FIELDS + COMMON_TAIL_FIELDS + MYCO_ENTRY_FIELDS + TRAILING_FIELDS
)
VET_TEMPLATE_FIELDS = (
    LOCATOR_FIELDS + COMMON_TAIL_FIELDS + VET_ENTRY_FIELDS + TRAILING_FIELDS
)

BATCH_MANIFEST_FIELDS = (
    "packet_id",
    "batch_id",
    "source_id",
    "standard",
    "version_year",
    "source_filename",
    "source_sha256",
    "pdf_pages",
    "printed_pages",
    "tables",
    "task_count",
    "template_filename",
)
COMPARISON_FIELDS = (
    "blind_record_id",
    "batch_id",
    "source_id",
    "source_order",
    "pdf_page",
    "printed_table",
    "printed_row",
    "field",
    "construction_raw",
    "reentry_raw",
    "construction_normalised",
    "reentry_normalised",
    "comparison_rule",
    "comparison_status",
    "adjudication_status",
    "adjudicated_raw",
    "error_source",
    "adjudicator_id",
    "adjudication_date",
    "adjudication_note",
)
ADJUDICATION_FIELDS = (
    "blind_record_id",
    "field",
    "adjudication_status",
    "adjudicated_raw",
    "error_source",
    "adjudicator_id",
    "adjudication_date",
    "adjudication_note",
)
COMPARISON_RULE_CONTRACT = {
    "default": "nfkc_whitespace_v1",
    "drug_en_raw": "nfkc_whitespace_casefold_v1",
    "limit_value_raw": "decimal_equivalence_v1",
    "unit_raw": "nfkc_whitespace_casefold_micro_glyph_v1",
}
ADJUDICATION_ERROR_SOURCES = {
    "construction_confirmed": "reentry",
    "reentry_confirmed": "construction",
    "corrected_value": "both",
    "unresolved": "unresolved",
}

VET2022_ROW_COUNTS = (
    3,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    4,
    1,
    4,
    1,
    1,
    2,
    1,
    1,
    1,
    9,
    8,
    1,
    1,
    8,
    2,
    9,
    7,
    8,
    8,
    8,
    1,
    1,
    8,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    8,
)
VET2022_TABLE_PAGES = {
    **{table: 5 for table in range(1, 3)},
    **{table: 6 for table in range(3, 8)},
    **{table: 7 for table in range(8, 12)},
    **{table: 8 for table in range(12, 17)},
    **{table: 9 for table in range(17, 20)},
    **{table: 10 for table in range(20, 24)},
    **{table: 11 for table in range(24, 27)},
    **{table: 12 for table in range(27, 30)},
    **{table: 13 for table in range(30, 34)},
    **{table: 14 for table in range(34, 39)},
    **{table: 15 for table in range(39, 42)},
}
LOCATOR_CONTRACT_FIELDS = (
    "blind_record_id",
    "construction_seed_row",
    "source_id",
    "section_number",
    "pdf_page",
    "printed_page",
    "printed_table",
    "printed_row",
)
# Frozen from the independently checked 144-row source-page/seed-row crosswalk.
LOCATOR_CONTRACT_SHA256 = (
    "846ffc6da9324810e6a5712e2ad2f90b8ed84d4a0a626cd4651306b7d77d4a35"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="write value-free entry templates")
    prepare.add_argument("--source-manifest", type=Path, default=DEFAULT_MANIFEST)
    prepare.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)

    reconcile = subparsers.add_parser(
        "reconcile", help="compare frozen independent entries with construction seeds"
    )
    reconcile.add_argument("--source-manifest", type=Path, default=DEFAULT_MANIFEST)
    reconcile.add_argument("--entry-dir", type=Path, required=True)
    reconcile.add_argument("--attestation", type=Path)
    reconcile.add_argument(
        "--pending-attestation",
        action="store_true",
        help="compare before the declaration arrives; entry digests come from "
        "the entry directory's unpack_receipt.json and the audit cannot pass",
    )
    reconcile.add_argument("--manual-2005", type=Path, default=DEFAULT_MYCO_SEED)
    reconcile.add_argument("--manual-2019", type=Path, default=DEFAULT_VET2019_SEED)
    reconcile.add_argument("--manual-2022", type=Path, default=DEFAULT_VET2022_SEED)
    reconcile.add_argument("--adjudication", type=Path)
    reconcile.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def _task(
    *,
    batch_id: str,
    source_order: int,
    section_number: str,
    pdf_page: int,
    printed_page: int,
    printed_table: int,
    printed_row: int,
    continued: bool = False,
) -> dict[str, str]:
    prefix = {
        "MYC2005": "BR-MYC2005",
        "VET2019": "BR-VET2019",
        "VET2022": "BR-VET2022",
    }[batch_id]
    return {
        "blind_record_id": f"{prefix}-{source_order:03d}",
        "construction_seed_row": str(source_order),
        "source_order": str(source_order),
        "source_id": CONTRACT_BY_BATCH[batch_id].source_id,
        "section_number": section_number,
        "pdf_page": str(pdf_page),
        "printed_page": str(printed_page),
        "printed_table": str(printed_table),
        "printed_row": str(printed_row),
        "continued_from_previous_page": str(continued).lower(),
    }


def _locator_contract_sha256(tasks: dict[str, list[dict[str, str]]]) -> str:
    payload = {
        batch_id: [
            {field: row[field] for field in LOCATOR_CONTRACT_FIELDS}
            for row in tasks[batch_id]
        ]
        for batch_id in ("MYC2005", "VET2019", "VET2022")
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_tasks() -> dict[str, list[dict[str, str]]]:
    myco: list[dict[str, str]] = []
    order = 0
    for table, count, pdf_page, printed_page in (
        (1, 4, 3, 1),
        (2, 2, 4, 2),
        (3, 2, 4, 2),
        (4, 1, 4, 2),
    ):
        for printed_row in range(1, count + 1):
            order += 1
            myco.append(
                _task(
                    batch_id="MYC2005",
                    source_order=order,
                    section_number=f"4.{table}",
                    pdf_page=pdf_page,
                    printed_page=printed_page,
                    printed_table=table,
                    printed_row=printed_row,
                )
            )

    vet2019: list[dict[str, str]] = []
    order = 0
    for table, start, count, pdf_page, printed_page in (
        (26, 1, 5, 19, 10),
        (26, 6, 2, 20, 11),
        (38, 1, 3, 23, 14),
        (38, 4, 3, 24, 15),
    ):
        for printed_row in range(start, start + count):
            order += 1
            vet2019.append(
                _task(
                    batch_id="VET2019",
                    source_order=order,
                    section_number=f"4.1.{table}",
                    pdf_page=pdf_page,
                    printed_page=printed_page,
                    printed_table=table,
                    printed_row=printed_row,
                    continued=printed_row > 5 if table == 26 else printed_row > 3,
                )
            )

    if len(VET2022_ROW_COUNTS) != 41 or sum(VET2022_ROW_COUNTS) != 122:
        raise AuditError("invalid GB 31650.1-2022 table-row contract")
    vet2022: list[dict[str, str]] = []
    order = 0
    for table, count in enumerate(VET2022_ROW_COUNTS, start=1):
        pdf_page = VET2022_TABLE_PAGES[table]
        for printed_row in range(1, count + 1):
            order += 1
            vet2022.append(
                _task(
                    batch_id="VET2022",
                    source_order=order,
                    section_number=f"4.{table}",
                    pdf_page=pdf_page,
                    printed_page=pdf_page - 4,
                    printed_table=table,
                    printed_row=printed_row,
                )
            )

    tasks = {"MYC2005": myco, "VET2019": vet2019, "VET2022": vet2022}
    all_ids = [row["blind_record_id"] for rows in tasks.values() for row in rows]
    if len(all_ids) != 144 or len(set(all_ids)) != 144:
        raise AuditError("blind task IDs are incomplete or duplicated")
    observed_locator_digest = _locator_contract_sha256(tasks)
    if observed_locator_digest != LOCATOR_CONTRACT_SHA256:
        raise AuditError(
            "blind locator contract differs: "
            f"expected {LOCATOR_CONTRACT_SHA256}, got {observed_locator_digest}"
        )
    return tasks


def _read_manifest(path: Path) -> tuple[list[dict[str, str]], tuple[str, ...]]:
    if not path.is_file():
        raise AuditError(f"source manifest is missing: {path}")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = tuple(reader.fieldnames or ())
        rows = list(reader)
    required = {
        "source_id",
        "family",
        "standard",
        "version_year",
        "source_filename",
        "sha256",
        "page_count",
        "released_limit_rows",
    }
    if not required.issubset(fields):
        raise AuditError("source manifest lacks required identity fields")
    return rows, fields


def verify_manifest(path: Path) -> dict[str, dict[str, str]]:
    rows, _fields = _read_manifest(path)
    by_id = {row["source_id"]: row for row in rows}
    if len(by_id) != len(rows):
        raise AuditError("source manifest has duplicate source IDs")
    resolved: dict[str, dict[str, str]] = {}
    for contract in SOURCE_CONTRACTS:
        row = by_id.get(contract.source_id)
        if row is None:
            raise AuditError(f"source manifest lacks {contract.source_id}")
        expected = {
            "family": contract.family,
            "standard": contract.standard,
            "version_year": contract.version_year,
            "source_filename": contract.filename,
            "sha256": contract.sha256,
            "page_count": str(contract.page_count),
            "released_limit_rows": str(contract.released_limit_rows),
        }
        differences = {
            field: (row.get(field, ""), value)
            for field, value in expected.items()
            if row.get(field, "") != value
        }
        if differences:
            raise AuditError(
                f"source identity differs for {contract.source_id}: {differences}"
            )
        resolved[contract.batch_id] = row
    return resolved


def packet_contract() -> dict[str, object]:
    """Return the material contract that defines a compatible blind packet."""
    return {
        "protocol_version": PROTOCOL_VERSION,
        "source_identities": [
            {
                "batch_id": contract.batch_id,
                "source_id": contract.source_id,
                "sha256": contract.sha256,
            }
            for contract in SOURCE_CONTRACTS
        ],
        "tasks": build_tasks(),
        "template_fields": {
            "MYC2005": MYCO_TEMPLATE_FIELDS,
            "VET2019": VET_TEMPLATE_FIELDS,
            "VET2022": VET_TEMPLATE_FIELDS,
        },
        "comparison_rules": COMPARISON_RULE_CONTRACT,
        "entry_statuses": ("transcribed", "illegible"),
        "adjudication_error_sources": ADJUDICATION_ERROR_SOURCES,
        "confirmation_statement": CONFIRMATION_STATEMENT,
    }


def packet_contract_sha256() -> str:
    encoded = json.dumps(
        packet_contract(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def packet_id() -> str:
    suffix = packet_contract_sha256()[:16]
    return f"BR144-v{PROTOCOL_VERSION}-{suffix}"


def _blank_template_rows(
    tasks: list[dict[str, str]], entry_fields: tuple[str, ...]
) -> list[dict[str, str]]:
    return [
        {
            **{field: task[field] for field in LOCATOR_FIELDS},
            "entry_status": "",
            **{field: "" for field in entry_fields},
            "reviewer_note": "",
        }
        for task in tasks
    ]


def _write_text_atomic(path: Path, text: str) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        prefix=f".{path.name}.",
        suffix=".partial",
        dir=path.parent,
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        stream.write(text)
    temporary.replace(path)
    return file_metadata(path)


def _write_csv_atomic(
    path: Path,
    fields: tuple[str, ...],
    rows: list[dict[str, str]],
    *,
    expected_rows: int,
) -> dict[str, object]:
    """Write a deterministic UTF-8-BOM CSV with repository-friendly LF lines."""
    if len(rows) != expected_rows:
        raise AuditError(
            f"unexpected output row count for {path.name}: "
            f"expected {expected_rows}, got {len(rows)}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8-sig",
        newline="",
        prefix=f".{path.name}.",
        suffix=".partial",
        dir=path.parent,
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)
    metadata = file_metadata(path)
    metadata["rows"] = len(rows)
    return metadata


def _protocol_text(identifier: str) -> str:
    return f"""# Blind re-entry protocol for 144 manually transcribed records

- Packet ID: `{identifier}`
- Protocol version: `{PROTOCOL_VERSION}`
- Status: awaiting a real independent reviewer

This packet targets every record created through author-only manual transcription:
9 GB 2761-2005 rows, 13 GB 31650-2019 page-break rows and all 122 GB
31650.1-2022 rows. It does not validate the other 46,193 released records and does
not support a dataset-wide field-error estimate.

## Blindness boundary

Give the reviewer only this directory and privately supplied copies of the three
source PDFs after the custodian has checked their SHA-256 digests against
`batch_manifest.csv`. Do not provide the construction seeds, release CSVs,
current release record IDs, earlier comparison output or author-entered values.
The same templates may instead be supplied as the value-free workbook written by
`Program/Clean/261024_reviewer_handoff.py build`, whose locator cells are locked.
The directory must contain exactly `packet_manifest.json` and the files listed
under its `files` object; the generator refuses a non-empty output directory.
The source pages necessarily display the printed values and are the permitted
evidence. Source-page images are excluded from this repository and from the
public data deposit because the standards retain their original rights.

The 17 relevant PDF pages are:

- SRC0012: PDF pages 3-4, printed pages 1-2, Tables 1-4.
- SRC0016: PDF pages 19-20 and 23-24, printed pages 10-11 and 14-15,
  Tables 26 and 38. Section 4.1.38.3 says Table 39, while the visible table title
  is Table 38; use the visible title recorded in the template.
- SRC0017: PDF pages 5-15, printed pages 1-11, Tables 1-41.

## Reviewer instructions

1. Work in source order and retain the printed wording, punctuation, qualifiers,
   numeric representation and unit. For merged cells, repeat the inherited food
   or animal label on every data row.
2. Do not change any prefilled locator column. Set `entry_status` to
   `transcribed` or `illegible`. An illegible row requires a reviewer note and
   all raw-entry fields must remain blank.
3. Complete every raw-entry field appropriate to the template. English drug names
   belong in `drug_en_raw`; do not replace a printed multi-name heading with a
   preferred database name.
4. Freeze the three completed CSVs before any comparison. Record their SHA-256
   digests in `reviewer_attestation.json`, complete the independence fields and
   set `confirmation` to `{CONFIRMATION}`.
5. Return the three CSVs and the attestation together. Keep the source PDFs and
   page images outside the returned directory.

When the workbook route is used, the reviewer instead returns the completed
workbook with a declaration form that gives the reviewer's role and completion
date and confirms each independence item; the custodian keeps the returning
message as the record. On receipt, and before any comparison, the custodian
records the workbook's SHA-256 digest, converts it with
`261024_reviewer_handoff.py unpack` (which rejects any changed locator cell) and
transcribes the declaration and the resulting CSV digests into the attestation,
where `reviewer_id` is a stable pseudonymous code.

## Reconciliation

Only after the reviewer has frozen and returned the entry files may the data
custodian run:

```text
python3 Program/Clean/260716_blind_manual_reentry.py reconcile \\
  --entry-dir <completed-entry-directory> \\
  --attestation <completed-entry-directory>/reviewer_attestation.json \\
  --output-dir Data/Interim/manual_reentry/reconciliation
```

The output directory must be new or empty. Preserve each reconciliation run in
its own directory. If the first run reports differences, copy and complete the
generated adjudication template, then rerun into another new directory with
`--adjudication <completed-adjudication.csv>`.

The comparison preserves both raw strings. Predeclared normalisation is limited
to Unicode NFKC, whitespace collapsing, English case-folding, micro-sign glyph
equivalence and Decimal-equivalent numeric strings. Substance composition,
food scope, animal qualifiers and tissue wording are never deleted or aliased.

Any missing or disagreeing field is written to
`blind_reentry_adjudication_template.csv`. The construction seeds remain
read-only. The allowed adjudication outcomes are:

- `construction_confirmed` with `error_source=reentry`: the printed source
  supports the construction value; copy that exact raw value to `adjudicated_raw`.
- `reentry_confirmed` with `error_source=construction`: the source supports the
  blind re-entry; copy that exact raw value to `adjudicated_raw`.
- `corrected_value` with `error_source=both`: the source supports a third value.
- `unresolved` with `error_source=unresolved`: leave `adjudicated_raw` blank.

Every adjudication row also requires an adjudicator, ISO date and source-based
note. From protocol 1.2 the author adjudicates against the printed source page;
the adjudicator must not be the independent re-entry reviewer, and each note
names the PDF page and the reason for the outcome. A run can pass after
adjudication only when no field is missing and every disagreement is resolved as
`construction_confirmed`. If adjudication identifies a construction error,
correct the relevant seed in a separate reviewed commit, rebuild downstream
files and rerun the full release validator before updating the manuscript or
closing the provenance gap.
"""


def _initialise_empty_output_dir(path: Path) -> None:
    try:
        if path.is_symlink():
            raise AuditError(f"output directory must not be a symlink: {path}")
        if path.exists():
            if not path.is_dir():
                raise AuditError(f"output path is not a directory: {path}")
            if any(path.iterdir()):
                raise AuditError(f"output directory must be empty: {path}")
        else:
            path.mkdir(parents=True)
    except OSError as error:
        raise AuditError(
            f"cannot initialise output directory {path}: {error}"
        ) from error


def prepare_packet(source_manifest: Path, output_dir: Path) -> dict[str, object]:
    sources = verify_manifest(source_manifest)
    tasks = build_tasks()
    identifier = packet_id()
    _initialise_empty_output_dir(output_dir)

    batch_rows = []
    page_descriptions = {
        "MYC2005": ("3-4", "1-2", "1-4"),
        "VET2019": ("19-20;23-24", "10-11;14-15", "26;38"),
        "VET2022": ("5-15", "1-11", "1-41"),
    }
    for contract in SOURCE_CONTRACTS:
        pdf_pages, printed_pages, tables = page_descriptions[contract.batch_id]
        batch_rows.append(
            {
                "packet_id": identifier,
                "batch_id": contract.batch_id,
                "source_id": contract.source_id,
                "standard": contract.standard,
                "version_year": contract.version_year,
                "source_filename": contract.filename,
                "source_sha256": contract.sha256,
                "pdf_pages": pdf_pages,
                "printed_pages": printed_pages,
                "tables": tables,
                "task_count": str(len(tasks[contract.batch_id])),
                "template_filename": contract.template_filename,
            }
        )

    outputs: dict[str, dict[str, object]] = {}
    outputs["batch_manifest.csv"] = _write_csv_atomic(
        output_dir / "batch_manifest.csv",
        BATCH_MANIFEST_FIELDS,
        batch_rows,
        expected_rows=3,
    )
    for batch_id, fields in (
        ("MYC2005", MYCO_TEMPLATE_FIELDS),
        ("VET2019", VET_TEMPLATE_FIELDS),
        ("VET2022", VET_TEMPLATE_FIELDS),
    ):
        contract = CONTRACT_BY_BATCH[batch_id]
        entry_fields = MYCO_ENTRY_FIELDS if batch_id == "MYC2005" else VET_ENTRY_FIELDS
        outputs[contract.template_filename] = _write_csv_atomic(
            output_dir / contract.template_filename,
            fields,
            _blank_template_rows(tasks[batch_id], entry_fields),
            expected_rows=len(tasks[batch_id]),
        )

    attestation = {
        "packet_id": identifier,
        "protocol_version": PROTOCOL_VERSION,
        "packet_contract_sha256": packet_contract_sha256(),
        "initial_transcriber_id": INITIAL_TRANSCRIBER_ID,
        "reviewer_id": "",
        "reviewer_role": "",
        "review_date": "",
        "independent_person": None,
        "no_access_to_construction_seeds": None,
        "no_access_to_release_values": None,
        "source_files_verified_against_manifest": None,
        "completed_entry_sha256": {
            contract.template_filename: "" for contract in SOURCE_CONTRACTS
        },
        "confirmation_statement": CONFIRMATION_STATEMENT,
        "confirmation": "",
    }
    outputs["reviewer_attestation.json"] = write_json_atomic(
        output_dir / "reviewer_attestation.json", attestation
    )
    outputs["README.md"] = _write_text_atomic(
        output_dir / "README.md", _protocol_text(identifier)
    )

    manifest_payload = {
        "packet_id": identifier,
        "protocol_version": PROTOCOL_VERSION,
        "packet_contract_sha256": packet_contract_sha256(),
        "locator_contract_sha256": LOCATOR_CONTRACT_SHA256,
        "status": "awaiting_independent_reentry",
        "provenance_gap": {"status": "open", "records": 144},
        "task_counts": {
            "total": 144,
            "MYC2005": 9,
            "VET2019": 13,
            "VET2022": 122,
        },
        "source_manifest": file_metadata(source_manifest),
        "source_identities": [
            {
                "batch_id": contract.batch_id,
                "source_id": contract.source_id,
                "filename": sources[contract.batch_id]["source_filename"],
                "sha256": contract.sha256,
            }
            for contract in SOURCE_CONTRACTS
        ],
        "blindness": {
            "construction_seed_files_read": False,
            "release_tables_read": False,
            "expected_values_in_templates": False,
            "source_page_images_included": False,
        },
        "files": outputs,
        "manuscript_claim_eligible": False,
    }
    outputs["packet_manifest.json"] = write_json_atomic(
        output_dir / "packet_manifest.json", manifest_payload
    )
    return manifest_payload


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AuditError(f"cannot load rebuild contract: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_construction_rows(
    manual_2005: Path, manual_2019: Path, manual_2022: Path
) -> tuple[dict[str, list[dict[str, str]]], dict[str, dict[str, object]]]:
    clean_dir = Path(__file__).resolve().parent
    myco_module = _load_module(
        clean_dir / "260716_rebuild_mycotoxin.py", "blind_audit_rebuild_mycotoxin"
    )
    vet_module = _load_module(
        clean_dir / "260716_rebuild_vetdrug.py", "blind_audit_rebuild_vetdrug"
    )
    inputs = {
        "MYC2005": (manual_2005, myco_module.MANUAL_2005_SPEC),
        "VET2019": (manual_2019, vet_module.MANUAL_2019_SPEC),
        "VET2022": (manual_2022, vet_module.MANUAL_2022_SPEC),
    }
    rows = {
        batch_id: load_locked_csv(path, spec)
        for batch_id, (path, spec) in inputs.items()
    }
    metadata = {
        batch_id: file_metadata(path) for batch_id, (path, _spec) in inputs.items()
    }
    return rows, metadata


def _read_entry_file(
    path: Path,
    fields: tuple[str, ...],
    expected_tasks: list[dict[str, str]],
    entry_fields: tuple[str, ...],
    expected_sha256: str,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    if not path.is_file():
        raise AuditError(f"completed entry file is missing: {path}")
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        raise AuditError(f"cannot read completed entry file: {path}") from error
    observed_sha256 = hashlib.sha256(raw).hexdigest()
    if observed_sha256 != expected_sha256:
        raise AuditError(f"attested entry digest differs for {path.name}")
    with StringIO(text, newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != fields:
            raise AuditError(f"unexpected entry schema for {path.name}")
        rows = list(reader)
    if len(rows) != len(expected_tasks):
        raise AuditError(f"unexpected entry row count for {path.name}: {len(rows)}")
    by_id = {row["blind_record_id"]: row for row in rows}
    if len(by_id) != len(rows):
        raise AuditError(f"duplicate blind record ID in {path.name}")
    expected_by_id = {row["blind_record_id"]: row for row in expected_tasks}
    if set(by_id) != set(expected_by_id):
        raise AuditError(f"blind record IDs differ in {path.name}")
    for blind_id, row in by_id.items():
        expected = expected_by_id[blind_id]
        changed = {
            field: (row[field], expected[field])
            for field in LOCATOR_FIELDS
            if row[field] != expected[field]
        }
        if changed:
            raise AuditError(f"prefilled locator changed for {blind_id}: {changed}")
        if row["entry_status"] not in {"transcribed", "illegible"}:
            raise AuditError(f"invalid entry_status for {blind_id}")
        if row["entry_status"] == "transcribed" and any(
            not row[field].strip() for field in entry_fields
        ):
            raise AuditError(f"blank required entry field for {blind_id}")
        if row["entry_status"] == "illegible" and not row["reviewer_note"].strip():
            raise AuditError(f"illegible row lacks reviewer_note for {blind_id}")
        if row["entry_status"] == "illegible" and any(
            row[field].strip() for field in entry_fields
        ):
            raise AuditError(
                f"illegible row contains transcribed values for {blind_id}"
            )
    ordered = [by_id[row["blind_record_id"]] for row in expected_tasks]
    metadata = {
        "filename": path.name,
        "file_size_bytes": len(raw),
        "sha256": observed_sha256,
    }
    return ordered, metadata


def _validate_iso_date(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuditError(f"attestation lacks {field}")
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise AuditError(f"attestation has invalid {field}") from error
    return value


def validate_attestation(
    path: Path, identifier: str, entry_paths: dict[str, Path]
) -> tuple[dict[str, object], dict[str, object]]:
    if not path.is_file():
        raise AuditError(f"reviewer attestation is missing: {path}")
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise AuditError("reviewer attestation is invalid JSON") from error
    if payload.get("packet_id") != identifier:
        raise AuditError("attestation packet_id differs")
    if payload.get("protocol_version") != PROTOCOL_VERSION:
        raise AuditError("attestation protocol version differs")
    if payload.get("packet_contract_sha256") != packet_contract_sha256():
        raise AuditError("attestation packet contract differs")
    if payload.get("initial_transcriber_id") != INITIAL_TRANSCRIBER_ID:
        raise AuditError("attestation initial transcriber differs")
    reviewer_id = payload.get("reviewer_id")
    if not isinstance(reviewer_id, str) or not reviewer_id.strip():
        raise AuditError("attestation lacks reviewer_id")
    if reviewer_id.strip().casefold() == INITIAL_TRANSCRIBER_ID.casefold():
        raise AuditError("reviewer must differ from the initial transcriber")
    if (
        not isinstance(payload.get("reviewer_role"), str)
        or not payload["reviewer_role"].strip()
    ):
        raise AuditError("attestation lacks reviewer_role")
    _validate_iso_date(payload.get("review_date"), "review_date")
    for field in (
        "independent_person",
        "no_access_to_construction_seeds",
        "no_access_to_release_values",
        "source_files_verified_against_manifest",
    ):
        if payload.get(field) is not True:
            raise AuditError(f"attestation does not confirm {field}")
    if payload.get("confirmation_statement") != CONFIRMATION_STATEMENT:
        raise AuditError("attestation confirmation statement differs")
    if payload.get("confirmation") != CONFIRMATION:
        raise AuditError("attestation confirmation is incomplete")
    digests = payload.get("completed_entry_sha256")
    if not isinstance(digests, dict) or set(digests) != set(entry_paths):
        raise AuditError("attestation entry digest inventory differs")
    for filename in entry_paths:
        digest = digests.get(filename)
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise AuditError(f"attestation has invalid entry digest for {filename}")
    metadata = {
        "filename": path.name,
        "file_size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    return payload, metadata


def receipt_digests(
    path: Path, entry_paths: dict[str, Path]
) -> tuple[dict[str, str], dict[str, object]]:
    """Entry digests frozen when the returned workbook was unpacked."""
    if not path.is_file():
        raise AuditError(f"unpack receipt is missing: {path}")
    raw = path.read_bytes()
    try:
        digests = json.loads(raw.decode("utf-8-sig"))["csv"]
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as error:
        raise AuditError("unpack receipt is invalid") from error
    if not set(entry_paths) <= set(digests):
        raise AuditError("unpack receipt lacks an entry file")
    selected = {filename: digests[filename] for filename in entry_paths}
    for filename, digest in selected.items():
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise AuditError(f"unpack receipt has invalid entry digest for {filename}")
    metadata = {
        "filename": path.name,
        "file_size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    return selected, metadata


def _normalise_text(value: str, *, casefold: bool = False) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.casefold() if casefold else value


def _normalise_decimal(value: str) -> str:
    value = _normalise_text(value)
    try:
        decimal = Decimal(value)
    except InvalidOperation:
        return value
    if not decimal.is_finite():
        return value
    normalised = format(decimal.normalize(), "f")
    return "0" if normalised in {"-0", ""} else normalised


def _normalise_unit(value: str) -> str:
    return _normalise_text(value, casefold=True).replace("µ", "μ")


def _comparison_rule(field: str) -> tuple[str, object]:
    if field == "limit_value_raw":
        return COMPARISON_RULE_CONTRACT[field], _normalise_decimal
    if field == "unit_raw":
        return COMPARISON_RULE_CONTRACT[field], _normalise_unit
    if field == "drug_en_raw":
        return COMPARISON_RULE_CONTRACT[field], lambda value: _normalise_text(
            value, casefold=True
        )
    return COMPARISON_RULE_CONTRACT["default"], _normalise_text


def _expected_values(
    tasks: dict[str, list[dict[str, str]]],
    construction: dict[str, list[dict[str, str]]],
) -> dict[str, dict[str, str]]:
    field_maps = {
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
    expected: dict[str, dict[str, str]] = {}
    for batch_id, task_rows in tasks.items():
        seed_rows = construction[batch_id]
        if len(seed_rows) != len(task_rows):
            raise AuditError(f"construction row count differs for {batch_id}")
        seed_by_row = {
            str(row_number): seed for row_number, seed in enumerate(seed_rows, start=1)
        }
        mapping = field_maps[batch_id]
        for task in task_rows:
            seed_row = task["construction_seed_row"]
            if seed_row not in seed_by_row:
                raise AuditError(
                    f"construction seed row {seed_row} is missing for {batch_id}"
                )
            seed = seed_by_row[seed_row]
            expected[task["blind_record_id"]] = {
                entry_field: seed[seed_field]
                for entry_field, seed_field in mapping.items()
            }
    return expected


def _compare_entries(
    tasks: dict[str, list[dict[str, str]]],
    entries: dict[str, list[dict[str, str]]],
    expected: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for batch_id, task_rows in tasks.items():
        entry_by_id = {row["blind_record_id"]: row for row in entries[batch_id]}
        fields = MYCO_ENTRY_FIELDS if batch_id == "MYC2005" else VET_ENTRY_FIELDS
        for task in task_rows:
            blind_id = task["blind_record_id"]
            entry = entry_by_id[blind_id]
            for field in fields:
                construction_raw = expected[blind_id][field]
                reentry_raw = entry[field]
                rule, normaliser = _comparison_rule(field)
                construction_normalised = normaliser(construction_raw)
                reentry_normalised = normaliser(reentry_raw)
                if reentry_raw == construction_raw:
                    status = "exact_match"
                elif not reentry_raw.strip():
                    status = "missing"
                elif reentry_normalised == construction_normalised:
                    status = "normalised_match"
                else:
                    status = "disagreement"
                rows.append(
                    {
                        "blind_record_id": blind_id,
                        "batch_id": batch_id,
                        "source_id": task["source_id"],
                        "source_order": task["source_order"],
                        "pdf_page": task["pdf_page"],
                        "printed_table": task["printed_table"],
                        "printed_row": task["printed_row"],
                        "field": field,
                        "construction_raw": construction_raw,
                        "reentry_raw": reentry_raw,
                        "construction_normalised": construction_normalised,
                        "reentry_normalised": reentry_normalised,
                        "comparison_rule": rule,
                        "comparison_status": status,
                        "adjudication_status": "",
                        "adjudicated_raw": "",
                        "error_source": "",
                        "adjudicator_id": "",
                        "adjudication_date": "",
                        "adjudication_note": "",
                    }
                )
    if len(rows) != 846:
        raise AuditError(f"field comparison count differs: {len(rows)}")
    return rows


def _read_adjudication(
    path: Path | None,
    unresolved: list[dict[str, str]],
    *,
    excluded_adjudicator_ids: set[str],
) -> tuple[
    dict[tuple[str, str], dict[str, str]],
    dict[str, object] | None,
]:
    if path is None:
        return {}, None
    if not path.is_file():
        raise AuditError(f"adjudication file is missing: {path}")
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        raise AuditError(f"cannot read adjudication file: {path}") from error
    with StringIO(text, newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != ADJUDICATION_FIELDS:
            raise AuditError("unexpected adjudication schema")
        rows = list(reader)
    by_key = {(row["blind_record_id"], row["field"]): row for row in rows}
    if len(by_key) != len(rows):
        raise AuditError("duplicate adjudication key")
    unresolved_by_key = {
        (row["blind_record_id"], row["field"]): row for row in unresolved
    }
    expected_keys = set(unresolved_by_key)
    if set(by_key) != expected_keys:
        raise AuditError("adjudication keys do not match unresolved comparisons")
    for key, row in by_key.items():
        status = row["adjudication_status"]
        if (
            status not in ADJUDICATION_ERROR_SOURCES
            or row["error_source"] != ADJUDICATION_ERROR_SOURCES[status]
        ):
            raise AuditError(f"invalid adjudication status for {key}")
        adjudicator_id = row["adjudicator_id"].strip()
        if not adjudicator_id or not row["adjudication_note"].strip():
            raise AuditError(f"incomplete adjudication metadata for {key}")
        if adjudicator_id.casefold() in excluded_adjudicator_ids:
            raise AuditError(f"adjudicator must be independent for {key}")
        _validate_iso_date(row["adjudication_date"], "adjudication_date")
        adjudicated_raw = row["adjudicated_raw"]
        if status != "unresolved" and not adjudicated_raw.strip():
            raise AuditError(f"adjudicated value is blank for {key}")
        comparison = unresolved_by_key[key]
        confirmed_field = {
            "construction_confirmed": "construction_raw",
            "reentry_confirmed": "reentry_raw",
        }.get(status)
        if confirmed_field and adjudicated_raw != comparison[confirmed_field]:
            raise AuditError(f"adjudicated value differs from confirmed side for {key}")
        if status == "unresolved" and adjudicated_raw.strip():
            raise AuditError(f"unresolved adjudication has a value for {key}")
    metadata = {
        "filename": path.name,
        "file_size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    return by_key, metadata


def _apply_adjudication(
    comparisons: list[dict[str, str]],
    adjudication: dict[tuple[str, str], dict[str, str]],
) -> None:
    for row in comparisons:
        key = (row["blind_record_id"], row["field"])
        if key in adjudication:
            for field in ADJUDICATION_FIELDS[2:]:
                row[field] = adjudication[key][field]


def reconcile_packet(
    *,
    source_manifest: Path,
    entry_dir: Path,
    attestation_path: Path | None,
    manual_2005: Path,
    manual_2019: Path,
    manual_2022: Path,
    adjudication_path: Path | None,
    output_dir: Path,
) -> dict[str, object]:
    _initialise_empty_output_dir(output_dir)
    verify_manifest(source_manifest)
    tasks = build_tasks()
    identifier = packet_id()
    entry_paths = {
        contract.template_filename: entry_dir / contract.template_filename
        for contract in SOURCE_CONTRACTS
    }
    if attestation_path is None:
        # Declaration pending: compare now, but the audit cannot pass.
        attestation, attestation_metadata = None, None
        completed_digests, receipt_metadata = receipt_digests(
            entry_dir / "unpack_receipt.json", entry_paths
        )
    else:
        attestation, attestation_metadata = validate_attestation(
            attestation_path, identifier, entry_paths
        )
        completed_digests = attestation["completed_entry_sha256"]
    if not isinstance(completed_digests, dict):
        raise AuditError("attestation entry digest inventory differs")
    entries: dict[str, list[dict[str, str]]] = {}
    entry_metadata: dict[str, dict[str, object]] = {}
    for batch_id, template_fields, entry_fields in (
        ("MYC2005", MYCO_TEMPLATE_FIELDS, MYCO_ENTRY_FIELDS),
        ("VET2019", VET_TEMPLATE_FIELDS, VET_ENTRY_FIELDS),
        ("VET2022", VET_TEMPLATE_FIELDS, VET_ENTRY_FIELDS),
    ):
        filename = CONTRACT_BY_BATCH[batch_id].template_filename
        rows, metadata = _read_entry_file(
            entry_paths[filename],
            template_fields,
            tasks[batch_id],
            entry_fields,
            str(completed_digests[filename]),
        )
        entries[batch_id] = rows
        entry_metadata[filename] = metadata
    construction, seed_metadata = _load_construction_rows(
        manual_2005, manual_2019, manual_2022
    )
    expected = _expected_values(tasks, construction)
    comparisons = _compare_entries(tasks, entries, expected)
    unresolved = [
        row
        for row in comparisons
        if row["comparison_status"] in {"disagreement", "missing"}
    ]
    adjudication, adjudication_input_metadata = _read_adjudication(
        adjudication_path,
        unresolved,
        excluded_adjudicator_ids=(
            {str(attestation["reviewer_id"]).strip().casefold()} if attestation else set()
        ),
    )
    _apply_adjudication(comparisons, adjudication)

    status_counts = {
        status: sum(row["comparison_status"] == status for row in comparisons)
        for status in ("exact_match", "normalised_match", "disagreement", "missing")
    }
    affected_records = {row["blind_record_id"] for row in unresolved}
    adjudication_counts = {
        status: sum(row.get("adjudication_status") == status for row in comparisons)
        for status in (
            "construction_confirmed",
            "reentry_confirmed",
            "corrected_value",
            "unresolved",
        )
    }
    missing_exists = status_counts["missing"] > 0
    construction_error = (
        adjudication_counts["reentry_confirmed"]
        + adjudication_counts["corrected_value"]
        > 0
    )
    all_disagreements_resolved_as_reentry = all(
        row["comparison_status"] not in {"disagreement", "missing"}
        or row["adjudication_status"] == "construction_confirmed"
        for row in comparisons
    )
    entries_resolved = (
        not missing_exists
        and (not unresolved or all_disagreements_resolved_as_reentry)
        and not construction_error
    )
    gap_closed = entries_resolved and attestation is not None
    if gap_closed:
        audit_status = "pass"
    elif construction_error:
        audit_status = "correction_required"
    elif not entries_resolved:
        audit_status = "review_required"
    else:
        audit_status = "attestation_pending"

    comparison_metadata = _write_csv_atomic(
        output_dir / "blind_reentry_field_comparison.csv",
        COMPARISON_FIELDS,
        comparisons,
        expected_rows=846,
    )
    adjudication_template = [
        {
            "blind_record_id": row["blind_record_id"],
            "field": row["field"],
            "adjudication_status": "",
            "adjudicated_raw": "",
            "error_source": "",
            "adjudicator_id": "",
            "adjudication_date": "",
            "adjudication_note": "",
        }
        for row in unresolved
        if not row["adjudication_status"]
    ]
    adjudication_metadata = _write_csv_atomic(
        output_dir / "blind_reentry_adjudication_template.csv",
        ADJUDICATION_FIELDS,
        adjudication_template,
        expected_rows=len(adjudication_template),
    )
    report = {
        "protocol_version": PROTOCOL_VERSION,
        "packet_id": identifier,
        "packet_contract_sha256": packet_contract_sha256(),
        "locator_contract_sha256": LOCATOR_CONTRACT_SHA256,
        "status": audit_status,
        "scope": {
            "records": 144,
            "fields": 846,
            "released_dataset_records": 46337,
            "interpretation": (
                "Targeted audit of all author-manually-transcribed records; "
                "not a dataset-wide field-error estimate."
            ),
        },
        "provenance_gap": {
            "status": "closed" if gap_closed else "open",
            "records": 144,
            "correction_required": construction_error,
        },
        "comparison_counts": status_counts,
        "records_with_initial_disagreement_or_missing": len(affected_records),
        "adjudication_counts": adjudication_counts,
        "attestation": {
            "reviewer_id": attestation["reviewer_id"],
            "reviewer_role": attestation["reviewer_role"],
            "review_date": attestation["review_date"],
            "independent_person": True,
            "entry_files": entry_metadata,
            "attestation_file": attestation_metadata,
        } if attestation else {
            "status": "pending",
            "entry_files": entry_metadata,
            "entry_digest_source": receipt_metadata,
        },
        "inputs": {
            "source_manifest": file_metadata(source_manifest),
            "construction_seeds": seed_metadata,
            "adjudication": adjudication_input_metadata,
        },
        "outputs": {
            "field_comparison": comparison_metadata,
            "adjudication_template": adjudication_metadata,
        },
    }
    write_json_atomic(output_dir / "blind_reentry_report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "prepare":
            payload = prepare_packet(args.source_manifest, args.output_dir)
            print(
                f"prepared {payload['task_counts']['total']} blind tasks: "
                f"{args.output_dir}"
            )
            return 0
        attestation = (
            None
            if args.pending_attestation
            else args.attestation or args.entry_dir / "reviewer_attestation.json"
        )
        report = reconcile_packet(
            source_manifest=args.source_manifest,
            entry_dir=args.entry_dir,
            attestation_path=attestation,
            manual_2005=args.manual_2005,
            manual_2019=args.manual_2019,
            manual_2022=args.manual_2022,
            adjudication_path=args.adjudication,
            output_dir=args.output_dir,
        )
        print(f"blind re-entry audit {report['status']}: {args.output_dir}")
        return 0 if report["status"] == "pass" else 1
    except (AuditError, ReplayError) as error:
        print(f"blind re-entry audit error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
