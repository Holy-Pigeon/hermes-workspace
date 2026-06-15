-- StockChoose migration v0.8
-- 引入「纯研究类型」(research_only)：把个股研究库里「不值得买但值得研究」的标的
-- 及其论据正式纳入 StockChoose DB，与论点复核 cron 统一闭环管理。
--
-- 设计（与合伙人确认的思路一致）：
--   1. 新增 pick_type 字段：investable（买入候选，默认）/ research_only（纯研究对象）
--      —— status 仍表达生命周期(active/watching/closed/invalidated/research)，
--         pick_type 表达「是不是买入候选」，两者正交，不互相冒充。
--   2. status CHECK 增加 'research' —— research_only 票的常驻状态，
--      不参与 active/watching 的买入梯队，但持续复核论据有效性。
--   3. expected_upside_pct 放开 NOT NULL —— research_only 票本质没有买入期望收益，
--      允许 NULL；investable 票仍必须填（由 validate_pick.py 语义门把关，不在 DB 层硬卡）。
--   4. 复核视图纳入 research 状态 —— 让 research_only 票也进入「最近7天未复核」的复核循环。
--
-- 可回滚：见文件末尾 ROLLBACK 注释块。

BEGIN;

-- ── 1. 新增 pick_type 字段 ──
ALTER TABLE stock_picks
    ADD COLUMN IF NOT EXISTS pick_type VARCHAR(32) NOT NULL DEFAULT 'investable';

COMMENT ON COLUMN stock_picks.pick_type IS
    'investable=买入候选(走25%加权收益门槛); research_only=纯研究对象(不值得买但值得研究,豁免收益门槛,但仍须≥4条量化论据)。';

-- pick_type CHECK
ALTER TABLE stock_picks DROP CONSTRAINT IF EXISTS stock_picks_pick_type_check;
ALTER TABLE stock_picks ADD CONSTRAINT stock_picks_pick_type_check
    CHECK (pick_type::text = ANY (ARRAY['investable'::text, 'research_only'::text]));

-- ── 2. status CHECK 增加 'research' ──
ALTER TABLE stock_picks DROP CONSTRAINT IF EXISTS stock_picks_status_check;
ALTER TABLE stock_picks ADD CONSTRAINT stock_picks_status_check
    CHECK (status::text = ANY (ARRAY[
        'active'::text, 'watching'::text, 'closed'::text,
        'invalidated'::text, 'research'::text]));

-- ── 3. expected_upside_pct 放开 NOT NULL（research_only 允许 NULL）──
ALTER TABLE stock_picks ALTER COLUMN expected_upside_pct DROP NOT NULL;
-- CHECK 仍保留：非空时必须 0..150（不变）。NULL 由 CHECK 放行（CHECK 对 NULL 求值为 unknown=通过）。
COMMENT ON COLUMN stock_picks.expected_upside_pct IS
    '概率加权期望收益%(牛/基准/熊三情景加权)。investable 必填且 active 须≥25;research_only 可为 NULL(无买入期望)。';

-- 单一开仓唯一约束：research 状态不算「开仓」，不纳入 one_open_per_code 唯一约束。
-- (原约束只管 active/watching，research 天然不冲突，无需改。)

-- ── 4. 复核视图纳入 research 状态 ──
-- 用 DROP+CREATE 而非 CREATE OR REPLACE：新增 pick_type 列改变了列集合，
-- CREATE OR REPLACE 不允许在中间插列，必须先 DROP。
DROP VIEW IF EXISTS stale_stock_picks_for_thesis_review;
CREATE VIEW stale_stock_picks_for_thesis_review AS
SELECT
    sp.id AS stock_pick_id,
    sp.stock_code,
    sp.stock_name,
    sp.market,
    sp.selected_date,
    sp.selected_price,
    sp.sector,
    sp.expected_upside_pct,
    sp.status AS stock_status,
    sp.pick_type,
    COUNT(st.id) AS thesis_count,
    MIN(st.validity_last_checked_at) AS oldest_thesis_validity_checked_at,
    MAX(st.validity_last_checked_at) AS newest_thesis_validity_checked_at,
    COUNT(*) FILTER (
        WHERE st.validity_last_checked_at IS NULL
           OR st.validity_last_checked_at < NOW() - INTERVAL '7 days'
    ) AS stale_thesis_count
FROM stock_picks sp
JOIN stock_theses st ON st.stock_pick_id = sp.id
WHERE sp.status IN ('active', 'watching', 'research')
GROUP BY sp.id
HAVING COUNT(*) FILTER (
        WHERE st.validity_last_checked_at IS NULL
           OR st.validity_last_checked_at < NOW() - INTERVAL '7 days'
    ) > 0
ORDER BY
    MIN(st.validity_last_checked_at) NULLS FIRST,
    sp.selected_date ASC,
    sp.id ASC;

INSERT INTO rule_versions (version, effective_date, change_summary, document_path)
VALUES ('v0.8', CURRENT_DATE,
    '引入 pick_type(investable/research_only) 与 status=research：把个股研究库「不值得买但值得研究」的标的及论据纳入 DB，三个 cron(论点复核+索引重建+研究note入库)整合为统一闭环;research_only 豁免收益门槛但保留≥4条量化论据要求,upside 放开 NULL。',
    'docs/selection_rules.md')
ON CONFLICT (version) DO NOTHING;

COMMIT;

-- ════════════════════════════════════════════════════════════════════
-- ROLLBACK（如需回滚，手动执行下列语句）：
-- BEGIN;
--   DROP VIEW IF EXISTS stale_stock_picks_for_thesis_review;
--   -- 恢复原视图(只含 active/watching、无 pick_type 列)：见 migration 002
--   ALTER TABLE stock_picks DROP CONSTRAINT IF EXISTS stock_picks_status_check;
--   ALTER TABLE stock_picks ADD CONSTRAINT stock_picks_status_check
--     CHECK (status::text = ANY (ARRAY['active','watching','closed','invalidated']::text[]));
--   -- 注意:回滚前须先把所有 status='research' 的行改成别的状态,否则 CHECK 失败
--   ALTER TABLE stock_picks DROP CONSTRAINT IF EXISTS stock_picks_pick_type_check;
--   ALTER TABLE stock_picks DROP COLUMN IF EXISTS pick_type;
--   -- 注意:恢复 expected_upside_pct NOT NULL 前须先填补所有 NULL 值
--   ALTER TABLE stock_picks ALTER COLUMN expected_upside_pct SET NOT NULL;
-- COMMIT;
-- ════════════════════════════════════════════════════════════════════
