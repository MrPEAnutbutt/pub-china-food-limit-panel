#!/usr/bin/env python3
"""Integrity checks for the frozen GB 2763 OCR word tables.

The 2019 and 2021 standards are scanned PDFs.  Their downstream parser must
only consume OCR output after every source page has been written and the final
TSV digest has been recorded in a completion manifest.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any


TSV_COLUMNS = ("page", "text", "x", "y", "w", "h", "conf", "occ")
MANIFEST_NAME = "completion_manifest.json"
MANIFEST_SCHEMA_VERSION = 1


class OCRIntegrityError(ValueError):
    """Raised when a frozen OCR input is incomplete or has changed."""


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest of a file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_tsv(path: str | Path, expected_pages: int | None = None) -> dict[str, Any]:
    """Validate an OCR TSV and return deterministic file/page metadata."""

    path = Path(path)
    page_counts: dict[int, int] = {}
    word_count = 0
    previous_page = 0

    try:
        stream = path.open(encoding="utf-8", newline="")
    except OSError as error:
        raise OCRIntegrityError(f"cannot read OCR TSV: {path}") from error

    with stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if tuple(reader.fieldnames or ()) != TSV_COLUMNS:
            raise OCRIntegrityError(
                f"unexpected OCR TSV header in {path.name}: {reader.fieldnames}"
            )
        for line_number, row in enumerate(reader, start=2):
            try:
                page = int(row["page"])
                x = int(row["x"])
                y = int(row["y"])
                width = int(row["w"])
                height = int(row["h"])
                confidence = float(row["conf"])
                occlusion = float(row["occ"])
            except (TypeError, ValueError) as error:
                raise OCRIntegrityError(
                    f"invalid OCR field in {path.name} line {line_number}"
                ) from error
            if page < 1 or page < previous_page:
                raise OCRIntegrityError(
                    f"non-monotonic page sequence in {path.name} line {line_number}"
                )
            if not row["text"].strip():
                raise OCRIntegrityError(
                    f"blank OCR token in {path.name} line {line_number}"
                )
            if min(x, y, width, height) < 0 or width == 0 or height == 0:
                raise OCRIntegrityError(
                    f"invalid OCR bounding box in {path.name} line {line_number}"
                )
            if not -1 <= confidence <= 100 or not 0 <= occlusion <= 1:
                raise OCRIntegrityError(
                    f"invalid OCR confidence/occlusion in {path.name} line {line_number}"
                )
            page_counts[page] = page_counts.get(page, 0) + 1
            word_count += 1
            previous_page = page

    if not page_counts:
        raise OCRIntegrityError(f"OCR TSV contains no words: {path.name}")
    if expected_pages is not None:
        observed = set(page_counts)
        required = set(range(1, expected_pages + 1))
        missing = sorted(required - observed)
        extra = sorted(observed - required)
        if missing or extra:
            detail = []
            if missing:
                detail.append(f"missing pages {missing[:10]}")
            if extra:
                detail.append(f"unexpected pages {extra[:10]}")
            raise OCRIntegrityError(
                f"incomplete OCR TSV {path.name}: " + "; ".join(detail)
            )

    counts_payload = json.dumps(
        [[page, page_counts[page]] for page in sorted(page_counts)],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "filename": path.name,
        "file_size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "word_count": word_count,
        "page_count": len(page_counts),
        "first_page": min(page_counts),
        "last_page": max(page_counts),
        "page_word_counts_sha256": hashlib.sha256(counts_payload).hexdigest(),
    }


def verify_completion_manifest(
    manifest_path: str | Path,
    *,
    source_pdf_root: str | Path | None = None,
) -> dict[str, Any]:
    """Verify every frozen TSV and, when supplied, each source PDF."""

    manifest_path = Path(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OCRIntegrityError(f"cannot read completion manifest: {manifest_path}") from error

    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise OCRIntegrityError("unsupported OCR completion-manifest schema")
    editions = manifest.get("editions")
    if not isinstance(editions, dict) or not editions:
        raise OCRIntegrityError("completion manifest has no editions")

    source_root = Path(source_pdf_root) if source_pdf_root is not None else None
    for year, entry in sorted(editions.items()):
        if not isinstance(entry, dict):
            raise OCRIntegrityError(f"invalid completion-manifest entry for {year}")
        pdf_metadata = entry.get("source_pdf", {})
        tsv_metadata = entry.get("ocr_tsv", {})
        expected_pages = pdf_metadata.get("page_count")
        if not isinstance(expected_pages, int) or expected_pages < 1:
            raise OCRIntegrityError(f"invalid source page count for {year}")

        filename = tsv_metadata.get("filename")
        if not filename or Path(filename).name != filename:
            raise OCRIntegrityError(f"unsafe OCR TSV filename for {year}")
        actual = inspect_tsv(manifest_path.parent / filename, expected_pages)
        for field in (
            "filename",
            "file_size_bytes",
            "sha256",
            "word_count",
            "page_count",
            "first_page",
            "last_page",
            "page_word_counts_sha256",
        ):
            if actual[field] != tsv_metadata.get(field):
                raise OCRIntegrityError(
                    f"OCR TSV {year} differs from completion manifest: {field}"
                )

        if source_root is not None:
            pdf_filename = pdf_metadata.get("filename")
            if not pdf_filename or Path(pdf_filename).name != pdf_filename:
                raise OCRIntegrityError(f"unsafe source PDF filename for {year}")
            matches = list(source_root.rglob(pdf_filename))
            if len(matches) != 1:
                raise OCRIntegrityError(
                    f"expected one source PDF for {year}, found {len(matches)}"
                )
            pdf_path = matches[0]
            if pdf_path.stat().st_size != pdf_metadata.get("file_size_bytes"):
                raise OCRIntegrityError(f"source PDF size differs for {year}")
            if sha256_file(pdf_path) != pdf_metadata.get("sha256"):
                raise OCRIntegrityError(f"source PDF digest differs for {year}")

    return manifest

