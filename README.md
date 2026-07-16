# China Food Safety Maximum-Limit Panel: code and build evidence

Curated code-and-evidence archive behind the Data Descriptor "A cross-edition panel
of chemical limits in China's food safety standards". The dataset itself (24 CSV
files holding 46,337 limit records from five mandatory Chinese food-safety standard
families, 2002–2026) is deposited at figshare under the reserved DOI
`10.6084/m9.figshare.33005717` and becomes public upon journal acceptance. This
repository holds the extraction, alignment, release-assembly, testing and validation
code, plus frozen intermediate evidence, exported from the private build workspace.

Licences: the code is MIT-licensed (see `LICENSE`); the released dataset carries
CC BY 4.0 (see `Data/Final/china_food_limit_panel_v1/LICENSE.md`). Source standards
are not redistributed; the data package's `SOURCE_ACQUISITION.md` explains how to
obtain them from the issuing bodies. A good entry point is
`Data/Final/china_food_limit_panel_v1/validate.py`, whose 21 self-contained checks
run offline.

## Layout

| Path | Contents |
|---|---|
| `Program/Clean/` | Extraction, release assembly, source manifest, English-label linkage, timeline generation, and tests |
| `Program/Analysis/` | Generates the manuscript tables and figures from `Data/Final` |
| `Data/Interim/` | Frozen build evidence (manual-transcription replays, blind re-entry packet, OCR adjudications, text-layer reconciliation) |
| `Data/Final/china_food_limit_panel_v1/` | Data-package documentation, licence, `validate.py` and the frozen validation report |
| `Results/tab/`, `Results/fig/` | The standard result interface used by the manuscript |

Not included: source-standard PDFs (not redistributed), the manuscript source, and
the per-word OCR dumps (see "Reproducibility boundary").

## Release at a glance

- Five long tables: contaminants 739, pesticide residues 38,024, mycotoxins 61,
  veterinary-drug residues 1,365, food additives 6,148; 46,337 records in total.
- `source_manifest.csv` holds 25 source-identity rows: 21 edition sources (19
  contributing released data, 2 archived unextracted), 2 government text-layer
  extraction copies, and 2 audit copies titled "Amendment No. 1" whose rendered
  content is the full standard text (excluded from extraction).
- The release ships 24 CSV files; derived panels, lookups and the 12 quarantined
  rows do not count toward the 46,337 long-table total.
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

This runs the 21 self-contained checks; the 30 optional external-input checks are
recorded as `not_run` and the overall status is `partial`. With a legally held
source tree and the generated tables, the full run is:

```bash
python Data/Final/china_food_limit_panel_v1/validate.py \
  --source-root /path/to/source-library \
  --results-tab Results/tab \
  --require-source-checks
```

The frozen report passes 51 of 51: 21 in-package checks, 28 source-tree checks and
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
```

Four tables are written to `Results/tab/` and three figures to `Results/fig/`. The
scripts read `Data/Final` directly and assert on key cases, per-edition row counts,
the shipped file inventory and standard identities. The figure script accepts only
the `edition_source` byte streams registered in `source_manifest.csv` and fails
rather than guessing.

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
