# 模拟持仓系统 (Paper Trading)

**性质**：纸面账户，不动真金白银。整个投资合伙体系的**回测基石**——所有项目（StockChoose / 创新引擎产出的策略 / 期权期货实验）都用模拟账户执行决策，真实价格驱动盯市，积累带时间戳的净值曲线 → 才能做严肃回测、用数据证明每个策略到底赚不赚钱。

**发起人**：用户（2026-06-11）。**状态**：building（已跑通，持续运营）。

## 为什么存在
StockChoose 那张 review 表只记相对涨跌，无法回答"如果真按它建仓、配多少钱、含汇率和费用，组合净值曲线长什么样"。光靠 cron+提示词无法回测。必须有一个真实记账的账户体系，回测时钟才能开始走。**每拖一天就少一天数据**，所以越早建越好。

## 总资金 1 亿，分账户（纸面，随时可改）
| 账户 | 策略 | 分配 | 占比 |
|---|---|---|---|
| stockchoose | A股/港股价值选股(跟StockChoose池) | 4000万 | 40% |
| us-tech-value | 美股科技/半导体价值长持 | 2500万 | 25% |
| options-lab | 纪律化期权(封顶仓位+买长ITM+不马丁) | 1000万 | 10% |
| futures-macro | 期货/宏观对冲(联动Polymarket) | 1000万 | 10% |
| innovation | 创新引擎新策略试验田 | 500万 | 5% |
| 现金储备 | 未分配(等机会) | 1000万 | 10% |

options-lab 是刻意设计：用模拟仓**用数据对照**纪律化期权打法 vs 用户"天天买call马丁式加仓亏40万"的负偏度打法，论期望值不论胜率。

## 技术栈
- SQLite 库 `paper_trading.db`，纯 Python stdlib，用 `/usr/bin/python3` 跑。
- 4 张表：accounts / positions / trades(不可变审计) / nav_snapshots(回测曲线数据源)。
- 跨币种：positions.fx_rate 记录原币种→账户base汇率，估值统一换算。港币用 HKD/CNY≈0.87(2026-06-11央行中间价86.975)。

## 常用命令
```bash
cd ~/hermes-workspace/paper-trading
/usr/bin/python3 pt.py report                 # 全账户总览
/usr/bin/python3 pt.py positions --account stockchoose
/usr/bin/python3 pt.py buy --account X --symbol 601138 --name 工业富联 --currency CNY --qty 1000 --price 73.75 --reason "..."
/usr/bin/python3 pt.py buy --account X --symbol 09926 --currency HKD --qty 1000 --price 87 --fx 0.87 --reason "..."  # 港币传 --fx
/usr/bin/python3 pt.py sell --account X --symbol 601138 --qty 500 --price 80 --reason "..."
/usr/bin/python3 pt.py mark --account X --symbol 601138 --price 75      # 盯市更新最新价
/usr/bin/python3 pt.py snapshot --account X    # 净值快照(回测数据点),默认今天
/usr/bin/python3 pt.py trades --account X      # 流水
```

## 待建（下一步）
- **定时盯市+快照 cron**：每个交易日收盘后用 akshare 拉所有持仓最新价 → mark → snapshot，自动积累净值曲线。这是回测数据的自动管道，否则要手动盯市。
- **回测分析脚本**：从 nav_snapshots 算年化收益/最大回撤/夏普/对比基准(沪深300/纳指)。
- us-tech-value / options-lab / futures-macro 账户尚空仓，等具体决策建仓。

## 初始建仓记录 (2026-06-11)
stockchoose 账户按 StockChoose active 池真实入选价建仓 4 只（康方生物/工业富联/小商品城/紫金矿业），等权各约800万。watching 状态(中际旭创/东山精密/春风动力)不建仓。首日组合净值 8814万（-2.07%，主要拖累=康方-26%）。
