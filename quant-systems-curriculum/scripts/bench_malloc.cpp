// bench_malloc.cpp — malloc 行为实测：分配延迟长尾 + 大小块阈值 + 内存池对照
// 注意：bins/arena/tcache 是 glibc 特有实现，本机 macOS 用不同 allocator，
//       但"小块快、偶发尖峰、大块更贵、内存池稳定"的定性行为跨平台通用。
// 编译: c++ -O2 -std=c++17 bench_malloc.cpp -o bench_malloc
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <vector>
#include <chrono>
#include <algorithm>

static inline uint64_t now_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

// 测一组分配的延迟分布
struct Stat { double p50, p99, p999, mx, mean; };
static Stat run_alloc(size_t sz, int N) {
    std::vector<double> lat; lat.reserve(N);
    std::vector<void*> ptrs; ptrs.reserve(N);
    for (int i = 0; i < N; ++i) {
        uint64_t t0 = now_ns();
        void* p = malloc(sz);
        uint64_t t1 = now_ns();
        // 触碰首字节，确保真实分配（否则可能惰性）
        if (p) *(char*)p = 1;
        ptrs.push_back(p);
        lat.push_back((double)(t1 - t0));
    }
    for (void* p : ptrs) free(p);
    std::sort(lat.begin(), lat.end());
    double sum = 0; for (double x : lat) sum += x;
    return { lat[N/2], lat[(size_t)(N*0.99)], lat[(size_t)(N*0.999)], lat.back(), sum/N };
}

int main() {
    const int N = 500000;

    printf("=== 不同大小 malloc 的延迟分布（%d 次，ns）===\n", N);
    printf("%-14s %8s %8s %8s %10s %8s\n", "size", "p50", "p99", "p99.9", "max", "mean");
    for (size_t sz : {16ul, 64ul, 256ul, 1024ul, 4096ul, 65536ul, 1048576ul}) {
        Stat s = run_alloc(sz, N);
        char label[32];
        if (sz >= 1048576) snprintf(label, sizeof label, "%zuB(1MB,mmap)", sz);
        else if (sz >= 65536) snprintf(label, sizeof label, "%zuB(64KB)", sz);
        else snprintf(label, sizeof label, "%zuB", sz);
        printf("%-14s %8.0f %8.0f %8.0f %10.0f %8.1f\n", label, s.p50, s.p99, s.p999, s.mx, s.mean);
    }

    // ── 内存池对照：预分配一大块，从池里 bump 分配 ──
    printf("\n=== 内存池 bump 分配 vs malloc（64B 对象，%d 次）===\n", N);
    Stat sm = run_alloc(64, N);
    // 池
    const size_t POOL = (size_t)N * 64 + 4096;
    char* pool = (char*)malloc(POOL);
    *(volatile char*)pool = 1;
    std::vector<double> lat; lat.reserve(N);
    size_t off = 0;
    for (int i = 0; i < N; ++i) {
        uint64_t t0 = now_ns();
        void* p = pool + off; off += 64;   // bump 指针，一次加法
        uint64_t t1 = now_ns();
        *(char*)p = 1;
        lat.push_back((double)(t1 - t0));
    }
    std::sort(lat.begin(), lat.end());
    double sum = 0; for (double x : lat) sum += x;
    printf("malloc(64B):  p50=%.0f p99=%.0f max=%.0f mean=%.1f ns\n", sm.p50, sm.p99, sm.mx, sm.mean);
    printf("内存池 bump:  p50=%.0f p99=%.0f max=%.0f mean=%.1f ns\n",
           lat[N/2], lat[(size_t)(N*0.99)], lat.back(), sum/N);
    printf("→ 内存池 mean 是 malloc 的 1/%.1f, 且无 malloc 的偶发尖峰\n", sm.mean / (sum/N < 1e-6 ? 1e-6 : sum/N));
    free(pool);
    return 0;
}
