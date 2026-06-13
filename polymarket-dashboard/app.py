"""
Polymarket 全景监控 — Flask 后端
port 5052 | frpc → 6012
"""
import json, threading, time
from pathlib import Path
from datetime import datetime, timezone
from flask import Flask, jsonify, send_from_directory, request

BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "data"
STATIC_DIR  = BASE_DIR / "static"
LATEST_FILE = DATA_DIR / "snapshot_latest.json"
CHANGES_FILE= DATA_DIR / "changes_1h.json"

app = Flask(__name__, static_folder=str(STATIC_DIR))

# ─── background refresh ───────────────────────────────────────────────────────

_last_fetch = 0
_fetch_lock = threading.Lock()

def _do_fetch():
    global _last_fetch
    with _fetch_lock:
        import sys
        sys.path.insert(0, str(BASE_DIR))
        from fetcher import run
        try:
            run()
            _last_fetch = time.time()
        except Exception as e:
            print(f"[fetch error] {e}")

def _bg_fetch():
    """启动时立即 fetch，之后每 30min 一次"""
    _do_fetch()
    while True:
        time.sleep(1800)
        _do_fetch()

# ─── helpers ──────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None

# ─── API ──────────────────────────────────────────────────────────────────────

@app.route("/api/snapshot")
def api_snapshot():
    """完整快照，带可选 category 过滤"""
    cat_filter = request.args.get("category")   # macro | sector | all
    cid_filter = request.args.get("category_id")
    data = _load_json(LATEST_FILE)
    if not data:
        return jsonify({"markets": [], "fetched_at": None, "count": 0})
    markets = data.get("markets", [])
    if cat_filter and cat_filter != "all":
        markets = [m for m in markets if m.get("category") == cat_filter]
    if cid_filter:
        markets = [m for m in markets if m.get("category_id") == cid_filter]
    # 按 volume 降序
    markets.sort(key=lambda m: m.get("volume", 0), reverse=True)
    return jsonify({
        "fetched_at": data.get("fetched_at"),
        "count": len(markets),
        "markets": markets,
    })


@app.route("/api/changes")
def api_changes():
    """1h 变动列表，按 |delta| 降序"""
    data = _load_json(CHANGES_FILE)
    if not data:
        return jsonify({"changes": [], "computed_at": None})
    changes = data.get("changes", [])
    min_delta = float(request.args.get("min_delta", 2))
    changes = [c for c in changes if abs(c.get("delta_pct", 0)) >= min_delta]
    return jsonify(data | {"changes": changes})


@app.route("/api/categories")
def api_categories():
    """所有分类元信息"""
    from categories import CATEGORIES
    return jsonify(CATEGORIES)


@app.route("/api/summary")
def api_summary():
    """顶部卡片：每个宏观分类的 yes_prob 代表值"""
    data = _load_json(LATEST_FILE)
    if not data:
        return jsonify({"cards": []})
    from categories import CATEGORIES, MACRO_IDS, SECTOR_IDS

    # 按 category_id 分组，取 volume 最高的市场作代表
    from collections import defaultdict
    groups = defaultdict(list)
    for m in data.get("markets", []):
        groups[m.get("category_id")].append(m)

    cards = []
    for cat in CATEGORIES:
        cid = cat["id"]
        ms = sorted(groups.get(cid, []), key=lambda m: m.get("volume", 0), reverse=True)
        top = ms[0] if ms else None
        cards.append({
            "id": cid,
            "label": cat["label"],
            "category": cat["category"],
            "subcategory": cat["subcategory"],
            "icon": cat["icon"],
            "description": cat["description"],
            "top_question": top["question"] if top else None,
            "top_prob": top["yes_prob"] if top else None,
            "top_volume": top["volume"] if top else 0,
            "market_count": len(ms),
            "fetched_at": data.get("fetched_at"),
        })
    return jsonify(cards)


# ─── 北极星指标条：精选高成交二元市场 + 24h 变动 ──────────────────────────────
# 区间型市场（market_type=range）一律剔除，杜绝单点极端行权价误导。
# 每个 category_id 取成交量最大的 binary 市场作代表，再全局按优先级/成交量取 top N。
NORTHSTAR_PRIORITY = [
    "us_recession", "fed_rate_cut", "cpi_inflation", "geopolitics",
    "sector_ai", "btc_price", "sector_ipo", "us_china_trade",
]

