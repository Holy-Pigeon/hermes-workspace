#!/usr/bin/env python3
"""生成 Kernel Bypass（内核旁路）课时配图（5 张）。直接画机制本身，不做拟人类比。
输出到 ../assets/kbypass-*.png，DPI 150，白底。
避免 Hiragino 缺字形字符（µ/✓/✗ 等），用 us / [好] / [坏] 代替。"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mp
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle
import numpy as np
from pathlib import Path

plt.rcParams["font.sans-serif"] = ["Hiragino Sans GB", "Songti SC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

OUT = Path(__file__).resolve().parents[1] / "assets"
OUT.mkdir(exist_ok=True)

C_KERNEL = "#d62728"     # 内核态 红
C_USER = "#4C78A8"       # 用户态 蓝
C_HW = "#6c757d"         # 硬件 灰
C_EDGE = "#3b4252"
C_GOOD = "#2ca02c"       # 好/快 绿
C_HL = "#fff3cd"
C_BAD = "#ffe3e3"


def _save(fig, name):
    p = OUT / name
    fig.savefig(p, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("saved", p)


def _box(ax, x, y, w, h, text, fc, ec, tc="white", fs=10, weight="normal"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02",
                                facecolor=fc, edgecolor=ec, lw=1.8))
    ax.text(x + w/2, y + h/2, text, ha="center", va="center",
            color=tc, fontsize=fs, weight=weight)


def _arrow(ax, x1, y1, x2, y2, color="#3b4252", lw=2, style="-|>"):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style,
                                 mutation_scale=16, color=color, lw=lw))


# ── 图1：标准内核路径 vs kernel bypass 路径（核心对比）──────────────
def fig1_paths():
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 6.6))

    # 左：标准 Linux 内核路径
    ax = axes[0]
    ax.set_title("标准 Linux 路径：穿过整条内核协议栈", fontsize=12.5, weight="bold", color=C_KERNEL)
    steps_l = [
        (5.2, "策略代码（用户态）", C_USER, C_USER),
        (4.3, "唤醒阻塞的线程（上下文切换）", "white", C_KERNEL),
        (3.4, "内核态 → 用户态 拷贝数据", "white", C_KERNEL),
        (2.5, "协议栈逐层解析 以太网/IP/UDP", "white", C_KERNEL),
        (1.6, "软中断 softirq 取包", "white", C_KERNEL),
        (0.7, "网卡硬件中断通知 CPU", "white", C_KERNEL),
        (-0.2, "网卡收到 UDP 组播行情包", C_HW, C_HW),
    ]
    for y, t, fc, ec in steps_l:
        tc = "white" if fc not in ("white",) else C_EDGE
        _box(ax, 0.3, y, 5.4, 0.62, t, fc if fc != "white" else "white", ec, tc=tc, fs=9.5)
    for i in range(len(steps_l) - 1):
        y_from = steps_l[i+1][0] + 0.62
        y_to = steps_l[i][0]
        _arrow(ax, 3.0, y_from, 3.0, y_to, color=C_KERNEL, lw=1.6)
    # 延迟来源标注
    ax.text(6.0, 0.9, "← 异步打断", fontsize=8.5, color=C_KERNEL)
    ax.text(6.0, 1.8, "← 调度不定时", fontsize=8.5, color=C_KERNEL)
    ax.text(6.0, 2.7, "← 逐层开销", fontsize=8.5, color=C_KERNEL)
    ax.text(6.0, 3.6, "← 一次跨态拷贝", fontsize=8.5, color=C_KERNEL)
    ax.text(6.0, 4.5, "← 唤醒延迟", fontsize=8.5, color=C_KERNEL)
    ax.text(3.0, 6.05, "每一步都在加延迟和抖动", fontsize=10.5, color=C_KERNEL, ha="center", weight="bold")
    ax.set_xlim(0, 8.2); ax.set_ylim(-0.6, 6.4)
    ax.axis("off")

    # 右：kernel bypass 路径
    ax = axes[1]
    ax.set_title("Kernel Bypass：把内核整个踢出数据路径", fontsize=12.5, weight="bold", color=C_GOOD)
    _box(ax, 0.3, 5.2, 5.4, 0.62, "策略代码（用户态）", C_USER, C_USER, fs=9.5)
    _box(ax, 0.3, 3.9, 5.4, 0.62, "用户态轮询线程 busy-poll 直接读包", C_USER, C_USER, fs=9.5)
    _box(ax, 0.3, 2.6, 5.4, 0.62, "用户态自己解析协议（或轻量栈）", C_USER, C_USER, fs=9.5)
    _box(ax, 0.3, 1.3, 5.4, 0.62, "网卡 Rx 队列 DMA 直接映射到用户态", C_GOOD, C_GOOD, fs=9.5)
    _box(ax, 0.3, -0.2, 5.4, 0.62, "网卡收到 UDP 组播行情包", C_HW, C_HW, fs=9.5)
    ys = [-0.2, 1.3, 2.6, 3.9, 5.2]
    for i in range(len(ys) - 1):
        _arrow(ax, 3.0, ys[i] + 0.62, 3.0, ys[i+1], color=C_GOOD, lw=2)
    ax.text(6.0, 1.95, "无中断\n无跨态拷贝\n无协议栈\n无唤醒", fontsize=9, color=C_GOOD, weight="bold", va="center")
    ax.text(3.0, 6.05, "内核被整个绕开，只剩最短直达路径", fontsize=10.5, color=C_GOOD, ha="center", weight="bold")
    ax.set_xlim(0, 8.2); ax.set_ylim(-0.6, 6.4)
    ax.axis("off")

    fig.suptitle("一个行情包到策略代码，要穿过多少层？——内核路径 vs 绕过内核",
                 fontsize=13.5, weight="bold", y=1.01)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    _save(fig, "kbypass-1-paths.png")


# ── 图2：中断驱动 vs 轮询 busy-poll ──────────────────────────────
def fig2_interrupt_vs_poll():
    fig, axes = plt.subplots(2, 1, figsize=(9.5, 5.6))

    # 上：中断驱动（被动等待）
    ax = axes[0]
    ax.set_title("中断驱动（epoll/recv 阻塞）：包来了才被叫醒，中间有不确定延迟", fontsize=11.5, weight="bold", color=C_KERNEL, loc="left")
    ax.text(0.2, 1.5, "CPU 核：", fontsize=10, weight="bold")
    # 时间轴：CPU 在睡，包到达，中断，唤醒
    ax.axhline(0.8, 0.08, 0.95, color="#ccc", lw=1)
    ax.add_patch(Rectangle((1.0, 0.55), 3.0, 0.5, facecolor="#e9ecef", edgecolor="#aaa"))
    ax.text(2.5, 0.8, "线程阻塞睡眠（不耗 CPU）", ha="center", va="center", fontsize=9, color="#666")
    _arrow(ax, 4.3, 2.0, 4.3, 1.1, color=C_KERNEL, lw=2)
    ax.text(4.3, 2.2, "包到达", ha="center", fontsize=9, color=C_KERNEL, weight="bold")
    ax.add_patch(Rectangle((4.3, 0.55), 1.4, 0.5, facecolor="#ffd8a8", edgecolor="#e8590c"))
    ax.text(5.0, 0.8, "中断+唤醒", ha="center", va="center", fontsize=8.5, color="#d9480f")
    ax.add_patch(Rectangle((5.7, 0.55), 2.5, 0.5, facecolor=C_USER, edgecolor=C_USER))
    ax.text(6.95, 0.8, "线程处理包", ha="center", va="center", fontsize=9, color="white")
    ax.annotate("这段唤醒延迟不确定\n（几百 ns ~ 几 us，时高时低）",
                xy=(5.0, 0.55), xytext=(5.0, -0.15), ha="center",
                fontsize=9, color=C_KERNEL, weight="bold",
                arrowprops=dict(arrowstyle="->", color=C_KERNEL))
    ax.set_xlim(0, 9); ax.set_ylim(-0.6, 2.5); ax.axis("off")

    # 下：轮询 busy-poll（永远醒着）
    ax = axes[1]
    ax.set_title("轮询 busy-poll：一个核死循环查队列，包一到立刻看到（延迟确定）", fontsize=11.5, weight="bold", color=C_GOOD, loc="left")
    ax.text(0.2, 1.5, "CPU 核：", fontsize=10, weight="bold")
    ax.axhline(0.8, 0.08, 0.95, color="#ccc", lw=1)
    # 一连串轮询小块
    for i in range(7):
        x = 1.0 + i * 0.62
        ax.add_patch(Rectangle((x, 0.55), 0.5, 0.5, facecolor="#d3f9d8", edgecolor=C_GOOD))
        ax.text(x + 0.25, 0.8, "查", ha="center", va="center", fontsize=8, color="#2b8a3e")
    _arrow(ax, 5.2, 2.0, 5.2, 1.1, color=C_GOOD, lw=2)
    ax.text(5.2, 2.2, "包到达", ha="center", fontsize=9, color=C_GOOD, weight="bold")
    ax.add_patch(Rectangle((5.34, 0.55), 2.5, 0.5, facecolor=C_USER, edgecolor=C_USER))
    ax.text(6.6, 0.8, "立刻处理包", ha="center", va="center", fontsize=9, color="white")
    ax.annotate("几乎零等待：线程本来就醒着\n代价 = 这个核 100% 空转烧着",
                xy=(4.9, 0.55), xytext=(5.2, -0.15), ha="center",
                fontsize=9, color=C_GOOD, weight="bold",
                arrowprops=dict(arrowstyle="->", color=C_GOOD))
    ax.set_xlim(0, 9); ax.set_ylim(-0.6, 2.5); ax.axis("off")

    fig.suptitle("面试分水岭题：忙等为什么比 epoll 延迟低？代价是什么？",
                 fontsize=13, weight="bold", y=1.0)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    _save(fig, "kbypass-2-interrupt-vs-poll.png")


# ── 图3：跨态拷贝 vs 零拷贝 ────────────────────────────────────
def fig3_copy():
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6))

    # 左：标准路径有一次跨态拷贝
    ax = axes[0]
    ax.set_title("[坏] 标准路径：内核态 → 用户态 拷一次", fontsize=12, weight="bold", color=C_KERNEL, loc="left")
    ax.add_patch(FancyBboxPatch((0.5, 2.6), 4.5, 1.4, boxstyle="round,pad=0.03",
                                facecolor=C_BAD, edgecolor=C_KERNEL, lw=1.8))
    ax.text(2.75, 3.75, "内核态空间", ha="center", fontsize=10, color=C_KERNEL, weight="bold")
    ax.add_patch(Rectangle((1.0, 2.85), 1.6, 0.6, facecolor=C_KERNEL, alpha=0.6, edgecolor=C_EDGE))
    ax.text(1.8, 3.15, "内核 buffer", ha="center", va="center", fontsize=8.5, color="white")
    ax.add_patch(FancyBboxPatch((0.5, 0.4), 4.5, 1.4, boxstyle="round,pad=0.03",
                                facecolor="#e7f0f7", edgecolor=C_USER, lw=1.8))
    ax.text(2.75, 1.55, "用户态空间", ha="center", fontsize=10, color=C_USER, weight="bold")
    ax.add_patch(Rectangle((1.0, 0.65), 1.6, 0.6, facecolor=C_USER, alpha=0.7, edgecolor=C_EDGE))
    ax.text(1.8, 0.95, "你的 buffer", ha="center", va="center", fontsize=8.5, color="white")
    _arrow(ax, 1.8, 2.85, 1.8, 1.25, color=C_KERNEL, lw=2.5)
    ax.text(2.1, 2.05, "拷贝\n(耗时+占带宽)", fontsize=9, color=C_KERNEL, weight="bold", va="center")
    ax.set_xlim(0, 5.5); ax.set_ylim(0, 4.5); ax.axis("off")

    # 右：零拷贝
    ax = axes[1]
    ax.set_title("[好] Kernel Bypass：DMA 直接落到用户态", fontsize=12, weight="bold", color=C_GOOD, loc="left")
    ax.add_patch(FancyBboxPatch((0.5, 0.4), 4.5, 1.4, boxstyle="round,pad=0.03",
                                facecolor="#e7f0f7", edgecolor=C_USER, lw=1.8))
    ax.text(2.75, 1.55, "用户态空间（DMA 区直接映射到这）", ha="center", fontsize=9, color=C_USER, weight="bold")
    ax.add_patch(Rectangle((1.0, 0.65), 1.6, 0.6, facecolor=C_GOOD, alpha=0.7, edgecolor=C_EDGE))
    ax.text(1.8, 0.95, "用户态 DMA 区", ha="center", va="center", fontsize=8, color="white")
    ax.add_patch(FancyBboxPatch((0.5, 3.0), 4.5, 1.0, boxstyle="round,pad=0.03",
                                facecolor="#f1f3f5", edgecolor=C_HW, lw=1.8))
    ax.text(2.75, 3.7, "网卡（DMA 写入）", ha="center", fontsize=10, color=C_HW, weight="bold")
    ax.add_patch(Rectangle((1.0, 3.12), 1.6, 0.42, facecolor=C_HW, alpha=0.6, edgecolor=C_EDGE))
    ax.text(1.8, 3.33, "网卡收包队列", ha="center", va="center", fontsize=8, color="white")
    _arrow(ax, 1.8, 3.12, 1.8, 1.25, color=C_GOOD, lw=2.5)
    ax.text(2.1, 2.1, "DMA 直达\n（零跨态拷贝）", fontsize=9, color=C_GOOD, weight="bold", va="center")
    ax.text(2.75, 2.4, "—— 内核被绕过 ——", ha="center", fontsize=8.5, color="#aaa", style="italic")
    ax.set_xlim(0, 5.5); ax.set_ylim(0, 4.5); ax.axis("off")

    fig.suptitle("零拷贝：包直接出现在用户态内存，省掉内核态→用户态那一次搬运",
                 fontsize=13, weight="bold", y=1.02)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    _save(fig, "kbypass-3-copy.png")


# ── 图4：用 CPU 换延迟的权衡 ──────────────────────────────────
def fig4_tradeoff():
    fig, ax = plt.subplots(figsize=(9, 4.8))
    # 两根柱：延迟 vs CPU 占用
    cats = ["epoll 阻塞\n(中断驱动)", "busy-poll\n(轮询)"]
    x = np.arange(2)
    lat = [3.2, 0.4]      # 相对延迟（含唤醒抖动）
    cpu = [5, 100]        # 一个核的占用%
    w = 0.32
    ax2 = ax.twinx()
    b1 = ax.bar(x - w/2, lat, w, color=C_KERNEL, alpha=0.75, label="尾延迟（越低越好）")
    b2 = ax2.bar(x + w/2, cpu, w, color=C_GOOD, alpha=0.7, label="CPU 占用（一个核 %）")
    ax.set_ylabel("相对尾延迟（us，越低越好）", fontsize=10.5, color=C_KERNEL)
    ax2.set_ylabel("CPU 占用（%，越低越省）", fontsize=10.5, color=C_GOOD)
    ax.set_xticks(x); ax.set_xticklabels(cats, fontsize=11)
    ax.set_ylim(0, 4); ax2.set_ylim(0, 120)
    for i, v in enumerate(lat):
        ax.text(i - w/2, v + 0.08, f"{v} us", ha="center", fontsize=9.5, color=C_KERNEL, weight="bold")
    for i, v in enumerate(cpu):
        ax2.text(i + w/2, v + 2, f"{v}%", ha="center", fontsize=9.5, color="#2b8a3e", weight="bold")
    ax.set_title("低延迟交易的取舍：故意「浪费」一个核，换包到即见的确定性",
                 fontsize=12.5, weight="bold")
    # 合并图例
    lines = [b1, b2]
    ax.legend([b1, b2], ["尾延迟（越低越好）", "CPU 占用（一个核 %）"],
              loc="upper center", fontsize=10)
    ax2.annotate("烧满一个核，但延迟降一个数量级\n且不再有唤醒抖动 —— HFT 认为值",
                xy=(1 + w/2, 100), xytext=(0.35, 72),
                fontsize=9.5, color="#2b8a3e", weight="bold",
                arrowprops=dict(arrowstyle="->", color=C_GOOD))
    _save(fig, "kbypass-4-tradeoff.png")


# ── 图5：适用边界——只热路径走 bypass ─────────────────────────
def fig5_boundary():
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    # 热路径
    _box(ax, 0.5, 3.2, 8.5, 1.0,
         "热路径（行情接收 / 下单发送）→ Kernel Bypass（DPDK / Onload）",
         C_GOOD, C_GOOD, fs=10.5, weight="bold")
    ax.text(0.5, 2.85, "只有这条最在意延迟的链路值得上 bypass：独占网卡、绑核、busy-poll", fontsize=9, color="#2b8a3e")
    # 管理/监控面
    _box(ax, 0.5, 1.2, 8.5, 1.0,
         "管理面 / 监控 / 日志 / 多进程共享 → 仍走正常内核 socket",
         C_USER, C_USER, fs=10.5, weight="bold")
    ax.text(0.5, 0.85, "享受内核给的一切：TCP 重传、拥塞控制、防火墙、tcpdump 抓包", fontsize=9, color=C_USER)
    # 提示
    ax.add_patch(FancyBboxPatch((0.5, -0.6), 8.5, 0.75, boxstyle="round,pad=0.02",
                                facecolor=C_HL, edgecolor="#e0a800", lw=1.5))
    ax.text(4.75, -0.22,
            "绕过内核 = 放弃内核给的一切保护与工具，所以只用在最热那一条路径上，其余照常走内核",
            ha="center", va="center", fontsize=9.5, color="#664d03", weight="bold")
    ax.set_xlim(0, 9.5); ax.set_ylim(-0.9, 4.6)
    ax.set_title("适用边界：bypass 不是免费的护城河，只铺在最热的那条路径",
                 fontsize=12.5, weight="bold")
    ax.axis("off")
    _save(fig, "kbypass-5-boundary.png")


if __name__ == "__main__":
    fig1_paths()
    fig2_interrupt_vs_poll()
    fig3_copy()
    fig4_tradeoff()
    fig5_boundary()
    print("ALL DONE")
