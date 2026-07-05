#!/usr/bin/env python3
"""生成「进程 vs 线程」课时配图（3 张）。画机制本身，不做拟人类比。
输出到 ../assets/procthread-*.png，DPI 150，白底。"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle
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
C_ORANGE = "#d08770"
C_PURPLE = "#8e6bb0"
C_SHARE = "#e3f9e5"
C_PRIV = "#eef2ff"


def _save(fig, name):
    p = OUT / name
    fig.savefig(p, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("saved", p)


# ── 图1：task_struct / mm_struct 共享关系（进程 vs 线程各拥有什么）──
def fig1_datastruct():
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(11.0, 5.4))

    def task_box(ax, x, y, w, label, color):
        ax.add_patch(FancyBboxPatch((x, y), w, 0.5, boxstyle="round,pad=0.02",
                                    facecolor=color, edgecolor=C_EDGE, lw=1.5))
        ax.text(x + w/2, y + 0.25, label, ha="center", va="center", fontsize=8.5, color="#222")

    # 左：两个进程 —— 各自独立 mm_struct（地址空间）
    axL.set_title("两个进程：各有独立 mm_struct（地址空间）", fontsize=11, weight="bold")
    for i, px in enumerate([0.3, 3.3]):
        axL.add_patch(FancyBboxPatch((px, 0.5), 2.5, 4.2, boxstyle="round,pad=0.03",
                                     facecolor="#fafbfc", edgecolor=C_BLUE, lw=2))
        axL.text(px + 1.25, 4.45, f"进程 {i+1}", ha="center", fontsize=10, weight="bold", color=C_BLUE)
        task_box(axL, px+0.25, 3.75, 2.0, "task_struct\n(PID, 调度实体)", C_PRIV)
        task_box(axL, px+0.25, 3.05, 2.0, "mm_struct\n(独立地址空间)", C_PRIV)
        task_box(axL, px+0.25, 2.35, 2.0, "独立页表 / 堆 / 全局区", C_PRIV)
        task_box(axL, px+0.25, 1.65, 2.0, "打开的文件表 fd", C_PRIV)
        task_box(axL, px+0.25, 0.85, 2.0, "内核栈 + 用户栈", C_PRIV)
    axL.text(3.05, 0.15, "两个进程之间：地址空间完全隔离，互不可见\n一个崩了另一个不受影响（故障域隔离）",
             ha="center", fontsize=9, color=C_BLUE, weight="bold")
    axL.set_xlim(0, 6.1); axL.set_ylim(0, 4.9); axL.axis("off")

    # 右：一个进程内两个线程 —— 共享 mm_struct，各自栈/TLS
    axR.set_title("一个进程内两个线程：共享 mm_struct，各自栈/TLS", fontsize=11, weight="bold")
    axR.add_patch(FancyBboxPatch((0.3, 0.5), 5.5, 4.2, boxstyle="round,pad=0.03",
                                 facecolor="#fafbfc", edgecolor=C_GOOD, lw=2))
    axR.text(3.05, 4.45, "进程（一个地址空间）", ha="center", fontsize=10, weight="bold", color=C_GOOD)
    # 共享区（中间横跨）
    task_box(axR, 0.6, 3.65, 4.9, "共享：mm_struct（地址空间）· 堆 · 全局区 · 打开的文件表 fd · 代码段", C_SHARE)
    axR.text(3.05, 3.5, "↑ 所有线程共享这一份 ↑", ha="center", fontsize=8, color=C_GOOD)
    # 两个线程各自私有
    for i, px in enumerate([0.6, 3.15]):
        axR.add_patch(FancyBboxPatch((px, 0.9), 2.35, 2.2, boxstyle="round,pad=0.02",
                                     facecolor="white", edgecolor=C_ORANGE, lw=1.6))
        axR.text(px + 1.17, 2.85, f"线程 {i+1}（私有）", ha="center", fontsize=9, weight="bold", color=C_ORANGE)
        task_box(axR, px+0.15, 2.15, 2.05, "task_struct (TID)", "#fdeee4")
        task_box(axR, px+0.15, 1.55, 2.05, "自己的栈 stack", "#fdeee4")
        task_box(axR, px+0.15, 0.95, 2.05, "TLS 线程局部存储", "#fdeee4")
    axR.text(3.05, 0.15, "线程之间：直接读写同一份内存（通信快，但要同步）\n一个线程踩坏内存/崩溃 → 整个进程一起完",
             ha="center", fontsize=9, color=C_BAD, weight="bold")
    axR.set_xlim(0, 6.1); axR.set_ylim(0, 4.9); axR.axis("off")

    fig.suptitle("数据结构视角：Linux 底层进程和线程都是 task_struct，差别在「共享还是独占 mm_struct」",
                 fontsize=12, weight="bold", y=1.0)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    _save(fig, "procthread-1-datastruct.png")


# ── 图2：fork(COW) vs clone(共享) 的创建路径 ──────────────────────
def fig2_create():
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(11.0, 4.8))

    # 左：fork —— 复制地址空间，写时复制 COW
    axL.set_title("fork() 建进程：复制地址空间（写时复制 COW）", fontsize=10.5, weight="bold")
    axL.add_patch(FancyBboxPatch((0.3, 3.4), 2.3, 0.7, boxstyle="round,pad=0.02", facecolor=C_PRIV, edgecolor=C_BLUE, lw=1.6))
    axL.text(1.45, 3.75, "父进程\n地址空间", ha="center", va="center", fontsize=9, weight="bold")
    axL.add_patch(FancyBboxPatch((3.6, 3.4), 2.3, 0.7, boxstyle="round,pad=0.02", facecolor=C_PRIV, edgecolor=C_BLUE, lw=1.6))
    axL.text(4.75, 3.75, "子进程\n地址空间(新)", ha="center", va="center", fontsize=9, weight="bold")
    axL.annotate("", xy=(3.6, 3.75), xytext=(2.6, 3.75), arrowprops=dict(arrowstyle="->", color=C_BLUE, lw=1.8))
    axL.text(3.1, 3.95, "fork", ha="center", fontsize=8.5, color=C_BLUE)
    # COW 共享物理页
    axL.add_patch(Rectangle((1.9, 1.6), 2.4, 0.9, facecolor=C_SHARE, edgecolor=C_GOOD, lw=1.6))
    axL.text(3.1, 2.05, "物理页：初始共享\n(标记只读)", ha="center", va="center", fontsize=8.5, color="#222")
    axL.annotate("", xy=(2.6, 2.5), xytext=(1.45, 3.4), arrowprops=dict(arrowstyle="->", color=C_GOOD, lw=1.4))
    axL.annotate("", xy=(3.6, 2.5), xytext=(4.75, 3.4), arrowprops=dict(arrowstyle="->", color=C_GOOD, lw=1.4))
    axL.text(3.1, 1.15, "谁先写某页 → 那一刻才真复制该页\n(copy-on-write，省掉全量拷贝)", ha="center", fontsize=8.5, color=C_GOOD, weight="bold")
    axL.text(3.1, 0.35, "本机实测：fork 建进程 mean≈174 us", ha="center", fontsize=9, color=C_BAD, weight="bold")
    axL.set_xlim(0, 6.2); axL.set_ylim(0, 4.4); axL.axis("off")

    # 右：clone —— 共享地址空间，只建新栈
    axR.set_title("pthread/clone 建线程：共享地址空间，只建新栈", fontsize=10.5, weight="bold")
    axR.add_patch(FancyBboxPatch((1.9, 3.2), 2.4, 0.95, boxstyle="round,pad=0.02", facecolor=C_SHARE, edgecolor=C_GOOD, lw=1.8))
    axR.text(3.1, 3.67, "同一份 mm_struct\n(地址空间不复制)", ha="center", va="center", fontsize=9, weight="bold")
    for i, px in enumerate([1.0, 4.0]):
        axR.add_patch(FancyBboxPatch((px, 1.7), 1.6, 0.7, boxstyle="round,pad=0.02", facecolor="#fdeee4", edgecolor=C_ORANGE, lw=1.5))
        axR.text(px+0.8, 2.05, f"线程{i+1}\n新栈+TID", ha="center", va="center", fontsize=8.5)
        axR.annotate("", xy=(px+0.8, 2.4), xytext=(3.1 if i else 3.1, 3.2), arrowprops=dict(arrowstyle="->", color=C_ORANGE, lw=1.4))
    axR.text(3.1, 1.15, "clone(CLONE_VM|CLONE_FILES|...)：\n共享内存/文件表，只分配新栈和调度实体", ha="center", fontsize=8.5, color=C_ORANGE, weight="bold")
    axR.text(3.1, 0.35, "本机实测：pthread 建线程 mean≈5.5 us（快 31 倍）", ha="center", fontsize=9, color=C_GOOD, weight="bold")
    axR.set_xlim(0, 6.2); axR.set_ylim(0, 4.4); axR.axis("off")

    fig.suptitle("创建/申请视角：fork 复制整个地址空间(COW) vs clone 共享地址空间只建栈 —— 差一个量级",
                 fontsize=11.5, weight="bold", y=1.0)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    _save(fig, "procthread-2-create.png")


# ── 图3：本机实测 创建开销 + 上下文切换开销 ────────────────────────
def fig3_cost():
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(11.0, 4.4))

    # 左：创建开销（对数 Y，差 31 倍）
    labels = ["建线程\n(pthread)", "建进程\n(fork)"]
    vals = [5550, 173769]  # ns，本机实测 mean
    colors = [C_GOOD, C_BAD]
    bars = axL.bar(labels, vals, color=colors, width=0.55, edgecolor=C_EDGE, lw=1.2)
    axL.set_yscale("log")
    axL.set_ylabel("创建一次的平均耗时 (ns, 对数轴)", fontsize=10)
    for b, v in zip(bars, vals):
        axL.text(b.get_x()+b.get_width()/2, v*1.15, f"{v/1000:.1f} us", ha="center", fontsize=10, weight="bold")
    axL.set_title("创建开销：建进程是建线程的 31 倍（本机实测）", fontsize=10.5, weight="bold")
    axL.text(0.5, 2200, "fork 要建新地址空间/\n页表/COW 元数据 → 重",
             ha="center", va="center", fontsize=8.5, color=C_BAD)
    axL.set_ylim(1000, 500000)

    # 右：上下文切换 vs 纯计算（对数 Y，差 541 倍）
    labels2 = ["同线程\n纯计算", "跨线程\n上下文切换"]
    vals2 = [2.0, 1063]
    bars2 = axR.bar(labels2, vals2, color=[C_BLUE, C_BAD], width=0.55, edgecolor=C_EDGE, lw=1.2)
    axR.set_yscale("log")
    axR.set_ylabel("单次耗时 (ns, 对数轴)", fontsize=10)
    for b, v in zip(bars2, vals2):
        txt = f"{v:.0f} ns" if v >= 10 else f"{v:.0f} ns"
        axR.text(b.get_x()+b.get_width()/2, v*1.2, txt, ha="center", fontsize=10, weight="bold")
    axR.set_title("上下文切换：是纯计算的 541 倍（本机实测）", fontsize=10.5, weight="bold")
    axR.text(0.5, 130, "切换=陷内核+调度+\n刷TLB/冷cache\n关键线程目标:零切换",
             ha="center", va="center", fontsize=8.5, color=C_BAD)
    axR.set_ylim(1, 5000)

    fig.suptitle("开销视角（本机实测）：建进程>>建线程，跨线程切换>>纯计算 —— 低延迟系统两者都要压到零",
                 fontsize=11.5, weight="bold", y=1.0)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    _save(fig, "procthread-3-cost.png")


if __name__ == "__main__":
    fig1_datastruct()
    fig2_create()
    fig3_cost()
    print("ALL DONE")
