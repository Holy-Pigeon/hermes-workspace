# 上下文治理：从问题到数据结构、流程，再用源码深挖它的精妙设计

> 本文是一篇分析文档（Analysis）。先从第一性原理推导出「上下文应被组织成什么结构、按什么流程治理」，再回到 Claude Code、OpenCode 及一个第三方 Rust 复刻的**真实实现里逐行解剖**——重点不是「常量对没对上」，而是**那些第一性原理推不出、只有撞过生产事故才会写进代码的精妙设计**：半轮切割、字符级断点、双阈值刹车、压缩自身的失败兜底、单消息撑爆窗口的 replay。
>
> 证据级别逐处标注：OpenCode 为完全开源一手源码（clone commit `cd292a4`）；Claude Code 官方不开源，证据来自对本机官方二进制 v2.1.161 的 `strings` 取证；soongenwong/claudecode 为第三方复刻，仅作旁证。

---

## 一、从问题出发

### 1.1 症状

长会话跑到中后段，agent 开始系统性退化：重复犯同一个错、忘记早期定下的约束、把已经被推翻的方案又捡回来、你纠正它越改越乱。这不是模型变笨了，是**输入变脏了**。

### 1.2 根因：上下文不是"越多越好"，而是会衰减的资源

把上下文窗口当成一块固定预算的注意力，三件事在持续侵蚀它：

1. **稀释**：token 越堆越多，早期那几条最重要的信息（用户最初要什么、定下了什么约束）占总量的比例越来越小，模型对它们的注意权重被后来的海量内容摊薄。
2. **噪音累积**：工具调用的冗长返回（整个文件、整页搜索结果、调试输出）是最大的体积来源，但它们的边际价值随时间衰减——十轮前那次 `grep` 的完整输出，现在几乎纯是噪音，却还在占预算、还在分散注意力。
3. **错误锚定**：会话中段一个被推翻的判断，只要还躺在历史里，就可能被模型反复引用，形成"错误一旦进入上下文就阴魂不散"。

还有一个常被忽略的位置效应——**中间塌陷（lost in the middle）**：长上下文里，首部和尾部的信息召回质量明显好于中段。约束如果躺在第 30 轮的某条消息里（既不在最前也不在最近），它的实际生效概率是打折的。

### 1.3 为什么两种朴素做法都不行

- **全量保留**：直接撞上 1.2 的全部问题，且最终撞窗口上限硬截断，截断点是机械的、不挑内容的，极可能把"还有用的约束"和"早就没用的旧工具输出"一起切掉或一起留下。
- **简单截断（只留最近 N 条）**：丢失早期的目标和约束——而这恰恰是长会话里最该保住、又最先被自然遗忘的东西。等于优先保护了最不需要保护的（最近细节本来就还在），牺牲了最需要保护的（最初意图）。

**问题本质于是清晰**：需要一种机制，**区分对待**上下文里不同价值密度的内容——无损保留高价值的、有损压缩中等价值的、直接丢弃低价值的——而不是一刀切。这把我们推向数据结构设计。

---

## 二、数据结构设计（从第一性原理推，先不看任何实现）

### 2.1 第一刀：按"稳定性"分层

内容的第一个本质属性是：它多久会变一次。

- **稳定层（持久）**：系统指令、用户长期偏好、项目级约束、踩过的坑。跨会话都成立，不该参与压缩，应外置到对话流之外（配置 / 记忆 / 文件），每次会话开头注入。
- **易失层（会话内）**：本次任务的具体对话、工具调用、中间产物。这才是需要治理的部分。

意义：**把"约束和目标"从易失层抢救出来钉死在稳定层**，从根上避免稀释（直接回应 1.2 的稀释与中间塌陷——稳定层永远在最前）。

### 2.2 第二刀：把易失层按"价值密度 × 时效"分区

| 区 | 内容 | 处置 |
|---|---|---|
| **保护区（最近）** | 最近几轮的原始对话与工具调用 | 无损保留——细节还热，正在被引用 |
| **可压缩区（较早）** | 更早的对话历史 | 有损压缩成结构化摘要——保留事实、丢弃过程 |
| **可丢弃区（噪音）** | 早期冗长工具输出、被推翻的中间尝试 | 直接清除/截断——价值已衰减到接近零 |

