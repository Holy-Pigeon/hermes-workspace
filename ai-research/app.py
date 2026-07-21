#!/usr/bin/env python3
"""AI Research 门户 Web 服务。
页签: 核心论文链接(读 data/papers.json)。可扩展更多页签。
数据严谨: 每条论文带 verified 字段(核对来源), 不摆未核对内容。
"""
import json
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, send_from_directory, make_response

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
STATIC = os.path.join(BASE, "static")

app = Flask(__name__, static_folder=None)


def no_cache(resp):
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


def load_json(name):
    with open(os.path.join(DATA, name), "r", encoding="utf-8") as f:
        return json.load(f)


@app.route("/")
def index():
    resp = make_response(send_from_directory(STATIC, "index.html"))
    return no_cache(resp)


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "ts": datetime.now(timezone.utc).isoformat()})


@app.route("/api/papers")
def api_papers():
    try:
        data = load_json("papers.json")
    except FileNotFoundError:
        return jsonify({"error": "papers.json not found"}), 404
    # 统计
    total = sum(len(c.get("papers", [])) for c in data.get("collections", []))
    data["_stats"] = {"total_papers": total,
                      "collections": len(data.get("collections", []))}
    return jsonify(data)


if __name__ == "__main__":
    port = int(os.environ.get("AI_RESEARCH_PORT", "5056"))
    app.run(host="127.0.0.1", port=port, debug=False)
