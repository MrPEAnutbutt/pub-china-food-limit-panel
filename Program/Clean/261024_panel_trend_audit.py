#!/usr/bin/env python3
"""Audit every panel cell judged stable, tightened, relaxed or fluctuation.

Links each panel row of the eight release panels back to the long-table rows
it depends on, then flags the dependencies listed under A4 of the round-1
revision plan (reviewer comment R1.3): qualifiers, differing scope text,
manual entries awaiting the blind re-entry, quarantined rules for the same
key, the two GB 2763 editions whose visible rule count differs from the
declared count, rules the panel builder dropped, direction labels the values
do not reproduce, gaps between compared editions, and member cells whose host
rule excludes the member, covers only part of it, or follows a rewritten
exclusion list (A8). Every flag is counted
per panel, zeros included. The release is only read.

Usage:
    python3 Program/Clean/261024_panel_trend_audit.py --output-dir <empty-dir>
    python3 Program/Clean/261024_panel_trend_audit.py \\
        --release-dir <release-dir> --output-dir <empty-dir>
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import unicodedata

CLEAN_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CLEAN_DIR.parents[1]
if str(CLEAN_DIR) not in sys.path:
    sys.path.insert(0, str(CLEAN_DIR))

import release_panel_utils as panel_utils  # noqa: E402


def load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, CLEAN_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


POLLUTANT = load_script("rebuild_pollutant", "260715_rebuild_pollutant.py")
MYCOTOXIN = load_script("rebuild_mycotoxin", "260716_rebuild_mycotoxin.py")
REPLAY = load_script("replay_release_inputs", "260716_replay_release_inputs.py")

DEFAULT_RELEASE = PROJECT_ROOT / "Data" / "Final" / "china_food_limit_panel_v1"
DEFAULT_DEPENDENCY = PROJECT_ROOT / "Data" / "Interim" / "release_dependencies"

PANELS = {
    "pesticide_panel": ("pesticide_limits_long.csv", panel_utils.PESTICIDE_YEARS),
    "additive_panel": ("additive_limits_long.csv", panel_utils.ADDITIVE_YEARS),
    "pollutant_category_panel": ("pollutant_limits_long.csv", POLLUTANT.YEARS),
    "pollutant_member_panel": ("pollutant_limits_long.csv", POLLUTANT.YEARS),
    "mycotoxin_panel": ("mycotoxin_limits_long.csv", MYCOTOXIN.YEARS),
    "mycotoxin_member_panel": ("mycotoxin_limits_long.csv", MYCOTOXIN.YEARS),
    "vetdrug_panel": ("vetdrug_limits_long.csv", panel_utils.VETDRUG_SUMMARY_YEARS),
    "vetdrug_member_panel": ("vetdrug_limits_long.csv", REPLAY.YEARS_VETDRUG),
}
JUDGED = ("stable", "stable_gmp", "tightened", "relaxed", "fluctuation")
ALL = tuple(PANELS)
QUALIFIED = ("pesticide_panel", "additive_panel", "pollutant_category_panel",
             "pollutant_member_panel")

# flag -> (kind, panels where it can occur)
FLAGS = {
    "link_failure": ("rule_violation", ALL),
    "masked_multiple_rules": ("rule_violation", (
        "mycotoxin_panel", "mycotoxin_member_panel", "pollutant_member_panel",
        "vetdrug_member_panel")),
    "label_not_reproduced_by_monotonic_rule": ("rule_violation", ALL),
    "scope_text_differs": ("rule_violation", (
        "pesticide_panel", "additive_panel", "pollutant_category_panel",
        "mycotoxin_panel", "vetdrug_panel")),
    "qualifier_differs": ("rule_violation", QUALIFIED),
    "residual_member_scope_changes": ("rule_violation", (
        "pollutant_member_panel", "mycotoxin_member_panel")),
    "host_rule_does_not_cover_member": ("rule_violation", ("pollutant_member_panel",)),
    "manual_entry_mycotoxin_2005": ("needs_decision", ("mycotoxin_member_panel",)),
    "manual_entry_vetdrug_2019_cross_page": ("needs_decision", (
        "vetdrug_panel", "vetdrug_member_panel")),
    "manual_entry_vetdrug_2022": ("needs_decision", ("vetdrug_member_panel",)),
    "quarantined_rule_same_key": ("needs_decision", (
        "additive_panel", "pollutant_category_panel", "pollutant_member_panel")),
    "pesticide_edition_2016": ("needs_decision", ("pesticide_panel",)),
    "pesticide_edition_2019": ("needs_decision", ("pesticide_panel",)),
    "edition_gap": ("needs_decision", ALL),
    "qualifier_present": ("informational", QUALIFIED),
    "host_category_changes": ("informational", (
        "pollutant_member_panel", "mycotoxin_member_panel")),
    "animal_label_changes": ("informational", ("vetdrug_member_panel",)),
    "value_shown_but_not_compared": ("informational", ("mycotoxin_panel",)),
    "conflict_row": ("informational", ("pesticide_panel", "additive_panel")),
    "pesticide_review_exception": ("informational", ("pesticide_panel",)),
}

FLAG_FIELDS = ("panel", "panel_record_id", "trend", "flag", "kind", "years",
               "source_record_ids", "detail")
SUMMARY_FIELDS = ("panel", "flag", "kind", "applicable", "judged_cells",
                  "flagged_cells", *JUDGED)
LINK_FIELDS = ("panel", "panel_record_id", "version_year", "panel_value",
               "source_record_ids")
VETDRUG_MG_PER_UG = 0.001


class AuditError(RuntimeError):
    """Raised when an input cannot be audited as released."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--dependency-dir", type=Path, default=DEFAULT_DEPENDENCY)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields, rows) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def decimal(value: str) -> Decimal | None:
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def same_number(left: str, right: str) -> bool:
    a, b = decimal(left), decimal(right)
    return a is not None and a == b


