#!/usr/bin/env python3
"""数据论文三张图 —— Scientific Data 投稿用。

Fig 1  覆盖矩阵:五族 × 年份,格子按【读取方式】着色,格内标条目数。
       两个空格(GB2762-2005 / GB2760-1996)是盘上有 PDF 但未抽取的版本 —— 照实画出来,
       不留白也不假装没有。
Fig 2  双列表的列归属:GB2762-2022 汞表页图 + word bbox + 两个表头 + 推导出的列分界线
       + 破折号位置。画的就是 build_pollutant_doublecol.py 真正跑的那套坐标逻辑。
Fig 3  版本时间线:发布日 → 实施日,中间线段表示过渡期。日期直接读取发布包中的
       version_dates.csv；该表保留封面读取方法与官方登记交叉核对结果。

产物:Results/fig/fig1{Name}.{pdf,png,tex}
      Results/temp/DatapaperFigures/{figure_source_data,standard_cover_dates}.csv
      每张图的数值均可回到这些接口文件与 Data/Final 发布包。
"""
import argparse
import csv
import glob
import hashlib
import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import matplotlib.image as mpimg

# CSV 类输入读本工程 Data/Final(与 Database 发布包逐文件一致)
PROJ = str(Path(__file__).resolve().parents[2])
REL = os.path.join(PROJ, "Data", "Final", "china_food_limit_panel_v1")
OUT = os.path.join(PROJ, "Results", "fig")                       # 图:fig1<Name>.pdf/.png(+手写 .tex wrapper)
TEMP = os.path.join(PROJ, "Results", "temp", "DatapaperFigures") # 溯源/中间层
os.makedirs(OUT, exist_ok=True)
os.makedirs(TEMP, exist_ok=True)
DATES_CSV = os.path.join(TEMP, "standard_cover_dates.csv")

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 8,
    "axes.linewidth": 0.6,
    "pdf.fonttype": 42,   # TrueType,期刊要求可编辑字体
})
# 图 2 的标注要写表头原文(总汞/甲基汞),得有中文字体
CJK = "Songti SC"

# Okabe-Ito 色盲安全配色
C_TEXT = "#0072B2"   # PDF 文本层
C_COPY = "#56B4E9"   # 政府托管文本层副本；原扫描件做身份锚定与 OCR 交叉检查
C_MAN = "#CC79A7"    # 源图人工转录
C_DOC = "#009E73"    # Word 表格段落流
C_NONE = "#E8E8E8"   # 盘上有,未抽取

MODE_LABEL = {
    "text": "PDF text layer",
    "text_copy": "Government-hosted text layer (OCR audit)",
    "manual": "Manual transcription from page images",
    "docx": "Word table stream",
    "none": "Archived, not extracted",
}
MODE_COLOR = {
    "text": C_TEXT,
    "text_copy": C_COPY,
    "manual": C_MAN,
    "docx": C_DOC,
    "none": C_NONE,
}


