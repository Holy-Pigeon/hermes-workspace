## 手写单生产者单消费者无锁环形队列（SPSC Ring Buffer）

> 阶段 C4 · 内存模型与并发 ｜ 难度 🔴 硬核 ｜ 档位 A·低延迟核心
> 出处级别：Erik Rigtorp《Correctly implementing a ring buffer》一手原文（rigtorp.se/ringbuffer/）+ LMAX Disruptor 官方白皮书旁证。

### 问题入口

低延迟交易系统里，行情线程要把解析好的 tick 交给策略线程，策略线程再把订单交给下单线程——这是典型的**线程间单向移交**。如果用 `std::mutex` + `std::queue`，每次入队出队都要抢锁，锁竞争会带来微秒级、且**不确定**的延迟尖峰。HFT 关心的不是均值，是 P99.9 的最坏几次——一次尖峰就吃单/滑点。

所以热路径的标配是**单生产者单消费者无锁队列（SPSC）**：一个线程只写、一个线程只读，用原子变量协调，全程不加锁。

### 朴素想法与卡点

朴素实现：一个数组 + 一个 `size` 计数器，生产者 `size++`、消费者 `size--`。卡点在于：

1. `size` 被两个线程同时读写，是数据竞争，必须原子化。
2. 即便原子化，`size` 这个变量被两个线程频繁读写，会在两个 CPU 核之间反复弹跳（cache line 来回失效），这就是 **false sharing 的近亲——真共享热点**，性能极差。

### 核心设计（Rigtorp 一手方案）

正确实现的关键有三点，全部来自 Rigtorp 原文：

1. **读写下标分离 + cache line 对齐**。用两个下标 `writeIdx_`（只有生产者写）和 `readIdx_`（只有消费者写），各自 `alignas(64)` 对齐到独立 cache line。Rigtorp 原文：

   > "read (readIdx_) and write (writeIdx_) indices are aligned to the size of a cache line (alignas(64))... to reduce cache coherency traffic."

   为什么 64 字节？因为 x86_64 / ARM 的 cache line 是 64 字节（原文确认）。可用 `std::hardware_destructive_interference_size`（C++17）替代硬编码 64。

2. **acquire/release 配对**，而非 `seq_cst`。生产者写完数据后 `writeIdx_.store(next, std::memory_order_release)`；消费者 `writeIdx_.load(std::memory_order_acquire)`。release 保证「数据写入」先于「下标发布」对消费者可见，acquire 保证消费者读到新下标后能看到对应数据。这比默认的 `seq_cst` 省掉一道全屏障——**能讲清这里为什么 `relaxed` 不够、`acquire/release` 刚好够，是 A 档面试的分水岭题**。

3. **预分配 + 不取模用容量判断**。环形缓冲区在启动时一次性分配（呼应 LMAX Disruptor 原文 "All memory for the ring buffer is pre-allocated on start up"），热路径**绝不 new/malloc**。

### 反直觉点

- **`size` 计数器是性能杀手，要消掉它**。高手实现不维护共享 `size`，而是各自持有对方下标的**本地缓存副本**（`writeIdxCached_` / `readIdxCached_`），只有本地判断「满/空」失败时才去读对方的真实原子下标，把跨核 cache 同步降到最低。这是 Rigtorp 实现比教科书快数倍的核心 trick。
- **x86 上 release 几乎免费**。x86 是 TSO 内存模型，store-release 不需要额外屏障指令，所以「无锁队列在 x86 上快」有硬件原因——但代码仍要写对 memory_order，因为同一份代码要能在 ARM（弱内存模型）上正确运行。

### 适用边界

- SPSC 只对**一个生产者 + 一个消费者**成立。多生产者要上 MPMC（Disruptor 模式或 CAS 循环），复杂度和延迟都更高。
- 无锁 ≠ 无等待。这是 lock-free 不是 wait-free；最坏延迟上界要 wait-free 才有保证，少数顶尖岗会深挖这点。

### 关联

- 上游：C4-18 六种 memory_order（本课的 acquire/release 是那节的应用）。
- 下游：C4-22 MPMC & Disruptor（多生产者推广）、C5-28 内存池（预分配理念）。
- 系统侧呼应：O3-15 false sharing、O3-13 HugePages（大缓冲降 TLB miss）。
