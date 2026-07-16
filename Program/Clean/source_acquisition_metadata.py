#!/usr/bin/env python3
"""Public locators for byte-identified source and translation documents.

The locators in this module serve two distinct purposes.  A URL may identify
the standard or provide a reference copy without identifying the exact byte
stream used for extraction.  Only records labelled ``byte_exact_official_file``
have been downloaded and matched to the frozen source SHA-256 digest.

Locator discovery dates are kept separate from original retrieval dates.  A
post-hoc official locator must never be presented as original acquisition
provenance when that provenance was not recorded.
"""

from __future__ import annotations

from dataclasses import dataclass


LOCATOR_CHECKED_DATE = "2026-07-16"
TRANSLATION_RETRIEVED_DATE = "2026-07-15"


@dataclass(frozen=True)
class SourceLocator:
    """One public locator and its relationship to a frozen Chinese source."""

    source_id: str
    locator_status: str
    landing_url: str
    file_url: str = ""
    expected_sha256: str = ""
    notes: str = ""


@dataclass(frozen=True)
class TranslationSource:
    """One byte-locked unofficial English translation and its public source."""

    filename: str
    sha256: str
    file_size_bytes: int
    publication: str
    source_landing_url: str
    download_url: str
    locator_status: str
    retrieved_date: str = TRANSLATION_RETRIEVED_DATE
    notes: str = ""


