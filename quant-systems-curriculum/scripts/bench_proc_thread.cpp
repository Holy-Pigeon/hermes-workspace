// bench_proc_thread.cpp — 进程 vs 线程「创建开销」实测（macOS 可跑，Linux 同理）
// 方法：分别测 fork() 建进程 与 pthread 建线程 各 N 次的平均耗时。
//   - fork 子进程立即 _exit(0)，父进程 waitpid 回收
//   - pthread 线程体空转立即返回，主线程 join
// 编译: c++ -O2 -std=c++17 -pthread bench_proc_thread.cpp -o bench_proc_thread
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <pthread.h>
#include <unistd.h>
#include <sys/wait.h>
#include <chrono>
#include <vector>
#include <algorithm>

static void* noop(void*) { return nullptr; }

int main() {
    const int N = 2000;

    // ── fork 建进程 ──
    std::vector<double> fork_ns;
    fork_ns.reserve(N);
    for (int i = 0; i < N; ++i) {
        auto t0 = std::chrono::steady_clock::now();
        pid_t pid = fork();
        if (pid == 0) { _exit(0); }        // 子进程立刻退出
        auto t1 = std::chrono::steady_clock::now();
        int st; waitpid(pid, &st, 0);       // 父回收（不计入创建计时）
        fork_ns.push_back(std::chrono::duration<double, std::nano>(t1 - t0).count());
    }

    // ── pthread 建线程 ──
    std::vector<double> thr_ns;
    thr_ns.reserve(N);
    for (int i = 0; i < N; ++i) {
        pthread_t th;
        auto t0 = std::chrono::steady_clock::now();
        pthread_create(&th, nullptr, noop, nullptr);
        auto t1 = std::chrono::steady_clock::now();
        pthread_join(th, nullptr);          // 回收（不计入创建计时）
        thr_ns.push_back(std::chrono::duration<double, std::nano>(t1 - t0).count());
    }

    auto stats = [](std::vector<double>& v) {
        std::sort(v.begin(), v.end());
        double sum = 0; for (double x : v) sum += x;
        double mean = sum / v.size();
        double p50 = v[v.size()/2];
        double p99 = v[(size_t)(v.size()*0.99)];
        printf("  mean=%.0f ns  p50=%.0f ns  p99=%.0f ns\n", mean, p50, p99);
        return mean;
    };

    printf("fork() 建进程 x%d:\n", N);
    double fm = stats(fork_ns);
    printf("pthread_create 建线程 x%d:\n", N);
    double tm = stats(thr_ns);
    printf("→ 建进程平均是建线程的 %.1f 倍开销\n", fm / tm);
    return 0;
}
