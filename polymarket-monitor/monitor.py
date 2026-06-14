#!/usr/bin/env python3
"""
Polymarket 异动监控 — 独立项目
目标：每次运行时扫描与投资组合相关的 Polymarket 市场，
     检测价格大幅变动并推送 Discord 告警。

配置（见 config.json）：
  - keywords:      监控关键词列表（宏观/行业/个股）
  - alert_thresh:  单市场价格变动超过 X% 则告警（默认 5%）
  - min_volume:    最低成交量过滤噪音（默认 $50K）
  - discord_target: Discord 推送 target

状态文件：state.json
  保存上次每个市场的价格快照，对比后触发告警。

用法：
  python3 monitor.py [--dry-run]   # 干跑，仅打印，不推送
  python3 monitor.py               # 正式运行
"""

import json
import sys
import os
import time
import urllib.request
import urllib.parse
import urllib.error
import argparse
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
STATE_FILE  = os.path.join(SCRIPT_DIR, "state.json")
LOG_FILE    = os.path.join(SCRIPT_DIR, "monitor.log")

GAMMA_API = "https://gamma-api.polymarket.com"
POLYMARKET_SCRIPT = os.path.expanduser("~/.hermes/skills/research/polymarket/scripts/polymarket.py")
PYTHON = "/opt/homebrew/bin/python3"

# Polymarket 境外站，方案B精细化分流下命令行/cron 默认不走代理 → 直连 SSL EOF。
# 优先读环境变量代理，否则 fallback 本机 Clash 混合端口 7897；POLYMARKET_NO_PROXY=1 可强制直连。
_PROXY = (
    os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    or os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY")
    or ("" if os.environ.get("POLYMARKET_NO_PROXY") else "http://127.0.0.1:7897")
)
_opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({"http": _PROXY, "https": _PROXY}) if _PROXY
    else urllib.request.ProxyHandler({})
)

# ─── Config ──────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "keywords": [
        "recession", "fed rate", "CPI", "tariff",
        "nvidia", "apple", "microsoft", "google", "amazon", "meta",
        "china", "taiwan", "semiconductor", "AI",
        "nasdaq", "sp500", "bitcoin"
    ],
    "alert_thresh": 5.0,
    "min_volume": 50000,
    "min_days_to_resolution": 2.0,
    "discord_target": "discord:1466490258634969341",
    # 全局墙钟预算(秒)：cron 硬上限 120s，留安全裕度在 95s 前停止扫描并保存已得状态，
    # 避免超时被 kill 导致 save_state 不执行→快照变陈旧→下一轮 delta 基于过期价格(复利盲区)。
    "wall_budget_sec": 80.0
}

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        # merge with defaults for any missing keys
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    return dict(DEFAULT_CONFIG)

def save_config(cfg: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

# ─── State ───────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}

def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

# ─── Logging ─────────────────────────────────────────────────────────────────

def log(msg: str):
    """日志写 stderr，不污染 stdout（stdout 专用于 Hermes cron 推送）"""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line, file=sys.stderr, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

# ─── Polymarket fetch ─────────────────────────────────────────────────────────

def _get(url: str, retries: int = 2) -> dict | list | None:
    """带 retry 的 JSON 拉取，失败间隔 1s"""
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": "hermes-polymarket-monitor/1.0"})
        try:
            with _opener.open(req, timeout=6) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1)
            else:
                log(f"HTTP error {url}: {e}")
                return None
    return None

def _parse_json_field(val):
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return val
    return val

def _fmt_volume(vol) -> str:
    try:
        v = float(vol)
        if v >= 1_000_000:
            return f"${v/1_000_000:.1f}M"
        if v >= 1_000:
            return f"${v/1_000:.1f}K"
        return f"${v:.0f}"
    except Exception:
        return str(vol)

SEARCH_API = "https://gamma-api.polymarket.com/public-search"


