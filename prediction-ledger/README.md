# 预测台账 (prediction-ledger)

Tetlock式预测计分卡。把每篇研究note末尾的【可证伪论点+证伪条件】登记为带截止日的结构化预测，到期后录入真实结果，自动算命中率和Brier校准分。

## 为什么存在
我们已产出 ~11 篇研究 note，每篇都按纪律给了「可证伪论点 + 证伪条件 + 待验证下一步」，几乎全绑定中报 8/31 窗口。但**此前没有任何统一台账捕获这些站立预测并给自己计分**——thesis.json/catalyst.json 只覆盖 4 只持仓的失效条件，不覆盖候选研究与站立预测。

没有计分卡，「纪律和可重复流程」就无法被自己证伪：我们不知道自己判断准不准、在哪类标的上系统性犯错。这正是超级预测者的核心——留痕 + 复盘 + 校准。

## 用法
```bash
# 看所有站立预测（带到期倒计时，逾期会 ⏰ 提醒去录结果）
python3 prediction_ledger.py list
python3 prediction_ledger.py list --due-soon 14   # 只看14天内到期

# 财报落地后，拉一手数据，录入结果
python3 prediction_ledger.py resolve P001 correct --value "中报净利YoY 38%"
#   outcome: correct(论点成立) / wrong(被证伪) / partial(部分) / void(前提失效作废)

# 计分卡：命中率 + Brier 分
python3 prediction_ledger.py score

# cron 友好：无逾期则静默 exit0
python3 prediction_ledger.py list --quiet
```

## 计分
- **命中率**：correct=1 / partial=0.5 / wrong=0 的均值
- **Brier 分** = mean((confidence − hit)²)，0=完美 / 0.25=随机瞎猜 / 越低越准。同时惩罚「方向错」和「过度自信」。

## 数据诚实
- confidence 是登记时的主观概率，**结果必须以一手财报/监管公告录入，不凭印象**。
- 只登记可证伪、有明确截止日和数值阈值的论点。模糊的「值得关注」不登记。
- void 用于前提失效（如标的被并购/停牌）导致论点无法验证，不计入分母。

## 当前状态
9 条 pending（P001-P009），覆盖 4 持仓 + 宁德/迈瑞/海康候选 + 工业富联筹码 + 康方南向。
大批在 2026-08-31 中报窗口到期 → 那时是第一次真正给自己计分的时刻。
