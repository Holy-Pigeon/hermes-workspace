## 经验主题：长会话跑偏时，导出成果 md → 新会话读 md 续做 —— 与 Claude Code / OpenCode 的自动 compaction 是同一机制

### 一句话结论
你手动做的「导出 md → 开新会话读 md + 下派任务」，本质就是 Claude Code 和 OpenCode 内置的 **context compaction（上下文压缩）**——把长会话有损压成一份结构化摘要 + 保留最近几轮，重置注意力预算。区别只是：它们到阈值自动触发，你靠手感手动触发。理解了它们的源码实现，你能把手动版做得更对。

### 场景 / 触发
长任务做到中后段、会话几十轮后，agent 开始：重复犯同一个错、忘记早期约束、把被推翻的方案又捡回来、纠错指令下越改越乱。

### 这个问题 Claude Code 怎么做
> 证据级别：Claude Code 官方**不开源**，以下来自我对本机官方二进制（v2.1.161，`@anthropic-ai/claude-code-darwin-arm64/claude`）用 `strings` 抠出的**真实嵌入 prompt**，非第三方猜测。

1. **自动触发**：二进制内含 `Auto-compact window size`、`auto-compact`、`wasCompacted` 等常量——上下文接近窗口上限时自动触发压缩（UI 提示即 "Context left until auto-compact"）。
2. **压缩动作**：触发时对历史跑一段固定 prompt，原文开头是：*"Your task is to create a detailed summary of this conversation. This summary will be placed at the start of a continuing session; newer messages that build on this context will follow after your summary..."*
3. **摘要是结构化的 8 点模板**（二进制里逐条抠到）：`1. Primary Request and Intent`（用户核心诉求）→ … → `7. Pending Tasks`（待办）等。强制模型把「用户要什么、做了什么、还差什么」显式列出，而不是写流水账。
4. 压缩后，摘要放到新上下文**开头**，后续消息接在它之后继续。

### 这个问题 OpenCode 怎么做
> 证据级别：OpenCode **完全开源**（github.com/sst/opencode，TypeScript），以下是我直接读到的源码逻辑。

OpenCode 拆成**三招组合**，比 Claude Code 暴露得更细：

1. **溢出检测**（`session/overflow.ts`）：`usable = 模型输入上限 − 保留缓冲(默认 20000 token)`，当前 token 总数 ≥ usable 即判定 overflow，触发压缩。
2. **prune 擦工具输出**（`compaction.ts`）：从后往前保护最近 `PRUNE_PROTECT=40000` token 的工具调用，**更早的工具输出直接清空**（标记 compacted），因为冗长旧工具结果是最大噪音源。`skill` 类工具输出受保护不擦。
3. **select 保留尾部 + summarize**：保留最近 `tail_turns`（默认 2 轮）原文，其余历史喂给专门的 `compaction` agent 压成摘要。摘要模板（`core/session/compaction.ts` 的 `SUMMARY_TEMPLATE`）是 **8 段式**：`## Goal / ## Constraints & Preferences / ## Progress (Done/In Progress/Blocked) / ## Key Decisions / ## Next Steps / ## Critical Context / ## Relevant Files`，并规定 "terse bullets, not prose"（要点不要散文）、"preserve exact file paths, commands, error strings"（保留确切路径/命令/报错原文）。

### 这个问题 第三方 Rust 复刻（soongenwong/claudecode）怎么做
> 证据级别：这是一个**第三方独立复刻**，其 README 自己声明 "an independent open-source implementation inspired by Claude Code, **not the official Anthropic product**"。**不能当官方源码**，仅作「同一模式被独立重现」的旁证。以下来自我读到的 `rust/crates/runtime/src/compact.rs`。

逻辑与前两家同构，且把阈值写死得很直白（`CompactionConfig` 默认值）：

