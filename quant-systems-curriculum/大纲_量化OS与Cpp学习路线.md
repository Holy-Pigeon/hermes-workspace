# 量化系统底层修炼 · 操作系统 & C++ 学习大纲

> 目标读者：想进/对标 幻方、九坤、灵均、明汯、锐天 这类头部量化私募
> **低延迟交易系统 / HPC / 高频研究** 岗位的人。
>
> 设计参照 AI-Teacher 的「分阶段 + 课时 + 难度标注」课程范式。

---

## 〇、先回答你的核心问题：要到什么程度？

量化对 C++/OS 的要求**不是一个统一标准**，按岗位分三档，深度天差地别。先对号入座，再决定学到哪：

| 档位 | 典型岗位 | C++ 深度 | OS 深度 | 谁在这一档 |
|---|---|---|---|---|
| **C 档 · 量化研究员** | 高频/中频 Quant Researcher（用 C++ 写信号/因子） | 现代 C++「会用、写得干净高效」 | Linux 基础系统编程「会用」 | 多数研究员岗到此为止 |
| **B 档 · HPC/平台** | 回测引擎、因子计算平台、策略平台开发 | 模板/SIMD/内存池「重工程+性能」 | NUMA/cache/虚存「懂体系结构」 | 平台组核心 |
| **A 档 · 低延迟核心** | Tick-to-Trade、交易系统工程师、Core Dev | 无锁/内存模型/纳秒优化「天花板」 | 内核旁路/绑核/抖动控制「啃内核」 | 幻方/九坤的硬核交易 infra |

**一句话标定**：
- 想做**研究员**——把 C 档练扎实就能过 C++ 关，OS 知道个所以然即可。
- 想做**低延迟交易系统**——A 档是门槛，**分水岭在「C++ 内存模型 + 无锁队列」和「Linux 绑核 + 内核旁路 + 抖动控制」**，这两块过不了，简历直接出局。

> 难度标注：🟢 入门必备 / 🟡 进阶 / 🔴 硬核（低延迟岗强考察）/ ⚫ 天花板（顶级 Core Dev）

---

# 第一部分：C++ 学习路线

## 阶段 C1 · 现代 C++ 地基（🟢 全员必过）

> 目标：能写出无泄漏、无多余拷贝、符合现代 C++ 习惯的代码。研究员岗 C++ 关到此即可。

1. **RAII 与生命周期**：值语义 vs 引用语义、确定性析构、智能指针（unique/shared/weak）
   - *量化用途*：订单对象、连接、锁的确定性释放；交易系统不允许泄漏/悬垂。**面试几乎必问 RAII**
2. **移动语义**：右值引用、`std::move`、移动 vs 拷贝开销、移动构造/赋值
   - *量化用途*：行情/订单对象在管线间传递避免深拷贝
3. **Lambda 与可调用对象**：捕获语义、`std::function` 的堆分配陷阱
   - *量化用途*：回调式行情处理；**面经高频「std::function 为什么慢」**——热路径要用函数指针/模板回调替代
4. **现代特性脉络（11/14/17/20）**：`auto`、结构化绑定、`if constexpr`、`std::optional/variant/string_view`、ranges
   - *量化用途*：`string_view` 零拷贝解析行情；`if constexpr` 编译期分支
5. **异常 vs 错误码、`noexcept`**：为什么 HFT 热路径常 `-fno-exceptions`
   - *量化用途*：`noexcept` 让移动/容器优化生效；面试会问「为什么 HFT 关异常」

## 阶段 C2 · 模板与泛型（🟡 进阶）

6. **模板基础**：特化、偏特化、变长模板（variadic）
   - *量化用途*：行情解析器按协议类型分发；泛型容器
7. **完美转发**：`std::forward`、引用折叠、万能引用
   - *量化用途*：`emplace` 类接口、通用消息分发
