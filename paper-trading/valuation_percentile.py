#!/usr/bin/env python3
"""
valuation_percentile.py  — 估值历史分位扫描器 (纯只读)

补上整个模拟持仓系统从未回答过的核心价投问题:
  "每只持仓相对它【自己的历史】, 现在是贵还是便宜?"

我们已有 correlation / alpha / thesis / catalyst, 但从无估值锚 —— 锚定效应下,
很容易把买入成本或近期股价当参照。本工具用个股【自身历史估值分位】做独立坐标:
当前 PE-TTM / PB / PS 处在过去 N 年的第几分位 (0%=史上最便宜, 100%=史上最贵)。

数据源 (全部一手行情, 拉不到就跳过并告警, 绝不编造):
  - A股: akshare stock_value_em (东财个股估值, ~8年日频 PE-TTM/PB/PS)
  - 港股: akshare stock_hk_indicator_eniu (亿牛, PE/PB 周频)

诚实声明:
  - 分位是【历史相对】读数, 不预测未来, 不等于"该买/该卖"。低分位也可能是价值陷阱
    (基本面恶化导致估值下台阶), 高分位也可能是成长重定价。须配合 thesis/catalyst 用。
  - 亏损股 (PE<0, 如 pre-profit biotech 康方) PE 无意义, 自动改用 PB/PS。
  - 港股 eniu 为周频且历史较短(自上市), 样本不足时标注不稳健。
"""
import argparse
import sqlite3
import sys
import os
import datetime as dt

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_trading.db")

# 分位告警阈值
LOW_PCTL = 20.0    # <=20% 史上偏便宜区
HIGH_PCTL = 80.0   # >=80% 史上偏贵区
MIN_SAMPLES = 60   # 少于此样本数标注不稳健


def pct_rank(series, value):
    """value 在 series 中的百分位 (0-100)。series 为 list[float]。"""
    vals = [v for v in series if v is not None]
    if not vals:
        return None
    below = sum(1 for v in vals if v < value)
    equal = sum(1 for v in vals if v == value)
    # 中点法
    return 100.0 * (below + 0.5 * equal) / len(vals)


def load_positions():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT symbol,name,market,avg_cost,last_price FROM positions WHERE quantity>0"
    ).fetchall()
    con.close()
    return rows


def fetch_a_share(symbol):
    """返回 dict: {'PE':[(date,val)...],'PB':..,'PS':..} 日频升序。"""
    import os
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    import akshare as ak
    from marketdata import safe_call
    df = safe_call(lambda: ak.stock_value_em(symbol=symbol),
                   label=f"value_em:{symbol}")
    if df is None or df.empty:
        return None
    out = {}
    colmap = {"PE": "PE(TTM)", "PB": "市净率", "PS": "市销率"}
    dates = df["数据日期"].astype(str).tolist()
    for k, col in colmap.items():
        if col in df.columns:
            out[k] = [(d, float(v)) for d, v in zip(dates, df[col].tolist()) if v == v]
    return out


def fetch_hk(symbol):
    """symbol 形如 '09926' -> eniu 'hk09926'。返回 {'PE':..,'PB':..}。"""
    import akshare as ak
    eniu = "hk" + symbol.lstrip("0").zfill(5) if not symbol.startswith("hk") else symbol
    eniu = "hk" + symbol  # eniu 用 5位带前导0, 如 hk09926
    out = {}
    for k, ind, col in [("PE", "市盈率", "pe"), ("PB", "市净率", "pb")]:
        try:
            d = ak.stock_hk_indicator_eniu(symbol=eniu, indicator=ind)
            if d is not None and not d.empty and col in d.columns:
                out[k] = [(str(dd), float(vv)) for dd, vv in zip(d["date"].tolist(), d[col].tolist()) if vv == vv]
        except Exception:
            pass
    return out


def trailing(series, years):
    """取最近 years 年的子序列 (series 为 [(date,val)] 升序)。"""
    if not series:
        return []
    cutoff = (dt.date.today() - dt.timedelta(days=int(365.25 * years))).isoformat()
    return [(d, v) for d, v in series if d >= cutoff]


