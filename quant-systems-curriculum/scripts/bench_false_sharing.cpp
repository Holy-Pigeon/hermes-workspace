// false sharing 实测 benchmark
// 两个线程各自对自己的计数器自增 N 次。
// 版本 A：两个计数器紧挨着（很可能落在同一条 64B cache line）→ false sharing
// 版本 B：每个计数器用 alignas(64) 撑开到独占一条 cache line → 无 false sharing
// 编译：c++ -O2 -std=c++17 -pthread bench_false_sharing.cpp -o bench_fs
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <thread>
#include <chrono>
#include <new>

static constexpr int64_t ITERS = 200'000'000;

// ── 版本 A：紧挨着，共享 cache line ──
struct Packed {
    std::atomic<int64_t> a{0};
    std::atomic<int64_t> b{0};
};

// ── 版本 B：各自对齐到 64B，独占 cache line ──
struct Padded {
    alignas(64) std::atomic<int64_t> a{0};
    alignas(64) std::atomic<int64_t> b{0};
};

template <typename T>
double run(T& s) {
    auto t0 = std::chrono::steady_clock::now();
    std::thread t1([&] { for (int64_t i = 0; i < ITERS; ++i) s.a.fetch_add(1, std::memory_order_relaxed); });
    std::thread t2([&] { for (int64_t i = 0; i < ITERS; ++i) s.b.fetch_add(1, std::memory_order_relaxed); });
    t1.join(); t2.join();
    auto t1e = std::chrono::steady_clock::now();
    return std::chrono::duration<double>(t1e - t0).count();
}

int main() {
    printf("hardware_destructive_interference_size = %zu\n",
#ifdef __cpp_lib_hardware_interference_size
           std::hardware_destructive_interference_size
#else
           (size_t)64
#endif
    );
    printf("sizeof(Packed)=%zu  sizeof(Padded)=%zu\n", sizeof(Packed), sizeof(Padded));

    // 多跑几轮取最优，减少调度噪声
    double bestA = 1e9, bestB = 1e9;
    for (int r = 0; r < 5; ++r) {
        Packed pk; double ta = run(pk); if (ta < bestA) bestA = ta;
        Padded pd; double tb = run(pd); if (tb < bestB) bestB = tb;
    }
    printf("Packed  (shared line) : %.3f s\n", bestA);
    printf("Padded  (alignas 64)  : %.3f s\n", bestB);
    printf("slowdown from false sharing: %.2fx\n", bestA / bestB);
    return 0;
}