def close(left, right) -> bool:
    try:
        return math.isclose(float(left), float(right), rel_tol=1e-9)
    except (TypeError, ValueError):
        return False


def norm(text: str) -> str:
    return panel_utils._normalise_scope_text(text or "")


def monotonic_label(numbers: list) -> str:
    if len(set(numbers)) == 1:
        return "stable"
    pairs = list(zip(numbers, numbers[1:]))
    if all(a >= b for a, b in pairs) and numbers[-1] < numbers[0]:
        return "tightened"
    if all(a <= b for a, b in pairs) and numbers[-1] > numbers[0]:
        return "relaxed"
    return "fluctuation"


def new_cell(panel: str, row: dict[str, str]) -> dict:
    return {
        "panel": panel, "record_id": row["record_id"], "trend": row["trend"],
        "values": {}, "links": {}, "compared": [], "numbers": {},
        "scope": None, "qualifier": None, "host": None, "animals": None,
        "residual": None,
        "flags": [],
    }


def link_failure(cell: dict, year: str, reason: str) -> None:
    cell["flags"].append(("link_failure", f"{year}: {reason}"))


# ---------- adapters: one per panel ----------

def pesticide_or_additive_cells(panel, rows, long_by_id):
    years = PANELS[panel][1]
    value_column = "limit_value" if panel == "pesticide_panel" else "max_use"
    for row in rows:
        cell = new_cell(panel, row)
        for year in years:
            ids = json.loads(row[f"source_record_ids_{year}"] or "[]")
            if not ids:
                continue
            missing = [i for i in ids if i not in long_by_id]
            linked = [long_by_id[i] for i in ids if i in long_by_id]
            if missing:
                link_failure(cell, year, f"record_id not in long table: {missing}")
            if any(r["version_year"] != year for r in linked):
                link_failure(cell, year, "linked row from another edition")
            cell["links"][year] = linked
            cell["values"][year] = row[f"v{year}"]
            if len(linked) == 1 and linked[0][value_column] != row[f"v{year}"]:
                link_failure(cell, year, "panel value differs from long row")
        cell["compared"] = list(cell["links"])
        if all(len(cell["links"][y]) == 1 for y in cell["compared"]):
            rules = {y: cell["links"][y][0] for y in cell["compared"]}
            if panel == "pesticide_panel":
                cell["numbers"] = {y: decimal(r["limit_value"]) for y, r in rules.items()}
                cell["scope"] = {y: panel_utils._pesticide_v2_scope_signature(r)
                                 for y, r in rules.items()}
                cell["qualifier"] = {y: (r["limit_qualifier"], r["is_temporary"])
                                     for y, r in rules.items()}
            else:
                cell["numbers"] = {y: decimal(r["max_use"]) for y, r in rules.items()}
                cell["scope"] = {y: (norm(r["food_zh"]), norm(r["note"]))
                                 for y, r in rules.items()}
                cell["qualifier"] = {y: norm(r["note"]) for y, r in rules.items()}
        yield cell


