#!/usr/bin/env python3
"""db-freshness · 数据库表级新鲜度看门狗

系统级 gap（artifact-freshness 明文标注但 v1 未覆盖的盲区的实现）:
  - cron-health 读 jobs.json → 盯 JOB(跑没跑/送没送达/触没触发)
  - artifact-freshness 读文件 mtime → 盯文件型产出(dossier/note/scan)停更
  - 但「DB 文件 mtime 新鲜、内部某张时序表却静默冻结」两者都失明。
    典型: paper_trading.db 每日 daily_mark 写 nav_snapshots(DB mtime 永远新),
    而 benchmark_levels / alpha_snapshots 因恒生单源东财失效停更 → 06-22 曾冻结 10 天无人察觉。
    根因: 「取不到数就跳过、绝不编造」是数据真实性铁律的正确护栏,
           但它把一次硬失败转成表级静默冻结, 而 job/文件 两层监控对此结构性失明。

本工具: 纯只读 sqlite, 对配置里声明的每张时序表:
  1) STALE_TABLE  —— 表内最新日期距今超过交易日容忍窗口(周末不算迟到)
  2) LAG_DIVERGENCE —— 同库内「下游表」落后「上游基准表」超阈值(依赖链断裂,如 benchmark→alpha)

绝不改库、绝不写库、绝不下单。只读 + 报告 + 给 cron 判断要不要 ping。
"""
import sqlite3, json, sys, os, datetime, argparse

HOME = os.path.expanduser("~")
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checks.json")


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def trading_days_between(d_from: datetime.date, d_to: datetime.date) -> int:
    """粗略交易日差: 排除周末(不含节假日, 故容忍窗口需留冗余)。d_to>d_from 时为正。"""
    if d_to <= d_from:
        return 0
    n = 0
    cur = d_from
    while cur < d_to:
        cur += datetime.timedelta(days=1)
        if cur.weekday() < 5:  # 0-4 = Mon-Fri
            n += 1
    return n


def parse_date(v):
    if v is None:
        return None
    s = str(v)[:10]
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def max_date(conn, table, col):
    try:
        row = conn.execute(f"SELECT MAX({col}) FROM {table}").fetchone()
        return parse_date(row[0]) if row else None
    except sqlite3.Error as e:
        return ("__ERR__", str(e))


def run_checks(today=None):
    today = today or datetime.date.today()
    cfg = load_config()
    alerts = []
    report = []

    for db in cfg.get("databases", []):
        path = os.path.expanduser(db["path"])
        if not os.path.exists(path):
            alerts.append({"type": "DB_MISSING", "db": db["path"]})
            report.append(f"[DB_MISSING] {db['path']}")
            continue
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        latest = {}  # table -> date
        try:
            for t in db.get("tables", []):
                md = max_date(conn, t["table"], t["date_col"])
                if isinstance(md, tuple) and md[0] == "__ERR__":
                    alerts.append({"type": "QUERY_ERROR", "db": db["path"],
                                   "table": t["table"], "detail": md[1]})
                    report.append(f"[QUERY_ERROR] {db['path']}::{t['table']} {md[1]}")
                    continue
                if md is None:
                    alerts.append({"type": "EMPTY_TABLE", "db": db["path"], "table": t["table"]})
                    report.append(f"[EMPTY_TABLE] {db['path']}::{t['table']}")
                    continue
                latest[t["table"]] = md
                lag = trading_days_between(md, today)
                tol = t.get("tolerance_trading_days", 2)
                status = "OK" if lag <= tol else "STALE"
                line = f"{db['path']}::{t['table']:18} latest={md} lag={lag}td tol={tol} -> {status}"
                report.append(("[STALE_TABLE] " if status == "STALE" else "") + line)
                if status == "STALE":
                    alerts.append({"type": "STALE_TABLE", "db": db["path"], "table": t["table"],
                                   "latest": str(md), "lag_trading_days": lag, "tolerance": tol})

            # 依赖链背离检查: 下游表落后上游基准表
            for dep in db.get("dependencies", []):
                up, dn = dep["upstream"], dep["downstream"]
                if up in latest and dn in latest:
                    div = trading_days_between(latest[dn], latest[up])
                    maxlag = dep.get("max_lag_trading_days", 1)
                    if div > maxlag:
                        alerts.append({"type": "LAG_DIVERGENCE", "db": db["path"],
                                       "upstream": up, "downstream": dn,
                                       "upstream_latest": str(latest[up]),
                                       "downstream_latest": str(latest[dn]),
                                       "divergence_trading_days": div, "max_lag": maxlag})
                        report.append(f"[LAG_DIVERGENCE] {db['path']} {dn}({latest[dn]}) 落后 "
                                      f"{up}({latest[up]}) {div}td > {maxlag}")
        finally:
            conn.close()

    return {"today": str(today), "alerts": alerts, "report": report,
            "alert_count": len(alerts)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true",
                    help="无告警 exit0 静默 / 有告警 exit1 打印(给 cron 判断要不要 ping)")
    args = ap.parse_args()

    res = run_checks()

    if args.quiet:
        if res["alert_count"] == 0:
            sys.exit(0)
        print(f"⚠️ db-freshness: {res['alert_count']} 张表/依赖链异常")
        for a in res["alerts"]:
            print("  -", json.dumps(a, ensure_ascii=False))
        sys.exit(1)

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"=== db-freshness @ {res['today']} · {res['alert_count']} 告警 ===")
        for line in res["report"]:
            print(line)


if __name__ == "__main__":
    main()
