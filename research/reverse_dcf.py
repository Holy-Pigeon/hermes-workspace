#!/usr/bin/env python3
"""
reverse_dcf.py — 隐含增长反推器（纯计算，无外部依赖）

价投核心工具：不预测"该值多少钱"，而是反过来问
**"当前股价已经 price-in 了多高的未来增长预期？这个预期合理吗？"**
（《分析框架·5 估值·反向验证》的操作化）

模型：退出倍数法两阶段
  P0 = E0 * (1+g)^N * exitMultiple / (1+r)^N
解出隐含 g：
  g = ( P0 * (1+r)^N / (E0 * exitMultiple) )^(1/N) - 1

也支持正算：给定 g，算"公允价"，与现价对比看溢/折价。

注意：
- E0 用每股 TTM 盈利（或每股 FCF），口径在调用处声明。
- exitMultiple 是 N 年后市场愿意给的成熟期倍数（净利→退出PE / FCF→退出P/FCF）。
- 本工具只做"隐含预期"的算术，不替你判断这个 g 能不能兑现——那是 thesis 的活。
"""
import argparse


def implied_growth(p0, e0, exit_mult, r, n):
    return (p0 * (1 + r) ** n / (e0 * exit_mult)) ** (1.0 / n) - 1


def fair_price(e0, g, exit_mult, r, n):
    return e0 * (1 + g) ** n * exit_mult / (1 + r) ** n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="标的")
    ap.add_argument("--price", type=float, required=True, help="当前股价")
    ap.add_argument("--eps", type=float, required=True, help="每股 TTM 盈利(或每股FCF)")
    ap.add_argument("--r", type=float, default=0.10, help="股权折现率(默认0.10)")
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--exit-mults", default="15,18,22",
                    help="N年后退出倍数情景,逗号分隔")
    ap.add_argument("--check-g", type=float, default=None,
                    help="给定一个增长率g(小数),反算公允价对比现价")
    args = ap.parse_args()

    mults = [float(x) for x in args.exit_mults.split(",")]
    print(f"=== {args.name} 反向验证 ===")
    print(f"现价 {args.price} | 每股TTM盈利 {args.eps:.3f} | "
          f"当前倍数 {args.price/args.eps:.1f}x | r={args.r:.0%} | N={args.years}y")
    print(f"\n[隐含增长] 当前价 price-in 的 {args.years} 年盈利复合增速:")
    for m in mults:
        g = implied_growth(args.price, args.eps, m, args.r, args.years)
        print(f"  退出倍数 {m:>4.0f}x → 隐含年化净利增速 g = {g:>6.1%}")

    if args.check_g is not None:
        print(f"\n[公允价] 若实际增速 g={args.check_g:.0%}:")
        for m in mults:
            fp = fair_price(args.eps, args.check_g, m, args.r, args.years)
            prem = args.price / fp - 1
            tag = "高估" if prem > 0 else "低估"
            print(f"  退出 {m:>4.0f}x → 公允价 {fp:6.1f} | 现价{tag} {abs(prem):.0%}")


if __name__ == "__main__":
    main()