1. **触发判定**（`should_compact`）：可压缩消息数 > `preserve_recent_messages`（默认 **4** 条）**且** 估算 token ≥ `max_estimated_tokens`（默认 **10000**）才压缩。
2. **保留 + 摘要 + 注入**（`compact_session`）：保留最近 4 条原文，更早的 `summarize` 成摘要；若已有旧摘要则 `merge_compact_summaries` **增量合并**（和 OpenCode 的 previousSummary 合并、Claude Code 的「更新锚定摘要」一致）。
3. **续接 prompt**（三个常量）：摘要前置 *"This session is being continued from a previous conversation that ran out of context..."*；并强制 *"Continue... without asking the user any further questions. Resume directly — do not acknowledge the summary, do not recap..."*——即**直接续做、不许复述摘要**。这点三家都有，是防止重启后浪费一轮在"我回顾一下"上的关键。

### 提炼出的原理（建立在三份真实实现之上）
三个独立实现殊途同归，暴露了上下文管理的底层规律：

1. **长上下文会衰减**：token 越堆越多，早期约束被稀释、旧工具输出变噪音、中途错判被当前提反复引用。三家都不是「截断旧消息」了事，而是**有损压缩成高信噪比摘要**。
2. **摘要必须结构化**：三家摘要模板高度相似——都强制 `目标 / 约束 / 进度 / 关键决策 / 待办 / 关键上下文 / 相关文件`。这不是巧合：**结构化字段防止模型丢掉「用户最初要什么」和「已定下的约束」**，这两样正是长会话最先被稀释的东西。
3. **保留最近原文 + 摘要前文 + 直接续做**：最近几轮逐字保留（细节无损），更早的压成摘要（去噪），并明令新会话不复述摘要直接干活。新会话 = 干净注意力预算读一份精炼事实。

### 这对你的手动做法意味着什么（可直接抄的改进）
你的手动版要逼近这套工程实现，关键是**让 AI 导出的 md 对齐它们的结构化摘要模板**，而不是随便写个「进度小结」。建议导出时套用这个融合模板：

### 关于导出 md 的推荐模板
- 目标 (Goal)
- 约束与偏好 (Constraints)：早期定下的规则、口径、禁忌
- 进度 (Progress)：已完成 / 进行中 / 受阻
- 关键决策 (Key Decisions)：决定 + 为什么
- 下一步 (Next Steps)：有序待办
- 关键上下文 (Critical Context)：重要技术事实、报错原文、待解问题
- 相关文件 (Relevant Files)：路径 + 为什么重要

要点照搬三家的硬规则：**用要点不写散文、保留确切路径/命令/报错原文、不要复述失败的中间过程**。新会话第一条消息 = 这份 md + 明确的下一步任务，并要求它直接续做、别先复述。

### 反直觉点 / 踩过的坑
- 直觉以为「上下文越多 AI 越懂全局」，实际**长上下文稀释关键信息**——三家产品都宁可有损压缩也不留全文。
- **md 里最该保的是「约束」和「目标」，不是「做过的事」**。三家模板都把 Constraints / Primary Intent 放最前——这是长会话最先丢、丢了最致命的。流水账式 md（只记做了啥）等于白重启。
- OpenCode 专门把**旧工具输出**当头号噪音清掉（prune），印证：导出 md 时，冗长的中间工具结果 / 调试输出最该被你筛掉。
- 三家都强制「续接后直接干活、不复述摘要」——你手动重启时也该在新会话里明说这点，否则 AI 容易先花一轮复述你给的 md，浪费注意力。

### 适用边界
适用于状态能被一份结构化 md 描述的任务（写码 / 写文档 / 做分析）。强依赖完整对话细节、难压缩成快照的任务效果打折。上下文窗口越小、任务越长，收益越大——这也正是三家把触发阈值设在窗口上限附近的原因。注意阈值是各家工程取舍：Rust 复刻默认 10000 token / 4 条是保守值，OpenCode 用「输入上限 − 20000 缓冲」动态算，真实产品按模型窗口浮动。

### 关联
上下文压缩（compaction）、上下文腐化（context rot）、注意力预算、子代理上下文隔离、prune（工具输出清理）、增量摘要合并。

证据：OpenCode `session/{overflow,compaction}.ts` + `core/session/compaction.ts`（开源一手）；Claude Code v2.1.161 官方二进制嵌入 prompt（一手取证，官方不开源）；soongenwong/claudecode `runtime/src/compact.rs`（第三方复刻，旁证）。

---
记录日期：2026-06-22
成熟度：验证过（源码 / 官方二进制一手取证）
