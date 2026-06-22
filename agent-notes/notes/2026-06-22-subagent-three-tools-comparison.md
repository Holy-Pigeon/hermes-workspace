# Subagent 机制三家对比：核心数据结构、解决的问题、调用流程

> 本文是一篇分析文（Analysis）。主题是 agent 把任务"委托给子代理"这件事——三家工具（Claude Code、OpenCode、Hermes）都实现了它，但数据结构、要解决的核心问题、调用流程各有取舍。本文逐项拆开对比，所有结论标注证据级别。
>
> 证据级别：
> - **Hermes** = 完全开源一手源码（本机 editable 安装 v0.15.1，`/Users/xiaogexu/.hermes/hermes-agent/tools/delegate_tool.py`，2801 行）。
> - **OpenCode** = 完全开源一手源码（本机 clone，`packages/opencode/src/tool/task.ts` 等）。
> - **Claude Code** = 官方不开源，证据来自对本机官方二进制 v2.1.161（GIT_SHA 6a550ae，BUILD 2026-06-02）的 `strings` 取证，属一手二进制证据但经过混淆，标注「二进制取证」。

---

## 一、先讲清楚"subagent 到底解决什么核心问题"

三家的注释/prompt 里反复出现同一个词：**context（上下文）**。这不是巧合——subagent 的存在理由，本质上是**上下文经济学**，不是"多线程加速"。具体是三个问题：

### 1.1 上下文污染隔离（最核心）

主 agent 的上下文是稀缺预算（参见上下文治理那篇）。一个"读 50 个文件找出 null 指针风险"的子任务，会产生海量中间工具输出——如果在主上下文里做，这些噪音会永久占据预算、稀释主线意图。

三家的共识解法是：**子任务在一个独立的上下文里跑，主上下文只收到最终摘要**。证据：

- **Hermes**（`delegate_tool.py:15`）：注释直白——"The parent's context only sees the delegation call and the summary result, never the child's intermediate tool calls or reasoning."
- **Claude Code**（二进制）：UI 文案"Each subagent has its own context window, custom system prompt, and specific tools."
- **OpenCode**：task 工具起一个独立的 child session（独立 `sessionID`），父会话只拿到 `<task>` 包起来的结果。

这是 subagent 与"在主循环里多调几个工具"的根本区别：**它买的是上下文隔离，代价是子代理冷启动、要重新建立上下文**。

### 1.2 并行化独立工作流

当任务能拆成 2+ 个互不依赖的子任务时，并行跑省墙钟时间。三家都支持，但并发模型不同（见第四节）。

### 1.3 能力/权限收窄（专精化）

给子代理一个更窄的工具集和更聚焦的 system prompt，让它在一个明确边界内做事，比让全能主 agent 临时切换心智更稳。Claude Code 的 agent 定义和 OpenCode 的 subagent_type 都把这个做成了"预定义角色"。

> 反直觉点（三家 prompt 都在强调）：**subagent 不是免费的，是"昂贵的路径"**。Claude Code 二进制里有一句近乎告诫的话——"**Do not spawn agents unless the user asks.** Each spawn starts cold and re-derives context you already have — it's the expensive path on this plan. A task with 'multiple angles,' 'thorough,' or several parts is not a request to spawn; handle it inline with your own tools." 即：子代理要重新建立你主上下文里已经有的认知，这个冷启动成本经常被低估。能 inline 做就别 spawn。

---

## 二、核心数据结构对比

### 2.1 "子代理定义" —— 三家差异最大的地方

| 维度 | Claude Code | OpenCode | Hermes |
|---|---|---|---|
| 子代理是什么 | 预定义 **agent 定义**（markdown 文件 + frontmatter） | 预定义 **subagent_type**（config 里的 agent） | **运行时构造**的 child AIAgent，无预定义角色文件 |
| 选择方式 | `subagent_type` 参数选类型，省略=general-purpose | `subagent_type` 必填 | `role` 参数（leaf/orchestrator）+ `toolsets` 临时指定 |
| 定义携带的字段 | `agentType / whenToUse / tools / model / permissionMode / memory / hooks / skills / color / getSystemPrompt`（二进制取证） | agent.permission / tools / model 等 | 临时拼：`goal / context / toolsets / role / model`，没有持久角色定义 |

**这是一个真正的设计分野**：

