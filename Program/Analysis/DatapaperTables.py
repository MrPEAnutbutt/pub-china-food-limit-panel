#!/usr/bin/env python3
"""九张稿件表 —— 从 Data/Final 生成 Results/tab/tab1<Name>.tex(longtable, 约定命名)。

脚本直接读取本工程 Data/Final 真源，输出供 main-en.tex ``\\input`` 的
LaTeX longtable。历史 markdown 生成器已停用，避免维护两套稿件结果接口。
独立核验结果表和核验宏另读入 git 的冻结核验证据(Data/Interim 下三处)。
label = 文件名主干、无下划线(tab1AlignmentFailures / tab1ExtractionMethod /
tab1FileInventory / tab1ValidationMetrics / tab1PanelRules / tab1TraceExamples /
tab1Restructuring / tab1IndependentVerification / tab1NaturalKeys)。
表里的 → 与 μ 走 main-en.tex 的 \\newunicodechar 渲染;**加粗** 由 bold() 转 \\textbf{}。
另写 Results/tab/DatapaperNumbers.tex:正文引用的发布包计数宏(宏名只用字母)。
"""
import argparse
import csv
import importlib.util
import json
import os
import re
from collections import Counter, OrderedDict
from decimal import ROUND_HALF_UP, Decimal
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
    baijiu = member("铅", "白酒")
    liquor = member("铅", "酒类")
    paddy = member("无机砷", "稻谷")
    brown = member("无机砷", "糙米")

    pcb_apparent = float(pcb["v2022"]) / float(pcb["v2017"])
    pcb_real = mass_mgkg(pcb["v2017"], pcb["unit_2017"]) / mass_mgkg(
        pcb["v2022"], pcb["unit_2022"]
    )
    milk_fold = float(milk["v2017"]) / float(milk["v2022"])
    basis_en = {
        "粉状产品计": "a powdered-product basis",
        "固态产品计": "a solid-product basis",
    }

    assert pcb["trend"] == "tightened"
    assert nit["trend"] == "incomparable_basis_unit_or_value"
    assert milk["trend"] == "tightened"
    assert baijiu["trend"] == "stable" and len({baijiu[f"v{y}"] for y in ("2012", "2017", "2022", "2025")}) == 1
    assert spirits["v2022"] == "" and "spans two printed rules" in spirits["note"]
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
         f"From 2022 the {baijiu['v2022']} mg/kg class names baijiu instead of all distilled "
         f"spirits; other spirits fall under the {liquor['v2022']} mg/kg rule for alcoholic "
         f"beverages. Baijiu stays at {baijiu['v2012']} mg/kg in all four editions; distilled "
         "spirits now spans two rules, so the member panel leaves it blank from 2022."),
        ("Category (split)", "Inorganic arsenic, rice",
         "Printed category **deleted**",
         f"Paddy and brown rice move from a shared paddy/brown-rice/milled-rice category at "
         f"{paddy['v2017']} mg/kg to separate {paddy['v2022']} mg/kg entries in 2022; "
         "both member-level changes are **relaxations**."),
    ]
    body = [" & ".join(bold(c) for c in row) for row in rows]
    write_tab("tab1AlignmentFailures", T1_SPEC, T1_CAP, T1_HEAD, body)


# ── Table 2 · 各抽取方法的记录数与占比 ────────────────────────────
T2_SPEC = (r"@{}>{\raggedright\arraybackslash}p{0.16\textwidth}"
           r">{\raggedright\arraybackslash}p{0.08\textwidth}"
           r">{\raggedleft\arraybackslash}p{0.09\textwidth}"
           r">{\raggedleft\arraybackslash}p{0.08\textwidth}"
           r">{\raggedright\arraybackslash}p{0.44\textwidth}@{}")
T2_CAP = ("Released records by extraction method. Each row is an edition and the method recorded "
          "in the \\texttt{extraction\\_method} field of its long-table rows; the last rows total "
          "each method across the release. Shares are percentages of all released records. The "
          "same counts, with shares within each family, are released in "
          "\\texttt{extraction\\_method\\_summary.csv}. The coordinate parser assigns rows and "
          "columns from word positions in the PDF text layer. The 2019 and 2021 pesticide "
          "editions were read from government-hosted text-layer copies, and OCR of the edition "
          "scans served only as a cross-check.")
T2_HEAD = "Standard & Version & Records & Share & Extraction method"
LONG_TABLE = OrderedDict([("contaminant", "pollutant_limits_long.csv"),
                          ("pesticide", "pesticide_limits_long.csv"),
                          ("mycotoxin", "mycotoxin_limits_long.csv"),
                          ("veterinary_drug", "vetdrug_limits_long.csv"),
                          ("additive", "additive_limits_long.csv")])
FAMILY_LABEL = {"contaminant": "Contaminants", "pesticide": "Pesticide residues",
                "mycotoxin": "Mycotoxins", "veterinary_drug": "Veterinary drug residues",
                "additive": "Food additives"}
STANDARD_LABEL = {"MOA Announcement 235": "Announcement No.~235"}
COPY_NOTE = "read from a government-hosted text-layer copy, with OCR of the scan as a cross-check"
METHOD_NOTE = {
    ("pesticide", "2019"): COPY_NOTE,
    ("pesticide", "2021"): COPY_NOTE,
    ("mycotoxin", "2005"): "the text layer is corrupt",
    ("veterinary_drug", "2019", "manual_page_image_transcription"): "rows at page breaks",
}


def share(part, whole):
    return str((Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.01"),
                                                               rounding=ROUND_HALF_UP))


