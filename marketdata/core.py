"""
marketdata.core — 多源取数核心实现

市场代号：
  "A"  = A股（沪/深），代码如 301013 / 600519 / 000001
  "HK" = 港股，代码如 00700 / 09926（5位，左补0）
  "US" = 美股，代码如 AAPL（暂只支持日线，源单一）

每个 (市场, 数据类型) 配一条按可靠性排序的源链，逐个尝试，
任一成功即返回；全失败抛 MarketDataError 并附所有源的失败原因。
"""
import time
import sys
import io
import threading
from contextlib import redirect_stderr

# akshare 的进度条/警告会污染 stdout，统一在此抑制
import warnings
warnings.filterwarnings("ignore")

# 单次取数最长等待秒数。akshare 底层 HTTP 可能 hang（不抛异常），
# 若无此上限，单源挂起会拖死整条降级链——多源容错只对"异常"生效、对"hang"无效，
# 这正是 daily_mark cron 被 120s 墙杀的根因。此值给每个源一个硬墙，
# 超时即放弃该源、降级到下一源，让"自动降级"对 hang 也真正生效。
CALL_TIMEOUT_S = 12


def _call_with_timeout(fn, timeout=CALL_TIMEOUT_S):
    """在 daemon 线程跑 fn；超时则放弃（线程留给进程退出时回收，不阻塞主流程）。
    返回 (result, timed_out)；fn 内部异常原样抛出由调用方捕获。"""
    box = {}

    def worker():
        try:
            box["val"] = fn()
        except BaseException as e:  # noqa: BLE001 透传给主线程重抛
            box["err"] = e

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None, True
    if "err" in box:
        raise box["err"]
    return box.get("val"), False


class MarketDataError(Exception):
    """所有源都取数失败时抛出，message 里带各源失败原因，便于诊断。"""
    pass


def _lazy_ak():
    """延迟 import akshare（首次调用才加载，加速无需取数的脚本）。"""
    import akshare as ak
    return ak


def detect_market(code: str) -> str:
    """从代码格式推断市场。纯启发式，调用方可显式传 market 覆盖。"""
    c = str(code).strip().upper()
    if c.isalpha():
        return "US"
    digits = "".join(ch for ch in c if ch.isdigit())
    if len(digits) == 5:
        return "HK"
    if len(digits) == 6:
        return "A"
    # 4位或更短的纯数字默认按港股左补0处理
    if digits and len(digits) <= 5:
        return "HK"
    raise MarketDataError(f"无法从代码 {code!r} 推断市场，请显式传 market=")


def _retry(fn, attempts=3, base_delay=1.5, label=""):
    """对单个源做指数退避重试。返回 (结果, None) 或 (None, 错误字符串)。"""
    last_err = None
    for i in range(attempts):
        try:
            buf = io.StringIO()
            with redirect_stderr(buf):
                result, timed_out = _call_with_timeout(fn)
            if timed_out:
                last_err = f"超时>{CALL_TIMEOUT_S}s(hang)"
            elif result is not None and len(result) > 0:
                return result, None
            else:
                last_err = "返回空数据"
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:60]}"
        if i < attempts - 1:
            time.sleep(base_delay * (i + 1))
    return None, f"[{label}] {last_err}"


# ── 港股日线源链：新浪优先（实测稳），东财次之 ──────────────────────────
def _hk_daily_sources(code: str):
    ak = _lazy_ak()
    code5 = "".join(ch for ch in str(code) if ch.isdigit()).zfill(5)
    return [
        ("sina:stock_hk_daily",
         lambda: _norm_daily(ak.stock_hk_daily(symbol=code5, adjust="qfq"), "sina")),
        ("em:stock_hk_hist",
         lambda: _norm_daily(ak.stock_hk_hist(symbol=code5, period="daily", adjust="qfq"), "em")),
    ]


# ── A股日线源链：新浪优先（实测今天东财全挂），东财次之 ──────────────────
def _a_daily_sources(code: str):
    ak = _lazy_ak()
    digits = "".join(ch for ch in str(code) if ch.isdigit()).zfill(6)
    prefix = "sh" if digits[0] == "6" else "sz"
    return [
        ("sina:stock_zh_a_daily",
         lambda: _norm_daily(ak.stock_zh_a_daily(symbol=prefix + digits, adjust="qfq"), "sina")),
        ("em:stock_zh_a_hist",
         lambda: _norm_daily(ak.stock_zh_a_hist(symbol=digits, period="daily", adjust="qfq"), "em")),
    ]


def _us_daily_sources(code: str):
    ak = _lazy_ak()
    return [
        ("sina:stock_us_daily",
         lambda: _norm_daily(ak.stock_us_daily(symbol=str(code).upper(), adjust="qfq"), "sina")),
    ]


