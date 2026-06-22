# OpenCode 源码解剖:Summary 异步标题/摘要 与 ContextEpoch/RunState 并发锁

> ⚠ **本文档涉及的是上下文工程的「边界机制」(偏会话编排,而非直接决定喂模型什么内容)**
>
> 「压缩 / 指令注入」这类机制直接决定送进模型的 token;而本文剖析的两个机制处于上下文工程的**边界**:
> - **Summary**(异步标题/摘要):产出会话元数据(标题、diff 摘要),**不阻塞主推理循环**,失败也不影响主任务 —— 它是「旁路产物」。
> - **ContextEpoch / RunState**:负责会话级**并发安全**(乐观锁 + 串行化),保证「同一会话同一时刻只有一条受控的修改路径」—— 它是「编排守门人」。
>
> 二者都偏 **会话编排(session orchestration)**,故标注为边界机制。

源码取证基于真实行号,clone 路径:
- `packages/opencode/src/session/summary.ts`
- `packages/opencode/src/session/run-state.ts`
- `packages/core/src/session/context-epoch.ts`
- `packages/opencode/src/session/prompt.ts`(title/summary 异步 fork 与 loop 入口)

---

# 一、Summary —— 异步标题/摘要生成

**一句话:** 在不阻塞主推理循环、且生成失败不污染主任务的前提下,旁路产出「会话标题」与「每个用户消息的 diff 摘要」这类会话元数据。

涉及两个协作点:
- `title()`:`prompt.ts:177-237` 定义,`prompt.ts:1186-1192` 触发(标题生成)。
- `summarize()`:`summary.ts:102-127` 定义,`prompt.ts:1304-1305` 触发(diff 摘要)。

## 1.1 子设计:`Effect.forkIn(scope)` 异步跑 + `Effect.ignore` 吞错

**行号:** `prompt.ts:1186-1192`(title)、`prompt.ts:1304-1305`(summary)

**精简代码:**
```ts
// title —— prompt.ts:1186-1192
if (step === 1)
  yield* title({
    session, modelID: lastUser.model.modelID,
    providerID: lastUser.model.providerID, history: msgs,
  }).pipe(Effect.ignore, Effect.forkIn(scope))

// summary —— prompt.ts:1304-1305
if (step === 1)
  yield* summary.summarize({ sessionID, messageID: lastUser.id })
    .pipe(Effect.ignore, Effect.forkIn(scope))
```

**精妙点拆解:**
- `Effect.forkIn(scope)`:把任务 fork 到**会话级 scope** 而非当前 fiber。主循环 `yield*` 立刻拿到 fork 后的句柄并继续往下跑模型调用,标题/摘要在后台并行生成。绑定到 `scope` 而非全局 —— 会话结束/取消时,这些后台任务随 scope 一起被清理,不会泄漏成孤儿 fiber。
- `Effect.ignore`:吞掉**整个** error channel。标题生成是「锦上添花」,失败了用户照样能继续对话。

**防什么坑:**
1. **防主循环被旁路任务阻塞** —— 标题生成要再发一次 LLM 请求(`prompt.ts:209` `llm.stream`),如果同步等它,用户的真实回复会被白白拖慢一个 LLM round-trip。
2. **防旁路失败炸穿主任务** —— 若不 `ignore`,标题模型超时/限流会让整个会话 prompt 失败。注意 `title()` 内部 `setTitle` 还额外包了一层 `Effect.catchCause`(`prompt.ts:236`)兜底记日志,是「双重保险」。
3. **防 fiber 泄漏** —— `forkIn(scope)` 绑定生命周期,会话取消时后台任务被一并 interrupt。

## 1.2 子设计:只在 `step === 1` 触发一次

**行号:** `prompt.ts:1186`(title)、`prompt.ts:1304`(summary)

**精简代码:**
```ts
step++                 // prompt.ts:1185
if (step === 1) ...title(...)        // 1186
...
if (step === 1) ...summary.summarize(...)  // 1304
```

**防什么坑:**
- **防重复生成 / 重复 LLM 花费** —— 一次会话的主循环会跑很多 step(多轮工具调用),标题只需在「第一轮」生成一次。用 `step === 1` 作为单次触发门闩,避免每个 step 都重复发标题请求、重复算 diff。
- **幂等兜底** —— 即使触发,`title()` 内部还有二道闸:`prompt.ts:184` `if (!Session.isDefaultTitle(...)) return`(标题已非默认值则跳过),`prompt.ts:190` 要求「真实用户消息恰好只有 1 条」才生成。`step === 1` 是性能闸,内部条件是正确性闸。

