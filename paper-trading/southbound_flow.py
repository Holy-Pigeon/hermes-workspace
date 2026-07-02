#!/usr/bin/env python3
"""southbound_flow.py — 港股通(南向资金)持股流向监控 (纯只读, 一手 akshare)

填补整个系统最大的覆盖盲区: 唯一的港股持仓康方生物(09926)此前无任何
资金流/筹码维度信号(A股股东户数 holder_concentration.py 拉不到港股, 北向
per-stock 数据已于 2024-08 被监管冻结)。南向 per-stock 持股(东财 stock_hsgt_
individual_em)对港股通标的仍 LIVE(实测康方更新至建仓当日), 且南向资金=
内地机构/聪明钱, 与价格/财报/临床维度完全不重叠。

核心设计 = 方向依赖(同 holder_concentration 的吸筹/派发框架, 但用占比变化):
  占比↑ + 价跌 = 🟢 弱势吸筹(南向逆势加仓, 强信号)
  占比↑ + 价涨 = 🟢 顺势增持
  占比↓ + 价涨 = 🔴 派发(南向在涨势中减仓出货)
  占比↓ + 价跌 = 🟡 资金流出/割肉(左侧未见底)
单看占比无意义, 必配同期股价。

数据: 东财 stock_hsgt_individual_em(symbol=港股代码), 日频。
非买卖指令; 占比是历史读数不预测股价; 拉不到的标的跳过+告警绝不编造。
"""
import sys, argparse
import pandas as pd

# 组合内港股通标的(目前仅康方; 后续新增港股持仓加这里)
HK_HOLDINGS = {
    "09926": "康方生物",
}

LOOKBACKS = [("5日", 5), ("20日", 20), ("40日", 40), ("60日", 60)]

# 触发阈值(40日窗口为主判据)
PCT_MOVE_TRIG = 1.0   # 占比变化 >=1.0pp 视为显著
PRICE_MOVE_TRIG = 8.0 # 同期股价变化 >=8% 视为显著


def fetch(symbol):
    import os
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    import akshare as ak
    from marketdata import safe_call
    df = safe_call(lambda: ak.stock_hsgt_individual_em(symbol=symbol),
                   label=f"southbound:{symbol}")
    if df is None or df.empty:
        return None
    df["持股日期"] = pd.to_datetime(df["持股日期"])
    return df.sort_values("持股日期").reset_index(drop=True)


def classify(pct_move, price_move):
    """pct_move: 占比变化(pp, 正=增持); price_move: 同期股价变化(%)"""
    if abs(pct_move) < PCT_MOVE_TRIG and abs(price_move) < PRICE_MOVE_TRIG:
        return "⚪中性", "南向占比与股价均无显著变化"
    if pct_move > 0 and price_move < 0:
        return "🟢弱势吸筹", "南向逆势加仓(占比升+价跌)=内地资金便宜区吸筹"
    if pct_move > 0 and price_move >= 0:
        return "🟢顺势增持", "南向占比升+价涨=资金趋势确认"
    if pct_move < 0 and price_move > 0:
        return "🔴派发", "南向涨势中减仓(占比降+价升)=顶部出货预警"
    return "🟡资金流出", "南向占比降+价跌=左侧未见底/割肉"


def analyze(symbol, name):
    try:
        df = fetch(symbol)
    except Exception as e:
        return None, f"⚠️ {name}({symbol}) 拉取失败, 跳过不编造: {repr(e)[:80]}"
    if df is None or len(df) < 6:
        return None, f"⚠️ {name}({symbol}) 数据不足({0 if df is None else len(df)}行), 跳过"
    last = df.iloc[-1]
    lines = [f"=== {name}({symbol})  最新 {last['持股日期'].date()}  "
             f"南向占比 {last['持股数量占A股百分比']:.2f}%  持股 {last['持股数量']/1e8:.3f}亿股 ==="]
    primary = None  # 40日判据
    for lbl, n in LOOKBACKS:
        if len(df) <= n:
            continue
        r = df.iloc[-1 - n]
        sh0, shn = last["持股数量"], r["持股数量"]
        p0, pn = last["当日收盘价"], r["当日收盘价"]
        pct_move = last["持股数量占A股百分比"] - r["持股数量占A股百分比"]
        price_move = (p0 / pn - 1) * 100 if pn else 0.0
        lines.append(f"  {lbl}前({r['持股日期'].date()}): 持股变{(sh0/shn-1)*100:+.2f}% "
                     f"占比变{pct_move:+.2f}pp 股价变{price_move:+.1f}%")
        if n == 40:
            tag, why = classify(pct_move, price_move)
            primary = (tag, why, pct_move, price_move)
    if primary:
        tag, why, pm, prm = primary
        lines.append(f"  >>> [40日判据] {tag}: {why} (占比{pm:+.2f}pp / 价{prm:+.1f}%)")
        signal = not tag.startswith("⚪")
    else:
        signal = False
    return {"signal": signal, "tag": primary[0] if primary else "⚪中性"}, "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", help="单只港股代码(如 09926), 缺省扫全部组合港股")
    ap.add_argument("--quiet", action="store_true", help="无显著信号时静默(exit0空输出)")
    args = ap.parse_args()

    targets = {args.symbol: HK_HOLDINGS.get(args.symbol, args.symbol)} if args.symbol else HK_HOLDINGS
    any_signal = False
    out = []
    for sym, nm in targets.items():
        res, text = analyze(sym, nm)
        out.append(text)
        if res and res["signal"]:
            any_signal = True

    if args.quiet and not any_signal:
        return 0
    print("\n\n".join(out))
    print("\n[数据诚实] 南向占比/价全东财一手日频, 吸筹/派发是占比×价一阶启发式历史读数"
          "不预测股价, 拉不到的标的跳过不编造, 非买卖指令。")
    return 1 if any_signal else 0


if __name__ == "__main__":
    sys.exit(main())
