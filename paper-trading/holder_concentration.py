#!/usr/bin/env python3
"""
股东户数 / 筹码集中度扫描器 (holder_concentration.py) —— 纯只读，一手 akshare。

为什么有价值（一个全新的、独立于估值/财务/相关性的信号维度）:
  我们已有 valuation_percentile（估值锚）/ alpha_check（相对收益）/ thesis / catalyst /
  correlation。但从未量化过 A 股最经典的「筹码集中度」信号——股东户数。
  股东户数下降 = 筹码向更少的手集中（机构/大户吸筹）；上升 = 筹码分散（散户接盘）。

关键：信号是【方向依赖】的，必须结合同期价格涨跌幅一起读，绝不能单看户数：
  - 户数↓ + 价格平/跌（低位）   => 「吸筹」: 大户在弱势中集中筹码 (看多线索)
  - 户数↑ + 价格大涨（高位）   => 「派发」: 散户在强势中蜂拥接盘 (见顶警示)
  - 户数↓ + 价格大涨          => 「强势集中」: 越涨越集中, 通常是主升浪 (确认)
  - 户数↑ + 价格跌            => 「割肉离场/扩散」: 弱势中散户割肉或扩散 (中性偏弱)

数据诚实: 股东户数为交易所/公司披露的【季度/不定期】快照(东财 stock_zh_a_gdhs_detail_em),
  非实时, 有披露滞后(Q1 数据约 4 月底才出)。这是历史相对读数, 不预测未来, 仅作筹码体检,
  非买卖指令。拉不到的标的(部分 SH 代码端口异常/港股无此数据)明确跳过并告警, 绝不编造。

用法:
  python3 holder_concentration.py                 # 扫全部 A 股纸面持仓
  python3 holder_concentration.py --code 002415   # 单只
  python3 holder_concentration.py --quiet          # 仅在有显著信号时输出(可挂 watchdog)
"""
import sys, argparse, sqlite3, os

DB = os.path.join(os.path.dirname(__file__), "paper_trading.db")

# 显著阈值: 户数季环比变动绝对值 >= 10% 视为显著筹码迁移
SIG_PCT = 10.0


def get_a_share_holdings():
    """从纸面 DB 读真实 A 股持仓 (6 开头 SH / 0,3 开头 SZ)，港股(0 开头 5 位/HK)跳过。"""
    if not os.path.exists(DB):
        return []
    out = []
    try:
        con = sqlite3.connect(DB)
        cur = con.cursor()
        # positions 表: symbol, name (尽量宽松取列)
        cur.execute("SELECT DISTINCT symbol, name FROM positions WHERE quantity > 0")
        for sym, name in cur.fetchall():
            s = str(sym).strip()
            # A 股: 6 位纯数字
            if len(s) == 6 and s.isdigit():
                out.append((s, name or s))
        con.close()
    except Exception as e:
        print(f"[警告] 读 DB 持仓失败, 回退空: {e}", file=sys.stderr)
    return out


def classify(d_pct, price_chg):
    """根据户数环比变动 d_pct 与同期价格涨跌 price_chg 给出方向依赖的信号标签。"""
    concentrating = d_pct <= -SIG_PCT      # 户数显著下降=集中
    dispersing = d_pct >= SIG_PCT          # 户数显著上升=分散
    up = price_chg >= 8.0
    down = price_chg <= -8.0

    if concentrating and (down or abs(price_chg) < 8.0):
        return "🟢吸筹", "户数显著下降+价格弱/平 → 大户在弱势中集中筹码(看多线索)", True
    if concentrating and up:
        return "🟢强势集中", "户数下降+价格大涨 → 越涨越集中,主升浪特征(确认)", True
    if dispersing and up:
        return "🔴派发", "户数显著上升+价格大涨 → 散户在强势中接盘(见顶警示)", True
    if dispersing and down:
        return "🟡扩散割肉", "户数上升+价格下跌 → 弱势中散户割肉/筹码扩散(中性偏弱)", True
    if dispersing:
        return "🟡分散", "户数显著上升 → 筹码趋于分散(留意)", True
    if concentrating:
        return "🟢集中", "户数显著下降 → 筹码趋于集中", True
    return "中性", "户数变动不显著", False


def scan_one(code, name):
    try:
        import os
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _root not in sys.path:
            sys.path.insert(0, _root)
        import akshare as ak
        from marketdata import safe_call
    except Exception as e:
        print(f"[错误] 无 akshare: {e}", file=sys.stderr)
        return None
    try:
        df = safe_call(lambda: ak.stock_zh_a_gdhs_detail_em(symbol=code),
                       label=f"gdhs:{code}")
    except Exception as e:
        print(f"[跳过] {name}({code}) 拉股东户数失败(端口异常,绝不编造): {repr(e)[:80]}", file=sys.stderr)
        return None
    if df is None or len(df) == 0:
        print(f"[跳过] {name}({code}) 无股东户数数据", file=sys.stderr)
        return None
    try:
        last = df.iloc[-1]
        date = last["股东户数统计截止日"]
        d_pct = float(last["股东户数-增减比例"])
        price_chg = float(last["区间涨跌幅"])
        cnt = int(last["股东户数-本次"])
    except Exception as e:
        print(f"[跳过] {name}({code}) 字段解析失败: {repr(e)[:80]}", file=sys.stderr)
        return None
    tag, why, sig = classify(d_pct, price_chg)
    # 取最近 4 期趋势串
    trend = []
    for _, r in df.tail(4).iterrows():
        try:
            trend.append(f"{str(r['股东户数统计截止日'])[:10]} 户数{float(r['股东户数-增减比例']):+.1f}% 价{float(r['区间涨跌幅']):+.1f}%")
        except Exception:
            pass
    return {
        "code": code, "name": name, "date": str(date)[:10],
        "d_pct": d_pct, "price_chg": price_chg, "count": cnt,
        "tag": tag, "why": why, "significant": sig, "trend": trend,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", help="单只 A 股代码, 如 002415")
    ap.add_argument("--quiet", action="store_true", help="仅在有显著信号时输出")
    args = ap.parse_args()

    if args.code:
        targets = [(args.code, args.code)]
    else:
        targets = get_a_share_holdings()
        if not targets:
            print("[信息] 无 A 股纸面持仓可扫(港股无此数据)", file=sys.stderr)
            return 0

    results = []
    for code, name in targets:
        r = scan_one(code, name)
        if r:
            results.append(r)

    sig_results = [r for r in results if r["significant"]]

    if args.quiet and not sig_results:
        return 0  # 静默: 无显著筹码迁移

    out = sig_results if args.quiet else results
    if not out:
        return 0

    print("=" * 64)
    print("股东户数 / 筹码集中度体检 (一手东财, 季度快照, 非实时, 非买卖指令)")
    print("=" * 64)
    for r in out:
        print(f"\n【{r['tag']}】{r['name']}({r['code']})  截止 {r['date']}")
        print(f"  最新户数 {r['count']:,}  环比 {r['d_pct']:+.1f}%  同期价 {r['price_chg']:+.1f}%")
        print(f"  解读: {r['why']}")
        if r["trend"]:
            print(f"  近4期: " + " | ".join(r["trend"]))
    print()
    return 1 if sig_results else 0


if __name__ == "__main__":
    sys.exit(main())
