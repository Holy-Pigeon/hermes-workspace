# 长期记忆系统：agent 怎么记住"你是谁、这个项目有什么规矩"

> Doc Type：分析文 ｜ Category：Memory ｜ Maturity：验证过
> 取证对象：OpenCode（`/tmp/oc-src` @ `cd292a4`，真实源码）、Hermes Agent（`~/.hermes/hermes-agent`，真实源码）、Claude Code v2.1.161（官方二进制 `claude.exe` 218MB，`strings` 一手取证 + 第三方 Rust 复刻旁证）
> 所有结论标注 `文件:行号` 或 `strings 命中原文`；推断部分明确标"推断"；官方二进制取不到的明确标"取不到"。

---

## 一、问题引入：会话一关，agent 就"失忆"了

每个 agent 会话本质上是**一次性的**。你这轮跟它说清了"我用 homebrew 的 python3，系统那个太老会崩"，它这轮记住了；下次开个新会话，它又一脸茫然地用回 `/usr/bin/python3`，重新把你气一遍。

这就是长期记忆要解决的根本问题：

> 怎么把**跨会话有效的事实**——用户是谁、偏好什么、项目有什么约定、上次踩过什么坑——持久化到磁盘，并在未来的会话里自动喂回给模型，让它不必每次从零开始认识你？

注意要先划清一条边界，否则全文会跑偏：**长期记忆 ≠ 会话内的上下文压缩（compaction）**。

- **compaction** 处理的是"这一个会话太长了、塞不下了"，把早期对话摘要掉，是**会话内**、**临时**的（会话结束即烟消云散）。
- **长期记忆** 处理的是"这个事实下个会话还得用"，落到磁盘文件，是**跨会话**、**持久**的。

本文只谈后者。三家在这件事上的分歧，比检索那篇大得多——因为长期记忆触及一个更尖锐的设计抉择：

> 记忆到底**谁来写**？是让用户/agent 手动维护一份明文文件，还是给模型一个"写回记忆"的工具让它自己沉淀，甚至让系统在后台**自动**总结写入？

这条"谁来写、写到哪、何时读"的光谱，把三家清楚地拉开了档次。先把结论摆出来，后面逐层坐实：

> - **OpenCode 在光谱最左端**：纯静态文件（`AGENTS.md`），没有任何"写回记忆"工具，全靠人/prompt 软提示去手动改文件。
> - **Hermes 在中间**：有一个结构化的 `memory` 工具（agent 主动调），加一个"定期让子 agent 复盘并写回"的半自动机制，落到两个字符预算受控的 markdown 文件。
> - **Claude Code 在最右端（v2.1.161）**：已经进化成"分层记忆文件 + 服务端记忆 store + 版本快照 + 后台 Dream 自动巩固/修剪"的复杂系统，记忆能被 agent 自动管理。

这是一条清晰的"从静态到动态、从手动到自治"的演化轴。

---

## 二、数据结构设计：记忆存在哪、长什么样、有没有写入工具

长期记忆的全部设计，可以拆成三个问题：**记忆的载体是什么（文件还是结构化 store）？有没有给模型一个写记忆的工具？记忆怎么分层（用户级 vs 项目级）？** 三家在这三个问题上的答案，恰好对应上面那条演化轴。

### 2.1 记忆载体：从明文 md 到结构化 store

| 维度 | OpenCode | Hermes | Claude Code |
|---|---|---|---|
| 载体 | 纯静态 Markdown | 两个 markdown 文件（§ 分隔条目） | 分层 md 文件 **+** 服务端记忆 store |
| 文件 | `AGENTS.md` / `CLAUDE.md` / `CONTEXT.md` | `MEMORY.md`（agent 笔记）+ `USER.md`（用户画像） | `CLAUDE.md` / `CLAUDE.local.md` + 服务端 `memory_store` |
| 取证 | `instruction.ts:60-68` | `memory_tool.py:55-57, 245-250` | strings: `~/.claude/CLAUDE.md`、`memories.create(store_id, path=...)` |
| 有无结构化存储 | 无（就是明文 md） | 无独立 DB，md 内用 `§` 分隔条目 | **有**：服务端 `/v1/memory_stores`，REST CRUD |

