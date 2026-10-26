#!/usr/bin/env python3
"""Build a portable manifest and public source-acquisition guide.

The source standards are not redistributed with the release.  This manifest
records every exact source file by stable ID, basename, byte length, and
SHA-256 digest.  It separates edition-identity anchors, extraction copies, and
identity-audit copies, with explicit links between related byte streams.  The
companion guide distinguishes exact-byte downloads from identity-only public
locators and records the four byte-locked unofficial English translations.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
from pathlib import Path

from source_acquisition_metadata import (
    LOCATOR_CHECKED_DATE,
    TRANSLATION_SOURCES,
    source_locators_by_id,
)
from source_manifest_utils import (
    DEFAULT_EXTRACTION_COPY_ROOT,
    OUTPUT_COLUMNS,
    SOURCE_DOCUMENTS,
    resolve_source_path,
    source_class,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RELEASE_DIR = (
    PROJECT_ROOT / "Data" / "Final" / "china_food_limit_panel_v1"
)

LONG_TABLES = {
    "contaminant": "pollutant_limits_long.csv",
    "pesticide": "pesticide_limits_long.csv",
    "mycotoxin": "mycotoxin_limits_long.csv",
    "veterinary_drug": "vetdrug_limits_long.csv",
    "additive": "additive_limits_long.csv",
}


def file_sha256(path: Path) -> str:
    """Return a streaming SHA-256 digest."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def released_counts(release_dir: Path) -> dict[tuple[str, str], int]:
    """Count released long-table rows by family and edition year."""

    counts: dict[tuple[str, str], int] = {}
    for family, filename in LONG_TABLES.items():
        path = release_dir / filename
        with path.open(encoding="utf-8-sig", newline="") as handle:
            by_year = Counter(row["version_year"] for row in csv.DictReader(handle))
        counts.update({(family, year): count for year, count in by_year.items()})
    return counts


def _released_rows(document_role: str, status: str, row_count: int) -> str:
    """Return the row attribution required for one manifest role and status."""

    if status == "extracted":
        if document_role not in {"edition_source", "extraction_copy"}:
            raise ValueError(f"invalid extracted source role: {document_role}")
        if row_count <= 0:
            raise ValueError("extracted source has no released rows")
        return str(row_count)
    if status == "archived_unextracted":
        if document_role != "edition_source" or row_count != 0:
            raise ValueError("invalid archived-unextracted source attribution")
        return "0"
    if status == "identity_anchor_crosscheck":
        if document_role != "edition_source":
            raise ValueError(
                "identity-anchor crosscheck status requires an edition source"
            )
        return ""
    if status == "excluded_from_extraction":
        if document_role != "identity_audit_copy":
            raise ValueError(f"invalid excluded source role: {document_role}")
        return ""
    raise ValueError(f"unknown release_status: {status}")


def build_manifest(
    source_root: Path,
    release_dir: Path,
    output_path: Path | None = None,
    extraction_copy_root: Path = DEFAULT_EXTRACTION_COPY_ROOT,
) -> list[dict[str, str]]:
    """Build and write the source manifest from byte-identified inputs."""

    counts = released_counts(release_dir)
    rows: list[dict[str, str]] = []
    for document in SOURCE_DOCUMENTS:
        source_path = resolve_source_path(
            document, source_root, extraction_copy_root
        )
        if not source_path.is_file():
            raise FileNotFoundError(f"source document not found: {source_path}")
        row_count = counts.get((document.family, document.version_year), 0)
        try:
            released_rows = _released_rows(
                document.source_role, document.release_status, row_count
            )
        except ValueError as error:
            raise ValueError(f"{error}: {document.source_id}") from error
        rows.append(
            {
                "source_id": document.source_id,
                "family": document.family,
                "standard": document.standard,
                "version_year": document.version_year,
                "source_role": document.source_role,
                "release_status": document.release_status,
                "released_limit_rows": released_rows,
                "source_filename": source_path.name,
                "source_format": source_path.suffix.lower().lstrip("."),
                "file_size_bytes": str(source_path.stat().st_size),
                "sha256": file_sha256(source_path),
                "extraction_mode": document.extraction_mode,
                "document_identity": document.document_identity,
                "notes": document.notes,
                "related_source_id": document.related_source_id,
                "acquisition_landing_url": document.acquisition_landing_url,
                "acquisition_file_url": document.acquisition_file_url,
                "retrieved_date": document.retrieved_date,
                "page_count": (
                    "" if document.page_count is None else str(document.page_count)
                ),
                "source_class": source_class(document),
            }
        )

    extracted_keys = {
        (document.family, document.version_year)
        for document in SOURCE_DOCUMENTS
        if document.release_status == "extracted"
    }
    if set(counts) != extracted_keys:
        missing = sorted(set(counts) - extracted_keys)
        extra = sorted(extracted_keys - set(counts))
        raise ValueError(
            f"source manifest and long-table editions differ; "
            f"missing={missing}, extra={extra}"
        )

    output_path = output_path or release_dir / "source_manifest.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=OUTPUT_COLUMNS,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    return rows


