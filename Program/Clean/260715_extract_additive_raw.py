#!/usr/bin/env python3
"""GB 2760 三版重抽 —— 改用 `pdftotext -raw`(阅读序)而非 `-layout`(重排版)。

★ 为什么必须换源。GB2760 的 PDF 把字距编码成独立的显示指令,`-layout` 的分栏算法据此
  把一个 token 判成多列,于是【拦腰折断】:

      -layout:            003,                     ← 竟排在 CNS 行【上面】
                 CNS 号 17.  17.
                              004      INS 号 200,
      -raw   :   C N S号 1 7. 0 0 3, 1 7. 0 0 4  I N S号 2 0 0, 2 0 2   ← 顺序完整

  实测 -layout 的产物:
    · CNS 号:2014/2024 有 ~87% 被截成大类号("17.009"→"17"),或把两个号绞成 "17.17.004";
      而 CNS 是添加剂的【永久标识符】、跨版主键 —— 脱氢乙酸(17.009)与其它 17.x 会全部塌成 "17"。
    · food_code:2011 只有 87.9% 合法(12.03 被截成 "12.0")。
    · 食品名:出现 "醋"、"以" 这类碎片。
    · 还有整类添加剂被旧脚本主动放弃(2024 内联单位"5g/kg"+倒序竖排)。

  -raw 里【数字被逐字符加空格,中文不加】,所以只折叠"数字/标点之间"的空格就能还原 token 边界;
  中文即便被两端对齐拉散(如 "按 稀 释 倍 数"),因为最后是无空格拼接,也不受影响。

产物: additive_raw_long.csv (year,additive,cns,ins,food_code,food,max_use,unit,note)
      与旧 -layout 产物对拍见 diff_additive_sources.py
"""
import argparse
import csv
import glob
import os
import re
import subprocess
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "Data" / "Interim" / "additive_extraction"
YEARS = ["2011", "2014", "2024"]

# ⚠ 顶级食品类别号写作 NN.0(01.0 乳及乳制品 / 03.0 冷冻饮品),不是被截尾的 NN.0x。
#   把 `\.\d{2}` 写死会把这一整层判成非法(我一度据此误判"2011 有 12% 的 food_code 被截断")。
CODE = re.compile(r"^\d{2}(?:\.\d{1,2})*$")
NUM = re.compile(r"^\d+(?:\.\d+)?$")
# 内联单位:GB2760-2024 部分添加剂表头不写 /(g/kg),把单位写进值里。
# g/L 用于液态食品(果蔬汁饮料),与 g/kg 【不可直接比较】—— 这就是四维对齐里的单位维。
INLINE = re.compile(r"^(\d+(?:\.\d+)?)(g/kg|mg/kg|g/L|mg/L|g/份)$")
CNS_LINE = re.compile(r"^CNS(?:号)?([\d.,，()ⅰⅱi]*?)(?:INS(?:号)?(.*))?$")
CNS_FRAGMENT = re.compile(r"^[\d.,，()ⅰⅱi]+$")
GMP = "按生产需要适量使用"
QUAR = []          # 出口闸门隔离的行(须人核,不得静默丢弃)
RECENT_LIMIT = 80


def collapse(s):
    """折叠【数字/标点之间】与【ASCII 字母/斜杠之间】的空格。

    -raw 把字距编码成真空格,所以 '1 7. 0 0 3' 要多轮才能并干净;
    内联单位 '0. 2 5g / k g' 同理,并完才认得出是 0.25 g/kg。
    汉字不受影响(它们本来就没空格,或即便被两端对齐拉散,下游也是无空格拼接)。

    ⚠ 字符类里【不能含括号】。曾经含过,后果是 ") 5.0" 的空格被抹掉,**限量值被粘进食品名**:
        "03.0 冷冻饮品(03.04食用冰除外)5.0 可单独…以磷酸根(PO 4 3-)计"
      于是解析器往后找值,抓到了磷酸根分子式 PO₄³⁻ 的【下标 4】当限量。
      CNS 行(17.009(i),17.009(ii))不受影响 —— 它是在 flat(已去掉全部空白)上匹配的,不靠折叠。
    """
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"(?<=[\d.,]) +(?=[\d.,])", "", s)
        s = re.sub(r"(?<=[A-Za-z/]) +(?=[A-Za-z/])", "", s)
        s = re.sub(r"(?<=\d) +(?=[A-Za-z])", "", s)      # '5 g/kg' → '5g/kg'
    return s


