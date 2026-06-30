#!/usr/bin/env python3
"""生成「硬件时间戳与 tick-to-trade」课时配图（4 张）。直接画机制本身。
软件打点开销数字来自本机实测（bench_timestamp.cpp）；硬件时间戳/PTP 为机制示意。
输出到 ../assets/ts-*.png，DPI 150，白底。避免 µ/✓/✗ 缺字形字符（用 us 代替 µs）。"""
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


# ── 图1：tick-to-trade 链路 + 打点 ──────────────────────────
def fig1_t2t_chain():
    fig, ax = plt.subplots(figsize=(12, 4.4))
    stages = [
        ("网卡\n收包", C_PURPLE),
        ("内核\n驱动", C_BLUE),
        ("行情\n解析", C_GREEN),
        ("策略\n计算", C_GREEN),
        ("下单\n序列化", C_GREEN),
        ("内核\n驱动", C_BLUE),
        ("网卡\n发包", C_PURPLE),
    ]
    n = len(stages)
    x0 = 1.0; dx = 1.55
    ys = 2.4
    for i, (t, col) in enumerate(stages):
        x = x0 + i*dx
        _box(ax, x, ys, t, col, w=1.15, h=0.85, fs=9)
        if i < n-1:
            ax.annotate("", xy=(x+0.62, ys), xytext=(x+0.93, ys),
                        arrowprops=dict(arrowstyle="<-", color=C_GREY, lw=1.6))
    # T0 / T1 硬件打点
    ax.annotate("T0\nRX 硬件时间戳", xy=(x0, ys+0.5), xytext=(x0, ys+1.25),
                ha="center", fontsize=9.5, color=C_RED, weight="bold",
                arrowprops=dict(arrowstyle="->", color=C_RED, lw=1.8))
    ax.annotate("T1\nTX 硬件时间戳", xy=(x0+(n-1)*dx, ys+0.5), xytext=(x0+(n-1)*dx, ys+1.25),
                ha="center", fontsize=9.5, color=C_RED, weight="bold",
                arrowprops=dict(arrowstyle="->", color=C_RED, lw=1.8))
    # 总线
    ax.annotate("", xy=(x0+(n-1)*dx, ys-0.95), xytext=(x0, ys-0.95),
                arrowprops=dict(arrowstyle="<->", color=C_EDGE, lw=1.6))
    ax.text((x0 + x0+(n-1)*dx)/2, ys-1.3, "tick-to-trade = T1 - T0（行情到达网卡 → 下单离开网卡）",
            ha="center", fontsize=10.5, color=C_EDGE, weight="bold")
    ax.set_xlim(0, x0+(n-1)*dx+1.0); ax.set_ylim(0.6, 4.0); ax.axis("off")
    fig.suptitle("tick-to-trade：交易系统最核心的端到端延迟指标", fontsize=13, weight="bold", y=1.0)
    fig.tight_layout()
    _save(fig, "ts-1-t2t-chain.png")


# ── 图2：软件打点开销与尾部尖峰（本机实测）──────────────────
def fig2_software_cost():
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6))
    # 左：分辨率 + 各分位（对数 Y 轴，因尾部尖峰跨数量级）
    ax = axes[0]
    labels = ["p50", "p99", "p99.9", "max"]
    cg = [0.5, 1000, 1000, 18000]     # clock_gettime（p50=0 用0.5占位避免log0）
    mach = [0.5, 41.7, 41.7, 5417]    # mach_absolute_time
    x = np.arange(len(labels)); w = 0.36
    ax.bar(x - w/2, cg, w, label="clock_gettime", color=C_RED, edgecolor=C_EDGE, lw=0.8, zorder=3)
    ax.bar(x + w/2, mach, w, label="mach (≈rdtsc)", color=C_GREEN, edgecolor=C_EDGE, lw=0.8, zorder=3)
    ax.set_yscale("log")
    ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=10.5)
    ax.set_ylabel("单次取时间戳开销（ns，对数轴）", fontsize=10)
    ax.legend(fontsize=9.5, loc="upper left")
    ax.grid(axis="y", ls="--", alpha=0.4, zorder=0)
    for xi, v in zip(x - w/2, cg):
        if v >= 1: ax.text(xi, v*1.15, f"{int(v)}", ha="center", fontsize=8, color=C_RED)
        else: ax.text(xi, 0.6, "~0", ha="center", fontsize=7.5, color=C_RED)
    for xi, v in zip(x + w/2, mach):
        if v >= 1: ax.text(xi, v*1.15, f"{v:g}", ha="center", fontsize=8, color=C_GREEN)
        else: ax.text(xi, 0.6, "~0", ha="center", fontsize=7.5, color=C_GREEN)
    ax.set_title("软件打点的开销分布（本机实测，对数轴）", fontsize=10.5, weight="bold")
    # 右：致命问题文字图
    ax = axes[1]
    ax.text(0.5, 4.3, "软件时间戳的三个致命问题", ha="center", fontsize=12, weight="bold", color=C_EDGE)
    probs = [
        ("1. 观测者效应", "打点动作自己花几十~上千 ns，\n与被测的几百 ns 热路径同量级\n→ 量尺改变了被测对象", C_RED),
        ("2. 量尺自己会抖", "最快的 mach 也有 max 5.4us 尖峰\n（被中断/调度打断）\n→ 拿会抖的尺子量抖动，分不清谁的尖峰", C_ORANGE),
        ("3. 测不到真实到达", "软件只能打在「代码执行到那行」时\n网卡→代码这几 us 完全测不到\n→ 还误算进策略耗时", C_PURPLE),
    ]
    y = 3.5
    for title, body, col in probs:
        ax.text(0.04, y, title, fontsize=10.5, color=col, weight="bold")
        ax.text(0.06, y-0.45, body, fontsize=8.8, color=C_EDGE, va="top")
        y -= 1.25
    ax.set_xlim(0, 1); ax.set_ylim(0, 4.7); ax.axis("off")
    fig.suptitle("为什么软件时间戳不够：开销、抖动、盲区（引出硬件时间戳）",
                 fontsize=13, weight="bold", y=1.02)
    fig.tight_layout()
    _save(fig, "ts-2-software-cost.png")