def table2():
    summary = rd("extraction_method_summary.csv")
    counted = Counter()
    for family, name in LONG_TABLE.items():
        counted.update((family, r["version_year"], r["extraction_method"]) for r in rd(name))
    total = sum(counted.values())
    if counted != Counter({(r["family"], r["version_year"], r["extraction_method"]):
                          int(r["records"]) for r in summary}):
        raise ValueError("extraction_method_summary.csv disagrees with the long tables")
    body, previous = [], None
    for r in summary:
        if r["family"] != previous:
            previous = r["family"]
            body.append(f"\\addlinespace \\multicolumn{{5}}{{@{{}}l}}"
                        f"{{\\emph{{{FAMILY_LABEL[previous]}}}}}")
        if share(r["records"], total) != r["share_of_release_pct"]:
            raise ValueError(f"share of release differs for {r}")
        note = (METHOD_NOTE.get((r["family"], r["version_year"], r["extraction_method"]))
                or METHOD_NOTE.get((r["family"], r["version_year"])))
        method = f"\\path{{{r['extraction_method']}}}" + (f"; {note}" if note else "")
        body.append(f"{STANDARD_LABEL.get(r['standard'], r['standard'])} & "
                    f"{r['version_year']} & {int(r['records']):,} & "
                    f"{r['share_of_release_pct']} & {method}")
    methods = Counter()
    for (_, _, method), n in counted.items():
        methods[method] += n
    for i, (method, n) in enumerate(methods.most_common()):
        lead = "\\midrule " if i == 0 else ""
        body.append(f"{lead}All editions & & {n:,} & {share(n, total)} & \\path{{{method}}}")
    body.append(f"Total & & {total:,} & 100.00 &")
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
         "digest, role, source class, release status and attributed row count."),
        ("extraction_method_summary.csv",
         "Released records by family, edition and row-level extraction method, with "
         "shares of the family and of the release."),
        ("record_id_changes.csv",
         "Record identifiers replaced, removed or added since release v1.0, paired on "
         "each table's natural key."),
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
        "from those records and are not additional limits. Each long table ends with "
        "row-level source-reference, extraction-method and verification fields, and "
        "every panel links its cells to the contributing long-table records."
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


# ── Table 5 · 长表状况到面板与趋势 ────────────────────────────────
T5_SPEC = (r"@{}>{\raggedright\arraybackslash}p{0.21\textwidth}"
           r">{\raggedright\arraybackslash}p{0.43\textwidth}"
           r">{\raggedright\arraybackslash}p{0.28\textwidth}@{}")
T5_HEAD = "Condition kept in the long tables & Treatment in the panels & Trend state (panel rows)"
T5_CAP = ("How conditions retained in the long tables carry into the panels and trends. "
          "Counts refer to release v1.1 and are panel rows unless stated otherwise. A trend "
          "is assigned only when consecutive editions each contribute one rule with the same "
          "unit, basis and scope; otherwise the row receives the named state. No trend field "
          "records the appearance or withdrawal of a limit.")
YEARS = {
    "pesticide_panel.csv": ("2012", "2014", "2016", "2019", "2021", "2026"),
    "additive_panel.csv": ("2011", "2014", "2024"),
    "pollutant_category_panel.csv": ("2012", "2017", "2022", "2025"),
    "pollutant_member_panel.csv": ("2012", "2017", "2022", "2025"),
}
JUDGED = {"stable", "tightened", "relaxed", "fluctuation"}


def tt(code):
    """字段值或文件名 → \\path{}(下划线处可断行)。"""
    return "\\path{" + code + "}"