## 1.3 子设计:标题输入用裁剪后的 history + 优先小模型

**行号:** `prompt.ts:186-208`(输入构造)、`prompt.ts:200-205`(模型选择)、`prompt.ts:214` `small: true`

**精简代码:**
```ts
// 只取「首条真实用户消息」之前的上下文 —— prompt.ts:186-192
const real = (m) => m.info.role === "user" &&
  !m.parts.every((p) => "synthetic" in p && p.synthetic)
const idx = input.history.findIndex(real)
if (idx === -1) return
if (input.history.filter(real).length !== 1) return   // 必须恰好一条
const context = input.history.slice(0, idx + 1)

// 模型选择:专用 title agent 模型 > 当前 provider 小模型 > 当前模型 —— prompt.ts:200-205
const ag = yield* agents.get("title")
const mdl = ag.model
  ? yield* provider.getModel(ag.model.providerID, ag.model.modelID)
  : ((yield* provider.getSmallModel(input.providerID)) ??
     (yield* provider.getModel(input.providerID, input.modelID)))

// 拼一句显式指令前缀,small:true —— prompt.ts:209-219
messages: [{ role: "user", content: "Generate a title for this conversation:\n" }, ...msgs]
```

**精妙点拆解:**
- 输入只截到**第一条真实用户消息**(`slice(0, idx+1)`),过滤掉 `synthetic` 合成消息(系统注入/提醒类),让标题反映用户真实意图,而非系统噪声。
- 模型走三级回退:专用 `title` agent 模型 → provider 的 `getSmallModel`(便宜的小模型)→ 回退当前主模型。`small: true`(`prompt.ts:214`)显式声明这是低成本任务。
- 输出后处理:`prompt.ts:227-233` 剥 `<think>...</think>` 推理标签、取首个非空行、截断到 100 字符(超长则 `97 + "..."`)。

**防什么坑:**
- **防标题被工具调用/多轮噪声污染** —— 只用首轮用户输入。
- **防小题大做烧钱** —— 标题不该用旗舰模型,优先小模型。
- **防 reasoning 模型把 `<think>` 思维链当标题写进去** —— 显式正则剥离(`prompt.ts:228`)。
- **防标题过长撑爆 UI** —— 100 字符截断。

## 1.4 子设计:`summarize()` 的幂等清零 + 角色守卫 + diff 计算

**行号:** `summary.ts:102-127`,辅助 `computeDiff` 在 `summary.ts:82-100`

**精简代码:**
```ts
// 先把摘要清零并广播空 diff —— summary.ts:106-114
yield* sessions.setSummary({ sessionID, summary: { additions:0, deletions:0, files:0 } })
yield* events.publish(Session.Event.Diff, { sessionID, diff: [] })
if ((yield* config.get()).snapshot === false) return        // summary.ts:115 配置开关

const all = yield* sessions.messages({ sessionID }).pipe(Effect.orDie)
if (!all.length) return
// 只挑「该用户消息 + 它的 assistant 子消息」 —— summary.ts:119-121
const messages = all.filter((m) =>
  m.info.id === messageID ||
  (m.info.role === "assistant" && m.info.parentID === messageID))
const target = messages.find((m) => m.info.id === messageID)
if (!target || target.info.role !== "user") return          // summary.ts:123 角色守卫
const msgDiffs = yield* computeDiff({ messages })            // 124
target.info.summary = { ...target.info.summary, diffs: msgDiffs }
```
```ts
// computeDiff:从 step-start.snapshot 取 from,step-finish.snapshot 取 to —— summary.ts:82-100
if (from && to) return yield* snapshot.diffFull(from, to)
return []
```

**防什么坑:**
- **防陈旧摘要残留** —— 先 `setSummary(全零)` 再算,保证旧 diff 立刻被清掉,UI 不会显示上一轮的过期数字。
- **防对非用户消息算 diff** —— `summary.ts:123` 角色守卫:只对 `role === "user"` 的目标消息挂 diff。
- **防快照功能关闭时空跑** —— `summary.ts:115` `snapshot === false` 直接 return。
- **防跨消息串扰** —— 通过 `parentID === messageID` 精确圈定本轮 assistant 子消息,只对这一组 message 算 from/to 快照差。

---

# 二、ContextEpoch / RunState —— 上下文纪元与并发锁

