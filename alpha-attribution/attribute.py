#!/usr/bin/env python3
"""
alpha-attribution · 呼叫α负读数的失败模式归因器

为什么存在（元层能力缺口，非缺某只票）
---------------------------------------------------
系统使命「超越巴菲特」=相对收益游戏。call-alpha-tracker 已给出**负读数**
（2026-06-23 首跑：12/13 条进行中呼叫为负呼叫α，均值约 -3.19pp；StockChoose
选股口径 -4.45pp 跑输沪深300）。但过去两周系统对这个负 verdict 的唯一回应是
**继续加发现 lens**（quality-compounder / us-tech-scout / valuation-trigger
各一镜头），**没有任何一轮回答最该问的：为什么已下的呼叫在亏相对钱**。

这是确认偏误 + 缝补舒适区在架构层固化：用「再造一个更好的入口漏斗」回避
「现有出口在亏钱」的难题。本工具补的就是这个缺口——把负呼叫α**机械拆成
三类失败模式**，让「发现-呼叫-计分-归因-改规则」闭环里缺的那一环（归因）落地。

三类失败模式（机械可判，不靠主观叙事）
---------------------------------------------------
F1 方向错（看空强势股 / 看多弱势股）：
    stance=看空但标的跑赢基准（excess>0），或 stance=看多但标的跑输基准。
    典型：把「贵」当「该空」信号——但贵的票可以更贵。系统性把估值高位
    当做空理由，是深度价值锚定在出口侧的复发。
F2 时机错（好生意买在 price-in 满了）：
    stance=看多 且 direction 属「质量/护城河/成长」派系（非便宜派），
    却跑输基准。典型：买伟大公司付了过高价，reverse_dcf 隐含增速已高仍进池。
F3 选择错（便宜陷阱）：
    stance=看多 且 direction 属「便宜/低估」派系，却跑输基准。
    典型：低 PE 分位锚定选出真烂生意，便宜是有原因的。

输出：每条负呼叫贴一个失败模式标签 + 全样本失败模式分布，指出
**当前最痛的系统性偏差是哪一类**，结论应回灌 StockChoose 选股规则 /
research-pipeline 入池门槛，而非再开新发现镜头。

边界与诚实纪律
---------------------------------------------------
- 纯只读。取数完全复用 call-alpha-tracker（call_alpha.py --json），本工具
  零独立取数、零写盘，任一源失败即该条标 SKIP，绝不编造。
- 失败模式按 direction 标签 + 已实现 excess **机械分类**，是确定性规则不是
  主观叙事；direction→派系映射显式声明，未知 direction 标 UNKNOWN 不强判。
- 呼叫α是**至今浮动相对收益**，非已结算业绩（论点多在 8/31 才证伪）。负读数
  是**过程信号不是终局定论**，但 12/13 负的一致性已足够拉响方法论警报，
  本器把「一致性负」翻译成「偏差结构」，供改规则用，不是买卖指令。
- 必须用 /opt/homebrew/bin/python3 运行（依赖 call_alpha → marketdata/akshare）。
"""
import sys, os, json, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
CALL_ALPHA = os.path.join(WS, "call-alpha-tracker", "call_alpha.py")
PY = "/opt/homebrew/bin/python3"

