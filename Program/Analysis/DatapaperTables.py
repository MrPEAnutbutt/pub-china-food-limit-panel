#!/usr/bin/env python3
"""九张稿件表 —— 从 Data/Final 生成 Results/tab/tab1<Name>.tex(longtable, 约定命名)。

脚本直接读取本工程 Data/Final 真源，输出供 main-en.tex ``\\input`` 的
LaTeX longtable。历史 markdown 生成器已停用，避免维护两套稿件结果接口。
独立核验结果表和核验宏另读入 git 的冻结核验证据(Data/Interim 下三处),
农残两版条数对账的译本核对另读入 git 的冻结提取报告。
label = 文件名主干、无下划线(tab1AlignmentFailures / tab1ExtractionMethod /
tab1FileInventory / tab1ValidationMetrics / tab1PanelRules / tab1TraceExamples /
tab1Restructuring / tab1IndependentVerification / tab1NaturalKeys)。
表里的 → 与 μ 走 main-en.tex 的 \\newunicodechar 渲染;**加粗** 由 bold() 转 \\textbf{}。
另写 Results/tab/DatapaperNumbers.tex:正文引用的发布包计数宏(宏名只用字母)。
"""
import argparse
import csv
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
T2_SPEC = (r"@{}>{\raggedright\arraybackslash}p{0.19\textwidth}"
           r">{\raggedright\arraybackslash}p{0.08\textwidth}"
           r">{\raggedleft\arraybackslash}p{0.09\textwidth}"
           r">{\raggedleft\arraybackslash}p{0.12\textwidth}"
           r">{\raggedleft\arraybackslash}p{0.12\textwidth}"
           r">{\raggedleft\arraybackslash}p{0.12\textwidth}"
           r">{\raggedleft\arraybackslash}p{0.12\textwidth}@{}")
T2_CAP = ("Released records by edition and extraction method. Each count is the number of "
          "long-table rows with that value of \\texttt{extraction\\_method}; in column order the "
          "values are \\texttt{pdf\\_text\\_and\\_coordinate\\_parser}, \\texttt{pdf\\_text\\_layer}, "
          "\\texttt{word\\_table\\_stream} and \\texttt{manual\\_page\\_image\\_transcription}. The "
          "coordinate parser assigns rows and columns from word positions in the PDF text layer. "
          "The last rows total each method and give its share of all released records. The same "
          "counts, with shares within each family, are released in "
          "\\texttt{extraction\\_method\\_summary.csv}. "
          "\\textsuperscript{a}Read from a government-hosted copy; OCR of the edition scan, an "
          "audit-only copy, served only as a cross-check. "
          "\\textsuperscript{b}The text layer is corrupt. "
          "\\textsuperscript{c}Rows at page breaks.")
T2_HEAD = ("Standard & Version & Records & Coordinate parser & Text layer & Word table & "
           "Page image (manual)")
METHODS = ("pdf_text_and_coordinate_parser", "pdf_text_layer", "word_table_stream",
           "manual_page_image_transcription")
LONG_TABLE = OrderedDict([("contaminant", "pollutant_limits_long.csv"),
                          ("pesticide", "pesticide_limits_long.csv"),
                          ("mycotoxin", "mycotoxin_limits_long.csv"),
                          ("veterinary_drug", "vetdrug_limits_long.csv"),
                          ("additive", "additive_limits_long.csv")])
FAMILY_LABEL = {"contaminant": "Contaminants", "pesticide": "Pesticide residues",
                "mycotoxin": "Mycotoxins", "veterinary_drug": "Veterinary drug residues",
                "additive": "Food additives"}
