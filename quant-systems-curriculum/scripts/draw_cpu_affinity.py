#!/usr/bin/env python3
"""生成「CPU 亲和性与核隔离」课时配图（4 张）。直接画机制本身。
上下文切换开销数字来自本机实测（bench_ctxsw.cpp）。
输出到 ../assets/aff-*.png，DPI 150，白底。避免 µ/✓/✗ 缺字形字符（用 us）。"""
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


# ── 图1：上下文切换开销 vs 纯计算（对数轴，本机实测）──────────
def fig1_ctxsw_cost():
    fig, ax = plt.subplots(figsize=(9, 5.0))
    names = ["同线程\n一次计算", "一次\n上下文切换"]
    vals = [1.9, 1152.0]
    colors = [C_GREEN, C_RED]
    xs = np.arange(len(names))
    ax.bar(xs, vals, color=colors, edgecolor=C_EDGE, lw=1.0, width=0.5, zorder=3)
    ax.set_yscale("log")  # 差近600倍，对数轴才看得清
    for x, v in zip(xs, vals):
        ax.text(x, v*1.25, f"{v:g} ns", ha="center", fontsize=12, weight="bold",
                color=(C_GREEN if v < 10 else C_RED))
    ax.set_xticks(xs); ax.set_xticklabels(names, fontsize=11)
    ax.set_ylabel("耗时（ns，对数轴）", fontsize=11)
    ax.set_ylim(1, 3000)
    ax.grid(axis="y", ls="--", alpha=0.4, zorder=0)
    ax.text(0.5, 1600, "上下文切换 = 纯计算的约 592 倍\n（还不含切换后冷 cache 的隐形代价）",
            ha="center", fontsize=10.5, color=C_RED, weight="bold",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#ffe3e3", edgecolor=C_RED))
    ax.set_title("一次上下文切换有多贵（本机实测，pipe 乒乓 20万轮）",
                 fontsize=12, weight="bold")
    fig.tight_layout()
    _save(fig, "aff-1-ctxsw-cost.png")


# ── 图2：CPU 亲和性——漂移 vs 绑核 ──────────────────────────
def fig2_affinity():
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4))
    # 左：默认漂移
    ax = axes[0]
    cores = ["核0", "核1", "核2", "核3"]
    for i, c in enumerate(cores):
        ax.add_patch(Rectangle((0.5 + i*1.6, 1.2), 1.3, 1.3, facecolor="#f0f0f0",
                               edgecolor=C_EDGE, lw=1.3))
        ax.text(0.5 + i*1.6 + 0.65, 1.35, c, ha="center", fontsize=9.5, color=C_GREY)
    # 线程按时间在核间跳（漂移轨迹，t0->t1->t2->t3 时间顺序）
    traj = [0, 1, 2, 3]  # 依次漂到核0->核1->核2->核3，箭头不交叉
    for step, ci in enumerate(traj):
        x = 0.5 + ci*1.6 + 0.65
        ax.add_patch(FancyBboxPatch((x-0.45, 1.75), 0.9, 0.4, boxstyle="round,pad=0.02",
                                    facecolor="#ffe3e3", edgecolor=C_RED, lw=1.4))
        ax.text(x, 1.95, f"t{step}", ha="center", va="center", fontsize=8.5, color=C_RED, weight="bold")
        if step > 0:
            px = 0.5 + traj[step-1]*1.6 + 0.65
            ax.annotate("", xy=(x-0.42, 2.28), xytext=(px+0.42, 2.28),
                        arrowprops=dict(arrowstyle="->", color=C_RED, lw=1.5))
    ax.text(3.7, 3.05, "默认：线程按时间在核间漂移", ha="center", fontsize=10.5, weight="bold", color=C_RED)
    ax.text(3.7, 0.7, "每次搬家 = 迁移 + 冷 cache", ha="center", fontsize=9.8, color=C_RED)
    ax.set_xlim(0, 7.4); ax.set_ylim(0.3, 3.4); ax.axis("off")
    # 右：绑核固定
    ax = axes[1]
    for i, c in enumerate(cores):
        fc = "#e3fbe3" if i == 2 else "#f0f0f0"
        ax.add_patch(Rectangle((0.5 + i*1.6, 1.2), 1.3, 1.3, facecolor=fc,
                               edgecolor=C_EDGE, lw=1.3))
        ax.text(0.5 + i*1.6 + 0.65, 1.35, c, ha="center", fontsize=9.5, color=C_GREY)
    x = 0.5 + 2*1.6 + 0.65
    ax.add_patch(FancyBboxPatch((x-0.5, 1.75), 1.0, 0.5, boxstyle="round,pad=0.02",
                                facecolor="#e3fbe3", edgecolor=C_GREEN, lw=1.8))
    ax.text(x, 2.0, "交易\n线程", ha="center", va="center", fontsize=8.5, color=C_GREEN, weight="bold")
    ax.text(3.7, 3.1, "绑核：钉死在核2", ha="center", fontsize=11, weight="bold", color=C_GREEN)
    ax.text(3.7, 0.7, "pthread_setaffinity_np / taskset -c 2", ha="center", fontsize=9.3, color=C_GREEN)
    ax.set_xlim(0, 7.4); ax.set_ylim(0.3, 3.4); ax.axis("off")
    fig.suptitle("CPU 亲和性：默认漂移（迁移+冷cache）vs 绑核固定（不搬家）",
                 fontsize=12.5, weight="bold", y=1.02)
    fig.tight_layout()
    _save(fig, "aff-2-affinity.png")


