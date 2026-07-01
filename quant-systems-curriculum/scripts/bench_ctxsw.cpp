// 上下文切换开销实测（macOS 可跑）
// 方法：两个线程通过一对 pipe 乒乓传递 1 字节，每次传递强制一次上下文切换
// 对照：同一线程内纯函数调用的开销，凸显切换的代价
// 编译：c++ -O2 -std=c++17 -pthread bench_ctxsw.cpp -o bench_ctxsw
#include <cstdio>
#include <cstdint>
#include <thread>
#include <unistd.h>
#include <chrono>
#include <vector>
#include <algorithm>

int main() {
    const int N = 200000;

    // ── pipe 乒乓：强制上下文切换 ──
    int p1[2], p2[2];
    if (pipe(p1) || pipe(p2)) { perror("pipe"); return 1; }

    std::thread worker([&]{
        char c;
        for (int i = 0; i < N; ++i) {
            read(p1[0], &c, 1);    // 等主线程
            write(p2[1], &c, 1);   // 回给主线程
        }
    });

    char c = 'x';
    auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < N; ++i) {
        write(p1[1], &c, 1);       // 唤醒 worker（切换过去）
        read(p2[0], &c, 1);        // 等 worker 回（切换回来）
    }
    auto t1 = std::chrono::steady_clock::now();
    worker.join();

    double total = std::chrono::duration<double>(t1 - t0).count();
    // 每轮 = 2 次上下文切换（去worker + 回主线程）
    double per_sw = total / (N * 2.0) * 1e9;
    printf("pipe 乒乓 %d 轮, 总耗时 %.3f s\n", N, total);
    printf("每次上下文切换约 %.0f ns（含 syscall+调度+可能的冷cache）\n", per_sw);

    // ── 对照：同线程纯函数调用开销 ──
    volatile uint64_t acc = 0;
    auto t2 = std::chrono::steady_clock::now();
    for (int i = 0; i < N*2; ++i) acc += acc*2654435761u + i;
    auto t3 = std::chrono::steady_clock::now();
    double per_call = std::chrono::duration<double>(t3 - t2).count() / (N*2.0) * 1e9;
    printf("对照：同线程一次定量计算约 %.1f ns\n", per_call);
    printf("→ 上下文切换是纯计算的约 %.0f 倍开销\n", per_sw / per_call);
    printf("acc=%llu\n", (unsigned long long)acc);
    return 0;
}