"可丢弃区"与"可压缩区"是**正交**的两个维度：一条很早的消息，文字结论可能进可压缩区被摘要，但它附带的 5000 字工具输出进可丢弃区被直接擦掉。**工具输出值得被单独、更激进地处理**，因为体积最大、衰减最快。

### 2.3 第三刀：可压缩区压成结构化摘要的 schema

压缩不能压成自由散文（散文会再次稀释关键字段、token 效率低）。应压成**固定字段的结构化摘要**，强制把长会话里最易丢、最致命的维度显式拎出来。从问题倒推，schema 至少要有：目标 / 约束与偏好 / 进度 / 关键决策 / 下一步 / 关键上下文 / 相关文件。两条硬规则：**用要点不写散文**、**保留确切路径/命令/报错原文**。

### 2.4 数据结构总览

```
上下文
├── 稳定层（持久，外置，永不压缩，注入在最前）
└── 易失层（会话内，受治理）
      ├── [可丢弃区] 早期冗长工具输出、废弃尝试  → 清除/截断
      ├── [可压缩区] 较早历史                    → 压成结构化摘要(2.3)
      └── [保护区]   最近原文                     → 无损保留
```

摘要不是附属品，而是一等公民——它是可压缩区被折叠后的代表，随会话推进被**增量更新**（旧摘要 + 新历史 → 合并出新摘要），而非每次从头重写。

> **推导到此为止的盲区（后面源码会狠狠补上）**：第一性原理只能推到"保护最近 N 轮"这种**离散、整齐**的边界。但真实世界里"最近 1 轮"可能就是一次贴了整个文件的巨型消息，单独一条就超预算。推导给不出"边界落在一轮内部、甚至一条消息内部怎么办""压缩动作自己失败了怎么办""单条消息就撑爆窗口怎么办"。这些正是下面源码里最有价值的部分。

---

## 三、流程分析（静态结构 → 运转的状态机）

四个问题：何时触发、保留什么、丢弃/压缩什么、如何续接。

### 3.1 何时触发

不能等撞窗口硬上限才动手（那时已在跑偏边缘，且没余量做压缩本身的开销）。合理触发：**当前 token ≥（窗口上限 − 安全缓冲）**。缓冲给"生成摘要"这步留 token，也给压缩后续接留呼吸空间。

### 3.2 一次治理周期的动作序列

1. **prune（擦噪音）**：从最近往回，保护最近一段工具调用，更早的冗长工具输出清空/截断。先擦噪音——最高性价比的瘦身，可能擦完就不必更激进压缩。
2. **select（选保护区）**：从尾部保留最近内容，确定"可压缩区/保护区"分界。
3. **summarize（压历史）**：分界前的历史按 2.3 schema 压成结构化摘要；已有旧摘要则增量合并。
4. **assemble（重组）**：稳定层 + 结构化摘要 + 保护区原文，拼成新上下文。

### 3.3 如何续接（最易被忽略、却最关键）

压缩完重启，必须给模型明确指令：**直接从断点续做，不复述摘要、不寒暄式回顾**。否则模型拿到摘要的第一反应往往是"让我回顾一下之前……"，白费一轮注意力复述你刚给它的东西。这是把"省下的预算"兑现成"干活"的闸门。

---

## 四、源码深挖：那些第一性原理推不出的精妙设计

下面不再做"常量核对"，而是**逐个解剖那些只有撞过生产事故才会写进代码的设计**。每一处都先问"它在防什么坑"。

### 4.0 先看一个反直觉的工程哲学：触发判断故意用粗估

`packages/core/src/util/token.ts` 全文就两行：

```
const CHARS_PER_TOKEN = <常数>
export const estimate = (input: string) => Math.max(0, Math.round(input.length / CHARS_PER_TOKEN))
```

**整个 compaction 的 token 计算，从头到尾不调用真正的 tokenizer，只用「字符数 ÷ 常数」粗估。** 这是个值得记下的取舍：触发与切分判断要在每一步、对每一条消息反复跑，若用精确 tokenizer 会很贵；而**判断"要不要压缩、在哪切"本就不需要精确**——反正上面留了 20000 token 的 buffer 兜底。用 O(1) 粗估换性能，把精确性让渡给安全余量。这是"哪里该精确、哪里该偷懒"的典型工程判断，纯理论推导不会告诉你这件事。