@app.route("/api/northstar")
def api_northstar():
    data = _load_json(LATEST_FILE)
    if not data:
        return jsonify({"items": [], "fetched_at": None})
    changes = _load_json(CHANGES_FILE) or {}
    delta_map = {c["id"]: c.get("delta_pct") for c in changes.get("changes", [])}

    from collections import defaultdict
    groups = defaultdict(list)
    for m in data.get("markets", []):
        if m.get("market_type") == "range":   # range 市场进区间条，不进北极星
            continue
        if m.get("yes_prob") is None:
            continue
        groups[m.get("category_id")].append(m)

    items = []
    for cid, ms in groups.items():
        ms.sort(key=lambda m: m.get("volume", 0), reverse=True)
        top = ms[0]
        items.append({
            "category_id":   cid,
            "label":         top.get("category_label", cid),
            "icon":          top.get("icon", "📊"),
            "question":      top.get("question", ""),
            "yes_prob":      top.get("yes_prob"),
            "volume":        top.get("volume", 0),
            "volume_24hr":   top.get("volume_24hr", 0),
            "delta_pct":     delta_map.get(top.get("id")),   # None=无历史基准
            "category":      top.get("category", ""),
            "slug":          top.get("slug", ""),
        })

    def sort_key(it):
        try: pr = NORTHSTAR_PRIORITY.index(it["category_id"])
        except ValueError: pr = 999
        return (pr, -it["volume"])
    items.sort(key=sort_key)
    return jsonify({"items": items[:8], "fetched_at": data.get("fetched_at")})


# ─── 区间分布条：按 event 聚合各价格档概率 ───────────────────────────────────
@app.route("/api/ranges")
def api_ranges():
    """返回区间型市场，按 event_id 聚合成一组档位（供 stacked bar 展示）"""
    data = _load_json(LATEST_FILE)
    if not data:
        return jsonify({"groups": [], "fetched_at": None})
    from collections import defaultdict
    ev = defaultdict(list)
    for m in data.get("markets", []):
        if m.get("market_type") != "range":
            continue
        if m.get("yes_prob") is None:
            continue
        ev[m.get("event_id")].append(m)

    groups = []
    for eid, ms in ev.items():
        if len(ms) < 2:   # 单档不算区间
            continue
        ms.sort(key=lambda m: m.get("yes_prob", 0), reverse=True)
        tot_vol = sum(m.get("volume", 0) for m in ms)
        top = ms[0]
        groups.append({
            "event_id":    eid,
            "event_title": top.get("event_title", "") or top.get("question", ""),
            "category_id": top.get("category_id"),
            "category":    top.get("category", ""),
            "label":       top.get("category_label", ""),
            "icon":        top.get("icon", "📊"),
            "volume":      tot_vol,
            "buckets": [
                {"q": m.get("question", ""), "prob": m.get("yes_prob"), "vol": m.get("volume", 0)}
                for m in ms[:8]
            ],
        })
    groups.sort(key=lambda g: g["volume"], reverse=True)
    cat_filter = request.args.get("category")
    if cat_filter and cat_filter != "all":
        groups = [g for g in groups if g["category"] == cat_filter]
    return jsonify({"groups": groups[:12], "fetched_at": data.get("fetched_at")})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """手动触发刷新"""
    t = threading.Thread(target=_do_fetch, daemon=True)
    t.start()
    return jsonify({"status": "started", "ts": datetime.now(timezone.utc).isoformat()})


@app.route("/api/status")
def api_status():
    data = _load_json(LATEST_FILE)
    return jsonify({
        "last_fetch": _last_fetch,
        "last_fetch_iso": datetime.fromtimestamp(_last_fetch, tz=timezone.utc).isoformat() if _last_fetch else None,
        "market_count": data["count"] if data else 0,
        "data_age_s": time.time() - _last_fetch if _last_fetch else None,
    })


# ─── Static ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(str(STATIC_DIR), "index.html")

@app.route("/<path:p>")
def static_file(p):
    return send_from_directory(str(STATIC_DIR), p)


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # 单实例守护: 防止重复启动堆叠 bg_fetch 线程(各自30min轮询Gamma API+
    # 无锁写同一data/目录)。用文件锁(flock)抢占, 抢不到即退出, 绝不再起第二个。
    import fcntl, sys as _sys
    _lock_path = BASE_DIR / ".app.lock"
    _lock_fp = open(_lock_path, "w")
    try:
        fcntl.flock(_lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("[FATAL] 另一个 app.py 实例已在运行(持有 .app.lock), 本次退出避免重复 fetch/写竞争", file=_sys.stderr)
        _sys.exit(1)
    _lock_fp.write(str(__import__("os").getpid()))
    _lock_fp.flush()

    STATIC_DIR.mkdir(exist_ok=True)
    t = threading.Thread(target=_bg_fetch, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5052, debug=False)
