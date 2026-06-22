# 工具系统：从理想 Schema 到真实实现，再用源码证伪

> 本文是一篇分析文（Analysis），不是单点实战经验条目。写法上先从「一个工具应该被设计成什么数据结构」的直觉推导出发，再请出 OpenCode 的真实源码逐条验证或证伪这套推导。Tool Schema 与 Tool Call/Observation 这两个话题在源码里是一体两面，故合并成一篇。
>
> 证据级别在文中逐处标注：OpenCode 为完全开源一手源码（本机 clone，commit 见行内引用）；Claude Code 官方不开源，相关结论来自先前会话对官方二进制 v2.1.161 的 `strings` 取证，仍属一手二进制证据，但本次未复核，标注为「二进制取证·待复核」。

---

## 一、从问题出发：为什么工具不能只是 `run(command)`

Agent 的能力边界，本质上由「它能用什么方式影响外部世界」决定，而这件事完全由工具定义。一个朴素的 agent 可能只给模型一个万能工具：

```
run_shell(command: string)
```

这能跑通 demo，但工程上极不稳定，原因有三：

1. **太泛，模型决策空间爆炸**。一个 `command: string` 参数意味着模型每次都要现场拼一段 shell，拼错的概率、踩到副作用的概率、输出无法预测的概率都很高。
2. **无法做权限分级**。读文件和 `rm -rf` 都走同一个入口，沙箱无从下手——要么全放开（危险），要么全拦截（没法用）。
3. **输出不可控**。`cat 一个大文件` 和 `ls` 返回同一个通道，体积无上限，直接灌爆上下文。

直觉上的改进方向是两条：**把工具拆细 + 给每个工具配结构化 schema**。拆细后变成：

```
search_files / read_file / edit_file / run_tests / run_build / git_diff / git_status
```

每个工具窄、可预测、可单独授权。这个方向是对的，下面用源码验证。但拆细之后，"schema 该长什么样"这件事，直觉会想当然，源码会打脸。

---

## 二、理想 Schema vs 真实 Schema（第一处证伪）

### 2.1 直觉版本

凭直觉设计一个工具规格，多半会写成这样：

```
ToolSpec {
  name, description,
  input_schema:  { ... },
  output_schema: { ... },     // 直觉：得声明返回结构
  side_effect: false,         // 直觉：标注有没有副作用
  permission_required: false, // 直觉：标注要不要权限
  max_output_length, on_failure ...
}
```

看起来很完备：输入输出都声明、副作用和权限都做成字段，调度器读字段就能决定拦不拦、怎么回滚。

### 2.2 OpenCode 真实接口

`packages/opencode/src/tool/tool.ts` 里 `Tool.Def` 的真实字段：

```ts
export interface Def<Parameters, M extends Metadata> {
  id: string
  description: string
  parameters: Parameters            // 输入 schema（Effect Schema → JSON Schema）
  jsonSchema?: JSONSchema7
  execute(args, ctx): Effect.Effect<ExecuteResult<M>>
  formatValidationError?(error): string
}
```

`ExecuteResult` 长这样：

```ts
export interface ExecuteResult<M> {
  title: string
  metadata: M
  output: string                    // 注意：output 是运行期产物，不是声明期 schema
  attachments?: FilePart[]
}
```

**被证伪的三处**：

| 直觉字段 | 真实情况 |
|---|---|
| `output_schema` | **不存在**。只有运行时的 `output: string`。模型不被告知返回结构，工具自己决定怎么把结果序列化成文本/附件喂回去。 |
| `side_effect: bool` | **不存在**。没有任何静态的"副作用"声明字段。 |
| `permission_required: bool` | **不存在**。权限不是声明出来的字段，而是命令式地在 `execute` 里临场询问（见第三节）。 |

只有 `input_schema`（`parameters`）是真实存在且核心的——它驱动 AI SDK 的 function-calling，参数不合法会抛 `InvalidArgumentsError`，其 `message` getter 直接生成喂回模型的纠错话术："The X tool was called with invalid arguments… Please rewrite the input so it satisfies the expected schema."（一手源码，tool.ts）。这就是工具层最重要的一条自愈回路：**参数错 → 结构化报错 → 模型重写输入**，全靠 input schema 撑着。