### 4.1 触发：可用预算 = 输入上限 − 缓冲，且缓冲本身是 min 出来的

`overflow.ts`：

```
const COMPACTION_BUFFER = 20_000
export function usable(input) {
  const reserved = input.cfg.compaction?.reserved
    ?? Math.min(COMPACTION_BUFFER, maxOutputTokens(input.model, input.outputTokenMax))
  return input.model.limit.input
    ? Math.max(0, input.model.limit.input - reserved)
    : Math.max(0, context - maxOutputTokens(...))
}
```

**精妙点 1：缓冲不是写死的 20000，而是 `min(20000, 该模型的最大输出 token)`。** 为什么？buffer 的真实用途是"给模型这一轮的输出留地方"。如果某个模型最大输出只有 8000，却预留 20000，就白白浪费了 12000 的可用上下文。取两者较小值，保证"既够装下输出、又不浪费"。

**精妙点 2：`limit.input` 缺失时降级用 `context − maxOutput`。** 不同 provider 报告的字段不齐（有的给 input 上限，有的只给总 context），代码对两种都兜了底，且全程 `Math.max(0, ...)` 防止算出负预算。这是面对"上游数据不规整"的防御性编程。

### 4.2 保护区不是"最近 N 轮"，而是"连续 token 预算 + 半轮切割"

这是原文最该补的一处。`select` + `splitTurn`（`opencode/src/session/compaction.ts`）：

```
function preserveRecentBudget({ cfg, model }) {
  return cfg.compaction?.preserve_recent_tokens
    ?? Math.min(MAX_PRESERVE_RECENT_TOKENS,
         Math.max(MIN_PRESERVE_RECENT_TOKENS, Math.floor(usable(...) * 0.25)))
}
```

保护区预算不是"2 轮"这种离散值，而是 **usable 的 25%，再用 `[MIN, MAX]` 双向夹逼**。为什么夹？小模型 25% 可能小到放不下半条消息（下限保底），大模型 25% 可能大到把该压的也留下（上限封顶）。这是"按比例自适应 + 绝对边界兜底"的组合拳。

更精妙的是**装不下一整轮时的"半轮切割"**：

```
for (let i = recent.length - 1; i >= 0; i--) {
  if (total + size <= budget) { total += size; keep = 整轮; continue }
  // 这一轮整个放不下，但还有 remaining 预算
  const split = yield* splitTurn({ turn, budget: budget - total, ... })
  if (split) keep = split        // 在轮内找一条消息当新边界
  break
}
```

`splitTurn` 会在这一轮内部**从前往后逐条消息试**，找到"从某条开始到轮尾恰好塞进剩余预算"的切点。**于是保护区的边界可以落在一轮的中间**——前半轮进可压缩区被摘要，后半轮进保护区被原文保留。第一性原理只能推到"保留最近 N 轮"，而真实代码做到了"保留最近 N token，边界精确到轮内某条消息"。

**为什么必须这么做？** 设想最近一轮是 agent 一口气调了 8 个工具、贴了几个大文件，单这一轮就 30000 token、远超保护预算。"只保护整轮"会面临二选一：要么整轮留下（撑爆预算）、要么整轮压掉（丢失最近的关键上下文）。半轮切割是唯一的出路。

### 4.3 字符级断点：core 包把切割做到一条消息内部

`opencode` 包切到"轮内某条消息"还不是极限。`core/src/session/compaction.ts` 的 `select` 把同样的思路推到**单条消息内部的字符级**：

```
for (let index = conversation.length - 1; index >= 0; index--) {
  const next = total + Token.estimate(conversation[index])
  if (next > tokens) {
    const remaining = Math.max(0, tokens - total) * 4   // token → char（×4）
    if (remaining > 0) {
      splitPrefix = conversation[index].slice(0, -remaining)  // 前半 → head（被摘要）
      splitSuffix = conversation[index].slice(-remaining)     // 后半 → recent（保原文）
      split = index + 1
    }
    break
  }
  total = next; split = index
}
```

当某条消息**自己就跨越了保护区边界**，它被从中间劈开：尾部 `remaining*4` 个字符（保留原文进 recent），剩下的头部进 head 被摘要。`*4` 是 token→字符的反向换算（呼应 4.0 的 CHARS_PER_TOKEN）。**这是"保护区边界落在一条消息内部"的字符级实现**——连一条消息都不放过，能保多少最近原文就保多少。

