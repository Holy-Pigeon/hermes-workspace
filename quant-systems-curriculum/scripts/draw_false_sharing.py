#!/usr/bin/env python3
"""生成「false sharing & cache line」课时配图（5 张）。直接画机制本身。
性能数字全部来自本机实测（bench_false_sharing.cpp / probe_cacheline.cpp）。
输出到 ../assets/fs-*.png，DPI 150，白底。避免 µ/✓/✗ 缺字形字符。"""
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
C_A = "#d62728"     # 变量a / 核1 红
C_B = "#2ca02c"     # 变量b / 核2 绿
C_LINE = "#7048e8"  # cache line 紫
C_BOX = "white"
C_BAD = "#d62728"
C_GOOD = "#2ca02c"
C_GREY = "#888"


def _save(fig, name):
    p = OUT / name
    fig.savefig(p, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("saved", p)


def _box(ax, x, y, t, color, w=3.0, h=0.6, fs=10, fc=C_BOX):
    ax.add_patch(FancyBboxPatch((x - w/2, y - h/2), w, h, boxstyle="round,pad=0.02",
                                facecolor=fc, edgecolor=color, lw=1.8))
    ax.text(x, y, t, ha="center", va="center", fontsize=fs)


# ── 图1：现象——互不共享却互相拖慢 ──────────────────────────
def fig1_phenomenon():
    fig, ax = plt.subplots(figsize=(10.5, 4.2))
    # 两个线程
    _box(ax, 2.2, 3.4, "线程 1\n只写 a", C_A, w=2.4, h=1.0, fs=11)
    _box(ax, 7.8, 3.4, "线程 2\n只写 b", C_B, w=2.4, h=1.0, fs=11)
    ax.text(5.0, 3.4, "零共享\n零依赖", ha="center", va="center", fontsize=10,
            color=C_GREY, style="italic")
    # 期望 vs 实际
    _box(ax, 2.2, 1.6, "期望：完美并行", C_GOOD, w=3.2, h=0.7, fs=10.5)
    _box(ax, 7.8, 1.6, "实际：慢 3.72 倍", C_BAD, w=3.2, h=0.7, fs=10.5, fc="#ffe3e3")
    ax.annotate("", xy=(6.2, 1.6), xytext=(3.8, 1.6),
                arrowprops=dict(arrowstyle="->", color=C_BAD, lw=2.2))
    ax.text(5.0, 1.95, "为什么？", ha="center", fontsize=10.5, color=C_BAD, weight="bold")
    ax.text(5.0, 0.55, "代码层面互不共享，硬件缓存层面却被绑在同一条 cache line 上\n这就是 false sharing（伪共享）",
            ha="center", fontsize=10.5, color=C_EDGE, weight="bold")
    ax.set_xlim(0, 10); ax.set_ylim(0, 4.3); ax.axis("off")
    fig.suptitle("反直觉现象：两个线程各写一个变量、互不共享，却互相拖慢",
                 fontsize=13, weight="bold", y=1.0)
    fig.tight_layout()
    _save(fig, "fs-1-phenomenon.png")


# ── 图2：cache line 是缓存的最小搬运单位 ──────────────────────
def fig2_cacheline():
    fig, ax = plt.subplots(figsize=(10.5, 4.0))
    # 内存：一条 line 64B，含 8 个 8B 槽
    y = 2.6
    x0 = 0.6
    slot_w = 1.05
    labels = ["a", "b", "", "", "", "", "", ""]
    cols = [C_A, C_B, "white", "white", "white", "white", "white", "white"]
    for i in range(8):
        fc = "#ffe3e3" if i == 0 else ("#e3fbe3" if i == 1 else "white")
        ax.add_patch(Rectangle((x0 + i*slot_w, y), slot_w, 0.8,
                               facecolor=fc, edgecolor=C_EDGE, lw=1.3))
        if labels[i]:
            ax.text(x0 + i*slot_w + slot_w/2, y+0.4, labels[i], ha="center", va="center",
                    fontsize=12, weight="bold", color=cols[i])
        ax.text(x0 + i*slot_w + slot_w/2, y-0.25, f"{i*8}B", ha="center", va="center",
                fontsize=8, color=C_GREY)
    # 整条 line 的大括号
    ax.add_patch(Rectangle((x0, y), 8*slot_w, 0.8, fill=False, edgecolor=C_LINE, lw=2.6))
    ax.text(x0 + 4*slot_w, y+1.25, "一条 cache line = 64 字节（缓存与内存交换的最小单位）",
            ha="center", fontsize=11, color=C_LINE, weight="bold")
    # 下方说明
    ax.text(x0 + 4*slot_w, 1.5,
            "你只读了 8 字节的 a，CPU 却把整条 64B line 一起拉进缓存",
            ha="center", fontsize=10.5, color=C_EDGE)
    ax.text(x0 + 4*slot_w, 0.9,
            "后果：a 和 b 间距 < 一条 line → 它们落在同一条 line → 硬件眼里是「同一块货」",
            ha="center", fontsize=10.5, color=C_BAD, weight="bold")
    ax.set_xlim(0, 9.4); ax.set_ylim(0.4, 4.2); ax.axis("off")
    fig.suptitle("根因：CPU 缓存的最小单位是 cache line，不是「一个变量」",
                 fontsize=13, weight="bold", y=1.0)
    fig.tight_layout()
    _save(fig, "fs-2-cacheline.png")


# ── 图3：MESI 乒乓 ──────────────────────────────────────────
def fig3_mesi():
    fig, ax = plt.subplots(figsize=(10.5, 4.8))
    # 核1 核2 各有一份 line 副本
    _box(ax, 2.2, 4.0, "核 1 缓存", C_A, w=2.8, h=0.7, fs=11)
    _box(ax, 7.8, 4.0, "核 2 缓存", C_B, w=2.8, h=0.7, fs=11)
    # line 副本
    ax.add_patch(Rectangle((1.0, 3.0), 2.4, 0.55, facecolor="#ffe3e3", edgecolor=C_EDGE, lw=1.3))
    ax.text(2.2, 3.27, "line[a,b]", ha="center", va="center", fontsize=9.5)
    ax.add_patch(Rectangle((6.6, 3.0), 2.4, 0.55, facecolor="#e3fbe3", edgecolor=C_EDGE, lw=1.3))
    ax.text(7.8, 3.27, "line[a,b]", ha="center", va="center", fontsize=9.5)
    # 乒乓步骤
    steps = [
        ("1. 核1 写 a → 独占整条 line → 让核2 副本失效", C_A, 1.85),
        ("2. 核2 写 b → 同一条 line → 抢回独占 → 核1 副本失效", C_B, 1.25),
        ("3. 核1 又写 a → 再抢回来……line 在两核间反复横跳", C_BAD, 0.65),
    ]
    for txt, col, yy in steps:
        ax.text(5.0, yy, txt, ha="center", fontsize=10.3, color=col, weight="bold")
    # 双向乒乓箭头（弧度调小，避免下弧压到文字）
    ax.annotate("", xy=(6.5, 3.27), xytext=(3.5, 3.27),
                arrowprops=dict(arrowstyle="->", color=C_BAD, lw=2.2,
                                connectionstyle="arc3,rad=-0.22"))
    ax.annotate("", xy=(3.5, 3.27), xytext=(6.5, 3.27),
                arrowprops=dict(arrowstyle="->", color=C_BAD, lw=2.2,
                                connectionstyle="arc3,rad=-0.22"))
    ax.text(5.0, 2.5, "cache line 乒乓（ping-pong）：每次抢夺走核间互联，几十~上百周期",
            ha="center", fontsize=9.8, color=C_BAD, style="italic")
    ax.set_xlim(0, 10); ax.set_ylim(0.2, 4.7); ax.axis("off")
    fig.suptitle("MESI 协议：一条 line 同时只能一个核独占写 → 互相作废 → 乒乓",
                 fontsize=12.5, weight="bold", y=1.0)
    fig.tight_layout()
    _save(fig, "fs-3-mesi-pingpong.png")


# ── 图4：padding 前后对比 ────────────────────────────────────
def fig4_padding():
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    slot_w = 0.9
    # 左：紧挨，同一条 line
    ax = axes[0]
    x0 = 0.4
    for i in range(8):
        fc = "#ffe3e3" if i == 0 else ("#e3fbe3" if i == 1 else "white")
        ax.add_patch(Rectangle((x0 + i*slot_w, 1.6), slot_w, 0.8,
                               facecolor=fc, edgecolor=C_EDGE, lw=1.2))
    ax.text(x0+0.5*slot_w, 2.0, "a", ha="center", va="center", fontsize=12, weight="bold", color=C_A)
    ax.text(x0+1.5*slot_w, 2.0, "b", ha="center", va="center", fontsize=12, weight="bold", color=C_B)
    ax.add_patch(Rectangle((x0, 1.6), 8*slot_w, 0.8, fill=False, edgecolor=C_LINE, lw=2.4))
    ax.text(x0+4*slot_w, 2.75, "同一条 cache line", ha="center", fontsize=10.5, color=C_LINE, weight="bold")
    ax.text(x0+4*slot_w, 1.1, "a、b 紧挨 → 乒乓 → 慢 3.72×", ha="center", fontsize=10.5, color=C_BAD, weight="bold")
    ax.text(x0+4*slot_w, 0.55, "struct { atomic<int64_t> a, b; }", ha="center", fontsize=9, color=C_GREY, family="monospace")
    ax.set_xlim(0, 7.8); ax.set_ylim(0.2, 3.1); ax.axis("off")
    # 右：alignas 撑开
    ax = axes[1]
    x0 = 0.4
    # line1 只放 a
    for i in range(8):
        fc = "#ffe3e3" if i == 0 else "white"
        ax.add_patch(Rectangle((x0 + i*slot_w, 2.3), slot_w, 0.7,
                               facecolor=fc, edgecolor=C_EDGE, lw=1.0))
    ax.text(x0+0.5*slot_w, 2.65, "a", ha="center", va="center", fontsize=11, weight="bold", color=C_A)
    ax.add_patch(Rectangle((x0, 2.3), 8*slot_w, 0.7, fill=False, edgecolor=C_A, lw=2.2))
    # line2 只放 b
    for i in range(8):
        fc = "#e3fbe3" if i == 0 else "white"
        ax.add_patch(Rectangle((x0 + i*slot_w, 1.3), slot_w, 0.7,
                               facecolor=fc, edgecolor=C_EDGE, lw=1.0))
    ax.text(x0+0.5*slot_w, 1.65, "b", ha="center", va="center", fontsize=11, weight="bold", color=C_B)
    ax.add_patch(Rectangle((x0, 1.3), 8*slot_w, 0.7, fill=False, edgecolor=C_B, lw=2.2))
    ax.text(x0+4*slot_w, 3.25, "各自独占一条 line", ha="center", fontsize=10.5, color=C_GOOD, weight="bold")
    ax.text(x0+4*slot_w, 0.8, "alignas(64) 撑开 → 无乒乓 → 基准速度", ha="center", fontsize=10.5, color=C_GOOD, weight="bold")
    ax.text(x0+4*slot_w, 0.3, "alignas(64) ... a;  alignas(64) ... b;", ha="center", fontsize=8.5, color=C_GREY, family="monospace")
    ax.set_xlim(0, 7.8); ax.set_ylim(0.0, 3.5); ax.axis("off")
    fig.suptitle("解法：用 alignas 把热点变量撑到各自独占一条 cache line（空间换吞吐）",
                 fontsize=12.5, weight="bold", y=1.02)
    fig.tight_layout()
    _save(fig, "fs-4-padding.png")


# ── 图5：实测间距扫描曲线（真实数据）────────────────────────
def fig5_measured():
    # 本机实测数据 probe_cacheline.cpp
    gaps = [8, 16, 32, 64, 128, 256]
    times = [0.829, 0.712, 0.538, 0.160, 0.160, 0.160]
    fig, ax = plt.subplots(figsize=(10, 4.6))
    xs = np.arange(len(gaps))
    colors = [C_BAD if t > 0.2 else C_GOOD for t in times]
    bars = ax.bar(xs, times, color=colors, edgecolor=C_EDGE, lw=1.0, width=0.62, zorder=3)
    for x, t in zip(xs, times):
        ax.text(x, t + 0.02, f"{t:.3f}s", ha="center", fontsize=10, weight="bold",
                color=(C_BAD if t > 0.2 else C_GOOD))
    ax.set_xticks(xs)
    ax.set_xticklabels([f"{g}B" for g in gaps], fontsize=11)
    ax.set_xlabel("两个计数器的内存间距", fontsize=11)
    ax.set_ylabel("耗时（秒，越低越好）", fontsize=11)
    ax.set_ylim(0, 1.05)
    ax.grid(axis="y", ls="--", alpha=0.4, zorder=0)
    # 标注拐点：虚线放在 32B(idx2) 与 64B(idx3) 之间的间隙，避免穿过柱子
    ax.axvline(2.5, color=C_LINE, ls="--", lw=1.6, alpha=0.7, zorder=2)
    ax.text(2.5, 0.78, "拐点：64B 处\nfalse sharing 消失", ha="center", fontsize=9.8,
            color=C_LINE, weight="bold")
    # 5.2x 标注放在 8B 柱子上方空白处，不挡柱子
    ax.text(0, 0.95, "间距越小争抢越凶\n8B 时慢 5.2×", ha="center", fontsize=9.5,
            color=C_BAD, weight="bold")
    ax.set_title("本机实测：间距扫描曲线，cache line 在此「显形」（Apple Silicon, line=128B 报告值）",
                 fontsize=12, weight="bold")
    fig.tight_layout()
    _save(fig, "fs-5-measured.png")


if __name__ == "__main__":
    fig1_phenomenon()
    fig2_cacheline()
    fig3_mesi()
    fig4_padding()
    fig5_measured()
    print("ALL DONE")
