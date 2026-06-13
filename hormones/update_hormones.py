#!/usr/bin/env python3
"""
激素系统引擎 — 稳态控制器(homeostatic controller),非情绪随机数。

设计哲学:门控型(冲动→先过闸),非驱动型(渴望→行动)。
每次调用流程: 读 state → 按真实时长惰性衰减 → 按本轮客观事件加减 → 封顶/封底 → 写回 → 落 log。

CLI 用法:
  # 上报一轮事件(创新引擎跑完时调用),事件用 key:count 形式,逗号分隔
  python3 update_hormones.py tick --events "unexplained_anomaly:3,bullish_urge:1"
  python3 update_hormones.py tick --events "produced_alpha:1"     # 发了alpha→好奇素清零
  python3 update_hormones.py tick --events "user_traded:1"        # 用户交易→克制素↑
  python3 update_hormones.py tick                                  # 无事件,仅衰减(空轮)

  # 只读当前状态(先惰性衰减再打印,不落事件)
  python3 update_hormones.py status

输出: JSON 到 stdout,含衰减后各激素值、是否过阈值(校准期仅标注不驱动)、本轮变更摘要。
"""
import json
import math
import sys
import argparse
from datetime import datetime, timezone, timedelta

STATE_PATH = "/Users/xiaogexu/hermes-workspace/hormones/state.json"
LOG_PATH = "/Users/xiaogexu/hermes-workspace/hormones/hormones.log"
TZ = timezone(timedelta(hours=8))  # Asia/Shanghai


def now():
    return datetime.now(TZ)


def parse_ts(s):
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return now()


def load_state():
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(st):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def log(line):
    ts = now().isoformat()
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{ts}  {line}\n")


def decay(st, t_now):
    """惰性衰减: 按距上次更新的真实小时数,指数衰减回 baseline。"""
    last = parse_ts(st["last_updated"])
    dt_h = max(0.0, (t_now - last).total_seconds() / 3600.0)
    changes = []
    for name, h in st["hormones"].items():
        cfg = st["config"][name]
        base = cfg.get("baseline", 0.0)
        rate = cfg["decay_per_hour"]
        old = h["value"]
        # 向 baseline 指数回归: new = base + (old-base)*exp(-rate*dt)
        new = base + (old - base) * math.exp(-rate * dt_h)
        h["value"] = round(new, 3)
        if abs(new - old) > 0.001:
            changes.append(f"{name} {old:.2f}->{new:.2f}(衰减{dt_h:.2f}h)")
    return dt_h, changes


def apply_events(st, events):
    """按 event_weights 把客观事件计数转成激素增量。"""
    changes = []
    for ev, count in events.items():
        if ev not in st["event_weights"]:
            changes.append(f"!!未知事件 {ev} 已忽略")
            continue
        weights = st["event_weights"][ev]
        for hname, w in weights.items():
            if hname == "_doc":
                continue
            if hname not in st["hormones"]:
                continue
            delta = w * count
            old = st["hormones"][hname]["value"]
            st["hormones"][hname]["value"] = round(old + delta, 3)
            changes.append(f"{hname} {old:.2f} {'+' if delta>=0 else ''}{delta:.1f} (事件 {ev}x{count})")
    return changes


def clamp(st):
    """封顶/封底: 防单一驱动力无限累积绑架行为(对应'封顶仓位'纪律)。"""
    notes = []
    for name, h in st["hormones"].items():
        cfg = st["config"][name]
        cap = cfg["cap"]
        v = h["value"]
        if v > cap:
            h["value"] = cap
            notes.append(f"{name} 触顶 clamp {v:.2f}->{cap}")
        if v < 0:
            h["value"] = 0.0
            notes.append(f"{name} 触底 clamp {v:.2f}->0")
    return notes


def threshold_report(st):
    """过阈值标注。校准期仅记录,不驱动行为。"""
    fired = []
    for name, h in st["hormones"].items():
        cfg = st["config"][name]
        if h["value"] >= cfg["threshold"]:
            fired.append({"hormone": name, "value": h["value"], "threshold": cfg["threshold"]})
    return fired


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["tick", "status"])
    ap.add_argument("--events", default="", help="逗号分隔的 key:count,如 unexplained_anomaly:3,bullish_urge:1")
    args = ap.parse_args()

    st = load_state()
    t_now = now()

    dt_h, decay_changes = decay(st, t_now)

    event_changes = []
    events = {}
    if args.cmd == "tick" and args.events.strip():
        for part in args.events.split(","):
            part = part.strip()
            if not part:
                continue
            k, _, v = part.partition(":")
            try:
                events[k.strip()] = float(v)
            except ValueError:
                events[k.strip()] = 1.0
        event_changes = apply_events(st, events)

    clamp_notes = clamp(st)
    st["last_updated"] = t_now.isoformat()
    if args.cmd == "tick":
        save_state(st)

    fired = threshold_report(st)

    # 落 log (仅 tick 写)
    if args.cmd == "tick":
        summary_bits = []
        if events:
            summary_bits.append("events=" + ",".join(f"{k}x{int(v)}" for k, v in events.items()))
        if decay_changes:
            summary_bits.append("decay[" + "; ".join(decay_changes) + "]")
        if event_changes:
            summary_bits.append("apply[" + "; ".join(event_changes) + "]")
        if clamp_notes:
            summary_bits.append("clamp[" + "; ".join(clamp_notes) + "]")
        vals = " ".join(f"{n}={h['value']:.1f}" for n, h in st["hormones"].items())
        fired_str = ",".join(f["hormone"] for f in fired) if fired else "none"
        log(f"TICK | {vals} | fired={fired_str} | " + " | ".join(summary_bits))

    out = {
        "phase": st["phase"],
        "as_of": t_now.isoformat(),
        "hours_since_last": round(dt_h, 3),
        "hormones": {n: h["value"] for n, h in st["hormones"].items()},
        "thresholds_fired": fired,
        "note": "校准期: 过阈值仅记录,不驱动行为" if st["phase"] == "calibration" else "active: 过阈值可驱动行为",
        "changes": {
            "decay": decay_changes,
            "events": event_changes,
            "clamp": clamp_notes,
        },
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
