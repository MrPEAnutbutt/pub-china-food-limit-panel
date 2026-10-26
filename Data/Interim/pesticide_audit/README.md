# Independent reading of GB 2763-2019 and GB 2763-2021

- Protocol version: `1.0`
- Seed: `GB2763-audit-20261024`
- Status: awaiting a real independent reviewer

## Population and strata

The released rows for the two editions (7,108 and 10,092, together 17,200) come
from government-hosted text-layer copies (SRC0024, SRC0025). Each row is linked
to its group in `pesticide_ocr_crosscheck.csv`, which compares the text layer
with an OCR reading of the issuing authority's scans (SRC0009, SRC0010). The
linkage is one row per text-layer group; `pesticide_row_crosscheck_status.csv`
lists the status of all 17,200 rows.

288 rows are drawn with probability proportional to stratum size
from the `consistent` and `text_only` strata of each edition (largest-remainder
rounding). Within a stratum, rows are ranked by SHA-256 of
`GB2763-audit-20261024:<record_id>` and the lowest ranks are taken, so the draw does not depend
on software versions. All 9 `conflict` rows are included, and the 3 `ocr_only`
groups, which have no released row, are included to check for omissions.
300 template rows in all.

| Edition | Stratum | Selection | Population | Sample |
|---|---|---|---:|---:|
| 2019 | consistent | proportional_random | 1,929 | 32 |
| 2019 | text_only | proportional_random | 5,175 | 87 |
| 2021 | consistent | proportional_random | 1,772 | 30 |
| 2021 | text_only | proportional_random | 8,315 | 139 |
| 2019 | conflict | census | 4 | 4 |
| 2021 | conflict | census | 5 | 5 |
| 2019 | ocr_only | census | 1 | 1 |
| 2021 | ocr_only | census | 2 | 2 |

## Blindness boundary

The reviewer receives `pesticide_blind_read_template.csv` (or the workbook built
from it by `261024_reviewer_handoff.py`) and the two scans, whose SHA-256 digests
the custodian checks against `source_manifest.csv` before handoff. The template
gives the edition, section, pesticide, food category, food and a reference scan
page; it gives no value, comparison status or record ID. Rows are in document
order, so the strata cannot be read from the order.
`pesticide_audit_sample_key.csv` links blind IDs to record IDs and strata and is
held by the custodian until the completed template is frozen.

## Reviewer instructions

For each row, find the section and the food in the scan and record:

- `entry_status`: `transcribed`, `illegible` or `not_found` (the food is not
  printed in that section under that category).
- `limit_value_raw`: the printed limit exactly as shown, including any asterisk
  and any printed qualifier. Leave it blank for `illegible` and `not_found`.
- `reviewer_note`: required for `illegible` and `not_found`; also used when the
  printed food or category wording differs from the template.

## Pre-declared comparison

Comparison starts only after the custodian has recorded the SHA-256 digest of the
returned file. Both strings are normalised with Unicode NFKC and whitespace
removal. The printed asterisk sets the temporary-limit flag and is compared with
`is_temporary`; the remaining number is compared with `limit_value` by Decimal
equality. A sampled released row is in error when the value or the asterisk
differs, or when it is `not_found`. For an `ocr_only` group, `transcribed`
confirms a row missing from the text layer. `illegible` rows leave the denominator, are
reported separately and are replaced by the next-ranked row of the same stratum.

Each error is adjudicated by the author against the scan page and classified as
a text-layer error, an extraction error or a reviewer misreading. Error rates
are reported per stratum with Clopper-Pearson 95% intervals. The proportional
allocation makes the 288-row random sample self-weighting up to
rounding, so the overall rate is the pooled rate over those rows with its
Clopper-Pearson interval; `weight` in the key file supports the weighted check.
The 9 `conflict` rows and 3 `ocr_only` groups are reported as targeted findings,
not as part of the random-sample rate. If one error type occurs twice or more,
the extraction rule is traced, corrected across all rows and the affected
stratum is drawn again.
