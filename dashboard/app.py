#!/usr/bin/env python3
"""
价值雷达 Web 服务
=====================
port 5051 | frpc → 6011
两大模块：
1. Cron 雷达：所有定时任务状态、最近输出、项目评估记录（从 ideas_log.md 读）
2. 系统监控：CPU / 内存 / 磁盘 / 网络 / 进程等实时指标
"""
import os, sys, json, glob, re, datetime, subprocess, urllib.request, urllib.error, hashlib, hmac, secrets, time
from pathlib import Path
from flask import Flask, jsonify, send_from_directory, request, session, redirect, Response
import psutil

HERMES_HOME   = Path.home() / ".hermes"
JOBS_JSON     = HERMES_HOME / "cron" / "jobs.json"
OUTPUT_DIR    = HERMES_HOME / "cron" / "output"
IDEAS_LOG     = Path.home() / "hermes-workspace" / "innovation-engine" / "ideas_log.md"
REVIEWS_FILE  = Path.home() / "hermes-workspace" / "innovation-engine" / "reviews.json"
PROJECTS_FILE = Path(__file__).parent / "projects.json"
STATIC        = Path(__file__).parent / "static2"

# idea 唯一键的单一权威实现（与 innovation-engine/engine/ie.py 共用同一模块，根除口径分裂）
sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))
from idea_hash import compute_idea_id

HEARTBEAT_FRESH_SECONDS = 25 * 3600  # 心跳文件 25 小时内更新过视为"在线"
HEALTH_CHECK_TIMEOUT_S  = 1.0

app = Flask(__name__, static_folder=str(STATIC))

# ── 登录鉴权 ─────────────────────────────────────────────────────────────────
# 该面板经 frpc 暴露到公网(1.12.235.152:6011)，必须登录才能访问。
# 密码从环境变量 DASHBOARD_PASSWORD 读取(不硬编码、不进 git)；
# session 密钥从 DASHBOARD_SECRET_KEY 读，未设则每次启动随机生成(重启即登出，可接受)。
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
app.secret_key = os.environ.get("DASHBOARD_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=14),
)
# 失败限速：同一 IP 连续失败计数，超阈值临时锁定，挡暴力破解
_login_fails = {}          # ip -> [fail_count, lock_until_ts]
_LOCK_THRESHOLD = 5        # 连续失败 5 次
_LOCK_SECONDS = 300        # 锁 5 分钟

