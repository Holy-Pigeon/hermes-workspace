#!/usr/bin/env python3
"""生成「缺页处理全流程 + 核心换页算法」两张配图。画机制本身，不做拟人类比。
输出到 ../assets/paging-6/7-*.png，DPI 150，白底。"""
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
C_BAD = "#d62728"
C_GOOD = "#2ca02c"
C_BLUE = "#4C78A8"
C_FREE = "#f0f2f5"
C_HL = "#fff3cd"
C_ORANGE = "#d08770"
C_PURPLE = "#8e6bb0"


def _save(fig, name):
    p = OUT / name
    fig.savefig(p, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("saved", p)


# ── 图6：缺页处理全流程（handle_mm_fault 决策树）─────────────────────
def fig6_fault_handler():
    fig, ax = plt.subplots(figsize=(10.0, 6.4))

    def box(x, y, w, h, t, ec, fc="white", fs=9.0):
        ax.add_patch(FancyBboxPatch((x-w/2, y-h/2), w, h, boxstyle="round,pad=0.02",
                                    facecolor=fc, edgecolor=ec, lw=1.7))
        ax.text(x, y, t, ha="center", va="center", fontsize=fs, color="#222")

    def arrow(x0, y0, x1, y1, c=C_EDGE, lw=1.6, ls="-"):
        ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                    arrowprops=dict(arrowstyle="->", color=c, lw=lw, ls=ls))

    # 顶部：CPU 访存触发缺页
    box(5.0, 6.0, 4.4, 0.62, "CPU 执行 load/store，访问的虚拟页 PTE 无效", C_EDGE, C_HL, 9.5)
    box(5.0, 5.1, 3.4, 0.55, "硬件触发缺页异常 (#PF)，陷入内核", C_BAD, "#ffe3e3", 9.5)
    arrow(5.0, 5.68, 5.0, 5.38)
    box(5.0, 4.2, 3.4, 0.55, "内核 handle_mm_fault()", C_BLUE, "#eef2ff", 9.5)
    arrow(5.0, 4.82, 5.0, 4.48)

    # 第一分叉：地址合法吗（在某个 VMA 里、权限对吗）
    box(5.0, 3.25, 4.6, 0.7, "查 VMA：这个虚拟地址合法吗？\n(落在某段映射内 + 权限匹配)", C_EDGE, "white", 9.0)
    arrow(5.0, 3.92, 5.0, 3.6)

    # 非法 → SIGSEGV
    box(1.55, 3.25, 2.5, 0.7, "非法 / 越权\n→ SIGSEGV\n(段错误，杀进程)", C_BAD, "#ffe3e3", 8.8)
    arrow(2.7, 3.25, 3.8, 3.25, c=C_BAD)
    ax.text(3.25, 3.5, "否", ha="center", fontsize=8.5, color=C_BAD, weight="bold")

    # 合法 → 按页类型三分叉
    ax.text(5.0, 2.72, "合法：按「这一页是什么类型」决定从哪加载", ha="center", fontsize=9, color=C_GOOD, weight="bold")
    arrow(5.0, 2.9, 5.0, 2.6, c=C_GOOD)

    cols = [
        (2.0, C_ORANGE, "#fdeee4", "① 匿名页 (堆/栈)",
         "没有后备文件\n→ 分配零页帧\n+ 清零(安全)\nminor fault · us"),
        (5.0, C_BLUE, "#eef2ff", "② 文件页 (mmap文件/代码)",
         "有后备文件\n→ 从 page cache 找\n命中=minor / 未命中\n读磁盘文件=major"),
        (8.0, C_BAD, "#ffe3e3", "③ swap 页 (曾被换出)",
         "PTE 记着 swap 槽位\n→ 从 swap 区\n读回磁盘\nmajor fault · ms!"),
    ]
    for x, ec, fc, title, body in cols:
        box(x, 1.7, 2.7, 0.5, title, ec, fc, 8.6)
        arrow(5.0, 2.28, x, 1.96, c=ec)
        ax.add_patch(FancyBboxPatch((x-1.35, 0.35), 2.7, 0.95, boxstyle="round,pad=0.02",
                                    facecolor="white", edgecolor=ec, lw=1.4))
        ax.text(x, 0.82, body, ha="center", va="center", fontsize=8.0, color="#333")
        arrow(x, 1.44, x, 1.32, c=ec)

    # 底部汇合：建 PTE + 重执行
    ax.text(5.0, -0.12, "三类都归到：填好 PTE 映射 → 刷新 → 从触发缺页的那条指令「重新执行」，这次访存命中。",
            ha="center", fontsize=9.2, color=C_EDGE, weight="bold")

    ax.set_xlim(0, 10); ax.set_ylim(-0.4, 6.4); ax.axis("off")
    ax.set_title("缺页处理全流程：内核如何判定合法性、并按页类型决定「从哪加载数据」",
                 fontsize=12, weight="bold")
    _save(fig, "paging-6-fault-handler.png")


