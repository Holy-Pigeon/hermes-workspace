"""
Polymarket 全景监控 — 数据抓取器 v4
关键修复（v3→v4）：
  1. Gamma API 的 ?tag=<slug> 查询参数已失效（返回全站热门=世界杯噪音）。
     正确做法：用 ?tag_id=<数字ID>，实测真过滤。tag_id 池见 TAG_POOL。
  2. urllib 的 SSL 间歇性 EOF（_ssl.c:1081）→ 改用 curl 子进程做数据通路，
     走本地 socks5 代理（境外 API 直连不稳），带重试。
  3. 新增 event 分组（event_id/event_title）+ 区间市场识别（market_type），
     供前端"区间分布条"使用，杜绝单点极端行权价当类目代表的误导。
策略：
  - 遍历干净的 tag_id 池批量拉活跃事件
  - 对每个 market 的 question 做关键词分类（精准 > tag 归属）
  - 无法归类 / 命中 BLOCKLIST 的 market 丢弃（避免体育娱乐噪音）
"""

import json, time, subprocess, sys, re
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
SNAP_DIR = DATA_DIR / "snapshots"
DATA_DIR.mkdir(exist_ok=True)
SNAP_DIR.mkdir(exist_ok=True)

LATEST_FILE  = DATA_DIR / "snapshot_latest.json"
CHANGES_FILE = DATA_DIR / "changes_1h.json"
EVENTS_API   = "https://gamma-api.polymarket.com/events"
PROXY        = "socks5h://127.0.0.1:7897"   # 本地 TUN 代理；境外 API 直连 SSL 不稳

sys.path.insert(0, str(BASE_DIR))
from categories import CATEGORIES

CAT_MAP = {c["id"]: c for c in CATEGORIES}

# ─── 干净 tag_id 池（实测真过滤、挂活跃高成交事件）─────────────────────────────
# 由 events?order=volume 反查热门事件挂的 tag 统计得出，远比 slug 可靠
TAG_POOL: dict[str, int] = {
    "crypto":          21,
    "crypto-prices":   1312,
    "tech":            1401,
    "big-tech":        101999,
    "ai":              439,
    "finance":         120,
    "business":        107,
    "economy":         100328,
    "economic-policy": 101800,
    "fed-rates":       100196,
    "geopolitics":     100265,
    "ipos":            600,
}

