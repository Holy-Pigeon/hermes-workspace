#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
exit-sentinel · 持仓论点破裂哨兵（SOUL「卖出纪律」的自动化纵向监控）

元层缺口（非缺某只票，缺一整类能力）:
  发现→估值→护城河→valuation-trigger「等合理价格」——买入那半边 Buffett 纪律系统已建满。
  但**卖出/减仓那半边完全空白**: 4 个在持仓位没有任何东西盯着它们「论点是否已破裂」。
  prediction-ledger 记了每个论点的证伪条件, 但只在遥远的 verify_by(多为 8/31 中报)才结算,
  期间价格/基本面若已朝证伪方向大幅移动, 没有任何机制提醒「该重新承保这个仓位了」。
  这正是 SOUL 反复警告的沉没成本 + 处置效应 + 确认偏误(亏损仓死扛等回本): 芒格说
  投资最大的错误往往不是没买对, 而是该卖时没卖 / 论点破了还抱着。本哨兵就是那个「盯持仓的人」。

它做什么(纯只读、机械、可证伪):
  1. 从 paper-trading 读实际在持仓位(单一事实源, 非手填)
  2. 从 prediction-ledger 按代码匹配该仓位的可证伪论点 + 证伪条件 + verify_by
  3. 从 research/ 匹配该仓位的深度 note(论点出处)
  4. 对每个仓位机械判定三类「重新承保」红旗:
     - ORPHAN   : 在持但无任何可证伪论点登记 = 裸持无退出纪律(最严重, 违反「研究是投资」)
     - WINDOW   : 论点 verify_by 临近(≤ WINDOW_DAYS 天) = 该主动准备结算/复核, 别等被动到期
     - ADVERSE  : 价格已朝论点的不利方向大幅移动(≥ ADVERSE_PP) = 市场在告诉你论点可能有问题, 去核

它绝不做什么:
  - 不下卖出/减仓指令(SOUL 底线: 只给分析框架不给买卖指令)
  - 不发明数据: 仓位读 DB, 论点读 ledger, 价格读 marketdata 一手, 全失败诚实标注不编造
  - 不做线性外推: ADVERSE 只标「价格与论点方向背离」这一事实, 不预测后续走势

