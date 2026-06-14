#!/usr/bin/env python3
"""
moat_scorecard.py — 护城河耐久度计分卡 (纯只读, 一手 akshare)

为什么存在:
  整个系统已有 价格/财报/估值分位/相关性/筹码/资金流/反向DCF 等 ~8 个维度,
  但每篇研究 note 都把"护城河尽调"当作【待验证下一步】无限延期, 从无任何工具
  把"护城河有多强、多耐久"翻译成可证伪的数字。本工具填这个洞。

护城河 ≠ 故事。Buffett 的硬标准: 长期可持续的高 ROE + 稳定的 margin(=定价权).
  本工具用 8 年年报序列, 把定性的"护城河强"翻译成 4 个可量化的耐久度支柱:
    ① ROE 持久性: 过去 N 年 ROE≥15% 的年数占比 (Buffett 门槛)
    ② ROE 水平:   近 N 年 ROE 中位数 (越高资本回报越强)
    ③ 利润率稳定: 销售净利率的变异系数 CV=std/mean (越低=定价权越稳, 不被成本/竞争侵蚀)
    ④ 利润率趋势: 近半段 vs 远半段净利率均值之差 (扩张=护城河加宽 / 收缩=被侵蚀)
  辅助读数: 毛利率水平(financial_abstract), 存货周转趋势(运营效率).

判定 (纯启发式, 非买卖指令):
  🏰 宽护城河:  ROE≥15%年占比≥70% 且 净利率CV≤0.20 (高且稳)
  🧱 窄护城河:  ROE≥15%年占比≥40% 或 净利率CV≤0.30
  ⚠️ 护城河存疑: 利润率显著收缩(趋势<-3pp) 或 ROE持久性<40%
  —  数据不足: 年报<4

数据诚实:
  - ROE/净利率/周转全取 stock_financial_analysis_indicator 年报(12-31)行, 一手.
  - 毛利率该端口常为 NaN, 回退 financial_abstract; 取不到则标 n/a 绝不编造.
  - CV/趋势是历史会计读数, 不预测未来; 护城河会被颠覆, 高分≠该买.
  - 拉不到的标的明确跳过+告警.
"""
import sys, argparse, json
import statistics as st
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from moat_core import classify_moat

try:
    import akshare as ak
except Exception as e:
    print(f"[FATAL] akshare import 失败: {e}", file=sys.stderr); sys.exit(2)

# 组合持仓 + 发现管线真候选 (A股, 港股无此端口)
DEFAULT_UNIVERSE = {
    "002415": "海康威视",
    "601138": "工业富联",
    "600415": "小商品城",
    "601899": "紫金矿业",
    "300750": "宁德时代",
    "300760": "迈瑞医疗",
}

def f(x):
    try:
        v = float(x)
        if v != v:  # NaN
            return None
        return v
    except Exception:
        return None

def fetch_gross_margin_annual(code):
    """毛利率年报序列, 从 financial_abstract 兜底 (analysis_indicator 常 NaN)."""
    try:
        df = ak.stock_financial_abstract(symbol=code)
    except Exception:
        return {}
    # financial_abstract: 行=指标, 列=报告期(YYYYMMDD)
    gm_rows = df[df['指标'].astype(str) == '毛利率']
    if gm_rows.empty:
        return {}
    row = gm_rows.iloc[0]
    out = {}
    for col in df.columns:
        c = str(col)
        if c.endswith('1231') and len(c) == 8:
            v = f(row[col])
            if v is not None:
                out[c[:4]] = v
    return out