三家的载体复杂度，直接体现了演化程度：

- **OpenCode**：记忆就是仓库里的明文 markdown，没有任何隐藏结构。`instruction.ts:60-68` 列出查找列表——全局看 `~/.config/opencode/AGENTS.md` 和 `~/.claude/CLAUDE.md`，项目级看 `AGENTS.md`/`CLAUDE.md`/`CONTEXT.md`（`CONTEXT.md` 注释标 deprecated）。**透明、可 git、可手改，但也仅此而已。**
- **Hermes**：仍是 markdown，但内部用分隔符 `ENTRY_DELIMITER = "\n§\n"`（`memory_tool.py:59`）把记忆切成一条条独立条目，写盘是整个条目列表 join 后**原子改写整文件**（temp file + `atomic_replace`，`memory_tool.py:570-599`）。比 OpenCode 多了"条目"这个粒度。
- **Claude Code**：strings 里同时出现两套——本地 `CLAUDE.md`/`CLAUDE.local.md` 文件，以及一套**服务端记忆 API**：`memories.create(store_id, path=..., content=...)` / `retrieve` / `update` / `list` / `delete`，对应 REST `/v1/memory_stores/...`。记忆已经从"仓库里的文件"升级成"挂在 session 上的远程资源"，且每次 mutation 都生成不可变版本快照 `memver_...`（strings 原文："immutable `memver_...` snapshot. Versions accumulate for the lifetime of the parent memory"），提供审计与回滚。

### 2.2 写记忆工具：这是分水岭

> **OpenCode 没有给模型任何"写回记忆"的工具。**

这是取证里最干脆的一条。OpenCode 的 `tool/` 目录 42 个工具，逐个看下来**没有 `memory.ts` / `remember.ts`**。`memory` 这个词在 `src/` 里只命中 `prompt/beast.txt`、`prompt/copilot-gpt-5.txt`、`prompt/gemini.txt`——而这些是**原样收录的第三方厂商 prompt 文案**（Copilot "Beast Mode" 等），OpenCode 并没有为它们实现配套工具。模型想沉淀点什么，只能用通用的 `write`/`edit` 去改 `AGENTS.md`，且要不要改全凭系统 prompt 的一句软提示（`default.txt:75`："proactively suggest writing it to AGENTS.md so that you will know to run it next time"）——**不保证执行**。

Hermes 则有一个**结构化的 `memory` 工具**，schema 定义在 `memory_tool.py:652-701`：

| 字段 | 取值 | 取证 |
|---|---|---|
| `action` | `add` / `replace` / `remove` | `memory_tool.py:680-683` |
| `target` | `memory`（agent 笔记）/ `user`（用户画像） | `memory_tool.py:685-688` |
| `content` | 字符串，add/replace 必填 | `memory_tool.py:690-692` |
| `old_text` | 短唯一子串，定位 replace/remove 的目标条目 | `memory_tool.py:694-696` |

三个动作各自的文件操作（`memory_tool.py`）：
- **add**（`:297-345`）：strip → 威胁扫描 → 文件锁 → 重读盘 → **精确去重**（`content in entries` 命中即返回"已存在"，`:321-322`）→ 预算检查 → append → 整文件原子改写。
- **replace**（`:347-405`）：用 `old_text in e` **子串匹配**定位（`:367`），多条命中且文本不同则报错要求更具体（`:372-381`），命中后整条替换。
- **remove**（`:407-441`）：同样子串匹配，`entries.pop(idx)` 后整文件改写。

注意一个**文档与实现的偏差**：schema 的 `action` 枚举里**不含 `read`**（`:682`），但 docstring 多处提到 `memory(action=read)`，dispatch 分支（`:620-638`）只处理 add/replace/remove，else 报"Unknown action"——**read 不是已注册的合法 action**（推断为文档未同步）。