def joined(parts):
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def table5():
    trend = {f: Counter(r["trend"] for r in rd(f)) for f in (
        "pollutant_category_panel.csv", "pollutant_member_panel.csv", "pesticide_panel.csv",
        "mycotoxin_panel.csv", "mycotoxin_member_panel.csv", "vetdrug_panel.csv",
        "vetdrug_member_panel.csv", "additive_panel.csv")}
    cells = {f: Counter(r[f"status_{y}"] for r in rd(f) for y in YEARS[f])
             for f in ("pesticide_panel.csv", "additive_panel.csv")}
    multi_pest = sum(n for s, n in cells["pesticide_panel.csv"].items() if s.startswith("multiple"))
    multi_add = sum(n for s, n in cells["additive_panel.csv"].items() if s.startswith("multiple"))
    pol_cat = rd("pollutant_category_panel.csv")
    # 污染物类别面板按 物质·类别·基准 分行:同版一格至多一条规则。
    assert {r[f"cell_status_{y}"] for r in pol_cat
            for y in YEARS["pollutant_category_panel.csv"]} == {"single", "missing"}
    pol_long = rd("pollutant_limits_long.csv")
    with_basis = sum(1 for r in pol_long if r["limit_basis"])
    density = sum(1 for r in pol_long if r["normalization_status"] == "density_required")

    blanks, noted = Counter(), 0
    for r in rd("pollutant_member_panel.csv"):
        noted += bool(r["note"])
        for group in filter(None, r["note"].split(" | ")):
            years, text = group.split(": ", 1)
            blanks[text.split(" by ")[0].split(";")[0]] += len(years.split(", "))
    assert set(blanks) == {"excluded", "spans two printed rules", "host not determinable"}

    # 隔离片段:污染物片段须在同版、同物质、同值的已发布规则里找到完整版本;
    # 添加剂片段按 食品分类号+添加剂名 找面板行,看缺的是哪一格、趋势判没判。
    def chars(text):
        return set(re.sub(r"[\s、,，()（）\[\]［］]", "", text))
    quarantine = rd("quarantined_rows.csv")
    pol_q = [q for q in quarantine if q["standard"] == "GB 2762"]
    add_q = [q for q in quarantine if q["standard"] == "GB 2760"]
    for q in pol_q:
        assert any(r["version_year"] == q["version_year"] and r["analyte_zh"] == q["analyte_zh"]
                   and float(r["limit_value"]) == float(q["parsed_value"])
                   and chars(q["food_zh"]) <= chars(r["food_category_zh"]) for r in pol_long), q
    add_rows = {}
    for q in add_q:
        for r in rd("additive_panel.csv"):
            if r["food_code"] == q["food_code"] and q["additive_zh"] in r["additive_names_zh"]:
                assert r[f"status_{q['version_year']}"] == "missing"
                add_rows[r["record_id"]] = r["trend"]
    add_judged = sum(t in JUDGED for t in add_rows.values())

    # 认定的同物与包含关系以发布包验证器里冻结的常量为准。
    spec = importlib.util.spec_from_file_location("release_validate", os.path.join(REL, "validate.py"))
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    renames = len(validator.POLLUTANT_CONFIRMED_ALIASES)
    containment = len(validator.POLLUTANT_CONFIRMED_CONTAINMENT)

    pest = rd("pesticide_panel.csv")
    pest_judged = [r for r in pest if r["trend"] in JUDGED]
    pest_flagged = sum(1 for r in pest_judged if json.loads(r["count_mismatch_editions"]))
    t = trend

    rows = [
        ("Several rules for one entity, food and edition (a multi-value cell)",
         f"Pesticide and additive cells keep every candidate value, rule and source record "
         f"and leave the scalar value blank ({multi_pest} pesticide and {multi_add} additive "
         "cells). Contaminant category rows are keyed by analyte, category and basis, and no "
         "contaminant cell holds two rules. The veterinary-drug summary keeps printed animal "
         "groups; its member panel compares one animal at a time.",
         f"{tt('incomparable_multiple_rules')}: pesticide "
         f"{t['pesticide_panel.csv']['incomparable_multiple_rules']}, additive "
         f"{t['additive_panel.csv']['incomparable_multiple_rules']}, veterinary-drug member "
         f"{t['vetdrug_member_panel.csv']['incomparable_multiple_rules']}; "
         f"{tt('unresolved_multiple_animals')}: veterinary-drug summary "
         f"{t['vetdrug_panel.csv']['unresolved_multiple_animals']}"),
        ("Printed qualifier or basis of expression",
         f"A contaminant basis such as dry weight or solid product ({with_basis} long-table "
         "rows) is part of the category-row key, so rows on different bases are never "
         "compared; in the member panel a basis that changes across editions blocks the "
         "trend. Pesticide qualifiers, including the temporary-limit asterisk, enter the "
         "scope signature that must agree across editions.",
         f"{tt('incomparable_basis_unit_or_value')}: contaminant member "
         f"{t['pollutant_member_panel.csv']['incomparable_basis_unit_or_value']} (basis or "
         f"unit); {tt('incomparable_unresolved_review_or_source_qualifier')}: pesticide "
         f"{t['pesticide_panel.csv']['incomparable_unresolved_review_or_source_qualifier']} "
         "(source marker c)"),
        ("Units that cannot be converted",
         "Mass-per-mass units are converted before comparison. A volume-based value needs a "
         f"density and keeps a blank normalised value ({density} contaminant long-table "
         "rows). The additive grams-per-serving unit is not converted, and GMP is compared "
         "only with GMP.",
         f"{tt('incomparable_unit_dimension_or_value')}: contaminant category "
         f"{t['pollutant_category_panel.csv']['incomparable_unit_dimension_or_value']}; "
         f"{tt('incomparable_units')}: additive {t['additive_panel.csv']['incomparable_units']}; "
         f"{tt('stable_gmp')}: additive {t['additive_panel.csv']['stable_gmp']}"),
        ("Scope text that changes (exclusion list, food label, use condition, animals covered)",
         "Compared after Unicode and punctuation normalisation. Confirmed contaminant renames "
         "count as equal. Where a contaminant member heads its host category, that "
         "category's exclusions must also agree.",
         f"{tt('incomparable_scope_text')}: contaminant category "
         f"{t['pollutant_category_panel.csv']['incomparable_scope_text']} and member "
         f"{t['pollutant_member_panel.csv']['incomparable_scope_text']}, pesticide "
         f"{t['pesticide_panel.csv']['incomparable_scope_text']:,}, mycotoxin "
         f"{t['mycotoxin_panel.csv']['incomparable_scope_text']}, veterinary-drug summary "
         f"{t['vetdrug_panel.csv']['incomparable_scope_text']}, additive "
         f"{t['additive_panel.csv']['incomparable_scope_text']}"),
        ("Category without a counterpart in another edition",
         "A row present in one edition carries no trend. A contaminant category that is no "
         "longer printed is not read as withdrawn; its foods are followed in the member "
         "panel, which releases a member only when at least two editions have a "
         f"determinable host. {tt('coverage_status')} records when a printed name is present "
         "and does not date a limit.",
         f"{tt('single_version')}: contaminant "
         f"{t['pollutant_category_panel.csv']['single_version']}, pesticide "
         f"{t['pesticide_panel.csv']['single_version']}, mycotoxin "
         f"{t['mycotoxin_panel.csv']['single_version']}, additive "
         f"{t['additive_panel.csv']['single_version']}; {tt('single_version_unmatched')}: "
         f"mycotoxin member {t['mycotoxin_member_panel.csv']['single_version_unmatched']}; "
         f"{tt('single_2002_unmatched')} and {tt('single_2019_unmatched')}: veterinary-drug "
         f"summary {t['vetdrug_panel.csv']['single_2002_unmatched']} and "
         f"{t['vetdrug_panel.csv']['single_2019_unmatched']}; "
         f"{tt('incomparable_category_disappeared')}: contaminant category "
         f"{t['pollutant_category_panel.csv']['incomparable_category_disappeared']}"),
        ("Host category of a contaminant member not determinable",
         "The edition cell and its host are left blank, and note gives the reason: the "
         f"inherited rule excludes the member ({blanks['excluded']} cells), the member spans "
         f"two printed rules ({blanks['spans two printed rules']}), or another edition names "
         "the member in an exclusion list that differs from this rule's "
         f"({blanks['host not determinable']}). Manually confirmed renames ({renames}) and "
         f"containment links ({containment}) fix the host where the printed text does not.",
         f"Trend from the remaining editions; {noted} rows carry a note"),
        ("Quarantined fragment",
         f"Excluded from every long table and panel and kept in {tt('quarantined_rows.csv')}. "
         f"Each of the {len(pol_q)} contaminant fragments duplicates a released rule of the "
         f"same edition, analyte and value, so no contaminant cell is lost. The {len(add_q)} additive "
         f"fragments leave the 2011 or 2014 cell of {len(add_rows)} additive rows blank.",
         f"Trend from the editions present; {add_judged} of the {len(add_rows)} additive rows "
         "carry one. A blank cell is not read as absence"),
        ("Edition skipped between two editions that hold the rule",
         "No trend spans the gap.",
         f"{tt('incomparable_edition_gap')}: pesticide "
         f"{t['pesticide_panel.csv']['incomparable_edition_gap']}, additive "
         f"{t['additive_panel.csv']['incomparable_edition_gap']}, veterinary-drug member "
         f"{t['vetdrug_member_panel.csv']['incomparable_edition_gap']}"),
        ("Edition whose visible rule count differs from its declared total (GB 2763-2016 and "
         "GB 2763-2019)",
         f"Trends are kept, and {tt('count_mismatch_editions')} names the editions a trend "
         "relies on, so users can exclude them. The archived GB 2762-2005 and GB 2760-1996 "
         "editions were not extracted, and no panel spans them.",
         f"{pest_flagged:,} of {len(pest_judged):,} judged pesticide rows are flagged"),
    ]
    body = [("\\addlinespace " if i else "") + " & ".join(row) for i, row in enumerate(rows)]
    write_tab("tab1PanelRules", T5_SPEC, T5_CAP, T5_HEAD, body)


