-- StockChoose 股票池数据库初始化脚本
-- Database: stockchoose
-- Version: v0.1

BEGIN;

CREATE TABLE IF NOT EXISTS stock_picks (
    id BIGSERIAL PRIMARY KEY,
    stock_code VARCHAR(32) NOT NULL,
    stock_name VARCHAR(128) NOT NULL,
    market VARCHAR(32),
    selected_date DATE NOT NULL DEFAULT CURRENT_DATE,
    selected_price NUMERIC(18, 4) NOT NULL,
    currency VARCHAR(16) DEFAULT 'CNY',
    sector VARCHAR(128) NOT NULL,
    expected_upside_pct NUMERIC(8, 2) CHECK (expected_upside_pct IS NULL OR (expected_upside_pct >= 0 AND expected_upside_pct <= 150)),
    target_price NUMERIC(18, 4),
    target_market_cap NUMERIC(24, 4),
    conviction_rating VARCHAR(32) CHECK (conviction_rating IN ('high', 'medium_high', 'medium', 'watch')),
    score NUMERIC(5, 2) CHECK (score IS NULL OR (score >= 0 AND score <= 100)),
    status VARCHAR(32) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'watching', 'closed', 'invalidated', 'research')),
    pick_type VARCHAR(32) NOT NULL DEFAULT 'investable' CHECK (pick_type IN ('investable', 'research_only')),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (stock_code, selected_date)
);

COMMENT ON TABLE stock_picks IS '每日筛选出的股票池主表。每条记录代表某只股票在某个日期被纳入股票池。';
COMMENT ON COLUMN stock_picks.stock_code IS '股票代码，例如 09992.HK、AAPL、300750.SZ。';
COMMENT ON COLUMN stock_picks.stock_name IS '股票名称。';
COMMENT ON COLUMN stock_picks.selected_date IS '入选日期。';
COMMENT ON COLUMN stock_picks.selected_price IS '入选价格。';
COMMENT ON COLUMN stock_picks.sector IS '所在板块/行业方向。';
COMMENT ON COLUMN stock_picks.expected_upside_pct IS '预期涨幅百分比，例如 50.00 表示预期上涨 50%。';

CREATE TABLE IF NOT EXISTS stock_theses (
    id BIGSERIAL PRIMARY KEY,
    stock_pick_id BIGINT NOT NULL REFERENCES stock_picks(id) ON DELETE CASCADE,
    thesis_title VARCHAR(256) NOT NULL,
    thesis_detail TEXT NOT NULL,
    still_valid BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(32) NOT NULL DEFAULT 'valid' CHECK (status IN ('valid', 'needs_review', 'invalidated')),
    key_supporting_data TEXT NOT NULL,
    invalidation_condition TEXT,
    last_checked_date DATE,
    validity_last_checked_at TIMESTAMPTZ,
    validity_check_count INTEGER NOT NULL DEFAULT 0,
    last_validation_summary TEXT,
    last_supporting_data_snapshot TEXT,
    next_check_due_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE stock_theses IS '股票入选核心论点子表。一只股票可以对应多个核心论点，每个论点需要持续维护状态。';
COMMENT ON COLUMN stock_theses.still_valid IS '该核心论点是否仍然成立。';
COMMENT ON COLUMN stock_theses.key_supporting_data IS '关键支撑数据，例如业绩增速、订单、估值、行业价格、资金流等。';
COMMENT ON COLUMN stock_theses.invalidation_condition IS '该论点的失效条件。';

CREATE TABLE IF NOT EXISTS rule_versions (
    id BIGSERIAL PRIMARY KEY,
    version VARCHAR(32) NOT NULL UNIQUE,
    effective_date DATE NOT NULL DEFAULT CURRENT_DATE,
    change_summary TEXT NOT NULL,
    document_path TEXT NOT NULL DEFAULT 'docs/selection_rules.md',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE rule_versions IS '筛选规则文档版本记录。';

CREATE TABLE IF NOT EXISTS stock_pick_reviews (
    id BIGSERIAL PRIMARY KEY,
    stock_pick_id BIGINT NOT NULL REFERENCES stock_picks(id) ON DELETE CASCADE,
    review_date DATE NOT NULL DEFAULT CURRENT_DATE,
    current_price NUMERIC(18, 4),
    price_change_pct NUMERIC(8, 2),
    review_summary TEXT NOT NULL,
    action VARCHAR(32) NOT NULL CHECK (action IN ('keep', 'upgrade', 'downgrade', 'close', 'invalidate')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE stock_pick_reviews IS '股票池复盘表，用于记录每周/每次复盘结论。';

CREATE INDEX IF NOT EXISTS idx_stock_picks_code ON stock_picks(stock_code);
CREATE INDEX IF NOT EXISTS idx_stock_picks_selected_date ON stock_picks(selected_date DESC);
CREATE INDEX IF NOT EXISTS idx_stock_picks_status ON stock_picks(status);
CREATE INDEX IF NOT EXISTS idx_stock_theses_pick_id ON stock_theses(stock_pick_id);
CREATE INDEX IF NOT EXISTS idx_stock_theses_status ON stock_theses(status);
CREATE INDEX IF NOT EXISTS idx_stock_theses_validity_last_checked_at ON stock_theses(validity_last_checked_at);
CREATE INDEX IF NOT EXISTS idx_stock_pick_reviews_pick_id ON stock_pick_reviews(stock_pick_id);

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

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_stock_picks_updated_at ON stock_picks;
CREATE TRIGGER trg_stock_picks_updated_at
BEFORE UPDATE ON stock_picks
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_stock_theses_updated_at ON stock_theses;
CREATE TRIGGER trg_stock_theses_updated_at
BEFORE UPDATE ON stock_theses
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

INSERT INTO rule_versions (version, effective_date, change_summary, document_path)
VALUES ('v0.1', CURRENT_DATE, '初始版本：一年内 50%+ 潜在涨幅候选股筛选框架、打分模型、股票池维护规则。', 'docs/selection_rules.md')
ON CONFLICT (version) DO NOTHING;

INSERT INTO rule_versions (version, effective_date, change_summary, document_path)
VALUES ('v0.2', CURRENT_DATE, '增加论点有效性最近检查时间、检查次数、验证摘要、支撑数据快照和待复盘视图，用于每日 17 点复核最近七天未更新论点的股票。', 'docs/selection_rules.md')
ON CONFLICT (version) DO NOTHING;

INSERT INTO rule_versions (version, effective_date, change_summary, document_path)
VALUES ('v0.3', CURRENT_DATE, '明确 50%+ 空间只是入选条件，不能作为核心论据；新增护城河、利润可持续性和非线性外推约束；要求每只股票至少 4 条核心论点。', 'docs/selection_rules.md')
ON CONFLICT (version) DO NOTHING;

INSERT INTO rule_versions (version, effective_date, change_summary, document_path)
VALUES ('v0.4', CURRENT_DATE, '按真实买入决策标准升级：所有核心论据必须量化，包含当前基数、目标假设、桥接测算、情景/概率和失效阈值；纯定性论据不合格。', 'docs/selection_rules.md')
ON CONFLICT (version) DO NOTHING;

COMMIT;