### 4.4 prune 的三重刹车：防无效写、防重复擦、有白名单

`prune` 函数（`opencode/src/session/compaction.ts`）远不止"擦掉旧工具输出"：

```
export const PRUNE_PROTECT = 40_000   // 从尾部保护 40k token 的工具调用
export const PRUNE_MINIMUM = 20_000   // 省不到 20k 就整个不擦
const PRUNE_PROTECTED_TOOLS = ["skill"]

loop: for (倒序遍历消息) {
  if (role === "user") turns++
  if (turns < 2) continue                          // 最近 2 轮完全不碰
  if (role === "assistant" && summary) break loop  // 撞到上一次压缩点，停
  for (倒序遍历 parts) {
    if (part 非 completed 工具) continue
    if (PRUNE_PROTECTED_TOOLS.includes(part.tool)) continue   // skill 永不擦
    if (part.state.time.compacted) break loop                 // 撞到已擦过的，停
    total += estimate(part.output)
    if (total <= PRUNE_PROTECT) continue            // 前 40k 受保护
    pruned += estimate; toPrune.push(part)
  }
}
if (pruned > PRUNE_MINIMUM) { 实际擦除 }            // 关键：省不够就不动手
```

四个第一性原理推不出的细节：

1. **`PRUNE_MINIMUM` 的"省不够就不擦"**：擦除是有成本的写操作（更新存储、可能触发事件）。如果遍历一圈发现总共才能省下 5000 token（< 20000），**宁可一条都不擦**——避免为蝇头小利做一堆 I/O。这是"不做负 ROI 的操作"。
2. **`time.compacted` 标记防重复擦**：每条被擦的工具输出打时间戳，下次 prune 倒序撞到第一条带标记的就 `break loop`。保证 prune 永远只处理"上次压缩点之后新产生的"工具输出，是**增量**而非每次全量重扫。
3. **`skill` 白名单**：不是所有工具输出都是噪音。skill 加载的是高价值指令（怎么做某件事），擦了等于让 agent 失忆。**对"工具输出=噪音"这个假设打了个补丁**——区分"数据型输出"（可擦）和"指令型输出"（保留）。
4. **撞到 `summary` 消息就停**：prune 的作用域被严格限制在"上一次压缩之后"，不去动已被摘要覆盖的远古历史（那些马上要被整体折叠掉，擦它没意义）。

### 4.5 增量合并的真实数据结构：hidden 集合

原文只写了"prompt 层让模型合并旧摘要"，但**多次压缩在数据结构上怎么衔接**才是硬骨头。`completedCompactions` + `hidden`（`processCompaction`）：

```
const prior = completedCompactions(history)            // 找出所有已完成的压缩对
const hidden = new Set(prior.flatMap(i => [i.userIndex, i.assistantIndex]))
const previousSummary = prior.at(-1)?.summary          // 取最后一次摘要
const selected = yield* select({
  messages: history.filter((_, index) => !hidden.has(index)),  // 排除已压缩消息
  ...
})
```

精妙处：历史里"已经被某次压缩覆盖过的那些原始消息"用 `hidden` 索引集合**排除在本次 select 之外**——它们的信息已经活在 `previousSummary` 里了，再喂一遍就是重复。于是每次压缩只对"上次摘要之后的新增量"做选择，再把新增量 merge 进旧摘要。**这是"增量更新而非全量重写"在数据结构层的落地**，比 prompt 里写一句"merge in the new facts"硬得多。

### 4.6 最该补的一节：压缩自己失败了怎么办

第一性原理假设"压缩总会成功"，但生产代码必须回答三个失败场景。

**场景 A：连摘要 prompt 都塞不下。** `core` 包 `compactAfterOverflow`：

```
const summaryOutput = Math.min(output || SUMMARY_OUTPUT_TOKENS, SUMMARY_OUTPUT_TOKENS)
if (Token.estimate(summaryPrompt) > context - summaryOutput) return false   // 放弃压缩
```

如果要喂给"摘要模型"的 prompt 本身就超窗口，**直接放弃压缩并返回 false**，不做注定失败的 LLM 调用。先验证可行性再动手。

**场景 B：单条消息就撑爆窗口（overflow replay）。** `opencode` 包 `processCompaction` 里 `input.overflow` 分支：