def pollutant_scope(raw: str, aliases: dict[str, str]):
    """Category head and exclusion set, equal across a confirmed rename."""

    base, exclusions = POLLUTANT.split_category(raw, aliases)
    if not base:
        return (norm(raw),)
    weak = {POLLUTANT.weak_category_key(k): POLLUTANT.weak_category_key(v)
            for k, v in aliases.items()}
    key = POLLUTANT.weak_category_key(base)
    if key in weak or key in weak.values():
        head = weak.get(key, key)
    else:
        head = re.sub(r"[、,，]", "", norm(base))
    return head, tuple(sorted({norm(e) for e in exclusions}))


def pollutant_category_cells(rows, long_rows, aliases):
    index = defaultdict(list)
    for r in long_rows:
        index[(r["version_year"], r["analyte_zh"], r["food_category_zh"],
               r["limit_basis"])].append(r)
    for row in rows:
        cell = new_cell("pollutant_category_panel", row)
        for year in POLLUTANT.YEARS:
            if row[f"cell_status_{year}"] == "missing":
                continue
            linked = index.get((year, row["analyte_zh"], row[f"source_category_{year}"],
                                row[f"basis_{year}"]), [])
            cell["links"][year] = linked
            cell["values"][year] = row[f"v{year}"]
            if row[f"cell_status_{year}"] != "single":
                continue
            if len(linked) != 1:
                link_failure(cell, year, f"{len(linked)} long rows for source category")
            elif not (same_number(linked[0]["limit_value"], row[f"v{year}"])
                      and linked[0]["unit"] == row[f"unit_{year}"]):
                link_failure(cell, year, "panel value or unit differs from long row")
        cell["compared"] = list(cell["links"])
        cell["numbers"] = {y: POLLUTANT.comparable_value(row[f"v{y}"], row[f"unit_{y}"])
                           for y in cell["compared"]}
        cell["scope"] = {y: pollutant_scope(row[f"source_category_{y}"], aliases)
                         for y in cell["compared"]}
        cell["qualifier"] = {y: row[f"basis_{y}"] for y in cell["compared"]}
        yield cell


def host_coverage(member, host, year, printed_lists, fold, contained_in):
    """Why the host rule does not cover the member, or "" when it does."""

    def within(name):
        chain = {name}
        while name in contained_in and contained_in[name] not in chain:
            name = contained_in[name]
            chain.add(name)
        return chain

    member = fold(member)
    base, exclusions = POLLUTANT.split_category(host, {})
    removed = set()
    for item in exclusions:
        for part in {item, *POLLUTANT.split_top_level(item, "和")}:
            part = fold(part)
            if part:
                removed.add(part)
                if part.endswith("及其制品"):
                    removed |= {part[:-4], part[:-4] + "制品"}
                elif "及其" in part:
                    removed.add(part[: part.index("及其")])
    if within(member) & removed:
        return "excluded"
    own = {fold(base), *(fold(p) for p in POLLUTANT.split_top_level(base))}
    variants = {member, member[:-4]} if member.endswith("及其制品") else {member, member + "及其制品"}
    if member.endswith("制品") and not member.endswith("及其制品"):
        variants.add(member[:-2] + "及其制品")
    if own & variants or any(name.startswith(member + "及其") for name in own):
        return ""
    if any(member in within(name) and name != member for name in removed):
        return "spans two rules"
    printed = {fold(item) for item in exclusions}
    lists = [other for other_year, year_lists in printed_lists.items() if other_year != year
             for other in year_lists if member in other]
    if printed and lists and not any(printed <= other for other in lists):
        return "rewritten exclusion list"
    return ""


