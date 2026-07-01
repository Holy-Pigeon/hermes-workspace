// busy-polling 忙等 vs 阻塞唤醒 的延迟对比（macOS 可跑）
// 生产者隔一段时间发布一个数据(带时间戳)，消费者两种方式感知：
//   A. busy-poll: 死循环读原子标志(牺牲CPU换低延迟)
//   B. blocking:  condition_variable 阻塞等待(省CPU但唤醒有内核调度延迟)
// 测「数据发布 -> 消费者感知」的延迟分布
// 编译：c++ -O2 -std=c++17 -pthread bench_busypoll.cpp -o bench_busypoll
#include <cstdio>
#include <cstdint>
#include <atomic>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <chrono>
#include <vector>
#include <algorithm>

static inline uint64_t ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

const int ROUNDS = 20000;

// ── A. busy-poll ──
void test_busypoll() {
    std::atomic<uint64_t> stamp{0};
    std::atomic<bool> stop{false};
    std::vector<double> lat; lat.reserve(ROUNDS);

    std::thread consumer([&]{
        uint64_t last = 0;
        while (!stop.load(std::memory_order_relaxed)) {
            uint64_t s = stamp.load(std::memory_order_acquire);   // 死循环轮询
            if (s != last && s != 0) {
                lat.push_back((double)(ns() - s));
                last = s;
            }
        }
    });

    for (int i = 0; i < ROUNDS; ++i) {
        std::this_thread::sleep_for(std::chrono::microseconds(80));
        stamp.store(ns(), std::memory_order_release);   // 发布
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    stop = true; consumer.join();

    std::sort(lat.begin(), lat.end());
    size_t n = lat.size();
    printf("busy-poll   : p50=%.0f  p99=%.0f  p99.9=%.0f  max=%.0f ns  (样本%zu)\n",
           lat[n/2], lat[(size_t)(n*0.99)], lat[(size_t)(n*0.999)], lat.back(), n);
}

// ── B. blocking (condition_variable) ──
void test_blocking() {
    std::mutex m; std::condition_variable cv;
    uint64_t stamp = 0; bool ready = false, stop = false;
    std::vector<double> lat; lat.reserve(ROUNDS);

    std::thread consumer([&]{
        std::unique_lock<std::mutex> lk(m);
        while (true) {
            cv.wait(lk, [&]{ return ready || stop; });   // 阻塞等待，让出CPU
            if (stop) break;
            lat.push_back((double)(ns() - stamp));
            ready = false;
        }
    });

    for (int i = 0; i < ROUNDS; ++i) {
        std::this_thread::sleep_for(std::chrono::microseconds(80));
        {
            std::lock_guard<std::mutex> lk(m);
            stamp = ns(); ready = true;
        }
        cv.notify_one();   // 唤醒消费者（触发内核调度）
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    { std::lock_guard<std::mutex> lk(m); stop = true; } cv.notify_one();
    consumer.join();

    std::sort(lat.begin(), lat.end());
    size_t n = lat.size();
    printf("blocking cv : p50=%.0f  p99=%.0f  p99.9=%.0f  max=%.0f ns  (样本%zu)\n",
           lat[n/2], lat[(size_t)(n*0.99)], lat[(size_t)(n*0.999)], lat.back(), n);
}

int main() {
    printf("数据发布 -> 消费者感知 的延迟分布对比:\n");
    test_busypoll();
    test_blocking();
    return 0;
}
