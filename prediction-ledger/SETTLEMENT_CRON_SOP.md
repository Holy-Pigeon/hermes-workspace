# 预测台账结算 cron —— agent 交付 SOP（turnkey spec）

**状态**: resolve-queue 机读队列已就绪（`prediction_ledger.py resolve-queue`，纯只读，已自测）。
本文件是**结算侧 agent cron 的现成 prompt/SOP**，等用户把它挂成 cron 即可即插即用。
挂 cron 本身属 `--touches-cron` → 需用户拍板（见 ideas_log L13 approve）。

---

## 为什么需要它（准则层）
台账当前是**只写不结算**的空转态：17 条预测全 pending、0 条 resolved。
唯一的结算侧 cron（`prediction_ledger_due_reminder.sh`，周一 21:00）是 no_agent 哑脚本，
只 `list` 打印，无任何机制去拉一手财报数字并调 `resolve`。
后果：8/31 将有 11 条预测集中到期，却无人值守结算通路 → 校准反馈到期即断，
Brier 分永远攒不出来，台账「不知道自己准不准」的自陈存在理由被自己空转掉。

## 建议调度
- **cadence**: 每月一次（如每月 1 号 10:00），或隔周。避免高频（结算是低频事件，逾期项按月扫足够）。
- **deliver**: discord:1466490258634969341
- **enabled_toolsets**: terminal, file, web, browser, search（需拉一手财报）
- **workdir**: /Users/xiaogexu/hermes-workspace/prediction-ledger

## Agent prompt（可直接粘进 cron 定义）
```
你是预测台账的「结算官」。运行结算 SOP：把到期的站立预测按证伪条件用一手数据判定 correct/wrong/partial 并录入，让 Brier 校准分真正积累。

步骤：
1. 拉队列（纯只读）：
   /usr/bin/python3 prediction_ledger.py resolve-queue --window 15 --json
   若 due_count=0 → 本轮无到期项，回 [SILENT]。

2. 对队列每一条（按 days_to_verify 升序，优先逾期项）：
   a. 读 claim + falsification + source_note，明确「证伪条件」到底要哪个一手数字。
   b. 去拉**一手数据**核实（铁律：监管文件/交易所公告/公司财报 > 媒体口径）：
      - A股中报/年报：巨潮/交易所公告、或 akshare 财务接口（marketdata 已硬化的 safe_call）
      - 港股：披露易 HKEXnews
      - 美股：SEC EDGAR / 公司 IR
      - 南向持股占比：akshare gdhs/南向通口径
      - 若财报尚未披露/数据查不到 → 该条**跳过不 resolve**（宁可留 pending 也不猜），报告里注明「数据未到，顺延」。
   c. 按证伪条件机械判定：
      - 证伪条件命中 → wrong
      - 论点兑现 → correct
      - 部分兑现/方向对幅度不足 → partial
      - 前提失效/事件取消 → void
   d. 录入（带实测值，便于回溯）：
      /usr/bin/python3 prediction_ledger.py resolve <id> <correct|wrong|partial|void> --value "实测数字+一手来源"

3. 全部处理完，跑一遍计分：
   /usr/bin/python3 prediction_ledger.py score
   把新的命中率/Brier 分 + 本轮 resolve 了哪几条（及各自实测依据）汇报到 Discord。

纪律：
- 数据诚实：每条 resolve 必须附一手来源，凭印象=禁止。查不到就顺延不硬判。
- 不下买卖指令，只做「判断准不准」的校准记账。
- 结算完若 score 出现「同标的多论点」结果相关红旗（resolve-queue 已能识别），
  按 calibration_health 建议：同标的多论点考虑合并计 1 分，避免伪多重印证高估统计力。
- 无到期项 → [SILENT]，不刷屏。
```

## 挂 cron 后的自监控注意（历史反模式，务必带上）
若把上面包成一个 shell 包装器再挂，且它用 exit1 表示「有信号」，
必须把该包装脚本加进 cron-health 的 `SELF_SIGNAL_SCRIPTS` 白名单，
否则 by-design 的 exit1 会被误判为 RUN_ERROR（看门狗自我告警反模式，本工作区反复复发）。
但**本 SOP 是 agent 驱动（非 no_agent shell）**，正常 exit0，无此风险——除非另包 shell。

---
数据诚实：resolve-queue 输出、pending=17/resolved=0、哑脚本仅 list 三点均一手读
predictions.json + jobs.json + 脚本源码核实，非推测。本文件是交付规格，非已挂 cron。
