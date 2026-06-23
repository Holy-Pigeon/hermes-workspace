#!/usr/bin/env python3
"""
artifact-freshness · 产出物新鲜度看门狗（cron-health 的产出侧对偶）
================================================================
解决的系统级 gap（元层巡检 2026-06-23 实证）:
  cron-health 盯的是 **JOB** 健康(jobs.json: 脚本跑没跑、送没送达)。
  但过去 10 天最反复、最痛的失效是另一类——**JOB 绿灯 + 交付正常, 产出物却静默冻结**:
    · 2026-06-22  恒生基准单源东财失效, alpha_snapshots 冻结 10 天, 而 alpha_check
                  job 每轮照常跑绿灯(『基准缺失跳过不编造』护栏 darkening 了产出而非报错);
    · 2026-06-21  research-pipeline 产出脏 dossier 后未重生成, valuation-trigger 照常
                  消费这份冻结的 dossier;
    · us-tech-scout latest_scan.json / polymarket changes_1h.json 等若某源挂掉同样静默不更新。
  根因机制: 『取不到数就跳过、绝不编造』是数据真实性铁律的正确护栏, 但它把一次**硬失败**
  转成了**静默冻结**——产出文件停止更新, 而 job 层监控对此结构性失明。

本工具就是那个盯『文件到底有没有变新』的看门狗:
  读 dashboard/projects.json(已由 ie.py register-project 维护的单一事实源),
  对每个声明了 heartbeat_file + freshness_hours 的项目, 比对该路径下**最新文件的 mtime**
  与声明的新鲜度 SLA, 超期即报 STALE_OUTPUT。

边界(诚实声明, 绝不夸大覆盖):
  · 只查**文件/目录 mtime**。能抓: JSON/note/dossier/scan 等文件型产出停更。
  · **抓不到 DB 内单表冻结**(如 paper_trading.db 内 alpha_snapshots 冻结但 daily_mark
    仍写价格→DB mtime 仍新鲜)。这类需内容级校验, 属更重的单独议题, 留 TODO 钩子, 不在 v1 谎称覆盖。
  · 只对**显式声明 freshness_hours** 的项目告警(避免对无 SLA 项目误报); 无 SLA 的项目
    列入 unmonitored 名单作治理提醒(推动补声明), 但不告警。

纯只读, 绝不改任何文件 / 不动 cron / 不下单。有告警 exit 1(看门狗约定), 否则 exit 0。
"""
import json
import os
import sys
import argparse
import subprocess
from datetime import datetime, timezone

PROJECTS_PATH = os.path.expanduser("~/hermes-workspace/dashboard/projects.json")
# 超期容忍倍数: 声明 freshness_hours 的 TOL 倍后才告警, 给重试/调度抖动/周末留冗余,
# 只抓真冻结不抓轻微迟到(宁缺毋滥, 防『狼来了』侵蚀看门狗可信度)。
TOLERANCE = 1.5
# 至少冗余小时数(对短 cadence 项目防抖)。
MIN_SLACK_HOURS = 6


def newest_mtime(path):
    """返回 path 下最新文件的 mtime(epoch 秒)。文件→自身; 目录→递归最新文件(排除 .git)。
    取不到返回 None(绝不编造时间)。"""
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return None
    if os.path.isfile(path):
        try:
            return os.path.getmtime(path)
        except OSError:
            return None
    # 目录: 递归找最新文件 mtime
    latest = None
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d != ".git"]
        for fn in files:
            fp = os.path.join(root, fn)
            try:
                m = os.path.getmtime(fp)
            except OSError:
                continue
            if latest is None or m > latest:
                latest = m
    return latest


def analyze(now=None):
    if now is None:
        now = datetime.now(timezone.utc).timestamp()
    with open(PROJECTS_PATH) as f:
        data = json.load(f)
    projects = data.get("projects", data if isinstance(data, list) else [])

    alerts = []          # 声明了 SLA 且超期
    monitored = []       # 声明了 SLA 且新鲜
    unmonitored = []     # 有 heartbeat 但无 SLA(治理提醒, 不告警)
    missing = []         # 声明了 heartbeat 但路径不存在

    for p in projects:
        pid = p.get("id", "?")
        hb = p.get("heartbeat_file")
        fresh_h = p.get("freshness_hours")
        if not hb:
            continue
        mt = newest_mtime(hb)
        if mt is None:
            missing.append({"id": pid, "heartbeat": hb})
            continue
        age_h = (now - mt) / 3600.0
        if fresh_h is None:
            unmonitored.append({"id": pid, "age_hours": round(age_h, 1)})
            continue
        slack = max(fresh_h * TOLERANCE, fresh_h + MIN_SLACK_HOURS)
        if age_h > slack:
            alerts.append({
                "type": "STALE_OUTPUT",
                "id": pid,
                "name": p.get("name", pid),
                "heartbeat": hb,
                "age_hours": round(age_h, 1),
                "sla_hours": fresh_h,
                "alert_threshold_hours": round(slack, 1),
            })
        else:
            monitored.append({"id": pid, "age_hours": round(age_h, 1),
                              "sla_hours": fresh_h})
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "alert_count": len(alerts),
        "alerts": alerts,
        "monitored_fresh": monitored,
        "unmonitored_no_sla": unmonitored,
        "missing_path": missing,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="输出完整 JSON")
    ap.add_argument("--quiet", action="store_true",
                    help="无告警 exit 0 静默; 有 STALE_OUTPUT 则 exit 1 并打印")
    args = ap.parse_args()

    try:
        out = analyze()
    except FileNotFoundError:
        print(json.dumps({"error": f"projects.json not found at {PROJECTS_PATH}"}))
        sys.exit(2)

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        alerts = out["alerts"]
        if not alerts:
            print(f"✅ 所有声明 SLA 的产出物均新鲜 "
                  f"(已监控 {len(out['monitored_fresh'])} / "
                  f"无SLA未监控 {len(out['unmonitored_no_sla'])} / "
                  f"路径缺失 {len(out['missing_path'])})")
        else:
            print(f"⚠️ 检出 {len(alerts)} 条产出物冻结告警 (STALE_OUTPUT):")
            for a in alerts:
                print(f"  [{a['type']}] {a['name']} ({a['id']}): "
                      f"产出已 {a['age_hours']}h 未更新 "
                      f"(SLA={a['sla_hours']}h, 告警阈值={a['alert_threshold_hours']}h) "
                      f"→ {a['heartbeat']}")
        if out["unmonitored_no_sla"]:
            ids = ", ".join(u["id"] for u in out["unmonitored_no_sla"])
            print(f"  ℹ️ 无 freshness_hours SLA(建议补声明以纳入监控): {ids}")
        if out["missing_path"]:
            ids = ", ".join(m["id"] for m in out["missing_path"])
            print(f"  ❓ heartbeat 路径不存在: {ids}")

    if args.quiet:
        sys.exit(1 if out["alert_count"] else 0)


if __name__ == "__main__":
    main()
