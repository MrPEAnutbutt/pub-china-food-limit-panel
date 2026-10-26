# China Food Safety Maximum-Limit Panel, 2002–2026 (release v1.1)

This package aligns maximum-limit rules from five mandatory Chinese food-safety
standard families across editions. The release contains 46,337 long-table rules
from 19 extracted editions, while the documented source corpus covers 21 edition
sources. The two additional edition sources, GB 2762-2005 and GB 2760-1996, are
archived and have no released limit rows.

All 26 CSV files use UTF-8 with a byte-order mark. Read codes, years, and
identifiers as text when software might infer numeric types.
Run `validate.py` to obtain the current row inventory and package hashes;
`validation_report.json` records the latest validation run.
`SOURCE_ACQUISITION.md` gives a public locator and byte-identity status for
each of the 25 Chinese source files and four unofficial English translations.

## Release v1.1 and versioning policy

Release v1.1 replaces v1.0, the version circulated for peer review. The record
count is unchanged. The release corrects 1,019 pesticide category assignments,
six temporary-limit marks, nine veterinary-drug animal labels and one
veterinary-drug English name; it withholds panel trends in more situations
where the compared scope or edition sequence is not comparable; and it adds
row-level source, extraction-method and verification fields together with
`extraction_method_summary.csv` and `record_id_changes.csv`.

Future releases follow these rules:

- **Version numbers.** Corrections, new editions, added columns and added
  tables increment the minor version. A change to the meaning or format of an
  existing column or code increments the major version.
- **Corrections.** An error in a released record is corrected at its
  construction source (an extraction rule or a manual-transcription seed) and
  the package is rebuilt; released files are never edited by hand.
  `record_id_changes.csv` lists every identifier the correction changes.
- **Newly issued standards.** A new edition of a covered family is added as a
  new edition source, extracted with the family's documented method and
  validated before release; records of earlier editions are kept.
- **Superseded or replaced source files.** A frozen source file is never
  replaced silently. A replacement or newly matched issuing-authority file
  receives its own `source_id` in `source_manifest.csv`, and rows re-extracted from it are
  listed in `record_id_changes.csv`.

## Edition coverage

| Family | Instruments represented | Editions with released rules | Archived edition without released rules |
|---|---|---|---|
| Contaminants | GB 2762 | 2012, 2017, 2022, 2025 | 2005 |
| Pesticide residues | GB 2763 | 2012, 2014, 2016, 2019, 2021, 2026 | — |
| Mycotoxins | GB 2761 | 2005, 2011, 2017 | — |
| Veterinary-drug residues | MOA Announcement 235, GB 31650, GB 31650.1 | 2002, 2019, 2022 | — |
| Food additives | GB 2760 | 2011, 2014, 2024 | 1996 |

The 21 edition-source cells consist of 19 extracted editions and two archived
editions. `version_dates.csv` therefore has 21 rows. Twenty rows contain a
complete issue/effective-date pair. The GB 2760-1996 row deliberately leaves
both dates blank because they were not printed on the archived cover and were
absent from the register used for the cross-check; its `date_status`
is `not_printed`.

## Why cross-edition comparison needs more than a number

A printed limit can change along four independent dimensions:

1. **Unit.** Compare `limit_mgkg` only where `normalization_status` is
   `already_mg_per_kg` or `converted_mass_per_mass`. An `mg/L` record has
   `normalization_status = density_required` and a blank `limit_mgkg` because
   conversion requires a defensible density.
2. **Chemical species.** Total mercury and methylmercury, and total arsenic and
   inorganic arsenic, remain separate analytes.
3. **Basis of expression.** `limit_basis` retains dry-weight, solid-product,
   powdered-product, as-consumed, and related qualifiers. Equal digits on
   different bases are not directly comparable.
4. **Food scope.** Printed categories split, merge, narrow, and absorb residual
   foods. Member panels expose item- or animal-level mappings where supported;
   rule objects retain scope text where a member mapping is not defensible.

## CSV inventory

