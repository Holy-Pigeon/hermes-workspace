# 代码库检索：agent 怎么"认识"一个它从没见过的仓库

> Doc Type：分析文 ｜ Category：Context Engineering ｜ Maturity：验证过
> 取证对象：OpenCode（`/tmp/oc-src` @ `cd292a4`，真实源码）、Hermes Agent（`~/.hermes/hermes-agent`，真实源码）、Claude Code v2.1.161（官方二进制 `claude.exe` 218MB，`strings` 一手取证 + 第三方 Rust 复刻旁证）
> 所有结论标注 `文件:行号`；推断部分明确标"推断"；官方二进制取不到的明确标"取不到"。

---

## 一、问题引入：模型的"上下文窗口"装不下一个代码库

你把 agent 丢进一个几十万行的陌生仓库，让它"把登录逻辑里的超时改成 30 秒"。模型面对的根本困境是：**它的注意力预算（上下文窗口）只有十几万到几十万 token，而代码库随便就是它的几十上百倍。** 它不可能把整个仓库读进脑子，必须先解决一个前置问题——

> 在海量文件里，**哪几个文件、哪几行**和当前任务相关？怎么用最少的 token 把它们捞出来？

这就是 **检索（Retrieval）**。它是 Context Engineering 的入口环节：检索决定了"什么进上下文"，而进上下文的东西决定了模型能不能干对活。检索捞错了、捞漏了，后面再强的推理都是空中楼阁。

历史上这件事有**两条根本不同的路线**，理解这个分歧是理解全文的钥匙：

**路线 A — 预构 repo map（地图派）**。代表是 aider。会话一开始，先用 ctags / tree-sitter 把全仓的函数、类、签名抽出来，建一张"代码地图"，再用 PageRank 之类的算法按重要性排序，把这张**压缩后的全库概览**塞进系统 prompt。模型一上来就对仓库有"鸟瞰视角"，知道有哪些模块、关键符号定义在哪。代价是：启动要花算力解析全仓，地图本身占 token，仓库一变地图就要重建。

**路线 B — agentic 按需检索（探子派）**。不预先建任何地图。会话开始时模型对仓库几乎一无所知，靠**自己在对话循环里调检索工具**（grep 搜内容、glob 找文件、read 读文件）一轮一轮地探。像派探子进城打探，而不是先发一张地图。代价是模型没有先验全貌，定位要多轮试探、烧更多回合。

本文最反直觉的取证结论先放这里：

> **Claude Code、OpenCode、Hermes 三家，无一例外全部走路线 B（agentic 按需检索），没有任何一家预构 repo map。**

在前面几篇分析里，三家往往在设计上分道扬镳（压缩策略、权限哲学各不同）；但在"怎么认识代码库"这件事上，它们**罕见地高度一致**。这个一致本身就是强信号——下面先坐实它，再看三家在一致的大方向下，于"符号级检索能力"这个二阶细节上如何分出深浅。

---

## 二、数据结构设计：检索工具的参数与返回值

既然不建地图，那么"检索"这件事就**完全等价于几个工具的设计**。模型能捞到什么、捞多少、以什么格式拿到，全由这几个工具的 schema 决定。三家的检索工具惊人地收敛到同一组原语：**grep（搜内容）+ glob（找文件）+ read（读文件）**，底层几乎都压在 ripgrep 上。

### 2.1 grep / 内容搜索：底层都是 ripgrep

| 维度 | Claude Code | OpenCode | Hermes |
|---|---|---|---|
| 工具名 | `Grep` | `grep` | `search_files`（target=content）|
| 底层 | ripgrep（确证）| ripgrep（确证）| ripgrep，缺失时回退 grep |
| 取证 | description 原文 "built on ripgrep" / "Uses ripgrep (not grep)" | `grep.ts:5,24,63` → `core/src/ripgrep.ts:226-233` | `file_operations.py:1951-1962`，回退 `:1941-1943` |
| 输出模式 | content / files_with_matches(默认) / count | 文本分组（固定）| content / files_only / count（`file_tools.py:1470`）|
| 结果上限 | 默认 250 条（`head_limit`，0=不限）| 硬编码 100（`grep.ts:67,77`）| 默认 50（`file_operations.py:560-561`）|
| 截断提示 | "(Results are truncated. Consider using a more specific path or pattern.)" | "(more matches available)"（`grep.ts:96-99`）| "[Hint: Results truncated. Use offset=N ...]"（`file_tools.py:1354-1356`）|