LOGIN_HTML = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>价值雷达 · 登录</title><style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#080810;color:#e2e2f0;font-family:-apple-system,'SF Pro Display','PingFang SC',sans-serif;
min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.box{width:100%;max-width:360px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.09);
border-radius:18px;padding:36px 28px;backdrop-filter:blur(20px)}
h1{font-size:22px;font-weight:600;margin-bottom:6px;background:linear-gradient(90deg,#818cf8,#34d399);
-webkit-background-clip:text;-webkit-text-fill-color:transparent}
p{color:#7878a0;font-size:13px;margin-bottom:24px}
input{width:100%;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);border-radius:10px;
padding:13px 14px;color:#e2e2f0;font-size:15px;margin-bottom:14px;outline:none}
input:focus{border-color:#818cf8}
button{width:100%;background:#818cf8;color:#080810;border:none;border-radius:10px;padding:13px;
font-size:15px;font-weight:600;cursor:pointer}
button:active{transform:scale(.98)}
.err{color:#f87171;font-size:13px;margin-bottom:14px;min-height:18px}
</style></head><body><div class="box">
<h1>价值雷达</h1><p>合伙人驾驶舱 · 请登录</p>
<form method="post" action="/login">
<div class="err">__ERR__</div>
<input type="password" name="password" placeholder="访问密码" autofocus autocomplete="current-password">
<button type="submit">进入</button>
</form></div></body></html>"""

# 无需登录即可访问的端点
_PUBLIC_PATHS = {"/login", "/healthz"}

def _client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip()

@app.before_request
def _require_login():
    if request.path in _PUBLIC_PATHS:
        return None
    # 未配置密码 => 鉴权关闭(本地开发场景)，但记一条警告头
    if not DASHBOARD_PASSWORD:
        return None
    if session.get("authed"):
        return None
    # 未登录：API 返回 401 JSON，页面跳登录
    if request.path.startswith("/api/"):
        return jsonify({"error": "unauthorized"}), 401
    return redirect("/login")

@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})

@app.route("/login", methods=["GET", "POST"])
def login():
    if not DASHBOARD_PASSWORD:
        return redirect("/")
    ip = _client_ip()
    now = time.time()
    fc = _login_fails.get(ip, [0, 0])
    if request.method == "POST":
        if fc[1] > now:
            return Response(LOGIN_HTML.replace("__ERR__", "尝试过多，请 5 分钟后再试"), mimetype="text/html"), 429
        pw = request.form.get("password", "")
        if hmac.compare_digest(pw, DASHBOARD_PASSWORD):
            session.permanent = True
            session["authed"] = True
            _login_fails.pop(ip, None)
            return redirect("/")
        # 失败
        fc[0] += 1
        if fc[0] >= _LOCK_THRESHOLD:
            fc[1] = now + _LOCK_SECONDS
            fc[0] = 0
        _login_fails[ip] = fc
        return Response(LOGIN_HTML.replace("__ERR__", "密码错误"), mimetype="text/html"), 401
    return Response(LOGIN_HTML.replace("__ERR__", ""), mimetype="text/html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ── Helpers ──────────────────────────────────────────────────────────────────

def read_jobs():
    try:
        d = json.loads(JOBS_JSON.read_text())
        return d.get("jobs", [])
    except Exception:
        return []

def last_output(job_id: str, n_chars=600):
    """读取该 job 最近一次输出文件的末尾内容"""
    d = OUTPUT_DIR / job_id
    if not d.exists():
        return None, None
    files = sorted(d.glob("*.md"))
    if not files:
        return None, None
    latest = files[-1]
    try:
        text = latest.read_text(errors="replace")
        # 截取末尾，去掉空行
        snippet = text.strip()[-n_chars:] if len(text) > n_chars else text.strip()
        ts = latest.stem  # e.g. 2026-06-11_14-37-55
        return ts.replace("_", " ").replace("-", "/", 2).replace("-", ":"), snippet
    except Exception:
        return None, None

def _split_title_desc(raw_title: str):
    """idea 录入格式不统一：有的把完整描述塞在标题列（含 **问题**/**根因** 等正文），
    有的标题列只放简短标题、描述在 note 列。本函数把标题列拆成
    (短标题, 完整描述)，让面板对两种格式都鲁棒，不必回改 80+ 条历史数据。

    拆分策略：
    - 找第一个正文标记（**xxx**、句号、冒号 等）作为短标题与正文的边界；
    - 找不到就用前 N 字当短标题；
    - 完整描述 = 整个标题列原文（保真，不丢信息）。
    """
    t = (raw_title or "").strip()
    if not t:
        return "", ""
    import re as _re
    # 候选边界：① 第一个 markdown 粗体标记 **xxx**  ② 首个强分隔(句号/冒号)在 ≤60 字处
    # 取更靠前的那个作为短标题的截断点，避免短标题里塞进大段正文
    bounds = []
    m = _re.search(r"\*\*", t)
    if m and m.start() > 0:
        bounds.append(m.start())
    for sep in ("。", "：", ":", "；"):
        idx = t.find(sep)
        if 0 < idx <= 60:
            bounds.append(idx)
    if bounds:
        short = t[:min(bounds)].strip(" ：:，,。.；-—")
    else:
        short = t[:50].strip()
    if not short:
        short = t[:50]
    return short, t


def _shorten(text: str, limit: int = 80) -> str:
    """列表展示用：截断到 limit 字（含省略号），超出加省略号。原文保真，仅展示层截断。"""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    body = limit - 1            # 给省略号留 1 字，保证结果总长 ≤ limit
    cut = text[:body]
    for sep in ("。", "；", "，", "、", " ", "："):
        idx = cut.rfind(sep)
        if idx >= body * 0.6:   # 切点不能太靠前
            return cut[:idx + 1].rstrip("，、：；") + "…"
    return cut + "…"


def _idea_bucket(category: str) -> str:
    """把细碎的多级分类（如 '研究型alpha·新数据源·南向资金'）归并成顶层桶。
    取第一个分隔符（· / ／ /）之前的部分。空则归 '未分类'。"""
    cat = (category or "").strip()
    if not cat:
        return "未分类"
    for sep in ("·", "・", "／", "/", " "):
        if sep in cat:
            cat = cat.split(sep)[0].strip()
            break
    return cat or "未分类"


def parse_ideas():
    """从 ideas_log.md 解析 idea 条目"""
    if not IDEAS_LOG.exists():
        return []
    lines = IDEAS_LOG.read_text().splitlines()
    items = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("`") or line.startswith("本文件"):
            continue
        # 格式: YYYY-MM-DD [HH:MM] | 状态emoji | 标题 | 类别 | 发起人 | 可逆性 | 备注
        if "|" in line and re.match(r"\d{4}-\d{2}-\d{2}", line):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3:
                status_raw = parts[1] if len(parts) > 1 else ""
                status = "building"  if "🛠" in status_raw else \
                         "proposed"  if "💡" in status_raw else \
                         "done"      if "✅" in status_raw else \
                         "parked"    if "❄️" in status_raw else \
                         "rejected"  if "❌" in status_raw else "unknown"
                raw_title = parts[2] if len(parts) > 2 else ""
                note_col  = parts[5] if len(parts) > 5 else ""   # 可逆性列
                desc_col  = parts[6] if len(parts) > 6 else ""   # 备注/完整描述列
                short_title, title_full = _split_title_desc(raw_title)
                # 完整描述：备注列(parts[6])非空优先用它；否则用标题列完整原文
                full_desc = desc_col.strip() if desc_col.strip() else title_full
                # 唯一键：实现已收口到 shared/idea_hash.py(与 ie.py 共用),
                # 日期::sha1(日期::标题)[:12],纯十六进制,免疫标题里所有特殊字符。
                items.append({
                    "id":       compute_idea_id(parts[0], raw_title),   # date::短哈希(免疫所有特殊字符)
                    "date":     parts[0],
                    "status":   status,
                    "status_raw": status_raw,
                    "title":    title_full,                        # 完整标题列原文(保真)
                    "title_short": _shorten(short_title, 100),     # 短标题(智能拆分,不再硬截长正文)
                    "desc":     full_desc,                          # 完整描述(卡片正文+详情共用)
                    "category": parts[3] if len(parts) > 3 else "",
                    "bucket":   _idea_bucket(parts[3] if len(parts) > 3 else ""),
                    "author":   parts[4] if len(parts) > 4 else "",
                    "note":     note_col,
                })
    return items

# ── API ──────────────────────────────────────────────────────────────────────

@app.route("/api/cron/jobs")
def api_cron_jobs():
    jobs = read_jobs()
    result = []
    for j in jobs:
        ts, snippet = last_output(j["id"])
        result.append({
            "id":           j["id"],
            "name":         j["name"],
            "schedule":     j.get("schedule_display") or j.get("schedule", {}).get("display", ""),
            "enabled":      j.get("enabled", True),
            "state":        j.get("state", ""),
            "last_run_at":  j.get("last_run_at"),
            "last_status":  j.get("last_status"),
            "next_run_at":  j.get("next_run_at"),
            "completed":    j.get("repeat", {}).get("completed", 0) if isinstance(j.get("repeat"), dict) else 0,
            "deliver":      j.get("deliver", ""),
            "no_agent":     j.get("no_agent", False),
            "last_output_ts":   ts,
            "last_output_snippet": snippet,
        })
    return jsonify(result)

@app.route("/api/cron/output/<job_id>")
def api_cron_output(job_id):
    d = OUTPUT_DIR / job_id
    if not d.exists():
        return jsonify({"files": [], "latest": None})
    files = sorted(d.glob("*.md"), reverse=True)
    try:
        latest_text = files[0].read_text(errors="replace") if files else ""
    except Exception:
        latest_text = ""
    return jsonify({
        "files": [f.name for f in files[:20]],
        "latest": latest_text[:4000],
    })

@app.route("/api/ideas")
def api_ideas():
    """支持分面过滤 + 分页。
    query params:
      status   — building|proposed|done|parked|rejected|unknown（逗号分隔多选）
      bucket   — 顶层分类桶（逗号分隔多选）
      q        — 标题/备注关键词
      page     — 1-based，默认 1
      page_size— 默认 20
    返回 {items, total, page, page_size, has_more, facets:{status:{},bucket:{}}}
    无任何分页/过滤参数时退化为返回全部（向后兼容）。
    """
    all_items = parse_ideas()

    # ── facets：始终基于全集计算，便于前端展示每个筛选项的计数 ──
    status_facet, bucket_facet = {}, {}
    for it in all_items:
        status_facet[it["status"]] = status_facet.get(it["status"], 0) + 1
        bucket_facet[it["bucket"]] = bucket_facet.get(it["bucket"], 0) + 1

    # ── 过滤 ──
    status_f = [s for s in request.args.get("status", "").split(",") if s]
    bucket_f = [b for b in request.args.get("bucket", "").split(",") if b]
    q        = request.args.get("q", "").strip().lower()

    items = all_items
    if status_f:
        items = [i for i in items if i["status"] in status_f]
    if bucket_f:
        items = [i for i in items if i["bucket"] in bucket_f]
    if q:
        items = [i for i in items if q in (i["title"] + i["note"]).lower()]

    total = len(items)

    # ── 分页 ──
    has_page = "page" in request.args or "page_size" in request.args
    has_filter = bool(status_f or bucket_f or q)
    if not has_page and not has_filter:
        # 向后兼容：无参数时返回裸数组（老前端仍可用）
        return jsonify(all_items)

    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    try:
        page_size = min(100, max(1, int(request.args.get("page_size", 20))))
    except ValueError:
        page_size = 20

    start = (page - 1) * page_size
    page_items = items[start:start + page_size]

    return jsonify({
        "items":     page_items,
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "has_more":  start + page_size < total,
        "facets":    {"status": status_facet, "bucket": bucket_facet},
    })

@app.route("/api/ideas/review", methods=["POST"])
def api_ideas_review():
    """
    接收前端的审核决定，追加写入 reviews.json
    body: { idea_id, action: "approve"|"refine"|"reject", comment: "" }
    """
    data = request.get_json(silent=True) or {}
    idea_id = data.get("idea_id", "").strip()
    action  = data.get("action", "").strip()
    comment = data.get("comment", "").strip()
    stage   = data.get("stage", "initial").strip()   # initial | progress

    if not idea_id or action not in ("approve", "refine", "reject"):
        return jsonify({"ok": False, "error": "invalid params"}), 400

    # 读已有 reviews
    reviews = []
    if REVIEWS_FILE.exists():
        try:
            reviews = json.loads(REVIEWS_FILE.read_text())
        except Exception:
            reviews = []

    # initial 阶段去重（同一 idea 只保最新），progress 阶段追加
    if stage == "initial":
        reviews = [r for r in reviews if not (r.get("idea_id") == idea_id and r.get("stage","initial") == "initial")]
    reviews.append({
        "idea_id":   idea_id,
        "action":    action,
        "comment":   comment,
        "stage":     stage,
        "ts":        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "processed": False,
    })

    REVIEWS_FILE.write_text(json.dumps(reviews, ensure_ascii=False, indent=2))
    return jsonify({"ok": True})

@app.route("/api/ideas/timeline")
def api_ideas_timeline():
    """返回单个 idea 的完整时间线（提出→审批→执行→完成）"""
    idea_id = request.args.get("idea_id", "").strip()
    ideas = parse_ideas()
    idea = next((i for i in ideas if i["id"] == idea_id), None)

    # 从 reviews.json 取该 idea 所有事件，按时间排序
    reviews = []
    if REVIEWS_FILE.exists():
        try:
            all_reviews = json.loads(REVIEWS_FILE.read_text())
            reviews = [r for r in all_reviews if r.get("idea_id") == idea_id]
            reviews.sort(key=lambda r: r.get("ts", ""))
        except Exception:
            pass

    # 构造 events 列表
    events = []
    if idea:
        events.append({
            "type":   "proposed",
            "ts":     idea["date"],
            "author": idea.get("author", ""),
            "text":   idea.get("note", ""),
        })
    for rv in reviews:
        events.append({
            "type":    "review",
            "ts":      rv.get("ts", ""),
            "author":  rv.get("author", "user"),
            "action":  rv.get("action", ""),
            "comment": rv.get("comment", ""),
            "stage":   rv.get("stage", "initial"),
            "processed": rv.get("processed", False),
        })

    return jsonify({"idea": idea, "events": events})

@app.route("/api/ideas/reviews")
def api_ideas_reviews():
    if not REVIEWS_FILE.exists():
        return jsonify([])
    try:
        return jsonify(json.loads(REVIEWS_FILE.read_text()))
    except Exception:
        return jsonify([])

# ── Projects (统一门户) ──────────────────────────────────────────────────────

def _heartbeat_mtime(path_str: str) -> float | None:
    """返回心跳文件/目录的最新 mtime，目录递归取最大值；找不到则 None。"""
    p = Path(os.path.expanduser(path_str))
    if not p.exists():
        return None
    if p.is_file():
        return p.stat().st_mtime
    # 目录：取目录内所有文件中最新的 mtime
    latest = 0.0
    for f in p.rglob("*"):
        if f.is_file():
            try:
                m = f.stat().st_mtime
                if m > latest:
                    latest = m
            except Exception:
                pass
    return latest if latest > 0 else None

def _check_health_http(port: int, health_path: str) -> bool:
    url = f"http://127.0.0.1:{port}{health_path or '/'}"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=HEALTH_CHECK_TIMEOUT_S) as resp:
            return 200 <= resp.status < 500
    except Exception:
        return False

_PROJECT_RUNTIME_CACHE = {}   # key -> (expire_ts, result_dict)
PROJECT_RUNTIME_TTL_S  = 8.0  # 健康探测结果缓存 8 秒，避免频繁筛选反复探活多个端口

def _project_runtime(p: dict) -> dict:
    """返回 {'online': bool, 'last_seen': 'YYYY-MM-DD HH:MM:SS' | None}，带 8s 缓存。"""
    key = p.get("id") or p.get("name") or json.dumps(p, sort_keys=True)
    now = datetime.datetime.now().timestamp()
    cached = _PROJECT_RUNTIME_CACHE.get(key)
    if cached and cached[0] > now:
        return cached[1]
    result = _project_runtime_uncached(p)
    _PROJECT_RUNTIME_CACHE[key] = (now + PROJECT_RUNTIME_TTL_S, result)
    return result

def _project_runtime_uncached(p: dict) -> dict:
    ports = p.get("ports") or {}
    local_port = ports.get("local")
    if local_port:
        if _check_health_http(int(local_port), p.get("health_path", "/")):
            return {
                "online": True,
                "last_seen": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
    hb = p.get("heartbeat_file")
    if hb:
        mtime = _heartbeat_mtime(hb)
        if mtime is not None:
            # 每项目可声明 freshness_hours 覆盖全局 25h 阈值。
            # 根因修复(2026-06-18): 全局单一 25h 阈值对周度/按需库类项目天然误判——
            # 周度 cron 项目必然有 ~6/7 时间超过 25h 却完全健康, 历次只换心跳锚点
            # 治不了本(L13/L24/L31), 真正的修复是让阈值随 cadence 自适应。
            try:
                _fh_raw = p.get("freshness_hours")
                fh = float(_fh_raw) if _fh_raw else None
            except (TypeError, ValueError):
                fh = None
            threshold = fh * 3600 if fh else HEARTBEAT_FRESH_SECONDS
            fresh = (datetime.datetime.now().timestamp() - mtime) < threshold
            return {
                "online": bool(fresh),
                "last_seen": datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
            }
    return {"online": False, "last_seen": None}

@app.route("/api/projects")
def api_projects():
    """项目门户。支持 tag / online 过滤 + 分页（11 个项目量小，但统一信封 + 分面）。
    query params:
      tag      — 标签（逗号分隔多选）
      online   — '1' 只看在线 / '0' 只看离线
      page, page_size
    无过滤/分页参数时返回 {projects:[...]}（向后兼容老前端）。
    """
    if not PROJECTS_FILE.exists():
        return jsonify({"projects": []})
    try:
        config = json.loads(PROJECTS_FILE.read_text())
    except Exception as e:
        return jsonify({"projects": [], "error": f"projects.json parse error: {e}"}), 500

    enriched = [{**p, **_project_runtime(p)} for p in config.get("projects", [])]

    # facets
    tag_facet = {}
    online_count = 0
    for p in enriched:
        for t in (p.get("tags") or []):
            tag_facet[t] = tag_facet.get(t, 0) + 1
        if p.get("online"):
            online_count += 1

    # filters
    tag_f    = [t for t in request.args.get("tag", "").split(",") if t]
    online_f = request.args.get("online", "")

    items = enriched
    if tag_f:
        items = [p for p in items if set(tag_f) & set(p.get("tags") or [])]
    if online_f in ("0", "1"):
        want = online_f == "1"
        items = [p for p in items if bool(p.get("online")) == want]

    has_page   = "page" in request.args or "page_size" in request.args
    has_filter = bool(tag_f or online_f in ("0", "1"))
    if not has_page and not has_filter:
        # 向后兼容
        return jsonify({"projects": enriched})

    total = len(items)
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    try:
        page_size = min(100, max(1, int(request.args.get("page_size", 20))))
    except ValueError:
        page_size = 20
    start = (page - 1) * page_size

    return jsonify({
        "projects":  items[start:start + page_size],
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "has_more":  start + page_size < total,
        "facets":    {"tag": tag_facet, "online": online_count, "total_projects": len(enriched)},
    })

@app.route("/api/system")
def api_system():
    # CPU
    cpu_pct      = psutil.cpu_percent(interval=0.3)
    cpu_count    = psutil.cpu_count()
    cpu_freq     = psutil.cpu_freq()

    # Memory
    mem          = psutil.virtual_memory()
    swap         = psutil.swap_memory()

    # Disk
    disks = []
    for part in psutil.disk_partitions():
        if "loop" in part.device or part.fstype in ("devtmpfs", "tmpfs", "devfs"):
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "device":     part.device,
                "mountpoint": part.mountpoint,
                "fstype":     part.fstype,
                "total_gb":   round(usage.total / 1e9, 1),
                "used_gb":    round(usage.used  / 1e9, 1),
                "free_gb":    round(usage.free  / 1e9, 1),
                "pct":        usage.percent,
            })
        except Exception:
            pass

    # Network
    net    = psutil.net_io_counters()
    net_if = psutil.net_if_stats()
    active_if = [k for k, v in net_if.items() if v.isup and k != "lo"]

    # Processes (top 8 by CPU)
    procs = []
    for p in sorted(psutil.process_iter(["pid","name","cpu_percent","memory_percent","status"]),
                    key=lambda x: x.info["cpu_percent"] or 0, reverse=True)[:8]:
        procs.append(p.info)

    # Load average
    try:
        load = list(os.getloadavg())
    except Exception:
        load = [0, 0, 0]

    # Uptime
    boot_time = psutil.boot_time()
    uptime_s  = int(datetime.datetime.now().timestamp() - boot_time)
    uptime_h  = uptime_s // 3600
    uptime_m  = (uptime_s % 3600) // 60

    return jsonify({
        "cpu": {
            "percent": cpu_pct,
            "count":   cpu_count,
            "freq_mhz": round(cpu_freq.current, 0) if cpu_freq else None,
            "load_1":  round(load[0], 2),
            "load_5":  round(load[1], 2),
            "load_15": round(load[2], 2),
        },
        "memory": {
            "total_gb":  round(mem.total   / 1e9, 1),
            "used_gb":   round(mem.used    / 1e9, 1),
            "avail_gb":  round(mem.available / 1e9, 1),
            "pct":       mem.percent,
            "swap_total_gb": round(swap.total / 1e9, 1),
            "swap_used_gb":  round(swap.used  / 1e9, 1),
            "swap_pct":      swap.percent,
        },
        "disks": disks,
        "network": {
            "bytes_sent_gb":  round(net.bytes_sent / 1e9, 2),
            "bytes_recv_gb":  round(net.bytes_recv / 1e9, 2),
            "active_if":      active_if,
        },
        "processes": procs,
        "uptime":  f"{uptime_h}h {uptime_m}m",
        "boot_time": datetime.datetime.fromtimestamp(boot_time).strftime("%Y-%m-%d %H:%M"),
        "now":     datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

# ── StockChoose 选股池 ────────────────────────────────────────────────────────

def _sc_conn():
    """连本地 PostgreSQL stockchoose 库（只读用途）。"""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    conn = psycopg2.connect(dbname="stockchoose", user="postgres", host="localhost",
                            connect_timeout=3)
    return conn, RealDictCursor

def _num(v):
    """numeric/Decimal → float，None 原样。"""
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return v

@app.route("/api/stockchoose/picks")
def sc_picks():
    """股票池列表。?status=active|all（默认 active）。带论点数/复核数/最近复核动作。"""
    status = request.args.get("status", "active")
    try:
        conn, RDC = _sc_conn()
    except Exception as e:
        return jsonify({"error": f"DB 连接失败: {e}", "picks": []}), 503
    try:
        with conn.cursor(cursor_factory=RDC) as cur:
            # status=all 时按 stock_code 去重：同一代码只显示一条，活跃态(active/watching/research)
            # 优先，否则取最新一条(closed 历史按 selected_date 倒序取最新)。避免同股多条历史记录在
            # 「全部」页签里并排显示造成"重复"观感。具体某只票的完整历史仍可在详情页查看。
            if status == "all":
                where = ""
                params = ()
                dedup = """
                    AND p.id = (
                        SELECT p2.id FROM stock_picks p2
                        WHERE p2.stock_code = p.stock_code
                        ORDER BY (p2.status IN ('active','watching','research')) DESC,
                                 p2.selected_date DESC, p2.id DESC
                        LIMIT 1
                    )
                """
                where = "WHERE TRUE " + dedup
            else:
                where = "WHERE p.status = %s"
                params = (status,)
            cur.execute(f"""
                SELECT p.id, p.stock_code, p.stock_name, p.market, p.sector,
                       p.selected_date, p.selected_price, p.currency,
                       p.expected_upside_pct, p.target_price, p.conviction_rating,
                       p.score, p.status, p.updated_at,
                       p.gain_since_pick_pct, p.last_mark_price, p.last_mark_date,
                       (SELECT count(*) FROM stock_theses t WHERE t.stock_pick_id = p.id) AS n_thesis,
                       (SELECT count(*) FROM stock_theses t WHERE t.stock_pick_id = p.id AND t.still_valid) AS n_thesis_valid,
                       (SELECT count(*) FROM stock_pick_reviews r WHERE r.stock_pick_id = p.id) AS n_review,
                       (SELECT r.review_date FROM stock_pick_reviews r WHERE r.stock_pick_id = p.id ORDER BY r.review_date DESC LIMIT 1) AS last_review_date,
                       (SELECT r.action FROM stock_pick_reviews r WHERE r.stock_pick_id = p.id ORDER BY r.review_date DESC LIMIT 1) AS last_action,
                       (SELECT r.current_price FROM stock_pick_reviews r WHERE r.stock_pick_id = p.id ORDER BY r.review_date DESC LIMIT 1) AS last_price
                FROM stock_picks p
                {where}
                ORDER BY p.status='active' DESC, p.expected_upside_pct DESC
            """, params)
            rows = cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("selected_price", "expected_upside_pct", "target_price", "score", "last_price",
                      "gain_since_pick_pct", "last_mark_price"):
                d[k] = _num(d.get(k))
            for k in ("selected_date", "last_review_date", "last_mark_date"):
                if d.get(k):
                    d[k] = str(d[k])
            d["updated_at"] = str(d["updated_at"])[:16] if d.get("updated_at") else None
            # 较选入价的当前涨跌幅：优先用主表每日盯市值 gain_since_pick_pct（refresh_pick_marks.py 刷新），
            # 主表无盯市值时回退到最近一次复核价反推（旧逻辑，数据可能陈旧）。
            if d.get("gain_since_pick_pct") is not None:
                d["price_change_since_pick"] = d["gain_since_pick_pct"]
            elif d.get("last_price") and d.get("selected_price"):
                d["price_change_since_pick"] = round((d["last_price"] / d["selected_price"] - 1) * 100, 2)
            else:
                d["price_change_since_pick"] = None
            out.append(d)
        # 汇总
        active = [x for x in out if x["status"] == "active"]
        summary = {
            "total": len(out),
            "active": len(active),
            "avg_expected_upside": round(sum(x["expected_upside_pct"] for x in active) / len(active), 2) if active else None,
        }
        return jsonify({"picks": out, "summary": summary})
    finally:
        conn.close()

@app.route("/api/stockchoose/pick/<int:pick_id>")
def sc_pick_detail(pick_id):
    """单只票全论据 + 复核历史。"""
    try:
        conn, RDC = _sc_conn()
    except Exception as e:
        return jsonify({"error": f"DB 连接失败: {e}"}), 503
    try:
        with conn.cursor(cursor_factory=RDC) as cur:
            cur.execute("SELECT * FROM stock_picks WHERE id = %s", (pick_id,))
            pick = cur.fetchone()
            if not pick:
                return jsonify({"error": "未找到该标的"}), 404
            pick = dict(pick)
            for k in ("selected_price", "expected_upside_pct", "target_price", "target_market_cap", "score",
                      "gain_since_pick_pct", "last_mark_price"):
                pick[k] = _num(pick.get(k))
            for k in ("selected_date", "last_mark_date"):
                if pick.get(k):
                    pick[k] = str(pick[k])
            for k in ("created_at", "updated_at"):
                pick[k] = str(pick[k])[:16] if pick.get(k) else None

            cur.execute("""
                SELECT id, thesis_title, thesis_detail, still_valid, status,
                       key_supporting_data, invalidation_condition, last_checked_date,
                       validity_check_count, last_validation_summary, next_check_due_at
                FROM stock_theses WHERE stock_pick_id = %s ORDER BY id
            """, (pick_id,))
            theses = []
            for t in cur.fetchall():
                t = dict(t)
                for k in ("last_checked_date",):
                    if t.get(k):
                        t[k] = str(t[k])
                t["next_check_due_at"] = str(t["next_check_due_at"])[:16] if t.get("next_check_due_at") else None
                theses.append(t)

            cur.execute("""
                SELECT id, review_date, current_price, price_change_pct, review_summary, action, created_at
                FROM stock_pick_reviews WHERE stock_pick_id = %s ORDER BY review_date DESC, id DESC
            """, (pick_id,))
            reviews = []
            for rv in cur.fetchall():
                rv = dict(rv)
                rv["current_price"] = _num(rv.get("current_price"))
                rv["price_change_pct"] = _num(rv.get("price_change_pct"))
                rv["review_date"] = str(rv["review_date"]) if rv.get("review_date") else None
                rv["created_at"] = str(rv["created_at"])[:16] if rv.get("created_at") else None
                reviews.append(rv)
        return jsonify({"pick": pick, "theses": theses, "reviews": reviews})
    finally:
        conn.close()

@app.route("/api/stockchoose/rules")
def sc_rules():
    """当前规则版本。"""
    try:
        conn, RDC = _sc_conn()
    except Exception as e:
        return jsonify({"error": f"DB 连接失败: {e}", "versions": []}), 503
    try:
        with conn.cursor(cursor_factory=RDC) as cur:
            cur.execute("SELECT version, effective_date, change_summary FROM rule_versions ORDER BY effective_date DESC, id DESC LIMIT 10")
            vs = [{"version": r["version"], "effective_date": str(r["effective_date"]), "change_summary": r["change_summary"]} for r in cur.fetchall()]
        return jsonify({"versions": vs})
    finally:
        conn.close()

# ── Static ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    resp = send_from_directory(str(STATIC), "index.html")
    # 禁止浏览器缓存HTML,确保前端改动立即生效(手机端尤其爱强缓存,曾导致"看着还是旧的/空的")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp

@app.route("/stockchoose")
def stockchoose_page():
    resp = send_from_directory(str(STATIC), "stockchoose.html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp

if __name__ == "__main__":
    # 绑回环：只允许本机/frpc(localIP=127.0.0.1)访问，掐掉局域网直连暴露
    app.run(host="127.0.0.1", port=5051, debug=False)
