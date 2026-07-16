#!/usr/bin/env python3
"""Shared fail-closed utilities for the legacy family rebuilds."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
from typing import Any, Iterable, Sequence
from urllib.parse import urlparse


class ReplayError(ValueError):
    """Raised when a frozen input or external extraction step has changed."""


@dataclass(frozen=True)
class CSVSpec:
    """Identity and structural requirements for a frozen CSV input."""

    fields: tuple[str, ...]
    rows: int
    unique_key: tuple[str, ...]
    sha256: str


LEGACY_EDITION_CONTRACTS = {
    ("mycotoxin", "2005"): {
        "standard": "GB 2761",
        "source_format": "pdf",
        "release_status": "extracted",
        "released_limit_rows": "9",
        "extraction_mode": "manual_page_image_transcription",
        "document_identity": "full_standard",
    },
    ("mycotoxin", "2011"): {
        "standard": "GB 2761",
        "source_format": "pdf",
        "release_status": "extracted",
        "released_limit_rows": "22",
        "extraction_mode": "pdf_text_layer",
        "document_identity": "full_standard",
    },
    ("mycotoxin", "2017"): {
        "standard": "GB 2761",
        "source_format": "pdf",
        "release_status": "extracted",
        "released_limit_rows": "30",
        "extraction_mode": "pdf_text_layer",
        "document_identity": "full_standard",
    },
    ("veterinary_drug", "2002"): {
        "standard": "MOA Announcement 235",
        "source_format": "doc",
        "release_status": "extracted",
        "released_limit_rows": "551",
        "extraction_mode": "word_table_stream",
        "document_identity": "official_announcement",
    },
    ("veterinary_drug", "2019"): {
        "standard": "GB 31650",
        "source_format": "pdf",
        "release_status": "extracted",
        "released_limit_rows": "692",
        "extraction_mode": "pdf_text_with_manual_page_break_rows",
        "document_identity": "full_standard",
    },
    ("veterinary_drug", "2022"): {
        "standard": "GB 31650.1",
        "source_format": "pdf",
        "release_status": "extracted",
        "released_limit_rows": "122",
        "extraction_mode": "manual_page_image_transcription",
        "document_identity": "supplementary_standard",
    },
}

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


def sha256_file(path: str | Path) -> str:
    """Return a streaming SHA-256 digest."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_metadata(path: str | Path) -> dict[str, Any]:
    """Return portable metadata for a replay input or output."""

    resolved = Path(path)
    return {
        "filename": resolved.name,
        "file_size_bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }


def load_locked_csv(path: str | Path, spec: CSVSpec) -> list[dict[str, str]]:
    """Read a required CSV after digest, schema, row-count and key checks."""

    path = Path(path)
    if not path.is_file():
        raise ReplayError(f"required frozen CSV is missing: {path}")
    observed_digest = sha256_file(path)
    if observed_digest != spec.sha256:
        raise ReplayError(
            f"frozen CSV digest differs for {path.name}: "
            f"expected {spec.sha256}, got {observed_digest}"
        )
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != spec.fields:
            raise ReplayError(
                f"unexpected CSV schema for {path.name}: {reader.fieldnames}"
            )
        rows = list(reader)
    if len(rows) != spec.rows:
        raise ReplayError(
            f"unexpected row count for {path.name}: "
            f"expected {spec.rows}, got {len(rows)}"
        )
    keys = [tuple(row[field] for field in spec.unique_key) for row in rows]
    if any(not all(key) for key in keys):
        raise ReplayError(f"blank business-key component in {path.name}")
    if len(set(keys)) != len(keys):
        raise ReplayError(f"duplicate business key in {path.name}")
    return rows


def read_manifest(path: str | Path) -> list[dict[str, str]]:
    """Read a source manifest while enforcing the legacy core contract."""

    required = (
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
    path = Path(path)
    if not path.is_file():
        raise ReplayError(f"source manifest is missing: {path}")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = tuple(reader.fieldnames or ())
        missing = [field for field in required if field not in fieldnames]
        if missing or len(fieldnames) != len(set(fieldnames)):
            raise ReplayError(
                "unexpected source-manifest schema; "
                f"missing_core_fields={missing}, duplicate_headers="
                f"{len(fieldnames) != len(set(fieldnames))}"
            )
        rows = list(reader)
    if not rows:
        raise ReplayError("source manifest is empty")

    row_identities = [tuple(row[field] for field in required) for row in rows]
    if len(row_identities) != len(set(row_identities)):
        raise ReplayError("duplicate source-manifest row")
    source_ids = [row["source_id"] for row in rows]
    if len(source_ids) != len(set(source_ids)):
        raise ReplayError("duplicate source_id in source manifest")
    filenames = [row["source_filename"] for row in rows]
    if len(filenames) != len(set(filenames)):
        raise ReplayError("duplicate source_filename in source manifest")

    allowed_roles = {
        "edition_source",
        "extraction_copy",
        "identity_audit_copy",
    }
    allowed_statuses = {
        "extracted",
        "archived_unextracted",
        "identity_anchor_crosscheck",
        "excluded_from_extraction",
    }
    for row in rows:
        source_id = row["source_id"]
        filename = row["source_filename"]
        if Path(filename).name != filename or "/" in filename or "\\" in filename:
            raise ReplayError(
                f"source_filename is not a basename for {source_id}: {filename}"
            )
        try:
            size = int(row["file_size_bytes"])
        except ValueError as error:
            raise ReplayError(
                f"file_size_bytes must be positive for {source_id}"
            ) from error
        if size <= 0:
            raise ReplayError(f"file_size_bytes must be positive for {source_id}")
        if not re_fullmatch_sha256(row["sha256"]):
            raise ReplayError(f"invalid sha256 for {source_id}")
        if not row["standard"] or not row["document_identity"]:
            raise ReplayError(f"blank standard or document_identity for {source_id}")
        if not row["extraction_mode"]:
            raise ReplayError(f"blank extraction_mode for {source_id}")
        if row["source_role"] not in allowed_roles:
            raise ReplayError(f"invalid source_role for {source_id}")
        if row["release_status"] not in allowed_statuses:
            raise ReplayError(f"invalid release_status for {source_id}")
        suffix = Path(filename).suffix.lower().lstrip(".")
        if row["source_format"] not in {"pdf", "doc", "docx"}:
            raise ReplayError(f"invalid source_format for {source_id}")
        if row["source_format"] != suffix:
            raise ReplayError(f"source_format does not match filename for {source_id}")
        if not (len(row["version_year"]) == 4 and row["version_year"].isdigit()):
            raise ReplayError(f"invalid version_year for {source_id}")
        released = row["released_limit_rows"]
        status = row["release_status"]
        role = row["source_role"]
        if status == "extracted":
            if (
                role not in {"edition_source", "extraction_copy"}
                or not released.isdigit()
                or int(released) <= 0
            ):
                raise ReplayError(f"invalid released_limit_rows for {source_id}")
        elif status == "archived_unextracted":
            if role != "edition_source" or released != "0":
                raise ReplayError(f"invalid released_limit_rows for {source_id}")
        elif status == "identity_anchor_crosscheck":
            if role != "edition_source" or released:
                raise ReplayError(f"invalid released_limit_rows for {source_id}")
        elif role != "identity_audit_copy" or released:
            raise ReplayError(f"invalid released_limit_rows for {source_id}")

    by_source_id = {row["source_id"]: row for row in rows}
    has_relation_field = "related_source_id" in fieldnames
    if not has_relation_field and any(
        row["source_role"] == "extraction_copy" for row in rows
    ):
        raise ReplayError("extraction_copy requires related_source_id")
    if has_relation_field:
        for row in rows:
            source_id = row["source_id"]
            related_source_id = row["related_source_id"]
            if row["source_role"] == "edition_source":
                if related_source_id:
                    raise ReplayError(
                        f"edition source must not have related_source_id: {source_id}"
                    )
                continue
            if not related_source_id or related_source_id not in by_source_id:
                raise ReplayError(
                    f"invalid related_source_id for {source_id}: {related_source_id}"
                )
            anchor = by_source_id[related_source_id]
            if anchor["source_role"] != "edition_source" or any(
                row[field] != anchor[field]
                for field in ("family", "standard", "version_year")
            ):
                raise ReplayError(
                    f"related_source_id does not identify the same edition for "
                    f"{source_id}"
                )
    return rows


def re_fullmatch_sha256(value: str) -> bool:
    """Return whether a value is a lower-case SHA-256 digest."""

    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def validate_source_acquisition(
    rows: Sequence[dict[str, str]],
    source_metadata: Sequence[dict[str, Any]],
) -> None:
    """Match locked acquisition notes to verified source identities."""

    expected = {
        (str(source["family"]), str(source["version_year"])): source
        for source in source_metadata
    }
    observed = {(row["family"], row["version_year"]): row for row in rows}
    if len(observed) != len(rows):
        raise ReplayError("duplicate family/year in source acquisition metadata")
    if set(observed) != set(expected):
        raise ReplayError("source acquisition editions do not match verified sources")

    allowed_statuses = {
        "mismatch_with_current_official_download",
        "official_download_unavailable",
        "stable_official_url_unverified",
    }
    for key, row in observed.items():
        source = expected[key]
        if row["source_filename"] != source["filename"]:
            raise ReplayError(f"acquisition source_filename differs for {key}")
        if row["sha256"] != source["sha256"]:
            raise ReplayError(f"acquisition sha256 differs for {key}")
        if row["original_retrieval_date"] != "unrecorded":
            raise ReplayError(f"unsupported original retrieval date for {key}")
        if not _iso_date(row["url_verified_date"]):
            raise ReplayError(f"invalid URL verification date for {key}")
        status = row["byte_identity_status"]
        if status not in allowed_statuses:
            raise ReplayError(f"invalid byte identity status for {key}")
        landing = row["official_landing_url"]
        download = row["official_download_url"]
        for url in (landing, download):
            if url and not _official_government_url(url):
                raise ReplayError(f"official government URL required for {key}")
        if status == "mismatch_with_current_official_download" and not (
            landing and download
        ):
            raise ReplayError(f"mismatch status requires two official URLs for {key}")
        if status == "official_download_unavailable" and not landing:
            raise ReplayError(f"official landing URL required for {key}")
        if status == "stable_official_url_unverified" and (landing or download):
            raise ReplayError(f"unverified official URL status must leave URLs blank for {key}")
        if not row["access_notes"].strip():
            raise ReplayError(f"blank acquisition access notes for {key}")


def _iso_date(value: str) -> bool:
    parts = value.split("-")
    return (
        len(parts) == 3
        and tuple(map(len, parts)) == (4, 2, 2)
        and all(part.isdigit() for part in parts)
    )


def _official_government_url(value: str) -> bool:
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (
        hostname == "gov.cn" or hostname.endswith(".gov.cn")
    )


def verify_manifest_source(
    source_path: str | Path,
    manifest_rows: Sequence[dict[str, str]],
    *,
    family: str,
    version_year: str,
) -> dict[str, Any]:
    """Verify an explicit source path against one edition-manifest row."""

    source_path = Path(source_path)
    matches = [
        row
        for row in manifest_rows
        if row["family"] == family
        and row["version_year"] == version_year
        and row["source_role"] == "edition_source"
    ]
    if len(matches) != 1:
        raise ReplayError(
            f"expected one {family} {version_year} edition in source manifest, "
            f"found {len(matches)}"
        )
    row = matches[0]
    contract = LEGACY_EDITION_CONTRACTS.get((family, version_year))
    if contract is None:
        raise ReplayError(f"no legacy edition contract for {family} {version_year}")
    for field, expected in contract.items():
        if row[field] != expected:
            raise ReplayError(
                f"manifest {field} differs for {family} {version_year}: "
                f"expected {expected}, got {row[field]}"
            )
    if not source_path.is_file():
        raise ReplayError(f"source file is missing: {source_path}")
    if source_path.name != row["source_filename"]:
        raise ReplayError(
            f"source filename differs for {family} {version_year}: "
            f"expected {row['source_filename']}, got {source_path.name}"
        )
    observed_size = source_path.stat().st_size
    if observed_size != int(row["file_size_bytes"]):
        raise ReplayError(
            f"source size differs for {source_path.name}: "
            f"expected {row['file_size_bytes']}, got {observed_size}"
        )
    observed_digest = sha256_file(source_path)
    if observed_digest != row["sha256"]:
        raise ReplayError(
            f"source digest differs for {source_path.name}: "
            f"expected {row['sha256']}, got {observed_digest}"
        )
    return {
        "source_id": row["source_id"],
        "family": family,
        "standard": row["standard"],
        "version_year": version_year,
        "filename": source_path.name,
        "source_format": row["source_format"],
        "file_size_bytes": observed_size,
        "sha256": observed_digest,
        "release_status": row["release_status"],
        "released_limit_rows": int(row["released_limit_rows"]),
        "extraction_mode": row["extraction_mode"],
        "document_identity": row["document_identity"],
    }


def run_checked(
    command: Sequence[str | os.PathLike[str]],
    *,
    timeout: int,
) -> subprocess.CompletedProcess[bytes]:
    """Run an external command and expose a concise failure diagnostic."""

    rendered = [os.fspath(part) for part in command]
    try:
        return subprocess.run(
            rendered,
            check=True,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        stderr = getattr(error, "stderr", b"") or b""
        detail = stderr.decode("utf-8", "replace").strip() or str(error)
        raise ReplayError(f"external command failed ({rendered[0]}): {detail}") from error


def pdftotext_layout(
    source_path: str | Path,
    *,
    executable: str = "pdftotext",
) -> str:
    """Extract layout-preserving text and fail on any Poppler error."""

    completed = run_checked(
        [executable, "-layout", os.fspath(source_path), "-"],
        timeout=180,
    )
    return completed.stdout.decode("utf-8", "replace")


def tool_version(command: Sequence[str], *, timeout: int = 30) -> str:
    """Capture a deterministic one-line tool version."""

    completed = run_checked(command, timeout=timeout)
    payload = (completed.stdout + completed.stderr).decode("utf-8", "replace")
    return next((line.strip() for line in payload.splitlines() if line.strip()), "")


def python_environment() -> dict[str, str]:
    """Return the interpreter identity used by a replay."""

    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
    }


def write_csv_atomic(
    path: str | Path,
    fields: Sequence[str],
    rows: Iterable[Sequence[Any] | dict[str, Any]],
    *,
    expected_rows: int | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Write a BOM CSV after optional pre-promotion identity checks."""

    path = Path(path)
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
        materialized = list(rows)
        if materialized and isinstance(materialized[0], dict):
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(materialized)
        else:
            writer = csv.writer(stream)
            writer.writerow(fields)
            writer.writerows(materialized)
    temporary_metadata = file_metadata(temporary)
    if expected_rows is not None and len(materialized) != expected_rows:
        temporary.unlink()
        raise ReplayError(
            f"unexpected output row count for {path.name}: "
            f"expected {expected_rows}, got {len(materialized)}"
        )
    if (
        expected_sha256 is not None
        and temporary_metadata["sha256"] != expected_sha256
    ):
        temporary.unlink()
        raise ReplayError(
            f"unexpected output digest for {path.name}: "
            f"expected {expected_sha256}, got {temporary_metadata['sha256']}"
        )
    os.replace(temporary, path)
    metadata = file_metadata(path)
    metadata["rows"] = len(materialized)
    return metadata


def write_json_atomic(path: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Write deterministic UTF-8 JSON through a temporary file."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f".{path.name}.",
        suffix=".partial",
        dir=path.parent,
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        stream.write(encoded)
    os.replace(temporary, path)
    return file_metadata(path)


def require_output_identity(
    metadata: dict[str, Any],
    *,
    expected_rows: int,
    expected_sha256: str,
) -> None:
    """Fail if a rebuilt core artefact differs from the frozen release input."""

    if metadata["rows"] != expected_rows:
        raise ReplayError(
            f"unexpected output row count for {metadata['filename']}: "
            f"expected {expected_rows}, got {metadata['rows']}"
        )
    if metadata["sha256"] != expected_sha256:
        raise ReplayError(
            f"unexpected output digest for {metadata['filename']}: "
            f"expected {expected_sha256}, got {metadata['sha256']}"
        )
