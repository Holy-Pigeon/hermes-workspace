#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
科技股价值-成长发现管线 (tech_screener.py) — 纯只读
================================================================
动机: 整个投研系统(6工具+6篇note)全部向内监控已持有的4只股票, 从无任何
"向组合外发现新机会"的管线。一个4只持仓的组合却没有候选标的漏斗, 这是结构盲区。
本工具在【能力圈内的策展科技白名单】上做逐只价值-成长扫描, 等优质科技股进入便宜区。

不撒网全市场(东财全截面端口本轮持续断连, 且全市场撒网非价投), 而是盯一个
人工策展的优质科技股池, 用每只【自身历史估值分位】+【真实财报增速】定位买点。

数据全部一手 akshare:
  - stock_value_em: 个股历史估值序列(PE-TTM/PB/PS/PEG), 算自身历史分位
  - stock_financial_abstract: 多季营收/净利/ROE/毛利率, 算YoY增速
拉不到的标的明确跳过并告警, 绝不编造。

判定逻辑(非买卖指令, 是候选漏斗):
  ⭐ 价值成长候选 = PE自身历史分位<35% 且 净利YoY>20% 且 ROE>12% 且 通过质量闸(ROE持久性≥50%)
     质量闸(alpha-attribution F3便宜陷阱归因落地): 近6年报ROE≥15%占比<50%→降🧱(高ROE不可持续);
     50~80%→发⭐但叠加质量警示; ≥80%→干净⭐。把「便宜」与「生意够不够好」分离, 防深度价值锚定漏。
  📈 成长但偏贵    = 净利YoY>25% 但 PE分位>70%
  ⚠️ 潜在价值陷阱  = PE分位<25% 但 净利YoY<0 (便宜可能有原因)
  ·  中性

用法:
  python3 tech_screener.py            # 全白名单扫描
  python3 tech_screener.py --quiet    # 只在有⭐候选时输出(可挂cron)
  python3 tech_screener.py --symbol 000651