8. **`constexpr`/`consteval` 编译期计算**：把查表/协议偏移在编译期算好
   - *量化用途*：**zero-cost abstraction 的核心抓手**，运行时零开销
9. **TMP 模板元编程 + `type_traits`**（🔴）：编译期分支消除、类型选择
   - *量化用途*：高性能序列化/反序列化框架
10. **SFINAE → C++20 concepts**：约束模板接口
    - *量化用途*：新代码库普遍要求 concepts

## 阶段 C3 · 对象模型与底层（🟡→🔴 面试挖深度区）

11. **对象内存布局**：`sizeof`、对齐/padding、`#pragma pack`
    - *量化用途*：按协议二进制布局直接 reinterpret 映射行情结构体
12. **虚函数表 vtable**：虚调用开销、何时避免虚函数
    - *量化用途*：**面经常考 vtable 机制 + 如何去虚化**
13. **CRTP 静态多态**（🔴）：奇异递归模板，零虚调用开销
    - *量化用途*：策略/handler 框架的标配
14. **编译链接全过程**：预处理→编译→汇编→链接、符号解析、ODR、name mangling、`extern "C"`
    - *量化用途*：大型代码库构建问题排查、模板实例化膨胀
15. **静态库 vs 动态库**：符号可见性、`-fvisibility`、启动延迟

## 阶段 C4 · 内存模型与并发（⚫ A 档真正的分水岭）

> **这是低延迟岗 C++ 面试的核心战场。** 过不了这关，做不了交易系统。

16. **线程基础**（🟢）：`std::mutex`、`condition_variable`、死锁
17. **`std::atomic` 与 CAS**（🔴）：原子操作、ABA 问题
    - *量化用途*：无锁队列、序号计数器、状态切换
18. **六种 memory_order**（🔴 核心）：relaxed/consume/acquire/release/acq_rel/seq_cst
    - *量化用途*：**A 档面试核心**——无锁队列正确性依赖 acquire/release 配对；能讲清「这里为什么 relaxed 就够」是区分高手的题
19. **内存屏障与重排**（🔴）：编译器重排 vs CPU 重排、x86 TSO 模型
    - *量化用途*：理解为什么 x86 上某些 barrier 是空操作
20. **false sharing & cache line 对齐**（🔴）：64B cache line、`alignas`、`hardware_destructive_interference_size`
    - *量化用途*：多线程计数器/队列的性能杀手；**面经高频「两线程各写一个变量为什么变慢」**
21. **手写 SPSC ring buffer**（🔴 必刷）：单生产单消费无锁队列
    - *量化用途*：行情线程→策略线程、策略→下单线程的标配；**面试经常要求手写**
22. **MPMC 队列 & Disruptor 模式**（🔴）：多生产者；了解 LMAX Disruptor 思想加分
23. **wait-free / lock-free / obstruction-free 区别**（🔴）：HFT 追 wait-free 保证最坏延迟
24. **无锁内存回收**（⚫）：hazard pointer / RCU——少数顶尖岗会问

## 阶段 C5 · 性能优化（🔴 B/A 档硬核）

25. **zero-cost abstraction 理念**：抽象不带来运行时开销
26. **内联与分支预测**：`always_inline`、热/冷路径分离 `[[likely]]/[[unlikely]]`、`__builtin_expect`
27. **branchless 编程**：用算术/查表替代 if
    - *量化用途*：行情解析、订单匹配热路径
28. **避免动态分配 + 内存池**（🔴 必考）：对象池/arena allocator、自定义 allocator
    - *量化用途*：**热路径绝对禁止 new/malloc**；面经高频「如何在交易路径做到零分配」
29. **SIMD / intrinsics**（🟡→🔴）：SSE/AVX2/AVX-512、自动向量化
    - *量化用途*：因子批量计算、回测向量化；HPC 岗必备
30. **数据导向设计 DOD**（🔴）：SoA vs AoS、cache 友好布局
    - *量化用途*：order book 结构设计
