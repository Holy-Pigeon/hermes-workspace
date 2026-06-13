#!/usr/bin/env python3
"""StockChoose 数据库辅助工具。

供每日选股 / 论据复核定时任务调用，封装常用读写操作，保证入库数据符合
docs/selection_rules.md 规范（去重、唯一约束、论据有效性字段维护等）。

用法（命令行子命令，输出 JSON 便于上层解析）：

  # 选股前：列出当前 active/watching 股票池（用于去重，禁止重复入库同代码）
  python3 db_helper.py current-pool

  # 论据复核前：列出最近 N 天未更新论据有效性、且【排除今天新入选】的股票
  python3 db_helper.py stale-for-review --exclude-today --days 7 --limit 5

  # 查看某只股票的全部论据（复核时用）
  python3 db_helper.py theses --stock-pick-id 25

  # 复核后：更新单条论据的有效性
  python3 db_helper.py update-thesis --thesis-id 88 --status valid \
      --summary "Q1数据已验证" --snapshot "收入131亿,同比+52%" --still-valid true

  # 复核后：写一条复盘记录
  python3 db_helper.py add-review --stock-pick-id 25 --action keep \
      --current-price 195.0 --price-change-pct 1.7 --summary "维持active"

  # 复核后：调整股票状态（如降级 watching / 失效 invalidated）
  python3 db_helper.py set-pick-status --stock-pick-id 25 --status watching

  # 执行任意 SQL 文件（选股入库用，复用 tmp/daily_*.sql 模板）
  python3 db_helper.py run-sql --file /projects/StockChoose/tmp/daily_xxx.sql

所有命令默认连接：host=localhost port=5432 dbname=stockchoose user=postgres
可用环境变量 PGHOST/PGPORT/PGDATABASE/PGUSER 覆盖。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 确保能 import 同目录 validate_pick

import psycopg2
import psycopg2.extras


def get_conn():
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ.get("PGDATABASE", "stockchoose"),
        user=os.environ.get("PGUSER", "postgres"),
    )


def _rows_to_dicts(cur):
    if cur.description is None:  # 无结果集的语句（INSERT/UPDATE 无 RETURNING）
        return []
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall():
        d = {}
        for k, v in zip(cols, r):
            d[k] = str(v) if v is not None and not isinstance(v, (int, float, bool)) else v
        out.append(d)
    return out


def cmd_current_pool(conn, args):
    """当前 active/watching 股票池，选股去重必用。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, stock_code, stock_name, market, selected_date, status,
                   expected_upside_pct, conviction_rating, score
            FROM stock_picks
            WHERE status IN ('active','watching')
            ORDER BY selected_date DESC, id DESC
            """
        )
        return _rows_to_dicts(cur)


def cmd_stale_for_review(conn, args):
    """最近 N 天未更新论据有效性的股票；可排除今天新入选的。"""
    days = args.days
    exclude_today = args.exclude_today
    limit = args.limit
    # 直接用视图（已含 7 天 stale 逻辑），再叠加 days / 排除今天 的过滤
    sql = """
        SELECT v.*
        FROM stale_stock_picks_for_thesis_review v
        JOIN stock_picks sp ON sp.id = v.stock_pick_id
        WHERE (
                v.oldest_thesis_validity_checked_at IS NULL
                OR v.oldest_thesis_validity_checked_at < NOW() - (%s || ' days')::interval
              )
    """
    params = [str(days)]
    if exclude_today:
        sql += " AND sp.selected_date < CURRENT_DATE\n"
    sql += " ORDER BY v.oldest_thesis_validity_checked_at NULLS FIRST, v.selected_date ASC, v.stock_pick_id ASC"
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return _rows_to_dicts(cur)


def cmd_theses(conn, args):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, stock_pick_id, thesis_title, thesis_detail, still_valid, status,
                   key_supporting_data, invalidation_condition, last_checked_date,
                   validity_last_checked_at, validity_check_count, last_validation_summary,
                   last_supporting_data_snapshot, next_check_due_at
            FROM stock_theses
            WHERE stock_pick_id = %s
            ORDER BY id
            """,
            (args.stock_pick_id,),
        )
        return _rows_to_dicts(cur)


