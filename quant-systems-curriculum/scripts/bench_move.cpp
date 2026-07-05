// bench_move.cpp — 移动 vs 拷贝 的开销实测 + noexcept 对 vector 扩容的影响
// 关键：让移动/拷贝的结果真正逃逸(存进外部容器)，否则 -O2 会把无副作用的循环整段删掉，
//       导致移动测出 0ms 的假象。
// 编译: c++ -O2 -std=c++17 bench_move.cpp -o bench_move
#include <cstdio>
#include <cstdint>
#include <vector>
#include <string>
#include <chrono>
#include <utility>

// 一个"重"对象：内部持有堆分配的大 buffer（模拟行情快照/订单批）
struct HeavyObj {
    std::vector<double> data;
    std::string tag;
    HeavyObj() : data(4096, 1.5), tag("order-batch-payload-string") {}
    HeavyObj(const HeavyObj&) = default;                 // 深拷贝
    HeavyObj(HeavyObj&&) noexcept = default;             // 移动
};

struct MoveNoexcept {
    std::vector<double> data;
    MoveNoexcept() : data(256, 1.0) {}
    MoveNoexcept(const MoveNoexcept&) = default;
    MoveNoexcept(MoveNoexcept&& o) noexcept : data(std::move(o.data)) {}
    MoveNoexcept& operator=(MoveNoexcept&&) noexcept = default;
    MoveNoexcept& operator=(const MoveNoexcept&) = default;
};

struct MoveThrowing {
    std::vector<double> data;
    MoveThrowing() : data(256, 1.0) {}
    MoveThrowing(const MoveThrowing&) = default;
    MoveThrowing(MoveThrowing&& o) /* 没有 noexcept */ : data(std::move(o.data)) {}
};

template <class F>
double timed(F&& f) {
    auto t0 = std::chrono::steady_clock::now();
    f();
    auto t1 = std::chrono::steady_clock::now();
    return std::chrono::duration<double, std::milli>(t1 - t0).count();
}

int main() {
    const int N = 200000;

    // 预建 N 个源对象（构造成本不计入计时）
    std::vector<HeavyObj> src_copy(N), src_move(N);
    // 结果落地容器，强制移动/拷贝的效果逃逸，防止整段循环被优化掉
    std::vector<HeavyObj> dst;
    dst.reserve(N);

    // ── 拷贝：从 src_copy 深拷贝进 dst ──
    double t_copy = timed([&]{
        for (int i = 0; i < N; ++i) dst.emplace_back(src_copy[i]);          // 拷贝构造
    });
    volatile size_t sink = dst.size();
    dst.clear();

    // ── 移动：从 src_move 移动进 dst（偷指针）──
    double t_move = timed([&]{
        for (int i = 0; i < N; ++i) dst.emplace_back(std::move(src_move[i])); // 移动构造
    });
    sink += dst.size();
    dst.clear(); dst.shrink_to_fit();

    printf("重对象(4096 double + string) %d 次(结果均落地 dst，防优化):\n", N);
    printf("  拷贝构造(深拷贝): %.2f ms\n", t_copy);
    printf("  移动构造(偷指针): %.2f ms\n", t_move);
    printf("  → 移动比拷贝快 %.1f 倍\n\n", t_copy / (t_move < 1e-4 ? 1e-4 : t_move));

    // ── noexcept 对 vector 扩容的影响（多轮取中位，减小噪声）──
    const int M = 200000;
    auto run_ne = [&]{
        return timed([&]{
            std::vector<MoveNoexcept> v;
            for (int i = 0; i < M; ++i) v.emplace_back();
            sink += v.size();
        });
    };
    auto run_thr = [&]{
        return timed([&]{
            std::vector<MoveThrowing> v;
            for (int i = 0; i < M; ++i) v.emplace_back();
            sink += v.size();
        });
    };
    // 预热一轮（排除首次分配/cache 冷启动），再各测 5 轮取最小值（最少受调度干扰）
    run_ne(); run_thr();
    double t_ne = 1e9, t_thr = 1e9;
    for (int k = 0; k < 5; ++k) { double x = run_ne();  if (x < t_ne)  t_ne  = x; }
    for (int k = 0; k < 5; ++k) { double x = run_thr(); if (x < t_thr) t_thr = x; }
    printf("vector<T> push %d 个元素(触发多次扩容搬迁, 5轮取最小):\n", M);
    printf("  T 移动构造 noexcept(扩容走移动): %.2f ms\n", t_ne);
    printf("  T 移动构造 未标 noexcept(扩容退化拷贝): %.2f ms\n", t_thr);
    printf("  → noexcept 版快 %.1f 倍（这就是为什么移动构造要标 noexcept）\n", t_thr / (t_ne < 1e-4 ? 1e-4 : t_ne));
    printf("sink=%zu\n", (size_t)sink);
    return 0;
}