# ── Table 6 · 三条记录从源表追到面板 ──────────────────────────────
T6_SPEC = (r"@{}>{\raggedright\arraybackslash}p{0.09\textwidth}"
           r">{\raggedright\arraybackslash}p{0.27\textwidth}"
           r">{\raggedright\arraybackslash}p{0.27\textwidth}"
           r">{\raggedright\arraybackslash}p{0.27\textwidth}@{}")
T6_HEAD = ("Step & Comparable: acephate, tea & Unit changes: lead, concentrated juice & "
           "Quarantined: inorganic arsenic, rice")
T6_CAP = ("Three records traced from the source table to the panels: a comparable pesticide "
          "limit, a contaminant limit whose unit changes dimension, and a contaminant entry "
          "whose malformed duplicate was quarantined. Identifiers are released "
          "record\\_id values; page numbers refer to the PDF files in source\\_manifest.csv.")


def table6():
    def one(rows, **match):
        hits = [r for r in rows if all(r[k] == v for k, v in match.items())]
        assert len(hits) == 1, match
        return hits[0]

    pest_long = {r["record_id"]: r for r in rd("pesticide_limits_long.csv")}
    tea = one(rd("pesticide_panel.csv"), pesticide_zh="乙酰甲胺磷", food_zh="茶叶")
    years = YEARS["pesticide_panel.csv"]
    assert [tea[f"status_{y}"] for y in years] == ["single_rule"] * 6
    assert [tea[f"v{y}"] for y in years] == ["0.1"] * 4 + ["0.05"] * 2
    assert tea["trend"] == "tightened" and json.loads(tea["count_mismatch_editions"]) == ["2016", "2019"]
    tea_rows = {y: pest_long[json.loads(tea[f"source_record_ids_{y}"])[0]] for y in years}
    first, last = tea_rows["2012"], tea_rows["2026"]
    copies = [y for y in years
              if tea_rows[y]["edition_source_id"] != tea_rows[y]["extraction_source_id"]]
    assert copies == ["2019", "2021"]
    assert all(tea_rows[y]["verification_status"] == "confirmed_agreement" for y in copies)

    pol_long = {r["record_id"]: r for r in rd("pollutant_limits_long.csv")}
    cat = rd("pollutant_category_panel.csv")
    mem = rd("pollutant_member_panel.csv")
    pyears = YEARS["pollutant_category_panel.csv"]
    juice_c = one(cat, analyte_zh="铅", food_category_zh="浓缩果蔬汁")
    juice_m = one(mem, analyte_zh="铅", food_member_zh="浓缩果蔬汁(浆)")
    units = [juice_c[f"unit_{y}"] for y in pyears]
    assert units == [juice_m[f"unit_{y}"] for y in pyears] == ["mg/L", "mg/L", "mg/kg", "mg/kg"]
    assert {juice_c[f"v{y}"] for y in pyears} == {juice_m[f"v{y}"] for y in pyears} == {"0.5"}
    juice_long = [pol_long[json.loads(juice_c[f"source_record_ids_{y}"])[0]] for y in pyears]
    assert [r["normalization_status"] for r in juice_long] == (
        ["density_required"] * 2 + ["already_mg_per_kg"] * 2)
    assert all(r["limit_mgkg"] == "" for r in juice_long[:2])

    frag = one(rd("quarantined_rows.csv"), version_year="2017", analyte_zh="无机砷")
    rice_c = one(cat, analyte_zh="无机砷", food_category_zh="稻谷糙米大米")
    rice_2017 = pol_long[json.loads(rice_c["source_record_ids_2017"])[0]]
    assert rice_2017["food_category_zh"] == "稻谷、糙米、大米" and rice_2017["limit_value"] == "0.2"
    members = {name: one(mem, analyte_zh="无机砷", food_member_zh=name)
               for name in ("稻谷", "糙米", "大米")}
    assert all(json.loads(m["source_record_ids_2017"]) == [rice_2017["record_id"]]
               for m in members.values())
    assert rice_c["trend"] == "incomparable_category_disappeared"

    def rid(row):
        return f"\\texttt{{{row['record_id']}}}"

    rows = [
        ("Source table",
         f"GB 2763, acephate (section 4.{first['section_number']} in 2012, "
         f"4.{last['section_number']} in 2026): tea {first['limit_value']} mg/kg in 2012--2019 "
         f"and {last['limit_value']} mg/kg in 2021 and 2026 (PDF p. {first['source_page']} in "
         f"2012, p. {last['source_page']} in 2026).",
         "GB 2762, Table 1 (lead), p. 5: concentrated fruit and vegetable juice (pulp) 0.5 mg/L "
         "in 2012 and 2017; 0.5 under the table's mg/kg header in 2022 and 2025.",
         "GB 2762-2017, Table 4 (arsenic), p. 9: paddy, brown rice and milled rice, inorganic "
         "arsenic 0.2 mg/kg, with a footnote marker after paddy."),
        ("Long table",
         f"Six rows, one per edition, sharing \\texttt{{{tea['pesticide_key']}}} and "
         f"\\texttt{{{tea['food_key']}}}, e.g. {rid(last)} (2026; source page "
         f"{last['source_page']}, y = {float(last['source_y']):.1f}). The 2019 and 2021 rows "
         "come from the text-layer extraction copies and agree with the OCR cross-check of "
         "the scans.",
         f"Four rows. The 2012 and 2017 rows keep unit mg/L, "
         f"{tt('normalization_status')} {tt('density_required')} and a blank "
         f"{tt('limit_mgkg')}; the 2022 and 2025 rows are already in mg/kg.",
         f"The coordinate parser releases {rid(rice_2017)}. A second, line-based reading of "
         "the same entry began with a separator; the bracket-structure gate moved it to "
         f"{tt('quarantined_rows.csv')} as {rid(frag)}."),
        ("Panel",
         f"{tt('pesticide_panel.csv')} {rid(tea)}: {tt('single_rule')} in all six editions; "
         f"{tt('source_record_ids_YYYY')} returns each cell to its long-table row.",
         f"Category row {rid(juice_c)} and member row {rid(juice_m)} hold 0.5 in all four "
         "editions, with units mg/L, mg/L, mg/kg and mg/kg.",
         f"The released row fills the 2017 cell of category row {rid(rice_c)} and of the "
         "paddy, brown-rice and milled-rice member rows. The fragment enters no panel, so no "
         "cell is lost."),
        ("Trend",
         f"{tt('tightened')}. {tt('count_mismatch_editions')} lists 2016 and 2019, whose "
         "visible rule counts differ from the declared totals; the trend is kept and flagged.",
         f"{tt('incomparable_unit_dimension_or_value')} for the category and "
         f"{tt('incomparable_basis_unit_or_value')} for the member. Equal digits are not "
         "read as stable.",
         f"{tt('incomparable_category_disappeared')} for the category row, which is not "
         "printed after 2017; the member rows follow the split "
         "(Table~\\ref{tab1Restructuring})."),
    ]
    body = [("\\addlinespace " if i else "") + " & ".join(row) for i, row in enumerate(rows)]
    write_tab("tab1TraceExamples", T6_SPEC, T6_CAP, T6_HEAD, body)


