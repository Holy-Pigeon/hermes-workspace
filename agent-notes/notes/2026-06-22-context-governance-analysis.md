# 上下文治理：从问题到数据结构、流程，再用源码验证

> 本文是一篇分析文档（Analysis），不是单点实战经验条目。写法上先从问题与第一性原理推导出「上下文应该被组织成什么数据结构、按什么流程运转」，最后才请出 Claude Code、OpenCode 及一个第三方 Rust 复刻的真实实现来验证或证伪这套推导。
>
> 证据级别在文中逐处标注：OpenCode 为完全开源一手源码；Claude Code 官方不开源，证据来自对本机官方二进制 v2.1.161 的 `strings` 取证；soongenwong/claudecode 为第三方复刻，仅作旁证。

---

## 一、从问题出发

### 1.1 症状

长会话跑到中后段，agent 开始系统性退化：重复犯同一个错、忘记早期定下的约束、把已经被推翻的方案又捡回来、你纠正它越改越乱。这不是模型变笨了，是**输入变脏了**。

### 1.2 根因：上下文不是"越多越好"，而是会衰减的资源

把上下文窗口当成一块固定预算的注意力，三件事在持续侵蚀它：

1. **稀释**：token 越堆越多，早期那几条最重要的信息（用户最初要什么、定下了什么约束）占总量的比例越来越小，模型对它们的注意权重被后来的海量内容摊薄。
2. **噪音累积**：工具调用的冗长返回（整个文件、整页搜索结果、调试输出）是最大的体积来源，但它们的边际价值随时间衰减——十轮前那次 `grep` 的完整输出，现在几乎纯是噪音，却还在占预算、还在分散注意力。
3. **错误锚定**：会话中段一个被推翻的判断，只要还躺在历史里，就可能被模型反复引用，形成"错误一旦进入上下文就阴魂不散"。

还有一个常被忽略的位置效应——**中间塌陷（lost in the middle）**：长上下文里，首部和尾部的信息召回质量明显好于中段。也就是说，约束如果躺在第 30 轮的某条消息里（既不在最前也不在最近），它的实际生效概率是打折的。

### 1.3 为什么两种朴素做法都不行

- **全量保留**：直接撞上 1.2 的全部问题，且最终撞窗口上限硬截断，截断点是机械的、不挑内容的，极可能把"还有用的约束"和"早就没用的旧工具输出"一起切掉或一起留下。
- **简单截断（只留最近 N 条）**：丢失早期的目标和约束——而这恰恰是长会话里最该保住、又最先被自然遗忘的东西。等于优先保护了最不需要保护的（最近细节本来就还在），牺牲了最需要保护的（最初意图）。

**问题的本质于是清晰了**：我们需要一种机制，能**区分对待**上下文里不同价值密度的内容——无损保留高价值的、有损压缩中等价值的、直接丢弃低价值的——而不是一刀切地全留或全截。这把我们直接推向数据结构设计。

---

## 二、数据结构设计（抛开任何现成实现，从第一性原理推）

如果让我们从零设计一套"会自我治理的上下文"，它不该是一个扁平的消息数组，而应该是一个**分层、分区、带生命周期的结构**。

### 2.1 第一刀：按"稳定性"分层

内容的第一个本质属性是：它多久会变一次。

- **稳定层（持久）**：系统指令、用户的长期偏好、项目级约束、踩过的坑。这些跨会话都成立，根本不该参与压缩，应该外置到对话流之外（配置 / 记忆 / 文件），每次会话开头注入。
- **易失层（会话内）**：本次任务的具体对话、工具调用、中间产物。这才是需要治理的部分。

这一刀的意义：**把"约束和目标"从易失层里抢救出来，钉死在稳定层**，从根上避免它们被稀释（直接回应 1.2 的稀释问题和 1.2 的中间塌陷——稳定层永远在最前）。

### 2.2 第二刀：把易失层按"价值密度 × 时效"分区

易失层内部不是均质的，按"现在还值不值得逐字保留"切成三区：

