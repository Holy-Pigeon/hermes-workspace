#!/usr/bin/env python3
"""
marketdata-canary · 共享取数层「契约/可导入性」金丝雀
========================================================
解决的系统级 gap（元层诊断, 2026-06-30）：

  marketdata 统一取数层 6-13 建成后, 已成为整条数据 fabric 的单点依赖——
  daily_mark / correlation_check / refresh_pick_marks / quality_screener /
  us_tech_scout / call_alpha / valuation_trigger / research-pipeline 等 11+
  消费方全部 from marketdata import。统一层一崩, 全线静默崩。

  6-30 03:07 真实事故坐实了这个风险: marketdata 在 /usr/bin/python3=3.9.6 下
  因 PEP604 联合类型注解(str|None)运行期求值崩溃, 整层 import 失败, 所有经
  系统 python3 调用的消费方静默被 SKIP——而这个事故**只是因为 call-alpha-tracker
  恰好那天跑、恰好把全部呼叫 SKIP 才被人肉发现**, 没有任何自动监控盯着它。

  现有三个元监控都盖不到这一类失效:
    - cron-health      : 盯「最后一公里交付」(job 跑完但没送达)
    - artifact-freshness: 盯「产出文件静默冻结」(mtime 停更)
    - 本金丝雀          : 盯「共享取数层在消费方实际用的解释器下还能不能 import +
                          公共 API 契约还在不在」——在事故发生**前**主动抓, 而非
                          靠某个消费方碰巧 SKIP 才暴露。

本工具做的事(纯只读, 零写盘, 零下单, 删目录即回滚):
  1) 在**两个解释器**(/usr/bin/python3=系统3.9 与 /opt/homebrew/bin/python3)
     下分别 import marketdata——这正是 6-30 事故的判别维度(3.9 崩、3.14 不崩)。
  2) 校验公共 API 契约: __all__ 里声明的每个符号都真能 import 到(防 core.py
     改名/删函数而 __init__ 没同步, 让消费方运行期才 AttributeError)。
  3) 任一解释器 import 失败 或 任一契约符号缺失 → exit 1 + 打印精确诊断
     (哪个解释器/哪个符号/什么报错)。全绿 → --quiet 静默 exit 0(watchdog 纪律)。

为什么不实际取数: 取数会打外网、引入源抖动噪声(那是 marketdata 自身降级逻辑
  + cron-health 该管的), 金丝雀只验证「层本身健康可用」这一最底层契约, 快、稳、
  零外部依赖, 适合高频跑。数据诚实: 不取数即不产生任何行情数字, 无编造空间。

退出码: 0 = 两解释器均可 import 且契约完整 / 1 = 存在 import 失败或契约缺失。
"""
import json
import os
import subprocess
import sys
import argparse

# 消费方实际使用的两个解释器(6-30 事故的判别维度)
INTERPRETERS = [
    ("/usr/bin/python3", "系统3.9"),
    ("/opt/homebrew/bin/python3", "homebrew"),
]

MARKETDATA_ROOT = os.path.expanduser("~/hermes-workspace")

# 在子解释器里跑的探针: import marketdata + 校验 __all__ 每个符号可解析。
# 纯 import, 不调用任何取数函数(不打外网)。输出单行 JSON 供父进程解析。
PROBE = r"""
import json, sys, importlib
sys.path.insert(0, "__MD_ROOT__")
out = {"import_ok": False, "missing": [], "err": None, "n_symbols": 0}
try:
    md = importlib.import_module("marketdata")
    out["import_ok"] = True
    names = getattr(md, "__all__", [])
    out["n_symbols"] = len(names)
    for n in names:
        if not hasattr(md, n):
            out["missing"].append(n)
except Exception as e:
    out["err"] = "{}: {}".format(type(e).__name__, str(e)[:160])
print(json.dumps(out, ensure_ascii=False))
""".replace("__MD_ROOT__", MARKETDATA_ROOT)


def probe_interpreter(py_path):
    """在指定解释器下跑探针, 返回 (ok, detail_dict)。解释器不存在=跳过(非失败)。"""
    if not os.path.exists(py_path):
        return None, {"skipped": True, "reason": "解释器不存在"}
    try:
        r = subprocess.run(
            [py_path, "-c", PROBE],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return False, {"err": "探针超时(30s)"}
    except Exception as e:  # noqa
        return False, {"err": f"无法启动解释器: {e}"}
    line = (r.stdout or "").strip().splitlines()
    if not line:
        return False, {"err": f"探针无输出 (stderr: {(r.stderr or '')[:160]})"}
    try:
        d = json.loads(line[-1])
    except Exception:
        return False, {"err": f"探针输出非JSON: {line[-1][:160]}"}
    ok = bool(d.get("import_ok")) and not d.get("missing")
    return ok, d


def main():
    ap = argparse.ArgumentParser(description="marketdata 共享层契约金丝雀")
    ap.add_argument("--quiet", action="store_true",
                    help="全绿静默 exit0; 有问题 exit1 并打印(给 cron 用)")
    ap.add_argument("--json", action="store_true", help="输出完整 JSON")
    args = ap.parse_args()

    results = []
    any_fail = False
    for py, label in INTERPRETERS:
        ok, detail = probe_interpreter(py)
        if ok is False:
            any_fail = True
        results.append({"interp": label, "path": py, "ok": ok, "detail": detail})

    out = {"all_ok": not any_fail, "results": results}

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        sys.exit(1 if any_fail else 0)

    if args.quiet and not any_fail:
        sys.exit(0)

    print("=" * 70)
    print("marketdata 共享取数层 · 契约/可导入性金丝雀")
    print("=" * 70)
    for r in results:
        d = r["detail"]
        if r["ok"] is None:
            print(f"  [{r['interp']}] ⏭️ 跳过: {d.get('reason')}")
        elif r["ok"]:
            print(f"  [{r['interp']}] ✅ import OK, 契约 {d.get('n_symbols')} 个符号全在")
        else:
            if d.get("err"):
                print(f"  [{r['interp']}] ❌ import 失败: {d.get('err')}")
            elif d.get("missing"):
                print(f"  [{r['interp']}] ❌ 契约缺失符号: {d.get('missing')} "
                      f"(__init__ 与 core 不同步, 消费方将运行期 AttributeError)")
            else:
                print(f"  [{r['interp']}] ❌ 未知失败: {d}")
    print("-" * 70)
    if any_fail:
        print("结论: ⚠️ 共享取数层契约受损 → 下游消费方将静默失效, 立即排查"
              "(这正是 6-30 03:07 事故的失效类型, 本次在崩之前/之中即抓到)。")
    else:
        print("结论: ✅ 两解释器均可 import 且公共 API 契约完整, 数据 fabric 底座健康。")
    print("数据诚实: 纯 import + 契约校验, 不取数不打外网, 无任何行情数字可编造。")
    if args.quiet:
        sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
