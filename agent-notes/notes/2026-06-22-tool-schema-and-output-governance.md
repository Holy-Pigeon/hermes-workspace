# 工具系统：从一次工具调用的生命周期，看三家如何治理 Schema 与输出

> 本文是一篇分析文（Analysis）。按「问题引入 → 数据结构设计 → 流程分析」三段式展开，对照 Claude Code、OpenCode、Hermes 三家的真实实现，看一个 agent 工具系统在工程上到底要解决哪些问题、各自落到了什么数据结构、串成了什么流程。
>
> 证据级别逐处标注：
> - **OpenCode** —— 完全开源，本机 clone 一手源码，commit 见行内引用。
> - **Hermes** —— 本机可读 Python 源码（`~/.hermes/hermes-agent/`），一手。
> - **Claude Code** —— 官方不开源，结论来自对官方二进制 v2.1.161（`/opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe`，218MB）的 `strings` 取证，属一手二进制证据，本次已复核。文中凡引 CC 的字符串/常量均可在该二进制中检出。

---

## 一、问题引入：一次工具调用要穿过多少道关

Agent 的能力边界，本质由「它能用什么方式影响外部世界」决定，而这件事完全由工具系统定义。把镜头拉到**一次工具调用的完整生命周期**，会发现它要依次穿过四道关，每一道都对应一个必须在工程上解决的问题：

1. **模型决定调用什么、传什么参数** —— 工具怎么向模型描述自己？参数错了怎么办？（Schema 与输入治理）
2. **系统决定让不让这次调用发生** —— 读、写、执行的风险天差地别，权限怎么分级？（执行控制）
3. **工具执行、产出结果** —— 结果可能是 3 行，也可能是 30 万字符，怎么不撑爆上下文？（输出治理）
4. **结果回到模型、进入历史、最终被压缩** —— 历史里的旧输出怎么不拖垮长会话？（生命周期治理）

这四个问题，三家都必须回答。下面先看它们各自把「工具」这个东西定义成了什么数据结构（决定了第 1、2 关的答案），再看一次调用怎么在这套结构上流动（第 3、4 关）。

一个反面参照能让问题更清楚：最朴素的 agent 只给模型一个万能工具 `run_shell(command: string)`。它能跑通 demo，但三关全失守 —— 参数是自由文本无从校验、读和 `rm -rf` 同一个入口无法分级、输出体积无上限。三家的工具系统，本质都是在系统性地修补这三个洞。

---

## 二、数据结构设计：工具被定义成什么

### 2.1 三家的「工具定义」核心字段

**OpenCode —— `Tool.Def`**（`packages/opencode/src/tool/tool.ts`，一手源码）：

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

**Hermes —— `ToolEntry`**（`tools/registry.py`，一手源码）：

```python
class ToolEntry:
    __slots__ = (
        "name", "toolset", "schema", "handler", "check_fn",
        "requires_env", "is_async", "description", "emoji",
        "max_result_size_chars", "dynamic_schema_overrides",
    )
```

**Claude Code** —— 二进制里检出工具以常量名登记（`DnO="Read"`、`MnO="Write"`、`_DK="Grep"`、Bash 工具等），并存在一个关键的布尔维度 `isDeferred` / `deferredBuiltinTools`（`/context` 面板把工具按 `systemTools` 与 `deferredBuiltinTools` 分列渲染）。

### 2.2 三个值得记住的设计共性与差异

**共性一：输入 schema 是绝对核心，输出结构不进 schema。**

三家的工具定义里，**输入参数 schema 都是一等公民**，但**没有一家在工具定义里声明"输出 schema"**。OpenCode 的 `ExecuteResult` 里 `output: string` 是运行期产物而非声明期契约；Hermes 的 handler 直接返回 JSON 字符串；CC 的工具结果也是运行时序列化的文本。

> 设计含义：模型不被预先告知工具会返回什么结构，工具自己决定怎么把结果序列化成文本喂回。输出的"约束"不靠 schema 声明，而靠运行时的长度治理（见第三节）。这是三家一致的取舍 —— 输入要严（驱动 function-calling），输出要治（驱动上下文预算），两件事用两套机制。

**共性二：权限不是数据结构里的字段，是执行点的行为。**

三家的工具定义里**都没有 `side_effect` 或 `permission_required` 这类声明字段**。权限分级是在执行时命令式地做的：

- OpenCode：`ctx` 上挂 `ask()`，工具动手前调用。`shell.ts` 执行前 `ctx.ask({ permission: "bash" })`，越权访问外部目录再 `ctx.ask({ permission: "external_directory" })`；`write.ts` / `edit.ts` 各自 ask；纯读工具 `read` / `grep` / `glob` 不 ask（一手源码）。
- CC：二进制里检出独立的 permission 模式机（`permission_mode`、`ask`/`allow`/`deny` 路径），按工具与参数在调用点决策。
- Hermes：`handle_function_call` 里走 pre-tool-call hook + 编辑审批链，同样在执行点拦截。

