// bench_vtable.cpp — 虚调用 vs 直接调用 vs CRTP 静态多态 的调用开销实测
// 关键点：
//  1. 让编译器无法把虚调用去虚化/内联，测真实的间接跳转+分支预测失败代价。
//  2. 非虚/CRTP 版本也要防止整个循环被优化消失——用 volatile 读入参数、结果累加进 volatile，
//     保证三者都真实执行 N 次调用，公平对比。
// 编译: c++ -O2 -std=c++17 bench_vtable.cpp -o bench_vtable
#include <cstdio>
#include <cstdint>
#include <vector>
#include <chrono>
#include <random>
#include <memory>

struct Base {
    virtual int calc(int x) const { return x + 1; }
    virtual ~Base() = default;
};
struct DerivedA : Base { int calc(int x) const override { return x * 2 + 7; } };
struct DerivedB : Base { int calc(int x) const override { return x - 3; } };

struct Plain {
    int calc(int x) const { return x * 2 + 7; }
};

template <class D>
struct CrtpBase {
    int calc(int x) const { return static_cast<const D*>(this)->calc_impl(x); }
};
struct CrtpImpl : CrtpBase<CrtpImpl> {
    int calc_impl(int x) const { return x * 2 + 7; }
};

int main() {
    const int N = 20'000'000;

    // 输入数组：每个元素从内存读，编译器无法把循环折叠成常量
    std::vector<int> in(N);
    std::mt19937 rng(42);
    for (int i = 0; i < N; ++i) in[i] = (int)(rng() & 0xffff);

    // 多态对象数组，类型随机打乱 → vtable 分派 + 间接跳转目标不可预测
    std::vector<std::unique_ptr<Base>> objs;
    objs.reserve(N);
    for (int i = 0; i < N; ++i) {
        if (rng() & 1) objs.emplace_back(std::make_unique<DerivedA>());
        else           objs.emplace_back(std::make_unique<DerivedB>());
    }

    volatile int sink = 0;

    // ── 虚调用（类型混合，vtable 分派 + 分支预测失败 + 无法内联）──
    auto t0 = std::chrono::steady_clock::now();
    int acc = 0;
    for (int i = 0; i < N; ++i) acc += objs[i]->calc(in[i]);
    auto t1 = std::chrono::steady_clock::now();
    sink += acc;
    double ns_virt = std::chrono::duration<double, std::nano>(t1 - t0).count() / N;

    // ── 直接调用（非虚，可内联；但从 in[] 读参数、结果累加，循环不会被优化掉）──
    Plain p;
    auto t2 = std::chrono::steady_clock::now();
    acc = 0;
    for (int i = 0; i < N; ++i) acc += p.calc(in[i]);
    auto t3 = std::chrono::steady_clock::now();
    sink += acc;
    double ns_direct = std::chrono::duration<double, std::nano>(t3 - t2).count() / N;

    // ── CRTP 静态多态（编译期确定，可内联）──
    CrtpImpl c;
    auto t4 = std::chrono::steady_clock::now();
    acc = 0;
    for (int i = 0; i < N; ++i) acc += c.calc(in[i]);
    auto t5 = std::chrono::steady_clock::now();
    sink += acc;
    double ns_crtp = std::chrono::duration<double, std::nano>(t5 - t4).count() / N;

    printf("sizeof(含vptr对象)=%zu B, sizeof(Plain无vptr)=%zu B, sizeof(CrtpImpl)=%zu B\n",
           sizeof(DerivedA), sizeof(Plain), sizeof(CrtpImpl));
    printf("虚调用(类型混合,vtable+分支预测失败): %.3f ns/call\n", ns_virt);
    printf("直接调用(非虚,内联):                 %.3f ns/call\n", ns_direct);
    printf("CRTP 静态多态(编译期,内联):          %.3f ns/call\n", ns_crtp);
    double d = ns_direct < 1e-3 ? 1e-3 : ns_direct;
    double cc = ns_crtp < 1e-3 ? 1e-3 : ns_crtp;
    printf("→ 虚调用比直接调用慢 %.1f 倍, 比 CRTP 慢 %.1f 倍\n", ns_virt / d, ns_virt / cc);
    printf("sink=%d\n", (int)sink);
    return 0;
}