The five rule-level files contain 46,337 released rules:

- `pollutant_limits_long.csv`: 739 rows.
- `pesticide_limits_long.csv`: 38,024 rows.
- `mycotoxin_limits_long.csv`: 61 rows.
- `vetdrug_limits_long.csv`: 1,365 rows.
- `additive_limits_long.csv`: 6,148 rows.

The five category or rule-group panels are:

- `pollutant_category_panel.csv`: 255 rows.
- `pesticide_panel.csv`: 11,718 rows.
- `mycotoxin_panel.csv`: 40 rows.
- `vetdrug_panel.csv`: 559 rows.
- `additive_panel.csv`: 2,762 rows.

The three supported member-level panels are
`pollutant_member_panel.csv` (384 rows), `mycotoxin_member_panel.csv`
(55 rows), and `vetdrug_member_panel.csv` (1,157 rows). No additive member
panel is released because dotted GB 2760 codes were reused or redefined across
editions and a dotted prefix does not establish inheritance.

The remaining thirteen CSV files provide audits, provenance, dates, lookups,
identifier changes, and schema metadata:

- `pesticide_edition_reconciliation.csv`: six edition-level count audits.
- `pesticide_ocr_crosscheck.csv`: 17,203 text-layer/OCR comparison keys for
  2019 and 2021.
- `standard_timeline_conflicts.csv`: two candidate rows for one deterministically
  resolved ancillary-timeline metadata conflict.
- `standard_version_timeline.csv`: 1,504 ancillary version events across a much
  broader set of food-safety standards.
- `version_dates.csv`: 21 edition-source date records.
- `quarantined_rows.csv`: 12 rejected extraction fragments.
- `source_manifest.csv`: 25 source-file fingerprints and relationships.
- `extraction_method_summary.csv`: released records by family, edition and
  row-level extraction method (20 rows).
- `record_id_changes.csv`: 1,215 record identifiers replaced, removed or added
  since v1.0.
- `entity_names_en.csv`: 753 stable-key entity labels.
- `additive_names_en.csv`: 221 Chinese Number System (CNS)-keyed additive
  labels.
- `food_category_names_en.csv`: 394 family-specific stable-key food labels.
- `data_dictionary.csv`: the field schema for the other 25 CSV files.

`data_dictionary.csv` has ten metadata columns: `table`, `column`, `type`,
`nullable`, `missing_value`, `allowed_values`, `key_role`, `description_en`,
`description_zh`, and `notes`. Its shell-style patterns, including `v20??`,
expand over actual headers. `validate.py` currently verifies all 466 fields in
the other 25 CSV files and fails on uncovered, ambiguous, mistyped, non-null,
or out-of-vocabulary values.

## Rule identifiers and source lineage

Each released rule has a deterministic `record_id`. The five long tables also
carry `edition_source_id` and `extraction_source_id`, both of which reference
`source_manifest.csv`:

- `edition_source_id` identifies the file that establishes the regulatory
  edition represented by the row.
- `extraction_source_id` identifies the file from which the released fields
  were extracted.
- The identifiers are equal when one file serves both roles.
- For GB 2763-2019 and GB 2763-2021, the identifiers differ. The scanned
  editions are the edition-identity anchors; government-hosted text-layer
  copies supply the released coordinates and text fields.

`conflict = 1` means that multiple released rows share the declared business
key. Such rows can contain different values or distinct printed rules with the
same value. Inspect every rule or the panel lineage fields before resolving
them. Exact duplicate records cause the release builder to fail; distinct
rules are retained.

`record_id` is a digest of the row's fields as built; the fields added in v1.1
(the long tables' source, extraction-method and verification fields, the panels'
`source_record_ids_YYYY` and `count_mismatch_editions`) are not digested. It
stays the same across releases only while the digested fields, including values,
labels and, for panels, trend, are unchanged; a correction to them gives the row
a new identifier. Two tables digest fewer fields. `pesticide_limits_long.csv`
digests the printed rule (edition, raw pesticide names, raw parent category, raw
food, value, unit, qualifier and temporary flag), so a correction to a derived
label alone, such as `parent_category_zh`, keeps the identifier.
`pesticide_panel.csv` derives its identifier from `pesticide_key` and `food_key`
alone. For
longitudinal use across releases, join on the natural keys below rather than on
`record_id`. `record_id_changes.csv` pairs the previous and current identifiers
on the same keys and lists rows that were removed or added.

