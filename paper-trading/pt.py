#!/usr/bin/env python3
"""
模拟持仓系统 CLI (paper trading)
================================
纸面交易，不动真金白银。用法见各子命令 --help。

子命令：
  init                          初始化数据库
  create-account                创建账户（项目/策略一个账户，分配资金）
  list-accounts                 列出所有账户及现金
  buy / sell                    模拟买入/卖出（自动更新现金、持仓、流水）
  positions                     查看某账户或全部持仓
  mark                          盯市：更新某持仓最新价
  snapshot                      对账户做净值快照（回测曲线数据点）
  report                        账户总览：现金/持仓市值/总净值/收益率
  trades                        查看交易流水

所有金额以账户 base_currency 记账。跨币种标的 buy/sell 时传 --fx 汇率。
python: 用 /usr/bin/python3 即可（仅 stdlib sqlite3）。
"""
import argparse
import json
import sqlite3
import sys
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_trading.db")


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _live_price_quiet(symbol, currency, market):
    """尽力取当日实时价用于建仓价护栏；任何失败都安静返回 None（护栏不阻断主流程）。"""
    try:
        import akshare as ak
    except Exception:
        return None
    mk = "A"
    if currency == "HKD" or "HK" in (market or "").upper():
        mk = "HK"
    elif currency == "USD" or "US" in (market or "").upper() or "NASDAQ" in (market or "").upper():
        mk = "US"
    try:
        if mk == "HK":
            df = ak.stock_hk_spot()
            m = dict(zip(df["代码"].astype(str), df["最新价"]))
            return float(m.get(str(symbol).zfill(5)) or m.get(str(symbol)) or 0) or None
        if mk == "A":
            prefix = "sh" if str(symbol).startswith(("6", "9")) else "sz"
            d = ak.stock_zh_a_minute(symbol=f"{prefix}{symbol}", period="1", adjust="")
            return float(d.iloc[-1]["close"]) if len(d) else None
        if mk == "US":
            df = ak.stock_us_spot_em()
            m = dict(zip(df["代码"].astype(str), df["最新价"]))
            return float(m.get(str(symbol)) or 0) or None
    except Exception:
        return None
    return None


def _acct_id(c, name_or_id):
    if str(name_or_id).isdigit():
        return int(name_or_id)
    row = c.execute("SELECT id FROM accounts WHERE name=?", (name_or_id,)).fetchone()
    if not row:
        sys.exit(f"账户不存在: {name_or_id}")
    return row["id"]


def cmd_init(a):
    import schema
    schema.init_db()


def cmd_create_account(a):
    c = conn()
    c.execute(
        "INSERT INTO accounts(name,strategy,base_currency,initial_capital,cash,note) VALUES(?,?,?,?,?,?)",
        (a.name, a.strategy, a.currency, a.capital, a.capital, a.note),
    )
    c.commit()
    print(f"账户已创建: {a.name} | 策略={a.strategy} | 初始资金={a.capital:,.0f} {a.currency}")


def cmd_list_accounts(a):
    c = conn()
    rows = c.execute("SELECT * FROM accounts ORDER BY id").fetchall()
    out = [dict(r) for r in rows]
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_buy(a):
    c = conn()
    aid = _acct_id(c, a.account)
    # 数据完整性护栏：纸面建仓价应是【建仓当日】成交价，不是信号日的旧价。
    # 若与当日实时价偏离过大(默认>15%)，极可能误用了信号日价格（如康方09926曾被118.1旧价污染，
    # 实际建仓日区间仅82.85-90.25）。这里仅告警，不阻断，提醒人工核对。
    if a.asset_type == "stock" and not getattr(a, "no_price_check", False):
        ref = _live_price_quiet(a.symbol, a.currency, a.market)
        if ref and abs(a.price - ref) / ref > 0.15:
            print(f"⚠️ 建仓价护栏: {a.symbol} 录入价 {a.price} 与当日实时价 {ref} 偏离 "
                  f"{(a.price-ref)/ref*100:+.1f}% (>15%)。请确认是否误用了信号日旧价！"
                  f" 若确为当日真实价，加 --no-price-check 跳过。", file=sys.stderr)
    cost_base = a.qty * a.price * a.multiplier * a.fx + a.fee
    acct = c.execute("SELECT cash, base_currency FROM accounts WHERE id=?", (aid,)).fetchone()
    if cost_base > acct["cash"] + 1e-6:
        sys.exit(f"现金不足: 需 {cost_base:,.2f}，可用 {acct['cash']:,.2f}")
    # 更新/建立持仓
    pos = c.execute(
        "SELECT * FROM positions WHERE account_id=? AND asset_type=? AND symbol=? AND direction=?",
        (aid, a.asset_type, a.symbol, a.direction),
    ).fetchone()
    if pos:
        new_qty = pos["quantity"] + a.qty
        new_cost = (pos["avg_cost"] * pos["quantity"] + a.price * a.qty) / new_qty
        c.execute(
            "UPDATE positions SET quantity=?, avg_cost=?, last_price=?, updated_at=datetime('now','localtime') WHERE id=?",
            (new_qty, new_cost, a.price, pos["id"]),
        )
    else:
        c.execute(
            "INSERT INTO positions(account_id,asset_type,symbol,name,market,currency,direction,quantity,avg_cost,multiplier,fx_rate,last_price,meta) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (aid, a.asset_type, a.symbol, a.name, a.market, a.currency, a.direction, a.qty, a.price, a.multiplier, a.fx, a.price, a.meta),
        )
    c.execute("UPDATE accounts SET cash=cash-? WHERE id=?", (cost_base, aid))
    c.execute(
        "INSERT INTO trades(account_id,asset_type,symbol,name,market,currency,side,direction,quantity,price,multiplier,fx_rate,fee,reason,meta) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (aid, a.asset_type, a.symbol, a.name, a.market, a.currency, "buy", a.direction, a.qty, a.price, a.multiplier, a.fx, a.fee, a.reason, a.meta),
    )
    c.commit()
    print(f"买入 {a.name or a.symbol} x{a.qty} @ {a.price} ({a.currency}) | 花费 {cost_base:,.2f} 账户base | 理由: {a.reason}")


