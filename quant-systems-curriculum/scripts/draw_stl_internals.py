#!/usr/bin/env python3
"""生成「STL 内部实现」课时配图（4 张）。直接画机制本身。
性能数字来自本机实测（bench_stl.cpp）。输出到 ../assets/stl-*.png，DPI 150，白底。
避免 µ/✓/✗ 缺字形字符。"""
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
C_BLUE = "#1f77b4"
C_RED = "#d62728"
C_GREEN = "#2ca02c"
C_PURPLE = "#7048e8"
C_GREY = "#888"
C_BOX = "white"


def _save(fig, name):
    p = OUT / name
    fig.savefig(p, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("saved", p)


# ── 图1：vector 成倍扩容 ──────────────────────────────────
def fig1_vector_growth():
    fig, ax = plt.subplots(figsize=(10.5, 4.6))
    caps = [1, 2, 4, 8, 16, 32, 64, 128]
    x = 0.3
    maxcap = caps[-1]
    scale = 8.5 / maxcap
    for i, c in enumerate(caps):
        w = c * scale
        # 已用部分（深）+ 预留部分（浅）
        used = max(1, c // 2) if i > 0 else 1
        ax.add_patch(Rectangle((x, 4.0 - i*0.46), w, 0.34,
                               facecolor="#d6e4ff", edgecolor=C_BLUE, lw=1.2))
        ax.text(x + w + 0.12, 4.0 - i*0.46 + 0.17, f"capacity={c}",
                va="center", fontsize=9.5, color=C_BLUE)
        if i > 0:
            ax.text(x - 0.05, 4.0 - i*0.46 + 0.17, "2x", ha="right", va="center",
                    fontsize=8.5, color=C_RED, weight="bold")
    ax.annotate("", xy=(x-0.15, 4.0 - 7*0.46 + 0.17), xytext=(x-0.15, 4.0 + 0.17),
                arrowprops=dict(arrowstyle="->", color=C_RED, lw=1.6))
    ax.text(0.3, 0.55, "每次扩容容量翻倍 → 插入 N 个元素总搬迁 1+2+4+...+N ≈ 2N = O(N)",
            fontsize=10.5, color=C_EDGE, weight="bold")
    ax.text(0.3, 0.15, "均摊到每次 push_back 是 O(1)。本机 libc++ 实测因子 = 2.00x（MSVC 用 1.5x）",
            fontsize=10, color=C_GREY)
    ax.set_xlim(0, 10.5); ax.set_ylim(0, 4.6); ax.axis("off")
    fig.suptitle("vector 成倍扩容：容量按 2 的幂跳，搬迁次数对数级（本机 libc++ 实测 2x）",
                 fontsize=12.5, weight="bold", y=1.0)
    fig.tight_layout()
    _save(fig, "stl-1-vector-growth.png")


# ── 图2：链地址 vs 开放寻址 内存布局 ──────────────────────
def fig2_hashmap_layout():
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.0))
    # 左：unordered_map 链地址法
    ax = axes[0]
    # 桶数组
    for i in range(5):
        ax.add_patch(Rectangle((0.5, 3.6 - i*0.55), 0.7, 0.45,
                               facecolor="#eee", edgecolor=C_EDGE, lw=1.2))
        ax.text(0.85, 3.6 - i*0.55 + 0.22, f"[{i}]", ha="center", va="center", fontsize=8.5)
    ax.text(0.85, 4.25, "桶数组", ha="center", fontsize=9.5, color=C_EDGE)
    # 散落堆上的节点（不同位置，体现散落）
    nodes = [(2.6, 3.7), (4.0, 2.9), (2.9, 2.1), (4.2, 3.5), (3.3, 1.3)]
    bucket_y = [3.6, 3.05, 2.5, 3.6, 1.95]
    for (nx, ny), by in zip(nodes, bucket_y):
        ax.add_patch(FancyBboxPatch((nx, ny), 0.95, 0.4, boxstyle="round,pad=0.02",
                                    facecolor="#ffe3e3", edgecolor=C_RED, lw=1.3))
        ax.text(nx+0.47, ny+0.2, "node", ha="center", va="center", fontsize=8, color=C_RED)
        ax.annotate("", xy=(nx, ny+0.2), xytext=(1.2, by+0.05),
                    arrowprops=dict(arrowstyle="->", color=C_GREY, lw=1.0,
                                    connectionstyle="arc3,rad=0.1"))
    ax.text(3.3, 0.6, "每个键值对 = 单独 new 的节点\n散落堆上 → 指针追逐 → cache miss\ninsert 一次 = 一次 malloc",
            ha="center", fontsize=9.5, color=C_RED, weight="bold")
    ax.set_title("std::unordered_map（链地址法）", fontsize=11, weight="bold", color=C_RED)
    ax.set_xlim(0, 5.5); ax.set_ylim(0.2, 4.6); ax.axis("off")
    # 右：开放寻址扁平哈希
    ax = axes[1]
    cells = ["k3", "", "k1", "k7", "", "k2", "k9", ""]
    for i, c in enumerate(cells):
        fc = "#e3fbe3" if c else "white"
        ax.add_patch(Rectangle((0.6, 3.9 - i*0.42), 3.2, 0.38,
                               facecolor=fc, edgecolor=C_GREEN, lw=1.3))
        if c:
            ax.text(2.2, 3.9 - i*0.42 + 0.19, f"{c} | val", ha="center", va="center",
                    fontsize=9, color=C_GREEN)
        else:
            ax.text(2.2, 3.9 - i*0.42 + 0.19, "(空槽)", ha="center", va="center",
                    fontsize=8.5, color=C_GREY)
    ax.text(2.2, 4.4, "一整块连续内存", ha="center", fontsize=9.5, color=C_GREEN)
    ax.text(2.2, 0.55, "所有键值对压在连续一块\n冲突时探测相邻槽 → cache 行内命中\n零逐节点分配",
            ha="center", fontsize=9.5, color=C_GREEN, weight="bold")
    ax.set_title("开放寻址扁平哈希（F14 / abseil flat_hash_map）", fontsize=11, weight="bold", color=C_GREEN)
    ax.set_xlim(0, 4.4); ax.set_ylim(0.2, 4.7); ax.axis("off")
    fig.suptitle("哈希表内存布局：节点散落（链地址）vs 连续一块（开放寻址）",
                 fontsize=13, weight="bold", y=1.01)
    fig.tight_layout()
    _save(fig, "stl-2-hashmap-layout.png")


