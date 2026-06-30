// 探测本机真实 cache line：对不同对齐间距测 false sharing 强度
// 间距跨过真实 line size 时，slowdown 会突然消失 → 找到拐点
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <thread>
#include <chrono>
#include <cstdlib>

static constexpr int64_t ITERS = 100'000'000;

double run_with_gap(int gap_bytes) {
    // 在一块缓冲里放两个计数器，间距 gap_bytes
    alignas(256) static unsigned char buf[4096];
    auto* a = new (buf + 0) std::atomic<int64_t>(0);
    auto* b = new (buf + gap_bytes) std::atomic<int64_t>(0);
    auto t0 = std::chrono::steady_clock::now();
    std::thread t1([&] { for (int64_t i = 0; i < ITERS; ++i) a->fetch_add(1, std::memory_order_relaxed); });
    std::thread t2([&] { for (int64_t i = 0; i < ITERS; ++i) b->fetch_add(1, std::memory_order_relaxed); });
    t1.join(); t2.join();
    auto t1e = std::chrono::steady_clock::now();
    return std::chrono::duration<double>(t1e - t0).count();
}

int main() {
    double base = 1e9;
    for (int gap : {8, 16, 32, 64, 128, 256}) {
        double best = 1e9;
        for (int r = 0; r < 3; ++r) { double t = run_with_gap(gap); if (t < best) best = t; }
        if (gap == 256) {} // 256 视为无竞争基线
        printf("gap=%4d B : %.3f s\n", gap, best);
    }
    return 0;
}