def pollutant_member_cells(rows, long_rows, aliases, contained_in):
    folded = {unicodedata.normalize("NFKC", k): unicodedata.normalize("NFKC", v)
              for k, v in aliases.items()}

    def fold(text):
        return POLLUTANT.match_key(text, folded)

    index = defaultdict(list)
    direct = defaultdict(list)
    printed_lists = defaultdict(lambda: defaultdict(list))
    for r in long_rows:
        index[(r["version_year"], r["analyte_zh"], r["food_category_zh"])].append(r)
        if r["confidence"] != "high":
            continue
        _, exclusions = POLLUTANT.split_category(r["food_category_zh"], {})
        if exclusions:
            printed_lists[r["analyte_zh"]][r["version_year"]].append(
                {fold(item) for item in exclusions})
        # Same split as build_member_panel: a member's own rules, before any
        # fall-back to a parent category.
        base, _ = POLLUTANT.split_category(r["food_category_zh"], aliases)
        if not base:
            continue
        parts = {base}
        top = POLLUTANT.split_top_level(base)
        if len(top) > 1 and len(base) > 4:
            parts |= {p for p in (POLLUTANT.clean_member(t, aliases) for t in top)
                      if p and 1 < len(p) <= 8}
        for part in parts:
            direct[(r["version_year"], r["analyte_zh"], part)].append(r)

    def variants(member):
        if member.endswith("及其制品"):
            return member, member[:-4]
        return member, member + "及其制品"

    for row in rows:
        cell = new_cell("pollutant_member_panel", row)
        member = row["food_member_zh"]
        for year in POLLUTANT.YEARS:
            if not row[f"v{year}"]:
                continue
            linked = [
                r for r in index.get((year, row["analyte_zh"], row[f"host_category_{year}"]), [])
                if same_number(r["limit_value"], row[f"v{year}"])
                and r["unit"] == row[f"unit_{year}"] and r["limit_basis"] == row[f"basis_{year}"]
            ]
            cell["links"][year] = linked
            cell["values"][year] = row[f"v{year}"]
            if not linked:
                link_failure(cell, year, "no long row matches host category and value")
            reason = host_coverage(member, row[f"host_category_{year}"], year,
                                   printed_lists[row["analyte_zh"]], fold, contained_in)
            if reason:
                cell["flags"].append((
                    "host_rule_does_not_cover_member",
                    f"{year}: {reason}; host {row[f'host_category_{year}']}"))
            for variant in variants(member):
                own = direct.get((year, row["analyte_zh"], variant), [])
                distinct = {(r["limit_value"], r["unit"], r["limit_basis"]) for r in own}
                if len(distinct) > 1:
                    cell["flags"].append((
                        "masked_multiple_rules",
                        f"{year}: {len(own)} own rules for {variant} with "
                        f"{len(distinct)} values; host {row[f'host_category_{year}']} used"))
                    break
        cell["compared"] = list(cell["links"])
        cell["numbers"] = {y: POLLUTANT.comparable_value(row[f"v{y}"], row[f"unit_{y}"])
                           for y in cell["compared"]}
        cell["qualifier"] = {y: row[f"basis_{y}"] for y in cell["compared"]}
        cell["host"] = {y: norm(row[f"host_category_{y}"]) for y in cell["compared"]}
        # Years in which the member is the host's own head: the member then
        # stands for the head minus its exclusions.
        cell["residual"] = {}
        for y in cell["compared"]:
            base, exclusions = POLLUTANT.split_category(row[f"host_category_{y}"], aliases)
            if base in variants(member) or base.startswith(member + "及其"):
                cell["residual"][y] = tuple(sorted({norm(e) for e in exclusions}))
        yield cell


def mycotoxin_cells(rows, long_rows):
    index = defaultdict(list)
    for r in long_rows:
        key = MYCOTOXIN.canonical_food(r["food_category_zh"])
        if key:
            index[(r["version_year"], r["toxin_zh"], key)].append(r)
    for row in rows:
        cell = new_cell("mycotoxin_panel", row)
        for year in MYCOTOXIN.YEARS:
            if not row[f"v{year}"]:
                continue
            linked = index.get((year, row["toxin_zh"], row["food_zh"]), [])
            cell["links"][year] = linked
            cell["values"][year] = row[f"v{year}"]
            # The builder keeps the first row of an edition for a canonical food.
            if not linked or linked[0]["limit_value"] != row[f"v{year}"]:
                link_failure(cell, year, "first long row does not carry the panel value")
            if len(linked) > 1:
                cell["flags"].append((
                    "masked_multiple_rules",
                    f"{year}: {len(linked)} rules share the canonical food; kept "
                    + " | ".join(f"{r['food_category_zh']}={r['limit_value']}" for r in linked)))
        # Trend uses the 2011 and 2017 text-layer editions only.
        cell["compared"] = [y for y in cell["links"]
                            if y != "2005" and decimal(row[f"v{y}"]) is not None]
        cell["numbers"] = {y: decimal(row[f"v{y}"]) for y in cell["compared"]}
        cell["scope"] = {y: norm(cell["links"][y][0]["food_category_zh"])
                         for y in cell["compared"] if cell["links"][y]}
        if "2005" in cell["links"]:
            numbers = [decimal(row[f"v{y}"]) for y in MYCOTOXIN.YEARS if y in cell["links"]]
            with_2005 = (monotonic_label(numbers)
                         if None not in numbers and len(numbers) > 1 else "not numeric")
            cell["flags"].append((
                "value_shown_but_not_compared",
                f"2005={row['v2005']} (manual) shown; label with 2005 would be {with_2005}"))
        yield cell


