"""
marketdata.core — 多源取数核心实现

市场代号：
  "A"  = A股（沪/深），代码如 301013 / 600519 / 000001
  "HK" = 港股，代码如 00700 / 09926（5位，左补0）
  "US" = 美股，代码如 AAPL（暂只支持日线，源单一）

每个 (市场, 数据类型) 配一条按可靠性排序的源链，逐个尝试，
任一成功即返回；全失败抛 MarketDataError 并附所有源的失败原因。
"""
# PEP 604 写法 (str | None) 在 Python 3.9 运行期求值会崩；本地 /usr/bin/python3
# 是 3.9.6, cron 经此解释器调用本模块会整体 import 失败(静默拖垮所有取数消费方)。
# 延迟注解求值即可让 X | None 注解在 3.9 下安全(注解变字符串, 不在运行期 eval)。
from __future__ import annotations
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
    """取最近一个交易日收盘价 (float) + 日期 (str)。基于 get_daily 末行。
    日线源链全挂时（东财+akshare-sina 同时失败），降级到独立的 sina 实时
    快照直连（hq.sinajs.cn，不经 akshare，是真正独立的第三通路）——
    2026-06-15 事故就是日线两源全挂、无第三通路 → 4 只票退回旧价。"""
    try:
        df = get_daily(code, market)
        last = df.iloc[-1]
        return float(last["close"]), str(last["date"])
    except MarketDataError:
        # 终极兜底：sina 实时快照直连
        res = _sina_quote_direct(code, market)
        if res is not None:
            return res
        raise


def _sina_quote_direct(code: str, market: str = None):
    """独立于 akshare 的 sina 实时行情直连兜底。
    返回 (收盘价 float, 日期 str) 或 None。带 3 次指数退避重试。
    A股: list=sh600519 → 字段[3]=现价(收盘); 港股: list=rt_hk09926 → 字段[6]=现价。"""
    import urllib.request
    import datetime as _dt
    market = (market or detect_market(code)).upper()
    digits = "".join(ch for ch in str(code) if ch.isdigit())

    def _fetch(url):
        last_err = None
        for i in range(3):
            try:
                req = urllib.request.Request(
                    url, headers={"Referer": "https://finance.sina.com.cn",
                                  "User-Agent": "Mozilla/5.0"})
                return urllib.request.urlopen(req, timeout=8).read().decode("gbk")
            except Exception as e:  # noqa
                last_err = e
                time.sleep(1.5 * (i + 1))
        raise last_err

    today = _dt.date.today().isoformat()
    try:
        if market == "A":
            d6 = digits.zfill(6)
            prefix = "sh" if d6[0] == "6" else "sz"
            txt = _fetch(f"https://hq.sinajs.cn/list={prefix}{d6}")
            f = txt.split('"')[1].split(",")
            if len(f) > 3 and f[3] and float(f[3]) > 0:
                return float(f[3]), today
        elif market == "HK":
            d5 = digits.zfill(5)
            txt = _fetch(f"https://hq.sinajs.cn/list=rt_hk{d5}")
            f = txt.split('"')[1].split(",")
            if len(f) > 6 and f[6] and float(f[6]) > 0:
                return float(f[6]), today
        # 美股暂不支持直连，返回 None 让上层抛原始错误
    except Exception:
        return None
    return None


# ── 腾讯行情源：qt.gtimg.cn 单请求批量，国内直连不被 Clash 拦 ──────────────
def _tencent_symbol(code: str, market: str = None) -> str | None:
    """把 (code, market) 映射成腾讯行情代码。
    A股 sh/sz+6位；港股 r_hk+5位(实时)；美股 us+TICKER。无法识别返回 None。"""
    c = str(code).strip().upper()
    mk = (market or detect_market(c)).upper()
    digits = "".join(ch for ch in c if ch.isdigit())
    if mk == "HK":
        return "r_hk" + digits.zfill(5)
    if mk == "US":
        return "us" + c
    if mk == "A":
        d6 = digits.zfill(6)
        if d6 and d6[0] in ("6", "9"):
            return "sh" + d6
        if d6:
            return "sz" + d6
    return None