def _markdown_cell(value: str) -> str:
    """Escape text for a simple Markdown table cell."""

    return value.replace("|", "\\|").replace("\n", " ")


def _locator_links(landing_url: str, file_url: str) -> str:
    """Render public landing and file URLs without exposing local paths."""

    links = []
    if landing_url:
        links.append(f"[landing page]({landing_url})")
    if file_url:
        links.append(f"[file]({file_url})")
    return "; ".join(links) or "unavailable"


def validate_acquisition_metadata(rows: list[dict[str, str]]) -> None:
    """Fail closed when locators and frozen byte identities diverge."""

    by_id = {row["source_id"]: row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError("duplicate source_id in source manifest rows")

    locators = source_locators_by_id()
    if set(by_id) != set(locators):
        missing = sorted(set(by_id) - set(locators))
        extra = sorted(set(locators) - set(by_id))
        raise ValueError(
            "source rows and acquisition locators differ; "
            f"missing_locators={missing}, extra_locators={extra}"
        )

    for source_id, locator in locators.items():
        row = by_id[source_id]
        if locator.locator_status == "byte_exact_official_file":
            if not locator.file_url or not locator.expected_sha256:
                raise ValueError(
                    f"exact-byte locator is incomplete: {source_id}"
                )
            if row["sha256"] != locator.expected_sha256:
                raise ValueError(
                    "exact-byte locator digest differs from source manifest: "
                    f"{source_id}"
                )
        if locator.locator_status == "recorded_acquisition_url":
            if row["acquisition_landing_url"] != locator.landing_url:
                raise ValueError(
                    f"recorded landing URL differs for {source_id}"
                )
            if row["acquisition_file_url"] != locator.file_url:
                raise ValueError(f"recorded file URL differs for {source_id}")


def write_source_acquisition_guide(
    rows: list[dict[str, str]], output_path: Path
) -> Path:
    """Write a portable guide for locating and verifying every exact input."""

    validate_acquisition_metadata(rows)
    locators = source_locators_by_id()
    lines = [
        "# Source acquisition and exact-input verification",
        "",
        "The Chinese source standards are not redistributed in this release. "
        "`source_manifest.csv` is the authoritative inventory of the 25 exact "
        "byte streams used, retained for identity audit, or archived without "
        "extraction. Each input is identified by a stable `source_id`, basename, "
        "byte length, and SHA-256 digest.",
        "",
        "## How to use this guide",
        "",
        "1. Follow the public locator for the relevant `source_id`.",
        "2. Treat the downloaded filename as a hint. Compare its byte length and "
        "SHA-256 digest with `source_manifest.csv`.",
        "3. Use a candidate only when its SHA-256 digest exactly matches. A current "
        "official or government-hosted file with a different digest is a reference "
        "copy and must not silently replace the frozen input.",
        "4. If no byte-exact public download is recorded, cite the stable standard "
        "identity and request the frozen source bytes from the authors, subject to "
        "the source publisher's redistribution terms.",
        "",
        "A blank `retrieved_date` in `source_manifest.csv` means that the original "
        "retrieval date was unrecorded. Public locators were checked on "
        f"{LOCATOR_CHECKED_DATE}. A locator found later establishes locatability "
        "at the check date and does not reconstruct original acquisition provenance.",
        "",
        "Locator status meanings:",
        "",
        "- `byte_exact_official_file`: the current issuing-authority file matched "
        "the frozen SHA-256 digest on the locator check date.",
        "- `recorded_acquisition_url`: the URL was retained with the source record; "
        "the original retrieval date remains unrecorded.",
        "- `standard_identity_only` and `page_images_identity_only`: the official "
        "page identifies the instrument, while the exact frozen-byte acquisition "
        "path remains unrecorded.",
        "- `official_reference_copy_differs` and "
        "`government_reference_copy_differs`: the public reference file has a "
        "different byte identity.",
        "- `authoritative_archive_identity_only`: an authoritative archive supplies "
        "a reference copy when no current issuer-hosted exact file was located.",
        "- `related_standard_only`: the locator identifies the related standard; "
        "it does not identify the separate audit-copy byte stream.",
        "",
        "Source classes (`source_class` in `source_manifest.csv`):",
        "",
        "- `issuing_authority_file`: an edition text issued by the standard-setting "
        "authority. The locator status states whether the frozen bytes match a "
        "current issuer download.",
        "- `government_hosted_copy`: a copy downloaded from a government website "
        "other than the issuing authority; it supplied released values.",
        "- `third_party_translation`: an unofficial English translation used only "
        "for English labels.",
        "- `audit_only_copy`: a file used for edition identity, OCR cross-checking "
        "or identity audit; no released value is read from it.",
        "",
        "## Chinese source documents",
        "",
        "| ID | Standard | Year | Source class | Frozen filename | Bytes | "
        "Frozen SHA-256 | Public locator | Locator status | Original retrieval | Notes |",
        "|---|---|---:|---|---|---:|---|---|---|---|---|",
    ]

    for row in rows:
        locator = locators[row["source_id"]]
        cells = (
            row["source_id"],
            row["standard"],
            row["version_year"],
            f"`{row['source_class']}`",
            f"`{row['source_filename']}`",
            row["file_size_bytes"],
            f"`{row['sha256']}`",
            _locator_links(locator.landing_url, locator.file_url),
            f"`{locator.locator_status}`",
            row["retrieved_date"] or "unrecorded",
            locator.notes,
        )
        lines.append("| " + " | ".join(_markdown_cell(cell) for cell in cells) + " |")

    lines.extend(
        [
            "",
            "## Unofficial English translations",
            "",
            "These four PDFs support English food-category linkage. They are "
            "external unofficial translations and do not replace the Chinese "
            "normative standards. The extraction script checks each filename and "
            "SHA-256 digest before parsing.",
            "",
            "| Frozen filename | Source class | Bytes | Publication | Frozen SHA-256 | "
            "Public locator | Locator status | Retrieved | Notes |",
            "|---|---|---:|---|---|---|---|---|---|",
        ]
    )
    for translation in TRANSLATION_SOURCES:
        cells = (
            f"`{translation.filename}`",
            "`third_party_translation`",
            str(translation.file_size_bytes),
            translation.publication,
            f"`{translation.sha256}`",
            _locator_links(
                translation.source_landing_url, translation.download_url
            ),
            f"`{translation.locator_status}`",
            translation.retrieved_date,
            translation.notes,
        )
        lines.append("| " + " | ".join(_markdown_cell(cell) for cell in cells) + " |")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument(
        "--extraction-copy-root",
        type=Path,
        default=DEFAULT_EXTRACTION_COPY_ROOT,
        help="Directory containing byte-identified government text-layer copies",
    )
    parser.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE_DIR)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--guide-output",
        type=Path,
        help="Source-acquisition guide output (default: RELEASE_DIR/SOURCE_ACQUISITION.md)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Write the source manifest and print a concise role summary."""

    args = parse_args(argv)
    rows = build_manifest(
        args.source_root,
        args.release_dir,
        args.output,
        args.extraction_copy_root,
    )
    guide_output = args.guide_output or args.release_dir / "SOURCE_ACQUISITION.md"
    write_source_acquisition_guide(rows, guide_output)
    roles = Counter(row["source_role"] for row in rows)
    print(
        f"Wrote {len(rows)} source documents and {guide_output}: "
        f"{roles['edition_source']} edition sources, "
        f"{roles['extraction_copy']} extraction copies, "
        f"{roles['identity_audit_copy']} identity-audit copies"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