def mycotoxin_member_cells(rows, long_rows, taxonomy_rows):
    taxonomy = {REPLAY.clean(t["child"]): REPLAY.clean(t["parent"]) for t in taxonomy_rows}
    rename = {"植物油": "植物油脂"}
    index = defaultdict(list)
    parts_by_row = {}
    part_rows = defaultdict(list)
    for r in long_rows:
        index[(r["version_year"], r["toxin_zh"], r["food_category_zh"])].append(r)
        base = REPLAY.clean(REPLAY.BRACKET.sub("", r["food_category_zh"]))
        parts = {rename.get(p, p) for p in (REPLAY.clean(p) for p in base.split("、")) if p}
        parts_by_row[r["record_id"]] = parts
        for part in parts:
            part_rows[(r["version_year"], r["toxin_zh"], part)].append(r)
    for row in rows:
        cell = new_cell("mycotoxin_member_panel", row)
        member = row["food_member_zh"]
        for year in MYCOTOXIN.YEARS:
            if not row[f"v{year}"]:
                continue
            linked = [r for r in index.get((year, row["toxin_zh"], row[f"host_category_{year}"]), [])
                      if close(float(r["limit_value"]) * REPLAY.UNIT_FACTOR[r["unit"]],
                               row[f"v{year}"])]
            cell["links"][year] = linked
            cell["values"][year] = row[f"v{year}"]
            if len(linked) != 1:
                link_failure(cell, year, f"{len(linked)} long rows match host and value")
                continue
            # The node that supplied the value: the member itself or the
            # nearest taxonomy ancestor named in the host row.
            node, seen = member, set()
            while node and node not in parts_by_row[linked[0]["record_id"]] and node not in seen:
                seen.add(node)
                node = taxonomy.get(node)
            competing = part_rows.get((year, row["toxin_zh"], node), [])
            if len(competing) > 1:
                cell["flags"].append((
                    "masked_multiple_rules",
                    f"{year}: {len(competing)} rules name {node}; last kept "
                    + " | ".join(f"{r['food_category_zh']}={r['limit_value']}" for r in competing)))
        cell["compared"] = list(cell["links"])
        cell["numbers"] = {y: float(row[f"v{y}"]) for y in cell["compared"]}
        cell["host"] = {y: norm(row[f"host_category_{y}"]) for y in cell["compared"]}
        cell["residual"] = {}
        for y in cell["compared"]:
            # A bracket qualifies only the listed item it follows.
            for item in REPLAY.split_listed(row[f"host_category_{y}"]):
                name = REPLAY.clean(REPLAY.BRACKET.sub("", item))
                if rename.get(name, name) != member:
                    continue
                excluded = []
                for match in REPLAY.BRACKET.finditer(item):
                    if "除" in match.group(1):
                        inner = re.sub(r"除外?|除", "", match.group(1))
                        excluded.extend(REPLAY.clean(p) for p in re.split(r"[、,，]", inner)
                                        if REPLAY.clean(p))
                cell["residual"][y] = tuple(sorted({norm(e) for e in excluded}))
        yield cell


def covered_animals(rows) -> tuple[str, ...]:
    animals = set()
    for r in rows:
        animals |= REPLAY.animal_members(r["animal"])
        if "其他动物" in r["animal"].split("/"):
            animals.add("其他动物")
    return tuple(sorted(animals))