# 不能当添加剂名的行:表头,以及【备注的续行】——
# 备注常折行成 "以即饮状态计,相应的固体饮料" / "按稀释倍数增加使用量" / "品类别除外按生产需要适量使用",
# 若它正好落在 CNS 行上方,就会被当成添加剂名(实测 2024 出现过三个这样的假添加剂)。
HDR = (
    "食品分类号",
    "食品名称",
    "最大使用量",
    "使用量",
    "使用量计",
    "残留量",
    "功能",
    "备注",
    "表A",
    "以即饮状态",
    "按稀释倍数",
    "按照稀释倍数",
    "按冲调倍数",
    "按生产需要",
    "品类别除外",
    "载体",
)
BRACKETS = {"(": ")", "（": "）", "[": "]", "［": "］"}


def _remove_alias_parentheses(text):
    alias = re.compile(r"[（(]\s*(?:又名|又称|俗称|简称)")
    while match := alias.search(text):
        stack = []
        end = len(text)
        for index in range(match.start(), len(text)):
            char = text[index]
            if char in BRACKETS:
                stack.append(BRACKETS[char])
            elif char in BRACKETS.values():
                if not stack or stack[-1] != char:
                    break
                stack.pop()
                if not stack:
                    end = index + 1
                    break
        text = text[: match.start()] + text[end:]
    return text


def additive_canon(n):
    # The 2024 phosphate-group heading prints footnote 7 immediately after
    # “磷酸”.  pdftotext flattens the superscript into the grouped entity name.
    n = re.sub(r"(?<=磷酸)7\s*[)）](?=[,，])", "", n)
    marker = re.search(r"\d+\s*[)）]\s*$", n)
    if marker:
        without_marker = n[: marker.start()]
        opens = n.count("(") + n.count("（")
        closes = n.count(")") + n.count("）")
        clean_opens = without_marker.count("(") + without_marker.count("（")
        clean_closes = without_marker.count(")") + without_marker.count("）")
        if closes > opens and clean_opens == clean_closes:
            n = without_marker
    n = re.sub(r"\s+", "", n)
    # Keep stereochemical prefixes such as L(+) and meaningful variants such
    # as 焦糖色(普通法).  Remove each explicit alias parenthesis separately;
    # splitting at the first alias would discard later members in grouped
    # names such as the five sorbitan esters.
    n = _remove_alias_parentheses(n)
    han = list(re.finditer(r"[一-鿿]", n))
    if han and re.search(r"[A-Za-z]{2,}", n[han[-1].end() :]):
        n = n[: han[-1].end()]
    return n


def _name_boundary(line):
    compact = re.sub(r"\s+", "", line)
    if not compact:
        return False
    if any(header in compact for header in HDR):
        return True
    if compact.startswith(("以", "按", "按照", "如用于", "用量", ")", "）", "]", "］")):
        return True
    if compact in {"算", "用", "量"}:
        return True
    if compact.startswith(("量≤", "量<", "量=")):
        return True
    if compact.endswith(("。", "；", ";")):
        return True
    if compact.startswith("品") and any(term in compact for term in ("制品", "糖果")):
        return True
    if "计" in compact or "除外" in compact:
        return True
    if re.search(r"[)）]\d", compact) and not re.search(r"(?:又名|又称|俗称|简称)", compact):
        return True
    if re.match(r"^\d{2}(?:\.\d{1,2})+(?=[一-鿿（([])", compact):
        return True
    if re.fullmatch(r"\d+(?:\.\d+)?", compact):
        return True
    if compact.startswith(("GB2760", "附录", "CNS号", "INS号")):
        return True
    return bool(re.search(r"(?:以|按).*(?:计|增加使用量)$", compact))


def _name_piece(line):
    """Return the printed-name part of one physical line.

    English transliterations can share a line with the Chinese name.  Keep
    meaningful ASCII prefixes inside chemical names, then stop after the last
    Han character plus trailing digits and punctuation before the English
    transliteration begins.
    """
    line = line.rstrip()
    matches = list(re.finditer(r"[一-鿿]", line))
    if not matches:
        return ""
    end = matches[-1].end()
    # Numeric prefixes of an English translation are not part of the Chinese
    # name: "4-苯基苯酚 4-phenylphenol" and
    # "2,4-二氯苯氧乙酸 2,4-dichlorophenoxy...".
    if re.match(
        r"\s+[\d,.'()）\-—\s]*\d[\d,.'()）\-—\s]*[A-Za-z]",
        line[end:],
    ):
        return line[:end].rstrip()
    while end < len(line) and re.match(r"[\s\d,，、;；)）\]］]", line[end]):
        end += 1
    prefix = line[:end]
    opens = sum(prefix.count(char) for char in BRACKETS)
    closes = sum(prefix.count(char) for char in BRACKETS.values())
    if opens > closes:
        tail = line[end:]
        if re.search(r"[A-Za-z]{2,}", tail) and not any(
            closing in tail for closing in BRACKETS.values()
        ):
            return prefix.rstrip()
        return line
    return prefix.rstrip()


