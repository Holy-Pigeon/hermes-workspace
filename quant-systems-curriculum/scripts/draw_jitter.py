#!/usr/bin/env python3
"""生成「系统级抖动消除 + 尾延迟思维」课时配图（5 张）。画机制本身。
输出到 ../assets/jitter-*.png，DPI 150，白底。"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mp
from matplotlib.patches import FancyBboxPatch, Rectangle, FancyArrowPatch
import numpy as np
from pathlib import Path

plt.rcParams["font.sans-serif"] = ["Hiragino Sans GB", "Songti SC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

OUT = Path(__file__).resolve().parents[1] / "assets"
OUT.mkdir(exist_ok=True)

C_EDGE = "#3b4252"
C_BAD = "#d62728"
C_GOOD = "#2ca02c"
C_BLUE = "#4C78A8"
C_HL = "#fff3cd"


def _save(fig, name):
    p = OUT / name
    fig.savefig(p, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("saved", p)


# ── 图1：均值 vs 尾延迟——为什么量化只看 P99.9 ─────────────────────
def fig1_tail_thinking():
    fig, ax = plt.subplots(figsize=(9, 4.0))
    np.random.seed(3)
    base = np.random.normal(1.2, 0.25, 5000)
    spikes = np.concatenate([base, np.random.normal(28, 6, 90)])
    bins = np.linspace(0, 45, 90)
    ax.hist(spikes, bins=bins, color=C_BLUE, alpha=0.75)
    ax.set_yscale("log")
    ax.set_ylim(0.7, 5000)
    mean = spikes.mean()
    p50 = np.percentile(spikes, 50)
    p99 = np.percentile(spikes, 99)
    p999 = np.percentile(spikes, 99.9)
    for v, lab, c, yt in [(p50, "P50(中位)", "#2ca02c", 1500),
                          (mean, "均值", "#888", 600),
                          (p99, "P99", "#e0a800", 250),
                          (p999, "P99.9", C_BAD, 100)]:
        ax.axvline(v, color=c, ls="--", lw=1.6)
        ax.text(v + 0.5, yt, f"{lab}\n{v:.1f}us", color=c, fontsize=9, weight="bold")
    ax.annotate("抖动尖峰簇\n(中断/缺页/调度/降频)\n占比不到 2%，但它定生死",
                xy=(28, 30), xytext=(33, 800), fontsize=9.5, color=C_BAD, ha="center", weight="bold",
                arrowprops=dict(arrowstyle="->", color=C_BAD, lw=1.8))
    ax.set_xlabel("tick-to-trade 延迟（微秒 us）", fontsize=11)
    ax.set_ylabel("出现次数（对数刻度）", fontsize=11)
    ax.set_title("尾延迟思维：均值和中位数都很美，P99.9 暴露真相——量化只为最坏几次买单", fontsize=11.5, weight="bold")
    ax.set_xlim(0, 45)
    _save(fig, "jitter-1-tail-thinking.png")


# ── 图2：抖动来源全谱（六大类）──────────────────────────────────
def fig2_sources():
    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    ax.add_patch(FancyBboxPatch((3.6, 4.4), 2.8, 0.7, boxstyle="round,pad=0.02",
                                facecolor="#ffe3e3", edgecolor=C_BAD, lw=2))
    ax.text(5.0, 4.75, "延迟尖峰 jitter", ha="center", va="center", fontsize=12, weight="bold", color=C_BAD)
    sources = [
        ("中断 IRQ", "网卡中断抢占交易核", 1.2),
        ("缺页 page fault", "访问未映射内存", 2.6),
        ("调度抢占", "CFS 把你的线程换下", 4.0),
        ("cache/TLB", "切换后冷 cache 重填", 5.4),
        ("NUMA 跨节点", "访远端内存延迟翻倍", 6.8),
        ("频率波动", "C-state/turbo 变频", 8.2),
    ]
    for name, desc, x in sources:
        ax.add_patch(FancyBboxPatch((x-0.95, 1.7), 1.9, 1.4, boxstyle="round,pad=0.02",
                                    facecolor="white", edgecolor=C_BLUE, lw=1.8))
        ax.text(x, 2.75, name, ha="center", fontsize=10, weight="bold", color=C_BLUE)
        ax.text(x, 2.15, desc, ha="center", fontsize=7.8, color="#444")
        ax.annotate("", xy=(x, 3.1), xytext=(5.0, 4.4),
                    arrowprops=dict(arrowstyle="->", color="#bbb", lw=1.3))
    ax.text(5.0, 0.9, "每一类都对应一个或多个消除手段（见下一张清单）。\n"
            "低延迟调优 = 逐一识别 → 逐一拔掉 → cyclictest 验证",
            ha="center", fontsize=10, color="#333", weight="bold")
    ax.set_xlim(0, 9.6); ax.set_ylim(0.4, 5.4); ax.axis("off")
    ax.set_title("抖动来源全谱：tail latency 的六大敌人", fontsize=12.5, weight="bold")
    _save(fig, "jitter-2-sources.png")


# ── 图3：核隔离前后——内核线程 vs 独占交易核 ────────────────────
def fig3_isolation():
    fig, axes = plt.subplots(2, 1, figsize=(9.5, 5.4))
    cores = ["核0", "核1", "核2", "核3", "核4", "核5", "核6", "核7"]
    # 上：默认——交易线程和一切混跑
    ax = axes[0]
    for i, c in enumerate(cores):
        ax.add_patch(Rectangle((i*1.2, 0), 1.1, 1.2, facecolor="#ffe9e9", edgecolor=C_EDGE, lw=1.5))
        ax.text(i*1.2+0.55, 0.85, c, ha="center", fontsize=9, color="#333")
        ax.text(i*1.2+0.55, 0.4, "内核+\n中断+\n你+别人", ha="center", va="center", fontsize=6.8, color=C_BAD)
    ax.text(4.8, 1.55, "[默认] 交易线程和内核线程、中断、其它进程在所有核上混跑 → 随时被抢占",
            ha="center", fontsize=10, color=C_BAD, weight="bold")
    ax.set_xlim(-0.2, 9.8); ax.set_ylim(-0.2, 1.9); ax.axis("off")
    # 下：隔离——核6/7 独占
    ax = axes[1]
    for i, c in enumerate(cores):
        if i >= 6:
            fc, txt, tc = "#e3f9e5", "交易线程\n忙轮询\n(独占)", C_GOOD
        else:
            fc, txt, tc = "#eef1f5", "内核+中断+\n其它进程", "#888"
        ax.add_patch(Rectangle((i*1.2, 0), 1.1, 1.2, facecolor=fc, edgecolor=C_EDGE, lw=1.5))
        ax.text(i*1.2+0.55, 0.92, c, ha="center", fontsize=9, color="#333")
        ax.text(i*1.2+0.55, 0.42, txt, ha="center", va="center", fontsize=6.8, color=tc)
    ax.text(4.8, 1.55, "[隔离] isolcpus+nohz_full 把核6/7从调度器抢出，IRQ亲和把中断赶到核0-5，交易核上只跑你",
            ha="center", fontsize=9.3, color=C_GOOD, weight="bold")
    ax.set_xlim(-0.2, 9.8); ax.set_ylim(-0.2, 1.9); ax.axis("off")
    fig.suptitle("CPU 隔离 + 绑核：把交易核从操作系统手里「抢」出来独占", fontsize=12.5, weight="bold", y=0.99)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    _save(fig, "jitter-3-isolation.png")


# ── 图4：系统级抖动消除清单（来源→手段映射）────────────────────
def fig4_checklist():
    fig, ax = plt.subplots(figsize=(10, 6))
    rows = [
        ("中断 IRQ 抢占", "IRQ 亲和：网卡中断绑到非交易核 (/proc/irq/*/smp_affinity)"),
        ("调度器抢占", "isolcpus + nohz_full + sched_setaffinity 绑核独占 + SCHED_FIFO"),
        ("缺页 page fault", "mlockall 锁页 + 启动 touch 预热全部内存"),
        ("TLB miss", "HugePages 大页 (2MB/1GB) 降低页表项数量"),
        ("内存换出 swap", "mlockall + swappiness=0，严禁交易进程被换出"),
        ("NUMA 跨节点访存", "numactl 把线程+内存+网卡绑同一 NUMA node"),
        ("CPU 降频/变频", "关 C-state/P-state + performance governor + 关 turbo"),
        ("透明大页回收", "关 THP（transparent_hugepage=never），它合并/回收会引尖峰"),
        ("同步写盘阻塞", "日志/落盘异步化，热路径绝不同步 write"),
    ]
    y = 5.55
    ax.text(2.4, 6.05, "抖动来源", ha="center", fontsize=11, weight="bold", color=C_BAD)
    ax.text(7.0, 6.05, "消除手段", ha="center", fontsize=11, weight="bold", color=C_GOOD)
    for src, fix in rows:
        ax.add_patch(FancyBboxPatch((0.1, y-0.26), 4.5, 0.5, boxstyle="round,pad=0.02",
                                    facecolor="#ffeeee", edgecolor=C_BAD, lw=1.3))
        ax.text(0.3, y, src, ha="left", va="center", fontsize=9.2, color="#7a2020", weight="bold")
        ax.annotate("", xy=(4.85, y), xytext=(4.6, y), arrowprops=dict(arrowstyle="->", color="#888", lw=1.4))
        ax.add_patch(FancyBboxPatch((4.9, y-0.26), 5.0, 0.5, boxstyle="round,pad=0.02",
                                    facecolor="#eefaef", edgecolor=C_GOOD, lw=1.3))
        ax.text(5.05, y, fix, ha="left", va="center", fontsize=8.2, color="#2f5d3a")
        y -= 0.58
    ax.text(5.0, y-0.05, "验证：cyclictest 测最大调度延迟，从几十 us 压到 us 内才算调好",
            ha="center", fontsize=9.8, color=C_BLUE, weight="bold")
    ax.set_xlim(0, 10); ax.set_ylim(y-0.4, 6.3); ax.axis("off")
    ax.set_title("系统级抖动消除清单：每个来源都有对应的「拔掉」手段", fontsize=12.5, weight="bold")
    _save(fig, "jitter-4-checklist.png")


# ── 图5：调优前后 cyclictest 最大延迟对比 ──────────────────────────
def fig5_before_after():
    fig, ax = plt.subplots(figsize=(8.6, 4.2))
    stages = ["默认系统", "+绑核\n+IRQ亲和", "+HugePage\n+mlockall", "+关C-state\n+isolcpus", "全套\n(终态)"]
    maxlat = [85, 42, 22, 9, 3.5]   # 最大延迟 us（示意：逐级下降）
    x = np.arange(len(stages))
    bars = ax.bar(x, maxlat, color=[C_BAD, "#e0773a", "#e0a800", "#8bc34a", C_GOOD], edgecolor=C_EDGE, width=0.6)
    ax.set_yscale("log")
    ax.set_ylim(1, 150)
    for xi, v in zip(x, maxlat):
        ax.text(xi, v*1.12, f"{v} us", ha="center", fontsize=10, weight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(stages, fontsize=9)
    ax.set_ylabel("cyclictest 最大延迟（us，对数轴）", fontsize=10.5)
    ax.axhline(3.5, color=C_GOOD, ls=":", lw=1.2)
    ax.set_title("逐级调优：cyclictest 最大延迟从 ~85us 压到个位数 us（示意趋势，非实测）", fontsize=11.5, weight="bold")
    ax.text(0.02, 0.96, "* 数值为示意调优趋势，真实数字依硬件而定，需本机 cyclictest 实测",
            transform=ax.transAxes, fontsize=8, color="#888", va="top")
    _save(fig, "jitter-5-before-after.png")


if __name__ == "__main__":
    fig1_tail_thinking()
    fig2_sources()
    fig3_isolation()
    fig4_checklist()
    fig5_before_after()
    print("ALL DONE")
