#!/usr/bin/env python3
"""
test_moat_core.py — moat_core 判定单元测试 (纯函数, 零网络, 秒级).
用历史已验证的真实指标向量回归, 锁死 2026-06-13 定版的护栏行为, 防未来漂移.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from moat_core import classify_moat, compute_metrics, lstsq_slope

fail = 0

def check(name, got, want):
    global fail
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: got={got} want={want}")
    if not ok:
        fail += 1

print("=== classify_moat 护栏回归 (历史已验证向量) ===")

# 迈瑞: 真宽护城河 (ROE中位29.7/净利率均值29.4/CV0.111)
v, r, f = classify_moat({"roe_persistence": 1.0, "npm_cv": 0.111, "npm_mean": 29.4,
                         "npm_trend": 1.0, "roe_persistence_recent": 1.0, "npm_slope_recent": 0.5})
check("迈瑞→🏰宽", r, 0)

# 工业富联: 薄利代工, 定价权护栏须把高ROE降级 (净利率仅4.2%)
v, r, f = classify_moat({"roe_persistence": 0.9, "npm_cv": 0.07, "npm_mean": 4.2,
                         "npm_trend": 0.2, "roe_persistence_recent": 1.0, "npm_slope_recent": 0.1})
check("工业富联→🧱窄(定价权护栏降级)", r, 1)
check("工业富联→护栏flag firing", any("非定价权" in x for x in f), True)

# 宁德: 低谷穿越型, 全样本CV0.241须升🏰 (近5年ROE持久100%+斜率正)
v, r, f = classify_moat({"roe_persistence": 0.67, "npm_cv": 0.241, "npm_mean": 13.9,
                         "npm_trend": -0.4, "roe_persistence_recent": 1.0, "npm_slope_recent": 1.5})
check("宁德→🏰宽(低谷穿越升级)", r, 0)
check("宁德→升级flag firing", any("低谷穿越升级" in x for x in f), True)

# 紫金: 商品周期股, CV0.56须被周期护栏拦在升级路径外 → 维持🧱
v, r, f = classify_moat({"roe_persistence": 1.0, "npm_cv": 0.56, "npm_mean": 12.0,
                         "npm_trend": 2.0, "roe_persistence_recent": 1.0, "npm_slope_recent": 2.3})
check("紫金→🧱窄(周期护栏挡升级, ROE持久≥40%入窄)", r, 1)

# 海康: 真侵蚀 (净利率趋势-6.1pp) → ⚠️存疑, 不被强行救
v, r, f = classify_moat({"roe_persistence": 1.0, "npm_cv": 0.15, "npm_mean": 20.0,
                         "npm_trend": -6.1, "roe_persistence_recent": 0.6, "npm_slope_recent": -1.0})
check("海康→⚠️存疑(真侵蚀)", r, 3)

# MSFT: 美股宽护城河 (用 scout 实测向量 ROE持久1.0/净利率32.1/CV0.212)
# 注意 CV0.212>0.20 故基础门槛入🧱, 但ROE持久1.0≥0.40也入🧱; 美股scout旧逻辑是🏰
# 这里验证统一口径: CV0.212 不满足🏰(≤0.20), 但近5年若满足升级则可升🏰
v, r, f = classify_moat({"roe_persistence": 1.0, "npm_cv": 0.212, "npm_mean": 32.1,
                         "npm_trend": 2.0, "roe_persistence_recent": 1.0, "npm_slope_recent": 1.0})
# 全样本: roe_pers1.0>=0.70 但 cv0.212>0.20 → 不满足🏰条件 → 入🧱(roe_pers>=0.40)
# 近5年升级: rank1 + 持久1.0 + 斜率1.0>0.3 + trend2>=-3 + cv0.212<=0.30 + mean32>=8 → 升🏰
check("MSFT→🏰宽(高ROE厚margin经低谷升级路径)", r, 0)

print("\n=== compute_metrics 数学正确性 ===")
# 斜率: [10,12,14,16,18] 每年+2 → 斜率应=2.0
check("lstsq_slope线性序列", round(lstsq_slope([10,12,14,16,18]), 2), 2.0)
# CATL式: 近5年[13.7,11.7,?,14.9,18.1]-不对, 用纯净序列验证统计
m = compute_metrics([20,21,22,21,20], [29,30,29,30,29], recent_window=5)
check("compute_metrics npm_cv低", m["npm_cv"] < 0.05, True)
check("compute_metrics roe持久性100%", m["roe_persistence"], 1.0)

print(f"\n{'='*40}\n{'全部通过 ✅' if fail==0 else f'{fail} 个失败 ❌'}")
sys.exit(1 if fail else 0)