# ── 图3：实测三方查找延迟（真实数据）──────────────────────
def fig3_lookup_measured():
    names = ["sorted-vector\n二分", "std::unordered_map\n(链地址)", "开放寻址\n扁平哈希(自研)"]
    ns = [45.1, 18.8, 8.4]
    colors = [C_GREY, C_RED, C_GREEN]
    fig, ax = plt.subplots(figsize=(9.5, 5.0))
    xs = np.arange(len(names))
    bars = ax.bar(xs, ns, color=colors, edgecolor=C_EDGE, lw=1.0, width=0.55, zorder=3)
    for x, v in zip(xs, ns):
        ax.text(x, v + 0.8, f"{v:.1f} ns", ha="center", fontsize=11.5, weight="bold",
                color=C_EDGE)
    ax.set_xticks(xs)
    ax.set_xticklabels(names, fontsize=10.5)
    ax.set_ylabel("单次查找延迟（纳秒，越低越好）", fontsize=11)
    ax.set_ylim(0, 56)
    ax.grid(axis="y", ls="--", alpha=0.4, zorder=0)
    # 关键注解
    ax.text(1, 28, "并不慢！\n比二分快一倍多", ha="center", fontsize=9.8, color=C_RED, weight="bold")
    ax.text(2, 18, "最快\n比 unordered_map\n再快 2.2×", ha="center", fontsize=9.8, color=C_GREEN, weight="bold")
    ax.text(0, 51.5, "连续但跳跃访问 cache 不友好", ha="center", fontsize=9.2, color=C_GREY)
    ax.set_title("本机实测：100万键随机查找1000万次（关键：unordered_map 不是慢，是分配+cache 不连续）",
                 fontsize=11, weight="bold")
    fig.tight_layout()
    _save(fig, "stl-3-lookup-measured.png")


# ── 图4：迭代器失效规则 ──────────────────────────────────
def fig4_invalidation():
    fig, ax = plt.subplots(figsize=(11, 5.2))
    rows = [
        ("vector", "扩容(push_back触发realloc)", "全部失效", C_RED),
        ("vector", "erase 中间元素", "删除点及之后失效", C_RED),
        ("deque", "头尾以外插入/删除", "迭代器全失效", C_RED),
        ("list / forward_list", "任意插入", "都不失效", C_GREEN),
        ("list", "erase", "仅被删元素失效", C_GREEN),
        ("unordered_map", "rehash(insert触发)", "迭代器失效, 但指针/引用不失效", C_PURPLE),
        ("map / set (红黑树)", "insert", "不失效; erase 仅删除点", C_GREEN),
    ]
    y0 = 4.5
    dh = 0.58
    # 表头
    ax.text(1.2, y0+0.45, "容器", fontsize=10.5, weight="bold", color=C_EDGE)
    ax.text(4.2, y0+0.45, "触发操作", fontsize=10.5, weight="bold", color=C_EDGE)
    ax.text(8.2, y0+0.45, "失效范围", fontsize=10.5, weight="bold", color=C_EDGE)
    ax.plot([0.3, 10.7], [y0+0.25, y0+0.25], color=C_EDGE, lw=1.2)
    for i, (cont, op, eff, col) in enumerate(rows):
        y = y0 - i*dh
        if i % 2 == 0:
            ax.add_patch(Rectangle((0.3, y-0.24), 10.4, dh*0.92, facecolor="#f5f5f5",
                                   edgecolor="none", zorder=0))
        ax.text(0.45, y, cont, fontsize=9.8, color=C_EDGE, va="center")
        ax.text(3.6, y, op, fontsize=9.5, color=C_GREY, va="center")
        ax.text(7.4, y, eff, fontsize=9.5, color=col, va="center", weight="bold")
    ax.text(5.5, y0 - 7*dh - 0.1,
            "记牢三条: vector 扩容全失效 ｜ list 只失效被删的 ｜ unordered_map rehash 后指针仍有效",
            ha="center", fontsize=9.8, color=C_EDGE, weight="bold")
    ax.set_xlim(0, 11); ax.set_ylim(y0 - 7*dh - 0.5, y0 + 0.9); ax.axis("off")
    fig.suptitle("迭代器失效规则：偶发、难复现的一类 bug，规则必须背准",
                 fontsize=12.5, weight="bold", y=1.0)
    fig.tight_layout()
    _save(fig, "stl-4-invalidation.png")


if __name__ == "__main__":
    fig1_vector_growth()
    fig2_hashmap_layout()
    fig3_lookup_measured()
    fig4_invalidation()
    print("ALL DONE")