def name_from(recent):
    """从 CNS 行【上方】的若干行里取添加剂中文名。

    三个坑,都实测踩过:
      · 英文名与中文名同行 → 必须【截到最后一个汉字为止】。不能用"截到第一个 ASCII 字母",
        因为 β-胡萝卜素 / D-异抗坏血酸 / 5'-肌苷酸二钠 本身就以非汉字开头。英文名不含汉字,
        所以"最后一个汉字"是干净的分界。
      · 中文名太长会折行 → 以表格行、表头和备注为硬边界,回溯整个连续名称块。
      · 上方可能是表头行 → 显式排除。
    """
    parts = []
    started = False
    for line in reversed(recent):
        if _name_boundary(line):
            break
        piece = _name_piece(line)
        if piece:
            parts.insert(0, piece)
            started = True
            if len(parts) >= 10:
                break
        elif started:
            # English transliterations commonly occupy several physical lines
            # between pieces of one long Chinese name, so they are skipped.
            continue
    return additive_canon("".join(parts)) if parts else ""


def _unclosed_brackets(text):
    stack = []
    closing = set(BRACKETS.values())
    for char in text:
        if char in BRACKETS:
            stack.append(BRACKETS[char])
        elif char in closing:
            if not stack or stack[-1] != char:
                return None
            stack.pop()
    return stack


def repair_food_and_note(food, note):
    # In the 2014 text layer, the continued-table header token "备注" is
    # interleaved where the visible rule reads "倍数".  The surrounding
    # fixed wording and the 2011/2024 editions disambiguate this narrow case.
    note = note.replace("按照稀释备注增加使用量", "按照稀释倍数增加使用量")
    # Preserve the sentence boundary between two visually separate note lines.
    note = re.sub(r"([)）]计)(?=固体饮料按)", r"\1；", note)
    # This sentence is the footnote to the whole of Table A.1.  In both the
    # 2011 and 2014 text layers it follows the last visible row and otherwise
    # looks like that row's note.
    if re.fullmatch(
        r"(?:a|1\))?在表A\.1中使用范围以食品分类号和食品名称表示[。.]*",
        note,
    ):
        note = ""
    # A 2011 cross-page row is read in column order as
    # "最大使（仅限植脂末）用量...": the parenthetical is the continuation
    # of the food name, while the text on either side is one note phrase.
    # Restrict the repair to an explicit food-scope qualifier inserted inside
    # "最大使用量" so measurement-basis parentheses remain untouched.
    interleaved_scope = re.match(
        r"^(.*最大使)([（(](?:仅限|限于|只限)[^()（）]+[)）])(用量.*)$",
        note,
    )
    if interleaved_scope:
        prefix, scope, suffix = interleaved_scope.groups()
        food += scope
        note = prefix + suffix
    # A continued food-scope qualifier can follow a complete note on the next
    # physical page.  Move only an exclusion/restriction parenthetical; a
    # measurement-basis parenthetical therefore stays in the note.
    trailing_scope = re.match(
        r"^(.*?)([（(][^()（）]*(?:除外|仅限|只限|限于)[^()（）]*[)）])$",
        note,
    )
    if trailing_scope and trailing_scope.group(1).endswith(("计", "使用量")):
        note, scope = trailing_scope.groups()
        food += scope
    stack = _unclosed_brackets(food)
    if note.startswith("品") and not re.search(
        r"按(?:稀释|冲调)|以.+计|仅限|残留量|最大使用量",
        note,
    ):
        return food + note, ""
    if not stack or stack is None or not note:
        return food, note
    interleaved = re.match(
        r"^((?:(?:相应的)?固体饮料按(?:稀释|冲调)|残留量≤|"
        r"以[^()（）]{1,40}?计))(.*)$",
        note,
    )
    if interleaved:
        marker, remainder = interleaved.groups()
        pending = list(stack)
        for index, char in enumerate(remainder):
            if char in BRACKETS:
                pending.append(BRACKETS[char])
            elif char in BRACKETS.values():
                if not pending or pending[-1] != char:
                    break
                pending.pop()
                if not pending:
                    return food + remainder[: index + 1], marker + remainder[index + 1 :]
    for index, char in enumerate(note):
        if char in BRACKETS:
            stack.append(BRACKETS[char])
        elif char in BRACKETS.values():
            if not stack or stack[-1] != char:
                return food, note
            stack.pop()
            if not stack:
                prefix = note[: index + 1]
                remainder = note[index + 1 :]
                if remainder and not re.search(
                    r"按(?:稀释|冲调)|以.+计|仅限|残留量|最大使用量|固体饮料",
                    remainder,
                ):
                    return food + prefix + remainder, ""
                return food + prefix, remainder
    return food, note


def strip_balanced_bracketed_text(text):
    """Remove balanced parenthetical/category exclusions, including nesting."""
    output = []
    stack = []
    for char in text:
        if char in BRACKETS:
            stack.append(BRACKETS[char])
        elif char in BRACKETS.values() and stack and stack[-1] == char:
            stack.pop()
        elif not stack:
            output.append(char)
    return "".join(output)


