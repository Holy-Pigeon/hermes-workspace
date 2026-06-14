#!/usr/bin/env python3
"""
allocate.py — 资本配置纪律引擎 (纯只读)

价投第二支柱 = 资本配置。整个系统有 8+ 个信号生成工具
(估值分位/已实现α/护城河/相关性/筹码/南向...) 却从无一个
**可复用引擎**把这些信号综合成「目标权重」并对照行为护栏。
配置层此前只有一次性诊断 note(第六篇),从未工程化、从未定期跑。

本引擎做三件事(全部只读,绝不下单、绝不改库):
  1. 从 paper_trading.db 读真实持仓 → 计算当前市值权重。
  2. 对照「行为护栏」(用户自陈马丁/满仓负偏度教训固化):
       - 单标的权重上限 (集中度封顶,对抗满仓单押)
       - 等权惰性检测 (持仓权重高度雷同 = 从未做配置决策的信号)
       - 现金/敞口纪律 (账户级)
  3. 若给定信号文件,做「信号-权重对齐」诊断:
       edge 最大处是否给了最大权重?(对抗确认偏误/锚定成本)

设计哲学: 引擎不喊「买/卖」,只把「钱有没有放在 edge 最大处」
和「有没有违反预承诺的护栏」算成数字,surface 给人拍板。
这与 note#6 的一次性诊断互补: note 是某一天的快照,本引擎是可复跑的纪律。

数据诚实: 权重来自 DB 一手持仓市值,信号需人工/工具喂入 JSON,
绝不凭印象编造信号分。无信号文件时只做护栏体检,不做对齐诊断。
非买卖指令。
"""
import argparse
import os
import sqlite3
import json
import sys
import statistics

DB = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "paper-trading", "paper_trading.db",
)
DB = os.path.abspath(DB)

# ---- 行为护栏 (预承诺参数,源自用户自陈马丁/满仓负偏度教训) ----
MAX_SINGLE_WEIGHT = 0.35      # 单标的封顶: 任何一只 > 35% equity 即超集中
EQUAL_WEIGHT_CV = 0.12        # 权重变异系数 < 此值 = 近乎等权 = 未做配置决策
MIN_NAMES = 3                 # 有效持仓数下限(分散底线)


def load_positions(account):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """SELECT p.symbol,p.name,p.market,p.quantity,p.last_price,p.fx_rate,
                  a.name AS acct,a.cash,a.initial_capital
           FROM positions p JOIN accounts a ON p.account_id=a.id
           WHERE p.quantity>0 AND a.name=?""",
        (account,),
    ).fetchall()
    con.close()
    return rows


def list_accounts():
    con = sqlite3.connect(DB)
    rows = con.execute("SELECT name FROM accounts").fetchall()
    con.close()
    return [r[0] for r in rows]


def cv(values):
    if len(values) < 2:
        return 0.0
    m = statistics.mean(values)
    if m == 0:
        return 0.0
    return statistics.pstdev(values) / m