> 启发：设计自己的工具协议时，「输入 schema 严格 + 报错可喂回」远比「把副作用/权限做成声明字段」重要。声明式的 side_effect 字段在真实系统里没出现，因为它是个伪需求——副作用和权限是**行为**，要在执行点用行为控制，不是用元数据标签。

---

## 三、权限：命令式 `ctx.ask()`，不是声明式字段（承上）

真实工具的权限模型是临场询问。`ctx` 上挂着 `ask()`，工具在真正动手前调用它，由用户/策略决定放行还是拦：

- `shell.ts:288` —— 执行命令前 `ctx.ask({ permission: "bash" })`；越权访问外部目录还要额外一次 `ctx.ask({ permission: "external_directory" })`（shell.ts:274）。
- `write.ts:54`、`edit.ts:102 / :145` —— 写文件、改文件各自 `ctx.ask`。
- 纯读工具（`read` / `grep` / `glob`）**不 ask**——读操作默认放行。

（以上全部 OpenCode 一手源码。）

这印证了第二节的拆细方向：**正因为工具拆细了，权限才能精确分级**——读自动放行、写要确认、shell 要确认且外溢目录二次确认。如果还是一个 `run_shell`，这套分级根本无处落脚。权限是「行为发生点的一次命令式询问」，而不是「schema 上的一个布尔标签」，这是直觉最容易想反的地方。

---

## 四、Tool Call / Observation：真实形态是一个 state 机器，不是两个对象

### 4.1 直觉版本

直觉会把"调用"和"观测"拆成两个独立结构：

```
ToolCall    { id, tool, input, timestamp, status }
Observation { call_id, summary, raw_output_ref }   // 直觉：原始输出存外部，上下文放引用
```

### 4.2 真实形态：单个 ToolPart 的 state 机器

OpenCode 把一次工具调用持久化成 message 里的一个 **ToolPart**，调用与结果合在同一个 part 的 `state` 上，随生命周期推进（`message-v2.ts`）：

```
ToolPart {
  callID
  state: {
    status: pending | running | completed | error
    input              // 调用参数
    output / metadata  // completed 后才有
    time               // 时间戳
  }
}
```

直觉的"两个对象"在真实系统里是**一个对象的状态迁移**：`pending → running → completed/error`。`input` 在 running 时就写入，`output` 在 completed 时补上。好处是调用与结果天然对齐、不会错配，UI 也能实时渲染中间态。

### 4.3 第二处证伪：raw_output 不是"存外部 + 放引用"，而是"截断预览 + 落盘 + 让模型按需再取"

直觉里的 `raw_output_ref: "artifact://logs/call_001.txt"`（上下文只放一个引用 URI）听起来优雅，但**真实实现不是引用模型，是截断模型**。`tool/truncate.ts`（OpenCode 一手源码）：

```ts
export const MAX_LINES = 2000
export const MAX_BYTES = 50 * 1024          // 50 KB
const RETENTION = Duration.days(7)
```

`output(text)` 的真实行为：

1. **在限内**（≤2000 行且 ≤50KB）→ 原样返回，`truncated: false`。小输出根本不落盘，直接进上下文。
2. **超限** → 把**全文写到 TRUNCATION_DIR**，上下文里只放：`预览（头部或尾部 N 行）` + `...N lines/bytes truncated...` + 一句 **hint**，教模型怎么取回全文：

   > "The tool call succeeded but the output was truncated. Full output saved to: {file}. Use Grep to search the full content or Read with offset/limit to view specific sections."

3. 落盘文件每小时清理一次，保留 7 天（`Schedule.spaced(Duration.hours(1))` + `RETENTION`）。

和直觉版的关键差异：

| 直觉（artifact 引用） | 真实（truncate 落盘） |
|---|---|
| 上下文放一个 URI，模型看不到任何内容 | 上下文放**预览片段**，模型能看到头/尾，常常够用了 |
| 取回靠专门的 artifact resolver | 取回靠**复用现成的 Grep / Read offset+limit**，零新机制 |
| 所有输出都走外部 | **只有超限的才落盘**，小输出直接进上下文，省一次 IO |

更狠的一个细节——**带 task 子代理权限时，hint 会变**（truncate.ts，`hasTaskTool`）：

> "…Use the **Task tool to have explore agent process this file** with Grep and Read (with offset/limit). Do NOT read the full file yourself - delegate to save context."

