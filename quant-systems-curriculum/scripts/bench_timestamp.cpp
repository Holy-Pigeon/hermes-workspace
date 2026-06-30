// 取时间戳的开销与分辨率实测（macOS 可跑的部分）
// 论点支撑：软件打点本身有成本与抖动，引出为何需要硬件时间戳
// 编译：c++ -O2 -std=c++17 bench_timestamp.cpp -o bench_ts
#include <cstdio>
#include <cstdint>
#include <ctime>
#include <chrono>
#include <vector>
#include <algorithm>
#include <mach/mach_time.h>

static inline uint64_t mach_now() { return mach_absolute_time(); }

int main() {
    const int N = 2'000'000;

    // mach timebase: 把 mach ticks 换算成纳秒
    mach_timebase_info_data_t tb;
    mach_timebase_info(&tb);
    double mach_to_ns = (double)tb.numer / tb.denom;
    printf("mach timebase: numer=%u denom=%u (1 tick = %.3f ns)\n", tb.numer, tb.denom, mach_to_ns);

    // ── 1. 测 clock_gettime(CLOCK_MONOTONIC) 单次调用开销 ──
    {
        std::vector<double> samples; samples.reserve(N);
        timespec a, b;
        for (int i = 0; i < N; ++i) {
            clock_gettime(CLOCK_MONOTONIC, &a);
            clock_gettime(CLOCK_MONOTONIC, &b);
            double ns = (b.tv_sec - a.tv_sec)*1e9 + (b.tv_nsec - a.tv_nsec);
            samples.push_back(ns);
        }
        std::sort(samples.begin(), samples.end());
        double p50 = samples[N/2], p99 = samples[(int)(N*0.99)], p999 = samples[(int)(N*0.999)];
        printf("\nclock_gettime(CLOCK_MONOTONIC) 单次调用开销:\n");
        printf("  p50=%.1f ns  p99=%.1f ns  p99.9=%.1f ns  max=%.1f ns\n",
               p50, p99, p999, samples.back());
    }

    // ── 2. 测 mach_absolute_time (类比 rdtsc) 单次调用开销 ──
    {
        std::vector<double> samples; samples.reserve(N);
        for (int i = 0; i < N; ++i) {
            uint64_t a = mach_now();
            uint64_t b = mach_now();
            samples.push_back((b - a) * mach_to_ns);
        }
        std::sort(samples.begin(), samples.end());
        double p50 = samples[N/2], p99 = samples[(int)(N*0.99)], p999 = samples[(int)(N*0.999)];
        printf("\nmach_absolute_time (类比 x86 rdtsc) 单次调用开销:\n");
        printf("  p50=%.1f ns  p99=%.1f ns  p99.9=%.1f ns  max=%.1f ns\n",
               p50, p99, p999, samples.back());
    }

    // ── 3. 分辨率：连续两次取时间，最小非零增量 = 有效分辨率 ──
    {
        uint64_t mn = UINT64_MAX;
        for (int i = 0; i < N; ++i) {
            uint64_t a = mach_now(), b = mach_now();
            uint64_t d = b - a;
            if (d > 0 && d < mn) mn = d;
        }
        printf("\nmach_absolute_time 有效分辨率(最小非零增量): %.3f ns\n", mn * mach_to_ns);
    }
    return 0;
}
