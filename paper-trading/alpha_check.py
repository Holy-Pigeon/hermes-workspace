#!/usr/bin/env python3
"""
组合 Alpha / 基准跟踪器  (alpha_check.py, 纯只读 + 独立表)
=========================================================
为什么存在 —— 补上整个模拟持仓系统最大的认知黑洞:
我们的使命是「长期复合收益率超越巴菲特」, 这本质上是一场**相对收益**计分游戏。
但在此之前, 整个系统只记录**绝对盈亏**(stockchoose -2.46%), 从来不知道这个数字
到底是**跑赢还是跑输大盘**。-2.46% 如果当天沪深300 跌了 4%, 那其实是 +1.5% 的超额;
如果大盘涨了 1%, 那就是 -3.5% 的惨败。没有基准, 绝对收益数字毫无意义,
更无从谈起「超越巴菲特」—— 你连有没有超越指数都不知道。

这个工具做什么:
1. 计算每个有持仓账户【自建仓日(inception)以来】的组合收益率(绝对)。
2. 构建一个**市场敞口加权的混合基准**: A股敞口 -> 沪深300, 港股敞口 -> 恒生指数,
   权重 = 各市场投入本金占比。这是「如果我们不选股, 只买对应市场指数」的对照组。
3. 计算 **Alpha = 组合收益率 - 混合基准收益率**。这才是衡量我们选股能力的唯一标尺。
4. 同时给出两种口径:
   - equity-only(纯持仓口径): 剥离现金拖累, 衡量【选股 alpha】本身。
   - account(账户口径, 含现金): 衡量【账户整体】是否跑赢满仓指数(现金仓位也是一种决策)。
5. 把每日 alpha 快照写入独立表 alpha_snapshots, 积累超额收益曲线(回测/复盘基石)。

数据诚实:
- 指数点位全部来自 akshare 新浪/东财一手行情, 查不到就跳过该基准并告警, 绝不编造。
- inception 基准点位 = 建仓日(positions.opened_at 最早日)的指数收盘价, 从历史日线精确取。
- 标注「基准点位来源」与抓取时间。不混淆实时价与收盘价。

运行: /opt/homebrew/bin/python3 alpha_check.py [--quiet]
  --quiet: 无异常时静默(给 cron 用, 空 stdout 不打扰)。
纯只读现有表; 只新建/写入 benchmark_levels 与 alpha_snapshots 两张独立表, 不改持仓/不下单。
"""
import sqlite3
import os
import sys
import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_trading.db")

# 市场 -> 基准指数 (akshare stock_zh_index_daily symbol / 港股专用接口)
A_BENCH_SYMBOL = "sh000300"   # 沪深300
A_BENCH_NAME = "沪深300"
HK_BENCH_NAME = "恒生指数"


def log(msg):
    print(msg)


def ensure_tables(c):
    c.execute("""CREATE TABLE IF NOT EXISTS benchmark_levels(
        bench TEXT, date TEXT, close REAL, source TEXT, fetched_at TEXT,
        PRIMARY KEY(bench,date))""")
    c.execute("""CREATE TABLE IF NOT EXISTS alpha_snapshots(
        account_id INTEGER, date TEXT, scope TEXT,
        port_ret REAL, bench_ret REAL, alpha REAL,
        a_weight REAL, hk_weight REAL, created_at TEXT,
        PRIMARY KEY(account_id,date,scope))""")
    c.commit()


def fetch_index_series(market):
    """返回 {date_str: close} dict。market in ('A','HK')。失败返回 None。"""
    import akshare as ak
    try:
        if market == "A":
            df = ak.stock_zh_index_daily(symbol=A_BENCH_SYMBOL)  # 新浪源, 稳
            return {str(d): float(cl) for d, cl in zip(df["date"], df["close"])}, "sina:stock_zh_index_daily"
        else:  # HK
            df = ak.stock_hk_index_daily_em(symbol="HSI")
            # 列名: date, open, high, low, latest
            col = "latest" if "latest" in df.columns else "close"
            return {str(d): float(cl) for d, cl in zip(df["date"], df[col])}, "em:stock_hk_index_daily_em"
    except Exception as e:
        log(f"  [warn] {market} 基准抓取失败: {repr(e)[:70]}")
        return None, None


def nearest_on_or_before(series, target_date):
    """取 <= target_date 的最近一个交易日点位。series: {YYYY-MM-DD: close}。"""
    keys = sorted(k for k in series.keys() if k <= target_date)
    if not keys:
        return None, None
    return keys[-1], series[keys[-1]]


def latest_level(series):
    keys = sorted(series.keys())
    return keys[-1], series[keys[-1]]


