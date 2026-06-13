#!/usr/bin/env python3
"""
模拟持仓 · 每日收盘绩效摘要推送
===============================
每个交易日收盘盯市完成后运行（建议盯市脚本跑完再跑本脚本，或通过 Hermes cron 触发）。
从 paper_trading.db 读取最新数据，生成 Discord 友好的绩效摘要。

输出到 stdout（由 Hermes cron 的 deliver 机制推送），也可直接跑来测试。

依赖：仅 stdlib sqlite3，无需 akshare。
"""
import sqlite3
import os
import sys
import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_trading.db")


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def pos_value(c, account_id):
    rows = c.execute("SELECT * FROM positions WHERE account_id=?", (account_id,)).fetchall()
    total = 0.0
    for p in rows:
        px = p["last_price"] if p["last_price"] is not None else p["avg_cost"]
        fx = p["fx_rate"] if p["fx_rate"] is not None else 1
        val = px * p["quantity"] * p["multiplier"] * fx
        if p["direction"] == "short":
            val = (2 * p["avg_cost"] - px) * p["quantity"] * p["multiplier"] * fx
        total += val
    return total


def pos_pnl_details(c, account_id):
    """返回各持仓的盈亏明细列表，按盈亏金额排序"""
    rows = c.execute("SELECT * FROM positions WHERE account_id=? AND asset_type='stock'", (account_id,)).fetchall()
    results = []
    for p in rows:
        px = p["last_price"] if p["last_price"] is not None else p["avg_cost"]
        cost = p["avg_cost"]
        fx = p["fx_rate"] if p["fx_rate"] is not None else 1
        mkt_val = px * p["quantity"] * p["multiplier"] * fx
        cost_base = cost * p["quantity"] * p["multiplier"] * fx
        pnl = mkt_val - cost_base
        pnl_pct = pnl / cost_base * 100 if cost_base else 0
        results.append({
            "symbol": p["symbol"],
            "name": p["name"] or p["symbol"],
            "mkt_val": mkt_val,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "last_price": px,
            "avg_cost": cost,
        })
    results.sort(key=lambda x: x["pnl"], reverse=True)
    return results


def fmt_cny(n):
    """格式化人民币金额"""
    abs_n = abs(n)
    if abs_n >= 1e8:
        return f"{n/1e8:+.2f}亿"
    if abs_n >= 1e4:
        return f"{n/1e4:+.2f}万"
    return f"{n:+,.0f}"


def get_prev_nav(c, account_id, today):
    """获取昨日净值快照"""
    row = c.execute(
        "SELECT total_nav, pnl_pct FROM nav_snapshots WHERE account_id=? AND snapshot_date < ? ORDER BY snapshot_date DESC LIMIT 1",
        (account_id, today)
    ).fetchone()
    return row


def main():
    today = datetime.date.today().isoformat()
    db = conn()

    accounts = db.execute("SELECT * FROM accounts WHERE status='active' ORDER BY id").fetchall()
    if not accounts:
        print("[SILENT]")
        return

    lines = []
    lines.append(f"**📊 模拟持仓 · 每日收盘报告 {today}**")
    lines.append("")

    # ── 总组合概览 ──────────────────────────────────────────────
    total_init = total_nav = 0.0
    for a in accounts:
        pv = pos_value(db, a["id"])
        nav = a["cash"] + pv
        total_init += a["initial_capital"]
        total_nav += nav

    total_pnl = total_nav - total_init
    total_pnl_pct = total_pnl / total_init * 100 if total_init else 0
    pnl_sign = "📈" if total_pnl >= 0 else "📉"

    lines.append(f"**总组合净值：{total_nav/1e8:.4f}亿**  {pnl_sign} {fmt_cny(total_pnl)} ({total_pnl_pct:+.2f}%)")
    lines.append("")

    # ── 各账户明细 ───────────────────────────────────────────────
    lines.append("**各账户概览：**")
    for a in accounts:
        pv = pos_value(db, a["id"])
        nav = a["cash"] + pv
        pnl = nav - a["initial_capital"]
        pnl_pct = pnl / a["initial_capital"] * 100 if a["initial_capital"] else 0

        # 当日净值变动（与昨日对比）
        prev = get_prev_nav(db, a["id"], today)
        today_snap = db.execute(
            "SELECT total_nav, pnl_pct FROM nav_snapshots WHERE account_id=? AND snapshot_date=?",
            (a["id"], today)
        ).fetchone()

        if prev and today_snap:
            day_chg = today_snap["total_nav"] - prev["total_nav"]
            day_pct = day_chg / prev["total_nav"] * 100 if prev["total_nav"] else 0
            day_str = f"  今日{fmt_cny(day_chg)} ({day_pct:+.2f}%)"
        else:
            day_str = ""

        icon = "🟢" if pnl >= 0 else "🔴"
        lines.append(f"{icon} **{a['name']}**  净值 {nav/1e4:.0f}万  累计 {pnl_pct:+.2f}%{day_str}")

        # 该账户持仓盈亏
        pos_details = pos_pnl_details(db, a["id"])
        if pos_details:
            for p in pos_details:
                bar = "▲" if p["pnl"] >= 0 else "▼"
                lines.append(f"   {bar} {p['name']}({p['symbol']})  {fmt_cny(p['pnl'])} ({p['pnl_pct']:+.2f}%)  现价{p['last_price']:.2f}")

    lines.append("")

    # ── 全组合赢家/输家 ──────────────────────────────────────────
    all_pos = []
    for a in accounts:
        details = pos_pnl_details(db, a["id"])
        for d in details:
            d["account"] = a["name"]
            all_pos.append(d)

    if all_pos:
        all_pos.sort(key=lambda x: x["pnl"], reverse=True)
        if len(all_pos) > 1:
            top = all_pos[0]
            bot = all_pos[-1]
            lines.append(f"**今日最强：** {top['name']} {fmt_cny(top['pnl'])} ({top['pnl_pct']:+.2f}%)")
            if bot["pnl"] < 0:
                lines.append(f"**今日最弱：** {bot['name']} {fmt_cny(bot['pnl'])} ({bot['pnl_pct']:+.2f}%)")

    # ── 现金储备状态 ──────────────────────────────────────────────
    total_cash = sum(a["cash"] for a in accounts)
    cash_ratio = total_cash / total_nav * 100 if total_nav else 0
    lines.append("")
    lines.append(f"**现金储备：** {total_cash/1e4:.0f}万 ({cash_ratio:.1f}% of NAV)")

    # ── Alpha / 基准对比（衡量是否真的在超越大盘）──────────────────
    try:
        arows = db.execute(
            "SELECT a.account_id, ac.name, a.port_ret, a.bench_ret, a.alpha "
            "FROM alpha_snapshots a JOIN accounts ac ON ac.id=a.account_id "
            "WHERE a.scope='equity' AND a.date=(SELECT MAX(date) FROM alpha_snapshots)"
        ).fetchall()
        if arows:
            lines.append("")
            lines.append("**Alpha vs 基准（选股口径，自建仓以来）：**")
            for r in arows:
                v = "✅跑赢" if r["alpha"] >= 0 else "⚠️跑输"
                lines.append(
                    f"   {v} {r['name']}：组合{r['port_ret']*100:+.2f}% − 基准{r['bench_ret']*100:+.2f}% = "
                    f"**α {r['alpha']*100:+.2f}pp**")
    except Exception:
        pass

    db.close()

    report = "\n".join(lines)
    print(report)


if __name__ == "__main__":
    main()
