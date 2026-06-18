#!/usr/bin/env python3
"""
us-tech-scout web 控制台 — 美股科技耐久质量发现雷达的可视化控制台。

设计:
  - 扫描慢(12 只逐只拉年报 60s+), web 不每次现跑, 读 ../data/latest_scan.json 快照。
  - 提供"刷新扫描"按钮 → 后台 subprocess 跑 us_tech_scout.py --save(带文件锁防并发)。
  - 纯只读研究数据, 与 polymarket/模拟盘 面板一致: 默认无鉴权, 走 frpc 穿透即可。
  - 绑 127.0.0.1(非 0.0.0.0): frpc 经 localIP=127.0.0.1 拨入, 回环足够且不暴露 LAN。
"""
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

ROOT = Path(__file__).resolve().parent.parent          # us-tech-scout/
DATA = ROOT / "data" / "latest_scan.json"
SCANNER = ROOT / "us_tech_scout.py"
STATIC = Path(__file__).resolve().parent / "static"
PY = "/opt/homebrew/bin/python3"                        # akshare 在 homebrew python3
CN_TZ = timezone(timedelta(hours=8))

app = Flask(__name__, static_folder=str(STATIC))

# ── 扫描并发锁(刷新扫描是重操作, 同一时刻只允许一个在跑) ──
_scan_lock = threading.Lock()
_scan_state = {"running": False, "started_at": None, "finished_at": None, "error": None}


def _run_scan():
    """后台线程: 跑 us_tech_scout.py --save, 结果落盘 data/latest_scan.json。"""
    _scan_state.update(running=True, error=None,
                       started_at=datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S CST"),
                       finished_at=None)
    try:
        # --save 落盘快照; --quiet 避免无候选时刷屏(对落盘无影响)
        proc = subprocess.run(
            [PY, str(SCANNER), "--save"],
            capture_output=True, text=True, timeout=600, cwd=str(ROOT),
        )
        if proc.returncode not in (0, 1):   # 0=无候选 1=有候选, 都算成功
            _scan_state["error"] = (proc.stderr or proc.stdout or "未知错误")[-500:]
    except subprocess.TimeoutExpired:
        _scan_state["error"] = "扫描超时(>600s)"
    except Exception as e:
        _scan_state["error"] = f"{type(e).__name__}: {e}"
    finally:
        _scan_state.update(running=False,
                           finished_at=datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S CST"))
        _scan_lock.release()


@app.route("/")
def index():
    return send_from_directory(str(STATIC), "index.html")


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


@app.route("/api/scan")
def api_scan():
    """返回最新快照(只读)。"""
    if not DATA.exists():
        return jsonify({"ok": False, "error": "尚无扫描快照, 请点刷新扫描", "scan_state": _scan_state})
    try:
        snap = json.loads(DATA.read_text())
    except Exception as e:
        return jsonify({"ok": False, "error": f"快照解析失败: {e}"}), 500
    # 候选/关注/出局 分组, 给前端直接用
    results = snap.get("results", [])
    buckets = {"moat": [], "growth": [], "watch": [], "out": []}
    for r in results:
        f = r.get("flag")
        if f == "🏰":
            buckets["moat"].append(r)
        elif f == "⭐":
            buckets["growth"].append(r)
        elif f == "🔍":
            buckets["watch"].append(r)
        else:
            buckets["out"].append(r)
    return jsonify({"ok": True, "snapshot": snap, "buckets": buckets, "scan_state": _scan_state})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """触发后台重新扫描(带锁, 已在跑则拒绝)。"""
    if not _scan_lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "已有扫描在进行中", "scan_state": _scan_state}), 409
    threading.Thread(target=_run_scan, daemon=True).start()
    time.sleep(0.3)  # 让线程把 running 置 True 再返回
    return jsonify({"ok": True, "msg": "扫描已启动(约60-120s)", "scan_state": _scan_state})


@app.route("/api/status")
def api_status():
    """轮询扫描状态(前端刷新中转圈用)。"""
    mtime = None
    if DATA.exists():
        mtime = datetime.fromtimestamp(DATA.stat().st_mtime, CN_TZ).strftime("%Y-%m-%d %H:%M:%S CST")
    return jsonify({"ok": True, "scan_state": _scan_state, "snapshot_mtime": mtime})


if __name__ == "__main__":
    # 绑回环, 不绑 0.0.0.0(安全): frpc 经 localIP=127.0.0.1 拨入
    app.run(host="127.0.0.1", port=5053, debug=False)
