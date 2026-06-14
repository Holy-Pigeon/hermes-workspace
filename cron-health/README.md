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

## 检测三类失效(纯只读 jobs.json,绝不改 cron)
1. **RUN_ERROR**:`last_status == 'error'`(脚本超时/崩溃)
2. **DELIVERY_FAIL**:`last_delivery_error` 非空(产出了但没送达=最隐蔽,业务看门狗永远发现不了)
3. **STALE**:enabled 但 `last_run_at` 距今远超期望 cadence(调度根本没触发,比报错更隐蔽)。容忍 3 个周期 + 至少 2h 冗余,cadence 估不准就不报(宁缺毋滥,防误报)

## 用法
```bash
/usr/bin/python3 cron_health.py            # 人读摘要
/usr/bin/python3 cron_health.py --json     # 完整 JSON
/usr/bin/python3 cron_health.py --quiet    # 无告警 exit0 静默 / 有告警 exit1 打印(给 cron 判断要不要 ping)
```

## 设计纪律
- **纯只读**:只读 `~/.hermes/cron/jobs.json`,绝不修改 jobs.json、绝不动任何 cron 定义、绝不下单。完全可逆(删目录即回滚)
- **不误报**:STALE 阈值给足冗余(3 周期),cadence 估不准直接不判;实测当前所有 enabled job 近期都跑过,STALE 零误报
- **不重复造轮子**:不是又一个业务看门狗,而是盯**看门狗们自己**的元监控

## 待挂 cron(需用户拍板)
建议挂一个低频 cron(如每天 1-2 次)跑 `--quiet`,有告警才 ping。挂 cron 涉及 touches-cron → 已在面板 idea 区标 💡proposed 等拍板,本目录脚本本体已建好自测通过。