def analyze(code, name):
    try:
        df = ak.stock_financial_analysis_indicator(symbol=code, start_year='2017')
    except Exception as e:
        return {"code": code, "name": name, "error": str(e)[:80]}
    ann = df[df['日期'].astype(str).str.endswith('12-31')].copy()
    if ann.empty:
        return {"code": code, "name": name, "error": "无年报数据"}
    ann = ann.sort_values('日期')
    years = [str(d)[:4] for d in ann['日期'].tolist()]
    roe = [f(x) for x in ann['净资产收益率(%)'].tolist()]
    npm = [f(x) for x in ann['销售净利率(%)'].tolist()]
    turn = [f(x) for x in ann['存货周转率(次)'].tolist()]
    # 对齐: 仅保留 ROE 与净利率均非空年
    rows = [(y, r, n, t) for y, r, n, t in zip(years, roe, npm, turn) if r is not None and n is not None]
    if len(rows) < 4:
        return {"code": code, "name": name, "error": f"有效年报仅{len(rows)}年<4, 不足以评估耐久度"}
    years = [x[0] for x in rows]
    roe = [x[1] for x in rows]
    npm = [x[2] for x in rows]
    n = len(rows)

    # ① ROE 持久性
    roe_pers = sum(1 for r in roe if r >= 15) / n
    # ② ROE 水平 (中位)
    roe_med = st.median(roe)
    # ③ 净利率稳定 CV
    npm_mean = st.mean(npm)
    npm_cv = (st.pstdev(npm) / abs(npm_mean)) if npm_mean else None
    # ④ 净利率趋势 (近半 vs 远半均值差)
    h = n // 2
    far = st.mean(npm[:h])
    near = st.mean(npm[n - h:])
    npm_trend = near - far

    # ④b 近5年窗口 (隔离上市初虚高基期污染 + 全行业结构性低谷, 修复"低谷穿越型"假阴性).
    #     全样本 CV/趋势对"上市初margin虚高→行业低谷→再上台阶"型公司有系统性偏差:
    #     远半含上市初虚高margin当基准, 会把真实的 margin 扩张误读成"趋势平/被侵蚀";
    #     全行业补贴退坡的结构性低谷年, 会被算成该公司单独失去定价权(ROE持久性被压低).
    #     近5年窗口只看现行规模化/制度下的护城河本体, 与全样本互为交叉验证.
    def _slope(ys_vals):
        m = len(ys_vals)
        xs = list(range(m))
        xbar = st.mean(xs); ybar = st.mean(ys_vals)
        den = sum((x - xbar) ** 2 for x in xs)
        if den == 0:
            return 0.0
        return sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys_vals)) / den
    RW = 5
    if n >= RW:
        roe_recent = roe[-RW:]
        npm_recent = npm[-RW:]
        roe_pers_recent = sum(1 for r in roe_recent if r >= 15) / RW
        roe_med_recent = st.median(roe_recent)
        npm_slope_recent = _slope(npm_recent)  # pp/年, 正=margin逐年扩张
    else:
        roe_pers_recent = roe_med_recent = npm_slope_recent = None
    # 周转趋势 (运营效率, 辅助)
    turn_vals = [t for t in turn if t is not None]
    turn_trend = None
    if len(turn_vals) >= 4:
        th = len(turn_vals) // 2
        turn_trend = st.mean(turn_vals[len(turn_vals) - th:]) - st.mean(turn_vals[:th])

    gm = fetch_gross_margin_annual(code)
    gm_recent = None
    if gm:
        ys = sorted(gm.keys())
        gm_recent = gm[ys[-1]]

    # 判定: 收口到 moat_core 单一事实源 (护栏/门槛/低谷穿越升级全在那里, 防与 us_tech_scout 漂移)
    verdict, rank, flags = classify_moat({
        "roe_persistence": roe_pers,
        "roe_median": roe_med,
        "npm_mean": npm_mean,
        "npm_cv": npm_cv,
        "npm_trend": npm_trend,
        "roe_persistence_recent": roe_pers_recent,
        "npm_slope_recent": npm_slope_recent,
    })

    return {
        "code": code, "name": name, "verdict": verdict, "rank": rank,
        "n_years": n, "year_span": f"{years[0]}-{years[-1]}",
        "roe_persistence": round(roe_pers, 2),
        "roe_median": round(roe_med, 1),
        "roe_latest": round(roe[-1], 1),
        "npm_mean": round(npm_mean, 1),
        "npm_cv": round(npm_cv, 3) if npm_cv is not None else None,
        "npm_trend_pp": round(npm_trend, 1),
        "roe_persistence_recent5": round(roe_pers_recent, 2) if roe_pers_recent is not None else None,
        "roe_median_recent5": round(roe_med_recent, 1) if roe_med_recent is not None else None,
        "npm_slope_recent5_pp_yr": round(npm_slope_recent, 2) if npm_slope_recent is not None else None,
        "turn_trend": round(turn_trend, 2) if turn_trend is not None else None,
        "gm_recent": round(gm_recent, 1) if gm_recent is not None else None,
        "flags": flags,
        "roe_series": list(zip(years, [round(r, 1) for r in roe])),
        "npm_series": list(zip(years, [round(p, 1) for p in npm])),
    }