def food_has_unexplained_number(food):
    """Detect a number left in a food name after known category syntax is removed."""
    bare = strip_balanced_bracketed_text(food)
    category = r"\d{2}(?:\.\d{1,2})+"
    bare = re.sub(rf"(?<=除){category}(?=外)", "", bare)
    bare = re.sub(rf"{category}(?=类?(?:以外|除外)|外)", "", bare)
    bare = re.sub(r"\d+(?:\.\d+)?%", "", bare)
    return bool(re.search(r"\d", bare))


def heading_markers(recent):
    """Return physical Chinese name pieces after the last hard boundary."""
    markers = []
    for line in reversed(recent):
        if _name_boundary(line):
            break
        piece = _name_piece(line)
        if piece:
            markers.insert(0, re.sub(r"\s+", "", piece))
    return markers


def split_following_heading(note, next_additive, physical_markers=()):
    """Split a prior row note from the following additive heading."""
    if not note or not next_additive:
        return note, ""
    candidates = {next_additive, *physical_markers}
    first_name = re.split(r"[（(,，、]", next_additive, maxsplit=1)[0]
    if len(first_name) >= 2:
        candidates.add(first_name)
    positions = []
    for candidate in candidates:
        start = 0
        while candidate and (position := note.find(candidate, start)) >= 0:
            end = position + len(candidate)
            # Preserve a legitimate measurement-basis phrase such as
            # "以姜黄素计"; a later unprotected occurrence is the heading.
            protected = position > 0 and note[position - 1] == "以" and note[end:end + 1] == "计"
            if not protected:
                positions.append(position)
                break
            start = end
    if not positions:
        return note, ""
    prefix = note[: min(positions)]
    marker = re.match(r"^(\d+)[)）]", prefix)
    referenced = {
        marker
        for candidate in candidates
        for marker in re.findall(r"(\d+)[)）]", candidate)
    }
    if marker and marker.group(1) in referenced:
        return "", repair_entity_note(prefix)
    return prefix, ""


def strip_following_heading(note, next_additive, physical_markers=()):
    """Remove the next additive heading that follows a completed table row."""
    return split_following_heading(note, next_additive, physical_markers)[0]


def repair_entity_note(note):
    """Repair source-rendering damage in a pre-table entity footnote."""
    # GB 2760-2024 p. 74 closes the outer g/kg basis parenthesis before the
    # full stop.  The text layer retains the inner chemical-formula close but
    # drops the outer close.
    return note.replace(
        "5.0g/kg(以即饮状态计,最大使用量以磷酸根(PO43-)计。",
        "5.0g/kg(以即饮状态计,最大使用量以磷酸根(PO43-)计)。",
    )


def valid_food_code(code):
    if code == "00":
        return True
    return bool(CODE.fullmatch(code)) and 1 <= int(code[:2]) <= 16


def food_row_start(token):
    return valid_food_code(token) and ("." in token or token == "00")


def split_concatenated_food_codes(token):
    """Undo collapse of adjacent codes such as 02.03 + 02.02."""
    if CODE.fullmatch(token):
        return [token]
    for index in range(4, len(token) - 3):
        left, right = token[:index], token[index:]
        if valid_food_code(left) and valid_food_code(right):
            return [left, right]
    return [token]


def entity_note_for_food(entity_note, food_code):
    """Attach a pre-table footnote to the category branch it explicitly cites."""
    if not entity_note:
        return ""
    references = re.findall(r"\d{2}(?:\.\d{1,2})+", entity_note)
    if not references or any(reference.startswith(food_code) for reference in references):
        return entity_note
    return ""


def relocate_misordered_entity_notes(rows):
    """Move two page-foot notes whose PDF reading order precedes/follows another entity.

    Both notes identify their target additive in their own text.  The visual
    pages confirm that they are entity-level footnotes, so the note is copied
    to every rule for that additive in the same edition, matching the normal
    entity-note behaviour elsewhere in this extractor.
    """
    target_rules = (
        (re.compile(r"^a包括轻质和重质碳酸钙[。.]*$"), "碳酸钙"),
        (re.compile(r"^3\).*阿斯巴甜"), "阿斯巴甜"),
    )
    relocated = list(rows)
    for index, row in enumerate(list(relocated)):
        note = row[8]
        target = next(
            (name for pattern, name in target_rules if pattern.search(note)),
            "",
        )
        if not target or row[1] == target:
            continue
        targets = [
            target_index
            for target_index, candidate in enumerate(relocated)
            if candidate[0] == row[0] and candidate[1] == target
        ]
        if not targets:
            continue
        source = list(relocated[index])
        source[8] = ""
        relocated[index] = tuple(source)
        for target_index in targets:
            candidate = list(relocated[target_index])
            candidate[8] = " ".join(part for part in (note, candidate[8]) if part)
            relocated[target_index] = tuple(candidate)
    return relocated


