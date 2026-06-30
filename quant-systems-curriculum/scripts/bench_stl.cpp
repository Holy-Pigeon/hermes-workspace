// STL 内部实现实测：1) vector 扩容因子  2) unordered_map vs 开放寻址/flat 查找延迟
// 编译：c++ -O2 -std=c++17 bench_stl.cpp -o bench_stl
#include <vector>
#include <unordered_map>
#include <cstdio>
#include <cstdint>
#include <chrono>
#include <random>
#include <algorithm>

// ── 实验1：vector 扩容因子 ──
void exp_vector_growth() {
    printf("=== 实验1: vector 扩容因子 (libc++) ===\n");
    std::vector<int> v;
    size_t last = 0;
    int realloc_count = 0;
    double ratios = 0; int rn = 0;
    for (int i = 0; i < 100000; ++i) {
        v.push_back(i);
        if (v.capacity() != last) {
            if (last > 0) { ratios += (double)v.capacity()/last; rn++; }
            if (realloc_count < 12)
                printf("  size=%6d -> capacity=%zu%s\n", i+1, v.capacity(),
                       last? "" : " (首次分配)");
            last = v.capacity();
            realloc_count++;
        }
    }
    printf("  100000 次 push_back 共触发 %d 次扩容\n", realloc_count);
    printf("  平均扩容倍数 ~= %.2fx\n", ratios/rn);
}

// ── 极简开放寻址(线性探测)扁平哈希表：连续一块内存, cache 友好, 无逐节点 malloc ──
struct FlatHash {
    struct Slot { uint64_t key; uint64_t val; bool used; };
    std::vector<Slot> t;
    size_t mask;
    explicit FlatHash(size_t cap_pow2) : t(cap_pow2), mask(cap_pow2 - 1) {}
    static uint64_t mix(uint64_t x){ x^=x>>33; x*=0xff51afd7ed558ccdULL; x^=x>>33; return x; }
    void put(uint64_t k, uint64_t v){
        size_t i = mix(k) & mask;
        while (t[i].used && t[i].key != k) i = (i+1) & mask;
        t[i] = {k, v, true};
    }
    const uint64_t* get(uint64_t k) const {
        size_t i = mix(k) & mask;
        while (t[i].used) { if (t[i].key==k) return &t[i].val; i=(i+1)&mask; }
        return nullptr;
    }
};

// ── 实验2：unordered_map vs sorted-vector 二分 vs 开放寻址扁平哈希 ──
void exp_lookup() {
    printf("\n=== 实验2: 100万键随机查找 1000万次, 总延迟对比 ===\n");
    const int N = 1'000'000;
    const int Q = 10'000'000;
    std::mt19937_64 rng(42);

    std::vector<uint64_t> keys(N);
    for (int i = 0; i < N; ++i) keys[i] = rng();

    // unordered_map
    std::unordered_map<uint64_t,uint64_t> um;
    um.reserve(N);
    for (int i = 0; i < N; ++i) um[keys[i]] = i;

    // sorted flat vector (key,val) + 二分
    std::vector<std::pair<uint64_t,uint64_t>> flat(N);
    for (int i = 0; i < N; ++i) flat[i] = {keys[i], (uint64_t)i};
    std::sort(flat.begin(), flat.end());

    // 开放寻址扁平哈希 (容量取 >2N 的 2 的幂, 负载因子 ~0.48)
    size_t cap = 1; while (cap < (size_t)N*2) cap <<= 1;
    FlatHash fh(cap);
    for (int i = 0; i < N; ++i) fh.put(keys[i], i);

    // 随机查询序列（命中已存在的键）
    std::vector<uint64_t> q(Q);
    std::uniform_int_distribution<int> pick(0, N-1);
    for (int i = 0; i < Q; ++i) q[i] = keys[pick(rng)];

    volatile uint64_t sink = 0;
    // unordered_map 查找
    auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < Q; ++i) { auto it = um.find(q[i]); if (it!=um.end()) sink += it->second; }
    auto t1 = std::chrono::steady_clock::now();
    double tum = std::chrono::duration<double>(t1-t0).count();

    // flat 二分查找
    auto t2 = std::chrono::steady_clock::now();
    for (int i = 0; i < Q; ++i) {
        auto it = std::lower_bound(flat.begin(), flat.end(), std::make_pair(q[i], (uint64_t)0));
        if (it != flat.end() && it->first == q[i]) sink += it->second;
    }
    auto t3 = std::chrono::steady_clock::now();
    double tflat = std::chrono::duration<double>(t3-t2).count();

    // 开放寻址扁平哈希查找
    auto t4 = std::chrono::steady_clock::now();
    for (int i = 0; i < Q; ++i) { auto* p = fh.get(q[i]); if (p) sink += *p; }
    auto t5 = std::chrono::steady_clock::now();
    double tfh = std::chrono::duration<double>(t5-t4).count();

    printf("  std::unordered_map.find   : %.3f s  (%.1f ns/次)\n", tum, tum/Q*1e9);
    printf("  sorted-vector 二分         : %.3f s  (%.1f ns/次)\n", tflat, tflat/Q*1e9);
    printf("  开放寻址扁平哈希(自研)      : %.3f s  (%.1f ns/次)\n", tfh, tfh/Q*1e9);
    printf("  (sink=%llu, 防优化)\n", (unsigned long long)sink);
    printf("  内存布局: unordered_map 每键单独 new 节点(链式,散落堆上); flat/扁平哈希 连续一块\n");
}

int main() {
    exp_vector_growth();
    exp_lookup();
    return 0;
}