| 区 | 内容 | 处置 |
|---|---|---|
| **保护区（最近）** | 最近几轮的原始对话与工具调用 | 无损保留——细节还热，正在被引用 |
| **可压缩区（较早）** | 更早的对话历史 | 有损压缩成结构化摘要——保留事实、丢弃过程 |
| **可丢弃区（噪音）** | 早期冗长工具输出、被推翻的中间尝试 | 直接清除/截断——价值已衰减到接近零 |

注意"可丢弃区"与"可压缩区"是**正交**的两个维度：一条很早的消息，它的文字结论可能进可压缩区被摘要，但它附带的 5000 字工具输出进可丢弃区被直接擦掉。**工具输出值得被单独、更激进地处理**，因为它体积最大、衰减最快。

### 2.3 第三刀：可压缩区压成什么——结构化摘要的 schema

压缩不能压成一段自由散文（散文会再次稀释关键字段、且 token 效率低）。应该压成**固定字段的结构化摘要**，强制把长会话里最易丢、最致命的维度显式拎出来。从问题倒推，这个 schema 至少要有：

- **目标（Goal）**：用户到底要什么——最该保、最先被稀释的。
- **约束与偏好（Constraints）**：定下的规则、口径、禁忌——第二该保。
- **进度（Progress）**：已完成 / 进行中 / 受阻——避免重复劳动。
- **关键决策（Key Decisions）**：决定了什么 + 为什么——避免重蹈被推翻的方案。
- **下一步（Next Steps）**：有序待办——续接的落点。
- **关键上下文（Critical Context）**：重要技术事实、报错原文、待解问题。
- **相关文件（Relevant Files）**：确切路径 + 为什么重要。

并且要有两条硬规则：**用要点不写散文**（信噪比 + token 效率）、**保留确切路径/命令/报错原文**（这些东西一旦被"意译"就失去可执行性）。

### 2.4 数据结构总览

```
上下文
├── 稳定层（持久，外置，永不压缩，注入在最前）
│     ├── 系统指令 / 角色
│     ├── 用户长期偏好与约束
│     └── 跨会话的坑与事实（memory / skill / 文件）
│
└── 易失层（会话内，受治理）
      ├── [可丢弃区] 早期冗长工具输出、废弃尝试  → 清除/截断
      ├── [可压缩区] 较早历史                    → 压成结构化摘要(2.3 的 schema)
      └── [保护区]   最近 N 轮原文                → 无损保留
```

这套结构里，"摘要"不是附属品，而是一等公民——它是可压缩区被折叠后的代表，且会随会话推进被**增量更新**（旧摘要 + 新历史 → 合并出新摘要），而不是每次从头重写。

---

## 三、流程分析（这套结构怎么运转）

把上面的静态结构变成一台运转的状态机，需要回答四个问题：何时触发、保留什么、丢弃/压缩什么、如何续接。

### 3.1 何时触发

不能等撞到窗口硬上限才动手（那时已在跑偏边缘，且没有余量做压缩本身的开销）。合理的触发条件是：**当前 token 数 ≥（窗口上限 − 安全缓冲）**。缓冲的意义是给"生成摘要"这步本身留出 token，也给压缩后的续接留呼吸空间。

### 3.2 一次治理周期的动作序列

1. **prune（擦噪音）**：从最近往回数，保护住最近一段的工具调用，更早的冗长工具输出直接清空或截断到上限字符数。先擦噪音，因为这是最高性价比的瘦身，可能擦完就不需要更激进的压缩了。
2. **select（选保护区）**：从尾部保留最近 N 轮原文，确定"可压缩区"与"保护区"的分界线。
3. **summarize（压历史）**：把分界线之前的历史，按 2.3 的 schema 压成结构化摘要；若已存在旧摘要，则与新历史**合并增量更新**。
4. **assemble（重组）**：稳定层（最前）+ 结构化摘要 + 保护区原文（最后），拼成新的上下文。

### 3.3 如何续接（最容易被忽略、却最关键的一步）

