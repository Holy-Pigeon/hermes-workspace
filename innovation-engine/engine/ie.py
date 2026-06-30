#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
创新引擎 CLI（ie.py）—— idea 登记/状态流转的唯一合法入口。

设计目标：根因修复「正文喊拍板、状态却标 done」的错配。
机制：LLM 永远无权直接指定状态 emoji。状态位是「风险标志」的纯函数推导结果。
      凡带不可逆标志（动实盘/挂改删cron/删数据/不可逆方向）→ 强制 💡proposed。
      LLM 想把需拍板的事标成 ✅done —— 脚本直接拒绝、退出码非0。
      坏状态在机制层无法表达，不靠 prompt 自觉、不靠事后监控。

所有对 ideas_log.md 的写入都必须经过本脚本，LLM 禁止手写/手改 markdown。

用法见底部 _usage()，或 `ie.py help`。
用 /usr/bin/python3 跑（仅 stdlib）。
"""
import sys, os, re, json, datetime, argparse, shutil, hashlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "ideas_log.md")
REVIEWS = os.path.join(ROOT, "reviews.json")
BACKUP_DIR = os.path.join(ROOT, "engine", ".backups")
# 驾驶舱项目清单（新建项目须同步到这里，否则监控平台看不到）
WORKSPACE = os.path.dirname(ROOT)
PROJECTS_JSON = os.path.join(WORKSPACE, "dashboard", "projects.json")

# idea 唯一键的单一权威实现（与 dashboard/app.py 共用同一模块，根除口径分裂）
sys.path.insert(0, os.path.join(WORKSPACE, "shared"))
from idea_hash import compute_idea_id

# ── 状态字典：emoji ↔ 名称（与 dashboard/app.py parse_ideas 解析口径一致）──
EMOJI = {
    "proposed": "💡proposed",
    "building": "🛠building",
    "done":     "✅done",
    "parked":   "❄️parked",
    "rejected": "❌rejected",
}
NAME_BY_EMOJI = {v: k for k, v in EMOJI.items()}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}")

# 不可逆风险标志 → 命中任意一个，状态强制 proposed
IRREVERSIBLE_FLAGS = [
    "touches_real_money",   # 动真金白银/实盘账户
    "touches_cron",         # 挂/改/删 cron（改变系统自动行为节奏）
    "deletes_data",         # 删数据
    "irreversible",         # 其它不可逆方向调整
]


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


_BACKUP_KEEP = 5  # SOUL纪律: git才是回退机制, .backups仅留极小滚动窗口做单次写前崩溃保护, 不做归档


def _backup():
    # 写前安全副本(防in-place改写中途崩溃), 但只保留最近 _BACKUP_KEEP 份滚动窗口。
    # 不再无限增长成「手工备份归档」——那是 git 的职责(SOUL: git即备份, 不留.bak堆积)。
    os.makedirs(BACKUP_DIR, exist_ok=True)
    if os.path.exists(LOG):
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(LOG, os.path.join(BACKUP_DIR, f"ideas_log.{stamp}.md"))
    # 滚动清理: 仅保留最近 _BACKUP_KEEP 份
    try:
        snaps = sorted(
            f for f in os.listdir(BACKUP_DIR)
            if f.startswith("ideas_log.") and f.endswith(".md")
        )
        for stale in snaps[:-_BACKUP_KEEP]:
            os.remove(os.path.join(BACKUP_DIR, stale))
    except OSError:
        pass


def _read_lines():
    with open(LOG, "r", encoding="utf-8") as f:
        return f.read().splitlines()


def _write_lines(lines):
    with open(LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def idea_id(ts, title):
    """idea 唯一键 = 日期::sha1(日期::标题)[:12]。
    实现已收口到 shared/idea_hash.py(与 dashboard/app.py 共用),本函数仅转调,
    保留同名薄包装以兼容本文件所有既有调用点。改算法只改共享模块一处。"""
    return compute_idea_id(ts, title)


def parse_records(lines):
    """返回 [(行号, dict)]，dict 含 ts/status/title/category/originator/reversibility/link/raw"""
    out = []
    for i, ln in enumerate(lines):
        if not DATE_RE.match(ln):
            continue
        parts = [p.strip() for p in ln.split("|")]
        if len(parts) < 3:
            continue
        status_raw = parts[1]
        status = NAME_BY_EMOJI.get(status_raw, "unknown")
        # 容错：emoji 可能带前后缀
        if status == "unknown":
            for emo, nm in NAME_BY_EMOJI.items():
                if emo in status_raw:
                    status = nm
                    break
        out.append((i, {
            "ts": parts[0],
            "status": status,
            "status_raw": status_raw,
            "title": parts[2] if len(parts) > 2 else "",
            "category": parts[3] if len(parts) > 3 else "",
            "originator": parts[4] if len(parts) > 4 else "",
            "reversibility": parts[5] if len(parts) > 5 else "",
            "link": parts[6] if len(parts) > 6 else "",
            "raw": ln,
        }))
    return out


# ─────────────────────────── derive ───────────────────────────
def derive_status(flags, done, building):
    """状态位的纯函数推导 —— 这是根因修复的核心。
    - 命中任意不可逆标志 → 强制 proposed（且若调用方妄图标 done/building，报错）
    - 否则可逆：--done → done；默认 → building
    返回 (status_name, error_or_None)
    """
    irreversible_hit = [f for f in IRREVERSIBLE_FLAGS if flags.get(f)]
    if irreversible_hit:
        if done or building:
            return None, (
                f"拒绝：该 idea 命中不可逆标志 {irreversible_hit}，必须是 💡proposed 等用户拍板，"
                f"不允许标 {'done' if done else 'building'}。这正是要根除的错配。"
            )
        return "proposed", None
    # 可逆
    if done:
        return "done", None
    return "building", None


# ─────────────────────────── add ───────────────────────────
def cmd_add(args):
    flags = {f: getattr(args, f) for f in IRREVERSIBLE_FLAGS}
    status, err = derive_status(flags, args.done, args.building)
    if err:
        print(err, file=sys.stderr)
        return 2
    ts = _now()
    title = args.title.strip().replace("|", "/")  # 标题里的竖线会破坏列解析
    category = (args.category or "未分类").replace("|", "/")
    originator = (args.originator or "创新引擎").replace("|", "/")
    reversibility = (args.reversibility or ("可逆" if status != "proposed" else "需拍板")).replace("|", "/")
    link = (args.link or "").replace("|", "/")
    row = f"{ts} | {EMOJI[status]} | {title} | {category} | {originator} | {reversibility} | {link}"

    lines = _read_lines()
    # 插到 '## Idea 列表' 标题后第一条（最新在最上）
    hdr = next((i for i, l in enumerate(lines) if l.strip() == "## Idea 列表"), None)
    if hdr is None:
        print("错误：ideas_log.md 缺少 '## Idea 列表' 锚点", file=sys.stderr)
        return 3
    ins = hdr + 1
    while ins < len(lines) and lines[ins].strip() == "":
        ins += 1
    _backup()
    new = lines[:ins] + [row] + lines[ins:]
    _write_lines(new)
    iid = idea_id(ts, title)
    print(json.dumps({"ok": True, "status": EMOJI[status], "idea_id": iid,
                      "needs_approval": status == "proposed"}, ensure_ascii=False))
    return 0


# ─────────────────────────── transition ───────────────────────────
def _find_record(records, target_id):
    for ln_no, r in records:
        if idea_id(r["ts"], r["title"]) == target_id:
            return ln_no, r
        # 宽松匹配：target_id 的标题片段是该记录标题前缀
        if "::" in target_id:
            t_ts, t_title = target_id.split("::", 1)
            if r["ts"] == t_ts and r["title"].startswith(t_title[:30]):
                return ln_no, r
    return None, None


def cmd_transition(args):
    """可逆事项 building→done 等合法流转。
    安全阀：禁止把 proposed 直接 transition 成 done/building —— proposed 只能由 review 流转。
    """
    new_status = args.to
    if new_status not in EMOJI:
        print(f"未知状态 {new_status}，合法：{list(EMOJI)}", file=sys.stderr)
        return 2
    lines = _read_lines()
    records = parse_records(lines)
    ln_no, r = _find_record(records, args.id)
    if ln_no is None:
        print(f"未找到 idea_id={args.id}", file=sys.stderr)
        return 3
    if r["status"] == "proposed" and not args.via_review:
        print(f"拒绝：proposed 状态只能经 review 流转（approve/reject/refine），"
              f"不允许直接 transition。idea={args.id}", file=sys.stderr)
        return 4
    parts = [p.strip() for p in lines[ln_no].split("|")]
    parts[1] = EMOJI[new_status]
    _backup()
    lines[ln_no] = " | ".join(parts)
    _write_lines(lines)
    print(json.dumps({"ok": True, "from": r["status"], "to": new_status,
                      "title": r["title"][:50]}, ensure_ascii=False))
    return 0


# ─────────────────────────── review ───────────────────────────
def cmd_review(args):
    """确定性处理 reviews.json 中 processed:false 的拍板，替代 LLM 手改 markdown。
    approve: proposed→building ；reject: →rejected ；refine: 原条目→parked（迭代版由后续 add 追加）
    """
    if not os.path.exists(REVIEWS):
        print(json.dumps({"ok": True, "processed": 0, "note": "无 reviews.json"}, ensure_ascii=False))
        return 0
    with open(REVIEWS, "r", encoding="utf-8") as f:
        reviews = json.load(f)
    lines = _read_lines()
    records = parse_records(lines)
    results = []
    changed = False
    for rv in reviews:
        if rv.get("processed"):
            continue
        action = rv.get("action")
        target = rv.get("idea_id", "")
        ln_no, r = _find_record(records, target)
        if ln_no is None:
            results.append({"idea_id": target, "result": "NOT_FOUND"})
            continue
        target_status = {"approve": "building", "reject": "rejected", "refine": "parked"}.get(action)
        if not target_status:
            results.append({"idea_id": target, "result": f"UNKNOWN_ACTION:{action}"})
            continue
        parts = [p.strip() for p in lines[ln_no].split("|")]
        parts[1] = EMOJI[target_status]
        lines[ln_no] = " | ".join(parts)
        rv["processed"] = True
        changed = True
        results.append({"idea_id": target[:50], "action": action,
                        "from": r["status"], "to": target_status,
                        "comment": rv.get("comment", "")})
        # 刷新 records（行内容变了，行号不变）
        records = parse_records(lines)
    if changed:
        _backup()
        _write_lines(lines)
        with open(REVIEWS, "w", encoding="utf-8") as f:
            json.dump(reviews, f, ensure_ascii=False, indent=2)
    print(json.dumps({"ok": True, "processed": len([x for x in results if x.get('action')]),
                      "results": results}, ensure_ascii=False, indent=2))
    return 0


# ─────────────────────────── lint ───────────────────────────
def cmd_lint(args):
    """不变式校验门（CI gate）。结构性错误 → 退出码非0。
    1. 每条记录列数>=7
    2. 状态 emoji 必须可识别（无 unknown）
    3. （警告）历史遗留：正文含拍板关键词但状态非 proposed 且未结案
    """
    lines = _read_lines()
    records = parse_records(lines)
    errors, warns = [], []
    KW = ["待你拍板", "待用户拍板", "需你拍板", "需用户拍板", "留给用户拍板", "留用户拍板", "留拍板", "需拍板"]
    OPEN = ("proposed", "done", "rejected", "parked")  # 已结案或已正确待拍板，不再告警
    for ln_no, r in records:
        ncol = len(r["raw"].split("|"))
        if ncol < 7:
            errors.append(f"L{ln_no+1}: 列数={ncol}<7 «{r['title'][:30]}»")
        if r["status"] == "unknown":
            errors.append(f"L{ln_no+1}: 状态无法识别 «{r['status_raw']}» «{r['title'][:30]}»")
        body = r["title"]
        if any(k in body for k in KW) and r["status"] not in OPEN:
            warns.append(f"L{ln_no+1}: 正文含拍板词但状态={r['status']} «{r['title'][:40]}»")
        # 结构性信号：可逆性列明确标“需拍板/待拍板”却仍是 building = 与正文勾稽矛盾的错配
        # （此前只查正文 prose，漏掉这个最确定的列级信号 → 3 条 building 漏网）
        rev = r.get("reversibility", "")
        if any(k in rev for k in ("拍板",)) and r["status"] == "building":
            warns.append(f"L{ln_no+1}: 可逆性列=「{rev}」却状态=building（应为 proposed） «{r['title'][:40]}»")
    print(json.dumps({
        "records": len(records),
        "errors": errors,
        "warnings": warns,
        "ok": len(errors) == 0,
    }, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


# ─────────────────────────── list ───────────────────────────
def cmd_list(args):
    lines = _read_lines()
    records = parse_records(lines)
    flt = args.status
    rows = [r for _, r in records if (not flt or r["status"] == flt)]
    counts = {}
    for _, r in records:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(json.dumps({"counts": counts, "filter": flt,
                      "items": [{"ts": r["ts"], "status": r["status"], "title": r["title"][:60]}
                                for r in rows[:args.limit]]},
                     ensure_ascii=False, indent=2))
    return 0


# ─────────────────────────── register-project ───────────────────────────
def cmd_register_project(args):
    """把新建项目同步到驾驶舱 projects.json，否则监控平台看不到。
    幂等：同 id 已存在则更新，不重复添加。
    """
    pid = args.id.strip()
    if not pid:
        print("错误：--id 必填", file=sys.stderr)
        return 2
    if not os.path.exists(PROJECTS_JSON):
        print(f"错误：找不到 {PROJECTS_JSON}", file=sys.stderr)
        return 3
    with open(PROJECTS_JSON, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    projects = cfg.setdefault("projects", [])
    card = {
        "id": pid,
        "name": args.name or pid,
        "icon": args.icon or "🧩",
        "desc": args.desc or "",
        "ports": ({"local": args.local_port, "remote": args.remote_port}
                  if args.local_port else None),
        "tags": [t.strip() for t in (args.tags or "脚本").split(",") if t.strip()],
    }
    if args.health_path:
        card["health_path"] = args.health_path
    if args.heartbeat_file:
        card["heartbeat_file"] = args.heartbeat_file
    # 幂等：同 id 更新
    existing = next((i for i, x in enumerate(projects) if x.get("id") == pid), None)
    action = "updated" if existing is not None else "added"
    if existing is not None:
        projects[existing] = card
    else:
        projects.append(card)
    with open(PROJECTS_JSON, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps({"ok": True, "action": action, "id": pid,
                      "total_projects": len(projects)}, ensure_ascii=False))
    return 0


# ─────────────────────────── deregister-project ───────────────────────────
def cmd_deregister_project(args):
    """从驾驶舱 projects.json 移除一个项目卡片（退场/下线/被拒项目的治理出口）。
    根因修复：register-project 让注册表只增不减，被拒/退场项目的卡片只能靠手改 json 清，
    与『所有登记走脚本、禁止手改』的纪律自相矛盾。本动作让退场也有确定性脚本路径。
    幂等：id 不存在则报 not_found（退出码非0），存在则移除。只动 projects.json，不碰项目目录文件。
    """
    pid = args.id.strip()
    if not pid:
        print("错误：--id 必填", file=sys.stderr)
        return 2
    if not os.path.exists(PROJECTS_JSON):
        print(f"错误：找不到 {PROJECTS_JSON}", file=sys.stderr)
        return 3
    with open(PROJECTS_JSON, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    projects = cfg.setdefault("projects", [])
    idx = next((i for i, x in enumerate(projects) if x.get("id") == pid), None)
    if idx is None:
        print(json.dumps({"ok": False, "result": "NOT_FOUND", "id": pid,
                          "total_projects": len(projects)}, ensure_ascii=False), file=sys.stderr)
        return 4
    removed = projects.pop(idx)
    with open(PROJECTS_JSON, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps({"ok": True, "action": "removed", "id": pid,
                      "name": removed.get("name", ""), "total_projects": len(projects)},
                     ensure_ascii=False))
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="ie.py", description="创新引擎 idea 登记唯一入口")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="登记新 idea（状态由风险标志自动推导）")
    a.add_argument("title", help="一句话标题/正文")
    a.add_argument("--category", default="")
    a.add_argument("--originator", default="创新引擎")
    a.add_argument("--reversibility", default="")
    a.add_argument("--link", default="")
    a.add_argument("--done", action="store_true", help="可逆且本轮已完成 → ✅done")
    a.add_argument("--building", action="store_true", help="可逆进行中 → 🛠building（默认）")
    a.add_argument("--touches-real-money", dest="touches_real_money", action="store_true")
    a.add_argument("--touches-cron", dest="touches_cron", action="store_true")
    a.add_argument("--deletes-data", dest="deletes_data", action="store_true")
    a.add_argument("--irreversible", action="store_true")
    a.set_defaults(func=cmd_add)

    t = sub.add_parser("transition", help="可逆事项状态流转（building→done 等）")
    t.add_argument("--id", required=True, help="idea_id（日期::标题前40字）")
    t.add_argument("--to", required=True, help="目标状态名")
    t.add_argument("--via-review", dest="via_review", action="store_true", help="内部用，普通调用勿加")
    t.set_defaults(func=cmd_transition)

    r = sub.add_parser("review", help="确定性处理 reviews.json 拍板")
    r.set_defaults(func=cmd_review)

    l = sub.add_parser("lint", help="不变式校验门")
    l.set_defaults(func=cmd_lint)

    ls = sub.add_parser("list", help="列出 idea")
    ls.add_argument("--status", default="")
    ls.add_argument("--limit", type=int, default=30)
    ls.set_defaults(func=cmd_list)

    rp = sub.add_parser("register-project", help="把新建项目同步到驾驶舱 projects.json")
    rp.add_argument("--id", required=True, help="项目唯一 id（短横线小写，如 stock-discovery）")
    rp.add_argument("--name", default="", help="显示名")
    rp.add_argument("--icon", default="", help="emoji 图标，默认 🧩")
    rp.add_argument("--desc", default="", help="一句话描述")
    rp.add_argument("--tags", default="", help="逗号分隔标签，默认 脚本")
    rp.add_argument("--heartbeat-file", dest="heartbeat_file", default="",
                    help="判在线的心跳文件/目录（脚本型项目指其输出目录或日志，mtime 新鲜=在线）")
    rp.add_argument("--health-path", dest="health_path", default="",
                    help="有 web 服务时的健康检查路径，如 /api/status")
    rp.add_argument("--local-port", dest="local_port", type=int, default=None)
    rp.add_argument("--remote-port", dest="remote_port", type=int, default=None)
    rp.set_defaults(func=cmd_register_project)

    dp = sub.add_parser("deregister-project", help="从驾驶舱移除项目卡片（退场/被拒项目治理出口）")
    dp.add_argument("--id", required=True, help="要移除的项目 id")
    dp.set_defaults(func=cmd_deregister_project)
    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
