# StockChoose

本目录用于维护“未来一年具备 50%+ 潜在涨幅股票池”的筛选规则、数据库和后续复盘记录。

## 目录结构

```text
StockChoose/
├── README.md
├── docs/
│   └── selection_rules.md      # 可持续迭代的选股规则文档
├── db/
│   ├── schema.sql              # PostgreSQL 表结构
│   ├── init_db.sh              # 创建 stockchoose 数据库并应用 schema
│   ├── start_postgres.sh       # 启动本地 PostgreSQL，不依赖 systemd
│   └── stop_postgres.sh        # 停止本地 PostgreSQL
├── pgdata/                     # PostgreSQL 本地数据目录
└── logs/
    └── postgres.log            # PostgreSQL 日志
```

## 数据库

已安装本地 PostgreSQL，并初始化数据库：

- 数据库名：`stockchoose`
- 默认用户：`postgres`
- 默认端口：`5432`
- 数据目录：`/projects/StockChoose/pgdata`

由于当前运行环境不支持 systemd，PostgreSQL 通过 `pg_ctl` 在项目目录下运行。

### 启动数据库

```bash
/projects/StockChoose/db/start_postgres.sh
```

### 停止数据库

```bash
/projects/StockChoose/db/stop_postgres.sh
```

### 初始化/更新表结构

```bash
/projects/StockChoose/db/init_db.sh
```

### 连接数据库

```bash
sudo -u postgres psql -d stockchoose
```

## 核心表

### 1. stock_picks

股票池主表，每条记录代表某只股票在某天入选。

关键字段：

- `stock_code`：股票代码
- `stock_name`：名称
- `selected_date`：入选日期
- `selected_price`：入选价格
- `sector`：所在板块
- `expected_upside_pct`：预期涨幅
- `target_price`：目标价
- `target_market_cap`：目标市值
- `conviction_rating`：确定性评级
- `score`：综合评分
- `status`：当前状态

### 2. stock_theses

核心论点子表，一只股票可对应多个论点。

关键字段：

- `stock_pick_id`：关联股票池主表 ID
- `thesis_title`：论点标题
- `thesis_detail`：论点详情
- `still_valid`：是否仍然成立
- `status`：论点状态：`valid` / `needs_review` / `invalidated`
- `key_supporting_data`：关键支撑数据
- `invalidation_condition`：失效条件
- `last_checked_date`：最近检查日期
- `validity_last_checked_at`：最近一次验证论点有效性的时间，用于判断最近 7 天是否更新过
- `validity_check_count`：论点有效性验证次数
- `last_validation_summary`：最近一次论点有效性验证摘要
- `last_supporting_data_snapshot`：最近一次验证时使用的关键支撑数据快照
- `next_check_due_at`：下一次建议检查时间

### 3. stock_pick_reviews

复盘记录表，用于记录每周/每次复盘结论。

### 4. rule_versions

筛选规则版本表，用于记录 `docs/selection_rules.md` 的演进。

## 示例：插入一只股票

```sql
INSERT INTO stock_picks (
    stock_code,
    stock_name,
    market,
    selected_date,
    selected_price,
    currency,
    sector,
    expected_upside_pct,
    target_price,
    conviction_rating,
    score,
    notes
) VALUES (
    '09992.HK',
    '泡泡玛特',
    'HK',
    CURRENT_DATE,
    175.70,
    'HKD',
    '全球化消费品牌/潮玩IP',
    50.00,
    263.55,
    'medium_high',
    80,
    '示例：海外增长、IP矩阵、估值修复共同驱动。'
)
RETURNING id;
```

插入论点：

```sql
INSERT INTO stock_theses (
    stock_pick_id,
    thesis_title,
    thesis_detail,
    still_valid,
    status,
    key_supporting_data,
    invalidation_condition,
    last_checked_date
) VALUES (
    1,
    '海外收入高增长带来估值重估',
    '公司海外收入快速增长，美洲和欧洲市场仍处早期，若门店扩张和单店效率持续，可能从中国消费股重估为全球IP消费平台。',
    TRUE,
    'valid',
    '2025年海外多个区域收入高速增长，美洲同比大幅增长。',
    '海外收入增速连续两个季度明显低于预期，或海外单店模型恶化。',
    CURRENT_DATE
);
```

## 规则迭代流程

当发现筛选规则存在错误或需要优化时：

1. 修改 `docs/selection_rules.md`；
2. 在文档底部 `版本记录` 增加一行；
3. 在数据库 `rule_versions` 表插入新版本记录；
4. 后续选股时使用最新版本规则。

示例：

```sql
INSERT INTO rule_versions (version, effective_date, change_summary, document_path)
VALUES ('v0.2', CURRENT_DATE, '修正估值打分权重，增加现金流约束。', 'docs/selection_rules.md');
```

## 后续建议

已配置两个自动化定时任务：

1. 每天 08:00：按照 `docs/selection_rules.md` 筛选 3 只股票，写入 `stock_picks`，并把核心论点和关键支撑数据写入 `stock_theses`；
2. 每天 17:00：从 `stale_stock_picks_for_thesis_review` 中选 5 只最近 7 天未更新论点有效性的股票，验证其支持论点是否仍成立，并更新论点状态。

后续可以继续增加：

1. Python 入库脚本；
2. 行情价格自动更新；
3. 每周复盘自动报表；
4. 规则版本和股票表现之间的回测分析。
