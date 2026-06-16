#!/usr/bin/env python3
"""
prediction_ledger.py — Tetlock式预测台账计分卡 (纯只读/纯本地, 不碰DB不下单)

把每篇研究note末尾的【可证伪论点+证伪条件】登记为带截止日的结构化预测,
到期后人工录入真实结果(resolve), 自动计算命中率和Brier校准分。

为什么存在: 我们已产出~11篇note, 每篇都给了'可证伪论点+证伪条件+待验证下一步',
但从无统一台账捕获这些站立预测并在中报落地后给自己计分。没有计分卡,
'纪律和可重复流程'无法被自己证伪——我们不知道自己的判断到底准不准, 在哪类
标的上系统性犯错。这正是Tetlock超级预测者的核心: 留痕 + 复盘 + 校准。

命令:
  list [--due-soon N]   列出预测(--due-soon只显示N天内到期的pending)
  resolve <id> <correct|wrong|partial|void> [--value "实测值"]  录入结果
  score                 计算命中率+Brier分(仅基于已resolved的)
  --quiet               无到期/无变化时静默(exit0), 供cron挂

数据诚实: confidence是登记时主观概率, 录入结果须以一手财报/监管公告为准,
不凭印象。Brier分=mean((confidence - hit)^2), 越低越准(0完美/0.25=瞎猜)。
"""
import json, sys, os
from datetime import datetime, date

LEDGER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "predictions.json")


def load():
    with open(LEDGER) as f:
        return json.load(f)


