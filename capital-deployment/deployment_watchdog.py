#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资本部署看门狗 (capital-deployment / deployment_watchdog.py)
=============================================================
盯【全书资本部署率】这个系统最大盲区——被 allocation-discipline 明确跳过的空账户。

为什么存在（元层系统级 gap，非缝补）:
  allocation-discipline.allocate.py 第 80 行对无持仓账户直接 `无持仓,跳过`,
  于是 4 个 100% 现金的 sleeve(us-tech-value/options-lab/futures-macro/innovation
  合计 50M = 全书 56%)自 2026-06-11 建账起 24 天无人盯。价投可以慢、可以等好价格,
  但『机会成本 = 大额现金长期零配置且无人复盘为什么不配』本身必须被看见、被逼着给出理由,
  否则不是纪律是遗忘。这不是叫你追高买入——是把『闲置』从静默变成每周一次必须回答的问题。

判定(纯只读 paper_trading.db,不下单不改库):
  · 对每个 status=active 账户算部署率 = (initial_capital - cash) / initial_capital
  · 对每个账户算『距最后一笔 trade 的天数』(从无交易=距建账天数)
  · 红旗规则(防御性阈值,可在 CONFIG 调):
      🔴 IDLE_UNDEPLOYED : 部署率 < 5% 且 距最后动作 > IDLE_DAYS(默认14天)
                          = 大额现金长期零配置无人复盘
      🟠 UNDER_DEPLOYED  : 5% ≤ 部署率 < 40% 且 距最后动作 > IDLE_DAYS
      🟠 STALE_BOOK      : 账户有持仓但距最后一笔 trade > STALE_DAYS(默认30天)
                          = 仓位从不复盘/再平衡,可能论点已漂移
  · 输出全书部署率汇总 + 逐账户红旗

设计边界(数据诚实):
  · 本工具只『点名闲置 + 逼出理由』,绝不建议买什么、更不下单。部署与否是判断动作归用户。
  · 部署率是资金口径快照(现金/初始),不含浮盈浮亏对权益的影响,是『钱投出去没有』的纯度量。
  · 阈值是防御性启发式非真理;IDLE_DAYS 给足冗余只抓『真忘了』不抓正常观望。
  · --quiet: 无🔴红旗则 exit0 静默(cron 友好);有🔴 exit1。
