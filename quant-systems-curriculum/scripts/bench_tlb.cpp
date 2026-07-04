// bench_tlb.cpp — 测「访存延迟随工作集增大的阶梯」：
// 依赖式指针追逐(pointer chase)遍历一个随机置换的环，工作集越大，
// 越会先后越过 L1/L2/LLC 容量与 TLB reach，单次访存延迟阶梯式抬升。
// 这是 cache + TLB 共同作用的经典测量（无法在用户态干净隔离纯 TLB，故如实标注）。
// 编译: clang++ -O2 -std=c++17 bench_tlb.cpp -o bench_tlb
#include <cstdio>
#include <cstdint>
#include <vector>
#include <random>
#include <algorithm>
#include <chrono>

int main() {
    // 每个元素 64B（=一个 cache line），元素内存下一个要跳的索引
    struct Node { uint64_t next; uint64_t pad[7]; };
    // 工作集大小档位（字节）
    const uint64_t sizes[] = {
        16ull*1024, 64ull*1024, 256ull*1024, 1ull*1024*1024,
        4ull*1024*1024, 16ull*1024*1024, 64ull*1024*1024, 256ull*1024*1024
    };
    printf("workset_bytes,n_nodes,ns_per_access\n");
    std::mt19937_64 rng(12345);
    for (uint64_t bytes : sizes) {
        uint64_t n = bytes / sizeof(Node);
        if (n < 2) continue;
        std::vector<Node> a(n);
        // 造一个覆盖全部节点的随机单环（random permutation cycle）
        std::vector<uint64_t> perm(n);
        for (uint64_t i = 0; i < n; ++i) perm[i] = i;
        std::shuffle(perm.begin() + 1, perm.end(), rng); // perm[0]=0 固定起点
        for (uint64_t i = 0; i < n; ++i)
            a[perm[i]].next = perm[(i + 1) % n];
        // 预热：把所有页都 touch 到（排除缺页干扰，纯测稳态访存）
        volatile uint64_t warm = 0;
        for (uint64_t i = 0; i < n; ++i) warm += a[i].next;
        // 正式测量：依赖链，编译器无法乱序/预取
        const uint64_t iters = 50'000'000ull;
        uint64_t idx = 0;
        auto t0 = std::chrono::steady_clock::now();
        for (uint64_t i = 0; i < iters; ++i) idx = a[idx].next;
        auto t1 = std::chrono::steady_clock::now();
        volatile uint64_t sink = idx; (void)sink; (void)warm;
        double ns = std::chrono::duration<double, std::nano>(t1 - t0).count() / iters;
        printf("%llu,%llu,%.3f\n", (unsigned long long)bytes,
               (unsigned long long)n, ns);
        fflush(stdout);
    }
    return 0;
}
