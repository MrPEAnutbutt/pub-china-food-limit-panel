# Portable standard-timeline replay

This directory freezes the deterministic outputs of
`Program/Clean/build_version_timeline.py`. The replay used six explicit input
roles:

1. `standards_catalog.csv`, the local standards catalogue;
2. `食品安全国家标准全量清单_2026-01-12.xlsx`, the official-register export;
3. the categorised standard-PDF anchor directory;
4. `source_manifest.csv`, whose `edition_source` rows define the descriptor's
   source-edition coverage; and
5. `Data/Interim/standard_cover_dates.csv`, the cover-date transcription; and
6. `official_date_corrections.csv`, a source-backed correction layer for
   verified errors in the official-register export.

Input locations are injected at run time. No machine-specific absolute path is
stored in these outputs. The `path` column in `standard_versions_long.csv` is a
basename locator.

## Frozen interfaces

- `standard_versions_long.csv`: 1,504 dated-edition or amendment events for
  1,348 standard identities (1,470 formal editions and 34 amendments).
- `standard_timeline.csv`: one history summary row per standard identity.
- `standard_timeline_conflicts.csv`: the two candidates in one official-register
  metadata conflict (`GB 14936-2012`), with the selected candidate and ranking
  reason retained.
- `coverage_version_dates.csv`: exactly the 21 `edition_source` identities in
  the five-family release manifest. The three veterinary identities remain
  separate: `MOA Announcement 235-2002`, `GB 31650-2019`, and
  `GB 31650.1-2022`.
- `official_date_corrections.csv`: one expected-old-value correction. The
  official-register export reports the effective date of `GB 1886.5-2015` as
  `2015-03-22`, which predates its `2015-09-22` issue date. The original
  standard PDF in the National Health Commission's 2015 No. 8 announcement
  prints `2016-03-22` as the effective date. The row retains the official ZIP
  URL, member filename, extracted-PDF SHA-256, observed values, corrected
  values, and verification note.

The announcement page is
<https://www.nhc.gov.cn/zwgkzt/cybz/201510/3ba3419aab8a41a09f4f924788f73793.shtml>.
Its official attachment is
<https://www.nhc.gov.cn/ewebeditor/uploadfile/2015/10/20151030162720807.zip>.
The extracted `GB 1886.5-2015` PDF has SHA-256
`7f8806254dbe801d36f0b0c842db579c3a71e4caa3d7b255f6d587ada5fd668a`.

## Date-scope audit

The broad timeline cannot replace the panel's edition-date key by itself. The
official-register export supplies matching issue/effective dates for 8 of the
21 covered source editions. Cover transcription supplies dates for 12 further
editions. `GB 2760-1996` prints neither date and remains an explicit row with
blank dates and `date_status=not_printed`.

`coverage_version_dates.csv` therefore reconciles the two sources and preserves
the complete 21-edition-source scope: 19 extracted editions and two
`archived_unextracted` editions (`GB 2762-2005` and `GB 2760-1996`). A downstream
release may use this table as the source for `version_dates.csv` when it keeps
all 21 identities and permits the documented blank dates for `GB 2760-1996`.

Resolution counts in this replay are:

- `cover_and_official_register_agree`: 8;
- `source_document_only`: 12; and
- `not_printed_on_cover_and_absent_from_register`: 1.

## Replay contract

Run the builder twice with the same six input roles and distinct output
directories. Pass `official_date_corrections.csv` through
`--date-corrections-csv`. All four generated CSV files must be byte-identical.
The builder fails when
the cover-date identity set differs from the manifest's `edition_source` set,
when issue/effective dates are only partly filled, or when a cover date
conflicts with an available official-register date. It also fails when a date
correction no longer matches its declared observed values, or when any emitted
timeline event has a missing date mate or an issue date later than its effective
date.

When the broad catalogue, workbook, and categorised PDF tree are temporarily
unavailable, the verified correction can be replayed against the frozen long
and wide interfaces:

```bash
python3 Program/Clean/build_version_timeline.py \
  --frozen-input-dir Data/Interim/standard_timeline \
  --date-corrections-csv \
    Data/Interim/standard_timeline/official_date_corrections.csv \
  --output-dir Data/Interim/standard_timeline
```

This narrow replay requires the declared old dates to match exactly one long
event and, for a current formal edition, the corresponding wide row. It writes
both tables only after all corrections, event chronology, and long--wide latest
edition consistency have passed. A second replay of the same correction fails
because the old values are no longer present. The next broad-source rebuild
must still pass the same correction file; byte comparison should then reproduce
the two corrected frozen tables.
