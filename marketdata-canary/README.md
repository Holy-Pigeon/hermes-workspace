# marketdata-canary · 共享取数层契约金丝雀 🐦

## 它是什么
盯**共享取数层 `marketdata` 自身可用性**的元监控。在数据 fabric 真正崩之前/之中，
主动验证「`marketdata` 在两个消费方解释器下还能不能 import + 公共 API 契约还在不在」。

## 为什么存在（元层诊断）
`marketdata`（6-13 建）已是整条数据 fabric 的**单点依赖**：daily_mark / correlation_check /
refresh_pick_marks / quality_screener / us_tech_scout / call_alpha / valuation_trigger /
research-pipeline 等 11+ 消费方全部 `from marketdata import`。统一层一崩，全线静默崩。

**6-30 03:07 真实事故**坐实风险：marketdata 在 `/usr/bin/python3=3.9.6` 下因 PEP604
联合类型注解（`str | None`）运行期求值崩溃，整层 import 失败，所有经系统 python3 调用的
消费方静默被 SKIP——而这事故**只因 call-alpha-tracker 那天恰好跑、恰好把全部呼叫 SKIP
才被人肉发现**，没有任何自动监控盯着它。

现有三个元监控盖不到这一类：
| 监控 | 盯什么 | 盖得到 6-30 事故吗 |
|---|---|---|
| cron-health | 最后一公里交付（跑完没送达） | ❌ |
| artifact-freshness | 产出文件 mtime 静默冻结 | ❌（消费方 SKIP 后可能仍写出空报告/旧报告） |
| **marketdata-canary** | **共享层 import 可用性 + API 契约** | ✅ |

## 做什么（纯只读，零写盘，零下单，删目录即回滚）
1. 在**两个解释器**（`/usr/bin/python3`=系统3.9、`/opt/homebrew/bin/python3`）下分别
   `import marketdata`——这正是 6-30 事故的判别维度（3.9 崩、3.14 不崩）。
2. 校验公共 API 契约：`__all__` 里每个符号都真能解析（防 core 改名/删函数而 `__init__`
   未同步，让消费方运行期才 `AttributeError`）。
3. 任一解释器 import 失败 或 任一契约符号缺失 → exit 1 + 精确诊断；全绿 → `--quiet` 静默 exit 0。

**不实际取数**：取数会打外网、引入源抖动噪声（那是 marketdata 自身降级逻辑 + cron-health 该管的）。
金丝雀只验证「层本身健康可用」这一最底层契约，快、稳、零外部依赖，适合高频跑；不取数即无行情
数字，无编造空间。

## 用法
```bash
/usr/bin/python3 ~/hermes-workspace/marketdata-canary/canary.py          # 人读
/usr/bin/python3 ~/hermes-workspace/marketdata-canary/canary.py --quiet  # cron（全绿静默 exit0，有问题 exit1）
/usr/bin/python3 ~/hermes-workspace/marketdata-canary/canary.py --json   # 机读
```

## 退出码
- `0` = 两解释器均可 import 且契约完整
- `1` = 存在 import 失败或契约缺失（下游消费方将静默失效，立即排查）

## 验证记录
- 正常态：两解释器 ✅，13 个契约符号全在，exit0。
- 回归捕获自测：注入 `str | None` 注解的模块在 3.9 下探针返回
  `TypeError: unsupported operand type(s) for |` → 正确判失败 exit1（与 6-30 事故签名一致）。

## 拟挂 cron（💡proposed 待拍板）
建议每小时一次（与 polymarket-monitor / 组合巡检同档），`--quiet`：全绿静默，崩了立即 ping。
挂 cron 须用户拍板，已挂面板 idea 区。
