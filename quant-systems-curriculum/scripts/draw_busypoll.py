#!/usr/bin/env python3
"""生成「busy-polling 忙等 vs 阻塞」课时配图（4 张）。直接画机制本身。
忙等/阻塞唤醒延迟来自本机实测（bench_busypoll.cpp），对数 Y 轴。
输出到 ../assets/bp-*.png，DPI 150，白底。避免 µ/✓/✗ 缺字形字符（用 us）。"""
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


# ── 图1：两种等待哲学对比 ────────────────────────────────
def fig1_two_ways():
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4))
    # 左：busy-poll
    ax = axes[0]
    _box(ax, 2.5, 3.6, "消费者线程", C_GREEN, w=2.4, h=0.6, fs=10)
    ax.text(2.5, 2.9, "while(!ready) {}", ha="center", fontsize=9.5, color=C_GREEN, family="monospace")
    ax.text(2.5, 2.55, "死循环反复查标志", ha="center", fontsize=9.3, color=C_GREEN)
    ax.text(2.5, 1.9, "一直在 CPU 上转（不睡）", ha="center", fontsize=9.5, color=C_GREEN, weight="bold")
    ax.text(2.5, 1.2, "CPU 100% | 延迟极低且确定", ha="center", fontsize=9.3, color=C_EDGE)
    ax.text(2.5, 0.6, "数据一到,下一圈立刻发现", ha="center", fontsize=9.3, color=C_GREEN, weight="bold")
    ax.set_title("busy-polling 忙等", fontsize=11, weight="bold", color=C_GREEN)
    ax.set_xlim(0, 5); ax.set_ylim(0.3, 4.1); ax.axis("off")
    # 右：blocking
    ax = axes[1]
    _box(ax, 2.5, 3.6, "消费者线程", C_RED, w=2.4, h=0.6, fs=10)
    ax.text(2.5, 2.75, "epoll_wait / cv.wait()\n睡下去,让出 CPU", ha="center", fontsize=9.5, color=C_RED)
    ax.text(2.5, 1.9, "睡在等待队列（不占 CPU）", ha="center", fontsize=9.5, color=C_RED, weight="bold")
    ax.text(2.5, 1.2, "CPU ~0 | 延迟高且有抖动", ha="center", fontsize=9.3, color=C_EDGE)
    ax.text(2.5, 0.6, "数据到,内核唤醒→调度→上CPU", ha="center", fontsize=9.3, color=C_RED, weight="bold")
    ax.set_title("blocking 阻塞等待", fontsize=11, weight="bold", color=C_RED)
    ax.set_xlim(0, 5); ax.set_ylim(0.3, 4.1); ax.axis("off")
    fig.suptitle("两种「等数据」哲学：忙等（占CPU换低延迟）vs 阻塞（省CPU有唤醒延迟）",
                 fontsize=12, weight="bold", y=1.02)
    fig.tight_layout()
    _save(fig, "bp-1-two-ways.png")


