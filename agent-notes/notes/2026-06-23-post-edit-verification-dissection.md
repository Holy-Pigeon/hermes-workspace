# 编辑后验证：让 agent 知道"自己刚把代码改坏了"

> Doc Type：分析文 ｜ Category：Agent Loop ｜ Maturity：验证过
> 取证对象：OpenCode（`/tmp/oc-src` @ `cd292a4`，真实源码）、Hermes Agent（`~/.hermes/hermes-agent`，真实源码）、Claude Code v2.1.161（官方二进制 `claude.exe` 218MB，`strings` 一手取证 + 第三方 Rust 复刻旁证）
> 所有结论标注 `文件:行号`；推断部分明确标"推断"；官方二进制取不到的明确标"取不到"。

---

## 一、问题引入：LLM 没有编译器

agent 写代码这件事有个根本缺陷：**模型本身不会编译、不会做类型检查**。它生成 `edit`/`write` 把字符替进文件，落盘那一刻，它并不知道自己有没有写出语法错误、引用了不存在的符号、类型对不上。如果就此停手，错误要等到很久以后（用户跑测试、CI 报红）才暴露，而那时 agent 早已离开案发现场。

要把 agent 从"开环生成器"变成"闭环工程师"，必须补上一个 **行动后验证（post-edit verification）** 环节：

> 编辑 → **立刻校验** → 把错误回灌进上下文 → 模型下一轮看到错误 → 自我纠错

这正是 agent loop 里"行动—观察—反思"中**观察质量**的核心。观察得越准、越聚焦，纠错回合越短。三家 agent 都实现了这套闭环，但在**两个关键设计点**上分出了高下：

1. **错误从哪来**：靠语言服务器（LSP）实时诊断，还是靠外部 IDE，还是靠跑一遍编译器？
2. **回灌什么**：回灌文件里**所有**错误，还是只回灌**本次编辑新引入的**错误？

第二点是分水岭。一个被频繁编辑的文件里往往本来就躺着一堆历史报错（别人写的、还没修的）。如果每次编辑后把全量错误都怼给模型，模型会被噪声淹没，甚至跑去修与本次无关的代码——这是典型的"观察信噪比"问题。

本文拆这条线：三家如何拿到诊断、如何区分新旧、如何把"只属于你这次的错"精准送到模型眼前。

---

## 二、数据结构设计：诊断对象、基线快照、增量键

### 2.1 共同地基：LSP Diagnostic 对象

三家的诊断数据都源自 LSP（Language Server Protocol）标准的 `Diagnostic` 结构，字段一致：

| 字段 | 含义 | 取证 |
|---|---|---|
| `severity` | 1=ERROR 2=WARN 3=INFO 4=HINT | OpenCode `diagnostic.ts:6-13`；Hermes `manager.py:625,630` |
| `range.start.line/character` | 出错位置（0-based） | OpenCode `diagnostic.ts:14-15`；Hermes `manager.py:622-624` |
| `message` | 错误文本 | OpenCode `diagnostic.ts:17`；Hermes `manager.py:633` |
| `code` / `source` | 规则码 / 产生方（tsc、eslint…） | OpenCode `client.ts:94-100`；Hermes `manager.py:625,632` |

OpenCode 直接复用 VSCode 类型 `export type Diagnostic = VSCodeDiagnostic`（`client.ts:27`）。这是整条机制的原子。

### 2.2 OpenCode：无基线，全量过滤

OpenCode **没有基线数据结构**。它的"数据结构"就是一次性的过滤+格式化，核心是 `report()`（`diagnostic.ts:20-27`）：

```
const MAX_PER_FILE = 20                          // diagnostic.ts:3
const errors = issues.filter(i => i.severity === 1)  // 只留 ERROR
const limited = errors.slice(0, MAX_PER_FILE)        // 每文件上限 20 条
return `<diagnostics file="${file}">\n${...}\n</diagnostics>`
```

单条渲染成 `ERROR [line:col] message`（行列已 +1 转 1-based）。**关键事实**：只回灌 `severity===1`（ERROR），WARN/INFO/HINT 全丢；每文件 20 条封顶，超出 `... and N more`。

工具返回值结构（`edit.ts:203-211`）：
- `output`（字符串）：真正喂给模型的，里面拼了 `<diagnostics>` 文本块
- `metadata.diagnostics`：`Record<string, Diagnostic[]>`，结构化原始数据，给 UI/历史用

注意：OpenCode 取的是"当前文件**全部** ERROR"（`edit.ts:199-200`），**不与编辑前做任何比对**。模型看到的是"这文件现在所有的错"，包含历史遗留错误。