| Table | Natural key |
|---|---|
| `pollutant_limits_long.csv` | `version_year`, `analyte_zh`, `food_category_zh`, `limit_basis` |
| `pesticide_limits_long.csv` | `version_year`, `section_number`, `source_page`, `source_y`; `pesticide_key` and `food_key` group rules across editions |
| `mycotoxin_limits_long.csv` | `version_year`, `toxin_zh`, `food_category_zh` |
| `vetdrug_limits_long.csv` | `version_year`, `drug_zh`, `animal_raw`, `tissue_zh` |
| `additive_limits_long.csv` | `version_year`, `cns_code`, `food_code` |
| `pollutant_category_panel.csv` | `analyte_zh`, `food_category_zh` |
| `pollutant_member_panel.csv` | `analyte_zh`, `food_member_zh` |
| `pesticide_panel.csv` | `pesticide_key`, `food_key` |
| `mycotoxin_panel.csv` | `toxin_zh`, `food_zh` |
| `mycotoxin_member_panel.csv` | `toxin_zh`, `food_member_zh` |
| `vetdrug_panel.csv` | `drug_en`, `tissue_zh` |
| `vetdrug_member_panel.csv` | `drug_zh`, `animal`, `tissue_zh` |
| `additive_panel.csv` | `cns_code`, `food_code` |

Each key is unique within the release except in two tables. In
`additive_limits_long.csv`, one `cns_code` and `food_code` pair can carry
several printed rules in the same edition, such as a general limit and a limit
restricted to one food; `additive_panel.csv` holds them together in
`rules_YYYY`. In `pollutant_category_panel.csv`, an analyte and category pair
appears once for each basis of expression and is told apart by the
`basis_YYYY` fields.

## Row-level sources, extraction methods and verification

Each long table ends with four fields:

- `source_reference` cites the edition (for example `GB 2763-2019`), adds the
  page or table row where one was recorded, and ends with a public locator URL.
  Pages are recorded for all pesticide rows (the PDF page of the extraction
  file), Word table rows for the 2002 veterinary-drug rows, and the PDF page,
  printed table and row for the 144 manually transcribed rows. The URL links a
  file directly only when the frozen bytes match it; otherwise it identifies the
  standard.
- `extraction_method` is the row-level read path:
  `pdf_text_and_coordinate_parser`, `pdf_text_layer`, `word_table_stream`, or
  `manual_page_image_transcription`. `extraction_method_summary.csv` counts the
  records by family, edition and method.
- `verification_status` is `confirmed_agreement`, `unresolved_disagreement`, or
  `no_cross_source_comparison`.
- `verification_basis` lists the evidence in a fixed order, or `none`:
  `ocr_crosscheck` (the GB 2763-2019/2021 OCR comparison of the value),
  `independent_audit_reading` (two rounds of independent, stratified reading of
  the 2019/2021 scans), `independent_blind_reentry` (independent blind re-entry
  of all 144 manually transcribed rows), and `author_scan_check` (the author's
  check of the edition scan behind a recorded correction).

A reading against the source settles a row before the automated OCR comparison
does, and a release error found by a reading counts as agreement only after it
was corrected. `no_cross_source_comparison` records the absence of a usable
second source; it is not evidence of an error.

## Pesticide stable keys and rule-preserving panel

`pesticide_limits_long.csv` assigns two deterministic ASCII keys:

- `pesticide_key` begins with `PST-` and hashes a normalised English common
  name, with a Chinese-name fallback.
- `food_key` begins with `FOD-` and hashes a conservative normalisation of the
  Chinese base-food label. Parenthetical scope remains in `food_raw` and in
  the rule objects.

