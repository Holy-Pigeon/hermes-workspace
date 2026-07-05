#!/usr/bin/env python3
"""生成「malloc 原理」课时配图（3 张）。画机制本身，不做拟人类比。
输出到 ../assets/malloc-*.png，DPI 150，白底。"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.patches import FancyBboxPatch, Rectangle
import numpy as np
from pathlib import Path

plt.rcParams["font.sans-serif"] = ["Hiragino Sans GB", "Songti SC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

OUT = Path(__file__).resolve().parents[1] / "assets"
OUT.mkdir(exist_ok=True)

C_EDGE = "#3b4252"; C_BAD = "#d62728"; C_GOOD = "#2ca02c"
C_BLUE = "#4C78A8"; C_ORANGE = "#d08770"; C_PURPLE = "#8e6bb0"
C_PRIV = "#eef2ff"; C_SHARE = "#e3f9e5"; C_HL = "#fff3cd"


def _save(fig, name):
    p = OUT / name
    fig.savefig(p, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig); print("saved", p)


# ── 图1：glibc malloc 结构总览（arena / bins / brk / mmap）──────────
def fig1_structure():
    fig, ax = plt.subplots(figsize=(10.4, 6.0))
    ax.text(5.2, 5.75, "你调用 malloc(size) 时，分配器按 size 走不同的路", ha="center", fontsize=11.5, weight="bold")

    # 顶部：malloc 入口
    ax.add_patch(FancyBboxPatch((4.0, 4.9), 2.4, 0.6, boxstyle="round,pad=0.02", facecolor=C_HL, edgecolor=C_EDGE, lw=1.8))
    ax.text(5.2, 5.2, "malloc(size)", ha="center", va="center", fontsize=10.5, weight="bold")

    def box(x, y, w, h, title, body, ec, fc):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02", facecolor=fc, edgecolor=ec, lw=1.7))
        ax.text(x+w/2, y+h-0.26, title, ha="center", fontsize=9.3, weight="bold", color=ec)
        ax.text(x+w/2, y+h/2-0.26, body, ha="center", va="center", fontsize=8.0, color="#222")

    # 左：小块 → thread cache / bins（走用户态，快）
    box(0.3, 2.6, 4.6, 1.9, "小块（≤ 约128KB）→ 走用户态空闲链表",
        "① tcache：每线程本地小缓存(glibc)，无锁最快\n"
        "② fastbins/smallbins：按大小分档的空闲块链表\n"
        "③ 不够就从 top chunk 切；再不够 brk() 抬堆顶\n"
        "命中缓存 = 几十 ns；要 brk 系统调用 = 偶发尖峰",
        C_GOOD, C_SHARE)
    ax.annotate("", xy=(2.6, 4.5), xytext=(4.6, 4.9), arrowprops=dict(arrowstyle="->", color=C_GOOD, lw=1.7))
    ax.text(3.3, 4.75, "size 小", ha="center", fontsize=8.5, color=C_GOOD)

    # 右：大块 → 直接 mmap（走内核，贵）
    box(5.6, 2.6, 4.5, 1.9, "大块（> mmap 阈值，约128KB）→ 直接 mmap",
        "绕过 bins，直接向内核 mmap 一整段\n"
        "每次都陷内核 + 之后首访缺页\n"
        "free 时 munmap 还给内核\n"
        "→ 每次都贵，且可能微秒~毫秒尖峰",
        C_BAD, "#ffe3e3")
    ax.annotate("", xy=(7.8, 4.5), xytext=(5.8, 4.9), arrowprops=dict(arrowstyle="->", color=C_BAD, lw=1.7))
    ax.text(7.1, 4.75, "size 大", ha="center", fontsize=8.5, color=C_BAD)

    # 底部：arena + 多线程
    box(0.3, 0.4, 9.8, 1.7, "arena（分配区）与多线程",
        "主分配区用 brk 管堆(向上增长)；每个 arena 有自己的一把锁 + 一套 bins。\n"
        "多线程争用同一 arena 会加锁排队 → glibc 给不同线程分配到不同 arena 缓解，但线程多时仍有锁竞争。\n"
        "这就是「malloc 在多线程热路径不确定」的根源之一：可能命中缓存(快)，可能等锁/brk/mmap(尖峰)。",
        C_PURPLE, "#f5f0fa")
    ax.annotate("", xy=(2.6, 2.1), xytext=(2.6, 2.6), arrowprops=dict(arrowstyle="<->", color=C_PURPLE, lw=1.3))
    ax.annotate("", xy=(7.8, 2.1), xytext=(7.8, 2.6), arrowprops=dict(arrowstyle="<->", color=C_PURPLE, lw=1.3))

    ax.set_xlim(0, 10.4); ax.set_ylim(0.2, 6.0); ax.axis("off")
    ax.set_title("glibc malloc 的内部结构：小块走用户态 bins，大块直接 mmap（本机 macOS 用不同实现，机制类似）",
                 fontsize=11, weight="bold")
    _save(fig, "malloc-1-structure.png")


# ── 图2：一次 malloc 可能踩中的开销层 ────────────────────────────
def fig2_costlayers():
    fig, ax = plt.subplots(figsize=(9.8, 5.4))
    ax.text(4.9, 4.62, "一行 malloc(size) 背后：可能走快路径，也可能踩中尖峰层", ha="center", fontsize=10.5, weight="bold")
    layers = [
        ("① tcache/fastbin 命中", "拿现成空闲块，无锁", "快 ~几十 ns", C_GOOD),
        ("② 需要加 arena 锁", "多线程争用 → 等锁", "不确定", C_ORANGE),
        ("③ bins 都没有 → 切 top chunk / brk()", "系统调用抬堆顶", "微秒级", C_BAD),
        ("④ 大块 → mmap 一整段", "陷内核映射", "微秒级", C_BAD),
        ("⑤ 首次访问新内存 → 缺页", "内核分配物理页(见O3)", "微秒~毫秒尖峰", C_BAD),
    ]
    y = 3.95
    for title, mid, cost, c in layers:
        ax.add_patch(FancyBboxPatch((0.4, y-0.34), 5.4, 0.64, boxstyle="round,pad=0.02",
                                    facecolor="white" if c != C_GOOD else C_SHARE, edgecolor=c, lw=1.7))
        ax.text(0.6, y, title, ha="left", va="center", fontsize=9, color="#222")
        ax.text(6.05, y, mid, ha="left", va="center", fontsize=8.3, color="#555")
        ax.text(9.75, y, cost, ha="right", va="center", fontsize=8.8, color=c, weight="bold")
        y -= 0.82
    ax.text(4.9, -0.15,
            "①是快路径(命中缓存)，但②③④⑤随时可能发生且不可预测 → malloc 延迟方差巨大。\n"
            "交易热路径要「每次都一样快」，而 malloc 给不了这个保证 → 用预分配内存池(C5-28)绕开整套逻辑。",
            ha="center", fontsize=9, color="#333", weight="bold")
    ax.set_xlim(0, 10); ax.set_ylim(-0.5, 4.9); ax.axis("off")
    ax.set_title("malloc 的「不确定」从哪来：一次调用可能踩中 5 层开销", fontsize=12, weight="bold")
    _save(fig, "malloc-2-costlayers.png")


# ── 图3：本机实测 分配延迟长尾（按 size）+ 内存池对照 ───────────────
def fig3_bench():
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(11.2, 4.6))

    # 左：不同 size 的 mean 与 max（对数），凸显大块的尖峰
    sizes = ["16B", "64B", "256B", "1KB", "4KB", "64KB", "1MB\n(mmap)"]
    mean = [23.9, 19.0, 22.7, 50.8, 163.3, 107.0, 648.3]
    mx   = [11000, 9334, 11000, 9625, 19417, 1298000, 12026958]
    x = np.arange(len(sizes))
    w = 0.38
    axL.bar(x - w/2, mean, w, color=C_BLUE, label="mean（典型）", edgecolor=C_EDGE, lw=0.8)
    axL.bar(x + w/2, mx,   w, color=C_BAD,  label="max（最坏一次）", edgecolor=C_EDGE, lw=0.8)
    axL.set_yscale("log")
    axL.set_ylim(10, 3e7)
    axL.yaxis.set_major_locator(mticker.FixedLocator([10, 1e2, 1e3, 1e4, 1e5, 1e6, 1e7]))
    axL.yaxis.set_major_formatter(mticker.FixedFormatter(["10", "100", "1us", "10us", "100us", "1ms", "10ms"]))
    axL.set_xticks(x); axL.set_xticklabels(sizes, fontsize=8)
    axL.set_ylabel("分配延迟 (ns, 对数轴)", fontsize=10)
    axL.legend(fontsize=8.5, loc="upper left")
    axL.set_title("不同 size 的 malloc：mean 稳定，但 max 尖峰随块变大而爆炸", fontsize=10, weight="bold")
    axL.annotate("1MB 块 max≈12ms!\n(mmap+缺页)", xy=(6, 12026958), xytext=(3.3, 5e6),
                 fontsize=8.5, color=C_BAD, weight="bold", ha="center",
                 arrowprops=dict(arrowstyle="->", color=C_BAD, lw=1.5))

    # 右：内存池 vs malloc（64B）的 mean 与 max
    labels = ["mean", "max（最坏一次）"]
    malloc_v = [15.6, 22750]
    pool_v = [11.8, 5958]
    xx = np.arange(2); ww = 0.36
    axR.bar(xx - ww/2, malloc_v, ww, color=C_BAD, label="malloc(64B)", edgecolor=C_EDGE, lw=0.8)
    axR.bar(xx + ww/2, pool_v, ww, color=C_GOOD, label="内存池 bump", edgecolor=C_EDGE, lw=0.8)
    axR.set_yscale("log")
    axR.set_ylim(5, 1e5)
    axR.yaxis.set_major_locator(mticker.FixedLocator([10, 1e2, 1e3, 1e4]))
    axR.yaxis.set_major_formatter(mticker.FixedFormatter(["10", "100", "1us", "10us"]))
    axR.set_xticks(xx); axR.set_xticklabels(labels, fontsize=9)
    axR.set_ylabel("延迟 (ns, 对数轴)", fontsize=10)
    axR.legend(fontsize=8.5, loc="upper left")
    axR.set_title("内存池 vs malloc：均值接近，但尾部 max 内存池低得多", fontsize=10, weight="bold")
    axR.text(0.5, 25000, "内存池的价值主要在\n消除尾部尖峰(确定性)", ha="center", fontsize=8.3, color=C_GOOD, weight="bold")

    fig.suptitle("本机实测(Apple Silicon)：malloc 均值不可怕，可怕的是不可预测的尾部尖峰(大块尤甚)",
                 fontsize=11, weight="bold", y=1.0)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    _save(fig, "malloc-3-bench.png")


if __name__ == "__main__":
    fig1_structure()
    fig2_costlayers()
    fig3_bench()
    print("ALL DONE")
