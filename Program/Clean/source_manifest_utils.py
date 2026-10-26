#!/usr/bin/env python3
"""Stable source identities and relationships for the release manifest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXTRACTION_COPY_ROOT = PROJECT_ROOT / "Data/Raw/政府文本层副本"

OTHER = Path("补充_其它限量标准")
RESIDUE = Path("补充_农兽药残留限量标准")
POLLUTANT = Path("补充_食安国标全文_卫健委分类") / "污染物"

SOURCE_ARCHIVE = "source_archive"
EXTRACTION_COPY_ROOT = "extraction_copy_root"


@dataclass(frozen=True)
class SourceDocument:
    """One byte-identified document with a stable release identifier."""

    source_id: str
    family: str
    standard: str
    version_year: str
    relative_path: Path
    storage_root: str
    source_role: str
    release_status: str
    extraction_mode: str
    document_identity: str
    notes: str = ""
    related_source_id: str = ""
    acquisition_landing_url: str = ""
    acquisition_file_url: str = ""
    retrieved_date: str = ""
    page_count: int | None = None


def edition(
    source_id: str,
    family: str,
    standard: str,
    year: int,
    path: Path,
    mode: str,
    *,
    page_count: int | None,
    identity: str = "full_standard",
    status: str = "extracted",
    notes: str = "",
) -> SourceDocument:
    """Define an edition-identity source from the external source archive."""

    return SourceDocument(
        source_id=source_id,
        family=family,
        standard=standard,
        version_year=str(year),
        relative_path=path,
        storage_root=SOURCE_ARCHIVE,
        source_role="edition_source",
        release_status=status,
        extraction_mode=mode,
        document_identity=identity,
        notes=notes,
        page_count=page_count,
    )


SOURCE_DOCUMENTS = (
    edition(
        "SRC0001",
        "contaminant",
        "GB 2762",
        2005,
        OTHER / "GB 2762-2005 食品中污染物限量.pdf",
        "not_extracted",
        page_count=11,
        status="archived_unextracted",
    ),
    edition(
        "SRC0002",
        "contaminant",
        "GB 2762",
        2012,
        POLLUTANT / "GB 2762-2012 食品安全国家标准 食品中污染物限量.pdf",
        "pdf_text_and_coordinate_parser",
        page_count=17,
    ),
    edition(
        "SRC0003",
        "contaminant",
        "GB 2762",
        2017,
        POLLUTANT / "GB 2762-2017 食品安全国家标准 食品中污染物限量.pdf",
        "pdf_text_and_coordinate_parser",
        page_count=19,
    ),
    edition(
        "SRC0004",
        "contaminant",
        "GB 2762",
        2022,
        POLLUTANT / "GB 2762-2022 食品安全国家标准 食品中污染物限量.pdf",
        "pdf_text_and_coordinate_parser",
        page_count=20,
    ),
    edition(
        "SRC0005",
        "contaminant",
        "GB 2762",
        2025,
        POLLUTANT / "GB 2762-2025 食品安全国家标准 食品中污染物限量.pdf",
        "pdf_text_and_coordinate_parser",
        page_count=21,
    ),
    edition(
        "SRC0006",
        "pesticide",
        "GB 2763",
        2012,
        RESIDUE / "GB 2763-2012 食品安全国家标准 食品中农药最大残留限量.pdf",
        "pdf_text_and_coordinate_parser",
        page_count=183,
    ),
    edition(
        "SRC0007",
        "pesticide",
        "GB 2763",
        2014,
        RESIDUE / "GB 2763-2014 食品安全国家标准 食品中农药最大残留限量.pdf",
        "pdf_text_and_coordinate_parser",
        page_count=234,
    ),
    edition(
        "SRC0008",
        "pesticide",
        "GB 2763",
        2016,
        RESIDUE / "GB 2763-2016 食品安全国家标准 食品中农药最大残留限量.pdf",
        "pdf_text_and_coordinate_parser",
        page_count=265,
    ),
    edition(
        "SRC0009",
        "pesticide",
        "GB 2763",
        2019,
        RESIDUE / "GB 2763-2019 食品安全国家标准 食品中农药最大残留限量.pdf",
        "ocr_scanned_pdf",
        page_count=333,
        status="identity_anchor_crosscheck",
        notes=(
            "Scanned edition-identity anchor and OCR crosscheck copy; released "
            "coordinates are supplied by related extraction copy SRC0024"
        ),
    ),
    edition(
        "SRC0010",
        "pesticide",
        "GB 2763",
        2021,
        RESIDUE / "GB 2763-2021 食品安全国家标准 食品中农药最大残留限量.pdf",
        "ocr_scanned_pdf",
        page_count=422,
        status="identity_anchor_crosscheck",
        notes=(
            "Scanned edition-identity anchor and OCR crosscheck copy; released "
            "coordinates are supplied by related extraction copy SRC0025"
        ),
    ),
    edition(
        "SRC0011",
        "pesticide",
        "GB 2763",
        2026,
        RESIDUE / "GB 2763-2026 食品安全国家标准 食品中农药最大残留限量.pdf",
        "pdf_text_and_coordinate_parser",
        page_count=442,
    ),
    edition(
        "SRC0012",
        "mycotoxin",
        "GB 2761",
        2005,
        OTHER / "GB 2761-2005 食品中真菌毒素限量.pdf",
        "manual_page_image_transcription",
        page_count=4,
    ),
    edition(
        "SRC0013",
        "mycotoxin",
        "GB 2761",
        2011,
        OTHER / "GB 2761-2011 食品安全国家标准 食品中真菌毒素限量.pdf",
        "pdf_text_layer",
        page_count=9,
    ),
    edition(
        "SRC0014",
        "mycotoxin",
        "GB 2761",
        2017,
        OTHER / "GB 2761-2017 食品安全国家标准 食品中真菌毒素限量.pdf",
        "pdf_text_layer",
        page_count=10,
    ),
    edition(
        "SRC0015",
        "veterinary_drug",
        "MOA Announcement 235",
        2002,
        RESIDUE / "农业部235号公告-2002 动物性食品中兽药最高残留限量.doc",
        "word_table_stream",
        page_count=None,
        identity="official_announcement",
    ),
    edition(
        "SRC0016",
        "veterinary_drug",
        "GB 31650",
        2019,
        RESIDUE / "GB 31650-2019 食品安全国家标准 食品中兽药最大残留限量.pdf",
        "pdf_text_with_manual_page_break_rows",
        page_count=64,
    ),
    edition(
        "SRC0017",
        "veterinary_drug",
        "GB 31650.1",
        2022,
        RESIDUE
        / "GB 31650.1-2022 食品安全国家标准 食品中兽药最大残留限量增补.pdf",
        "manual_page_image_transcription",
        page_count=18,
        identity="supplementary_standard",
    ),
    edition(
        "SRC0018",
        "additive",
        "GB 2760",
        1996,
        OTHER / "GB 2760-1996 食品添加剂使用卫生标准.pdf",
        "not_extracted",
        page_count=55,
        status="archived_unextracted",
    ),
    edition(
        "SRC0019",
        "additive",
        "GB 2760",
        2011,
        OTHER / "GB 2760-2011 食品安全国家标准 食品添加剂使用标准.pdf",
        "pdf_text_layer",
        page_count=352,
    ),
    edition(
        "SRC0020",
        "additive",
        "GB 2760",
        2014,
        OTHER / "GB 2760-2014 食品安全国家标准 食品添加剂使用标准.pdf",
        "pdf_text_layer",
        page_count=705,
    ),
    edition(
        "SRC0021",
        "additive",
        "GB 2760",
        2024,
        OTHER / "GB 2760-2024 食品安全国家标准 食品添加剂使用标准.pdf",
        "pdf_text_layer",
        page_count=264,
    ),
    SourceDocument(
        source_id="SRC0022",
        family="contaminant",
        standard="GB 2762",
        version_year="2017",
        relative_path=POLLUTANT
        / "GB 2762-2017 《食品安全国家标准 食品中污染物限量》（GB 2762-2017）第1号修改单.pdf",
        storage_root=SOURCE_ARCHIVE,
        source_role="identity_audit_copy",
        release_status="excluded_from_extraction",
        extraction_mode="not_extracted",
        document_identity="full_standard_text_misnamed_as_amendment",
        notes="Rendered file contains the complete 22-page standard text",
        related_source_id="SRC0003",
        page_count=22,
    ),
    SourceDocument(
        source_id="SRC0023",
        family="contaminant",
        standard="GB 2762",
        version_year="2022",
        relative_path=POLLUTANT
        / "GB 2762-2022 GB 2762-2022《食品安全国家标准 食品中污染物限量》第1号修改单.pdf",
        storage_root=SOURCE_ARCHIVE,
        source_role="identity_audit_copy",
        release_status="excluded_from_extraction",
        extraction_mode="not_extracted",
        document_identity="full_standard_text_misnamed_as_amendment",
        notes="Rendered file contains the complete 21-page standard text",
        related_source_id="SRC0004",
        page_count=21,
    ),
    SourceDocument(
        source_id="SRC0024",
        family="pesticide",
        standard="GB 2763",
        version_year="2019",
        relative_path=Path("GB2763-2019_shanghai_gov_textlayer.pdf"),
        storage_root=EXTRACTION_COPY_ROOT,
        source_role="extraction_copy",
        release_status="extracted",
        extraction_mode="pdf_text_and_coordinate_parser",
        document_identity="full_standard",
        notes=(
            "Government-hosted text-layer extraction copy; government hosting "
            "does not establish issuing-authority certification of this byte stream"
        ),
        related_source_id="SRC0009",
        acquisition_landing_url=(
            "https://nyncw.sh.gov.cn/ncpaqnybz/20200115/"
            "ee0a5a3ead224babb4b384843c0af6d0.html"
        ),
        acquisition_file_url=(
            "https://nyncw.sh.gov.cn/cmsres/2b/"
            "2b883e1ab03843219ad485c27bf472d6/"
            "0aa902a98de948912eef082611290b9e.pdf"
        ),
        page_count=332,
    ),
    SourceDocument(
        source_id="SRC0025",
        family="pesticide",
        standard="GB 2763",
        version_year="2021",
        relative_path=Path("GB2763-2021_lushan_gov_textlayer.pdf"),
        storage_root=EXTRACTION_COPY_ROOT,
        source_role="extraction_copy",
        release_status="extracted",
        extraction_mode="pdf_text_and_coordinate_parser",
        document_identity="full_standard",
        notes=(
            "Government-hosted text-layer extraction copy; government hosting "
            "does not establish issuing-authority certification of this byte stream"
        ),
        related_source_id="SRC0010",
        acquisition_landing_url=(
            "https://www.lushan.gov.cn/bmxzxxgk/bumeng/nyncj_195829/"
            "fdzdgknr_195835/zcwj_195837/202108/t20210816_5200479.html"
        ),
        acquisition_file_url=(
            "https://www.lushan.gov.cn/bmxzxxgk/bumeng/nyncj_195829/"
            "fdzdgknr_195835/zcwj_195837/202108/"
            "P020210816186031311653.pdf"
        ),
        page_count=422,
    ),
)


OUTPUT_COLUMNS = (
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
    "related_source_id",
    "acquisition_landing_url",
    "acquisition_file_url",
    "retrieved_date",
    "page_count",
    "source_class",
)

SOURCE_CLASSES = (
    "issuing_authority_file",
    "government_hosted_copy",
    "third_party_translation",
    "audit_only_copy",
)


def source_class(document: SourceDocument) -> str:
    """Classify a Chinese source file; translations are listed separately."""

    if document.source_role == "extraction_copy":
        return "government_hosted_copy"
    if (
        document.source_role == "identity_audit_copy"
        or document.release_status == "identity_anchor_crosscheck"
    ):
        return "audit_only_copy"
    return "issuing_authority_file"


def source_documents_by_id() -> dict[str, SourceDocument]:
    """Return all documents keyed by stable ``SRC####`` identity."""

    documents = {document.source_id: document for document in SOURCE_DOCUMENTS}
    if len(documents) != len(SOURCE_DOCUMENTS):
        raise ValueError("duplicate stable source_id")
    for document in SOURCE_DOCUMENTS:
        related = document.related_source_id
        if related and related not in documents:
            raise ValueError(
                f"unknown related_source_id {related} for {document.source_id}"
            )
    return documents


