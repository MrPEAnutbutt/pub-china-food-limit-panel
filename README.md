# China Food Safety Maximum-Limit Panel: code and build evidence

Curated code-and-evidence archive behind the Data Descriptor "A cross-edition panel
of chemical limits in China's food safety standards". The dataset itself (26 CSV
files holding 46,337 limit records from five mandatory Chinese food-safety standard
families, 2002–2026) is deposited at figshare under the DOI
`10.6084/m9.figshare.33005717`. This repository holds the extraction, alignment, release-assembly, testing and
validation code, plus frozen intermediate and verification evidence, exported from
the private build workspace. Archive versions 1.1.0 to 1.1.3 match release v1.1
of the dataset, and 1.1.3 is the current one (see "Versions").

Licences: the code is MIT-licensed (see `LICENSE`); the released dataset carries
CC BY 4.0 (see `Data/Final/china_food_limit_panel_v1/LICENSE.md`). Source standards
are not redistributed; the data package's `SOURCE_ACQUISITION.md` explains how to
obtain them from the issuing bodies. A good entry point is
`Data/Final/china_food_limit_panel_v1/validate.py`, whose 23 self-contained checks
run offline.

## Layout

| Path | Contents |
|---|---|
| `Program/Clean/` | Extraction, release assembly, source manifest, English-label linkage, timeline generation, independent-verification sampling and comparison, identifier-change tracking, and tests |
| `Program/Analysis/` | Generates the manuscript tables, figures and number macros; `DatapaperUsage.py` is a worked example that links panels to long tables and source files |
| `Data/Interim/` | Frozen build evidence (manual-transcription replays, OCR adjudications, text-layer reconciliation, panel-trend audits) and independent-verification evidence (see below) |
| `Data/Final/china_food_limit_panel_v1/` | Data-package documentation, data dictionary, licence, `validate.py` and the frozen validation report |
| `Results/tab/`, `Results/fig/` | The standard result interface used by the manuscript |

