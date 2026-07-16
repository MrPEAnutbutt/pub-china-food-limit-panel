#!/usr/bin/env python3
"""食品类别英文名 · 从 USDA GAIN 英译本【连接】出来,不做机器翻译

发布包此前没有食品类别的英文名,理由是"标准不印英文,机翻等于造数据"。理由本身对,
结论下早了 —— 标准自己不印,但**别人替它印了**:USDA FAS 的 GAIN 报告为农产品贸易
合规做了全文英译,公开、免费、可引、可追责,且逐条对应标准自身的条目。我们只做连接,
不做翻译。英译本由 ``--translations-dir`` 显式指定，原文件名保留不变。

难点:英译本是**英文单语**(没有中英对照),而我们的长表已按名称排过序(**不保源顺序**)。
所以既不能按字符串连,也不能按行序连。

用【值签名】连:一个食品在整版标准里、跨所有物质的限量值向量,几乎是唯一指纹。

    小麦  → {(2,4-D, 2.0), (Glyphosate, 5.0), (Chlorpyrifos, 0.5), …}
    Wheat → {(2,4-D, 2.0), (Glyphosate, 5.0), (Chlorpyrifos, 0.5), …}

两侧共用【物质英文名】当键 —— 物质名是标准自己印的双语(已在 entity_names_en.csv),
是唯一不靠我们判断的桥。签名相同 = 同一个食品;签名对不上 = 不收,留空。

添加剂不需要签名:GB 2760 的食品分类号(01.02.02)在中英文本里是同一个码,按码直连,
再用同一条的最大使用量是否相等来验证码确实连对了。

★ 证伪:把英文侧的食品标签在版内随机重排后重跑同一算法。匹配率的【落差】才是证据强度,
   匹配率本身不是。一个不会失败的检查不是证据。
"""
import argparse
import csv
import hashlib
import json
import random
import re
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

from source_acquisition_metadata import TRANSLATION_PDFS

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RELEASE_DIR = REPO_ROOT / "Data" / "Final" / "china_food_limit_panel_v1"
DEFAULT_TRANSLATIONS_DIR = REPO_ROOT / "Data" / "Raw" / "外部英译本"
DEFAULT_REPORT_OUTPUT = REPO_ROOT / "Results" / "temp" / "datapaper" / "food_en_report.json"
NS = "{http://www.w3.org/1999/xhtml}"
random.seed(20260715)

FOD_KEY = re.compile(r"^FOD-[0-9a-f]{16}$")

SRC = {
    "pesticide": "USDA FAS, unofficial English translation of GB 2763-2016",
    "additive": "USDA FAS Beijing, unofficial English translation of GB 2760-2014",
    "contaminant": "USDA FAS GAIN CH2023-0040, unofficial English translation of GB 2762-2022",
}
CROSS = "USDA FAS GAIN CH2019-0170, unofficial English translation of GB 2763-2019"

PAGE = re.compile(r"GB\s*2763-\d{4}|GB\s*2762-\d{4}|GB2760-\d{4}")
ITEM = re.compile(r"^(.+?)\s+(\d+(?:\.\d+)?)\s*\*?$")
# 只挡真噪声。★ 别在这里放裸的 [a-z]:开了 re.I 之后它会吃掉每一个字母开头的行(第一版就栽在这)。
NOTE = re.compile(r"^(\*|Note[:\s]|The MRL|Temporary|Residue definition|ADI[:\s]|Major purpose|"
                  r"Maximum residue|Table\b|Food Category|Appendix|Annex|Specifications|"
                  r"[a-z]$|\d+$)", re.I)

def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_translation_files(translations_dir, expected=None):
    """锁定英译本文件名与内容；任一文件缺失或变化都在解析前终止。"""
    expected = TRANSLATION_PDFS if expected is None else expected
    paths = {}
    for filename, wanted_digest in expected.items():
        path = Path(translations_dir) / filename
        if not path.is_file():
            raise FileNotFoundError(f"required translation PDF is missing: {path}")
        actual_digest = file_sha256(path)
        if actual_digest != wanted_digest:
            raise ValueError(
                "translation PDF SHA256 mismatch for "
                f"{filename}: expected {wanted_digest}, got {actual_digest}"
            )
        paths[filename] = path
    return paths


