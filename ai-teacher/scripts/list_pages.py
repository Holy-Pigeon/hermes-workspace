#!/usr/bin/env python3
"""List all pages in the AI Teacher Notion database with key properties."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync_to_notion as S

token = S.load_token()
config = S.load_config()
db_id = config["database_id"]

pages = []
cursor = None
while True:
    payload = {"page_size": 100}
    if cursor:
        payload["start_cursor"] = cursor
    res = S.notion_request("POST", f"databases/{db_id}/query", token, payload)
    for p in res.get("results", []):
        props = p["properties"]
        def sel(name):
            v = props.get(name, {}).get("select")
            return v["name"] if v else None
        def title(name):
            arr = props.get(name, {}).get("title", [])
            return "".join(t.get("plain_text", "") for t in arr)
        def date(name):
            d = props.get(name, {}).get("date")
            return d["start"] if d else None
        pages.append({
            "id": p["id"],
            "name": title("Name"),
            "category": sel("Category"),
            "stage": sel("Stage"),
            "lesson_date": date("Lesson Date"),
            "archived": p.get("archived", False),
        })
    if res.get("has_more"):
        cursor = res.get("next_cursor")
    else:
        break

print(f"TOTAL: {len(pages)}")
for p in sorted(pages, key=lambda x: (x["category"] or "zzz", x["lesson_date"] or "")):
    print(json.dumps(p, ensure_ascii=False))
