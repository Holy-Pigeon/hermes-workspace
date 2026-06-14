#!/usr/bin/env python3
"""
moat_core.py — 护城河耐久度判定的【单一事实源】(pure function, 零网络/零依赖)

为什么存在 (元层收口):
  护城河"耐久质量"分类逻辑此前在两处各写一份:
    ① moat-durability/moat_scorecard.py  (A股持仓/候选, akshare A股年报口径)
    ② us-tech-scout/us_tech_scout.py      (美股科技发现, akshare 美股年报口径)
  两份是同一套 Buffett 方法论(ROE持久性 + 净利率水平/稳定CV + 毛利 + 趋势)的
  **分叉副本**。最危险的后果: moat_scorecard 在 2026-06-13 加的两道硬护栏——
    · 定价权护栏(净利率<8%的高ROE是杠杆/周转非定价权 → 🏰降🧱, 防薄利代工假宽护城河)
    · 低谷穿越升级(穿越结构性行业低谷型的全样本假阴性修复, 防CATL式真护城河被误判窄)
  在 us_tech_scout 里**完全缺失**, 且 scout 连"利润率侵蚀红旗"都没有。
  → 一个美股半导体/硬件名穿越周期低谷, 或护城河正被侵蚀, 在 scout 里会被错判。
  同一套方法论两处实现 = 必然漂移: 任何一处修了护栏, 另一处不会同步。

  本模块把判定逻辑收敛成**一个纯函数 classify_moat(指标字典)**, 两个工具都 import 它。
  数据取数仍各自负责(A股 vs 美股端口不同), 但"给定指标 → 护城河结论"只有一份代码。

判定门槛与护栏全部继承自 moat_scorecard 2026-06-13 定版, 不改变任何已验证行为。
"""
import statistics as st


def lstsq_slope(ys):
    """最小二乘线性斜率 (pp/年). ys 为按时间升序的净利率序列."""
    m = len(ys)
    if m < 2:
        return 0.0
    xs = list(range(m))
    xbar = st.mean(xs)
    ybar = st.mean(ys)
    den = sum((x - xbar) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys)) / den


def compute_metrics(roe_series, npm_series, recent_window=5):
    """
    从按时间升序的 ROE / 净利率年报序列计算护城河指标.
    roe_series / npm_series: list[float], 已对齐(同年份, 已去 None), 升序.
    返回 dict, 供 classify_moat 消费. 不取数, 纯计算.
    """
    n = len(npm_series)
    roe_pers = sum(1 for r in roe_series if r >= 15) / len(roe_series) if roe_series else 0.0
    roe_med = st.median(roe_series) if roe_series else None
    npm_mean = st.mean(npm_series) if npm_series else None
    npm_cv = (st.pstdev(npm_series) / abs(npm_mean)) if (npm_mean) else None
    # 趋势: 近半 vs 远半
    npm_trend = None
    if n >= 2:
        h = n // 2
        far = st.mean(npm_series[:h]) if h else npm_series[0]
        near = st.mean(npm_series[n - h:]) if h else npm_series[-1]
        npm_trend = near - far
    # 近5年窗口 (隔离上市初虚高基期 + 结构性低谷)
    rw = recent_window
    if n >= rw:
        roe_recent = roe_series[-rw:]
        npm_recent = npm_series[-rw:]
        roe_pers_recent = sum(1 for r in roe_recent if r >= 15) / rw
        roe_med_recent = st.median(roe_recent)
        npm_slope_recent = lstsq_slope(npm_recent)
    else:
        roe_pers_recent = roe_med_recent = npm_slope_recent = None
    return {
        "n_years": n,
        "roe_persistence": roe_pers,
        "roe_median": roe_med,
        "npm_mean": npm_mean,
        "npm_cv": npm_cv,
        "npm_trend": npm_trend,
        "roe_persistence_recent": roe_pers_recent,
        "roe_median_recent": roe_med_recent,
        "npm_slope_recent": npm_slope_recent,
    }


def classify_moat(m, gross_margin=None):
    """
    单一事实源: 给定护城河指标字典 → (verdict, rank, flags).
    rank: 0=🏰宽 1=🧱窄 2=·普通 3=⚠️存疑
    护栏与门槛继承 moat_scorecard 2026-06-13 定版:
      ① 基础门槛(高且稳→🏰 / 较高或较稳→🧱 / 否则·普通)
      ② 定价权护栏: 净利率<8%的高ROE是杠杆/周转非定价权 → 🏰降🧱
      ③ 侵蚀红旗: 净利率趋势<-3pp 或 ROE持久性<40% → ⚠️存疑
      ④ 低谷穿越升级: 全样本保守(🧱/⚠️)但近5年[ROE持久≥80%+净利率斜率>0.3pp/年
         +非真侵蚀+CV≤0.30(排周期股)+净利率均值≥8%] → 升一级
    gross_margin: 可选, 仅展示用, 不参与判定(各端口口径差异大).
    """
    roe_pers = m.get("roe_persistence") or 0.0
    npm_cv = m.get("npm_cv")
    npm_mean = m.get("npm_mean")
    npm_trend = m.get("npm_trend")
    roe_pers_recent = m.get("roe_persistence_recent")
    npm_slope_recent = m.get("npm_slope_recent")
    flags = []

    # ① 基础门槛
    if roe_pers >= 0.70 and npm_cv is not None and npm_cv <= 0.20:
        verdict, rank = "🏰宽护城河", 0
    elif (roe_pers >= 0.40) or (npm_cv is not None and npm_cv <= 0.30):
        verdict, rank = "🧱窄护城河", 1
    else:
        verdict, rank = "·普通", 2

    # ② 定价权护栏 (防薄利代工假🏰)
    if rank == 0 and npm_mean is not None and npm_mean < 8:
        verdict, rank = "🧱窄护城河", 1
        flags.append(f"高ROE靠杠杆/周转(净利率仅{npm_mean:.1f}%<8%), 非定价权护城河")

    # ③ 侵蚀红旗
    if npm_trend is not None and npm_trend < -3:
        flags.append(f"利润率收缩{npm_trend:.1f}pp(护城河被侵蚀?)")
        verdict, rank = "⚠️护城河存疑", 3
    if roe_pers < 0.40:
        flags.append(f"ROE≥15%仅{roe_pers*100:.0f}%年份(资本回报不持久)")
        if rank < 3:
            verdict, rank = "⚠️护城河存疑", 3

    # ④ 低谷穿越升级 (防真护城河被全样本污染误判窄)
    trough_crossed = (
        rank in (1, 3)
        and roe_pers_recent is not None and roe_pers_recent >= 0.80
        and npm_slope_recent is not None and npm_slope_recent > 0.3
        and npm_trend is not None and npm_trend >= -3
        and npm_cv is not None and npm_cv <= 0.30
        and npm_mean is not None and npm_mean >= 8
    )
    if trough_crossed:
        if rank == 3:
            verdict, rank = "🧱窄护城河", 1
        elif rank == 1:
            verdict, rank = "🏰宽护城河", 0
        flags.append(
            f"低谷穿越升级: 近5年ROE≥15%持久{roe_pers_recent*100:.0f}%+净利率斜率"
            f"{npm_slope_recent:+.1f}pp/年(全样本被上市初虚高/行业低谷污染, 须核margin修复是否含成本端顺风)"
        )

    return verdict, rank, flags
