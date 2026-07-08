#!/usr/bin/env python3
"""
correlation_check.py  —  组合相关性 & 集中度分析器 (纯只读)

使命背景:
  我们持有 4 只 stockchoose 真实纸面持仓 (康方/工业富联/小商品城/紫金), 但从未量化过
  它们之间的【隐藏相关性】与【因子集中度】。表面是 4 只 -> 看似分散; 实际若高度共振,
  等于一个集中赌注, 一个宏观冲击 (如中美关税持续、人民币、A股系统性回撤) 会同时打穿多只。
  Polymarket 6/12 实查: "US x China tariff agreement by June 30" 仅 4% Yes -> 关税近期几乎
  必然延续, 而工业富联(AI server/EMS出口) + 小商品城(出口贸易枢纽) 同属贸易敞口, 可能共享
  远高于直觉的 beta。本工具用一手日线收益率把"我们到底有多分散"算成数字。

做什么 (纯只读, 不改库不下单):
  1. 从 paper_trading.db 读真实持仓 (symbol/market/数量/成本/现价/币种/fx) -> 真实市值权重
  2. 用 akshare 一手日线 (A股新浪/东财, 港股) 拉每只 N 日收盘 -> 日收益率序列
  3. 计算:
     - 两两皮尔逊相关矩阵 (对齐交易日, A股与港股取交集日期)
     - 每只与"组合其余部分"的相关 (它对分散化的边际贡献)
     - 市值权重集中度: 最大单一持仓占比 + HHI 赫芬达尔指数 + 有效持仓数 (1/HHI)
     - 加权平均成对相关 (组合"内聚度", 越高越像一个赌注)
     - 简单组合波动率 vs 等权独立假设波动率 -> 分散化收益(diversification ratio)
  4. 分级告警: 任一成对相关 >0.7 = HOT 共振; 有效持仓数 < 实际只数*0.6 = 集中度警告

数据诚实:
  - 收益率全部来自 akshare 一手日线收盘, 拉不到的标的明确跳过并告警, 绝不用估算填充
  - 港股与A股交易日历不同, 只在共同交易日上算相关 (内连接), 报告实际可用样本数
  - 样本 < 20 个交易日时标注"样本不足, 相关性不稳健", 不强行下结论
  - 这是【历史】相关性, 不预测未来; 仅作为集中度体检 + 风险预算输入

用法:
  python3 correlation_check.py [--days 60] [--quiet] [--account stockchoose]
  --quiet: 无告警时空 stdout (供 cron 静默)
"""
import argparse, sqlite3, sys, os, json
from datetime import datetime, timedelta

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_trading.db")

HOT_CORR = 0.70      # 成对相关红线: 共振
WARN_CORR = 0.50     # 成对相关黄线
MIN_SAMPLE = 20      # 最小可信样本交易日


def log(msg, buf):
    buf.append(msg)


def fetch_positions(account):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("""
        SELECT p.symbol, p.name, p.market, p.quantity, p.avg_cost, p.last_price,
               p.currency, p.fx_rate, a.name AS acct
        FROM positions p JOIN accounts a ON p.account_id = a.id
        WHERE a.name = ? AND p.quantity > 0
    """, (account,))
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


def market_kind(market):
    m = (market or "").lower()
    if "hk" in m or "港" in m:
        return "hk"
    return "a"


def get_hist(symbol, kind, days):
    """返回 {date_str: close} 一手日线. 拉不到返回 None.

    已收口到 marketdata 统一层(新浪→东财自动降级), 取代旧版裸 akshare 单源
    stock_hk_hist/stock_zh_a_hist (东财一断就崩的历史病根)。窗口截断在调用方
    pct_returns 之前由本函数返回全量日线, 上游按 days 自行取相关区间。
    """
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from marketdata import get_daily, MarketDataError
    market = "HK" if kind == "hk" else "A"
    try:
        df = get_daily(symbol, market=market)
        if df is None or len(df) == 0:
            return None
        d = {}
        for _, r in df.iterrows():
            d[str(r["date"])] = float(r["close"])
        return d
    except MarketDataError as e:
        return {"__error__": str(e)}
    except Exception as e:
        return {"__error__": str(e)}


def pct_returns(series_by_date):
    """series_by_date: {date: close} -> {date: ret} (与前一交易日比)."""
    dates = sorted(series_by_date.keys())
    out = {}
    for i in range(1, len(dates)):
        prev = series_by_date[dates[i - 1]]
        cur = series_by_date[dates[i]]
        if prev:
            out[dates[i]] = (cur - prev) / prev
    return out


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return cov / (vx ** 0.5 * vy ** 0.5)