# ── 图3：三层时间戳打点位置 ──────────────────────────────
def fig3_three_layers():
    fig, ax = plt.subplots(figsize=(11, 5.2))
    layers = [
        ("用户态代码", "clock_gettime / rdtsc", "最晚、最不准\n含中断+协议栈+调度延迟", C_RED, 4.0),
        ("内核收包软中断", "SO_TIMESTAMP / SO_TIMESTAMPNS", "前移一步\n仍漏掉网卡→内核段", C_ORANGE, 2.7),
        ("网卡 PHY 物理层", "SO_TIMESTAMPING + 网卡硬件时钟 PHC", "最早、最准、零 CPU 开销\n最接近线上真实时刻", C_GREEN, 1.4),
    ]
    for name, api, note, col, y in layers:
        _box(ax, 3.1, y, name, col, w=3.2, h=0.85, fs=10.5, fc="white")
        ax.text(5.4, y+0.18, api, fontsize=9.3, color=C_EDGE, va="center")
        ax.text(5.4, y-0.28, note, fontsize=8.8, color=col, va="center", weight="bold")
    # 从上到下「越来越接近真实」箭头（放在最左侧留白，明显远离方框）
    ax.annotate("", xy=(0.55, 1.1), xytext=(0.55, 4.3),
                arrowprops=dict(arrowstyle="->", color=C_GREEN, lw=2.2))
    ax.text(0.95, 2.7, "打点位置越往下越接近真实", ha="center", va="center",
            fontsize=9.0, color=C_GREEN, weight="bold", rotation=90)
    ax.set_xlim(0, 10.0); ax.set_ylim(0.7, 4.7); ax.axis("off")
    fig.suptitle("三层时间戳：把打点位置从用户态一路前移到网卡物理层",
                 fontsize=12.5, weight="bold", y=1.0)
    fig.tight_layout()
    _save(fig, "ts-3-three-layers.png")


# ── 图4：PTP 跨机同步 ────────────────────────────────────
def fig4_ptp():
    fig, ax = plt.subplots(figsize=(11, 4.6))
    # grandmaster
    _box(ax, 5.5, 4.0, "Grandmaster Clock\n（基准时钟 / GPS 溯源）", C_PURPLE, w=3.6, h=0.85, fs=10)
    # 三台机器
    machines = [("行情网关", 1.8), ("策略机", 5.5), ("下单机", 9.2)]
    for name, x in machines:
        _box(ax, x, 1.6, name + "\n网卡 PHC", C_BLUE, w=2.2, h=0.85, fs=9.5)
        ax.annotate("", xy=(x, 2.05), xytext=(5.5, 3.55),
                    arrowprops=dict(arrowstyle="->", color=C_GREEN, lw=1.6,
                                    connectionstyle="arc3,rad=0.0"))
    ax.text(5.5, 2.75, "ptp4l (IEEE 1588) 纳秒级同步", ha="center", fontsize=10,
            color=C_GREEN, weight="bold")
    ax.text(5.5, 0.7, "三台机器的 PHC 对齐到同一基准 → 跨机 T2T 相减才有意义\nPTP 亚微秒~纳秒级，NTP 仅毫秒级（差 1000 倍，远远不够）",
            ha="center", fontsize=9.8, color=C_EDGE, weight="bold")
    ax.set_xlim(0, 11); ax.set_ylim(0.2, 4.7); ax.axis("off")
    fig.suptitle("PTP 跨机时间同步：让多台机器的表对齐到纳秒",
                 fontsize=12.5, weight="bold", y=1.0)
    fig.tight_layout()
    _save(fig, "ts-4-ptp-sync.png")


if __name__ == "__main__":
    fig1_t2t_chain()
    fig2_software_cost()
    fig3_three_layers()
    fig4_ptp()
    print("ALL DONE")