These keys group typographic variants without discarding scope evidence.
`pesticide_zh_raw`, `pesticide_en_raw`, `parent_category_raw`, `food_raw`,
`value_raw`, `limit_qualifier`, and `is_temporary` preserve the evidence needed
to audit the grouping and comparison.

For each edition, `pesticide_panel.csv` uses this repeated contract:

| Template | Meaning |
|---|---|
| `status_YYYY` | `missing`, `single_rule`, `multiple_rules_same_value`, or `multiple_rules_distinct_values` |
| `vYYYY` | Scalar value only when `status_YYYY == single_rule`; blank otherwise |
| `values_YYYY` | JSON array of all distinct values in the cell |
| `units_YYYY` | JSON array of all represented units |
| `source_record_ids_YYYY` | JSON array of contributing `pesticide_limits_long.csv` record identifiers |
| `source_ids_YYYY` | JSON union of edition and extraction source identifiers |
| `edition_source_ids_YYYY` | JSON array of edition-source identifiers |
| `extraction_source_ids_YYYY` | JSON array of extraction-source identifiers |
| `rules_YYYY` | JSON array of every contributing rule, including scope, qualifier, source, and locator fields |
| `candidate_count_YYYY` | Number of contributing rules; equals both lineage-array lengths |
| `distinct_value_count_YYYY` | Number of entries in `values_YYYY` |

A numeric pesticide trend is assigned only after the following gates pass: one
rule per represented edition, compatible units, no unresolved review or source
qualifier, equivalent normalised scope, and numeric values. The remaining
states include `incomparable_multiple_rules`, `incomparable_units`,
`incomparable_scope_text`,
`incomparable_unresolved_review_or_source_qualifier`, and
`incomparable_non_numeric`. A trend is also withheld as
`incomparable_edition_gap` when the editions holding a rule skip an edition in
between. `single_version` carries no cross-edition trend.
`count_mismatch_editions` lists the represented editions whose visible rule
count differs from the declared aggregate (2016 and 2019); trends that depend on
them are kept and flagged.

`pesticide_names_zh` and `food_names_zh` preserve all normalised display labels
represented by a stable key. Inspect `rules_YYYY` whenever these arrays contain
multiple labels or the trend starts with `incomparable_`.

`review_status` is a semicolon-delimited set drawn from this fixed component
vocabulary:

| Component | Meaning | Effect on numeric trend assignment |
|---|---|---|
| `text_layer_auto_extracted` | Base flag for a coordinate-parser row | None by itself |
| `source_structure_exception` | A documented source-layout exception was handled | None by itself; inspect the rule object |
| `source_glyph_correction` | A documented source glyph was normalised during extraction | None by itself; retain `value_raw` |
| `food_label_continuation_joined` | A wrapped food label was joined | None by itself; retain `food_raw` |
| `food_value_multiline_joined` | A wrapped food/value row was joined | None by itself; inspect the locator |
| `margin_header_overlap_removed` | A repeated margin/header overlap was removed | None by itself; inspect the locator |
| `source_qualifier_unresolved_c` | Source marker `c` remains semantically unresolved | Blocks numeric trend assignment |
| `scan_temporary_mark_correction` | The edition scan prints no temporary-limit asterisk that the extraction copy prints; `is_temporary` and `limit_qualifier` follow the scan | None by itself; `value_raw` keeps the copy's text |

These flags describe extraction and local adjudication. None certifies an
independent human re-transcription. The trend gate also fails closed for any
future component containing `unresolved`, `uncertain`, `ambiguous`, `pending`
or a `review_` prefix.

## Other panels

`additive_panel.csv` groups exact normalised CNS code and GB 2760 food code.
Its repeated fields are `status_YYYY`, `vYYYY`, `values_YYYY`, `units_YYYY`,
`source_record_ids_YYYY`, `rules_YYYY`, `candidate_count_YYYY`, and
`distinct_value_count_YYYY`. Additive cell states are `missing`, `single`,
`multiple_same_value`, and `multiple_distinct_values`. A difference in
normalised `food_zh` or `note` among represented one-rule editions yields
`incomparable_scope_text` before a numeric or good-manufacturing-practice
(GMP) trend is assigned.