def raw(translations_dir, name):
    path = Path(translations_dir) / name
    return subprocess.run(
        ["pdftotext", "-raw", path, "-"],
        capture_output=True,
        check=True,
        timeout=900,
    ).stdout.decode("utf-8", "replace").splitlines()


def fnum(s):
    """限量值归一。'0.2*'(临时限量)与 '0.2' 是同一个值:星号是状态,不是数值。"""
    s = (s or "").strip().replace("*", "").replace(",", "")
    try:
        return round(float(s), 6)
    except ValueError:
        return None


def rd(release_dir, filename):
    with (Path(release_dir) / filename).open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def pesticide_entity_names_by_key(entity_rows):
    """以稳定的 ``pesticide_key`` 连接农药英文名，并拒绝键级冲突。"""
    names = {}
    for row in entity_rows:
        if row.get("entity_type") != "pesticide":
            continue
        key = (row.get("entity_key") or "").strip()
        name = (row.get("name_en") or "").strip()
        if not key or not name:
            raise ValueError("pesticide entity row is missing entity_key or name_en")
        if key in names and norm(names[key]) != norm(name):
            raise ValueError(f"pesticide_key has conflicting English names: {key}")
        names[key] = name
    return names


def attach_pesticide_food_keys(matches, reasons, pesticide_rows):
    """把标签级匹配落到稳定 ``FOD-*`` 键，并拒绝一对多歧义。"""
    label_keys = defaultdict(set)
    for row in pesticide_rows:
        label = (row.get("food_zh") or "").strip()
        key = (row.get("food_key") or "").strip()
        if not label:
            continue
        if not FOD_KEY.fullmatch(key):
            raise ValueError(f"invalid or missing pesticide food_key for {label!r}: {key!r}")
        label_keys[label].add(key)

    label_conflicts = {
        label: sorted(keys) for label, keys in label_keys.items() if len(keys) > 1
    }
    if label_conflicts:
        label = sorted(label_conflicts)[0]
        raise ValueError(
            f"pesticide food label maps to multiple food_keys: {label!r} -> "
            f"{label_conflicts[label]}"
        )

    candidates = defaultdict(list)
    for food_zh, food_en in matches.items():
        keys = label_keys.get(food_zh, set())
        if len(keys) != 1:
            raise ValueError(f"matched pesticide food label has no unique food_key: {food_zh!r}")
        key = next(iter(keys))
        candidates[key].append((food_zh, food_en, reasons[food_zh]))

    keyed = {}
    aliases = {}
    conflicts = {}
    for key, values in sorted(candidates.items()):
        english_names = {norm(food_en) for _, food_en, _ in values}
        if len(english_names) > 1:
            conflicts[key] = sorted(
                {f"{food_zh} -> {food_en}" for food_zh, food_en, _ in values}
            )
            continue
        chosen = sorted(values, key=lambda value: (value[0], value[1]))[0]
        keyed[key] = {
            "food_zh": chosen[0],
            "food_en": chosen[1],
            "reason": chosen[2],
        }
        if len(values) > 1:
            aliases[key] = sorted({food_zh for food_zh, _, _ in values})
    return keyed, aliases, conflicts


def write_csv_lf(path, fieldnames, rows):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


# ───────────────────── 英译本解析(保守:宁可漏,不可错) ─────────────────────
def parse_2763_en(lines):
    """'4.N <英文农药名>' 段下是该农药的限量表。返回 (pest_en, food_en, val)。"""
    SEC = re.compile(r"^4\.\d+\s+(.+?)\s*$")
    out, pest = [], None
    for r0 in lines:
        line = PAGE.sub(" ", r0).strip()
        if not line:
            continue
        m = SEC.match(line)
        if m and "...." not in line and not NOTE.match(m.group(1)):
            pest = m.group(1).strip()
            continue
        if pest is None or NOTE.match(line):
            continue
        m = ITEM.match(line)
        if not m:
            continue
        food, v = m.group(1).strip(), fnum(m.group(2))
        if v is not None and len(food) >= 2 and not NOTE.match(food):
            out.append((pest, food, v))
    return out