Not included: source-standard PDFs (not redistributed), the manuscript source, the
per-word OCR dumps (see "Reproducibility boundary"), and the verifier's signed
declarations, completed workbooks and handoff packets (see "Independent
verification evidence").

## Release at a glance

- Five long tables: contaminants 739, pesticide residues 38,024, mycotoxins 61,
  veterinary-drug residues 1,365, food additives 6,148; 46,337 records in total.
- `source_manifest.csv` holds 25 source-identity rows: 21 edition sources (19
  contributing released data, 2 archived unextracted), 2 government text-layer
  extraction copies, and 2 audit copies titled "Amendment No. 1" whose rendered
  content is the full standard text (excluded from extraction).
- The release ships 26 CSV files; derived panels, lookups, summaries, the
  identifier-change table and the 12 quarantined rows do not count toward the
  46,337 long-table total.
- Every long-table row names its source edition and file (`source_reference`),
  its extraction method (`extraction_method`, summarised in
  `extraction_method_summary.csv`) and its independent cross-check status
  (`verification_status`, `verification_basis`). `record_id_changes.csv` lists
  the 1,215 identifiers that changed from v1.0 to v1.1.
- The 2019 and 2021 pesticide rows were parsed from government-hosted text-layer
  copies. The archived edition scans carry edition identity and provide a frozen OCR
  cross-check: of 17,203 comparison groups, 3,701 agree, 9 conflict, 13,490 appear
  only in the text layer and 3 only in OCR. The scans carry stamp occlusion and
  limited OCR recall, so the cross-check is not a complete error-rate estimate for
  the released rows.

## Validation

Offline, from any working directory:

```bash
python Data/Final/china_food_limit_panel_v1/validate.py
```

The self-contained checks need the data package files next to `validate.py`;
download the package from figshare into
`Data/Final/china_food_limit_panel_v1/` first. This runs the 23 self-contained
checks; the 30 optional external-input checks are recorded as `not_run` and the
overall status is `partial`. With a legally held source tree and the generated
tables, the full run is:

```bash
python Data/Final/china_food_limit_panel_v1/validate.py \
  --source-root /path/to/source-library \
  --results-tab Results/tab \
  --require-source-checks
```

The frozen report passes 53 of 53: 23 in-package checks, 28 source-tree checks and
2 generated-table checks, with zero `fail`, `skip` or `not_run`. Catalogue size is
not a pass count, and skipped or unrun checks never count as passes. The report
records status and evidence per check, and pins the sha256 of package files and of
the external inputs actually used (excluding the report itself), with paths relative
to their declared roots.

The directory name passed to `--source-root` becomes the label prefix inside the
report; do not rename it. Expected source identities and public locations are listed
in the data package's `SOURCE_ACQUISITION.md`.

## Regenerating the manuscript tables and figures

```bash
python Program/Analysis/DatapaperTables.py
python Program/Analysis/DatapaperFigures.py --source-root /path/to/source-library
python Program/Analysis/DatapaperUsage.py
```

Nine tables and the number macros `DatapaperNumbers.tex` are written to
`Results/tab/` and three figures to `Results/fig/`. The scripts read `Data/Final`
directly and assert on key cases, per-edition row counts, the shipped file
inventory and standard identities; the independent-verification table and its
macros also read the frozen evidence in `Data/Interim/pesticide_audit/`,
`Data/Interim/pesticide_audit_round2/` and
`Data/Interim/manual_reentry/reconciliation/04_attested/`. The figure script
accepts only the `edition_source` byte streams registered in `source_manifest.csv`
and fails rather than guessing. `DatapaperUsage.py` needs only pandas; with
`--release-dir` it runs against a downloaded copy of the package and writes the
example counts to `Results/tab/DatapaperUsageNumbers.tex`.

## Independent verification evidence

A university researcher who took no part in building the database (pseudonym
IR-01) read sampled rows from the source standards without access to the
released values. The archive keeps the protocol, the sample, what was returned,
the comparison and the adjudication:

| Path | Contents |
|---|---|
| `Data/Interim/manual_reentry/blind_packet/` | Blind re-entry protocol and packet manifest for the 144 manually transcribed mycotoxin and veterinary-drug records |
| `Data/Interim/independent_review/returned/` | Round 1 returns: the three completed re-entry files, the 300-row pesticide reading, the reviewer attestation and receipts |
| `Data/Interim/manual_reentry/reconciliation/` | Field-by-field comparison of the re-entry with the construction seeds, in four stages from the initial comparison to the attested result, with the author's adjudications |
| `Data/Interim/pesticide_audit/` | Round 1 pesticide sample (288 random rows from GB 2763-2019 and GB 2763-2021, plus 9 conflict rows and 3 OCR-only groups), comparison and adjudication |
| `Data/Interim/independent_review_round2/returned/` | Round 2 return: the 258-row pesticide reading and receipts |
| `Data/Interim/pesticide_audit_round2/` | Round 2 redraw after the category-rule correction, its comparison, and `category_corrections.csv` listing the 1,019 corrected pesticide categories |

The `README.md` in `blind_packet/`, `pesticide_audit/` and
`pesticide_audit_round2/` is the protocol as frozen before the reading; its digest
is pinned in `packet_manifest.json` or `audit_manifest.json`, so its "Status:
awaiting …" line records the state at that point and is not updated. The results
are in `reconciliation/04_attested/` and in each `comparison/` directory. The
blank `blind_packet/reviewer_attestation.json` is the form handed out; the
completed one is in `independent_review/returned/`. The receipts pin the sha256 of the signed declarations
and completed workbooks, which are withheld because they can carry the verifier's
signature or editing-account metadata.

## Tests

```bash
python -m unittest discover -s Program/Clean/tests
```

In the build workspace the suite runs 351 tests with 4 skipped. Some tests need
files this archive does not ship: the data package (download it into
`Data/Final/china_food_limit_panel_v1/`), the withheld OCR dumps, the additive
interim tables regenerated from the source PDFs, and the workspace's
`.gitignore` rules for source documents. Without them those tests fail or error
rather than pass.

## Reproducibility boundary

The mycotoxin and veterinary-drug manual-transcription tables are replayed as frozen
construction evidence and are not regenerated algorithmically; replay is the
extraction method, not an independent verification of those records. The scripts
take source and interim directories on the command line and do not depend on
machine-specific absolute paths.

The per-word OCR dumps (`ocr_words_*.tsv`, with coordinates) can reconstruct the
scanned editions' text and are therefore not included in this archive. The `git`
field inside `validation_report.json` records a commit of the private build
workspace, not of this repository's history.
`Data/Interim/pesticide_ocr/completion_manifest.json` pins the dumps' sha256
digests, so a rerun of OCR over the reacquired scans can be verified byte for byte.

## Withdrawn evidence

An early internal LLM image re-reading lacked records of the model, prompts and raw
outputs, and its results were withdrawn from the formal Technical Validation
evidence. If it is ever reinstated, the run metadata, page images, raw outputs and
difference tables should be archived first.

## Versions

All versions share the Zenodo concept DOI `10.5281/zenodo.21397471`.

- **1.1.3** — the manuscript tables, figure captions and number macros as revised
  for the resubmission: shorter table and figure captions, Table 4 without the
  declared-rule-total row, and the pesticide count-reconciliation numbers read from
  the frozen text-layer extraction report. No released data value changed.
- **1.1.2** — the manuscript tables and figure captions as revised in the first
  round of peer review (Table 2 with one column per extraction method, Tables 4 and
  6 condensed, source-class terminology), the data package's README and data
  dictionary describing the date register as a register of current national
  food-safety standards, and the validation report regenerated for these files.
  No released data value changed.
- **1.1.1** — created from the same commit as 1.1.0 before the 1.1.2 changes were
  pushed; its content is identical to 1.1.0.
- **1.1.0** — code and evidence behind dataset release v1.1, prepared in the first
  round of peer review: corrected pesticide categories, temporary-limit marks and
  veterinary-drug labels; stricter panel comparability rules; row-level source,
  extraction-method and verification fields; identifier-change tracking; the
  independent-verification evidence; nine manuscript tables and the usage example.
- **1.0.0** (`10.5281/zenodo.21397472`) — code and evidence behind dataset release
  v1.0, as first submitted.