def vetdrug_cells(rows, long_rows):
    index = defaultdict(list)
    for r in long_rows:
        if r["version_year"] in panel_utils.VETDRUG_SUMMARY_YEARS:
            identity = panel_utils._normalise_vetdrug_english(r["drug_en"])
            index[(r["version_year"], identity, r["tissue_zh"])].append(r)
    for row in rows:
        cell = new_cell("vetdrug_panel", row)
        for year in panel_utils.VETDRUG_SUMMARY_YEARS:
            if not row[f"v{year}"]:
                continue
            linked = index.get((year, row["drug_en"], row["tissue_zh"]), [])
            cell["links"][year] = linked
            cell["values"][year] = row[f"v{year}"]
            shown = {decimal(v) for v in row[f"v{year}"].split("/")}
            if {decimal(r["limit_value"]) for r in linked} != shown:
                link_failure(cell, year, "long values differ from panel values")
        cell["compared"] = list(cell["links"])
        cell["numbers"] = {y: decimal(row[f"v{y}"]) for y in cell["compared"]}
        cell["scope"] = {y: covered_animals(cell["links"][y]) for y in cell["compared"]}
        yield cell


def vetdrug_specificity(label: str) -> int:
    tokens = [t for t in label.split("/") if t]
    return min((0 if t == "所有食品动物" else 1 if t in {"家禽", "禽"} else 2
                for t in tokens), default=2)


def vetdrug_member_cells(rows, long_rows):
    index = defaultdict(list)
    for r in long_rows:
        if decimal(r["limit_value"]) is not None:
            index[(r["version_year"], r["drug_zh"], r["tissue_zh"])].append(r)
    for row in rows:
        cell = new_cell("vetdrug_member_panel", row)
        for year in REPLAY.YEARS_VETDRUG:
            if not row[f"v{year}"]:
                continue
            covering = [r for r in index.get((year, row["drug_zh"], row["tissue_zh"]), [])
                        if row["animal"] in REPLAY.animal_members(r["animal"])]
            if not covering:
                link_failure(cell, year, "no long row covers the animal")
                continue
            # The crosswalk keeps the last row of the most specific label.
            top = max(vetdrug_specificity(r["animal"]) for r in covering)
            linked = [r for r in covering if vetdrug_specificity(r["animal"]) == top]
            cell["links"][year] = linked
            cell["values"][year] = row[f"v{year}"]
            if not close(float(linked[-1]["limit_value"]) * VETDRUG_MG_PER_UG, row[f"v{year}"]):
                link_failure(cell, year, "kept long row does not carry the panel value")
            if len({r["limit_value"] for r in linked}) > 1:
                cell["flags"].append((
                    "masked_multiple_rules",
                    f"{year}: {len(linked)} equally specific rules; last kept "
                    + " | ".join(f"{r['animal']}={r['limit_value']}" for r in linked)))
        cell["compared"] = list(cell["links"])
        cell["numbers"] = {y: float(row[f"v{y}"]) for y in cell["compared"]}
        cell["animals"] = {y: tuple(sorted({r["animal"] for r in cell["links"][y]}))
                           for y in cell["compared"]}
        yield cell


# ---------- quarantine ----------

def name_tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[、,，()（）\[\]［］]", re.sub(r"\s+", "", text))
            if len(t) >= 2}


def quarantine_flags(cells, panel_rows, quarantine):
    by_id = {row["record_id"]: row for row in panel_rows}
    for cell in cells:
        if cell["panel"] not in FLAGS["quarantined_rule_same_key"][1]:
            continue
        row = by_id[cell["record_id"]]
        for q in quarantine:
            year = q["version_year"]
            if cell["panel"] == "additive_panel":
                hit = (q["standard"] == "GB 2760" and q["food_code"] == row["food_code"]
                       and q["additive_zh"] in json.loads(row["additive_names_zh"]))
            elif q["standard"] == "GB 2762" and q["analyte_zh"] == row["analyte_zh"]:
                name = row.get("food_member_zh") or row["food_category_zh"]
                hit = any(name in t or t in name for t in name_tokens(q["food_zh"]))
            else:
                hit = False
            if hit:
                state = "compared" if year in cell["compared"] else "not in panel"
                cell["flags"].append((
                    "quarantined_rule_same_key",
                    f"{year}: {q['record_id']} {q['reject_reason']} "
                    f"({q['food_zh']}={q['parsed_value']}); edition {state}"))


# ---------- generic checks ----------

