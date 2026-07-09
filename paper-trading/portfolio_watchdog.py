#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
portfolio_watchdog.py — 组合巡检编排器 (纯只读, 零下单, 完全可逆)

把已建好的 5 个治理/健康检查器统一编排成一条「巡检」命令, 只在真正出现
红旗时输出, 否则静默——直接服务于每小时 watchdog 纪律。

⚠️ 信号纪律的核心设计 (避免 watchdog 沦为每小时噪音):
  把检查分成两类, 因为它们的【漂移速度】完全不同——
  - 【急性/快动】每天都可能变, 值得高频盯: 
      · thesis_check  价格类失效条件 (随盯市价每日变)
      · catalyst      催化剂窗口跨过临近阈值 (随日期逼近)
    这两类构成默认/--quiet 巡检对象, 挂 cron 高频跑。今天无触发→真静默。
  - 【慢性/结构】数周才漂移一次, 高频报=同一句话天天刷屏=噪音:
      · valuation_percentile  估值历史分位 (工业富联史上偏高区是已知静态事实)
      · correlation_check     相关性/地域集中度 (A股79%敞口是已登记的结构事实)
    这两类**不进高频巡检**, 仅 --full 时跑, 供人工每周复审。

  → 这样默认 --quiet 路径只在真出现【新的急性红旗】时才 ping, 符合
    'watchdog: 没异动就闭嘴, 每次 ping 都有 alpha' 的纪律。

编排对象 (全部为既有纯只读脚本, 本脚本不重复实现其逻辑, 只调度+聚合):
  急性(默认): thesis_check.py --json / catalyst_check.py
  结构(--full额外): valuation_percentile.py --quiet / correlation_check.py --quiet
  alpha_check.py 不编排 (网络IO+进度条, 每日盯市已自动跑, 避免重复拉指数)

退出码: 0 = 无急性红旗 (静默) ; 1 = 有红旗 (打印聚合报告)
设计为可挂 cron --quiet: 无红旗空 stdout, 有红旗才推 Discord。

数据诚实: 本脚本不产生任何新数据, 只转发子脚本的一手结论; 子脚本拉不到
数据时各自告警/跳过, 本编排器原样透传, 绝不填充。
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = "/opt/homebrew/bin/python3"
CATALYST_NEAR_DAYS = 30  # 催化剂窗口临近阈值(天), 与 catalyst_check WARN 对齐


def run(cmd, timeout=120):
    """跑子脚本, 返回 (exit_code, stdout, stderr)。失败不抛, 透传。"""
    try:
        p = subprocess.run(
            cmd, cwd=str(HERE), capture_output=True, text=True, timeout=timeout
        )
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"[TIMEOUT] {' '.join(cmd)} 超过 {timeout}s"
    except Exception as e:  # noqa
        return -1, "", f"[ERR] {' '.join(cmd)}: {e}"


def check_thesis():
    """价格类失效条件是否触发。返回 (有无红旗, 摘要行list)。"""
    code, out, err = run([PY, "thesis_check.py", "--json"])
    if code != 0 and not out:
        return None, [f"⚠️ thesis_check 执行异常: {err.strip()[:200]}"]
    try:
        data = json.loads(out)
    except Exception:
        return None, ["⚠️ thesis_check JSON 解析失败"]
    flags = []
    for h in data:
        trig = h.get("triggered") or []
        if trig:
            nm = h.get("name", h.get("symbol", "?"))
            dd = h.get("drawdown_pct")
            for t in trig:
                flags.append(f"🚨 [失效条件触发] {nm} (回撤{dd}%): {t}")
    return (len(flags) > 0), flags


def check_quiet(label, script, extra=None, timeout=120):
    """跑 --quiet 类脚本, stdout 非空即红旗。返回 (有无红旗, 摘要行list)。"""
    cmd = [PY, script, "--quiet"] + (extra or [])
    code, out, err = run(cmd, timeout=timeout)
    out = (out or "").strip()
    if out:
        # 取前若干非空行作为摘要, 完整内容由人工跑脚本看
        lines = [l for l in out.splitlines() if l.strip()]
        head = lines[:12]
        body = "\n    ".join(head)
        more = "" if len(lines) <= 12 else f"\n    …(共{len(lines)}行, 跑 {script} 看全文)"
        return True, [f"⚠️ [{label}] 有告警:\n    {body}{more}"]
    if code not in (0, 1) and err.strip():
        return None, [f"⚠️ {label} 执行异常: {err.strip()[:200]}"]
    return False, []


def check_catalyst():
    """催化剂窗口是否临近(<=30天)。catalyst_check 无 --quiet, 解析文本。"""
    code, out, err = run([PY, "catalyst_check.py"])
    if not out:
        return None, [f"⚠️ catalyst_check 执行异常: {err.strip()[:200]}"]
    # 解析所有「距今 N 天」, 配对其上文的标的行
    flags = []
    lines = out.splitlines()
    cur_title = None
    for ln in lines:
        # 标的行形如: [    ] 601138  2026 半年度报告  | 距今 80 天 | 远期登记
        m = re.search(r"距今\s+(\d+)\s+天", ln)
        if m:
            days = int(m.group(1))
            if days <= CATALYST_NEAR_DAYS:
                flags.append(f"📅 [催化剂临近 {days}天] {ln.strip()}")
    return (len(flags) > 0), flags


