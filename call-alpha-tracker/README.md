# call-alpha-tracker · 研究「呼叫」的基准调整后收益记分卡

## 元层能力缺口（为什么存在 · 非缺某只票）
系统使命「超越巴菲特」本质是一个**相对收益**游戏。但全系统唯一的计分卡
`prediction-ledger` 衡量的是**基本面论点是否兑现**（中报净利 beat / margin 守住 /
陷阱判定对不对），它**不回答「按这个判断行动到底跑赢还是跑输大盘」**。

两者会系统性背离：
- 论点 **correct** 但股票跑输沪深300 → 赚了认知、亏了相对钱；
- 论点 **wrong** 但股票暴涨 → 陷阱判错，若真做空会巨亏。

我们有 13 条带方向(`direction`)+建仓日(`created`)的研究呼叫，却**零跟踪**它们从
呼叫日至今的「基准调整后呼叫α」。没有这个闭环，就无法证伪：研究流程到底在为
组合创造**相对收益**，还是只在产出读起来很对的 note。这是「缺一类能力」而非
「缺一只票」——`prediction-ledger` 是事后 Brier（论点对不对），本器是**收益侧的另一半**
（按判断行动赚没赚到相对钱）。

## 它做什么
对 `prediction-ledger/predictions.json` 里每条 **未结算** 预测：
- 取标的从呼叫日→今日涨跌（`marketdata.get_daily`，多源降级，一手）
- 取同期匹配基准涨跌（A→沪深300 / HK→恒生，复用 alpha_check 同款稳源逻辑）
- 按呼叫方向折算 **呼叫α = stance × (标的收益 − 基准收益)**
  - `stance`：看多=+1（期望跑赢基准）/ 看空=−1（期望跑输）/ 中性结构性=0 不计
- 正呼叫α = 这条呼叫**既方向对、又跑赢基准** = 真创造相对收益

`direction → stance` 映射见脚本顶部 `DIRECTION_STANCE`，新增方向取值时在此登记。

## 用法（必须用 /opt/homebrew/bin/python3）
```bash
cd ~/hermes-workspace/call-alpha-tracker
/opt/homebrew/bin/python3 call_alpha.py            # 完整记分板
/opt/homebrew/bin/python3 call_alpha.py --quiet    # 无可计分呼叫则静默 exit0(cron友好)
/opt/homebrew/bin/python3 call_alpha.py --json      # 结构化输出
```

## 首跑硬结果（2026-06-23）
12 条进行中呼叫，**仅 2 条正呼叫α，平均 −3.19pp**。最差是工业富联两条看空
(P001/P008)——股票自呼叫日 +12.5%/+7.5% 远超沪深300，看空方向至今在亏相对钱。
这正是系统此前看不见的镜子：基本面论点要到 8/31 才证伪，但**市场已经在用真金
白银投票，而我们的方向判断迄今大面积跑输**。这不等于判断错（论点可能 8/31 才兑现），
但它是一个**应该现在就盯的过程信号**，且与 ledger 的事后 Brier 严格互补。

## 数据诚实纪律
- 纯只读。取数全走 marketdata，任一源失败即跳过该条并标 `SKIP_*`，**绝不编造价格**。
- 呼叫α是**至今浮动相对收益**，非已结算业绩；论点未到窗口前只是过程读数。
- 未知 direction 标 `UNKNOWN_DIR` 不强行计分；中性/结构性预测标 `NO_DIR_ALPHA`。
- 已结算预测交给 ledger 的 Brier，本器只看进行中的过程α，二者互补不替代。

## 未挂 cron（待用户拍板）
建议挂周度 cron（与 prediction-ledger 周度提醒同档），让呼叫α漂移有定时巡检。
挂 cron 涉及无人值守定时任务 → 按可逆性铁律须用户拍板，已在面板 idea 区登记
`--touches-cron` proposed。当前可按需手动跑。
