#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
edge_fusion.py — 正交性加权的信号融合器 (元层桥接，纯本地、只读、无网络)

它补的系统级 gap
------------------
我们已有两端,中间却断了:
  · signal-orthogonality/  知道每条信号消费哪根【原始数据】(root_inputs),
    能审计『N 重印证是否真独立』,但它只在【叙事层】(research-pipeline 简报头)
    被消费——只是写进披露文字,从不影响一分钱。
  · allocation-discipline/allocate.py  消费一个扁平 {symbol: score} 信号文件,
    把 edge 最大处对齐到最大权重。但【谁来生成那个 score】从无定义。

断裂的后果(确认偏误工程化复发):
  若有人/工具把 10 条信号【简单平均】成一个 score 喂给 allocate,
  而其中 7 条是 price 派生(tech_screener/reverse_dcf/valuation_percentile/
  alpha/correlation/holder/southbound),那么这个"综合 edge"实际上 ~70%
  是 price 动量味道的——3 条基本面信号(moat/earnings_quality/balance)被
  7:3 票数碾压。这就是 signal-orthogonality 警告的"伪多重印证"直接渗进了
  目标权重。审计器看得见,却拦不住,因为它管不到 allocate 的输入。

本融合器做什么
------------------
给定每个标的的【按信号 id 的原始分】,它:
  1. 按 signal_registry.json 的 root_inputs 把信号归到【根输入簇】
     (price / income_statement / cash_flow / balance_sheet / shares_holders /
      southbound_flow / prediction_market / ...)。
  2. 簇内先聚合(默认均值)——同根的多条信号合成【一票】,
     不让 7 条 price 派生当 7 票。
  3. 簇间再聚合成单一 composite edge。默认【等簇权】(每个独立根输入一票),
     这正是『按独立根输入数计权而非信号条数计权』(signal-orthogonality 的裁定建议)。
  4. 输出 {symbol: composite_edge} —— 可直接喂给 allocate.py --signals。
     同时报告每个标的的【有效独立簇数】和【price 簇占比】,
     让人看见这个 edge 到底由几根真正独立的证据撑起来。

数据诚实
------------------
  · root_inputs 来自 signal-orthogonality 登记表(人工维护的单一事实源),
    本工具不复制一份,直接读它,避免双副本漂移。
  · 原始信号分需人工/上游工具喂入 JSON,本工具绝不取数、不编造分数。
  · 融合是确定性算术(簇内/簇间聚合),非预测、非买卖指令。
  · 未登记的信号 id 会被显式列出并拒绝纳入,不静默吞掉。

用法
------------------
  # 输入 JSON 形如:
  #   {"00700.HK": {"tech_screener": 0.8, "reverse_dcf": 0.6,
  #                 "moat_scorecard": -0.3, "southbound_flow": 0.5}}
  python3 edge_fusion.py --scores scores.json
  python3 edge_fusion.py --scores scores.json --out fused.json   # 落盘给 allocate 用
  python3 edge_fusion.py --scores scores.json --cluster-weight cap  # 簇间用 1/sqrt(n) 降权
  echo '{"X":{"alpha_check":0.5,"correlation_check":0.5}}' | python3 edge_fusion.py --scores -