- Claude Code 和 OpenCode 走"**预定义角色库**"路线——你事先声明若干种子代理（code-reviewer、test-runner、general-purpose…），每种带固定的工具集/模型/系统提示，调用时选 type。Claude Code 甚至给每个 agent 配了 `color`（UI 着色）、`whenToUse`（告诉主模型何时该用它）、`hooks`、`skills`、`memory`。
- Hermes 走"**运行时即时构造**"路线——没有"code-reviewer 子代理"这种预制件，每次 `delegate_task` 临时传 goal + 选 toolsets 现场拼一个。角色感更弱，灵活度更高。

证据（Hermes `delegate_tool.py` 的 `delegate_task` 签名）：

```python
def delegate_task(
    goal=None, context=None, toolsets=None,
    tasks=None,            # 批量模式：[{goal, context, toolsets, role}, ...]
    role=None,            # 'leaf'（默认，不能再委托）| 'orchestrator'（可再委托）
    ...
)
```

### 2.2 "调用记录 / 结果" 数据结构

三家把一次委托的结果序列化成什么，差异同样明显：

**Claude Code（二进制取证）** —— 结果是一个 **task_notification 事件**，字段：
```
{ type: "system", subtype: "task_notification",
  task_id, status: "completed"|"failed"|"stopped",
  output_file, summary,
  usage: { total_tokens, tool_uses, duration_ms } }
```
异步模式还有 `{ status: "async_launched", agentId, description, outputFile, canReadOutputFile }`。关键约束（二进制原文）：结果**作为独立消息异步到达**——"results arrive as separate messages. Never fabricate or predict agent results in any format."

**OpenCode** —— 结果是 **XML 标签包裹的文本**（`task.ts` 的 `renderOutput`）：
```
<task id="{sessionID}" state="running|completed|error">
  <summary>...</summary>
  <task_result>...</task_result>   <!-- error 时是 <task_error> -->
</task>
```
注意它把 `sessionID` 直接当 task id 暴露——因为子代理就是一个完整 session。

**Hermes** —— 结果是**结构化 dict**（`delegate_tool.py` `_run_single_child` 返回），字段最全：
```python
{ "task_index", "status",          # completed|failed|timeout|error|interrupted
  "summary", "exit_reason",
  "api_calls", "duration_seconds", "model",
  "tokens": {"input", "output"},
  "tool_trace",                     # 子代理工具调用轨迹
  "error",                          # 仅 failed
  "_child_role", "_child_cost_usd"  # 下划线字段：回传父聚合器后被剥离，不进模型上下文
}
```

三家的共同点：结果里都带 **status 状态机 + summary + usage/tokens**。差异：Hermes 的 dict 最细（连子代理的累计美元成本都折算回父会话），Claude Code 把全文写 `output_file`（落盘，主上下文只放 summary，和工具输出 truncate 同一个思路），OpenCode 用 XML 把状态和正文结构化。

### 2.3 状态机

三家子代理生命周期状态高度趋同（说明这是问题本身决定的，不是抄来的）：

| | 运行中 | 成功 | 失败 | 其他 |
|---|---|---|---|---|
| Claude Code | (async) async_launched | completed | failed | stopped（用户中断） |
| OpenCode | running | completed | error | — |
| Hermes | running | completed | failed / error / timeout | interrupted（用户中断） |

Hermes 多了一个 `timeout` 独立态（有 `_get_child_timeout` 硬超时 + 诊断 dump），和把"用户中断"显式建模为 `interrupted`（对应 `interrupt_subagent`）。

---

## 三、上下文隔离怎么实现（解决核心问题的关键机制）

三家都做隔离，但"隔离的彻底程度"不同，这是最值得记的一点。

### 3.1 全隔离 vs 继承上下文

- **默认全隔离**：三家默认都是子代理拿一个**全新的、只含 goal + context 的精简上下文**，看不到父的对话历史。Hermes 的 `_build_child_system_prompt` 是证据——子代理的 system prompt 就是 `YOUR TASK:{goal}` + 可选 `CONTEXT:{context}` + workspace 提示，父历史一概不注入。这逼着调用方**把子代理需要的信息显式打包进 context 参数**——这也是为什么三家文档都反复强调"subagent 不知道你的对话，要把路径/约束/错误信息都写进去"。

- **继承上下文的特例（Claude Code 的 fork）**：Claude Code 有一个特殊的 `fork` 子代理类型（二进制：`FORK_SUBAGENT_TYPE`，`model:"inherit"`, `tools:["*"]`, `permissionMode:"bubble"`, `maxTurns:200`），它**继承完整对话上下文**——"You've inherited the conversation context above from a parent agent… operating in an isolated git worktree." 这是"上下文隔离"光谱的另一端：上下文全继承，但**文件系统隔离**（独立 git worktree），改动不影响父。注意它不可通过 `subagent_type` 选择，是省略 type 且 fork 实验开启时隐式触发的。

