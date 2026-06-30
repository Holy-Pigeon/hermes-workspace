#!/usr/bin/env python3
"""生成「六种 memory_order」课时配图（5 张）。直接画机制本身，不做拟人类比。
输出到 ../assets/memorder-*.png，DPI 150，白底。"""
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
C_W = "#d62728"      # 写/线程1 红
C_R = "#2ca02c"      # 读/线程2 绿
C_SYNC = "#7048e8"   # 同步边 紫
C_HL = "#fff3cd"
C_BOX = "white"


def _save(fig, name):
    p = OUT / name
    fig.savefig(p, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("saved", p)


def _box(ax, x, y, t, color, w=3.0, h=0.6, fs=10):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.02",
                                facecolor=C_BOX, edgecolor=color, lw=1.8))
    ax.text(x, y, t, ha="center", va="center", fontsize=fs)


# ── 图1：为什么需要内存序——源码顺序 != 实际执行顺序 ──────────────────
def fig1_reorder():
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.4))
    # 左：源码里你写的顺序
    ax = axes[0]
    src = ["data = 42;        // ① 写数据", "ready = true;     // ② 置标志位"]
    for i, s in enumerate(src):
        y = 1.6 - i * 0.9
        _box(ax, 2.6, y, s, C_W, w=4.6, h=0.62, fs=10.5)
        if i == 0:
            ax.annotate("", xy=(2.6, y - 0.55), xytext=(2.6, y - 0.35),
                        arrowprops=dict(arrowstyle="->", color=C_W, lw=1.8))
    ax.text(2.6, 2.6, "你在源码里写的顺序", ha="center", fontsize=12, weight="bold", color=C_W)
    ax.set_xlim(-0.2, 5.4); ax.set_ylim(0.1, 3.0); ax.axis("off")
    # 右：CPU/编译器实际可能跑的顺序
    ax = axes[1]
    src2 = ["ready = true;     // ② 先可见了！", "data = 42;        // ① 还没写完"]
    for i, s in enumerate(src2):
        y = 1.6 - i * 0.9
        _box(ax, 2.6, y, s, "#888", w=4.6, h=0.62, fs=10.5)
    ax.text(2.6, 2.6, "CPU / 编译器实际可能的顺序", ha="center", fontsize=12, weight="bold", color="#555")
    ax.text(2.6, 0.45, "→ 另一个线程看到 ready==true 就去读 data，\n却读到旧值/半成品。这就是「重排」之祸。",
            ha="center", fontsize=10.2, color=C_W, weight="bold")
    ax.set_xlim(-0.2, 5.4); ax.set_ylim(0.1, 3.0); ax.axis("off")
    fig.suptitle("为什么要管内存序：源码顺序 ≠ 实际执行顺序（编译器重排 + CPU 乱序）",
                 fontsize=13, weight="bold", y=1.02)
    fig.tight_layout()
    _save(fig, "memorder-1-reorder.png")


# ── 图2：六种 memory_order 强弱谱系 + 开销 ──────────────────────────
def fig2_spectrum():
    fig, ax = plt.subplots(figsize=(11, 4.2))
    items = [
        ("relaxed", "只保证单变量原子性\n+ 修改顺序", "#2ca02c", 0.5),
        ("consume", "(实践基本不用\n退化为 acquire)", "#bbbbbb", 1.0),
        ("acquire", "读屏障：之后的访问\n不被提到它前面", "#4C78A8", 1.8),
        ("release", "写屏障：之前的访问\n不被拖到它后面", "#4C78A8", 1.8),
        ("acq_rel", "读改写一步\n兼具 acq+rel", "#d08770", 2.6),
        ("seq_cst", "全局单一总序\n最强最贵(默认)", "#d62728", 3.4),
    ]
    n = len(items)
    xs = np.linspace(0.8, 10.2, n)
    for x, (name, desc, c, cost) in zip(xs, items):
        ax.add_patch(FancyBboxPatch((x - 0.78, 1.4), 1.56, 1.5, boxstyle="round,pad=0.02",
                                    facecolor="white", edgecolor=c, lw=2.2))
        ax.text(x, 2.62, name, ha="center", fontsize=11, weight="bold", color=c)
        ax.text(x, 1.95, desc, ha="center", fontsize=8.3, color="#333")
        # 开销条
        ax.add_patch(Rectangle((x - 0.4, 0.2), 0.8, cost * 0.22, facecolor=c, alpha=0.65, edgecolor=C_EDGE))
    # 谱系箭头
    ax.annotate("", xy=(10.6, 3.35), xytext=(0.4, 3.35),
                arrowprops=dict(arrowstyle="->", color="#555", lw=2))
    ax.text(5.5, 3.6, "约束越来越强 →  插入的屏障越来越重 →  越来越慢", ha="center",
            fontsize=11, color="#555", weight="bold")
    ax.text(0.2, 0.55, "运行\n开销", ha="center", fontsize=9, color="#555")
    ax.set_xlim(-0.3, 11); ax.set_ylim(0, 3.95); ax.axis("off")
    ax.set_title("六种 memory_order：从最弱(relaxed)到最强(seq_cst)，强度与开销同向递增",
                 fontsize=13, weight="bold")
    _save(fig, "memorder-2-spectrum.png")