```
if (input.overflow) {
  // 从 parent 往前找最后一条「非压缩的用户消息」，把它摘出来 replay
  for (let i = idx - 1; i >= 0; i--) {
    if (msg.role === "user" && 非压缩) { replay = msg; messages = slice(0, i); break }
  }
}
```

当某次请求因为"单条用户消息太大"（比如贴了超大文件/图片）直接撑爆，普通压缩救不了（最近这条本身就超窗口）。处理是：**把这条用户消息抽出来作为 `replay`，压缩它前面的所有历史，压完再把这条重新接上重放一次**。配合 `stripMedia: true` 在转模型消息时**剥离所有媒体附件**（图片等是体积黑洞）。

**场景 C：剥了媒体还是塞不下——明确停机，不假装成功。**

```
if (result === "compact") {   // 压缩流程回报"还是 overflow"
  processor.message.error = new ContextOverflowError({
    message: replay
      ? "Conversation history too large to compact - exceeds model context limit"
      : "Session too large to compact - context exceeds model limit even after stripping media",
  }).toObject()
  return "stop"
}
```

走到这一步，系统**诚实地报错停机**，而不是悄悄截断一段然后继续跑（那样会产出基于残缺上下文的错误结果）。两条错误信息还**区分了是 replay 场景还是普通场景**，方便定位。这正是合伙人哲学里那条"查不到/做不到就明说，不编造"在工程上的体现。

### 4.7 续接细节：synthetic 标记 + overflow 专属提示语

续接那条消息不是普通用户消息：

```
yield* session.updatePart({
  ...,
  metadata: { compaction_continue: true },   // 内部标记
  synthetic: true,                            // 标记为合成、非用户真实输入
  text: (input.overflow
    ? "The previous request exceeded the provider's size limit due to large media attachments. ... suggest they try again with smaller or fewer files.\n\n"
    : "") + "Continue if you have next steps, or stop and ask for clarification if you are unsure how to proceed.",
})
```

两个细节：`synthetic: true` + `compaction_continue` 标记让下游 provider 插件能**区分"系统自动续接"和"用户真打了字"**（避免把系统的续接指令误当用户意图计费/记录）；overflow 场景**专门追加一句话**提示模型"刚才有大附件被移除了，如果用户在问那些附件，告诉他文件太大、建议换小的"——把"为什么上下文里突然少了东西"显式告诉模型，免得它困惑。

---

## 五、三家对照：差异在工程取舍，骨架是同一个

| 设计点 | OpenCode（开源一手） | Claude Code（官方二进制） | Rust 复刻（旁证） |
|---|---|---|---|
| 触发 = 上限 − 缓冲 | 命中，缓冲 `min(20000, maxOutput)` 动态算 | 命中，阈值取"设定值与模型窗口较小者" | 命中，写死 10000 token |
| 保护区边界 | **连续 token 预算 + 半轮切割 + 字符级断点** | 近因加权（"特别关注最近消息"） | 离散：保留最近 4 条 |
| prune 工具输出 | **三重刹车（MINIMUM/compacted标记/skill白名单）+ 40k 保护** | 隐含 | — |
| 结构化摘要 schema | 7 字段，含 Done/InProgress/Blocked 三态进度 | 7 段（Intent/Concepts/Files/Errors/...） | 命中 |
| 增量合并 | **hidden 索引集合排除已压缩消息** | prompt 层 merge | `merge_compact_summaries` 函数 |
| 压缩失败兜底 | **三场景全覆盖（预检/replay/停机报错）** | 隐含 | — |
| 续接"直接干活" | synthetic 标记 + overflow 专属提示 | 摘要前置续接 | 专设 `DIRECT_RESUME_INSTRUCTION` 常量 |
| 安全约束 | skill 白名单保护指令型输出 | **"All user messages" 段 + 安全约束逐字保留** | — |
| token 计算 | **故意用字符粗估换性能** | 未知 | 同为估算 |

**Claude Code 二进制取证补充**：摘要 prompt 原文要求"This summary will be placed at the start of a continuing session"（摘要前置续接），7 段结构为 `1 Primary Request and Intent / 2 Key Technical Concepts / 3 Files and Code Sections / 4 Errors and fixes / 5 Problem Solving / 6 All user messages / 7 Pending Tasks`；其中**第 6 段"All user messages"要求逐字列出所有非工具用户消息，并明确"Preserve any security-relevant instructions or constraints verbatim so they remain in effect after compaction"**——把"约束逐字保留"提到比 OpenCode 更硬的位置（专列一段、明令 verbatim）。第 3 段还要求"Pay special attention to the most recent messages"，与保护区的近因加权呼应。