The pollutant panels retain the printed unit and basis for each edition:
`vYYYY`, `unit_YYYY`, `basis_YYYY`, `cell_status_YYYY`, and
`source_category_YYYY`. `unit_summary` exposes cross-edition unit changes.
`pollutant_member_panel.limit_basis` is blank when all represented rows are
unqualified and is `varies_by_version` when represented basis states differ.

`vetdrug_panel.csv` may retain slash-separated unresolved multi-animal values.
Use `vetdrug_member_panel.csv` for animal-specific scalar comparisons.
`mycotoxin_member_panel.csv` and `pollutant_member_panel.csv` similarly expose
host-category restructuring for the mappings supported by their taxonomies.

In `pollutant_member_panel.csv` a member takes, in each edition, its own
printed rule or else the rule of the first ancestor category that has a value
and does not exclude it. An exclusion written as "A和B" excludes both A and B,
"X及其制品" excludes X and X制品, and any other "X及其Y" excludes X; a printed
"X及其Y" rule, such as `果蔬汁类及其饮料`, is also X's own rule. The walk stops
at the first ancestor rule found. That edition's cell is left blank in three
cases: the rule excludes the member and no separate limit for the analyte is
located; the
member spans two printed rules (in 2022 `蒸馏酒` splits into `白酒` at 0.5 and
other spirits at 0.2 mg/kg); or the member is named in another edition's
exclusion list that differs from this rule's, so the printed text does not
fix its host. `note` names the edition and the reason for each such blank,
with groups separated by ` | `. Rows left with fewer than two editions are not
released. Where Appendix A or the limit table shows that a name was renamed or
lies within another category, the author confirmed the link against the cited
page before it was used: five renames (`双壳类` = `双壳贝类`, `固体饮料类` =
`固体饮料`, the 2022 rewording of the cereal list `稻谷糙米大米小麦小麦粉玉米玉米面`
= `稻谷糙米大米小麦小麦粉玉米玉米粉玉米糁`, `矿泉水` = `饮用天然矿泉水`, `咖啡豆` =
`生咖啡豆及烘焙咖啡豆`), which count as the same name in both panels, and seven
containment links (`白酒` within `蒸馏酒`, `大米` within `大米(粉)`, `八宝粥罐头`
within `粥类罐头`, `蔓越莓` and `醋栗` within `浆果和其他小粒水果`, `肝脏制品`
within `畜禽肝脏及其制品`, `肾脏制品` within `畜禽肾脏及其制品`), which are used
only to find a member's host.

Every panel carries `source_record_ids_YYYY`, a JSON array of the long-table
records that each edition cell reports. Across panels a trend is withheld when
the represented editions skip an edition (`incomparable_edition_gap`), when an
edition holds more than one applicable rule (`incomparable_multiple_rules`), or
when the compared scope differs (`incomparable_scope_text`). Scope differs for
a contaminant category when its printed head or exclusion list changes
(confirmed renames count as equal), and for a contaminant member when the
exclusions of the host category it heads change. For mycotoxins it differs when
the 2011 and 2017 printed categories differ, or when the exclusions of a
member's own listed item change; a bracket qualifies only the listed item it
follows. For the veterinary-drug summary it differs when the 2002 and 2019 rules
cover different animals.

## Pesticide extraction and the three audit tables

GB 2763-2019 and GB 2763-2021 were extracted from government-hosted text-layer
copies. Their original scanned editions establish edition identity and provide
an OCR cross-check. Government hosting alone does not establish issuing-authority
certification of a particular byte stream, so both file roles and hashes remain
visible in `source_manifest.csv` and the long-table source identifiers.