31. **延迟测量**（🔴）：`rdtsc`、percentile p50/p99/p999、避免 jitter
    - *量化用途*：「如何测一个函数的纳秒延迟」是经典面试题
32. **PGO / LTO**（🟡）：Profile-Guided Optimization、链接期优化

## 阶段 C6 · 工具链与库（动手能力证据）

33. **编译器优化选项**（🟢）：`-O2/-O3/-march=native/-flto`、UB 风险
34. **Godbolt（Compiler Explorer）**（🟡）：看汇编验证「这个抽象真零开销吗」
35. **性能工具**（🔴）：`perf`、火焰图、`vtune`、`valgrind`(cachegrind/callgrind)
36. **Sanitizer**（🟡→🔴）：ASan/TSan/UBSan——**TSan 查数据竞争是无锁开发必备**
37. **STL 内部实现**（🔴 面经超高频）：vector 扩容、`unordered_map` 实现与缺点、`std::sort` 内省排序、迭代器失效
    - *量化用途*：「为什么 HFT 不用 std::unordered_map」（cache 不友好，常自研开放寻址哈希）
38. **工业级库**（🟡→🔴）：folly（ProducerConsumerQueue、F14）、abseil、Boost（asio/intrusive/lockfree）

---

# 第二部分：操作系统（Linux）学习路线

## 阶段 O1 · Linux 系统编程地基（🟢 全员必过）

> 目标：达到《Linux 高性能服务器编程》水平。研究员岗到此即可。

1. **进程 vs 线程**：fork/clone、TLS、进程隔离故障域
   - *量化用途*：行情/策略/下单分进程隔离
2. **信号、文件描述符、IPC 基础**
3. **Socket 编程基础**：TCP/UDP、`TCP_NODELAY` 关 Nagle
   - *量化用途*：行情多 UDP 组播、下单多 TCP，必关 Nagle
4. **epoll（LT/ET）**：多连接管理
5. **mmap / 共享内存 / `/dev/shm`**：进程间零拷贝共享行情

## 阶段 O2 · 进程调度与 CPU（🟡→🔴）

6. **CFS 调度器原理**（🟡）：vruntime、nice/权重——理解默认调度为何引入抖动
7. **上下文切换开销**（🔴）：~1-3µs + 冷 cache 代价
   - *量化用途*：切换=丢 cache+TLB，直接抬高 tail latency；目标是关键线程**零切换**
8. **CPU 亲和性**（🔴）：`sched_setaffinity`/`taskset`/`pthread_setaffinity`
   - *量化用途*：行情接收、下单线程**钉死到固定核**
9. **CPU 隔离**（🔴）：`isolcpus`/`nohz_full`/`rcu_nocbs`
   - *量化用途*：把交易核从内核调度器手里抢出来，核上只跑忙轮询线程
10. **NUMA 架构**（🔴）：`numactl`、本地/远端内存、`numa_alloc_onnode`
    - *量化用途*：线程+内存+网卡要在**同一 NUMA node**，跨 node 延迟翻倍
11. **实时调度类**（🔴）：`SCHED_FIFO/RR`、优先级——防关键线程被抢占

## 阶段 O3 · 内存管理（🟡→🔴）

12. **虚拟内存、四级页表、TLB**（🟡）：理解访存隐藏开销
13. **HugePages**（🔴）：2MB/1GB 大页，减少 TLB miss
    - *量化用途*：大行情表、订单簿用大页降抖动
14. **page fault 与内存预热**（🔴）：minor/major fault、`mlockall` + touch 全内存
    - *量化用途*：缺页=微秒级尖峰；启动预热，运行期零缺页
15. **cache line 对齐 + false sharing**（🔴，与 C++ C4 呼应）
16. **`mlockall` 锁页防 swap**（🔴）：严禁交易进程被换出
17. **内存带宽、prefetch、访问模式**（🔴）：SoA vs AoS
18. **自定义内存池**（🔴）：运行期禁 malloc，malloc 不确定性=抖动源