### 2.3 Hermes：delta-baseline 增量字典（三家最精巧）

Hermes 引入了"基线快照"这个核心数据结构 `_delta_baseline`（`manager.py:184`）：

```python
self._delta_baseline: Dict[str, List[Dict[str, Any]]] = {}
# key = os.path.abspath(file_path)，value = 该文件上次快照时的诊断列表
```

它要回答的问题是：**这条诊断，是不是我这次编辑新引入的？** 判定靠 `_diag_key`（`manager.py:608-636`）——把一条诊断压成一个去重键，用 `\x00` 连接 5 段：

```
severity ∥ code ∥ source ∥ message(strip) ∥ "start.line:char-end.line:char"
```

`seen = {_diag_key(d) for d in baseline}` 后，`diags = [d for d in diags if _diag_key(d) not in seen]`（`manager.py:368-369`）——一个干净的**集合差**：当前诊断 − 编辑前诊断 = 本次新增。

但集合差有个陷阱：**编辑增删了行，文件下半部分本来就有的旧错误会平移到新行号**，`range` 一变，`_diag_key` 就变，集合差会把它误判成"新错"。Hermes 为此专门做了 `range_shift.py`：

- `build_line_shift(pre_text, post_text)`（`range_shift.py:33`）：用 `difflib.SequenceMatcher.get_opcodes()`（`:61-62`）算出编辑前后的行号映射——和 git diff/blame 同款手法
- `equal` 段线性平移（`:70-72`），`delete`/`replace` 段返回 None 丢弃（`:73-79`）
- 做集合差前先 `shift_baseline(baseline, line_shift)`（`manager.py:366-367`）把旧诊断行号映射到编辑后坐标，这样"平移过的旧错"能和新快照里同一条 hash 相等、被正确过滤掉

还有一个**熔断集合** `_broken`（`manager.py:175`），key = `(server_id, per_server_root)`。LSP server spawn/init 超时一次，就把它拉黑（`manager.py:413-415`），后续编辑直接跳过、不再付超时成本。这是健壮性的关键数据结构。

### 2.4 Claude Code：baseline 追踪器（官方二进制取证）

官方二进制里这套机制由一个单例追踪器对象承载（minify 后类名 `Nm`，单例 `m3H=Nm.getInstance()`）。从 `strings` 抠出的真实状态字段：

```
this.baseline                  // 编辑前每文件的诊断快照（与 Hermes 的 _delta_baseline 同构）
this.rightFileDiagnosticsState
this.lastProcessedTimestamps
areDiagnosticArraysEqual       // 诊断数组相等判定（对应 Hermes 的 _diag_key 比对）
```

核心方法名（确证存在）：`getNewDiagnostics`、`getDiagnostics`、`formatDiagnosticsSummary`、`parseDiagnosticResult`、`getLSPDiagnosticAttachments`。

> **一个重要的交叉印证**：Hermes 源码注释（`manager.py:371-372`）写着"mirroring claude-code's **diagnosticTracking**"。但子任务在官方 218MB 二进制里 `grep -i diagnosticTracking` **0 命中**——这个词不是官方的字面标识符，是 Hermes 作者对该机制的功能性命名。官方真实的对外标签叫 `<new-diagnostics>`、方法叫 `getNewDiagnostics`。机制实质完全对得上，命名是 Hermes 自己起的。Hermes 注释还诚实标注它移植的是 Claude Code 的 `beforeFileEdited`/`getNewDiagnostics` 模式（`manager.py:24-26`、`file_operations.py:1177-1179`），只是接到本地 LSP 而非 MCP IDE RPC。

回灌给模型的 prompt 包裹标签（二进制原文确证）：

```
<new-diagnostics>The following new diagnostic issues were detected:
${formatDiagnosticsSummary(...)}</new-diagnostics>
```

单条格式（二进制原文）：`符号 [Line N:M] message [code] (source)`，4000 字符上限，超长 `…[truncated]`。**注意名字里的 `new`**——和 Hermes 一样，Claude Code 也只回灌"新增"诊断，不是全量。

---

## 三、流程分析：编辑落盘后那几百毫秒发生了什么

三家的闭环都是"写前快照（可选）→ 落盘 → 触发 LSP → 等诊断稳定 → 过滤 → 格式化 → 回灌"，但精度不同。分三段看。

### 第一段：触发与等待——怎么知道 LSP "算完了"

LSP 是异步的：你告诉它文件变了，它在后台慢慢算，算完通过 `publishDiagnostics` 推回来。难点是**什么时候认为诊断已经稳定**，太早读拿到旧结果，太晚读白白阻塞。