压缩完重启，必须给模型一条明确指令：**直接从断点续做，不要复述摘要、不要寒暄式回顾**。否则模型拿到摘要后的第一反应往往是"让我回顾一下我们之前……"，白白浪费一轮注意力去复述你刚给它的东西。这一步是把"省下来的预算"真正兑现成"干活"的闸门。

### 3.4 推导小结（接下来要验证的清单）

到这里，纯靠"问题→第一性原理"我们推出了一套设计，它给出了若干**可证伪的断言**：

- (A) 上下文该分稳定层 / 易失层，约束目标应外置。
- (B) 触发条件是"窗口上限 − 安全缓冲"，而非撞满才动。
- (C) 工具输出应被单独、更激进地清理（prune）。
- (D) 保留最近 N 轮原文（保护区）。
- (E) 较早历史压成**结构化字段摘要**，字段大致是 目标/约束/进度/决策/下一步/上下文/文件。
- (F) 摘要规则：要点不写散文、保留确切路径命令报错原文。
- (G) 摘要随会话**增量合并**而非重写。
- (H) 续接时强制"直接干活、不复述摘要"。

下面逐条拿三份真实实现对照。

---

## 四、源码验证

### 4.1 OpenCode（完全开源，TypeScript，一手源码）

> 证据：github.com/sst/opencode，本地 clone commit `cd292a4`，下列常量为直接读到的源码。

**验证 (B) 触发条件 —— 命中。**
`packages/opencode/src/session/overflow.ts`：

```
const COMPACTION_BUFFER = 20_000
function usable(...) {
  const reserved = cfg.compaction?.reserved
    ?? Math.min(COMPACTION_BUFFER, maxOutputTokens(model))
  return model.limit.input - reserved   // 上限 − 缓冲
}
function isOverflow(...) { return count >= usable(input) }
```

与推导 (B) 完全一致：可用预算 = 模型输入上限 − 保留缓冲（默认 20000 token），当前 token ≥ 可用预算即触发。我们推"窗口上限减一个安全缓冲"，它正是这么实现的，缓冲默认值都给到了。

**验证 (C) prune 工具输出 —— 命中，且比推导更细。**
`packages/opencode/src/session/compaction.ts`：

```
export const PRUNE_PROTECT = 40_000
const TOOL_OUTPUT_MAX_CHARS = 2_000
const PRUNE_PROTECTED_TOOLS = ["skill"]
```

从后往前保护最近 `PRUNE_PROTECT=40000` token 的工具调用，更早的工具输出被清掉；单条工具输出还有 `2000` 字符的硬上限（超出截断标 `[truncated]`）。一个我没推到的工程细节：`skill` 类工具输出被列入**保护名单**永不擦——因为 skill 内容是高价值指令而非噪音。这印证了推导 2.2 "工具输出应被单独、更激进处理"，且补充了"不是所有工具输出都是噪音，要有白名单"这一层。

**验证 (D) 保护区 —— 命中。**

```
const DEFAULT_TAIL_TURNS = 2
const limit = cfg.compaction?.tail_turns ?? DEFAULT_TAIL_TURNS
```

默认保留最近 2 轮原文，正是推导的"保护区"。

**验证 (E)(F) 结构化摘要 schema —— 高度命中，几乎逐字对上。**
`packages/core/src/session/compaction.ts` 的 `SUMMARY_TEMPLATE`，字段为：

```
## Goal
## Constraints & Preferences
## Progress
## Key Decisions
## Next Steps
## Critical Context
## Relevant Files
```

并附两条规则：

```
- Use terse bullets, not prose paragraphs.
- Preserve exact file paths, commands, error strings, and identifiers when known.
```

这是本文最强的一处验证：我们在第二节**没有看任何源码**、纯从"长会话最易丢什么"倒推出的七个字段（目标/约束/进度/决策/下一步/关键上下文/相关文件），与 OpenCode 生产代码里的模板**字段几乎一一对应**；连两条硬规则（要点不写散文、保留确切路径命令报错原文）都和推导 (F) 逐字吻合。这说明这套 schema 不是某家的随意选择，而是问题结构本身逼出来的解。