输出 = 「持仓重新承保队列」(exit 侧的待办队列, 正是 candidate-deepening 在 entry 侧做的镜像)。
喂给人工/authoring 去重新承保, 决定继续持有 / 减仓 / 清仓——决策永远是人的。
"""
import json, os, sys, sqlite3, re, datetime, pathlib

ROOT = pathlib.Path(__file__).resolve().parent
WS = ROOT.parent
PT_DB = WS / "paper-trading" / "paper_trading.db"
LEDGER = WS / "prediction-ledger" / "predictions.json"
RESEARCH = WS / "research"

# 护栏型阈值(偏保守, 对抗过度告警 alert fatigue)
WINDOW_DAYS = 21        # 论点证伪窗口 ≤ 此天数 → 主动准备复核
ADVERSE_PP = 15.0       # 价格朝论点不利方向移动 ≥ 此 pp → 背离红旗

# ---- marketdata 一手取价(多源降级, 取不到诚实标 None 绝不编造) ----
def _live_price(symbol):
    try:
        sys.path.insert(0, str(WS / "marketdata"))
        import core as _md
        r = _md.get_last_close(symbol)
        # get_last_close 返回 (price, date); 只取价格, 取不到返回 None
        if isinstance(r, (tuple, list)):
            return float(r[0]) if r and r[0] is not None else None
        return float(r) if r is not None else None
    except Exception:
        return None


def load_positions():
    if not PT_DB.exists():
        return []
    c = sqlite3.connect(str(PT_DB))
    cur = c.cursor()
    cur.execute("SELECT symbol,name,market,currency,direction,quantity,avg_cost,last_price "
                "FROM positions WHERE quantity>0")
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    c.close()
    return rows


def load_ledger():
    if not LEDGER.exists():
        return []
    d = json.load(open(LEDGER))
    return d if isinstance(d, list) else d.get("predictions", [])


def _code_of(text):
    """从 '工业富联(601138)' / '09926' 等抽出证券代码集合"""
    if not text:
        return set()
    return set(re.findall(r"\b(\d{4,6})\b", str(text)))


def match_theses(symbol, ledger):
    """按代码匹配该仓位所有 pending 可证伪论点"""
    out = []
    for p in ledger:
        codes = _code_of(p.get("subject", "")) | _code_of(p.get("symbol", ""))
        if symbol.lstrip("0") in {c.lstrip("0") for c in codes} or symbol in codes:
            out.append(p)
    return out


def match_notes(symbol):
    if not RESEARCH.exists():
        return []
    hits = []
    for f in RESEARCH.glob("note_*.md"):
        # 只在标题区(首个分隔线前)匹配, 避免顺带提及污染(同 candidate-deepening 修复教训)
        try:
            head = "".join(open(f).readlines()[:14])
        except Exception:
            continue
        if symbol in head or symbol.lstrip("0") in head:
            hits.append(f.name)
    return hits


def days_to(dstr):
    try:
        d = datetime.datetime.strptime(dstr, "%Y-%m-%d").date()
        return (d - datetime.date.today()).days
    except Exception:
        return None


def analyze():
    positions = load_positions()
    ledger = load_ledger()
    results = []
    for pos in positions:
        sym = pos["symbol"]
        theses = [t for t in match_theses(sym, ledger) if (t.get("outcome") in (None, "pending"))]
        notes = match_notes(sym)
        live = _live_price(sym)
        cost = pos.get("avg_cost")
        px = live if live is not None else pos.get("last_price")
        pnl_pp = None
        if cost and px:
            pnl_pp = round((px / cost - 1) * 100, 1)
            if pos.get("direction") == "short":
                pnl_pp = -pnl_pp

        flags = []
        # ORPHAN: 在持但零可证伪论点
        if not theses:
            flags.append(("ORPHAN", "在持仓位零可证伪论点登记=裸持无退出纪律, 违反『研究是投资』"))
        # WINDOW: 论点证伪窗口临近
        for t in theses:
            dd = days_to(t.get("verify_by", ""))
            if dd is not None and 0 <= dd <= WINDOW_DAYS:
                flags.append(("WINDOW",
                              f"{t.get('id')} 证伪窗口{dd}天后到({t.get('verify_by')}): {t.get('falsification','')[:80]}"))
        # ADVERSE: 价格朝论点不利方向大幅移动
        if pnl_pp is not None and theses and live is not None:
            for t in theses:
                dirn = (t.get("direction") or "")
                # 看空估值论点: 若价格反而大涨→论点不利(该复核是否要认错/减看空)
                if "bear" in dirn and pnl_pp >= ADVERSE_PP:
                    flags.append(("ADVERSE",
                                  f"{t.get('id')}看空但价+{pnl_pp}pp: 论点或有误, 去核是否认错"))
                # 看多/价值论点: 若价格大跌→可能是论点破裂而非错杀, 该重新承保
                if any(k in dirn for k in ["bull", "value", "cheap", "long", "mispriced"]) and pnl_pp <= -ADVERSE_PP:
                    flags.append(("ADVERSE",
                                  f"{t.get('id')}看多但价{pnl_pp}pp: 区分错杀vs论点破裂, 重新承保"))
        # 无论点但仅凭价格也标(裸持又大跌=最危险)
        if not theses and pnl_pp is not None and pnl_pp <= -ADVERSE_PP:
            flags.append(("ADVERSE", f"裸持且价{pnl_pp}pp=无退出纪律的深套仓, 最高优先重新承保"))

        results.append({
            "symbol": sym, "name": pos.get("name"), "direction": pos.get("direction"),
            "cost": cost, "price": px, "price_source": "live" if live is not None else "db_snapshot",
            "pnl_pp": pnl_pp, "n_theses": len(theses),
            "thesis_ids": [t.get("id") for t in theses],
            "notes": notes, "flags": flags,
        })
    return results


def main():
    quiet = "--quiet" in sys.argv
    as_json = "--json" in sys.argv
    res = analyze()
    flagged = [r for r in res if r["flags"]]

    if as_json:
        print(json.dumps({"positions": len(res), "flagged": len(flagged), "results": res},
                         ensure_ascii=False, indent=1))
        sys.exit(1 if flagged else 0)

    if quiet:
        if not flagged:
            sys.exit(0)
        print(f"🚨 exit-sentinel: {len(flagged)}/{len(res)} 持仓需重新承保")
        for r in flagged:
            kinds = ",".join(sorted({f[0] for f in r["flags"]}))
            print(f"  [{kinds}] {r['name']}({r['symbol']}) P&L={r['pnl_pp']}pp 论点数={r['n_theses']}")
            for k, msg in r["flags"]:
                print(f"      · {k}: {msg}")
        sys.exit(1)

    print("=" * 72)
    print("exit-sentinel · 持仓论点破裂哨兵 (卖出纪律自动化)")
    print(f"日期 {datetime.date.today()} | 在持 {len(res)} | 需重新承保 {len(flagged)}")
    print("=" * 72)
    for r in res:
        head = f"{r['name']}({r['symbol']}) {r['direction']}"
        pnl = f"{r['pnl_pp']}pp" if r['pnl_pp'] is not None else "n/a"
        print(f"\n■ {head} | 成本{r['cost']} 现价{r['price']}({r['price_source']}) P&L={pnl}")
        print(f"  可证伪论点: {r['n_theses']}条 {r['thesis_ids']} | note: {r['notes'] or '无'}")
        if r["flags"]:
            for k, msg in r["flags"]:
                print(f"  🚩 {k}: {msg}")
        else:
            print("  ✅ 有论点在册、窗口未近、价格未背离——继续持有(仍须到 verify_by 结算)")
    print("\n" + "-" * 72)
    print("注: 本哨兵只标『该重新承保了』, 不发卖出/减仓指令; 继续持有/减仓/清仓由人决定。")
    print("数据诚实: 仓位读 paper-trading DB, 论点读 prediction-ledger, 价格 marketdata 一手,")
    print("      取不到标 db_snapshot 不编造; 阈值(WINDOW=21d/ADVERSE=15pp)是防御性启发式非真理。")
    sys.exit(1 if flagged else 0)


if __name__ == "__main__":
    main()
