-- StockChoose migration v0.2
-- Add thesis validity review tracking fields and stale review view.

BEGIN;

ALTER TABLE stock_theses
    ADD COLUMN IF NOT EXISTS validity_last_checked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS validity_check_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_validation_summary TEXT,
    ADD COLUMN IF NOT EXISTS last_supporting_data_snapshot TEXT,
    ADD COLUMN IF NOT EXISTS next_check_due_at TIMESTAMPTZ;

COMMENT ON COLUMN stock_theses.validity_last_checked_at IS '最近一次验证该论点有效性的时间，用于判断最近七天是否更新过论点有效性。';
COMMENT ON COLUMN stock_theses.validity_check_count IS '论点有效性验证次数。';
COMMENT ON COLUMN stock_theses.last_validation_summary IS '最近一次论点有效性验证摘要。';
COMMENT ON COLUMN stock_theses.last_supporting_data_snapshot IS '最近一次验证时使用的关键支撑数据快照。';
COMMENT ON COLUMN stock_theses.next_check_due_at IS '下一次建议检查时间。';

CREATE INDEX IF NOT EXISTS idx_stock_theses_validity_last_checked_at
    ON stock_theses(validity_last_checked_at);

CREATE OR REPLACE VIEW stale_stock_picks_for_thesis_review AS
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
    COUNT(st.id) AS thesis_count,
    MIN(st.validity_last_checked_at) AS oldest_thesis_validity_checked_at,
    MAX(st.validity_last_checked_at) AS newest_thesis_validity_checked_at,
    COUNT(*) FILTER (
        WHERE st.validity_last_checked_at IS NULL
           OR st.validity_last_checked_at < NOW() - INTERVAL '7 days'
    ) AS stale_thesis_count
FROM stock_picks sp
JOIN stock_theses st ON st.stock_pick_id = sp.id
WHERE sp.status IN ('active', 'watching')
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
VALUES ('v0.2', CURRENT_DATE, '增加论点有效性最近检查时间、检查次数、验证摘要、支撑数据快照和待复盘视图，用于每日 17 点复核最近七天未更新论点的股票。', 'docs/selection_rules.md')
ON CONFLICT (version) DO NOTHING;

COMMIT;