def cmd_sell(a):
    c = conn()
    aid = _acct_id(c, a.account)
    pos = c.execute(
        "SELECT * FROM positions WHERE account_id=? AND asset_type=? AND symbol=? AND direction=?",
        (aid, a.asset_type, a.symbol, a.direction),
    ).fetchone()
    if not pos or pos["quantity"] < a.qty - 1e-6:
        sys.exit(f"持仓不足: 持有 {pos['quantity'] if pos else 0}，欲卖 {a.qty}")
    proceeds_base = a.qty * a.price * a.multiplier * a.fx - a.fee
    realized = (a.price - pos["avg_cost"]) * a.qty * a.multiplier * a.fx - a.fee
    if a.direction == "short":
        realized = (pos["avg_cost"] - a.price) * a.qty * a.multiplier * a.fx - a.fee
    new_qty = pos["quantity"] - a.qty
    if new_qty <= 1e-6:
        c.execute("DELETE FROM positions WHERE id=?", (pos["id"],))
    else:
        c.execute("UPDATE positions SET quantity=?, last_price=?, updated_at=datetime('now','localtime') WHERE id=?", (new_qty, a.price, pos["id"]))
    c.execute("UPDATE accounts SET cash=cash+? WHERE id=?", (proceeds_base, aid))
    c.execute(
        "INSERT INTO trades(account_id,asset_type,symbol,name,market,currency,side,direction,quantity,price,multiplier,fx_rate,fee,realized_pnl,reason,meta) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (aid, a.asset_type, a.symbol, pos["name"], pos["market"], pos["currency"], "sell", a.direction, a.qty, a.price, a.multiplier, a.fx, a.fee, realized, a.reason, a.meta),
    )
    c.commit()
    print(f"卖出 {pos['name'] or a.symbol} x{a.qty} @ {a.price} | 实现盈亏 {realized:,.2f} 账户base | 理由: {a.reason}")


def cmd_positions(a):
    c = conn()
    if a.account:
        aid = _acct_id(c, a.account)
        rows = c.execute("SELECT p.*, ac.name AS acct FROM positions p JOIN accounts ac ON ac.id=p.account_id WHERE account_id=? ORDER BY p.id", (aid,)).fetchall()
    else:
        rows = c.execute("SELECT p.*, ac.name AS acct FROM positions p JOIN accounts ac ON ac.id=p.account_id ORDER BY p.account_id, p.id").fetchall()
    print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))


def cmd_mark(a):
    c = conn()
    aid = _acct_id(c, a.account)
    n = c.execute(
        "UPDATE positions SET last_price=?, updated_at=datetime('now','localtime') WHERE account_id=? AND symbol=?",
        (a.price, aid, a.symbol),
    ).rowcount
    c.commit()
    print(f"盯市更新: {a.symbol} -> {a.price} ({n} 条持仓)")


def _positions_value(c, aid):
    rows = c.execute("SELECT * FROM positions WHERE account_id=?", (aid,)).fetchall()
    total = 0.0
    for p in rows:
        px = p["last_price"] if p["last_price"] is not None else p["avg_cost"]
        fx = p["fx_rate"] if p["fx_rate"] is not None else 1
        # 估值统一换算到账户 base 币种：原币种价 × 数量 × 乘数 × 汇率
        val = px * p["quantity"] * p["multiplier"] * fx
        if p["direction"] == "short":
            val = (2 * p["avg_cost"] - px) * p["quantity"] * p["multiplier"] * fx
        total += val
    return total