即：超大输出不仅落盘，还主动引导模型**把读取委托给子代理**，让脏活在隔离的子上下文里发生，主上下文只收摘要。这是"上下文预算"思维渗透到工具输出层的直接证据。

### 4.4 还有一层：历史里的工具输出会被二次截断

即便当时进了上下文，等会话触发 compaction，历史里的工具输出还会再砍一刀（`message-v2.ts` 的 `truncateToolOutput`，一手源码）：

```ts
function truncateToolOutput(text, maxChars) {
  if (!maxChars || text.length <= maxChars) return text
  const omitted = text.length - maxChars
  return `${text.slice(0, maxChars)}\n[Tool output truncated for compaction: omitted ${omitted} chars]`
}
```

所以工具输出在生命周期里被治理了**两次**：产出时（truncate.ts，落盘可回取）、压缩时（message-v2.ts，直接砍头不可回取）。前者保护"当下这一轮别爆"，后者保护"历史别拖垮长会话"。

---

## 五、输出长度的多道闸（read 工具为例）

`read.ts`（一手源码）单独又设了三道限制，说明"最大输出长度"不是一个全局常量，而是**每个工具按自己语义分别设闸**：

```ts
const DEFAULT_READ_LIMIT = 2000          // 默认读 2000 行
const MAX_LINE_LENGTH    = 2000          // 单行超 2000 字符就截，附 "(line truncated...)"
const MAX_BYTES          = 50 * 1024     // 总字节闸
```

三道闸正交：行数闸防"文件太长"、单行闸防"某行是压缩过的超长 minified JS"、字节闸防"行数不多但每行巨大"。直觉里"max_output_length 一个数搞定"在真实工具里是分维度的多个常量，因为撑爆上下文的姿势不止一种。

---

## 六、把推导收回到三条可执行结论

1. **工具要窄、输入 schema 要严、报错要能喂回模型**。这是稳定性的真正来源——不是模型更聪明，而是工具把模型的决策空间收窄了、把错误变成了可自愈的结构化反馈。`run_shell(command)` 的不稳定是设计缺陷，不是模型缺陷。
2. **副作用和权限是行为，不是字段**。别在 schema 上堆 `side_effect / permission_required` 这类声明标签（真实系统里压根没有）；要在执行点用命令式询问做分级——读放行、写确认、shell 确认。
3. **工具输出要分级治理，且优先复用现成工具取回**。在限内直接进上下文；超限落盘 + 给预览 + 教模型用 Grep/Read 按需取（大到一定程度就引导委托子代理）；历史里再随 compaction 二次截断。不要为"取回全量输出"发明 artifact 协议——`Read offset/limit + Grep` 已经够了。

对我自己手动用 agent 的启发：当某个工具老让 agent 跑偏，先别怪模型，去看这个工具的**输入 schema 是不是太松、输出是不是没设闸**。给工具加约束的杠杆，远大于换个更强的模型。

---

## 证据清单

| 结论 | 来源 | 级别 |
|---|---|---|
| Tool.Def 无 output_schema/side_effect/permission_required | `tool/tool.ts` | OpenCode 一手源码 |
| InvalidArgumentsError 自愈回路 | `tool/tool.ts` | 一手源码 |
| 权限走命令式 ctx.ask（shell/write/edit 各自 ask，read 不 ask） | `tool/shell.ts:274,288`、`write.ts:54`、`edit.ts:102,145` | 一手源码 |
| ToolPart state 机器（pending/running/completed/error） | `session/message-v2.ts` | 一手源码 |
| 输出 truncate：MAX_LINES=2000 / MAX_BYTES=50KB / 7天保留 / 落盘+hint | `tool/truncate.ts` | 一手源码 |
| 带 task 权限时 hint 引导委托子代理 | `tool/truncate.ts` `hasTaskTool` | 一手源码 |
| compaction 期二次截断 truncateToolOutput | `session/message-v2.ts` | 一手源码 |
| read 三道闸（行数/单行/字节） | `tool/read.ts:13-16` | 一手源码 |
| Claude Code 的对应机制 | v2.1.161 二进制 strings | 二进制取证·待复核（本次未复核） |

---
记录日期：2026-06-22
成熟度：验证过
文章类型：分析文
主题分类：Tool Use
