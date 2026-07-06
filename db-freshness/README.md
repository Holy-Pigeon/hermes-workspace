# db-freshness · 数据库表级新鲜度看门狗

## 解决的系统级 gap（artifact-freshness 明文标注却未实现的盲区）

组合的失效监控此前有两层，但都对「DB 文件新鲜、内部某张表静默冻结」失明：

| 看门狗 | 读什么 | 盯什么 | 对表级冻结 |
|--------|--------|--------|-----------|
| cron-health | `jobs.json` | JOB 跑没跑 / 送没送达 / 触没触发 | **失明**（job 绿灯） |
| artifact-freshness | 文件 mtime | 文件型产出（dossier/note/scan）停更 | **失明**（DB mtime 新鲜） |
| **db-freshness（本项目）** | **sqlite 表内最新日期** | **时序表内容是否停更 + 依赖链是否断裂** | ✅ 覆盖 |

**根因机制**：`paper_trading.db` 每交易日由 `daily_mark` 写 `nav_snapshots` → DB 文件 mtime 永远新鲜。但 `benchmark_levels` / `alpha_snapshots` 依赖取恒生基准价，一旦单源东财失效，「取不到数就跳过、绝不编造」这条**正确**的数据真实性护栏会把硬失败转成**表级静默冻结**——nav 照写，bench/alpha 停更，而 job 层与文件层监控都看不到。这正是 artifact-freshness README 亲述的 **06-22 `alpha_snapshots` 冻结 10 天无人察觉** 事件的结构性根因，它当时 v1 明确标注「抓不到 DB 内单表冻结，留 TODO」。本项目就是那个 TODO 的实现。

## 建项发现实证（2026-07-06 创新引擎巡检）

实测 `paper_trading.db`（今 7/6，周一）：
- `nav_snapshots` max = **2026-07-03**（lag 1 交易日，OK）
- `alpha_snapshots` max = **2026-07-02**（lag 2 交易日）
- `benchmark_levels` max = **2026-07-01**（lag 3 交易日）

当下仍在容忍窗口内（未告警，不误报），但 bench/alpha 已在 nav 之后**开始拉开身位**——正是单源基准失效向下游传导的早期形态。若无本工具，等它冻结到两位数天数才被发现（如 06-22），alpha 绩效读数已脏多日。

## 检测两类失效（纯只读 sqlite，绝不写库）

1. **STALE_TABLE**：表内最新日期距今超过「交易日容忍窗口」（排除周末，故窗口留冗余防节假日误报）。
2. **LAG_DIVERGENCE**：同库下游表落后上游基准表超阈值 —— 依赖链断裂（如 `alpha` 落后 `nav` = alpha 计算链断，多因基准缺失），比单表 STALE 更早暴露「上游停而下游被迫停」。

## 用法
```bash
/usr/bin/python3 db_freshness.py          # 人读摘要(每表 latest/lag/状态)
/usr/bin/python3 db_freshness.py --json    # 完整 JSON(alerts 结构化)
/usr/bin/python3 db_freshness.py --quiet   # 无告警 exit0 静默 / 有告警 exit1 打印(给 cron 判断要不要 ping)
```

配置在 `checks.json`：声明库路径、表、时序列名、容忍交易日、依赖链。新增库/表只改配置不改码。

## 边界（诚实声明）
- 交易日差**只排周末不排节假日**，故容忍窗口留 +1 冗余，宁松勿误报。
- 只查「最新日期」是否停更，**不校验行内数值是否合理**（如价格是否为 0/异常跳变）——那是更重的内容质量校验，属单独议题，本工具不谎称覆盖。
- 只读打开（`mode=ro`），对实盘库零写入风险。

## 与既有监控的关系（三层闭环，互补不重叠）
job 层（cron-health）+ 文件层（artifact-freshness）+ **表层（db-freshness）** = 从「脚本→交付→文件产出→DB 内容」全链路失效可观测。三者读不同数据源、抓不同失效路径，无职责重叠。

## cadence
表级冻结漂移慢但一旦发生代价高（绩效读数脏多日）。建议每日 1 次随收盘批处理后跑 `--quiet`，有告警才 ping。**挂 cron 需用户拍板（💡proposed），脚本已就绪 `--quiet` 一行可挂。**
