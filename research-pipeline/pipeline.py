#!/usr/bin/env python3
"""
pipeline.py — 研究编排流水线 (纯只读编排器)

目的: 把此前【创新引擎每轮亲手跑】的研究尽调链路产品化、剥离成独立可挂 cron 的
专职流水线, 让创新引擎回到元层不再下场做个股研究。

它不发明任何新数据/新分析, 只把已有三件工具按价投尽调顺序串起来:
  ① stock-discovery/tech_screener.py  → 发现 ⭐ 候选 + 取 PE/price/增长/质量
  ② research/reverse_dcf.py            → 候选现价 price-in 多高增速 (隐含预期)
  ③ moat-durability/moat_scorecard.py  → 候选护城河耐久度 verdict

输出一份【候选研究简报 stub】: 把三件套结论拼到一张表, 末尾留 thesis/催化剂/
预测台账登记的 TODO 钩子。这份 stub 是【人/后续研究 cron 深挖的起点】, 不是终稿,
更不是买卖指令。

数据诚实: 本编排器零新增数据, 只转发各子脚本一手结论; EPS-TTM 由 price/PE 反算
(±1%, 与各 note 口径一致); 子脚本拉不到数据时各自告警/跳过, 编排器原样透传绝不填充。

退出码: 0=无新候选(--quiet 静默) / 1=有候选简报。
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta

WS = os.path.expanduser("~/hermes-workspace")
PY = "/opt/homebrew/bin/python3"
SCREENER = os.path.join(WS, "stock-discovery", "tech_screener.py")
RDCF = os.path.join(WS, "research", "reverse_dcf.py")
MOAT = os.path.join(WS, "moat-durability", "moat_scorecard.py")
LEDGER = os.path.join(WS, "prediction-ledger", "prediction_ledger.py")
ORTHO = os.path.join(WS, "signal-orthogonality", "signal_orthogonality.py")
# 本流水线消费的三件套信号 id (须与 signal_registry.json 登记一致)
PIPELINE_SIGNALS = "tech_screener,reverse_dcf,moat_scorecard"
OUT_DIR = os.path.join(WS, "research-pipeline", "dossiers")

# 校准闭环窗口: 每次周度跑surface掉在N天内到期/已逾期的站立预测,
# 提醒去拉一手财报resolve。没有这一步, prediction-ledger只进不出,
# score()永不触发, Tetlock自我校准在8/31窗口静默死亡。
DUE_SOON_DAYS = 45

CN_TZ = timezone(timedelta(hours=8))


def run(cmd, cwd=None):
    """跑子进程, 返回 (stdout, stderr, rc). 失败不抛, 让调用方决定。"""
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return p.stdout, p.stderr, p.returncode


def parse_screener(out):
    """从 tech_screener 文本输出解析 ⭐ 候选块。返回 list of dict。
    只抓 ⭐(价值成长候选), 不抓 🔍/🔄/⚠️ — 那些是降级/存疑, 不进尽调流水线。"""
    cands = []
    # 候选块以 "⭐ 名称(代码)" 起头
    blocks = re.split(r"\n(?=[⭐🔍🔄⚠️])", out)
    for b in blocks:
        if not b.startswith("⭐"):
            continue
        m = re.search(r"⭐\s+(.+?)\((\d{6})\)", b)
        if not m:
            continue
        name, code = m.group(1).strip(), m.group(2)
        pe = _grab(r"PE-TTM\s+([\d.]+)", b)
        price = _grab(r"价格:\s+([\d.]+)", b)
        npm = _grab(r"净利率\s+([\-\d.]+)%", b)
        d = {"code": code, "name": name, "pe_ttm": pe, "price": price, "net_margin": npm,
             "raw": b.strip()}
        cands.append(d)
    return cands


def _grab(pat, s):
    m = re.search(pat, s)
    return float(m.group(1)) if m else None


def reverse_dcf_for(name, price, eps):
    out, _, _ = run([PY, RDCF, "--name", name, "--price", f"{price}",
                     "--eps", f"{eps}", "--exit-mults", "15,18,22"])
    return out.strip()


def moat_for(code, name):
    out, _, _ = run([PY, MOAT, code, "--name", name, "--json"])
    # 进度条在 stderr, JSON 在 stdout; 取 stdout 里第一个 '[' 起的 JSON
    i = out.find("[")
    if i < 0:
        return None
    try:
        arr = json.loads(out[i:])
        return arr[0] if arr else None
    except Exception:
        return None


def ortho_disclosure():
    """跑 signal-orthogonality 审计本流水线三件套, 把『印证力折扣』如实写进简报头。
    这是反确认偏误的工程化: 流水线把 tech_screener+reverse_dcf+moat 拼成『三层尽调』,
    但前两者共享 price+income_statement (🔴高度共线), 名义3层独立证据实际打折。
    子脚本拉不到就返回温和占位, 绝不编造正交结论。"""
    out, _, _ = run([PY, ORTHO, "--signals", PIPELINE_SIGNALS])
    out = (out or "").strip()
    header = "### ⚠️ 信号正交性披露 (反『伪多重印证』)"
    if not out:
        return header + "\n> (正交性审计器无输出, 跳过; 引用本简报时仍须自行判断证据独立性)"
    # 抽取关键裁定行, 避免把整段审计塞进每份简报
    key = []
    for ln in out.splitlines():
        s = ln.strip()
        if s.startswith("并集根输入") or s.startswith("🔴") or s.startswith("❌") or "income_statement" in s and "被" in s:
            key.append("> " + s)
    body = "\n".join(key) if key else "> " + out.replace("\n", "\n> ")
    return (header + "\n> 本简报的『发现/估值/护城河』三层并非完全独立证据——"
            "tech_screener 与 reverse_dcf 共享 price+利润表(🔴高度共线), "
            "三者都消费利润表。**按独立根输入计权而非按层数计权**, 避免虚假信心。\n" + body)


def build_dossier(cands):
    now = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M")
    lines = [f"# 候选研究简报 (研究编排流水线自动生成)  {now} CST", ""]
    lines.append("> 本简报是【尽调起点 stub】非终稿, ⭐=tech_screener 价值成长候选, 已自动拼接")
    lines.append("> 反向DCF隐含增速 + 护城河 verdict。**候选≠买入**, 须人工补 thesis/催化剂/")
    lines.append("> 一手财报核验后才进 StockChoose 复审通道。数据全转发子脚本一手结论。")
    lines.append("")
    lines.append(ortho_disclosure())
    lines.append("")
    for c in cands:
        lines.append(f"## ⭐ {c['name']}({c['code']})")
        lines.append("")
        # tech_screener 块
        lines.append("### 发现层 (tech_screener 一手)")
        lines.append("```")
        lines.append(c["raw"])
        lines.append("```")
        # 反向DCF
        eps = None
        if c["price"] and c["pe_ttm"] and c["pe_ttm"] != 0:
            eps = round(c["price"] / c["pe_ttm"], 3)
        lines.append("")
        lines.append("### 估值层 (reverse_dcf, EPS-TTM=price/PE 反算 ±1%)")
        if eps and c["net_margin"] is not None and c["net_margin"] > 0:
            lines.append("```")
            lines.append(reverse_dcf_for(c["name"], c["price"], eps))
            lines.append("```")
        elif c["net_margin"] is not None and c["net_margin"] <= 0:
            lines.append("(亏损/微利, PE 口径反向DCF 无意义, 跳过 — 须改用 PS/现金跑道框架)")
        else:
            lines.append("(缺 price/PE, 无法反算 EPS, 跳过)")
        # 护城河
        lines.append("")
        lines.append("### 护城河层 (moat_scorecard 一手, 8年年报)")
        mv = moat_for(c["code"], c["name"])
        if mv:
            lines.append(f"- **verdict**: {mv.get('verdict')}  (rank {mv.get('rank')})")
            lines.append(f"- ROE中位 {mv.get('roe_median')}% / ROE持久性 {mv.get('roe_persistence')} "
                         f"/ 净利率均值 {mv.get('npm_mean')}% / CV {mv.get('npm_cv')} "
                         f"/ 近5年净利率斜率 {mv.get('npm_slope_recent5_pp_yr')}pp/年")
            if mv.get("flags"):
                for f in mv["flags"]:
                    lines.append(f"- ⚑ {f}")
        else:
            lines.append("(moat 端口无数据/港股无此端口, 跳过)")
        # TODO 钩子
        lines.append("")
        lines.append("### 待人工/后续研究 cron 深挖 (TODO)")
        lines.append("- [ ] 拆最新单季 YoY 的量增 vs 价/基数效应 (一手财报)")
        lines.append("- [ ] 护城河来源定性: 网络效应/转换成本/规模经济/牌照 哪一种?")
        lines.append("- [ ] 估值隐含增速 vs 历史实际增速的安全垫判断")
        lines.append("- [ ] 若通过 → 登记 prediction-ledger (可证伪论点+证伪条件+截止日)")
        lines.append("- [ ] 若通过 → 进 StockChoose 复审通道")
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def ledger_due_soon():
    """surface掉在DUE_SOON_DAYS天内到期或已逾期的站立预测。
    纯只读转发 prediction_ledger.py list --due-soon; 子脚本拉不到就返回空串绝不编造。
    返回 (text, has_overdue): text为空表示无临近到期项。"""
    out, _, rc = run([PY, LEDGER, "list", "--due-soon", str(DUE_SOON_DAYS)])
    out = out.strip()
    if not out or "无匹配" in out:
        return "", False
    return out, (rc == 1)


def main():
    ap = argparse.ArgumentParser(description="研究编排流水线 (纯只读编排器)")
    ap.add_argument("--quiet", action="store_true",
                    help="无 ⭐ 候选时静默 exit0 (cron 友好); 有候选则写 dossier 并打印路径")
    ap.add_argument("--symbol", help="只对单只跑 (调试用)")
    ap.add_argument("--no-write", action="store_true", help="不落盘, 仅 stdout")
    args = ap.parse_args()

    cmd = [PY, SCREENER]
    if args.symbol:
        cmd += ["--symbol", args.symbol]
    out, err, rc = run(cmd, cwd=os.path.dirname(SCREENER))
    cands = parse_screener(out)

    # 校准闭环: 无论有无新候选都surface临近到期的站立预测,
    # 这是prediction-ledger唯一的"出"机制——否则只进不出, score()永不触发。
    due_text, has_overdue = ledger_due_soon()

    if not cands:
        if has_overdue or (due_text and not args.quiet):
            print("研究编排流水线: 本轮无 ⭐ 新候选, 但有站立预测临近到期需校准:")
            print(due_text)
            print("\n→ 去拉一手财报后 prediction_ledger.py resolve <id> <correct|wrong|partial|void>")
            sys.exit(1 if has_overdue else 0)
        if not args.quiet:
            print("研究编排流水线: 本轮无 ⭐ 价值成长候选 (发现层空)。")
        sys.exit(0)

    dossier = build_dossier(cands)
    if due_text:
        dossier += "\n\n## ⏰ 校准闭环: 临近到期的站立预测 (去resolve)\n\n```\n" + due_text + "\n```\n"

    if args.no_write:
        print(dossier)
        sys.exit(1)

    os.makedirs(OUT_DIR, exist_ok=True)
    fname = f"dossier_{datetime.now(CN_TZ).strftime('%Y-%m-%d')}.md"
    fpath = os.path.join(OUT_DIR, fname)
    with open(fpath, "w") as f:
        f.write(dossier)

    names = ", ".join(f"{c['name']}({c['code']})" for c in cands)
    print(f"研究编排流水线: 生成 {len(cands)} 份候选简报 → {fpath}")
    print(f"候选: {names}")
    print("（这是尽调起点 stub, 非买卖指令; 须人工补 thesis/催化剂/一手核验）")
    sys.exit(1)


if __name__ == "__main__":
    main()
