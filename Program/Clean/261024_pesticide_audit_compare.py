#!/usr/bin/env python3
"""Compare the independent reading of GB 2763-2019 and -2021 with the release.

Reads the completed template frozen by `261024_reviewer_handoff.py unpack`,
checks it against the unpack receipt and the audit files against
`audit_manifest.json`, and applies the pre-declared comparison in
`Data/Interim/pesticide_audit/README.md`. Writes one row per template row and
the error rate of each random stratum with a Clopper-Pearson 95% interval.

Without `--adjudication` the run lists every discrepancy in an adjudication
template. The author records a verdict for each against the scan page and
reruns into a new directory with `--adjudication`; only then are rates written.

Usage:
    python3 Program/Clean/261024_pesticide_audit_compare.py --output-dir <empty-dir>
    python3 Program/Clean/261024_pesticide_audit_compare.py \\
        --adjudication <completed-adjudication.csv> --output-dir <empty-dir>
"""

from __future__ import annotations

import argparse
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

from scipy.stats import beta


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RELEASE = PROJECT_ROOT / "Data" / "Final" / "china_food_limit_panel_v1"
DEFAULT_AUDIT = PROJECT_ROOT / "Data" / "Interim" / "pesticide_audit"
DEFAULT_RETURNED = PROJECT_ROOT / "Data" / "Interim" / "independent_review" / "returned"
COMPLETED = "pesticide_blind_read_completed.csv"

# Round 1 drew every stratum in proportion; round 2 redrew the strata with a
# category error. The strata themselves are read from the audit directory.
RANDOM_SELECTIONS = ("proportional_random", "redraw_random")
DISCREPANCIES = ("value_differs", "asterisk_differs", "value_and_asterisk_differ",
                 "not_found")
VERDICTS = ("text_layer_error", "extraction_error", "reviewer_misreading")
RELEASE_ERRORS = ("text_layer_error", "extraction_error")
# The release prints the temporary-limit mark as U+2217; NFKC leaves it alone.
ASTERISKS = ("*", "∗")
LEADING_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?")

COMPARISON_FIELDS = (
    "blind_id", "edition", "stratum", "selection", "record_id", "section_number",
    "pesticide_zh", "parent_category_zh", "food_zh", "released_limit_value",
    "released_is_temporary", "entry_status", "limit_value_raw", "reviewer_note",
    "outcome", "verdict",
)
ADJUDICATION_FIELDS = ("blind_id", "outcome", "verdict", "scan_pdf_page", "note")
RATE_FIELDS = (
    "edition", "stratum", "population_rows", "sample_rows", "compared", "illegible",
    "discrepancies", "errors", "error_rate", "ci95_low", "ci95_high",
)