SOURCE_LOCATORS = (
    SourceLocator(
        "SRC0001",
        "standard_identity_only",
        "https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=9632C56DCA563F1B40A6B3397D0DB2C1",
        notes="SAMR catalogue record; the frozen PDF acquisition path was not recorded.",
    ),
    SourceLocator(
        "SRC0002",
        "byte_exact_official_file",
        "https://www.nhc.gov.cn/sps/c100088/201301/999e3ffd3984444eb70bbf908b1871c9.shtml",
        "https://www.nhc.gov.cn/sps/c100088/201301/999e3ffd3984444eb70bbf908b1871c9/files/1732844510434_60460.pdf",
        "8ebbcf11896b5a2684414e6f8d63de8bf4595b3547629a947d4eeda37bfe8647",
        "Official file matched to the frozen digest on the locator check date.",
    ),
    SourceLocator(
        "SRC0003",
        "standard_identity_only",
        "https://www.nhc.gov.cn/sps/c100088/201704/e8b91e9057a84df7a30875a69bf7de12.shtml",
        notes="Official announcement covering the standard; exact frozen-file provenance was not recorded.",
    ),
    SourceLocator(
        "SRC0004",
        "standard_identity_only",
        "https://www.nhc.gov.cn/wjw/c100175/202207/8119dcdb74404387a64867eb75c3f193.shtml",
        notes="Official standard information page; exact frozen-file provenance was not recorded.",
    ),
    SourceLocator(
        "SRC0005",
        "standard_identity_only",
        "https://www.nhc.gov.cn/sps/c100088/202509/5dc5e1e2b26d4d27a7913b9e71bbe931.shtml",
        notes="Official announcement; exact frozen-file provenance was not recorded.",
    ),
    SourceLocator(
        "SRC0006",
        "standard_identity_only",
        "https://www.nhc.gov.cn/sps/c100088/201212/00c5db5d073346bca439045e0776a9e1.shtml",
        notes="Official announcement provides a DOC attachment; the frozen input is a PDF.",
    ),
    SourceLocator(
        "SRC0007",
        "byte_exact_official_file",
        "",
        "https://www.nhc.gov.cn/ewebeditor/uploadfile/2014/04/20140409103007373.pdf",
        "078022a2db7d1c2d20e1f14b800dab77e4e0fc4a81faa666c1225b9343ea2042",
        "Official file matched to the frozen digest on the locator check date.",
    ),
    SourceLocator(
        "SRC0008",
        "standard_identity_only",
        "https://www.nhc.gov.cn/sps/c100088/201702/894bf13f24094c55a3462c990f4569ae.shtml",
        notes="Official announcement; exact frozen-file provenance was not recorded.",
    ),
    SourceLocator(
        "SRC0009",
        "standard_identity_only",
        "https://www.nhc.gov.cn/sps/c100088/201908/38ed3bdd0d374cf2b21298cadcdc562f.shtml",
        notes="Official announcement for the scanned edition-identity anchor.",
    ),
    SourceLocator(
        "SRC0010",
        "standard_identity_only",
        "https://jgs.moa.gov.cn/nybz/202103/t20210318_6364007.htm",
        notes="Official MARA announcement for the scanned edition-identity anchor.",
    ),
    SourceLocator(
        "SRC0011",
        "standard_identity_only",
        "https://www.nhc.gov.cn/sps/c100088/202602/c0c4a9266f7e43cda1bf3bec59fc2786.shtml",
        notes="Official announcement; exact frozen-file provenance was not recorded.",
    ),
    SourceLocator(
        "SRC0012",
        "page_images_identity_only",
        "https://www.nhc.gov.cn/zwgkzt/psp/201212/34513.shtml",
        notes="Official page images identify the standard; the frozen PDF packaging history was not recorded.",
    ),
    SourceLocator(
        "SRC0013",
        "official_reference_copy_differs",
        "https://www.nhc.gov.cn/sps/c100088/201105/d436870f8e624dc582f66819b8b34850.shtml",
        notes="The current official download differs byte-for-byte from the frozen PDF.",
    ),
    SourceLocator(
        "SRC0014",
        "standard_identity_only",
        "https://www.nhc.gov.cn/sps/c100088/201704/e8b91e9057a84df7a30875a69bf7de12.shtml",
        notes="Official announcement covering the standard; exact frozen-file provenance was not recorded.",
    ),
    SourceLocator(
        "SRC0015",
        "authoritative_archive_identity_only",
        "",
        "https://faolex.fao.org/docs/pdf/chn176367.pdf",
        notes="FAOLEX reference copy; no current issuer-hosted exact download was located, and the frozen input is a DOC file.",
    ),
    SourceLocator(
        "SRC0016",
        "government_reference_copy_differs",
        "https://nyncw.sh.gov.cn/ncpaqnybz/20200115/09b82c84bb09475681f5b3a5a5818e03.html",
        "https://nyncw.sh.gov.cn/cmsres/7a/7a3599a39fbb49b9b9a1c57dd697133c/018af30c25faee41ca2f1b03d265a903.pdf",
        notes="Current government-hosted PDF differs byte-for-byte from the frozen input.",
    ),
    SourceLocator(
        "SRC0017",
        "standard_identity_only",
        "https://www.moa.gov.cn/govpublic/ncpzlaq/202209/t20220930_6412380.htm",
        notes="Official MARA announcement; its linked bulletin PDF is not the frozen standard file.",
    ),
    SourceLocator(
        "SRC0018",
        "standard_identity_only",
        "https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=CE486942632286F735CCC6C3ECC9A5DD",
        notes="SAMR catalogue record; the catalogue supplies no full text for this withdrawn standard.",
    ),
    SourceLocator(
        "SRC0019",
        "official_reference_copy_differs",
        "https://www.nhc.gov.cn/sps/c100088/201105/d436870f8e624dc582f66819b8b34850.shtml",
        notes="The current official download differs byte-for-byte from the frozen PDF.",
    ),
    SourceLocator(
        "SRC0020",
        "standard_identity_only",
        "https://www.nhc.gov.cn/sps/c100088/201412/b2b4a716a5494277b4219154c89b23a9.shtml",
        notes="Official announcement; exact frozen-file provenance was not recorded.",
    ),
    SourceLocator(
        "SRC0021",
        "standard_identity_only",
        "https://www.nhc.gov.cn/sps/c100088/202403/bda120e678df4a49a8beb90852559d7c.shtml",
        notes="Official announcement; exact frozen-file provenance was not recorded.",
    ),
    SourceLocator(
        "SRC0022",
        "related_standard_only",
        "https://www.nhc.gov.cn/sps/c100088/201704/e8b91e9057a84df7a30875a69bf7de12.shtml",
        notes="Related official standard page; the misnamed audit copy has no recorded public byte source.",
    ),
    SourceLocator(
        "SRC0023",
        "related_standard_only",
        "https://www.nhc.gov.cn/wjw/c100175/202207/8119dcdb74404387a64867eb75c3f193.shtml",
        notes="Related official standard page; the misnamed audit copy has no recorded public byte source.",
    ),
    SourceLocator(
        "SRC0024",
        "recorded_acquisition_url",
        "https://nyncw.sh.gov.cn/ncpaqnybz/20200115/ee0a5a3ead224babb4b384843c0af6d0.html",
        "https://nyncw.sh.gov.cn/cmsres/2b/2b883e1ab03843219ad485c27bf472d6/0aa902a98de948912eef082611290b9e.pdf",
        notes="Government-hosted text-layer extraction copy; original retrieval date is unrecorded.",
    ),
    SourceLocator(
        "SRC0025",
        "recorded_acquisition_url",
        "https://www.lushan.gov.cn/bmxzxxgk/bumeng/nyncj_195829/fdzdgknr_195835/zcwj_195837/202108/t20210816_5200479.html",
        "https://www.lushan.gov.cn/bmxzxxgk/bumeng/nyncj_195829/fdzdgknr_195835/zcwj_195837/202108/P020210816186031311653.pdf",
        notes="Government-hosted text-layer extraction copy; original retrieval date is unrecorded.",
    ),
)


