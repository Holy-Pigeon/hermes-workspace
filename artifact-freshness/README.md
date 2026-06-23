# artifact-freshness · 产出物新鲜度看门狗

## 解决的系统级 gap（cron-health 的产出侧对偶）

整个组合已有 **cron-health** 盯 cron 基础设施自身——但它盯的是 **JOB**：脚本跑没跑（RUN_ERROR）、跑完送没送达（DELIVERY_FAIL）、调度触没触发（STALE）。读的是 `jobs.json`。

**但过去 10 天最反复、最痛的失效是另一类——JOB 绿灯 + 交付正常，产出物却静默冻结：**

| 日期 | 事件 | job 层看到的 | 真相 |
|------|------|-------------|------|
| 06-22 | 恒生基准单源东财失效 | alpha_check 每轮绿灯 | `alpha_snapshots` 冻结 **10 天**，「基准缺失跳过不编造」护栏 darkening 了产出而非报错 |
| 06-21 | dossier 生成后未重生成 | research-pipeline 绿灯 | valuation-trigger 照常消费这份**冻结的脏 dossier**，误判台积电进买入区 |
| 通用 | 任一数据源挂掉 | scan/json 文件停更，job 不报错 | 「取不到数就跳过、绝不编造」是数据真实性铁律的**正确**护栏，但它把硬失败转成**静默冻结** |

**根因机制**：`no-data → skip, don't fabricate` 是对的，但它让一次硬失败变成产出文件停更，而 **job 层监控对此结构性失明**。`projects.json` 早已声明 `heartbeat_file` + `freshness_hours`，但驾驶舱只**被动展示**，没有任何东西**主动告警**。

## 它做什么

读 `dashboard/projects.json`（ie.py register-project 维护的单一事实源），对每个声明了 `heartbeat_file` + `freshness_hours` 的项目，比对该路径下**最新文件 mtime** vs 声明的新鲜度 SLA，超期（容忍 1.5× 或 +6h 取大）即报 **STALE_OUTPUT**。

```bash
/usr/bin/python3 artifact_freshness.py          # 人读摘要
/usr/bin/python3 artifact_freshness.py --json   # 完整 JSON
/usr/bin/python3 artifact_freshness.py --quiet  # 无告警 exit0 / 有冻结 exit1（给 cron 判断要不要 ping）
```

## 边界（诚实声明，绝不夸大覆盖）

- 只查**文件/目录 mtime**。能抓：JSON / note / dossier / scan 等文件型产出停更。
- **抓不到 DB 内单表冻结**——如 `paper_trading.db` 内 `alpha_snapshots` 冻结但 `daily_mark` 仍写价格 → DB mtime 仍新鲜。这类需内容级校验，属更重的单独议题，v1 留 TODO 不谎称覆盖。**正因如此，06-22 那次 alpha 冻结本工具 v1 仍抓不到**——它能抓的是文件型冻结（dossier/scan/watchlist），DB 内表级冻结需后续内容校验扩展。
- 只对**显式声明 `freshness_hours`** 的项目告警；无 SLA 的项目列入 `unmonitored_no_sla` 作治理提醒（推动补声明），不告警，避免对无 SLA 项目误报。

## 首跑实证（2026-06-23）

24 个项目中仅 **7 个**声明了 freshness SLA、**14 个无 SLA**（含 paper-trading——恰是 alpha 板冻结 10 天的地方）。这道无 SLA 名单本身就是治理产出：要让本看门狗真正覆盖最痛的产出，需推动各项目补 `freshness_hours` 声明（尤其 paper-trading / us-tech-scout / valuation-trigger）。

## 设计纪律

纯只读 `projects.json` 与各 heartbeat 路径，**绝不改任何文件、不动 cron、不下单**。取不到 mtime 返回 None 绝不编造时间。完全可逆（删目录即回滚）。
