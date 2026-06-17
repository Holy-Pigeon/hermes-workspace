#!/usr/bin/env python3
"""
模拟持仓系统 · 收盘自动盯市 + 净值快照
=========================================
每个交易日收盘后跑：用 akshare 拉所有持仓的最新价 → mark 更新 → 对每个账户 snapshot。
自动积累净值曲线（nav_snapshots），是回测数据的来源。

运行环境：必须用 /opt/homebrew/bin/python3（akshare 在那）。
但 pt.py 用 sqlite3（stdlib），homebrew python3 也有，所以本脚本直接操作 DB，不调 pt.py CLI。

价格获取：
- A股(沪/深)：ak.stock_zh_a_spot_em() 或单只 ak.stock_bid_ask_em，用 stock_zh_a_spot_em 批量更快
- 港股：ak.stock_hk_spot_em()
- 美股(未来 us-tech-value 建仓后)：ak.stock_us_spot_em() —— 暂未持仓，先留接口
查不到的标的：跳过(保留上次 last_price)，并打印告警 —— 绝不编造价格。

去重/幂等：snapshot 用 ON CONFLICT 覆盖当日，重复跑安全。
"""
import sqlite3
import os
import sys
import datetime
import threading

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_trading.db")

# 全表兜底的墙钟时间预算(秒)。东财间歇 RemoteDisconnected 时港股全表分46页爬~52s,
# A+HK+US 叠加破 120s cron 墙 → 进程被杀在 commit 前 → NAV 快照丢失(风控backbone失效)。
# 给兜底设硬预算: 超时即放弃该源, 保留上次价 + 告警, 让脚本永远跑得到 commit+snapshot。
# 单只主路(<1s)不受此限, 仅护栏慢兜底。
FALLBACK_WALL_BUDGET_SEC = float(os.environ.get("DAILY_MARK_FALLBACK_BUDGET", "45"))
# 单只主路硬墙: akshare *_hist 在东财 hang(不抛异常)时会拖死主路, 普通 try/except 救不了。
# 历史病根: 主路无此墙 → 东财 hang 时 4 只票串行各 hang 数十秒叠加破 120s cron 墙 →
# 进程被杀在 commit 前 → NAV 快照丢失(2026-06-12起连续3天盯市失效)。每只票套硬墙,
# 超时即放弃该只(走全表兜底→兜底再不行保留上次价), 让脚本永远跑得到 commit+snapshot。
PERSTOCK_TIMEOUT_SEC = float(os.environ.get("DAILY_MARK_PERSTOCK_TIMEOUT", "8"))


def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")


def _call_with_timeout(fn, timeout_sec, label):
    """在 daemon 线程跑 fn(), join 超时即放弃(返回 None)。
    akshare 底层 HTTP 可能 hang 不抛异常, 普通 try/except 救不了, 必须线程级硬墙。
    返回 (result, timed_out)。"""
    box = {}

    def _run():
        try:
            box["r"] = fn()
        except Exception as e:  # noqa
            box["e"] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout_sec)
    if t.is_alive():
        log(f"  ⏱ {label} 超时 >{timeout_sec:.0f}s(hang), 放弃兜底, 保留上次价")
        return None, True
    if "e" in box:
        raise box["e"]
    return box.get("r"), False


def is_a_share_trading_day():
    """粗判：周末不交易。法定节假日不在此处理（akshare 拉不到当日数据时自然跳过）。"""
    return datetime.date.today().weekday() < 5


def _today_str():
    return datetime.date.today().strftime("%Y-%m-%d")


def _check_fresh(date_val, sym):
    """末行日期是否够新（今天或最近1个自然日内）。停牌/接口陈旧时返回 False，宁可缺也不用脏价。"""
    try:
        ds = str(date_val)[:10]
        d = datetime.datetime.strptime(ds, "%Y-%m-%d").date()
        stale_days = (datetime.date.today() - d).days
        if stale_days > 3:
            log(f"  ⚠️ {sym} 末行日期 {ds} 距今 {stale_days} 天，疑似停牌/陈旧，跳过不污染")
            return False
        return True
    except Exception:
        return True  # 解析失败不阻断，照常用


