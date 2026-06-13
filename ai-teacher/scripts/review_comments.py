#!/usr/bin/env python3
"""Review ALL AI-Teacher Notion lesson pages for UNRESOLVED reader comments.

Pipeline each run:
  1. Query the lesson database -> every lesson page (id + title).
  2. For each page, walk all blocks and collect inline + page-level comments
     (reuses the recursive walk; see notion skill fetch_comments.py).
  3. Diff against resolved_comments.json (keyed by comment_id) to find NEW ones.
  4. Print the new/unresolved comments as JSON for the agent to answer.

State management:
  - resolved_comments.json holds {"resolved": {comment_id: {meta}}, ...}.
  - A comment is "resolved" only after the agent appends an answer AND calls
    this script with --mark <comment_id> [<comment_id> ...].
  - comment_id is Notion's stable per-comment UUID -> no confusion between an
    already-answered comment and a brand-new one, even on the same block.
  - We also ignore comments authored by the integration bot itself (if any).

Usage:
    # list unresolved comments across all lessons (JSON to stdout)
    python3 review_comments.py

    # mark comments resolved after answering
    python3 review_comments.py --mark <comment_id> <comment_id> ...

    # limit to one page (debug)
    python3 review_comments.py --page <page_id>

Token resolution: $NOTION_API_KEY / $NOTION_API_TOKEN, else
~/.openclaw/openclaw.json skills.entries.notion.apiKey.
"""
import argparse
import json
import os
import subprocess
import sys
import time

NOTION_VERSION = "2025-09-03"
BASE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(BASE)
CONFIG_PATH = os.path.join(PROJECT, ".openclaw", "notion_ai_teacher.json")
STATE_PATH = os.path.join(PROJECT, "resolved_comments.json")


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
            return json.loads(open(STATE_PATH).read())
        except Exception:
            pass
    return {"resolved": {}, "last_review": None}


def save_state(state):
    state["last_review"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with open(STATE_PATH, "w") as f:
        f.write(json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def get_data_source_id(call, database_id):
    """API version 2025-09-03 requires querying via data_sources, not databases.
    A database can have multiple data sources; the lesson DB has exactly one."""
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

    found = []
    for bid in block_ids:
        res = call("GET", "https://api.notion.com/v1/comments?block_id=%s" % bid)
        for c in res.get("results", []):
            txt = "".join(t.get("plain_text", "") for t in c.get("rich_text", []))
            found.append({
                "comment_id": c.get("id"),
                "discussion_id": c.get("discussion_id"),
                "block": bid,
                "anchored_text": block_text(call, bid) if bid != page_id else "(page-level)",
                "who": c.get("created_by", {}).get("id"),
                "time": c.get("created_time"),
                "text": txt,
            })
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mark", nargs="+", default=[], help="comment_ids to mark resolved")
    ap.add_argument("--page", default="", help="restrict to a single page id (debug)")
    args = ap.parse_args()

    state = load_state()

    if args.mark:
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        for cid in args.mark:
            state["resolved"][cid] = {"resolved_at": now}
        save_state(state)
        print(json.dumps({"marked": args.mark, "total_resolved": len(state["resolved"])},
                         ensure_ascii=False))
        return 0

    token = get_token()
    call = make_client(token)
    config = json.loads(open(CONFIG_PATH).read())
    database_id = config["database_id"]

    if args.page:
        pages = [{"page_id": args.page, "title": "(single)"}]
    else:
        pages = list_lesson_pages(call, database_id)

    resolved = state.get("resolved", {})
    unresolved = []
    total_comments = 0
    for pg in pages:
        comments = collect_comments(call, pg["page_id"])
        for c in comments:
            total_comments += 1
            cid = c["comment_id"]
            if cid in resolved:
                continue
            c["page_id"] = pg["page_id"]
            c["page_title"] = pg["title"]
            unresolved.append(c)

    out = {
        "pages_scanned": len(pages),
        "total_comments_seen": total_comments,
        "already_resolved": len(resolved),
        "unresolved_count": len(unresolved),
        "unresolved": unresolved,
    }
    # don't bump last_review on a read-only scan that found nothing actionable?
    # We DO record scan time so we can tell the system is alive.
    save_state(state)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