def source_ids_by_edition() -> dict[tuple[str, str, str], dict[str, str]]:
    """Map each edition to its identity and extraction source IDs."""

    documents = source_documents_by_id()
    relations: dict[tuple[str, str, str], dict[str, str]] = {}
    for document in SOURCE_DOCUMENTS:
        if document.source_role != "edition_source":
            continue
        key = (document.family, document.standard, document.version_year)
        if key in relations:
            raise ValueError(f"duplicate edition identity: {key}")
        relations[key] = {
            "edition_source_id": document.source_id,
            "extraction_source_id": document.source_id,
        }
    for document in SOURCE_DOCUMENTS:
        if document.source_role != "extraction_copy":
            continue
        anchor = documents[document.related_source_id]
        key = (anchor.family, anchor.standard, anchor.version_year)
        if key not in relations:
            raise ValueError(f"extraction copy has no edition identity: {key}")
        if (
            document.family,
            document.standard,
            document.version_year,
        ) != key:
            raise ValueError(
                f"extraction copy metadata differs from related edition: "
                f"{document.source_id}"
            )
        relations[key]["extraction_source_id"] = document.source_id
    return relations


def resolve_source_path(
    document: SourceDocument,
    source_root: Path,
    extraction_copy_root: Path,
) -> Path:
    """Resolve a source without exposing a machine-specific path in output."""

    if document.storage_root == SOURCE_ARCHIVE:
        root = source_root
    elif document.storage_root == EXTRACTION_COPY_ROOT:
        root = extraction_copy_root
    else:
        raise ValueError(
            f"unknown storage_root {document.storage_root} for {document.source_id}"
        )
    return root / document.relative_path


# Validate static identities and relationships at import time.
source_ids_by_edition()
