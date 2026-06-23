#!/usr/bin/env python3
"""
call-alpha-tracker · 研究「呼叫」的基准调整收益记分卡

为什么存在（元层能力缺口，非缺某只票）
---------------------------------------------------
系统使命「超越巴菲特」本质是一个**相对收益**游戏。但全系统唯一的计分卡
prediction-ledger 衡量的是**基本面论点是否兑现**（中报净利是否 beat、margin
是否守住），它**不回答「按这个判断行动到底跑赢还是跑输大盘」**。

二者会系统性背离：
  - 论点「correct」但股票跑输沪深300（赚了认知，亏了相对钱）；
  - 论点「wrong」但股票暴涨（陷阱判定错，但若做空会巨亏）。
我们有 13 条带方向(direction)+建仓日(created)的研究呼叫，却**零跟踪**它们
从呼叫日至今的「基准调整后呼叫α」。没有这个闭环，就无法证伪：我们的研究
流程到底在为组合创造相对收益，还是只在产出读起来很对的note。

本工具就是那个闭环：对每条 prediction，取
  · 标的从呼叫日→今日的涨跌（marketdata 一手日线，多源降级）
  · 同期匹配基准（A→沪深300 / HK→恒生）的涨跌
  · 按呼叫方向(看多/看空)折算「呼叫α」= 方向 × (标的 − 基准)
正的呼叫α = 这条研究呼叫**既方向对、又跑赢基准**=真创造相对收益。

边界与诚实纪律
---------------------------------------------------
- 纯只读。取数全走 marketdata（get_daily / safe_call），任一源失败即跳过该条
  并标 SKIP，**绝不编造价格或收益**。
- 呼叫α是**至今的浮动相对收益**，不是已结算业绩；论点未到证伪窗口前，它只是
  「市场迄今怎么投票」的过程读数，与 prediction-ledger 的事后 Brier 互补不替代。
- 方向映射只覆盖已知 direction 取值；未知方向标 UNKNOWN 不强行计分。
- 必须用 /opt/homebrew/bin/python3 运行（akshare/marketdata 依赖装在那）。
"""
import sys, os, json, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
sys.path.insert(0, WS)  # 让 marketdata 可被 import

LEDGER = os.path.join(WS, "prediction-ledger", "predictions.json")

# direction → 持仓立场: +1 看多(期望标的跑赢基准) / -1 看空(期望跑输) / 0 不计分
DIRECTION_STANCE = {
    "bearish_on_valuation": -1,
    "value_trap_warning": -1,
    "bearish": -1,
    "overvalued": -1,
    "distribution_topping": -1,            # 筹码顶部派发=看空
    "mispriced_trough_not_trap": +1,
    "bullish": +1,
    "undervalued": +1,
    "bullish_on_recovery": +1,
    "real_cheap_not_trap": +1,             # 真便宜非陷阱=看多
    "real_cheap_growth": +1,
    "organic_ramp_intact": +1,             # 放量逻辑完好=看多
    "recovery_inflection_not_trap": +1,    # 复苏拐点=看多
    "reasonably_undervalued_growth": +1,
    "smart_money_accumulation": +1,        # 聪明钱吸筹=看多
    "moat_understated": +1,                # 护城河被低估=看多
    # 中性/结构性预测(如分散化)不计方向α
    "low_correlation_diversifier": 0,
    "diversification": 0,
    "neutral": 0,
}

# 标的代码 → 市场 + 基准。HK 用恒生, A 用沪深300, US 用纳指100(QQQ)
def market_of(symbol):
    # 港股: 5位数字(09926/00700) / A股: 6位数字 / 美股: 无数字(纯字母代码 AAPL/MSFT)
    digits = "".join(ch for ch in symbol if ch.isdigit())
    if len(digits) == 5:
        return "HK"
    if len(digits) == 6:
        return "A"
    if len(digits) == 0:
        return "US"   # us-tech-scout 暗区 sleeve 的纯字母代码, 否则会被默认错配到沪深300
    return "A"


def log(m):
    print(m, file=sys.stderr)


def fetch_stock_series(symbol, market):
    """返回 {date_str: close}，失败抛异常（绝不编造）。"""
    from marketdata import get_daily
    digits = "".join(ch for ch in symbol if ch.isdigit())
    code = digits if digits else symbol
    df = get_daily(code, market=market)
    if df is None or len(df) == 0:
        raise RuntimeError("空日线")
    return {str(d): float(c) for d, c in zip(df["date"], df["close"]) if c == c}


def fetch_benchmark_series(market):
    """A→沪深300(新浪稳源) / HK→恒生(东财→新浪降级)。返回(series, name, src)。"""
    from marketdata import safe_call
    import akshare as ak
    if market == "A":
        df = safe_call(lambda: ak.stock_zh_index_daily(symbol="sh000300"),
                       label="bench:沪深300")
        s = {str(d): float(c) for d, c in zip(df["date"], df["close"])}
        return s, "沪深300", "sina:stock_zh_index_daily"
    if market == "HK":
        # 东财优先, 失败降级新浪
        try:
            df = safe_call(lambda: ak.stock_hk_index_daily_em(symbol="HSI"),
                           label="bench:HSI:em", attempts=2)
            col = "latest" if "latest" in df.columns else df.columns[-1]
            s = {str(d): float(c) for d, c in zip(df["date"], df[col])}
            return s, "恒生指数", "em:stock_hk_index_daily_em"
        except Exception:
            df = safe_call(lambda: ak.stock_hk_index_daily_sina(symbol="HSI"),
                           label="bench:HSI:sina")
            col = "close" if "close" in df.columns else df.columns[-1]
            s = {str(d): float(c) for d, c in zip(df["date"], df[col])}
            return s, "恒生指数", "sina:stock_hk_index_daily_sina"
    if market == "US":
        # 复用已验证的 marketdata 美股日线通道(stock_us_daily), QQQ=纳指100 ETF 作科技基准
        from marketdata import get_daily
        df = get_daily("QQQ", market="US")
        s = {str(d): float(c) for d, c in zip(df["date"], df["close"]) if c == c}
        return s, "纳指100(QQQ)", "marketdata:get_daily(US)"
    raise RuntimeError(f"无{market}基准")


