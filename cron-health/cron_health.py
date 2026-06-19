#!/usr/bin/env python3
"""
cron-health · 定时任务交付健康度看门狗
================================================
解决的系统级 gap: 现有所有看门狗只盯「持仓/选股/护城河」等业务对象,
**没有任何东西盯 cron 自身的健康**, 尤其是「最后一公里交付」。

发现动机(2026-06-14 创新引擎实测):
  多个 job last_status=ok(脚本/agent 正常跑完产出报告), 但 last_delivery_error
  ="Discord send failed" —— 报告生成成功却静默没送达用户, 而因为 job 本身算 ok,
  没有任何机制会报警。整个组合的价值链终点是「把结论交付给用户」, 这最后一步零监控。

本工具做三件事(纯只读 jobs.json, 不改任何 cron):
  1) RUN_ERROR    : last_status == 'error' (脚本超时/崩溃)
  2) DELIVERY_FAIL: last_delivery_error 非空 (产出了但没送达=最隐蔽)
  3) STALE        : enabled 但 last_run_at 距今超过「该 cadence 应跑次数」过久
                    (说明调度根本没触发, 比报错更隐蔽)

输出 JSON, 供它自己的 cron 判断要不要 ping 用户。
绝不修改 jobs.json, 绝不动 cron, 完全只读。
"""
import json
import os
import sys
import argparse
from datetime import datetime, timezone, timedelta

JOBS_PATH = os.path.expanduser("~/.hermes/cron/jobs.json")
# 交付/运行失败累积台账(JSONL, 每行一条去重后的失败事件)。
# *.log 已被 .gitignore 覆盖=运行时状态不入库, 删文件即回滚。
LEDGER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "delivery_failures.log")

# ── 看门狗型脚本「exit 1 = 发现告警」并非崩溃 ──────────────────────────
# 根因(2026-06-15 创新引擎实测): cron-health 自身是 --quiet 看门狗, 有告警即 exit 1。
# cron 框架把任何 exit!=0 记成 last_status=error → 下一轮 cron-health 读到自己
# last_status=error → 误报 [RUN_ERROR] cron-health → 又 exit 1 → 永久自我告警死循环。
# 同样的坑会命中所有「rc=1 即硬信号」的看门狗脚本(如预测台账到期提醒)。
# 修复: 对这些脚本, 仅当报错是「by-design 的 exited with code 1」时跳过 RUN_ERROR;
# 真正的超时(timed out)/其他退出码(code 2+)仍如实告警, 不放过真崩溃。
SELF_SIGNAL_SCRIPTS = {
    "cron_health.sh",            # 本看门狗自身
    "prediction_ledger_due_reminder.sh",  # 逾期 rc=1 硬信号
    "portfolio_watchdog.sh",     # watchdog 模式, 有红旗 exit 1
    "portfolio_watchdog_full.sh",
}


def _is_by_design_exit1(job):
    """该 job 是否为「exit 1 = 发现告警」的看门狗, 且本次报错正是 by-design 的 code 1。
    超时/其他退出码不在此列(仍视为真故障)。"""
    script = str(job.get("script") or "")
    base = os.path.basename(script)
    if base not in SELF_SIGNAL_SCRIPTS:
        return False
    err = str(job.get("last_error") or "")
    # 只看首行(框架的退出判决), 不看其后嵌入的 stdout——否则报告正文里引用的
    # 别的 job「timed out」字样会污染判断。首行形如 "Script exited with code 1"
    # 或 "Script timed out after 120s"。
    first_line = err.splitlines()[0] if err else ""
    fl = first_line.lower()
    # 只豁免「纯 exit code 1」信号; 首行含 timed out / code 2+ 的真故障不豁免
    if "timed out" in fl:
        return False
    return "exited with code 1" in fl

# cadence 关键词 -> 容忍的「最大未运行秒数」(留足冗余, 只抓真卡死不抓抖动)
# 仅用于 STALE 粗判; 拿不准就不报(宁缺毋滥)。


def parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def expected_interval_seconds(job):
    """从 schedule 粗估期望运行间隔(秒)。拿不准返回 None=不做 STALE 判断。"""
    sch = job.get("schedule") or {}
    disp = str(sch.get("display") or sch.get("expr") or "")
    kind = sch.get("kind")
    # every Nm / every Nh 形式
    if kind == "interval" or disp.startswith("every"):
        import re
        m = re.search(r"(\d+)\s*m", disp)
        if m:
            return int(m[1]) * 60
        h = re.search(r"(\d+)\s*h", disp)
        if h:
            return int(h[1]) * 3600
        return None
    # 标准 5 段 cron: 只对「每小时/每天」给保守阈值
    parts = disp.split()
    if len(parts) == 5:
        minute, hour, dom, mon, dow = parts
        # 每小时(分钟固定, 小时*)
        if hour == "*" and minute != "*":
            return 3600
        # 每周(dow 固定) —— 必须先于「每天」判断, 否则 `0 18 * * 0` 会被
        # 「每天」分支(只看 hour/dom/mon 不看 dow)截胡误判成 24h, 把 168h 一跑的
        # 周度任务在 72h 后误报 STALE(狼来了)。dow 限定才是周度的判别特征。
        if dow not in ("*",) and (hour.isdigit() or "," in hour):
            return 7 * 86400
        # 每天(小时固定单值, 且非周度)
        if hour.isdigit() and dom == "*" and mon == "*":
            return 86400
        # 含逗号的多次/天(dow=*)
        if "," in hour:
            return 86400  # 保守按天
        # 每周(dow 固定) — 兜底(理论上已被上面提前分支覆盖)
        if dow not in ("*",) and hour.isdigit():
            return 7 * 86400
    return None


def analyze(now=None):
    if now is None:
        now = datetime.now(timezone.utc)
    with open(JOBS_PATH) as f:
        data = json.load(f)
    alerts = []
    for j in data.get("jobs", []):
        if not j.get("enabled", True):
            continue
        name = j.get("name", "?")
        jid = j.get("id", "?")
        last_run = parse_dt(j.get("last_run_at"))
        # 1) RUN_ERROR (看门狗 by-design 的 exit 1 不算崩溃, 避免自我告警死循环)
        if j.get("last_status") == "error" and not _is_by_design_exit1(j):
            alerts.append({
                "type": "RUN_ERROR",
                "job": name, "id": jid,
                "last_run": j.get("last_run_at"),
                "detail": str(j.get("last_error") or "")[:200],
            })
        # 2) DELIVERY_FAIL (即使 last_status==ok)
        de = j.get("last_delivery_error")
        if de:
            alerts.append({
                "type": "DELIVERY_FAIL",
                "job": name, "id": jid,
                "last_run": j.get("last_run_at"),
                "deliver_target": j.get("deliver"),
                "detail": str(de)[:200],
            })
        # 3) STALE: 期望间隔可估 且 实际太久没跑
        interval = expected_interval_seconds(j)
        if interval and last_run:
            lr = last_run if last_run.tzinfo else last_run.replace(tzinfo=timezone.utc)
            overdue = (now - lr).total_seconds()
            # 容忍 3 个周期(给重试/抖动留冗余), 且至少 2 小时
            tol = max(interval * 3, 7200)
            if overdue > tol:
                alerts.append({
                    "type": "STALE",
                    "job": name, "id": jid,
                    "last_run": j.get("last_run_at"),
                    "overdue_hours": round(overdue / 3600, 1),
                    "expected_interval_hours": round(interval / 3600, 2),
                })
    return alerts


def _ledger_key(a):
    """失败事件的去重键: 同一个 job 的同一次失败 run 只记一次。
    锚定 (id, last_run, type)——因 last_run 随每次 run 变化, 同一次失败 run 被
    多轮 cron-health 重复读到时 key 相同=不重复入账; 下一次 run 再失败则 last_run
    不同=新事件入账。这正是把『快照态』转成『按失败 run 计数』的关键。"""
    return f"{a.get('id')}|{a.get('last_run')}|{a.get('type')}"