三家的 grep 都做了**同一件关键的事：硬截断 + 提示**。Claude Code 250、OpenCode 100、Hermes 50。这不是抠门，是 Context Engineering 的刻意取舍——**宁可只给前 N 条、逼模型把 pattern 写得更准，也不愿把几千条匹配怼进上下文把窗口撑爆**。截断本身就是一种注意力预算管理。

值得单独点出的两个工程细节：
- **Claude Code 的 description 明文禁止模型直接调 `grep`/`rg` 命令**（"NEVER invoke grep or rg as a command"），强制走 Grep 工具——为的是统一权限与输出治理。
- **Hermes 加了防空转锁**：同一搜索连续 4 次直接 BLOCKED，第 3 次起加警告（`file_tools.py:1323-1349`）。这是对 agentic 检索一个真实病灶的补丁——模型容易拿同一个烂 pattern 反复搜、原地打转。

### 2.2 glob / 文件查找：按名字捞文件

| 维度 | Claude Code | OpenCode | Hermes |
|---|---|---|---|
| 工具名 | `Glob` | `glob` | `search_files`（target=files）|
| 底层 | ripgrep | `rg --files --glob`（`glob.ts:50` → `ripgrep.ts:157-168`）| `rg --files --sortr=modified -g`（`file_operations.py:1908-1912`）|
| 排序 | 按修改时间（description 原文）| — | 按 mtime 倒序（最近改的在前）|
| 上限 | 同 head_limit | 100（`glob.ts:49-51`）| 50 |

注意一个共同设计：**结果按修改时间倒序**（Claude Code 与 Hermes 都明确）。这是个很懂工程直觉的小细节——你在一个仓库里最近改过的文件，大概率就是当前任务相关的文件。用 mtime 排序，等于把"最可能相关"的文件顶到前面，配合截断，让有限的 N 条里信息密度最高。

### 2.3 read / 读文件：带行号、有多重上限

三家的 read 都不是"无脑全文吐出"，而是**带行号 + 多重上限**的受控读取：

- **Claude Code**：`Read` 默认读前 N 行，绝对路径，支持 PDF/ipynb（description 确证）。
- **OpenCode**：`read.ts` 默认 2000 行、单行 ≤2000 字符、≤50KB（`read.ts:13-17`）；超限提示用 offset 续读；**还兼任目录列举**（对目录路径返回 entries，`read.ts:264-298`）——OpenCode 没有独立的 `ls` 工具。
- **Hermes**：`read_file` 默认 500 行、max 2000，输出格式 `LINE_NUM|CONTENT`，>100K 字符拒绝（`file_tools.py:1375-1387`）。

行号是个被低估的设计。**带行号读 → 模型才能精确地说"改第 47 行" → edit 工具才能精确定位**。read 的输出格式，其实是为下游 edit 的输入格式服务的，这是工具链的隐性契约。

### 2.4 符号级检索（LSP）：三家深浅不一的分水岭

到这里三家高度一致。真正的差异在这一层——**有没有把"语言感知的符号检索"（跳到定义、找所有引用、列工作区符号）暴露给模型**。这是 grep 这种"纯文本正则"做不到的：grep 搜 `login` 会把注释、字符串、变量名全搜出来，而 LSP 的 `workspace/symbol` 能精确告诉你 `login` 这个**函数**定义在哪、被谁调用。

| | Claude Code | OpenCode | Hermes |
|---|---|---|---|
| LSP 符号检索能力 | 取不到证据（二进制无 workspace symbol 等命中）| **已实现并暴露**，但默认关闭 | 仅声明 capability，**从不实际请求** |
| 具体 | 靠 Task subagent 多轮 grep 近似 | 9 个操作：goToDefinition / findReferences / workspaceSymbol / documentSymbol / 调用层级等（`tool/lsp.ts:11-21`）| `client.py:367-369` 声明 definition/references/documentSymbol，但全仓只发 `textDocument/diagnostic`（`client.py:771-775`）|
| 门控 | — | 仅 `OPENCODE_EXPERIMENTAL_LSP_TOOL` 开（`registry.ts:234`，默认 false）| LSP 只用于编辑后诊断回灌，非检索 |

