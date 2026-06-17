"""
marketdata — 统一行情/财务取数层（多源 + 重试 + 自动降级）

为什么存在：诊断发现全工作区 9 个脚本各自 import akshare、港股取数有 5 种
不同调法、只有 2 个脚本有重试、全部默认东财(em)单源——东财一断（高频现象）
就崩。本模块把"取一只票的日线/快照"收敛成一个稳定接口，内部按
东财→新浪→腾讯 顺序自动降级，任一源活着就能拿到数据。

用法（所有取数脚本应改为）：
    from marketdata import get_daily, get_spot, MarketDataError
    df = get_daily("00700", market="HK")      # 港股腾讯控股日线
    px = get_spot("301013", market="A")       # A股利和兴最新价

    # 任意 akshare endpoint（尤其财务/估值口）一行硬化，套 12s hang 墙 + 重试：
    from marketdata import safe_call
    import akshare as ak
    df = safe_call(lambda: ak.stock_financial_abstract(symbol="600519"),
                   label="abstract:600519")

设计原则：
- 一手数据优先，多源交叉；任一源成功即返回，全失败抛 MarketDataError（绝不返回填充值）
- 每个源独立重试 + 超时；失败原因全程记录，便于诊断
- 纯读，无副作用，不写任何文件/DB
- 必须用 /opt/homebrew/bin/python3 运行（akshare 装在那）
"""
from .core import (
    get_daily,
    get_spot,
    get_last_close,
    get_last_close_batch,
    safe_call,
    MarketDataError,
    detect_market,
)

__all__ = [
    "get_daily",
    "get_spot",
    "get_last_close",
    "get_last_close_batch",
    "safe_call",
    "MarketDataError",
    "detect_market",
]