def search_markets(keyword: str) -> list[dict]:
    """Search Polymarket markets by keyword via public-search (semantic search endpoint).
    Returns flat list of market dicts from matching events.
    Falls back to /markets?_q= if public-search fails.
    """
    url = f"{SEARCH_API}?q={urllib.parse.quote(keyword)}"
    data = _get(url)
    markets = []

    if data and isinstance(data, dict):
        events = data.get("events", [])
        for evt in events:
            # skip closed events
            if evt.get("closed") or evt.get("archived"):
                continue
            for m in evt.get("markets", []):
                if not (m.get("closed") or m.get("archived")):
                    # attach event title to market for context
                    m["_event_title"] = evt.get("title", "")
                    markets.append(m)

    if not markets:
        # fallback: /markets?_q= with keyword text filter
        log(f"[INFO] public-search returned nothing for '{keyword}', falling back to markets API")
        fb_url = f"{GAMMA_API}/markets?limit=50&active=true&closed=false&_q={urllib.parse.quote(keyword)}"
        fb_data = _get(fb_url) or []
        if isinstance(fb_data, list):
            markets = fb_data
        else:
            markets = fb_data.get("markets", fb_data.get("data", []))
        # filter to keyword-relevant only
        kw_lower = keyword.lower()
        parts = [p for p in kw_lower.split() if len(p) > 2]
        if parts:
            markets = [m for m in markets
                       if any(p in m.get("question", "").lower() for p in parts)]

    return markets

def days_to_resolution(market: dict) -> float | None:
    """市场距离到期(endDate)还有多少天。无法解析返回 None（视为长期，不过滤）。"""
    end = market.get("endDate") or market.get("endDateIso")
    if not end:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(end, fmt).replace(tzinfo=timezone.utc)
            return (dt - datetime.now(timezone.utc)).total_seconds() / 86400.0
        except Exception:
            continue
    return None

def extract_yes_price(market: dict) -> float | None:
    """Extract YES outcome price as float 0-1."""
    prices = _parse_json_field(market.get("outcomePrices", "[]"))
    outcomes = _parse_json_field(market.get("outcomes", "[]"))
    if not isinstance(prices, list) or not prices:
        return None
    # binary market: YES is index 0
    try:
        if isinstance(outcomes, list) and len(outcomes) >= 1:
            # find YES index
            for i, o in enumerate(outcomes):
                if isinstance(o, str) and o.upper() == "YES":
                    return float(prices[i])
        return float(prices[0])
    except Exception:
        return None

# ─── Discord push ─────────────────────────────────────────────────────────────

def send_discord(message: str, target: str, dry_run: bool = False):
    if dry_run:
        print(f"[DRY-RUN] Would send to {target}:\n{message}")
        return
    hermes_send = os.path.expanduser("~/.hermes/skills/messaging/send_message.sh")
    if os.path.exists(hermes_send):
        import subprocess
        subprocess.run([hermes_send, target, message], capture_output=True)
        log(f"Discord pushed: {message[:80]}...")
        return

    # fallback: use Hermes skill Python API if available
    skill_py = os.path.expanduser("~/.hermes/skills/messaging/discord/scripts/send.py")
    if os.path.exists(skill_py):
        import subprocess
        subprocess.run([PYTHON, skill_py, "--target", target, "--message", message], capture_output=True)
        log(f"Discord pushed via skill: {message[:80]}...")
        return

    log(f"[WARN] Could not find Discord send mechanism. Message was: {message[:120]}")

# ─── Core scan logic ──────────────────────────────────────────────────────────

