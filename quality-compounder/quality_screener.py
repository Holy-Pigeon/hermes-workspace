#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
质量复利发现器 (quality_screener.py) — 纯只读
================================================================
元层动机(创新引擎 2026-06-19 诊断): 整个发现侧只有一个镜头——
stock-discovery/tech_screener.py 的 ⭐候选硬门槛是【PE自身历史分位<35%】,
即"必须便宜才进尽调漏斗"。这是纯粹的深度价值/均值回归单一视角。

但 SOUL 第一条投资哲学是段永平【好生意 > 好价格】、Nick Sleep 规模经济复利、
可选权价值。系统在哲学与实现上自相矛盾: 嘴上"好生意优先", 发现入口却"好价格(便宜)优先"。
后果: 一只 ROE 35%/毛利 60%/跑道很长但 PE 处自身史 50 分位(不贵不便宜)的伟大复利机器,
会被 tech_screener 判为"·中性"永不进漏斗。这是锚定效应(锚在历史估值分位)在系统层固化,
也解释了为什么研究库 18 篇 note / 预测台账 13 条几乎全是"低分位陷阱 vs 错杀"同质范式。

本工具是 tech_screener 的【正交镜头】: 把锚从"历史估值低分位"换成"企业复利质量本身"。
两个漏斗殊途同归, 都把候选喂给 moat_scorecard 做护城河尽调 + reverse_dcf 做估值反算。
价值漏斗答"够不够便宜", 质量漏斗答"够不够好"——巴菲特后期范式(好公司合理价)只有后者能发现。

判定逻辑(非买卖指令, 是候选漏斗; 锚=质量, 不锚估值):
  💎 高质量复利候选 = 同时满足复利质量硬门槛(下), 且估值不极端泡沫(PE分位<90%留作护栏)
       复利硬门槛(全部满足):
         · ROE 年度 ≥ 18%          (高资本回报=复利引擎)
         · 近年 ROE 持久性: 可得年报里 ≥15% 的年份占比 ≥ 70%  (不是一年好,是持续好)
         · 毛利率 ≥ 35%            (有定价权而非薄利走量)
         · 净利率 ≥ 12%            (定价权落到底线,排除杠杆/周转伪高ROE)
         · 营收 5 段同比里 ≥ 60% 为正  (还在成长,有再投资跑道)
         · TTM 现金含量 OCF/归母 ≥ 60%  (是真钱不是纸面利润)
  🌱 准复利(差一项)= 复利门槛差且仅差 1 项 → 列出差哪项, 供人工判断是否值得跟
  💰 优质但已贵    = 复利门槛全过但 PE 分位 ≥ 90% (好公司但当前价不合理, 入观察不入尽调)
  ·  不符合质量门槛 (绝大多数)

与 tech_screener 的协同(写进判定输出, 让两镜头交叉可执行):
  - 同一标的若 tech_screener 判 ⭐(便宜) + 本器判 💎(优质) = 双镜头共振 = 最高优先尽调
  - 本器 💎 但 tech_screener ·中性 = "好公司但不便宜", 正是本器要补的盲区(锚不同)
  - 数据全部一手 akshare, 复用 tech_screener 同款取数口径(ROE年度/TTM现金含量/净利率护栏)

用法:
  /opt/homebrew/bin/python3 quality_screener.py            # 全白名单扫描
  /opt/homebrew/bin/python3 quality_screener.py --quiet    # 只在有💎候选时输出(可挂cron)
  /opt/homebrew/bin/python3 quality_screener.py --symbol 600519