`pesticide_ocr_crosscheck.csv` compares the text-layer extraction with OCR from
the scanned anchors. It contains 3,701 `consistent`, 9 `conflict`, 13,490
`text_only`, and 3 `ocr_only` comparison keys. These outcomes are diagnostic;
they do not overwrite released text-layer rules. Six GB 2763-2019 Table 111
rows follow the edition scan for the temporary-limit mark (see `review_status`).
Users can filter by `status`,
`key_level`, row counts, and source pages when choosing a review sample.

`pesticide_edition_reconciliation.csv` compares the printed aggregate MRL count
with visible coordinate-extracted rules and separately checks the complete
section roster. Four editions reconcile exactly. GB 2763-2016 has eight fewer
visible rules than its printed aggregate, and GB 2763-2019 has one more. All six
section rosters are complete. The file records these two aggregate differences
as unresolved and retains every visible rule. An aggregate match provides no
record-level accuracy guarantee.

`standard_timeline_conflicts.csv` records every candidate and the deterministic
selection reason for a duplicated official-version key in the ancillary
`standard_version_timeline.csv`. The ancillary timeline supplies context and
must not replace `version_dates.csv` as the edition-identity date table.

## Source manifest roles

`source_manifest.csv` has 25 rows:

- 21 `edition_source` rows: 17 directly extracted files, two scanned
  `identity_anchor_crosscheck` editions for GB 2763-2019/2021, and two
  `archived_unextracted` editions.
- Two `extraction_copy` rows for the 2019/2021 government-hosted text-layer
  copies. Each points to its scanned anchor through `related_source_id`.
- Two `identity_audit_copy` rows excluded from extraction. Their filenames
  claim “Amendment No. 1”, while content inspection shows full GB 2762 standard
  text; each points to the corresponding edition source.

`source_class` places each file in one of four classes: 19
`issuing_authority_file` rows (edition texts issued by the standard-setting
authority; the locator status in `SOURCE_ACQUISITION.md` states whether the
frozen bytes match a current issuer download), two `government_hosted_copy`
rows (the 2019/2021 extraction copies), and four `audit_only_copy` rows (the two
scanned anchors and the two misnamed full-text copies, from which no released
value is read). The four English translations are listed as
`third_party_translation` in `SOURCE_ACQUISITION.md`.

Every row records a portable basename, file size, SHA-256 digest, extraction
mode, document identity, and page count where applicable. Acquisition URLs are
present only where recorded. Blank `retrieved_date` values mean that no
retrieval date was captured; they must not be inferred.

`SOURCE_ACQUISITION.md` supplements the manifest with public locators checked
on 16 July 2026. It distinguishes exact-byte official downloads, standard
identity pages, public reference files whose bytes differ from the frozen
input, and the two recorded government extraction-copy URLs. Only SRC0002 and
SRC0007 currently have issuing-authority downloads whose size and SHA-256 match
the frozen Chinese input. SRC0024 and SRC0025 retain their original recorded
URLs, while their original retrieval dates remain unrecorded. The guide also
locks the filename, byte size, SHA-256 digest, public locator and recorded
retrieval date for all four unofficial English translations. A locator checked
after construction does not reconstruct original acquisition provenance.

The release directory does not bundle the 25 source files or the cited
third-party translation PDFs. Source-dependent validation requires separately
obtained files with the recorded basenames and, for manifest entries, matching
sizes and SHA-256 digests. The validator also enforces the four translation
byte locks recorded in `SOURCE_ACQUISITION.md`.

## English-name lookups

`entity_names_en.csv` uses `entity_key`; pesticide rows share the same stable
`PST-` key as the pesticide long table and panel. `additive_names_en.csv` joins
to additive records by `cns_code`. `food_category_names_en.csv` uses a
family-specific stable key:

- `family == additive`: join `food_key` to
  `additive_limits_long.food_code`.
- `family == pesticide`: join `food_key` to the `FOD-` key in
  `pesticide_limits_long.food_key` or `pesticide_panel.food_key`.

Lookup coverage is partial. An unmatched stable key means that no label passed
the stated matching gates against the cited translations. It does not imply
that an English term has no possible translation. `match_method`, `evidence`,
and `source_doc` retain the join evidence and attribution.

