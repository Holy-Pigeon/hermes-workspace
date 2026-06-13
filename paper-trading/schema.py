"""
模拟持仓系统 (Paper Trading) — schema 初始化
=================================================
纸面账户，不动真金白银。总资金 1 亿，分多个账户给不同策略项目。
回测的基石：所有项目（StockChoose / 创新引擎产出的策略 / 期货期权实验）都用模拟账户执行决策，
真实价格驱动盯市，积累带时间戳的净值曲线 → 才能做严肃回测。

设计要点：
- accounts: 不同项目/策略一个账户，各自分配初始资金。
- positions: 当前持仓（支持股票/期货/期权，asset_type 区分）。
- trades: 每笔买卖流水（不可变审计轨迹）。
- nav_snapshots: 每次盯市的账户净值快照 → 回测曲线的数据源。
- 现金 = 账户内未投资金额，自动随交易增减。
全部金额以账户 base_currency 记账（默认 CNY），跨币种标的在 trade 里记原币种价+汇率。
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_trading.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,          -- 账户名（=项目/策略名）
    strategy        TEXT NOT NULL,                 -- 策略描述
    base_currency   TEXT NOT NULL DEFAULT 'CNY',
    initial_capital REAL NOT NULL,                 -- 初始分配资金
    cash            REAL NOT NULL,                 -- 当前现金（随交易增减）
    status          TEXT NOT NULL DEFAULT 'active',-- active/closed
    note            TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL REFERENCES accounts(id),
    asset_type      TEXT NOT NULL,                 -- stock/futures/option
    symbol          TEXT NOT NULL,                 -- 标的代码
    name            TEXT,                          -- 标的名称
    market          TEXT,                          -- 市场（A股/HKEX/US/...）
    currency        TEXT NOT NULL DEFAULT 'CNY',   -- 标的计价币种
    direction       TEXT NOT NULL DEFAULT 'long',  -- long/short
    quantity        REAL NOT NULL,                 -- 持仓数量（股/张/手）
    avg_cost        REAL NOT NULL,                 -- 平均成本（原币种，每单位）
    multiplier      REAL NOT NULL DEFAULT 1,       -- 合约乘数（期货期权用，股票=1）
    fx_rate         REAL NOT NULL DEFAULT 1,       -- 原币种->账户base汇率（估值用）
    last_price      REAL,                          -- 最近盯市价（原币种）
    opened_at       TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    meta            TEXT,                          -- JSON: 期权行权价/到期日/期货合约月等
    UNIQUE(account_id, asset_type, symbol, direction)
);

CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL REFERENCES accounts(id),
    asset_type      TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    name            TEXT,
    market          TEXT,
    currency        TEXT NOT NULL DEFAULT 'CNY',
    side            TEXT NOT NULL,                 -- buy/sell
    direction       TEXT NOT NULL DEFAULT 'long',
    quantity        REAL NOT NULL,
    price           REAL NOT NULL,                 -- 成交价（原币种）
    multiplier      REAL NOT NULL DEFAULT 1,
    fx_rate         REAL NOT NULL DEFAULT 1,       -- 原币种->账户base汇率
    fee             REAL NOT NULL DEFAULT 0,       -- 手续费（账户base币种）
    realized_pnl    REAL DEFAULT 0,                -- 平仓时实现盈亏（账户base币种）
    reason          TEXT,                          -- 决策理由（哪个项目/什么逻辑）
    traded_at       TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    meta            TEXT
);

CREATE TABLE IF NOT EXISTS nav_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL REFERENCES accounts(id),
    snapshot_date   TEXT NOT NULL,                 -- YYYY-MM-DD
    cash            REAL NOT NULL,
    positions_value REAL NOT NULL,                 -- 持仓市值（账户base币种）
    total_nav       REAL NOT NULL,                 -- 总净值 = cash + positions_value
    pnl_pct         REAL,                          -- 相对 initial_capital 的累计收益率
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(account_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_positions_account ON positions(account_id);
CREATE INDEX IF NOT EXISTS idx_trades_account ON trades(account_id);
CREATE INDEX IF NOT EXISTS idx_nav_account_date ON nav_snapshots(account_id, snapshot_date);
"""

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"Schema initialized at {DB_PATH}")

if __name__ == "__main__":
    init_db()
