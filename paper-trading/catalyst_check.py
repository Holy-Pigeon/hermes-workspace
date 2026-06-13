#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
catalyst_check.py — 持仓催化剂日历预警 (纯只读, 不改库不下单, 完全可逆)

读取 catalyst/catalysts.json, 计算每个催化剂窗口距今天数, 分级预警:
  - <=14 天 : [HOT]   临近 — 立即去拉确切披露日, 准备核查基本面失效条件
  - <=30 天 : [WARN]  接近 — 进入观察, 确认预约披露时间表
  - <=60 天 : [WATCH] 在视野内
  - >60 天  : [ ]     远期, 静默登记

设计目的: thesis_check.py 只能自动盯【价格类】失效条件; 本脚本把【基本面类】
失效条件锚定到日历窗口, 临近时把它们推到人工核查台前, 对抗"无限期拖延核实"。

数据诚实: deadline 多为【制度/法定窗口】而非公司公告的确切披露日。
exact_date_confirmed=false 时, 脚本会明确提示"确切日期待核实", 不假装精确。
"""
import json, sys, os
from datetime import date, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
CAL = os.path.join(BASE, "catalyst", "catalysts.json")


def load():
    with open(CAL, "r", encoding="utf-8") as f:
        return json.load(f)


def tier(days):
    if days < 0:
        return "PAST", "已过窗口(确认是否已披露)"
    if days <= 14:
        return "HOT", "临近-立即拉确切披露日+备好基本面核查"
    if days <= 30:
        return "WARN", "接近-确认预约披露时间表"
    if days <= 60:
        return "WATCH", "在视野内"
    return "FAR", "远期登记"


def main():
    data = load()
    today = date.today()
    cats = data.get("catalysts", {})
    rows = []
    for sym, events in cats.items():
        for ev in events:
            dl = datetime.strptime(ev["deadline"], "%Y-%m-%d").date()
            days = (dl - today).days
            t, desc = tier(days)
            rows.append((days, sym, ev, t, desc))
    rows.sort(key=lambda r: r[0])

    print("=" * 78)
    print(f"持仓催化剂日历预警  |  今天 {today}  |  {len(rows)} 个窗口")
    print("=" * 78)
    hot = 0
    for days, sym, ev, t, desc in rows:
        flag = {"HOT": "[HOT]", "WARN": "[WARN]", "WATCH": "[WATCH]",
                "FAR": "[    ]", "PAST": "[PAST]"}[t]
        if t in ("HOT", "WARN", "PAST"):
            hot += 1
        conf = "确切日已核实" if ev.get("exact_date_confirmed") else "确切日待核实(仅制度窗口)"
        print(f"\n{flag} {sym}  {ev['event']}  | 距今 {days} 天 | {desc}")
        print(f"      窗口性质: {ev['window_type']}  ({conf})")
        if not ev.get("exact_date_confirmed"):
            print(f"      → 去拉确切日: {ev.get('source_to_confirm','?')}")
        inv = ev.get("linked_invalidation", [])
        if inv:
            print(f"      届时需核查的基本面失效条件:")
            for c in inv:
                print(f"        · {c}")
        if ev.get("note"):
            print(f"      note: {ev['note']}")

    print("\n" + "-" * 78)
    if hot:
        print(f"⚠ 有 {hot} 个窗口处于 WARN/HOT/PAST, 需人工动作(拉确切日 + 核实基本面失效条件)")
    else:
        print("✓ 无临近窗口(全部 >30 天), 维持静默观察")
    print("数据诚实声明: deadline 为制度/法定窗口, 非公司公告确切披露日; 临近时务必去交易所核实确切日与真实财报数据, 不凭印象。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
