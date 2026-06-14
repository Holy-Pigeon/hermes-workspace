#!/usr/bin/env python3
"""
parity_check.py — marketdata 迁移前的等价性验证器（纯只读，不动任何在跑脚本）

为什么存在（元层诊断）：
  marketdata 统一取数层 2026-06-13 已建成，但全工作区 grep 实测 9 个目标脚本
  仍 100% 裸 import akshare、0 个 import marketdata——统一层建好却没人用，地基
  搁浅，"东财一断高频崩"的原始病根在 9 个脚本里依旧存活。

  把脚本迁到 marketdata 需要用户拍板（动到在跑的 daily_mark / cron）。拍板卡在
  一个未被证伪的风险疑虑上：「marketdata 降级取到的数，和各脚本现在裸调 akshare
  取到的数，是不是同一个数？」如果不是，迁移会悄悄改变盯市/估值结果。

  本工具就是把这个疑虑变成可验证的事实：对真实持仓 + 抽样标的，同时跑
  ① 旧路径（脚本现在用的裸 akshare 接口）② 新路径（marketdata.get_last_close），
  逐只比对收盘价，给出一致/偏差报告。一致 → 拍板变成按钮级安全决策；
  不一致 → 暴露真实风险，迁移前必须先修，避免悄悄改账。

边界与诚实：
  - 纯读，不写任何文件/DB，不下单，删本文件即完全回滚。
  - 比对的是「日线最新收盘价」这一最高频字段（daily_mark 的核心用途）。
  - 容差：A股/港股价格四舍五入到分（0.01）算一致；浮点噪声不算偏差。
  - 任一路径取数失败如实标 ERROR，绝不用另一路径的值填充冒充一致。
  - 必须用 /opt/homebrew/bin/python3 运行（akshare 装在那）。

退出码：0 = 全部一致（可安全迁移） / 1 = 存在偏差或取数失败（迁移前需排查）。
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

try:
    from marketdata import get_last_close, detect_market, MarketDataError
except Exception as e:  # noqa
    print(f"[FATAL] 无法导入 marketdata: {e}")
    sys.exit(1)


# 真实持仓（取自 paper-trading positions 表，2026-06-14）+ 几个研究高频标的抽样
DEFAULT_TARGETS = [
    ("09926", "康方生物", "HK"),
    ("601138", "工业富联", "A"),
    ("600415", "小商品城", "A"),
    ("601899", "紫金矿业", "A"),
    ("00700", "腾讯控股", "HK"),
    ("600519", "贵州茅台", "A"),
    ("002230", "科大讯飞", "A"),
]

TOL = 0.01  # 收盘价容差：到分


def raw_akshare_close(code, market):
    """旧路径：复刻 daily_mark.py 现在用的裸 akshare 调法（逐只 hist 取最后一根收盘）。"""
    import akshare as ak
    if market == "A":
        df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="")
    elif market == "HK":
        df = ak.stock_hk_hist(symbol=code.zfill(5), period="daily", adjust="")
    elif market == "US":
        df = ak.stock_us_hist(symbol=code, period="daily", adjust="")
    else:
        raise ValueError(f"未知市场 {market}")
    if df is None or len(df) == 0:
        raise RuntimeError("空数据")
    # akshare 中文列名「收盘」
    col = "收盘" if "收盘" in df.columns else df.columns[2]
    return float(df.iloc[-1][col])


def main():
    ap = argparse.ArgumentParser(description="marketdata 迁移前等价性验证")
    ap.add_argument("--quiet", action="store_true", help="全部一致时静默(exit 0)，给 cron 用")
    args = ap.parse_args()

    rows = []
    n_ok = n_diff = n_err = 0
    for code, name, mkt in DEFAULT_TARGETS:
        old_v = new_v = None
        old_err = new_err = None
        try:
            old_v = raw_akshare_close(code, mkt)
        except Exception as e:  # noqa
            old_err = str(e)[:60]
        try:
            res = get_last_close(code, market=mkt)
            # get_last_close 返回 (close: float, date: str)
            if isinstance(res, (tuple, list)):
                new_v = float(res[0])
            elif isinstance(res, dict):
                new_v = float(res.get("close") or res.get("last") or res.get("price"))
            else:
                new_v = float(res)
        except Exception as e:  # noqa
            new_err = str(e)[:60]

        if old_err or new_err:
            status = "ERROR"
            n_err += 1
        elif abs(old_v - new_v) <= TOL:
            status = "OK"
            n_ok += 1
        else:
            status = "DIFF"
            n_diff += 1
        rows.append((code, name, mkt, old_v, new_v, old_err or new_err, status))

    all_ok = (n_diff == 0 and n_err == 0)
    if args.quiet and all_ok:
        sys.exit(0)

    print("=" * 78)
    print("marketdata 迁移等价性验证  (旧裸akshare收盘 vs marketdata.get_last_close)")
    print("=" * 78)
    print(f"{'代码':<8}{'名称':<10}{'市':<4}{'旧收盘':>11}{'新收盘':>11}  {'判定'}")
    print("-" * 78)
    for code, name, mkt, ov, nv, err, st in rows:
        ovs = f"{ov:.2f}" if ov is not None else "—"
        nvs = f"{nv:.2f}" if nv is not None else "—"
        mark = {"OK": "✅一致", "DIFF": "⚠️偏差", "ERROR": "❌取数失败"}[st]
        line = f"{code:<8}{name:<10}{mkt:<4}{ovs:>11}{nvs:>11}  {mark}"
        if err:
            line += f"  ({err})"
        print(line)
    print("-" * 78)
    print(f"一致 {n_ok} / 偏差 {n_diff} / 失败 {n_err}  （共 {len(rows)}）")
    if all_ok:
        print("结论：✅ 全部一致 → marketdata 与旧路径取数等价，逐脚本迁移可安全推进。")
    else:
        print("结论：⚠️ 存在偏差/失败 → 迁移前需逐项排查，勿盲目切换（避免悄悄改账）。")
    print("数据诚实：纯只读双路径取数对照，任一路径失败如实标记绝不互相填充。")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
