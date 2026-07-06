# cron-health · 定时任务交付健康度看门狗

## 解决的系统级 gap
组合的所有看门狗都盯**业务对象**(持仓/选股/护城河/预测台账),但**没有任何东西盯 cron 基础设施自身**——尤其是「最后一公里交付」。

整个系统的价值链终点是「把结论送达用户」。如果 job 脚本/agent 正常跑完(`last_status=ok`),但推送那一步失败(`last_delivery_error` 非空),**用户什么都收不到,而且没有任何告警**——因为 job 本身算成功。这是最隐蔽的失效:你以为系统在工作,其实结论全石沉大海。

## 发现实证(2026-06-14 创新引擎巡检)
实测 jobs.json,多个 job `last_status=ok` 却 `last_delivery_error="Discord send failed"`:
- StockChoose 每日选股 14:30(每天产出选股日报 → 没送达)
- 涨价观测池每日跟踪(→ 没送达)
- 研究编排流水线周度(既 RUN_ERROR 又 DELIVERY_FAIL)

选股日报是 StockChoose 唯一的对外产出,连续静默失败=整条选股链白跑。

## 检测五类失效(纯只读,绝不改 cron / 不下单)
1. **RUN_ERROR**:`last_status == 'error'`(脚本超时/崩溃)
2. **DELIVERY_FAIL**:`last_delivery_error` 非空(产出了但没送达=最隐蔽,业务看门狗永远发现不了)
3. **STALE**:enabled 但 `last_run_at` 距今远超期望 cadence(调度根本没触发,比报错更隐蔽)。容忍 3 个周期 + 至少 2h 冗余,cadence 估不准就不报(宁缺毋滥,防误报)
4. **PAUSED_STALE**:`enabled=false` 但暂停超过 7 天仍未处理(被静默关掉的僵尸 job,驾驶舱卡片仍显示为『活着』=治理盲区)
5. **UNWIRED_PROJECT**(2026-07-07 加):项目卡片在驾驶舱『活着』、目录里有可跑 `.py`,**但它既没有自己的 cron、也没被任何编排器串联调用 → 静默从不执行的僵尸能力**。

### UNWIRED_PROJECT 的根因盲区与实证
现有两个元看门狗对这一类**结构性失明**:
- cron-health(本体旧版)只读 `jobs.json` 里**已存在的 job**——这些项目根本没进 jobs.json;
- artifact-freshness 只对**声明了 `freshness_hours`** 的项目告警——这些项目没声明 SLA。

于是「建好了脚本、注册了卡片、却忘了给它挂 cron / 接编排器」的项目会永久无声躺尸。**实证代价(2026-07-07 巡检)**:`capital-deployment`(资本部署看门狗)一直未接线,而它一跑就报出 **50M(全书 56%)现金闲置 25 天无人复盘**——这种该每天盯的机会成本信号却从未触发。同批检出 `quality-compounder`、`db-freshness` 同样未接线。

判据(保守防狼来了):项目须**同时**满足「有 `heartbeat_file` + 非 `manual` + 无 `ports`(排除 launchd 常驻 web 服务) + 目录内有 `.py` + 不在核心/库白名单(marketdata/research/innovation-engine/paper-trading/stockchoose) + id 未在执行语料(jobs.json / `~/.hermes/scripts/*.sh` / `paper-trading/*.py` 编排器)中出现」才告警。任何异常静默返回空,绝不影响主 cron 健康路径。

## 用法
```bash
/usr/bin/python3 cron_health.py            # 人读摘要(并去重 append 失败台账)
/usr/bin/python3 cron_health.py --json     # 完整 JSON(含 newly_logged / flapping_7d)
/usr/bin/python3 cron_health.py --quiet    # 无告警 exit0 静默 / 有告警 exit1 打印(给 cron 判断要不要 ping)
/usr/bin/python3 cron_health.py --history 168   # 只读台账, 报告近 N 小时各 job 失败 run 次数
/usr/bin/python3 cron_health.py --no-record     # 不写台账(纯快照)
```

## 失败累积台账(2026-06-17 加固:把快照态升级为可累积的 flapping 记录)
**根因**:原版只读每个 job 的 `last_delivery_error`/`last_status` **快照**——一个 job 这轮交付失败、下轮成功就把 flag 清掉。**间歇性失败(flapping)对快照式监控天然隐形**:任意时点跑都可能恰好 exit0,被误读成「已恢复」(2026-06-17 今晨的「backbone 已恢复」结论 7 小时内即被同日傍晚的 ai-teacher DELIVERY_FAIL 证伪,正是这个盲区)。

**修复**:每轮把 DELIVERY_FAIL / RUN_ERROR 失败事件**去重后 append 进 `delivery_failures.log`**(JSONL)。去重键 = `(job_id, last_run, type)`——同一次失败 run 被多轮 cron-health 重复读到只记一次,下一次 run 再失败则 `last_run` 变化=新事件入账。于是「按失败 run 计数」可见,**flapping 频率/占比浮出水面**。

**纪律**:`--history` 让「已恢复」这类结论必须以**一段时间窗内零失败**为据,而非单次快照 exit0。正常输出末尾也会附近 7d 失败计数,提醒「快照清也别急着说已恢复」。

- 台账 `delivery_failures.log` 是运行时状态,`*.log` 已被 `.gitignore` 覆盖=不入库,删文件即回滚。

## 设计纪律
- **纯只读 jobs.json**:绝不修改 jobs.json、绝不动任何 cron 定义、绝不下单。台账是 append-only 本地文件,写失败也绝不影响主告警路径。完全可逆(删目录/台账即回滚)
- **不误报**:STALE 阈值给足冗余(3 周期),cadence 估不准直接不判;实测当前所有 enabled job 近期都跑过,STALE 零误报
- **不重复造轮子**:不是又一个业务看门狗,而是盯**看门狗们自己**的元监控

## 待挂 cron(需用户拍板)
建议挂一个低频 cron(如每天 1-2 次)跑 `--quiet`,有告警才 ping。挂 cron 涉及 touches-cron → 已在面板 idea 区标 💡proposed 等拍板,本目录脚本本体已建好自测通过。