def parse_2762_en(translations_dir, pdf):
    """GB 2762 英译本按坐标读 —— 与我们抽中文源是同一套办法,理由也一样:
    -raw 把名和值拆成两块,-layout 也拼不回来(类别名跨行,且续行排在【值之后】)。

    两个坑:
    · '4.1' 与 'Lead' 是【两个独立的 line】,所以物质名不能从 '4.N xxx' 取,
      改从表标题 'Table 1: Lead Limits in Foods' 取(整句在一个 line 里)。
    · 汞/砷/亚硝酸盐是【双值列】表(总汞|甲基汞)。单值列的假设在这里会把两列的数
      混成一个物质 —— 那正是本文批判的错误。检测到两个数值列就整页跳过,并记账。
    """
    path = Path(translations_dir) / pdf
    xml = subprocess.run(
        ["pdftotext", "-bbox-layout", path, "-"],
        capture_output=True,
        timeout=600,
    ).stdout.decode("utf-8", "replace")
    CAP = re.compile(r"Table\s+\d+\s*[:.]?\s*(.+?)\s+limits?\s+in\s+foods?", re.I)
    NUMONLY = re.compile(r"^\d+(?:\.\d+)?$")
    out, analyte, skipped = [], None, []
    for pno, page in enumerate(ET.fromstring(xml).iter(NS + "page"), 1):
        lines = []
        for ln in page.iter(NS + "line"):
            ws = [(w.text or "").strip() for w in ln.iter(NS + "word")]
            ws = [w for w in ws if w]
            if not ws:
                continue
            lines.append(dict(t=" ".join(ws), y=(float(ln.get("yMin")) + float(ln.get("yMax"))) / 2,
                              x0=float(ln.get("xMin")), x1=float(ln.get("xMax"))))
        for ln in lines:
            m = CAP.search(PAGE.sub("", ln["t"]).strip())
            if m:
                analyte = m.group(1).strip()
        if analyte is None:
            continue
        # ★ 段号("4.1")和页码("1")也是纯数字行,都排在左页边(x≈54)。它们会被聚成
        #   "第二个数值列",害得每一页都被误判成双列表。限量值都在右列,只认 x>350。
        nums = [line for line in lines if NUMONLY.match(line["t"]) and line["x0"] > 350]
        if len(nums) < 2:
            continue
        cols, xs = [], sorted(line["x0"] for line in nums)
        for x in xs:
            if cols and x - cols[-1][-1] <= 25:
                cols[-1].append(x)
            else:
                cols.append([x])
        cols = [c for c in cols if len(c) >= 2]
        if not cols:
            continue
        if len(cols) > 1:                                   # 真·双值列 → 不猜,整页跳过
            skipped.append((pno, analyte))
            continue
        vx = min(cols[0])
        vals = [line for line in nums if abs(line["x0"] - vx) <= 25]
        names = [line for line in lines
                 if not NUMONLY.match(line["t"]) and len(line["t"]) > 2
                 and line["x1"] < vx + 5
                 and not NOTE.match(PAGE.sub("", line["t"]).strip())
                 and not CAP.search(line["t"])
                 and not re.match(r"^\d+\.\d+", line["t"])]
        buckets = defaultdict(list)
        for n in names:                                     # 每个名字行归到 y 最近的值行
            i = min(range(len(vals)), key=lambda j: abs(n["y"] - vals[j]["y"]))
            buckets[i].append(n)
        for i, v in enumerate(vals):
            food = re.sub(r"\s+", " ", PAGE.sub("", " ".join(
                n["t"] for n in sorted(buckets[i], key=lambda n: n["y"]))).strip())
            val = fnum(v["t"])
            if food and val is not None and len(food) >= 3:
                out.append((analyte, food, val))
    return out, skipped