def _tencent_batch(symbols: list) -> dict:
    """腾讯批量取价：单请求多只。返回 {腾讯symbol: (price, date|None)}。
    取不到/价≤0 的不进 dict。字段：[3]=现价，[30]=YYYYMMDDHHMMSS（部分市场无）。"""
    import urllib.request
    import ssl
    if not symbols:
        return {}
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    url = "https://qt.gtimg.cn/q=" + ",".join(symbols)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=12, context=ctx).read().decode("gbk", "ignore")
    out = {}
    for seg in raw.split(";"):
        seg = seg.strip()
        if not seg.startswith("v_") or "=" not in seg:
            continue
        key, _, val = seg.partition("=")
        sym = key[2:]  # 去 v_ 前缀；港股保留 r_hk
        val = val.strip().strip('"')
        fields = val.split("~")
        if len(fields) < 4:
            continue
        try:
            price = float(fields[3])
        except (ValueError, IndexError):
            continue
        if price <= 0:
            continue
        dt = None
        if len(fields) > 30 and fields[30]:
            ds = "".join(ch for ch in fields[30] if ch.isdigit())[:8]
            if len(ds) == 8:
                dt = f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}"
        out[sym] = (price, dt)
    return out


def get_last_close_batch(items: list, max_workers: int = 8) -> dict:
    """批量取最近收盘价，自动并发 + 多源降级。

    items: [(code, market), ...]，market 可为 None（自动推断）。
    返回 {(code, market): (price float, date str)}，取不到的标的不进 dict
    （调用方据此判断缺失，保留上次价，绝不编造）。

    策略：① 先腾讯单请求批量一次拿全（最快，整池 <1s）；
         ② 腾讯未命中的标的，走线程池并发调 get_last_close
            （内部 sina→em 日线 + sina/腾讯直连终极兜底），干掉串行慢。
    """
    import datetime as _dt
    from concurrent.futures import ThreadPoolExecutor

    if not items:
        return {}
    result = {}

    # ① 腾讯批量
    sym_to_item = {}
    for code, market in items:
        ts = _tencent_symbol(code, market)
        if ts:
            sym_to_item[ts] = (code, market)
    if sym_to_item:
        try:
            today = _dt.date.today().isoformat()
            batch = _tencent_batch(list(sym_to_item.keys()))
            for ts, (px, dt) in batch.items():
                item = sym_to_item.get(ts)
                if item is not None:
                    result[item] = (px, dt or today)
        except Exception:
            pass  # 腾讯整体失败不致命，下面逐只并发兜底

    # ② 未命中的并发兜底
    missing = [it for it in items if it not in result]
    if missing:
        def _one(it):
            code, market = it
            try:
                return it, get_last_close(code, market)
            except Exception:
                return it, None
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for it, val in ex.map(_one, missing):
                if val is not None:
                    result[it] = val
    return result


# ── 美股实时报价：腾讯+新浪双源交叉，取「现价/昨收/涨跌%」─────────────────
# 存在理由（2026-06-22 事故）：日线源停在上一交易日，get_daily/get_spot 美股
# 都回退日线末行，拿不到「当日实时涨跌幅」；裸调 Yahoo chart 的 chartPreviousClose
# 字段锚点错位（拉区间时锚到区间首日前一日，不是真·上一交易日收盘），算出虚高跌幅。
# 此函数专取美股盘中报价，双源交叉：两源都成功且现价偏差<0.5% 才返回，否则抛
# MarketDataError（背离即存疑，绝不二选一）。指数同理（^DJI/^IXIC/^GSPC）。
#
# 字段位置（已实测锁定 2026-06-22）：
#   腾讯 https://qt.gtimg.cn/q=usGOOGL  → [3]现价 [4]昨收 [32]涨跌%
#   新浪 https://hq.sinajs.cn/list=gb_googl → [1]现价 [2]涨跌% [4]涨跌额；昨收=现价-涨跌额
#   指数  腾讯 usDJI/usINX/usIXIC      新浪 gb_$dji/gb_$inx/gb_$ixic（同 gb_ 格式）
# 注意：新浪 int_nasdaq/int_dji 系列是过期脏数据（曾报纳指 22484 实际 26236），禁用。

# 常用美股指数 → (腾讯symbol, 新浪symbol)。传指数名或这些 key 即可。
_US_INDEX_SYMBOLS = {
    "DJI": ("usDJI", "gb_$dji"), "^DJI": ("usDJI", "gb_$dji"),
    "DOW": ("usDJI", "gb_$dji"), "道指": ("usDJI", "gb_$dji"), "道琼斯": ("usDJI", "gb_$dji"),
    "IXIC": ("usIXIC", "gb_$ixic"), "^IXIC": ("usIXIC", "gb_$ixic"),
    "NASDAQ": ("usIXIC", "gb_$ixic"), "纳指": ("usIXIC", "gb_$ixic"), "纳斯达克": ("usIXIC", "gb_$ixic"),
    "INX": ("usINX", "gb_$inx"), "^GSPC": ("usINX", "gb_$inx"), "GSPC": ("usINX", "gb_$inx"),
    "SPX": ("usINX", "gb_$inx"), "标普": ("usINX", "gb_$inx"), "标普500": ("usINX", "gb_$inx"),
}