def stdev(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return (sum((x - m) ** 2 for x in xs) / (n - 1)) ** 0.5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--account", default="stockchoose")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    buf = []
    alerts = []

    pos = fetch_positions(args.account)
    if len(pos) < 2:
        if not args.quiet:
            print(f"[correlation_check] {args.account} 持仓 < 2 只, 无相关性可算。")
        return

    # --- 市值权重 (统一折算本币/基准, 用 last_price * qty * fx) ---
    for p in pos:
        p["mv"] = p["quantity"] * (p["last_price"] or p["avg_cost"]) * (p["fx_rate"] or 1.0)
    total_mv = sum(p["mv"] for p in pos)
    for p in pos:
        p["w"] = p["mv"] / total_mv if total_mv else 0

    # 集中度
    hhi = sum(p["w"] ** 2 for p in pos)
    eff_n = 1.0 / hhi if hhi else 0
    max_w = max(p["w"] for p in pos)
    max_name = max(pos, key=lambda x: x["w"])["name"]

    log("=" * 64, buf)
    log(f" 组合相关性 & 集中度体检 — {args.account}  ({datetime.now():%Y-%m-%d %H:%M})", buf)
    log("=" * 64, buf)
    log(f"持仓 {len(pos)} 只 | 总市值(基准币) {total_mv:,.0f}", buf)
    log("", buf)
    log("权重:", buf)
    for p in sorted(pos, key=lambda x: -x["w"]):
        log(f"  {p['name']:<8} {p['symbol']:<8} {p['w']*100:5.1f}%  ({market_kind(p['market'])})", buf)
    log("", buf)
    log(f"集中度: 最大单一持仓 {max_name} {max_w*100:.1f}% | HHI {hhi:.3f} | "
        f"有效持仓数 {eff_n:.2f} / {len(pos)} 实际", buf)
    if eff_n < len(pos) * 0.6:
        a = (f"集中度警告: 有效持仓数仅 {eff_n:.2f} (实际 {len(pos)} 只), "
             f"权重高度集中于 {max_name}({max_w*100:.0f}%)")
        alerts.append(a)

    # 市场/地域集中度 (单一市场系统性 beta 敞口)
    mkt_w = {}
    for p in pos:
        k = market_kind(p["market"])
        mkt_w[k] = mkt_w.get(k, 0) + p["w"]
    log("", buf)
    log("市场/地域敞口: " + " | ".join(
        f"{'A股' if k=='a' else '港股'} {w*100:.1f}%" for k, w in
        sorted(mkt_w.items(), key=lambda x: -x[1])), buf)
    top_mkt_k, top_mkt_w = max(mkt_w.items(), key=lambda x: x[1])
    if top_mkt_w > 0.70:
        alerts.append(
            f"单一市场集中: {'A股' if top_mkt_k=='a' else '港股'}敞口达 "
            f"{top_mkt_w*100:.0f}%, 组合系统性绑定单一市场 beta — "
            f"一个 A股系统性回撤 / 人民币 / 中国宏观冲击会同时打穿多只, "
            f"名义 {len(pos)} 只分散在地域维度上是假象")

    # --- 拉收益率 ---
    log("", buf)
    log(f"拉取一手日线 (近 {args.days} 交易日窗口)...", buf)
    rets = {}
    for p in pos:
        kind = market_kind(p["market"])
        hist = get_hist(p["symbol"], kind, args.days)
        if hist is None:
            log(f"  ✗ {p['name']} {p['symbol']}: 无数据, 跳过", buf)
            alerts.append(f"数据缺口: {p['name']}({p['symbol']}) 拉不到日线, 已剔除出相关性计算")
            continue
        if "__error__" in hist:
            log(f"  ✗ {p['name']} {p['symbol']}: 拉取异常 {hist['__error__'][:60]}, 跳过", buf)
            alerts.append(f"数据缺口: {p['name']}({p['symbol']}) 拉取异常, 已剔除")
            continue
        r = pct_returns(hist)
        # 只保留最近 days 个
        keys = sorted(r.keys())[-args.days:]
        rets[p["symbol"]] = {"name": p["name"], "ret": {k: r[k] for k in keys}, "w": p["w"]}
        log(f"  ✓ {p['name']} {p['symbol']}: {len(keys)} 个交易日收益率", buf)

    syms = list(rets.keys())
    if len(syms) < 2:
        log("可用收益率序列 < 2, 无法计算相关性。", buf)
        out = "\n".join(buf)
        if alerts or not args.quiet:
            print(out)
            if alerts:
                print("\n*** 告警 ***")
                for a in alerts:
                    print("  ⚠ " + a)
        return

    # --- 成对相关矩阵 (共同交易日内连接) ---
    log("", buf)
    log("成对相关矩阵 (Pearson, 仅共同交易日):", buf)
    hdr = "         " + "".join(f"{rets[s]['name'][:5]:>7}" for s in syms)
    log(hdr, buf)
    corr = {}
    weighted_corr_num = 0.0
    weighted_corr_den = 0.0
    min_overlap = 10 ** 9
    for si in syms:
        rowstr = f"{rets[si]['name'][:7]:<9}"
        for sj in syms:
            if si == sj:
                rowstr += f"{1.0:>7.2f}"
                continue
            common = sorted(set(rets[si]["ret"]) & set(rets[sj]["ret"]))
            min_overlap = min(min_overlap, len(common))
            if len(common) < 2:
                rowstr += f"{'n/a':>7}"
                continue
            xs = [rets[si]["ret"][d] for d in common]
            ys = [rets[sj]["ret"][d] for d in common]
            c = pearson(xs, ys)
            corr[(si, sj)] = (c, len(common))
            rowstr += f"{(c if c is not None else float('nan')):>7.2f}"
            if si < sj and c is not None:
                wij = rets[si]["w"] * rets[sj]["w"]
                weighted_corr_num += wij * c
                weighted_corr_den += wij
        log(rowstr, buf)

    sample_ok = min_overlap >= MIN_SAMPLE
    log("", buf)
    log(f"共同交易日样本: 最少 {min_overlap} 个 "
        f"({'样本充足' if sample_ok else '样本不足, 相关性不稳健, 仅供参考'})", buf)

    # 加权平均成对相关 (组合内聚度)
    if weighted_corr_den > 0:
        wavg = weighted_corr_num / weighted_corr_den
        log(f"市值加权平均成对相关 (组合内聚度): {wavg:.2f}  "
            f"[0=完全独立, 1=同一只]", buf)

    # 高相关对告警
    log("", buf)
    flagged = []
    for (si, sj), (c, n) in corr.items():
        if si < sj and c is not None and c >= WARN_CORR:
            level = "HOT共振" if c >= HOT_CORR else "偏高"
            flagged.append((c, si, sj, n, level))
    flagged.sort(reverse=True)
    if flagged:
        log("高相关持仓对:", buf)
        for c, si, sj, n, level in flagged:
            log(f"  [{level}] {rets[si]['name']} ↔ {rets[sj]['name']}: "
                f"r={c:.2f} (n={n})", buf)
            if c >= HOT_CORR and sample_ok:
                alerts.append(
                    f"相关性共振: {rets[si]['name']} ↔ {rets[sj]['name']} r={c:.2f} "
                    f"-> 二者实为同一风险敞口, 名义分散是假象, 合计权重 "
                    f"{(rets[si]['w']+rets[sj]['w'])*100:.0f}%")
    else:
        log("无成对相关 ≥ 0.50, 持仓间分散度尚可。", buf)

    # --- 下行beta: 冲击来时每只是否随"其余组合"一起跌 (回答本工具真正的使命) ---
    # 全期 Pearson 是"平静期"共振度, 对危机 regime 结构性失明 (相关性在回撤中
    # 会朝 1 收敛)。docstring 承诺的是"中国宏观/关税冲击会不会同时打穿多只",
    # 全期相关低是 false comfort。正确度量必须条件在【外生的市场承压信号】上,
    # 而非条件在这只自己身上 (那会因沿对角线截断诱导虚假相关, 是选择偏误陷阱)。
    # 做法: 对每只 i, 用"其余持仓"(权重加权, 剔除 i 本身=近似外生) 的日收益为
    # 承压信号, 只在【其余组合下跌日】上算 i 与其余组合的相关。这直接回答:
    # "当组合的其余部分在跌时, 这只是跟着一起跌(正相关=集中), 还是逆势抗跌?"
    log("", buf)
    log("下行同步性 (其余组合下跌日, 每只与'其余组合'的相关):", buf)
    down_flagged = []
    dn_num = 0.0
    dn_den = 0.0
    all_dates = None
    for s in syms:
        ds = set(rets[s]["ret"].keys())
        all_dates = ds if all_dates is None else (all_dates & ds)
    all_dates = sorted(all_dates or [])
    if len(all_dates) >= MIN_SAMPLE:
        wsum_all = sum(rets[s]["w"] for s in syms)
        for si in syms:
            # 其余组合(剔除 si)的权重加权日收益 = 外生承压信号
            others = [s for s in syms if s != si]
            w_oth = sum(rets[s]["w"] for s in others)
            if w_oth <= 0 or len(others) < 1:
                continue
            rest = {d: sum(rets[s]["w"] / w_oth * rets[s]["ret"][d] for s in others)
                    for d in all_dates}
            down_days = [d for d in all_dates if rest[d] < 0]
            if len(down_days) < max(5, MIN_SAMPLE // 3):
                continue
            xs = [rets[si]["ret"][d] for d in down_days]
            ys = [rest[d] for d in down_days]
            dc = pearson(xs, ys)
            if dc is None:
                continue
            # 全期(全部日)i 与其余组合的相关, 作对照
            xf = [rets[si]["ret"][d] for d in all_dates]
            yf = [rest[d] for d in all_dates]
            full = pearson(xf, yf)
            wi = rets[si]["w"]
            dn_num += wi * dc
            dn_den += wi
            delta = (dc - full) if full is not None else None
            log(f"  {rets[si]['name']:<8} 下行r={dc:+.2f} "
                f"(全期r={full if full is not None else float('nan'):+.2f}, "
                f"Δ={'+' if delta is not None and delta >= 0 else ''}"
                f"{delta:.2f}, n下行={len(down_days)})", buf)
            # regime 不对称: 下行时明显更同步 (相关上升且已跨黄线)
            if dc >= WARN_CORR and (full is None or dc - full >= 0.15):
                down_flagged.append((dc, full, si, len(down_days)))
        if dn_den > 0:
            dn_wavg = dn_num / dn_den
            log(f"权重加权下行同步性 {dn_wavg:+.2f}  "
                f"[高=其余组合跌时各只跟跌=集中赌注; 低/负=有真实抗跌分散]", buf)
            if dn_wavg >= HOT_CORR:
                alerts.append(
                    f"下行高同步: 权重加权下行相关 {dn_wavg:.2f} — 组合其余部分下跌时"
                    f"各持仓普遍跟跌, 全期相关低估了冲击下的同步性; 名义分散在"
                    f"回撤 regime 下是假象 (一个中国宏观/关税冲击会同时打穿多只)")
        for dc, full, si, n in sorted(down_flagged, reverse=True):
            alerts.append(
                f"下行同步: {rets[si]['name']} 在其余组合下跌日 r={dc:+.2f} "
                f"(全期仅 {full if full is not None else float('nan'):+.2f}, n={n}) — "
                f"平静期看似独立, 冲击来时却跟着组合一起跌, 全期相关低估了它的下行 beta")
    else:
        log(f"  共同交易日 {len(all_dates)} < {MIN_SAMPLE}, 下行样本不足, 跳过。", buf)

    # --- 分散化比率 (简化: 组合波动率 vs 加权独立波动率) ---
    # 用共同交易日构造等权对齐序列
    all_common = None
    for s in syms:
        ds = set(rets[s]["ret"].keys())
        all_common = ds if all_common is None else (all_common & ds)
    all_common = sorted(all_common or [])
    if len(all_common) >= MIN_SAMPLE:
        # 组合日收益 = sum w_i * r_i (用相对权重归一)
        wsum = sum(rets[s]["w"] for s in syms)
        port = []
        for d in all_common:
            port.append(sum(rets[s]["w"] / wsum * rets[s]["ret"][d] for s in syms))
        port_vol = stdev(port)
        # 加权平均【独立】波动率 = sum w_i*sigma_i (不开方, 这是各自波动的简单加权和)
        wavg_vol = 0.0
        for s in syms:
            sig = stdev([rets[s]["ret"][d] for d in all_common])
            wavg_vol += rets[s]["w"] / wsum * sig
        if port_vol > 0:
            # Choueifaty 分散化比率 = 加权平均个股波动 / 组合波动, >=1, 越大越分散
            div_ratio = wavg_vol / port_vol
            log("", buf)
            log(f"加权平均个股日波动率 {wavg_vol*100:.2f}% vs 组合日波动率 "
                f"{port_vol*100:.2f}% -> 分散化比率 {div_ratio:.2f} "
                f"[=1 毫无分散(形同一只), >1 有分散收益, 越大越好] (n={len(all_common)})", buf)
            if div_ratio < 1.10:
                alerts.append(
                    f"分散化薄弱: 分散化比率仅 {div_ratio:.2f} (加权个股波动 "
                    f"{wavg_vol*100:.2f}% / 组合波动 {port_vol*100:.2f}%), "
                    f"持仓在波动上几乎不互相抵消, 接近一个集中赌注")

    out = "\n".join(buf)
    if alerts or not args.quiet:
        print(out)
        if alerts:
            print("\n" + "*" * 64)
            print("*** 告警 (值得 review) ***")
            for a in alerts:
                print("  ⚠ " + a)
            print("*" * 64)


if __name__ == "__main__":
    main()
