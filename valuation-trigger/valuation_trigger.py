#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
valuation-trigger · 估值触发观察哨（SOUL「等合理价格」的自动化纵向监控）

元层缺口（非缺某只票）:
  发现侧已建成 4 个正交镜头(tech_screener 价值 / quality_screener 质量 / us_tech_scout 美股 /
  research-pipeline 编排), 每周吐出一批「好生意」候选, 并对每个候选用 reverse_dcf 算出
  「当前价 price-in 了多高的增速」。**但这个隐含增速只是一次性打印, 没有任何东西纵向跟踪它、
  没有任何东西在它跌进合理区时告警。** 段永平/巴菲特范式是「找到伟大生意, 然后等一个合理价格」——
  「好生意」那半边系统建满了, 「等合理价格」那半边只有一张每周打印的纸, 没人盯。
  本工具就是那个「盯价格的人」: 把每期 dossier 的隐含增速快照存档, 与该生意「已兑现的真实增速」
  比对, 当某个已通过质量门槛的好生意, 其「价格要求的增速」明显低于「它实际在交付的增速」时,
  说明市场对一门好生意给了保守定价 → 进入「值得人工深挖建仓」的观察窗口, 推送告警。

它不做什么:
  - 不发明新数据: 只解析 research-pipeline 已落盘的 dossier(reverse_dcf 一手结论)
  - 不下买卖指令: 输出是「该认真看这个价位了」的信号, 须人工补 thesis + 一手核验
  - 不做线性外推: 已兑现增速(近一年 YoY)只作「生意当前动能」的参照, 故意用最保守的
    退出倍数档(15x)算价格要求, 并要求显著安全垫, 对抗「过去高增长→未来必高增长」的偏误

信号逻辑(margin of safety):
  对每个候选, 取 reverse_dcf 在**保守退出倍数 15x** 下的隐含年化增速 g_req(价格要求的增速),
  与发现层「近一年净利 YoY」g_now(生意已兑现的增速)比对:
    安全垫 = g_now - g_req
  当 安全垫 ≥ MARGIN_PP(默认 10pp) 且 g_req ≤ G_REQ_CAP(默认 20%, 绝对低门槛护栏) → 🟢买入区候选
  当上期不在买入区、本期进入 → 触发「新进买入区」告警(纵向穿越才推, 避免每周重复刷屏)
  纯解析+比对, 零写盘外部状态, 只读 dossier + 自己的 history.json