def cmd_update_thesis(conn, args):
    """更新单条论据有效性，自动 +1 检查次数、刷新检查时间、设定下次检查时间。"""
    still_valid = None
    if args.still_valid is not None:
        still_valid = args.still_valid.lower() in ("true", "1", "yes", "t")
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE stock_theses
            SET status = COALESCE(%s, status),
                still_valid = COALESCE(%s, still_valid),
                last_validation_summary = COALESCE(%s, last_validation_summary),
                last_supporting_data_snapshot = COALESCE(%s, last_supporting_data_snapshot),
                validity_last_checked_at = NOW(),
                validity_check_count = validity_check_count + 1,
                last_checked_date = CURRENT_DATE,
                next_check_due_at = NOW() + INTERVAL '7 days'
            WHERE id = %s
            RETURNING id, stock_pick_id, status, still_valid, validity_check_count
            """,
            (args.status, still_valid, args.summary, args.snapshot, args.thesis_id),
        )
        res = _rows_to_dicts(cur)
    conn.commit()
    return res


def cmd_add_review(conn, args):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO stock_pick_reviews
                (stock_pick_id, review_date, current_price, price_change_pct, review_summary, action)
            VALUES (%s, CURRENT_DATE, %s, %s, %s, %s)
            RETURNING id, stock_pick_id, action, review_date
            """,
            (args.stock_pick_id, args.current_price, args.price_change_pct,
             args.summary, args.action),
        )
        res = _rows_to_dicts(cur)
    conn.commit()
    return res


def cmd_set_pick_status(conn, args):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE stock_picks SET status = %s WHERE id = %s RETURNING id, stock_code, status",
            (args.status, args.stock_pick_id),
        )
        res = _rows_to_dicts(cur)
    conn.commit()
    return res


def cmd_run_sql(conn, args):
    with open(args.file, "r", encoding="utf-8") as f:
        sql = f.read()
    # 入库前语义校验门（根因修复：防 expected_upside_pct 口径错配等）
    try:
        from validate_pick import (validate_after_sql, get_max_pick_id,
                                    ValidationError)
        _has_validator = True
    except ImportError:
        _has_validator = False
    with conn.cursor() as cur:
        before_max_id = get_max_pick_id(cur) if _has_validator else None
        cur.execute(sql)
        try:
            res = _rows_to_dicts(cur)
        except psycopg2.ProgrammingError:
            res = []
        warnings = []
        if _has_validator and not getattr(args, "skip_validation", False):
            try:
                warnings = validate_after_sql(cur, before_max_id)
            except ValidationError as e:
                conn.rollback()
                return {"ok": False, "validation_failed": True,
                        "file": args.file, "error": str(e)}
    conn.commit()
    out = {"ok": True, "file": args.file, "result": res}
    if warnings:
        out["warnings"] = warnings
    return out


def main():
    p = argparse.ArgumentParser(description="StockChoose DB helper")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("current-pool")

    s = sub.add_parser("stale-for-review")
    s.add_argument("--days", type=int, default=7)
    s.add_argument("--exclude-today", action="store_true")
    s.add_argument("--limit", type=int, default=5)

    s = sub.add_parser("theses")
    s.add_argument("--stock-pick-id", type=int, required=True)

    s = sub.add_parser("update-thesis")
    s.add_argument("--thesis-id", type=int, required=True)
    s.add_argument("--status", choices=["valid", "needs_review", "invalidated"])
    s.add_argument("--still-valid")
    s.add_argument("--summary")
    s.add_argument("--snapshot")

    s = sub.add_parser("add-review")
    s.add_argument("--stock-pick-id", type=int, required=True)
    s.add_argument("--action", required=True,
                   choices=["keep", "upgrade", "downgrade", "close", "invalidate"])
    s.add_argument("--current-price", type=float)
    s.add_argument("--price-change-pct", type=float)
    s.add_argument("--summary", required=True)

    s = sub.add_parser("set-pick-status")
    s.add_argument("--stock-pick-id", type=int, required=True)
    s.add_argument("--status", required=True,
                   choices=["active", "watching", "closed", "invalidated"])

    s = sub.add_parser("run-sql")
    s.add_argument("--file", required=True)
    s.add_argument("--skip-validation", action="store_true",
                   help="应急逃生口：跳过入库语义校验门（仅在确认校验误报时用）")

    args = p.parse_args()
    conn = get_conn()
    try:
        fn = {
            "current-pool": cmd_current_pool,
            "stale-for-review": cmd_stale_for_review,
            "theses": cmd_theses,
            "update-thesis": cmd_update_thesis,
            "add-review": cmd_add_review,
            "set-pick-status": cmd_set_pick_status,
            "run-sql": cmd_run_sql,
        }[args.cmd]
        result = fn(conn, args)
        print(json.dumps(result, ensure_ascii=False, default=str, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