**OpenCode**（`client.ts:499-519`）用"push 事件 + pull 轮询竞速"：
- 一边监听 `textDocument/publishDiagnostics` 推送，命中后做 **150ms 防抖**（`DIAGNOSTICS_DEBOUNCE_MS=150`）再 resolve
- 一边主动 `requestDocumentDiagnostics` 轮询拉
- `Promise.race` 谁先到用谁，document 模式 **5s 硬超时**（`DIAGNOSTICS_DOCUMENT_WAIT_TIMEOUT_MS=5000`），单次 pull 请求 3s 超时
- TypeScript server 特例：首次 push 直接 seed 缓存，免等第二次防抖（`client.ts:116-121`）

**Hermes**（`client.py:793-844`）几乎同款：document pull task + push wait task 并发 `FIRST_COMPLETED`，push 侧带防抖，document 模式 **5s**、full 模式 **10s**（`client.py:70-71`）。

**Claude Code**：官方二进制里**取不到**绑定到诊断采集的固定 sleep/debounce 常量。它用的是 registry 异步交付模型——`getLSPDiagnosticAttachments` 维护 pending set，带版本号陈旧丢弃（"Dropping stale publishDiagnostics ... server v{} < current v{}"）、去重、单文件/总量限流。即"事件到了就投递、旧版本丢弃"，而非定时等待。（第三方 Rust 复刻用了固定 `tokio::timeout(2s)` 轮询，但那是复刻自己的选择，**不能反推官方**。）

### 第二段：过滤——新旧错误的分水岭

这是三家拉开差距的一段。

**OpenCode：不区分。** `edit.ts:199-200` 直取当前文件全部 ERROR，无快照、无 diff。模型看到文件里所有的错，包括编辑前就有的。三个写工具广度不同：
- `edit` 只报被编辑文件本身（`edit.ts:200`）
- `apply_patch` 遍历本次改动的每个文件分别 report（`apply_patch.ts:286-293`）
- `write` 唯一会跨文件：除当前文件外还顺带报其他文件的 error，上限 5 个文件（`MAX_PROJECT_DIAGNOSTICS_FILES=5`，`write.ts:18,81,88`）

**Hermes：精确增量。** 完整三步（`manager.py:357-378`）：
1. 取编辑前 baseline（写前 `snapshot_baseline` 存的，`manager.py:281-300`，外层 8s 超时）
2. 若编辑改了行数，用 `shift_baseline` 把 baseline 行号映射到编辑后坐标（`manager.py:366-367`）
3. 集合差 `_diag_key not in seen` 滤掉旧错（`manager.py:368-369`）
4. **roll forward**：把当前全量诊断写回 baseline（`manager.py:373-378`，2s 超时），下次编辑的增量是相对"刚才"算的——这正是注释说的 mirroring claude-code 的 diagnosticTracking 滚动基线

**Claude Code：增量（官方确证）。** `getNewDiagnostics` 的逻辑（二进制原文）是：拉全量诊断后 `.filter(O => this.baseline.has(normalizeFileUri(O.uri)))`，只保留 baseline 已追踪 URI 上的诊断，再比对出新增。prompt 标签直接叫 `<new-diagnostics>`。触发绑定编辑工具：仅当工具集含 Edit/Write 类工具才采集（`H.options.tools.some(...)`）。诊断有两条来源：IDE-MCP（`mcp__ide__getDiagnostics`，source=`ide-mcp`）和内建 LSP（source=`lsp`）。

一句话对比这段：

| | 新旧错误区分 | 行号平移处理 | 滚动基线 |
|---|---|---|---|
| OpenCode | ❌ 全量回灌 | 不需要（无基线） | 无 |
| Hermes | ✅ 集合差 | ✅ difflib opcode 重映射 | ✅ |
| Claude Code | ✅ baseline filter | 推断有（areDiagnosticArraysEqual） | ✅（getNewDiagnostics） |

### 第三段：回灌与降级——把错误送进上下文，且绝不弄坏写入

**回灌形态**三家都是把格式化文本拼进 tool result，让模型下一轮直接读到：
- OpenCode：拼进 `output` 字符串，`LSP errors detected in this file, please fix:`（`edit.ts:201`）
- Hermes：独立字段 `WriteResult.lsp_diagnostics`，前缀 `LSP diagnostics introduced by this edit:`（`file_operations.py:1738`）——和 syntax lint 分两个 channel
- Claude Code：作为 attachment 包进 `<new-diagnostics>` 标签