# direction → 派系（三分而非二分，2026-07-01 元层修复归因误标）
#   cheap_trap : 纯低估锚、无质量/证伪trap背书 → 跑输=F3 真便宜陷阱(叠ROE质量闸对症)
#   cheap_qual : 低估锚但direction自带『证伪trap』或『成长/复苏拐点』背书(证据词_not_trap/_growth/
#                _inflection) → 跑输≠便宜陷阱，是【好生意等价/择时】问题，ROE质量闸对它无效(它本就高ROE)
#   quality    : 质量护城河成长派(F2靶) / short: 看空派(F1) / neutral: 不计
#
# 根因(为何拆)：原映射把 *_not_trap / *_growth / *_inflection 一律塞进 cheap→F3，于是
# 茅台/宁德/迈瑞(系统自己研究note已逐项证伪trap、皆高ROE)被机械贴『便宜陷阱』，
# 处方开出『叠ROE质量闸』——但这些票本就过质量闸，处方无效。这正是 StockChoose F3 veto
# 连卡3轮的上游病根：归因层把 F2/时机问题误报成 F3/选择问题，enforcement 打错靶。
FAMILY = {
    # 低估锚 + 自带『非陷阱/成长/复苏拐点』背书 → 跑输属择时/耐心问题，非选烂生意
    "real_cheap_not_trap": "cheap_qual",
    "real_cheap_growth": "cheap_qual",
    "mispriced_trough_not_trap": "cheap_qual",
    "recovery_inflection_not_trap": "cheap_qual",
    "bullish_on_recovery": "cheap_qual",
    "reasonably_undervalued_growth": "cheap_qual",
    # 纯低估锚、无质量背书 → 跑输=F3 真便宜陷阱(低分位锚定选出真烂生意)
    "undervalued": "cheap_trap",
    "cheap": "cheap_trap",
    # 质量/护城河/成长派（看多，锚=生意质量）→ 跑输=F2 时机错(好生意买贵了)
    "moat_understated": "quality",
    "organic_ramp_intact": "quality",
    "smart_money_accumulation": "quality",
    "bullish": "quality",
    # 看空派 → F1 由 stance+excess 判
    "bearish_on_valuation": "short",
    "value_trap_warning": "short",
    "bearish": "short",
    "overvalued": "short",
    "distribution_topping": "short",
    # 中性
    "low_correlation_diversifier": "neutral",
    "diversification": "neutral",
    "neutral": "neutral",
}

MODE_LABEL = {
    "F1": "方向错(看空强势/看多弱势)",
    "F2": "时机错(好生意买在price-in满)",
    "F3": "选择错(便宜陷阱)",
    "F4": "耐心错(证伪trap的好生意买早/需时间)",
}
MODE_FIX = {
    "F1": "改规则: 别把『贵』当『该空』——贵的票可以更贵。StockChoose/入池门槛"
          "应区分『估值高位』与『派发顶背离』，单凭高 PE 分位不构成做空理由。",
    "F2": "改规则: 好生意也要等合理价。research-pipeline 入池前 reverse_dcf 隐含"
          "增速若已 price-in 满（要求增速≈已兑现增速），即便护城河强也应延后进池。",
    "F3": "改规则: 杀便宜陷阱。低 PE 分位是必要非充分条件，入池须叠加质量闸"
          "（ROE 持久性/毛利/现金含量），避免低分位锚定选出真烂生意。",
    "F4": "⚠不是选择错，别开ROE质量闸(这些票本就高ROE、note已逐项证伪trap)。"
          "真问题是【好生意买早/耐心不足】：低估锚成立但价值兑现需时间(证伪trap≠立即跑赢)。"
          "对症=延长评估窗口至论点证伪日(多为中报8/31)再计分，且入场分批而非一次性满仓，"
          "而非把它误报成F3去加质量闸——加了也拦不住(它过闸)，只会误伤真正的好生意候选。",
}


def get_call_alpha_rows():
    """复用 call-alpha-tracker 的 --json，绝不独立取数。"""
    out = subprocess.run([PY, CALL_ALPHA, "--json"],
                         capture_output=True, text=True, timeout=180)
    if out.returncode != 0:
        raise RuntimeError(f"call_alpha.py 退出码 {out.returncode}: {out.stderr[:200]}")
    return json.loads(out.stdout)


