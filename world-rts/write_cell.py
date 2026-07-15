#!/usr/bin/env python3
"""World-RTS 数据写入工具。
按四因子结构化写入 matrix.json，并自动计算瓶颈强度。
瓶颈强度 = 物理缺口 × 战略相关性 × 填补难度 × 安全放大器
        = (0..1)   × (0..1)    × (1..3)   × (1..3)   = 0..9

cell 数据结构:
{
  "score": 6.75,                      # 自动算出
  "physical_gap":        {"value":0.75, "self_sufficiency":25, "desc":"...", "source":"..."},  # 唯一硬数据
  "strategic_relevance": {"value":1.0,  "desc":"...", "source":"..."},   # 政策判断
  "irreplaceability":    {"value":3.0,  "desc":"..."},                   # 半客观
  "security_amp":        {"value":3.0,  "desc":"...", "source":"..."}    # 政策判断
}

用法:
  # 设置一格（物理缺口用 self_sufficiency 自给分自动换算 value）
  python3 write_cell.py set cn d09 \
    --ss 25 --pg-desc "先进制程自给率约..." --pg-src "SIA 2024" \
    --sr 1.0 --sr-desc "十四五核心攻关" --sr-src "十四五规划" \
    --irr 3.0 --irr-desc "EUV单点卡死" \
    --sec 3.0 --sec-desc "举国体制+大基金" --sec-src "国安战略"
  # 查看透明度
  python3 write_cell.py stat
"""
import argparse
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data", "matrix.json")


def load():
    with open(DATA, "r", encoding="utf-8") as f:
        return json.load(f)


def save(m):
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


def compute_score(cell):
    """瓶颈强度 = 物理缺口 × 战略相关性 × 填补难度 × 安全放大器。缺任一项返回 None。"""
    try:
        pg = cell["physical_gap"]["value"]
        sr = cell["strategic_relevance"]["value"]
        irr = cell["irreplaceability"]["value"]
        sec = cell["security_amp"]["value"]
        if None in (pg, sr, irr, sec):
            return None
        return round(pg * sr * irr * sec, 2)
    except (KeyError, TypeError):
        return None


def cmd_set(args):
    m = load()
    # 校验 faction / dim 存在
    if not any(x["id"] == args.faction for x in m["factions"]):
        raise SystemExit(f"未知阵营: {args.faction}")
    if not any(x["id"] == args.dim for x in m["dimensions"]):
        raise SystemExit(f"未知维度: {args.dim}")
    # 物理缺口: self_sufficiency(0-100 自给分) → value = (100-ss)/100
    pg_value = round((100 - args.ss) / 100, 3) if args.ss is not None else None
    cell = {
        "physical_gap": {"value": pg_value, "self_sufficiency": args.ss, "desc": args.pg_desc or "", "source": args.pg_src or ""},
        "strategic_relevance": {"value": args.sr, "desc": args.sr_desc or "", "source": args.sr_src or ""},
        "irreplaceability": {"value": args.irr, "desc": args.irr_desc or ""},
        "security_amp": {"value": args.sec, "desc": args.sec_desc or "", "source": args.sec_src or ""},
    }
    cell["score"] = compute_score(cell)
    key = f"{args.faction}::{args.dim}"
    m.setdefault("cells", {})[key] = cell
    save(m)
    print(f"✓ {key} score={cell['score']} (pg={pg_value} sr={args.sr} irr={args.irr} sec={args.sec})")


def cmd_stat(args):
    m = load()
    total = m["meta"]["factions_count"] * m["meta"]["dimensions_count"]
    cells = m.get("cells", {})
    filled = sum(1 for c in cells.values() if c and c.get("score") is not None)
    hard = sum(1 for c in cells.values() if c and c.get("physical_gap", {}).get("self_sufficiency") is not None)
    print(f"总格 {total} · 已填 {filled} ({round(filled/total*100,1)}%) · 硬数据锚定 {hard}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("set")
    s.add_argument("faction")
    s.add_argument("dim")
    s.add_argument("--ss", type=float, help="自给分 0-100（物理缺口 value 自动换算）")
    s.add_argument("--pg-desc"); s.add_argument("--pg-src")
    s.add_argument("--sr", type=float, help="战略相关性 0.2/0.5/0.8/1.0")
    s.add_argument("--sr-desc"); s.add_argument("--sr-src")
    s.add_argument("--irr", type=float, help="填补难度 1.0-3.0")
    s.add_argument("--irr-desc")
    s.add_argument("--sec", type=float, help="安全放大器 1.0-3.0")
    s.add_argument("--sec-desc"); s.add_argument("--sec-src")
    s.set_defaults(func=cmd_set)

    st = sub.add_parser("stat")
    st.set_defaults(func=cmd_stat)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