"""
import json, re, sys, os, glob, datetime, pathlib

ROOT = pathlib.Path(__file__).resolve().parent
DOSSIER_DIR = ROOT.parent / "research-pipeline" / "dossiers"
HISTORY = ROOT / "history.json"

# 参数(护栏型, 偏保守, 对抗确认偏误/线性外推)
REF_EXIT_MULT = 15      # 用最保守退出倍数档算「价格要求的增速」
MARGIN_PP = 10.0        # 安全垫: 已兑现增速须超价格要求至少这么多 pp
G_REQ_CAP = 20.0        # 绝对护栏: 价格要求的增速本身须 ≤ 此值(否则即便有安全垫也是高预期定价)

CAND_HDR = re.compile(r"^##\s+([🏰⭐🔥💎🧱🔍🔗])?\s*(.+?)\s*$")
NPYOY = re.compile(r"净利YoY\s*([-\d.]+)%")
PRICE = re.compile(r"现价\s*([-\d.]+)\s*[@|]")
EXIT_G = re.compile(r"退出倍数\s*(\d+)x\s*→\s*隐含年化净利增速\s*g\s*=\s*([-\d.]+)%")


def parse_dossier(path):
    """解析一份 dossier → {name: {price, g_now, g_req_at_15x, flag, date}}"""
    txt = pathlib.Path(path).read_text(encoding="utf-8")
    # dossier 文件名带日期
    m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path))
    ddate = m.group(1) if m else ""
    out = {}
    cur = None
    for line in txt.splitlines():
        h = CAND_HDR.match(line)
        if h and h.group(2) and "尽调" not in line and "估值层" not in line and "发现层" not in line:
            # 候选标题行(## ⭐ 名称) —— 排除小节标题(### 开头不会进这里, 但 ## 误命中防御)
            name = h.group(2).strip()
            if name in ("待人工/后续研究 cron 深挖 (TODO)",):
                cur = None
                continue
            cur = name
            out[cur] = {"flag": (h.group(1) or "").strip(), "date": ddate,
                        "price": None, "g_now": None, "g_req": None}
            continue
        if cur is None:
            continue
        mp = PRICE.search(line)
        if mp and out[cur]["price"] is None:
            try:
                out[cur]["price"] = float(mp.group(1))
            except ValueError:
                pass
        mn = NPYOY.search(line)
        if mn and out[cur]["g_now"] is None:
            try:
                out[cur]["g_now"] = float(mn.group(1))
            except ValueError:
                pass
        me = EXIT_G.search(line)
        if me and int(me.group(1)) == REF_EXIT_MULT:
            try:
                out[cur]["g_req"] = float(me.group(2))
            except ValueError:
                pass
    # 只保留三要素齐全的
    return {k: v for k, v in out.items()
            if v["g_now"] is not None and v["g_req"] is not None and v["price"] is not None}


def in_buy_zone(rec):
    margin = rec["g_now"] - rec["g_req"]
    return (margin >= MARGIN_PP) and (rec["g_req"] <= G_REQ_CAP), margin


def load_history():
    if HISTORY.exists():
        try:
            return json.loads(HISTORY.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def latest_dossier():
    files = sorted(glob.glob(str(DOSSIER_DIR / "dossier_*.md")))
    return files[-1] if files else None


def main():
    quiet = "--quiet" in sys.argv
    write = "--no-write" not in sys.argv
    dpath = latest_dossier()
    if not dpath:
        print("[valuation-trigger] 无 dossier 可解析(research-pipeline 尚未产出)", file=sys.stderr)
        sys.exit(0)

    parsed = parse_dossier(dpath)
    if not parsed:
        print(f"[valuation-trigger] {os.path.basename(dpath)} 未解析出任何带估值的候选", file=sys.stderr)
        sys.exit(0)

    hist = load_history()           # {name: {last_in_zone: bool, last_seen: date, ...}}
    new_entries = []                # 本期「新进买入区」
    in_zone_now = []                # 本期所有在买入区的
    snapshot = {}

    for name, rec in parsed.items():
        zone, margin = in_buy_zone(rec)
        prev = hist.get(name, {})
        prev_zone = prev.get("last_in_zone", False)
        snapshot[name] = {
            "date": rec["date"], "flag": rec["flag"], "price": rec["price"],
            "g_now": rec["g_now"], "g_req15x": rec["g_req"],
            "margin_pp": round(margin, 1), "in_zone": zone,
        }
        if zone:
            in_zone_now.append((name, rec, margin))
            if not prev_zone:
                new_entries.append((name, rec, margin))

    # 更新 history
    if write:
        newhist = dict(hist)
        for name, rec in parsed.items():
            zone, margin = in_buy_zone(rec)
            newhist[name] = {"last_in_zone": zone, "last_seen": rec["date"],
                             "g_now": rec["g_now"], "g_req15x": rec["g_req"]}
        HISTORY.write_text(json.dumps(newhist, ensure_ascii=False, indent=2), encoding="utf-8")

    # 输出
    src = os.path.basename(dpath)
    if not quiet:
        print(f"=== valuation-trigger @ {src}  (退出倍数{REF_EXIT_MULT}x基准, 安全垫≥{MARGIN_PP}pp, g_req≤{G_REQ_CAP}%) ===")
        for name, s in sorted(snapshot.items(), key=lambda kv: -kv[1]["margin_pp"]):
            mark = "🟢买入区" if s["in_zone"] else "  观察"
            print(f"{mark} {s['flag']}{name}: 价格要求增速 {s['g_req15x']:.1f}% | "
                  f"已兑现净利YoY {s['g_now']:.1f}% | 安全垫 {s['margin_pp']:+.1f}pp | 现价 {s['price']}")

    if new_entries:
        lines = [f"【估值触发·新进买入区】{src} 解析出 {len(new_entries)} 个好生意跌入合理价格观察窗:"]
        for name, rec, margin in new_entries:
            lines.append(
                f"• {rec['flag']}{name}: 现价{rec['price']}只 price-in {rec['g_req']:.1f}% 增速(15x保守退出), "
                f"而它近一年净利已兑现 {rec['g_now']:.1f}% → 安全垫{margin:+.1f}pp。"
                f"市场对这门已过质量门槛的好生意给了保守定价。")
        lines.append("⚠️ 这是「该认真看这个价位了」的信号, 非买卖指令; 须人工补 thesis + 一手财报核验 + "
                     "判断已兑现增速可持续性(防线性外推), 通过后登记 prediction-ledger + 进 StockChoose 复审。")
        print("\n".join(lines))
        sys.exit(1)   # cron 友好: 有新信号 exit1
    elif not quiet:
        zn = len(in_zone_now)
        print(f"\n本期无「新进买入区」穿越(当前买入区内 {zn} 个, 均非本期新进, 不重复推送)。")
    sys.exit(0)


if __name__ == "__main__":
    main()