def classify(row):
    """对一条 OK 行返回 (mode, family)；非 OK / 正α / 中性返回 (None, family)。"""
    direction = row.get("direction", "")
    family = FAMILY.get(direction, "unknown")
    if row.get("status") != "OK":
        return None, family
    ca = row.get("call_alpha", 0)
    if ca >= 0:
        return None, family  # 正α=没失败，不归因
    # 负α：按 stance/family 分类
    stance = row.get("stance")
    if family == "short" or stance == "看空":
        return "F1", family          # 看空却负α=标的跑赢基准=空在强势股
    if family == "quality":
        return "F2", family          # 看多好生意却跑输=买贵了
    if family == "cheap_qual":
        return "F4", family          # 看多『证伪trap/成长』的低估票却跑输=好生意买早/需时间(非陷阱)
    if family == "cheap_trap":
        return "F3", family          # 看多纯低估票却跑输=真便宜陷阱
    if family == "neutral":
        return None, family          # 低相关分散器跑输≠失败(它本就不追涨), 不污染F2桶
    if stance == "看多":
        return "F2", family          # 未归类看多默认归时机/质量侧
    return None, family


def main():
    quiet = "--quiet" in sys.argv
    as_json = "--json" in sys.argv
    try:
        rows = get_call_alpha_rows()
    except Exception as e:
        print(f"[alpha-attribution] 取 call-alpha 失败，跳过(不编造): {e}",
              file=sys.stderr)
        sys.exit(2)

    classified, skips = [], []
    for r in rows:
        mode, fam = classify(r)
        if r.get("status") != "OK":
            skips.append(r)
            continue
        if mode:
            classified.append({**r, "mode": mode, "family": fam})

    ok_rows = [r for r in rows if r.get("status") == "OK"]
    losers = [r for r in ok_rows if r.get("call_alpha", 0) < 0]

    if as_json:
        print(json.dumps({
            "ok_count": len(ok_rows),
            "loser_count": len(losers),
            "classified": classified,
        }, ensure_ascii=False, indent=1))
        return

    # quiet: 只有当存在负α呼叫(=系统在亏相对钱)才输出，否则静默
    if quiet and not losers:
        sys.exit(0)

    from collections import Counter
    dist = Counter(c["mode"] for c in classified)

    print("=" * 66)
    print("呼叫α负读数 · 失败模式归因   (机械分类, 至今浮动非结算)")
    print(f"  进行中呼叫 {len(ok_rows)} 条 | 负α {len(losers)} 条 | 已归因 {len(classified)} 条")
    print("=" * 66)
    if not classified:
        print("  当前无负α呼叫可归因——发现+尽调机器暂未在总量上亏相对钱。")
    else:
        # 哪一类失败模式最痛（条数 + 累计负α）
        burden = {}
        for c in classified:
            burden.setdefault(c["mode"], [0, 0.0])
            burden[c["mode"]][0] += 1
            burden[c["mode"]][1] += c["call_alpha"]
        print("  失败模式分布（条数 / 累计呼叫α）:")
        for m in sorted(burden, key=lambda x: burden[x][1]):
            n, tot = burden[m]
            print(f"    {m} {MODE_LABEL[m]:<22} {n}条 / {tot:+.1f}pp")
        worst = min(burden, key=lambda x: burden[x][1])
        print("-" * 66)
        print(f"  ⚠ 最痛系统性偏差: {worst} {MODE_LABEL[worst]}")
        print(f"    {MODE_FIX[worst]}")
        print("-" * 66)
        print("  逐条:")
        for c in sorted(classified, key=lambda x: x["call_alpha"]):
            print(f"    {c['mode']} {c['id']} {c['subject'][:16]:<16} "
                  f"[{c['stance']}] 呼叫α {c['call_alpha']:+.1f}pp "
                  f"({c['direction']})")
    print("=" * 66)
    print("注: 归因是机械规则(direction派系+已实现excess), 非主观叙事。结论应回灌")
    print("    StockChoose选股规则/research-pipeline入池门槛, 而非再开新发现镜头。")


if __name__ == "__main__":
    main()
