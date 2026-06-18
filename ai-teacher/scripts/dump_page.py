#!/usr/bin/env python3
"""Dump plain text of given Notion page block trees (headings + paragraphs)."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync_to_notion as S

token = S.load_token()

def rt_text(rich):
    out = []
    for r in rich:
        if r.get("type") == "equation":
            out.append("$" + r["equation"]["expression"] + "$")
        else:
            out.append(r.get("plain_text", r.get("text", {}).get("content", "")))
    return "".join(out)

def dump(page_id, label):
    print(f"\n========== {label} ({page_id}) ==========")
    cursor = None
    while True:
        path = f"blocks/{page_id}/children?page_size=100"
        if cursor:
            path += f"&start_cursor={cursor}"
        res = S.notion_request("GET", path, token)
        for b in res.get("results", []):
            t = b["type"]
            data = b.get(t, {})
            if "rich_text" in data:
                txt = rt_text(data["rich_text"])
                prefix = {"heading_1":"# ","heading_2":"## ","heading_3":"### ",
                          "bulleted_list_item":"- ","numbered_list_item":"1. ",
                          "paragraph":"","code":"[code] "}.get(t,"")
                if txt.strip():
                    print(prefix + txt)
            elif t == "equation":
                print("$$" + data.get("expression","") + "$$")
            elif t == "divider":
                print("---")
        if res.get("has_more"):
            cursor = res.get("next_cursor")
        else:
            break

pages = json.loads(sys.argv[1])
for pid, label in pages:
    dump(pid, label)