Claude Code 走得最远，记忆有三种 `memory_type`（strings 命中）：`team`（团队共享）、`auto`（自动管理）、以及个人/项目层。关键证据：
- **服务端 CRUD 工具**：`memories.create/retrieve/update/list/delete`，带 `expected_content_sha256` 做乐观并发控制（strings 原文）。
- **`#` 快捷写入**：strings 命中 `# Claude remembers "Alice"`、`# auto memory`——延续 Claude Code 经典的"输入以 `#` 开头即被当作要记住的事追加进记忆"。
- **自动管理记忆**：代码里有 `isAutoManagedMemory` 判定（strings），`auto memory files are allowed for reading/writing`——存在一类**由系统而非用户维护**的记忆文件。

### 2.3 记忆分层：用户级 vs 项目级 vs 团队级

| 层级 | OpenCode | Hermes | Claude Code |
|---|---|---|---|
| 用户/全局级 | `~/.config/opencode/AGENTS.md`、`~/.claude/CLAUDE.md`（`instruction.ts:61-62`）| `USER.md`（用户画像，profile 作用域）| `~/.claude/CLAUDE.md`（strings）|
| 项目级 | 项目内 `AGENTS.md`（findUp 到 worktree，`instruction.ts:64-68`）| `MEMORY.md`（agent 自己的项目笔记）| `Project CLAUDE.md`（strings）|
| 本地/私有级 | 无明确 | 无 | `Personal CLAUDE.local.md`（strings：不该 check-in 到团队共享文件的个人引用）|
| 团队级 | 无 | 无 | **Team memory**（`team/` 子目录，strings："shared with all repository collaborators"）|

分层的精细度同样拉开档次。OpenCode 分"全局/项目"两层；Hermes 用**语义**而非位置分层（`memory`=agent 笔记 vs `user`=用户画像，`memory_tool.py:5-9`），都在 profile 目录下；Claude Code 分到**四层**，且明确区分"团队共享"与"个人私有"——strings 里甚至有一条治理规则原文："that would check a personal reference into the team-shared file"（防止把个人引用误写进团队文件）。

### 2.4 Hermes 独有：字符预算

Hermes 是三家里唯一对记忆做**硬性容量上限**的（`memory_tool.py:124`、config `config.py:1541-1551`）：
- `memory_char_limit = 2200`（≈800 tokens）、`user_char_limit = 1375`（≈500 tokens）。
- 用**字符数而非 token**，理由原文："char counts are model-independent"（`memory_tool.py:17`）——模型无关、可预测。
- 系统 prompt 里那个 `98% — 2160/2200 chars` 的进度条就来自这里（`_render_block`，`memory_tool.py:475-491`）。超限直接拒绝写入，提示"先 replace/remove"（`:328-339`）——**把取舍决策推给模型**，而不是自动淘汰。

这是个很有意思的设计点：OpenCode/Claude Code 的文件记忆理论上能无限长（代价是 token 爆炸），Hermes 用一个写死的字符预算逼模型"记账"——记忆满了就得先删旧的才能记新的。

---

## 三、流程分析：记忆何时写 → 何时读 → 怎么喂回模型

把数据结构串成动态流程，长期记忆的生命周期是三段：**写入（沉淀）→ 读取（加载）→ 注入（喂回 prompt）**。三家在"写入由谁触发"和"读取是否实时"这两个节点上分歧最大。

### 3.1 写入：从"人工改文件"到"后台自动巩固"

这是三家差异的核心，正好排成一条自动化程度递增的阶梯：

**OpenCode —— 全手动 + prompt 软提示。** 两条路径：(1) 用户直接编辑 `AGENTS.md`；(2) agent 跑 `/init` 命令（`command/index.ts:78-86`，"guided AGENTS.md setup"），按 `command/template/initialize.txt` 模板用通用 write 工具生成 `AGENTS.md`。模板会让模型读 README/CI/lockfile，提取"高信号、仓库特有"的命令写进去。但这全程**靠通用 write 工具 + prompt 提示**，没有专门的记忆 API，沉不沉淀全看模型自觉。