class CompareError(RuntimeError):
    """Raised when an input breaks the freeze or the comparison contract."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--returned-dir", type=Path, default=DEFAULT_RETURNED)
    parser.add_argument("--adjudication", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, fields, rows) -> dict[str, object]:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return {"filename": path.name, "rows": len(rows), "sha256": sha256(path)}


def check_frozen(release: Path, audit: Path, returned: Path) -> dict[str, str]:
    """Refuse to compare unless every input matches its recorded digest."""
    manifest = json.loads((audit / "audit_manifest.json").read_text())
    receipt = json.loads((returned / "unpack_receipt.json").read_text())
    expected = {
        returned / COMPLETED: receipt["csv"][COMPLETED],
        release / "pesticide_limits_long.csv":
            manifest["inputs"]["pesticide_limits_long.csv"]["sha256"],
    }
    for name in ("key", "template", "strata"):
        meta = manifest["outputs"][name]
        expected[audit / meta["filename"]] = meta["sha256"]
    for path, digest in expected.items():
        if sha256(path) != digest:
            raise CompareError(f"digest differs from its record: {path.name}")
    return {path.name: digest for path, digest in expected.items()}


def read_reviewer_value(raw: str) -> tuple[Decimal | None, bool]:
    text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", raw))
    asterisk = any(mark in text for mark in ASTERISKS)
    for mark in ASTERISKS:
        text = text.replace(mark, "")
    number = LEADING_NUMBER.match(text)
    return (Decimal(number.group(0)) if number else None), asterisk


def outcome(row: dict[str, str], released: dict[str, str] | None) -> str:
    status = row["entry_status"]
    if status == "illegible":
        return "illegible"
    if released is None:
        return "omission_confirmed" if status == "transcribed" else "omission_not_confirmed"
    if status == "not_found":
        return "not_found"
    value, asterisk = read_reviewer_value(row["limit_value_raw"])
    value_ok = value == Decimal(released["limit_value"])
    asterisk_ok = asterisk == (released["is_temporary"] == "true")
    if value_ok and asterisk_ok:
        return "agree"
    if asterisk_ok:
        return "value_differs"
    return "asterisk_differs" if value_ok else "value_and_asterisk_differ"


def compare(release: Path, audit: Path, returned: Path) -> list[dict[str, str]]:
    key = {row["blind_id"]: row for row in read_csv(audit / "pesticide_audit_sample_key.csv")}
    template = read_csv(audit / "pesticide_blind_read_template.csv")
    completed = read_csv(returned / COMPLETED)
    if [row["blind_id"] for row in completed] != [row["blind_id"] for row in template]:
        raise CompareError("completed rows differ from the template rows")
    wanted = {row["record_id"] for row in key.values() if row["record_id"]}
    released = {
        row["record_id"]: row
        for row in read_csv(release / "pesticide_limits_long.csv")
        if row["record_id"] in wanted
    }
    if set(released) != wanted:
        raise CompareError("a sampled record is missing from the release")
    rows = []
    for row in completed:
        meta = key[row["blind_id"]]
        source = released.get(meta["record_id"])
        rows.append({
            "blind_id": row["blind_id"],
            "edition": row["edition"],
            "stratum": meta["stratum"],
            "selection": meta["selection"],
            "record_id": meta["record_id"],
            "section_number": row["section_number"],
            "pesticide_zh": row["pesticide_zh"],
            "parent_category_zh": row["parent_category_zh"],
            "food_zh": row["food_zh"],
            "released_limit_value": source["limit_value"] if source else "",
            "released_is_temporary": source["is_temporary"] if source else "",
            "entry_status": row["entry_status"],
            "limit_value_raw": row["limit_value_raw"],
            "reviewer_note": row["reviewer_note"],
            "outcome": outcome(row, source),
            "verdict": "",
            "_weight": meta["weight"],
            "_population": meta["population_rows"],
        })
    return rows


def apply_adjudication(rows: list[dict[str, str]], path: Path) -> None:
    flagged = {row["blind_id"]: row for row in rows if row["outcome"] in DISCREPANCIES}
    verdicts = read_csv(path)
    if [row["blind_id"] for row in verdicts] != list(flagged):
        raise CompareError("adjudication rows differ from the discrepancies")
    for verdict in verdicts:
        row = flagged[verdict["blind_id"]]
        if verdict["outcome"] != row["outcome"]:
            raise CompareError(f"{row['blind_id']}: outcome differs")
        if verdict["verdict"] not in VERDICTS:
            raise CompareError(f"{row['blind_id']}: invalid verdict")
        if not verdict["scan_pdf_page"].strip() or not verdict["note"].strip():
            raise CompareError(f"{row['blind_id']}: scan page and note are required")
        row["verdict"] = verdict["verdict"]


def clopper_pearson(errors: int, n: int) -> tuple[float, float]:
    low = 0.0 if errors == 0 else beta.ppf(0.025, errors, n - errors + 1)
    high = 1.0 if errors == n else beta.ppf(0.975, errors + 1, n - errors)
    return float(low), float(high)


def rate_row(edition: str, stratum: str, rows: list[dict[str, str]],
             population: int) -> dict[str, object]:
    compared = [row for row in rows if row["outcome"] != "illegible"]
    errors = sum(row["verdict"] in RELEASE_ERRORS for row in compared)
    low, high = clopper_pearson(errors, len(compared))
    return {
        "edition": edition, "stratum": stratum, "population_rows": population,
        "sample_rows": len(rows), "compared": len(compared),
        "illegible": len(rows) - len(compared),
        "discrepancies": sum(row["outcome"] in DISCREPANCIES for row in rows),
        "errors": errors, "error_rate": round(errors / len(compared), 6),
        "ci95_low": round(low, 6), "ci95_high": round(high, 6),
    }


def random_strata(audit: Path) -> list[tuple[str, str]]:
    return [(row["edition"], row["stratum"])
            for row in read_csv(audit / "pesticide_audit_strata.csv")
            if row["selection"] in RANDOM_SELECTIONS]


def rates(rows: list[dict[str, str]],
          strata: list[tuple[str, str]]) -> tuple[list[dict[str, object]], float]:
    out, pooled = [], []
    for edition, stratum in strata:
        subset = [row for row in rows
                  if row["edition"] == edition and row["stratum"] == stratum]
        pooled += subset
        out.append(rate_row(edition, stratum, subset, int(subset[0]["_population"])))
    population = sum(item["population_rows"] for item in out)
    out.append(rate_row("2019+2021", "random", pooled, population))
    compared = [row for row in pooled if row["outcome"] != "illegible"]
    weighted = sum(float(row["_weight"]) * (row["verdict"] in RELEASE_ERRORS)
                   for row in compared) / sum(float(row["_weight"]) for row in compared)
    return out, round(weighted, 6)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = args.output_dir
    if output.exists() and any(output.iterdir()):
        print(f"output directory must be empty: {output}", file=sys.stderr)
        return 2
    try:
        inputs = check_frozen(args.release_dir, args.audit_dir, args.returned_dir)
        rows = compare(args.release_dir, args.audit_dir, args.returned_dir)
        if args.adjudication:
            apply_adjudication(rows, args.adjudication)
            inputs[args.adjudication.name] = sha256(args.adjudication)
    except CompareError as error:
        print(f"pesticide audit compare error: {error}", file=sys.stderr)
        return 2

    output.mkdir(parents=True, exist_ok=True)
    outputs = {"comparison": write_csv(
        output / "pesticide_audit_comparison.csv", COMPARISON_FIELDS,
        [{field: row[field] for field in COMPARISON_FIELDS} for row in rows])}
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["outcome"]] = counts.get(row["outcome"], 0) + 1
    summary: dict[str, object] = {"outcomes": counts}
    if args.adjudication:
        table, weighted = rates(rows, random_strata(args.audit_dir))
        outputs["rates"] = write_csv(output / "pesticide_audit_rates.csv",
                                     RATE_FIELDS, table)
        summary["weighted_random_error_rate"] = weighted
        summary["verdicts"] = {
            verdict: sum(row["verdict"] == verdict for row in rows)
            for verdict in VERDICTS
        }
    else:
        outputs["adjudication_template"] = write_csv(
            output / "pesticide_audit_adjudication_template.csv", ADJUDICATION_FIELDS,
            [{"blind_id": row["blind_id"], "outcome": row["outcome"], "verdict": "",
              "scan_pdf_page": "", "note": ""}
             for row in rows if row["outcome"] in DISCREPANCIES])
    manifest = {"inputs": inputs, "outputs": outputs, "summary": summary}
    (output / "compare_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
