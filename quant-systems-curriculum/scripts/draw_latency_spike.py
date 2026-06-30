#!/usr/bin/env python3
"""生成「延迟尖峰溯源」课时配图（4 张）。
图1延迟分布用本机实测直方图(bench_latency_spike.cpp), 强制对数 Y 轴。
输出到 ../assets/spike-*.png，DPI 150，白底。避免 µ/✓/✗ 缺字形字符(用 us)。"""
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


# ── 图1：延迟长尾分布（对数 Y 轴，本机实测）──────────────────
def fig1_distribution():
    # 本机实测直方图 bench_latency_spike.cpp
    bins = ["0-50","50-100","100-200","200-500","500-1k","1k-2k","2k-5k","5k-10k","10k-50k"]
    cnt = [4616384, 303157, 71087, 9249, 5, 13, 24, 70, 11]
    fig, ax = plt.subplots(figsize=(11, 5.0))
    xs = np.arange(len(bins))
    # 主峰绿、尖峰红（500ns 以上算尖峰）
    colors = [C_GREEN if i < 4 else C_RED for i in range(len(bins))]
    ax.bar(xs, cnt, color=colors, edgecolor=C_EDGE, lw=0.8, width=0.7, zorder=3)
    ax.set_yscale("log")  # 铁律：长尾必须对数 Y 轴
    for x, c in zip(xs, cnt):
        ax.text(x, c*1.4, f"{c:,}" if c >= 100 else str(c), ha="center",
                fontsize=8, color=(C_GREEN if x < 4 else C_RED), rotation=0)
    ax.set_xticks(xs); ax.set_xticklabels(bins, fontsize=9.5, rotation=20)
    ax.set_xlabel("单次迭代耗时区间（ns）", fontsize=11)
    ax.set_ylabel("迭代次数（对数轴）", fontsize=11)
    ax.set_ylim(0.5, 5e7)
    ax.grid(axis="y", ls="--", alpha=0.4, zorder=0)
    # P50/P99/max 竖线注解（主峰注解放最左上空白，避开第一柱计数标注）
    ax.text(1.2, 2e7, "主峰 p50=41.7ns（461万次落在 0-50ns 桶）", ha="left", fontsize=9.5,
            color=C_GREEN, weight="bold")
    # 箭头尖端落到 5k-10k 柱体内部（该桶计数70，柱高约70）
    ax.annotate("尾部尖峰区\n约100次飙到 5-50us\n被中断/调度打断", xy=(7, 70), xytext=(4.7, 6e3),
                ha="center", fontsize=9.2, color=C_RED, weight="bold",
                arrowprops=dict(arrowstyle="->", color=C_RED, lw=1.8))
    ax.text(6.0, 1.5e6, "max = 45us = p50 的 1083 倍", ha="center",
            fontsize=10.5, color=C_RED, weight="bold",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#ffe3e3", edgecolor=C_RED))
    ax.set_title("固定工作量循环的延迟长尾分布（本机实测500万次，对数Y轴让尖峰可见）",
                 fontsize=11.5, weight="bold")
    fig.tight_layout()
    _save(fig, "spike-1-distribution.png")


# ── 图2：五大尖峰来源 ────────────────────────────────────
def fig2_sources():
    fig, ax = plt.subplots(figsize=(11, 5.2))
    sources = [
        ("缺页 page fault", "访问的页不在物理内存\n触发内核换页", "us 级", C_RED),
        ("中断 IRQ/softirq", "网卡等硬件中断\n打断当前线程", "us 级", C_ORANGE),
        ("调度抢占", "线程被换下 CPU\n回来时 cache 全冷", "1-3 us + 冷cache", C_PURPLE),
        ("cache/TLB miss", "数据不在 cache\n访存穿透到内存", "几十~几百 ns", C_BLUE),
        ("CPU 频率波动", "C-state 唤醒延迟\nP-state 降频", "us 级唤醒", C_GREEN),
    ]
    # 中心「延迟尖峰」
    _box(ax, 5.5, 2.6, "延迟尖峰\nlatency spike", C_EDGE, w=2.3, h=1.0, fs=11, fc="#fff3cd")
    # 五个来源环绕
    positions = [(2.0, 4.3), (8.8, 4.3), (1.3, 2.0), (9.5, 2.0), (5.5, 0.5)]
    for (name, mech, mag, col), (x, y) in zip(sources, positions):
        _box(ax, x, y, name, col, w=2.6, h=0.6, fs=9.5)
        ax.text(x, y-0.5, mech, ha="center", va="top", fontsize=7.8, color=C_GREY)
        ax.text(x, y+0.42, mag, ha="center", fontsize=8, color=col, weight="bold")
        ax.annotate("", xy=(5.5, 2.6), xytext=(x, y),
                    arrowprops=dict(arrowstyle="->", color=col, lw=1.4, alpha=0.6,
                                    shrinkA=8, shrinkB=42))
    ax.text(5.5, 4.9, "五类嫌疑人量级/特征不同 → 可靠「特征」反推「凶手」",
            ha="center", fontsize=10, color=C_EDGE, weight="bold")
    ax.set_xlim(0, 11); ax.set_ylim(-0.4, 5.2); ax.axis("off")
    fig.suptitle("延迟尖峰的五大来源：先建嫌疑人清单，溯源就是逐个排查",
                 fontsize=12.5, weight="bold", y=1.0)
    fig.tight_layout()
    _save(fig, "spike-2-sources.png")


# ── 图3：四把工具各管一段 ────────────────────────────────
def fig3_toolchain():
    fig, ax = plt.subplots(figsize=(11.5, 4.6))
    tools = [
        ("cyclictest", "量系统本底抖动\n(调优前后各跑一次)", C_BLUE),
        ("perf stat/sched", "归类: 哪类事件计数异常\n(缺页/切换/cache-miss)", C_GREEN),
        ("ftrace/trace-cmd", "内核函数级时间线\n(尖峰时刻在做什么)", C_ORANGE),
        ("eBPF/bpftrace", "低开销在线探针\n(生产环境抓尖峰调用栈)", C_PURPLE),
    ]
    n = len(tools)
    x0 = 1.6; dx = 2.9
    for i, (name, desc, col) in enumerate(tools):
        x = x0 + i*dx
        _box(ax, x, 2.6, name, col, w=2.5, h=0.75, fs=10.5)
        ax.text(x, 1.75, desc, ha="center", va="top", fontsize=8.6, color=C_EDGE)
        ax.text(x, 3.35, f"第{i+1}把", ha="center", fontsize=8.5, color=col, weight="bold")
        if i < n-1:
            ax.annotate("", xy=(x+1.45, 2.6), xytext=(x+1.05, 2.6),
                        arrowprops=dict(arrowstyle="->", color=C_GREY, lw=1.6))
    ax.text(x0+(n-1)*dx/2, 0.6, "组合拳：没有一把工具直接告诉你「是缺页」，四把交叉印证才能锁定凶手",
            ha="center", fontsize=10, color=C_EDGE, weight="bold")
    ax.set_xlim(0, x0+(n-1)*dx+1.6); ax.set_ylim(0.2, 3.9); ax.axis("off")
    fig.suptitle("溯源工具链：四把刀各管一段（Linux 标准工具，本机 macOS 未执行）",
                 fontsize=12, weight="bold", y=1.0)
    fig.tight_layout()
    _save(fig, "spike-3-toolchain.png")


# ── 图4：溯源决策流程 ────────────────────────────────────
def fig4_decision():
    fig, ax = plt.subplots(figsize=(10.5, 6.0))
    # 流程：尖峰时刻对齐内核事件 → 分支
    _box(ax, 5.2, 5.5, "尖峰发生：业务侧记时刻 + 内核侧记事件，对齐时刻线", C_EDGE, w=7.5, h=0.65, fs=10, fc="#fff3cd")
    branches = [
        ("那一刻有 page_fault ?", "缺页 → mlockall + 预热全内存 (O3)", C_RED, 4.4),
        ("那一刻有 irq_handler ?", "中断 → 网卡中断绑非交易核 (O4)", C_ORANGE, 3.5),
        ("那一刻有 sched_switch ?", "抢占 → 绑核+isolcpus+FIFO (O2)", C_PURPLE, 2.6),
        ("都没有但 cache-miss 高 ?", "数据布局 → DOD/SoA (C5)", C_BLUE, 1.7),
        ("核刚从空闲唤醒 ?", "频率/C-state → 关C-state+锁频 (O8)", C_GREEN, 0.8),
    ]
    for q, action, col, y in branches:
        ax.text(0.5, y, q, fontsize=9.8, color=C_EDGE, va="center")
        ax.annotate("", xy=(5.7, y), xytext=(4.6, y),
                    arrowprops=dict(arrowstyle="->", color=col, lw=1.6))
        ax.text(5.9, y, action, fontsize=9.5, color=col, va="center", weight="bold")
    ax.text(5.2, 0.1, "铁律：每次只改一项，用 cyclictest/分布图重测验证尖峰是否被砍掉",
            ha="center", fontsize=9.8, color=C_RED, weight="bold")
    ax.set_xlim(0, 11); ax.set_ylim(-0.2, 6.0); ax.axis("off")
    fig.suptitle("溯源决策流程：尖峰不是猜出来的，是「对齐时刻线」对出来的",
                 fontsize=12.5, weight="bold", y=1.0)
    fig.tight_layout()
    _save(fig, "spike-4-decision.png")


if __name__ == "__main__":
    fig1_distribution()
    fig2_sources()
    fig3_toolchain()
    fig4_decision()
    print("ALL DONE")