**Hermes —— agent 主动调 + 后台子 agent 半自动复盘。** 两条路径：
1. **主动**：schema description 内嵌"WHEN TO SAVE"行为指导（`memory_tool.py:654-675`）——用户纠正、透露偏好、发现环境事实时主动存；明确 SKIP 任务进度/临时 TODO；优先级"用户偏好与纠正 > 环境事实 > 流程知识"。
2. **后台复盘（nudge）**：每 turn `_turns_since_memory += 1`（`conversation_loop.py:552-559`），达到 `_memory_nudge_interval`（默认 10）就在**回合结束后**（响应已交付给用户）spawn 一个**后台 review agent**（`background_review.py`）。这个 fork 共享父进程的 `_memory_store`，白名单只给 memory/skill 工具（`:459-472`），用 `_MEMORY_REVIEW_PROMPT`（`:34-43`）让它复盘"用户是否透露了画像/期望"并自行调 `memory` 工具保存。**关键：它不是正则自动抽取，而是让一个子 agent 用同一个 memory 工具去复盘——仍走工具、受同样的预算/去重/扫描约束。**

**Claude Code —— `#` 快捷 + 服务端 store + 后台 Dream 自动巩固。** 写入路径最丰富：
1. **`#` 快捷写入**（经典机制，strings 佐证 `# Claude remembers`）。
2. **服务端 store CRUD**（agent 调 `memories.create/update/delete`）。
3. **Dream —— 自动巩固/修剪。** 这是 v2.1.161 最值得记的新东西。strings 抠出两段完整 prompt 原文：
   - `# Dream: Memory Consolidation` —— "You are performing a dream — a reflective pass over your memory files. Synthesize what you've learned recently into durable, well-organized memories."（把近期学到的东西综合成持久、组织良好的记忆）
   - `# Dream: Memory Pruning` —— "a pruning pass over your memory files. The job is small: delete stale or invalidated memories, and collapse duplicates."（删除过时/失效记忆，合并重复）
   - 触发是**基于时间和会话数的阈值**：strings 命中 `[autoDream] firing — ${z}h since last, ${Y.length} sessions to review`，以及 `minHours`/`minSessions` 配置和 `.consolidate-lock` 锁文件。即：距上次巩固超过 N 小时、且有 M 个会话待复盘时，后台自动"做梦"整理记忆。

把三家的写入触发并排看，是一条非常清晰的自动化阶梯：**OpenCode（人手改）→ Hermes（agent 调工具 + 定期子 agent 复盘）→ Claude Code（agent 调 + 系统后台 Dream 自动巩固修剪）**。

### 3.2 读取与注入：实时生效 vs 冻结快照

记忆写完了，什么时候、以什么方式喂回模型？这里 Hermes 有一个反直觉但很关键的设计。

**OpenCode —— 启动期注入 system prompt + read 时就近补充。** 两条路径：
- **路径 A（启动期）**：`instruction.system()`（`instruction.ts:155-169`）收集路径、读文件、包装成 `"Instructions from: <path>\n<content>"`，在 `prompt.ts:1315` 拼进 system 数组。**多层 AGENTS.md 取首个不堆叠**——`systemPaths()` 项目级 findUp"第一组匹配即 break"（`:122-133`，注释原文 "so we don't stack AGENTS.md/CLAUDE.md from every ancestor"）。
- **路径 B（read 时就近）**：`tool/read.ts:300` 每次读文件时调 `instruction.resolve()`（`:179-221`），从被读文件所在目录向上走，沿途的子目录 `AGENTS.md` 按需动态补充进来，每条每个 message 只附一次（`s.claims` 去重）。即根/全局走 A、子目录走 B 的"按需逐层补充"。