def parse_2760_en(lines):
    """两样东西:① 附录 E.1 = 完整的【分类号 → 英文食品类别名】(标准自己的分类系统);
       ② 表 A.1 = 每个添加剂(带 CNS 号)下的 '分类号 英文类别名 最大使用量',用来验证 ①。"""
    # ★ 取【最后】一次出现:第一次是目录行("Appendix E.1 …………179"),
    #   按它切片会把正文表 A.1 整个划到附录侧,CNS 号一条都读不到。
    i0 = max(i for i, line in enumerate(lines) if line.strip().startswith("Appendix E.1"))
    # ★ 顺序要紧:'01.0' 必须先于 '01' 匹配,否则 01.0 被读成 01,顶层类别全丢。
    CODE = re.compile(r"^(\d{2}\.0|\d{2}(?:\.\d{2}){1,4})(?:\s+(.*))?$")
    SKIP = re.compile(r"^(Category No\.|Table E\.1|Please refer|Appendix)")
    # ★ 跨行续接必须知道【什么时候停】。16.07 是附录 E 的最后一条,不设停止条件的话,
    #   它会把后面的页码和译者注("Note: the original Index was formulated…")全吞进类别名。
    #   这个错是 validate 的 check_food_en 首跑抓到的 —— 发布出去的英文名在源文件里
    #   逐字找不到,就说明它不是从那份文件里来的。
    STOP = re.compile(r"^(Note[:\s]|Index\b)")
    cats, cur = {}, None
    for r0 in lines[i0:]:
        line = re.sub(r"^\d{0,3}GB2760-\d{4}\s*", "", r0.strip())
        if not line or SKIP.match(line):
            continue
        if STOP.match(line):
            break
        if re.fullmatch(r"\d{1,4}", line):                   # 页码,不是类别名的续行
            continue
        m = CODE.match(line)
        if m:
            cur = m.group(1)
            cats[cur] = (m.group(2) or "").strip()
        elif cur and len(cats[cur]) < 150:                   # 类别名跨行续接
            cats[cur] = (cats[cur] + " " + line).strip()
    cats = {k: v for k, v in cats.items() if v and v != "--"}

    ROW = re.compile(r"^(\d{2}\.0|\d{2}(?:\.\d{2}){1,4})\s+(.+?)\s+(\d+(?:\.\d+)?)\s*$")
    CNS = re.compile(r"^CNS\s+([\d.,\s]+?)\s+INS")
    rows, cns_en, prev, cur_cns = [], {}, "", None
    for r0 in lines[:i0]:
        line = r0.strip()
        if not line:
            continue
        m = CNS.match(line)
        if m:
            name = PAGE.sub("", prev).strip()
            if name and not NOTE.match(name) and not ROW.match(name):
                codes = [c.strip() for c in m.group(1).split(",") if c.strip()]
                for c in codes:
                    cns_en[c] = name
                cur_cns = codes[0]
            prev = line
            continue
        m = ROW.match(line)
        if m and cur_cns:
            v = fnum(m.group(3))
            if v is not None:
                rows.append((cur_cns, m.group(1), m.group(2).strip(), v))
        prev = line
    return cats, cns_en, rows


# ───────────────────────── 值签名匹配(核心) ─────────────────────────
# 闸门不是拍脑袋定的:扫过 (2,2)…(5,5),用【跨译本一致率】当标尺(打乱负对照在所有档位
# 都是 0,不具区分力)。(4,4) 同时优于 (5,5):匹配更多(114 vs 103)且一致率更高(97.4% vs 96.9%)。
# 再放松到 (3,3) 只多买到 2pp 的记录覆盖,一致率却掉到 95.7% —— 不换。错值比缺值危险得多。
MIN_SIG = 4      # 签名下限:靠一两个(农药,值)巧合配上的不算证据
MIN_OVL = 4      # Jaccard 路径的交集下限
MARGIN = 0.08    # 必须显著优于次优 —— 并列 = 不可判,不是"从中选一个"


