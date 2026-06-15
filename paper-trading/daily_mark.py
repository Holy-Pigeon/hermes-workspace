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

    主路：逐只单股 *_hist 接口取最近收盘（快、精准命中、不依赖几千行全表）。
    实测单只 <0.2s；旧版用 stock_hk_spot_em()/stock_zh_a_spot_em() 全表接口，
    港股全表分46页爬4660只耗时~52s，三市场叠加超120s → 脚本超时被杀 → 更新未commit
    → 表现为"持仓没数据"（如康方09926）。逐只方案 4 只票总取数 <1s。
    兜底：单只接口失效时回落全表批量。查不到/陈旧 → 不写入，保留上次价，绝不编造。
    """
    import akshare as ak
    prices = {}

    # ---- A股：逐只 stock_zh_a_hist ----
    for s in symbols_by_market.get("A", []):
        try:
            df, to = _call_with_timeout(
                lambda s=s: ak.stock_zh_a_hist(symbol=s, period="daily", adjust=""),
                PERSTOCK_TIMEOUT_SEC, f"A股单只 {s}")
            if to:
                continue
            if df is not None and len(df):
                row = df.iloc[-1]
                if _check_fresh(row["日期"], s):
                    prices[s] = float(row["收盘"])
        except Exception as e:
            log(f"  A股单只 {s} 失败: {repr(e)[:60]}")

    # ---- 港股：逐只 stock_hk_hist ----
    for s in symbols_by_market.get("HK", []):
        try:
            df, to = _call_with_timeout(
                lambda s=s: ak.stock_hk_hist(symbol=s.zfill(5), period="daily", adjust=""),
                PERSTOCK_TIMEOUT_SEC, f"港股单只 {s}")
            if to:
                continue
            if df is not None and len(df):
                row = df.iloc[-1]
                if _check_fresh(row["日期"], s):
                    prices[s] = float(row["收盘"])
        except Exception as e:
            log(f"  港股单只 {s} 失败: {repr(e)[:60]}")

    # ---- 美股：逐只 stock_us_hist ----
    for s in symbols_by_market.get("US", []):
        try:
            df, to = _call_with_timeout(
                lambda s=s: ak.stock_us_hist(symbol=s, period="daily", adjust=""),
                PERSTOCK_TIMEOUT_SEC, f"美股单只 {s}")
            if to:
                continue
            if df is not None and len(df):
                row = df.iloc[-1]
                if _check_fresh(row["日期"], s):
                    prices[s] = float(row["收盘"])
        except Exception as e:
            log(f"  美股单只 {s} 失败: {repr(e)[:60]}")

    # ---- 兜底：仍缺的标的，回落全表批量接口（仅对缺失市场拉一次）----
    missing = {mk: [s for s in syms if s not in prices]
               for mk, syms in symbols_by_market.items() if syms}
    missing = {mk: syms for mk, syms in missing.items() if syms}
    if missing:
        log(f"逐只接口未覆盖 {missing}，回落全表兜底")
        _fallback_spot(ak, missing, prices)

    # ---- 终极兜底：marketdata 统一层(sina→em 多源降级)。----
    # 病根: 本脚本逐只/全表全走东财(em)单源, 东财间歇全线 RemoteDisconnected 时(实测
    # 2026-06-15 全挂)4/4 持仓取价全失败→保留上次价→NAV 快照被陈旧价污染(风控backbone失效)。
    # marketdata 层有 sina 源, 东财全挂时仍能取到真实收盘。此处仅对"仍缺"的标的兜底,
    # 且复用 _check_fresh 同一新鲜度闸门, 拿不到/陈旧仍保留上次价, 绝不编造。纯增量、不改既有路径。
    still_missing = {mk: [s for s in syms if s not in prices]
                     for mk, syms in symbols_by_market.items() if syms}
    still_missing = {mk: syms for mk, syms in still_missing.items() if syms}
    if still_missing:
        try:
            import os as _os
            _root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
            if _root not in sys.path:
                sys.path.insert(0, _root)
            from marketdata import get_last_close
            log(f"全表兜底仍缺 {still_missing}，转 marketdata 统一层(sina→em)兜底")
            for mk, syms in still_missing.items():
                for s in syms:
                    try:
                        res, to = _call_with_timeout(
                            lambda s=s, mk=mk: get_last_close(s, mk),
                            PERSTOCK_TIMEOUT_SEC, f"marketdata {mk} {s}")
                        if to or res is None:
                            continue
                        px, dt = res
                        if px is not None and _check_fresh(dt, s):
                            prices[s] = float(px)
                            log(f"  {s} <- {px} (marketdata sina兜底, {dt})")
                    except Exception as e:
                        log(f"  marketdata {mk} {s} 兜底失败: {repr(e)[:60]}")
        except Exception as e:
            log(f"  marketdata 兜底整体不可用(忽略, 不影响既有逻辑): {repr(e)[:80]}")

    return prices


def _fallback_spot(ak, missing, prices):
    """全表批量兜底。仅在逐只接口失败时调用，慢但全。
    每个源套墙钟预算(FALLBACK_WALL_BUDGET_SEC), 总预算在源间共享递减——
    防止东财 hang 累加破 120s cron 墙杀掉脚本(NAV快照丢失的历史病根)。
    超时即放弃该源, 保留上次价 + 告警, 让脚本永远跑得到 commit+snapshot。"""
    import time
    deadline = time.monotonic() + FALLBACK_WALL_BUDGET_SEC

    def _remaining():
        return max(1.0, deadline - time.monotonic())

    if missing.get("A"):
        try:
            df, to = _call_with_timeout(ak.stock_zh_a_spot_em, _remaining(), "A股全表兜底")
            if not to and df is not None:
                m = dict(zip(df["代码"].astype(str), df["最新价"]))
                for s in missing["A"]:
                    if s in m and m[s] == m[s]:
                        prices[s] = float(m[s])
        except Exception as e:
            log(f"  A股全表兜底失败: {repr(e)[:60]}")
    if missing.get("HK"):
        try:
            df, to = _call_with_timeout(ak.stock_hk_spot_em, _remaining(), "港股全表兜底")
            if not to and df is not None:
                m = dict(zip(df["代码"].astype(str), df["最新价"]))
                for s in missing["HK"]:
                    key = s.zfill(5)
                    if key in m and m[key] == m[key]:
                        prices[s] = float(m[key])
                    elif s in m and m[s] == m[s]:
                        prices[s] = float(m[s])
        except Exception as e:
            log(f"  港股全表兜底失败: {repr(e)[:60]}")
    if missing.get("US"):
        try:
            df, to = _call_with_timeout(ak.stock_us_spot_em, _remaining(), "美股全表兜底")
            if not to and df is not None:
                m = dict(zip(df["代码"].astype(str), df["最新价"]))
                for s in missing["US"]:
                    if s in m and m[s] == m[s]:
                        prices[s] = float(m[s])
        except Exception as e:
            log(f"  美股全表兜底失败: {repr(e)[:60]}")


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