def nearest_on_or_after(series, target):
    """取 >= target 的最早一天(呼叫日当天若停牌取之后第一个交易日)。"""
    ks = sorted(k for k in series.keys() if k >= target)
    return (ks[0], series[ks[0]]) if ks else (None, None)


def latest(series):
    k = max(series.keys())
    return k, series[k]


def main():
    quiet = "--quiet" in sys.argv
    as_json = "--json" in sys.argv
    if not os.path.exists(LEDGER):
        log("找不到 prediction-ledger/predictions.json")
        sys.exit(2)
    data = json.load(open(LEDGER))
    preds = data if isinstance(data, list) else data.get("predictions", [])

    bench_cache = {}
    rows = []
    for p in preds:
        if p.get("outcome") not in (None, "pending"):
            continue  # 已结算的交给 ledger 的 Brier, 这里只看进行中的过程α
        subj = p.get("subject", "")
        direction = p.get("direction", "")
        stance = DIRECTION_STANCE.get(direction, None)
        created = p.get("created")
        pid = p.get("id")
        if stance is None:
            rows.append({"id": pid, "subject": subj, "status": "UNKNOWN_DIR",
                         "direction": direction})
            continue
        if stance == 0:
            rows.append({"id": pid, "subject": subj, "status": "NO_DIR_ALPHA",
                         "direction": direction})
            continue
        mkt = market_of(subj)
        try:
            ss = fetch_stock_series(subj, mkt)
        except Exception as e:
            rows.append({"id": pid, "subject": subj, "status": "SKIP_STOCK",
                         "err": str(e)[:60]})
            continue
        if mkt not in bench_cache:
            try:
                bench_cache[mkt] = fetch_benchmark_series(mkt)
            except Exception as e:
                bench_cache[mkt] = ("ERR", str(e)[:60])
        bres = bench_cache[mkt]
        if bres[0] == "ERR":
            rows.append({"id": pid, "subject": subj, "status": "SKIP_BENCH",
                         "err": bres[1]})
            continue
        bs, bname, bsrc = bres
        s0d, s0 = nearest_on_or_after(ss, created)
        b0d, b0 = nearest_on_or_after(bs, created)
        if s0 is None or b0 is None:
            rows.append({"id": pid, "subject": subj, "status": "SKIP_NODATE"})
            continue
        s1d, s1 = latest(ss)
        b1d, b1 = latest(bs)
        sr = (s1 / s0 - 1) * 100
        br = (b1 / b0 - 1) * 100
        excess = sr - br
        call_alpha = stance * excess  # 看空时跑输基准=正贡献
        rows.append({
            "id": pid, "subject": subj, "direction": direction,
            "stance": "看多" if stance > 0 else "看空",
            "from": s0d, "stock_ret": round(sr, 2), "bench": bname,
            "bench_ret": round(br, 2), "excess": round(excess, 2),
            "call_alpha": round(call_alpha, 2), "status": "OK",
            "verify_by": p.get("verify_by"),
        })

    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return

    ok = [r for r in rows if r["status"] == "OK"]
    if quiet and not ok:
        sys.exit(0)

    print("=" * 64)
    print("研究呼叫 · 基准调整后呼叫α 记分卡  (至今浮动, 非结算业绩)")
    print(f"  生成: {datetime.date.today()}  |  进行中呼叫: {len(ok)} 条")
    print("=" * 64)
    if ok:
        winners = [r for r in ok if r["call_alpha"] > 0]
        print(f"  方向对+跑赢基准(正呼叫α): {len(winners)}/{len(ok)}")
        avg = sum(r["call_alpha"] for r in ok) / len(ok)
        print(f"  平均呼叫α: {avg:+.2f}pp")
        print("-" * 64)
        for r in sorted(ok, key=lambda x: -x["call_alpha"]):
            flag = "✅" if r["call_alpha"] > 0 else "❌"
            print(f"{flag} {r['id']} {r['subject'][:18]:<18} [{r['stance']}] "
                  f"自{r['from']}: 标的{r['stock_ret']:+.1f}% "
                  f"vs {r['bench']}{r['bench_ret']:+.1f}% "
                  f"→ 呼叫α {r['call_alpha']:+.1f}pp")
    skips = [r for r in rows if r["status"] not in ("OK",)]
    if skips:
        print("-" * 64)
        for r in skips:
            print(f"   · {r['id']} {r['subject'][:18]:<18} {r['status']} "
                  f"{r.get('err', r.get('direction', ''))}")
    print("=" * 64)
    print("注: 呼叫α=方向×(标的−基准)的至今浮动相对收益; 与 prediction-ledger")
    print("    事后Brier(论点是否兑现)互补——这里答'按判断行动跑没跑赢大盘'。")


if __name__ == "__main__":
    main()