def physical_lines(text):
    """Yield text segments while preserving content on both sides of page breaks."""
    starts_new_page = False
    for raw in text.split("\n"):
        pieces = raw.split("\x0c")
        for index, piece in enumerate(pieces):
            yield piece, starts_new_page
            starts_new_page = index < len(pieces) - 1
        if len(pieces) == 1:
            starts_new_page = False


def append_metadata(current, fragment):
    current = current.replace("，", ",")
    fragment = fragment.replace("，", ",")
    if not current:
        return fragment.strip(",")
    if not fragment:
        return current.strip(",")
    if current.endswith(","):
        return current + fragment.lstrip(",")
    if fragment.startswith((",", "(")):
        return current + fragment
    return current + "," + fragment


def extract(path, year, audit=None):
    """audit: 若传入 dict,回填 {添加剂: [未能解析的表内行]},用于条目级召回审计。
    分母 = PDF 里 'CNS 号' 行的条数(每个添加剂条目恰好一行),这是可独立复核的真值。"""
    txt = subprocess.run(["pdftotext", "-raw", path, "-"],
                         capture_output=True, timeout=300).stdout.decode("utf-8", "replace")
    rows = []
    cur_add = cur_cns = cur_ins = ""
    recent, chunk = [], []
    in_table = started = False
    metadata_phase = ""
    cur_entity_note = pending_entity_note = ""

    def value_idx(toks):
        """值 = 从【左】往右第一个数值 token(纯数字,或带内联单位如 0.25g/kg、0.2g/L)。

        ⚠ 三个坑:
          · 排除语里的分类号会自成 token(折行时 "…、除" / "05.01.01 以外的可可制品"),
            不能当成值。判据:**限量值最多一个小数点**,而排除语引用的必是多级分类号。
            不能直接用 CODE 判 —— 放宽 NN.0 之后 '10.0' 既像分类号又像一个常见的限量值。
          · 紧跟 "以外/外" 的数字必是被排除的分类号,不是值。
          · 必须【从左往右】找:一个 chunk 里可能挤着两条 GB2760-2024 的行
            (08.03 熟肉制品 0.25g/kg  14.02.03 果蔬汁类饮料 0.2g/L),从右找会取到第二条的值。
        """
        bracketed_candidates = []
        for i in range(1, len(toks)):
            t = toks[i]
            if t.count(".") >= 2:                      # 多级分类号,不可能是限量值
                continue
            # 被排除的分类号:"…除05.01以外的…"、"冷冻饮品（03.04 食用冰除外）"
            if (i + 1 < len(toks) and valid_food_code(t)
                    and re.search(r"以外|除外", toks[i + 1])):
                continue
            if re.search(r"[（(]$", toks[i - 1]):       # 紧跟左括号 → 括注里的分类号
                continue
            if NUM.match(t) or INLINE.match(t):
                if "残留量" in "".join(toks[:i]):
                    continue
                if _unclosed_brackets("".join(toks[:i])):
                    bracketed_candidates.append(i)
                    continue
                return i
        # PDF reading order can insert the value before the remaining food-name
        # text closes its parenthesis.  If no later outside-bracket value exists,
        # the last numeric candidate is the value; earlier candidates are category
        # references such as 12.10.02.
        return bracketed_candidates[-1] if bracketed_candidates else None

    def value_unit(t):
        m = INLINE.match(t)
        return (m.group(1), m.group(2)) if m else (t, "g/kg")

    def complete(c):
        return GMP in "".join(c) or value_idx(c) is not None

    def flush(next_additive="", physical_markers=()):
        nonlocal chunk, pending_entity_note
        c, chunk = chunk, []
        # 食品分类号【必为多段】(01.0 / 12.01 / 02.02.01.01)。裸的 "13"、"25" 是表A.2 的
        # 序号,不是分类号 —— 放行就会把名录行当限量行。"00" 是本脚本给"各类食品"的合成码。
        if not c or not cur_add or not CODE.fullmatch(c[0]) or ("." not in c[0] and c[0] != "00"):
            return
        code = c[0]
        if GMP in "".join(c):
            food, _, trailing = "".join(c[1:]).partition(GMP)
            # pdftotext can place the GMP cell before a food-name continuation
            # from the next physical page.  Recover the tail only when the
            # pre-GMP text visibly requires continuation; otherwise trailing
            # material may belong to a following additive heading or note.
            trailing = strip_following_heading(
                trailing, next_additive, physical_markers
            )
            open_brackets = _unclosed_brackets(food)
            note = ""
            if trailing and re.search(r"[、，,]$", food) and not open_brackets:
                # A punctuation-final fragment is an unfinished food list.
                food += trailing
            elif trailing:
                # Material after the max-use cell normally belongs to the note
                # column.  repair_food_and_note also handles the rarer case in
                # which a bracketed food name continues before that note.
                food, note = repair_food_and_note(food, trailing)
            if food and re.search(r"[一-鿿]", food):
                reason = (
                    "CNS号缺失或格式异常"
                    if not re.match(r"^\d{2}\.\d{3}", cur_cns)
                    else "非法食品分类号"
                    if not valid_food_code(code)
                    else "食品类别括号不完整"
                    if _unclosed_brackets(food) != []
                    else "食品名残留裸数值(值可能取错位置)"
                    if code != "00" and food_has_unexplained_number(food)
                    else ""
                )
                if reason:
                    QUAR.append(
                        {
                            "year": year,
                            "additive": cur_add,
                            "cns": cur_cns,
                            "food_code": code,
                            "food": food,
                            "max_use": "GMP",
                            "unit": "",
                            "reject": reason,
                            "raw_chunk": " ".join(c),
                        }
                    )
                else:
                    entity_note = entity_note_for_food(cur_entity_note, code)
                    note = " ".join(part for part in (entity_note, note) if part)
                    rows.append((year, cur_add, cur_cns, cur_ins, code, food, "GMP", "",
                                 note))
            return
        vi = value_idx(c)
        if vi is None or vi < 2:
            if audit is not None and cur_add:
                audit[cur_add].append(" ".join(c))
            return
        food = "".join(c[1:vi])                       # 汉字被两端对齐拉散时,无空格拼接才对
        if not re.search(r"[一-鿿]", food):
            if audit is not None:
                audit[cur_add].append(" ".join(c))
            return
        val, unit = value_unit(c[vi])
        note, carried_note = split_following_heading(
            "".join(c[vi + 1:]), next_additive, physical_markers
        )
        if carried_note:
            pending_entity_note = carried_note
        food, note = repair_food_and_note(food, note)
        entity_note = entity_note_for_food(cur_entity_note, code)
        note = " ".join(part for part in (entity_note, note) if part)
        # ——— 出口闸门:两条【可判定】的错值特征。命中就隔离,不猜、不静默丢。———
        # ① 值长成 0X.XX:限量值不会有"前导零+非零数字"(0.5/1.0 会,03.04 只可能是食品分类号)。
        # ② 剥掉平衡括注、类别号引用和百分比后,食品名里还剩裸数字
        #    → 说明值取错了位置
        #    ("冷冻饮品(03.04食用冰除外)0.68" 的真值是 0.68,而 val 读成了页码 211)。
        # ⚠ "食品名里有数字" 这个判据太粗,会大面积误伤 —— 食品名【合法地】含数字的有三种:
        #    · 方括号排除语:"饮料类[14.01包装饮用水、14.02.03 果蔬汁类饮料除外]"
        #    · 圆括号排除语:"冷冻饮品(03.04食用冰除外)"
        #    · 类别官名本身就带号:"02.02类以外的脂肪乳化制品"、"除05.01.01以外的可可制品"
        #   真正的错值签名是:**括注之外、且不跟"以外/除外"的裸数值**(值被粘进了食品名)。
        rej = ("CNS号缺失或格式异常" if not re.match(r"^\d{2}\.\d{3}", cur_cns)
               else "非法食品分类号" if not valid_food_code(code)
               else "食品类别括号不完整" if _unclosed_brackets(food) != []
               else "值形如食品分类号" if re.match(r"^0\d\.", val)
               else "食品名残留裸数值(值可能取错位置)"
               if food_has_unexplained_number(food) else "")
        if rej:
            QUAR.append({"year": year, "additive": cur_add, "cns": cur_cns, "food_code": code,
                         "food": food, "max_use": val, "unit": unit, "reject": rej,
                         "raw_chunk": " ".join(c)})
            return
        rows.append((year, cur_add, cur_cns, cur_ins, code, food, val, unit,
                     note))
    pagebreak = False
    for raw, starts_new_page in physical_lines(txt):
        # pdftotext 可把旧页页脚和新页首行放在同一个物理行:
        #   "GB2760—2024\fCNS号..."。两侧都要保留;换页时同时回退上一页已暂存的纯数字页码。
        if starts_new_page:
            pagebreak = True
            if (
                len(chunk) > 1
                and re.fullmatch(r"\d{1,3}", chunk[-1])
                and complete(chunk[:-1])
            ):
                chunk.pop()
            if recent and re.fullmatch(r"\d{1,3}", re.sub(r"\s+", "", recent[-1])):
                recent.pop()
        line = collapse(raw).strip()
        if not line:
            continue
        flat = re.sub(r"\s+", "", line)
        if flat.startswith("GB2760"):
            continue

        if pagebreak:                                  # 页眉页脚 / 续表头
            if re.fullmatch(r"\d{1,3}", flat) or flat.startswith("GB") or flat.startswith("表A.1"):
                continue
            pagebreak = False

        # ⚠ 必须等 started(见过第一条 CNS 行)才允许 break —— 目次/前言里就会提到"食品用香料",
        #   不加这个门会在正文开始前就跳出,一行都抽不到。
        # ⚠ 更要紧的是【表A.2】:它紧接在表A.1 之后、附录B 之前,列的是"可在各类食品中按需使用"的
        #   添加剂名录,列结构是 序号|添加剂名|CNS号|INS号。不在这里停,最后一个添加剂(紫胶红)
        #   会把整张表A.2 吞成自己的限量行,而"限量值"读到的其实是 **INS 号**
        #   (实测出现 紫胶红 = 1450 g/kg 这种物理上不可能的值)。
        # ⚠ 2024 的表A.2 在 -raw 里【没有"表A.2"标题行】,直接以列头
        #   "例外食品类别编号 食品分类号 食品名称" 起头,而这个列头同样含"食品分类号+食品名称",
        #   会把 in_table 重新打开。它的行是 "序号. 分类号 食品名"(1.01.01.01 巴氏杀菌乳),
        #   序号≥10 时折叠出来的 "34.08.01.01" 恰好长得像合法分类号 → 混进最后一个添加剂的限量行。
        if started and (re.match(r"^表A\.2", flat) or "例外食品类别编号" in flat
                        or flat.startswith("附录B") or flat.startswith("B.1")
                        or "食品用香料" in flat):
            break

        m = CNS_LINE.match(flat)
        if m:
            next_additive = name_from(recent)
            pending_entity_note = ""
            flush(next_additive, heading_markers(recent))
            cur_add = next_additive
            cur_entity_note, pending_entity_note = pending_entity_note, ""
            cur_cns = m.group(1).replace("，", ",").rstrip(",")
            cur_ins = (m.group(2) or "").strip()
            metadata_phase = "ins" if m.group(2) is not None else "cns"
            in_table = False
            started = True
            if audit is not None:
                audit.setdefault(cur_add or f"?CNS{cur_cns}", [])
            recent = [line]
            continue
        if metadata_phase:
            if flat.startswith(("INS号", "INS")):
                cur_ins = flat.split("号", 1)[1] if "号" in flat else flat[3:]
                metadata_phase = "ins"
                continue
            if flat.startswith("功能"):
                cur_cns = cur_cns.strip(",")
                cur_ins = cur_ins.strip(",")
                metadata_phase = ""
            elif metadata_phase == "cns" and CNS_FRAGMENT.fullmatch(flat):
                cur_cns = append_metadata(cur_cns, flat)
                continue
            elif metadata_phase == "ins" and not re.search(r"[一-鿿]", flat):
                cur_ins = append_metadata(cur_ins, flat)
                continue
            else:
                metadata_phase = ""
        if "INS号" in flat and "功能" in flat:
            next_additive = name_from(recent + [line.split("功能", 1)[0]])
            flush(next_additive, heading_markers(recent + [line.split("功能", 1)[0]]))
            cur_add = next_additive
            cur_cns = ""
            cur_ins = flat.split("INS号", 1)[1].replace("功能", "").strip()
            in_table = False
            started = True
            if audit is not None:
                audit.setdefault(cur_add or "?CNS-missing", [])
            recent = [line]
            continue
        recent = (recent + [line])[-RECENT_LIMIT:]
        # 表A.1 的列头必含【最大使用量】—— 只认"食品分类号+食品名称"会把表A.2 的列头也认进来。
        if "食品分类号" in flat and "食品名称" in flat and "最大使用量" in flat:
            in_table = True
            continue
        if not (in_table and cur_add):
            continue

        toks = line.split()
        if toks:
            toks = split_concatenated_food_codes(toks[0]) + toks[1:]
        # 行块重组。表格行会折成多行,且【续行可能以一个分类号开头】——
        #   05.01.02 巧克力和巧克力制品、除
        #   05.01.01 以外的可可制品          ← 排除语的一部分,不是新行
        #
        # ⚠ 不能用"上一块还没拿到值就算续行":某行的值若解析失败,它会把【下一条真行】整个吞掉,
        #   于是下一行的分类号被当成上一行的限量值(实测:二氧化硅 2014 读出 "12.01"、
        #   双乙酰酒石酸 2024 读出 "03.0" —— 都是食品分类号冒充限量值)。
        #   排除语续行是有【字面标记】的:上一块以 除/、/( 收尾,或本行的分类号后面紧跟"以外"。
        #   只认这两种;否则一律另起新行,让上一块解析失败进审计 —— 缺值远好过错值。
        joined_chunk = "".join(chunk)
        unclosed = _unclosed_brackets(joined_chunk) if chunk else []
        cont = chunk and (bool(unclosed)
                          or re.search(r"[除、（(]$", joined_chunk)
                          or (len(toks) > 1 and re.match(r"^(?:类)?(?:以外|外)", toks[1])))
        leading_value = bool(toks) and bool(NUM.fullmatch(toks[0]) or INLINE.fullmatch(toks[0]))
        value_note = len(toks) > 1 and bool(
            re.match(r"^(?:以.*计|残留量|仅限|可单独|按稀释|按冲调)", "".join(toks[1:]))
        )
        standalone_value = (
            leading_value
            and bool(chunk)
            and not complete(chunk)
            and (len(toks) == 1 or value_note)
        )
        newrow = (
            bool(toks)
            and food_row_start(toks[0])
            and not cont
            and not standalone_value
        )
        # 「各类食品(表A.2 所列除外) …… 按生产需要适量使用」这类行【没有食品分类号】。
        # 只认以分类号开头的行,会把整个条目丢掉 —— 2024 把大量添加剂改成 GMP 通用,
        # 实测因此丢了 72 个条目(条目召回 74%)。这类行以「各类食品」起头,单列一条规则。
        allfood = bool(toks) and toks[0].startswith("各类食品") and (not chunk or complete(chunk))
        # Some 2024 cells contain two rules for one merged food-code/name cell:
        # a numeric limit followed by a GMP line carrying a second age-specific
        # note.  When that GMP marker starts a physical line after a completed
        # numeric chunk, repeat the just-parsed code and food for the second rule.
        repeated_value_index = value_idx(chunk) if chunk else None
        repeated_gmp = (
            bool(chunk)
            and chunk[0] != "00"
            and repeated_value_index is not None
            and _unclosed_brackets(
                "".join(chunk[:repeated_value_index])
            ) == []
            and "".join(toks).startswith(GMP)
        )
        if repeated_gmp:
            repeated_code = chunk[0]
            before = len(rows)
            flush()
            if len(rows) == before + 1 and rows[-1][4] == repeated_code:
                chunk = [repeated_code, rows[-1][5]] + toks
            elif audit is not None:
                audit[cur_add].append("unresolved repeated GMP rule: " + " ".join(toks))
        elif newrow or allfood:
            flush()
            chunk = ["00"] + toks if allfood else toks   # "00" = 各类食品(无分类号)
        elif chunk:
            chunk += toks
    flush()
    return relocate_misordered_entity_notes(rows)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Extract the GB 2760 additive tables from the three source PDFs."
    )
    parser.add_argument(
        "--source-dir",
        required=True,
        type=Path,
        help="Directory containing the GB 2760 source PDFs (searched recursively).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Derived-data directory (default: {DEFAULT_OUTPUT_DIR}).",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    QUAR.clear()
    out = []
    for yr in YEARS:
        hits = [p for p in glob.glob(str(args.source_dir / "**" / f"GB 2760-{yr}*.pdf"), recursive=True)
                if "使用标准" in p or "使用卫生" in p]
        if not hits:
            print(f"⚠ {yr} 未找到")
            continue
        audit = {}
        rs = extract(sorted(hits, key=len)[0], yr, audit)
        out += rs
        got = {r[1] for r in rs}
        cns_ok = sum(1 for r in rs if re.match(r"^\d{2}\.\d{3}", r[2]))
        code_ok = sum(1 for r in rs if CODE.fullmatch(r[4]))
        miss = [a for a in audit if a not in got]
        print(f"{yr}: {len(rs)} 行 | 条目 {len(got)}/{len(audit)} = {len(got)/len(audit):.1%} "
              f"| CNS 合法 {cns_ok/len(rs):.1%} | food_code 合法 {code_ok/len(rs):.1%}")
        if miss:
            print(f"   ⚠ 零行条目 {len(miss)}:{miss[:6]}")
            for a in miss[:2]:
                print(f"      「{a}」表内未解析行:{audit[a][:3]}")

    p = args.output_dir / "additive_raw_long.csv"
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year", "additive", "cns", "ins", "food_code", "food", "max_use", "unit", "note"])
        w.writerows(out)
    q = args.output_dir / "additive_quarantine.csv"
    cols = ["year", "additive", "cns", "food_code", "food", "max_use", "unit", "reject", "raw_chunk"]
    with open(q, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(QUAR)
    print(f"\n→ {p}  共 {len(out)} 行")
    print(f"→ {q}  隔离 {len(QUAR)} 行")
    for r in QUAR:
        print(f"   ⚠ {r['year']} {r['additive'][:14]:16s} {r['food_code']:12s} "
              f"{r['food'][:22]:24s} 值={r['max_use']:6s} — {r['reject']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