**结论分层**：
- **OpenCode** 走得最远——真做了一套完整的 LSP 符号工具（连 incoming/outgoing call hierarchy 都有），workspaceSymbol 每个 client 还做了 `slice(0,10)` 截断（`lsp.ts:439`）。但**默认关着**，要设实验 flag 才给模型用。等于"能力备好了，但默认不信任它，先让模型用 grep"。
- **Hermes** 的 LSP **纯粹是编辑后纠错的基础设施**，不是检索手段——它声明了符号能力但代码里从不发起符号请求，唯一实际用途是 patch/write 后拉诊断、把 lint/类型错误回灌给模型（`file_operations.py:1610-1734`）。符号定位完全降级为 grep。
- **Claude Code** 二进制里搜不到任何 workspace symbol 痕迹（确证 0 命中），符号级探索靠 **Task subagent 多轮 grep** 近似。

**一句话**：符号检索能力 OpenCode（有但默认关）> Hermes（有声明无实现）≈ Claude Code（取不到）。但**三家的默认主力都是 ripgrep 正则**——这再次印证了它们对 agentic 检索的押注：宁可用语言无关的、糙但稳的正则，也不默认依赖每语言一套、维护成本高的 LSP 符号图。

---

## 三、流程分析：模型从零认识一个代码库

数据结构铺完，看动态——一个对仓库一无所知的模型，**实际是怎么一步步把相关代码捞到眼前的**。这条流程三家几乎同构，分三段：启动注入 → 按需探索 → （可选）符号精定位。

### 3.1 第一段：启动注入——给的是"说明书"，不是"地图"

会话启动时，三家往系统 prompt 里塞的东西高度一致，而且**都刻意不塞文件树/目录树**：

- **OpenCode**：`<env>` 块只有工作目录、git 标志、平台、日期（`system.ts:61-72`），**无文件列表**；外加 AGENTS.md / CLAUDE.md 内容（`instruction.ts:155-169`，从 cwd 向 git root findUp，首个命中即停）。
- **Hermes**：`build_context_files_prompt`（`prompt_builder.py:1469-1508`）按"首个命中即用"装一种项目上下文文件（HERMES.md / AGENTS.md / CLAUDE.md / .cursorrules），每源 ≤20000 字符，注入前还过 prompt-injection 安全扫描（`:44-60`）；grep `os.walk|file_tree|repo_structure` **0 命中**——**不注入任何目录树**。
- **Claude Code**：注入 CLAUDE.md（业内确证），同样无预构地图证据。

这一段的设计哲学非常统一：**给模型的是一份"人工写的入门说明书"（AGENTS.md / CLAUDE.md），而不是一张"机器生成的代码地图"。** 这是路线 B 的必然——既然不预构 repo map，那对仓库的全局认知就交给人来沉淀（在 AGENTS.md 里写清架构、约定、关键路径），而非机器抽符号。OpenCode 的 initialize 命令模板甚至明说 AGENTS.md 是用来存"hard-earned context"的（`initialize.txt:33`）。

> 这对你（用户）的直接启发：**给 agent 配仓库时，认真写一份 AGENTS.md/CLAUDE.md，远比期待它"自己读懂全仓"有效。** 你写的说明书，就是它唯一的先验地图。

### 3.2 第二段：按需探索——grep/glob/read 的迭代循环

启动后模型对仓库的认知约等于零，于是进入 agentic 检索的核心循环：

```
模型有了任务
  → 不知道相关文件在哪
  → 调 glob 找候选文件（按 mtime 排序，截断前 N 条）
  → 调 grep 在内容里搜关键词（ripgrep，截断前 N 条 + 提示）
  → 调 read 读出最可疑的文件（带行号，分页）
  → 信息够了？够 → 干活；不够 → 拿新线索再 grep/glob/read
  → （回合数与 token 随探索深度增长）
```