def generic_flags(cell: dict, years: tuple[str, ...]) -> None:
    flags = cell["flags"]
    compared = cell["compared"]
    linked = [r for y in compared for r in cell["links"].get(y, [])]

    numbers = [cell["numbers"].get(y) for y in compared]
    if numbers and None not in numbers:
        if isinstance(numbers[0], tuple):  # pollutant: (dimension, value)
            numbers = [n[1] for n in numbers]
        expected = monotonic_label(numbers) if len(numbers) > 1 else "single_version"
        label = "stable" if cell["trend"] == "stable_gmp" else cell["trend"]
        if cell["trend"] != "stable_gmp" and expected != label:
            flags.append(("label_not_reproduced_by_monotonic_rule",
                          f"label {cell['trend']}, values give {expected}"))

    positions = [years.index(y) for y in compared]
    if positions and positions != list(range(positions[0], positions[-1] + 1)):
        skipped = [years[i] for i in range(positions[0], positions[-1] + 1)
                   if i not in positions]
        flags.append(("edition_gap", "skipped " + ",".join(skipped)))

    for key, flag in (("scope", "scope_text_differs"), ("host", "host_category_changes"),
                      ("animals", "animal_label_changes"), ("qualifier", "qualifier_differs")):
        per_year = cell[key]
        if per_year and len({per_year[y] for y in compared if y in per_year}) > 1:
            flags.append((flag, " -> ".join(f"{y}:{per_year[y]}" for y in compared
                                             if y in per_year)))
    residual = cell["residual"]
    if residual and len(set(residual.values())) > 1:
        flags.append(("residual_member_scope_changes", " -> ".join(
            f"{y}:minus {','.join(v) or 'nothing'}" for y, v in residual.items())))
    qualifier = cell["qualifier"]
    if qualifier and any(v not in ("", ("", "false")) for v in qualifier.values()):
        flags.append(("qualifier_present", ",".join(sorted({str(v) for v in qualifier.values()}))))

    if cell["panel"] == "pesticide_panel":
        for year in ("2016", "2019"):
            if year in compared:
                flags.append((f"pesticide_edition_{year}", f"{year} cell compared"))
        exceptions = sorted({r["review_status"] for r in linked
                             if r["review_status"] != "text_layer_auto_extracted"})
        if exceptions:
            flags.append(("pesticide_review_exception", ",".join(exceptions)))
    if any(r.get("conflict") == "1" for r in linked):
        flags.append(("conflict_row", "linked row has conflict=1"))
    if cell["panel"] == "mycotoxin_member_panel" and any(
            r["confidence"] == "manual" for r in cell["links"].get("2005", [])):
        flags.append(("manual_entry_mycotoxin_2005", "2005 manual rule compared"))
    if cell["panel"].startswith("vetdrug"):
        if any(r["source"] == "manual" for r in cell["links"].get("2019", [])):
            flags.append(("manual_entry_vetdrug_2019_cross_page", "2019 manual rule compared"))
        if any(r["source"] == "manual" for r in cell["links"].get("2022", [])):
            flags.append(("manual_entry_vetdrug_2022", "2022 manual rule compared"))


# ---------- driver ----------

def audit(tables: dict[str, list[dict[str, str]]], quarantine, taxonomy_rows, aliases,
          contained_in):
    """Return (cells, links) for every panel row; judged cells carry flags."""

    cells = []
    for panel, (long_name, years) in PANELS.items():
        rows, long_rows = tables[panel], tables[long_name]
        if panel in ("pesticide_panel", "additive_panel"):
            long_by_id = {r["record_id"]: r for r in long_rows}
            panel_cells = list(pesticide_or_additive_cells(panel, rows, long_by_id))
        elif panel == "pollutant_category_panel":
            panel_cells = list(pollutant_category_cells(rows, long_rows, aliases))
        elif panel == "pollutant_member_panel":
            panel_cells = list(pollutant_member_cells(rows, long_rows, aliases, contained_in))
        elif panel == "mycotoxin_panel":
            panel_cells = list(mycotoxin_cells(rows, long_rows))
        elif panel == "mycotoxin_member_panel":
            panel_cells = list(mycotoxin_member_cells(rows, long_rows, taxonomy_rows))
        elif panel == "vetdrug_panel":
            panel_cells = list(vetdrug_cells(rows, long_rows))
        else:
            panel_cells = list(vetdrug_member_cells(rows, long_rows))
        quarantine_flags(panel_cells, rows, quarantine)
        for cell in panel_cells:
            if cell["trend"] in JUDGED:
                generic_flags(cell, years)
            else:
                cell["flags"] = [f for f in cell["flags"] if f[0] == "link_failure"]
            unknown = {f[0] for f in cell["flags"]} - set(FLAGS)
            if unknown:
                raise AuditError(f"unregistered flag: {unknown}")
        cells.extend(panel_cells)
    return cells