## 阶段 O4 · 中断与内核旁路（⚫ 低延迟核心战场）

> **这是 A 档岗位的天花板分水岭。** kernel bypass 几乎是顶级低延迟岗的门槛标志。

19. **硬中断/软中断**（🟡）：softirq、ksoftirqd——网卡中断是抖动主因
20. **中断亲和性**（🔴）：`/proc/irq/*/smp_affinity`
    - *量化用途*：把网卡中断绑到**非交易核**
21. **用户态/内核态切换 + syscall 开销**（🔴）：~百 ns 级、`vdso`
    - *量化用途*：热路径减少 syscall
22. **kernel bypass 思想**（⚫）：绕过内核协议栈，数据直达用户态
23. **Solarflare/Onload、Exablaze、Mellanox**（⚫）：业界标配低延迟网卡，onload 是量化最常见接管 socket 方案
24. **DPDK / 用户态网络栈**（⚫）：自研行情/下单网络栈，轮询收包
25. **busy-polling 忙等 vs 阻塞**（🔴）：关键线程死循环轮询而非 epoll 阻塞
    - *量化用途*：牺牲 CPU 换确定性低延迟；**面试分水岭题「忙等为什么比 epoll 延迟低、代价是什么」**

## 阶段 O5 · 网络深入（🔴）

26. **io_uring**（🟡）：新一代异步 IO/网络，减少 syscall
27. **零拷贝**（🔴）：`sendfile`/`MSG_ZEROCOPY`
28. **组播行情接收**（🔴）：UDP multicast、A/B 双线丢包重传
    - *量化用途*：交易所行情靠 UDP 组播
29. **网卡多队列、RSS、流定向**（🔴）：把目标行情流锁到指定核
30. **硬件时间戳**（🔴）：`SO_TIMESTAMPING`、网卡时间戳
    - *量化用途*：精确测量收到行情的时刻，算 tick-to-trade
31. **PTP 时间同步**（🔴）：ptp4l、纳秒级对时
    - *量化用途*：跨机延迟测量、合规打点

## 阶段 O6 · IO 与存储（🟡，非热路径主战场）

32. **page cache、`O_DIRECT`**：tick 数据落盘不污染 cache
33. **异步 IO**：`io_uring`/`libaio`，落行情/日志不阻塞热点线程
34. **日志异步化**（🔴）：**交易热点路径绝不同步写盘**，日志走旁路线程
    - *工程意识*：「日志/落盘不能拖慢交易线程」是必考

## 阶段 O7 · 性能分析（🔴 硬核岗必会）

35. **perf**（🔴）：stat/record/top，看 cache-miss、IPC、分支预测
36. **火焰图 FlameGraph**（🔴）：定位 CPU 热点
37. **PMU 性能计数器**（🔴）：L1/L2/LLC miss 分析
38. **ftrace / trace-cmd**（🔴）：内核函数级追踪、调度延迟
39. **eBPF / bcc / bpftrace**（🔴）：低开销在线观测调度、syscall、网络延迟
40. **cyclictest**（🔴）：测系统调度抖动/最大延迟，验证 RT 调优
41. **延迟直方图 HdrHistogram**（🔴）：统计 P50/P99/P999 tick-to-trade
    - *综合题*：「怎么定位一个延迟尖峰是缺页、中断还是调度引起的」——要能串起 ftrace/eBPF/perf/cyclictest

## 阶段 O8 · 实时性与抖动控制（⚫ 终极目标）

42. **抖动 jitter 来源全谱**：中断/缺页/调度/cache/NUMA/频率波动
43. **PREEMPT_RT 实时内核**：降低抢占延迟上界
44. **CPU 频率锁定**（🔴）：关 C-state/P-state、performance governor、关 turbo
    - *面试题*：「为什么要关 C-state」直接区分做过真实低延迟 vs 只看过书
