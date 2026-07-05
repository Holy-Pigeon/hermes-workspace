#!/usr/bin/env python3
"""生成「虚函数与 vtable」课时配图（3 张）。画机制本身，不做拟人类比。
输出到 ../assets/vtable-*.png，DPI 150，白底。"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle
import numpy as np
from pathlib import Path

plt.rcParams["font.sans-serif"] = ["Hiragino Sans GB", "Songti SC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

OUT = Path(__file__).resolve().parents[1] / "assets"
OUT.mkdir(exist_ok=True)

C_EDGE = "#3b4252"; C_BAD = "#d62728"; C_GOOD = "#2ca02c"
C_BLUE = "#4C78A8"; C_ORANGE = "#d08770"; C_PURPLE = "#8e6bb0"
C_PRIV = "#eef2ff"; C_SHARE = "#e3f9e5"


def _save(fig, name):
    p = OUT / name
    fig.savefig(p, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig); print("saved", p)


# ── 图1：vtable / vptr 内存布局 ────────────────────────────────────
def fig1_layout():
    fig, ax = plt.subplots(figsize=(10.2, 5.6))
    # 两个对象（DerivedA / DerivedB），每个开头都有一个 vptr
    def obj_box(x, y, name, color, vtname):
        ax.add_patch(FancyBboxPatch((x, y), 2.2, 1.5, boxstyle="round,pad=0.02",
                                    facecolor="#fafbfc", edgecolor=color, lw=2))
        ax.text(x+1.1, y+1.62, name, ha="center", fontsize=9.5, weight="bold", color=color)
        ax.add_patch(Rectangle((x+0.15, y+0.85), 1.9, 0.5, facecolor="#ffe3e3", edgecolor=C_BAD, lw=1.5))
        ax.text(x+1.1, y+1.1, "vptr (8字节)", ha="center", va="center", fontsize=8.5, color="#222")
        ax.add_patch(Rectangle((x+0.15, y+0.2), 1.9, 0.5, facecolor=C_PRIV, edgecolor=C_EDGE, lw=1.2))
        ax.text(x+1.1, y+0.45, "对象自己的数据成员", ha="center", va="center", fontsize=8, color="#333")
        return x+1.1, y+1.1  # vptr 中心

    ax.text(1.6, 5.2, "堆/栈上的对象", ha="center", fontsize=10.5, weight="bold", color=C_EDGE)
    vxa, vya = obj_box(0.5, 3.0, "DerivedA 对象", C_BLUE, "vtA")
    vxb, vyb = obj_box(0.5, 0.7, "DerivedB 对象", C_ORANGE, "vtB")

    # 中间：两张 vtable（每类型一张，全类共享）
    ax.text(5.3, 5.2, "vtable（每个类一张，同类所有对象共享）", ha="center", fontsize=10, weight="bold", color=C_PURPLE)
    def vtable_box(x, y, name, entries, color):
        ax.add_patch(FancyBboxPatch((x, y), 2.6, 1.55, boxstyle="round,pad=0.02",
                                    facecolor="#f5f0fa", edgecolor=color, lw=2))
        ax.text(x+1.3, y+1.68, name, ha="center", fontsize=9, weight="bold", color=color)
        for k, e in enumerate(entries):
            yy = y + 1.15 - k*0.5
            ax.add_patch(Rectangle((x+0.15, yy), 2.3, 0.42, facecolor="white", edgecolor=color, lw=1))
            ax.text(x+1.3, yy+0.21, e, ha="center", va="center", fontsize=7.8, color="#222")
        return x, y+0.9
    vtA_x, vtA_y = vtable_box(4.0, 3.0, "vtable_DerivedA", ["[0] &DerivedA::calc", "[1] &~DerivedA"], C_BLUE)
    vtB_x, vtB_y = vtable_box(4.0, 0.7, "vtable_DerivedB", ["[0] &DerivedB::calc", "[1] &~DerivedB"], C_ORANGE)

    # 右：真正的函数机器码
    ax.text(9.0, 5.2, "函数机器码", ha="center", fontsize=10, weight="bold", color=C_GOOD)
    for yy, lbl, col in [(3.9, "DerivedA::calc\n{ x*2+7 }", C_BLUE), (1.5, "DerivedB::calc\n{ x-3 }", C_ORANGE)]:
        ax.add_patch(FancyBboxPatch((8.0, yy), 1.9, 0.9, boxstyle="round,pad=0.02",
                                    facecolor=C_SHARE, edgecolor=col, lw=1.6))
        ax.text(8.95, yy+0.45, lbl, ha="center", va="center", fontsize=8, color="#222")

    # 箭头：对象 vptr → vtable → 函数
    ax.annotate("", xy=(vtA_x, vtA_y+0.15), xytext=(vxa+1.0, vya), arrowprops=dict(arrowstyle="->", color=C_BLUE, lw=1.8))
    ax.annotate("", xy=(vtB_x, vtB_y+0.15), xytext=(vxb+1.0, vyb), arrowprops=dict(arrowstyle="->", color=C_ORANGE, lw=1.8))
    ax.annotate("", xy=(8.0, 4.35), xytext=(6.6, 4.1), arrowprops=dict(arrowstyle="->", color=C_BLUE, lw=1.6))
    ax.annotate("", xy=(8.0, 1.95), xytext=(6.6, 1.8), arrowprops=dict(arrowstyle="->", color=C_ORANGE, lw=1.6))

    ax.text(5.1, 0.05, "每个多态对象头部藏一个 vptr(8字节)→指向本类的 vtable→表里存虚函数地址。"
            "调用 obj->calc() = 读vptr→查表取地址→间接跳转，多绕两跳。",
            ha="center", fontsize=8.8, color="#333", weight="bold")
    ax.set_xlim(0, 10.2); ax.set_ylim(-0.2, 5.5); ax.axis("off")
    ax.set_title("虚函数的内存布局：对象里的 vptr → 类的 vtable → 真正的函数地址", fontsize=12, weight="bold")
    _save(fig, "vtable-1-layout.png")


# ── 图2：虚调用 vs 直接调用 的 CPU 执行路径 ────────────────────────
def fig2_callpath():
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(11.0, 4.6))

    def chain(ax, steps, c):
        # steps: list of (text, facecolor)，从上到下均匀排布 + 竖直箭头串联
        n = len(steps)
        top = 3.5
        gap = 0.85
        ys = [top - i*gap for i in range(n)]
        for (t, fc), y in zip(steps, ys):
            ax.add_patch(FancyBboxPatch((0.4, y), 5.2, 0.6, boxstyle="round,pad=0.02",
                                        facecolor=fc, edgecolor=c, lw=1.6))
            ax.text(3.0, y+0.3, t, ha="center", va="center", fontsize=9, color="#222")
        for i in range(n-1):
            ax.annotate("", xy=(3.0, ys[i+1]+0.6), xytext=(3.0, ys[i]),
                        arrowprops=dict(arrowstyle="->", color=c, lw=1.5))
        ax.set_xlim(0, 6); ax.set_ylim(ys[-1]-0.2, top+0.7); ax.axis("off")

    axL.set_title("直接调用 / CRTP（编译期确定目标）", fontsize=10.5, weight="bold", color=C_GOOD)
    chain(axL, [
        ("编译期就知道调哪个函数", C_SHARE),
        ("可以直接内联进调用点", "white"),
        ("CPU 顺序执行，流水线不断", "white"),
        ("实测 ≈ 0.06 ns/call（近乎免费）", C_SHARE),
    ], C_GOOD)

    axR.set_title("虚调用（运行期才知道目标）", fontsize=10.5, weight="bold", color=C_BAD)
    chain(axR, [
        ("① 从对象读 vptr（一次访存）", "white"),
        ("② 从 vtable 取函数地址（再访存）", "white"),
        ("③ 间接跳转到该地址（无法内联）", "#ffe3e3"),
        ("④ 目标不定→分支预测失败→流水线冲刷", "#ffe3e3"),
    ], C_BAD)

    fig.suptitle("为什么虚调用慢：多两次访存 + 无法内联 + 目标不可预测导致分支预测失败", fontsize=11.5, weight="bold", y=1.0)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    _save(fig, "vtable-2-callpath.png")


# ── 图3：本机实测 调用开销对比 ────────────────────────────────────
def fig3_bench():
    fig, ax = plt.subplots(figsize=(9.0, 4.6))
    labels = ["直接调用\n(非虚,内联)", "CRTP\n(静态多态)", "虚调用\n(类型混合)"]
    vals = [0.062, 0.063, 4.65]   # ns/call，本机实测（两次均值）
    colors = [C_GOOD, C_BLUE, C_BAD]
    bars = ax.bar(labels, vals, color=colors, width=0.55, edgecolor=C_EDGE, lw=1.2)
    ax.set_yscale("log")
    ax.set_ylim(0.03, 20)
    import matplotlib.ticker as mticker
    ax.yaxis.set_major_locator(mticker.FixedLocator([0.1, 1, 10]))
    ax.yaxis.set_major_formatter(mticker.FixedFormatter(["0.1", "1", "10"]))
    ax.yaxis.set_minor_formatter(mticker.NullFormatter())
    ax.set_ylabel("单次调用耗时 (ns/call, 对数轴)", fontsize=11)
    for b, v in zip(bars, vals):
        ax.text(b.get_x()+b.get_width()/2, v*1.25, f"{v:.2f} ns", ha="center", fontsize=10.5, weight="bold")
    ax.annotate("虚调用比内联调用慢约 70 倍\n(主因:分支预测失败+阻断内联,\n非 vtable 间接跳转本身)",
                xy=(2, 4.65), xytext=(0.75, 6.5), fontsize=9.5, color=C_BAD, weight="bold", ha="center",
                arrowprops=dict(arrowstyle="->", color=C_BAD, lw=1.8))
    ax.set_title("本机实测：虚调用 vs 直接调用 vs CRTP（20M 次调用均值，Apple Silicon）", fontsize=11, weight="bold")
    _save(fig, "vtable-3-bench.png")


if __name__ == "__main__":
    fig1_layout()
    fig2_callpath()
    fig3_bench()
    print("ALL DONE")
