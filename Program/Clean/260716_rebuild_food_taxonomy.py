#!/usr/bin/env python3
"""Rebuild the normative GB 2762 Appendix A food taxonomy.

为什么需要它:排除语只能给出"被排除者 ⊂ 母类"这一种父子边。但 GB2762-2022 把镉·食用菌
改成按菌种列举(松茸1.0/松露2.0/羊肚菌0.6),而 2012 只有"新鲜食用菌 0.2"——
"松茸 ⊂ 新鲜食用菌"这条链,排除语里没有,两个词也毫无字面重叠,字符串推不出来。

它在标准自己的附录A 里。GB2762 正文 3 明文规定:
    "食品类别(名称)说明(见附录A)用于界定污染物限量的适用范围…
     当某种污染物限量应用于某一食品类别(名称)时,则该食品类别(名称)内的所有类别食品均适用。"
即附录A 是【规范性】分类树,限量沿树向下继承。

★ 260714 重写。上一版按"缩进 x 聚三档"直接切列,建出的边不可靠(松茸 ⊂ "不包" /
  "蔬菜及其"),产物只好弃用为 food_taxonomy_UNRELIABLE.csv。根因是**版式没吃透**:

  附录A 是【两列表】——
    · 左列 = 大类(食用菌及其制品 / 谷物及其制品(不包括焙烤食品)),是【跨多行的合并单元格】,
      文字【垂直居中】并按窄栏折行("谷物及其制"/"品(不包括"/"焙烤食品)" 落在三行)。
      它既不在所辖块的开头、也不在结尾 —— 按 y 顺序读必然错位,这是上一版建出假边的根源。
    · 右列 = 三级缩进树(实测 x = 127 / 145 / 163,18pt 一档):
        新鲜食用菌(L1) → 松茸、松露、双孢菇(L2)
        谷物(L1) → 稻谷、玉米、小麦(L2);小麦粉制品(L2) → 生湿面制品(L3)

  正确的支点是【表格线】:大类合并单元格的辖域由横线划定,与文字位置无关。
  横线/竖线在文本层里没有,但在【渲染图】里一测即得(整行/整列暗像素跨度),
  再按 72/DPI 折回 pt 与 bbox 词对齐。于是:
    横线分带 → 带内左列碎片按(y,x)拼成大类名 → 右列按缩进建三级栈。

  跨页:标准会把大类名【重印】一遍(食用菌及其制品 在 p15、p16 各出现一次),故不需合并单元格;
  但 L1 子标题不会重印(新鲜食用菌 在 p15,菌种在 p16),所以【大类名相同就不重置 L1/L2 栈】。

  拉丁学名折行("Yang;茶褐新生牛肝菌…"、"Rugiboletus extremiorientalis…"、"Dai)")会掉进
  L1 的 x 档冒充节点 —— 判据:节点行必以【中文】开头,拉丁字母开头的一律并回上一行。

产物: food_taxonomy.csv  (child, parent, level, src_year)

The four source PDFs must be supplied explicitly. Their SHA-256 identities are
locked below, and replay must reproduce the frozen 798-row snapshot byte for
byte. The parser requires Poppler, NumPy, and Pillow.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

from release_dependency_utils import (
    RELEASE_DEPENDENCY_SPECS,
    read_locked_csv,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KNOWN_CATEGORIES = (
    PROJECT_ROOT
    / "Data"
    / "Interim"
    / "release_dependencies"
    / "pollutant_old_path.csv"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "Data"
    / "Interim"
    / "release_dependencies"
    / "food_taxonomy.csv"
)
NS = "{http://www.w3.org/1999/xhtml}"
YEARS = ("2022", "2025", "2017", "2012")
DPI = 150
FURNITURE = re.compile(r"^GB\s*\d|^表\s*A|^附\s*录|^食品类别|^\d+$")
EXPECTED_OUTPUT_SHA256 = (
    "f5730ffcc4bfe4f54a427445a2a392fbdb473de609a6aa3b23584f6ced415f7d"
)
SOURCE_DIGESTS = {
    "2012": "8ebbcf11896b5a2684414e6f8d63de8bf4595b3547629a947d4eeda37bfe8647",
    "2017": "3d03a0d9488bfc100d0d6830d370f1607a18a620852c7927a4db289305ce7ade",
    "2022": "7ce8442362405a2b6381811ee6dca5aab75ee0b6613ea11888c2facc60d1ea39",
    "2025": "a8cad4d17354ef28c7dc6dae3dc3c0bde0b1d9315260f8e630b531f0d19966b4",
}


def clean(s):
    """条目文本 → 裸类别名。拉丁学名与括注一律截掉(限量表侧的 canonical 也剥括号,两边对齐)。"""
    s = re.sub(r"\s+", "", s)
    s = re.split(r"[A-Za-z]", s, maxsplit=1)[0]
    s = re.split(r"[\(（\[［]", s, maxsplit=1)[0]
    return s.strip("、,，.。:;:")


def page_grid(pdf, pno):
    """从渲染图测表格线,折回 pt。返回 (横线[], 竖线[])。"""
    with tempfile.TemporaryDirectory() as directory:
        tag = str(Path(directory) / f"grid_{pno}")
        subprocess.run(
            [
                "pdftoppm",
                "-f",
                str(pno),
                "-l",
                str(pno),
                "-r",
                str(DPI),
                "-png",
                str(pdf),
                tag,
            ],
            capture_output=True,
            check=True,
        )
        hits = sorted(Path(directory).glob(f"grid_{pno}*.png"))
        if not hits:
            return [], []
        with Image.open(hits[0]) as image:
            a = np.asarray(image.convert("L"))
    H, W = a.shape
    d = a < 128

    def merge(idx):
        g = []
        for i in idx:
            if g and i - g[-1][-1] <= 3:
                g[-1].append(i)
            else:
                g.append([i])
        return [float(np.mean(x)) * 72.0 / DPI for x in g]

    return (merge(np.where(d.sum(axis=1) > 0.45 * W)[0]),
            merge(np.where(d.sum(axis=0) > 0.30 * H)[0]))


def page_words(pdf, pno):
    xml = subprocess.run(["pdftotext", "-bbox-layout", "-f", str(pno), "-l", str(pno), pdf, "-"],
                         capture_output=True, timeout=300).stdout.decode("utf-8", "replace")
    pgs = list(ET.fromstring(xml).iter(NS + "page"))
    if not pgs:
        return []
    return [(float(w.get("xMin")), float(w.get("xMax")), float(w.get("yMin")),
             (w.text or "").strip())
            for w in pgs[0].iter(NS + "word") if (w.text or "").strip()]


def lines_of(ws, tol=6.0):
    ws = sorted(ws, key=lambda w: w[2])
    out, cur, last = [], [], None
    for w in ws:
        if last is not None and w[2] - last > tol:
            out.append(cur)
            cur = []
        cur.append(w)
        last = w[2]
    if cur:
        out.append(cur)
    return [sorted(line, key=lambda w: w[0]) for line in out]


def appendix_pages(pdf):
    """附录A 的页码。
    ⚠ 不能用 `表\\s*A\\.\\s*1` 去匹配 -layout 文本:续页页眉被排版拆成【倒序两行】
      ("1 (续)" 在上、"表 A." 在下),正则一律失配 —— 实测 2022 只认出首页 15,
      后 5 页(菌种全在那儿)整段丢掉,松茸/松露/木耳的父链因此建不出来。
      改为把空白全抹掉再找 "表A"(同时覆盖 表A.1 与 表A.1(续))。"""
    info = subprocess.run(
        ["pdfinfo", str(pdf)], capture_output=True, check=True
    ).stdout.decode("utf-8", "replace")
    n = int(
        next(
            (
                line.split()[1]
                for line in info.split("\n")
                if line.startswith("Pages:")
            ),
            0,
        )
    )
    out = []
    for p in range(1, n + 1):
        t = subprocess.run(["pdftotext", "-layout", "-f", str(p), "-l", str(p), pdf, "-"],
                           capture_output=True).stdout.decode("utf-8", "replace")
        if "表A" in re.sub(r"\s+", "", t):
            out.append(p)
    return out


def major_candidates(ws):
    """左列大类名的候选(按可信度排序)。
    ⚠ 2012/2017 的大类是【竖排】(一字一行),名字过长时折成两条竖列 —— 而【两版的读列方向相反】:
        2012 "其他类（除上述食品以外的食品）"  右列 x=112.3 → 其他类（除上述食
                                              左列 x= 96.2 → 品以外的食品）      = 自右向左
        2017 "可可制品、巧克力和巧克力制品以及糖果"
                                              左列 x= 81.0 → 可可制品、巧克力和巧
                                              右列 x= 90.0 → 克力制品以及糖果    = 自左向右
      两列的 y 交错(2012: 479.1, 484.3, 489.4 …),按 (y,x) 行序读就逐字咬合成 "其品他以类外的"
      —— 上一版那批假大类名全部源于此。
      而 2022/2025、以及 2012 的另一些格子却是【横排折行】,必须按 y 读。同表并存,一套顺序必错一半。

    判据:竖排的每个 word 恒为【单字】;只要出现多字 word 就是横排。
    列序:竖排是【排满一列才溢到下一列】,故【先排的列必更满】——
         2012 是 8 字 vs 7 字、2017 是 10 字 vs 8 字,两版都成立。长者优先,另一序作为备选。"""
    if not ws:
        return []
    if not all(len(w[3]) == 1 for w in ws):
        return ["".join(w[3] for w in sorted(ws, key=lambda w: (w[2], w[0])))]
    cols = {}
    for w in ws:
        k = next((k for k in cols if abs(k - w[0]) < 6), w[0])
        cols.setdefault(k, []).append(w)
    txt = {k: "".join(t[3] for t in sorted(v, key=lambda t: t[2])) for k, v in cols.items()}
    ltr = [txt[k] for k in sorted(txt)]
    rtl = [txt[k] for k in sorted(txt, reverse=True)]
    first = ltr if len(ltr[0]) >= len(rtl[0]) else rtl
    other = rtl if first is ltr else ltr
    return ["".join(first), "".join(other)]


OPEN, CLOSE = "（(［[【", "）)］]】"


def balance(s):
    return sum(1 for c in s if c in OPEN) - sum(1 for c in s if c in CLOSE)


def indent_anchors(inds):
    """缩进档位。most_common(3) 会被折行残渣顶掉真档位(2022 聚出假档 136,而真档是 127/145/163),
    故先按频次滤噪、再把相距 <8pt 的档位并掉(同一档的抖动),最后按 x 升序取前三级。"""
    cnt = Counter(inds)
    lo = max(3, int(0.02 * len(inds)))
    keep = sorted((x for x, c in cnt.items() if c >= lo))
    merged = []
    for x in keep:
        if merged and x - merged[-1] < 8:
            if cnt[x] > cnt[merged[-1]]:
                merged[-1] = x
        else:
            merged.append(x)
    return merged[:3]


def parse_version(pdf, yr, known, unresolved):
    edges, pages = {}, appendix_pages(pdf)
    if not pages:
        print(f"{yr}: 未找到附录A")
        return edges

    # 缩进档位从【本文档】聚,不写死:各版排版不同,照抄别版的偏移量会把父子压成同一档
    all_ind = []
    cache = {}
    for p in pages:
        hr, vr = page_grid(pdf, p)
        ws = page_words(pdf, p)
        if len(vr) < 3 or len(hr) < 2:
            continue
        cb = vr[1]                              # 竖线[0]=表左边框, [1]=大类列|子类列 分界
        cache[p] = (hr, cb, ws)
        for ln in lines_of([w for w in ws if w[0] >= cb]):
            txt = "".join(w[3] for w in ln)
            if FURNITURE.match(txt) or not re.match(r"[一-鿿]", txt):
                continue
            all_ind.append(round(ln[0][0]))
    if not all_ind:
        print(f"{yr}: 附录A 无可用条目")
        return edges
    anchors = indent_anchors(all_ind)
    print(f"{yr}: 附录A 页 {pages} | 缩进档位 {anchors}")

    prev_major, stack = None, {}
    for p in pages:
        if p not in cache:
            continue
        hr, cb, ws = cache[p]
        for top, bot in zip(hr[:-1], hr[1:]):
            band = [w for w in ws if top < w[2] < bot]
            cands = [clean(c) for c in major_candidates([w for w in band if w[1] < cb])]
            cands = [c for c in cands if c]
            # 白名单兜底:拼出来的大类名若不在已知类别里,先试另一种列序;两种都对不上就
            # 【判为未解析】(major=None)—— 宁可丢掉这条根边,也不发出一条假边。
            # 假父子边会造出假趋势,比缺链危险得多;缺链只是少一次比较。
            major = next((c for c in cands if c in known), None)
            if major is None and cands:
                unresolved.append((yr, cands[0]))
            if major is None:
                major = prev_major if not cands else None
            if major is None:
                stack = {}                      # 根未解析:L1 边不发,但 L2/L3 仍靠栈自建
            elif major != prev_major:           # 新的大类格 → 清栈;同名=跨页续格 → 保栈
                stack = {}
            prev_major = major

            depth = 0                           # 未闭合的括号数
            for ln in lines_of([w for w in band if w[0] >= cb]):
                txt = "".join(w[3] for w in ln)
                if FURNITURE.match(txt):
                    continue
                # 长括注(例如:…、…等)会折行,续行仍以中文开头,骗过"必以中文开头"那道闸,
                # 于是 "槭树糖浆等）" 被当成一个类别。只要上一条目的括号还没闭合,本行就是续行。
                if depth > 0:
                    depth += balance(txt)
                    continue
                if not re.match(r"[一-鿿]", txt):     # 拉丁学名折行 → 并回上一节点,不建节点
                    continue
                depth = max(0, balance(txt))
                name = clean(txt)
                if not name or len(name) > 20:
                    continue
                x0 = ln[0][0]
                lvl = min(range(len(anchors)), key=lambda i: abs(anchors[i] - x0)) + 1
                # 先入栈再发边:根未解析(major=None)时 L1 边要丢,但 L1 节点【仍须进栈】,
                # 否则它下面的 L2/L3 会一起断掉 —— 一条根名没拼对,不该赔上整棵子树。
                stack[lvl] = name
                for d in range(lvl + 1, 4):
                    stack.pop(d, None)          # 下钻的更深层已作废
                parent = major if lvl == 1 else stack.get(lvl - 1)
                if not parent or parent == name:
                    continue
                # 键里【必须】带 year:类别会跨版改名(蛋白饮料→蛋白饮料类、果蔬汁类→果蔬汁类及其饮料),
                # 跨版共用一张父表会把 A 版的父安到 B 版的子身上 —— 又是一条假边。
                edges.setdefault((name, parent, yr), lvl)
    return edges


def sha256_file(path):
    """Return the SHA-256 digest of a file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_for_year(source_dir, year):
    """Resolve and verify one full-edition source PDF."""

    candidates = sorted(
        path
        for path in Path(source_dir).glob(f"GB 2762-{year}*.pdf")
        if "修改单" not in path.name
    )
    if len(candidates) != 1:
        raise ValueError(
            f"expected one full GB 2762-{year} source, found {len(candidates)}"
        )
    source = candidates[0]
    observed = sha256_file(source)
    expected = SOURCE_DIGESTS[year]
    if observed != expected:
        raise ValueError(
            f"GB 2762-{year} source digest differs: expected {expected}, got {observed}"
        )
    return source