**Hermes —— 冻结快照，每 session 一次，mid-session 写不改当前 prompt。** 这是最值得记的一条：
- 初始化时 `MemoryStore.load_from_disk()`（`memory_tool.py:132-170`）读两文件 → 去重 → 威胁扫描 → 生成 `_system_prompt_snapshot`。
- 注入点 `system_prompt.py:303-312`，`format_for_system_prompt` **只返回这个冻结快照，不返回 live 状态**（`memory_tool.py:443-454`）。
- **后果**：mid-session 用 memory 工具写的记忆**立即落盘**（持久化是真的，`:343,403,439`），但**当前会话的系统 prompt 不会变**——要等下个 session 启动重新 load 才被模型"看见"。
- **为什么这么设计？** 注释说得很直白：保 **prefix cache 稳定**（`memory_tool.py:11-14`）。系统 prompt 整体每 session 只构建一次并缓存，仅在 context compression 后才重建（`system_prompt.py:347-360`）。如果记忆一写就改 system prompt，整个 prompt 前缀的 KV cache 全部失效，每次都要重算——`background_review.py:439-441` 提到这能省约 26% 成本。**Hermes 用"记忆延迟一个会话生效"换取了缓存命中率。**

**Claude Code —— 注入 system prompt + 用前先核验。** strings 佐证 "Project CLAUDE.md instructions are loaded in your system prompt"、"loaded into every Claude Code session, so it must be concise"。更有意思的是它内置了一段**"用记忆前先核验"的纪律**（strings 原文 `## Before recommending from memory`）："A memory that names a specific function, file, or flag is a claim that it existed when the memory was written. It may have been renamed, removed, or never merged. Before recommending it: 检查文件是否存在 / grep 这个函数或 flag。" 并且明确了**记忆与 CLAUDE.md 冲突时的裁决**："CLAUDE.md is the maintained, checked-in source. Delete the memory, or rewrite it to agree"（CLAUDE.md 是权威，记忆若与之矛盾则删或改）。

### 3.3 去重与冲突检测

三家都意识到记忆会重复、会过时、会冲突，处理力度递增：
- **OpenCode**：无专门去重机制（就是文本文件，靠 `/init` 模板提示模型"原地改进"）。
- **Hermes**：load 时 `dict.fromkeys` 去重（`memory_tool.py:157-158`）+ add 时精确匹配拒绝重复（`:321-322`）；还有**外部漂移检测** `_detect_external_drift`（`:515-568`）——若磁盘文件被 patch 工具/shell/手改/姊妹 session 改过导致不能 round-trip，则备份 `.bak.<ts>` 并**拒绝写入**（防止互相覆盖，issue #26045）。属精确匹配去重，无语义去重。
- **Claude Code**：Dream Pruning 专门"collapse duplicates"（语义级合并重复）；记忆指令原文 "Do not write duplicate memories. First check if there is an existing memory... Delete existing memories that are superceded"——**让模型在写入时就主动查重、淘汰被取代的旧记忆**。

---

## 四、设计取舍：静态文件 vs 动态自治记忆，各自的代价

把三条路线摆在一起，本质是在回答："记忆系统该做多重？"

**OpenCode 的极简主义（纯静态文件）：**
- 好处：透明可审计、可 git 版本化、人可直接编辑、与 Claude Code/Cursor 生态互通（`initialize.txt` 还读 `.cursorrules`），实现复用现成 read/write，零额外存储。"取首个不堆叠"控住了 token 预算。
- 代价：**模型没有原子的"记住这条"能力**，沉淀全靠 prompt 软提示，不保证执行；记忆是粗粒度文本块，无字段、无检索、无淘汰；全文塞 system prompt，越大越费 token。

**Hermes 的中间路线（结构化工具 + 字符预算 + 冻结快照）：**
- 好处：有原子的 add/replace/remove，记忆可控；字符预算逼模型记账、防膨胀；冻结快照保住 prefix cache（省钱）；后台 nudge 复盘让记忆"自动长出来"但仍走工具受约束；漂移检测防多 session 互相踩。
- 代价：**记忆延迟一个会话才生效**（冻结快照的直接后果，本会话内学到的下个会话才用得上）；字符上限是硬墙，满了必须删才能写；只有精确去重，无语义去重。

**Claude Code 的重型自治（分层 + 服务端 store + 版本快照 + Dream）：**
- 好处：分层精细（团队/项目/个人/auto），服务端 store 带版本快照可审计可回滚，Dream 让记忆**自我巩固和修剪**（不靠用户维护就能保持整洁），并内置"用前核验""冲突时 CLAUDE.md 权威"的纪律对抗记忆陈旧。
- 代价：**复杂度最高**——服务端依赖（team memory server 可能 "marked not-available"）、Dream 是额外的后台 LLM 开销（strings 里 Dream 完成会打印 cache read/created token 数，说明它真的烧 token）、自动管理的记忆对用户是"黑盒"（不像一个 md 文件那样一眼能看全）。