def fetch_prices(symbols_by_market):
    """返回 {symbol: price}。

    统一走 marketdata.get_last_close_batch（腾讯单请求批量一次拿全，未命中的
    并发降级 sina→em 日线 + sina/腾讯直连终极兜底）。整池通常 <1s，且内部多源
    自动降级——彻底取代旧版「逐只 akshare 串行 + 全表兜底 + marketdata 垫底」
    三层复杂逻辑（东财单源一断就全崩、串行 hang 累加破 cron 墙的历史病根）。

    保留 _check_fresh 新鲜度闸门：末行日期距今 >3 天视为停牌/陈旧，不写入，
    保留上次价 —— 绝不编造，绝不用脏价污染 NAV 快照。
    查不到的标的不进返回 dict，调用方据此保留上次价。
    """
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from marketdata import get_last_close_batch

    # 组装批量请求：[(symbol, market), ...]
    items = []
    for mk, syms in symbols_by_market.items():
        for s in syms:
            items.append((s, mk))
    if not items:
        return {}

    prices = {}
    try:
        marks = get_last_close_batch(items)  # {(sym,mk): (price, date)}
    except Exception as e:
        log(f"  marketdata 批量取价整体失败(保留上次价,不编造): {repr(e)[:80]}")
        return prices

    for (sym, mk), val in marks.items():
        if val is None:
            continue
        px, dt = val
        if px is not None and _check_fresh(dt, sym):
            prices[sym] = float(px)
            log(f"  {sym} <- {px} (marketdata, {dt})")
    return prices


def classify_market(market, currency):
    if currency == "HKD" or "HK" in (market or "").upper():
        return "HK"
    if currency == "USD" or "US" in (market or "").upper() or "NASDAQ" in (market or "").upper():
        return "US"
    return "A"


def main():
    if not is_a_share_trading_day():
        log("周末，非交易日，跳过盯市。")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 1. 收集所有持仓标的，按市场分类
    rows = conn.execute("SELECT DISTINCT symbol, market, currency, asset_type FROM positions WHERE asset_type='stock'").fetchall()
    if not rows:
        log("无股票持仓，无需盯市（期货/期权暂不自动盯市）。")
        # 仍对所有账户快照（现金账户净值也要记录曲线）
        do_snapshots(conn)
        conn.close()
        return

    symbols_by_market = {"A": set(), "HK": set(), "US": set()}
    sym_meta = {}
    for r in rows:
        mk = classify_market(r["market"], r["currency"])
        symbols_by_market[mk].add(r["symbol"])
        sym_meta[r["symbol"]] = mk

    log(f"待盯市标的: A股{len(symbols_by_market['A'])} 港股{len(symbols_by_market['HK'])} 美股{len(symbols_by_market['US'])}")

    # 2. 拉价格
    prices = fetch_prices(symbols_by_market)

    # 3. mark 更新
    updated, missing = 0, []
    for sym, mk in sym_meta.items():
        if sym in prices:
            conn.execute(
                "UPDATE positions SET last_price=?, updated_at=datetime('now','localtime') WHERE symbol=? AND asset_type='stock'",
                (prices[sym], sym),
            )
            updated += 1
            log(f"  {sym} -> {prices[sym]}")
        else:
            missing.append(sym)
    conn.commit()
    if missing:
        log(f"⚠️ 未取到价格(保留上次价,不编造): {missing}")

    # 4. 快照所有账户
    do_snapshots(conn)
    conn.close()
    log(f"盯市完成: 更新 {updated} 只，缺失 {len(missing)} 只。")


def _positions_value(conn, aid):
    rows = conn.execute("SELECT * FROM positions WHERE account_id=?", (aid,)).fetchall()
    total = 0.0
    for p in rows:
        px = p["last_price"] if p["last_price"] is not None else p["avg_cost"]
        fx = p["fx_rate"] if p["fx_rate"] is not None else 1
        val = px * p["quantity"] * p["multiplier"] * fx
        if p["direction"] == "short":
            val = (2 * p["avg_cost"] - px) * p["quantity"] * p["multiplier"] * fx
        total += val
    return total


def do_snapshots(conn):
    date = datetime.date.today().isoformat()
    accts = conn.execute("SELECT * FROM accounts WHERE status='active'").fetchall()
    for a in accts:
        pv = _positions_value(conn, a["id"])
        nav = a["cash"] + pv
        pnl = (nav - a["initial_capital"]) / a["initial_capital"] * 100
        conn.execute(
            "INSERT INTO nav_snapshots(account_id,snapshot_date,cash,positions_value,total_nav,pnl_pct) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(account_id,snapshot_date) DO UPDATE SET cash=excluded.cash,positions_value=excluded.positions_value,total_nav=excluded.total_nav,pnl_pct=excluded.pnl_pct",
            (a["id"], date, a["cash"], pv, nav, pnl),
        )
        log(f"快照 {a['name']}: 净值={nav:,.0f} 收益={pnl:+.2f}%")
    conn.commit()


if __name__ == "__main__":
    main()