# ── 图2：实测延迟对比（对数Y轴）──────────────────────────
def fig2_measured():
    labels = ["p50", "p99", "p99.9", "max"]
    busy = [83, 167, 3167, 9250]
    block = [13958, 18958, 35292, 88167]
    fig, ax = plt.subplots(figsize=(10, 5.0))
    x = np.arange(len(labels)); w = 0.36
    ax.bar(x - w/2, busy, w, label="busy-poll 忙等", color=C_GREEN, edgecolor=C_EDGE, lw=0.8, zorder=3)
    ax.bar(x + w/2, block, w, label="blocking 阻塞唤醒", color=C_RED, edgecolor=C_EDGE, lw=0.8, zorder=3)
    ax.set_yscale("log")
    for xi, v in zip(x - w/2, busy):
        ax.text(xi, v*1.3, f"{v}", ha="center", fontsize=8.5, color=C_GREEN, weight="bold")
    for xi, v in zip(x + w/2, block):
        ax.text(xi, v*1.3, f"{v}", ha="center", fontsize=8.5, color=C_RED, weight="bold")
    ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("数据发布→感知 延迟（ns，对数轴）", fontsize=11)
    ax.set_ylim(30, 3e5)
    ax.legend(fontsize=10, loc="upper left")
    ax.grid(axis="y", ls="--", alpha=0.4, zorder=0)
    ax.text(2.0, 1.2e5, "忙等 p50=83ns vs 阻塞 p50=13958ns\n→ 忙等快约 168 倍",
            ha="center", fontsize=10.5, color=C_EDGE, weight="bold",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#fff3cd", edgecolor=C_EDGE))
    ax.set_title("忙等 vs 阻塞唤醒 延迟（本机实测各2万次，对数Y轴）",
                 fontsize=11.5, weight="bold")
    fig.tight_layout()
    _save(fig, "bp-2-measured.png")


# ── 图3：忙等消灭了「唤醒往返」──────────────────────────
def fig3_why_fast():
    fig, axes = plt.subplots(2, 1, figsize=(11, 5.4))
    # 上：阻塞的长链条
    ax = axes[0]
    stages = [("数据到达", C_BLUE), ("内核唤醒", C_RED), ("等调度器", C_RED),
              ("上下文切换恢复", C_RED), ("冷cache", C_RED), ("终于处理", C_GREEN)]
    x0 = 0.6; dx = 1.85
    for i, (t, col) in enumerate(stages):
        _box(ax, x0 + i*dx, 1.0, t, col, w=1.5, h=0.6, fs=8.5,
             fc=("#ffe3e3" if col==C_RED else "white"))
        if i < len(stages)-1:
            ax.annotate("", xy=(x0+i*dx+0.85, 1.0), xytext=(x0+i*dx+0.75, 1.0),
                        arrowprops=dict(arrowstyle="->", color=C_GREY, lw=1.4))
    ax.text(x0 + 2.5*dx, 1.85, "阻塞：中间这段「唤醒往返」= 微秒级 + 抖动", ha="center",
            fontsize=10, color=C_RED, weight="bold")
    ax.set_xlim(0, x0+6*dx); ax.set_ylim(0.4, 2.2); ax.axis("off")
    # 下：忙等直达
    ax = axes[1]
    _box(ax, 1.5, 1.0, "数据到达", C_BLUE, w=1.6, h=0.6, fs=9)
    _box(ax, 4.5, 1.0, "下一圈循环\n(几纳秒)", C_GREEN, w=1.8, h=0.7, fs=8.5, fc="#e3fbe3")
    _box(ax, 7.5, 1.0, "立刻处理", C_GREEN, w=1.6, h=0.6, fs=9, fc="#e3fbe3")
    ax.annotate("", xy=(3.5, 1.0), xytext=(2.4, 1.0), arrowprops=dict(arrowstyle="->", color=C_GREY, lw=1.4))
    ax.annotate("", xy=(6.5, 1.0), xytext=(5.5, 1.0), arrowprops=dict(arrowstyle="->", color=C_GREY, lw=1.4))
    ax.text(4.5, 1.85, "忙等：线程一直在CPU上转,无内核介入,cache 常热", ha="center",
            fontsize=10, color=C_GREEN, weight="bold")
    ax.set_xlim(0, 11.4); ax.set_ylim(0.4, 2.2); ax.axis("off")
    fig.suptitle("忙等为什么快：消灭了「唤醒睡着线程 + 调度 + 冷cache」这一段",
                 fontsize=12.5, weight="bold", y=1.0)
    fig.tight_layout()
    _save(fig, "bp-3-why-fast.png")


# ── 图4：忙等的代价 ──────────────────────────────────────
def fig4_cost():
    fig, ax = plt.subplots(figsize=(10.5, 5.0))
    # 一个核 100% 占用
    _box(ax, 2.5, 3.8, "隔离核（独占）", C_GREEN, w=2.6, h=0.6, fs=10, fc="#e3fbe3")
    ax.add_patch(Rectangle((1.2, 2.3), 2.6, 1.0, facecolor=C_ORANGE, edgecolor=C_EDGE, lw=1.5, alpha=0.85))
    ax.text(2.5, 2.8, "忙等线程\n100% 空转", ha="center", va="center", fontsize=9.5, color="white", weight="bold")
    ax.text(2.5, 1.8, "哪怕没数据也满速转\n功耗高、发热大", ha="center", fontsize=9, color=C_ORANGE, weight="bold")
    # 代价清单
    costs = [
        "1. 一整个核 100% 占用,只干这一件事",
        "2. 必须配绑核+隔离独占(否则抢别人CPU/自己被换下)",
        "3. 核数有限,只有关键路径(行情/下单)才值得",
    ]
    for i, c in enumerate(costs):
        ax.text(5.2, 3.5 - i*0.7, c, fontsize=9.8, color=C_EDGE, va="center")
    ax.text(5.3, 0.9, "本质:烧掉一整个核的算力+电费,换纳秒级无抖动响应\n——仅在关键路径上这笔交易才划算",
            ha="center", fontsize=9.8, color=C_RED, weight="bold")
    ax.set_xlim(0, 10.5); ax.set_ylim(0.4, 4.4); ax.axis("off")
    fig.suptitle("忙等的代价：用一整个核的 100% 空转,换确定性低延迟",
                 fontsize=12.5, weight="bold", y=1.0)
    fig.tight_layout()
    _save(fig, "bp-4-cost.png")


if __name__ == "__main__":
    fig1_two_ways()
    fig2_measured()
    fig3_why_fast()
    fig4_cost()
    print("ALL DONE")
