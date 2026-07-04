#!/usr/bin/env python3
"""生成「虚拟内存·页·页表·换页」课时配图。画机制本身，不做拟人类比。
输出到 ../assets/paging-*.png，DPI 150，白底。"""
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
C_USED = "#4C78A8"
C_HL = "#fff3cd"
C_ORANGE = "#d08770"


def _save(fig, name):
    p = OUT / name
    fig.savefig(p, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("saved", p)


# ── 图1：虚拟地址空间 → 页表 → 物理内存的映射 ──────────────────────
def fig1_vm_mapping():
    fig, ax = plt.subplots(figsize=(9.6, 5.4))
    # 左：虚拟地址空间（每个进程独立、连续）
    ax.text(1.4, 5.35, "进程看到的\n虚拟地址空间", ha="center", fontsize=10.5, weight="bold", color=C_BLUE)
    vlabels = ["代码 .text", "数据 .data", "堆 heap↓", "(未映射)", "栈 stack↑"]
    vcolors = [C_USED, C_USED, C_USED, C_FREE, C_USED]
    for i, (t, c) in enumerate(zip(vlabels, vcolors)):
        y = 4.4 - i * 0.78
        ax.add_patch(Rectangle((0.5, y), 1.8, 0.7, facecolor=c, edgecolor=C_EDGE, lw=1.5))
        ax.text(1.4, y + 0.35, t, ha="center", va="center", fontsize=9,
                color="white" if c == C_USED else "#999")
    # 中：页表（虚拟页号 → 物理页帧号）
    ax.add_patch(FancyBboxPatch((4.0, 0.9), 2.0, 3.9, boxstyle="round,pad=0.03",
                                facecolor="#eef2ff", edgecolor=C_BLUE, lw=2))
    ax.text(5.0, 4.55, "页表\n(每进程一份)", ha="center", fontsize=10, weight="bold", color=C_BLUE)
    rows = [("VPN 0", "PFN 7"), ("VPN 1", "PFN 3"), ("VPN 2", "PFN 9"),
            ("VPN 3", "缺失", ), ("VPN 4", "PFN 1")]
    vpn3_y = None
    for i, (vpn, pfn) in enumerate(rows):
        y = 3.9 - i * 0.62
        bad = pfn == "缺失"
        if bad:
            vpn3_y = y
        ax.text(4.15, y, vpn, ha="left", va="center", fontsize=8.5, color="#333")
        ax.text(5.95, y, pfn, ha="right", va="center", fontsize=8.5,
                color=C_BAD if bad else C_GOOD, weight="bold")
    # 右：物理内存（页帧，乱序、可被多进程共享）
    ax.text(8.4, 5.35, "物理内存\n(页帧 page frame)", ha="center", fontsize=10.5, weight="bold", color=C_ORANGE)
    for i in range(6):
        y = 4.4 - i * 0.62
        ax.add_patch(Rectangle((7.7, y), 1.5, 0.55, facecolor="#fdeee4", edgecolor=C_EDGE, lw=1.2))
        ax.text(8.45, y + 0.27, f"PFN {i}", ha="center", va="center", fontsize=8.5, color="#555")
    # 箭头：虚拟页 → 页表 → 物理帧
    ax.annotate("", xy=(4.0, 3.4), xytext=(2.3, 3.4),
                arrowprops=dict(arrowstyle="->", color=C_BLUE, lw=1.8))
    ax.text(3.15, 3.6, "查表翻译", ha="center", fontsize=8.5, color=C_BLUE)
    ax.annotate("", xy=(7.7, 2.9), xytext=(6.0, 3.6),
                arrowprops=dict(arrowstyle="->", color=C_GOOD, lw=1.8))
    ax.text(6.9, 3.55, "命中→物理帧", ha="center", fontsize=8, color=C_GOOD)
    ax.annotate("VPN3 无映射\n→ 缺页异常", xy=(5.98, vpn3_y), xytext=(7.0, 1.2),
                ha="center", fontsize=8.5, color=C_BAD, weight="bold",
                arrowprops=dict(arrowstyle="->", color=C_BAD, lw=1.6))
    ax.text(4.9, 0.25,
            "关键：虚拟地址「连续、每进程独立」，物理帧「乱序、可空缺、可共享」。页表就是两者之间的翻译字典。",
            ha="center", fontsize=9.5, color="#333", weight="bold")
    ax.set_xlim(0, 9.8); ax.set_ylim(0, 5.7); ax.axis("off")
    ax.set_title("虚拟内存：每个进程都以为自己独占一整块连续内存，页表把它翻译到零散的物理帧",
                 fontsize=12, weight="bold")
    _save(fig, "paging-1-vm-mapping.png")


# ── 图2：一个虚拟地址如何被拆开走四级页表 ──────────────────────────
def fig2_pagewalk():
    fig, ax = plt.subplots(figsize=(9.8, 5.2))
    # 顶部：48位虚拟地址被切成 9+9+9+9+12
    ax.text(4.9, 4.85, "一个 64 位虚拟地址（实际用低 48 位）被硬件切成 5 段", ha="center", fontsize=11, weight="bold")
    segs = [("PGD\n9bit", C_BLUE), ("PUD\n9bit", C_BLUE), ("PMD\n9bit", C_BLUE),
            ("PTE\n9bit", C_BLUE), ("页内偏移\n12bit", C_ORANGE)]
    x = 0.6
    ws = [1.55, 1.55, 1.55, 1.55, 2.0]
    xc = []
    for (t, c), w in zip(segs, ws):
        ax.add_patch(Rectangle((x, 3.9), w, 0.65, facecolor="white", edgecolor=c, lw=2))
        ax.text(x + w/2, 4.22, t, ha="center", va="center", fontsize=9, color=c, weight="bold")
        xc.append(x + w/2)
        x += w + 0.05
    # 四级级联查表
    levels = [("① CR3 指向\nPGD 顶级表", xc[0]),
              ("② PGD项指向\nPUD 表", xc[1]),
              ("③ PUD项指向\nPMD 表", xc[2]),
              ("④ PMD项指向\nPTE 表", xc[3])]
    for i, (t, x0) in enumerate(levels):
        y = 2.9
        ax.add_patch(FancyBboxPatch((x0-0.8, y-0.45), 1.6, 0.9, boxstyle="round,pad=0.02",
                                    facecolor="#eef2ff", edgecolor=C_BLUE, lw=1.6))
        ax.text(x0, y, t, ha="center", va="center", fontsize=8, color="#222")
        ax.annotate("", xy=(x0, 3.4), xytext=(x0, 3.85),
                    arrowprops=dict(arrowstyle="->", color=C_BLUE, lw=1.5))
        if i < 3:
            ax.annotate("", xy=(xc[i+1], 2.9), xytext=(x0+0.8, 2.9),
                        arrowprops=dict(arrowstyle="->", color="#888", lw=1.3))
    # 最终：PTE 里的物理帧号 + 偏移 = 物理地址
    ax.add_patch(FancyBboxPatch((xc[3]-0.8, 1.35-0.45), 1.6, 0.9, boxstyle="round,pad=0.02",
                                facecolor="#e3f9e5", edgecolor=C_GOOD, lw=1.8))
    ax.text(xc[3], 1.35, "⑤ PTE 给出\n物理帧号 PFN", ha="center", va="center", fontsize=8, color="#222")
    ax.annotate("", xy=(xc[3], 1.85), xytext=(xc[3], 2.42),
                arrowprops=dict(arrowstyle="->", color=C_BLUE, lw=1.5))
    # 偏移直接拼上
    ax.add_patch(FancyBboxPatch((xc[4]-0.95, 1.35-0.45), 1.9, 0.9, boxstyle="round,pad=0.02",
                                facecolor="#fdeee4", edgecolor=C_ORANGE, lw=1.8))
    ax.text(xc[4], 1.35, "页内偏移\n(不翻译,直接拼)", ha="center", va="center", fontsize=8, color="#222")
    ax.annotate("", xy=(xc[4], 1.85), xytext=(xc[4], 3.85),
                arrowprops=dict(arrowstyle="->", color=C_ORANGE, lw=1.5, ls="--"))
    # 物理地址（放在 PFN 框 xc[3] 与 偏移框 xc[4] 正下方之间，两箭头竖直下汇不交叉）
    pa_l, pa_r = 5.2, 9.0
    ax.add_patch(Rectangle((pa_l, 0.2), pa_r - pa_l, 0.62, facecolor=C_GOOD, edgecolor=C_EDGE, lw=1.5))
    ax.text((pa_l + pa_r) / 2, 0.51, "物理地址 = PFN × 4KB + 页内偏移", ha="center", va="center",
            fontsize=9.5, color="white", weight="bold")
    # PFN(xc[3]) 竖直下汇框顶部左侧；偏移(xc[4]) 竖直下汇框顶部右侧，互不横穿
    ax.annotate("", xy=(xc[3], 0.82), xytext=(xc[3], 0.9),
                arrowprops=dict(arrowstyle="->", color=C_GOOD, lw=1.4))
    ax.annotate("", xy=(xc[4], 0.82), xytext=(xc[4], 1.85),
                arrowprops=dict(arrowstyle="->", color=C_ORANGE, lw=1.4))
    ax.text(9.0, 2.9, "一次翻译\n= 4 次访存\n(每级读一次内存)", ha="center", fontsize=9,
            color=C_BAD, weight="bold")
    ax.set_xlim(0, 10.2); ax.set_ylim(0, 5.2); ax.axis("off")
    ax.set_title("四级页表：一次「虚拟→物理」翻译背后是 4 次串行内存访问（这就是为什么要 TLB 缓存它）",
                 fontsize=11.5, weight="bold")
    _save(fig, "paging-2-pagewalk.png")


# ── 图3：TLB 命中 vs 未命中的两条路 ────────────────────────────────
def fig3_tlb():
    fig, ax = plt.subplots(figsize=(9.6, 4.8))
    ax.add_patch(FancyBboxPatch((3.9, 3.9), 2.0, 0.7, boxstyle="round,pad=0.02",
                                facecolor=C_HL, edgecolor=C_EDGE, lw=2))
    ax.text(4.9, 4.25, "CPU 要访问虚拟地址", ha="center", va="center", fontsize=10.5, weight="bold")
    # TLB 查询
    ax.add_patch(FancyBboxPatch((3.7, 2.7), 2.4, 0.8, boxstyle="round,pad=0.02",
                                facecolor="#eef2ff", edgecolor=C_BLUE, lw=2))
    ax.text(4.9, 3.1, "查 TLB\n(页表项的高速缓存)", ha="center", va="center", fontsize=9.5, weight="bold", color=C_BLUE)
    ax.annotate("", xy=(4.9, 3.5), xytext=(4.9, 3.9), arrowprops=dict(arrowstyle="->", color=C_EDGE, lw=1.6))
    # 命中路
    ax.add_patch(FancyBboxPatch((0.6, 1.3), 3.3, 1.0, boxstyle="round,pad=0.02",
                                facecolor="#e3f9e5", edgecolor=C_GOOD, lw=2))
    ax.text(2.25, 1.8, "TLB 命中\n直接拿到物理帧号\n~1 个时钟周期", ha="center", va="center", fontsize=9.5, color="#222", weight="bold")
    ax.annotate("命中(绝大多数)", xy=(2.25, 2.3), xytext=(3.4, 2.75),
                ha="center", fontsize=9, color=C_GOOD, weight="bold",
                arrowprops=dict(arrowstyle="->", color=C_GOOD, lw=1.8))
    # 未命中路
    ax.add_patch(FancyBboxPatch((6.0, 1.3), 3.4, 1.0, boxstyle="round,pad=0.02",
                                facecolor="#fdeee4", edgecolor=C_BAD, lw=2))
    ax.text(7.7, 1.8, "TLB 未命中(TLB miss)\n走四级页表 page walk\n~4次访存 数十~上百 ns", ha="center", va="center", fontsize=9.5, color="#222", weight="bold")
    ax.annotate("未命中", xy=(7.7, 2.3), xytext=(6.4, 2.75),
                ha="center", fontsize=9, color=C_BAD, weight="bold",
                arrowprops=dict(arrowstyle="->", color=C_BAD, lw=1.8))
    # 回填
    ax.annotate("翻完把结果填回 TLB", xy=(4.0, 1.8), xytext=(6.0, 1.05),
                ha="center", fontsize=8.5, color="#888",
                arrowprops=dict(arrowstyle="->", color="#aaa", lw=1.2, ls="--"))
    ax.text(4.9, 0.35,
            "TLB reach = TLB项数 × 页大小。工作集一旦超过 TLB reach，就频繁 miss、频繁 page walk → 访存变慢。\n"
            "这正是 HugePages 的价值：2MB 大页让同样的 TLB 项数覆盖 512 倍的内存（下一张实测图看阶梯）。",
            ha="center", fontsize=9.5, color="#333", weight="bold")
    ax.set_xlim(0, 10); ax.set_ylim(0, 4.8); ax.axis("off")
    ax.set_title("TLB：页表翻译的高速缓存。命中≈免费，未命中要重走四级页表", fontsize=12, weight="bold")
    _save(fig, "paging-3-tlb.png")


# ── 图4：本机实测 —— 访存延迟随工作集的阶梯（cache + TLB reach）────
def fig4_measured():
    # 本机 bench_tlb.cpp 实测数据（Apple Silicon）
    kb = np.array([16, 64, 256, 1024, 4096, 16384, 65536, 262144])  # workset KB
    ns = np.array([2.040, 1.362, 5.179, 4.949, 7.119, 12.991, 78.843, 94.018])
    fig, ax = plt.subplots(figsize=(9.2, 4.6))
    ax.plot(kb, ns, "-o", color=C_BLUE, lw=2, markersize=7, label="指针追逐 单次访存延迟(本机实测)")
    ax.set_xscale("log", base=2)
    ax.set_xticks(kb)
    ax.set_xticklabels(["16K","64K","256K","1M","4M","16M","64M","256M"])
    for x, y in zip(kb, ns):
        ax.annotate(f"{y:.0f}ns", (x, y), textcoords="offset points", xytext=(0, 9),
                    ha="center", fontsize=8.5, color="#333")
    # 标注关键阶梯
    ax.annotate("16M→64M：13ns 陡增到 79ns（6倍）\n同时越过 LLC 容量 + TLB reach\n→ 每次访存都要重走页表",
                xy=(65536, 78.8), xytext=(2000, 62),
                fontsize=9.5, color=C_BAD, weight="bold", ha="left",
                arrowprops=dict(arrowstyle="->", color=C_BAD, lw=1.8))
    ax.annotate("小工作集：全落 L1/L2\n1~7ns", xy=(64, 1.36), xytext=(30, 22),
                fontsize=9, color=C_GOOD, weight="bold", ha="center",
                arrowprops=dict(arrowstyle="->", color=C_GOOD, lw=1.5))
    ax.set_xlabel("工作集大小（对数轴）", fontsize=11)
    ax.set_ylabel("单次随机访存延迟 (ns)", fontsize=11)
    ax.set_title("本机实测：工作集越过 cache 与 TLB reach，访存延迟阶梯式抬升", fontsize=12, weight="bold")
    ax.grid(True, which="both", alpha=0.25)
    ax.legend(fontsize=9.5, loc="upper left")
    ax.set_ylim(0, 105)
    _save(fig, "paging-4-measured.png")


# ── 图5：demand paging + 换页(swap) 全流程状态机 ────────────────────
def fig5_swap():
    fig, ax = plt.subplots(figsize=(9.8, 5.2))
    def box(x, y, w, h, t, ec, fc="white", fs=9.5):
        ax.add_patch(FancyBboxPatch((x-w/2, y-h/2), w, h, boxstyle="round,pad=0.02",
                                    facecolor=fc, edgecolor=ec, lw=1.8))
        ax.text(x, y, t, ha="center", va="center", fontsize=fs, color="#222")
    box(2.0, 4.6, 3.2, 0.7, "mmap/malloc 申请一段内存", C_BLUE, "#eef2ff", 10)
    ax.text(2.0, 4.05, "只登记「虚拟地址→合法」，还没给物理页", ha="center", fontsize=8.5, color="#888")
    box(2.0, 3.2, 3.2, 0.7, "首次访问该页", C_EDGE, C_HL, 10)
    ax.annotate("", xy=(2.0, 3.55), xytext=(2.0, 4.25), arrowprops=dict(arrowstyle="->", color=C_EDGE, lw=1.6))
    # 分叉：页表里有没有映射
    box(2.0, 1.9, 3.4, 0.85, "查页表：这页在物理内存里吗？", C_EDGE, "white", 9.5)
    ax.annotate("", xy=(2.0, 2.32), xytext=(2.0, 2.85), arrowprops=dict(arrowstyle="->", color=C_EDGE, lw=1.6))
    # minor fault（判定框 → minor 框，向右上分叉）
    box(6.4, 3.3, 3.6, 1.0, "minor fault（次缺页）\n页在内存/可共享，只差建映射\n内核填页表项 · 微秒级", C_ORANGE, "#fdeee4", 9)
    ax.annotate("", xy=(4.6, 3.1), xytext=(3.7, 2.05),
                arrowprops=dict(arrowstyle="->", color=C_ORANGE, lw=1.8))
    ax.text(4.05, 2.75, "命中/COW共享", ha="center", fontsize=8.2, color=C_ORANGE, weight="bold")
    # major fault（判定框 → major 框，向右下分叉）
    box(6.4, 1.35, 3.6, 1.0, "major fault（主缺页）\n页被换出到 swap 磁盘\n要从磁盘读回 · 毫秒级!", C_BAD, "#ffe3e3", 9)
    ax.annotate("", xy=(4.6, 1.35), xytext=(3.7, 1.75),
                arrowprops=dict(arrowstyle="->", color=C_BAD, lw=1.8))
    ax.text(4.15, 1.12, "被swap换出了", ha="center", fontsize=8.2, color=C_BAD, weight="bold")
    # 换页方向说明
    ax.annotate("内存紧张时\n内核换出冷页(page-out)", xy=(6.4, 0.85), xytext=(6.4, 0.25),
                ha="center", fontsize=8.5, color=C_BAD,
                arrowprops=dict(arrowstyle="->", color=C_BAD, lw=1.4, ls="--"))
    ax.text(4.9, 4.95,
            "「申请内存」≠「拿到物理页」：物理页要等首次访问时惰性分配(demand paging)",
            ha="center", fontsize=10.5, weight="bold", color="#333")
    ax.text(2.0, 0.5, "交易系统对策：\n启动预热(消 minor)\n+ mlockall(消 major)\n= 运行期零缺页",
            ha="center", fontsize=9, color=C_GOOD, weight="bold")
    ax.set_xlim(0, 9.8); ax.set_ylim(0, 5.3); ax.axis("off")
    ax.set_title("申请内存 → 缺页 → 换页 的完整生命周期：两种缺页，代价差三个数量级", fontsize=11.5, weight="bold")
    _save(fig, "paging-5-swap.png")


if __name__ == "__main__":
    fig1_vm_mapping()
    fig2_pagewalk()
    fig3_tlb()
    fig4_measured()
    fig5_swap()
    print("ALL DONE")
