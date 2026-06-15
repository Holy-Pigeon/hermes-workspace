#!/usr/bin/env python3
"""
research_db_sync.py —— 研究库 ↔ StockChoose DB 缺口发现（纯只读，确定性）
================================================================
职责：扫描 research/note_*.md 里所有「带股票代码」的个股 note，对照 StockChoose DB
里已入库的 stock_code，找出「研究库有深度 note、但 DB 里完全没有记录」的标的，
输出 JSON 缺口清单，供每日闭环 cron 的 LLM 环节据此把论据提炼入库（research_only）。

设计原则（与系统理念一致）：
- 发现缺口是纯函数（机制层），不依赖 LLM 自觉；LLM 只负责「提炼论据并入库」这步判断动作。
- 纯只读：本脚本绝不写 DB、绝不改 note。只产出清单。
- 复用 build_index.py 的 note 解析逻辑（parse_note），保持单一事实源。
- 「方法论/组合类」note（无股票代码）不纳入缺口——它们不是个股标的，无需入库。

用法：
  /usr/bin/python3 research_db_sync.py            # 人类可读 + JSON
  /usr/bin/python3 research_db_sync.py --json      # 仅 JSON（供 cron 脚本注入）

DB 连接走环境变量 PGHOST/PGPORT/PGUSER/PGDATABASE（默认 localhost:5432/postgres/stockchoose）。
psycopg2 在 /usr/bin/python3，故本脚本用系统 python3 跑。
"""
import json
import os
import sys
from pathlib import Path

# 复用 build_index.py 的 note 解析（同目录）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_index import parse_note  # noqa: E402

RESEARCH = Path(__file__).resolve().parent


def get_db_codes():
    """返回 DB 里已存在的 stock_code 集合（任何 status / pick_type 都算已覆盖）。"""
    import psycopg2
    conn = psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ.get("PGDATABASE", "stockchoose"),
        user=os.environ.get("PGUSER", "postgres"),
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT stock_code FROM stock_picks")
            return {r[0].strip() for r in cur.fetchall()}
    finally:
        conn.close()


def main():
    json_only = "--json" in sys.argv
    db_codes = get_db_codes()

    gaps = []
    covered = []
    for p in sorted(RESEARCH.glob("note_*.md")):
        info = parse_note(p)
        code = (info.get("code") or "").strip()
        if not code:
            continue  # 方法论/组合类 note，无个股代码，不纳入缺口
        rec = {
            "code": code,
            "name": info.get("name", ""),
            "obj": info.get("obj", ""),
            "date": info.get("date", ""),
            "type": info.get("type", ""),
            "concl": info.get("concl", ""),
            "file": info.get("file", ""),
            "tag": info.get("tag", ""),
        }
        if code in db_codes:
            covered.append(rec)
        else:
            gaps.append(rec)

    # 同一 code 多篇 note 只报一次缺口（取最新一篇的结论），但保留 note 文件清单
    by_code = {}
    for g in gaps:
        by_code.setdefault(g["code"], {"code": g["code"], "name": g["name"],
                                        "obj": g["obj"], "files": [], "latest": g})
        by_code[g["code"]]["files"].append(g["file"])
        if g["date"] >= by_code[g["code"]]["latest"]["date"]:
            by_code[g["code"]]["latest"] = g
    gap_list = sorted(by_code.values(), key=lambda x: x["latest"]["date"], reverse=True)

    result = {
        "db_codes_count": len(db_codes),
        "notes_with_code": len(gaps) + len(covered),
        "covered_count": len(covered),
        "gap_count": len(gap_list),
        "gaps": gap_list,
    }

    if json_only:
        print(json.dumps(result, ensure_ascii=False))
        return

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\n" + "=" * 60, file=sys.stderr)
    if gap_list:
        print(f"⚠️ 发现 {len(gap_list)} 个研究库→DB 缺口（有深度 note 但 DB 无记录）：", file=sys.stderr)
        for g in gap_list:
            print(f"  - {g['obj']}  最新 note: {g['latest']['file']}", file=sys.stderr)
            print(f"      结论: {g['latest']['concl'][:80]}", file=sys.stderr)
    else:
        print("✅ 无缺口：所有带代码的个股 note 都已在 DB 有记录。", file=sys.stderr)


if __name__ == "__main__":
    main()
