#!/usr/bin/env python3
"""
martingale-guard · 加仓摊低负偏度哨兵
====================================================================
它盯的是什么(系统级 gap,不是缺某只票):
  用户 #1 自陈的爆仓机制 = 「马丁格尔 + 满仓 = 负偏度」——不断向下加仓
  摊低成本、越亏越买、仓位越滚越大,一次不回头就归零。

  但现有配置层三个工具全部盯不到这个:
    - allocation-discipline: 只看【某一天快照】的静态权重集中度(单标的封顶/等权惰性)
    - exit-sentinel:         只看【论点是否破裂】(裸持/窗口/价格背离)
    - capital-deployment:    只看【现金部署率】

  三者都不读 trades 的【时间序列】,看不到「同一只票在下跌途中被反复买入、
  且每次买得更多」这条最危险的行为轨迹。这是 temporal 维度的盲区。

它做什么(纯只读,绝不下单、绝不改库):
  读 paper_trading.db 的 trades 表,对每个 symbol 把 buy 序列按时间排开,检测:
    R1 加仓摊低 (average-down):  后续 buy 价 < 首次 buy 价,即向下加仓
    R2 马丁放大 (size escalation): 后续 buy 的金额 ≥ 前一次 buy 金额(越亏买越多)
    R3 负偏度轨迹 (R1 且 R2 同时成立): 最危险——下跌途中还在加码 = 教科书马丁
    R4 现价确认 (可选,marketdata): 拉现价,若加仓后当前仍浮亏,红旗升级为「已兑现风险」

  分级:
    🔴 R3 命中(向下加仓且金额放大)              = 触碰用户预承诺红线
    🟠 R1 命中(向下加仓但金额未放大)            = 摊低但未马丁,警戒
    🟡 单标的累计买入次数 ≥ THRESH(频繁加仓)     = 行为惯性苗头
    🟢 每个 symbol 仅单次建仓 / 加仓在上涨途中     = 干净(顺势非逆势)

设计哲学:哨兵只把「有没有在重演马丁轨迹」算成数字 surface 给人,不喊买卖。
当前模拟盘 4 持仓均为单次建仓 = 应报 🟢,本工具是【面向未来的绊线】:
一旦哪天开始向下加仓,cron 立即 --quiet 出声。防患于未然 > 事后复盘。

数据诚实:
  - 序列全部来自 trades 一手成交记录,不估算。
  - 现价用 marketdata 多源容错;取不到就跳过 R4 只做 R1-R3(不编造现价)。
  - 阈值是防御性预承诺参数,非预测,非买卖指令。
"""
import sqlite3, os, sys, argparse, json
from collections import defaultdict

DB = os.path.expanduser("~/hermes-workspace/paper-trading/paper_trading.db")

# ── 预承诺阈值(可调) ──
FREQ_THRESH   = 3      # 单标的买入次数 ≥ 此值 → 🟡 频繁加仓苗头
DOWN_EPS      = 0.005  # 价格视为"下跌"的最小跌幅(0.5%,滤噪)
SIZE_EPS      = 0.98   # 后一次金额 ≥ 前次的此倍数 → 视为"未缩量/放大"


def load_trades(account=None):
    if not os.path.exists(DB):
        raise SystemExit(f"[martingale-guard] DB 不存在: {DB}")
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    acc_filter, params = "", []
    if account:
        row = c.execute("SELECT id FROM accounts WHERE name=? OR id=?",
                        (account, account)).fetchone()
        if row:
            acc_filter = "WHERE account_id=?"; params = [row["id"]]
    q = (f"SELECT symbol,name,market,currency,side,quantity,price,fx_rate,traded_at "
         f"FROM trades {acc_filter} ORDER BY traded_at ASC, id ASC")
    rows = [dict(r) for r in c.execute(q, params)]
    c.close()
    return rows


def try_price(symbol, market):
    """尽力取现价;取不到返回 None(绝不编造)。"""
    try:
        sys.path.insert(0, os.path.expanduser("~/hermes-workspace"))
        from marketdata import get_last_close
        mkt = "HK" if (market and "HK" in market.upper()) else \
              ("US" if (market and "US" in (market or "").upper()) else "A")
        return get_last_close(symbol, market=mkt)
    except Exception:
        return None