45. **TSC 时钟源**（🔴）：高频取时间戳用 TSC、`tsc=reliable`
46. **关闭 THP 透明大页、`swappiness=0`**（🔴）：THP 合并/回收会引尖峰
47. **tail latency P99/P999/P9999 思维**（🔴）：量化关心的不是均值，是**最坏几次**——一次尖峰就吃单/滑点
48. **系统级抖动消除清单**：isolcpus + nohz_full + IRQ 亲和 + HugePage + mlockall + 关 C-state，用 cyclictest 验证从几十 µs 压到 µs 内

---

# 第三部分：建议学习节奏

| 阶段 | 时长 | 目标档位 | 关键产出 |
|---|---|---|---|
| **地基** | 1-2 月 | 过 C 档线 | 现代 C++（C1-C2）+ Linux 系统编程（O1）+ STL 实现原理 + gdb/cmake |
| **性能与体系结构** | 2-3 月 | 进 B 档 | 对象模型/CRTP（C3）+ cache/NUMA/虚存（O2-O3）+ perf/火焰图/godbolt + 手写无锁 SPSC + cacheline 对齐实验 |
| **并发与无锁** | 3 月+（最难） | A 档硬核 | C++ 六种 memory_order + 手写 SPSC/MPMC（C4）+ false sharing + TSan 验证 |
| **低延迟天花板** | 项目驱动 | 顶级 Core Dev | 系统调优清单（O8）+ onload/DPDK（O4）+ eBPF 延迟溯源 + tick-to-trade P99.9 优化 |

## 三大「必刷」高频题（基于典型量化 C++ 面经归纳）
1. **手写无锁 SPSC 环形队列**（C4-21）
2. **内存模型 / false sharing / cache line**（C4-18/20）
3. **STL 内部**：vector 扩容、为什么不用 std::map、移动语义（C6-37）

## OS 侧分水岭题
1. **kernel bypass 为什么省延迟、省了哪些开销**（O4-22）
2. **如何精确测量 tick-to-trade 延迟**（O5-30 硬件时间戳）
3. **延迟尖峰溯源**：缺页/中断/调度，怎么定位（O7-41）

---

## 数据透明声明

- **技术知识点本身**（memory_order 语义、false sharing、isolcpus、kernel bypass、HugePages 等）：低延迟系统领域**公认硬知识**，已用官方一手技术文档逐条核验，出处见 `证据_一手出处核验.md`。核心锚点：
  - cache line 64B / `alignas(64)` / `hardware_destructive_interference_size` → Erik Rigtorp《Correctly implementing a ring buffer》原文确认。
  - LMAX Disruptor「false sharing 定义 + ring buffer 预分配 + 50ns/2500 万 msg·s⁻¹ 标杆」→ LMAX 官方技术白皮书原文确认。
  - `isolcpus`/`nohz_full`/HugeTLB/`sched_setaffinity`/`mlockall` → Linux 官方内核参数文档 + man7 手册页原文确认。
  - 六种 `memory_order`、`hardware_destructive_interference_size` → cppreference 标准库定义。
- **「幻方/九坤要求到哪一档」的深度标定**：基于对头部量化低延迟技术栈的**领域认知归纳**，**非真实 JD 原文**。用户 2026-06-30 明确同意跳过 JD 抓取，改以官方技术文档夯实知识深度——故本大纲不假托任何公司 JD，深度切分属经验判断。
- 标注的「面经高频/面试常考」为**对该类岗位典型考点的归纳重构**，非逐字引用。
- **证据纪律**：未使用任何 SEO 营销农场文作证据源；所有引用 URL 经 curl 实测可达 + 原文比对，留痕见证据文件。

---

*生成：参照 AI-Teacher 分阶段课程范式。如需发布为 Notion 专栏（类似 AI-Teacher 课程库），可二次确认后同步。*