def main():
    ap = argparse.ArgumentParser(description="组合巡检编排器(纯只读)")
    ap.add_argument("--quiet", action="store_true",
                    help="仅当有红旗时输出, 否则静默(供cron)")
    ap.add_argument("--days", type=int, default=60,
                    help="correlation 用的回看交易日数(默认60)")
    ap.add_argument("--full", action="store_true",
                    help="额外跑慢漂移的结构检查(估值分位+相关性), 供人工周度复审")
    args = ap.parse_args()

    sections = []   # (模块名, 红旗行list)
    errors = []     # 执行异常(非红旗, 但要让人知道某模块没跑成)

    # 急性/快动检查: 默认每次都跑, 构成高频巡检的红旗来源
    checks = [
        ("持仓失效条件", check_thesis, None),
        ("催化剂日历", check_catalyst, None),
    ]
    # 结构/慢漂移检查: 仅 --full, 避免高频刷屏已知静态事实
    if args.full:
        checks += [
            ("估值历史分位", lambda: check_quiet("估值分位", "valuation_percentile.py"), None),
            ("相关性/集中度", lambda: check_quiet("相关性", "correlation_check.py",
                                              ["--days", str(args.days)]), None),
            # 慢漂移信号工具(季更): 此前各自建成但无任何 cron 调用=孤儿能力,
            # 收口进 --full 周度复审, 与急性 --quiet 高频巡检分层。
            # 注: moat_scorecard 全 universe 取数 >600s 且为年更频率, 不进周度编排,
            #     另列优化/单独季度 cadence 待办, 避免拖垮 --full。
            ("筹码集中度", lambda: check_quiet("筹码集中度", "holder_concentration.py", timeout=180), None),
            ("南向资金流", lambda: check_quiet("南向资金", "southbound_flow.py", timeout=180), None),
            # 资本配置纪律(价投第二支柱): allocate.py 此前是孤儿能力——能跑、对真实持仓
            # 算权重/查行为护栏(单标的封顶/等权惰性/信号-权重错配), 退码0/1合约与 check_quiet
            # 对齐, 却无任何 cron/编排调用=只在真人手动跑时存在。权重漂移慢, 归入 --full 周度
            # 结构层(与估值分位同 cadence), 收口这个 built-but-unwired 缺口。
            ("资本配置纪律", lambda: check_quiet(
                "资本配置", "../allocation-discipline/allocate.py", ["--all"], timeout=120), None),
            # 卖出纪律哨兵(exit-sentinel): built-but-unwired 缺口——脚本已建成自测、卡片已注册,
            # 但独立 cron 被用户 07-03 否决, 从建成起从未被任何调度器盯活性=PHANTOM卡片。
            # 它是 valuation-trigger(买入侧) 的卖出侧镜像, 盯4持仓论点破裂(ORPHAN/WINDOW/ADVERSE),
            # 论点漂移慢(证伪窗口多为季报级)且 --quiet 退码0/1合约与 check_quiet 对齐,
            # 收口进 --full 周度复审=无需新 cron 即让卖出侧监控有调度器盯活性(与配置纪律同 cadence)。
            ("持仓论点破裂哨兵", lambda: check_quiet(
                "卖出哨兵", "../exit-sentinel/exit_sentinel.py", timeout=120), None),
            # 马丁加仓哨兵(martingale-guard): built-but-unwired 缺口——脚本已建成自测、卡片已注册,
            # 但独立 cron 属真金白银风控敏感被留 proposed, 从建成起无任何调度器盯活性=cron-health
            # 反复告警的 UNWIRED_PROJECT 僵尸卡片。它盯成交时间序列的向下加仓摊低负偏度轨迹(用户
            # 第一自陈的爆仓机制), 属慢漂移行为纪律信号(轨迹随成交累积演化, 非高频), --quiet 退码
            # 0/1 + stdout 非空即红旗的合约与 check_quiet 完全对齐。与 exit-sentinel 同类,
            # 收口进 --full 周度复审=无需新独立 cron 即让此风控有调度器盯活性(同 cadence 结构层)。
            ("马丁加仓哨兵", lambda: check_quiet(
                "马丁哨兵", "../martingale-guard/martingale_guard.py", timeout=120), None),
        ]

    any_flag = False
    for name, fn, _ in checks:
        try:
            res = fn()
        except Exception as e:  # noqa
            errors.append(f"⚠️ {name} 编排异常: {e}")
            continue
        has, rows = res
        if has is None:
            errors.append(rows[0] if rows else f"⚠️ {name} 状态未知")
            continue
        if has and rows:
            any_flag = True
            sections.append((name, rows))

    # 输出
    if not any_flag and not errors:
        if not args.quiet:
            print("✅ 组合巡检: 全部治理检查通过, 无红旗 (失效条件/估值分位/集中度/催化剂均正常)")
        sys.exit(0)

    out = []
    out.append("=" * 70)
    out.append("🛡️ 组合巡检红旗汇总  (portfolio_watchdog)")
    out.append("=" * 70)
    for name, rows in sections:
        out.append(f"\n── {name} ──")
        for r in rows:
            out.append(f"  {r}")
    if errors:
        out.append("\n── 执行异常(需人工复跑确认) ──")
        for e in errors:
            out.append(f"  {e}")
    out.append("\n" + "-" * 70)
    out.append("说明: 本报告仅转发各只读子脚本结论, 不产生新数据; 详情请单独跑对应脚本。")
    print("\n".join(out))
    sys.exit(1)


if __name__ == "__main__":
    main()
