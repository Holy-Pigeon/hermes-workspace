#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
akeso_trial_watch.py — 康方生物(09926) AK112/ivonescimab 注册性临床试验监控器 (纯只读)

动机
----
catalyst_check.py 把康方 AK112 关键临床读出明确标注为"非定期, 需单独盯
ClinicalTrials/公司公告" —— 这是全组合里【最大的单一二元催化剂】, 却是唯一
没有任何自动触发器的失效条件。靠人工想起来去翻 ClinicalTrials.gov, 确认偏误
下极易被无限拖延。本工具用 ClinicalTrials.gov v2 API 自动监控:
  1) 一组人工策展的【注册性 Phase 3】NCT(HARMONi 系列等)的状态变化
  2) 任何 ivonescimab Phase3 试验的 lastUpdatePostDate 变化(=注册表被改动, 可能
     是结果发布/状态切换/完成日修订的先兆)
  3) primary completion date 临近预警(数据读出窗口在逼近)

数据诚实
--------
- 数据源: ClinicalTrials.gov 官方 v2 API (一手监管登记表)。注册表 PCD 是【计划/
  预计】完成日, 不是公司公告的拓扑读出日; 真正的 OS/PFS 读出时点以康方港交所
  公告 / 学术会议(ASCO/ESMO/WCLC)为准。本工具只负责"注册表一有风吹草动就喊你
  去核实", 不替代公告。
- 只读: 不下单、不改持仓库。完全可逆。

用法
----
  python3 akeso_trial_watch.py            # 正常运行, 有变化/临近窗口才输出告警
  python3 akeso_trial_watch.py --full     # 打印全部受监控试验当前快照
  python3 akeso_trial_watch.py --init      # 初始化 state(首次, 不喊变化)