**验证 (G) 增量合并 —— 命中。**
同文件 line 169：存在旧摘要时，prompt 为 *"Update the anchored summary below ... Preserve still-true details, remove stale details, and merge in the new facts"*——保留仍成立的、删除过时的、并入新事实。正是推导的"增量更新而非重写"。

### 4.2 Claude Code（官方不开源，二进制取证）

> 证据：本机官方二进制 `@anthropic-ai/claude-code-darwin-arm64/claude`，v2.1.161，218MB，下列为 `strings` 抠出的真实嵌入字符串。

**验证 (B) 触发 —— 命中（行为级证据）。**
二进制含常量 `Auto-compact window size`、`wasCompacted`，以及说明串：*"Auto-compact summarizes the conversation when context usage approaches this limit. The actual threshold is the minimum of this setting and your model's maximum context window."*——接近上限自动触发，阈值取设定值与模型窗口的较小者。与推导 (B)"接近上限触发"一致。

**验证 (E)(H) 摘要结构与续接 —— 命中，且揭示一个我没推到的安全设计。**
摘要 prompt 原文开头：

> "Your task is to create a detailed summary of this conversation. This summary will be placed at the start of a continuing session; newer messages that build on this context will follow after your summary..."

即"摘要置于续接会话开头、后续消息接在其后"——直接验证 (H) 的"摘要前置 + 续接"。其摘要结构是 7 段式：

```
1. Primary Request and Intent
2. Key Technical Concepts
3. Files and Code Sections
4. Errors and fixes
5. Problem Solving
6. All user messages
7. Pending Tasks
```

对照推导 (E)：`1 Primary Request and Intent` = 目标，`7 Pending Tasks` = 下一步，`3 Files and Code Sections` = 相关文件，`4 Errors and fixes` = 关键上下文。字段命名不同但骨架同构。

**两个我没推到、值得记下的设计**：
- **第 6 段 "All user messages"** 要求列出**所有**非工具结果的用户消息，且原文明确：*"Preserve any security-relevant instructions or constraints verbatim so they remain in effect after compaction."*——安全相关的指令/约束必须**逐字保留**，以便压缩后仍然生效。这是对推导 2.1"约束要保住"的一个更硬的强化：不只是进摘要，而是**逐字进摘要、专列一段**。
- **第 3 段** 要求"Pay special attention to the most recent messages"，把"近因加权"也写进了摘要指令——与保护区(D)形成呼应：最近的内容不仅原文保留，连进摘要时也要被重点对待。

### 4.3 soongenwong/claudecode（第三方 Rust 复刻，旁证）

> 证据级别：该仓库 README 自述为 "an independent open-source implementation inspired by Claude Code, not the official Anthropic product"。**不能当官方源码**，仅作"同一模式被独立重现"的旁证。下列来自 `rust/crates/runtime/src/compact.rs`。

**验证 (B)(D) 触发与保护区 —— 命中（阈值写得最直白）。**

```
CompactionConfig { preserve_recent_messages: 4, max_estimated_tokens: 10_000 }
fn should_compact(...) -> bool {
    compactable.len() > preserve_recent_messages   // 可压缩消息 > 4 条
      && estimated_tokens >= max_estimated_tokens   // 且 ≥ 10000 token
}
```

保留最近 4 条（保护区 D），且需同时满足"有足够多可压缩消息"和"token 达阈值"才动手（触发 B）。注意它的阈值是写死的保守值（10000 token / 4 条），不像 OpenCode 那样按模型窗口动态算——这正好印证推导 3.1 的"阈值是工程取舍"，不同实现取舍不同。

**验证 (G)(H) 合并与续接 —— 命中。**

```
COMPACT_CONTINUATION_PREAMBLE: "This session is being continued from a previous conversation that ran out of context..."
COMPACT_DIRECT_RESUME_INSTRUCTION: "Continue the conversation from where it left off without asking the user any further questions. Resume directly — do not acknowledge the summary, do not recap what was happening, and do not preface with continuation text."
fn compact_session: ... merge_compact_summaries(existing_summary, &summarize_messages(removed)) ...
```

