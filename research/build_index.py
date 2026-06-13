#!/usr/bin/env python3
"""
research/ 个股研究 note 自动索引生成器（纯只读，不改 note 本身）
==============================================================
扫描 research/note_*.md，抓取：对象(股票名+代码) / 日期 / 类型 / 一句话结论 / 证伪条件 / 文件名，
生成 INDEX.md。兼容两种头部格式：
  A(06-12批): 标题行 `# ...紫金矿业(601899)...` + `日期：x | 类型：y | 作者：z`
  B(06-13批): 标题行 `# 迈瑞医疗(300760)...` + `**日期**: x` / `**类型**: y` / `**结论一句话**: z`
用法: /opt/homebrew/bin/python3 build_index.py   （或系统 python3，纯标准库）
"""
import re, sys
from pathlib import Path
from datetime import datetime

RESEARCH = Path(__file__).resolve().parent
OUT = RESEARCH / "INDEX.md"

# 已知组合持仓代码（用于标 [持仓] vs [组合外]）
HOLDINGS = {"601899", "601138", "600415", "09926"}

def grab_field(text, *labels):
    """从正文找 `label：value` 或 `**label**: value`，返回第一个命中的 value（单行）。"""
    for lab in labels:
        # **label**: value  或  label: value  或 label：value
        m = re.search(rf"\*{{0,2}}{re.escape(lab)}\*{{0,2}}\s*[:：]\s*(.+)", text)
        if m:
            return m.group(1).strip().lstrip("*").strip()
    return ""

def parse_note(path):
    raw = path.read_text(errors="replace")
    lines = raw.splitlines()
    # 日期：文件名最稳 note_YYYY-MM-DD_xxx
    mdate = re.search(r"note_(\d{4}-\d{2}-\d{2})", path.name)
    date = mdate.group(1) if mdate else ""
    # 标题行：第一个 # 开头
    title = next((l.lstrip("# ").strip() for l in lines if l.startswith("#")), path.stem)
    # 对象：标题里抓 名称 (代码)，代码兼容 601899 / 09926.HK / 300760，名称与括号间可有空格
    mobj = re.search(r"([\u4e00-\u9fa5A-Za-z·]{2,12}?)\s*[（(]\s*(\d{4,6})(?:\.[A-Za-z]{2})?\s*[)）]", title)
    if mobj:
        name, code = mobj.group(1).strip(), mobj.group(2)
        obj = f"{name}({code})"
    else:
        # 无股票代码：取标题破折号/—/前的主体作对象名（不截断中文词）
        head = re.split(r"\s*[—\-–]\s*|\s+[（(]", title)[0].strip()
        name = head if head else path.stem
        code = ""
        obj = name
    # 类型
    typ = grab_field(raw, "类型")
    typ = re.sub(r"^\W+", "", typ).split("|")[0].strip()[:40]
    # 一句话结论：优先显式字段，否则抓"结论"段或触发段首句
    concl = grab_field(raw, "结论一句话", "一句话结论", "一句话", "硬结论", "核心结论", "一句话读数")
    if not concl:
        # 找含"结论"的行
        m = re.search(r"\*{0,2}结论\*{0,2}[:：]\s*(.+)", raw)
        if m:
            concl = m.group(1).strip()
    if not concl:
        # 抓"硬结论"段（## 标题含硬结论/核心结论 的下一非空行）
        m = re.search(r"##[^\n]*(?:硬结论|核心结论|结论)[^\n]*\n+(.+)", raw)
        if m:
            concl = m.group(1).strip()
    if not concl:
        # 退回触发段第一句
        mt = re.search(r"##\s*0?\.?\s*触发\s*\n+(.+)", raw)
        if mt:
            concl = mt.group(1).strip()
    concl = re.sub(r"\*\*", "", concl).strip()
    if len(concl) > 160:
        concl = concl[:158] + "…"
    # 证伪条件：抓含"证伪条件"的行
    falsify = ""
    mf = re.search(r"证伪条件[^:：\n]*[:：]?\s*([^\n]+)", raw)
    if mf:
        falsify = re.sub(r"\*\*", "", mf.group(1)).strip()[:120]
    # 分类标签：先按是否有股票代码二分，杜绝"组合外候选深研"被"组合"关键词误吞
    if code:
        tag = "持仓" if code in HOLDINGS else "组合外候选"
    else:
        tag = "组合/方法论"
    return {
        "date": date, "obj": obj, "name": name, "code": code,
        "type": typ, "concl": concl or "（未抓到结论字段，见原文）",
        "falsify": falsify, "tag": tag, "file": path.name,
    }

def main():
    notes = sorted(RESEARCH.glob("note_*.md"))
    rows = [parse_note(p) for p in notes]
    rows.sort(key=lambda r: (r["date"], r["file"]), reverse=True)

    order = {"持仓": 0, "组合外候选": 1, "组合/方法论": 2}
    out = []
    out.append("# 个股研究 Note 总索引")
    out.append("")
    out.append(f"自动生成：`build_index.py` 扫描 `research/note_*.md`。共 **{len(rows)}** 篇。最后更新：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    out.append("")
    out.append("> 纯只读索引，不修改任何 note。新增 note 后重跑 `build_index.py` 即刷新。结论一句话/证伪条件均自原文抓取，以原文为准。")
    out.append("")

    for cat in ["持仓", "组合外候选", "组合/方法论"]:
        sub = [r for r in rows if r["tag"] == cat]
        if not sub:
            continue
        out.append(f"## {cat}（{len(sub)} 篇）")
        out.append("")
        out.append("| 日期 | 对象 | 类型 | 一句话结论 | 证伪条件 | 文件 |")
        out.append("|---|---|---|---|---|---|")
        for r in sub:
            fcell = r["falsify"] if r["falsify"] else "—"
            out.append(f"| {r['date']} | **{r['obj']}** | {r['type']} | {r['concl']} | {fcell} | `{r['file']}` |")
        out.append("")

    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"✅ 已生成 {OUT}（{len(rows)} 篇）")
    # 摘要打印分类计数
    from collections import Counter
    c = Counter(r["tag"] for r in rows)
    for k in ["持仓", "组合外候选", "组合/方法论"]:
        if c.get(k):
            print(f"   {k}: {c[k]} 篇")

if __name__ == "__main__":
    main()
