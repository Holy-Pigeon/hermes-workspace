// 缺页尖峰实测（macOS 可跑）：首次访问新内存(触发缺页) vs 预热后访问 的每页延迟
// 论点支撑：缺页=微秒级尖峰;预热后运行期零缺页
// 编译：c++ -O2 -std=c++17 bench_pagefault.cpp -o bench_pf
#include <cstdio>
#include <cstdint>
#include <vector>
#include <algorithm>
#include <chrono>
#include <sys/mman.h>
#include <unistd.h>

static inline uint64_t ns_now() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

int main() {
    const size_t PAGE = 4096;
    const size_t NPAGES = 200000;              // 20万页 ≈ 800MB
    const size_t SIZE = PAGE * NPAGES;

    // mmap 一块匿名内存（此时只保留地址，物理页未分配）
    char* buf = (char*)mmap(nullptr, SIZE, PROT_READ|PROT_WRITE,
                            MAP_PRIVATE|MAP_ANONYMOUS, -1, 0);
    if (buf == MAP_FAILED) { perror("mmap"); return 1; }

    // ── 1. 冷访问：每页第一个字节首次写入 → 触发缺页 ──
    std::vector<double> cold; cold.reserve(NPAGES);
    for (size_t i = 0; i < NPAGES; ++i) {
        uint64_t t0 = ns_now();
        buf[i*PAGE] = 1;                        // 首次写 → page fault
        uint64_t t1 = ns_now();
        cold.push_back((double)(t1 - t0));
    }

    // ── 2. 热访问：同样的页再写一次（已分配，无缺页）──
    std::vector<double> hot; hot.reserve(NPAGES);
    for (size_t i = 0; i < NPAGES; ++i) {
        uint64_t t0 = ns_now();
        buf[i*PAGE] = 2;                        // 已预热 → 无缺页
        uint64_t t1 = ns_now();
        hot.push_back((double)(t1 - t0));
    }

    auto pct = [](std::vector<double>& v, double p){
        std::sort(v.begin(), v.end());
        return v[(size_t)(v.size()*p)];
    };
    auto mx = [](std::vector<double>& v){ return *std::max_element(v.begin(), v.end()); };
    double cold_max = mx(cold), hot_max = mx(hot);
    printf("首次访问(触发缺页)  : p50=%.0f ns  p99=%.0f ns  p99.9=%.0f ns  max=%.0f ns\n",
           pct(cold,0.5), pct(cold,0.99), pct(cold,0.999), cold_max);
    printf("预热后访问(无缺页)  : p50=%.0f ns  p99=%.0f ns  p99.9=%.0f ns  max=%.0f ns\n",
           pct(hot,0.5), pct(hot,0.99), pct(hot,0.999), hot_max);
    printf("缺页 max 是预热后 max 的 %.0f 倍\n", cold_max / (hot_max>0?hot_max:1));

    // 缺页直方图（用于对数Y轴分布图）
    double edges[] = {0,100,200,500,1000,2000,5000,10000,50000,1e18};
    int nb = 9;
    std::vector<long> c1(nb,0), c2(nb,0);
    for (double v: cold) for(int b=0;b<nb;++b) if(v>=edges[b]&&v<edges[b+1]){c1[b]++;break;}
    for (double v: hot)  for(int b=0;b<nb;++b) if(v>=edges[b]&&v<edges[b+1]){c2[b]++;break;}
    const char* names[]={"0-100","100-200","200-500","500-1k","1k-2k","2k-5k","5k-10k","10k-50k","50k+"};
    printf("\n直方图(桶 | 缺页 | 预热后):\n");
    for(int b=0;b<nb;++b) printf("  %-9s | %8ld | %8ld\n", names[b], c1[b], c2[b]);

    munmap(buf, SIZE);
    return 0;
}
