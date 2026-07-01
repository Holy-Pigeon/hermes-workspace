// 访存局部性实测（macOS 可跑）：顺序 vs 随机访问同一块内存的延迟差
// 论点支撑：访存延迟高度依赖局部性——这是 NUMA「本地近、远端远」的底层同源原理
// 编译：c++ -O2 -std=c++17 bench_mem_locality.cpp -o bench_locality
#include <cstdio>
#include <cstdint>
#include <vector>
#include <random>
#include <algorithm>
#include <chrono>

int main() {
    // 用一块远大于 LLC 的内存（256MB），确保能打穿各级 cache
    const size_t N = 64 * 1024 * 1024;   // 64M 个 uint32 = 256MB
    std::vector<uint32_t> a(N);

    // 顺序访问链：a[i] = i+1（按顺序走）
    for (size_t i = 0; i < N; ++i) a[i] = (uint32_t)((i + 1) % N);

    const int STEPS = 50'000'000;

    // ── 1. 顺序访问（硬件预取器友好）──
    {
        uint32_t idx = 0;
        volatile uint32_t sink = 0;
        auto t0 = std::chrono::steady_clock::now();
        for (int s = 0; s < STEPS; ++s) { idx = a[idx]; sink += idx; }
        auto t1 = std::chrono::steady_clock::now();
        double ns = std::chrono::duration<double>(t1 - t0).count() / STEPS * 1e9;
        printf("顺序访问链   : %.2f ns/次 (sink=%u)\n", ns, (unsigned)sink);
    }

    // 随机访问链：打乱成一个覆盖全部下标的随机置换环（pointer chasing）
    std::vector<uint32_t> perm(N);
    for (size_t i = 0; i < N; ++i) perm[i] = (uint32_t)i;
    std::mt19937_64 rng(123);
    std::shuffle(perm.begin(), perm.end(), rng);
    // a[perm[i]] = perm[i+1]，形成一个随机大环
    for (size_t i = 0; i < N; ++i) a[perm[i]] = perm[(i + 1) % N];

    // ── 2. 随机访问（预取器无效，每跳一次几乎必 cache miss）──
    {
        uint32_t idx = 0;
        volatile uint32_t sink = 0;
        auto t0 = std::chrono::steady_clock::now();
        for (int s = 0; s < STEPS; ++s) { idx = a[idx]; sink += idx; }
        auto t1 = std::chrono::steady_clock::now();
        double ns = std::chrono::duration<double>(t1 - t0).count() / STEPS * 1e9;
        printf("随机访问链   : %.2f ns/次 (sink=%u)\n", ns, (unsigned)sink);
    }
    return 0;
}
