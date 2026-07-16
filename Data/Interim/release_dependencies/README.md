# Portable release dependencies

This directory freezes the five CSV inputs that the release builder previously
read from an external processing tree. It is an interim evidence layer. The
release builder may read these files, while downstream analysis must continue
to read only `Data/Final/`.

## Main release-builder inputs

| File | Data rows | SHA-256 | Evidential status |
|---|---:|---|---|
| `food_taxonomy.csv` | 798 | `f5730ffcc4bfe4f54a427445a2a392fbdb473de609a6aa3b23584f6ced415f7d` | Parser-derived GB 2762 Appendix A parent-child edges; source-PDF replay is byte-identical. |
| `category_alias.csv` | 8 | `59d4838dcf19b433308d2d850698bbc2a56599a0185a2e9f3279eeda347ffb66` | Human-authored adjudication seed: 3 rows are marked `已确认`; 5 remain `待核`. |
| `pollutant_old_path.csv` | 677 | `e05158cd82b8f5dc7cd0cb7c5a770e88c18fefa5e3d9d9593a3f142fbaa83c8f` | Historical text-parser recall backstop; 676 rows are `high` and one is `review_cat`. |
| `member_crosswalk_mycotoxin.csv` | 55 | `04fcaf11730263facb7e6be652fc51d7a2f121ce8a1c8f4f9b87ddee61967626` | Deterministically regenerated from the project-local 61-row mycotoxin long table and frozen taxonomy. |
| `member_crosswalk_vetdrug.csv` | 1,132 | `1ad4054e0fd2c51fcb05b27a30fd289cc37df00967350e369984195bdd8f3b35` | Deterministically regenerated from the project-local 1,365-row veterinary-drug long table. |

The header is excluded from each data-row count. All tracked CSV files use
UTF-8 with a byte-order mark and LF line endings.

## Supporting replay input

`pollutant_doublecol_long.csv` has 241 data rows and SHA-256
`e0955c56f5d3a048a1fb38b49c6cb7a750b4cd475fe9d68012a463b540fd1345`.
It is the archived coordinate-parser sidecar required to reproduce
`pollutant_old_path.csv` byte for byte. The release builder does not need to
read this sidecar directly.

The archived sidecar predates four category-text repairs in the surviving
coordinate-parser source. Re-running that later source against the same four
PDF bytes produces the same 241 keys and values, with corrected category text
in four rows, and a different file digest. The current pollutant rebuild has an
independent coordinate parser that quarantines the malformed historical hosts
and restores the corrected source rows. The frozen sidecar remains here solely
to make the historical recall path auditable and exactly replayable.

## Runtime requirements

The bundle verifier and member-crosswalk replay use the Python standard
library. Source-PDF replay additionally requires Poppler commands
`pdftotext`, `pdftoppm`, and `pdfinfo`; the taxonomy parser also requires the
Python packages NumPy and Pillow. The scripts verify source-PDF SHA-256
identities before parsing.

## Replay commands

Verify every schema, row count, unique key, manual-state count, and digest:

```bash
python3 Program/Clean/260716_replay_release_inputs.py verify
```

Rebuild both member crosswalks into a temporary directory and require their
digests to match the frozen snapshots:

```bash
python3 Program/Clean/260716_replay_release_inputs.py rebuild-members \
  --output-dir /tmp/release-dependencies-members
```

Rebuild the historical pollutant recall table from the four verified source
PDFs plus the archived coordinate sidecar:

```bash
python3 Program/Clean/260716_replay_release_inputs.py \
  rebuild-pollutant-legacy \
  --source-dir /path/to/gb2762-pdfs \
  --output /tmp/pollutant_old_path.csv
```

Rebuild the Appendix A taxonomy directly from the four verified source PDFs:

```bash
python3 Program/Clean/260716_rebuild_food_taxonomy.py \
  --source-dir /path/to/gb2762-pdfs \
  --output /tmp/food_taxonomy.csv
```

The PDF directory must contain exactly one full standard for each of 2012,
2017, 2022, and 2025. Files whose names contain `修改单` are excluded from
edition extraction. Both source-dependent commands fail when any PDF digest
differs from the locked source identity.

## Provenance and manual boundaries

- The snapshots were copied into this project on 2026-07-16 from the archived
  `260706_限量版本面板` processing bundle. The original creation timestamps
  and original retrieval dates were not recorded, so this directory makes no
  claim about them.
- The upstream script identities were:
  `build_food_taxonomy.py` =
  `dede1bdf049eb02d2fb4d9e902e2ac716e913fed7e0f4f2ace373e0072fb3052`,
  `build_member_panel_三族.py` =
  `a4177fabde21d7025d1983dfaff641d9ead429a53e26366ccdbe083c7c923fa6`,
  `build_pollutant_version_panel.py` =
  `3b983e0f53c374679caca5d5e3887a90c4f6384cb7ee3773e669fce1f3675bc5`,
  and `build_pollutant_doublecol.py` =
  `3d929a7783f99a22e2284df34cad2ec92225374b8b8a87a336eacf876dd1bdc7`.
- `category_alias.csv` is the only human-authored mapping table in this bundle.
  Five of its eight rows retain the literal `待核` status. The formal pollutant
  rebuild applies only `已确认` rows, excludes and counts all five `待核` rows,
  and fails on any unknown status, blank key, or duplicate source label.
- `pollutant_old_path.csv` is a historical recall input. Its one `review_cat`
  row and the malformed category hosts inherited from the archived sidecar are
  handled by the newer pollutant rebuild's quarantine and coordinate-source
  replacement gates.
- Both member crosswalk snapshots are fully reproducible from project-local
  upstream long tables. Their exact upstream digests are locked by the replay
  script.

The machine-readable `replay_report.json` repeats the locked identities and
manual boundaries without private absolute paths.