> 设计含义：副作用和权限是**行为属性**，依赖运行时参数（同一个 shell 工具，`ls` 与 `rm -rf` 风险不同），无法在静态 schema 上用一个布尔标签表达。三家都把它下沉到执行点，正是这个原因。而第一节那个 `run_shell` 之所以没法做权限，恰恰因为它没拆细 —— 工具拆得越细，执行点的分级才越精确。

**差异点：只有 Hermes 把"输出上限"做成了结构化字段。**

Hermes 的 `ToolEntry` 有 `max_result_size_chars`，注册时显式声明（`file_tools.py`：`read_file` / `write_file` / `patch` / `search_files` 全部 `max_result_size_chars=100_000`；`web_tools` / `terminal_tool` / `code_execution_tool` 同）。OpenCode 和 CC 则把对应阈值写成模块级常量（OpenCode `MAX_LINES=2000`；CC Read 默认 `25000` tokens）。

> 设计含义：这是三家最有意思的分叉。Hermes 把"每个工具允许多大输出"提升为**可按工具声明、registry 统一查询**的元数据（`registry.get_max_result_size(name)`），代价是多一个字段；OpenCode/CC 把它留在各工具内部作为常量，定义更瘦但阈值分散。没有对错 —— Hermes 选择了"输出预算可集中治理"，另两家选择了"工具定义最小化"。

---

## 三、流程分析：一次调用怎么在这套结构上流动

### 3.1 第一关 —— 输入治理：参数错了能自愈

三家都把"参数不合法"做成了**可喂回模型的结构化纠错**，而不是硬失败：

- **OpenCode**：参数不满足 `parameters` schema 抛 `InvalidArgumentsError`，其 message 直接生成喂回话术："The X tool was called with invalid arguments… Please rewrite the input so it satisfies the expected schema."（`tool.ts`，一手）。
- **Hermes**：先 `coerce_tool_args()` 容错 —— 开源模型常把 `42` 写成 `"42"`、把 `["a"]` 写成 `"a"`，Hermes 按 schema 类型自动强转/包装（`model_tools.py:606`），强转不了才报错；报错经 `_sanitize_tool_error()` 截断到 2000 字符（`_TOOL_ERROR_MAX_LEN=2000`）再喂回。
- **CC**：二进制里检出输入校验失败的结构化报错路径（`Invalid … request`、schema 不匹配提示）。

> 流程要点：**参数错 → 结构化报错 → 模型重写输入**，这是工具层最重要的一条自愈回路。它让"模型偶尔传错参"从致命错误降级为一次便宜的重试。稳定性不来自模型更聪明，而来自工具把错误变成了可恢复的结构化反馈。Hermes 比另两家多走一步"先容错强转再报错"，因为它要兼容更多开源模型的脏输出。

### 3.2 第二关 —— 执行控制：调用与结果的承载形态

工具执行时，"这次调用"和"它的结果"怎么被记录？OpenCode 给了最清晰的答案：**不是两个对象，是一个对象的状态迁移**。

OpenCode 把一次调用持久化成 message 里的一个 **ToolPart**（`session/message-v2.ts`，一手）：

```
ToolPart {
  callID
  state: {
    status: pending | running | completed | error
    input              // running 时写入
    output / metadata  // completed 后补上
    time
  }
}
```

调用与结果合在同一个 part 的 `state` 上随生命周期推进：`pending → running → completed/error`。好处是调用与结果天然对齐、不会错配，UI 还能实时渲染中间态。Hermes 的 `handle_function_call` 同步返回结果字符串、由上层会话组装成对应的 tool message，CC 二进制里也检出 `tool_use` / `tool_result` 配对校验（id 必须一一对应，否则抛错）—— 三家都保证了"调用-结果"的强配对，只是 OpenCode 把它显式建模成了状态机。

### 3.3 第三关 —— 输出治理：超限不截断，而是"落盘 + 预览 + 教模型按需取"

这是三家投入最多、也最趋同的一关。核心模式完全一致：**小输出直接进上下文，大输出落盘 + 只放预览片段 + 给一句 hint 教模型怎么取回全文**。

**OpenCode**（`tool/truncate.ts`，一手）：

```ts
export const MAX_LINES = 2000
export const MAX_BYTES = 50 * 1024          // 50 KB
const RETENTION = Duration.days(7)
```