"""
import sys, json, time, argparse, os
from datetime import datetime

try:
    import akshare as ak
except Exception as e:
    print(f"[FATAL] akshare 不可用: {e}", file=sys.stderr); sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_PATH = os.path.join(HERE, "watchlist.json")

# 默认能力圈内 A 股科技/先进制造白名单(可在 watchlist.json 覆盖)
# 选取标准: 有技术壁垒/平台或生态/数据飞轮, 非主题炒作。刻意不含已持仓的工业富联避免重复。
DEFAULT_WATCHLIST = [
    {"symbol": "002475", "name": "立讯精密",   "theme": "消费电子/连接器精密制造"},
    {"symbol": "300750", "name": "宁德时代",   "theme": "动力电池龙头/规模成本"},
    {"symbol": "002230", "name": "科大讯飞",   "theme": "AI语音/大模型"},
    {"symbol": "688981", "name": "中芯国际",   "theme": "晶圆代工/国产替代"},
    {"symbol": "600519", "name": "贵州茅台",   "theme": "对照锚(非科技,高ROE基准)"},
    {"symbol": "000725", "name": "京东方A",    "theme": "面板/周期科技"},
    {"symbol": "002415", "name": "海康威视",   "theme": "安防/AIoT/数据"},
    {"symbol": "300760", "name": "迈瑞医疗",   "theme": "医疗器械平台"},
    {"symbol": "688111", "name": "金山办公",   "theme": "国产SaaS办公/订阅"},
    {"symbol": "002241", "name": "歌尔股份",   "theme": "声学/VR代工"},
]


def load_watchlist():
    if os.path.exists(WATCHLIST_PATH):
        try:
            with open(WATCHLIST_PATH) as f:
                wl = json.load(f)
            if isinstance(wl, list) and wl:
                return wl
        except Exception as e:
            print(f"[warn] watchlist.json 读取失败, 用默认: {e}", file=sys.stderr)
    return DEFAULT_WATCHLIST


def pct_rank(series, value):
    """中点法分位: <value 的比例 + 0.5*(==value 比例)。返回 0..1"""
    vals = [v for v in series if v is not None and v == v and v > 0]  # PE/PS<=0 无意义剔除
    if not vals:
        return None, 0
    n = len(vals)
    below = sum(1 for v in vals if v < value)
    equal = sum(1 for v in vals if v == value)
    return (below + 0.5 * equal) / n, n


def get_valuation(symbol):
    """返回 (current_pe, pe_pct, pb_pct, ps_pct, peg, n_hist, price, asof) 或 None"""
    for attempt in range(3):
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
    pe_series = d["PE(TTM)"].tolist()
    pb_series = d["市净率"].tolist()
    ps_series = d["市销率"].tolist()
    cur_pe = float(last["PE(TTM)"]) if last["PE(TTM)"] == last["PE(TTM)"] else None
    cur_pb = float(last["市净率"]) if last["市净率"] == last["市净率"] else None
    cur_ps = float(last["市销率"]) if last["市销率"] == last["市销率"] else None
    pe_pct, n = (pct_rank(pe_series, cur_pe) if cur_pe and cur_pe > 0 else (None, len(pe_series)))
    pb_pct, _ = (pct_rank(pb_series, cur_pb) if cur_pb else (None, 0))
    ps_pct, _ = (pct_rank(ps_series, cur_ps) if cur_ps and cur_ps > 0 else (None, 0))
    try:
        peg = float(last["PEG值"])
    except Exception:
        peg = None
    return {
        "pe": cur_pe, "pb": cur_pb, "ps": cur_ps,
        "pe_pct": pe_pct, "pb_pct": pb_pct, "ps_pct": ps_pct, "peg": peg,
        "n_hist": n, "price": float(last["当日收盘价"]), "asof": str(last["数据日期"]),
    }


def _num(x):
    try:
        f = float(x)
        return f if f == f else None
    except Exception:
        return None


def get_growth(symbol):
    """从 financial_abstract 取最新季净利/营收 YoY、ROE、毛利率。返回 dict 或 None"""
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
    # 同季去年 = latest 的年份-1 同月日
    yoy_col = str(int(latest[:4]) - 1) + latest[4:]
    if yoy_col not in date_cols:
        return None

    def row(metric):
        r = f[f["指标"] == metric]
        return r.iloc[0] if len(r) else None

    out = {"period": latest, "yoy_period": yoy_col}
    np_now = row("归母净利润"); rev_now = row("营业总收入")
    if np_now is not None:
        a, b = _num(np_now[latest]), _num(np_now[yoy_col])
        out["net_profit_yoy"] = ((a - b) / abs(b) * 100) if (a is not None and b not in (None, 0)) else None
    if rev_now is not None:
        a, b = _num(rev_now[latest]), _num(rev_now[yoy_col])
        out["revenue_yoy"] = ((a - b) / abs(b) * 100) if (a is not None and b not in (None, 0)) else None
    # 上一季营收YoY(用于判断营收增速二阶导/V型拐点): 复苏初期营收先转正,
    # 利润滞后仍为负, 此时旧版trap规则(净利YoY<0)会把复苏拐点误判为价值陷阱(迈瑞案例)。
    out["revenue_yoy_prev"] = None
    if rev_now is not None and len(date_cols_sorted) >= 2:
        prev_q = date_cols_sorted[1]
        prev_yoy_col = str(int(prev_q[:4]) - 1) + prev_q[4:]
        if prev_yoy_col in date_cols:
            a, b = _num(rev_now[prev_q]), _num(rev_now[prev_yoy_col])
            out["revenue_yoy_prev"] = ((a - b) / abs(b) * 100) if (a is not None and b not in (None, 0)) else None
    roe = row("净资产收益率(ROE)")
    out["roe"] = _num(roe[latest]) if roe is not None else None
    # ROE 在 financial_abstract 是【累计YTD】口径: Q1 仅3个月累计ROE, 约为年化ROE的1/4,
    # 直接拿单季YTD ROE 去比 12% 年度门槛会系统性误杀优质股(几乎所有公司Q1 ROE都<12%)。
    # 故另取【最近一个完整年报(1231) ROE】作年度口径, 供 ⭐候选门槛判定; 单季ROE仅作展示。
    roe_annual = None
    if roe is not None:
        annual_cols = sorted([c for c in date_cols if c.endswith("1231")], reverse=True)
        for c in annual_cols:
            v = _num(roe[c])
            if v is not None:
                roe_annual = v
                out["roe_annual_period"] = c
                break
    out["roe_annual"] = roe_annual
    # ---- ROE 持久性(质量闸): alpha-attribution(2026-06-24)首跑坐实系统最痛系统性偏差=
    # F3「便宜陷阱」(累计呼叫α -16.8pp)——纯低PE分位入口选出真烂生意。归因建议: 低PE分位
    # 必要非充分, 入池须叠加质量闸。此处算【近6个完整年报里 ROE≥15% 的占比】, 供 classify
    # 在⭐候选上叠加质量标注(不静默丢弃, 与定价权护栏同范式), 把「便宜」和「生意够不够好」分离。
    roe_persist = None
    roe_years_used = 0
    if roe is not None:
        annual_cols2 = sorted([c for c in date_cols if c.endswith("1231")], reverse=True)[:6]
        vals = [_num(roe[c]) for c in annual_cols2]
        vals = [v for v in vals if v is not None]
        if vals:
            roe_years_used = len(vals)
            roe_persist = sum(1 for v in vals if v >= 15) / len(vals)
    out["roe_persist"] = roe_persist
    out["roe_years_used"] = roe_years_used
    gm = row("毛利率")
    out["gross_margin"] = _num(gm[latest]) if gm is not None else None
    # ---- 盈利质量护栏(防一次性收益/投资收益伪装成高增长) ----
    # 净利率: 归母净利/营收。SaaS等真实经营净利率极少>60%, 远超即疑似含非经常损益。
    npr, revr = row("归母净利润"), row("营业总收入")
    nm = None
    if npr is not None and revr is not None:
        a, b = _num(npr[latest]), _num(revr[latest])
        if a is not None and b not in (None, 0):
            nm = a / b * 100
    out["net_margin"] = nm
    # 现金含量: 经营现金流净额/归母净利。真实盈利OCF应跟得上, <30%且高增长=纸面利润疑云。
    # 【单季口径陷阱(立讯案例)】: financial_abstract 是YTD累计, 取latest=Q1时是单季OCF;
    # 苹果链/强季节性营运资金行业每个Q1经营现金流结构性为负(为下半年新机备料垫付),
    # 全年强烈转正——单季CC会给立讯-193%/歌尔-116%/海康-80%的假红旗, 而TTM CC全部干净
    # (立讯98%/歌尔119%/海康166%)。故护栏改用【TTM滚动口径】, 单季仅作展示。
    # TTM = latest累计 + 上一完整年报(1231) - 去年同期累计(yoy_col)。
    ocfr = row("经营现金流量净额")
    cc = None  # 单季口径(展示用)
    if ocfr is not None and npr is not None:
        o, a = _num(ocfr[latest]), _num(npr[latest])
        if o is not None and a not in (None, 0):
            cc = o / a * 100
    out["cash_content"] = cc
    # TTM 口径(护栏用): 需要 上一完整年报 列存在
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


def earnings_quality_suspect(grw):
    """盈利质量存疑判定: 净利率畸高(>60%, 经营上罕见) 或 现金含量过低(<30%)。
    返回 (suspect_bool, 原因字符串)。用于拦截一次性/投资收益伪装的高增长。
    现金含量优先用【TTM滚动口径】(避免苹果链/季节性营运资金的单季假红旗,立讯案例);
    TTM缺失时回退单季口径。"""
    if not grw:
        return False, ""
    nm = grw.get("net_margin")
    cc_ttm = grw.get("cash_content_ttm")
    cc_q = grw.get("cash_content")
    cc = cc_ttm if cc_ttm is not None else cc_q
    cc_label = "TTM" if cc_ttm is not None else "单季"
    reasons = []
    if nm is not None and nm > 60:
        reasons.append(f"净利率{nm:.0f}%畸高")
    if cc is not None and cc < 30:
        reasons.append(f"现金含量{cc_label}{cc:.0f}%过低")
    return (len(reasons) > 0), "+".join(reasons)


def ps_divergence_warn(val, grw):
    """营收估值 vs 盈利估值背离检测(科大讯飞案例)。
    PS-TTM 处自身史低分位(<10%)看似"营收最便宜", 但若同时 PE 分位偏高(>35%)
    或净利率很薄(<5%), 则低 PS 是市场对【营收质量恶化/增长不赚钱】的正确定价,
    不是错杀。此时 PS 低分位是误导性信号, 须用扣非/经营利润判, 慎用 PS 估值。
    返回 (warn_bool, 原因字符串)。"""
    if not val:
        return False, ""
    ps_pct = val.get("ps_pct")
    pe_pct = val.get("pe_pct")
    nm = grw.get("net_margin") if grw else None
    if ps_pct is None or ps_pct >= 0.10:
        return False, ""
    parts = []
    if pe_pct is not None and pe_pct > 0.35:
        parts.append(f"PE分位{pe_pct*100:.0f}%偏高")
    if nm is not None and nm < 5:
        parts.append(f"净利率{nm:.1f}%薄")
    if not parts:
        return False, ""
    return True, ("⚠️营收/盈利估值背离: PS史" + f"{ps_pct*100:.0f}%" +
                  "低分位但" + "+".join(parts) +
                  "=低PS是增长不赚钱的正确定价非错杀, 慎用PS, 须看扣非/经营利润")


def classify(val, grw):
    pe_pct = val.get("pe_pct") if val else None
    npy = grw.get("net_profit_yoy") if grw else None
    # 候选门槛用【年度口径ROE(最近1231)】, 避免单季YTD ROE系统性误杀; 缺年报回退单季ROE。
    roe = (grw.get("roe_annual") if grw and grw.get("roe_annual") is not None
           else (grw.get("roe") if grw else None))
    if pe_pct is None or npy is None:
        return "·", "数据不足"
    suspect, sus_reason = earnings_quality_suspect(grw)
    if pe_pct < 0.35 and npy > 20 and (roe is None or roe > 12):
        if suspect:
            # 高增长是纸面/一次性收益伪装, 降级为存疑, 绝不放行为候选
            return "🔍", f"伪候选-盈利质量存疑({sus_reason}), 高增长疑为一次性收益, 须看扣非/经营利润"
        # ---- 定价权护栏(与 moat_scorecard 同口径): 哲学是「好生意>好价格」, ⭐候选门槛
        # 不能只看 PE便宜+增长+ROE>12 而漏掉「这高ROE到底来自定价权还是杠杆/周转」。
        # 净利率<8% 的高ROE 多为薄利代工(工业富联4.2%)/大宗周期(随商品价波动)型,
        # 高ROE是杠杆/周转驱动非定价权——便宜+高增长可能只是周期顶/代工放量的幻觉。
        # 此时降级为🧱条件候选, 不发干净⭐, 从而【不进自动尽调流水线】(pipeline 只抓⭐),
        # 强制先由 moat_scorecard 核护城河本体再决定是否升格, 而非价格信号直接放行。
        nm = grw.get("net_margin")
        if nm is not None and nm < 8:
            return "🧱", (f"条件候选-便宜+高增长但净利率仅{nm:.1f}%(<8%), 高ROE疑为杠杆/周转"
                          "非定价权(薄利代工/大宗周期型), 须先过 moat_scorecard 核护城河本体再定")
        # ---- 质量闸(alpha-attribution F3便宜陷阱 -16.8pp 的归因落地): 单年ROE>12 过门槛后,
        # 再用【近6年报 ROE≥15% 持久性】区分「真复利机器」vs「单年高ROE的便宜烂生意」。
        # 持久性<50% = 高ROE不可持续(周期顶/一次性), 正是F3便宜陷阱的典型画像 → ⭐降级🧱,
        # 不进自动尽调流水线, 须先过 moat_scorecard 核护城河本体。≥50%但<80% 则发⭐但叠加质量警示。
        rp = grw.get("roe_persist")
        if rp is not None and grw.get("roe_years_used", 0) >= 3:
            if rp < 0.5:
                return "🧱", (f"条件候选-便宜+高增长但ROE持久性仅{rp*100:.0f}%(近{grw.get('roe_years_used')}年报ROE≥15%占比<50%)"
                              "=高ROE不可持续疑为周期/一次性(F3便宜陷阱画像), 须先过 moat_scorecard 核护城河本体")
            if rp < 0.8:
                return "⭐", (f"价值成长候选(便宜区+高增长+定价权门槛), 但ROE持久性{rp*100:.0f}%偏弱"
                              "(<80%)=复利质量待 moat_scorecard 核, 防便宜陷阱")
            return "⭐", f"价值成长候选(便宜区+高增长+净利率达定价权门槛+ROE持久性{rp*100:.0f}%强)"
        return "⭐", "价值成长候选(便宜区+高增长+净利率达定价权门槛)"
    if npy > 25 and pe_pct > 0.70:
        return "📈", "成长但估值偏贵"
    if pe_pct < 0.25 and npy < 0:
        # 区分【真陷阱】vs【复苏拐点】: 利润YoY滞后于营收YoY。若营收YoY已转正
        # 或较上季明显改善(二阶导向上), 则便宜可能是去库存/反腐冻结后的复苏拐点
        # (迈瑞案例: 26Q1营收+1.4%转正但净利仍-11.4%), 而非盈利持续恶化的真陷阱。
        rev = grw.get("revenue_yoy")
        rev_prev = grw.get("revenue_yoy_prev")
        inflecting = (rev is not None and rev > 0) or (
            rev is not None and rev_prev is not None and (rev - rev_prev) > 5)
        if inflecting:
            return "🔄", ("疑似复苏拐点(便宜+利润仍负但营收YoY已转正/加速, "
                          "利润滞后非衰退延续, 须核中报坐实拐点真伪)")
        return "⚠️", "潜在价值陷阱(便宜但盈利下滑, 营收YoY未见拐点)"
    return "·", "中性"


def fmt_pct(p):
    return f"{p*100:.0f}%" if p is not None else "n/a"


def fmt(x, suf=""):
    return f"{x:.1f}{suf}" if x is not None else "n/a"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="只在有⭐候选时输出")
    ap.add_argument("--symbol", help="只扫单只")
    args = ap.parse_args()

    wl = load_watchlist()
    if args.symbol:
        wl = [w for w in wl if w["symbol"] == args.symbol] or [{"symbol": args.symbol, "name": args.symbol, "theme": ""}]

    rows = []
    skipped = []
    for w in wl:
        sym = w["symbol"]
        val = get_valuation(sym)
        time.sleep(0.5)
        grw = get_growth(sym)
        time.sleep(0.5)
        if val is None and grw is None:
            skipped.append((sym, w.get("name", ""), "估值+财报端口均拉取失败"))
            continue
        flag, reason = classify(val, grw)
        rows.append({"w": w, "val": val, "grw": grw, "flag": flag, "reason": reason})

    stars = [r for r in rows if r["flag"] == "⭐"]
    # 🧱 条件候选(便宜+高增长但净利率<8%, 高ROE疑为杠杆/周转非定价权)其escalation
    # 路径是"先过 moat_scorecard 核护城河本体再升格"——但旧 --quiet 只在有⭐时输出,
    # 导致 🧱 在 cron 路径完全不可见=便宜薄利高增长股被静默丢弃, 升格链断裂。
    # 修复: 🧱 与 ⭐ 同属"须人工跟进的actionable信号", quiet 模式下一并surface,
    # 并对每个 🧱 打出明确的 moat_scorecard 升格判定命令钩子, 把死掉的升格链接活。
    bricks = [r for r in rows if r["flag"] == "🧱"]

    if args.quiet and not stars and not bricks:
        return  # 静默: 无⭐候选且无🧱条件候选才不输出

    print("=" * 78)
    print(f"科技股价值-成长发现管线  |  {datetime.now():%Y-%m-%d %H:%M}  |  纯只读 akshare 一手")
    print("=" * 78)
    print(f"白名单 {len(wl)} 只 | 成功 {len(rows)} | 跳过 {len(skipped)} | ⭐候选 {len(stars)}")
    print("-" * 78)
    # 排序: ⭐优先, 然后按 PE 分位升序(越便宜越前)
    order = {"⭐": 0, "🔍": 1, "🔄": 2, "⚠️": 3, "📈": 4, "·": 5}
    rows.sort(key=lambda r: (order.get(r["flag"], 9),
                             r["val"]["pe_pct"] if r["val"] and r["val"].get("pe_pct") is not None else 1.0))
    for r in rows:
        w, val, grw = r["w"], r["val"], r["grw"]
        name = f'{w.get("name","")}({w["symbol"]})'
        print(f'\n{r["flag"]} {name:22s} {w.get("theme","")}')
        if val:
            print(f'   估值: PE-TTM {fmt(val["pe"])} (自身史分位 {fmt_pct(val["pe_pct"])}, {val["n_hist"]}样本) | '
                  f'PB分位 {fmt_pct(val["pb_pct"])} | PS分位 {fmt_pct(val["ps_pct"])} | PEG {fmt(val["peg"])}')
            print(f'   价格: {val["price"]} (截面 {val["asof"]})')
        else:
            print("   估值: [拉取失败]")
        if grw:
            print(f'   成长: 净利YoY {fmt(grw.get("net_profit_yoy"),"%")} | 营收YoY {fmt(grw.get("revenue_yoy"),"%")} | '
                  f'ROE单季 {fmt(grw.get("roe"),"%")} | ROE年度 {fmt(grw.get("roe_annual"),"%")}({grw.get("roe_annual_period","-")}) | '
                  f'毛利率 {fmt(grw.get("gross_margin"),"%")} ({grw.get("period")} vs {grw.get("yoy_period")})')
        else:
            print("   成长: [拉取失败]")
        if val and val.get("net_margin") is not None or (grw and (grw.get("net_margin") is not None or grw.get("cash_content") is not None)):
            cc_q = grw.get("cash_content") if grw else None
            cc_ttm = grw.get("cash_content_ttm") if grw else None
            cc_disp = (f'TTM {fmt(cc_ttm,"%")} (单季 {fmt(cc_q,"%")})'
                       if cc_ttm is not None else f'单季 {fmt(cc_q,"%")}')
            print(f'   质量: 净利率 {fmt(grw.get("net_margin"),"%")} | 现金含量(OCF/归母) {cc_disp}')
        print(f'   判定: {r["reason"]}')
        if r["flag"] == "🧱":
            # 死链接活: 给条件候选打出明确的升格判定命令, 让"先过 moat_scorecard"可执行
            print(f'   ↳升格: 价格信号便宜但护城河本体存疑, 须人工核护城河再决定是否升⭐ → '
                  f'`/opt/homebrew/bin/python3 ~/hermes-workspace/moat-durability/moat_scorecard.py '
                  f'{w["symbol"]} --name {w.get("name","")}` (宽护城河+定价权达标方可升格, 否则弃)')
        if val:
            ps_warn, ps_reason = ps_divergence_warn(val, grw)
            if ps_warn:
                print(f'   背离: {ps_reason}')

    if skipped:
        print("\n" + "-" * 78)
        print("跳过(数据端口失败, 绝不编造):")
        for s in skipped:
            print(f"   {s[1]}({s[0]}): {s[2]}")

    print("\n" + "-" * 78)
    print("数据诚实: 分位=个股自身历史相对读数, 不预测未来; 低分位≠该买(价值陷阱), 需配")
    print("thesis/catalyst用; YoY为单季同比, 受基数/一次性影响; ROE/毛利率为财报口径。")
    print("本工具是【候选漏斗】不是买卖指令, ⭐仅代表值得深研, 须再做反向DCF+护城河尽调。")


if __name__ == "__main__":
    main()
