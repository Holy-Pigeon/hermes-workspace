#!/usr/bin/env python3
"""Round-robin reviewer for AI-Teacher Notion lessons: check ONE lesson per run
for new reader comments. Designed for a 30-min cron so a full sweep of N lessons
takes N*30min, but each tick is cheap (one page walk, not all of them).

State file: comment_review_state.json
    {
      "page_order":   [page_id, ...],      # stable rotation order
      "page_titles":  {page_id: title},    # for human-readable output
      "cursor":       int,                 # index into page_order for NEXT run
      "resolved":     {comment_id: {...}}, # answered comments (never re-surface)
      "last_review":  iso8601,
      "last_order_refresh": iso8601
    }

Why comment_id as the resolved key: it's Notion's stable per-comment UUID, so an
already-answered comment and a brand-new comment on the same block never get
confused.

Usage:
    # cron tick — review the NEXT lesson in rotation, advance cursor
    python3 review_comments.py
        -> prints JSON: which page was checked + any UNRESOLVED comments

    # rebuild rotation order from the DB (call when new lessons were added)
    python3 review_comments.py --refresh-order

    # mark comments resolved after the agent appended answers
    python3 review_comments.py --mark <comment_id> [<comment_id> ...]

    # force-check a specific page without advancing the cursor (debug)
    python3 review_comments.py --page <page_id>

Token: $NOTION_API_KEY / $NOTION_API_TOKEN, else
~/.openclaw/openclaw.json skills.entries.notion.apiKey.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

# Notion averages ~3 req/s; 8 concurrent short-lived curls stays under the
# burst ceiling while cutting the N+1 comment sweep from ~130s to ~13s.
COMMENT_FETCH_WORKERS = 8

NOTION_VERSION = "2025-09-03"
BASE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(BASE)
CONFIG_PATH = os.path.join(PROJECT, ".openclaw", "notion_ai_teacher.json")
STATE_PATH = os.path.join(PROJECT, "comment_review_state.json")


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def get_token():
    tok = os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_API_TOKEN")
    if tok:
        return tok
    try:
        cfg = json.loads(open(os.path.expanduser("~/.openclaw/openclaw.json")).read())
        return cfg["skills"]["entries"]["notion"]["apiKey"]
    except Exception:
        sys.exit("No Notion token (env or openclaw.json).")


def make_client(token):
    bearer = "Bearer " + token
    headers = ["-H", "Authorization: " + bearer,
               "-H", "Notion-Version: " + NOTION_VERSION,
               "-H", "Content-Type: application/json"]

    def call(method, url, payload=None):
        cmd = ["curl", "-s", "--retry", "3", "-X", method, *headers, url]
        if payload is not None:
            cmd += ["-d", json.dumps(payload, ensure_ascii=False)]
        for _ in range(5):
            out = subprocess.run(cmd, capture_output=True, text=True).stdout
            try:
                j = json.loads(out)
                if isinstance(j, dict) and ("results" in j or "object" in j or "type" in j):
                    return j
            except Exception:
                pass
            time.sleep(1)
        return {}

    return call


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            s = json.loads(open(STATE_PATH).read())
            s.setdefault("page_order", [])
            s.setdefault("page_titles", {})
            s.setdefault("cursor", 0)
            s.setdefault("resolved", {})
            return s
        except Exception:
            pass
    return {"page_order": [], "page_titles": {}, "cursor": 0,
            "resolved": {}, "last_review": None, "last_order_refresh": None}


def save_state(state):
    with open(STATE_PATH, "w") as f:
        f.write(json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def get_data_source_id(call, database_id):
    db = call("GET", "https://api.notion.com/v1/databases/%s" % database_id)
    sources = db.get("data_sources", [])
    if not sources:
        sys.exit("Database %s has no data_sources (cannot query)." % database_id)
    return sources[0]["id"]


def list_lesson_pages(call, database_id):
    data_source_id = get_data_source_id(call, database_id)
    pages = []
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        res = call("POST", "https://api.notion.com/v1/data_sources/%s/query" % data_source_id, payload)
        for p in res.get("results", []):
            if p.get("archived"):
                continue
            props = p.get("properties", {})
            name = props.get("Name", {}).get("title", [])
            title = "".join(t.get("plain_text", "") for t in name)
            pages.append({"page_id": p["id"], "title": title})
        if res.get("has_more"):
            cursor = res.get("next_cursor")
        else:
            break
    return pages


def refresh_order(call, state, database_id):
    """Rebuild page_order from the live DB, preserving already-known ordering and
    appending newly-found pages at the end so the rotation stays stable."""
    pages = list_lesson_pages(call, database_id)
    live_ids = [p["page_id"] for p in pages]
    titles = {p["page_id"]: p["title"] for p in pages}

    old_order = [pid for pid in state.get("page_order", []) if pid in set(live_ids)]
    known = set(old_order)
    new_ids = [pid for pid in live_ids if pid not in known]
    new_order = old_order + new_ids

    state["page_order"] = new_order
    state["page_titles"] = titles
    if state.get("cursor", 0) >= len(new_order):
        state["cursor"] = 0
    state["last_order_refresh"] = now_iso()
    return len(new_order), len(new_ids)


def block_text(call, block_id):
    b = call("GET", "https://api.notion.com/v1/blocks/%s" % block_id)
    t = b.get("type", "")
    body = b.get(t, {})
    rt = body.get("rich_text", []) if isinstance(body, dict) else []
    return "".join(x.get("plain_text", "") for x in rt)


def collect_comments(call, page_id):
    def children(bid):
        return call("GET", "https://api.notion.com/v1/blocks/%s/children?page_size=100" % bid).get("results", [])

    block_ids = [page_id]
    for b in children(page_id):
        block_ids.append(b["id"])
        if b.get("has_children"):
            for c in children(b["id"]):
                block_ids.append(c["id"])

    # N+1 killer: fan the per-block comment GETs out concurrently. This is the
    # single dominant cost (one GET per block, ~1.4s each serial). Keeping the
    # block_ids order via ex.map preserves deterministic output.
    def fetch(bid):
        return bid, call("GET", "https://api.notion.com/v1/comments?block_id=%s" % bid).get("results", [])

    with ThreadPoolExecutor(max_workers=COMMENT_FETCH_WORKERS) as ex:
        per_block = list(ex.map(fetch, block_ids))

    # Only blocks that actually carry comments need an anchored_text lookup;
    # fetch those concurrently too instead of one serial GET per comment.
    blocks_with_comments = [bid for bid, res in per_block if res and bid != page_id]
    anchor = {}
    if blocks_with_comments:
        with ThreadPoolExecutor(max_workers=COMMENT_FETCH_WORKERS) as ex:
            for bid, txt in ex.map(lambda b: (b, block_text(call, b)), blocks_with_comments):
                anchor[bid] = txt

    found = []
    for bid, res in per_block:
        for c in res:
            txt = "".join(t.get("plain_text", "") for t in c.get("rich_text", []))
            found.append({
                "comment_id": c.get("id"),
                "discussion_id": c.get("discussion_id"),
                "block": bid,
                "anchored_text": anchor.get(bid, "(page-level)") if bid != page_id else "(page-level)",
                "who": c.get("created_by", {}).get("id"),
                "time": c.get("created_time"),
                "text": txt,
            })
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mark", nargs="+", default=[], help="comment_ids to mark resolved")
    ap.add_argument("--refresh-order", action="store_true",
                    help="rebuild rotation order from the DB (run when new lessons added)")
    ap.add_argument("--page", default="", help="force-check one page id, don't advance cursor")
    args = ap.parse_args()

    state = load_state()

    # --- mark resolved -------------------------------------------------------
    if args.mark:
        ts = now_iso()
        for cid in args.mark:
            state["resolved"][cid] = {"resolved_at": ts}
        save_state(state)
        print(json.dumps({"marked": args.mark, "total_resolved": len(state["resolved"])},
                         ensure_ascii=False))
        return 0

    token = get_token()
    call = make_client(token)
    config = json.loads(open(CONFIG_PATH).read())
    database_id = config["database_id"]

    # --- refresh order -------------------------------------------------------
    if args.refresh_order:
        total, new = refresh_order(call, state, database_id)
        save_state(state)
        print(json.dumps({"page_order_size": total, "newly_added": new,
                          "cursor": state["cursor"]}, ensure_ascii=False))
        return 0

    # --- single-page debug ---------------------------------------------------
    if args.page:
        comments = collect_comments(call, args.page)
        resolved = state.get("resolved", {})
        unresolved = [c for c in comments if c["comment_id"] not in resolved]
        for c in unresolved:
            c["page_id"] = args.page
        print(json.dumps({"mode": "single-page", "page_id": args.page,
                          "comments_seen": len(comments),
                          "unresolved_count": len(unresolved),
                          "unresolved": unresolved}, ensure_ascii=False, indent=2))
        return 0

    # --- normal cron tick: review ONE page in rotation -----------------------
    # lazily init / heal the rotation order
    if not state.get("page_order"):
        refresh_order(call, state, database_id)

    order = state["page_order"]
    if not order:
        save_state(state)
        print(json.dumps({"reviewed_page": None, "reason": "no lessons in DB"},
                         ensure_ascii=False))
        return 0

    idx = state["cursor"] % len(order)
    page_id = order[idx]
    title = state.get("page_titles", {}).get(page_id, "(unknown)")

    comments = collect_comments(call, page_id)
    resolved = state.get("resolved", {})
    unresolved = []
    for c in comments:
        if c["comment_id"] in resolved:
            continue
        c["page_id"] = page_id
        c["page_title"] = title
        unresolved.append(c)

    # advance cursor for next tick (wrap around)
    state["cursor"] = (idx + 1) % len(order)
    state["last_review"] = now_iso()
    save_state(state)

    out = {
        "reviewed_page": page_id,
        "page_title": title,
        "rotation_index": idx,
        "rotation_size": len(order),
        "next_cursor": state["cursor"],
        "comments_on_page": len(comments),
        "unresolved_count": len(unresolved),
        "unresolved": unresolved,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