这给出一个有用的二维框架——**隔离有两个正交的轴**：
1. 上下文隔离（子代理看不看得到父历史）
2. 文件系统隔离（子代理的写操作影响不影响父）

| | 上下文隔离 | 文件隔离 |
|---|---|---|
| 常规 subagent（三家） | 是（全新上下文） | 否（同一工作区） |
| Claude Code fork | 否（继承） | 是（独立 worktree） |

Hermes 没做 worktree 级文件隔离，但它在结果聚合处做了**跨代理文件状态提醒**（`delegate_tool.py` 注释）：如果子代理写了父已经读过的文件，会显式提示父"重新读取再编辑"——用提醒代替隔离，解决同一个"子代理改了文件父不知道"的问题。

### 3.2 权限隔离

- **Claude Code**：agent 定义里带 `permissionMode`（如 fork 的 `"bubble"`），每个 agent 有自己的 `tools` 白名单（"Not available to subagents" 是 UI 里真实的警告文案）。
- **OpenCode**（`task.ts`）：`deriveSubagentSessionPermission` 从父 session 权限**派生**子权限；还默认给子代理 deny 掉 `todowrite` 和 `task` 本身（除非子 agent 显式声明）——**即默认不让子代理再起子代理**，防递归失控。
- **Hermes**：硬编码一个 `blocked tools` 黑名单（子代理永不可得，含 `execute_code` 等），叠加 `role` 机制——leaf 不给 delegation 工具集，orchestrator 才给。

三家都默认**收紧子代理能再委托的能力**，这是同一个安全直觉：放任递归 spawn = 失控的 token 烧钱树。

---

## 四、调用流程对比（从 spawn 到结果回收）

### 4.1 Hermes 流程（一手源码，最完整可追）

```
delegate_task(goal/tasks, role, toolsets)
  │
  ├─ 0. 前置闸：is_spawn_paused()？（TUI 可冻结新 spawn 的 kill switch）
  │       depth 检查：_delegate_depth ≥ max_spawn_depth → 拒绝（默认 MAX_DEPTH=1，扁平）
  │
  ├─ 1. _build_child_agent(goal, context, toolsets, role)
  │       · 构造精简 system prompt（只含 goal+context）
  │       · _strip_blocked_tools：剥离黑名单工具
  │       · leleaf 不给 delegation 工具集；orchestrator 才给
  │       · 绑定独立 credential lease（_credential_pool）
  │
  ├─ 2. 并发执行（_run_single_child 在 ThreadPool 里跑）
  │       · 单任务：直接同线程跑
  │       · 批量：ThreadPoolExecutor(max_workers=max_concurrent_children)
  │       · 每个 child 套一个硬 timeout（_get_child_timeout）
  │       · 心跳线程：周期 _touch_activity(parent) 防 gateway 因"无活动"杀父
  │       · 停滞检测：iter/tool 都不前进 N 个心跳周期 → 判定 stale
  │       · as_completed 轮询时检查父中断信号 → 传播 interrupt 给所有 child
  │
  └─ 3. 结果聚合
          · 每个 child 返回结构化 dict（见 2.2）
          · 折算 _child_cost_usd 进父会话成本
          · 跨代理文件写入提醒
          · 剥离下划线内部字段 → 序列化 JSON 数组回模型
```

### 4.2 三家流程的关键差异

| 流程环节 | Claude Code | OpenCode | Hermes |
|---|---|---|---|
| 并发原语 | 单条 assistant 消息里发多个 tool_use（"send a single message with both tool calls"） | Effect 运行时 + 可选 background job | ThreadPoolExecutor（max_concurrent_children） |
| 同步/异步 | 双模式：同步等结果 / 异步 `async_launched` 后台跑、完成发 notification | 默认前台；`background=true` 需实验 flag | 父**阻塞**直到所有 child 完成（同步） |
| 结果返回时机 | 异步：作为独立消息后续到达 | 前台：execute 返回；后台：通知 | 同步：delegate_task 返回即全部结果 |
| 可恢复性 | task_id（异步可读 output_file） | **`task_id` 可恢复**——传旧 task_id 续跑同一 session，不新建 | **不可恢复**——child 跑完即销毁，无 session 持久化 |
| 中断 | stopped 状态 + 用户取消 | session cancel | interrupt_subagent（不硬杀线程，设标志位） |

**最值得记的两个差异**：