# ─── 问题级别关键词分类规则 ───────────────────────────────────────────────────
# 格式：(category_id, [必须包含至少一个], [排除词])，按优先级排列，越精确越靠前
QUESTION_RULES: list[tuple[str, list[str], list[str]]] = [
    # ── 宏观 ──
    ("us_recession",   ["recession", "gdp contraction", "gdp decline", "economic contraction"], []),
    ("fed_rate_cut",   ["fed rate cut", "federal reserve cut", "fomc cut", "rate cut", "fed pivot",
                        "fed lower", "interest rate cut", "rate decrease", "rate cuts in",
                        "how many fed", "fed decision"], ["hike", "raise"]),
    ("fed_rate_hike",  ["fed rate hike", "federal reserve hike", "fomc hike", "rate hike",
                        "interest rate hike", "rate increase", "fed raise"], []),
    ("fed_funds_rate", ["federal funds rate", "ffr ", "fomc rate decision", "fed rate end",
                        "interest rate end of year", "year-end rate"], []),
    ("cpi_inflation",  ["cpi", "inflation rate", "core inflation", "pce", "inflation above",
                        "inflation below", "inflation exceed"], []),
    ("nasdaq_level",   ["nasdaq 20000", "nasdaq 19000", "nasdaq 18000", "nasdaq 17000",
                        "nasdaq 16000", "nasdaq end", "nasdaq year", "nasdaq hit"], []),
    ("sp500_level",    ["s&p 500", "s&p500", "spx ", "sp500", "spy "], []),
    ("btc_price",      ["bitcoin price", "btc price", "btc hit", "bitcoin hit", "btc above",
                        "btc below", "bitcoin above", "bitcoin below", "btc end of",
                        "bitcoin end of", "price will bitcoin", "bitcoin reach"], []),
    ("us_china_trade", ["us china tariff", "china tariff", "us tariff china", "trade war china",
                        "us china trade", "trump tariff china", "tariff rate china"], []),
    ("us_debt_fiscal", ["debt ceiling", "government shutdown", "us default", "us debt",
                        "budget deficit", "continuing resolution", "government funding"], []),
    ("usd_strength",   ["dollar index", "dxy ", "usd vs eur", "usd vs cny", "dollar strengthen",
                        "dollar weaken", "dollar end of year"], []),
    ("geopolitics",    ["ukraine", "taiwan conflict", "iran nuclear", "russia invade",
                        "nato troops", "military clash", "ceasefire", "middle east war",
                        "israel hamas", "north korea nuclear", "iran ", "strait of hormuz",
                        "permanent peace", "putin"], []),

    # ── 行业 ──
    ("sector_nvidia",    ["nvidia", "nvda"], []),
    ("sector_ai",        ["gpt-5", "gpt-6", "gpt5", "openai", "claude", "gemini", "ai model",
                          "ai regulation", "artificial intelligence act", "agi", "ai safety",
                          "anthropic", "llm benchmark", "best ai", "top ai model",
                          "xai", "grok"], []),
    ("sector_semiconductor", ["semiconductor", "tsmc", "chip ban", "export control chip",
                              "amd earnings", "intel earnings", "arm holdings",
                              "chip shortage", "chip act"], []),
    ("sector_mag7",      ["apple", "google", "alphabet", "microsoft", "meta ", "amazon",
                          "mag 7", "mag-7", "magnificent", "largest company", "biggest company",
                          "most valuable company", "market cap by end", "saudi aramco"], ["earnings call only"]),
    ("sector_crypto_reg",["crypto regulation", "bitcoin etf", "ethereum etf", "sec crypto",
                          "stablecoin bill", "crypto bill", "ethereum upgrade",
                          "coinbase", "binance", "sec approve"], []),
    ("btc_price",        ["bitcoin", "btc "], ["world cup", "nba", "nfl"]),  # 二次捕获
    ("sector_crypto_reg",["ethereum", "eth ", "solana", "xrp", "dogecoin", "crypto"], []),  # 加密二次捕获
    ("sector_ev",        ["tesla", "tsla", "ev sales", "electric vehicle", "rivian",
                          "lucid motors", "byd"], []),
    ("sector_energy",    ["oil price", "crude oil", "opec", "brent", "wti price",
                          "natural gas price", "energy price", "oil above", "oil below",
                          "gas price"], []),
    ("sector_pharma",    ["fda approval", "fda approve", "fda reject", "glp-1",
                          "ozempic", "wegovy", "biotech", "clinical trial", "eli lilly",
                          "novo nordisk", "pfizer", "vaccine"], []),
    ("us_china_trade",   ["china economy", "china gdp"], []),  # 二次捕获
    ("sector_china_stocks", ["alibaba", "tencent", "baidu", "jd.com", "pinduoduo",
                              "china tech", "hang seng", "csi 300"], []),
    ("sector_ipo",       ["ipo", "public offering", "klarna", "spacex ipo", "stripe ipo",
                          "reddit ipo", "chime", "listing nasdaq", "listing nyse",
                          "market cap above", "go public"], []),
    ("sector_fintech",   ["jpmorgan", "bank of america", "goldman sachs",
                          "morgan stanley", "blackrock", "financial regulation",
                          "bank earnings"], []),
]

# 全局过滤：包含这些词的 market 直接丢弃
BLOCKLIST = [
    "world cup", "fifa", "nba ", "nfl ", "nhl ", "mlb ", "ufc",
    "oscar", "emmy", "grammy", "academy award", "super bowl",
    "gta vi", "gta 6", "rihanna album", "carti album",
    "march madness", "ncaa", "wimbledon", "formula 1 race", "f1 race",
    "wrestle", "boxing match", "fight night",
    "american idol", "the voice ", "survivor episode",
    "world series", "premier league", "champions league goal",
    "player of the year", "mvp award", "league of legends", "esports",
    "soccer", "presidential nominee", "presidential election", "election winner",
    "governor", "senate race", "mayor",
]