def fmt(r):
    if "error" in r:
        return f"  [SKIP] {r['name']}({r['code']}): {r['error']}"
    lines = []
    lines.append(f"  {r['verdict']}  {r['name']}({r['code']})  [{r['year_span']}, {r['n_years']}年]")
    lines.append(f"      ROE: 中位{r['roe_median']}% / 最新{r['roe_latest']}% / ≥15%持久性{r['roe_persistence']*100:.0f}%")
    cv = r['npm_cv']
    cvtxt = f"CV{cv}" if cv is not None else "CV n/a"
    lines.append(f"      净利率: 均值{r['npm_mean']}% / 稳定性{cvtxt} / 趋势{r['npm_trend_pp']:+.1f}pp(近半-远半)")
    if r.get('roe_persistence_recent5') is not None:
        lines.append(
            f"      近5年: ROE中位{r['roe_median_recent5']}% / ≥15%持久{r['roe_persistence_recent5']*100:.0f}%"
            f" / 净利率斜率{r['npm_slope_recent5_pp_yr']:+.2f}pp/年"
        )
    extra = []
    if r['gm_recent'] is not None:
        extra.append(f"毛利率{r['gm_recent']}%")
    if r['turn_trend'] is not None:
        extra.append(f"存货周转趋势{r['turn_trend']:+.2f}")
    if extra:
        lines.append("      " + " / ".join(extra))
    if r['flags']:
        for fl in r['flags']:
            lines.append(f"      🚩 {fl}")
    return "\n".join(lines)

def main():
    ap = argparse.ArgumentParser(description="护城河耐久度计分卡 (纯只读)")
    ap.add_argument("code", nargs="?", help="单只股票代码 (默认全 universe)")
    ap.add_argument("--name", default="", help="单只时的名称")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    ap.add_argument("--quiet", action="store_true", help="仅在出现护城河存疑红旗时输出 (cron 友好)")
    args = ap.parse_args()

    if args.code:
        universe = {args.code: args.name or args.code}
    else:
        universe = DEFAULT_UNIVERSE

    results = [analyze(c, n) for c, n in universe.items()]
    results.sort(key=lambda r: r.get("rank", 9))

    flagged = [r for r in results if r.get("rank") == 3]

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        sys.exit(1 if flagged else 0)

    if args.quiet:
        if not flagged:
            sys.exit(0)
        print("=== 护城河耐久度: 存疑红旗 ===")
        for r in flagged:
            print(fmt(r))
        sys.exit(1)

    print("=== 护城河耐久度计分卡 (8年年报, 一手akshare) ===")
    print("    Buffett门槛: 长期高ROE+稳定margin=定价权耐久. 非买卖指令.")
    for r in results:
        print(fmt(r))
    print("\n  注: 护城河会被技术/竞争颠覆, 高分≠该买; 低CV是历史稳定不保证未来; 港股无此端口.")
    sys.exit(1 if flagged else 0)

if __name__ == "__main__":
    main()