TRANSLATION_SOURCES = (
    TranslationSource(
        "FSIS_GB2763-2016_en.pdf",
        "b28b87fb4a50759cd40c9889349ee59be24f9e49ea890af103d913fccccda542",
        2480852,
        "USDA FSIS unofficial English translation of GB 2763-2016",
        "https://www.fsis.usda.gov/inspection/import-export/import-export-library/china",
        "",
        "publisher_landing_only",
        notes="The original exact download URL was not retained; the current country page may point to a newer edition.",
    ),
    TranslationSource(
        "GAIN_CH2019-0170_GB2763-2019_en.pdf",
        "8f333e72aafa92140c9992fac61957efe686ce8d232a67d2b668f58560955730",
        4073400,
        "USDA FAS GAIN CH2019-0170 unofficial English translation",
        "https://www.fas.usda.gov/data/china-national-food-safety-standard-maximum-residue-limits-pesticides-foods",
        "https://bcz-cbl.be/sites/default/files/2023-10/GB%202763-2019_on%20MRLs%20for%20pesticides%20in%20food_en.pdf",
        "byte_exact_public_mirror",
        notes="The mirror download was matched to the frozen digest; the report identifies its USDA FAS provenance.",
    ),
    TranslationSource(
        "GAIN_CH2023-0040_GB2762-2022_en.pdf",
        "c8bccdb20f30b3f6246b18167af26dab16b09cc639621e98c9c16294b76c10a7",
        639722,
        "USDA FAS GAIN CH2023-0040 unofficial English translation",
        "https://www.fas.usda.gov/data/china-china-releases-standard-maximum-levels-contaminants-foods-0",
        "https://apps.fas.usda.gov/newgainapi/api/Report/DownloadReportByFileName?fileName=China+Releases+the+Standard+for+Maximum+Levels+of+Contaminants+in+Foods_Beijing_China+-+People%27s+Republic+of_CH2023-0040.pdf",
        "byte_exact_publisher_file",
        notes="Publisher download was matched to the frozen digest.",
    ),
    TranslationSource(
        "GAIN_GB2760-2014_en.pdf",
        "69d7d767b7c8c995f1dfd1b8bc828ced40a7d8f755a495ab977328e12665903f",
        2335051,
        "USDA FAS Beijing unofficial English translation of GB 2760-2014",
        "",
        "https://apps.fas.usda.gov/newgainapi/api/report/downloadreportbyfilename?filename=Standard+for+Food+Additive+Use+-+GB2760-2015_Beijing_China+-+Peoples+Republic+of_4-28-2015.pdf",
        "byte_exact_publisher_file",
        notes="Publisher download was matched to the frozen digest.",
    ),
)


TRANSLATION_PDFS = {
    source.filename: source.sha256 for source in TRANSLATION_SOURCES
}


def source_locators_by_id() -> dict[str, SourceLocator]:
    """Return public locators keyed by stable source ID."""

    locators = {locator.source_id: locator for locator in SOURCE_LOCATORS}
    if len(locators) != len(SOURCE_LOCATORS):
        raise ValueError("duplicate source locator ID")
    return locators


def translation_sources_by_filename() -> dict[str, TranslationSource]:
    """Return unofficial translation metadata keyed by locked filename."""

    sources = {source.filename: source for source in TRANSLATION_SOURCES}
    if len(sources) != len(TRANSLATION_SOURCES):
        raise ValueError("duplicate translation source filename")
    return sources


# Validate static uniqueness at import time.
source_locators_by_id()
translation_sources_by_filename()
