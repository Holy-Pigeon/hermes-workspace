#!/usr/bin/env python3
"""生成「内存预热与锁页」课时配图（4 张）。直接画机制本身。
缺页延迟分布来自本机实测（bench_pagefault.cpp），强制对数 Y 轴。
输出到 ../assets/pf-*.png，DPI 150，白底。避免 µ/✓/✗ 缺字形字符。"""
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


# ── 图1：缺页 vs 预热后 延迟分布（对数Y轴，本机实测）──────────
def fig1_distribution():
    bins = ["0-100","100-200","200-500","500-1k","1k-2k","2k-5k","5k-10k","10k-50k","50k+"]
    cold = [149995, 3, 70, 28801, 20238, 559, 207, 125, 2]
    hot  = [173318, 19, 9412, 16710, 426, 112, 3, 0, 0]
    fig, ax = plt.subplots(figsize=(11.5, 5.2))
    xs = np.arange(len(bins)); w = 0.4
    b1 = ax.bar(xs - w/2, cold, w, label="首次访问(触发缺页)", color=C_RED, edgecolor=C_EDGE, lw=0.6, zorder=3)
    b2 = ax.bar(xs + w/2, [max(v,0.5) for v in hot], w, label="预热后(无缺页)", color=C_GREEN, edgecolor=C_EDGE, lw=0.6, zorder=3)
    ax.set_yscale("log")
    ax.set_xticks(xs); ax.set_xticklabels(bins, fontsize=9, rotation=20)
    ax.set_xlabel("单次写入耗时区间（ns）", fontsize=11)
    ax.set_ylabel("次数（对数轴）", fontsize=11)
    ax.set_ylim(0.5, 5e5)
    ax.legend(fontsize=9.5, loc="upper right")
    ax.grid(axis="y", ls="--", alpha=0.4, zorder=0)
    # 标注尖峰区
    ax.annotate("缺页尾部尖峰\n2万+次落在1-2us\n数百次冲到5-50us", xy=(4-0.2, 20238), xytext=(2.3, 1.2e5),
                ha="center", fontsize=9.2, color=C_RED, weight="bold",
                arrowprops=dict(arrowstyle="->", color=C_RED, lw=1.6))
    ax.text(6.3, 6e4, "预热后同样的页\n尖峰桶基本清零", ha="center", fontsize=9.2, color=C_GREEN, weight="bold")
    ax.text(5.5, 3e5, "缺页 max=12ms(!) = 预热后的 1377 倍", ha="center", fontsize=10.5,
            color=C_RED, weight="bold",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#ffe3e3", edgecolor=C_RED))
    ax.set_title("缺页 vs 预热后 延迟分布（本机实测800MB，对数Y轴让尖峰可见）",
                 fontsize=11.5, weight="bold")
    fig.tight_layout()
    _save(fig, "pf-1-distribution.png")


# ── 图2：minor vs major fault ────────────────────────────
def fig2_fault_types():
    fig, ax = plt.subplots(figsize=(11, 4.6))
    # minor
    _box(ax, 2.5, 3.6, "minor fault（次缺页）", C_ORANGE, w=3.4, h=0.7, fs=10.5)
    ax.text(2.5, 2.85, "页在物理内存里\n只是当前进程没建映射\n(首次访问 / 写时复制COW)", ha="center", fontsize=9, color=C_EDGE)
    ax.text(2.5, 1.75, "代价：微秒级（内核建映射）", ha="center", fontsize=9.5, color=C_ORANGE, weight="bold")
    ax.text(2.5, 1.15, "→ 靠「预热」消灭", ha="center", fontsize=9.5, color=C_GREEN, weight="bold")
    # major
    _box(ax, 7.5, 3.6, "major fault（主缺页）", C_RED, w=3.4, h=0.7, fs=10.5)
    ax.text(7.5, 2.85, "页已被换出到 swap 磁盘\n访问时要从磁盘读回", ha="center", fontsize=9, color=C_EDGE)
    ax.text(7.5, 1.9, "代价：毫秒级（磁盘 IO）", ha="center", fontsize=9.5, color=C_RED, weight="bold")
    ax.text(7.5, 1.15, "→ 靠「mlockall 锁页」消灭", ha="center", fontsize=9.5, color=C_GREEN, weight="bold")
    ax.text(5.0, 0.4, "交易系统目标：两种都清零", ha="center", fontsize=10.5, color=C_EDGE, weight="bold")
    ax.set_xlim(0, 10); ax.set_ylim(0.1, 4.2); ax.axis("off")
    fig.suptitle("缺页的两种类型：minor（建映射，µs）vs major（swap磁盘，ms）".replace("µs","us"),
                 fontsize=12.5, weight="bold", y=1.0)
    fig.tight_layout()
    _save(fig, "pf-2-fault-types.png")


# ── 图3：预热——把缺页成本挪到启动期 ──────────────────────
def fig3_prewarm():
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    # 左：不预热
    ax = axes[0]
    ax.axhline(1.0, xmin=0.05, xmax=0.95, color=C_GREY, lw=1.0)
    ax.text(0.5, 3.55, "不预热：缺页发生在运行期", ha="center", fontsize=10.5, weight="bold", color=C_RED, transform=ax.transAxes)
    # 运行期几个尖峰
    import numpy as _np
    xs = _np.linspace(1, 9, 40)
    ys = _np.ones(40)*1.0
    for pos in [8, 18, 27, 35]:
        ys[pos] = 3.0
    ax.plot(xs, ys, color=C_RED, lw=1.3)
    ax.axvspan(1, 2.2, color="#e3fbe3", alpha=0.5)
    ax.text(1.6, 3.3, "启动", ha="center", fontsize=8.5, color=C_GREEN)
    ax.text(6, 3.3, "运行期(抢单区)", ha="center", fontsize=9, color=C_RED)
    ax.text(5, 0.3, "缺页尖峰砸在抢单瞬间 = 灾难", ha="center", fontsize=9.5, color=C_RED, weight="bold")
    ax.set_xlim(0, 10); ax.set_ylim(0, 4); ax.axis("off")
    # 右：预热
    ax = axes[1]
    ax.text(0.5, 3.55, "预热：缺页成本挪到启动期付清", ha="center", fontsize=10.5, weight="bold", color=C_GREEN, transform=ax.transAxes)
    xs = _np.linspace(1, 9, 40)
    ys = _np.ones(40)*1.0
    # 启动期一堆尖峰（集中付清），运行期平
    for pos in range(2, 9):
        ys[pos] = 2.6
    ax.plot(xs, ys, color=C_GREEN, lw=1.3)
    ax.axvspan(1, 2.9, color="#e3fbe3", alpha=0.5)
    ax.text(1.9, 3.3, "启动(预热touch全部页)", ha="center", fontsize=8.3, color=C_GREEN)
    ax.text(6.5, 3.3, "运行期：平", ha="center", fontsize=9, color=C_GREEN)
    ax.text(5, 0.3, "运行期零缺页,曲线平坦", ha="center", fontsize=9.5, color=C_GREEN, weight="bold")
    ax.set_xlim(0, 10); ax.set_ylim(0, 4); ax.axis("off")
    fig.suptitle("内存预热：延迟成本不消失,但时机可选——挪到启动期结清",
                 fontsize=12.5, weight="bold", y=1.02)
    fig.tight_layout()
    _save(fig, "pf-3-prewarm.png")


# ── 图4：mlockall 锁页防换出 ────────────────────────────
def fig4_mlockall():
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4))
    # 左：不锁页
    ax = axes[0]
    _box(ax, 2.5, 3.5, "预热好的物理页", C_GREEN, w=3.0, h=0.6, fs=10, fc="#e3fbe3")
    ax.annotate("", xy=(2.5, 1.9), xytext=(2.5, 3.15),
                arrowprops=dict(arrowstyle="->", color=C_RED, lw=2.0, ls="--"))
    ax.text(3.5, 2.55, "内存紧张时\n被换出", ha="left", fontsize=9, color=C_RED, weight="bold")
    _box(ax, 2.5, 1.4, "swap 磁盘", C_RED, w=3.0, h=0.6, fs=10, fc="#ffe3e3")
    ax.text(2.5, 0.6, "下次访问 = major fault (ms级)", ha="center", fontsize=9.3, color=C_RED, weight="bold")
    ax.set_title("不锁页：预热成果可能被 swap 掉", fontsize=10.5, weight="bold", color=C_RED)
    ax.set_xlim(0, 5); ax.set_ylim(0.2, 4.1); ax.axis("off")
    # 右：锁页
    ax = axes[1]
    _box(ax, 2.5, 3.5, "预热好的物理页", C_GREEN, w=3.0, h=0.6, fs=10, fc="#e3fbe3")
    # 锁的图示
    ax.add_patch(Rectangle((0.7, 1.0), 3.6, 2.9, fill=False, edgecolor=C_GREEN, lw=2.2, ls="-"))
    ax.text(2.5, 2.55, "mlockall\n(MCL_CURRENT | MCL_FUTURE)", ha="center", fontsize=9.5, color=C_GREEN, weight="bold")
    ax.text(2.5, 1.5, "钉死在物理内存,禁止换出", ha="center", fontsize=9.3, color=C_GREEN)
    ax.text(2.5, 0.6, "配 swappiness=0 双保险 → 零 major fault", ha="center", fontsize=9.3, color=C_GREEN, weight="bold")
    ax.set_title("锁页：钉死在物理内存,永不换出", fontsize=10.5, weight="bold", color=C_GREEN)
    ax.set_xlim(0, 5); ax.set_ylim(0.2, 4.1); ax.axis("off")
    fig.suptitle("mlockall 锁页：预热(消灭minor) + 锁页(消灭major),配套才是零缺页",
                 fontsize=12, weight="bold", y=1.02)
    fig.tight_layout()
    _save(fig, "pf-4-mlockall.png")


if __name__ == "__main__":
    fig1_distribution()
    fig2_fault_types()
    fig3_prewarm()
    fig4_mlockall()
    print("ALL DONE")