# ─── HTTP（curl 通路，带重试）─────────────────────────────────────────────────

def _get(url: str, timeout: int = 30, retries: int = 3) -> list | dict | None:
    """curl 子进程；先试直连，失败再走代理。境外 API urllib 的 SSL 会间歇 EOF。"""
    for attempt in range(retries):
        for mode in (["--noproxy", "*"], ["-x", PROXY]):
            try:
                r = subprocess.run(
                    ["curl", "-s", *mode, "--max-time", str(timeout),
                     "-H", "User-Agent: hermes-polymarket/4.0", url],
                    capture_output=True, text=True, timeout=timeout + 5)
                if r.returncode == 0 and r.stdout.strip():
                    return json.loads(r.stdout)
            except Exception:
                pass
        time.sleep(1)
    print(f"[WARN] fetch failed: {url[:90]}", file=sys.stderr)
    return None


# ─── Classification ───────────────────────────────────────────────────────────

def _classify(question: str) -> str | None:
    q = (question or "").lower()
    for blk in BLOCKLIST:
        if blk in q:
            return None
    for cat_id, include_kws, exclude_kws in QUESTION_RULES:
        if any(kw in q for kw in exclude_kws):
            continue
        if any(kw in q for kw in include_kws):
            return cat_id
    return None


# ─── 区间市场识别 ─────────────────────────────────────────────────────────────
# 区间型：同一 event 下多个价格档 yes/no（BTC>100k, BTC>120k...），或问题含价格档模式。
# 这类市场的单个 yes_prob 不能代表类目，前端用"区间分布条"聚合展示。
_RANGE_PAT = re.compile(
    r"(\$[\d,]+k?|\b\d{4,6}\b|\bhit\b|\babove\b|\bbelow\b|\bbetween\b|reach|\bup or down\b|"
    r"market cap|closing|strike|end of (june|july|december|year|2026))", re.I)

def _is_range_market(question: str, event_market_count: int) -> bool:
    q = question or ""
    # 同 event 下 ≥3 个 market 基本就是区间/多档结构
    if event_market_count >= 3 and _RANGE_PAT.search(q):
        return True
    return False


# ─── Parse ────────────────────────────────────────────────────────────────────

def _parse_market(m: dict, cat_id: str, event: dict, event_mkt_count: int) -> dict:
    cat = CAT_MAP.get(cat_id, {})
    prices_raw = m.get("outcomePrices")
    outcomes_raw = m.get("outcomes")
    if isinstance(prices_raw, str):
        try: prices_raw = json.loads(prices_raw)
        except: prices_raw = None
    if isinstance(outcomes_raw, str):
        try: outcomes_raw = json.loads(outcomes_raw)
        except: outcomes_raw = None
    probs = {}
    if prices_raw and outcomes_raw:
        for name, price in zip(outcomes_raw, prices_raw):
            try: probs[str(name)] = float(price)
            except: pass
    elif prices_raw and len(prices_raw) == 2:
        probs = {"Yes": float(prices_raw[0]), "No": float(prices_raw[1])}
    yes_p = probs.get("Yes") or (max(probs.values()) if probs else None)
    try: volume = float(m.get("volumeNum") or m.get("volume") or 0)
    except: volume = 0.0
    try: vol24 = float(m.get("volume24hr") or 0)
    except: vol24 = 0.0
    question = m.get("question", "")
    return {
        "id":             m.get("conditionId") or m.get("id") or m.get("slug", ""),
        "question":       question,
        "slug":           m.get("slug", ""),
        "category_id":    cat_id,
        "category_label": cat.get("label", cat_id),
        "category":       cat.get("category", ""),
        "subcategory":    cat.get("subcategory", ""),
        "icon":           cat.get("icon", "📊"),
        "yes_prob":       yes_p,
        "probs":          probs,
        "volume":         volume,
        "volume_24hr":    vol24,
        "market_type":    "range" if _is_range_market(question, event_mkt_count) else "binary",
        "event_id":       event.get("id") or event.get("slug", ""),
        "event_title":    event.get("title", ""),
        "end_date":       m.get("endDateIso") or m.get("endDate") or "",
        "fetched_at":     datetime.now(timezone.utc).isoformat(),
    }


