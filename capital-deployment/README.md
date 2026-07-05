# 资本部署看门狗 (capital-deployment)

## 存在理由（元层系统级 gap）
盯【全书资本部署率】——系统此前最大的无人监控盲区。

`paper_trading.db` 全书 90M（可投），其中 4 个 sleeve 100% 现金、自 2026-06-11 建账起 24 天零配置：
- us-tech-value 25M / options-lab 10M / futures-macro 10M / innovation 5M = **50M（56% 全书）闲置**

而 `allocation-discipline/allocate.py` 第 80 行对无持仓账户直接 `无持仓,跳过`，`exit-sentinel` 只盯已建仓论点破裂，`valuation-trigger` 只盯候选估值 —— **没有任何一个看门狗盯"大额现金长期零配置"**。价投可以慢、可以等好价格，但机会成本必须被看见、被逼着给理由，否则闲置=遗忘不是纪律。

## 它做什么
纯只读 `paper_trading.db`，对每个 active 账户算部署率 + 距最后交易天数，红旗：
- 🔴 **IDLE_UNDEPLOYED**：部署率 <5% 且 >14 天无动作 = 大额现金长期零配置无人复盘
- 🟠 **UNDER_DEPLOYED**：5%–40% 部署且 >14 天无动作 = 显著欠配
- 🟠 **STALE_BOOK**：有持仓但 >30 天无任何 trade = 仓位从不复盘/再平衡

## 它不做什么（边界）
- **绝不建议买什么、绝不下单**。只把"闲置"从静默变成每周必须回答的问题。
- 部署与否是判断动作，归用户。追不追高、缩不缩 sleeve 规模，都由人拍板。
- 部署率是资金口径快照（现金/初始），不含浮盈亏。阈值是防御性启发式非真理。

## 用法
```
/usr/bin/python3 deployment_watchdog.py           # 人读态全书体检
/usr/bin/python3 deployment_watchdog.py --quiet   # cron友好:无🔴则静默exit0,有🔴 exit1
/usr/bin/python3 deployment_watchdog.py --json     # 结构化
```

## cadence
建议每周一次（周度足够，资本部署漂移是周/月级），随组合巡检 --full 或独立周度 cron。**挂 cron 须用户拍板**（proposed）。

## 数据诚实
纯只读快照，读库失败诚实报错 exit2 绝不编造，阈值防御性可在 CONFIG 调。
