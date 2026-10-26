# Blind re-entry protocol for 144 manually transcribed records

- Packet ID: `BR144-v1.2-9795b815a5f551e1`
- Protocol version: `1.2`
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
   set `confirmation` to `confirmed`.
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
python3 Program/Clean/260716_blind_manual_reentry.py reconcile \
  --entry-dir <completed-entry-directory> \
  --attestation <completed-entry-directory>/reviewer_attestation.json \
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
