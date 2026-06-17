#!/opt/homebrew/bin/python3
"""StockChoose 每日盯市脚本：刷新股票池的入选后涨跌幅。

对 stock_picks 里所有「非 closed」标的（active/watching/research）：
  1. 走统一取数层 marketdata.get_last_close_batch 批量取现价（腾讯单请求批量
     一次拿全，未命中的并发降级 sina→em→直连；全失败不编造，标取价失败）
  2. 计算 gain_since_pick_pct = 现价/selected_price - 1
  3. UPDATE 主表 last_mark_price / last_mark_date / gain_since_pick_pct

【取数统一】历史上本脚本自建 urllib 直打 qt.gtimg.cn（单源、无降级、无 hang 墙），
与 paper-trading 各走各的源导致同一只票取价打架。现已统一到 marketdata：
腾讯批量逻辑已内化进 marketdata.get_last_close_batch，调用方只管一行。

【解释器】必须用 /opt/homebrew/bin/python3 —— 它同时装了 psycopg2（读写PG）
和 akshare（marketdata 降级链依赖），一个解释器搞定取数+落库。

用法：
  /opt/homebrew/bin/python3 refresh_pick_marks.py            # 刷新全池非closed标的
  /opt/homebrew/bin/python3 refresh_pick_marks.py --dry-run  # 只取价不写库，打印结果

环境变量 PGHOST/PGPORT/PGDATABASE/PGUSER 同 db_helper.py。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

import psycopg2

# 统一取数层在 ~/hermes-workspace/marketdata
_WORKSPACE = "/Users/xiaogexu/hermes-workspace"
if _WORKSPACE not in sys.path:
    sys.path.insert(0, _WORKSPACE)
from marketdata import get_last_close_batch  # noqa: E402


def norm_market(market: str) -> str:
    """把 DB 里五花八门的 market 写法归一成 marketdata 的 A/HK/US。
    DB 实测值：'A' / 'A股/上交所' / 'A股/深交所' / 'SZSE ChiNext' / 'HKEX' 等。"""
    m = (market or "").upper()
    if "HK" in m or "港" in m or "HKEX" in m:
        return "HK"
    if "US" in m or "NASDAQ" in m or "NYSE" in m or "美" in m:
        return "US"
    return "A"  # 含 A股/上交所/深交所/SZSE/SSE/ChiNext 等


def get_conn():
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ.get("PGDATABASE", "stockchoose"),
        user=os.environ.get("PGUSER", "postgres"),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只取价不写库")
    args = ap.parse_args()

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, stock_code, stock_name, market, selected_price
                FROM stock_picks
                WHERE status <> 'closed'
                ORDER BY id
            """)
            picks = cur.fetchall()

        # 构建批量取价请求：每个 pick -> (code, 归一market)
        item_of: dict[int, tuple] = {}
        items: list[tuple] = []
        for pid, code, name, market, sel_price in picks:
            it = (str(code), norm_market(market))
            item_of[pid] = it
            if it not in items:
                items.append(it)

        # 一发批量取价（腾讯批量 + 并发降级，整池通常 <1s）
        marks = get_last_close_batch(items)  # {(code,market): (price, date)}

        results = []
        updated = 0
        fallback_today = date.today()
        with conn.cursor() as cur:
            for pid, code, name, market, sel_price in picks:
                it = item_of[pid]
                mark = marks.get(it)
                if mark is None:
                    results.append((name, code, "取价失败", None, None, None))
                    continue
                price, mark_date = mark
                mark_date = mark_date or fallback_today.isoformat()
                sel = float(sel_price) if sel_price else None
                gain = round((price / sel - 1) * 100, 2) if sel else None
                results.append((name, code, "ok", price, gain, mark_date))
                if not args.dry_run:
                    cur.execute("""
                        UPDATE stock_picks
                        SET last_mark_price = %s,
                            last_mark_date = %s,
                            gain_since_pick_pct = %s,
                            updated_at = NOW()
                        WHERE id = %s
                    """, (price, mark_date, gain, pid))
                    updated += 1
        if not args.dry_run:
            conn.commit()

        summary = {
            "marked": fallback_today.isoformat(),
            "total_picks": len(picks),
            "updated": 0 if args.dry_run else updated,
            "dry_run": args.dry_run,
            "missing": [
                {"name": n, "code": c} for n, c, st, pr, g, d in results if st != "ok"
            ],
            "results": [
                {"name": n, "code": c, "status": st, "price": pr,
                 "gain_pct": g, "mark_date": d}
                for n, c, st, pr, g, d in results
            ],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
