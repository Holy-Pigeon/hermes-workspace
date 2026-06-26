# candidate-deepening · 候选深研待办队列(orphaned authoring 环的补位）

## 它解决什么系统级 gap(非缺某只票)
研究流水线的链路是:

```
发现(tech_screener/us-tech-scout/quality-compounder)
   → 编排(research-pipeline 产 stub dossier)
   → [深度 note authoring: 把 stub 深挖成 thesis+证伪条件+登记 prediction-ledger]   ← 这一环 orphaned
   → 计分/校准(call-alpha-tracker / alpha-attribution / prediction-ledger / signal-orthogonality)
```

**中间的 authoring 环自 2026-06-13 起无人继承。** 历史上这 14 篇 conviction note
全由「创新引擎」亲自写;当创新引擎转为元层统筹官(明令"绝不亲自下场研究")后,
这一环没有任何项目接手:

- `research-pipeline` 按自己设计只产 **stub**(文件头自陈"尽调起点 stub 非终稿");
- `research/note_*.md` 冻结在 **2026-06-13**(13 天无新 conviction note);
- 下游 4 个计分/校准 meta 工具**无新料可量、空转**——
  系统在持续给"判断质量"加测量仪表,而被测量的判断产线本身已熄火。

**实证(2026-06-21 dossier)**:10 个候选里 7 个(AAPL/MSFT/GOOGL/NVDA/ASML/TSM/MA,
整条美股 25M sleeve)**零 conviction note**,卡在 TODO-stub limbo。

## 它做什么(纯确定性·只读·不写 note)
`deepening_queue.py` **不写 note**(深挖是判断动作,属 LLM authoring cron):
1. 读最新 `research-pipeline/dossiers/dossier_*.md` 的候选清单;
2. 对照 `research/note_*.md` 已有正文,按股票代码/ticker 字面命中;
3. 机械算出「哪些候选还没有 conviction note」= **深研待办队列**,输出 JSON / 人读清单。

退出码:`0`=无 pending(--quiet 静默)/`1`=有待深研候选。

## 谁消费这个队列
拟新建一条 **authoring cron**(💡proposed,挂 cron 须用户拍板):每日/每周读本队列,
对队首候选执行完整深挖 SOP(复用既有 reverse_dcf + moat_scorecard + Polymarket 前置扫描
+ 一手 akshare/agent-browser 取数),写 `research/note_*.md`,并登记 prediction-ledger。
这恰好把 4 个空转的计分工具重新喂活。

## 数据诚实
- 纯读本地文件(dossier markdown + note grep),取不到就报空,绝不编造;
- 候选↔note 匹配按字面命中,美股 ticker 用词边界避免 `MA` 误命中 `format`;
- 宁可漏报(标"疑似未深研")不误报已深研。

## 边界 / 未挂 cron
本队列构建器纯只读完全可逆(删目录即回滚)。是否挂 authoring cron 是 cadence 决策
+ 涉及无人值守写 note,按可逆性铁律留用户拍板,已 ie.py add --touches-cron → proposed。