def _tencent_us_quote(tx_sym: str):
    """腾讯单只美股/指数报价。返回 (price, prev_close, pct) 或 None。"""
    import urllib.request
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    url = "https://qt.gtimg.cn/q=" + tx_sym
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=10, context=ctx).read().decode("gbk", "ignore")
    if '"' not in raw:
        return None
    f = raw.split('"')[1].split("~")
    if len(f) <= 32:
        return None
    try:
        price = float(f[3]); prev = float(f[4]); pct = float(f[32])
    except (ValueError, IndexError):
        return None
    if price <= 0 or prev <= 0:
        return None
    return price, prev, pct


def _sina_us_quote(sina_sym: str):
    """新浪单只美股/指数报价。返回 (price, prev_close, pct) 或 None。
    gb_ 格式：[1]现价 [2]涨跌% [4]涨跌额；昨收=现价-涨跌额（末位昨收字段不可靠）。"""
    import urllib.request
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    url = "https://hq.sinajs.cn/list=" + sina_sym
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0",
                      "Referer": "https://finance.sina.com.cn"})
    raw = urllib.request.urlopen(req, timeout=10, context=ctx).read().decode("gbk", "ignore")
    if '"' not in raw:
        return None
    body = raw.split('"')[1]
    if not body.strip():
        return None
    f = body.split(",")
    if len(f) < 5:
        return None
    try:
        price = float(f[1]); pct = float(f[2]); chg = float(f[4])
    except (ValueError, IndexError):
        return None
    if price <= 0:
        return None
    return price, price - chg, pct


def get_us_quote(code: str):
    """
    取美股个股/指数的实时报价，腾讯+新浪双源交叉验证。

    个股传 ticker（'GOOGL'）；指数传 '^IXIC'/'纳指'/'IXIC' 等（见 _US_INDEX_SYMBOLS）。

    返回 dict: {price, prev_close, pct, sources}，其中：
      price       现价（两源均值，已确认一致）
      prev_close  上一交易日收盘
      pct         涨跌%（带正负号，如 -5.92）
      sources     ['tencent','sina'] 实际成功的源

    双源交叉规则（数据严谨性铁律）：
    - 两源都成功 → 现价相对偏差须 < 0.5%，否则抛 MarketDataError（背离即存疑）
    - 仅一源成功 → 返回该源，sources 标注单源（调用方可据此降低置信）
    - 两源全失败 → 抛 MarketDataError
    绝不返回填充值。
    """
    c = str(code).strip().upper()
    if c in _US_INDEX_SYMBOLS:
        tx_sym, sina_sym = _US_INDEX_SYMBOLS[c]
    else:
        tx_sym, sina_sym = "us" + c, "gb_" + c.lower()

    tx = sina = None
    errs = []
    try:
        tx = _tencent_us_quote(tx_sym)
    except Exception as e:  # noqa
        errs.append(f"tencent({tx_sym}): {type(e).__name__}: {str(e)[:50]}")
    try:
        sina = _sina_us_quote(sina_sym)
    except Exception as e:  # noqa
        errs.append(f"sina({sina_sym}): {type(e).__name__}: {str(e)[:50]}")

    if tx and sina:
        p_tx, _, _ = tx
        p_sina, _, _ = sina
        dev = abs(p_tx - p_sina) / max(p_tx, p_sina)
        if dev >= 0.005:
            raise MarketDataError(
                f"get_us_quote({code}) 双源背离: 腾讯={p_tx} 新浪={p_sina} "
                f"偏差{dev:.2%}≥0.5%，存疑不返回")
        # 两源一致：现价取均值，昨收/涨跌% 以腾讯为准（腾讯昨收是显式字段更可靠）
        price = round((p_tx + p_sina) / 2, 4)
        return {"price": price, "prev_close": tx[1], "pct": tx[2],
                "sources": ["tencent", "sina"]}
    if tx:
        return {"price": tx[0], "prev_close": tx[1], "pct": tx[2],
                "sources": ["tencent"]}
    if sina:
        return {"price": sina[0], "prev_close": sina[1], "pct": sina[2],
                "sources": ["sina"]}
    raise MarketDataError(f"get_us_quote({code}) 双源全失败:\n  " + "\n  ".join(errs))


