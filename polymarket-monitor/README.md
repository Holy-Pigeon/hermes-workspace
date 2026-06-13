# Polymarket 异动监控

独立工程，和 StockChoose 平行运行。

## 目标

每次运行扫描与投资组合相关的 Polymarket 预测市场，检测价格大幅变动，
异动时推送 Discord 告警。

## 文件结构

```
polymarket-monitor/
├── monitor.py      # 核心脚本（扫描 + 告警）
├── config.json     # 关键词 / 阈值 / Discord target
├── state.json      # 上次价格快照（自动生成）
├── monitor.log     # 运行日志（自动生成）
└── README.md       # 本文件
```

## 用法

```bash
# 初始化快照（第一次运行，不触发告警）
/opt/homebrew/bin/python3 monitor.py --init

# 正式运行（比对快照，有异动推 Discord）
/opt/homebrew/bin/python3 monitor.py

# 干跑，仅打印不推送
/opt/homebrew/bin/python3 monitor.py --dry-run
```

## 参数说明（config.json）

| 字段 | 默认值 | 说明 |
|------|--------|------|
| keywords | 宏观+科技关键词 | 搜索哪些市场 |
| alert_thresh | 5.0 | 价格变动超过 X% 则告警（单位：百分点） |
| min_volume | 50000 | 最低成交量过滤，降噪 |
| discord_target | discord:1466490258634969341 | 推送目标 |

## Cron 建议

每小时运行一次（和巡检频率对齐）：

```
0 * * * * /opt/homebrew/bin/python3 ~/hermes-workspace/polymarket-monitor/monitor.py >> ~/hermes-workspace/polymarket-monitor/monitor.log 2>&1
```

## 告警逻辑

1. 扫描 `keywords` 里每个词，调用 Polymarket Gamma API
2. 过滤：仅看 active + 未关闭 + 成交量 > `min_volume` 的市场
3. 对比上次快照，变动 > `alert_thresh` 百分点触发告警
4. 同一次运行最多推送 8 条，按变动幅度从大到小排序