def signature_match(zh, en, thr=0.60, shuffle=False):
    """zh/en 三元组 = (物质英文名, 食品名, 值);物质英文名是两侧共享的键。
    签名 = frozenset{(物质, 值)}。

    三道闸,全过才收:
      ① 签名要够长(≥MIN_SIG)。第一版没设这道闸,结果「哺乳动物肉类」靠一个农药的一个
         值就配上了 "Poultry meat" —— 家禽和哺乳动物在很多农药上限量相同,一个巧合
         什么也证明不了。
      ② 两侧都不能有并列。签名完全相同的两个食品(笋瓜/西葫芦这类)在数据里【本就不可分】,
         该判"不可判",而不是硬选一个。第一版让并列从 Jaccard 通道漏了出去,配出了
         「笋瓜 → Horseradish」。
      ③ 最佳必须显著优于次优(≥MARGIN),且互为最佳。
    """
    if shuffle:
        labs = [t[1] for t in en]
        random.shuffle(labs)
        en = [(p, labs[i], v) for i, (p, _, v) in enumerate(en)]

    zs, es = defaultdict(set), defaultdict(set)
    for p, f, v in zh:
        zs[f].add((p, v))
    for p, f, v in en:
        es[f].add((p, v))
    zs = {k: frozenset(v) for k, v in zs.items() if len(v) >= MIN_SIG}
    es = {k: frozenset(v) for k, v in es.items() if len(v) >= MIN_SIG}

    pairs, why = {}, {}
    zby, eby = defaultdict(list), defaultdict(list)
    for f, s in zs.items():
        zby[s].append(f)
    for f, s in es.items():
        eby[s].append(f)
    used = set()
    for s, zf in zby.items():
        ef = eby.get(s, [])
        if len(zf) == 1 and len(ef) == 1:                  # 唯一对唯一,无并列
            pairs[zf[0]] = ef[0]
            why[zf[0]] = ("exact_signature", len(s))
            used.add(ef[0])

    rz = [f for f in zs if f not in pairs]
    re_ = [g for g in es if g not in used]
    if rz and re_:
        def sc(a, b):
            """(Jaccard, 交集大小)。交集太小的一律判 0 —— 相似度高但只重合两条,是巧合。"""
            i, u = len(a & b), len(a | b)
            return (i / u if u and i >= MIN_OVL else 0.0)

        def top2(f, pool, key):
            v = sorted(((sc(zs[f], es[g]) if key else sc(zs[g], es[f]), g) for g in pool),
                       reverse=True)
            return (v + [(0.0, None), (0.0, None)])[:2]

        bz = {f: top2(f, re_, True) for f in rz}
        be = {g: top2(g, rz, False) for g in re_}
        for f, ((s1, g), (s2, _)) in bz.items():
            if g is None or s1 < thr or s1 - s2 < MARGIN:   # 不够好,或与次优并列 → 不可判
                continue
            (e1, ef), (e2, _) = be[g]
            if ef == f and e1 - e2 >= MARGIN:               # 互为最佳,且对面也不并列
                pairs[f] = g
                why[f] = ("mutual_best_jaccard", round(s1, 3))
    return pairs, why, len(zs), len(es)


def bridge_names(zh_names, en_names):
    """物质名桥:两侧归一后直配;剩下的按字符 3-gram 互为最佳。返回 zh_en_key -> en_sec_name。"""
    en_by = defaultdict(list)
    for s in en_names:
        en_by[norm(s)].append(s)
    out, left_z, left_e = {}, [], []
    for z in zh_names:
        k = norm(z)
        if k in en_by:
            out[z] = en_by[k][0]
        else:
            left_z.append(z)
    taken = set(out.values())
    left_e = [s for s in en_names if s not in taken]

    def g3(s):
        s = norm(s)
        return {s[i:i + 3] for i in range(max(1, len(s) - 2))}
    if left_z and left_e:
        for z in left_z:
            a = g3(z)
            c = max(((len(a & g3(e)) / max(1, len(a | g3(e))), e) for e in left_e), default=(0, None))
            if c[0] >= 0.70:
                out[z] = c[1]
    return out