# ─── Fetch ────────────────────────────────────────────────────────────────────

def fetch_all() -> list[dict]:
    seen_ids: set[str] = set()
    all_markets: list[dict] = []

    for tag_name, tag_id in TAG_POOL.items():
        print(f"  tag={tag_name}(id={tag_id}) ...", file=sys.stderr)
        url = (f"{EVENTS_API}?limit=40&active=true&closed=false"
               f"&tag_id={tag_id}&order=volume&ascending=false")
        data = _get(url)
        if not data or not isinstance(data, list):
            continue
        for event in data:
            mkts = event.get("markets") or []
            for m in mkts:
                mid = m.get("conditionId") or m.get("id") or m.get("slug", "")
                if not mid or mid in seen_ids:
                    continue
                cat_id = _classify(m.get("question", ""))
                if not cat_id:
                    continue
                seen_ids.add(mid)
                all_markets.append(_parse_market(m, cat_id, event, len(mkts)))
        time.sleep(0.3)

    macro = sum(1 for m in all_markets if m["category"] == "macro")
    sector = sum(1 for m in all_markets if m["category"] == "sector")
    print(f"  total classified: {len(all_markets)} (macro={macro}, sector={sector})", file=sys.stderr)
    return all_markets


# ─── Snapshot & Changes ───────────────────────────────────────────────────────

def save_latest(markets: list[dict]):
    LATEST_FILE.write_text(json.dumps({
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(markets),
        "markets": markets,
    }, ensure_ascii=False, indent=2))


def save_hourly_snapshot(markets: list[dict]):
    now = datetime.now(timezone.utc)
    fname = SNAP_DIR / f"{now.strftime('%Y-%m-%d_%H')}.json"
    slim = {m["id"]: m["yes_prob"] for m in markets if m["yes_prob"] is not None}
    fname.write_text(json.dumps({"ts": now.isoformat(), "probs": slim}, ensure_ascii=False))
    for old in sorted(SNAP_DIR.glob("*.json"))[:-72]:
        old.unlink(missing_ok=True)


def compute_changes(current: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc)
    prev_snap = None
    for h in range(1, 25):  # 回溯最多 24h，找到最近的存档做基准
        ts_key = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=h)
        fname = SNAP_DIR / f"{ts_key.strftime('%Y-%m-%d_%H')}.json"
        if fname.exists():
            try:
                prev_snap = json.loads(fname.read_text())["probs"]
                break
            except: pass
    changes = []
    for m in current:
        if m["yes_prob"] is None: continue
        prev_p = (prev_snap or {}).get(m["id"])
        if prev_p is None: continue
        delta = m["yes_prob"] - prev_p
        if abs(delta) >= 0.02:
            changes.append({**m, "prev_prob": prev_p, "delta": delta, "delta_pct": delta * 100})
    changes.sort(key=lambda x: abs(x["delta"]), reverse=True)
    CHANGES_FILE.write_text(json.dumps({
        "computed_at": now.isoformat(), "changes": changes,
    }, ensure_ascii=False, indent=2))
    return changes


def run():
    print(f"[{datetime.now().isoformat()}] fetcher v4 start", file=sys.stderr)
    markets = fetch_all()
    if not markets:
        print("[ERROR] 抓取为空，保留旧快照不覆盖", file=sys.stderr)
        return [], []
    save_latest(markets)
    save_hourly_snapshot(markets)
    changes = compute_changes(markets)
    print(f"[{datetime.now().isoformat()}] done. {len(markets)} markets, {len(changes)} changes.", file=sys.stderr)
    return markets, changes


if __name__ == "__main__":
    run()