def main():
    quiet = "--quiet" in sys.argv
    c = sqlite3.connect(DB_PATH)
    ensure_tables(c)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = datetime.date.today().isoformat()

    # ---- 1. 读持仓账户 + inception ----
    accounts = {}
    for aid, name, init_cap, cash in c.execute(
            "select id,name,initial_capital,cash from accounts"):
        accounts[aid] = {"name": name, "init": init_cap, "cash": cash,
                         "A_cost": 0.0, "HK_cost": 0.0, "A_val": 0.0, "HK_val": 0.0,
                         "inception": None}

    rows = list(c.execute(
        "select account_id,symbol,name,currency,quantity,avg_cost,last_price,fx_rate,opened_at "
        "from positions where quantity>0"))
    if not rows:
        if not quiet:
            log("无持仓, 无需 alpha 跟踪。")
        return

    for aid, sym, nm, cur, qty, cost, last, fx, opened in rows:
        a = accounts.get(aid)
        if a is None:
            continue
        mk = "HK" if cur == "HKD" else "A"
        cost_cny = qty * cost * (fx or 1.0)
        val_cny = qty * (last or cost) * (fx or 1.0)
        a[f"{mk}_cost"] += cost_cny
        a[f"{mk}_val"] += val_cny
        od = (opened or "")[:10]
        if od and (a["inception"] is None or od < a["inception"]):
            a["inception"] = od

    # ---- 2. 抓基准序列 (一次, 共享) ----
    a_series, a_src = fetch_index_series("A")
    hk_series, hk_src = fetch_index_series("HK")

    if a_series:
        ld, lv = latest_level(a_series)
        c.execute("INSERT OR REPLACE INTO benchmark_levels VALUES(?,?,?,?,?)",
                  (A_BENCH_NAME, ld, lv, a_src, now))
    if hk_series:
        ld, lv = latest_level(hk_series)
        c.execute("INSERT OR REPLACE INTO benchmark_levels VALUES(?,?,?,?,?)",
                  (HK_BENCH_NAME, ld, lv, hk_src, now))
    c.commit()

    out_lines = []
    flagged = False

    for aid, a in accounts.items():
        total_cost = a["A_cost"] + a["HK_cost"]
        if total_cost <= 0:
            continue  # 该账户无持仓
        incep = a["inception"]
        wa = a["A_cost"] / total_cost
        whk = a["HK_cost"] / total_cost

        # --- 基准收益: 各市场 (latest/incep - 1), 按本金权重加权 ---
        def bench_ret(series, incep_date):
            if not series:
                return None, None, None
            bd, bclose = nearest_on_or_before(series, incep_date)
            ld, lclose = latest_level(series)
            if bd is None or bclose in (None, 0):
                return None, None, None
            return (lclose / bclose - 1.0), (bd, bclose), (ld, lclose)

        a_r, a_base, a_now = bench_ret(a_series, incep) if a["A_cost"] > 0 else (0.0, None, None)
        hk_r, hk_base, hk_now = bench_ret(hk_series, incep) if a["HK_cost"] > 0 else (0.0, None, None)

        missing = (a["A_cost"] > 0 and a_r is None) or (a["HK_cost"] > 0 and hk_r is None)
        if missing:
            out_lines.append(f"[{a['name']}] 基准点位缺失, 跳过 alpha 计算(不编造)。")
            flagged = True
            continue

        blended_bench = wa * (a_r or 0.0) + whk * (hk_r or 0.0)

        # --- equity-only 组合收益 (剥离现金) ---
        total_val = a["A_val"] + a["HK_val"]
        port_ret_equity = total_val / total_cost - 1.0

        # --- account 口径 (含现金, 用 NAV) ---
        nav_row = c.execute(
            "select total_nav from nav_snapshots where account_id=? order by snapshot_date desc limit 1",
            (aid,)).fetchone()
        port_ret_acct = None
        if nav_row and a["init"]:
            port_ret_acct = nav_row[0] / a["init"] - 1.0

        alpha_equity = port_ret_equity - blended_bench

        # 写快照
        c.execute("INSERT OR REPLACE INTO alpha_snapshots VALUES(?,?,?,?,?,?,?,?,?)",
                  (aid, today, "equity", port_ret_equity, blended_bench, alpha_equity, wa, whk, now))
        if port_ret_acct is not None:
            # account 口径用同一混合基准做对照(账户含现金, 基准为满仓指数, 衡量现金决策+选股合力)
            alpha_acct = port_ret_acct - blended_bench
            c.execute("INSERT OR REPLACE INTO alpha_snapshots VALUES(?,?,?,?,?,?,?,?,?)",
                      (aid, today, "account", port_ret_acct, blended_bench, alpha_acct, wa, whk, now))

        # 输出
        out_lines.append(f"━━ [{a['name']}] 自 {incep} 建仓以来 ━━")
        out_lines.append(f"  市场敞口权重: A股 {wa*100:.0f}% / 港股 {whk*100:.0f}%  (按投入本金)")
        if a_base:
            out_lines.append(f"  沪深300: {a_base[1]:.1f}({a_base[0]}) → {a_now[1]:.1f}({a_now[0]})  = {a_r*100:+.2f}%")
        if hk_base:
            out_lines.append(f"  恒生:   {hk_base[1]:.1f}({hk_base[0]}) → {hk_now[1]:.1f}({hk_now[0]})  = {hk_r*100:+.2f}%")
        out_lines.append(f"  混合基准收益: {blended_bench*100:+.2f}%")
        out_lines.append(f"  ── 选股口径(equity-only) ──")
        out_lines.append(f"     组合收益 {port_ret_equity*100:+.2f}%  −  基准 {blended_bench*100:+.2f}%  =  ALPHA {alpha_equity*100:+.2f}%")
        if port_ret_acct is not None:
            out_lines.append(f"  ── 账户口径(含现金) ──")
            out_lines.append(f"     账户NAV收益 {port_ret_acct*100:+.2f}%  −  满仓基准 {blended_bench*100:+.2f}%  =  超额 {(port_ret_acct-blended_bench)*100:+.2f}%")
        # 判定: 跑输基准就标记(给 cron 用作信号)
        verdict = "跑赢✅" if alpha_equity >= 0 else "跑输⚠️"
        out_lines.append(f"  >>> 选股 {verdict} 基准 {abs(alpha_equity)*100:.2f}pp")
        if alpha_equity < 0:
            flagged = True

    c.commit()

    if out_lines and (not quiet or flagged):
        log(f"组合 Alpha / 基准跟踪  ({now})")
        log("基准: A股→沪深300(新浪) / 港股→恒生(东财), 一手行情")
        log("")
        for l in out_lines:
            log(l)
    c.close()


if __name__ == "__main__":
    main()