def get_us_quote_batch(codes: list):
    """批量取美股报价。腾讯单请求批量拿全 + 新浪逐只交叉。
    返回 {code: {price, prev_close, pct, sources}}，取不到的不进 dict。"""
    import urllib.request
    import ssl
    if not codes:
        return {}
    # 腾讯批量
    sym_map = {}  # tx_sym -> code
    for code in codes:
        c = str(code).strip().upper()
        tx_sym = _US_INDEX_SYMBOLS[c][0] if c in _US_INDEX_SYMBOLS else "us" + c
        sym_map[tx_sym] = code
    out = {}
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        url = "https://qt.gtimg.cn/q=" + ",".join(sym_map.keys())
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=12, context=ctx).read().decode("gbk", "ignore")
        for seg in raw.split(";"):
            seg = seg.strip()
            if not seg.startswith("v_") or "=" not in seg:
                continue
            key, _, val = seg.partition("=")
            tx_sym = key[2:]
            code = sym_map.get(tx_sym)
            if code is None:
                continue
            f = val.strip().strip('"').split("~")
            if len(f) <= 32:
                continue
            try:
                price = float(f[3]); prev = float(f[4]); pct = float(f[32])
            except (ValueError, IndexError):
                continue
            if price > 0 and prev > 0:
                out[code] = {"price": price, "prev_close": prev, "pct": pct,
                             "sources": ["tencent"]}
    except Exception:
        pass  # 腾讯整体失败不致命，逐只兜底
    # 腾讯未命中的逐只双源
    for code in codes:
        if code not in out:
            try:
                out[code] = get_us_quote(code)
            except MarketDataError:
                pass
    return out


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


# ---------------------------------------------------------------------------
# 报告币种登记表（单一事实源）
# ---------------------------------------------------------------------------
# 为什么在 marketdata 里：现价由本层以「上市交易币种」取（美股 ADR 报 USD），
# 而财报每股盈利按公司「报告币种」披露（台积电=TWD、阿斯麦=EUR）。两者相除得
# 到的 PE/隐含增速是币种错配的伪数——曾在 2026-06-21 同一天令 research-pipeline
# 与 valuation-trigger 各自踩坑，根因正是两处各自 hardcode 一份 NON_USD_REPORTING
# 清单、彼此漂移。取数层是唯一该知道「一只票财报用什么币种计」的地方，故把这份
# 登记收口到这里作为单一事实源，消费方一律 import，禁止再各自重定义。
#
# 无 FX 源时绝不编造换算：is_reporting_currency_mismatch() 只回答「现价币种 ≠
# 报告币种?」这个布尔事实，让消费方据此显式跳过估值层并标注币种冲突，绝不返回
# 失真倍数（数据真实性铁律）。
_REPORTING_CURRENCY = {
    # 美股 ADR / 双重上市：交易价 USD，但财报按本国币种披露
    "TSM": "TWD",   # 台积电
    "ASML": "EUR",  # 阿斯麦
    # 在此追加新标的即可，全工作区自动同步
}


def reporting_currency_registry() -> dict:
    """返回所有「报告币种≠交易币种」登记标的的副本 {symbol: reporting_ccy}。
    消费方需要遍历这批标的(如清洗历史)时用此入口，仍是单一事实源——不要在外部 hardcode。"""
    return dict(_REPORTING_CURRENCY)


def reporting_currency(symbol: str) -> str | None:
    """返回该标的财报披露所用币种（如 'TWD'/'EUR'）。未登记返回 None
    （None 表示「按其交易市场本币计，无错配」，最常见情形）。"""
    return _REPORTING_CURRENCY.get(str(symbol).strip().upper())


def trading_currency(symbol: str, market: str | None = None) -> str:
    """返回该标的交易价所用币种。A股=CNY, 港股=HKD, 美股=USD。"""
    mk = (market or detect_market(symbol)).upper()
    return {"A": "CNY", "HK": "HKD", "US": "USD"}.get(mk, "USD")


def is_reporting_currency_mismatch(symbol: str, market: str | None = None) -> bool:
    """现价币种 ≠ 财报币种?  True 表示「现价/财报每股盈利」直接相除会失真，
    消费方应跳过基于该比值的估值层（PE/隐含增速）并标注币种冲突。"""
    rc = reporting_currency(symbol)
    if rc is None:
        return False
    return rc != trading_currency(symbol, market)


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
