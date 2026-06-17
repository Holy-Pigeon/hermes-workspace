-- StockChoose migration v0.9
-- 在主表 stock_picks 上常驻「入选后涨跌幅 + 盯市快照」字段，并清洗 target_price 口径。
--
-- 背景（与合伙人确认的需求）：
--   1. target_price 历史口径脏乱（康方 expected_upside_pct=55.2% 但 target_price 只隐含 15%），
--      且代码 0 引用、半数为空。重定义为「概率加权目标价」，与 expected_upside_pct 同源：
--          target_price = ROUND(selected_price * (1 + expected_upside_pct/100), 4)
--      使两者口径自洽。research_only / upside 为 NULL 的标的 → target_price 置 NULL。
--   2. 新增 gain_since_pick_pct：入选后涨跌幅 = 现价/selected_price - 1（百分比）。
--      过去这个值只在控制台 API 临时用「最近一次复核价」反推、且数据陈旧（停在复核日）。
--      改为常驻主表，由每日盯市脚本 refresh_pick_marks.py 刷新，扫主表即可见全池。
--   3. 配套 last_mark_price / last_mark_date：盯市快照价与日期，标注 gain 的「保鲜期」。
--      （与 stock_pick_reviews.current_price 互不冲突：reviews 是 LLM 复核时的人工记录，
--        last_mark_* 是每日自动盯市的机器快照，两条通路独立。）
--
-- 注意：本迁移只「加列 + 清洗 target_price」，不加「剩余期望收益」列（合伙人明确不要）。
-- 可回滚：见文件末尾 ROLLBACK 注释块。

BEGIN;

-- ── 1. 新增盯市字段 ──
ALTER TABLE stock_picks
    ADD COLUMN IF NOT EXISTS gain_since_pick_pct NUMERIC(8, 2),
    ADD COLUMN IF NOT EXISTS last_mark_price     NUMERIC(18, 4),
    ADD COLUMN IF NOT EXISTS last_mark_date      DATE;

COMMENT ON COLUMN stock_picks.gain_since_pick_pct IS
    '入选后涨跌幅% = last_mark_price/selected_price - 1。由每日盯市脚本 refresh_pick_marks.py 刷新，非复核时人工填。';
COMMENT ON COLUMN stock_picks.last_mark_price IS
    '最近一次盯市收盘价（机器快照，区别于 stock_pick_reviews.current_price 的人工复核价）。';
COMMENT ON COLUMN stock_picks.last_mark_date IS
    'gain_since_pick_pct / last_mark_price 的快照日期，用于判断数据保鲜期。';

-- ── 2. 清洗 target_price：重定义为「概率加权目标价」，与 expected_upside_pct 同源 ──
-- 有 upside 的：反推加权目标价。NULL upside（research_only 等）：target_price 也置 NULL，不留脏值。
UPDATE stock_picks
SET target_price = CASE
        WHEN expected_upside_pct IS NULL THEN NULL
        ELSE ROUND(selected_price * (1 + expected_upside_pct / 100.0), 4)
    END;

COMMENT ON COLUMN stock_picks.target_price IS
    '概率加权目标价 = selected_price*(1+expected_upside_pct/100)，与 expected_upside_pct 同源。NULL=无买入期望(research_only)。';

COMMIT;

-- ════════════════════════════════════════════════════════════════════
-- ROLLBACK（如需回滚，手动执行）：
-- BEGIN;
--   ALTER TABLE stock_picks DROP COLUMN IF EXISTS gain_since_pick_pct;
--   ALTER TABLE stock_picks DROP COLUMN IF EXISTS last_mark_price;
--   ALTER TABLE stock_picks DROP COLUMN IF EXISTS last_mark_date;
--   -- 注意：target_price 被本迁移覆盖为加权目标价，原始脏值无法自动还原；
--   --       如需旧值请从 db_dump_full.sql 或 git 历史中恢复。
-- COMMIT;
-- ════════════════════════════════════════════════════════════════════
