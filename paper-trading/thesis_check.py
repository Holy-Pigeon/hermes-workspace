#!/usr/bin/env python3
"""
thesis_check.py — 持仓论点 & 失效条件巡检器 (read-only)
========================================================
合伙人 watchdog 的判断脚手架。每次 review 持仓时运行：
  1. 从 paper_trading.db 读真实持仓(成本/最新盯市价)
  2. 从 thesis/thesis.json 读每个持仓的论点+失效条件(含价格类阈值)
  3. 客观计算 drawdown%, 自动判定 type=price 的失效条件是否触发
  4. 列出 type=fundamental 的失效条件 → 提示需人工/数据核实(脚本不臆测基本面)
  5. 报告无 thesis 记录的"裸持仓"(治理缺口)

设计哲学(Munger): 买入即写死"什么会让我们认错"。复审时先看失效条件有没有被触发,
对抗确认偏误/锚定/沉没成本。脚本只做客观计算与清单提示, 绝不编造基本面数据。
纯只读, 不改库不下单, 完全可逆/无副作用。

用法:
  python3 thesis_check.py            # 全账户巡检
  python3 thesis_check.py --account stockchoose
  python3 thesis_check.py --json     # 机器可读输出(供 cron/推送复用)
"""
import sqlite3, os, json, argparse, sys

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "paper_trading.db")
THESIS = os.path.join(BASE, "thesis", "thesis.json")


def load_positions(account=None):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    q = ("SELECT p.symbol,p.name,p.market,p.direction,p.quantity,p.avg_cost,"
         "p.last_price,a.name AS acct FROM positions p "
         "JOIN accounts a ON a.id=p.account_id WHERE p.quantity!=0")
    args = []
    if account:
        q += " AND a.name=?"
        args.append(account)
    rows = [dict(r) for r in conn.execute(q, args).fetchall()]
    conn.close()
    return rows


def drawdown_pct(cost, last, direction="long"):
    if not cost or last is None:
        return None
    chg = (last - cost) / cost * 100.0
    return chg if direction == "long" else -chg


def evaluate(account=None):
    thesis = json.load(open(THESIS)).get("positions", {})
    positions = load_positions(account)
    results = []
    for p in positions:
        sym = p["symbol"]
        t = thesis.get(sym)
        dd = drawdown_pct(p["avg_cost"], p["last_price"], p["direction"])
        entry = {
            "symbol": sym, "name": p["name"], "acct": p["acct"],
            "avg_cost": p["avg_cost"], "last_price": p["last_price"],
            "drawdown_pct": round(dd, 2) if dd is not None else None,
            "has_thesis": t is not None,
            "triggered": [], "manual_check": [], "thesis": None,
        }
        if t is None:
            entry["alert"] = "NO_THESIS — 裸持仓, 无失效条件登记(治理缺口)"
            results.append(entry)
            continue
        entry["thesis"] = t.get("thesis")
        entry["stop_discipline"] = t.get("stop_discipline")
        # 价格类纪律红线
        sd = t.get("stop_discipline")
        if sd is not None and dd is not None and dd <= sd:
            entry["triggered"].append(
                f"纪律回撤红线: drawdown {dd:.1f}% <= {sd}% → 触发强制逻辑复审")
        for inv in t.get("invalidation", []):
            cond, typ, trig = inv.get("cond"), inv.get("type"), inv.get("trigger", "")
            if typ == "price":
                # 解析形如 'drawdown_pct <= -25'
                fired = False
                if "drawdown_pct" in trig and dd is not None:
                    try:
                        thr = float(trig.split("<=")[1].strip())
                        fired = dd <= thr
                    except Exception:
                        pass
                if fired:
                    entry["triggered"].append(f"[价格失效] {cond} (触发: {trig}, 实测dd={dd:.1f}%)")
            else:
                entry["manual_check"].append(f"[需核实] {cond} | 阈值: {trig}")
        results.append(entry)
    return results


def render(results):
    lines = []
    naked = [r for r in results if not r["has_thesis"]]
    fired = [r for r in results if r["triggered"]]
    lines.append("=" * 60)
    lines.append("持仓论点 & 失效条件巡检 (thesis_check)")
    lines.append("=" * 60)
    if fired:
        lines.append("\n🔴 触发失效/纪律条件 (需立即复审):")
        for r in fired:
            lines.append(f"  • {r['name']}({r['symbol']}) dd={r['drawdown_pct']}%")
            for t in r["triggered"]:
                lines.append(f"      → {t}")
    else:
        lines.append("\n🟢 无价格类失效/纪律红线被触发。")
    if naked:
        lines.append("\n⚠️  裸持仓(无thesis登记):")
        for r in naked:
            lines.append(f"  • {r['name']}({r['symbol']}) — {r.get('alert')}")
    lines.append("\n📋 各持仓状态 + 待人工核实的基本面失效条件:")
    for r in results:
        if not r["has_thesis"]:
            continue
        lines.append(f"\n  {r['name']}({r['symbol']}) | dd={r['drawdown_pct']}% | 红线{r.get('stop_discipline')}%")
        lines.append(f"    论点: {r['thesis']}")
        for m in r["manual_check"]:
            lines.append(f"    {m}")
    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not os.path.exists(THESIS):
        print(f"thesis.json 不存在: {THESIS}", file=sys.stderr)
        sys.exit(1)
    res = evaluate(a.account)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(render(res))


if __name__ == "__main__":
    main()