def scan(config: dict, state: dict, dry_run: bool = False) -> dict:
    """
    Scan all keywords, compare with previous state, collect alerts.
    Returns updated state.
    """
    alert_thresh = config.get("alert_thresh", 5.0) / 100.0
    min_volume   = config.get("min_volume", 50000)
    min_days_res = config.get("min_days_to_resolution", 2.0)
    keywords     = config.get("keywords", [])
    discord_tgt  = config.get("discord_target", "discord:1466490258634969341")
    wall_budget  = float(config.get("wall_budget_sec", 95.0))
    t_start      = time.monotonic()

    new_state = dict(state)
    alerts = []
    seen_ids = set()
    kw_done = 0
    truncated = False

    for kw in keywords:
        # 墙钟预算守门：超预算则停止扫描，保存已得状态(避免被 cron 120s 硬 kill 致 save_state 不执行)
        if time.monotonic() - t_start > wall_budget:
            truncated = True
            log(f"[BUDGET] wall budget {wall_budget}s exceeded after {kw_done}/{len(keywords)} keywords, stopping scan early (partial state saved).")
            break
        markets = search_markets(kw)
        kw_done += 1
        time.sleep(0.3)  # rate limit courtesy

        for m in markets:
            mid = m.get("conditionId") or m.get("id") or m.get("question", "")[:60]
            if not mid or mid in seen_ids:
                continue
            seen_ids.add(mid)

            # volume filter
            vol = 0
            try:
                vol = float(m.get("volume", 0) or 0)
            except Exception:
                pass
            if vol < min_volume:
                continue

            # skip closed
            if m.get("closed") or m.get("archived"):
                continue

            # 过滤即将到期的短线价格桶市场（如"BTC今日是否>$64000"）：
            # 临近到期概率天然剧烈摆动趋向0/1，对组合无信息量，纯噪音。
            dtr = days_to_resolution(m)
            if dtr is not None and dtr < min_days_res:
                continue

            yes_price = extract_yes_price(m)
            if yes_price is None:
                continue

            question = m.get("question", "?")
            prev_price = state.get(mid, {}).get("price")

            if prev_price is not None:
                delta = yes_price - float(prev_price)
                delta_pct = abs(delta)
                if delta_pct >= alert_thresh:
                    direction = "⬆️" if delta > 0 else "⬇️"
                    alerts.append({
                        "question": question,
                        "prev": float(prev_price),
                        "curr": yes_price,
                        "delta": delta,
                        "volume": vol,
                        "direction": direction,
                        "keyword": kw,
                    })
                    log(f"ALERT {direction} [{kw}] {question[:60]} | {float(prev_price)*100:.1f}% → {yes_price*100:.1f}% ({delta*100:+.1f}pp) vol={_fmt_volume(vol)}")

            new_state[mid] = {
                "price": yes_price,
                "question": question[:100],
                "volume": vol,
                "keyword": kw,
                "updated": datetime.now(timezone.utc).isoformat(),
            }

    # 输出结果 — 有异动 print 告警（Hermes cron deliver 机制负责推送），无异动 print [SILENT]
    if alerts:
        alerts_sorted = sorted(alerts, key=lambda a: abs(a["delta"]), reverse=True)[:8]
        lines = ["**【Polymarket 异动告警】**\n"]
        for a in alerts_sorted:
            lines.append(
                f"{a['direction']} **{a['question'][:70]}**\n"
                f"   {a['prev']*100:.1f}% → {a['curr']*100:.1f}%（{a['delta']*100:+.1f}pp）"
                f"  成交量 {_fmt_volume(a['volume'])}\n"
            )
        lines.append(f"\n_扫描关键词 {len(keywords)} 个，发现 {len(alerts)} 个异动（阈值 {config['alert_thresh']}%）_")
        msg = "\n".join(lines)
        print(msg)   # Hermes cron no_agent 模式：stdout 即推送内容
        log(f"Alert pushed: {len(alerts)} alerts.")
    else:
        print("[SILENT]")   # Hermes cron no_agent 模式：[SILENT] = 静默不推送
        cov = f"{kw_done}/{len(keywords)}" + ("(部分,预算截断)" if truncated else "")
        log(f"No alerts. Scanned {len(seen_ids)} markets across {cov} keywords.")

    return new_state


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Polymarket 异动监控")
    parser.add_argument("--dry-run", action="store_true", help="仅打印，不推送 Discord")
    parser.add_argument("--init", action="store_true", help="初始化状态快照（不告警）")
    args = parser.parse_args()

    config = load_config()
    save_config(config)   # ensure config.json exists
    state  = load_state()

    log(f"Starting scan (dry_run={args.dry_run}, init={args.init}, markets_in_state={len(state)})")

    if args.init:
        # Build initial snapshot without alerting
        new_state = scan(config, {}, dry_run=True)
        save_state(new_state)
        log(f"Init complete. Snapshot saved: {len(new_state)} markets.")
    else:
        new_state = scan(config, state, dry_run=args.dry_run)
        save_state(new_state)

    log(f"Scan complete. State now covers {len(new_state)} markets.")


if __name__ == "__main__":
    main()