def flag_rows(cells):
    for cell in cells:
        seen = set()
        for flag, detail in cell["flags"]:
            if (flag, detail) in seen:
                continue
            seen.add((flag, detail))
            yield {
                "panel": cell["panel"], "panel_record_id": cell["record_id"],
                "trend": cell["trend"], "flag": flag, "kind": FLAGS[flag][0],
                "years": ",".join(cell["compared"]),
                "source_record_ids": json.dumps(
                    {y: [r["record_id"] for r in cell["links"][y]] for y in cell["compared"]},
                    ensure_ascii=False, separators=(",", ":")),
                "detail": detail,
            }


def summary_rows(cells):
    for panel in PANELS:
        judged = [c for c in cells if c["panel"] == panel and c["trend"] in JUDGED]
        for flag, (kind, panels) in FLAGS.items():
            hit = [c for c in judged if any(f[0] == flag for f in c["flags"])]
            if flag == "link_failure":
                hit = [c for c in cells if c["panel"] == panel
                       and any(f[0] == flag for f in c["flags"])]
            by_trend = Counter(c["trend"] for c in hit)
            yield {
                "panel": panel, "flag": flag, "kind": kind,
                "applicable": "yes" if panel in panels else "no",
                "judged_cells": len(judged), "flagged_cells": len(hit),
                **{t: by_trend.get(t, 0) for t in JUDGED},
            }


def link_rows(cells):
    for cell in cells:
        for year, linked in cell["links"].items():
            yield {
                "panel": cell["panel"], "panel_record_id": cell["record_id"],
                "version_year": year, "panel_value": cell["values"].get(year, ""),
                "source_record_ids": json.dumps([r["record_id"] for r in linked]),
            }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    release, output = args.release_dir.resolve(), args.output_dir.resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"output directory is not empty: {output}")
    names = sorted(set(PANELS) | {v[0] for v in PANELS.values()})
    tables = {}
    inputs = {}
    for name in names:
        filename = name if name.endswith(".csv") else f"{name}.csv"
        path = release / filename
        tables[name] = read_csv(path)
        inputs[filename] = sha256(path)
    quarantine_path = release / "quarantined_rows.csv"
    taxonomy_path = args.dependency_dir / "food_taxonomy.csv"
    alias_path = args.dependency_dir / "category_alias.csv"
    containment_path = args.dependency_dir / "category_containment.csv"
    for path in (quarantine_path, taxonomy_path, alias_path, containment_path):
        inputs[path.name] = sha256(path)

    aliases = POLLUTANT.load_aliases(alias_path)
    folded = {unicodedata.normalize("NFKC", k): unicodedata.normalize("NFKC", v)
              for k, v in aliases.items()}
    cells = audit(tables, read_csv(quarantine_path), read_csv(taxonomy_path), aliases,
                  POLLUTANT.load_containment(containment_path, folded))
    flags = list(flag_rows(cells))
    summary = list(summary_rows(cells))
    links = list(link_rows(cells))
    for row in summary:
        if row["applicable"] == "no" and row["flagged_cells"]:
            raise AuditError(f"flag fired outside its panels: {row}")

    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "panel_trend_flags.csv", FLAG_FIELDS, flags)
    write_csv(output / "panel_trend_summary.csv", SUMMARY_FIELDS, summary)
    write_csv(output / "panel_cell_links.csv", LINK_FIELDS, links)
    coverage = {}
    for long_name in sorted({v[0] for v in PANELS.values()}):
        referenced = {r["record_id"] for c in cells if PANELS[c["panel"]][0] == long_name
                      for y in c["links"] for r in c["links"][y]}
        coverage[long_name] = {"rows": len(tables[long_name]),
                               "referenced_by_a_panel": len(referenced)}
    report = {
        "release_dir": str(release.relative_to(PROJECT_ROOT)
                           if release.is_relative_to(PROJECT_ROOT) else release),
        "inputs_sha256": inputs,
        "judged_trends": list(JUDGED),
        "flag_kinds": {flag: kind for flag, (kind, _) in FLAGS.items()},
        "panel_rows": {p: len(tables[p]) for p in PANELS},
        "link_failures": sum(r["flagged_cells"] for r in summary if r["flag"] == "link_failure"),
        "long_row_coverage": coverage,
    }
    (output / "panel_trend_audit_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"link_failures": report["link_failures"],
                      "flag_rows": len(flags)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
