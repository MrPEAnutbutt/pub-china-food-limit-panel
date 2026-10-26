# Independent reading of GB 2763-2019 and GB 2763-2021, round 2

- Protocol version: `1.0`, redraw step
- Seed: `GB2763-audit-20261024`
- Round 1: `pesticide_audit`
- Status: awaiting the independent reviewer

## Why a second round

In round 1, 7 of the 288 random rows filed a food under a long food label such
as 豆类蔬菜(食荚豌豆、豌豆(鲜)、菜豆和菜用大豆除外) instead of its category; the
limit values of those rows were correct. The protocol traces an error type found
twice or more, corrects it across all rows and draws the affected strata again.
The extraction rule was corrected in `260716_extract_pesticide_textlayer_scans.py`
(`PARENT_HEADINGS`), which changed the category of 1,019 of the 38,024 pesticide
rows and nothing else, and the release was rebuilt before this draw.

## Draw

The strata with a category error in round 1 are drawn again with the same seed
and the same sample sizes. Rows of the rebuilt release are ranked by SHA-256 of
`GB2763-audit-20261024:<record_id>`; the rows read in round 1 are located by edition, section,
page, position, food and printed value and skipped; the lowest-ranked remaining
rows are taken. The 2021 `consistent` stratum had no error and is not drawn
again. 258 template rows in all.

| Edition | Stratum | Population | Sample |
|---|---|---:|---:|
| 2019 | consistent | 1,929 | 32 |
| 2019 | text_only | 5,175 | 87 |
| 2021 | text_only | 8,315 | 139 |

## Reading and comparison

The template, the blindness boundary, the reviewer instructions and the
pre-declared comparison are those of round 1 (`pesticide_audit/README.md`).
Error rates are reported per stratum with Clopper-Pearson 95% intervals and
pooled over the round-2 rows.