"""
import sys, json, time, argparse, os
from datetime import datetime

try:
    import akshare as ak
except Exception as e:
    print(f"[FATAL] akshare 不可用: {e}", file=sys.stderr); sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
# 复用 stock-discovery 的 watchlist(同一能力圈, 不另维护一份避免漂移)
DISCOVERY_WL = os.path.expanduser("~/hermes-workspace/stock-discovery/watchlist.json")

DEFAULT_WATCHLIST = [
    {"symbol": "002475", "name": "立讯精密", "theme": "消费电子/连接器精密制造"},
    {"symbol": "300750", "name": "宁德时代", "theme": "动力电池龙头/规模成本"},
    {"symbol": "002230", "name": "科大讯飞", "theme": "AI语音/大模型"},
    {"symbol": "688981", "name": "中芯国际", "theme": "晶圆代工/国产替代"},
    {"symbol": "600519", "name": "贵州茅台", "theme": "高端白酒/高ROE基准"},
    {"symbol": "000725", "name": "京东方A", "theme": "面板/周期科技"},
    {"symbol": "002415", "name": "海康威视", "theme": "安防/AIoT/数据"},
    {"symbol": "300760", "name": "迈瑞医疗", "theme": "医疗器械平台"},
    {"symbol": "688111", "name": "金山办公", "theme": "国产SaaS办公/订阅"},
    {"symbol": "002241", "name": "歌尔股份", "theme": "声学/VR代工"},
]


def load_watchlist():
    if os.path.exists(DISCOVERY_WL):
        try:
            with open(DISCOVERY_WL) as f:
                wl = json.load(f)
            if isinstance(wl, list) and wl:
                return wl
        except Exception as e:
            print(f"[warn] 复用 discovery watchlist 失败, 用默认: {e}", file=sys.stderr)
    return DEFAULT_WATCHLIST


def _num(x):
    try:
        f = float(x)
        return f if f == f else None
    except Exception:
        return None


def pct_rank(series, value):
    vals = [v for v in series if v is not None and v == v and v > 0]
    if not vals or value is None or value <= 0:
        return None
    n = len(vals)
    below = sum(1 for v in vals if v < value)
    equal = sum(1 for v in vals if v == value)
    return (below + 0.5 * equal) / n


def get_pe_pct(symbol):
    """只取 PE 自身历史分位作泡沫护栏(不作主门槛)。失败返回 None 不阻断质量判定。"""
    for _ in range(3):
        try:
            d = ak.stock_value_em(symbol=symbol)
            break
        except Exception:
            time.sleep(2)
    else:
        return None
    if d is None or len(d) == 0:
        return None
    d = d.sort_values("数据日期")
    last = d.iloc[-1]
    cur_pe = _num(last["PE(TTM)"])
    return pct_rank(d["PE(TTM)"].tolist(), cur_pe)


def get_quality(symbol):
    """复利质量指标集。复用 tech_screener 同款口径: ROE年度(最近1231)、TTM现金含量、净利率。"""
    try:
        f = ak.stock_financial_abstract(symbol=symbol)
    except Exception:
        return None
    if f is None or "指标" not in f.columns:
        return None
    date_cols = [c for c in f.columns if c.isdigit() and len(c) == 8]
    if len(date_cols) < 5:
        return None
    date_cols_sorted = sorted(date_cols, reverse=True)
    latest = date_cols_sorted[0]
    yoy_col = str(int(latest[:4]) - 1) + latest[4:]

    def row(metric):
        r = f[f["指标"] == metric]
        return r.iloc[0] if len(r) else None

    out = {"period": latest}
    roe = row("净资产收益率(ROE)")
    npr = row("归母净利润")
    revr = row("营业总收入")
    gm = row("毛利率")
    ocfr = row("经营现金流量净额")

    # --- ROE 年度 + 持久性(可得年报里 ROE>=15% 占比) ---
    roe_annual = None
    roe_years = []
    if roe is not None:
        annual_cols = sorted([c for c in date_cols if c.endswith("1231")], reverse=True)
        for c in annual_cols:
            v = _num(roe[c])
            if v is not None:
                roe_years.append(v)
                if roe_annual is None:
                    roe_annual = v
                    out["roe_annual_period"] = c
    out["roe_annual"] = roe_annual
    out["roe_years_n"] = len(roe_years)
    out["roe_persistence"] = (sum(1 for v in roe_years if v >= 15) / len(roe_years)) if roe_years else None

    # --- 毛利率 ---
    out["gross_margin"] = _num(gm[latest]) if gm is not None else None

    # --- 净利率(归母/营收, 排除杠杆周转伪高ROE) ---
    nm = None
    if npr is not None and revr is not None:
        a, b = _num(npr[latest]), _num(revr[latest])
        if a is not None and b not in (None, 0):
            nm = a / b * 100
    out["net_margin"] = nm

    # --- 营收成长广度: 最近5段同比里为正的占比(再投资跑道是否还在) ---
    pos = total = 0
    if revr is not None:
        for c in date_cols_sorted[:5]:
            yc = str(int(c[:4]) - 1) + c[4:]
            if yc in date_cols:
                a, b = _num(revr[c]), _num(revr[yc])
                if a is not None and b not in (None, 0):
                    total += 1
                    if (a - b) > 0:
                        pos += 1
    out["rev_growth_breadth"] = (pos / total) if total else None
    out["rev_growth_n"] = total

    # --- TTM 现金含量(真钱 vs 纸面利润), 与 tech_screener 同款 TTM 口径 ---
    cc_ttm = None
    prev_fy = str(int(latest[:4]) - 1) + "1231"
    if ocfr is not None and npr is not None and prev_fy in date_cols:
        def _ttm(r):
            x, y, z = _num(r[latest]), _num(r[prev_fy]), _num(r[yoy_col])
            return (x + y - z) if None not in (x, y, z) else None
        o_ttm, n_ttm = _ttm(ocfr), _ttm(npr)
        if o_ttm is not None and n_ttm not in (None, 0):
            cc_ttm = o_ttm / n_ttm * 100
    out["cash_content_ttm"] = cc_ttm
    return out


# 复利质量硬门槛
GATES = [
    ("roe_annual",         lambda v: v is not None and v >= 18,  "ROE年度≥18%"),
    ("roe_persistence",    lambda v: v is not None and v >= 0.70, "ROE持久性(年报里≥15%占比)≥70%"),
    ("gross_margin",       lambda v: v is not None and v >= 35,  "毛利率≥35%(定价权)"),
    ("net_margin",         lambda v: v is not None and v >= 12,  "净利率≥12%(非杠杆周转伪高ROE)"),
    ("rev_growth_breadth", lambda v: v is not None and v >= 0.60, "营收成长广度≥60%(再投资跑道)"),
    ("cash_content_ttm",   lambda v: v is not None and v >= 60,  "TTM现金含量≥60%(真钱)"),
]


def evaluate(q, pe_pct):
    if not q:
        return "·", "数据不足", []
    failed = []
    for key, test, label in GATES:
        if not test(q.get(key)):
            failed.append(label)
    if len(failed) == 0:
        if pe_pct is not None and pe_pct >= 0.90:
            return "💰", f"优质但已贵(复利门槛全过, 但PE处自身史{pe_pct*100:.0f}%分位泡沫区, 入观察不入尽调)", failed
        return "💎", "高质量复利候选(复利门槛全过, 锚=质量非估值; 须过moat_scorecard核护城河+reverse_dcf反算隐含增速)", failed
    if len(failed) == 1:
        return "🌱", f"准复利(仅差1项: {failed[0]})", failed
    return "·", f"不符合质量门槛(差{len(failed)}项)", failed


def fmt(x, suf=""):
    return f"{x:.1f}{suf}" if x is not None else "n/a"


def fmt_pct01(p):
    return f"{p*100:.0f}%" if p is not None else "n/a"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="只在有💎候选时输出(可挂cron)")
    ap.add_argument("--symbol", help="只扫单只")
    args = ap.parse_args()

    wl = load_watchlist()
    if args.symbol:
        wl = [w for w in wl if w["symbol"] == args.symbol] or [{"symbol": args.symbol, "name": args.symbol, "theme": ""}]

    rows, skipped = [], []
    for w in wl:
        sym = w["symbol"]
        q = get_quality(sym)
        time.sleep(0.5)
        pe_pct = get_pe_pct(sym)
        time.sleep(0.5)
        if q is None:
            skipped.append((sym, w.get("name", ""), "财报端口拉取失败"))
            continue
        flag, reason, failed = evaluate(q, pe_pct)
        rows.append({"w": w, "q": q, "pe_pct": pe_pct, "flag": flag, "reason": reason})

    gems = [r for r in rows if r["flag"] == "💎"]
    sprouts = [r for r in rows if r["flag"] == "🌱"]

    if args.quiet and not gems:
        return  # watchdog: 无💎候选则静默 exit0

    print("=" * 80)
    print(f"质量复利发现器 (tech_screener 正交镜头·锚=质量非估值) | {datetime.now():%Y-%m-%d %H:%M} | 一手 akshare")
    print("=" * 80)
    print(f"白名单 {len(wl)} | 成功 {len(rows)} | 跳过 {len(skipped)} | 💎候选 {len(gems)} | 🌱准复利 {len(sprouts)}")
    print("-" * 80)
    order = {"💎": 0, "💰": 1, "🌱": 2, "·": 3}
    rows.sort(key=lambda r: (order.get(r["flag"], 9), -(r["q"].get("roe_annual") or 0)))
    for r in rows:
        w, q = r["w"], r["q"]
        name = f'{w.get("name","")}({w["symbol"]})'
        print(f'\n{r["flag"]} {name:22s} {w.get("theme","")}')
        print(f'   ROE年度 {fmt(q.get("roe_annual"),"%")}({q.get("roe_annual_period","-")}) | '
              f'ROE持久性 {fmt_pct01(q.get("roe_persistence"))}({q.get("roe_years_n")}年报) | '
              f'毛利率 {fmt(q.get("gross_margin"),"%")} | 净利率 {fmt(q.get("net_margin"),"%")}')
        print(f'   营收成长广度 {fmt_pct01(q.get("rev_growth_breadth"))}({q.get("rev_growth_n")}段) | '
              f'TTM现金含量 {fmt(q.get("cash_content_ttm"),"%")} | PE自身史分位 {fmt_pct01(r["pe_pct"])}')
        print(f'   判定: {r["reason"]}')
        if r["flag"] == "💎":
            print(f'   ↳尽调: `/opt/homebrew/bin/python3 ~/hermes-workspace/moat-durability/moat_scorecard.py '
                  f'{w["symbol"]} --name {w.get("name","")}` 核护城河本体, 再 reverse_dcf 反算现价隐含增速')
            print(f'   ↳交叉: 与 tech_screener.py --symbol {w["symbol"]} 比对——若彼也判⭐=双镜头共振(便宜+优质)最高优先')

    if skipped:
        print("\n" + "-" * 80)
        print("跳过(数据端口失败, 绝不编造):")
        for s in skipped:
            print(f"   {s[1]}({s[0]}): {s[2]}")

    print("\n" + "-" * 80)
    print("数据诚实: 全 akshare 一手财报口径; ROE持久性=可得年报里≥15%占比(年报数有限,非全历史);")
    print("成长广度=最近5段单季同比为正占比(受基数/季节性影响); 现金含量=TTM滚动。")
    print("本工具是【质量镜头候选漏斗】非买卖指令, 💎仅代表值得深研, 须再做护城河+反向DCF尽调。")


if __name__ == "__main__":
    main()
