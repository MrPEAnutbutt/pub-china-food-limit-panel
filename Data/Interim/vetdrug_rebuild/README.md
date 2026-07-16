# Veterinary-drug rebuild archive

This directory freezes the release-critical inputs and deterministic upstream
outputs for the 2002 announcement, GB 31650-2019 and GB 31650.1-2022.

- `vetdrug_2002_long.csv` and `vetdrug_2002_quarantine.csv`: deterministic
  Word-table reconstruction and its empty quarantine.
- `vetdrug_2002_row_locators.csv`: one-to-one sidecar linking every reconstructed
  row to the Word table row and within-cell block; stable rendered page numbers
  and printed row labels are unavailable.
- `source_acquisition.csv`: locked acquisition audit for the three source
  instruments, including government reference URLs, URL verification date,
  unrecorded original retrieval dates, and byte-identity comparisons.
- `vetdrug_2019_manual.csv`: required 13-row page-break seed.
- `vetdrug_2022_manual.csv`: required 122-row scan-transcription seed.
- `vetdrug_limits_by_version.csv`: 1,365-row family long table supplied to the
  release builder.
- `vetdrug_strictness_change.csv`: 657-row category-level panel supplied to
  the release builder.
- `vetdrug_2002_replay_report.json` and `vetdrug_replay_report.json`: source,
  tool, input and output identities from the latest successful replay.

The source documents are fingerprinted in the release `source_manifest.csv` and
are not copied into this intermediate archive. `source_acquisition.csv`
separates each frozen extraction copy from currently accessible government
reference files. The government reference PDFs checked for 2019 and 2022 on
2026-07-16 differ byte-for-byte from the frozen copies. A stable official URL
for the exact 2002 DOC was not verified, and the original retrieval dates of
all three frozen copies were not recorded.

Rebuild the Word-derived input first, then the family panel:

```sh
python3 Program/Clean/260716_rebuild_vetdrug_2002.py \
  --source-doc '/path/to/农业部235号公告-2002 动物性食品中兽药最高残留限量.doc'

python3 Program/Clean/260716_rebuild_vetdrug.py \
  --source-2002 '/path/to/农业部235号公告-2002 动物性食品中兽药最高残留限量.doc' \
  --source-2019 '/path/to/GB 31650-2019 食品安全国家标准 食品中兽药最大残留限量.pdf' \
  --source-2022 '/path/to/GB 31650.1-2022 食品安全国家标准 食品中兽药最大残留限量增补.pdf'
```

The Word rebuild requires LibreOffice and `python-docx`; the 2019 extraction
requires Poppler `pdftotext`. Every frozen input and core output is guarded by
schema, count, unique-key and SHA-256 checks where applicable. The family
report keeps the open provenance gap for 135 single-author manual records
explicit.

## Replay scope

The 2002 command converts and re-extracts the byte-identified Word table, then
rebuilds its 551-row CSV, empty quarantine, and row-locator sidecar. This is a
deterministic extraction replay and does not constitute independent double
entry.

The family command verifies all three source identities, reuses the 2002
rebuild plus the locked 13-row 2019 and 122-row 2022 manual seeds, and
deterministically rebuilds the 1,365-row long table and 657-row panel. It does
not recreate the 2019/2022 manual seeds from source pages and does not perform
independent retranscription. Those activities remain outside the archived
replay scope.

The optional real-source integration test discovers all six legacy documents
under a supplied source root, verifies every SHA-256 before execution, runs the
three rebuild CLIs, checks frozen output identities and reports, and compares
the rebuilt family long tables with the released `Data/Final` tables:

```sh
LEGACY_FAMILY_SOURCE_ROOT='/path/to/source/tree' \
  python3 -m unittest Program/Clean/tests/test_legacy_family_replay.py
```

Set `LEGACY_SOFFICE` when LibreOffice is not available as `soffice`. When the
source-root variable or any byte-identified source is unavailable, the
integration class reports an explicit skip; the source-free contract tests
still run.
