#!/usr/bin/env python3
"""StockChoose 每日盯市脚本：刷新股票池的入选后涨跌幅。

对 stock_picks 里所有「非 closed」标的（active/watching/research）：
  1. 按市场拼腾讯行情代码，批量取现价（A股 sh/sz、港股 hk、美股 us）
  2. 计算 gain_since_pick_pct = 现价/selected_price - 1
  3. UPDATE 主表 last_mark_price / last_mark_date / gain_since_pick_pct

腾讯行情接口 https://qt.gtimg.cn/q=... 走国内 IP，不被本机 Clash 代理拦截，
故用 /usr/bin/python3 + urllib 直连即可（无需 agent-browser）。

用法：
  /usr/bin/python3 refresh_pick_marks.py            # 刷新全池非closed标的
  /usr/bin/python3 refresh_pick_marks.py --dry-run  # 只取价不写库，打印结果

环境变量 PGHOST/PGPORT/PGDATABASE/PGUSER 同 db_helper.py。
"""
from __future__ import annotations  # 兼容 /usr/bin/python3 (3.9)：注解延迟求值，支持 X|Y / list[str]

import argparse
import json
import os
import ssl
import sys
import urllib.request
from datetime import date

import psycopg2


def tencent_symbol(stock_code: str, market: str) -> str | None:
    """把 (stock_code, market) 映射成腾讯行情代码。返回 None 表示无法识别。"""
    code = (stock_code or "").strip().upper()
    mk = (market or "").strip().upper()

    # 港股：代码常为 5 位数字（如 09926），腾讯用 hk + 去前导0到5位
    if mk in ("HK", "HKEX", "港股") or (code.isdigit() and len(code) == 5):
        return "hk" + code.zfill(5)

    # 美股：含字母（非纯数字），腾讯用 us<TICKER>
    if mk in ("US", "NASDAQ", "NYSE", "美股") or (code and not code.isdigit()):
        return "us" + code

    # A股：纯数字 6 位。6/9 开头=沪(sh)，0/3 开头=深(sz)
    if code.isdigit() and len(code) == 6:
        if code[0] in ("6", "9"):
            return "sh" + code
        if code[0] in ("0", "3"):
            return "sz" + code
    return None


def fetch_prices(symbols: list[str]) -> dict[str, float]:
    """批量取价。返回 {腾讯symbol: 现价}。取不到的不进 dict。"""
    if not symbols:
        return {}
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    url = "https://qt.gtimg.cn/q=" + ",".join(symbols)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=15, context=ctx).read().decode("gbk", "ignore")

    out: dict[str, float] = {}
    # 每段形如  v_sh601899="1~紫金矿业~601899~30.29~...";
    for seg in raw.split(";"):
        seg = seg.strip()
        if not seg.startswith("v_") or "=" not in seg:
            continue
        key, _, val = seg.partition("=")
        sym = key[2:]  # 去掉 v_ 前缀；港股是 r_hk09926 形式
        val = val.strip().strip('"')
        fields = val.split("~")
        if len(fields) < 4:
            continue
        try:
            price = float(fields[3])
        except (ValueError, IndexError):
            continue
        if price <= 0:
            continue
        out[sym] = price
    return out


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

        # 构建 symbol 映射
        sym_of: dict[int, str] = {}
        req_symbols: list[str] = []
        unresolved = []
        for pid, code, name, market, sel_price in picks:
            sym = tencent_symbol(code, market)
            if sym is None:
                unresolved.append((pid, code, name, market))
                continue
            # 腾讯返回 key：港股带 r_ 前缀，其余不带；统一请求时港股要写 r_hk
            req_sym = ("r_" + sym) if sym.startswith("hk") else sym
            sym_of[pid] = req_sym
            req_symbols.append(req_sym)

        prices = fetch_prices(req_symbols)

        results = []
        updated = 0
        today = date.today()
        with conn.cursor() as cur:
            for pid, code, name, market, sel_price in picks:
                req_sym = sym_of.get(pid)
                if not req_sym:
                    continue
                # fetch_prices 返回的 key 去掉了 v_，但保留 r_ 前缀
                price = prices.get(req_sym)
                if price is None:
                    results.append((name, code, "取价失败", None, None))
                    continue
                sel = float(sel_price)
                gain = round((price / sel - 1) * 100, 2) if sel else None
                results.append((name, code, "ok", price, gain))
                if not args.dry_run:
                    cur.execute("""
                        UPDATE stock_picks
                        SET last_mark_price = %s,
                            last_mark_date = %s,
                            gain_since_pick_pct = %s,
                            updated_at = NOW()
                        WHERE id = %s
                    """, (price, today, gain, pid))
                    updated += 1
        if not args.dry_run:
            conn.commit()

        # 输出 JSON 摘要
        summary = {
            "marked": today.isoformat(),
            "total_picks": len(picks),
            "updated": 0 if args.dry_run else updated,
            "dry_run": args.dry_run,
            "unresolved": [{"id": p, "code": c, "name": n, "market": m} for p, c, n, m in unresolved],
            "results": [
                {"name": n, "code": c, "status": st, "price": pr, "gain_pct": g}
                for n, c, st, pr, g in results
            ],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
