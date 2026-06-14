# us-tech-scout · 美股科技「耐久质量」发现扫描器

## 为什么存在（元层缺口，非缺某只票）
组合 90M 分 5 个 sleeve，其中 **us-tech-value(25M) sleeve 至今 100% 未部署**，而**全部分析工具
（tech_screener / moat_scorecard / reverse_dcf / valuation_percentile / holder_concentration /
southbound_flow）只覆盖 A股+港股**——美股 sleeve 在分析上是完全暗区。

但我们的投资哲学（段永平「好生意优先」/ Nick Sleep「规模经济返还用户」/ 平台可选权）最天然的
栖息地恰恰是美股科技龙头。这是「缺一类能力」而非「缺一只票」：给最该用价投框架的 sleeve 装上
发现雷达，让 25M 闲置资金有一个一手数据驱动的候选漏斗。

## 它做什么
对一个美股科技白名单（`watchlist.json` 可覆盖默认种子），拉 26 年年报序列，用 Buffett 硬标准
筛「耐久质量」——只回答「这是不是一门耐久的好生意」，**不回答「现在贵不贵」**（估值留给后续
reverse_dcf 阶段）：

| 维度 | 口径 | 含义 |
|---|---|---|
| ROE 持久性 | 近 8 年 ROE≥15% 的年占比 | 定价权 + 复利能力 |
| 净利率水平/稳定 | 均值 + CV(std/mean) | 定价权稳不稳 |
| 毛利率 | 近 8 年均值 | 宽护城河通常 ≥40% |
| 成长 | 近一年净利/营收 YoY | 还在不在成长 |

判定：
- 🏰 **宽护城河候选** = ROE持久≥80% + 净利率均值≥15% + 毛利≥40% + CV≤0.35 + 在成长
- ⭐ **优质成长候选** = 质量近门槛（ROE持久≥60%+净利率≥10%）+ 净利/营收 YoY>15%
- 🔍 **关注** = 质量达标但成长停滞（价值陷阱风险，须人工判）
- ·  未达门槛

## 用法
```
/opt/homebrew/bin/python3 us_tech_scout.py            # 全白名单
/opt/homebrew/bin/python3 us_tech_scout.py --symbol MSFT   # 单只调试
/opt/homebrew/bin/python3 us_tech_scout.py --quiet    # 无🏰/⭐候选静默exit0(cron友好)
/opt/homebrew/bin/python3 us_tech_scout.py --json     # 机读
```
退出码：0=无候选 / 1=有🏰/⭐候选。

## 数据诚实
- 全 akshare `stock_financial_us_analysis_indicator_em` 一手年报；某只拉不到则显式跳过并告警，
  **绝不填充**。
- **ROE 失真护栏**：回购大户因负/极小权益致 ROE_AVG 畸高（实测 AAPL ROE_AVG ~152%），工具对
  ROE 中位>100% 标注「疑回购致权益缩水，ROE 失真，以净利率/毛利为准」防误读。
- 这是**候选漏斗起点，非买卖指令**；CV/持久性是历史读数不预测未来。

## 已验证（一手实跑）
- MSFT → 🏰（ROE持久1.0/净利率均值32.1%/CV0.212/毛利68%/净利YoY15.5%）
- GOOGL → 🏰（ROE中位25.5%/净利率25.2%/毛利56.6%/净利YoY32%）
- AAPL → 🏰 + ⚠️ROE失真护栏正确 firing（ROE中位152.4% 标注以净利率/毛利为准）

## 边界 / 待办
- 全白名单 12 只逐只拉年报约 60s+，**超 120s 脚本 cron 墙**——若挂 cron 须走 600s bash 包装器模式
  （与 research_pipeline_weekly 同套路）。**挂 cron 需用户拍板**（已 💡proposed）。
- 暂只判生意质量，不取价格/不算估值。下一步天然衔接：候选 → reverse_dcf 算隐含增速 →
  人工补可选权/现金流 → 进 us-tech-value sleeve 复审。
- 白名单是种子，应随认知扩展（写 `watchlist.json` 覆盖）。