**一句话:** 用「数据库乐观锁(revision)+ 多维身份校验(location/agent)+ 会话级串行化(Runner)」三层,保证同一会话的上下文不会被并发请求互相覆盖,且 agent 不会被悄悄替换。

`context-epoch.ts` 是**乐观锁**层(谁能写 DB 里的上下文纪元);`run-state.ts` 是**串行化**层(同一会话同一时刻只跑一条 work)。

## 2.1 子设计:`RevisionMismatch` 乐观锁 + 自旋重试

**行号:** 异常类 `context-epoch.ts:19`;重试器 `context-epoch.ts:27-34`;触发点 `insert` `:232`、`replace` `:273`、`advance` `:342`、`fence` `:295`

**精简代码:**
```ts
class RevisionMismatch extends Error {}     // context-epoch.ts:19

// 自旋重试器 —— context-epoch.ts:27-34
const retryRevisionMismatch = (attempt) =>
  attempt().pipe(
    Effect.catchDefect((defect) =>
      defect instanceof RevisionMismatch
        ? Effect.yieldNow.pipe(Effect.andThen(retryRevisionMismatch(attempt)))  // 让出再重试
        : Effect.die(defect)))

// 写时用 WHERE revision = expected 做 CAS —— advance, context-epoch.ts:329-342
const updated = yield* db.update(SessionContextEpochTable)
  .set({ snapshot, revision: expectedRevision + 1 })
  .where(and(
    eq(session_id, sessionID),
    eq(revision, expectedRevision),          // 乐观锁条件
    isNull(replacement_seq)))
  .returning({ revision }).get()
if (!updated) return yield* Effect.die(new RevisionMismatch())   // CAS 失败 → 抛锁冲突
```

**精妙点拆解:**
- 经典 **CAS(compare-and-swap)**:每次写都带 `WHERE revision = expectedRevision`,并 `SET revision = +1`。若期间别人改过,`revision` 变了,`UPDATE` 影响 0 行,`.get()` 返回 undefined → 抛 `RevisionMismatch`。
- `RevisionMismatch` 被当成 **defect**(`Effect.catchDefect`)而非普通 error 抛 —— 它不该泄漏到调用方,而是被 `retryRevisionMismatch` 内部消化。
- 重试前插一个 `Effect.yieldNow`(`:31`):**让出调度**,给竞争者机会推进,避免忙等自旋把 fiber 卡死,也避免活锁。
- `initialize`(`:49`)、`prepare`(`:62`)两个公开入口都用 `retryRevisionMismatch` 包裹,所以乐观锁冲突对外是透明的「自动重读重试」。

**防什么坑:**
- **防并发覆盖(lost update)** —— 两个请求同时基于 revision=N 改上下文,只有一个能 commit,另一个 CAS 失败后**重读最新状态再算**,而不是盲目覆盖。
- **防活锁/CPU 空转** —— `yieldNow` 协作式让出。
- **防 replacement 期间被普通 advance 抢写** —— `advance` 的 WHERE 额外要求 `isNull(replacement_seq)`(`:336`),正在等待 agent 替换的纪元不允许被普通推进。

## 2.2 子设计:`LocationMismatch` —— 会话目录/工作区身份校验

**行号:** 异常类 `context-epoch.ts:20`;触发点 `insert` 事务内 `context-epoch.ts:200-214`

**精简代码:**
```ts
class LocationMismatch extends Error {}      // context-epoch.ts:20

// insert 时校验:会话必须落在期望的 directory + workspace —— :200-214
const placed = yield* db.select({ agent: SessionTable.agent })
  .from(SessionTable)
  .where(and(
    eq(SessionTable.id, sessionID),
    eq(SessionTable.directory, location.directory),
    location.workspaceID === undefined
      ? isNull(SessionTable.workspace_id)
      : eq(SessionTable.workspace_id, location.workspaceID)))
  .get()
if (!placed) return yield* Effect.die(new LocationMismatch())   // 位置不匹配
```

**防什么坑:**
- **防「同一 sessionID 在不同工作目录/工作区被初始化」** —— 上下文纪元(system context baseline)是和具体 `directory + workspace_id` 绑定的。如果某请求带着错误的 location 来初始化,baseline(包含项目文件结构、环境)就会错位。`WHERE` 没命中 → `LocationMismatch`,拒绝建立纪元。
- 把 location 校验放在 `insert` 的 `transaction({ behavior: "immediate" })`(`:236`)内,和插入原子化,杜绝「校验通过后位置又被改」的 TOCTOU 窗口。

