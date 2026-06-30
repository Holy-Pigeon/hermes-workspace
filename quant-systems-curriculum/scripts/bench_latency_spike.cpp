// 延迟尖峰实测：一个紧凑循环里每次迭代测耗时，收集分布
// 即便是固定工作量的循环，也会因中断/调度/缺页偶发尖峰 → 真实的长尾分布
// 输出直方图数据 + P50/P99/P99.9/max 供画图
// 编译：c++ -O2 -std=c++17 bench_latency_spike.cpp -o bench_spike
#include <cstdio>
#include <cstdint>
#include <vector>
#include <algorithm>
#include <mach/mach_time.h>

static inline uint64_t now() { return mach_absolute_time(); }

int main() {
    mach_timebase_info_data_t tb; mach_timebase_info(&tb);
    double to_ns = (double)tb.numer / tb.denom;

    const int N = 5'000'000;
    std::vector<double> lat; lat.reserve(N);

    // 固定工作量：每次迭代做一点点定量计算（约几十 ns）
    volatile uint64_t acc = 0;
    for (int i = 0; i < N; ++i) {
        uint64_t t0 = now();
        // 固定的小工作量
        for (int k = 0; k < 20; ++k) acc += acc * 2654435761u + k;
        uint64_t t1 = now();
        lat.push_back((t1 - t0) * to_ns);
    }

    std::sort(lat.begin(), lat.end());
    double p50 = lat[N/2], p90 = lat[(int)(N*0.90)], p99 = lat[(int)(N*0.99)];
    double p999 = lat[(int)(N*0.999)], p9999 = lat[(int)(N*0.9999)], mx = lat.back();
    printf("固定工作量循环, %d 次迭代, 延迟分布(ns):\n", N);
    printf("  p50=%.1f  p90=%.1f  p99=%.1f  p99.9=%.1f  p99.99=%.1f  max=%.1f\n",
           p50, p90, p99, p999, p9999, mx);
    printf("  max/p50 = %.0fx  (尾部尖峰是中位数的多少倍)\n", mx/p50);

    // 直方图：分桶统计 (用于画对数Y轴分布图)
    // 桶: 0-50,50-100,100-200,200-500,500-1k,1k-2k,2k-5k,5k-10k,10k-50k,50k+
    double edges[] = {0,50,100,200,500,1000,2000,5000,10000,50000,1e18};
    int nb = 10;
    std::vector<long> cnt(nb, 0);
    for (double v : lat) {
        for (int b = 0; b < nb; ++b) if (v >= edges[b] && v < edges[b+1]) { cnt[b]++; break; }
    }
    printf("\n直方图(桶: 计数):\n");
    const char* names[] = {"0-50","50-100","100-200","200-500","500-1k","1k-2k","2k-5k","5k-10k","10k-50k","50k+"};
    for (int b = 0; b < nb; ++b)
        printf("  %-9s : %ld\n", names[b], cnt[b]);
    printf("acc=%llu\n", (unsigned long long)acc);
    return 0;
}
