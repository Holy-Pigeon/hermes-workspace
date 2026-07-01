#!/usr/bin/env python3
"""生成「中断亲和性与 softirq」课时配图（4 张）。直接画机制本身。
中断绑核本机无法实测，图为机制示意；延迟代价引用 O2 已实测数据。
输出到 ../assets/irq-*.png，DPI 150，白底。避免 µ/✓/✗ 缺字形字符。"""
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


# ── 图1：网卡中断打断交易线程 ────────────────────────────
def fig1_problem():
    fig, ax = plt.subplots(figsize=(11, 4.4))
    # 交易核时间轴
    ax.annotate("", xy=(10, 2.5), xytext=(0.6, 2.5),
                arrowprops=dict(arrowstyle="->", color=C_EDGE, lw=1.5))
    ax.text(0.4, 2.9, "交易核（本以为独享）", fontsize=10.5, color=C_EDGE, weight="bold")
    # 策略计算段（被打断）
    for x0, x1, lab in [(1.0, 3.0, "策略计算"), (4.2, 6.2, "策略(接着算)"), (7.4, 9.4, "策略")]:
        ax.add_patch(Rectangle((x0, 2.3), x1-x0, 0.4, facecolor="#d6e4ff", edgecolor=C_BLUE, lw=1.2))
        ax.text((x0+x1)/2, 2.5, lab, ha="center", va="center", fontsize=8.5, color=C_BLUE)
    # 中断打断
    for xc in [3.6, 6.8]:
        ax.add_patch(Rectangle((xc, 2.3), 0.55, 0.4, facecolor="#ffe3e3", edgecolor=C_RED, lw=1.4))
        ax.text(xc+0.27, 2.5, "IRQ", ha="center", va="center", fontsize=7.5, color=C_RED, weight="bold")
        ax.annotate("", xy=(xc+0.27, 2.75), xytext=(xc+0.27, 3.4),
                    arrowprops=dict(arrowstyle="->", color=C_RED, lw=1.8))
        ax.text(xc+0.27, 3.6, "网卡\n来包", ha="center", fontsize=8, color=C_RED, weight="bold")
    ax.text(5.0, 1.5, "每次中断打断 ≈ 一次上下文切换代价（O2实测约1.2us）+ 冷cache,且不可预测",
            ha="center", fontsize=9.5, color=C_RED, weight="bold")
    ax.text(5.0, 1.0, "高频行情每秒几万次中断 → 交易核被反复打断 → 尾部延迟恶化",
            ha="center", fontsize=9.5, color=C_RED)
    ax.set_xlim(0, 10.5); ax.set_ylim(0.6, 4.0); ax.axis("off")
    fig.suptitle("问题：网卡中断（IRQ）会强制打断交易核上正在跑的线程",
                 fontsize=12.5, weight="bold", y=1.0)
    fig.tight_layout()
    _save(fig, "irq-1-problem.png")


# ── 图2：硬中断 vs 软中断 ────────────────────────────────
def fig2_hard_soft():
    fig, ax = plt.subplots(figsize=(11, 4.8))
    # 流程：网卡→硬中断→软中断→协议栈
    _box(ax, 1.5, 3.5, "网卡收到包", C_ORANGE, w=2.0, h=0.7, fs=9.5)
    _box(ax, 4.5, 3.5, "硬中断\n(上半部)", C_RED, w=2.0, h=0.85, fs=9.5, fc="#ffe3e3")
    _box(ax, 7.8, 3.5, "软中断 softirq\n(下半部 NET_RX)", C_PURPLE, w=2.6, h=0.85, fs=9, fc="#f0e6ff")
    ax.annotate("", xy=(3.5, 3.5), xytext=(2.5, 3.5), arrowprops=dict(arrowstyle="->", color=C_GREY, lw=1.6))
    ax.annotate("", xy=(6.5, 3.5), xytext=(5.5, 3.5), arrowprops=dict(arrowstyle="->", color=C_GREY, lw=1.6))
    ax.text(4.5, 2.55, "极简:应答硬件\n标记有活,尽快返回\n(期间屏蔽其他中断)", ha="center", fontsize=8.3, color=C_RED)
    ax.text(6.0, 2.6, "重活:协议栈\n处理,把包送上去", ha="center", fontsize=8.3, color=C_PURPLE)
    # ksoftirqd
    _box(ax, 7.8, 1.5, "ksoftirqd 线程", C_RED, w=2.4, h=0.6, fs=9, fc="#ffe3e3")
    ax.annotate("", xy=(7.8, 1.8), xytext=(7.8, 3.05), arrowprops=dict(arrowstyle="->", color=C_RED, lw=1.4, ls="--"))
    ax.text(9.15, 1.5, "← 处理不过来\n时被唤醒", fontsize=8.3, color=C_RED, va="center")
    ax.text(5.5, 0.7, "网络收包大头在软中断; ksoftirqd 某核活跃 = 该核被软中断压垮的信号(O7溯源特征)",
            ha="center", fontsize=9.3, color=C_EDGE, weight="bold")
    ax.set_xlim(0, 11); ax.set_ylim(0.3, 4.2); ax.axis("off")
    fig.suptitle("硬中断（上半部,尽快返回）vs 软中断（下半部,做重活）",
                 fontsize=12.5, weight="bold", y=1.0)
    fig.tight_layout()
    _save(fig, "irq-2-hard-soft.png")