这个循环就是"探子派"的本质：**用多轮工具调用，换取不预构地图省下的启动开销**。三家在这一段的差异只是工程润色：
- **Hermes** 加防空转锁（连搜 4 次同模式即 BLOCK）防止循环空转。
- **OpenCode / Claude Code** 引导把"开放式、跨多文件的探索"甩给 **Task/Agent subagent** 去做（Glob/Grep description 都明文写"open-ended search 用 Agent 工具"）——这是为了**把探索过程产生的大量中间 grep 结果隔离在子上下文里**，不污染主线程的注意力预算。这一步直接把检索和 Multi-Agent / Context Engineering 缝在了一起：subagent 的本质价值之一，就是当一次性的"检索 context 焚化炉"。

### 3.3 第三段：符号精定位（可选）

当正则不够、需要精确符号关系时（"这个函数到底被谁调用"），理论上走 LSP 符号检索。但如 2.4 所述，这一段在三家**默认都不走**：OpenCode 要开 flag、Hermes 没实现、Claude Code 取不到。实际生产里，模型多数时候靠 grep 正则 + read 上下文，把符号关系"读"出来，而非"查"出来。

### 3.4 渐进式补充注入（Hermes 的加分项）

Hermes 还有一个三家里独有的细节：`SubdirectoryHintTracker`（`subdirectory_hints.py:57`）——当模型用工具**首次进入一个新子目录**时，懒加载该目录下的 AGENTS.md/CLAUDE.md 并追加到**工具结果**（而非系统 prompt，保护 prompt 缓存，`:9-11`）。等于"探子走到哪个街区，才发哪个街区的本地说明书"。注释自陈灵感来自 Block/goose。这是对路线 B 的一个聪明缝补：全局地图不预发，但局部说明书随探索进度按需追加。

---

## 四、设计取舍：为什么三家都不要 repo map

把三家放一起，"全部选路线 B"这个一致结论，背后是一组共同的工程账：

**不预构 repo map 的好处（三家都吃到了）：**
- **零启动开销**：不需要会话一开始就 ctags/tree-sitter 解析全仓、跑 PageRank。大仓库尤其友好。
- **不预占注意力预算**：地图本身要占 token，agentic 路线把这部分窗口留给真正相关的代码。
- **零索引一致性问题**：仓库一改，地图就要重建/失效；不建地图就没这个维护负担。
- **押注成熟工具**：ripgrep 是工业级的、语言无关的、极快的（Hermes 注释称比 find 快约 200x，`file_operations.py:1824`），比自建符号图稳。

**代价（也三家共担）：**
- **模型没有全局先验**，定位靠多轮试探，回合数和 token 消耗高于"一上来就有地图"。
- **跨文件符号关系**（谁调用谁、定义在哪）在默认配置下只能用正则近似，不如 aider 的符号图精确。
- **硬截断可能漏长尾**（grep 100/250、workspaceSymbol slice 10）。

**三家共同的缓解手段，恰好构成一套完整方法论：**
1. **用 AGENTS.md/CLAUDE.md 让人工沉淀全局认知** —— 补上模型缺的"地图"，但由人写、按需读。
2. **用 subagent 隔离探索的 context 开销** —— 把检索产生的中间噪声关进子上下文。
3. **用 mtime 排序 + 硬截断 + 防空转锁** —— 在有限窗口里最大化检索的信噪比。
4. **把 LSP 符号能力作为可选项** —— 需要精确符号导航时再开，默认不背这个复杂度。

**最终定性**：在"怎么认识代码库"这个维度，三家做了**同一个根本判断**——与其花力气预构一张昂贵、易过期、占窗口的全库地图，不如把"认识代码库"做成模型在循环里用 ripgrep 一轮轮探的 agentic 能力，再用人工说明书（AGENTS.md）+ subagent 隔离 + 排序截断来补它的短板。这是 2024-2026 这一代编码 agent 的**集体技术选择**，也是 aider 式"地图派"在主流编码 agent 里逐渐让位于"探子派"的真实写照。

> 对你的最终启发：判断一个编码 agent 强不强，别问"它有没有代码库索引"，要问三件事——① 它的 grep/glob 截断给了多少、排序合不合理（决定单轮检索质量）；② 它会不会用 subagent 隔离探索（决定主上下文干不干净）；③ 它认不认 AGENTS.md（决定你能不能把全局认知喂给它）。这三点，比"有没有 repo map"重要得多。

---

记录日期：2026-06-23
成熟度：验证过