"""
import argparse
import json
import os
import sys
import statistics

WS = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
REG_PATH = os.path.join(WS, "signal-orthogonality", "signal_registry.json")


def load_registry():
    """读 signal-orthogonality 的登记表作为单一事实源(不复制 root_inputs)。"""
    with open(REG_PATH, "r", encoding="utf-8") as f:
        reg = json.load(f)
    by_id = {s["id"]: s for s in reg["signals"]}
    return by_id


def primary_cluster(root_inputs):
    """把一条信号归到一个【根输入簇】。
    一条信号常有多根输入(如 holder_concentration=[price, shares_holders]),
    我们取它【最有辨识度的非 price 根】作为簇键——因为 price 是公共背景,
    真正让这条信号独立的是它额外引入的那根数据。若只有 price,则归 price 簇。"""
    non_price = [r for r in root_inputs if r != "price"]
    if non_price:
        # 取字典序最小以稳定;通常一条信号的非price根只有1个(最多2个)
        return sorted(non_price)[0]
    return "price"


def fuse_symbol(sig_scores, by_id, cluster_weight="equal"):
    """对单个标的: {signal_id: score} -> (composite_edge, detail)。
    detail 含每簇均值、有效簇数、price 簇占比、未登记信号。"""
    clusters = {}          # cluster_key -> [scores]
    cluster_members = {}   # cluster_key -> [signal_ids]
    unregistered = []
    for sid, sc in sig_scores.items():
        if sid not in by_id:
            unregistered.append(sid)
            continue
        ck = primary_cluster(by_id[sid]["root_inputs"])
        clusters.setdefault(ck, []).append(float(sc))
        cluster_members.setdefault(ck, []).append(sid)

    if not clusters:
        return None, {"unregistered": unregistered, "clusters": {}, "eff_clusters": 0,
                      "price_share": None}

    # 簇内聚合: 同根多条 -> 一票(均值)
    cluster_vote = {ck: statistics.mean(v) for ck, v in clusters.items()}

    # 簇间权重
    n_clusters = len(cluster_vote)
    if cluster_weight == "cap":
        # 1/sqrt(n): 簇越多越保守,避免少数极端簇主导;仍等簇内
        import math
        w = {ck: 1.0 / math.sqrt(n_clusters) for ck in cluster_vote}
    else:  # equal: 每个独立根输入一票
        w = {ck: 1.0 / n_clusters for ck in cluster_vote}

    composite = sum(cluster_vote[ck] * w[ck] for ck in cluster_vote)

    # price 簇在【票数】里的占比(独立性诊断的关键)
    price_votes = 1 if "price" in cluster_vote else 0
    price_share = price_votes / n_clusters

    detail = {
        "clusters": {ck: round(cluster_vote[ck], 4) for ck in cluster_vote},
        "cluster_members": cluster_members,
        "eff_clusters": n_clusters,
        "price_share": round(price_share, 3),
        "unregistered": unregistered,
    }
    return round(composite, 4), detail


def main():
    ap = argparse.ArgumentParser(description="正交性加权信号融合器(纯只读)")
    ap.add_argument("--scores", required=True,
                    help="JSON: {symbol: {signal_id: raw_score}};传 '-' 从 stdin 读")
    ap.add_argument("--out", help="把 {symbol: composite_edge} 落盘到此路径(喂 allocate.py --signals)")
    ap.add_argument("--cluster-weight", choices=["equal", "cap"], default="equal",
                    help="簇间权重: equal=每独立根一票(默认) / cap=1/sqrt(n)更保守")
    ap.add_argument("--quiet", action="store_true", help="cron 友好:仅当出现单簇支撑(eff=1)告警时输出")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.scores == "-" else open(args.scores, "r", encoding="utf-8").read()
    data = json.loads(raw)

    by_id = load_registry()

    fused = {}
    details = {}
    warnings = []
    for sym, sig_scores in data.items():
        comp, det = fuse_symbol(sig_scores, by_id, cluster_weight=args.cluster_weight)
        if comp is None:
            warnings.append(f"{sym}: 无任何已登记信号,跳过 (未登记={det['unregistered']})")
            continue
        fused[sym] = comp
        details[sym] = det
        if det["eff_clusters"] == 1:
            warnings.append(f"{sym}: edge 仅由【1 个独立根输入】支撑(簇={list(det['clusters'])}) = 单证据伪装成多印证")
        if det["price_share"] == 1.0:
            warnings.append(f"{sym}: 全部信号都是 price 派生 = 纯动量味,无基本面/资金面独立印证")
        if det["unregistered"]:
            warnings.append(f"{sym}: 未登记信号被排除 {det['unregistered']} (请先在 signal_registry.json 登记)")

    has_signal = bool(warnings)
    if args.quiet and not any("仅由【1 个独立根输入】" in w or "纯动量味" in w for w in warnings):
        # cron 友好: 只在最危险的"伪多印证/纯动量"时 surface
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(fused, f, ensure_ascii=False, indent=2)
        sys.exit(0)

    print("=== 正交性加权信号融合 (按独立根输入计权,非信号条数) ===")
    print(f"簇间权重模式: {args.cluster_weight}\n")
    for sym in sorted(fused, key=lambda s: -fused[s]):
        d = details[sym]
        print(f"  {sym}: composite_edge={fused[sym]:+.3f} | 有效独立簇={d['eff_clusters']} | price簇占比={d['price_share']:.0%}")
        for ck, v in d["clusters"].items():
            mem = ",".join(d["cluster_members"][ck])
            print(f"      [{ck}] 簇均值{v:+.3f}  ←  {mem}")
    if warnings:
        print("\n⚠️ 独立性告警:")
        for w in warnings:
            print(f"  · {w}")
    print("\n裁定: composite_edge 已把同根信号合成一票,可安全喂 allocate.py --signals。")
    print("      有效独立簇越多 = edge 越由真多重独立印证撑起;eff=1 时务必警惕伪印证。")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(fused, f, ensure_ascii=False, indent=2)
        print(f"\n已落盘融合 edge -> {args.out}")

    sys.exit(1 if has_signal else 0)


if __name__ == "__main__":
    main()