- 在限内（≤2000 行且 ≤50KB）→ 原样返回，不落盘。
- 超限 → 全文写到 TRUNCATION_DIR，上下文放：预览 + `...N lines/bytes truncated...` + hint："Full output saved to: {file}. Use Grep to search the full content or Read with offset/limit to view specific sections."
- 落盘文件每小时清理、保留 7 天。

**Hermes**（`tools/tool_result_storage.py` + `budget_config.py`，一手）—— 做成了**三层预算**，docstring 原话：

```python
DEFAULT_RESULT_SIZE_CHARS  = 100_000   # Layer 2：单个结果超此阈值就持久化
DEFAULT_TURN_BUDGET_CHARS  = 200_000   # Layer 3：整轮所有结果总预算
DEFAULT_PREVIEW_SIZE_CHARS = 1_500     # 持久化后留在上下文的预览大小
```

- Layer 1（工具内）：`search_files` 等工具先自截一道。
- Layer 2（单结果）：超 `max_result_size_chars`（registry 里按工具声明的那个字段，默认 100K）→ `maybe_persist_tool_result()` 把全文写进 sandbox，上下文换成 `预览(1500字符) + 路径 + "Use the read_file tool with offset and limit to access specific sections."`
- Layer 3（整轮）：一轮内所有结果加起来超 `MAX_TURN_BUDGET_CHARS`(200K)，`enforce_turn_budget()` 挑最大的几个非持久化结果再压。

**Claude Code**（二进制，一手）：

- Read 工具有 token 上限 `SHO=25000`（可被 `CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS` 覆盖），超限抛 `MaxFileReadTokenExceededError`，message 原文教模型："Use offset and limit parameters to read specific portions of the file, or search for specific content instead of reading the whole file."
- Bash 工具输出有字符闸，hint 原文："If the output exceeds ${...} characters, output will be truncated before being returned to you."
- 更进一步，CC 的 `/context` 面板会**主动给省 token 建议**：Bash 结果占用过高 → "Pipe output through head, tail, or grep"；Read 占用过高 → "Use offset and limit parameters to read only the sections you need"；Grep 占用过高 → "Add more specific patterns or use the glob or type parameter"。

> 流程要点：三家都不约而同选了**"截断预览 + 落盘 + 复用现成 Read/Grep 取回"**，而不是"上下文放一个 artifact URI、用专门的 resolver 取回"。原因是后者要发明新机制，而 `Read offset/limit + Grep` 模型已经会用、零学习成本。差异只在分层粒度：CC 按工具设 token 闸、OpenCode 单层行/字节闸、Hermes 三层字符预算。Hermes 分层最细，因为它要同时管"单结果别爆"和"整轮别爆"两件事。

补一个 OpenCode 的精妙细节：带 task 子代理权限时，truncate 的 hint 会变（`truncate.ts` 的 `hasTaskTool`）——"Use the Task tool to have explore agent process this file… Do NOT read the full file yourself - delegate to save context."。即超大输出不仅落盘，还主动引导模型**把读取委托给子代理**，让脏活在隔离的子上下文里发生。这是"上下文预算"思维渗透到工具输出层的直接证据。

### 3.4 第四关 —— 生命周期治理：历史里的旧输出会被二次压缩

即便当时进了上下文，等会话触发 compaction，历史里的工具输出还会再砍一刀：

- **OpenCode**：`message-v2.ts` 的 `truncateToolOutput(text, maxChars)` —— 超限直接 `slice(0, maxChars)` + `[Tool output truncated for compaction: omitted N chars]`，**砍头不可回取**（一手）。
- **CC**：二进制检出 compaction 期的文件引用降级 —— "Note: {filename} was read before the last conversation was summarized, but the contents are too large to include. Use Read tool if you need to access it."。即压缩时把"曾经读过的大文件内容"替换成一句"要的话自己重读"。

> 流程要点：工具输出在生命周期里被治理了**两次**：产出时（落盘可回取，保护"当下这一轮别爆"）、压缩时（砍头/降级为引用，保护"历史别拖垮长会话"）。两道闸目标不同、可逆性不同，缺一不可。

### 3.5 额外一关 —— 工具太多本身也是上下文负担：延迟加载

当工具数量膨胀（尤其接了一堆 MCP），光是"所有工具的 schema"就能吃掉可观的上下文。CC 和 Hermes 都做了**延迟加载/按需暴露**：

- **CC**：`deferredBuiltinTools` —— 部分内置工具默认不进上下文，`/context` 面板单独列出 "loaded on-demand"，MCP 工具也标 "(loaded on-demand)"。
- **Hermes**：`tool_search` bridge（`tools/tool_search.py`）—— `tool_search` / `tool_describe` / `tool_call` 三件套，模型先搜目录、再描述、再调用，未召回的工具不占 schema 预算。且 bridge 严格按 session 的 toolset 作用域过滤，受限会话（subagent、kanban worker）无法借 bridge 越权调用。

