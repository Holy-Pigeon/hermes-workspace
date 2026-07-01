#!/usr/bin/env python3
"""生成「NUMA 架构」课时配图（4 张）。直接画机制本身。
访存局部性数字来自本机实测（bench_mem_locality.cpp）；NUMA 拓扑为机制示意。
输出到 ../assets/numa-*.png，DPI 150，白底。避免 µ/✓/✗ 缺字形字符。"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle, FancyArrowPatch
import numpy as np
from pathlib import Path

plt.rcParams["font.sans-serif"] = ["Hiragino Sans GB", "Songti SC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

OUT = Path(__file__).resolve().parents[1] / "assets"
OUT.mkdir(exist_ok=True)

C_EDGE = "#3b4252"
C_RED = "#d62728"
C_GREEN = "#2ca02c"
C_BLUE = "#1f77b4"
C_PURPLE = "#7048e8"
C_ORANGE = "#e8830c"
C_GREY = "#888"
C_BOX = "white"


def _save(fig, name):
    p = OUT / name
    fig.savefig(p, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("saved", p)


def _box(ax, x, y, t, color, w=2.0, h=0.7, fs=9.5, fc=C_BOX):
    ax.add_patch(FancyBboxPatch((x - w/2, y - h/2), w, h, boxstyle="round,pad=0.02",
                                facecolor=fc, edgecolor=color, lw=1.6))
    ax.text(x, y, t, ha="center", va="center", fontsize=fs)


# ── 图1：访存局部性 顺序 vs 随机（本机实测，对数轴）──────────
def fig1_locality():
    fig, ax = plt.subplots(figsize=(8.5, 5.0))
    names = ["顺序访问\n(预取器友好)", "随机访问\n(预取器失效)"]
    vals = [1.10, 90.54]
    colors = [C_GREEN, C_RED]
    xs = np.arange(len(names))
    ax.bar(xs, vals, color=colors, edgecolor=C_EDGE, lw=1.0, width=0.5, zorder=3)
    ax.set_yscale("log")
    for x, v in zip(xs, vals):
        ax.text(x, v*1.25, f"{v:.2f} ns", ha="center", fontsize=12, weight="bold",
                color=(C_GREEN if v < 10 else C_RED))
    ax.set_xticks(xs); ax.set_xticklabels(names, fontsize=10.5)
    ax.set_ylabel("单次访存延迟（ns，对数轴）", fontsize=11)
    ax.set_ylim(0.5, 300)
    ax.grid(axis="y", ls="--", alpha=0.4, zorder=0)
    ax.text(0.5, 200, "同一块256MB内存，仅访问「远近/可预测性」不同\n延迟差 82 倍 → 「数据离CPU越远越慢」是铁律",
            ha="center", fontsize=10, color=C_RED, weight="bold",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#ffe3e3", edgecolor=C_RED))
    ax.set_title("访存延迟极度依赖局部性（本机实测，NUMA 同源原理）",
                 fontsize=12, weight="bold")
    fig.tight_layout()
    _save(fig, "numa-1-locality.png")


# ── 图2：UMA vs NUMA ──────────────────────────────────────
def fig2_uma_vs_numa():
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    # 左：UMA
    ax = axes[0]
    for i in range(4):
        _box(ax, 1.2 + i*1.5, 4.0, f"核{i}", C_BLUE, w=1.0, h=0.6, fs=9.5)
    ax.add_patch(FancyBboxPatch((0.5, 2.6), 6.0, 0.55, boxstyle="round,pad=0.02",
                                facecolor="#f0f0f0", edgecolor=C_EDGE, lw=1.5))
    ax.text(3.5, 2.87, "共享内存总线", ha="center", fontsize=9.5, color=C_EDGE)
    _box(ax, 3.5, 1.4, "全部内存（等距）", C_GREY, w=5.0, h=0.7, fs=10)
    for i in range(4):
        ax.annotate("", xy=(1.2 + i*1.5, 2.65), xytext=(1.2 + i*1.5, 3.7),
                    arrowprops=dict(arrowstyle="-", color=C_GREY, lw=1.0))
    ax.annotate("", xy=(3.5, 1.75), xytext=(3.5, 2.55),
                arrowprops=dict(arrowstyle="<->", color=C_GREY, lw=1.2))
    ax.text(3.5, 0.6, "UMA：任何核访问任何内存，延迟一样", ha="center",
            fontsize=10, color=C_EDGE, weight="bold")
    ax.set_xlim(0, 7); ax.set_ylim(0.2, 4.6); ax.axis("off")
    # 右：NUMA
    ax = axes[1]
    # node0
    _box(ax, 1.6, 4.0, "核0 核1", C_GREEN, w=1.8, h=0.55, fs=9)
    _box(ax, 1.6, 2.9, "本地内存\nnode0", C_GREEN, w=1.8, h=0.75, fs=9, fc="#e3fbe3")
    ax.annotate("", xy=(1.6, 3.3), xytext=(1.6, 3.7),
                arrowprops=dict(arrowstyle="<->", color=C_GREEN, lw=1.6))
    ax.text(1.6, 4.55, "node0", ha="center", fontsize=9.5, color=C_GREEN, weight="bold")
    # node1
    _box(ax, 5.4, 4.0, "核2 核3", C_BLUE, w=1.8, h=0.55, fs=9)
    _box(ax, 5.4, 2.9, "本地内存\nnode1", C_BLUE, w=1.8, h=0.75, fs=9, fc="#d6e4ff")
    ax.annotate("", xy=(5.4, 3.3), xytext=(5.4, 3.7),
                arrowprops=dict(arrowstyle="<->", color=C_BLUE, lw=1.6))
    ax.text(5.4, 4.55, "node1", ha="center", fontsize=9.5, color=C_BLUE, weight="bold")
    # 跨 node 互联（慢）
    ax.annotate("", xy=(4.5, 2.9), xytext=(2.5, 2.9),
                arrowprops=dict(arrowstyle="<->", color=C_RED, lw=2.0, ls="--"))
    ax.text(3.5, 3.15, "跨 node 互联\n(UPI/Fabric)", ha="center", fontsize=8.5, color=C_RED, weight="bold")
    ax.text(3.5, 2.55, "慢 1.5~2 倍", ha="center", fontsize=8.5, color=C_RED, weight="bold")
    ax.text(3.5, 0.6, "NUMA：本地快，远端慢约一倍", ha="center",
            fontsize=10, color=C_EDGE, weight="bold")
    ax.set_xlim(0, 7); ax.set_ylim(0.2, 4.9); ax.axis("off")
    fig.suptitle("UMA（所有内存等距）vs NUMA（内存分节点，本地近远端远）",
                 fontsize=12.5, weight="bold", y=1.02)
    fig.tight_layout()
    _save(fig, "numa-2-uma-vs-numa.png")


# ── 图3：first-touch 陷阱 ────────────────────────────────
def fig3_first_touch():
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    # 左：陷阱
    ax = axes[0]
    _box(ax, 1.8, 4.0, "主线程\n(在 node0)", C_RED, w=2.0, h=0.75, fs=9.5)
    ax.text(1.8, 3.3, "malloc + memset\n(first-touch)", ha="center", fontsize=8.5, color=C_RED)
    _box(ax, 1.8, 2.2, "内存全落 node0", C_RED, w=2.2, h=0.6, fs=9, fc="#ffe3e3")
    ax.annotate("", xy=(1.8, 2.55), xytext=(1.8, 3.0),
                arrowprops=dict(arrowstyle="->", color=C_RED, lw=1.6))
    _box(ax, 5.0, 2.2, "工作线程\n(在 node1)", C_ORANGE, w=1.9, h=0.75, fs=9)
    ax.annotate("", xy=(2.95, 2.2), xytext=(4.0, 2.2),
                arrowprops=dict(arrowstyle="->", color=C_RED, lw=1.8, ls="--"))
    ax.text(3.5, 2.5, "跨 node 访问", ha="center", fontsize=8.5, color=C_RED, weight="bold")
    ax.text(3.4, 0.9, "陷阱：主线程统一初始化\n→ 内存全挤 node0\n→ node1 线程全程跨 node,慢一倍",
            ha="center", fontsize=9.2, color=C_RED, weight="bold")
    ax.set_title("错误：主线程统一 first-touch", fontsize=10.5, weight="bold", color=C_RED)
    ax.set_xlim(0, 7); ax.set_ylim(0.3, 4.6); ax.axis("off")
    # 右：正解
    ax = axes[1]
    _box(ax, 1.8, 3.6, "node0 线程\n初始化自己的块", C_GREEN, w=2.2, h=0.75, fs=9)
    _box(ax, 1.8, 2.2, "内存落 node0", C_GREEN, w=2.0, h=0.6, fs=9, fc="#e3fbe3")
    ax.annotate("", xy=(1.8, 2.55), xytext=(1.8, 3.2),
                arrowprops=dict(arrowstyle="->", color=C_GREEN, lw=1.5))
    _box(ax, 5.0, 3.6, "node1 线程\n初始化自己的块", C_BLUE, w=2.2, h=0.75, fs=9)
    _box(ax, 5.0, 2.2, "内存落 node1", C_BLUE, w=2.0, h=0.6, fs=9, fc="#d6e4ff")
    ax.annotate("", xy=(5.0, 2.55), xytext=(5.0, 3.2),
                arrowprops=dict(arrowstyle="->", color=C_BLUE, lw=1.5))
    ax.text(3.4, 0.9, "正解：谁用谁初始化\n→ 内存就近落到该线程的 node\n→ 全程本地访问", ha="center",
            fontsize=9.2, color=C_GREEN, weight="bold")
    ax.set_title("正确：谁用谁 first-touch", fontsize=10.5, weight="bold", color=C_GREEN)
    ax.set_xlim(0, 7); ax.set_ylim(0.3, 4.6); ax.axis("off")
    fig.suptitle("first-touch 坑：物理页落在「首次写它的核」所在 node，不由 malloc 决定",
                 fontsize=12, weight="bold", y=1.02)
    fig.tight_layout()
    _save(fig, "numa-3-first-touch.png")


# ── 图4：三对齐（线程+内存+网卡同 node）──────────────────
def fig4_alignment():
    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    # node1 大框
    ax.add_patch(FancyBboxPatch((2.5, 1.2), 5.5, 3.3, boxstyle="round,pad=0.05",
                                facecolor="#e3fbe3", edgecolor=C_GREEN, lw=2.2))
    ax.text(5.25, 4.15, "同一个 NUMA node（node1）", ha="center", fontsize=11,
            color=C_GREEN, weight="bold")
    _box(ax, 4.0, 3.3, "交易线程\n(绑到本node核)", C_PURPLE, w=2.2, h=0.85, fs=9.5, fc="white")
    _box(ax, 6.6, 3.3, "行情缓冲区\n(本地内存)", C_BLUE, w=2.2, h=0.85, fs=9.5, fc="white")
    _box(ax, 5.25, 1.9, "接收网卡\n(本node挂载)", C_ORANGE, w=2.4, h=0.85, fs=9.5, fc="white")
    # 内部三角连线（都近）
    ax.annotate("", xy=(5.7, 3.3), xytext=(5.0, 3.3),
                arrowprops=dict(arrowstyle="<->", color=C_GREEN, lw=1.6))
    ax.annotate("", xy=(4.5, 2.3), xytext=(4.3, 2.9),
                arrowprops=dict(arrowstyle="<->", color=C_GREEN, lw=1.6))
    ax.annotate("", xy=(6.1, 2.3), xytext=(6.3, 2.9),
                arrowprops=dict(arrowstyle="<->", color=C_GREEN, lw=1.6))
    ax.text(5.25, 0.6, "三者钉在同一 node → 全程本地访问,零跨node税",
            ha="center", fontsize=10, color=C_GREEN, weight="bold")
    ax.text(5.25, 4.85, "numactl --cpunodebind=1 --membind=1  +  网卡绑本 node 核",
            ha="center", fontsize=9.5, color=C_EDGE)
    ax.set_xlim(0, 10.5); ax.set_ylim(0.2, 5.2); ax.axis("off")
    fig.suptitle("NUMA 三对齐：线程 + 内存 + 网卡，全部在同一节点",
                 fontsize=12.5, weight="bold", y=1.0)
    fig.tight_layout()
    _save(fig, "numa-4-alignment.png")


if __name__ == "__main__":
    fig1_locality()
    fig2_uma_vs_numa()
    fig3_first_touch()
    fig4_alignment()
    print("ALL DONE")
