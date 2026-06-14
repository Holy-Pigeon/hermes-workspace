#!/usr/bin/env python3
"""
us_tech_scout.py — 美股科技「耐久质量」发现扫描器 (watchdog 型, 纯只读一手 API)

存在理由 (元层缺口, 非缺某只票):
  组合 90M 资金分 5 个 sleeve, 其中 us-tech-value(25M) sleeve 至今 100% 未部署,
  且**全部分析工具(tech_screener/moat/reverse_dcf/valuation_percentile/holder/southbound)
  只覆盖 A股+港股**——美股 sleeve 在分析上完全是暗区。可我们的投资哲学(段永平好生意优先 /
  Nick Sleep 规模经济返还 / 平台可选权)最天然的栖息地恰恰是美股科技龙头。
  这是「缺一类能力」而非「缺一只票」: 给最该用价投框架的 sleeve 装上发现雷达。

它做什么 (与 A股 tech_screener 同口径但用美股一手财报):
  对一个美股科技白名单, 拉 26 年年报序列, 用 Buffett 硬标准筛「耐久质量」:
    ① ROE 持久性: 近 8 年 ROE≥15% 的年占比 (定价权+复利能力)
    ② 净利率水平与稳定性: 均值 + CV(std/mean) (定价权稳不稳)
    ③ 毛利率: 宽护城河通常毛利≥40%
    ④ 营收/净利近一年 YoY: 还在不在成长
  判定:
    🏰 宽护城河候选 = ROE持久≥80% + 净利率均值≥15% + 毛利≥40% + CV≤0.35
    ⭐ 优质成长候选 = 上面差一档但近一年净利 YoY>15%
    🔍 关注 = 质量达标但成长停滞 (价值陷阱风险, 须人工判)
    ·  不达标
  **这是候选漏斗起点, 非买卖指令**; 不取价格/不算估值(估值留给后续 reverse_dcf 阶段),
  本工具只回答「这是不是一门耐久的好生意」, 不回答「现在贵不贵」。

数据诚实: 全 akshare stock_financial_us_analysis_indicator_em 一手年报; 某只拉不到则
  显式跳过并告警, 绝不填充; ROE_AVG 对回购大户(如 AAPL 因负权益)会畸高, 工具对
  ROE>100% 标注「疑回购致权益缩水, ROE 失真, 以净利率/毛利为准」防误读。

退出码: 0 = 无 🏰/⭐ 新候选 (--quiet 静默, cron 友好) / 1 = 有候选。
"""
import argparse
import json
import os
import statistics
import sys
import warnings
from datetime import datetime, timezone, timedelta
# 收口: 护城河判定走 moat-durability/moat_core 单一事实源 (防与 moat_scorecard 漂移)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "moat-durability"))
from moat_core import classify_moat, compute_metrics

warnings.filterwarnings("ignore")
CN_TZ = timezone(timedelta(hours=8))

# 美股科技白名单 (价投框架天然栖息地: 平台/生态/规模经济返还型)
# 可在 watchlist.json 覆盖; 此处为默认种子。
DEFAULT_WATCHLIST = [
    ("AAPL", "苹果"), ("MSFT", "微软"), ("GOOGL", "谷歌"),
    ("META", "Meta"), ("NVDA", "英伟达"), ("AMZN", "亚马逊"),
    ("V", "Visa"), ("MA", "万事达"), ("ADBE", "Adobe"),
    ("ASML", "ASML"), ("TSM", "台积电"), ("COST", "好市多"),
]


def load_watchlist():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.json")
    if os.path.exists(p):
        try:
            with open(p) as f:
                data = json.load(f)
            return [(d["symbol"], d.get("name", d["symbol"])) for d in data]
        except Exception:
            pass
    return DEFAULT_WATCHLIST


def fetch_annual(symbol):
    """拉 26 年年报指标。返回按年降序的 list[dict] 或 None(拉不到)。"""
    import akshare as ak
    try:
        df = ak.stock_financial_us_analysis_indicator_em(symbol=symbol, indicator="年报")
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:80]}"
    if df is None or df.empty:
        return None, "空数据"
    rows = []
    for _, r in df.iterrows():
        def g(k):
            try:
                v = r.get(k)
                return float(v) if v is not None and v == v else None
            except Exception:
                return None
        rows.append({
            "date": str(r.get("REPORT_DATE", ""))[:10],
            "rev": g("OPERATE_INCOME"),
            "rev_yoy": g("OPERATE_INCOME_YOY"),
            "np": g("PARENT_HOLDER_NETPROFIT"),
            "np_yoy": g("PARENT_HOLDER_NETPROFIT_YOY"),
            "roe": g("ROE_AVG"),
            "gpm": g("GROSS_PROFIT_RATIO"),
            "npm": g("NET_PROFIT_RATIO"),
            "eps": g("BASIC_EPS"),
        })
    return rows, None


