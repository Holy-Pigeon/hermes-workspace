# 创新引擎（Innovation Engine）

## 定位：元层统筹官，不是研究员
站在**所有项目之上**做统筹，不下场做具体活：
1. **架构/设计审视** — 项目职责是否重叠、数据通路是否冗余、取数是否收口 marketdata、有无该合并/拆分/下线的项目。
2. **准则/思路审视** — 每个项目的方法论真能赚钱吗？有无逻辑漏洞、线性外推、确认偏误、缝补舒适区。
3. **系统级 gap** — 组合缺什么**能力**（非缺某只票）；缺能力 → 新建独立项目 + 给它挂自己的 cron。
4. **治理闭环** — 处理审核队列、守住 idea 登记纪律。

**边界铁律**：觉得某 alpha 研究有价值 → 新建项目 + 写脚本 + 提议挂 cron（💡proposed），让那个专职 cron 去做。**绝不在创新引擎本轮亲自跑研究/分析个股。**

## 根因机制：为什么不再发生「正文喊拍板、状态标 done」
旧版是纯 prompt 驱动，LLM 每轮凭记忆守纪律、手写 markdown、自挑 emoji —— 随机性导致错配反复发生。监控只能事后抓，治标。

新版：**LLM 无权直接指定状态位。** 所有写入走 `engine/ie.py`，状态由「风险标志」纯函数推导：
- 命中 `--touches-real-money / --touches-cron / --deletes-data / --irreversible` 任一 → **强制 💡proposed**；若同时妄图 `--done/--building` → 脚本拒绝、退出码 2。
- 坏状态在机制层无法表达，不靠自觉、不靠监控。

## engine/ie.py 命令
| 命令 | 作用 |
|---|---|
| `add "标题" --category C [--done\|--building] [风险标志...]` | 登记新 idea，状态自动推导 |
| `register-project --id X --name N --desc D --tags T --heartbeat-file F` | 把新建项目同步到驾驶舱 projects.json（幂等，同 id 更新） |
| `review` | 确定性处理 reviews.json（approve→building / reject→rejected / refine→parked） |
| `transition --id "日期::标题前40" --to done` | 可逆事项流转（proposed 禁止直接流转，只能经 review） |
| `lint` | 不变式校验门：列数≥7、状态可识别；errors 非空则退出码 1 |
| `list [--status proposed] [--limit N]` | 列出 idea + 各状态计数 |

全部用 `/usr/bin/python3` 跑（仅 stdlib）。写入前自动备份到 `engine/.backups/`。

## 文件
- `ideas_log.md` — 全项目统一 idea 登记册（**只经 ie.py 改，禁止手写**）
- `reviews.json` — 面板写入的拍板队列（processed:false 待 ie.py 处理）
- `engine/ie.py` — 唯一合法入口
- `engine/cron_prompt.md` — cron 实际 prompt 的副本（改这里后需同步到 cron job 325debbbff7c）

## 状态机
```
add(可逆,--done) ───────────────► ✅done
add(可逆,默认) ──► 🛠building ──transition──► ✅done
add(不可逆) ──► 💡proposed ──review approve──► 🛠building ──► ✅done
                          └──review reject───► ❌rejected
                          └──review refine───► ❄️parked (+追加v2)
```
面板（dashboard/app.py parse_ideas）靠状态 emoji 解析：💡=待审区 / ✅=完成 / 🛠=进行中。
