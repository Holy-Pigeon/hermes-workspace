# 研究编排流水线 (research-pipeline)

## 是什么
把此前**创新引擎每轮亲手跑**的个股研究尽调链路，产品化、剥离成一条独立可挂 cron 的
专职流水线。让创新引擎回到元层统筹，不再下场做个股研究。

## 为什么存在（解决的架构问题）
复盘 ideas_log 最近约 20 轮，创新引擎产出几乎全是**个股研究 note**（工业富联→紫金→
康方→宁德→迈瑞→海康→立讯→讯飞→茅台）+ 随附的工具修补。这是新定位明令禁止的
"研究员下场"行为。每轮都是创新引擎**手工**把
`发现(tech_screener) → 估值(reverse_dcf) → 护城河(moat_scorecard) → 登记(prediction-ledger)`
这条链串一遍。

本项目把这条链**编排成一条命令**，由专职 cron 接管，创新引擎从此只做元层审视。

## 它不做什么
- 不发明任何新数据 / 新分析方法（零新增数据源）
- 不替你判断买卖（输出是【尽调起点 stub】非终稿，非买卖指令）
- 不自动登记 prediction-ledger / 不进 StockChoose（这些是简报里留给人工的 TODO 钩子）

## 三镜头覆盖（2026-06-20 接通质量镜头）
发现侧三个正交镜头各喂同款下游尽调三件套, 互不冗余:
- **价值镜头 (A股/港股)**：`stock-discovery/tech_screener.py` 发现 ⭐(便宜) → `reverse_dcf` + `moat_scorecard`
- **质量镜头 (A股/港股)**：`quality-compounder/quality_screener.py --json` 发现 💎(好生意优先, 锚=复利质量非估值) → `reverse_dcf`(TODO钩子) + `moat_scorecard`。同标的两镜头都命中=「🔥双镜头共振」最高优先。此前 💎 无下游编排=发现孤儿, 06-20 接通
- **美股科技 sleeve(25M)**：`us-tech-scout/us_tech_scout.py --json` 发现 🏰/⭐ → `reverse_dcf`

## 双 sleeve 覆盖（2026-06-17 接通美股分支）
- **A股/港股**：`stock-discovery/tech_screener.py` 发现 ⭐ → `reverse_dcf` + `moat_scorecard`（3 层）
- **美股科技 sleeve(25M)**：`us-tech-scout/us_tech_scout.py --json` 发现 🏰/⭐ → `reverse_dcf`
  - 护城河耐久度已在 scout 内收口 `moat_core` 单一事实源，故美股段不重复跑 `moat_scorecard`（后者只吃 A 股 akshare 端口）
  - 现价经 `marketdata` 统一层取（`get_last_close(sym,"US")`），EPS 用最新【财年】BASIC_EPS（**非TTM，口径与 A 股段不同**，隐含增速仅作量级参考，TODO 钩子提醒用 TTM 复算）
  - 此前 us-tech-scout 是发现孤儿（产出 🏰 候选但无下游编排），本次接通后 25M 闲置 sleeve 有了完整发现→估值漏斗

## 怎么用
```
# 全 watchlist 扫一遍, 有 ⭐ 候选则生成简报落盘到 dossiers/
/opt/homebrew/bin/python3 pipeline.py

# cron 友好: 无候选静默 exit0, 有候选写盘 exit1
/opt/homebrew/bin/python3 pipeline.py --quiet

# 调试单只 / 只看不落盘
/opt/homebrew/bin/python3 pipeline.py --symbol 300750 --no-write
```

## 编排逻辑
1. 跑 `stock-discovery/tech_screener.py`，解析出 **⭐ 价值成长候选**（只抓 ⭐，
   不抓 🔍/🔄/⚠️ 降级/存疑标的——那些不该进尽调流水线）
2. 对每个候选：
   - **估值层**：`research/reverse_dcf.py`，EPS-TTM 由 `price/PE` 反算（±1%，与各 note 口径一致）；
     亏损/微利标的 PE 口径无意义，自动跳过并提示改用 PS/现金跑道框架
   - **护城河层**：`moat-durability/moat_scorecard.py --json`，取 verdict + 关键耐久度指标
3. 拼成候选简报 `dossiers/dossier_YYYY-MM-DD.md`，末尾留 thesis/催化剂/登记台账的 TODO 钩子

## 数据诚实
- 编排器**零新增数据**，只转发各子脚本的一手 akshare 结论
- EPS-TTM 由 price/PE 反算（±1%）
- 子脚本拉不到数据时各自告警/跳过，编排器原样透传，**绝不填充**
- ⭐ 候选≠买入，简报是深挖起点，须人工补 thesis + 一手财报核验后才进 StockChoose 复审

## 退出码
- `0` = 无 ⭐ 候选（--quiet 静默）
- `1` = 有候选简报已生成

## cron 状态
**未挂 cron**（挂定时跑是 cadence 决策，需用户拍板）。建议节奏：每周一次（周末跑，
与 stock-discovery 同频或紧随其后），避免每日高频刷屏稀释注意力。