def build_parser():
    parser = argparse.ArgumentParser(
        description="Link English food-category names from USDA translation PDFs.",
    )
    parser.add_argument(
        "--release-dir",
        type=Path,
        default=DEFAULT_RELEASE_DIR,
        help=(
            "Release-package directory containing the input CSV files and receiving "
            "the two English-name CSV files. Defaults to "
            "Data/Final/china_food_limit_panel_v1 under the repository root."
        ),
    )
    parser.add_argument(
        "--translations-dir",
        type=Path,
        default=DEFAULT_TRANSLATIONS_DIR,
        help=(
            "Directory containing the four translation PDFs under their original "
            "filenames. Defaults to Data/Raw/外部英译本 under the repository root."
        ),
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        default=DEFAULT_REPORT_OUTPUT,
        help=(
            "JSON report file. Defaults to "
            "Results/temp/datapaper/food_en_report.json under the repository root."
        ),
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    release_dir = args.release_dir.expanduser()
    translations_dir = args.translations_dir.expanduser()
    report_output = args.report_output.expanduser()

    if not release_dir.is_dir():
        raise FileNotFoundError(f"release directory does not exist: {release_dir}")
    if not translations_dir.is_dir():
        raise FileNotFoundError(f"translations directory does not exist: {translations_dir}")

    verify_translation_files(translations_dir)
    rep = {"note": "英文食品类别名 = 从 USDA GAIN 英译本连接,非机器翻译。"
                   "英译本由 --translations-dir 提供,原文件名保留不变。",
           "sources": SRC,
           "translation_pdf_sha256": TRANSLATION_PDFS,
           "families": {}}
    rows_out, ent_out = [], []

    # ═════════ 1. 添加剂:按食品分类号直连,用最大使用量验证 ═════════
    cats_en, cns_en, a1 = parse_2760_en(
        raw(translations_dir, "GAIN_GB2760-2014_en.pdf")
    )
    add = rd(release_dir, "additive_limits_long.csv")
    code_zh, code_ver = {}, defaultdict(set)
    for r in add:
        c = r["food_code"].strip()
        if c:
            code_zh.setdefault(c, r["food_zh"])
            code_ver[c].add(r["version_year"])
    hit = {c for c in code_zh if c in cats_en}

    ours14 = {}
    for r in add:
        if r["version_year"] == "2014" and r["cns_code"].strip() and r["food_code"].strip():
            v = fnum(r["max_use"])
            if v is not None:
                ours14[(r["cns_code"].strip(), r["food_code"].strip())] = v
    ag = tot = 0
    for cns, code, _e, v in a1:
        if (cns, code) in ours14:
            tot += 1
            ag += abs(ours14[(cns, code)] - v) < 1e-9
    shuf = [x[3] for x in a1]
    random.shuffle(shuf)
    sag = stot = 0
    for (cns, code, _e, _v), v in zip(a1, shuf):
        if (cns, code) in ours14:
            stot += 1
            sag += abs(ours14[(cns, code)] - v) < 1e-9

    for c in sorted(hit):
        rows_out.append(dict(family="additive", food_key=c, food_zh=code_zh[c],
                             food_en=cats_en[c], match_method="food_category_code",
                             evidence="exact code join, value-verified", source_doc=SRC["additive"]))
    rep["families"]["additive"] = {
        "codes_in_data": len(code_zh), "codes_matched": len(hit),
        "coverage": round(len(hit) / len(code_zh), 4),
        "coverage_by_version": {v: round(sum(c in cats_en for c in code_ver if v in code_ver[c])
                                         / sum(v in s for s in code_ver.values()), 4)
                                for v in sorted({x for s in code_ver.values() for x in s})},
        "value_check_pairs": tot,
        "value_agreement_real": round(ag / tot, 4) if tot else None,
        "value_agreement_shuffled": round(sag / stot, 4) if stot else None,
        "unmatched_codes": sorted(set(code_zh) - hit),
    }

    # 添加剂英文名:按 CNS 号连(原先判"词边界不可恢复"而放弃,英译本直接印着)
    seen = set()
    for r in add:
        c = r["cns_code"].strip()
        if c and c in cns_en and c not in seen:
            seen.add(c)
            ent_out.append(dict(entity_type="food_additive", name_zh=r["additive_zh"],
                                name_en=cns_en[c], cns_code=c, source_standard="GB 2760",
                                source_doc=SRC["additive"]))
    ncns = len({r["cns_code"].strip() for r in add if r["cns_code"].strip()})
    rep["families"]["additive"]["additive_names_en"] = len(ent_out)
    rep["families"]["additive"]["additive_cns_in_data"] = ncns
    rep["families"]["additive"]["additive_name_coverage"] = round(len(ent_out) / ncns, 4)
    rep["families"]["additive"]["coverage_of_records"] = round(
        sum(r["food_code"].strip() in hit for r in add) / len(add), 4)

    # ═════════ 2. 农残:值签名匹配(GB 2763-2016,同版) ═════════
    p2en = pesticide_entity_names_by_key(rd(release_dir, "entity_names_en.csv"))
    allrow = rd(release_dir, "pesticide_limits_long.csv")
    pes = [r for r in allrow if r["version_year"] == "2016"]
    missing_entity_keys = sorted({
        r.get("pesticide_key", "") for r in pes if r.get("pesticide_key", "") not in p2en
    })
    if missing_entity_keys:
        raise ValueError(
            "2016 pesticide rows have keys missing from entity_names_en.csv: "
            f"{missing_entity_keys[:5]}"
        )
    etri = parse_2763_en(raw(translations_dir, "FSIS_GB2763-2016_en.pdf"))
    br = bridge_names(sorted({p2en[r["pesticide_key"]] for r in pes}),
                      sorted({t[0] for t in etri}))
    ztri = [(br[p2en[r["pesticide_key"]]], r["food_zh"], fnum(r["limit_value"])) for r in pes
            if p2en[r["pesticide_key"]] in br
            and fnum(r["limit_value"]) is not None]
    pr, wy, nz, ne = signature_match(ztri, etri)
    sp, _, _, _ = signature_match(ztri, etri, shuffle=True)

    # 交叉复核:换一份【由不同译者做的】英译本(GB 2763-2019),对同一份中文数据重跑,
    # 看两份字典是否给出同一个名字。这是唯一的外部检验 —— 打乱负对照在所有闸门档位都是 0,
    # 不具区分力;真正能证伪我们的,是另一队人独立译出的名字。
    etri19 = parse_2763_en(
        raw(translations_dir, "GAIN_CH2019-0170_GB2763-2019_en.pdf")
    )
    br19 = bridge_names(sorted({p2en[r["pesticide_key"]] for r in pes}),
                        sorted({t[0] for t in etri19}))
    z19 = [(br19[p2en[r["pesticide_key"]]], r["food_zh"], fnum(r["limit_value"])) for r in pes
           if p2en[r["pesticide_key"]] in br19
           and fnum(r["limit_value"]) is not None]
    pr19, _, _, _ = signature_match(z19, etri19)
    both = set(pr) & set(pr19)
    conflict = sorted(f for f in both if norm(pr[f]) != norm(pr19[f]))

    # ★ 两份独立译本给出【不同】名字的,一条也不发。
    #   唯一的分歧是「瓜果类水果」:2016 译本读成 'Melons Fruits'(组标题粘进了条目名),
    #   2019 译本读成 'Melons'。交叉复核抓到的是一个真的解析瑕疵 —— 那就别发,
    #   因此不从两个候选中主观选取一个名字。
    for f in conflict:
        pr.pop(f, None)

    keyed_foods, food_key_aliases, food_key_conflicts = attach_pesticide_food_keys(
        pr, wy, allrow
    )
    for food_key, matched in sorted(keyed_foods.items()):
        rows_out.append(dict(family="pesticide", food_key=food_key,
                             food_zh=matched["food_zh"], food_en=matched["food_en"],
                             match_method=matched["reason"][0],
                             evidence=f"{matched['reason'][1]}",
                             source_doc=SRC["pesticide"]))

    # 诚实的分母采用中文食品名全集；仅计算达到签名门槛的食品会抬高覆盖率。
    # 签名短于 MIN_SIG 的食品根本没进匹配,它们要算进分母,否则覆盖率是自己抬的。
    all_zh = {r["food_zh"] for r in pes}
    named_food_keys = set(keyed_foods)
    shipped_food_labels = {matched["food_zh"] for matched in keyed_foods.values()}
    shipped_food_labels.update(
        food_zh for labels in food_key_aliases.values() for food_zh in labels
    )
    named_rows = sum(r["food_key"] in named_food_keys for r in allrow)
    rep["families"]["pesticide"] = {
        "pesticides_bridged": len(br),
        "zh_foods_total": len(all_zh),
        "zh_foods_with_signature_ge_%d" % MIN_SIG: nz,
        "en_foods": ne,
        "shipped": len(keyed_foods),
        "food_labels_shipped": len(shipped_food_labels),
        "food_keys_total_all_versions": len({r["food_key"] for r in allrow}),
        "food_key_aliases_collapsed": food_key_aliases,
        "food_key_conflicts_dropped": food_key_conflicts,
        "coverage_of_all_food_names": round(len(shipped_food_labels) / len(all_zh), 4),
        "coverage_of_eligible_food_names": (
            round(len(shipped_food_labels) / nz, 4) if nz else None
        ),
        "coverage_of_mrl_records_all_versions": round(named_rows / len(allrow), 4),
        "matched_shuffled_control": len(sp),
        "gap": len(shipped_food_labels) - len(sp),
        "method_mix": dict(Counter(wy[f][0] for f in shipped_food_labels)),
        "unnamed_note": "签名短于 %d 的食品(只在极少数农药下出现)信息量不足以判定,留空不猜。" % MIN_SIG,
        "cross_source_check": {
            "second_source": CROSS,
            "note": "同一份中文 2016 数据,改用 2019 版英译本(不同译者、跨一版)重跑;"
                    "两份字典都命名的食品里,有多少给的是同一个名字",
            "foods_named_by_both": len(both),
            "agree": len(both) - len(conflict),
            "agreement": round((len(both) - len(conflict)) / len(both), 4) if both else None,
            "conflicts_dropped": conflict,
            "rule": "两份译本给出不同名字 → 一条也不发。",
        },
    }

    # ═════════ 3. 污染物:值签名匹配(GB 2762-2022,同版) ═════════
    pol = [r for r in rd(release_dir, "pollutant_limits_long.csv")
           if r["version_year"] == "2022"]
    ztri2 = [(r["analyte_en"] or r["analyte_zh"], r["food_category_zh"],
              fnum(r["limit_mgkg"] or r["limit_value"])) for r in pol
             if fnum(r["limit_mgkg"] or r["limit_value"]) is not None]
    etri2, skipped2 = parse_2762_en(
        translations_dir,
        "GAIN_CH2023-0040_GB2762-2022_en.pdf",
    )
    br2 = bridge_names(sorted({t[0] for t in ztri2}), sorted({t[0] for t in etri2}))
    ztri2 = [(br2[p], f, v) for p, f, v in ztri2 if p in br2]
    pr2, wy2, nz2, ne2 = signature_match(ztri2, etri2)
    sp2, _, _, _ = signature_match(ztri2, etri2, shuffle=True)
    # ★ 污染物这一族,方法失败了 —— 一条也不发。
    #   放宽闸门时它确实"配"出 32 条,但打乱负对照也配出 29 条:落差 3。按本文自己立的规矩,
    #   一个打乱后同样能通过的检查不是证据。抽查也证实是错的(乳粉→"fermented milk"、
    #   畜禽肾脏→"Matsutake mushroom")。
    #   病因清楚:值签名要能当指纹,得靠【物质数量】。一个食品在 GB 2763 里跨几百种农药,
    #   指纹几乎唯一;在 GB 2762 里只跨 8 种污染物,限量值又都取自 {0.1,0.2,0.5,1.0}
    #   这样的小集合 —— 信息量根本不够把两个食品分开。这不是参数没调好,是方法在这一族无效。
    #   宁可留空。错的英文名比缺的英文名危险得多。
    ztri2_all = {r["food_category_zh"] for r in pol}
    rep["families"]["contaminant"] = {
        "SHIPPED": 0,
        "verdict": "方法失败,不发布。放宽闸门可得 32 条,但打乱负对照得 29 条(落差 3),"
                   "抽查确认为错配。留空。",
        "analytes_bridged": len(br2), "zh_foods_total": len(ztri2_all),
        "zh_foods_with_signature_ge_%d" % MIN_SIG: nz2, "en_foods": ne2,
        "matched_at_strict_gates": len(pr2), "matched_shuffled_control": len(sp2),
        "gap": len(pr2) - len(sp2),
        "root_cause": "值签名的判别力来自物质数量。GB 2763 一个食品跨数百种农药 → 指纹近乎唯一;"
                      "GB 2762 只跨 8 种污染物、限量值又集中在 {0.1,0.2,0.5,1.0} → 信息量不足以分辨食品。",
        "two_column_pages_skipped": [f"p{p} ({a})" for p, a in skipped2],
        "two_column_note": "汞/砷/亚硝酸盐是双值列表。按单值列去读会把两列的数混成一个物质,"
                           "正是本文批判的那类错误,故整页跳过而不猜。",
    }

    rep["families"]["mycotoxin_and_vetdrug"] = {
        "SHIPPED": 0,
        "verdict": "未尝试。GB 2761/GB 31650 没有找到公开可引的英译本;而且这两族的物质数"
                   "(真菌毒素 5 种、兽药按靶动物分组)比污染物还少,值签名的判别力只会更差 —— "
                   "污染物那一族已经证明这条路走不通。留空。",
    }

    # ═════════ 落盘 ═════════
    write_csv_lf(
        release_dir / "food_category_names_en.csv",
        ["family", "food_key", "food_zh", "food_en", "match_method", "evidence", "source_doc"],
        rows_out,
    )
    write_csv_lf(
        release_dir / "additive_names_en.csv",
        ["entity_type", "name_zh", "name_en", "cns_code", "source_standard", "source_doc"],
        ent_out,
    )
    rep["output"] = {"food_category_names_en.csv": len(rows_out),
                     "additive_names_en.csv": len(ent_out)}
    report_output.parent.mkdir(parents=True, exist_ok=True)
    with report_output.open("w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(rep, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