STANDARD_LABEL = {"MOA Announcement 235": "Announcement No.~235"}
# 计数格上的表注标记(a/b/c 的含义写在 T2_CAP 末尾)。
METHOD_NOTE = {
    ("pesticide", "2019", "pdf_text_and_coordinate_parser"): "a",
    ("pesticide", "2021", "pdf_text_and_coordinate_parser"): "a",
    ("mycotoxin", "2005", "manual_page_image_transcription"): "b",
    ("veterinary_drug", "2019", "manual_page_image_transcription"): "c",
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
    if {method for _, _, method in counted} != set(METHODS):
        raise ValueError("extraction methods differ from the four table columns")
    # 每版一行、每种方法一列;前三格(标准、年份、该版记录数)是验证器解析的格式,不能动。
    editions = OrderedDict()
    for r in summary:
        if share(r["records"], total) != r["share_of_release_pct"]:
            raise ValueError(f"share of release differs for {r}")
        key = (r["family"], r["standard"], r["version_year"])
        editions.setdefault(key, {})[r["extraction_method"]] = int(r["records"])
    body, previous = [], None
    for (family, standard, year), by_method in editions.items():
        if family != previous:
            previous = family
            body.append(f"\\addlinespace \\multicolumn{{7}}{{@{{}}l}}"
                        f"{{\\emph{{{FAMILY_LABEL[family]}}}}}")
        cells = []
        for method in METHODS:
            n = by_method.get(method)
            mark = METHOD_NOTE.get((family, year, method))
            cells.append("" if n is None else f"{n:,}"
                         + (f"\\textsuperscript{{{mark}}}" if mark else ""))
        body.append(f"{STANDARD_LABEL.get(standard, standard)} & {year} & "
                    f"{sum(by_method.values()):,} & " + " & ".join(cells))
    methods = Counter()
    for (_, _, method), n in counted.items():
        methods[method] += n
    body.append("\\midrule All editions & & " + f"{total:,} & "
                + " & ".join(f"{methods[m]:,}" for m in METHODS))
    body.append("Share of release, \\% & & 100.00 & "
                + " & ".join(share(methods[m], total) for m in METHODS))
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
    "every eligible row. Its rate uses the decidable subset, and a parenthetical "
    "eligible count is shown when the two denominators differ. The shuffled "
    "column gives the value-permuted control. A traceback pass also requires "
    "at least 30 decidable rows and an observed-minus-shuffled gap of at least "
    "25 percentage points. Entity coverage compares "
    "the released unique-entity count with independently countable source-entry "
    "markers."
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
T4_SPEC = (r"@{}>{\raggedright\arraybackslash}p{0.37\textwidth}"
           r">{\raggedleft\arraybackslash}p{0.07\textwidth}"
           r">{\raggedright\arraybackslash}p{0.48\textwidth}@{}")
T4_HEAD = "File & Rows & Contents"

# 组 → [(文件名, 说明)]。行数一律从发布文件现数,不写死;文件集合与 Data/Final
# 不符即报错,避免稿件清单与发布包分家(README 行数过期的老病)。
DEPOSIT_INVENTORY = OrderedDict([
    ("Family-specific long tables", [
        ("pollutant_limits_long.csv", "Contaminant limits with basis and units."),
        ("pesticide_limits_long.csv", "Pesticide limits with qualifiers, keys and pages."),
        ("mycotoxin_limits_long.csv", "Mycotoxin limits with a confidence field."),
        ("vetdrug_limits_long.csv", "Veterinary-drug limits with animal labels."),
        ("additive_limits_long.csv", "Additive uses with CNS, INS and food codes."),
    ]),
    ("Aligned category panels", [
        ("pollutant_category_panel.csv", "Contaminant values by edition, units and bases."),
        ("pesticide_panel.csv", "Pesticide cells with every candidate rule."),
        ("mycotoxin_panel.csv", "Mycotoxin values by edition."),
        ("vetdrug_panel.csv", "Veterinary-drug values by printed animal group."),
        ("additive_panel.csv", "Additive cells by CNS and food code."),
    ]),
    ("Member-level panels", [
        ("pollutant_member_panel.csv", "Contaminant members with host by edition."),
        ("mycotoxin_member_panel.csv", "Mycotoxin members with host by edition."),
        ("vetdrug_member_panel.csv", "Animal--tissue pairs with values and trend."),
    ]),
    ("English-name lookups", [
        ("entity_names_en.csv", "Substance names printed in English."),
        ("food_category_names_en.csv", "Category labels from translations; partial."),
        ("additive_names_en.csv", "Additive names from a translation; partial."),
    ]),
    ("Metadata, audit and quarantine", [
        ("source_manifest.csv", "Identity, digest and class of each source file."),
        ("extraction_method_summary.csv", "Records by family, edition and method."),
        ("record_id_changes.csv", "Identifiers changed since release v1.0."),
        ("version_dates.csv", "Dates, their provenance and register check."),
        ("standard_version_timeline.csv", "Wider history of food-safety standards."),
        ("standard_timeline_conflicts.csv", "Candidates for one timeline conflict."),
        ("pesticide_edition_reconciliation.csv", "Visible against declared rule counts."),
        ("pesticide_ocr_crosscheck.csv", "OCR comparison groups for 2019 and 2021."),
        ("quarantined_rows.csv", "Rejected fragments with the reason."),
        ("data_dictionary.csv", "Definition of every released field."),
    ]),
])

# 非 CSV 存放物。行数列留 ---(不是表格)。
NON_CSV_FILES = [
    ("README.md", "Package overview and file list."),
    ("LICENSE.md", "CC BY 4.0 terms and source rights."),
    ("SOURCE_ACQUISITION.md", "Where to obtain each source file."),
    ("_build_stats.json", "Deterministic build statistics."),
    ("validate.py", "The validation suite."),
    ("validation_report.json", "Status and evidence for every check."),
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
        f"Inventory of the data deposit, {len(listed)} CSV files and "
        f"{len(NON_CSV_FILES)} documentation and code files in a flat directory. Row "
        "counts exclude the header row and are read from the released files. The five "
        f"long tables hold the {long_total:,} released limit records. The panels, "
        "lookups and audit tables are derived from those records and are not "
        "additional limits. All file digests in the deposit and the code archive are "
        "SHA-256."
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
T5_SPEC = (r"@{}>{\raggedright\arraybackslash}p{0.20\textwidth}"
           r">{\raggedright\arraybackslash}p{0.40\textwidth}"
           r">{\raggedright\arraybackslash}p{0.32\textwidth}@{}")
T5_HEAD = "Condition kept in the long tables & Treatment in the panels & Trend state (panel rows)"
T5_CAP = ("How conditions kept in the long tables carry into the panels. Counts are panel "
          "rows in release v1.1 unless stated otherwise.")
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

    t = trend

    rows = [
        ("Several rules in one cell (entity, food and edition)",
         f"Pesticide and additive cells keep every candidate rule, with the scalar value blank "
         f"({multi_pest} and {multi_add} cells). Contaminant rows are keyed by analyte, category "
         "and basis, so none holds two rules.",
         f"{tt('incomparable_multiple_rules')}: pesticide "
         f"{t['pesticide_panel.csv']['incomparable_multiple_rules']}, additive "
         f"{t['additive_panel.csv']['incomparable_multiple_rules']}, veterinary-drug member "
         f"{t['vetdrug_member_panel.csv']['incomparable_multiple_rules']}. "
         f"{tt('unresolved_multiple_animals')}: veterinary-drug summary "
         f"{t['vetdrug_panel.csv']['unresolved_multiple_animals']}"),
        ("Qualifier or basis of expression",
         f"A contaminant basis such as dry weight ({with_basis} long-table rows) is part of the "
         "row key and blocks a member trend when it changes. Pesticide qualifiers, including "
         "the temporary-limit asterisk, must agree.",
         f"{tt('incomparable_basis_unit_or_value')}: contaminant member "
         f"{t['pollutant_member_panel.csv']['incomparable_basis_unit_or_value']}. "
         f"{tt('incomparable_unresolved_review_or_source_qualifier')}: pesticide "
         f"{t['pesticide_panel.csv']['incomparable_unresolved_review_or_source_qualifier']}"),
        ("Unit that cannot be converted",
         "Mass-per-mass units are converted. Volume-based values "
         f"({density} contaminant long-table rows) and grams per serving are not, and GMP is "
         "compared only with GMP.",
         f"{tt('incomparable_unit_dimension_or_value')}: contaminant category "
         f"{t['pollutant_category_panel.csv']['incomparable_unit_dimension_or_value']}. "
         f"{tt('incomparable_units')}: additive {t['additive_panel.csv']['incomparable_units']}. "
         f"{tt('stable_gmp')}: additive {t['additive_panel.csv']['stable_gmp']}"),
        ("Scope text changes (exclusions, food label, use condition, animals)",
         "Compared after Unicode and punctuation normalisation. Confirmed contaminant renames "
         "count as equal, and a member's host exclusions must also agree.",
         f"{tt('incomparable_scope_text')}: contaminant category "
         f"{t['pollutant_category_panel.csv']['incomparable_scope_text']}, member "
         f"{t['pollutant_member_panel.csv']['incomparable_scope_text']}, pesticide "
         f"{t['pesticide_panel.csv']['incomparable_scope_text']:,}, mycotoxin "
         f"{t['mycotoxin_panel.csv']['incomparable_scope_text']}, veterinary-drug summary "
         f"{t['vetdrug_panel.csv']['incomparable_scope_text']}, additive "
         f"{t['additive_panel.csv']['incomparable_scope_text']}"),
        ("Category without a counterpart in another edition",
         "No trend. A contaminant category no longer printed is not read as withdrawn, and its "
         "foods are followed in the member panel.",
         f"{tt('single_version')}: contaminant "
         f"{t['pollutant_category_panel.csv']['single_version']}, pesticide "
         f"{t['pesticide_panel.csv']['single_version']}, mycotoxin "
         f"{t['mycotoxin_panel.csv']['single_version']}, additive "
         f"{t['additive_panel.csv']['single_version']}. {tt('single_*_unmatched')}: mycotoxin member "
         f"{t['mycotoxin_member_panel.csv']['single_version_unmatched']}, veterinary-drug "
         f"summary {t['vetdrug_panel.csv']['single_2002_unmatched'] + t['vetdrug_panel.csv']['single_2019_unmatched']}. "
         f"{tt('incomparable_category_disappeared')}: contaminant "
         f"{t['pollutant_category_panel.csv']['incomparable_category_disappeared']}"),
        ("Contaminant member host not determinable",
         f"Cell and host are left blank, and {tt('note')} gives the reason, namely exclusion by "
         f"the inherited rule ({blanks['excluded']} cells), a span over two rules "
         f"({blanks['spans two printed rules']}) or differing exclusion lists "
         f"({blanks['host not determinable']}).",
         f"Trend from the remaining editions, with a note on {noted} rows"),
        ("Quarantined fragment",
         f"Kept only in {tt('quarantined_rows.csv')}. The {len(pol_q)} contaminant fragments "
         f"duplicate released rules, so no cell is lost. The {len(add_q)} additive fragments "
         f"blank the 2011 or 2014 cell of {len(add_rows)} additive rows.",
         f"Trend from the editions present ({add_judged} of the {len(add_rows)} rows). A blank "
         "is not read as absence"),
        ("Rule missing from an intermediate edition",
         "No trend spans the gap.",
         f"{tt('incomparable_edition_gap')}: pesticide "
         f"{t['pesticide_panel.csv']['incomparable_edition_gap']}, additive "
         f"{t['additive_panel.csv']['incomparable_edition_gap']}, veterinary-drug member "
         f"{t['vetdrug_member_panel.csv']['incomparable_edition_gap']}"),
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
T6_CAP = ("Three records traced from the source table to the panels, namely a comparable "
          "pesticide limit, a contaminant limit whose unit changes dimension, and a contaminant "
          "entry whose malformed duplicate was quarantined. Identifiers are released "
          "\\texttt{record\\_id} values, and page numbers refer to the PDF files in "
          "\\texttt{source\\_manifest.csv}.")


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
    assert tea["trend"] == "tightened"
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
         "in 2012 and 2017, and 0.5 under the table's mg/kg header in 2022 and 2025.",
         "GB 2762-2017, Table 4 (arsenic), p. 9: paddy, brown rice and milled rice, inorganic "
         "arsenic 0.2 mg/kg, with a footnote marker after paddy."),
        ("Long table",
         f"Six rows, one per edition, sharing \\texttt{{{tea['pesticide_key']}}} and "
         f"\\texttt{{{tea['food_key']}}}, e.g. {rid(last)} (2026, source page "
         f"{last['source_page']}, y = {float(last['source_y']):.1f}). The 2019 and 2021 rows "
         "come from the government-hosted copies and agree with the OCR cross-check of "
         "the edition scans.",
         f"Four rows. The 2012 and 2017 rows keep unit mg/L, "
         f"{tt('normalization_status')} {tt('density_required')} and a blank "
         f"{tt('limit_mgkg')}. The 2022 and 2025 rows are already in mg/kg.",
         f"The coordinate parser releases {rid(rice_2017)}. A second, line-based reading of "
         "the same entry began with a separator, and the bracket-structure gate moved it to "
         f"{tt('quarantined_rows.csv')} as {rid(frag)}."),
        ("Panel",
         f"In {tt('pesticide_panel.csv')}, {rid(tea)} is {tt('single_rule')} in all six editions, "
         f"and {tt('source_record_ids_YYYY')} returns each cell to its long-table row.",
         f"Category row {rid(juice_c)} and member row {rid(juice_m)} hold 0.5 in all four "
         "editions, with units mg/L, mg/L, mg/kg and mg/kg.",
         f"The released row fills the 2017 cell of category row {rid(rice_c)} and of the "
         "paddy, brown-rice and milled-rice member rows. The fragment enters no panel, so no "
         "cell is lost."),
        ("Trend",
         f"{tt('tightened')}.",
         f"{tt('incomparable_unit_dimension_or_value')} for the category and "
         f"{tt('incomparable_basis_unit_or_value')} for the member. Equal digits are not "
         "read as stable.",
         f"{tt('incomparable_category_disappeared')} for the category row, which is not "
         "printed after 2017, while the member rows follow the split "
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
          "determined, and \\texttt{note} records the reason. Renames and containment links that the "
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
            block.append(f"{label} & " + " & ".join(cells) + f" & {tt(row['trend'])}")
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
            f"({tt('incomparable_category_disappeared')}), and B, C and D start in 2022 "
            f"({tt('stable')}). Milled rice reaches D through a confirmed containment link.")


def _absorbed_line(cat_row):
    old = cat_row("铅", "乳粉非脱盐乳清粉")
    dairy = cat_row("铅", "乳及乳制品")
    assert old["trend"] == "incomparable_category_disappeared"
    assert dairy["v2017"] == "0.3" and "乳粉" in dairy["source_category_2017"]
    assert dairy["trend"] == "incomparable_scope_text"
    return ("Category panel: E is not printed after 2017. The milk and dairy products class "
            "is printed from 2017. In 2017 its exclusions still name milk powder and its value "
            f"is 0.3, so its category row is {tt('incomparable_scope_text')}.")


def _narrowed_line(cat_row):
    old = cat_row("铅", "蒸馏酒黄酒")
    new = cat_row("铅", "白酒黄酒")
    rest = cat_row("铅", "酒类")
    assert old["trend"] == "incomparable_category_disappeared" and new["trend"] == "stable"
    assert rest["trend"] == "incomparable_scope_text"
    return ("Baijiu reaches G through a confirmed containment link. From 2022 distilled "
            "spirits spans H and J, so its cells are blank and \\texttt{note} gives the reason. "
            "The residual class keeps 0.2 while its exclusions change.")


def _renamed_line(cat_row):
    row = cat_row("镉", "饮用天然矿泉水")
    assert row["n_versions"] == "4" and row["trend"] == "stable"
    return f"The confirmed rename merges K and L into one category row ({tt('stable')})."


CAT_LINE = {"Split": _split_line, "Absorbed": _absorbed_line, "Narrowed": _narrowed_line,
            "Renamed": _renamed_line}


# ── 冻结核验证据(Data/Interim 下入 git 的三处) ────────────
INTERIM = os.path.join(PROJ, "Data", "Interim")
AUDIT_ONE = os.path.join(INTERIM, "pesticide_audit")
AUDIT_TWO = os.path.join(INTERIM, "pesticide_audit_round2")
REENTRY = os.path.join(INTERIM, "manual_reentry", "reconciliation")
TEXTLAYER_REPORT = os.path.join(INTERIM, "pesticide_textlayer_scans",
                                "pesticide_textlayer_extraction_report.json")


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
T8_HEAD = ("Stratum & Rows in stratum & Round 1 errors / read & Round 1 rate, \\% (95\\% CI) & "
           "v1.1 errors / read & v1.1 upper 95\\% bound, \\%")
STRATA = (("2019", "consistent", "2019, OCR agrees"),
          ("2019", "text_only", "2019, text layer only"),
          ("2021", "consistent", "2021, OCR agrees"),
          ("2021", "text_only", "2021, text layer only"))
T8_CAP = ("Independent reading of the GB 2763-2019 and GB 2763-2021 rows against the "
          "edition scans. Rows are stratified by edition and by whether the OCR "
          "comparison recovered the row (OCR agrees) or not (text layer only). Within a "
          "stratum, rows were drawn at random with a fixed seed, in proportion to stratum "
          "size. Round 1 read release v1.0. Round 2 redrew the three "
          "strata with errors at the same sizes from the corrected release, skipping rows "
          "already read. The v1.1 columns combine round 2 with the round-1 rows of the stratum "
          "that was not redrawn, which are unchanged in release v1.1. Verifier misreadings are "
          "not counted as errors. Rates are errors per row read. Intervals and upper bounds are two-sided "
          "95\\% Clopper--Pearson limits. The nine OCR conflict rows and three "
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
               "\\texttt{record\\_id} links panels to long tables. Across releases it stays the "
               "same only while the fields it is computed from are unchanged, and these keys identify the "
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
        report = json.load(handle)
    layers = report["layers"]
    # 正文写「所有检查通过」:报告须是带源文件的完整运行,且每项都是 pass。
    assert report["summary"]["status_counts"]["pass"] == sum(len(layer) for layer in layers.values())
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

    # 2016、2019 两版可见条数与声明总数之差;正文据冻结提取报告写
    # 「2016 版英译本逐节条数相同」「2019 版没有重复条」。
    counts = {r["version_year"]: r for r in rd("pesticide_edition_reconciliation.csv")}
    sixteen, nineteen = counts["2016"], counts["2019"]
    with open(TEXTLAYER_REPORT, encoding="utf-8") as handle:
        textlayer = json.load(handle)["visible_rule_reconciliation"]
    translation = textlayer["2016"]["independent_translation_check"]
    assert (translation["english_translation_visible_rules"]
            == translation["chinese_source_visible_rules"]
            == int(sixteen["coordinate_extracted_visible_rules"]))
    assert (translation["sections_with_equal_visible_rule_counts"]
            == translation["section_rosters_compared"]
            == int(sixteen["declared_section_roster"]))
    duplicates = textlayer["2019"]["plus_one_audit"]["checks"]
    assert duplicates["exact_full_rule_duplicates"] == duplicates["cross_page_exact_duplicates"] == 0

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
        ("CountSixteenVisible", int(sixteen["coordinate_extracted_visible_rules"])),
        ("CountSixteenDeclared", int(sixteen["declared_mrl_items"])),
        ("CountSixteenSections", int(sixteen["declared_section_roster"])),
        ("CountNineteenVisible", int(nineteen["coordinate_extracted_visible_rules"])),
        ("CountNineteenDeclared", int(nineteen["declared_mrl_items"])),
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
