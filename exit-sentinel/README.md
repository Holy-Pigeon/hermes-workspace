# exit-sentinel · 持仓论点破裂哨兵（卖出纪律自动化）

## 这填的是什么系统级缺口（非缺某只票，缺一整类能力）

段永平/巴菲特纪律有对称两半：**「找到伟大生意」+「等一个合理价格」**（买入侧），
以及**「论点破了/该卖时就卖」**（卖出侧）。芒格反复强调：投资最大的错误往往不是没买对，
而是**该卖时没卖、论点破了还抱着**——处置效应 + 沉没成本 + 确认偏误的合谋。

本组合的**买入侧已建满**：
- 发现：tech_screener / quality-compounder / us-tech-scout / research-pipeline（4 正交镜头）
- 估值：reverse_dcf（把「贵不贵」翻译成「需要多高增速」）
- 护城河：moat_scorecard
- **「等合理价格」的纵向自动化：valuation-trigger**（候选跌进合理区就告警）
- 待深研队列：candidate-deepening（entry 侧的重新承保队列）

**但卖出侧此前完全空白**：4 个在持仓位没有任何东西盯着「论点是否已破裂」。
prediction-ledger 记了每个论点的证伪条件，却只在遥远的 `verify_by`（多为 8/31 中报）
才被动结算；期间价格/基本面若已朝证伪方向大幅移动，**没有任何机制提醒「该重新承保了」**。
工业富联当前 -13% vs 成本、且头上压着 P001 看空估值论点——正是最该被主动复核的场景。

`exit-sentinel` 就是买入侧 `valuation-trigger` + `candidate-deepening` 的**卖出侧镜像**：
盯持仓、盯论点破裂、吐出「持仓重新承保队列」。

## 它做什么（纯只读、机械、可证伪）

1. 从 **paper-trading DB** 读实际在持仓位（单一事实源，非手填）
2. 从 **prediction-ledger** 按证券代码匹配该仓位的 pending 可证伪论点 + 证伪条件 + verify_by
3. 从 **research/** 匹配该仓位的深度 note（只在标题区匹配，防顺带提及污染）
4. 用 **marketdata** 取一手现价，机械判定三类「重新承保」红旗：

| 红旗 | 触发 | 含义 |
|------|------|------|
| `ORPHAN`  | 在持但零可证伪论点登记 | 裸持无退出纪律，违反「研究是投资」（最严重） |
| `WINDOW`  | 论点 `verify_by` ≤ 21 天 | 主动准备结算/复核，别被动等到期 |
| `ADVERSE` | 价格朝论点不利方向移动 ≥ 15pp | 市场在提示论点可能有问题，去核（看空却大涨=认错？看多却深套=错杀 vs 破裂？）|

## 它绝不做什么
- **不发卖出/减仓指令**（SOUL 底线：只给分析框架不给买卖指令）——只标「该重新承保了」，决策是人的
- **不发明数据**：仓位读 DB、论点读 ledger、价格读 marketdata 一手，全失败诚实标 `db_snapshot` 不编造
- **不做线性外推**：ADVERSE 只陈述「价格与论点方向背离」这一事实，不预测后续走势

## 用法
```
/usr/bin/python3 exit-sentinel/exit_sentinel.py          # 人读全量报告
/usr/bin/python3 exit-sentinel/exit_sentinel.py --quiet  # 看门狗模式: 有红旗 exit1 打印, 无则静默 exit0
/usr/bin/python3 exit-sentinel/exit_sentinel.py --json    # 结构化
```

## 阈值（防御性启发式，非真理）
- `WINDOW_DAYS = 21`：论点窗口临近门槛
- `ADVERSE_PP = 15.0`：价格背离门槛（偏保守，对抗 alert fatigue）

## 挂 cron（须用户拍板）
建议 daily 或每 3h `--quiet`，与组合巡检同档；有红旗才推 Discord，否则静默 exit0。
挂 cron 属新增无人值守定时任务 → 已在面板 idea 区标 💡proposed 等拍板。
（若挂 by-design exit1 看门狗，须同步加进 cron-health 的 SELF_SIGNAL_SCRIPTS 白名单防自误报。）

## 数据诚实
所有输入均一手实读；现价 marketdata 多源降级，取不到退回 DB 快照并显式标注；
本工具只让「论点破裂/窗口临近」可见，是否卖/减/继续持有由人决定。
