#!/usr/bin/env python3
"""模拟持仓 Web 服务 — Flask API + 静态页面"""
import sqlite3, os, json
from flask import Flask, jsonify, send_from_directory

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../paper_trading.db")
STATIC  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = Flask(__name__, static_folder=STATIC)

def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

# ── helpers ─────────────────────────────────────────────────────────────────

def pos_value(positions):
    total = 0.0
    for p in positions:
        px = p["last_price"] if p["last_price"] is not None else p["avg_cost"]
        fx = p["fx_rate"] or 1
        mult = p["multiplier"] or 1
        val = px * p["quantity"] * mult * fx
        if p["direction"] == "short":
            val = (2 * p["avg_cost"] - px) * p["quantity"] * mult * fx
        total += val
    return total

def enrich_position(p):
    d = dict(p)
    px = d["last_price"] if d["last_price"] is not None else d["avg_cost"]
    fx = d["fx_rate"] or 1
    mult = d["multiplier"] or 1
    cost_base = d["avg_cost"] * d["quantity"] * mult * fx
    mkt_val   = px * d["quantity"] * mult * fx
    if d["direction"] == "short":
        mkt_val = (2 * d["avg_cost"] - px) * d["quantity"] * mult * fx
    pnl       = mkt_val - cost_base
    pnl_pct   = pnl / cost_base * 100 if cost_base else 0
    d.update(market_value=round(mkt_val, 2),
             cost_base=round(cost_base, 2),
             unrealized_pnl=round(pnl, 2),
             pnl_pct=round(pnl_pct, 2),
             last_price=px)
    return d

# ── API ──────────────────────────────────────────────────────────────────────

@app.route("/api/accounts")
def api_accounts():
    c = db()
    rows = c.execute("SELECT * FROM accounts ORDER BY id").fetchall()
    result = []
    for a in rows:
        positions = c.execute("SELECT * FROM positions WHERE account_id=?", (a["id"],)).fetchall()
        pv  = pos_value(positions)
        nav = a["cash"] + pv
        pnl = (nav - a["initial_capital"]) / a["initial_capital"] * 100 if a["initial_capital"] else 0
        d = dict(a)
        d.update(positions_value=round(pv, 2),
                 nav=round(nav, 2),
                 pnl_pct=round(pnl, 2),
                 position_count=len(positions))
        result.append(d)
    c.close()
    return jsonify(result)

@app.route("/api/accounts/<int:aid>/positions")
def api_positions(aid):
    c = db()
    rows = c.execute("SELECT * FROM positions WHERE account_id=? ORDER BY opened_at DESC", (aid,)).fetchall()
    result = [enrich_position(r) for r in rows]
    c.close()
    return jsonify(result)

@app.route("/api/accounts/<int:aid>/nav")
def api_nav(aid):
    c = db()
    rows = c.execute(
        "SELECT snapshot_date, total_nav, pnl_pct, cash, positions_value "
        "FROM nav_snapshots WHERE account_id=? ORDER BY snapshot_date",
        (aid,)
    ).fetchall()
    c.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/accounts/<int:aid>/trades")
def api_trades(aid):
    c = db()
    rows = c.execute(
        "SELECT * FROM trades WHERE account_id=? ORDER BY id DESC LIMIT 100", (aid,)
    ).fetchall()
    c.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/positions/<int:pid>/trades")
def api_position_trades(pid):
    """某持仓标的的全部操作记录（按 symbol 匹配）"""
    c = db()
    pos = c.execute("SELECT * FROM positions WHERE id=?", (pid,)).fetchone()
    if not pos:
        c.close()
        return jsonify([])
    rows = c.execute(
        "SELECT * FROM trades WHERE account_id=? AND symbol=? ORDER BY id DESC",
        (pos["account_id"], pos["symbol"])
    ).fetchall()
    c.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/summary")
def api_summary():
    c = db()
    accts = c.execute("SELECT * FROM accounts").fetchall()
    total_init = total_nav = 0.0
    for a in accts:
        positions = c.execute("SELECT * FROM positions WHERE account_id=?", (a["id"],)).fetchall()
        pv  = pos_value(positions)
        nav = a["cash"] + pv
        total_init += a["initial_capital"]
        total_nav  += nav
    pnl = (total_nav - total_init) / total_init * 100 if total_init else 0
    c.close()
    return jsonify(dict(total_initial=round(total_init,2),
                        total_nav=round(total_nav,2),
                        total_pnl_pct=round(pnl,2)))

# ── Static ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(STATIC, "index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