## 2.3 子设计:`AgentMismatch` —— agent 选择一致性校验

**行号:** 异常类 `context-epoch.ts:21`;触发点 `insert` `:215`、`requireAgentSelection` `:145-157`、`fence` `:293-294`、`current` `:315-320`

**精简代码:**
```ts
export class AgentMismatch extends Error {}    // context-epoch.ts:21

// insert 内:DB 里已选定的 agent 必须等于本次 agent —— :215
if (placed.agent !== null && placed.agent !== agent)
  return yield* Effect.die(new AgentMismatch())

// requireAgentSelection:replace 前再校一遍 —— :145-157
if (!selected || (selected.agent !== null && selected.agent !== agent))
  return yield* Effect.die(new AgentMismatch())

// fence:写栅栏时校验「当前选定 agent + revision」都对得上 —— :293-295
if (!current || (current.selected !== null && current.selected !== agent))
  return yield* Effect.die(new AgentMismatch())
if (current.revision !== expectedRevision) return yield* Effect.die(new RevisionMismatch())
```

**精妙点拆解:** 校验式统一是 `selected !== null && selected !== agent` —— `null` 表示「尚未锁定 agent」(允许任意),一旦非 null 就必须严格匹配。多处(insert/replace/fence/current)重复同一守卫,形成纵深防御。

**防什么坑:**
- **防 agent 串话** —— 会话一旦绑定某 agent,后续基于该会话纪元的写操作必须来自同一 agent,防止 B agent 拿着 A agent 的会话纪元乱写。
- **`fence` 同时校验 agent + revision** —— 这是 agent 替换被阻挡(`AgentReplacementBlocked`)后,给 DB「下栅栏」时的双重一致性确认,确保栅栏落在正确的纪元版本上。

## 2.4 子设计:`AgentReplacementBlocked` —— agent 替换的有序阻挡

**行号:** 异常类 `context-epoch.ts:22-25`(TaggedError);触发逻辑 `prepareOnce` `:85-93`

**精简代码:**
```ts
export class AgentReplacementBlocked extends Schema.TaggedErrorClass<...>()(
  "SessionContextEpoch.AgentReplacementBlocked",
  { sessionID, previous: AgentV2.ID, current: AgentV2.ID }) {}   // :22-25

// prepareOnce —— :85-93
const replacingAgent = stored.agent !== agent
const result = (stored.replacement_seq === null && !replacingAgent)
  ? yield* SystemContext.reconcile(value, snapshot)   // 同 agent:温和对账
  : yield* SystemContext.replace(value, snapshot)     // 换 agent:走替换协议
if (result._tag === "ReplacementBlocked" && replacingAgent) {
  yield* fence(db, sessionID, agent, stored.revision)   // 下栅栏
  return yield* new AgentReplacementBlocked({ sessionID, previous: stored.agent, current: agent })
}
```

**精妙点拆解:**
- 区分两条路径:**同 agent** 走 `reconcile`(对账,温和合并上下文变化);**换 agent** 走 `replace`(替换协议)。
- 当替换被底层判定为 `ReplacementBlocked`(例如还有未处理的输入序列,不能此刻切换),不是直接报错丢弃,而是先 `fence`(`:91`)给 DB 落一个栅栏标记,再抛 **TaggedError**(可被上层结构化 `catchTag` 捕获)。
- `AgentReplacementBlocked` 是 `Schema.TaggedErrorClass`,带 `previous`/`current` 两个 agent ID —— 是**面向调用方的、可恢复的领域错误**,区别于 `RevisionMismatch` 那种内部 defect。

**防什么坑:**
- **防 agent 在「有飞行中输入」时被硬切换** —— 切换 agent 会重建 system context baseline,若此刻还有未消费的输入序列,会造成上下文断裂。`replacement_seq` 机制让替换「排队等到安全点」(见 `requestReplacement` `:159-176`:只有 `baseline_seq < seq` 才接受替换请求),而不是立即生效。
- **区分「内部锁冲突」与「业务阻挡」** —— `RevisionMismatch` 静默重试,`AgentReplacementBlocked` 是显式 TaggedError 交给上层决策,语义清晰。

## 2.5 子设计:RunState 的 `ensureRunning` —— 会话级串行化(共享 Runner)