def load_known_categories(path):
    """Read category names used to adjudicate ambiguous vertical major labels."""

    rows = read_locked_csv(
        path, RELEASE_DEPENDENCY_SPECS["pollutant_old_path.csv"]
    )
    known = {clean(row["food_category"]) for row in rows}
    known |= {
        "水果及其制品",
        "蔬菜及其制品",
        "豆类及其制品",
        "食用菌及其制品",
        "藻类及其制品",
        "谷物及其制品",
        "淀粉及淀粉制品",
        "特殊膳食用食品",
        "其他类",
        "焙烤食品",
        "冷冻饮品",
        "酒类",
        "可可制品、巧克力和巧克力制品以及糖果",
        "食糖及淀粉糖",
    }
    return known


def rebuild(source_dir, known_categories_path, output_path):
    """Rebuild the taxonomy and require the locked byte identity."""

    known = load_known_categories(known_categories_path)
    edges = {}
    unresolved = []
    source_metadata = {}
    for year in YEARS:
        source = source_for_year(source_dir, year)
        source_metadata[year] = {
            "filename": source.name,
            "sha256": SOURCE_DIGESTS[year],
        }
        for key, value in parse_version(source, year, known, unresolved).items():
            edges.setdefault(key, value)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        with temporary_path.open(
            "w", encoding="utf-8-sig", newline=""
        ) as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["child", "parent", "level", "src_year"])
            for (child, parent, year), level in sorted(edges.items()):
                writer.writerow([child, parent, level, year])
        observed = sha256_file(temporary_path)
        if observed != EXPECTED_OUTPUT_SHA256:
            raise ValueError(
                "replayed food taxonomy digest differs: "
                f"expected {EXPECTED_OUTPUT_SHA256}, got {observed}"
            )
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return {
        "rows": len(edges),
        "sha256": observed,
        "unresolved_major_cells": [
            {"version_year": year, "candidate": candidate}
            for year, candidate in unresolved
        ],
        "sources": source_metadata,
    }


def parse_args(argv=None):
    """Parse explicit source and output paths."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument(
        "--known-categories", type=Path, default=DEFAULT_KNOWN_CATEGORIES
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv=None):
    """Run the fail-closed taxonomy replay."""

    args = parse_args(argv)
    report = rebuild(args.source_dir, args.known_categories, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