# ── Table 7 · 类别拆分、并入、缩小、改名 ──────────────────────────
T7_SPEC = (r"@{}>{\raggedright\arraybackslash}p{0.24\textwidth}"
           r">{\raggedright\arraybackslash}p{0.10\textwidth}"
           r">{\raggedright\arraybackslash}p{0.10\textwidth}"
           r">{\raggedright\arraybackslash}p{0.10\textwidth}"
           r">{\raggedright\arraybackslash}p{0.10\textwidth}"
           r">{\raggedright\arraybackslash}p{0.22\textwidth}@{}")
T7_HEAD = "Member & 2012 & 2017 & 2022 & 2025 & Member trend"
T7_CAP = ("Category restructuring in the contaminant member panel. Each cell gives the value "
          "and, by letter, the printed category that hosts the member in that edition. A "
          "member takes its own printed rule or the rule of the first ancestor category that "
          "has a value and does not exclude it. A cell is blank when that rule excludes the "
          "member, when the member spans two printed rules, or when the host cannot be "
          "determined, and note records the reason. Renames and containment links that the "
          "printed text does not establish were confirmed against the source pages before "
          "use.")
HOST_EN = {
    "稻谷、糙米、大米": "paddy, brown rice, milled rice",
    "稻谷": "paddy",
    "糙米": "brown rice",
    "大米(粉)": "milled rice (flour)",
    "乳粉、非脱盐乳清粉": "milk powder, non-demineralised whey powder",
    "乳及乳制品(生乳、巴氏杀菌乳、灭菌乳、调制乳、发酵乳除外)":
        "milk and dairy products, excluding raw, pasteurised, sterilised, modified and "
        "fermented milk",
    "蒸馏酒、黄酒": "distilled spirits, yellow wine",
    "白酒、黄酒": "baijiu, yellow wine",
    "酒类(蒸馏酒、黄酒除外)": "alcoholic beverages, excluding distilled spirits and yellow wine",
    "酒类(白酒、黄酒除外)": "alcoholic beverages, excluding baijiu and yellow wine",
    "矿泉水": "mineral water",
    "饮用天然矿泉水": "natural mineral drinking water",
}
RESTRUCTURING = [
    ("Split", "inorganic arsenic", "无机砷", "mg/kg",
     [("稻谷", "Paddy"), ("糙米", "Brown rice"), ("大米", "Milled rice")]),
    ("Absorbed", "lead", "铅", "mg/kg", [("乳粉", "Milk powder")]),
    ("Narrowed", "lead", "铅", "mg/kg",
     [("白酒", "Baijiu"), ("蒸馏酒", "Distilled spirits"),
      ("酒类", "Alcoholic beverages (residual class)")]),
    ("Renamed", "cadmium", "镉", "mg/L", [("饮用天然矿泉水", "Natural mineral drinking water")]),
]


def table7():
    import unicodedata

    mem = rd("pollutant_member_panel.csv")
    cat = rd("pollutant_category_panel.csv")
    years = YEARS["pollutant_member_panel.csv"]
    letters = OrderedDict()

    def letter(host):
        host = unicodedata.normalize("NFKC", host)
        assert host in HOST_EN, host
        if host not in letters:
            letters[host] = chr(ord("A") + len(letters))
        return letters[host]

    def cat_row(analyte, name):
        hits = [r for r in cat if r["analyte_zh"] == analyte and r["food_category_zh"] == name]
        assert len(hits) == 1, (analyte, name)
        return hits[0]

    body, rows = [], {}
    for kind, analyte_en, analyte, unit, members in RESTRUCTURING:
        block = []
        for name, label in members:
            (row,) = [r for r in mem if r["analyte_zh"] == analyte and r["food_member_zh"] == name]
            rows[(analyte, name)] = row
            cells = []
            for y in years:
                if row[f"v{y}"]:
                    assert row[f"unit_{y}"] == unit
                    cells.append(f"{row[f'v{y}']} ({letter(row[f'host_category_{y}'])})")
                else:
                    assert y in row["note"]
                    cells.append("blank")
            block.append(f"{label}\\newline {{\\footnotesize\\texttt{{{row['record_id']}}}}} & "
                         + " & ".join(cells) + f" & {tt(row['trend'])}")
        used = sorted({letters[unicodedata.normalize("NFKC", r[f'host_category_{y}'])]
                       for (a, n), r in rows.items() if a == analyte
                       and n in dict(members) for y in years if r[f'host_category_{y}']})
        legend = "; ".join(f"{k}: {HOST_EN[h]}" for h, k in letters.items() if k in used)
        body.append(f"\\addlinespace \\multicolumn{{6}}{{@{{}}p{{0.92\\textwidth}}}}"
                    f"{{\\emph{{{kind}: {analyte_en}, {unit}.}} {legend}.}}")
        body += block
        body.append(f"\\multicolumn{{6}}{{@{{}}p{{0.92\\textwidth}}}}{{{CAT_LINE[kind](cat_row)}}}")
    write_tab("tab1Restructuring", T7_SPEC, T7_CAP, T7_HEAD, body)

    # 正文所述的事实,数据变了就报错。
    assert [rows[("无机砷", n)]["trend"] for n in ("稻谷", "糙米", "大米")] == [
        "relaxed", "relaxed", "stable"]
    assert rows[("铅", "乳粉")]["trend"] == "tightened"
    assert [rows[("铅", n)]["trend"] for n in ("白酒", "蒸馏酒", "酒类")] == [
        "stable", "stable", "incomparable_scope_text"]
    assert "spans two printed rules" in rows[("铅", "蒸馏酒")]["note"]


