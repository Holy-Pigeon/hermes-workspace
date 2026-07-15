#!/usr/bin/env python3
"""World-RTS 全景图 Web 服务。
读 data/matrix.json，提供热力矩阵 + 四因子拆解 API。
当前为骨架阶段：cells 为空，前端显示『待采集』，绝不摆假数字。
"""
import json
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, send_from_directory, make_response

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data", "matrix.json")
STATIC = os.path.join(BASE, "static")

app = Flask(__name__, static_folder=None)


def load_matrix():
    with open(DATA, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_transparency(m):
    """统计数据透明度：硬数据格 / 赋档格 / 待采集空格。"""
    total = m["meta"]["factions_count"] * m["meta"]["dimensions_count"]
    cells = m.get("cells", {})
    filled = 0
    hard = 0
    for _k, c in cells.items():
        if c and c.get("score") is not None:
            filled += 1
            # 物理缺口有真实硬数据分才算 hard-anchored
            pg = c.get("physical_gap", {})
            if pg.get("self_sufficiency") is not None:
                hard += 1
    return {
        "total": total,
        "filled": filled,
        "empty": total - filled,
        "hard_anchored": hard,
        "fill_pct": round(filled / total * 100, 1) if total else 0,
    }


def no_cache(resp):
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/")
def index():
    resp = make_response(send_from_directory(STATIC, "index.html"))
    return no_cache(resp)


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "ts": datetime.now(timezone.utc).isoformat()})


@app.route("/api/matrix")
def api_matrix():
    m = load_matrix()
    m["transparency"] = compute_transparency(m)
    return jsonify(m)


@app.route("/api/cell/<faction>/<dim>")
def api_cell(faction, dim):
    m = load_matrix()
    key = f"{faction}::{dim}"
    cell = m.get("cells", {}).get(key)
    fac = next((x for x in m["factions"] if x["id"] == faction), None)
    dimension = next((x for x in m["dimensions"] if x["id"] == dim), None)
    return jsonify({
        "faction": fac,
        "dimension": dimension,
        "cell": cell,  # None = 待采集
        "key": key,
    })


if __name__ == "__main__":
    port = int(os.environ.get("WORLD_RTS_PORT", "5055"))
    app.run(host="127.0.0.1", port=port, debug=False)
