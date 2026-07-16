#!/usr/bin/env python3
"""四张稿件表 —— 从 Data/Final 生成 Results/tab/tab1<Name>.tex(longtable, 约定命名)。

脚本直接读取本工程 Data/Final 真源，输出供 main-en.tex ``\\input`` 的
LaTeX longtable。历史 markdown 生成器已停用，避免维护两套稿件结果接口。
label = 文件名主干、无下划线(tab1AlignmentFailures / tab1ExtractionMethod /
tab1FileInventory / tab1ValidationMetrics)。
表里的 → 与 μ 走 main-en.tex 的 \\newunicodechar 渲染;**加粗** 由 bold() 转 \\textbf{}。
"""
import argparse
import csv
import json
import os
import re
from collections import Counter, OrderedDict
from pathlib import Path

PROJ = str(Path(__file__).resolve().parents[2])
REL = os.path.join(PROJ, "Data", "Final", "china_food_limit_panel_v1")
OUT = os.path.join(PROJ, "Results", "tab")
DEFAULT_VALIDATION_REPORT = os.path.join(REL, "validation_report.json")
os.makedirs(OUT, exist_ok=True)


def rd(f):
    with open(os.path.join(REL, f), encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def bold(s):
    """markdown **x** → \\textbf{x}"""
    return re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", s)


def write_tab(name, colspec, caption, header, body_rows):
    lines = ["\\begin{longtable}[]{" + colspec + "}",
             "\\caption{" + caption + "}\\label{" + name + "}\\tabularnewline",
             "\\toprule", header + " \\\\", "\\midrule", "\\endfirsthead",
             "\\toprule", header + " \\\\", "\\midrule", "\\endhead"]
    lines += [r + " \\\\" for r in body_rows]
    lines += ["\\bottomrule", "\\end{longtable}"]
    with open(os.path.join(OUT, name + ".tex"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {name}.tex ({len(body_rows)} rows)")


# ── Table 1 · 对齐失败四维 ────────────────────────────────────────
T1_SPEC = (r"@{}>{\raggedright\arraybackslash}p{0.13\textwidth}"
           r">{\raggedright\arraybackslash}p{0.17\textwidth}"
           r">{\raggedright\arraybackslash}p{0.28\textwidth}"
           r">{\raggedright\arraybackslash}p{0.30\textwidth}@{}")
T1_CAP = ("The alignment failures, one row per dimension along which a revision can move. "
          "Two columns hold the conclusion a numbers-only panel reaches and the fact. The "
          "dimensions are the unit (polychlorinated biphenyls), the chemical species (mercury "
          "and arsenic in edible fungi), the basis of expression (nitrite in infant formula, "
          "whose value holds while the basis moves from a powdered to a solid product), and the "
          "food category, which is absorbed (milk powder), narrowed (distilled spirits), or "
          "split (rice).")
T1_HEAD = "Dimension & Case & What a numbers-only panel concludes & What actually happened"


def table1():
    m = rd("pollutant_member_panel.csv")

    def member(analyte, food):
        matches = [
            row
            for row in m
            if row["analyte_zh"] == analyte and row["food_member_zh"] == food
        ]
        assert len(matches) == 1, f"Table 1 锚定行不唯一:{analyte}·{food}"
        return matches[0]

    def mass_mgkg(value, unit):
        factor = {"mg/kg": 1.0, "μg/kg": 0.001}[unit]
        return float(value) * factor

    pcb = member("多氯联苯", "水产动物及其制品")
    total_hg = member("总汞", "食用菌及其制品")
    methyl_hg = member("甲基汞", "食用菌及其制品")
    total_as = member("总砷", "食用菌及其制品")
    inorganic_as = member("无机砷", "食用菌及其制品")
    nit = member("亚硝酸盐", "婴儿配方食品")
    milk = member("铅", "乳粉")
    spirits = member("铅", "蒸馏酒")
    paddy = member("无机砷", "稻谷")
    brown = member("无机砷", "糙米")

    pcb_apparent = float(pcb["v2022"]) / float(pcb["v2017"])
    pcb_real = mass_mgkg(pcb["v2017"], pcb["unit_2017"]) / mass_mgkg(
        pcb["v2022"], pcb["unit_2022"]
    )
    milk_fold = float(milk["v2017"]) / float(milk["v2022"])
    spirits_fold = float(spirits["v2017"]) / float(spirits["v2022"])
    basis_en = {
        "粉状产品计": "a powdered-product basis",
        "固态产品计": "a solid-product basis",
    }

    assert pcb["trend"] == "tightened"
    assert nit["trend"] == "incomparable_basis_unit_or_value"
    assert milk["trend"] == spirits["trend"] == "tightened"
    assert paddy["trend"] == brown["trend"] == "relaxed"
    assert paddy["host_category_2017"] == brown["host_category_2017"] == "稻谷、糙米、大米"
    rows = [
        ("Unit", "PCBs, aquatic animals",
         f"{pcb['v2017']} → {pcb['v2022']}, a {pcb_apparent:g}-fold **relaxation**",
         f"The unit changed from {pcb['unit_2017']} to {pcb['unit_2022']} in 2022. "
         f"{pcb['v2017']} {pcb['unit_2017']} became "
         f"{mass_mgkg(pcb['v2022'], pcb['unit_2022']):g} mg/kg, a "
         f"{pcb_real:g}-fold **tightening**. The sign is reversed."),
        ("Species", "Mercury and arsenic, edible fungi",
         f"{total_hg['v2017']} → {methyl_hg['v2022']} and "
         f"{total_as['v2017']} → {inorganic_as['v2022']}, **stable**",
         "The 2022 entries regulate methylmercury and inorganic arsenic where the earlier "
         "entries regulate total mercury and total arsenic. The regulated quantities differ."),
        ("Basis of expression", "Nitrite, infant formula",
         f"{nit['v2012']} → {nit['v2022']}, **stable**",
         f"The value did not move, but the basis changed from {basis_en[nit['basis_2012']]} "
         f"in 2012 and 2017 to {basis_en[nit['basis_2022']]} in 2022 and 2025. "
         "The two printed values are not "
         "directly comparable. "
         "Wood-ear methylmercury, 0.1 on a dry-weight basis, is likewise not the 0.1 of the parent "
         "class as sold."),
        ("Category (absorbed)", "Lead, milk powder", "Printed category **deleted**",
         f"The member panel follows milk powder from {milk['v2017']} to {milk['v2022']} mg/kg "
         f"as its host changes, a {milk_fold:g}-fold **tightening**."),
        ("Category (narrowed)", "Lead, distilled spirits",
         "Printed category **deleted**",
         f"The member panel follows distilled spirits from {spirits['v2017']} to "
         f"{spirits['v2022']} mg/kg as the named 0.5 class narrows, a "
         f"{spirits_fold:g}-fold **tightening**."),
        ("Category (split)", "Inorganic arsenic, rice",
         "Printed category **deleted**",
         f"Paddy and brown rice move from a shared paddy/brown-rice/milled-rice category at "
         f"{paddy['v2017']} mg/kg to separate {paddy['v2022']} mg/kg entries in 2022; "
         "both member-level changes are **relaxations**."),
    ]
    body = [" & ".join(bold(c) for c in row) for row in rows]
    write_tab("tab1AlignmentFailures", T1_SPEC, T1_CAP, T1_HEAD, body)


# ── Table 2 · 读取方式与行数 ──────────────────────────────────────
T2_SPEC = (r"@{}>{\raggedright\arraybackslash}p{0.20\textwidth}"
           r">{\raggedright\arraybackslash}p{0.11\textwidth}"
           r">{\raggedright\arraybackslash}p{0.09\textwidth}"
           r">{\raggedleft\arraybackslash}p{0.07\textwidth}"
           r">{\raggedright\arraybackslash}p{0.34\textwidth}@{}")
T2_CAP = ("Extraction method and reliability by family. For each of the five families and each "
          "version, the primary read path and the resulting released row count. The 2019 and "
          "2021 pesticide editions use government-hosted text-layer extraction copies; frozen "
          "OCR of the corresponding scans is retained only as a cross-check.")
T2_HEAD = "Family & Standard & Version & Rows & Read path"
READ_PATH = {
    ("pesticide", "text"): "text layer",
    ("pesticide", "ocr"): "OCR (watermarked scan)",
    ("vetdrug", "docx-block"): "Word table stream (Ministry of Agriculture Announcement 235)",
    ("vetdrug", "text"): "text layer",
    ("vetdrug", "manual"): "manual (page images)",
}
STATIC_PATH = {
    ("contaminant", None): "text layer (coordinate-based)",
    ("mycotoxin", "2005"): "manual (corrupt text layer)",
    ("mycotoxin", "2011"): "text layer",
    ("mycotoxin", "2017"): "text layer",
    ("additive", None): "text layer",
}
STD = {"contaminant": "GB 2762", "pesticide": "GB 2763", "mycotoxin": "GB 2761",
       "vetdrug": "GB 31650", "additive": "GB 2760"}
VET_STANDARD = {
    "2002": "Ministry of Agriculture Announcement 235",
    "2019": "GB 31650",
    "2022": "GB 31650.1",
}
FAMILY_LABEL = {"contaminant": "Contaminants", "pesticide": "Pesticide residues",
                "mycotoxin": "Mycotoxins", "vetdrug": "Veterinary drug residues",
                "additive": "Food additives"}


def table2():
    body = []
    fam_of = OrderedDict([
        ("pollutant_limits_long.csv", "contaminant"), ("pesticide_limits_long.csv", "pesticide"),
        ("mycotoxin_limits_long.csv", "mycotoxin"), ("vetdrug_limits_long.csv", "vetdrug"),
        ("additive_limits_long.csv", "additive"),
    ])
    for f, fam in fam_of.items():
        rows = rd(f)
        for v in sorted({r["version_year"] for r in rows}):
            vr = [r for r in rows if r["version_year"] == v]
            if fam == "pesticide":
                roles = {row["source_copy_role"] for row in vr}
                if roles == {"government_hosted_text_layer_extraction_copy"}:
                    path = (
                        "government-hosted PDF text layer; frozen OCR cross-check "
                        "against the scanned edition"
                    )
                elif roles == {"archive_text_layer_edition_source_copy"}:
                    path = "edition PDF coordinate text layer"
                else:
                    raise ValueError(
                        f"unexpected GB 2763 source roles for {v}: {sorted(roles)}"
                    )
            elif "source" in rows[0]:
                srcs = Counter(r["source"] for r in vr)
                main = srcs.most_common(1)[0][0]
                path = READ_PATH.get((fam, main), main)
                extra = {s: c for s, c in srcs.items() if s != main}
                if extra:
                    tail = ", ".join(f"{c} {READ_PATH.get((fam, s), s)}" for s, c in extra.items())
                    path = f"{path}; {tail}"
            else:
                path = STATIC_PATH.get((fam, None)) or STATIC_PATH.get((fam, v), "text layer")
            standard = VET_STANDARD[v] if fam == "vetdrug" else STD[fam]
            body.append(f"{FAMILY_LABEL[fam]} & {standard} & {v} & {len(vr):,} & {path}")
    write_tab("tab1ExtractionMethod", T2_SPEC, T2_CAP, T2_HEAD, body)


# ── Table 3 · 主要源依赖验证指标 ──────────────────────────────────
T3_SPEC = (
    r"@{}>{\raggedright\arraybackslash}p{0.18\textwidth}"
    r">{\raggedright\arraybackslash}p{0.14\textwidth}"
    r">{\raggedleft\arraybackslash}p{0.16\textwidth}"
    r">{\raggedleft\arraybackslash}p{0.09\textwidth}"
    r">{\raggedleft\arraybackslash}p{0.09\textwidth}"
    r">{\raggedright\arraybackslash}p{0.14\textwidth}@{}"
)
T3_CAP = (
    "Main source-dependent validation diagnostics. Positional traceback uses "
    "every eligible row; its rate uses the decidable subset, and a parenthetical "
    "eligible count is shown when the two denominators differ. The shuffled "
    "column gives the value-permuted control. A traceback pass also requires "
    "at least 30 decidable rows and an observed-minus-shuffled gap of at least "
    "25 percentage points. Entity coverage compares "
    "the released unique-entity count with independently countable source-entry "
    "markers; it is a count proxy and not entity-level sensitivity."
)
T3_HEAD = (
    "Diagnostic & Edition & Numerator / denominator & Observed & Shuffled & "
    "Criterion"
)
TRACEBACK_CASES = (
    ("pollutant.2022", "Food--value traceback", "GB 2762-2022"),
    ("pesticide.2016", "Entity--food--value traceback", "GB 2763-2016"),
    ("vetdrug.2019", "Entity--tissue--value traceback", "GB 31650-2019"),
    ("additive.2024", "Entity--food--value traceback", "GB 2760-2024"),
)
ENTITY_CASES = (
    ("additive.2014", "Entity-count coverage", "GB 2760-2014"),
    ("additive.2024", "Entity-count coverage", "GB 2760-2024"),
    ("vetdrug.2019", "Entity-count coverage", "GB 31650-2019"),
    ("pesticide.2012", "Entity-count coverage", "GB 2763-2012"),
    ("pesticide.2014", "Entity-count coverage", "GB 2763-2014"),
    ("pesticide.2016", "Entity-count coverage", "GB 2763-2016"),
)


def _percentage(value):
    return f"{100 * float(value):.2f}\\%"


def table3(validation_report):
    with open(validation_report, encoding="utf-8") as handle:
        report = json.load(handle)
    if report.get("report_schema_version") != "3.0":
        raise ValueError("Table 3 requires validation-report schema 3.0")
    checks = {
        item["id"]: item
        for layer in report["layers"].values()
        for item in layer
    }
    body = []
    for case_id, diagnostic, edition in TRACEBACK_CASES:
        check_id = f"source.positional_traceback.{case_id}"
        item = checks.get(check_id)
        if item is None or item["status"] != "pass":
            raise ValueError(f"Table 3 requires a passing {check_id}")
        details = item["details"]
        denominator = f"{details['decidable']:,}"
        eligible = details.get("eligible_rows")
        if eligible is not None and eligible != details["decidable"]:
            denominator += f" ({eligible:,} eligible)"
        body.append(
            " & ".join(
                (
                    diagnostic,
                    edition,
                    f"{details['true_passed']:,} / {denominator}",
                    _percentage(details["true_rate"]),
                    _percentage(details["shuffled_rate"]),
                    f"$\\geq$ {_percentage(details['minimum_true_rate'])}",
                )
            )
        )
    for case_id, diagnostic, edition in ENTITY_CASES:
        check_id = f"source.entity_count_coverage.{case_id}"
        item = checks.get(check_id)
        if item is None or item["status"] != "pass":
            raise ValueError(f"Table 3 requires a passing {check_id}")
        details = item["details"]
        body.append(
            " & ".join(
                (
                    diagnostic,
                    edition,
                    (
                        f"{details['released_unique_entities']:,} / "
                        f"{details['independently_counted_source_entries']:,}"
                    ),
                    _percentage(details["entity_count_coverage"]),
                    "---",
                    (
                        f"{100 * details['minimum_coverage']:.0f}--"
                        f"{100 * details['maximum_coverage']:.0f}\\%"
                    ),
                )
            )
        )
    write_tab("tab1ValidationMetrics", T3_SPEC, T3_CAP, T3_HEAD, body)


# ── Table 3 · 存放清单 ────────────────────────────────────────────
T4_SPEC = (r"@{}>{\raggedright\arraybackslash}p{0.34\textwidth}"
           r">{\raggedleft\arraybackslash}p{0.07\textwidth}"
           r">{\raggedright\arraybackslash}p{0.51\textwidth}@{}")
T4_HEAD = "File & Rows & Contents"

# 组 → [(文件名, 说明)]。行数一律从发布文件现数,不写死;文件集合与 Data/Final
# 不符即报错,避免稿件清单与发布包分家(README 行数过期的老病)。
DEPOSIT_INVENTORY = OrderedDict([
    ("Family-specific long tables", [
        ("pollutant_limits_long.csv",
         "Contaminant limits as printed, with the basis of expression, normalisation "
         "status, extraction path, and a normalised value only where conversion is "
         "justified."),
        ("pesticide_limits_long.csv",
         "Pesticide maximum residue limits with cleaned and raw name strings, printed "
         "qualifiers, stable pesticide and food keys, review status, source page and "
         "coordinates, and separate edition and extraction source identifiers."),
        ("mycotoxin_limits_long.csv",
         "Mycotoxin limits as printed, with a per-record confidence field."),
        ("vetdrug_limits_long.csv",
         "Veterinary-drug limits with the printed target-animal cell alongside its "
         "canonical animal representation. The 2002 records carry Word-table locators."),
        ("additive_limits_long.csv",
         "Additive maximum-use entries with CNS and INS identifiers, food-category "
         "codes and use-condition notes."),
    ]),
    ("Aligned category panels", [
        ("pollutant_category_panel.csv",
         "Contaminant values by version with per-version units, bases, source "
         "categories and cell status."),
        ("pesticide_panel.csv",
         "Pesticide cells retaining every candidate value, unit, rule object and "
         "source record identifier, with stable keys and explicit status fields."),
        ("mycotoxin_panel.csv",
         "Mycotoxin values by version at the aligned category level."),
        ("vetdrug_panel.csv",
         "Veterinary-drug values by version at the aligned category level."),
        ("additive_panel.csv",
         "Additive cells retained at the exact CNS and food-code level, with every "
         "candidate and rule object preserved."),
    ]),
    ("Member-level panels", [
        ("pollutant_member_panel.csv",
         "Contaminant members with the applicable host category by version and the "
         "category-restructuring flag."),
        ("mycotoxin_member_panel.csv",
         "Mycotoxin members with the applicable host category by version and the "
         "category-restructuring flag."),
        ("vetdrug_member_panel.csv",
         "Animal and tissue pairs expanded from the printed animal groups, with "
         "values and a trend for each pair."),
    ]),
    ("English-name lookups", [
        ("entity_names_en.csv",
         "English substance names printed by the standards themselves."),
        ("food_category_names_en.csv",
         "Food-category labels linked to published translations, with the match "
         "method, evidence and source document. Partial; additives and pesticides only."),
        ("additive_names_en.csv",
         "Additive names linked to a published translation by CNS code. Partial."),
    ]),
    ("Metadata, audit and quarantine", [
        ("source_manifest.csv",
         "The source-identity key for the release. Covers 21 edition sources, two "
         "text-layer extraction copies and two identity-audit copies, each with its "
         "digest, role, release status and attributed row count."),
        ("version_dates.csv",
         "Issue and effective dates for the coverage editions, with date provenance "
         "and the official-register cross-check."),
        ("standard_version_timeline.csv",
         "The wider history of food-safety national standards as dated edition and "
         "amendment events. Ancillary to the five-family panel."),
        ("standard_timeline_conflicts.csv",
         "Two ranked candidate rows for the one metadata conflict met in the "
         "wider-history build."),
        ("pesticide_edition_reconciliation.csv",
         "Visible Chapter 4 rule counts and section rosters against each edition's "
         "declared aggregate, with printed qualifier counts."),
        ("pesticide_ocr_crosscheck.csv",
         "Text-layer against OCR comparison groups for the two scanned editions, with "
         "matched values, one-sided rows, matching level and status."),
        ("quarantined_rows.csv",
         "Fragments rejected by the extraction gates, with the rejection reason and "
         "source path."),
        ("data_dictionary.csv",
         "Every released field, with type, nullability, allowed values, key role and "
         "a bilingual description."),
    ]),
])

# 非 CSV 存放物。行数列留 ---(不是表格)。
NON_CSV_FILES = [
    ("README.md",
     "Package overview, file list and the five-family language-coverage matrix."),
    ("LICENSE.md",
     "CC BY 4.0 terms for the author-created compilation and the source-rights "
     "boundary."),
    ("SOURCE_ACQUISITION.md",
     "Public locator and byte-identity status for all 25 Chinese source files and "
     "the four translations."),
    ("_build_stats.json",
     "Deterministic build statistics written by the release assembler."),
    ("validate.py",
     "The distributed validation suite."),
    ("validation_report.json",
     "Machine-readable status and evidence for every catalogued check."),
]


def csv_rows(filename):
    with open(os.path.join(REL, filename), encoding="utf-8-sig", newline="") as fh:
        return max(sum(1 for _ in csv.reader(fh)) - 1, 0)


def table4():
    listed = [f for group in DEPOSIT_INVENTORY.values() for f, _ in group]
    on_disk = sorted(p.name for p in Path(REL).glob("*.csv"))
    if sorted(listed) != on_disk:
        missing = sorted(set(on_disk) - set(listed))
        extra = sorted(set(listed) - set(on_disk))
        raise ValueError(
            "存放清单与 Data/Final 不符 —— 表会过期。"
            f"清单缺:{missing};清单多余:{extra}"
        )
    for filename, _ in NON_CSV_FILES:
        if not os.path.isfile(os.path.join(REL, filename)):
            raise ValueError(f"存放清单列出但发布包没有:{filename}")

    counts = {f: csv_rows(f) for f in listed}
    long_total = sum(
        counts[f] for f, _ in DEPOSIT_INVENTORY["Family-specific long tables"]
    )
    caption = (
        "Inventory of the data deposit. The package is a flat directory of "
        f"{len(listed)} CSV files together with the documentation, the release "
        "licence, deterministic build statistics, the validation script and its "
        "machine-readable report. Row counts exclude the header row and are read "
        f"from the released files. The five long tables hold the {long_total:,} "
        "released limit records; the panels, lookups and audit tables are derived "
        "from those records and are not additional limits."
    )

    body = []
    for index, (group, entries) in enumerate(DEPOSIT_INVENTORY.items()):
        lead = "" if index == 0 else "\\addlinespace "
        body.append(f"{lead}\\multicolumn{{3}}{{@{{}}l}}{{\\emph{{{group}}}}}")
        for filename, description in entries:
            body.append(
                f"\\path{{{filename}}} & {counts[filename]:,} & {description}"
            )
    body.append("\\addlinespace \\multicolumn{3}{@{}l}{\\emph{Documentation and code}}")
    for filename, description in NON_CSV_FILES:
        body.append(f"\\path{{{filename}}} & --- & {description}")
    write_tab("tab1FileInventory", T4_SPEC, caption, T4_HEAD, body)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validation-report",
        default=DEFAULT_VALIDATION_REPORT,
        help="Passing schema-3 validation report used to generate the diagnostics table.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    table1()
    table2()
    table4()
    table3(args.validation_report)
    print("tables →", OUT)
