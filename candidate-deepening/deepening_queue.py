#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
candidate-deepening · 候选深研待办队列构建器 (确定性·只读)

它解决什么(系统级 gap, 非缺某只票):
  发现→编排→[深度note authoring]→计分/校准 这条研究流水线里, 中间的
  「把候选 stub 深挖成带 thesis+证伪条件+prediction-ledger 登记的 conviction note」
  这一环, 自 2026-06-13 起 orphaned(创新引擎转元层后无人继承)。结果:
    - research-pipeline 只产 stub(自陈"尽调起点非终稿");
    - research/note_*.md 冻结在 06-13;
    - 4 个计分/校准 meta 工具(call-alpha / alpha-attribution /
      prediction-ledger / signal-orthogonality)无新料可量, 空转。

本脚本不写 note(那是 LLM authoring cron 的判断动作), 只做确定性的事:
  读最新 dossier 的候选清单 + 对照 research/ 已有 note, 机械算出
  「哪些候选还没有 conviction note」= 深研待办队列, 输出 JSON / 人读清单。
  authoring cron 消费这个队列, 逐个深挖、写 note、登记 prediction-ledger。

数据诚实: 纯读本地文件(dossier markdown + note 文件名/正文 grep), 取不到
  就报空绝不编造; 候选↔note 的匹配按股票代码/ticker 字面命中, 宁可漏报
  (标"疑似未深研")不误报已深研。
