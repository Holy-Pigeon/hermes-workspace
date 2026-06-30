#!/usr/bin/env python3
"""生成 SPSC 环形队列课时配图（5 张）。直接画数据结构本身，不做拟人类比。
输出到 ../assets/spsc-*.png，DPI 150，白底。"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mp
from matplotlib.patches import FancyArrowPatch, Wedge, Rectangle, FancyBboxPatch
import numpy as np
from pathlib import Path

plt.rcParams["font.sans-serif"] = ["Hiragino Sans GB", "Songti SC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

OUT = Path(__file__).resolve().parents[1] / "assets"
OUT.mkdir(exist_ok=True)

# 配色（克制、高对比）
C_EMPTY = "#f0f2f5"      # 空槽
C_DATA = "#4C78A8"       # 已写入数据
C_READ = "#9ecae1"       # 已读待覆盖
C_EDGE = "#3b4252"
C_W = "#d62728"          # write 指针 红
C_R = "#2ca02c"          # read 指针 绿
C_HL = "#fff3cd"         # 高亮底


def _save(fig, name):
    p = OUT / name
    fig.savefig(p, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("saved", p)


# ── 图1：mutex 队列 vs 无锁 SPSC 的延迟分布（为什么要无锁）──────────────
def fig1_latency():
    fig, ax = plt.subplots(figsize=(8.4, 3.8))
    np.random.seed(7)
    # mutex: 均值低但有长尾尖峰（尖峰更集中、样本更多，让对数轴下的柱子真正长出来）
    base = np.random.normal(0.8, 0.15, 2000)
    spikes = np.concatenate([base, np.random.normal(6, 0.55, 180)])
    lockfree = np.random.normal(0.25, 0.05, 2000)
    bins = np.linspace(0, 11, 70)
    ax.hist(spikes, bins=bins, color="#d62728", alpha=0.55, label="mutex + queue（有锁）")
    ax.hist(lockfree, bins=bins, color="#4C78A8", alpha=0.7, label="SPSC 无锁队列")
    # 对数 Y 轴：让尾部尖峰真正可见（线性轴会把它压没）
    ax.set_yscale("log")
    ax.set_ylim(0.7, 1500)
    # P99.9 竖线，量化"最坏几次"
    p999 = np.percentile(spikes, 99.9)
    ax.axvline(p999, color="#d62728", ls="--", lw=1.5)
    ax.text(p999 + 0.15, 120, f"P99.9 ≈ {p999:.1f} us", color="#d62728", fontsize=9.5, weight="bold")
    ax.annotate("锁竞争尖峰\n（最坏的上百次，吃单/滑点就发生在这）",
                xy=(6, 60), xytext=(4.0, 400),
                fontsize=10, color="#d62728", ha="center", weight="bold",
                arrowprops=dict(arrowstyle="->", color="#d62728", lw=1.8))
    ax.annotate("绝大多数都很快\n（只看均值发现不了问题）",
                xy=(0.85, 500), xytext=(1.8, 30),
                fontsize=10, color="#333", ha="center",
                arrowprops=dict(arrowstyle="->", color="#888", lw=1.2))
    ax.set_xlabel("入队→出队延迟（微秒 us）", fontsize=11)
    ax.set_ylabel("出现次数（对数刻度）", fontsize=11)
    ax.set_title("为什么热路径不用锁：均值不重要，最坏的几次才致命", fontsize=12.5, weight="bold")
    ax.legend(fontsize=10, loc="upper right")
    ax.set_xlim(0, 11)
    _save(fig, "spsc-1-latency.png")


# ── 图2：环形队列的本质 = 一个数组首尾相接 ──────────────────────────
def fig2_ring_concept():
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    N = 8
    # 左：线性数组
    ax = axes[0]
    for i in range(N):
        ax.add_patch(Rectangle((i, 0), 0.96, 1, facecolor=C_EMPTY, edgecolor=C_EDGE, lw=1.5))
        ax.text(i + 0.48, 0.5, str(i), ha="center", va="center", fontsize=11, color="#555")
    ax.annotate("写到尾部就没地方了？", xy=(N, 0.5), xytext=(N - 3.5, 1.6),
                fontsize=11, color=C_W,
                arrowprops=dict(arrowstyle="->", color=C_W))
    ax.set_xlim(-0.5, N + 1.5); ax.set_ylim(-0.5, 2.2)
    ax.set_title("普通数组：线性，有尽头", fontsize=12, weight="bold")
    ax.axis("off")
    # 右：环形
    ax = axes[1]
    cx, cy, R = 0, 0, 1.0
    for i in range(N):
        a0 = 90 - i * 360 / N
        a1 = 90 - (i + 1) * 360 / N
        w = Wedge((cx, cy), R, a1, a0, width=0.45, facecolor=C_EMPTY, edgecolor=C_EDGE, lw=1.5)
        ax.add_patch(w)
        am = np.deg2rad((a0 + a1) / 2)
        ax.text(cx + 0.77 * np.cos(am), cy + 0.77 * np.sin(am), str(i),
                ha="center", va="center", fontsize=11, color="#555")
    ax.annotate("", xy=(0.2, 1.15), xytext=(-0.2, 1.15),
                arrowprops=dict(arrowstyle="->", color=C_DATA, lw=2,
                                connectionstyle="arc3,rad=-0.5"))
    ax.text(0, 1.45, "index 7 的下一个又回到 0", ha="center", fontsize=10.5, color=C_DATA)
    ax.set_xlim(-1.6, 1.6); ax.set_ylim(-1.4, 1.8)
    ax.set_aspect("equal"); ax.axis("off")
    ax.set_title("环形队列：下标取模首尾相接", fontsize=12, weight="bold")
    fig.suptitle("「环形」不是真的圆——是同一个数组，写到末尾绕回开头复用空槽", fontsize=12.5, weight="bold", y=1.02)
    _save(fig, "spsc-2-ring-concept.png")


def _draw_slots(ax, states, wpos, rpos, y=0, label_idx=True):
    """画一排槽位。states: 每槽颜色 list。wpos/rpos: 指针下标(可None)。"""
    N = len(states)
    for i, c in enumerate(states):
        ax.add_patch(Rectangle((i, y), 0.96, 1, facecolor=c, edgecolor=C_EDGE, lw=1.5))
        if label_idx:
            ax.text(i + 0.48, y - 0.28, str(i), ha="center", va="center", fontsize=9, color="#888")
    if wpos is not None:
        ax.annotate("写 writeIdx", xy=(wpos + 0.48, y + 1.02), xytext=(wpos + 0.48, y + 1.75),
                    ha="center", fontsize=10.5, color=C_W, weight="bold",
                    arrowprops=dict(arrowstyle="->", color=C_W, lw=2))
    if rpos is not None:
        ax.annotate("读 readIdx", xy=(rpos + 0.48, y), xytext=(rpos + 0.48, y - 1.15),
                    ha="center", fontsize=10.5, color=C_R, weight="bold",
                    arrowprops=dict(arrowstyle="->", color=C_R, lw=2))


# ── 图3：读写指针如何推进（4 个快照）──────────────────────────────
def fig3_pointers():
    fig, axes = plt.subplots(4, 1, figsize=(8.5, 8.2))
    N = 8
    E, D, Rd = C_EMPTY, C_DATA, C_READ
    snaps = [
        ("① 初始：空队列，读写指针都在 0",
         [E]*N, 0, 0),
        ("② 生产者写入 3 个 tick，writeIdx 前进到 3",
         [D,D,D,E,E,E,E,E], 3, 0),
        ("③ 消费者读走 2 个，readIdx 前进到 2（蓝→浅蓝=已读可覆盖）",
         [Rd,Rd,D,E,E,E,E,E], 3, 2),
        ("④ 继续写，writeIdx 绕回开头覆盖已读槽位（环形复用）",
         [D,D,D,D,D,D,D,E][:2]+[D]+[D,D,D,D,E] if False else [D,D,D,D,D,D,D,E],
         7, 2),
    ]
    # 修正第4个快照为绕回示意
    snaps[3] = ("④ 写满后 writeIdx 绕回，覆盖已被读过的旧槽（环形复用空间）",
                [D,D,D,D,D,D,D,D], 1, 2)
    for ax, (title, states, w, r) in zip(axes, snaps):
        _draw_slots(ax, states, w, r)
        ax.set_xlim(-0.5, N + 0.3); ax.set_ylim(-1.5, 2.1)
        ax.set_title(title, fontsize=11.5, loc="left", weight="bold")
        ax.axis("off")
    # 图例
    handles = [mp.Patch(facecolor=C_EMPTY, edgecolor=C_EDGE, label="空槽"),
               mp.Patch(facecolor=C_DATA, edgecolor=C_EDGE, label="已写入数据(待读)"),
               mp.Patch(facecolor=C_READ, edgecolor=C_EDGE, label="已读(可被覆盖)")]
    fig.legend(handles=handles, loc="lower center", ncol=3, fontsize=10, bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("读写指针各管一头：生产者只推 writeIdx，消费者只推 readIdx",
                 fontsize=13, weight="bold", y=1.0)
    fig.tight_layout(rect=[0, 0.02, 1, 0.97])
    _save(fig, "spsc-3-pointers.png")


# ── 图4：cache line 与伪共享（为什么要 alignas(64) 分离）────────────
def fig4_false_sharing():
    fig, axes = plt.subplots(2, 1, figsize=(9, 5.6))
    # 上：两个下标挤在同一 cache line —— 坏
    ax = axes[0]
    ax.add_patch(FancyBboxPatch((0.5, 0), 6, 1.2, boxstyle="round,pad=0.02",
                                facecolor="#ffe3e3", edgecolor=C_W, lw=2))
    ax.text(3.5, 1.45, "同一条 64 字节 Cache Line", ha="center", fontsize=11, color=C_W, weight="bold")
    ax.add_patch(Rectangle((1.0, 0.25), 1.6, 0.7, facecolor=C_W, alpha=0.7, edgecolor=C_EDGE))
    ax.text(1.8, 0.6, "writeIdx", ha="center", va="center", color="white", fontsize=10, weight="bold")
    ax.add_patch(Rectangle((3.4, 0.25), 1.6, 0.7, facecolor=C_R, alpha=0.8, edgecolor=C_EDGE))
    ax.text(4.2, 0.6, "readIdx", ha="center", va="center", color="white", fontsize=10, weight="bold")
    ax.annotate("生产者改 writeIdx", xy=(1.8, 0.95), xytext=(0.2, 2.0),
                fontsize=10, color=C_W, arrowprops=dict(arrowstyle="->", color=C_W))
    ax.annotate("消费者改 readIdx", xy=(4.2, 0.95), xytext=(5.0, 2.0),
                fontsize=10, color=C_R, arrowprops=dict(arrowstyle="->", color=C_R))
    ax.text(7.0, 0.6, "→ 任一核一写，整条 line\n在两核间反复失效弹跳\n= 伪共享 False Sharing",
            fontsize=10.5, color=C_W, va="center", weight="bold")
    ax.set_xlim(0, 11.5); ax.set_ylim(-0.3, 2.4)
    ax.set_title("[坏]：两个下标挤在同一 cache line", fontsize=12, weight="bold", loc="left", color=C_W)
    ax.axis("off")
    # 下：alignas(64) 分到两条 line —— 好
    ax = axes[1]
    ax.add_patch(FancyBboxPatch((0.5, 0), 2.7, 1.2, boxstyle="round,pad=0.02",
                                facecolor="#e3f9e5", edgecolor=C_R, lw=2))
    ax.add_patch(Rectangle((1.0, 0.25), 1.6, 0.7, facecolor=C_W, alpha=0.7, edgecolor=C_EDGE))
    ax.text(1.8, 0.6, "writeIdx", ha="center", va="center", color="white", fontsize=10, weight="bold")
    ax.text(1.85, 1.45, "Cache Line A", ha="center", fontsize=10.5, color=C_R, weight="bold")
    ax.add_patch(FancyBboxPatch((3.6, 0), 2.7, 1.2, boxstyle="round,pad=0.02",
                                facecolor="#e3f9e5", edgecolor=C_R, lw=2))
    ax.add_patch(Rectangle((4.1, 0.25), 1.6, 0.7, facecolor=C_R, alpha=0.8, edgecolor=C_EDGE))
    ax.text(4.9, 0.6, "readIdx", ha="center", va="center", color="white", fontsize=10, weight="bold")
    ax.text(4.95, 1.45, "Cache Line B", ha="center", fontsize=10.5, color=C_R, weight="bold")
    ax.text(7.0, 0.6, "→ 各占独立 line，互不干扰\nalignas(64) 把它们隔开\n两核各改各的，无弹跳",
            fontsize=10.5, color="#2ca02c", va="center", weight="bold")
    ax.set_xlim(0, 11.5); ax.set_ylim(-0.3, 2.4)
    ax.set_title("[好]：alignas(64) 各占一条 cache line", fontsize=12, weight="bold", loc="left", color="#2ca02c")
    ax.axis("off")
    fig.suptitle("伪共享 False Sharing：CPU 缓存以 64 字节为单位同步，挨太近会互相拖累",
                 fontsize=13, weight="bold", y=1.0)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    _save(fig, "spsc-4-false-sharing.png")


# ── 图5：acquire/release 的可见性保证（happens-before）─────────────
def fig5_memory_order():
    fig, ax = plt.subplots(figsize=(9.5, 5))
    # 生产者列
    px = 1.5
    cx = 7.5
    ax.text(px, 4.7, "生产者线程", ha="center", fontsize=12, weight="bold", color=C_W)
    ax.text(cx, 4.7, "消费者线程", ha="center", fontsize=12, weight="bold", color=C_R)
    # 步骤框
    def box(x, y, t, color):
        ax.add_patch(FancyBboxPatch((x-1.5, y-0.32), 3.0, 0.64, boxstyle="round,pad=0.02",
                                    facecolor="white", edgecolor=color, lw=1.8))
        ax.text(x, y, t, ha="center", va="center", fontsize=10)
    box(px, 3.8, "① 把 tick 数据写入槽位", C_W)
    box(px, 2.7, "② writeIdx.store(n, release)", C_W)
    box(cx, 2.7, "③ writeIdx.load(acquire)", C_R)
    box(cx, 1.6, "④ 读到新 writeIdx", C_R)
    box(cx, 0.5, "⑤ 安全读出①写的数据", C_R)
    # 内部顺序箭头
    ax.annotate("", xy=(px, 3.12), xytext=(px, 3.48), arrowprops=dict(arrowstyle="->", color=C_W, lw=1.8))
    ax.annotate("", xy=(cx, 1.92), xytext=(cx, 2.38), arrowprops=dict(arrowstyle="->", color=C_R, lw=1.8))
    ax.annotate("", xy=(cx, 0.82), xytext=(cx, 1.28), arrowprops=dict(arrowstyle="->", color=C_R, lw=1.8))
    # 跨线程 release->acquire 同步边
    ax.annotate("", xy=(cx-1.5, 2.7), xytext=(px+1.5, 2.7),
                arrowprops=dict(arrowstyle="->", color="#7048e8", lw=2.5,
                                connectionstyle="arc3,rad=-0.15"))
    ax.text(4.5, 3.15, "release → acquire 同步边", ha="center", fontsize=10.5, color="#7048e8", weight="bold")
    # 关键保证标注
    ax.add_patch(FancyBboxPatch((0.0, -0.7), 9.6, 0.7, boxstyle="round,pad=0.02",
                                facecolor=C_HL, edgecolor="#e0a800", lw=1.5))
    ax.text(4.8, -0.35,
            "保证：消费者一旦读到新 writeIdx（③④），就一定能看到①写好的数据——绝不会读到半成品",
            ha="center", va="center", fontsize=10.5, color="#664d03", weight="bold")
    ax.set_xlim(-0.3, 9.8); ax.set_ylim(-0.95, 5.1)
    ax.axis("off")
    ax.set_title("acquire/release：用最轻的同步，保证「数据先写好，指针才发布」",
                 fontsize=13, weight="bold")
    _save(fig, "spsc-5-memory-order.png")


if __name__ == "__main__":
    fig1_latency()
    fig2_ring_concept()
    fig3_pointers()
    fig4_false_sharing()
    fig5_memory_order()
    print("ALL DONE")
