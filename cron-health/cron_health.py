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
        # 每天(小时固定单值)
        if hour.isdigit() and dom == "*" and mon == "*":
            return 86400
        # 含逗号的多次/天
        if "," in hour:
            return 86400  # 保守按天
        # 每周(dow 固定)
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
        # 1) RUN_ERROR
        if j.get("last_status") == "error":
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="输出完整 JSON")
    ap.add_argument("--quiet", action="store_true",
                    help="无告警 exit 0 静默; 有告警 exit 1 并打印")
    args = ap.parse_args()
    try:
        alerts = analyze()
    except FileNotFoundError:
        print(json.dumps({"error": f"jobs.json not found at {JOBS_PATH}"}))
        sys.exit(2)
    out = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "alert_count": len(alerts),
        "alerts": alerts,
    }
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        if not alerts:
            print("✅ 所有 enabled cron 交付健康: 无 RUN_ERROR / DELIVERY_FAIL / STALE")
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
    if args.quiet:
        sys.exit(1 if alerts else 0)


if __name__ == "__main__":
    main()
