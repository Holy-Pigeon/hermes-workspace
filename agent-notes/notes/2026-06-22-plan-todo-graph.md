# Plan / Todo Graph：Agent 的可更新计划结构

> 一句话结论：Agent 不能只靠一段自然语言计划干活，它需要一个**可被自己反复读写的结构化计划对象**。生产级实现里这个对象分成两层——单会话内是**扁平有序 list**（OpenCode/Claude Code 的 TodoWrite），多 Agent/长周期协作才升级成**带 blocks/blockedBy 依赖边的 DAG**（Claude Code 的 Task 子系统）。结构选型不是审美，是被「谁来消费这个计划、计划要活多久」逼出来的。

---

## 一、问题：为什么一段自然语言计划不够用

让 LLM「先列个计划再干」，最朴素的做法是让它在回复里写一段话：

```
我打算这样做：先读错误日志，然后检查 mainTemplate.gradle，
再验证生成后的 Gradle 文件，最后生成一个最小 patch。
```

这段话作为「给人看的说明」没问题，但作为「Agent 自己要执行和跟踪的计划」有四个硬伤：

1. **没有可寻址的状态**。第 2 步做到一半被打断，模型重新读上下文时，无法机械地判断「哪一步 done、哪一步 doing、哪一步 pending」——它只能靠重新理解整段自然语言，而自然语言理解是有损、会漂移的。
2. **没有单一事实源**。模型可能在第 5 轮说「我已经读完日志了」，第 12 轮又说「我先读一下日志」——两句自然语言之间没有任何强制一致性。状态散落在对话历史里，越长越不可靠（这正是 context rot 在「计划」这件事上的具体表现）。
3. **无法被 UI / 其他 Agent 消费**。前端要画进度条、要高亮当前步、子 Agent 要认领任务，都需要一个能 `JSON.parse` 的结构，而不是一段散文。
4. **依赖关系隐形**。「修 noCompress」和「排查 AAPT2 环境」到底谁挡谁、能不能并行，埋在自然语言里只能靠模型每次重读时临场推断，没法机械校验（比如检测「A 依赖 B、B 又依赖 A」这种死循环）。

结论先行：**计划必须从「对话里的一段文字」外化成「会话状态里的一个数据对象」。** 一旦外化，问题就变成——这个对象长什么样？

---

## 二、数据结构设计：从一条 item 该带什么字段推起

不看任何源码，纯从需求倒推一条计划 item 至少要承载什么。

**最小可用版本**——每条 item 要回答「这步做什么 + 做到哪了」：

```
TodoItem {
  content: string    // 这步做什么
  status:  string    // pending | in_progress | completed | cancelled
}
```

加上 status 的那一刻，「计划」就从静态文本变成了**状态机**：每条 item 在 pending → in_progress → completed 之间迁移，模型每次行动后更新它，UI 随时读它。这就解决了第一、二个硬伤——状态可寻址、有单一事实源。

**再加一个约束**会发生什么？如果规定「**全局同时只能有一个 in_progress**」，那么这个 list 立刻获得了一个隐含语义：**当前焦点**。模型不需要额外字段记「我现在在干嘛」，扫一遍 list 找那个唯一的 in_progress 就是答案。这是个极轻的设计，却把「注意力聚焦」编码进了数据结构本身。

**那依赖关系呢？** 你会很自然地想给 item 加上：

```
TodoItem {
  id:        string
  content:   string
  status:    string
  blockedBy: string[]   // 必须先完成的前置 item id
}
```

有了 `blockedBy`，计划就从**线性 list** 升级成了 **DAG**（有向无环图）：

```
        定位错误日志
             │
        检查构建配置
             │
          验证假设
          ╱       ╲
   修 noCompress   排查 AAPT2 环境
```

DAG 能表达「两个分支可并行」「这步必须等那步」，还能机械校验环（A 依赖 B、B 依赖 A 就是非法的）。看起来更强——**但它也更贵**：要维护 id、要做拓扑排序决定下一步、要检测环、模型每次更新要保证图的一致性。

**这里就是设计的岔路口**：到底该用扁平 list 还是 DAG？纯推理给不出答案，得看真实产品在「成本 vs 表达力」之间怎么权衡。下面用三份一手证据来定标。

---

## 三、源码验证：生产级 Agent 真实的计划结构

> 取证方法：OpenCode 读公开源码（commit `cd292a4`）；Claude Code 官方不开源，用官方二进制（v2.x，darwin-arm64）`strings` 抠嵌入的工具定义与常量。二进制证据是「产品里真实存在这段文案/字段」的硬证，但抠不出完整运行逻辑，相应结论的颗粒度会标注清楚。

