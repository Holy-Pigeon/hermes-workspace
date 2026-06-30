#!/usr/bin/env python3
"""生成「热路径零分配与内存池」课时配图（5 张）。画机制本身，不做拟人类比。
输出到 ../assets/mempool-*.png，DPI 150，白底。"""
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
C_FREE = "#f0f2f5"
C_USED = "#4C78A8"
C_HL = "#fff3cd"


def _save(fig, name):
    p = OUT / name
    fig.savefig(p, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("saved", p)


# ── 图1：malloc 延迟的长尾分布（为什么热路径禁 malloc）──────────────
def fig1_malloc_tail():
    fig, ax = plt.subplots(figsize=(8.6, 3.9))
    np.random.seed(11)
    # 内存池：稳定在极低延迟（几十 ns）
    pool = np.random.normal(25, 4, 3000)
    # malloc：大多数快(命中free list)，但偶尔触发 mmap/sbrk/锁竞争 -> 微秒级尖峰
    base = np.random.normal(80, 20, 2800)
    spikes = np.concatenate([base, np.random.normal(2500, 400, 220)])
    bins = np.linspace(0, 3500, 80)
    ax.hist(spikes, bins=bins, color=C_BAD, alpha=0.55, label="malloc / new（每次现申请）")
    ax.hist(pool, bins=bins, color=C_GOOD, alpha=0.75, label="内存池（预分配复用）")
    ax.set_yscale("log")
    ax.set_ylim(0.7, 3000)
    p999 = np.percentile(spikes, 99.9)
    ax.axvline(p999, color=C_BAD, ls="--", lw=1.5)
    ax.text(p999 + 60, 120, f"malloc P99.9 ≈ {p999:.0f} ns", color=C_BAD, fontsize=9.5, weight="bold")
    ax.annotate("malloc 尖峰\n(触发 mmap/sbrk/页表/锁竞争)\n一次就吃掉一笔单",
                xy=(2500, 50), xytext=(1500, 600),
                fontsize=9.5, color=C_BAD, ha="center", weight="bold",
                arrowprops=dict(arrowstyle="->", color=C_BAD, lw=1.8))
    ax.annotate("内存池：紧贴 0，\n几乎无尾", xy=(25, 800), xytext=(550, 1200),
                fontsize=9.5, color=C_GOOD, ha="center", weight="bold",
                arrowprops=dict(arrowstyle="->", color=C_GOOD, lw=1.5))
    ax.set_xlabel("单次取一个对象的延迟（纳秒 ns）", fontsize=11)
    ax.set_ylabel("出现次数（对数刻度）", fontsize=11)
    ax.set_title("为什么热路径禁 new/malloc：均值不可怕，可怕的是不确定的微秒级尖峰", fontsize=12, weight="bold")
    ax.legend(fontsize=10, loc="upper right")
    ax.set_xlim(0, 3500)
    _save(fig, "mempool-1-malloc-tail.png")


# ── 图2：malloc 一次调用背后藏了多少不确定开销 ──────────────────────
def fig2_malloc_anatomy():
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    ax.text(4.8, 4.55, "你写的一行 `p = new Order();` 背后", ha="center", fontsize=12.5, weight="bold")
    layers = [
        ("① 分配器查 free list / bin", "快路径：命中就几十 ns", C_GOOD),
        ("② 没合适块 → 加锁(多线程竞争)", "锁等待：不确定", C_BAD),
        ("③ 向内核要内存 mmap/sbrk", "系统调用：微秒级", C_BAD),
        ("④ 首次访问触发缺页 page fault", "建页表项：微秒级尖峰", C_BAD),
        ("⑤ 构造函数 + 后续 cache miss", "冷内存：访问慢", C_BAD),
    ]
    y = 3.7
    for txt, cost, c in layers:
        ax.add_patch(FancyBboxPatch((0.4, y - 0.32), 5.6, 0.6, boxstyle="round,pad=0.02",
                                    facecolor="white", edgecolor=c, lw=1.8))
        ax.text(0.6, y, txt, ha="left", va="center", fontsize=10)
        ax.text(6.3, y, cost, ha="left", va="center", fontsize=9.5, color=c, weight="bold")
        y -= 0.78
    ax.text(4.8, -0.15,
            "①是快路径，但②③④⑤随时可能发生且不可预测 → 延迟方差巨大。\n"
            "交易热路径要的是「每次都一样快」，而不是「平均快」。",
            ha="center", fontsize=10, color="#333", weight="bold")
    ax.set_xlim(0, 9.6); ax.set_ylim(-0.6, 4.8); ax.axis("off")
    ax.set_title("malloc 的「不确定」从哪来：一次调用可能踩中 5 层开销", fontsize=12.5, weight="bold")
    _save(fig, "mempool-2-malloc-anatomy.png")


# ── 图3：对象池(free list)的工作原理 ────────────────────────────────
def fig3_objpool():
    fig, axes = plt.subplots(3, 1, figsize=(9, 7))
    N = 8
    def draw(ax, states, freehead, title):
        for i, s in enumerate(states):
            c = C_USED if s == "U" else C_FREE
            ax.add_patch(Rectangle((i, 0), 0.96, 1, facecolor=c, edgecolor=C_EDGE, lw=1.5))
            ax.text(i + 0.48, 0.5, "用" if s == "U" else "空", ha="center", va="center",
                    fontsize=10, color="white" if s == "U" else "#888")
            ax.text(i + 0.48, -0.32, str(i), ha="center", fontsize=8.5, color="#999")
        if freehead is not None:
            ax.annotate("free list 头\n(下一个可发)", xy=(freehead + 0.48, 1.02),
                        xytext=(freehead + 0.48, 1.95), ha="center", fontsize=9.5,
                        color=C_GOOD, weight="bold",
                        arrowprops=dict(arrowstyle="->", color=C_GOOD, lw=2))
        ax.set_xlim(-0.4, N + 0.3); ax.set_ylim(-0.7, 2.3)
        ax.set_title(title, fontsize=11, loc="left", weight="bold")
        ax.axis("off")
    draw(axes[0], ["F"]*N, 0, "① 启动时一次性预分配 N 个对象，全部挂进 free list（空闲链表）")
    draw(axes[1], ["U","U","U","F","F","F","F","F"], 3,
         "② acquire()：从 free list 头摘一个给你用（O(1)，零系统调用、零构造申请）")
    draw(axes[2], ["U","F","U","F","F","F","F","F"], 1,
         "③ release(obj)：用完归还，挂回 free list 头（不还给操作系统，留着复用）")
    fig.suptitle("对象池 / free list：启动预分配，运行期只在池内「借→还」，全程不碰 malloc",
                 fontsize=12.5, weight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    _save(fig, "mempool-3-objpool.png")


# ── 图4：arena / bump allocator 线性分配 ───────────────────────────
def fig4_arena():
    fig, ax = plt.subplots(figsize=(9.5, 4.2))
    # 一整块预分配 arena
    ax.add_patch(Rectangle((0.5, 1.5), 9, 1, facecolor=C_FREE, edgecolor=C_EDGE, lw=2))
    ax.text(5, 2.75, "启动时一次性 mmap 的一大块连续内存 (arena)", ha="center", fontsize=11, weight="bold")
    # 已分配部分
    segs = [(0.5, 1.8, "对象A"), (2.3, 1.5, "对象B"), (3.8, 2.2, "对象C")]
    x = 0.5
    for w, _, name in [(1.8,0,"A"),(1.5,0,"B"),(2.2,0,"C")]:
        ax.add_patch(Rectangle((x, 1.5), w, 1, facecolor=C_USED, edgecolor=C_EDGE, lw=1.5, alpha=0.8))
        ax.text(x + w/2, 2.0, name, ha="center", va="center", color="white", fontsize=10, weight="bold")
        x += w
    # bump 指针
    ax.annotate("bump 指针\n(下一个分配位置)", xy=(x, 1.5), xytext=(x, 0.5),
                ha="center", fontsize=10, color=C_BAD, weight="bold",
                arrowprops=dict(arrowstyle="->", color=C_BAD, lw=2))
    ax.text(x + 0.1, 2.0, "← 空闲", ha="left", va="center", fontsize=9.5, color="#888")
    ax.text(5, 0.0, "分配 = 指针往后挪一截（一条加法指令！）。不支持单个释放，\n"
            "整批用完后一次性 reset 指针回开头 → 整个 arena 瞬间清空复用。",
            ha="center", fontsize=10, color="#333", weight="bold")
    ax.set_xlim(0, 10); ax.set_ylim(-0.6, 3.2); ax.axis("off")
    ax.set_title("Arena / Bump 分配器：分配就是「指针 +size」，最快的分配方式", fontsize=12.5, weight="bold")
    _save(fig, "mempool-4-arena.png")


# ── 图5：何时用对象池 vs arena vs 栈 决策 ──────────────────────────
def fig5_decision():
    fig, ax = plt.subplots(figsize=(9.8, 5.2))
    def box(x, y, w, h, t, c, fc="white", fs=10):
        ax.add_patch(FancyBboxPatch((x-w/2, y-h/2), w, h, boxstyle="round,pad=0.02",
                                    facecolor=fc, edgecolor=c, lw=2))
        ax.text(x, y, t, ha="center", va="center", fontsize=fs, color="#222")
    box(4.9, 4.7, 5.0, 0.7, "热路径要一块内存放对象", "#333", fc="#eef2ff", fs=11)
    # 分支1
    box(1.9, 3.2, 3.0, 0.95, "大小固定、要单个\n频繁借还\n(订单/消息对象)", C_GOOD, fc="#e3f9e5", fs=9.5)
    box(1.9, 1.4, 3.0, 0.7, "对象池 / free list", C_GOOD, fc="white", fs=10.5)
    box(4.9, 3.2, 2.9, 0.95, "一批临时对象\n同生共死\n(一次行情的中间量)", C_BLUE, fc="#e7f0fb", fs=9.5)
    box(4.9, 1.4, 2.9, 0.7, "Arena / bump", C_BLUE, fc="white", fs=10.5)
    box(8.0, 3.2, 2.7, 0.95, "生命周期不超\n出本函数\n小、个数已知", "#d08770", fc="#fdeee4", fs=9.5)
    box(8.0, 1.4, 2.7, 0.7, "栈上 / std::array", "#d08770", fc="white", fs=10.5)
    for x in (1.9, 4.9, 8.0):
        ax.annotate("", xy=(x, 4.35), xytext=(4.9, 4.35), arrowprops=dict(arrowstyle="-", color="#bbb", lw=1.2))
        ax.annotate("", xy=(x, 3.72), xytext=(x, 4.35), arrowprops=dict(arrowstyle="->", color="#888", lw=1.5))
        ax.annotate("", xy=(x, 1.78), xytext=(x, 2.72), arrowprops=dict(arrowstyle="->", color="#888", lw=1.5))
    ax.text(4.9, 0.45, "共同铁律：内存都在启动时一次性分配好，热路径只「复用」，绝不 new/malloc/delete",
            ha="center", fontsize=10.5, color=C_BAD, weight="bold")
    ax.set_xlim(0, 9.9); ax.set_ylim(0, 5.2); ax.axis("off")
    ax.set_title("热路径内存策略决策树：按「生命周期形态」选工具", fontsize=12.5, weight="bold")
    _save(fig, "mempool-5-decision.png")


if __name__ == "__main__":
    fig1_malloc_tail()
    fig2_malloc_anatomy()
    fig3_objpool()
    fig4_arena()
    fig5_decision()
    print("ALL DONE")