# ── 图3：relaxed 够不够用——计数器 vs 发布标志 ─────────────────────
def fig3_relaxed():
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.3))
    # 左：relaxed 够用的场景——纯计数
    ax = axes[0]
    ax.add_patch(FancyBboxPatch((0.2, 0.2), 4.6, 3.4, boxstyle="round,pad=0.02",
                                facecolor="#e3f9e5", edgecolor=C_R, lw=2))
    ax.text(2.5, 3.25, "[可以用 relaxed]", ha="center", fontsize=12, weight="bold", color="#2ca02c")
    ax.text(2.5, 2.7, "多线程只是各自累加一个计数器：", ha="center", fontsize=10)
    _box(ax, 2.5, 2.05, "cnt.fetch_add(1, relaxed)", C_R, w=4.0, h=0.55, fs=10)
    ax.text(2.5, 1.25, "只关心「最终加够了没」，\n不关心谁先谁后、不依赖别的变量。\n要的只是原子性 → relaxed 最省。",
            ha="center", fontsize=9.6, color="#2f5d3a")
    ax.set_xlim(0, 5); ax.set_ylim(0, 3.7); ax.axis("off")
    # 右：relaxed 不够的场景——发布数据
    ax = axes[1]
    ax.add_patch(FancyBboxPatch((0.2, 0.2), 4.6, 3.4, boxstyle="round,pad=0.02",
                                facecolor="#ffe3e3", edgecolor=C_W, lw=2))
    ax.text(2.5, 3.25, "[不能用 relaxed]", ha="center", fontsize=12, weight="bold", color=C_W)
    ax.text(2.5, 2.7, "用一个标志位「发布」另一块数据：", ha="center", fontsize=10)
    _box(ax, 2.5, 2.05, "data=42; ready.store(1, relaxed)", C_W, w=4.4, h=0.55, fs=9)
    ax.text(2.5, 1.2, "relaxed 不约束跨变量顺序，消费者\n可能先看到 ready==1 才看到 data。\n必须 release/acquire 才能挂钩两者。",
            ha="center", fontsize=9.6, color="#7a2020")
    ax.set_xlim(0, 5); ax.set_ylim(0, 3.7); ax.axis("off")
    fig.suptitle("relaxed 只买「原子性」，不买「顺序」——能否用它，取决于你是否依赖别的变量",
                 fontsize=12.8, weight="bold", y=1.02)
    fig.tight_layout()
    _save(fig, "memorder-3-relaxed.png")


