# martingale-guard · 加仓摊低负偏度哨兵 🛡️

## 它盯的是什么(系统级 gap,不是缺某只票)
用户 **#1 自陈的爆仓机制** = 「马丁格尔 + 满仓 = 负偏度」:向下不断加仓摊低成本、
越亏越买、仓位越滚越大,一次不回头就归零。这是行为层最贵的一课。

**现有配置层三个工具全部盯不到这条轨迹:**
| 工具 | 看什么 | 盲区 |
|---|---|---|
| allocation-discipline | 某天**快照**的静态权重集中度 | 看不到时间序列 |
| exit-sentinel | **论点**是否破裂(裸持/窗口/背离) | 不读成交序列 |
| capital-deployment | 现金**部署率** | 与加仓行为无关 |

三者都不读 `trades` 表的**时间序列**,看不到「同一只票在下跌途中被反复买入、
且每次买得更多」这条最危险的行为轨迹。**temporal 维度是全系统盲区**,本项目补它。

## 它做什么(纯只读,绝不下单、绝不改库)
读 `paper-trading/paper_trading.db` 的 `trades` 表,对每个 symbol 把 buy 序列
按时间排开,四条规则:
- **R1 加仓摊低**:后续 buy 价 < 首次 buy 价(向下加仓)
- **R2 马丁放大**:后续 buy 金额 ≥ 前次(越亏买越多)
- **R3 负偏度轨迹**:R1 且 R2 同时成立 = 教科书马丁
- **R4 现价确认**(marketdata 多源):加权成本 vs 现价,浮亏则红旗升级为「已兑现风险」

## 分级
| 级别 | 含义 |
|---|---|
| 🔴 | R3 命中:下跌途中加仓且金额未缩量/放大 → 触碰预承诺红线 |
| 🟠 | R1 命中:向下加仓但金额缩量 → 摊低未马丁,仍属逆势 |
| 🟡 | 多次加仓含横盘/微跌,警惕行为惯性苗头 |
| 🟢 | 单次建仓 / 顺势金字塔加码(向赢家加仓=马丁反面) |

**关键设计:向赢家加仓(顺势 pyramiding)判 🟢,不误伤**——只抓「向输家加仓」。

## 用法
```
/opt/homebrew/bin/python3 martingale_guard.py --account stockchoose        # 全量
/opt/homebrew/bin/python3 martingale_guard.py --account stockchoose --quiet # cron:仅🔴🟠出声
/opt/homebrew/bin/python3 martingale_guard.py --no-price                    # 跳过现价确认
/opt/homebrew/bin/python3 martingale_guard.py --json                        # 机读
```
退出码:出现 🔴 → 1;否则 0。`--quiet` 无 🔴🟠 时完全静默(cron 友好)。

## 自测(_selftest.py)
临时 DB 注入三种轨迹,验证判级正确:
- 马丁(100→90→80→70 且金额递增) → 🔴 ✅
- 摊低缩量(50→45→40 金额递减) → 🟠 ✅
- 顺势(20→25→30) → 🟢 ✅(不误伤向赢家加仓)
```
/opt/homebrew/bin/python3 _selftest.py   # → 自测 PASS
```

## 首跑硬结果(2026-07-09, stockchoose)
当前 4 持仓(康方/工业富联/小商品城/紫金)**均为单次建仓 → 全 🟢**,负偏度红线未触碰。
本工具是**面向未来的绊线**:一旦哪天开始向下加仓,cron 立即出声。防患于未然 > 事后复盘。

## 数据诚实
- 序列全部来自 `trades` 一手成交,不估算。
- 现价用 marketdata 多源容错;取不到就跳过 R4 只做 R1–R3(不编造现价)。
- 阈值(FREQ_THRESH=3 / DOWN_EPS=0.5% / SIZE_EPS=0.98)是防御性预承诺参数,非预测,非买卖指令。

## 待扩展
- 挂 cron(每日收盘后)= 需用户拍板(改 cron 不可逆),当前 💡proposed。
- 未来可接 pt.py 建仓护栏,在**下单前**就拦截马丁(前置拦截 > 事后哨兵)。