def _norm_daily(df, src):
    """把不同源的日线列名归一成 date/open/high/low/close/volume，并标 _source。"""
    if df is None or len(df) == 0:
        return None
    df = df.copy()
    colmap = {
        "日期": "date", "开盘": "open", "最高": "high", "最低": "low",
        "收盘": "close", "成交量": "volume",
    }
    df = df.rename(columns=colmap)
    # 统一 date 为字符串
    if "date" in df.columns:
        df["date"] = df["date"].astype(str)
    df["_source"] = src
    return df


_DAILY_CHAINS = {
    "A": _a_daily_sources,
    "HK": _hk_daily_sources,
    "US": _us_daily_sources,
}


def get_daily(code: str, market: str = None):
    """
    取某只票的前复权日线 DataFrame（含 date/open/high/low/close/volume/_source）。
    按源链自动降级；全失败抛 MarketDataError。
    """
    market = (market or detect_market(code)).upper()
    if market not in _DAILY_CHAINS:
        raise MarketDataError(f"不支持的市场: {market}")
    errors = []
    for label, fn in _DAILY_CHAINS[market](code):
        result, err = _retry(fn, label=label)
        if result is not None:
            return result
        errors.append(err)
    raise MarketDataError(
        f"get_daily({code}, {market}) 所有源失败:\n  " + "\n  ".join(errors)
    )


def get_last_close(code: str, market: str = None):
    """取最近一个交易日收盘价 (float) + 日期 (str)。基于 get_daily 末行。"""
    df = get_daily(code, market)
    last = df.iloc[-1]
    return float(last["close"]), str(last["date"])


def get_spot(code: str, market: str = None):
    """
    取最新价 (float)。优先用轻量快照源；快照不可用时降级为 get_last_close。
    返回 dict: {price, date, source}
    """
    market = (market or detect_market(code)).upper()
    # 快照源（盘中实时）优先，失败则回退日线末行收盘
    ak = _lazy_ak()
    digits = "".join(ch for ch in str(code) if ch.isdigit())

    spot_sources = []
    if market == "A":
        code6 = digits.zfill(6)
        spot_sources = [
            ("em:stock_bid_ask_em",
             lambda: _spot_from_bidask(ak.stock_bid_ask_em(symbol=code6))),
        ]
    elif market == "HK":
        code5 = digits.zfill(5)
        spot_sources = [
            ("em:stock_hk_spot_em",
             lambda: None),  # 全表接口太慢/易挂，直接走日线兜底
        ]

    errors = []
    for label, fn in spot_sources:
        result, err = _retry(fn, attempts=2, label=label)
        if result is not None:
            return {"price": result, "date": "realtime", "source": label}
        errors.append(err or f"[{label}] 跳过")

    # 兜底：日线末行收盘（最稳）
    try:
        px, dt = get_last_close(code, market)
        return {"price": px, "date": dt, "source": "daily_close_fallback"}
    except MarketDataError as e:
        raise MarketDataError(
            f"get_spot({code}, {market}) 快照+日线全失败:\n  "
            + "\n  ".join(errors) + f"\n  {e}"
        )


def safe_call(fn, label="", attempts=3, base_delay=1.5):
    """
    通用「任意 akshare 取数」的硬化包装：给任何单个 endpoint 套上
    指数退避重试 + 12s hang 硬墙（与日线源链同一套机制）。

    存在理由：marketdata 的源链只收口了「价格/日线」，但全工作区真正高频、
    最易 hang 的是【财务/估值】endpoint（stock_financial_abstract /
    stock_value_em / stock_financial_*_analysis_indicator* 等），它们散落在
    各研究脚本里全是裸调用——单源、无重试、无超时。akshare 底层 HTTP 会
    「挂起不抛异常」，裸调用一旦撞上就把整个 cron 拖死到被 120s 墙杀
    （实测 stock_financial_abstract 当前就 hang>60s）。

    用法（任意 endpoint 一行硬化，不必先在 core 里枚举该 endpoint）：
        from marketdata import safe_call
        df = safe_call(lambda: ak.stock_financial_abstract(symbol=code),
                       label="abstract:600519")
    成功返回结果；全部重试/超时失败抛 MarketDataError（绝不返回填充值）。
    """
    result, err = _retry(fn, attempts=attempts, base_delay=base_delay, label=label)
    if result is not None:
        return result
    raise MarketDataError(f"safe_call({label}) 失败: {err}")


def _spot_from_bidask(df):
    """从 stock_bid_ask_em 的字段表里抽最新价。"""
    if df is None or len(df) == 0:
        return None
    try:
        row = df[df["item"] == "最新"]
        if not row.empty:
            return float(row.iloc[0]["value"])
    except Exception:
        pass
    return None