**行号:** `ensureRunning` `run-state.ts:88-94`;`runner` 工厂 `run-state.ts:52-69`;loop 入口 `prompt.ts:1389-1393`

**精简代码:**
```ts
// 每个 sessionID 复用同一个 Runner —— run-state.ts:52-69
const runner = Effect.fn(...)(function* (sessionID, onInterrupt) {
  const data = yield* InstanceState.get(state)
  const existing = data.runners.get(sessionID)
  if (existing) return existing                  // 已有则复用 —— :57-58
  const next = Runner.make(data.scope, {
    onIdle: Effect.gen(function* () {            // 空闲时自清理 —— :60-63
      data.runners.delete(sessionID)
      yield* status.set(sessionID, { type: "idle" })
    }),
    onBusy: status.set(sessionID, { type: "busy" }),
    onInterrupt,
  })
  data.runners.set(sessionID, next)
  return next
})

// ensureRunning:把 work 交给该会话的 Runner —— run-state.ts:88-94
return yield* (yield* runner(sessionID, onInterrupt)).ensureRunning(work)

// loop 入口 —— prompt.ts:1389-1393
const loop = Effect.fn("SessionPrompt.loop")(function* (input) {
  return yield* state.ensureRunning(
    input.sessionID,
    lastAssistant(input.sessionID),   // onInterrupt:被打断时返回最后一条 assistant
    runLoop(input.sessionID))         // work:真正的主循环
})
```

**精妙点拆解:**
- `runners: Map<SessionID, Runner>`(`run-state.ts:38`):每个会话一个 Runner,以 sessionID 为键。同一会话的并发 `loop` 调用会拿到**同一个** Runner 实例,`ensureRunning` 让它们汇流到同一条执行流(后来者「搭车」等待,而非另起一条)。
- `onIdle` 自清理(`:60-63`):Runner 空闲时把自己从 Map 删除并置 idle 状态 —— 防 Map 无限膨胀、内存泄漏。
- Runner 建在会话 `scope`(`:59`)上,且 layer 注册了 finalizer(`run-state.ts:39-47`):服务关闭时 `forEach(runners, cancel)` 全部取消并 `clear()` —— 优雅停机。

**防什么坑:**
- **防同一会话被并发跑出两条主循环** —— 这是核心。`ensureRunning` 保证同一 sessionID 同一时刻只有一条 work 在跑。
- **防 Runner 泄漏** —— idle 自删 + scope finalizer 双清理。

## 2.6 子设计:`startShell` / `assertNotBusy` —— BusyError 拒绝与串行入口

**行号:** `assertNotBusy` `run-state.ts:71-75`;`startShell` `run-state.ts:96-105`;`BusyError` 工厂 `:150-152`;shell 入口 `prompt.ts:1395-1400`

**精简代码:**
```ts
// busy 时直接拒绝 —— run-state.ts:71-75
const assertNotBusy = Effect.fn(...)(function* (sessionID) {
  const existing = data.runners.get(sessionID)
  if (existing?.busy) yield* busyError(sessionID)
})

// startShell:Runner 忙则转成 BusyError —— run-state.ts:96-105
const startShell = Effect.fn(...)(function* (sessionID, onInterrupt, work, ready?) {
  return yield* (yield* runner(sessionID, onInterrupt))
    .startShell(work, ready)
    .pipe(Effect.catchTag("RunnerBusy", () => Effect.fail(busyError(sessionID))))   // :104
})

function busyError(sessionID) { return new Session.BusyError({ sessionID }) }  // :150-152

// shell 入口配合 Latch 做「就绪同步」—— prompt.ts:1395-1400
const ready = yield* Latch.make()
return yield* state.startShell(input.sessionID, lastAssistant(input.sessionID), shellImpl(input, ready), ready)
```

**精妙点拆解:**
- 两种入口对「会话忙」的态度不同:
  - `ensureRunning`(主 loop):**汇流/搭车** —— 已在跑就复用同一条流。
  - `startShell`(shell 命令):**拒绝** —— 把底层 `RunnerBusy` 转成对外的 `BusyError`(`:104`),让调用方知道「会话正忙,稍后再试」。
- `startShell` 带可选 `Latch`(`ready`,`:100`/`prompt.ts:1398`):shell 进程「准备就绪」时开闸,调用方可同步等待 shell 真正启动,而非盲等。