def analyze_metric(series_full, label):
    """对一个指标(PE/PB/PS)算 当前值 + 全历史分位 + 近3年分位。"""
    if not series_full or len(series_full) < 5:
        return None
    cur_date, cur_val = series_full[-1]
    res = {"label": label, "cur": cur_val, "cur_date": cur_date, "n_full": len(series_full)}
    # 亏损 PE 处理
    if label == "PE" and cur_val <= 0:
        res["meaningless"] = True
        return res
    full_vals = [v for _, v in series_full if (label != "PE" or v > 0)]
    res["pctl_full"] = pct_rank(full_vals, cur_val)
    res["min_full"] = min(full_vals) if full_vals else None
    res["max_full"] = max(full_vals) if full_vals else None
    t3 = trailing(series_full, 3)
    t3_vals = [v for _, v in t3 if (label != "PE" or v > 0)]
    res["n_3y"] = len(t3_vals)
    res["pctl_3y"] = pct_rank(t3_vals, cur_val) if len(t3_vals) >= 5 else None
    res["unstable"] = len(full_vals) < MIN_SAMPLES
    return res


def fmt_pctl(p):
    if p is None:
        return "  n/a"
    return f"{p:5.1f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true",
                    help="仅当有低/高分位告警时输出, 否则静默(供cron)")
    args = ap.parse_args()

    positions = load_positions()
    if not positions:
        if not args.quiet:
            print("无持仓")
        return

    lines = []
    alerts = []
    lines.append("=" * 72)
    lines.append(f"估值历史分位扫描  (生成于 {dt.datetime.now():%Y-%m-%d %H:%M})")
    lines.append("分位 = 当前估值在【该股自身历史】中的位置  0%=史上最便宜 100%=史上最贵")
    lines.append("=" * 72)

    for p in positions:
        sym, name, market = p["symbol"], p["name"], p["market"]
        is_hk = "HK" in (market or "").upper() or "港" in (market or "")
        lines.append("")
        lines.append(f"【{name} {sym}】 {market}  成本 {p['avg_cost']} / 现价 {p['last_price']}")
        try:
            data = fetch_hk(sym) if is_hk else fetch_a_share(sym)
        except Exception as e:
            lines.append(f"  ⚠ 估值数据拉取失败, 跳过: {repr(e)[:90]}")
            alerts.append(f"{name}: 数据拉取失败")
            continue
        if not data:
            lines.append("  ⚠ 无估值历史数据, 跳过")
            continue
        for metric in ["PE", "PB", "PS"]:
            if metric not in data:
                continue
            r = analyze_metric(data[metric], metric)
            if r is None:
                continue
            if r.get("meaningless"):
                lines.append(f"  {metric:3s}: 当前 {r['cur']:.1f} (亏损/负值, PE无意义→看PB/PS)")
                continue
            rng = ""
            if r.get("min_full") is not None:
                rng = f"  [史区间 {r['min_full']:.1f}~{r['max_full']:.1f}]"
            flag = ""
            pf = r.get("pctl_full")
            if pf is not None:
                if pf <= LOW_PCTL:
                    flag = "  ◀ 史上偏低区"
                    alerts.append(f"{name} {metric} 处史上 {pf:.0f}% 分位(偏低)")
                elif pf >= HIGH_PCTL:
                    flag = "  ▶ 史上偏高区"
                    alerts.append(f"{name} {metric} 处史上 {pf:.0f}% 分位(偏高)")
            unst = "  (样本<60,不稳健)" if r.get("unstable") else ""
            lines.append(
                f"  {metric:3s}: 当前 {r['cur']:7.2f}  全史分位 {fmt_pctl(pf)}  "
                f"近3y分位 {fmt_pctl(r.get('pctl_3y'))}{rng}{flag}{unst}"
            )

    lines.append("")
    lines.append("-" * 72)
    if alerts:
        lines.append(f"⚑ 分位告警 ({len(alerts)}):")
        for a in alerts:
            lines.append(f"   • {a}")
    else:
        lines.append("✓ 无持仓处于史上极端分位区 (全部在 20%~80% 常态区间)")
    lines.append("提示: 低分位≠该买(警惕价值陷阱), 高分位≠该卖(可能成长重定价); 配合 thesis/catalyst 用。")
    lines.append("数据: A股=东财个股估值 港股=亿牛, 均一手行情; 历史相对读数, 不预测未来。")

    out = "\n".join(lines)
    if args.quiet and not alerts:
        return  # 静默
    print(out)


if __name__ == "__main__":
    main()
