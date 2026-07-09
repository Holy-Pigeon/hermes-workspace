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
  4) PAUSED_STALE : enabled=false 但暂停超过 PAUSED_STALE_DAYS 天仍未处理
                    (被静默关掉的僵尸 job; 其驾驶舱卡片仍显示为『活着』=治理盲区)

输出 JSON, 供它自己的 cron 判断要不要 ping 用户。
绝不修改 jobs.json, 绝不动 cron, 完全只读。
"""
import json
import os
import re
import sys
import argparse
from datetime import datetime, timezone, timedelta

JOBS_PATH = os.path.expanduser("~/.hermes/cron/jobs.json")
# 一个 cron 被暂停超过这么多天仍未处理(重开或删除) → 视为僵尸, 报 PAUSED_STALE。
# 阈值给足冗余(临时暂停几天很正常), 只抓「忘了它」的长期僵尸。
PAUSED_STALE_DAYS = 7
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
    "artifact_freshness.sh",     # 产出冻结 STALE_OUTPUT → by-design exit 1
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


PROJECTS_PATH = os.path.expanduser("~/hermes-workspace/dashboard/projects.json")
HSCRIPTS_DIR = os.path.expanduser("~/.hermes/scripts")
# 编排器所在目录: 部分项目不挂自己的 cron, 而是被 paper-trading 下的 watchdog
# 编排脚本(portfolio_watchdog.py 等)以子进程串联调用。这类算「已接线」不报。
ORCH_GLOB = os.path.expanduser("~/hermes-workspace/paper-trading/*.py")
# 核心/库/数据型项目: 天然无需自己的 cron(被 import 的库 / 数据目录 / 元层自身),
# 即便未在语料中出现也不算「僵尸未接线」, 白名单排除防误报。
UNWIRED_SKIP_IDS = {
    "marketdata",       # 统一取数库, 被各脚本 import 而非独立跑
    "research",         # note 数据目录
    "innovation-engine",  # 元层自身(本看门狗的调度方)
    "paper-trading",    # 编排器/DB 宿主
    "stockchoose",      # 有独立 cron(名称在 jobs.json 里是中文显示名)
}


def _run_corpus():
    """把「所有会真正触发执行的地方」的文本汇成一个语料串:
    cron 定义(jobs.json) + 『真正被调度的』shell 包装脚本 + paper-trading 下的编排器 py。
    一个项目若在此语料中被引用(id / 目录路径), 说明它有真实执行入口=已接线。
    纯只读, 取不到的源静默跳过绝不编造。

    假阴性堵漏(2026-07-09 创新引擎实测): 旧版把 scripts/ 下『所有』*.sh 无差别纳入语料,
    但一个 wrapper *.sh 若自己从未被 jobs.json 调度(既不在某 job 的 script 字段, 也不在
    任何 enabled job 的 prompt 里被 `bash .../x.sh` 调用), 它就只是另一个孤儿——读它的内容
    会把它提到的项目 id 误判成『已接线』。实证代价: call-alpha-tracker 的 call_alpha_tracker.sh
    存在于 scripts/ 且正文含该 id, 但零 cron 调度 → 旧版据此把这个真僵尸清白放行。
    修复: 仅当某 *.sh 的 basename 出现在 jobs.json 文本中(=真被调度)才纳入其内容为『已接线』证据。"""
    import glob as _glob
    corpus = ""
    jobs_text = ""
    # 假阳性堵漏(2026-07-10 创新引擎实测): 旧版把 *整份* jobs.json dump 进语料, 连同
    # last_error/last_status/last_delivery_error/paused_reason 等『运行期输出字段』一起纳入。
    # 致命自指: cron-health 自己上一轮报 UNWIRED 后, 框架把含那 4 个 id 的告警文本写进它的
    # last_error, 下一轮 corpus 因此『看见』这 4 个 id → 误判已接线 → 0 告警; 再下一轮 last_error
    # 清空 → 4 个 id 又消失 → 重新告警。=> 检测器的输出污染了自己的输入, 隔轮 fire/silence 翻烧饼,
    # 正是同 4 项目被反复重议 ~15 次的机制根因。
    # 修复: 只纳入每个 job 的『定义型字段』(真实接线证据), 剔除一切运行期输出字段。
    _DEF_FIELDS = ("name", "prompt", "script", "command", "context_from", "skills", "skill")
    try:
        with open(JOBS_PATH) as f:
            _jobs = json.load(f).get("jobs", [])
        _defs = []
        for _j in _jobs:
            _defs.append({k: _j.get(k) for k in _DEF_FIELDS if _j.get(k) is not None})
        jobs_text = json.dumps(_defs, ensure_ascii=False)
    except Exception:
        jobs_text = ""
    corpus += jobs_text
    # 编排器 py 始终纳入(它们被 scheduled 的 wrapper 调用, 是二级接线证据)
    for fp in _glob.glob(ORCH_GLOB):
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                corpus += " " + f.read()
        except Exception:
            continue
    # wrapper *.sh: 只纳入『真被 jobs.json 调度』的那些, 孤儿 wrapper 不算接线证据
    _wrapper_text = ""
    for fp in _glob.glob(os.path.join(HSCRIPTS_DIR, "*.sh")):
        if os.path.basename(fp) not in jobs_text:
            continue  # 该 wrapper 自己没被任何 cron 调度 → 它提到的 id 不算已接线
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                _wrapper_text += " " + f.read()
        except Exception:
            continue
    corpus += _wrapper_text
    # 接线链追踪(2026-07-10): 一个 scheduled wrapper/prompt 常只点名它直接调的 *.py 路径
    # (如 research_pipeline_weekly.sh 调 research-pipeline/pipeline.py), 而真正串联下游项目的
    # 子编排器就是那个 .py——它引用的 quality-compounder/signal-orthogonality 等 id 只写在 .py 里。
    # 故须顺链把『被 scheduled 语料点名的 .py 文件』内容也纳入, 否则会把经 pipeline.py 编排的
    # 真已接线项目误报 UNWIRED(此前靠 jobs.json 运行期字段污染意外遮住, 那个 bug 一修就暴露)。
    # 只跟一层。路径可能是绝对(/Users/.../pipeline.py)或 shell 变量式($WS/alpha-attribution/attribute.py),
    # 故按 basename 在 workspace 内解析, 兼容两种写法; 排除检测器自身防注释自指污染。
    _chain_text = jobs_text + " " + _wrapper_text
    _WS = os.path.expanduser("~/hermes-workspace")
    _SELF = os.path.abspath(__file__)
    _self_base = os.path.basename(_SELF)
    _ws_py = {}  # basename -> 首个匹配的 workspace 内 .py 绝对路径
    for _fp in _glob.glob(os.path.join(_WS, "**", "*.py"), recursive=True):
        _ws_py.setdefault(os.path.basename(_fp), _fp)
    _seen = set()
    for _bn in re.findall(r"([\w-]+\.py)", _chain_text):
        if _bn == _self_base or _bn in _seen:
            continue
        _seen.add(_bn)
        _fp = _ws_py.get(_bn)
        if not _fp or os.path.abspath(_fp) == _SELF:
            continue
        try:
            with open(_fp, encoding="utf-8", errors="ignore") as f:
                corpus += " " + f.read()
        except Exception:
            continue
    return corpus


def unwired_projects(now=None):
    """5) UNWIRED_PROJECT: 项目卡片在驾驶舱『活着』且目录里有可跑的 .py 脚本,
    但它既没有自己的 cron、也没被任何编排器串联调用 → 静默从不执行的僵尸能力。

    根因盲区(2026-07-07 创新引擎实测): 现有两个元看门狗对这一类结构性失明——
      · cron-health 只读 jobs.json 里『已存在的 job』(这些项目根本没进 jobs.json);
      · artifact-freshness 只对『声明了 freshness_hours』的项目告警(这些没声明 SLA)。
    实证代价: capital-deployment(资本部署看门狗)一直未接线, 而它一跑就报出
      50M(全书 56%)现金闲置 25 天无人复盘——这种该每天盯的信号却从未触发。

    判据(保守, 宁缺毋滥防狼来了): 项目须同时满足
      有 heartbeat_file + 非 manual + 无 ports(排除 launchd 常驻 web 服务)
      + 目录内至少一个 .py(有可执行载体) + 不在核心/库白名单
      + id 未在执行语料(cron/脚本/编排器)中出现。
    纯只读, 任何异常静默返回空列表, 绝不影响主 cron 健康路径。"""
    alerts = []
    try:
        with open(PROJECTS_PATH) as f:
            projs = json.load(f).get("projects", [])
    except Exception:
        return alerts
    corpus = _run_corpus()
    for p in projs:
        pid = p.get("id", "")
        if not pid or pid in UNWIRED_SKIP_IDS:
            continue
        if p.get("manual"):
            continue
        if p.get("ports"):          # 常驻 web 服务(launchd), 非 cron 驱动
            continue
        if not p.get("heartbeat_file"):
            continue
        pdir = os.path.expanduser("~/hermes-workspace/" + pid)
        if not os.path.isdir(pdir):
            continue
        # 目录内是否有可执行 .py 载体
        has_py = False
        try:
            for fn in os.listdir(pdir):
                if fn.endswith(".py"):
                    has_py = True
                    break
        except Exception:
            pass
        if not has_py:
            continue
        # 已接线? id 出现在执行语料即算(cron/脚本/编排器任一引用)
        if pid in corpus or ("/" + pid + "/") in corpus:
            continue
        alerts.append({
            "type": "UNWIRED_PROJECT",
            "job": p.get("name", pid), "id": pid,
            "detail": "驾驶舱卡片在线且有可跑脚本, 但无自己的 cron 也未被任何编排器调用"
                      "=静默从不执行的僵尸能力(该接线或该下线)",
        })
    return alerts


def analyze(now=None):
    if now is None:
        now = datetime.now(timezone.utc)
    with open(JOBS_PATH) as f:
        data = json.load(f)
    alerts = []
    for j in data.get("jobs", []):
        if not j.get("enabled", True):
            # 4) PAUSED_STALE: enabled=false 但已暂停超过 PAUSED_STALE_DAYS 天 =
            #    「被静默关掉却没人处理」的僵尸 job。根因盲区(2026-07-02 创新引擎实测):
            #    本看门狗此前对所有 disabled job 直接 continue → 一个项目的 cron 被暂停后
            #    永远不会被任何机制提醒, 而它的驾驶舱卡片仍显示为『活着的项目』(如
            #    quality-compounder 暂停 11d / call-alpha-tracker 暂停 9d, 卡片照常在线)。
            #    快速的临时暂停(几天内会重开)不该报; 只抓「忘了处理」的长期暂停。
            paused_at = parse_dt(j.get("paused_at"))
            if paused_at is not None:
                pa = paused_at if paused_at.tzinfo else paused_at.replace(tzinfo=timezone.utc)
                paused_days = (now - pa).total_seconds() / 86400
                if paused_days > PAUSED_STALE_DAYS:
                    alerts.append({
                        "type": "PAUSED_STALE",
                        "job": j.get("name", "?"), "id": j.get("id", "?"),
                        "paused_at": j.get("paused_at"),
                        "paused_days": round(paused_days, 1),
                        "detail": "cron 已长期暂停但未处理(重开或删除); 若驾驶舱仍有其项目卡片则显示为『活着』=僵尸",
                    })
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
    # 5) UNWIRED_PROJECT: 卡片在线+有脚本但无 cron 也无编排器调用=静默僵尸能力
    try:
        alerts.extend(unwired_projects(now))
    except Exception:
        pass  # 治理型检查异常绝不影响主 cron 健康告警
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
                elif a["type"] == "PAUSED_STALE":
                    line = f"  [PAUSED_STALE] {a['job']} → 已暂停 {a.get('paused_days')}天未处理 (paused_at={a.get('paused_at')})"
                elif a["type"] == "UNWIRED_PROJECT":
                    line = f"  [UNWIRED_PROJECT] {a['job']} (id={a.get('id')}) → {a.get('detail')}"
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
