#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
signal_orthogonality.py — 信号正交性审计器（元层工具，纯本地、无网络、只读）

它解决什么系统级 gap：
  整个组合有 8+ 个信号工具，研究 note 反复把『N 重独立印证』当作真 alpha 的特征
  （越多条不重叠证据合流 = 信号越强）。但这套逻辑只有在这些信号【输入正交】时才成立。
  若多条『独立印证』其实共享同一根原始数据（如都来自 price 序列），它们就是共线的，
  合流不增加信息量，只制造虚假信心——这是确认偏误在系统层的工程化复发。

  我们有信号生成器、有 allocate 配置层、有 prediction-ledger 校准器，
  却【从无】一个工具审计『我们引用的多重印证到底独立不独立』。本工具补这个洞。

它做什么：
  给定一组在某篇 note / 某个标的判断里被当作『独立印证』引用的信号 id，
  按 signal_registry.json 声明的 root_inputs 计算它们的【输入重叠度】，
  对每对信号给出 Jaccard 重叠，并按整体共享根输入给出独立性裁定：
    🟢 正交     —— 无共享根输入（真多重印证）
    🟡 部分共线 —— 共享部分根输入（印证力打折，须标注）
    🔴 高度共线 —— 共享主导根输入（伪独立，不应算作多重印证）

  特别地：price 是最易被重复计数的根输入（筹码/南向/α/相关/估值/反向DCF 全沾 price），
  本工具对『多条信号同时把 price 当唯一或主导输入』给最强红旗。

用法：
  python3 signal_orthogonality.py --signals tech_screener,holder_concentration,southbound_flow,alpha_check
  python3 signal_orthogonality.py --audit-all     # 审计登记表里全部信号两两重叠矩阵
  python3 signal_orthogonality.py --quiet --signals ...   # cron 友好: 仅 🔴 surface, exit 1

数据诚实：
  - root_inputs 是登记声明（人工维护），非自动推断；新增信号须在 registry 登记。
  - Jaccard/共线裁定是输入集合的确定性算术，非预测、非买卖指令。
  - 本工具不判信号对不对、不取数、不下单，只判『这几条证据独不独立』。
