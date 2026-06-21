# valuation-trigger · 估值触发观察哨

## 元层缺口（为什么存在 · 非缺某只票）
发现侧已建成 4 个正交「好生意」镜头（tech_screener 价值 / quality_screener 质量 /
us_tech_scout 美股 / research-pipeline 编排），每周对每个候选用 `reverse_dcf` 算出
「当前价 price-in 了多高的增速」。**但这个隐含增速只是一次性打印 —— 没有任何东西纵向跟踪它，
也没有任何东西在它跌进合理区时告警。**

段永平 / 巴菲特范式 =「找到伟大的生意，然后**等一个合理的价格**」。
「好生意」那半边系统建满了；「等合理价格」那半边只有一张每周打印、没人盯的纸。
本工具就是那个**盯价格的人**：纵向监控候选的「价格要求增速 vs 已兑现增速」，
当一门已过质量门槛的好生意被市场保守定价时，推送「该认真看这个价位了」的信号。

## 信号逻辑（margin of safety，偏保守）
对每个候选解析两个数：
- `g_req` = reverse_dcf 在**最保守退出倍数 15x** 档下、当前价 price-in 的年化增速（价格的要求）
- `g_now` = 发现层「近一年净利 YoY」（生意已兑现的动能）

安全垫 = `g_now − g_req`。判定 🟢买入区 须同时满足：
1. 安全垫 ≥ **10pp**（生意交付的增速显著高于价格要求的）
2. `g_req` ≤ **20%**（绝对护栏：价格要求本身不能是高预期定价）

**只在「上期不在买入区、本期进入」时告警**（纵向穿越才推），避免每周重复刷屏。

## 反偏误设计
- 用**最保守**退出倍数档（15x）算价格要求，不挑好看的高倍数
- `g_now` 只作「生意当前动能」参照，告警文案强制提示「须人工判已兑现增速可持续性，防线性外推」
- 输出明确是**尽调起点信号，非买卖指令**

## 它不做什么
- 不发明新数据：只解析 research-pipeline 已落盘的 dossier（reverse_dcf 一手结论）
- 不下买卖指令；不自动登记 prediction-ledger / 不自动进 StockChoose（留人工钩子）
- 零外部写盘，只读 dossier + 自己的 `history.json`（纵向穿越状态）

## 用法
```
# 全量打印 + 检测新进买入区（有新穿越 exit1，无则 exit0）
/opt/homebrew/bin/python3 valuation_trigger.py

# cron 友好：静默，仅在有「新进买入区」时输出告警块并 exit1
/opt/homebrew/bin/python3 valuation_trigger.py --quiet

# 只看不更新 history（调试）
/opt/homebrew/bin/python3 valuation_trigger.py --no-write
```

## 数据诚实
- 隐含增速、现价、净利YoY 全部转发自 dossier（reverse_dcf 一手 + marketdata 统一层现价）
- 只保留三要素（现价 / g_now / g_req@15x）齐全的候选，缺一不强行判定
- 价格有保鲜期：reverse_dcf 现价取自 dossier 生成时刻，跨日须以最新 dossier 为准

## 拟挂 cron（💡proposed，待拍板）
建议跟在 research-pipeline 周度（周日 15:00）之后，如**周日 15:30 周度**，
消费当期 dossier。挂 cron 涉及定时基础设施，按可逆性铁律须用户拍板。
