#!/usr/bin/env python3
"""Scan all AI Teacher lessons for content overlap. Pulls each page's body text,
builds a term/section signature, and reports the most similar lesson pairs so a
human can decide on merges. Read-only — touches nothing."""
import json, re, sys, time
from pathlib import Path
from collections import Counter
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync_to_notion as S

token = S.load_token()
config = S.load_config()
db_id = config["database_id"]

def rt_text(rich):
    out = []
    for r in rich:
        if r.get("type") == "equation":
            out.append(r["equation"]["expression"])
        else:
            out.append(r.get("plain_text",""))
    return "".join(out)

# fetch pages with 序号
pages = []
cursor = None
while True:
    payload = {"page_size": 100}
    if cursor: payload["start_cursor"] = cursor
    res = S.notion_request("POST", f"databases/{db_id}/query", token, payload)
    for p in res["results"]:
        name = "".join(t.get("plain_text","") for t in p["properties"]["Name"]["title"])
        seq = p["properties"].get("序号", {}).get("number")
        cat = p["properties"].get("Category", {}).get("select")
        pages.append({"id": p["id"], "name": name, "seq": seq,
                      "cat": cat["name"] if cat else ""})
    if res.get("has_more"): cursor = res["next_cursor"]
    else: break

# pull body text per page
def body_text(pid):
    txt = []
    cur = None
    while True:
        path = f"blocks/{pid}/children?page_size=100"
        if cur: path += f"&start_cursor={cur}"
        res = S.notion_request("GET", path, token)
        for b in res["results"]:
            t = b["type"]; data = b.get(t, {})
            if "rich_text" in data:
                txt.append(rt_text(data["rich_text"]))
            elif t == "equation":
                txt.append(data.get("expression",""))
        if res.get("has_more"): cur = res["next_cursor"]
        else: break
    return "\n".join(txt)

# tokenize: CJK bigrams + latin words + math symbols
def sig(text):
    text = text.lower()
    latin = re.findall(r"[a-z]{3,}", text)
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    cjk_bi = [cjk[i]+cjk[i+1] for i in range(len(cjk)-1)]
    return Counter(latin + cjk_bi)

print(f"fetching {len(pages)} bodies...", file=sys.stderr)
for p in pages:
    p["sig"] = sig(body_text(p["id"]))
    time.sleep(0.05)

def cosine(a, b):
    common = set(a) & set(b)
    dot = sum(a[k]*b[k] for k in common)
    import math
    na = math.sqrt(sum(v*v for v in a.values()))
    nb = math.sqrt(sum(v*v for v in b.values()))
    return dot/(na*nb) if na and nb else 0

pairs = []
for i in range(len(pages)):
    for j in range(i+1, len(pages)):
        s = cosine(pages[i]["sig"], pages[j]["sig"])
        pairs.append((s, i, j))
pairs.sort(reverse=True)

print("\n===== TOP 20 MOST SIMILAR LESSON PAIRS (cosine on body text) =====")
for s, i, j in pairs[:20]:
    a, b = pages[i], pages[j]
    print(f"{s:.3f}  #{a['seq']:>2} {a['name'][:26]:<26} <-> #{b['seq']:>2} {b['name'][:26]}")