# ── 图4：release/acquire 同步边 + happens-before ────────────────────
def fig4_acqrel():
    fig, ax = plt.subplots(figsize=(10, 5)
    )
    px, cx = 2.0, 7.5
    ax.text(px, 4.7, "生产者线程", ha="center", fontsize=12, weight="bold", color=C_W)
    ax.text(cx, 4.7, "消费者线程", ha="center", fontsize=12, weight="bold", color=C_R)
    _box(ax, px, 3.8, "① data = 42  (普通写)", C_W, w=3.4, fs=9.5)
    _box(ax, px, 2.7, "② ready.store(1, release)", C_W, w=3.4, fs=9.5)
    _box(ax, cx, 2.7, "③ while(ready.load(acquire)==0)", C_R, w=3.6, fs=9)
    _box(ax, cx, 1.6, "④ 读到 ready==1", C_R, w=3.4, fs=9.5)
    _box(ax, cx, 0.5, "⑤ 读 data —— 保证是 42", C_R, w=3.4, fs=9.5)
    ax.annotate("", xy=(px, 3.12), xytext=(px, 3.48), arrowprops=dict(arrowstyle="->", color=C_W, lw=1.8))
    ax.annotate("", xy=(cx, 1.92), xytext=(cx, 2.38), arrowprops=dict(arrowstyle="->", color=C_R, lw=1.8))
    ax.annotate("", xy=(cx, 0.82), xytext=(cx, 1.28), arrowprops=dict(arrowstyle="->", color=C_R, lw=1.8))
    # 同步边
    ax.annotate("", xy=(cx - 1.8, 2.7), xytext=(px + 1.7, 2.7),
                arrowprops=dict(arrowstyle="->", color=C_SYNC, lw=2.5, connectionstyle="arc3,rad=-0.15"))
    ax.text(4.75, 3.15, "release → acquire 同步边", ha="center", fontsize=10.5, color=C_SYNC, weight="bold")
    ax.add_patch(FancyBboxPatch((0.1, -0.75), 9.4, 0.72, boxstyle="round,pad=0.02",
                                facecolor=C_HL, edgecolor="#e0a800", lw=1.5))
    ax.text(4.8, -0.39,
            "happens-before：消费者 acquire 读到 release 发布的值，则 release 之前的全部写(①)对它可见",
            ha="center", va="center", fontsize=9.8, color="#664d03", weight="bold")
    ax.set_xlim(-0.2, 9.7); ax.set_ylim(-1.0, 5.1); ax.axis("off")
    ax.set_title("release/acquire：建立跨线程「同步边」，最轻地保证「先写好，再发布」",
                 fontsize=12.5, weight="bold")
    _save(fig, "memorder-4-acqrel.png")


# ── 图5：seq_cst 全局总序 vs acq/rel 无全局总序（IRIW 经典反例）───────
def fig5_seqcst():
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.6))
    # 左：acq/rel 下，两个读者可能看到相反顺序
    ax = axes[0]
    ax.text(2.5, 4.3, "release/acquire", ha="center", fontsize=12, weight="bold", color="#4C78A8")
    _box(ax, 1.2, 3.5, "T1: x=1\n(release)", C_W, w=1.7, h=0.75, fs=8.5)
    _box(ax, 3.8, 3.5, "T2: y=1\n(release)", C_R, w=1.7, h=0.75, fs=8.5)
    _box(ax, 1.2, 2.0, "T3 看到:\nx=1, y=0", "#888", w=1.7, h=0.75, fs=8.5)
    _box(ax, 3.8, 2.0, "T4 看到:\ny=1, x=0", "#888", w=1.7, h=0.75, fs=8.5)
    ax.text(2.5, 0.95, "两个读者对「x、y 谁先发生」\n给出相反结论 —— 允许！\n没有全局统一的总顺序。",
            ha="center", fontsize=9.5, color="#7a2020", weight="bold")
    ax.set_xlim(0, 5); ax.set_ylim(0.4, 4.7); ax.axis("off")
    # 右：seq_cst 下，所有线程看到同一个全局总序
    ax = axes[1]
    ax.text(2.5, 4.3, "seq_cst", ha="center", fontsize=12, weight="bold", color=C_W)
    _box(ax, 2.5, 3.5, "全局单一总序：x=1  →  y=1", C_W, w=4.2, h=0.6, fs=9.5)
    _box(ax, 1.2, 2.0, "T3 看到:\n与总序一致", "#2ca02c", w=1.7, h=0.75, fs=8.5)
    _box(ax, 3.8, 2.0, "T4 看到:\n与总序一致", "#2ca02c", w=1.7, h=0.75, fs=8.5)
    ax.text(2.5, 0.95, "所有线程被强制看到\n同一个先后顺序 —— 直觉最简单，\n但要插最重的屏障，最慢。",
            ha="center", fontsize=9.5, color="#2f5d3a", weight="bold")
    ax.set_xlim(0, 5); ax.set_ylim(0.4, 4.7); ax.axis("off")
    fig.suptitle("seq_cst 的「贵」买的是什么：一个所有线程公认的全局总序（acq/rel 给不了这个）",
                 fontsize=12.5, weight="bold", y=1.02)
    fig.tight_layout()
    _save(fig, "memorder-5-seqcst.png")


if __name__ == "__main__":
    fig1_reorder()
    fig2_spectrum()
    fig3_relaxed()
    fig4_acqrel()
    fig5_seqcst()
    print("ALL DONE")