def cmd_snapshot(a):
    c = conn()
    aid = _acct_id(c, a.account)
    acct = c.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()
    pv = _positions_value(c, aid)
    nav = acct["cash"] + pv
    pnl_pct = (nav - acct["initial_capital"]) / acct["initial_capital"] * 100
    date = a.date
    c.execute(
        "INSERT INTO nav_snapshots(account_id,snapshot_date,cash,positions_value,total_nav,pnl_pct) VALUES(?,?,?,?,?,?) ON CONFLICT(account_id,snapshot_date) DO UPDATE SET cash=excluded.cash,positions_value=excluded.positions_value,total_nav=excluded.total_nav,pnl_pct=excluded.pnl_pct",
        (aid, date, acct["cash"], pv, nav, pnl_pct),
    )
    c.commit()
    print(f"快照 {date} | {acct['name']}: 现金={acct['cash']:,.0f} 持仓={pv:,.0f} 净值={nav:,.0f} 收益={pnl_pct:+.2f}%")


def cmd_report(a):
    c = conn()
    rows = c.execute("SELECT * FROM accounts ORDER BY id").fetchall()
    total_nav = 0.0
    total_init = 0.0
    out = []
    for acct in rows:
        pv = _positions_value(c, acct["id"])
        nav = acct["cash"] + pv
        pnl_pct = (nav - acct["initial_capital"]) / acct["initial_capital"] * 100
        total_nav += nav
        total_init += acct["initial_capital"]
        out.append({
            "账户": acct["name"], "策略": acct["strategy"], "币种": acct["base_currency"],
            "初始资金": round(acct["initial_capital"], 0), "现金": round(acct["cash"], 0),
            "持仓市值": round(pv, 0), "净值": round(nav, 0), "收益率%": round(pnl_pct, 2),
        })
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if total_init:
        print(f"\n=== 全组合 === 初始 {total_init:,.0f} | 当前净值 {total_nav:,.0f} | 累计收益 {(total_nav-total_init)/total_init*100:+.2f}%")


def cmd_trades(a):
    c = conn()
    q = "SELECT t.*, ac.name AS acct FROM trades t JOIN accounts ac ON ac.id=t.account_id"
    params = []
    if a.account:
        q += " WHERE account_id=?"
        params.append(_acct_id(c, a.account))
    q += " ORDER BY t.id DESC LIMIT ?"
    params.append(a.limit)
    rows = c.execute(q, params).fetchall()
    print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser(description="模拟持仓系统 CLI (paper trading)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)

    s = sub.add_parser("create-account"); s.set_defaults(func=cmd_create_account)
    s.add_argument("--name", required=True); s.add_argument("--strategy", required=True)
    s.add_argument("--capital", type=float, required=True); s.add_argument("--currency", default="CNY")
    s.add_argument("--note", default="")

    sub.add_parser("list-accounts").set_defaults(func=cmd_list_accounts)

    for name, fn in [("buy", cmd_buy), ("sell", cmd_sell)]:
        s = sub.add_parser(name); s.set_defaults(func=fn)
        s.add_argument("--account", required=True)
        s.add_argument("--asset-type", dest="asset_type", default="stock", choices=["stock", "futures", "option"])
        s.add_argument("--symbol", required=True); s.add_argument("--name", default="")
        s.add_argument("--market", default=""); s.add_argument("--currency", default="CNY")
        s.add_argument("--direction", default="long", choices=["long", "short"])
        s.add_argument("--qty", type=float, required=True); s.add_argument("--price", type=float, required=True)
        s.add_argument("--multiplier", type=float, default=1); s.add_argument("--fx", type=float, default=1)
        s.add_argument("--fee", type=float, default=0); s.add_argument("--reason", default="")
        s.add_argument("--meta", default="")
        s.add_argument("--no-price-check", dest="no_price_check", action="store_true",
                       help="跳过建仓价 vs 当日实时价偏离护栏（确认录入价为当日真实价时用）")

    s = sub.add_parser("positions"); s.set_defaults(func=cmd_positions); s.add_argument("--account", default="")

    s = sub.add_parser("mark"); s.set_defaults(func=cmd_mark)
    s.add_argument("--account", required=True); s.add_argument("--symbol", required=True); s.add_argument("--price", type=float, required=True)

    s = sub.add_parser("snapshot"); s.set_defaults(func=cmd_snapshot)
    s.add_argument("--account", required=True)
    import datetime
    s.add_argument("--date", default=datetime.date.today().isoformat())

    sub.add_parser("report").set_defaults(func=cmd_report)

    s = sub.add_parser("trades"); s.set_defaults(func=cmd_trades)
    s.add_argument("--account", default=""); s.add_argument("--limit", type=int, default=20)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