"""
import json, sys, os, time, datetime, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(HERE, "akeso_trials", "trial_state.json")
API = "https://clinicaltrials.gov/api/v2/studies"

# 网络韧性: ClinicalTrials.gov 间歇性 SSL EOF / RemoteDisconnected (实测 7/2、7/12
# 均因单发裸调用崩溃 → 整个 cron RUN_ERROR → 全组合最大二元催化剂当天失明)。
# 借鉴 marketdata 的多源重试思路(此处单源, 做指数退避重试兜底瞬时抖动)。
FETCH_RETRIES = 4          # 总尝试次数
FETCH_BACKOFF = 2.0        # 退避基数(秒): 2,4,8...

# 人工策展: 康方 AK112 注册性/关键 Phase3 (会随认知更新; 含简短为何重要)
# 这些是"必盯"列表, 之外再做一次全量 ivonescimab Phase3 扫描兜底。
CURATED = {
    "NCT06396065": "AK112 NSCLC Ph3 (PCD 2025-04, ACTIVE_NOT_RECRUITING — 数据在流, 重点)",
    "NCT05899608": "1L 转移性 NSCLC ivo Ph3 (注册性一线扩展)",
    "NCT05184712": "AK112 NSCLC Ph3 (HARMONi-A 系, 已完成入组)",
    "NCT06928389": "ivo + 多西他赛 晚期 NSCLC Ph3 (2L 联合, PCD 2027-05)",
    "NCT06767514": "1L 高 PD-L1 NSCLC ivo Ph3 (头对头潜力)",
}

# 临近窗口分级(天)
HOT, WARN, WATCH = 30, 90, 180


def fetch(params):
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "akeso-watch/1.0"})
    last_err = None
    for attempt in range(FETCH_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # SSL EOF / RemoteDisconnected / 超时 等瞬时故障
            last_err = e
            if attempt < FETCH_RETRIES - 1:
                time.sleep(FETCH_BACKOFF * (2 ** attempt))
    raise last_err if last_err else RuntimeError("fetch failed with no captured error")


def parse_study(s):
    p = s.get("protocolSection", {})
    idm = p.get("identificationModule", {})
    sm = p.get("statusModule", {})
    dm = p.get("designModule", {})
    return {
        "nct": idm.get("nctId"),
        "title": idm.get("briefTitle", "")[:120],
        "status": sm.get("overallStatus"),
        "phase": ",".join(dm.get("phases", [])),
        "pcd": sm.get("primaryCompletionDateStruct", {}).get("date"),
        "last_update": sm.get("lastUpdatePostDateStruct", {}).get("date"),
    }


def get_all_phase3():
    """全量 ivonescimab Phase3 扫描 (兜底, 抓新增/状态变化)。"""
    out = {}
    data = fetch({
        "query.term": "ivonescimab",
        "filter.advanced": "AREA[Phase]PHASE3",
        "pageSize": 100,
        "fields": "NCTId,BriefTitle,OverallStatus,Phase,PrimaryCompletionDate,LastUpdatePostDate",
    })
    for s in data.get("studies", []):
        rec = parse_study(s)
        if rec["nct"]:
            out[rec["nct"]] = rec
    # 确保策展列表都在(可能有非 ivonescimab 命名/别名漏抓)
    for nct in CURATED:
        if nct not in out:
            try:
                d = fetch({"query.id": nct, "pageSize": 1,
                           "fields": "NCTId,BriefTitle,OverallStatus,Phase,PrimaryCompletionDate,LastUpdatePostDate"})
                for s in d.get("studies", []):
                    rec = parse_study(s)
                    if rec["nct"]:
                        out[rec["nct"]] = rec
            except Exception:
                pass
    return out


def days_until(datestr):
    if not datestr:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            d = datetime.datetime.strptime(datestr, fmt).date()
            return (d - datetime.date.today()).days
        except ValueError:
            continue
    return None


def load_state():
    if os.path.exists(STATE_PATH):
        return json.load(open(STATE_PATH, encoding="utf-8"))
    return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    json.dump(state, open(STATE_PATH, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        current = get_all_phase3()
    except Exception as e:
        print(f"[ERROR] ClinicalTrials.gov API 拉取失败: {e}", file=sys.stderr)
        sys.exit(2)

    prev = load_state()
    alerts = []

    for nct, rec in current.items():
        old = prev.get(nct)
        is_curated = nct in CURATED
        tag = "★必盯" if is_curated else "  扫描"
        # 1) 新增试验
        if old is None and prev:  # prev 非空才算"新增"(避免首次全量刷屏)
            alerts.append(f"[新增试验] {tag} {nct} {rec['status']} | {rec['title']}")
        elif old:
            # 2) 状态变化
            if old.get("status") != rec["status"]:
                alerts.append(
                    f"[状态变化] {tag} {nct}: {old.get('status')} → {rec['status']} | {rec['title']}")
            # 3) 注册表更新(lastUpdate 变化) —— 仅必盯列表喊, 避免噪音
            if is_curated and old.get("last_update") != rec["last_update"]:
                alerts.append(
                    f"[登记表更新] ★必盯 {nct}: lastUpdate {old.get('last_update')} → {rec['last_update']} | {CURATED[nct]} → 去 HKEXnews/官网核实有无结果披露")
            # 4) 完成日修订
            if old.get("pcd") != rec["pcd"]:
                alerts.append(
                    f"[完成日修订] {tag} {nct}: PCD {old.get('pcd')} → {rec['pcd']} | {rec['title']}")

    # 5) 临近 primary completion (仅必盯)
    for nct in CURATED:
        rec = current.get(nct)
        if not rec:
            continue
        d = days_until(rec.get("pcd"))
        if d is None:
            continue
        if -60 <= d <= WATCH:  # 含刚过完成日 60 天内(读出常滞后于 PCD)
            level = "HOT" if d <= HOT else ("WARN" if d <= WARN else "WATCH")
            when = f"距今 {d} 天" if d >= 0 else f"已过 {-d} 天"
            alerts.append(
                f"[完成窗口·{level}] ★必盯 {nct} PCD={rec['pcd']} ({when}) | {CURATED[nct]}")

    if mode == "--full":
        print("=" * 78)
        print(f"康方 AK112 试验快照  |  {datetime.date.today()}  |  {len(current)} 个 Ph3")
        print("=" * 78)
        for nct, rec in sorted(current.items(),
                               key=lambda kv: (kv[0] not in CURATED, kv[1].get('pcd') or 'z')):
            star = "★" if nct in CURATED else " "
            d = days_until(rec.get('pcd'))
            dd = f"{d:>5}d" if d is not None else "  ?  "
            print(f"{star} {nct} | {rec['status']:<22} | PCD {rec['pcd'] or '?':<10} {dd} | upd {rec['last_update'] or '?'}")
            print(f"    {rec['title']}")

    if mode == "--init":
        save_state(current)
        print(f"[init] state 初始化完成: {len(current)} 个试验已登记 → {STATE_PATH}")
        return

    # 输出告警
    if alerts:
        print("=" * 78)
        print(f"康方 AK112 临床监控告警  |  {datetime.date.today()}  |  {len(alerts)} 条")
        print("=" * 78)
        for a in alerts:
            print(" • " + a)
        print("-" * 78)
        print("数据诚实: PCD=注册表【计划】完成日, 非公司公告读出日。真正 OS/PFS 读出以")
        print("康方港交所公告 / ASCO·ESMO·WCLC 为准。本工具只提示去核实, 不替代一手公告。")
    else:
        # --quiet: 无告警时完全不输出(给 --no-agent cron 用, 空 stdout = 静默)
        if mode not in ("--full", "--quiet"):
            print(f"[{datetime.date.today()}] 康方 AK112 监控: 无注册表变化, 无临近读出窗口。静默。")

    # 写回 state(始终更新, 让下次以最新为基线)
    save_state(current)


if __name__ == "__main__":
    main()