### 证据 A：OpenCode 的 TodoWrite —— 扁平有序 list，刻意不要依赖边

`packages/core/src/session/todo.ts` 第 10-16 行，一条 todo 的完整 Schema：

```typescript
export const Info = Schema.Struct({
  content:  Schema.String,   // "Brief description of the task"
  status:   Schema.String,   // "pending, in_progress, completed, cancelled"
  priority: Schema.String,   // "high, medium, low"
})
```

只有三个字段：`content / status / priority`。**没有 id，没有 blockedBy，没有任何依赖边。** 这不是简化版——这就是 OpenCode 生产代码里 todo 的全部。

「顺序」从哪来？看它怎么存（同文件 update 函数）：写库前先整表删除，再带一个 `position` 索引按数组下标重新插入；读取时 `orderBy(asc(position))`。**顺序是数组位置，不是依赖关系。** 计划就是一个有序数组，没有图。

那遇到「这步被卡住、依赖别的事」怎么办？官方工具说明 `todowrite.txt` 第 28 行给了答案：

> If blocked or partial, keep it `in_progress` and add a follow-up todo describing the blocker.

**它明确拒绝用依赖边来表达阻塞**——不建 blockedBy 关系，而是「保持这条 in_progress + 新增一条描述阻塞的 follow-up todo」。这是一个非常关键的设计声明：在单 Agent、单会话的场景里，OpenCode 认定 DAG 的表达力**不值它的复杂度成本**，宁可用「加一条普通 todo」这种扁平手段绕过去。

同文件还坐实了「单焦点」约束（`todowrite.txt`）：

> `in_progress` - actively working (exactly ONE at a time)
> Keep exactly one `in_progress` while work remains

——和第二节纯推理推出的「唯一 in_progress = 当前焦点」完全吻合。

### 证据 B：Claude Code 的 TodoWrite —— 同样是扁平 list

官方二进制 `strings` 抠出的 TodoWrite 字段与约束，与 OpenCode 同构：每条 todo 带 `content`、一个进行时态的 `activeForm`（用于 UI 显示「正在做……」）、和 `status`；并反复强调 "exactly ONE" in_progress、"Update status in real time"、"Mark completed only after ... including any required verification"。

**结论同样清晰：Claude Code 给用户/模型日常用的 TodoWrite，也是扁平有序 list，没有依赖图。** 两家头部产品在「单会话计划」这件事上做了一模一样的选择——这不是巧合，是「单 Agent 线性推进」这个场景对结构复杂度的真实需求就这么低。

### 证据 C：Claude Code 的 Task 子系统 —— 这里才是真 DAG

抠二进制时在另一处发现了一组**完全不同**的工具定义，它独立于 TodoWrite，是一套面向「任务」而非「待办」的系统。原文（官方二进制内嵌的工具说明）：

```
Get a task by ID from the task list
## When to Use This Tool
- To understand task dependencies (what it blocks, what blocks it)
## Output
Returns full task details:
- subject:     Task title
- description: Detailed requirements and context
- status:      'pending', 'in_progress', or 'completed'
- blocks:      Tasks waiting on this one to complete
- blockedBy:   Tasks that must complete before this one can start
## Tips
- After fetching a task, verify its blockedBy list is empty before beginning work.
```

字段一目了然：`subject / description / status / **blocks** / **blockedBy**`。**这正是第二节推演的那个 DAG 结构**——每个任务显式声明「我挡着谁（blocks）」「谁挡着我（blockedBy）」，构成有向图。配套证据还有：

- 二进制里出现 `cyclicPrerequisite`（循环前置）常量 —— 说明它真的在**做环检测**，这是图结构才需要的校验，list 永远不会有环。
- 一组 `claim / already_claimed / [Tasks] Failed to claim task` 字符串 —— 任务可被**认领**，这是多 Agent 协作（多个 worker 抢任务）才需要的语义。
- 工具是 TaskCreate / TaskGet / TaskList / TaskUpdate 一整套 CRUD，而非 TodoWrite 那种「整表覆盖」的轻量写法。

**这就是全篇最硬的洞察**：同一个产品里**并存两种计划结构**，且是按使用场景刻意分化的——