# ── 图7：Linux 页面回收 —— active/inactive 双 LRU + Clock + 水位线 ────
def fig7_reclaim():
    fig, ax = plt.subplots(figsize=(10.0, 6.2))

    # 左半：active / inactive 双链表 + 页在其间流动
    ax.text(2.9, 5.85, "Linux 页面回收：两条 LRU 链表 + 二次机会", ha="center", fontsize=11, weight="bold", color=C_EDGE)

    def lru_row(y, label, color, n, hot_idx):
        ax.text(0.35, y+0.55, label, ha="left", fontsize=9.5, weight="bold", color=color)
        for i in range(n):
            x = 0.4 + i * 0.62
            fc = color if i in hot_idx else "white"
            ax.add_patch(Rectangle((x, y), 0.56, 0.5, facecolor=fc, edgecolor=color, lw=1.4, alpha=0.85 if i in hot_idx else 1))
        return y

    lru_row(4.7, "active 链表（近期访问过的热页，受保护）", C_BAD, 6, [0,1,2,3,4,5])
    lru_row(3.3, "inactive 链表（久未访问的冷页，回收候选）", C_BLUE, 6, [])

    # 流动箭头：active 尾 → inactive 头（降级）
    ax.annotate("久未访问→降级到 inactive", xy=(0.6, 3.85), xytext=(2.6, 4.55),
                fontsize=8.2, color="#666", ha="center",
                arrowprops=dict(arrowstyle="->", color="#888", lw=1.5, connectionstyle="arc3,rad=-0.3"))
    # 再次访问 → 升回 active（二次机会）
    ax.annotate("回收前又被访问\n→升回 active（二次机会）", xy=(3.4, 4.65), xytext=(2.15, 2.98),
                fontsize=8.2, color=C_GOOD, ha="center", weight="bold",
                arrowprops=dict(arrowstyle="->", color=C_GOOD, lw=1.5, connectionstyle="arc3,rad=0.3"))

    # inactive 尾 → 换出
    ax.annotate("", xy=(4.6, 3.55), xytext=(4.05, 3.55), arrowprops=dict(arrowstyle="->", color=C_BAD, lw=1.8))
    ax.add_patch(FancyBboxPatch((4.65, 3.15), 1.7, 0.8, boxstyle="round,pad=0.02", facecolor="#ffe3e3", edgecolor=C_BAD, lw=1.5))
    ax.text(5.5, 3.55, "从 inactive 尾\n回收/换出\n(swap 或丢弃)", ha="center", va="center", fontsize=8.0, color="#222")

    ax.text(2.9, 2.55,
            "近似 LRU：真 LRU 每次访存都要更新全局链表，太贵。Linux 用「双链表 + 访问位」近似——\n"
            "被访问的页有机会从 inactive 救回 active，只有真正冷的页才从 inactive 尾被换出。",
            ha="center", fontsize=8.4, color="#333")

    # 右下：水位线 + kswapd
    ax.text(8.4, 5.85, "水位线触发：谁来回收、何时回收", ha="center", fontsize=10.5, weight="bold", color=C_EDGE)
    # 画一个内存"水桶"表示空闲页水位
    bx, by, bw, bh = 7.2, 1.2, 1.1, 3.9
    ax.add_patch(Rectangle((bx, by), bw, bh, facecolor="#f7f9fc", edgecolor=C_EDGE, lw=1.6))
    levels = [(0.78, "high 水位", C_GOOD, "空闲充足，kswapd 睡"),
              (0.50, "low 水位", C_ORANGE, "跌破→唤醒 kswapd\n后台异步回收"),
              (0.22, "min 水位", C_BAD, "再跌破→直接回收\n(分配线程自己同步回收，卡!)")]
    for frac, name, c, desc in levels:
        yy = by + bh * frac
        ax.plot([bx, bx+bw], [yy, yy], color=c, lw=2)
        ax.text(bx+bw+0.15, yy, name, ha="left", va="center", fontsize=8.6, color=c, weight="bold")
        ax.text(bx+bw+0.15, yy-0.28, desc, ha="left", va="center", fontsize=7.4, color="#555")
    # 水面（当前空闲）
    ax.add_patch(Rectangle((bx, by), bw, bh*0.50, facecolor="#cfe3f7", edgecolor="none", alpha=0.7))
    ax.text(bx+bw/2, by-0.25, "空闲页水位", ha="center", fontsize=8.2, color=C_BLUE)

    ax.text(8.4, 0.35,
            "kswapd：后台回收守护进程，平时睡。\n空闲跌破 low 就异步回收(不卡应用)；\n跌破 min 只能同步直接回收——这一下就是缺页/分配尖峰。",
            ha="center", fontsize=7.8, color="#333")

    ax.text(2.9, 0.4,
            "swappiness(0~100)：调「回收匿名页(换 swap) vs 回收文件页(丢 cache)」的倾向。\n"
            "低延迟交易设 swappiness=0 + mlockall：尽量别碰 swap，交易页锁死不进这套回收流程。",
            ha="center", fontsize=8.0, color=C_GOOD, weight="bold")

    ax.set_xlim(0, 10.4); ax.set_ylim(0, 6.2); ax.axis("off")
    ax.set_title("核心换页算法（Linux 实现）：active/inactive 双 LRU 近似 + kswapd 水位线触发",
                 fontsize=11.5, weight="bold")
    _save(fig, "paging-7-reclaim.png")


if __name__ == "__main__":
    fig6_fault_handler()
    fig7_reclaim()
    print("ALL DONE")
