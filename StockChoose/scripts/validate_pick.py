#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""StockChoose 入库前语义校验门（validate_pick）。

根因修复：cmd_run_sql 过去裸执行 SQL，规则 v0.7 的口径铁律全靠 LLM 自觉，
导致最痛的错配——expected_upside_pct 本该填「概率加权期望收益」，
却可能被填成「牛市/基准潜在上涨空间」（大得多），DB 的 CHECK(>=0) 拦不住。

本模块在 SQL 执行后、commit 前对**本次新插入的 pick**做语义校验：
  硬错误 → 抛 ValidationError，调用方 rollback，绝不入库；
  警告 → 收集返回，放行但提示。

只校验「机制能客观判定」的规则；主观的概率合理性不硬卡（那是 LLM+人判断的事），
但对「几乎不可能为真」的数值（如加权收益>150%）视为强异常信号拦截。

被 db_helper.py run-sql 调用；也可独立 validate 当前全池：
  /usr/bin/python3 validate_pick.py --audit-pool
"""
import os
import sys
import json

# 规则 v0.7 阈值（与 docs/selection_rules.md 对齐）
ACTIVE_WEIGHTED_MIN = 25.0      # active 概率加权期望收益门槛 ≥25%
WATCHING_SUGGEST = 25.0         # watching 但达标 → 建议复审升级
MIN_THESES = 2                  # 每股核心论点下限（防注水，不再固定4条；条数随研究深度内生，不封顶）
UPSIDE_SANITY_MAX = 150.0       # 加权收益>150% = 几乎不可能, 强异常(疑似用牛市空间冒充)
THESIS_DETAIL_MIN_LEN = 30      # 论点详情过短疑似纯定性(仅警告)
# 论点全文（title+detail 合并）里必须出现情景/概率测算的证据词之一
SCENARIO_KEYWORDS = [
    "概率加权", "情景收益", "情景测算", "加权期望", "加权收益",
    "牛市", "基准情景", "熊市", "三情景", "上下行", "PE", "PS", "估值",
    "目标价", "目标估值", "目标市值",
]


class ValidationError(Exception):
    pass


def _fetch_new_picks(cur, pick_ids):
    """取指定 id 的 pick + 其论点，供校验。"""
    cur.execute(
        """
        SELECT id, stock_code, stock_name, status, expected_upside_pct,
               conviction_rating, score, pick_type
        FROM stock_picks WHERE id = ANY(%s)
        """,
        (pick_ids,),
    )
    cols = [d[0] for d in cur.description]
    picks = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.execute(
        """
        SELECT stock_pick_id, thesis_title, thesis_detail
        FROM stock_theses WHERE stock_pick_id = ANY(%s)
        """,
        (pick_ids,),
    )
    theses = {}
    for spid, title, detail in cur.fetchall():
        theses.setdefault(spid, []).append({"title": title or "", "detail": detail or ""})
    return picks, theses


def validate_picks(picks, theses_by_pick):
    """纯函数校验。返回 (errors, warnings)。"""
    errors, warnings = [], []
    for p in picks:
        pid = p["id"]
        name = f"{p.get('stock_code')}/{p.get('stock_name')}(id={pid})"
        status = (p.get("status") or "").strip()
        pick_type = (p.get("pick_type") or "investable").strip()
        is_research = pick_type == "research_only"
        upside = p.get("expected_upside_pct")
        upside = float(upside) if upside is not None else None
        ths = theses_by_pick.get(pid, [])

        # ── 硬错误（investable / research_only 共同要求：研究深度不掺水）──
        # 1. 论点数量 —— 下限防注水（≥2 条），不再固定 4 条；条数随研究深度内生、不封顶。
        #    真正防水的是下面的「情景证据词」「详情长度」质量门，而非数数。
        if len(ths) < MIN_THESES:
            errors.append(f"{name}: 论点仅 {len(ths)} 条 < 下限 {MIN_THESES}（研究太薄；条数本应随深度内生，但至少 2 条量化论据）")
        # 2. 必须有情景收益/估值分析证据（查论点全文 title+detail）
        has_scenario = any(
            any(k in (t["title"] + t["detail"]) for k in SCENARIO_KEYWORDS)
            for t in ths
        )
        if not has_scenario:
            errors.append(f"{name}: 论点全文无任何情景/估值测算证据词，无法证明做了量化分析")

        # 3. expected_upside_pct 数值校验 —— 分类型
        if is_research:
            # research_only：本质「不值得买但值得研究」，没有买入期望收益。
            # 允许 NULL；若填了值仍做合理性上限检查（防误填牛市空间），但不卡 >0/≥25 门槛。
            if upside is not None and upside > UPSIDE_SANITY_MAX:
                errors.append(
                    f"{name}: research_only 但 expected_upside_pct={upside}% > {UPSIDE_SANITY_MAX}% 几乎不可能为真，疑似误填"
                )
        else:
            # investable：必须填、>0、合理上限、active 须达门槛（原逻辑不变）
            if upside is None:
                errors.append(f"{name}: investable 类型 expected_upside_pct 为空，必须填概率加权期望收益")
            else:
                if upside <= 0:
                    errors.append(f"{name}: expected_upside_pct={upside} ≤0 非法")
                elif upside > UPSIDE_SANITY_MAX:
                    errors.append(
                        f"{name}: expected_upside_pct={upside}% > {UPSIDE_SANITY_MAX}% 几乎不可能为真，"
                        f"强烈疑似把『牛市/基准潜在上涨空间』误填进了『概率加权期望收益』字段——这正是要根除的口径错配"
                    )
                # active 必须达 25% 门槛
                if status == "active" and upside < ACTIVE_WEIGHTED_MIN:
                    errors.append(
                        f"{name}: status=active 但加权收益={upside}% < {ACTIVE_WEIGHTED_MIN}% 门槛，"
                        f"应降为 watching（规则 v0.7）"
                    )

        # 4. 类型与状态一致性 —— research_only 应处于 research 状态，反之亦然
        if is_research and status != "research":
            errors.append(f"{name}: pick_type=research_only 但 status={status}，纯研究类型状态应为 research")
        if status == "research" and not is_research:
            errors.append(f"{name}: status=research 但 pick_type={pick_type}，research 状态须配 research_only 类型")

        # ── 警告 ──
        if not is_research and status == "watching" and upside is not None and upside >= WATCHING_SUGGEST:
            warnings.append(f"{name}: watching 但加权收益={upside}%≥{WATCHING_SUGGEST}%，确认是否该升 active")
        short_theses = [t["title"][:20] for t in ths if len(t["detail"]) < THESIS_DETAIL_MIN_LEN]
        if short_theses:
            warnings.append(f"{name}: 论点详情过短疑似纯定性: {short_theses}")
        if not ths:
            warnings.append(f"{name}: 完全无论点")
    return errors, warnings


def validate_after_sql(cur, before_max_id):
    """run-sql 集成入口：校验本次新插入（id > before_max_id）的 picks。
    命中硬错误 → raise ValidationError（调用方据此 rollback）。
    返回 warnings 列表。
    """
    cur.execute("SELECT id FROM stock_picks WHERE id > %s ORDER BY id", (before_max_id,))
    new_ids = [r[0] for r in cur.fetchall()]
    if not new_ids:
        return []  # 本次没新增 pick（可能是纯论点/复核 SQL），不校验
    picks, theses = _fetch_new_picks(cur, new_ids)
    errors, warnings = validate_picks(picks, theses)
    if errors:
        msg = "入库校验失败（已回滚，未入库）：\n  - " + "\n  - ".join(errors)
        raise ValidationError(msg)
    return warnings


def get_max_pick_id(cur):
    cur.execute("SELECT COALESCE(MAX(id), 0) FROM stock_picks")
    return cur.fetchone()[0]


# ── 独立审计当前全池 ──
def _audit_pool():
    import psycopg2
    conn = psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ.get("PGDATABASE", "stockchoose"),
        user=os.environ.get("PGUSER", "postgres"),
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM stock_picks WHERE status IN ('active','watching','research') ORDER BY id")
            ids = [r[0] for r in cur.fetchall()]
            if not ids:
                print(json.dumps({"ok": True, "note": "池为空"}, ensure_ascii=False))
                return
            picks, theses = _fetch_new_picks(cur, ids)
            errors, warnings = validate_picks(picks, theses)
            print(json.dumps({
                "audited": len(picks),
                "errors": errors,
                "warnings": warnings,
                "ok": len(errors) == 0,
            }, ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    if "--audit-pool" in sys.argv:
        _audit_pool()
    else:
        print("用法: validate_pick.py --audit-pool  （或被 db_helper.py run-sql 调用）")