def _split_line(cat_row):
    shared = cat_row("无机砷", "稻谷糙米大米")
    later = [cat_row("无机砷", n) for n in ("稻谷", "糙米", "大米")]
    assert shared["trend"] == "incomparable_category_disappeared"
    assert all(r["trend"] == "stable" and r["coverage_status"] == "introduced_2022" for r in later)
    return ("Category panel: A is not printed after 2017 "
            f"({tt('incomparable_category_disappeared')}); B, C and D start in 2022 "
            f"({tt('stable')}). Milled rice reaches D through a confirmed containment link.")


def _absorbed_line(cat_row):
    old = cat_row("铅", "乳粉非脱盐乳清粉")
    dairy = cat_row("铅", "乳及乳制品")
    assert old["trend"] == "incomparable_category_disappeared"
    assert dairy["v2017"] == "0.3" and "乳粉" in dairy["source_category_2017"]
    assert dairy["trend"] == "incomparable_scope_text"
    return ("Category panel: E is not printed after 2017. The milk and dairy products class "
            "is printed from 2017; in 2017 its exclusions still name milk powder and its value "
            f"is 0.3, so its category row is {tt('incomparable_scope_text')}.")


def _narrowed_line(cat_row):
    old = cat_row("铅", "蒸馏酒黄酒")
    new = cat_row("铅", "白酒黄酒")
    rest = cat_row("铅", "酒类")
    assert old["trend"] == "incomparable_category_disappeared" and new["trend"] == "stable"
    assert rest["trend"] == "incomparable_scope_text"
    return ("Baijiu reaches G through a confirmed containment link. From 2022 distilled "
            "spirits spans H and J, so its cells are blank and note gives the reason; the "
            "residual class keeps 0.2 while its exclusions change.")


def _renamed_line(cat_row):
    row = cat_row("镉", "饮用天然矿泉水")
    assert row["n_versions"] == "4" and row["trend"] == "stable"
    return (f"The confirmed rename merges K and L into one category row, "
            f"\\texttt{{{row['record_id']}}} ({tt('stable')}).")


CAT_LINE = {"Split": _split_line, "Absorbed": _absorbed_line, "Narrowed": _narrowed_line,
            "Renamed": _renamed_line}


# ── 冻结核验证据(Data/Interim 下入 git 的三处) ────────────
INTERIM = os.path.join(PROJ, "Data", "Interim")
AUDIT_ONE = os.path.join(INTERIM, "pesticide_audit")
AUDIT_TWO = os.path.join(INTERIM, "pesticide_audit_round2")
REENTRY = os.path.join(INTERIM, "manual_reentry", "reconciliation")