| 维度 | TodoWrite（待办） | Task 系统（任务） |
|---|---|---|
| 数据结构 | 扁平有序 list | 带 blocks/blockedBy 的 **DAG** |
| 寻址 | 无 id，靠 position | 有 task id |
| 依赖表达 | 拒绝（用 follow-up todo 绕过） | 显式 blockedBy + 环检测 |
| 消费者 | 单 Agent 自己 + UI 进度条 | 多 Agent 协作（可 claim 认领） |
| 生命周期 | 单会话，整表覆盖 | 跨会话/跨 Agent，逐条 CRUD |
| 成本 | 极轻 | 重（拓扑、环检测、并发认领） |

---

## 四、机制原理：为什么是「两层」，而不是「一个够强的结构通吃」

把三份证据合起来，能反推出一条清晰的设计原则：**计划结构的复杂度，应当匹配「谁消费它、它要活多久」，而不是匹配「问题理论上有多复杂」。**

- **单 Agent、单会话、线性推进** → 扁平有序 list 就是最优解。消费者只有模型自己和一个进度条 UI，计划随会话结束即抛弃。这种场景下 DAG 的表达力是**过度设计**：你几乎不会真的需要并行分支（单个模型同一时刻只能干一件事，「exactly ONE in_progress」已经承认了这点），而维护图的成本（id、拓扑、环检测、一致性）每一步都要付。OpenCode「用 follow-up todo 表达阻塞」的设计，本质是**把图压扁成线**——因为单线程执行根本吃不下图的并行能力，留着图纯是负担。

- **多 Agent、跨会话、需要协作** → 这时 DAG 的成本才被它的收益盖过。一旦有多个 worker 同时干活，「谁能开工」就不再是「扫一个 in_progress」能回答的了，必须靠 `blockedBy` 显式声明前置、靠环检测防止死锁、靠 `claim` 防止两个 Agent 抢同一个任务。表达力的需求是**协作并发**逼出来的，不是问题本身复杂度逼出来的。

所以「Plan 要不要做成 DAG」这个问题，正确的问法不是「我的任务有没有依赖关系」（几乎所有任务都有），而是「**会不会有多个执行体并发消费这个计划**」。没有并发，再有依赖关系也压成线性 list 最划算；有了并发，才值得上图。

这也解释了第二节那个岔路口为什么纯推理给不出答案——因为答案不在「问题结构」里，在「执行模型」里。

---

## 五、对手动使用 Agent 的启发

1. **给 Agent 干多步活，先逼它产出结构化 todo，而不是一段计划散文。** 让它显式列出「步骤 + 状态」，并要求「实时更新状态、同时只保持一个进行中」。这等于把 Claude Code/OpenCode 内建的纪律手动加到任何 Agent 上，直接缓解长任务里的状态漂移。

2. **「同时只有一个 in_progress」是个可借用的注意力锚。** 当你发现 Agent 东一榔头西一棒子，让它回到「现在唯一在做的那一步是什么」——这个约束本身就是抗发散的工具。

3. **别急着上 DAG。** 如果是你自己盯着一个 Agent 干线性活，扁平有序 list（编号 todo）几乎总是够用，「遇阻就追加一条新 todo」比维护依赖图省心得多——这正是 OpenCode 的官方选择。只有当你真的开始**编排多个 Agent 并行**时，才需要认真考虑 blockedBy/认领这套重机制。

4. **判断要不要上图，问「有没有并发执行体」，不要问「有没有依赖关系」。** 这是本篇最可迁移的一条：结构复杂度匹配执行模型，不匹配问题复杂度。过早上 DAG 是常见的过度工程。

---

## 关联

- 上一篇《上下文治理分析》：本篇的「状态漂移」与「计划散落在对话历史里越长越不可靠」，正是 context rot 在「计划跟踪」维度的具体落点。计划外化成结构对象，本身也是一种对抗上下文腐烂的手段。
- 待补：Multi-Agent 编排篇——证据 C 的 Task 系统（claim/blockedBy）是多 Agent 协作的计划层，可在写多智能体专题时深挖其调度逻辑。

---

*取证清单：OpenCode `packages/core/src/session/todo.ts` 第10-16行（Schema）+ update/get 函数（position 排序）；`packages/opencode/src/tool/todowrite.txt` 第28行（阻塞处理）+ 单 in_progress 约束。Claude Code 官方二进制 v2.x（darwin-arm64）strings：TodoWrite 字段（content/activeForm/status）；Task 系统工具说明（subject/description/status/blocks/blockedBy + "verify its blockedBy list is empty"）、cyclicPrerequisite 常量、claim/already_claimed 字符串。二进制证据证「字段/文案在产品中真实存在」，不复原完整运行逻辑。最后更新：2026-06-22*