"""
import os
import re
import sys
import json
import glob
import argparse
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
WS = os.path.join(HOME, "hermes-workspace")
DOSSIER_DIR = os.path.join(WS, "research-pipeline", "dossiers")
RESEARCH_DIR = os.path.join(WS, "research")

# dossier 候选标题行形如:  "## ⭐ 海康威视(002415)"  或  "## 🏰 AAPL"
CAND_RE = re.compile(r"^#{1,3}\s*[⭐🏰🧱💎🔭]\s*(.+?)\s*$")
# 从标题里抽 A 股 6 位代码 或 港股 5 位 或 美股纯字母 ticker
A_CODE_RE = re.compile(r"\((\d{6})\)")
HK_CODE_RE = re.compile(r"\((\d{5})\)")
US_TICK_RE = re.compile(r"^([A-Z]{1,6})$")


def latest_dossier():
    files = sorted(glob.glob(os.path.join(DOSSIER_DIR, "dossier_*.md")))
    return files[-1] if files else None


def parse_candidates(path):
    """从 dossier 抽候选: 返回 [{title, key, kind}]"""
    out = []
    if not path or not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = CAND_RE.match(line.rstrip())
            if not m:
                continue
            title = m.group(1).strip()
            # 过滤掉非候选的装饰性小标题(发现层/估值层等不会带 emoji 前缀, 已被 regex 排除)
            am = A_CODE_RE.search(title)
            hm = HK_CODE_RE.search(title)
            if am:
                key, kind = am.group(1), "A"
            elif hm:
                key, kind = hm.group(1), "HK"
            else:
                um = US_TICK_RE.match(title)
                if um:
                    key, kind = um.group(1), "US"
                else:
                    continue  # 无法定位标的代码, 跳过(不猜)
            out.append({"title": title, "key": key, "kind": kind})
    # 去重(同一候选可能在多 sleeve 重复)
    seen, uniq = set(), []
    for c in out:
        if c["key"] in seen:
            continue
        seen.add(c["key"])
        uniq.append(c)
    return uniq


def _header_zone(txt):
    """取 note 的标的识别区 = 第一个 '---' 分隔线之前的 frontmatter(标题行+元数据块);
    无分隔线则退回前 12 行。conviction note 的真实主语(标题 + '标的:' 字段)只住在
    这一区, 正文里出现的代码/ticker 多是同业/供应链/对比的顺带提及, 不代表该 note
    是为它写的。只匹配 header zone = 兑现 docstring 承诺的'宁可漏报不误报已深研'。"""
    idx = txt.find("\n---")
    if idx != -1:
        return txt[:idx]
    return "\n".join(txt.splitlines()[:12])


def note_index():
    """返回 {note_file: header_zone_text}; 只保留标的识别区(标题+元数据), 不留全文,
    从机制上杜绝正文顺带提及被误判成'已深研'。"""
    notes = glob.glob(os.path.join(RESEARCH_DIR, "note_*.md"))
    blobs = {}
    for n in notes:
        try:
            with open(n, encoding="utf-8") as f:
                blobs[os.path.basename(n)] = _header_zone(f.read())
        except Exception:
            blobs[os.path.basename(n)] = ""
    return blobs


def has_note(key, kind, blobs):
    """候选是否已有专属 conviction note: 按代码/ticker 命中 note 的标的识别区(header zone)。
    只认 header 不认正文, 避免一篇 NVDA note 顺带提 ASML/TSM 就把它们误标已深研、
    永久踢出深研队列(这正是 docstring 承诺要避免的'误报已深研')。"""
    hits = []
    for fn, txt in blobs.items():
        if kind == "US":
            # 美股 ticker 要求词边界, 避免 MA 命中 "format" 之类
            if re.search(r"\b" + re.escape(key) + r"\b", txt):
                hits.append(fn)
        else:
            if key in txt:
                hits.append(fn)
    return hits


def build_queue():
    dossier = latest_dossier()
    cands = parse_candidates(dossier)
    blobs = note_index()
    pending, covered = [], []
    for c in cands:
        hits = has_note(c["key"], c["kind"], blobs)
        rec = {**c, "notes": hits}
        if hits:
            covered.append(rec)
        else:
            pending.append(rec)
    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "dossier": os.path.basename(dossier) if dossier else None,
        "dossier_mtime": (
            datetime.fromtimestamp(os.path.getmtime(dossier)).isoformat()
            if dossier else None
        ),
        "candidate_count": len(cands),
        "pending_count": len(pending),
        "covered_count": len(covered),
        "pending": pending,
        "covered": covered,
        "research_dir_latest_note": _latest_note_date(blobs),
    }


def _latest_note_date(blobs):
    dates = []
    for fn in blobs:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", fn)
        if m:
            dates.append(m.group(1))
    return max(dates) if dates else None


def main():
    ap = argparse.ArgumentParser(description="候选深研待办队列(确定性只读)")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--quiet", action="store_true",
                    help="cron 友好: 无 pending 则静默 exit0, 有则 exit1")
    args = ap.parse_args()

    q = build_queue()

    if args.json:
        print(json.dumps(q, ensure_ascii=False, indent=2))
        sys.exit(1 if q["pending_count"] else 0)

    if args.quiet and q["pending_count"] == 0:
        sys.exit(0)

    print("=== 候选深研待办队列 (candidate-deepening) ===")
    if not q["dossier"]:
        print("⚠️ 未找到任何 dossier, 队列为空 (research-pipeline 还没产出?)")
        sys.exit(0)
    print(f"最新 dossier: {q['dossier']} (mtime {q['dossier_mtime']})")
    print(f"研究库最新 note 日期: {q['research_dir_latest_note']}")
    print(f"候选 {q['candidate_count']} | 已深研 {q['covered_count']} | "
          f"⏳ 待深研 {q['pending_count']}")
    if q["pending"]:
        print("\n⏳ 待深研 (无 conviction note, 等 authoring cron 深挖):")
        for c in q["pending"]:
            print(f"  • [{c['kind']}] {c['title']}  (key={c['key']})")
    if q["covered"]:
        print("\n✅ 已有 note:")
        for c in q["covered"]:
            print(f"  • [{c['kind']}] {c['title']} → {', '.join(c['notes'][:3])}")
    sys.exit(1 if q["pending_count"] else 0)


if __name__ == "__main__":
    main()