# ── 图3：核隔离三件套 ────────────────────────────────────
def fig3_isolation():
    fig, ax = plt.subplots(figsize=(11, 5.0))
    items = [
        ("isolcpus=2,3", "把核移出 CFS 负载均衡域", "通用进程别来抢", C_BLUE, 4.1),
        ("nohz_full=2,3", "关掉核的周期性时钟中断(tickless)", "时钟中断别来打断", C_ORANGE, 2.9),
        ("rcu_nocbs=2,3", "把 RCU 回调卸载到其他核", "内核 RCU 软中断别来占", C_PURPLE, 1.7),
    ]
    for param, mech,治, col, y in items:
        _box(ax, 2.2, y, param, col, w=3.0, h=0.7, fs=10.5, fc="white")
        ax.text(4.1, y+0.16, mech, fontsize=9.5, color=C_EDGE, va="center")
        ax.text(4.1, y-0.24, "→ " + 治, fontsize=9.3, color=col, va="center", weight="bold")
    ax.text(5.5, 5.0, "写在内核启动参数 GRUB_CMDLINE_LINUX,三个各治一件事",
            ha="center", fontsize=10.5, color=C_EDGE, weight="bold")
    ax.text(5.5, 0.7, "隔离只是「内核不主动放任务」→ 必须再用 taskset 手动把交易线程绑上去,配套使用",
            ha="center", fontsize=9.8, color=C_RED, weight="bold")
    ax.set_xlim(0, 11); ax.set_ylim(0.3, 5.3); ax.axis("off")
    fig.suptitle("核隔离三件套：把核从内核调度器的地盘里划走（Linux 内核参数）",
                 fontsize=12.5, weight="bold", y=1.0)
    fig.tight_layout()
    _save(fig, "aff-3-isolation.png")


# ── 图4：抢核完整配方（四步流程）────────────────────────
def fig4_recipe():
    fig, ax = plt.subplots(figsize=(11, 5.2))
    steps = [
        ("1. 隔离", "isolcpus + nohz_full + rcu_nocbs", "把核腾空", C_BLUE, 4.3),
        ("2. 绑核", "pthread_setaffinity_np / taskset -c 2", "把交易线程钉到隔离核", C_GREEN, 3.4),
        ("3. 实时优先级", "SCHED_FIFO 优先级 99", "防被抢占", C_PURPLE, 2.5),
        ("4. 中断让开", "IRQ smp_affinity 绑到非交易核", "中断别来打断(见O4)", C_ORANGE, 1.6),
    ]
    for name, cmd, effect, col, y in steps:
        _box(ax, 1.7, y, name, col, w=2.2, h=0.62, fs=10, fc="white")
        ax.text(3.1, y+0.15, cmd, fontsize=9.2, color=C_EDGE, va="center")
        ax.text(3.1, y-0.22, "→ " + effect, fontsize=9.2, color=col, va="center", weight="bold")
        if y > 1.7:
            ax.annotate("", xy=(1.7, y-0.55), xytext=(1.7, y-0.31),
                        arrowprops=dict(arrowstyle="->", color=C_GREY, lw=1.4))
    ax.text(5.5, 0.75, "5. 验证:cyclictest -a2 -p99 测隔离核本底抖动,max 压到个位数 us = 生效",
            ha="center", fontsize=9.8, color=C_GREEN, weight="bold")
    ax.text(5.5, 5.0, "四件一起做才闭环:消灭上一节那 1152ns 的切换成本 → 零切换/零迁移/零时钟中断",
            ha="center", fontsize=9.8, color=C_EDGE, weight="bold")
    ax.set_xlim(0, 11); ax.set_ylim(0.4, 5.3); ax.axis("off")
    fig.suptitle("抢核完整配方：隔离 → 绑核 → 实时 → 中断让开 → 验证",
                 fontsize=12.5, weight="bold", y=1.0)
    fig.tight_layout()
    _save(fig, "aff-4-recipe.png")


if __name__ == "__main__":
    fig1_ctxsw_cost()
    fig2_affinity()
    fig3_isolation()
    fig4_recipe()
    print("ALL DONE")