> Hermes 这句 `introduced by this edit` 正是它系统 prompt 里"only NEW errors introduced by this write are surfaced (pre-existing errors are filtered out)"那句话的代码出处——文档承诺和实现严丝合缝。

**降级哲学**：三家都遵守"验证是增强层，绝不能弄坏一次写入"：
- OpenCode：`touchFile` 整个 `.catch(() => {})`（`lsp.ts:362`），LSP 失败就是 output 不含错误块，编辑照样成功
- Hermes：`get_diagnostics_sync` docstring 明写 **"Never raises"**（`manager.py:330-332`），超时/异常一律 `return []`；工具层三重 try/except（`file_operations.py:1673,1729`）；非 local backend（Docker/Modal/SSH）直接跳过，因为 server 看不到 sandbox 内文件；**且 LSP 只在 syntax lint 通过后才触发**——连 parse 都过不了的文件没必要问 LSP（`file_operations.py:1224-1226`）
- Claude Code：`getNewDiagnostics` 里 MCP 未连接或异常直接 `return []`

熔断更进一步：Hermes 的 `_mark_broken_for_file`（`manager.py:386-432`）在 server spawn 超时后拉黑该 server，注释直言"否则后续每次写入都要重新走 spawn 路径、重付 8s 超时，直到二进制被修好"——把"一个坏 LSP 拖垮所有编辑"的故障隔离掉。

---

## 四、提炼原理：观察的信噪比，才是 agent loop 的胜负手

把三家放一起，能看到一条清晰的演进谱系，本质是 **对"观察质量"的认知深度**：

1. **有验证 > 没验证**：三家都意识到 LLM 需要外部校验器闭环。这是 agent 从"代码生成器"到"会自查的工程师"的第一步。

2. **增量 > 全量**：OpenCode 全量回灌简单可用，但把历史噪声一起塞给模型，模型可能跑偏去修不相干的错。Hermes/Claude Code 的 baseline diff 只回灌"你这次造的孽"，信噪比高一个量级。**这不是小优化——它直接决定模型纠错时盯的是不是正确的目标。**

3. **行号平移处理 = 魔鬼在细节**：Hermes 的 `range_shift` 是最容易被忽略、却最见功力的一笔。没有它，"删了几行导致下方旧错全部平移"会让集合差误判一片新错，增量退化成全量。这种细节决定了增量方案是真好用还是纸面好看。

4. **降级与熔断 = 工业级与玩具的分界**：验证层失败时绝不能阻断主流程（never raises），坏 server 要能熔断隔离。Hermes 在这块做得最厚——它假设 LSP 一定会偶尔抽风，并为此设计。

底层是同一个 agent loop 原理：**循环的每一步，模型的决策质量取决于上一步观察的质量。** 给它全量噪声，它就在噪声里打转；给它精准的"你刚改坏的这一处"，它一击即中。验证机制的全部精巧，都在为"让观察更聚焦"服务。

---

## 五、对手动用 agent 的启发

1. **没接 LSP 的 agent，让它"自己跑一遍验证"**。如果你的 agent 环境没有这套自动诊断回灌（比如裸用某些 CLI），改完代码后**显式要求它跑一次 `tsc --noEmit` / `ruff` / `cargo check` 并把输出贴回来再继续**。手动补上这个闭环，纠错质量立刻不同。

2. **盯住"它在修哪个错"**。如果 agent 改完一处后突然跑去动一段你没让它碰的代码，很可能是它的验证是全量的、被历史报错带偏了。这时手动把范围圈死："只修你这次改动引入的报错，文件里原有的别动。"

3. **验证失败别让它瞎猜**。如果 LSP/编译器超时拿不到结果，好的做法是停下来说"没拿到诊断"，而不是假装文件没问题继续往下写。要求 agent 在验证环节诚实标注"未能验证"，比它编一个"看起来没问题"安全得多。

4. **这套思路可迁移到非代码场景**。"行动后验证 + 只回灌新增问题"是通用模式：让 agent 写完一份报告后，只检查它本次新增段落的事实/数字，而不是把整篇重核一遍——同样是用 baseline diff 提升观察信噪比。

---

## 关联

- 同系列：`2026-06-22-tool-schema-and-output-governance`（工具输出治理）、`2026-06-22-context-governance-analysis`（上下文治理）
- 机制归属：本文属 **Agent Loop**（行动—观察—反思闭环里的"观察"质量）；与 Tool Use（编辑工具本身）、Context Engineering（回灌占用上下文）正交相关
- 取证方法论：官方不开源时用二进制 `strings` 抠嵌入 prompt + 常量（确证），第三方复刻仅作旁证，推断必标推断