For use without Chinese-language matching, retain `pesticide_key` and
`food_key` as the analytical identifiers and left-join the English lookups.
Keep unmatched keys in the analysis; dropping them would make the sample depend
on translation coverage.

Additive and food labels drawn from unofficial third-party English translations
remain attributed to those documents and are not relicensed as author-created
translations. The principal lookup sources are the USDA Foreign Agricultural
Service translations of GB 2760-2014 and GB 2763-2016. See `LICENSE.md`.

### Five-family language-coverage matrix

| Family | Substance names | Food/animal/tissue English coverage | Stable machine join |
|---|---|---|---|
| Contaminants | English names printed by the standard occur in every long-table row | No released English food-category labels | Use panel `record_id` as an opaque within-table group ID; retain `food_category_zh` or `food_member_zh` |
| Pesticides | English names printed by the standard occur in every long-table row | 125 of 434 stable food keys; these keys cover 70.68% of long-table rows | `pesticide_key` and `food_key`; left-join the two English lookup tables |
| Mycotoxins | English names printed by the standard occur in every long-table row | No released English food-category labels | Use panel `record_id` as an opaque within-table group ID; retain the Chinese food field |
| Veterinary drugs | English names printed by the standard occur in every long-table row | No released English animal or tissue labels | Use panel `record_id` as an opaque within-table group ID; retain `animal`, `animal_raw` and `tissue_zh` |
| Additives | 221 of 320 represented CNS codes have a released English name | 269 of 279 represented food codes have a released English label | Join names by `cns_code` and foods by `food_code` |

The opaque `record_id` values permit deterministic within-table joins and
filters; they do not convey category semantics. For the three families without
food-scope English labels, a researcher who cannot read Chinese must retain the
source Chinese field and obtain a separately documented translation before
interpreting or relabelling a category. This limitation is deliberate because
the tested translation signatures did not support reliable released links.

## Missing values and regulatory sentinels

- A blank CSV field means unavailable or inapplicable according to that
  field's `missing_value` entry in `data_dictionary.csv`. A blank panel cell
  does not establish withdrawal of a limit.
- `GMP` is a valid non-numeric good-manufacturing-practice use condition. Its
  `unit` is blank by design.
- `g/份` means grams per serving and remains unconverted without a defensible
  serving mass.
- A blank `pollutant_limits_long.limit_mgkg` paired with
  `normalization_status = density_required` prevents an `mg/L` value from
  being treated as `mg/kg`.
- An em dash in `additive_limits_long.ins_code` records an explicit printed
  absence of an International Numbering System (INS) number. A blank field
  records a value that was not
  recovered.
- JSON arrays use `[]` for an empty collection; they are never encoded as a
  blank scalar.
- Placeholder strings such as `NA`, `N/A`, `null`, `.`, and `-` are not used
  as missing-value sentinels.
- Blank dates in the GB 2760-1996 `version_dates.csv` row are governed by
  `date_status = not_printed` and its explicit `date_resolution`.

## Locator coverage and traceback boundary

Locator coverage differs by extraction family:

- All 38,024 pesticide rules carry `section_number`, `source_page`, `source_y`,
  `food_x`, `parent_assignment_method`, and `table_open_method`. For 2019/2021
  those coordinates refer to the text-layer extraction copies, while
  `edition_source_id` retains the scanned anchors.
- All 551 MOA Announcement 235 rows carry `source_table_index`,
  `source_table_row`, `animal_block_index`, and `tissue_index`. These Word-stream
  locators are blank for the 814 veterinary-drug rows extracted from the 2019
  and 2022 PDFs; `source_reference` gives the PDF page, printed table and row
  for the 135 of those rows that were transcribed manually.
- Pollutant, mycotoxin, and additive long tables carry edition/extraction source
  identifiers and rule fields but no released page-coordinate columns.

`source_manifest.csv` provides file-level provenance. It does not create a
page locator where the family extractor did not release one. The optional
source-dependent positional checks in `validate.py` are diagnostics over
predeclared cases and do not imply full independent manual re-entry.