`merge_compact_summaries` 验证 (G) 增量合并；`COMPACT_DIRECT_RESUME_INSTRUCTION` 是对推导 (H) 最直白的一处实现——"直接续做、不许致谢摘要、不许复盘、不许写续接套话"，把我们说的"续接闸门"写成了一条强制指令。

### 4.4 验证结论汇总

| 推导断言 | OpenCode（开源一手） | Claude Code（官方二进制） | Rust 复刻（旁证） |
|---|---|---|---|
| (A) 稳定层/易失层分层 | 部分（skill 白名单体现） | 强命中（安全约束逐字保留） | — |
| (B) 上限−缓冲触发 | 命中（缓冲 20000） | 命中（取设定与窗口较小值） | 命中（10000/4 写死） |
| (C) prune 工具输出 | 命中（PRUNE_PROTECT 40000 + 2000 字上限 + skill 白名单） | 隐含 | — |
| (D) 保护区最近 N 轮 | 命中（tail 2 轮） | 命中（近因加权） | 命中（4 条） |
| (E) 结构化字段摘要 | 强命中（7 字段几乎逐字对上） | 命中（7 段同构） | 命中 |
| (F) 要点不写散文/留原文 | 命中（逐字吻合） | 命中 | — |
| (G) 增量合并摘要 | 命中 | 隐含 | 命中（merge 函数） |
| (H) 直接续做不复述 | 隐含 | 命中（摘要前置续接） | 强命中（专设指令） |

八条可证伪断言，**没有一条被证伪**；其中 (E)(F) 字段级几乎逐字命中，是最强证据——说明这套数据结构是问题本身逼出来的，不是抄来的。三家实现的差异集中在**工程参数取舍**（缓冲大小、阈值是动态还是写死、保护几轮），而非**结构原理**，这恰恰反向证明了第二、三节推导抓到的是不变量。

---

## 五、对实践的启示

把上面的原理落到日常手动操作（不依赖产品自动 compaction 时）：

1. **约束和目标外置**——写进项目级文件 / 记忆，别指望对话历史记住。对应稳定层(A)，且学 Claude Code 把安全/硬约束逐字钉住。
2. **手动导出 md 重启时，对齐结构化 schema**——目标/约束/进度/决策/下一步/关键上下文/相关文件，用要点、留确切路径命令报错原文。这是三家共识的摘要模板。
3. **导出时第一个该筛掉的是冗长工具输出和废弃尝试**——它们是 prune 的头号目标，价值衰减最快。
4. **主动压缩优于被动等阈值**——在感觉 AI 开始重复/遗忘的早期就重启，别等撞窗口上限。
5. **新会话第一句明令"直接续做、别复述我给的 md"**——把省下的预算兑现成干活，这是 (H) 的手动版。
6. **一任务一会话**——任务边界即会话边界，避免跨任务的废弃方案互相污染（对应"错误锚定"根因）。

---

## 附：证据清单

- OpenCode：`packages/opencode/src/session/overflow.ts`（COMPACTION_BUFFER=20000、usable、isOverflow）、`packages/opencode/src/session/compaction.ts`（PRUNE_PROTECT=40000、TOOL_OUTPUT_MAX_CHARS=2000、PRUNE_PROTECTED_TOOLS=["skill"]、DEFAULT_TAIL_TURNS=2）、`packages/core/src/session/compaction.ts`（SUMMARY_TEMPLATE 七字段 + 两条规则 + 增量合并 prompt）。完全开源一手，clone commit cd292a4。
- Claude Code：官方二进制 v2.1.161，`strings` 取证——摘要 prompt 原文、7 段式结构、`All user messages` 段的 verbatim 安全约束要求、`Auto-compact window size` 等常量。官方不开源，二进制取证。
- soongenwong/claudecode：`rust/crates/runtime/src/compact.rs`（CompactionConfig 默认 preserve_recent_messages=4 / max_estimated_tokens=10000、should_compact、merge_compact_summaries、两条续接常量）。第三方复刻，旁证。

---
文档类型：分析（Analysis）
记录日期：2026-06-22
成熟度：验证过（三份真实实现一手/二进制取证交叉验证）