def analyze(symbol, name):
    rows, err = fetch_annual(symbol)
    if rows is None:
        return {"symbol": symbol, "name": name, "ok": False, "err": err}
    recent = rows[:8]  # 近 8 年 (降序)
    # 收口: 用 moat_core 单一事实源算耐久度 (含定价权护栏+侵蚀红旗+低谷穿越升级),
    # 须按时间【升序】对齐 ROE/净利率序列喂给 compute_metrics.
    asc = list(reversed(recent))  # 升序
    roe_asc = [r["roe"] for r in asc if r["roe"] is not None and r["npm"] is not None]
    npm_asc = [r["npm"] for r in asc if r["roe"] is not None and r["npm"] is not None]
    gpms = [r["gpm"] for r in recent if r["gpm"] is not None]
    if not roe_asc or not npm_asc:
        return {"symbol": symbol, "name": name, "ok": False, "err": "ROE/净利率序列为空"}

    m = compute_metrics(roe_asc, npm_asc, recent_window=5)
    gpm_mean = statistics.mean(gpms) if gpms else None
    # 护城河耐久度判定 (单一事实源, 与 moat_scorecard 完全同源, 防漂移)
    moat_verdict, moat_rank, moat_flags = classify_moat(m, gross_margin=gpm_mean)

    roe_persist = m["roe_persistence"]
    roe_median = m["roe_median"]
    npm_mean = m["npm_mean"]
    npm_cv = m["npm_cv"]
    latest = rows[0]
    np_yoy = latest.get("np_yoy")
    rev_yoy = latest.get("rev_yoy")

    # ROE 失真护栏: 回购大户负权益致 ROE 畸高(AAPL ROE_AVG ~170%)
    roe_distorted = roe_median is not None and roe_median > 100

    # 发现漏斗判定: 在耐久度核心(moat_rank)之上叠加成长维度.
    # 关键改进: 护城河被侵蚀(moat_rank==3)或定价权不足(护栏降级)的名字, 不再可能拿🏰.
    growing = (np_yoy is not None and np_yoy > 15) or (rev_yoy is not None and rev_yoy > 15)
    eroding = moat_rank == 3  # 净利率收缩或ROE持久性不足, 护城河存疑

    if eroding:
        flag, verdict = "·", "护城河存疑(净利率收缩/ROE不持久), 不入候选"
    elif moat_rank == 0 and growing:
        flag, verdict = "🏰", "宽护城河候选: 高持久ROE+厚稳净利率+在成长"
    elif moat_rank == 0:
        flag, verdict = "🔍", "宽护城河但成长停滞(YoY≤15%), 价值陷阱风险须人工判"
    elif (roe_persist >= 0.60 and npm_mean is not None and npm_mean >= 10) and growing:
        flag, verdict = "⭐", "优质成长候选(质量近门槛+在成长, 须补估值+护城河尽调)"
    else:
        flag, verdict = "·", "未达耐久质量门槛"

    notes = list(moat_flags)  # 把 moat_core 的护栏/侵蚀/升级说明带出来, 透明化
    if roe_distorted:
        notes.append("ROE>100%疑回购致权益缩水失真, 以净利率/毛利为准")

    return {
        "symbol": symbol, "name": name, "ok": True, "flag": flag, "verdict": verdict,
        "moat_verdict": moat_verdict,
        "roe_persist": round(roe_persist, 2), "roe_median": round(roe_median, 1) if roe_median is not None else None,
        "npm_mean": round(npm_mean, 1) if npm_mean is not None else None,
        "npm_cv": round(npm_cv, 3) if npm_cv is not None else None,
        "gpm_mean": round(gpm_mean, 1) if gpm_mean is not None else None,
        "np_yoy": round(np_yoy, 1) if np_yoy is not None else None,
        "rev_yoy": round(rev_yoy, 1) if rev_yoy is not None else None,
        "latest_date": latest.get("date"), "n_years": len(roe_asc), "notes": notes,
    }


def main():
    ap = argparse.ArgumentParser(description="美股科技耐久质量发现扫描器 (watchdog型)")
    ap.add_argument("--symbol", help="只跑单只(调试)")
    ap.add_argument("--quiet", action="store_true", help="无🏰/⭐候选时静默 exit0 (cron友好)")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    wl = [(args.symbol, args.symbol)] if args.symbol else load_watchlist()
    results, skipped = [], []
    for sym, name in wl:
        r = analyze(sym, name)
        if r["ok"]:
            results.append(r)
        else:
            skipped.append(r)

    order = {"🏰": 0, "⭐": 1, "🔍": 2, "·": 3}
    results.sort(key=lambda r: (order.get(r["flag"], 9), -(r["roe_median"] or 0)))
    candidates = [r for r in results if r["flag"] in ("🏰", "⭐")]

    if args.json:
        print(json.dumps({"results": results, "skipped": skipped}, ensure_ascii=False, indent=2))
        sys.exit(1 if candidates else 0)

    if args.quiet and not candidates:
        sys.exit(0)

    now = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M")
    print(f"美股科技耐久质量扫描  {now} CST  | 白名单{len(wl)} 成功{len(results)} 跳过{len(skipped)} | 🏰/⭐候选{len(candidates)}")
    print("-" * 76)
    show = candidates if args.quiet else results
    for r in show:
        print(f"\n{r['flag']} {r['name']}({r['symbol']})  [{r['latest_date']} 年报, 近{r['n_years']}年]")
        print(f"   ROE持久性(≥15%占比) {r['roe_persist']} | ROE中位 {r['roe_median']}% | "
              f"净利率均值 {r['npm_mean']}% (CV {r['npm_cv']}) | 毛利率 {r['gpm_mean']}%")
        print(f"   近一年: 净利YoY {r['np_yoy']}% | 营收YoY {r['rev_yoy']}%")
        print(f"   判定: {r['verdict']}")
        for n in r["notes"]:
            print(f"   ⚠️ {n}")
        if r["flag"] in ("🏰", "⭐"):
            print(f"   ↳尽调: 须补 reverse_dcf(现价price-in多高增速) + 现金流质量 + 可选权; 候选≠买入")
    if skipped:
        print("\n[跳过/拉取失败 — 诚实标注不填充]")
        for s in skipped:
            print(f"   · {s['name']}({s['symbol']}): {s['err']}")
    print("\n本工具是【美股候选漏斗】非买卖指令; 只判生意质量不判估值, 估值留给 reverse_dcf 阶段。")
    sys.exit(1 if candidates else 0)


if __name__ == "__main__":
    main()