"""
import sqlite3
import os
import sys
import argparse
import datetime
import json

DB = os.path.expanduser("~/hermes-workspace/paper-trading/paper_trading.db")

CONFIG = {
    "IDLE_DAYS": 14,        # 空/低配账户多少天无动作算红旗
    "STALE_DAYS": 30,       # 有持仓账户多少天不复盘算陈旧
    "UNDEPLOYED_PCT": 0.05, # 部署率低于此=近乎空账户
    "UNDER_PCT": 0.40,      # 部署率低于此=显著欠配
}


def _now():
    return datetime.datetime.now()


def _parse_dt(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    return None


def load_book(db=DB):
    if not os.path.exists(db):
        raise FileNotFoundError(f"paper_trading.db 不存在: {db}")
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    accts = []
    for a in con.execute(
        "SELECT id,name,strategy,initial_capital,cash,status,created_at "
        "FROM accounts WHERE status='active'"
    ):
        aid = a["id"]
        npos = con.execute(
            "SELECT COUNT(*) FROM positions WHERE account_id=?", (aid,)
        ).fetchone()[0]
        last_trade = con.execute(
            "SELECT MAX(traded_at) FROM trades WHERE account_id=?", (aid,)
        ).fetchone()[0]
        accts.append({
            "id": aid,
            "name": a["name"],
            "strategy": a["strategy"],
            "initial": a["initial_capital"] or 0.0,
            "cash": a["cash"] or 0.0,
            "n_positions": npos,
            "last_trade": last_trade,
            "created_at": a["created_at"],
        })
    con.close()
    return accts


def analyze(accts):
    now = _now()
    rows = []
    for a in accts:
        init = a["initial"]
        deployed_pct = (init - a["cash"]) / init if init else 0.0
        # 距最后动作: 有交易用最后交易日,否则用建账日
        anchor = a["last_trade"] or a["created_at"]
        dt = _parse_dt(anchor)
        days_since = (now - dt).days if dt else None
        flags = []
        if deployed_pct < CONFIG["UNDEPLOYED_PCT"]:
            if days_since is not None and days_since > CONFIG["IDLE_DAYS"]:
                flags.append(("🔴", "IDLE_UNDEPLOYED",
                              f"部署率{deployed_pct:.0%}且{days_since}天无动作=大额现金长期零配置无人复盘"))
        elif deployed_pct < CONFIG["UNDER_PCT"]:
            if days_since is not None and days_since > CONFIG["IDLE_DAYS"]:
                flags.append(("🟠", "UNDER_DEPLOYED",
                              f"部署率{deployed_pct:.0%}显著欠配且{days_since}天无动作"))
        if a["n_positions"] > 0 and days_since is not None and days_since > CONFIG["STALE_DAYS"]:
            flags.append(("🟠", "STALE_BOOK",
                          f"有{a['n_positions']}持仓但{days_since}天无任何交易=仓位从不复盘/再平衡"))
        rows.append({
            "name": a["name"],
            "strategy": a["strategy"],
            "initial": init,
            "cash": a["cash"],
            "deployed_pct": deployed_pct,
            "n_positions": a["n_positions"],
            "days_since": days_since,
            "flags": flags,
        })
    return rows


def render(rows, as_json=False, quiet=False):
    red = [r for r in rows if any(f[0] == "🔴" for f in r["flags"])]
    if as_json:
        print(json.dumps({
            "book_total": sum(r["initial"] for r in rows),
            "book_cash": sum(r["cash"] for r in rows),
            "book_deployed_pct": (
                (sum(r["initial"] for r in rows) - sum(r["cash"] for r in rows))
                / sum(r["initial"] for r in rows)
            ) if sum(r["initial"] for r in rows) else 0.0,
            "accounts": [
                {k: v for k, v in r.items()} for r in rows
            ],
            "red_count": len(red),
        }, ensure_ascii=False, indent=2, default=str))
        return 1 if red else 0

    if quiet and not red:
        return 0

    tot = sum(r["initial"] for r in rows)
    cash = sum(r["cash"] for r in rows)
    dep = (tot - cash) / tot if tot else 0.0
    print("=== 资本部署看门狗 · 全书体检 ===")
    print(f"全书 {tot:,.0f} | 现金 {cash:,.0f} | 已部署 {dep:.0%} | 闲置 {cash:,.0f}({cash/tot:.0%})")
    print()
    for r in rows:
        marker = "🔴" if any(f[0] == "🔴" for f in r["flags"]) else (
                 "🟠" if r["flags"] else "  ")
        ds = f"{r['days_since']}d" if r["days_since"] is not None else "?"
        print(f"{marker} {r['name']:<16} 部署{r['deployed_pct']:>5.0%} | "
              f"现金{r['cash']:>13,.0f} | 持仓{r['n_positions']} | 距最后动作{ds}")
        for emo, code, msg in r["flags"]:
            print(f"      {emo} {code}: {msg}")
    if red:
        idle_cap = sum(r["cash"] for r in red)
        print()
        print(f"🔴 {len(red)}个账户大额现金长期零配置,合计闲置 {idle_cap:,.0f}"
              f"({idle_cap/tot:.0%}全书)。")
        print("   元层结论: 不是叫你追高,是这些 sleeve 该给出『为什么现在不配』的明确理由")
        print("   (等更好价格/等催化剂/该缩减该 sleeve 规模),否则闲置=遗忘非纪律。")
    print()
    print("数据诚实: 纯只读 paper_trading.db 快照,部署率=资金口径不含浮盈亏,"
          "阈值防御性启发式,本工具只点名闲置不建议买卖不下单。")
    return 1 if red else 0


def main():
    ap = argparse.ArgumentParser(description="资本部署看门狗")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    ap.add_argument("--quiet", action="store_true", help="cron友好:无🔴则静默exit0")
    ap.add_argument("--db", default=DB, help="paper_trading.db 路径")
    args = ap.parse_args()
    try:
        accts = load_book(args.db)
    except Exception as e:
        print(f"[deployment_watchdog] 读库失败(诚实报错不编造): {e}", file=sys.stderr)
        return 2
    rows = analyze(accts)
    code = render(rows, as_json=args.json, quiet=args.quiet)
    return code


if __name__ == "__main__":
    sys.exit(main())