def analyze(account, signals=None, quiet=False):
    rows = load_positions(account)
    if not rows:
        if not quiet:
            print(f"[{account}] 无持仓,跳过。")
        return 0

    # 市值权重 (以 base_currency 计, fx_rate 折算)
    mvs = []
    for r in rows:
        fx = r["fx_rate"] or 1.0
        mv = r["quantity"] * (r["last_price"] or 0) * fx
        mvs.append((r["symbol"], r["name"], mv))
    equity = sum(m for _, _, m in mvs)
    cash = rows[0]["cash"] or 0
    total = equity + cash
    weights = [(s, n, mv / equity if equity else 0) for s, n, mv in mvs]
    weights.sort(key=lambda x: -x[2])

    flags = []  # (级别, 文本)

    # 护栏 1: 单标的封顶
    for s, n, w in weights:
        if w > MAX_SINGLE_WEIGHT:
            flags.append(("🔴", f"{n}({s}) 权重 {w:.1%} > 封顶 {MAX_SINGLE_WEIGHT:.0%} = 超集中(对抗满仓单押护栏触发)"))

    # 护栏 2: 等权惰性
    ws = [w for _, _, w in weights]
    weight_cv = cv(ws)
    if len(ws) >= 3 and weight_cv < EQUAL_WEIGHT_CV:
        flags.append(("🟡", f"持仓权重高度雷同(CV={weight_cv:.3f}<{EQUAL_WEIGHT_CV}) = 近乎等权,疑似从未做主动配置决策"))

    # 护栏 3: 有效持仓数
    hhi = sum(w * w for _, _, w in weights)
    eff_n = 1 / hhi if hhi else 0
    if eff_n < MIN_NAMES:
        flags.append(("🟡", f"有效持仓数 {eff_n:.1f} < {MIN_NAMES} = 分散不足"))

    # 对齐诊断: 信号 vs 权重
    align_lines = []
    if signals:
        # signals: {symbol: score}, score 越高 edge 越大
        scored = [(s, n, w, signals.get(s)) for s, n, w in weights]
        have = [(s, n, w, sc) for s, n, w, sc in scored if sc is not None]
        if len(have) >= 2:
            # 排名错配: 信号最强的是否拿了最大权重?
            by_sig = sorted(have, key=lambda x: -x[3])
            by_w = sorted(have, key=lambda x: -x[2])
            top_sig = by_sig[0]
            top_w = by_w[0]
            if top_sig[0] != top_w[0]:
                flags.append(("🟡",
                    f"信号-权重错配: edge 最强是 {top_sig[1]}(信号{top_sig[3]:+.2f}) "
                    f"但最大权重给了 {top_w[1]}({top_w[2]:.1%},信号{top_w[3]:+.2f})"))
            # 负信号高权重 = 最危险
            for s, n, w, sc in have:
                if sc < 0 and w > 0.20:
                    flags.append(("🔴",
                        f"{n}({s}) 信号为负({sc:+.2f})却持 {w:.1%} 重仓 = 钱押在 edge 为负处"))
            align_lines = [f"  {n}({s}): 权重{w:.1%} | 信号{sc:+.2f}" for s, n, w, sc in by_sig]

    # ---- 输出 ----
    has_red = any(lvl == "🔴" for lvl, _ in flags)
    if quiet and not has_red:
        # cron 友好: 慢性 🟡(等权惰性/分散)长期存在,不每轮刷屏,
        # 仅当出现 🔴(超集中/负 edge 重仓)这类需立即处理的硬告警才 surface。
        return 0

    print(f"\n=== 资本配置纪律体检 · 账户 [{account}] ===")
    print(f"权益 {equity:,.0f} | 现金 {cash:,.0f} | 总额 {total:,.0f} | 仓位 {equity/total:.1%}")
    print(f"有效持仓数 {eff_n:.1f} | 权重CV {weight_cv:.3f}")
    print("当前权重(equity口径):")
    for s, n, w in weights:
        print(f"  {n}({s}): {w:.1%}")
    if align_lines:
        print("信号-权重对齐(信号降序):")
        for ln in align_lines:
            print(ln)
    if flags:
        print("护栏告警:")
        for lvl, txt in flags:
            print(f"  {lvl} {txt}")
    else:
        print("✅ 所有护栏通过,无超集中/无等权惰性/无信号-权重错配。")

    return 1 if any(lvl == "🔴" for lvl, _ in flags) else 0


def main():
    ap = argparse.ArgumentParser(description="资本配置纪律引擎(纯只读)")
    ap.add_argument("--account", default="stockchoose", help="账户名(默认 stockchoose)")
    ap.add_argument("--all", action="store_true", help="扫所有账户")
    ap.add_argument("--signals", help="信号 JSON 文件路径 {symbol: score}")
    ap.add_argument("--quiet", action="store_true", help="无🔴告警则静默(cron 友好)")
    args = ap.parse_args()

    signals = None
    if args.signals:
        with open(args.signals) as f:
            signals = json.load(f)

    accounts = list_accounts() if args.all else [args.account]
    rc = 0
    for acct in accounts:
        rc |= analyze(acct, signals=signals, quiet=args.quiet)
    sys.exit(rc)


if __name__ == "__main__":
    main()