一句话收束：**记忆系统的复杂度，本质是在"模型能多自治地维护自己的记忆"和"用户能多透明地掌控记忆"之间权衡。** OpenCode 把控制权完全交给用户（你自己改文件），Claude Code 把维护权大幅交给模型（Dream 自动整理），Hermes 卡在中间（agent 能写但受字符预算和冻结快照约束，用户随时能看那两个 md 文件）。

---

## 五、对"我自己怎么用 agent"的启发

1. **别指望 agent 默认记得住——主动喂"记忆文件"。** OpenCode 这种纯静态路线说明：很多 agent 的"长期记忆"就是个让你手填的 `AGENTS.md`/`CLAUDE.md`。与其每次重复交代环境，不如一次性把"我用 homebrew python3""这个项目的约定是 X"写进项目根的 markdown，让它每个会话自动加载。
2. **记忆会过时，是记忆系统最大的暗坑。** Claude Code 专门内置"用记忆前先核验文件/函数还在不在"的纪律，不是多余的——一条"用 foo() 函数"的记忆，半年后那函数可能早被重命名了。**对待 agent 给的、源自旧记忆的建议，保持和对待旧文档一样的警惕。**
3. **记忆不是越多越好，要主动淘汰。** Hermes 的字符预算和 Claude Code 的 Dream Pruning 都在干同一件事——**控制记忆总量、删掉过时的**。记忆膨胀会稀释注意力、增加成本。定期清理"已经不成立的旧记忆"和定期记新东西一样重要。
4. **冲突时谁说了算要事先定。** Claude Code 明确"CLAUDE.md（人维护的、check-in 的）> 自动记忆"。如果你同时用手写规则和 agent 自动记忆，**心里要有一个优先级**：人工明确写下的约定，永远压过 agent 自己总结的。

---

## 取证小结

- **载体演化**：OpenCode 纯静态 md（`instruction.ts:60-68`）→ Hermes md + § 条目（`memory_tool.py:59`）→ Claude Code 分层 md + 服务端 store + `memver_` 版本快照（strings）。
- **写记忆工具**：OpenCode **无**（42 个工具里没有，靠通用 write）；Hermes 有结构化 `memory` 工具 add/replace/remove（`memory_tool.py:652-701`）；Claude Code 有服务端 CRUD + `#` 快捷 + Dream 自动巩固。
- **注入模式**：OpenCode 启动期取首个 + read 时就近补充（`instruction.ts:155-221`）；Hermes **冻结快照**、每 session 一次、mid-session 写不改当前 prompt（为保 prefix cache，`memory_tool.py:11-14, 443-454`）；Claude Code 注入 system prompt + "用前核验"纪律（strings）。
- **写入触发自动化阶梯**：OpenCode 人手改 → Hermes agent 调工具 + 后台子 agent nudge 复盘（`conversation_loop.py:552-559`、`background_review.py`）→ Claude Code agent 调 + 后台 Dream 自动巩固/修剪（strings 两段 prompt 原文 + `[autoDream]` 触发日志）。
- **分层**：OpenCode 全局/项目两层；Hermes 语义分层（memory/user）；Claude Code 四层（team/project/personal/auto）。
- **去重**：OpenCode 无；Hermes 精确去重 + 漂移检测拒写（`memory_tool.py:515-568`）；Claude Code Dream 语义合并重复 + 写入时主动查重淘汰。

**未取证/读不到**：Claude Code 服务端 store 的具体存储后端、Dream 的精确触发阈值数值（只确证有 `minHours`/`minSessions` 但未读到默认值）、`#` 快捷的完整最新提示语（strings 仅命中示例 `# Claude remembers "Alice"`）——均标"取不到"，未编造。Hermes `memory(action=read)` 文档与实现的偏差已在 §2.2 标注。