"""
import argparse
import glob
import json
import os
import re
import sys
from itertools import combinations

REG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signal_registry.json")


def load_registry():
    with open(REG_PATH, "r", encoding="utf-8") as f:
        reg = json.load(f)
    by_id = {s["id"]: s for s in reg["signals"]}
    return reg, by_id


def jaccard(a, b):
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def verdict_pair(a_inputs, b_inputs):
    shared = set(a_inputs) & set(b_inputs)
    j = jaccard(a_inputs, b_inputs)
    if not shared:
        return "🟢", j, shared
    # 共享了输入。若共享集 == 任一方的全部输入（一方被另一方完全包含/同源）→ 高度共线
    if shared == set(a_inputs) or shared == set(b_inputs):
        return "🔴", j, shared
    if j >= 0.5:
        return "🔴", j, shared
    return "🟡", j, shared


def audit(signal_ids, by_id, quiet=False):
    missing = [s for s in signal_ids if s not in by_id]
    if missing:
        print("⚠️ 未登记信号(请先在 signal_registry.json 登记其 root_inputs): " + ", ".join(missing))
        return 2
    pairs = list(combinations(signal_ids, 2))
    red, yellow = [], []
    lines = []
    # 整体共享根输入分析
    input_count = {}
    for sid in signal_ids:
        for inp in by_id[sid]["root_inputs"]:
            input_count.setdefault(inp, []).append(sid)

    for a, b in pairs:
        v, j, shared = verdict_pair(by_id[a]["root_inputs"], by_id[b]["root_inputs"])
        line = f"  {v} {a} × {b}  Jaccard={j:.2f}" + (f"  共享根输入={{{', '.join(sorted(shared))}}}" if shared else "  正交")
        lines.append(line)
        if v == "🔴":
            red.append((a, b, shared))
        elif v == "🟡":
            yellow.append((a, b, shared))

    # 主导共享输入红旗：某根输入被 >=3 条信号共用
    dominant = {inp: sids for inp, sids in input_count.items() if len(sids) >= 3}

    n = len(signal_ids)
    # 独立性指数：实际独立根输入数 / 信号数（1.0=每条信号一个独立根；越低越共线）
    union_inputs = set()
    for sid in signal_ids:
        union_inputs |= set(by_id[sid]["root_inputs"])
    indep_index = len(union_inputs) / n if n else 0.0

    has_signal = bool(red) or bool(dominant)

    if quiet and not has_signal:
        return 0

    print(f"=== 信号正交性审计 ({n} 条被当作独立印证的信号) ===")
    print(f"信号: {', '.join(signal_ids)}")
    print(f"并集根输入: {{{', '.join(sorted(union_inputs))}}}  独立性指数={indep_index:.2f}  (越低越共线)")
    print("\n两两重叠:")
    for l in lines:
        print(l)
    if dominant:
        print("\n🔴 主导共享根输入(≥3条信号共用同一根=多重印证被高度稀释):")
        for inp, sids in dominant.items():
            print(f"  [{inp}] 被 {len(sids)} 条共用: {', '.join(sids)}")
            if inp == "price":
                print("     ⚠️ price 是最易重复计数的根输入: 把多条 price 派生信号当『独立印证』=确认偏误工程化")
    if red:
        print("\n🔴 高度共线信号对(不应同时算作独立印证):")
        for a, b, sh in red:
            print(f"  {a} 与 {b}: 共享 {{{', '.join(sorted(sh))}}}")
    if yellow:
        print("\n🟡 部分共线(印证力打折,引用时须标注非完全独立):")
        for a, b, sh in yellow:
            print(f"  {a} 与 {b}: 共享 {{{', '.join(sorted(sh))}}}")
    print("\n裁定建议:")
    if red or dominant:
        print("  ❌ 这组『多重印证』含共线项。真正独立的证据条数 < 名义条数。")
        print("     引用时应按【独立根输入数】而非【信号条数】计权,避免虚假信心。")
    elif yellow:
        print("  ⚠️ 这组印证大体独立但有部分重叠,可引用为多重印证但标注折扣。")
    else:
        print("  ✅ 这组信号输入正交,可作为真多重独立印证使用。")

    return 1 if has_signal else 0


def audit_all(reg, by_id, quiet=False):
    ids = [s["id"] for s in reg["signals"]]
    # 全量两两重叠中找出所有 🔴 对
    red = []
    for a, b in combinations(ids, 2):
        v, j, shared = verdict_pair(by_id[a]["root_inputs"], by_id[b]["root_inputs"])
        if v == "🔴":
            red.append((a, b, shared, j))
    if quiet and not red:
        return 0
    print(f"=== 全登记表信号正交性矩阵 ({len(ids)} 条信号) ===")
    # price 派生信号清单
    price_derived = [s["id"] for s in reg["signals"] if "price" in s["root_inputs"]]
    print(f"\nprice 派生信号({len(price_derived)}条,互相引用时最易伪独立): {', '.join(price_derived)}")
    if red:
        print(f"\n🔴 高度共线信号对 ({len(red)}对) — 不应同时算作独立印证:")
        for a, b, sh, j in red:
            print(f"  {a} × {b}  共享={{{', '.join(sorted(sh))}}} Jaccard={j:.2f}")
    else:
        print("\n✅ 无高度共线对。")
    print("\n用途: 写 note 主张『N重独立印证』前,把这 N 条信号 id 喂给 --signals,核实它们没落在 🔴 对里。")
    return 1 if red else 0


RESEARCH_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research")

# 声称『多重印证』的措辞(确认偏误最易在此工程化)
CLAIM_PAT = re.compile(r"([一二三四五六七八九十两N\d]+重(?:独立)?印证|多重(?:独立)?印证|重证据合流|不重叠的?证据合流|条不重叠)")
# 已做正交性披露的措辞(出现任一即视为已自检)
DISCLOSURE_PAT = re.compile(r"正交|共享根输入|共线|伪独立|印证力(?:折扣|打折)|独立性指数|派生自price|同源")


def scan_notes(quiet=False):
    """扫描 research/*.md: 找出声称『N重(独立)印证』却【未做正交性披露】的 note。
    这是反确认偏误的治理闸门——审计器存在但 note 绕过它=防御形同虚设。
    纯文本确定性检查, 不取数、不下单。退出码: 0=全部合规 / 1=有未披露的多重印证主张。"""
    if not os.path.isdir(RESEARCH_DIR):
        print(f"⚠️ 未找到 research 目录: {RESEARCH_DIR}")
        return 2
    offenders = []
    for path in sorted(glob.glob(os.path.join(RESEARCH_DIR, "*.md"))):
        base = os.path.basename(path)
        if base == "INDEX.md":
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                txt = f.read()
        except Exception:
            continue
        claims = CLAIM_PAT.findall(txt)
        if claims and not DISCLOSURE_PAT.search(txt):
            offenders.append((base, sorted(set(claims))[:4]))
    has_signal = bool(offenders)
    if quiet and not has_signal:
        return 0
    print("=== 研究库『多重印证』正交性治理扫描 ===")
    print(f"扫描目录: {RESEARCH_DIR}")
    if not offenders:
        print("✅ 所有声称多重印证的 note 均带正交性披露(或无此类主张)。")
        return 0
    print(f"\n🔴 {len(offenders)} 篇 note 声称『多重印证』但【未做正交性披露】(疑似伪独立/确认偏误):")
    for base, claims in offenders:
        print(f"  • {base}")
        print(f"      措辞: {', '.join(claims)}")
    print("\n裁定: 这些 note 主张多条证据合流, 但未核验这些信号是否真输入正交。")
    print("     补救: 把该 note 引用的信号 id 喂给 --signals 审计, 把折扣结论写回 note;")
    print("     若多条信号共享 price 等根输入, 名义『N重印证』的真实独立条数 < N, 须降权。")
    return 1 if has_signal else 0


def main():
    ap = argparse.ArgumentParser(description="信号正交性审计器")
    ap.add_argument("--signals", help="逗号分隔的信号 id,审计它们是否真独立")
    ap.add_argument("--audit-all", action="store_true", help="审计全登记表两两重叠")
    ap.add_argument("--scan-notes", action="store_true", help="扫描 research/*.md:找声称多重印证却未做正交披露的 note")
    ap.add_argument("--quiet", action="store_true", help="cron 友好:仅🔴 surface")
    args = ap.parse_args()

    if args.scan_notes:
        sys.exit(scan_notes(quiet=args.quiet))

    reg, by_id = load_registry()

    if args.audit_all:
        sys.exit(audit_all(reg, by_id, quiet=args.quiet))
    if args.signals:
        sids = [s.strip() for s in args.signals.split(",") if s.strip()]
        if len(sids) < 2:
            print("⚠️ 至少需要 2 条信号才能审计正交性")
            sys.exit(2)
        sys.exit(audit(sids, by_id, quiet=args.quiet))
    ap.print_help()
    sys.exit(0)


if __name__ == "__main__":
    main()