def analyze(account=None, use_price=True):
    trades = load_trades(account)
    buys = defaultdict(list)
    for t in trades:
        if str(t["side"]).lower() == "buy":
            buys[t["symbol"]].append(t)

    findings = []
    for sym, seq in buys.items():
        if len(seq) < 2:
            # 单次建仓 = 干净
            findings.append({"symbol": sym, "name": seq[0]["name"],
                             "level": "🟢", "n_buys": 1,
                             "detail": "单次建仓,无加仓轨迹"})
            continue

        name = seq[0]["name"]
        first_px = seq[0]["price"]
        r1 = r3 = False
        legs = []
        prev_notional = None
        for i, t in enumerate(seq):
            notional = t["quantity"] * t["price"] * (t["fx_rate"] or 1.0)
            down = i > 0 and t["price"] < first_px * (1 - DOWN_EPS)
            escalate = prev_notional is not None and notional >= prev_notional * SIZE_EPS
            if down:
                r1 = True
                if escalate:
                    r3 = True
            legs.append({"i": i, "px": t["price"], "notional": round(notional),
                         "down_vs_first": down, "escalate_vs_prev": bool(escalate),
                         "at": t["traded_at"]})
            prev_notional = notional

        # 现价确认(R4)
        px_now, underwater = None, None
        if use_price:
            px_now = try_price(sym, seq[0]["market"])
            if px_now is not None:
                # 加权平均成本
                tot_q = sum(t["quantity"] for t in seq)
                tot_c = sum(t["quantity"] * t["price"] for t in seq)
                avg_cost = tot_c / tot_q if tot_q else None
                underwater = (avg_cost is not None and px_now < avg_cost)

        if r3:
            level = "🔴"
            detail = "马丁轨迹:下跌途中加仓且金额未缩量/放大(触碰负偏度红线)"
            if underwater:
                detail += " · 现价仍浮亏=已兑现风险"
        elif r1:
            level = "🟠"
            detail = "向下加仓摊低成本(未放大金额,仍属逆势加仓)"
        else:
            # 所有后续加仓都在首笔成本上方 = 顺势金字塔加码(向赢家加仓),
            # 是马丁的反面(向输家加仓),无论次数多少都判 🟢。
            all_up = all(t["price"] >= first_px * (1 - DOWN_EPS) for t in seq[1:])
            if all_up:
                level = "🟢"
                detail = f"顺势加仓({len(seq)}次,均在成本上方=向赢家加码,马丁反面)"
            elif len(seq) >= FREQ_THRESH:
                level = "🟡"
                detail = f"频繁加仓({len(seq)}次,含横盘/微跌),警惕行为惯性苗头"
            else:
                level = "🟢"
                detail = f"多次买入({len(seq)}次)但未构成向下加仓轨迹"

        findings.append({"symbol": sym, "name": name, "level": level,
                         "n_buys": len(seq), "first_px": first_px,
                         "px_now": px_now, "underwater": underwater,
                         "legs": legs, "detail": detail})
    return findings


def main():
    ap = argparse.ArgumentParser(description="加仓摊低负偏度哨兵")
    ap.add_argument("--account", default=None, help="账户名或id,默认全部")
    ap.add_argument("--quiet", action="store_true",
                    help="cron 友好:仅 🔴/🟠 才输出,🟡🟢 静默")
    ap.add_argument("--no-price", action="store_true", help="跳过现价确认(R4)")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    findings = analyze(account=args.account, use_price=not args.no_price)
    order = {"🔴": 0, "🟠": 1, "🟡": 2, "🟢": 3}
    findings.sort(key=lambda f: order.get(f["level"], 9))

    hard = [f for f in findings if f["level"] in ("🔴", "🟠")]

    if args.json:
        print(json.dumps({"findings": findings, "hard_flags": len(hard)},
                         ensure_ascii=False, indent=2))
        return 1 if any(f["level"] == "🔴" for f in findings) else 0

    show = hard if args.quiet else findings
    if args.quiet and not hard:
        return 0  # 静默

    print("═" * 60)
    print("  马丁格尔加仓哨兵 · 负偏度轨迹检测")
    print("═" * 60)
    for f in show:
        line = f"{f['level']} {f['name']}({f['symbol']}) · 买入{f['n_buys']}次 · {f['detail']}"
        print(line)
        if not args.quiet and f["level"] in ("🔴", "🟠") and f.get("legs"):
            for lg in f["legs"]:
                mark = "↓加仓" if lg["down_vs_first"] else "  "
                esc = "·放大" if lg["escalate_vs_prev"] else ""
                print(f"      [{lg['i']}] {lg['at'][:10]} @{lg['px']} "
                      f"金额{lg['notional']:,} {mark}{esc}")
    if not hard:
        print("\n✅ 无马丁轨迹:所有持仓均为单次/顺势建仓,负偏度红线未触碰。")
    print("═" * 60)
    return 1 if any(f["level"] == "🔴" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