1. **可恢复性**：OpenCode 的 subagent 是**持久 session**，可以用 `task_id` 续跑（"continue the same subagent session as before instead of creating a fresh one"）；Hermes 的 child 是**一次性**的，跑完即焚，没有"续跑上次那个子代理"的概念。这直接源于 2.1 的分野——OpenCode 子代理 = 完整 session（天然可持久化），Hermes 子代理 = 线程内临时对象。

2. **同步 vs 异步**：Hermes 是**纯同步阻塞**模型（父等齐所有 child 才继续）——简单、结果对齐、但父在等待期间干不了别的（靠心跳防超时）。Claude Code 走得最远，有真正的异步后台子代理（`async_launched` → 干别的 → 完成时收 notification），OpenCode 居中（background 是实验特性）。

---

## 五、收敛成可执行结论

1. **subagent 的本质是上下文经济学，不是并发加速**。三家的核心理由都是"隔离子任务的中间噪音，主上下文只收摘要"。决定要不要 spawn 时，问的不是"能不能并行"，而是"这个子任务的中间产物会不会污染主上下文"。会 → 委托；不会 → inline 做，因为 spawn 要付冷启动重建上下文的成本（Claude Code 称之为"the expensive path"）。

2. **隔离要分两个轴看**：上下文隔离（看不看得到父历史）和文件隔离（写操作影响不影响父）。常规 subagent 隔上下文不隔文件——所以"子代理改了父读过的文件"是个真实的坑，Hermes 用跨代理写入提醒、Claude Code fork 用独立 worktree 各自解决。用任何 subagent 工具时，默认子代理改的文件父看不见，编辑前要重读。

3. **预定义角色 vs 运行时构造是真实的产品分野**。要可复用、可在 UI 里管理、带固定专精的子代理 → Claude Code/OpenCode 的预定义路线；要轻量、一次性、临时拼工具集 → Hermes 的运行时构造。没有优劣，只有匹配场景。

4. **递归 spawn 默认要收紧**。三家都默认不让子代理无限再委托（OpenCode deny task 权限、Hermes leaf 角色、Claude Code agent 工具白名单）。自己设计多代理系统时，"子代理能不能再生子代理"必须显式建模并设深度上限，否则就是失控的烧钱树。

对我自己用 agent 的启发：当我手动让一个 agent"顺便也把 X 研究一下"时，其实是在污染它的主上下文。更好的做法是把 X 显式委托出去（或开新会话），让主线只拿结论——这和这三家把 subagent 上下文隔离的动机完全一致。

---

## 证据清单

| 结论 | 来源 | 级别 |
|---|---|---|
| 父上下文只见委托调用+摘要 | Hermes `delegate_tool.py:15` 注释 | 一手源码 |
| delegate_task 签名 / role / tasks 批量 | Hermes `delegate_tool.py:1918` | 一手源码 |
| 结果 dict 全字段（status/summary/tokens/tool_trace/_child_cost_usd） | Hermes `_run_single_child` 返回 | 一手源码 |
| 状态机 completed/failed/timeout/interrupted | Hermes `delegate_tool.py:1686+` | 一手源码 |
| ThreadPool 并发 / 心跳 / 停滞检测 / 中断传播 | Hermes `_run_single_child`、`interrupt_subagent` | 一手源码 |
| leaf/orchestrator + blocked tools + depth cap | Hermes `_build_child_agent`、`MAX_DEPTH` | 一手源码 |
| 精简 system prompt（只含 goal+context） | Hermes `_build_child_system_prompt` | 一手源码 |
| task 工具 XML 输出 `<task state=...>` | OpenCode `tool/task.ts` `renderOutput` | 一手源码 |
| subagent_type 必填 / task_id 可恢复 session | OpenCode `tool/task.ts` Parameters | 一手源码 |
| 子权限从父派生 + 默认 deny todowrite/task | OpenCode `deriveSubagentSessionPermission` | 一手源码 |
| background 模式需实验 flag | OpenCode `task.ts` experimentalBackgroundSubagents | 一手源码 |
| Task 描述/agent 定义字段/own context window | Claude Code v2.1.161 二进制 | 二进制取证 |
| task_notification 状态机 + output_file + usage | Claude Code v2.1.161 二进制 | 二进制取证 |
| "Do not spawn unless asked / expensive path" | Claude Code v2.1.161 二进制 | 二进制取证 |
| fork 子代理：继承上下文 + 独立 worktree | Claude Code v2.1.161 二进制 `FORK_SUBAGENT_TYPE` | 二进制取证 |
| 并行=单消息多 tool_use | Claude Code v2.1.161 二进制 | 二进制取证 |

---
记录日期：2026-06-22
成熟度：验证过
文章类型：分析文
主题分类：Multi-Agent