def read(fn):
    with open(os.path.join(REL, fn), encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def save_figure(fig, name):
    """Write stable PDF metadata and the high-resolution PNG companion."""
    fig.savefig(
        os.path.join(OUT, f"{name}.pdf"),
        dpi=400,
        metadata={"CreationDate": None, "ModDate": None},
    )
    fig.savefig(os.path.join(OUT, f"{name}.png"), dpi=400)


# ---------------------------------------------------------------- 来源定位与版本日期
def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def edition_source_digests():
    """source_manifest.csv 里 role=edition_source 的 sha256 集合。"""
    with open(os.path.join(REL, "source_manifest.csv"), encoding="utf-8-sig") as fh:
        return {r["sha256"] for r in csv.DictReader(fh)
                if r.get("source_role") == "edition_source"}


def find_pdf(source_root, number, year):
    """定位某版源 PDF,并锁定到发布清单登记的那一份字节流。

    同名副本可能字节不同(例:GB 2762-2022 在 污染物/ 与 补充_其它限量标准/ 下各有一份,
    只有前者是 source_manifest 的 edition_source)。旧实现按路径长度取最短,
    等于让目录名长度决定用哪份源 —— 图会画在一份并不进发布包的 PDF 上。
    这里改为只认清单登记的 edition_source 摘要,认不出就报错,不猜。
    """
    hits = [p for p in glob.glob(os.path.join(source_root, "**", f"{number}-{year}*.pdf"),
                                 recursive=True)
            if "修改单" not in p]
    if not hits:
        return None
    registered = edition_source_digests()
    matched = sorted({p for p in hits if _sha256(p) in registered})
    if not matched:
        raise ValueError(
            f"{number}-{year}: {len(hits)} 个候选都不是 source_manifest 登记的 "
            f"edition_source,拒绝用未登记的字节流画图。候选:{[os.path.basename(p) for p in hits]}"
        )
    if len({_sha256(p) for p in matched}) > 1:
        raise ValueError(f"{number}-{year}: 多份不同字节的已登记源,无法判定:{matched}")
    return matched[0]


DATE_FAMILY = {
    "contaminant": "GB 2762",
    "pesticide": "GB 2763",
    "mycotoxin": "GB 2761",
    "veterinary_drug": "GB 31650",
    "additive": "GB 2760",
}


def build_dates():
    """直接投影发布包的日期接口，避免图脚本重新解释来源文件。"""
    rows = []
    for source in read("version_dates.csv"):
        year = int(source["version_year"])
        if source["standard"] == "MOA Announcement 235":
            label = "2002 announcement"
        elif source["standard"] == "GB 31650.1":
            label = "2022 suppl."
        else:
            label = str(year)
        rows.append(
            {
                "family": DATE_FAMILY[source["family"]],
                "number": source["standard"],
                "version_year": year,
                "label": label,
                "issue_date": source["issue_date"],
                "effective_date": source["effective_date"],
                "date_source": source["date_source"],
                "cross_check_official_register": source[
                    "cross_check_official_register"
                ],
                "pdf": source["source_filename"],
            }
        )
    with open(DATES_CSV, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    checked = [row for row in rows if row["cross_check_official_register"]]
    agree = [
        row for row in checked if row["cross_check_official_register"] == "agrees"
    ]
    print(
        f"[dates] {sum(bool(row['issue_date']) for row in rows)}/{len(rows)} versions dated; "
        f"official-register cross-check: {len(agree)}/{len(checked)} agree"
    )
    return rows


# ---------------------------------------------------------------- Fig 1
FAMILIES = [
    ("GB 2762", "Contaminants"),
    ("GB 2763", "Pesticide residues"),
    ("GB 2761", "Mycotoxins"),
    ("GB 31650", "Veterinary drug residues"),
    ("GB 2760", "Food additives"),
]


def coverage_cells():
    """每个版本一格:主读取方式 + 条目数。数直接从发布包的长表数,不从别处抄。"""
    cells = []

    def add(fam, yr, label, mode, n, note=""):
        cells.append({"family": fam, "version_year": yr, "label": label,
                      "mode": mode, "n_rows": n, "note": note})

    poll = read("pollutant_limits_long.csv")
    for yr in (2012, 2017, 2022, 2025):
        add("GB 2762", yr, str(yr), "text",
            sum(1 for r in poll if r["version_year"] == str(yr)))
    add("GB 2762", 2005, "2005", "none", 0, "scanned; not extracted")

    pest = read("pesticide_limits_long.csv")
    for yr in (2012, 2014, 2016, 2019, 2021, 2026):
        sub = [r for r in pest if r["version_year"] == str(yr)]
        roles = {row["source_copy_role"] for row in sub}
        if roles == {"government_hosted_text_layer_extraction_copy"}:
            mode = "text_copy"
            note = "scanned edition identity anchor; frozen OCR cross-check"
        elif roles == {"archive_text_layer_edition_source_copy"}:
            mode = "text"
            note = ""
        else:
            raise ValueError(f"unexpected GB 2763 source roles for {yr}: {sorted(roles)}")
        add("GB 2763", yr, str(yr), mode, len(sub), note)

    myco = read("mycotoxin_limits_long.csv")
    for yr, mode in ((2005, "manual"), (2011, "text"), (2017, "text")):
        add("GB 2761", yr, str(yr), mode,
            sum(1 for r in myco if r["version_year"] == str(yr)))

    vet = read("vetdrug_limits_long.csv")
    # 2002 = 农业部 235 号公告，2022 = GB 31650.1 增补件；格子太窄放不下全称，
    # 标签只写年份,身份在图注里说清楚。
    for yr, lab, mode in ((2002, "2002", "docx"), (2019, "2019", "text"),
                          (2022, "2022", "manual")):
        sub = [r for r in vet if r["version_year"] == str(yr)]
        nman = sum(r["source"] == "manual" for r in sub)
        note = f"{nman} rows hand-transcribed" if mode != "manual" and nman else ""
        add("GB 31650", yr, lab, mode, len(sub), note)

    add_ = read("additive_limits_long.csv")
    for yr in (2011, 2014, 2024):
        add("GB 2760", yr, str(yr), "text",
            sum(1 for r in add_ if r["version_year"] == str(yr)))
    add("GB 2760", 1996, "1996", "none", 0, "scanned; not extracted")
    return cells


def fig1(cells):
    fig, ax = plt.subplots(figsize=(7.2, 2.9))
    ypos = {f: len(FAMILIES) - 1 - i for i, (f, _) in enumerate(FAMILIES)}
    for c in cells:
        y = ypos[c["family"]]
        x = c["version_year"]
        hatch = "///" if c["mode"] == "none" else None
        ax.add_patch(Rectangle((x - 0.85, y - 0.34), 1.7, 0.68,
                               facecolor=MODE_COLOR[c["mode"]], edgecolor="white",
                               linewidth=0.8, hatch=hatch, zorder=2))
        dark = c["mode"] in ("text", "docx")
        ax.text(x, y + 0.10, c["label"], ha="center", va="center", fontsize=6.2,
                color="white" if dark else "#333333", zorder=3, linespacing=0.95)
        ax.text(x, y - 0.16, "—" if c["n_rows"] == 0 else f"{c['n_rows']:,}",
                ha="center", va="center", fontsize=6.6, weight="bold",
                color="white" if dark else "#333333", zorder=3)
        if c["note"].endswith("hand-transcribed"):
            ax.plot(x + 0.62, y + 0.24, marker="*", ms=6, color="white", zorder=4,
                    markeredgecolor=C_MAN, markeredgewidth=0.6)

    for f, en in FAMILIES:
        ax.text(1993.5, ypos[f], f, ha="right", va="center", fontsize=8, weight="bold")
        ax.text(1993.5, ypos[f] - 0.30, en, ha="right", va="center", fontsize=6.5,
                color="#666666", style="italic")
    ax.set_xlim(1994.5, 2028)
    ax.set_ylim(-0.75, len(FAMILIES) - 0.35)
    ax.set_yticks([])
    ax.set_xticks(range(1996, 2028, 4))
    ax.tick_params(axis="x", length=2, pad=1.5)
    for s in ("left", "right", "top"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_position(("outward", 4))
    ax.set_xlabel("Version year", fontsize=7.5, labelpad=1)
    for x in range(1996, 2028, 4):
        ax.axvline(x, color="#F2F2F2", lw=0.5, zorder=0)

    legend_modes = ("text", "text_copy", "docx", "manual", "none")
    handles = [Rectangle((0, 0), 1, 1, facecolor=MODE_COLOR[m], edgecolor="white",
                         hatch="///" if m == "none" else None)
               for m in legend_modes]
    ax.legend(handles, [MODE_LABEL[m] for m in legend_modes],
              loc="upper center", bbox_to_anchor=(0.42, -0.20), ncol=3, frameon=False,
              fontsize=6.4, handlelength=1.3, handleheight=0.9, columnspacing=1.2,
              handletextpad=0.5)
    # Helvetica 没有 ★ 的字形,得指定一个有的字体,否则输出里是个豆腐块
    ax.text(2028, -0.62, "★ cell also contains hand-transcribed rows", fontsize=5.8,
            color="#888888", ha="right", va="center",
            fontfamily=["DejaVu Sans", "Arial Unicode MS"])
    fig.subplots_adjust(left=0.20, right=0.99, top=0.97, bottom=0.30)
    save_figure(fig, "fig1Coverage")
    plt.close(fig)
    summary = {
        "n_cells": len(cells),
        "n_records": sum(c["n_rows"] for c in cells),
        "n_extracted_editions": sum(c["n_rows"] > 0 for c in cells),
    }
    print(f"[fig1] {summary['n_cells']} cells, {summary['n_records']:,} rows")
    return summary


# ---------------------------------------------------------------- Fig 2
NS = "{http://www.w3.org/1999/xhtml}"
DASH = re.compile(r"^[—–\-]+$")


def fig2(source_root):
    """GB2762-2022 汞表(总汞|甲基汞):画出 build_pollutant_doublecol.py 的真实几何。"""
    pdf = find_pdf(source_root, "GB 2762", 2022)
    page = 8   # 汞表所在页(总汞|甲基汞),见 pdftotext -layout 分页检索
    xml = subprocess.run(["pdftotext", "-bbox-layout", "-f", str(page), "-l", str(page), pdf, "-"],
                         capture_output=True).stdout.decode("utf-8", "replace")
    root = ET.fromstring(xml)
    pg = next(root.iter(NS + "page"))
    W, H = float(pg.get("width")), float(pg.get("height"))
    ws = [(float(w.get("xMin")), float(w.get("xMax")), float(w.get("yMin")),
           float(w.get("yMax")), (w.text or "").strip())
          for w in pg.iter(NS + "word") if (w.text or "").strip()]

    left = next(w for w in ws if w[4] == "总汞")
    right = min((w for w in ws if w[4] == "甲基汞" and abs(w[2] - left[2]) < 6 and w[0] > left[1]),
                key=lambda w: w[0])
    split_x = (left[1] + right[0]) / 2.0                    # 列分界
    head_center = (left[0] + left[1]) / 2.0
    cat_bound = 2 * head_center - split_x                    # 类别列右界 = 左表头中心的镜像

    dpi = 200
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(dpi), "-png",
                        pdf, os.path.join(td, "pg")], capture_output=True)
        img = mpimg.imread(glob.glob(os.path.join(td, "pg*.png"))[0])

    # 只画表格区域(表头往下到页脚),裁掉大片空白
    y0, y1 = left[2] - 44, min(H - 40, left[2] + 300)
    x0, x1 = 40, W - 40
    fig, ax = plt.subplots(figsize=(7.2, 4.3))
    ax.imshow(img, extent=[0, W, H, 0], zorder=0, interpolation="bilinear")

    seg = [w for w in ws if left[2] - 2 < w[2] < y1]
    for xmin, xmax, ymin, ymax, t in seg:
        ax.add_patch(Rectangle((xmin, ymin), xmax - xmin, ymax - ymin, fill=False,
                               edgecolor="#9AB8CC", lw=0.35, zorder=2))
    dashes = [w for w in seg if DASH.fullmatch(w[4]) and (w[0] + w[1]) / 2 >= cat_bound]
    for xmin, xmax, ymin, ymax, t in dashes:
        ax.add_patch(Rectangle((xmin - 1.5, ymin - 3, ), xmax - xmin + 3, ymax - ymin + 6,
                               fill=False, edgecolor="#D55E00", lw=1.1, zorder=4))
    for h, name, en in ((left, "总汞", "total mercury"), (right, "甲基汞", "methylmercury")):
        ax.add_patch(Rectangle((h[0] - 1, h[2] - 2), h[1] - h[0] + 2, h[3] - h[2] + 4,
                               fill=False, edgecolor="#0072B2", lw=1.4, zorder=5))
    ax.axvline(split_x, color="#0072B2", lw=1.2, ls="--", zorder=6)
    ax.axvline(cat_bound, color="#009E73", lw=1.2, ls=":", zorder=6)

    def lab(x, y, txt, color, ha="center"):
        ax.text(x, y, txt, fontsize=6.6, color=color, ha=ha, va="center", zorder=7,
                bbox=dict(boxstyle="round,pad=0.22", fc="white", ec=color, lw=0.5, alpha=0.94))

    def call(anchor_w, tx, ty, txt, color, ha):
        ax.annotate(txt, xy=((anchor_w[0] + anchor_w[1]) / 2, (anchor_w[2] + anchor_w[3]) / 2),
                    xytext=(tx, ty), fontsize=6.6, color=color, ha=ha, va="center", zorder=7,
                    bbox=dict(boxstyle="round,pad=0.24", fc="white", ec=color, lw=0.5,
                              alpha=0.95),
                    arrowprops=dict(arrowstyle="->", color=color, lw=0.8, shrinkA=1, shrinkB=3))

    # 两条竖线的标注放页脚,并朝相反方向展开 —— 它们只隔 48pt,同侧对齐必然叠在一起
    lab(cat_bound - 4, y1 - 10, f"category bound = {cat_bound:.1f}pt\n(mirror of header 1 centre)",
        "#009E73", ha="right")
    lab(split_x + 4, y1 - 10, f"column boundary = {split_x:.1f}pt\n(midpoint of the two headers)",
        "#0072B2", ha="left")
    # 两个表头标签都摆进「食品类别」表头格那片空白、各拉一条引线 —— 右表头贴着页边,
    # 标签放它旁边要么被裁掉、要么盖住上一行的「限量(mg/kg)」。
    call(left, left[0] - 12, left[2] - 13, "header 1  总汞 (total Hg)", "#0072B2", "right")
    call(right, left[0] - 12, right[2] - 31, "header 2  甲基汞 (methyl-Hg)", "#0072B2", "right")

    # 破折号:挑右列(甲基汞)里自上而下第二个 —— 它那行的食品名短(新鲜蔬菜),
    # 左边正好有整片空白放 callout,箭头也不会跟下面那条紫线交叉。
    rd = sorted([d for d in dashes if (d[0] + d[1]) / 2 > split_x], key=lambda w: w[2])
    if rd:
        d = rd[1] if len(rd) > 1 else rd[0]
        call(d, cat_bound - 105, d[2] + 3,
             "em-dash: no limit in this column,\nso the value on this row is the other analyte's",
             "#D55E00", "right")
    # 同一页上还印着第四个维度:限量后面跟着计量基准(以干重计)
    dw = [w for w in seg if "干重" in w[4]]
    if dw:
        call(dw[0], cat_bound - 105, dw[0][2] + 32,
             "the printed value also carries its basis of expression\n"
             "(“干重计”, dry weight), which changes across editions",
             "#7B5AA6", "right")
    # 字体回退链:拉丁字母走 Helvetica,汉字 Helvetica 没有 → 逐字回退到宋体。
    # 顺序反过来写(CJK 在前)会让整段英文都变成宋体的衬线拉丁,标注看着像正文。
    for t in ax.texts:
        t.set_fontfamily(["Helvetica", CJK, "DejaVu Sans"])
    ax.set_xlim(x0, x1)
    ax.set_ylim(y1, y0)
    ax.set_xticks([])
    ax.set_yticks([])
    for s_ in ax.spines.values():
        s_.set_visible(False)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    save_figure(fig, "fig1ColumnAssignment")
    plt.close(fig)
    print(f"[fig2] page {page}: split_x={split_x:.1f} cat_bound={cat_bound:.1f} "
          f"dashes={len(dashes)} words={len(seg)}")
    return {"page": page, "split_x": round(split_x, 1), "cat_bound": round(cat_bound, 1),
            "n_dashes": len(dashes)}


# ---------------------------------------------------------------- Fig 3
def fig3(dates):
    rows = [r for r in dates if r["issue_date"] and r["effective_date"]]
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    ypos = {f: len(FAMILIES) - 1 - i for i, (f, _) in enumerate(FAMILIES)}
    extracted = {(c["family"], c["version_year"]) for c in coverage_cells() if c["n_rows"] > 0}

    def dt(s):
        y, m, d = map(int, s.split("-"))
        return date(y, m, d)

    gaps = []
    for r in rows:
        y = ypos[r["family"]]
        a, b = dt(r["issue_date"]), dt(r["effective_date"])
        months = (b - a).days / 30.44
        got = (r["family"], r["version_year"]) in extracted
        fc = "#0072B2" if got else "white"
        ax.plot([a, b], [y, y], color="#0072B2" if got else "#BBBBBB", lw=2.6,
                solid_capstyle="butt", zorder=2, alpha=0.85 if got else 1)
        ax.plot([a], [y], marker="o", ms=4.2, mfc=fc, mec="#0072B2" if got else "#BBBBBB",
                mew=1.0, zorder=3)
        ax.plot([b], [y], marker="D", ms=3.6, mfc=fc, mec="#0072B2" if got else "#BBBBBB",
                mew=1.0, zorder=3)
        ax.text(a, y + 0.30, r["label"].replace("\n", " "), fontsize=5.9, ha="center",
                va="bottom", color="#333333" if got else "#AAAAAA")
        days = (b - a).days
        txt = f"{months:.0f}mo" if months >= 1 else ("same day" if days == 0 else f"{days}d")
        ax.text(b, y - 0.20, txt, fontsize=5.6, ha="left", va="center",
                color="#D55E00" if months < 1 else "#888888",
                weight="bold" if months < 1 else "normal")
        if got:
            gaps.append(months)

    for f, en in FAMILIES:
        ax.text(date(2000, 6, 1), ypos[f], f, ha="right", va="center", fontsize=8, weight="bold")
        ax.text(date(2000, 6, 1), ypos[f] - 0.28, en, ha="right", va="center", fontsize=6.5,
                color="#666666", style="italic")
    ax.set_xlim(date(2000, 9, 1), date(2027, 6, 1))
    ax.set_ylim(-0.85, len(FAMILIES) - 0.35)
    ax.set_yticks([])
    ax.set_xticks([date(y, 1, 1) for y in range(2002, 2028, 4)])
    ax.set_xticklabels([str(y) for y in range(2002, 2028, 4)])
    ax.tick_params(axis="x", length=2, pad=1.5)
    for s in ("left", "right", "top"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_position(("outward", 4))
    for y in range(2002, 2028, 4):
        ax.axvline(date(y, 1, 1), color="#F2F2F2", lw=0.5, zorder=0)

    h = [plt.Line2D([], [], marker="o", ms=4.2, ls="", mfc="#0072B2", mec="#0072B2"),
         plt.Line2D([], [], marker="D", ms=3.6, ls="", mfc="#0072B2", mec="#0072B2"),
         plt.Line2D([], [], color="#0072B2", lw=2.6),
         plt.Line2D([], [], marker="o", ms=4.2, ls="", mfc="white", mec="#BBBBBB")]
    ax.legend(h, ["Issued", "In force", "Transition period",
                  "Version archived but not extracted"],
              loc="upper center", bbox_to_anchor=(0.45, -0.16), ncol=4, frameon=False,
              fontsize=6.4, handletextpad=0.5, columnspacing=1.4)
    fig.subplots_adjust(left=0.185, right=0.985, top=0.97, bottom=0.26)
    save_figure(fig, "fig1Timeline")
    plt.close(fig)
    med = sorted(gaps)[len(gaps) // 2]
    print(f"[fig3] {len(rows)} versions dated; extracted-version transition gap: "
          f"median {med:.1f} months, min {min(gaps):.2f}, max {max(gaps):.1f}")
    return {
        "n_dated": len(rows),
        "n_cross_checked": sum(bool(r["cross_check_official_register"]) for r in rows),
        "n_agree": sum(r["cross_check_official_register"] == "agrees" for r in rows),
        "n_ocr_covers": sum(r["date_source"] == "OCR" for r in rows),
        "median_months": med,
    }


def write_figure_tex(name, caption):
    lines = [
        r"\begin{figure}[htbp]",
        r"\centering",
        rf"\includegraphics[width=\textwidth]{{Results/fig/{name}.pdf}}",
        rf"\caption{{{caption}}}",
        rf"\label{{{name}}}",
        r"\end{figure}",
    ]
    with open(os.path.join(OUT, f"{name}.tex"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        required=True,
        type=Path,
        help="Root of the local source-standard archive; source files are not redistributed.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    source_root = str(args.source_root)
    dates = build_dates()
    cells = coverage_cells()
    with open(os.path.join(TEMP, "figure_source_data.csv"), "w", newline="",
              encoding="utf-8-sig") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["family", "version_year", "label", "mode", "n_rows", "note"],
            lineterminator="\n",
        )
        w.writeheader()
        w.writerows(cells)
    coverage = fig1(cells)
    geo = fig2(source_root)
    timeline = fig3(dates)
    write_figure_tex(
        "fig1Coverage",
        "Coverage matrix. Rows are the five standard families and columns are version years "
        "from 1996 to 2026. Each cell gives the number of released limit records and is shaded "
        "by read path. The 2019 and 2021 pesticide cells use government-hosted copies; the "
        "edition scans, kept as audit-only copies, anchor edition identity and supply a frozen "
        "optical-character-recognition (OCR) cross-check. A star marks a mainly machine-read "
        "cell with hand-transcribed rows. "
        "The two hatched cells, GB 2762-2005 and GB 2760-1996, are archived but unextracted. "
        f"The matrix holds {coverage['n_cells']} coverage cells, and the "
        f"{coverage['n_extracted_editions']} extracted cells contain "
        f"{coverage['n_records']:,} records. The 2002 veterinary-drug "
        "cell is Ministry of Agriculture Announcement 235; its 2022 cell is the "
        "supplementary standard "
        "GB 31650.1.",
    )
    write_figure_tex(
        "fig1ColumnAssignment",
        "Column assignment in the two-column tables. The mercury table of GB 2762-2022 is "
        "rendered with word bounding boxes. Its two analyte headers set the value-column "
        f"boundary at {geo['split_x']:.1f} pt, and the inferred category boundary is "
        f"{geo['cat_bound']:.1f} pt; both are derived per page. Each row has a value in one "
        "column and an em-dash in the other, so the dash position assigns the value to an "
        "analyte. The same page also shows that an equal printed value can carry a different "
        "basis of expression.",
    )
    write_figure_tex(
        "fig1Timeline",
        "Version timeline from issue date to effective date. Dates are read from source covers "
        "or the 2002 announcement and released in \\texttt{version\\_dates.csv}; 20 of the 21 "
        "coverage editions have both dates, while GB 2760-1996 records an explicit missing date. "
        f"{timeline['n_cross_checked']} editions are listed in a register of current standards, "
        f"and for {timeline['n_agree']} of them both register dates agree with the source reading; "
        f"{timeline['n_ocr_covers']} covers required OCR. Across extracted editions, the "
        f"transition-period median is {timeline['median_months']:.0f} months. The 2002 "
        "announcement took effect on its issue date.",
    )
    print("figures →", OUT)