# ── 图3：中断亲和性——绑到非交易核 ──────────────────────
def fig3_affinity():
    fig, ax = plt.subplots(figsize=(11, 4.8))
    cores = [("核0\n(处理中断)", C_ORANGE, "#fff0e0"), ("核1\n(处理中断)", C_ORANGE, "#fff0e0"),
             ("核2\n(交易-净空)", C_GREEN, "#e3fbe3"), ("核3\n(交易-净空)", C_GREEN, "#e3fbe3")]
    for i, (lab, col, fc) in enumerate(cores):
        _box(ax, 1.6 + i*2.3, 2.6, lab, col, w=1.8, h=1.0, fs=9, fc=fc)
    # 网卡中断只投到核0/核1
    _box(ax, 5.2, 4.3, "网卡 IRQ", C_RED, w=2.0, h=0.6, fs=9.5, fc="#ffe3e3")
    for i in [0, 1]:
        ax.annotate("", xy=(1.6 + i*2.3, 3.15), xytext=(5.2, 4.0),
                    arrowprops=dict(arrowstyle="->", color=C_RED, lw=1.6))
    # 交易核上打叉表示中断不来
    for i in [2, 3]:
        x = 1.6 + i*2.3
        ax.annotate("", xy=(x, 3.15), xytext=(5.2, 4.0),
                    arrowprops=dict(arrowstyle="->", color=C_GREY, lw=1.2, ls="--", alpha=0.35))
        ax.text(x, 3.5, "中断不来", ha="center", fontsize=8, color=C_GREEN, weight="bold")
    ax.text(5.2, 1.5, "echo 1 > /proc/irq/128/smp_affinity   (位掩码 1=核0)", ha="center",
            fontsize=9.3, color=C_EDGE)
    ax.text(5.2, 0.95, "+ systemctl stop irqbalance（否则它会把中断均摊回交易核,推翻你的绑定）",
            ha="center", fontsize=9.3, color=C_RED, weight="bold")
    ax.set_xlim(0, 10.5); ax.set_ylim(0.5, 4.9); ax.axis("off")
    fig.suptitle("中断亲和性：把网卡 IRQ 只投递到非交易核（核0/1），交易核净空",
                 fontsize=12, weight="bold", y=1.0)
    fig.tight_layout()
    _save(fig, "irq-3-affinity.png")


# ── 图4：三零闭环 ────────────────────────────────────────
def fig4_complete():
    fig, ax = plt.subplots(figsize=(10.5, 5.0))
    # 中心交易核
    _box(ax, 5.25, 2.6, "交易核\n实现「三零」", C_EDGE, w=2.4, h=1.1, fs=11, fc="#fff3cd")
    items = [
        ("绑核 + isolcpus (O2)", "零上下文切换", C_BLUE, 2.0, 4.3),
        ("内存预热 + mlockall (O3)", "零缺页", C_PURPLE, 8.5, 4.3),
        ("中断亲和性 + 关irqbalance (本课O4)", "零中断打断", C_RED, 5.25, 0.7),
    ]
    for cmd, zero, col, x, y in items:
        _box(ax, x, y, zero, col, w=2.4, h=0.6, fs=10, fc="white")
        ax.text(x, y+(0.5 if y>3 else -0.5), cmd, ha="center", fontsize=8.5, color=col, weight="bold")
        ax.annotate("", xy=(5.25, 2.6), xytext=(x, y),
                    arrowprops=dict(arrowstyle="->", color=col, lw=1.6, alpha=0.7,
                                    shrinkA=6, shrinkB=32))
    ax.text(5.25, 4.85, "三者对称互补,缺一个就有对应尖峰漏进来(正是O7三大凶手)",
            ha="center", fontsize=10, color=C_EDGE, weight="bold")
    ax.set_xlim(0, 10.5); ax.set_ylim(0.2, 5.2); ax.axis("off")
    fig.suptitle("完整闭环：绑核 + 预热 + 中断亲和性 → 交易核「三零」",
                 fontsize=12.5, weight="bold", y=1.0)
    fig.tight_layout()
    _save(fig, "irq-4-complete.png")


if __name__ == "__main__":
    fig1_problem()
    fig2_hard_soft()
    fig3_affinity()
    fig4_complete()
    print("ALL DONE")