**为什么 agent 会话必须串行、不能并发(核心结论):**
1. **共享可变上下文纪元** —— 同一会话共享一份 system context baseline + revision(`context-epoch.ts`)。两条主循环并发跑会同时改 baseline / 追加消息,即便有乐观锁兜底,也会退化成大量 `RevisionMismatch` 自旋重试,浪费且行为不可预测。
2. **消息序列必须线性** —— 主循环不断 `updateMessage` 追加 assistant 消息(`prompt.ts:1254`),并按 `parentID` 串成对话树;并发会让消息交错、parent 关系错乱。
3. **工具副作用有顺序依赖** —— agent 会执行写文件、跑命令等有状态副作用,两条循环并发会互相破坏工作区(这也是 `cancelBackgroundJobs` `run-state.ts:116-148` 要级联取消子会话/后台任务的原因)。
4. **token/成本与上下文窗口语义** —— 上下文窗口是单线程递进的资源,并发推进会让「该不该压缩(compaction)」的判断失真。

因此:**RunState 用 per-session Runner 把同一会话强制串行(主循环搭车、shell 忙则拒绝),ContextEpoch 用乐观锁在 DB 层兜住偶发并发(跨进程/跨实例)** —— 两层一起构成会话编排的并发安全边界。

---

# 三、子设计清单表

| # | 父机制 | 子设计 | 源码行号 | 防什么坑 |
|---|--------|--------|----------|----------|
| 1.1 | Summary | `forkIn(scope)` + `Effect.ignore` 异步吞错 | prompt.ts:1186-1192 / 1304-1305 | 旁路任务阻塞主循环、失败炸穿主任务、fiber 泄漏 |
| 1.2 | Summary | `step === 1` 单次触发门闩 | prompt.ts:1186 / 1304 | 每 step 重复发标题请求、重复花费 |
| 1.3 | Summary | 裁剪 history + 三级小模型回退 + 输出清洗 | prompt.ts:186-208 / 200-205 / 227-233 | 工具噪声污染标题、旗舰模型烧钱、`<think>` 混入、标题超长 |
| 1.4 | Summary | `summarize` 先清零 + 角色守卫 + 精确圈 diff | summary.ts:106-127 / 82-100 | 陈旧摘要残留、对非用户消息算 diff、跨消息串扰 |
| 2.1 | ContextEpoch | `RevisionMismatch` 乐观锁 CAS + `yieldNow` 自旋重试 | context-epoch.ts:19,27-34,232,273,342 | 并发覆盖(lost update)、活锁/CPU 空转、替换期被抢写 |
| 2.2 | ContextEpoch | `LocationMismatch` 目录/工作区校验(事务内) | context-epoch.ts:20,200-214 | 同 sessionID 跨目录初始化、baseline 错位、TOCTOU |
| 2.3 | ContextEpoch | `AgentMismatch` agent 一致性纵深校验 | context-epoch.ts:21,145-157,215,293-295 | agent 串话、用错纪元乱写 |
| 2.4 | ContextEpoch | `AgentReplacementBlocked` 有序阻挡 + fence + TaggedError | context-epoch.ts:22-25,85-93 | 有飞行输入时硬切 agent、上下文断裂、内部锁冲突与业务阻挡混淆 |
| 2.5 | RunState | `ensureRunning` per-session Runner 串行化(搭车) + idle 自清理 | run-state.ts:52-69,88-94 / prompt.ts:1389-1393 | 同会话并发跑双主循环、Runner 内存泄漏 |
| 2.6 | RunState | `startShell` / `assertNotBusy` BusyError 拒绝 + Latch 就绪同步 | run-state.ts:71-75,96-105,150-152 / prompt.ts:1395-1400 | 会话忙时仍接 shell、盲等 shell 启动 |

---

# 四、边界机制定位小结

- **Summary** 是**产出侧边界**:它消费上下文产出元数据,但产物(标题、diff 摘要)流向 UI/会话列表,**不回流进喂给模型的 prompt**。因此它可以异步、可以失败、可以被忽略 —— 这正是「边界」的特征。
- **ContextEpoch / RunState** 是**控制侧边界**:它们不决定 prompt 内容,而是决定**「谁、在什么时刻、能否」修改会话上下文**。乐观锁守 DB 写入,Runner 串行化守执行流,二者共同保证「上下文工程」这条流水线在并发环境下不被并发请求撕裂。

两者都不属于「直接决定喂模型什么 token」的核心上下文工程(那是 compaction / 指令注入 / system context 的职责),而是围绕核心的**编排与并发安全外壳**,故定性为**边界机制**。