> 流程要点：这关在 OpenCode 里目前未见对应机制，是 CC / Hermes 在"工具规模化"上多走的一步 —— 工具数量本身就是 context 成本，延迟加载把"工具目录"也纳入了预算治理。

---

## 四、把三段收回到可执行结论

1. **输入要严、报错要能喂回；输出不进 schema、靠运行时治理。** 三家一致：function-calling 的稳定来自"输入 schema 严 + 参数错可自愈重试"，而不是声明输出结构。设计自己的工具协议时，把力气花在"输入校验 + 结构化纠错话术"上，回报最大。

2. **权限是执行点的行为，不是数据结构里的字段。** 三家都没有 `side_effect` / `permission_required` 声明字段，全部在执行点命令式分级（读放行、写确认、shell 确认且外溢二次确认）。前提是工具拆得够细 —— `run_shell(command)` 没法分级，正因为它没拆。

3. **大输出统一走"落盘 + 预览 + 复用 Read/Grep 按需取回"，且要治理两次。** 别为取回全量输出发明 artifact 协议；产出时落盘可回取、压缩时砍头降级。Hermes 把它做成三层字符预算（单结果 100K / 整轮 200K / 预览 1.5K）、CC 按工具设 token 闸并主动给省 token 建议、OpenCode 单层行字节闸并能引导委托子代理 —— 分层粒度可按自己系统的会话长度需求选。

4. **工具数量本身是 context 成本。** 工具一多就上延迟加载（CC `deferredBuiltinTools` / Hermes `tool_search` bridge），别让一堆用不到的工具 schema 白占预算。

对我自己手动用 agent 的启发：当某个工具老让 agent 跑偏，先别怪模型，去看这个工具的**输入 schema 是不是太松、输出是不是没设闸**。给工具加约束的杠杆，远大于换个更强的模型。

---

## 证据清单

| 结论 | 来源 | 级别 |
|---|---|---|
| OpenCode `Tool.Def` 字段 / `ExecuteResult.output` 运行期产物 | `tool/tool.ts` | OpenCode 一手源码 |
| OpenCode `InvalidArgumentsError` 自愈话术 | `tool/tool.ts` | 一手源码 |
| OpenCode 权限走命令式 `ctx.ask`（shell/write/edit ask，read 不 ask） | `tool/shell.ts`、`write.ts`、`edit.ts` | 一手源码 |
| OpenCode `ToolPart` 状态机 pending/running/completed/error | `session/message-v2.ts` | 一手源码 |
| OpenCode truncate：MAX_LINES=2000 / MAX_BYTES=50KB / 7天保留 + hint | `tool/truncate.ts` | 一手源码 |
| OpenCode 带 task 权限时引导委托子代理 | `tool/truncate.ts` `hasTaskTool` | 一手源码 |
| OpenCode compaction 期 `truncateToolOutput` 砍头 | `session/message-v2.ts` | 一手源码 |
| Hermes `ToolEntry` 字段含 `max_result_size_chars` | `tools/registry.py` | 一手源码 |
| Hermes `register()` 显式声明 max_result_size_chars=100_000 | `tools/file_tools.py` 等 | 一手源码 |
| Hermes `coerce_tool_args` 类型容错强转 | `model_tools.py:606` | 一手源码 |
| Hermes `_sanitize_tool_error` 截断 2000 字符 | `model_tools.py:583` | 一手源码 |
| Hermes 三层输出预算 100K/200K/1.5K | `tools/tool_result_storage.py`、`budget_config.py` | 一手源码 |
| Hermes `tool_search` bridge 延迟加载 + toolset 作用域过滤 | `tools/tool_search.py`、`model_tools.py` | 一手源码 |
| CC Read token 上限 25000 + MaxFileReadTokenExceededError hint | v2.1.161 二进制 strings | 二进制取证·已复核 |
| CC Bash 字符闸 hint 原文 | v2.1.161 二进制 strings | 二进制取证·已复核 |
| CC `/context` 省 token 建议（head/tail/grep、offset/limit、glob） | v2.1.161 二进制 strings | 二进制取证·已复核 |
| CC `deferredBuiltinTools` 延迟加载 | v2.1.161 二进制 strings | 二进制取证·已复核 |
| CC compaction 期文件引用降级提示 | v2.1.161 二进制 strings | 二进制取证·已复核 |
| CC tool_use/tool_result id 强配对校验 | v2.1.161 二进制 strings | 二进制取证·已复核 |

---
记录日期：2026-06-22
成熟度：验证过
文章类型：分析文
主题分类：Tool Use
