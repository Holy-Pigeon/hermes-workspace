# marketdata — 统一行情/财务取数层

## 为什么存在（根因诊断，2026-06-13）

巡检发现**港股取数失败是高频现象**，根因不是 akshare 本身，而是工程结构：

1. **零共享层**：全工作区 9 个脚本各自 `import akshare`，没有任何公共取数模块
2. **同一件事 N 种调法**：取港股价散落 5 种接口（`stock_hk_spot_em`/`stock_hk_spot`/`stock_hk_hist`/`stock_hk_indicator_eniu`/`stock_hk_index_daily_em`）
3. **失败处理不一致**：只有 2 个脚本有重试，其余 7 个裸调用，源一断就崩
4. **全部单源东财(em)**：东财接口间歇性 `RemoteDisconnected`（实测 2026-06-13 全线断连），无任何脚本会自动切新浪/腾讯 → **这就是高频失败的直接原因**

## 解决方案

一个共享模块，把"取一只票的日线/快照"收敛成稳定接口，内部**多源自动降级**：
- 港股日线：新浪(stock_hk_daily) → 东财(stock_hk_hist)
- A股日线：新浪(stock_zh_a_daily) → 东财(stock_zh_a_hist)
- 美股日线：新浪(stock_us_daily)
- 每源独立重试+超时，任一活着即返回；全失败抛 `MarketDataError`（绝不返回填充值，符合数据严谨性铁律）

**实测**：东财全挂时，A股/港股/美股仍可通过新浪源稳定取得。

## 用法

```python
import sys; sys.path.insert(0, '/Users/xiaogexu/hermes-workspace')
from marketdata import get_daily, get_last_close, get_spot, MarketDataError

df = get_daily("00700", market="HK")          # 港股腾讯日线 DataFrame
px, dt = get_last_close("301013", market="A") # A股利和兴最近收盘 (50.87, '2026-06-12')
spot = get_spot("301013")                       # {price, date, source}，market 可省略(自动推断)
```

- **必须用 `/opt/homebrew/bin/python3`**（akshare 装在 homebrew python）
- 日线列已归一：`date/open/high/low/close/volume/_source`
- `market` 可省略，按代码格式自动推断（5位→HK，6位→A，纯字母→US）

### 直连外部 API 的韧性收口（非 akshare）

对于直接打外部 REST API 的 cron（ClinicalTrials.gov 临床、Polymarket、南向等），
用 `http_get` / `http_get_json` 替代裸 `urllib.request.urlopen`——统一的指数退避
重试 + 超时墙，兜底瞬时 SSL EOF / RemoteDisconnected / 超时。全失败抛
`MarketDataError`（绝不返回填充值）。

```python
from marketdata import http_get_json
d = http_get_json("https://clinicaltrials.gov/api/v2/studies?query.term=ivonescimab",
                  headers={"User-Agent": "akeso-watch/1.0"}, timeout=30, label="ctgov")
```

> 背景：2026-07-13 akeso 临床监控因 ClinicalTrials.gov 间歇 SSL EOF 连续
> RUN_ERROR（催化剂监控当天失明），根因是单发裸 urlopen 无重试。当时只在
> akeso 内部内联修 backoff，未抽象。此原语把该教训收口成唯一可复用入口，
> 消除各脚本各自重造 retry/backoff/timeout（akeso/polymarket/core-sina 三份漂移）。


## 迁移清单（待逐步收口的脚本，全部可逆）

这些脚本目前各自取数，应逐步改为调本模块。**不一次性大改**，每改一个单独验证：

- [x] paper-trading/daily_mark.py（盯市，最高频，优先级最高）✅ 已收口(get_last_close_batch)
- [x] paper-trading/correlation_check.py ✅ 已收口(get_daily, 2026-06-29 实测4只全过)
- [ ] paper-trading/valuation_percentile.py（估值分位，低频接口，marketdata 暂未覆盖 stock_value_em/eniu，需先扩展统一层）
- [ ] paper-trading/alpha_check.py（指数日线，marketdata 暂未覆盖指数接口）
- [ ] paper-trading/pt.py（建仓价护栏，写路径，谨慎）
- [ ] paper-trading/holder_concentration.py
- [ ] paper-trading/southbound_flow.py
- [ ] stock-discovery/tech_screener.py
- [ ] moat-durability/moat_scorecard.py

## 边界

- 暂只覆盖日线+快照（最高频需求）。财务指标(stock_financial_abstract)、
  估值分位(stock_hk_indicator_eniu)等低频接口暂未纳入，后续按需扩展。
- 美股源较单一（只新浪），失败容忍度低于 A/港股。