def save(data):
    with open(LEDGER, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def days_to(d):
    return (datetime.strptime(d, "%Y-%m-%d").date() - date.today()).days


def cmd_list(preds, due_soon=None, quiet=False):
    lines = []
    overdue = []
    imminent = []   # ≤14天内到期: 应主动提醒"去拉财报准备resolve"
    for p in preds:
        if p["outcome"] != "pending":
            continue
        dd = days_to(p["verify_by"])
        if due_soon is not None and dd > due_soon:
            continue
        flag = ""
        if dd < 0:
            flag = f" ⏰逾期{-dd}天未录入结果"
            overdue.append(p["id"])
        elif dd <= 14:
            flag = f" 🔴{dd}天内到期"
            imminent.append(p["id"])
        elif dd <= 45:
            flag = f" 🟡{dd}天"
        lines.append(f"[{p['id']}] {p['subject']} (信心{p['confidence']:.0%}, 截止{p['verify_by']}{flag})")
        lines.append(f"      论点: {p['claim'][:90]}")
        lines.append(f"      证伪: {p['falsification'][:90]}")
    # quiet(cron)模式: 仅在有逾期或临近(≤14天)到期的预测时才surface(exit1),
    # 否则静默exit0。修复前只看overdue=只在错过窗口后才报, 提醒方向是反的。
    if quiet and not overdue and not imminent:
        return 0
    if not lines:
        print("无匹配的pending预测。")
        return 0
    print(f"=== 站立预测 ({len([x for x in preds if x['outcome']=='pending'])}条pending) ===")
    print("\n".join(lines))
    if overdue:
        print(f"\n⏰ {len(overdue)}条已逾期待录入结果: {', '.join(overdue)} — 去拉一手财报后 resolve")
        return 1
    if imminent:
        print(f"\n🔴 {len(imminent)}条14天内到期: {', '.join(imminent)} — 临近窗口, 准备拉一手财报届时 resolve")
        return 1
    return 0


def cmd_resolve(data, pid, outcome, value=None):
    valid = {"correct", "wrong", "partial", "void"}
    if outcome not in valid:
        print(f"outcome须为 {valid}")
        return 1
    for p in data["predictions"]:
        if p["id"] == pid:
            p["outcome"] = outcome
            p["resolved_value"] = value
            p["resolved_date"] = date.today().isoformat()
            save(data)
            print(f"✅ {pid} 标记为 {outcome}" + (f" (实测: {value})" if value else ""))
            return 0
    print(f"未找到预测 {pid}")
    return 1


def calibration_health(preds):
    """ex-ante 校准健康诊断(无需任何已结算): 在结果出来前就暴露
    '信心压缩'(所有预测都贴0.5=没真表态, Brier事后无法区分技巧与运气)
    与'到期日挤堆'(一次性集中结算=校准反馈无法分批)两类自毁问题。
    纯统计读数, 不臆造。"""
    live = [p for p in preds if p["outcome"] == "pending"]
    if not live:
        return []
    confs = [p["confidence"] for p in live]
    n = len(confs)
    mean = sum(confs) / n
    var = sum((c - mean) ** 2 for c in confs) / n
    std = var ** 0.5
    avg_info = sum(abs(c - 0.5) for c in confs) / n  # 平均离0.5的"表态强度"
    rng = max(confs) - min(confs)
    from collections import Counter
    dl = Counter(p.get("verify_by") for p in live)
    top_date, top_n = dl.most_common(1)[0]
    flags = []
    if avg_info < 0.10:
        flags.append(
            f"⚠️ 信心压缩: {n}条未决预测平均仅离0.5 {avg_info:.3f}(区间{min(confs):.2f}~{max(confs):.2f}/σ={std:.3f})"
            f" → 全在'勉强好于抛硬币'区, 没真表态, 8/31结算时Brier无法区分技巧vs运气。"
            f"建议: 真有把握的拉到0.70+, 真没把握的下到0.35-, 敢分散才可被证伪。")
    if top_n / n >= 0.6:
        flags.append(
            f"⚠️ 到期挤堆: {top_n}/{n}条({top_n/n:.0%})都在 {top_date} 结算 → 校准反馈一次性引爆无法分批,"
            f"且全绑同一窗口=系统性同向暴露。建议: 拆出可早于中报证伪的子论点(批价/月度数据/渠道)错峰结算。")
    # ⚠️ 结果相关性: 同一标的+同一结算窗口的多条预测, 由同一份财报驱动 → 结果不独立。
    # Brier 把它们当 n 条独立观测会高估统计力(伪多重印证在'计分'层的复发,
    # 对应 signal-orthogonality 在'信号'层抓的同一种确认偏误)。有效独立样本 < n。
    import re as _re
    def _subj(p):
        m = _re.search(r"\((\d{4,6})\)", p["subject"])
        return m.group(1) if m else p["subject"]
    clusters = Counter((_subj(p), p.get("verify_by")) for p in live)
    correlated = {k: c for k, c in clusters.items() if c > 1}
    if correlated:
        eff_n = len(clusters)  # 同(标的,窗口)折叠为1个独立单元
        detail = "; ".join(f"{subj}@{vb}×{c}条" for (subj, vb), c in
                           sorted(correlated.items(), key=lambda x: -x[1]))
        flags.append(
            f"⚠️ 结果相关: {len(correlated)}组同标的+同窗口预测由同一份财报驱动({detail})"
            f" → 名义n={n}但有效独立样本≈{eff_n}, Brier按n计会高估统计力(伪多重印证)。"
            f"建议: 同标的多论点要么合并计1分, 要么错开结算窗口让结果真正独立。")
    return flags


def _next_id(preds):
    mx = 0
    for p in preds:
        try:
            mx = max(mx, int(str(p["id"]).lstrip("P")))
        except Exception:
            pass
    return f"P{mx + 1:03d}"


def cmd_add(data, kw):
    """登记新预测的唯一合法入口(根因机制, 对标 ie.py 治 ideas_log 手写之弊)。

    在登记当下就拦两类自毁问题, 而非靠周度看门狗事后才发现:
      1) 信心压缩: confidence 落在 0.45~0.65 的'勉强好于抛硬币'泥潭 → 拒绝,
         强制要么真表态(≥0.70 / ≤0.30)要么显式 --force-mushy 自认没把握并留痕。
      2) 到期挤堆: 若该 verify_by 已堆 ≥5 条 pending → 警告(不硬拒, 但提示错峰)。
    必填: --subject --claim --falsification --confidence --verify-by --direction
    可选: --source-note --force-mushy(自认泥潭区, 留痕放行)
    """
    required = ["subject", "claim", "falsification", "confidence", "verify-by", "direction"]
    missing = [r for r in required if not kw.get(r)]
    if missing:
        print(f"缺必填参数: {', '.join('--' + m for m in missing)}")
        return 1
    try:
        conf = float(kw["confidence"])
    except ValueError:
        print("--confidence 须为 0~1 的小数")
        return 1
    if not (0.0 < conf < 1.0):
        print("--confidence 须严格在 (0,1) 区间")
        return 1
    # 日期格式校验
    try:
        datetime.strptime(kw["verify-by"], "%Y-%m-%d")
    except ValueError:
        print("--verify-by 须为 YYYY-MM-DD")
        return 1
    # ── 信心压缩护栏(登记时拦截, 非事后) ──
    if 0.45 <= conf <= 0.65 and "force-mushy" not in kw:
        print(f"❌ 信心 {conf:.0%} 落在 0.45~0.65 泥潭区 = 没真表态, 8/31结算时 Brier 无法区分技巧与运气。")
        print("   → 真有把握: 拉到 ≥0.70(看多论点)或 ≤0.30(看空论点); 真没把握: 加 --force-mushy 自认并留痕。")
        print("   敢分散信心才可被证伪。这是 prediction-ledger 的核心纪律, 不是建议。")
        return 1
    preds = data["predictions"]
    # ── 到期挤堆警告(不硬拒) ──
    same_day = sum(1 for p in preds if p["outcome"] == "pending" and p.get("verify_by") == kw["verify-by"])
    if same_day >= 5:
        print(f"⚠️ 警告: {kw['verify-by']} 已堆 {same_day} 条 pending 预测, 再加=校准反馈一次性引爆+同向暴露。")
        print("   建议拆出可早于该窗口证伪的子论点(批价/月度数据/渠道)错峰结算。已照常登记, 仅提示。")
    pid = _next_id(preds)
    rec = {
        "id": pid,
        "created": date.today().isoformat(),
        "subject": kw["subject"],
        "claim": kw["claim"],
        "falsification": kw["falsification"],
        "direction": kw["direction"],
        "confidence": conf,
        "verify_by": kw["verify-by"],
        "source_note": kw.get("source-note", ""),
        "outcome": "pending",
        "resolved_value": None,
        "resolved_date": None,
    }
    preds.append(rec)
    save(data)
    print(f"✅ 已登记 {pid}: {kw['subject']} (信心{conf:.0%}, 截止{kw['verify-by']})")
    return 0


def cmd_score(preds):
    # ex-ante 校准健康: 结果没出来也要先暴露信心压缩/到期挤堆
    for f in calibration_health(preds):
        print(f)
    resolved = [p for p in preds if p["outcome"] in ("correct", "wrong", "partial")]
    if not resolved:
        print("\n还没有已结算的预测可计分(事后Brier待8/31等窗口录入)。但上方 ex-ante 校准诊断现在就该看。")
        return 0
    print()
    # hit: correct=1, partial=0.5, wrong=0
    hitmap = {"correct": 1.0, "partial": 0.5, "wrong": 0.0}
    hits = [hitmap[p["outcome"]] for p in resolved]
    brier = sum((p["confidence"] - hitmap[p["outcome"]]) ** 2 for p in resolved) / len(resolved)
    hit_rate = sum(hits) / len(hits)
    print(f"=== 预测计分卡 (n={len(resolved)}已结算) ===")
    print(f"命中率(partial算0.5): {hit_rate:.1%}")
    print(f"Brier分: {brier:.3f}  (0=完美 / 0.25=随机瞎猜 / 越低越准)")
    print(f"\n按标的:")
    for p in resolved:
        print(f"  [{p['id']}] {p['subject']}: {p['outcome']} (信心{p['confidence']:.0%}) {p.get('resolved_value') or ''}")
    return 0


def main():
    args = sys.argv[1:]
    quiet = "--quiet" in args
    args = [a for a in args if a != "--quiet"]
    data = load()
    preds = data["predictions"]

    if not args or args[0] == "list":
        due = None
        if "--due-soon" in args:
            idx = args.index("--due-soon") + 1
            if idx >= len(args) or not args[idx].lstrip("-").isdigit():
                # 裸 --due-soon 不带天数 → 默认 45 天窗口, 不崩溃
                due = 45
            else:
                due = int(args[idx])
        return cmd_list(preds, due_soon=due, quiet=quiet)
    elif args[0] == "add":
        # 解析 --key value 与布尔 --flag(force-mushy)
        kw = {}
        i = 1
        bool_flags = {"force-mushy"}
        while i < len(args):
            a = args[i]
            if a.startswith("--"):
                key = a[2:]
                if key in bool_flags:
                    kw[key] = True
                    i += 1
                elif i + 1 < len(args):
                    kw[key] = args[i + 1]
                    i += 2
                else:
                    print(f"参数 {a} 缺值")
                    return 1
            else:
                i += 1
        return cmd_add(data, kw)
    elif args[0] == "resolve":
        val = None
        if "--value" in args:
            val = args[args.index("--value") + 1]
        return cmd_resolve(data, args[1], args[2], val)
    elif args[0] == "score":
        return cmd_score(preds)
    elif args[0] == "calib":
        # watchdog 专用: 只跑 ex-ante 校准健康诊断(信心压缩/到期挤堆)。
        # 有红旗→打印+exit1(cron 推送); 无红旗→静默 exit0。
        flags = calibration_health(preds)
        if not flags:
            if not quiet:
                print("校准健康: 无红旗(信心已分散+到期已错峰)。")
            return 0
        for f in flags:
            print(f)
        return 1
    else:
        print(__doc__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