def rd_path(path):
    with open(path, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def audit_rates(folder):
    path = os.path.join(folder, "comparison", "pesticide_audit_rates.csv")
    return {(r["edition"], r["stratum"]): r for r in rd_path(path)}


def audit_rows(folder):
    return rd_path(os.path.join(folder, "comparison", "pesticide_audit_comparison.csv"))


def reentry_report(stage):
    with open(os.path.join(REENTRY, stage, "blind_reentry_report.json"), encoding="utf-8") as fh:
        return json.load(fh)


def zero_error_upper(n):
    """0/n 的 Clopper–Pearson 95% 上界(闭式)。"""
    return 1 - 0.025 ** (1 / n)


def pct(share):
    """比例 → 一位小数的百分数,四舍五入(6.25 → 6.3)。"""
    return str((Decimal(str(share)) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ── Table 8 · 农残两版独立核验 ────────────────────────────────────
T8_SPEC = (r"@{}>{\raggedright\arraybackslash}p{0.21\textwidth}"
           r">{\raggedleft\arraybackslash}p{0.08\textwidth}"
           r">{\raggedleft\arraybackslash}p{0.11\textwidth}"
           r">{\raggedleft\arraybackslash}p{0.18\textwidth}"
           r">{\raggedleft\arraybackslash}p{0.11\textwidth}"
           r">{\raggedleft\arraybackslash}p{0.14\textwidth}@{}")
T8_HEAD = ("Stratum & Rows & Round 1 errors / read & Round 1 rate, \\% (95\\% CI) & "
           "v1.1 errors / read & v1.1 upper 95\\% bound, \\%")
STRATA = (("2019", "consistent", "2019, OCR agrees"),
          ("2019", "text_only", "2019, text layer only"),
          ("2021", "consistent", "2021, OCR agrees"),
          ("2021", "text_only", "2021, text layer only"))
T8_CAP = ("Independent reading of the GB 2763-2019 and GB 2763-2021 rows against the "
          "issuing-authority scans. Rows are stratified by edition and by whether the OCR "
          "comparison recovered the row (OCR agrees) or not (text layer only). Within a "
          "stratum, rows were drawn in proportion to stratum size by ranking a seeded SHA-256 "
          "digest of the record identifier. Round 1 read release v1.0: its errors are seven "
          "foods filed under a long food label instead of their category and one "
          "temporary-limit asterisk printed in the text-layer copy but not on the scan; two "
          "reviewer misreadings are not counted. After the category rule was corrected in all "
          "six editions, round 2 redrew the three strata with errors at the same sizes, "
          "skipping rows already read. The v1.1 columns combine round 2 with the round-1 rows "
          "of the stratum that was not redrawn; every row counted there is unchanged in "
          "release v1.1. Intervals are Clopper--Pearson. The nine OCR conflict rows and three "
          "OCR-only groups were read in full and are reported in the text.")


def v11_rows_unchanged(read_rows):
    """读过的行在 v1.1 里记录号、类别、数值都没变,才能算作 v1.1 的核验。"""
    released = {r["record_id"]: r for r in rd("pesticide_limits_long.csv")}
    for row in read_rows:
        now = released.get(row["record_id"])
        if now is None or (now["parent_category_zh"], now["limit_value"]) != (
                row["parent_category_zh"], row["released_limit_value"]):
            raise ValueError(f"核验读过的行在 v1.1 里变了:{row['blind_id']}")


def table8():
    one, two = audit_rates(AUDIT_ONE), audit_rates(AUDIT_TWO)
    carried = [r for r in audit_rows(AUDIT_ONE)
               if (r["edition"], r["stratum"]) in set(one) - set(two)]
    v11_unread = [r for r in audit_rows(AUDIT_TWO) + carried if r["outcome"] != "agree"]
    if v11_unread:
        raise ValueError("v1.1 列只收一致的行")
    v11_rows_unchanged(audit_rows(AUDIT_TWO) + carried)
    body, v11_read = [], 0
    for edition, stratum, label in STRATA:
        r1 = one[(edition, stratum)]
        # 第一轮零错的层不重抽,沿用第一轮读过的行(上面已核过在 v1.1 里没变)。
        r2 = two.get((edition, stratum), r1)
        v11_read += int(r2["compared"])
        body.append(f"{label} & {int(r1['population_rows']):,} & {r1['errors']} / "
                    f"{r1['compared']} & {pct(r1['error_rate'])} ({pct(r1['ci95_low'])}--"
                    f"{pct(r1['ci95_high'])}) & {r2['errors']} / {r2['compared']} & "
                    f"{pct(r2['ci95_high'])}")
    total = one[("2019+2021", "random")]
    body.append(f"\\addlinespace All four strata & {int(total['population_rows']):,} & "
                f"{total['errors']} / {total['compared']} & {pct(total['error_rate'])} "
                f"({pct(total['ci95_low'])}--{pct(total['ci95_high'])}) & 0 / {v11_read} & "
                f"{pct(zero_error_upper(v11_read))}")
    write_tab("tab1IndependentVerification", T8_SPEC, T8_CAP, T8_HEAD, body)
    return v11_read


# ── Table 9 · 跨发布版本连接用的自然键 ────────────────────────────
T9_SPEC = (r"@{}>{\raggedright\arraybackslash}p{0.15\textwidth}"
           r">{\raggedright\arraybackslash}p{0.30\textwidth}"
           r">{\raggedright\arraybackslash}p{0.21\textwidth}"
           r">{\raggedright\arraybackslash}p{0.21\textwidth}@{}")
T9_HEAD = "Family & Long table & Panel & Member panel"
KEY_TABLES = (("contaminant", "pollutant_limits_long.csv", "pollutant_category_panel.csv",
               "pollutant_member_panel.csv"),
              ("pesticide", "pesticide_limits_long.csv", "pesticide_panel.csv", None),
              ("mycotoxin", "mycotoxin_limits_long.csv", "mycotoxin_panel.csv",
               "mycotoxin_member_panel.csv"),
              ("veterinary_drug", "vetdrug_limits_long.csv", "vetdrug_panel.csv",
               "vetdrug_member_panel.csv"),
              ("additive", "additive_limits_long.csv", "additive_panel.csv", None))


def readme_keys():
    """README「Natural key」表:文件 → 键列(分号后的说明不算键)。"""
    keys, inside = {}, False
    with open(os.path.join(REL, "README.md"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("| Table | Natural key |"):
                inside = True
            elif inside and not line.startswith("|"):
                break
            elif inside and line.startswith("| `"):
                name, key = (c.strip() for c in line.strip().strip("|").split("|"))
                keys[name.strip("`")] = re.findall(r"`([a-z_]+)`", key.split(";")[0])
    return keys


def table9():
    keys = readme_keys()
    for r in rd("record_id_changes.csv"):
        if r["table"] in keys and list(json.loads(r["natural_key"])) != keys[r["table"]]:
            raise ValueError(f"README natural key differs from record_id_changes for {r['table']}")
    repeated = {}
    for name in keys:
        counts = Counter(tuple(r[c] for c in keys[name]) for r in rd(name))
        shared = {k: n for k, n in counts.items() if n > 1}
        if shared:
            repeated[name] = (sum(shared.values()), len(shared))
    if set(repeated) != {"additive_limits_long.csv", "pollutant_category_panel.csv"}:
        raise ValueError(f"natural keys repeat in an undocumented table: {sorted(repeated)}")
    add_rows, add_keys = repeated["additive_limits_long.csv"]
    cat_pairs = repeated["pollutant_category_panel.csv"][1]
    caption = ("Natural keys for joining records across releases. Within a release, "
               "\\texttt{record\\_id} links panels to long tables; across releases it stays the "
               "same only while the fields it digests are unchanged, and these keys identify the "
               "same printed entry or aligned group instead. \\texttt{record\\_id\\_changes.csv} "
               "pairs the identifiers of releases v1.0 and v1.1 on the same keys. In the pesticide "
               "long table, \\texttt{pesticide\\_key} and \\texttt{food\\_key} group rules across "
               f"editions. Each key is unique within the release, except that {add_rows} additive "
               f"long-table rows share {add_keys} code pairs, each carrying several printed rules "
               f"in one edition, and {cat_pairs} contaminant category-panel pairs appear once for "
               "each basis of expression.")

    def cell(name):
        return ", ".join(f"\\path{{{c}}}" for c in keys[name]) if name else "--"
    body = [f"{FAMILY_LABEL[family]} & {cell(long)} & {cell(panel)} & {cell(member)}"
            for family, long, panel, member in KEY_TABLES]
    write_tab("tab1NaturalKeys", T9_SPEC, caption, T9_HEAD, body)


# ── 正文数字宏 ────────────────────────────────────────────────────
def numbers(validation_report, audit_v11_rows):
    """正文引用的发布包计数与核验结果 → DatapaperNumbers.tex。"""
    rows = [r for f, _ in DEPOSIT_INVENTORY["Family-specific long tables"] for r in rd(f)]
    status = Counter(r["verification_status"] for r in rows)
    # source_reference 是「标准号-版本; [页码或表行;] 网址」,三段的才定位到页或表行。
    located = sum(len(r["source_reference"].split("; ")) == 3 for r in rows)
    with open(validation_report, encoding="utf-8") as handle:
        layers = json.load(handle)["layers"]
    # _build_stats.json 每个构建产出的 CSV 一项;其余 CSV 在构建后另写。
    with open(os.path.join(REL, "_build_stats.json"), encoding="utf-8") as handle:
        built = len(json.load(handle))
    pesticide = rd("pesticide_limits_long.csv")
    scanned = [r for r in pesticide if r["version_year"] in ("2019", "2021")]
    scanned_confirmed = sum(r["verification_status"] == "confirmed_agreement" for r in scanned)
    audit_read = sum("independent_audit_reading" in r["verification_basis"] for r in rows)
    methods = Counter(r["extraction_method"] for r in rows)

    initial, adjudicated, attested = (reentry_report(s) for s in
                                      ("01_initial", "02_adjudicated", "04_attested"))
    first = audit_rows(AUDIT_ONE)
    rate = audit_rates(AUDIT_ONE)[("2019+2021", "random")]
    verdicts = Counter(r["verdict"] for r in first if r["selection"] == "proportional_random")
    conflicts = [r for r in first if r["stratum"] == "conflict"]
    ocr_only = [r for r in first if r["stratum"] == "ocr_only"]
    assert all(r["outcome"] == "agree" for r in conflicts)
    assert all(r["outcome"] == "omission_not_confirmed" for r in ocr_only)
    second = audit_rates(AUDIT_TWO)[("2019+2021", "random")]
    corrected = rd_path(os.path.join(AUDIT_TWO, "category_corrections.csv"))

    values = OrderedDict([
        ("ReleaseCsvFiles", len(list(Path(REL).glob("*.csv")))),
        ("ReleaseBuiltCsvFiles", built),
        ("ReleaseSourceLocated", located),
        ("ReleaseSourceEditionOnly", len(rows) - located),
        ("ReleaseVerifiedAgreement", status["confirmed_agreement"]),
        ("ReleaseVerifiedDisagreement", status["unresolved_disagreement"]),
        ("ReleaseVerifiedNone", status["no_cross_source_comparison"]),
        ("ReleaseVerifiedNoneShare", pct(status["no_cross_source_comparison"] / len(rows))),
        ("ReleaseIdChanges", csv_rows("record_id_changes.csv")),
        ("MethodCoordinateShare", pct(methods["pdf_text_and_coordinate_parser"] / len(rows))),
        ("MethodTextShare", pct(methods["pdf_text_layer"] / len(rows))),
        ("MethodWordShare", pct(methods["word_table_stream"] / len(rows))),
        ("MethodManualRecords", methods["manual_page_image_transcription"]),
        ("MethodManualShare", pct(methods["manual_page_image_transcription"] / len(rows))),
        ("ValidationChecks", sum(len(layer) for layer in layers.values())),
        ("ValidationSelfContained", len(layers["self_contained"])),
        ("ValidationSourceDependent", len(layers["source_dependent"])),
        ("ScanEditionRows", len(scanned)),
        ("ScanEditionShareRelease", pct(len(scanned) / len(rows))),
        ("ScanEditionSharePesticide", pct(len(scanned) / len(pesticide))),
        ("ScanEditionConfirmed", scanned_confirmed),
        ("ScanEditionConfirmedShare", pct(scanned_confirmed / len(scanned))),
        ("AuditReadRows", audit_read),
        ("ReentryRecords", attested["scope"]["records"]),
        ("ReentryFields", attested["scope"]["fields"]),
        ("ReentryExact", initial["comparison_counts"]["exact_match"]),
        ("ReentryNormalised", initial["comparison_counts"]["normalised_match"]),
        ("ReentryDisagree", initial["comparison_counts"]["disagreement"]),
        ("ReentryMissing", initial["comparison_counts"]["missing"]),
        ("ReentryFormatting", adjudicated["adjudication_counts"]["construction_confirmed"]),
        ("ReentryCorrected", adjudicated["adjudication_counts"]["reentry_confirmed"]),
        ("ReentryUnresolved", attested["adjudication_counts"]["unresolved"]),
        ("AuditOneRows", int(rate["compared"])),
        ("AuditOneAgree", int(rate["compared"]) - int(rate["discrepancies"])),
        ("AuditOneMisreadings", verdicts["reviewer_misreading"]),
        ("AuditOneErrors", int(rate["errors"])),
        ("AuditOneCategoryErrors", verdicts["extraction_error"]),
        ("AuditOneAsteriskErrors", verdicts["text_layer_error"]),
        ("AuditOneRate", pct(rate["error_rate"])),
        ("AuditOneLow", pct(rate["ci95_low"])),
        ("AuditOneHigh", pct(rate["ci95_high"])),
        ("AuditConflictRows", len(conflicts)),
        ("AuditOcrOnlyGroups", len(ocr_only)),
        ("AuditTwoRows", int(second["compared"])),
        ("AuditTwoErrors", int(second["errors"])),
        ("AuditTwoUpper", pct(second["ci95_high"])),
        ("AuditReleaseRows", audit_v11_rows),
        ("AuditReleaseUpper", pct(zero_error_upper(audit_v11_rows))),
        ("CategoryCorrections", len(corrected)),
        ("CategoryCorrectionShare", pct(len(corrected) / len(pesticide))),
        ("AsteriskCorrections", sum("scan_temporary_mark_correction" in r["review_status"]
                                    for r in pesticide)),
    ])
    lines = ["% Generated by Program/Analysis/DatapaperTables.py; do not edit."]
    lines += [f"\\newcommand{{\\{name}}}{{{n:,}}}" if isinstance(n, int)
              else f"\\newcommand{{\\{name}}}{{{n}}}" for name, n in values.items()]
    with open(os.path.join(OUT, "DatapaperNumbers.tex"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote DatapaperNumbers.tex ({len(values)} macros)")


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
    table5()
    table6()
    table7()
    table9()
    numbers(args.validation_report, table8())
    print("tables →", OUT)