`quarantined_rows.csv` contains six additive fragments and six pollutant
fragments rejected by extraction gates. They remain outside the released long
tables. Family-specific entity fields identify which schema applies to each
quarantined row.

## Validation

Run package-internal checks from any working directory:

```bash
python validate.py
```

The default package directory is the directory containing `validate.py`.
`--output` selects another report path. The internal layer checks file presence,
headers, CSV integrity, build statistics, keys, edition coverage, conflict
flags, all dictionary declarations, lineage, missing values, normalisation,
panel contracts, audit tables, source relationships, row-level sources and
verification fields, identifier changes, dates, and README contracts.

Source standards, extraction copies, and cited translations may live in
different directories. Repeat `--source-root` to validate their union:

```bash
python validate.py \
  --source-root /path/to/standard-archive \
  --source-root /path/to/extraction-copies \
  --source-root /path/to/cited-translations \
  --require-source-checks
```

The validator indexes the supplied roots by basename and verifies manifest
size/SHA-256 fingerprints and all four translation byte locks before
source-dependent checks. Repeating
`--source-root` does not change the recorded portable labels. A missing,
ambiguous, or hash-mismatched file cannot satisfy a source check.

Generated manuscript tables are external to the release. Supply them explicitly
when needed:

```bash
python validate.py \
  --results-tab /path/to/project/Results/tab \
  --source-root /path/to/standard-archive \
  --source-root /path/to/extraction-copies \
  --source-root /path/to/cited-translations \
  --require-source-checks
```

`--auto-results-tab` opts into parent-directory discovery for repository
maintainers. Portable package validation leaves it off.

Validation statuses have fixed meanings:

- `pass`: the check ran and met its criterion.
- `fail`: the check ran and found a problem.
- `skip`: a supplied dependency lacked a required file or case.
- `not_run`: a dependency or executable was unavailable, so the check was not
  attempted.

`skip` and `not_run` never count as pass. A report containing either is
`partial`. `--require-source-checks` returns a nonzero exit code when any
source-dependent check is skipped or not run. The report records UTC time,
runtime details, Git state where available, package hashes, and hashes of every
external file actually used. External paths are stored relative to their
declared root label.

## Minimal Python example

```python
import json
import pandas as pd

panel = pd.read_csv(
    "pesticide_panel.csv",
    dtype=str,
    keep_default_na=False,
    encoding="utf-8-sig",
)

single_2026 = panel.loc[panel["status_2026"] == "single_rule"].copy()
single_2026["v2026"] = pd.to_numeric(single_2026["v2026"])

multiple = panel.loc[panel["status_2026"].str.startswith("multiple_rules_")].copy()
multiple["all_2026_values"] = multiple["values_2026"].map(json.loads)
multiple["source_rows"] = multiple["source_record_ids_2026"].map(json.loads)
multiple["rules"] = multiple["rules_2026"].map(json.loads)

food_en = pd.read_csv(
    "food_category_names_en.csv",
    dtype=str,
    keep_default_na=False,
    encoding="utf-8-sig",
).loc[lambda x: x["family"] == "pesticide", ["food_key", "food_en", "source_doc"]]

entity_en = pd.read_csv(
    "entity_names_en.csv",
    dtype=str,
    keep_default_na=False,
    encoding="utf-8-sig",
).loc[lambda x: x["entity_type"] == "pesticide", ["entity_key", "name_en"]]
entity_en = entity_en.rename(columns={"entity_key": "pesticide_key", "name_en": "pesticide_en"})

panel = panel.merge(food_en, on="food_key", how="left", validate="many_to_one")
panel = panel.merge(entity_en, on="pesticide_key", how="left", validate="many_to_one")
```

## Reuse and legal caution

This is a derived research resource and is not an authoritative legal source.
Verify consequential limits against an issuing-authority file of the standard.
The package license,
source-text boundaries, and third-party-label notices are in `LICENSE.md`.