def _load_ledger_keys():
    keys = set()
    rows = []
    if not os.path.exists(LEDGER_PATH):
        return keys, rows
    with open(LEDGER_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            rows.append(r)
            keys.add(r.get("key"))
    return keys, rows


def record_failures(alerts, now=None):
    """把本轮 DELIVERY_FAIL / RUN_ERROR 失败事件去重后 append 进台账。
    返回本轮新记入的条数。纯 append-only, 不改 jobs.json。"""
    if now is None:
        now = datetime.now(timezone.utc)
    failures = [a for a in alerts if a.get("type") in ("DELIVERY_FAIL", "RUN_ERROR")]
    if not failures:
        return 0
    seen, _ = _load_ledger_keys()
    new = 0
    with open(LEDGER_PATH, "a") as f:
        for a in failures:
            key = _ledger_key(a)
            if key in seen:
                continue
            rec = {
                "key": key,
                "logged_at": now.isoformat(),
                "type": a.get("type"),
                "job": a.get("job"),
                "id": a.get("id"),
                "last_run": a.get("last_run"),
                "deliver_target": a.get("deliver_target"),
                "detail": a.get("detail"),
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            seen.add(key)
            new += 1
    return new


def ledger_history(window_hours=168):
    """读台账, 统计近 window_hours 内各 job 的失败 run 次数=flapping 可见性。
    『已恢复』结论必须以一段窗口内零失败为据, 而非单次快照 exit0。"""
    _, rows = _load_ledger_keys()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    per_job = {}
    for r in rows:
        ts = parse_dt(r.get("logged_at"))
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts < cutoff:
            continue
        name = r.get("job", "?")
        d = per_job.setdefault(name, {"DELIVERY_FAIL": 0, "RUN_ERROR": 0,
                                      "last": None, "id": r.get("id")})
        t = r.get("type")
        if t in d:
            d[t] += 1
        if d["last"] is None or r.get("logged_at") > d["last"]:
            d["last"] = r.get("logged_at")
    return per_job


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="输出完整 JSON")
    ap.add_argument("--quiet", action="store_true",
                    help="无告警 exit 0 静默; 有告警 exit 1 并打印")
    ap.add_argument("--no-record", action="store_true",
                    help="不写失败台账(默认会去重 append)")
    ap.add_argument("--history", type=int, metavar="HOURS", nargs="?", const=168,
                    help="只读台账, 报告近 N 小时(默认168=7天)各 job 失败 run 次数")
    args = ap.parse_args()

    # --history: 纯只读台账, 把 flapping 频率打出来, 不读 jobs.json 不写台账
    if args.history is not None:
        hist = ledger_history(args.history)
        if args.json:
            print(json.dumps({"window_hours": args.history, "per_job": hist},
                             ensure_ascii=False, indent=2))
        elif not hist:
            print(f"✅ 近 {args.history}h 台账零失败事件(交付/运行均健康)")
        else:
            print(f"⚠️ 近 {args.history}h 交付/运行失败台账(按失败 run 去重计数):")
            for name, d in sorted(hist.items(),
                                  key=lambda kv: -(kv[1]['DELIVERY_FAIL'] + kv[1]['RUN_ERROR'])):
                total = d["DELIVERY_FAIL"] + d["RUN_ERROR"]
                print(f"  {name}: {total} 次失败 run "
                      f"(送达失败 {d['DELIVERY_FAIL']} / 运行错 {d['RUN_ERROR']}), "
                      f"最近 {d['last']}")
        return

    try:
        alerts = analyze()
    except FileNotFoundError:
        print(json.dumps({"error": f"jobs.json not found at {JOBS_PATH}"}))
        sys.exit(2)

    # 把本轮失败事件去重 append 进台账(把快照态转成可累积的 flapping 记录)
    newly_logged = 0
    if not args.no_record:
        try:
            newly_logged = record_failures(alerts)
        except Exception:
            newly_logged = 0  # 台账写失败绝不影响主告警路径
    out = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "alert_count": len(alerts),
        "alerts": alerts,
        "newly_logged": newly_logged,
        "flapping_7d": ledger_history(168),
    }
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        if not alerts:
            print("✅ 所有 enabled cron 交付健康(本快照): 无 RUN_ERROR / DELIVERY_FAIL / STALE")
        else:
            print(f"⚠️ 检出 {len(alerts)} 条 cron 健康告警:")
            for a in alerts:
                line = f"  [{a['type']}] {a['job']} (last_run={a.get('last_run')})"
                if a["type"] == "DELIVERY_FAIL":
                    line += f" → 送达失败: {a.get('detail')} (target={a.get('deliver_target')})"
                elif a["type"] == "RUN_ERROR":
                    line += f" → {a.get('detail')}"
                elif a["type"] == "STALE":
                    line += f" → 已 {a.get('overdue_hours')}h 未跑 (期望每 {a.get('expected_interval_hours')}h)"
                print(line)
        # flapping 可见性: 即便本快照干净, 近 7d 有过失败 run 也要提示(防『已恢复』误判)
        flap = out["flapping_7d"]
        if flap:
            print(f"  ⏳ 近7d失败台账(快照清也别急着说『已恢复』): " +
                  "; ".join(f"{n}×{d['DELIVERY_FAIL']+d['RUN_ERROR']}" for n, d in flap.items()))
    if args.quiet:
        sys.exit(1 if alerts else 0)


if __name__ == "__main__":
    main()
