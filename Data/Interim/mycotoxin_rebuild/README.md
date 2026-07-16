# GB 2761 rebuild archive

This directory freezes the release-critical inputs and deterministic upstream
outputs for the GB 2761 family.

- `myco2005_manual.csv`: required nine-row transcription seed.
- `source_acquisition.csv`: locked acquisition audit for all three source
  editions, including government reference URLs, URL verification date,
  unrecorded original retrieval dates, and byte-identity comparisons.
- `mycotoxin_limits_by_version.csv`: 61-row family long table supplied to the
  release builder.
- `mycotoxin_strictness_change.csv`: 40-row category-level panel supplied to
  the release builder.
- `mycotoxin_replay_report.json`: source, tool, input and output identities
  from the latest successful replay.

The source documents are referenced by filename, size and SHA-256 in the
release `source_manifest.csv`; they are not copied into this intermediate
archive. `source_acquisition.csv` separates the frozen extraction-copy identity
from currently accessible government reference files. The 2011 attachment and
the 2017 ZIP entry available on 2026-07-16 differ byte-for-byte from the frozen
copies. The 2005 government page exposes four page images and no stable single
PDF. Original retrieval dates for the frozen copies were not recorded.

Run the rebuild with explicit source paths:

```sh
python3 Program/Clean/260716_rebuild_mycotoxin.py \
  --source-2005 '/path/to/GB 2761-2005 食品中真菌毒素限量.pdf' \
  --source-2011 '/path/to/GB 2761-2011 食品安全国家标准 食品中真菌毒素限量.pdf' \
  --source-2017 '/path/to/GB 2761-2017 食品安全国家标准 食品中真菌毒素限量.pdf'
```

The script stops when a source identity, seed schema, seed row count, seed
business key, seed digest, output row count or output digest differs. The
report keeps the open provenance gap for the nine single-author transcription
records explicit.

## Replay scope

The replay verifies the source-file identities, reuses the locked nine-row
2005 seed, reparses the 2011 and 2017 text layers, and deterministically rebuilds
the 61-row long table and 40-row panel. It does not recreate the 2005 seed from
page images and does not provide an independent second transcription. Those
two activities remain outside the archived replay scope.

The optional real-source integration test discovers all six legacy documents
under a supplied source root, verifies every SHA-256 before execution, runs the
three rebuild CLIs, checks frozen output identities and reports, and compares
the rebuilt family long tables with the released `Data/Final` tables:

```sh
LEGACY_FAMILY_SOURCE_ROOT='/path/to/source/tree' \
  python3 -m unittest Program/Clean/tests/test_legacy_family_replay.py
```

When the environment variable or any byte-identified source is unavailable,
the integration class reports an explicit skip; the source-free contract tests
still run.
