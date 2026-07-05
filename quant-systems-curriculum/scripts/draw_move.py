#!/usr/bin/env python3
"""生成「移动语义」课时配图（3 张）。画机制本身，不做拟人类比。
输出到 ../assets/move-*.png，DPI 150，白底。"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.patches import FancyBboxPatch, Rectangle
import numpy as np
from pathlib import Path

plt.rcParams["font.sans-serif"] = ["Hiragino Sans GB", "Songti SC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

OUT = Path(__file__).resolve().parents[1] / "assets"
OUT.mkdir(exist_ok=True)

C_EDGE = "#3b4252"; C_BAD = "#d62728"; C_GOOD = "#2ca02c"
C_BLUE = "#4C78A8"; C_ORANGE = "#d08770"; C_PRIV = "#eef2ff"; C_SHARE = "#e3f9e5"


def _save(fig, name):
    p = OUT / name
    fig.savefig(p, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig); print("saved", p)


# ── 图1：拷贝(深拷贝) vs 移动(偷指针) 的机制对比 ────────────────────
def fig1_copy_vs_move():
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(11.2, 4.8))

    def obj(ax, x, y, name, color, ptr_label):
        ax.add_patch(FancyBboxPatch((x, y), 2.0, 0.95, boxstyle="round,pad=0.02",
                                    facecolor="#fafbfc", edgecolor=color, lw=1.8))
        ax.text(x+1.0, y+1.08, name, ha="center", fontsize=9.5, weight="bold", color=color)
        ax.add_patch(Rectangle((x+0.15, y+0.15), 1.7, 0.55, facecolor=C_PRIV, edgecolor=C_EDGE, lw=1.2))
        ax.text(x+1.0, y+0.42, ptr_label, ha="center", va="center", fontsize=8, color="#222")
        return x+1.0, y+0.42

    def heapblk(ax, x, y, label, color):
        ax.add_patch(Rectangle((x, y), 2.6, 0.8, facecolor=color, edgecolor=C_EDGE, lw=1.5))
        ax.text(x+1.3, y+0.4, label, ha="center", va="center", fontsize=8.5, color="#222")
        return x+1.3, y+0.8

    # 左：拷贝 —— 复制一份堆数据
    axL.set_title("拷贝构造：深拷贝，复制整块堆数据", fontsize=10.5, weight="bold", color=C_BAD)
    sx, sy = obj(axL, 0.3, 3.3, "源对象 a", C_BLUE, "data 指针 →")
    dx, dy = obj(axL, 3.3, 3.3, "新对象 b", C_BLUE, "data 指针 →")
    h1x, _ = heapblk(axL, 0.3, 1.4, "堆: 4096 个 double(原)", "#dbe7f5")
    h2x, _ = heapblk(axL, 3.3, 1.4, "堆: 4096 个 double(新复制!)", "#ffe3e3")
    axL.annotate("", xy=(h1x, 2.2), xytext=(sx, sy), arrowprops=dict(arrowstyle="->", color=C_BLUE, lw=1.5))
    axL.annotate("", xy=(h2x, 2.2), xytext=(dx, dy), arrowprops=dict(arrowstyle="->", color=C_BAD, lw=1.5))
    axL.annotate("逐字节复制 4096 个 double\n(实测这类深拷贝 ≈ 15 us/次)", xy=(4.6, 1.8), xytext=(2.9, 0.5),
                 fontsize=8.5, color=C_BAD, weight="bold", ha="center",
                 arrowprops=dict(arrowstyle="->", color=C_BAD, lw=1.4))
    axL.text(3.0, 4.55, "a 仍有效，b 是独立副本", ha="center", fontsize=8.5, color="#555")
    axL.set_xlim(0, 6.2); axL.set_ylim(0.2, 4.8); axL.axis("off")

    # 右：移动 —— 偷指针，不复制堆
    axR.set_title("移动构造：偷指针，堆数据一个字节都不动", fontsize=10.5, weight="bold", color=C_GOOD)
    sx2, sy2 = obj(axR, 0.3, 3.3, "源对象 a(将失效)", C_ORANGE, "data = nullptr")
    dx2, dy2 = obj(axR, 3.3, 3.3, "新对象 b", C_GOOD, "data 指针 →")
    hx, _ = heapblk(axR, 1.8, 1.4, "堆: 4096 个 double(原封不动)", C_SHARE)
    axR.annotate("", xy=(hx-0.3, 2.2), xytext=(dx2, dy2), arrowprops=dict(arrowstyle="->", color=C_GOOD, lw=1.8))
    axR.annotate("指针所有权从 a 交给 b\n(只改几个指针，实测 ≈ 10 ns/次)", xy=(2.6, 1.9), xytext=(3.2, 0.5),
                 fontsize=8.5, color=C_GOOD, weight="bold", ha="center",
                 arrowprops=dict(arrowstyle="->", color=C_GOOD, lw=1.4))
    axR.text(3.0, 4.55, "a 被掏空(置 nullptr)，b 接管原堆", ha="center", fontsize=8.5, color="#555")
    axR.set_xlim(0, 6.2); axR.set_ylim(0.2, 4.8); axR.axis("off")

    fig.suptitle("移动 vs 拷贝的本质：拷贝复制整块堆数据，移动只转移指针所有权(堆数据不动)",
                 fontsize=11.5, weight="bold", y=1.0)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    _save(fig, "move-1-copy-vs-move.png")


# ── 图2：左值/右值 与 移动的触发 ──────────────────────────────────
def fig2_value_category():
    fig, ax = plt.subplots(figsize=(10.2, 5.0))
    ax.text(5.1, 4.75, "什么时候会触发移动而不是拷贝？", ha="center", fontsize=12, weight="bold")

    def card(x, y, w, h, title, body, tc, fc):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02",
                                    facecolor=fc, edgecolor=tc, lw=1.8))
        ax.text(x+w/2, y+h-0.28, title, ha="center", fontsize=9.5, weight="bold", color=tc)
        ax.text(x+w/2, y+h/2-0.28, body, ha="center", va="center", fontsize=8.3, color="#222")

    card(0.4, 2.7, 4.4, 1.7, "左值 lvalue：有名字、能取地址",
         "HeavyObj a;\nHeavyObj b(a);        // 拷贝\nb = a;                // 拷贝\n→ 编译器认为 a 之后还要用，必须保留",
         C_BLUE, C_PRIV)
    card(5.4, 2.7, 4.4, 1.7, "右值 rvalue：临时的、将亡的",
         "HeavyObj b(func());   // func 返回的临时值→移动\nHeavyObj b(std::move(a));// 显式转成右值→移动\n→ 这个值反正要销毁，堆数据直接偷走",
         C_GOOD, C_SHARE)

    ax.text(5.1, 2.35, "std::move 做的唯一一件事：把左值「强制转成右值引用」，告诉编译器「这个我不要了，可以偷」",
            ha="center", fontsize=9, color=C_ORANGE, weight="bold")
    ax.text(5.1, 1.95, "它自己不移动任何东西——真正的移动发生在被调用的移动构造/移动赋值里", ha="center", fontsize=8.3, color="#666")

    # 底部：一个对象通常成对定义 5 个特殊函数
    card(0.4, 0.3, 9.4, 1.3, "Rule of Five（要么全默认，要么全定义）",
         "析构 ~T() · 拷贝构造 T(const T&) · 拷贝赋值 operator=(const T&) · 移动构造 T(T&&) · 移动赋值 operator=(T&&)\n"
         "定义了其中任何一个(尤其析构)，移动构造/赋值可能不再自动生成 → 该类会悄悄退化成「只能拷贝」",
         C_EDGE, "white")
    ax.set_xlim(0, 10.2); ax.set_ylim(0, 5.0); ax.axis("off")
    ax.set_title("左值 vs 右值：移动只在「源是右值(将亡值)」时触发", fontsize=12, weight="bold")
    _save(fig, "move-2-value-category.png")


# ── 图3：本机实测 移动vs拷贝 + noexcept 扩容 ───────────────────────
def fig3_bench():
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(11.0, 4.4))

    # 左：移动 vs 拷贝一个重对象（对数）
    labels = ["移动构造\n(偷指针)", "拷贝构造\n(深拷贝4096double)"]
    vals = [2.33, 3022.72]  # ms，本机实测
    bars = axL.bar(labels, vals, color=[C_GOOD, C_BAD], width=0.5, edgecolor=C_EDGE, lw=1.2)
    axL.set_yscale("log")
    axL.set_ylim(1, 8000)
    axL.yaxis.set_major_locator(mticker.FixedLocator([1, 10, 100, 1000]))
    axL.yaxis.set_major_formatter(mticker.FixedFormatter(["1", "10", "100", "1000"]))
    axL.set_ylabel("20万次总耗时 (ms, 对数轴)", fontsize=10)
    for b, v in zip(bars, vals):
        axL.text(b.get_x()+b.get_width()/2, v*1.3, f"{v:.0f} ms" if v>=10 else f"{v:.1f} ms",
                 ha="center", fontsize=10, weight="bold")
    axL.set_title("移动 vs 拷贝：重对象差 3 个量级(本机实测)", fontsize=10.5, weight="bold")
    axL.text(0.5, 200, "差距随对象「持有的堆数据量」放大\n(小对象差距会缩小)", ha="center", fontsize=8.3, color="#555")

    # 右：noexcept 对 vector 扩容的影响
    labels2 = ["移动构造\nnoexcept", "移动构造\n未标noexcept"]
    vals2 = [18.35, 45.34]  # ms
    bars2 = axR.bar(labels2, vals2, color=[C_GOOD, C_BAD], width=0.5, edgecolor=C_EDGE, lw=1.2)
    axR.set_ylabel("vector 装 20 万元素耗时 (ms)", fontsize=10)
    for b, v in zip(bars2, vals2):
        axR.text(b.get_x()+b.get_width()/2, v+1.2, f"{v:.1f} ms", ha="center", fontsize=10.5, weight="bold")
    axR.set_title("noexcept 决定扩容走移动还是退化拷贝", fontsize=10.5, weight="bold")
    axR.annotate("未标 noexcept → vector 扩容\n不敢用移动(怕抛异常破坏强保证)\n→ 退化成拷贝，慢 2.5 倍",
                 xy=(1, 45.34), xytext=(0.35, 33), fontsize=8.5, color=C_BAD, weight="bold", ha="center",
                 arrowprops=dict(arrowstyle="->", color=C_BAD, lw=1.5))
    axR.set_ylim(0, 58)

    fig.suptitle("本机实测：移动省掉深拷贝(左)；移动构造必须标 noexcept，否则 vector 扩容退化拷贝(右)",
                 fontsize=11, weight="bold", y=1.0)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    _save(fig, "move-3-bench.png")


if __name__ == "__main__":
    fig1_copy_vs_move()
    fig2_value_category()
    fig3_bench()
    print("ALL DONE")