**结论**：三家在**结构骨架上完全同构**（分层、触发缓冲、保护区、结构化摘要、增量合并、直接续接），差异全部集中在**工程取舍**——缓冲是动态算还是写死、保护区是 token 连续切还是离散数条、prune 做不做、失败怎么兜。骨架同构反向证明：第二三节的推导抓到的是问题本身的不变量；而第四节那些差异，才是各家在生产环境里被真实流量打磨出来的、值得逐个学习的工程智慧。

---

## 六、对实践的启示（手动操作 agent 时）

1. **约束和目标外置**——写进项目级文件 / 记忆，别指望对话历史记住。学 Claude Code 把安全/硬约束**逐字**钉死，而不只是"提一句"。
2. **手动导出 md 重启时对齐结构化 schema**——目标/约束/进度(分 Done/InProgress/Blocked)/决策/下一步/关键上下文/相关文件，用要点、留确切路径命令报错原文。
3. **导出时第一个筛掉冗长工具输出和废弃尝试**——但**给"指令型内容"留白名单**（你之前加载的 skill、定下的规则别擦），学 OpenCode 的 skill 保护。
4. **主动压缩优于被动等阈值**——在感觉 AI 开始重复/遗忘的早期就重启，给压缩本身留余量（对应 buffer 哲学）。
5. **保护区按"信息量"而非"轮数"留**——如果最近一轮特别大，宁可只留它的关键尾部（半轮切割的手动版），而不是机械数"留最近 3 轮"。
6. **新会话第一句明令"直接续做、别复述我给的 md"**——把省下的预算兑现成干活。
7. **一任务一会话**——任务边界即会话边界，避免跨任务废弃方案互相污染（对应"错误锚定"根因）。

---

## 附：证据清单

- **OpenCode**（完全开源一手，clone commit `cd292a4`）：
  - `packages/opencode/src/session/overflow.ts`：`COMPACTION_BUFFER=20000`、`usable`（缓冲 `min(buffer, maxOutput)`、limit.input 缺失降级、Math.max(0) 防负）、`isOverflow`。
  - `packages/opencode/src/session/compaction.ts`：`PRUNE_PROTECT=40000`、`PRUNE_MINIMUM=20000`、`PRUNE_PROTECTED_TOOLS=["skill"]`、`preserveRecentBudget`（usable×25% 夹在 MIN/MAX）、`select`/`splitTurn`（半轮切割）、`prune`（三重刹车 + time.compacted 标记 + 撞 summary 停）、`completedCompactions`/`hidden`（增量合并）、`processCompaction`（overflow replay + ContextOverflowError 停机 + synthetic 续接）。
  - `packages/core/src/session/compaction.ts`：`SUMMARY_TEMPLATE`（7 字段 + 三态进度 + 两条规则）、`select`（字符级断点 splitPrefix/splitSuffix）、`buildPrompt`（增量合并 prompt）、`compactAfterOverflow`（摘要 prompt 预检 return false）。
  - `packages/core/src/util/token.ts`：`estimate = length / CHARS_PER_TOKEN`（字符粗估）。
  - `packages/opencode/src/session/message-v2.ts`：`stripMedia` / `toolOutputMaxChars` 在 `toModelMessagesEffect` 的落地。
- **Claude Code**（官方不开源，本机二进制 v2.1.161 `strings` 取证）：摘要 prompt 原文、7 段式结构、`All user messages` 段的 verbatim 安全约束要求、"most recent messages"近因加权、`Auto-compact window size`/`wasCompacted` 常量。
- **soongenwong/claudecode**（第三方 Rust 复刻，旁证）：`rust/crates/runtime/src/compact.rs`——`CompactionConfig{ preserve_recent_messages:4, max_estimated_tokens:10000 }`、`should_compact`、`merge_compact_summaries`、`COMPACT_DIRECT_RESUME_INSTRUCTION` 续接常量。

---
文档类型：分析（Analysis）
记录日期：2026-06-22
成熟度：验证过（三份真实实现一手/二进制取证交叉验证，第四节逐函数解剖）
