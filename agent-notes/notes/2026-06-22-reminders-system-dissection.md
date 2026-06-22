# OpenCode 源码取证:动态提醒注入(Reminders)与系统提示构成与路由(System)

> 取证基准:`/tmp/oc-src/packages/opencode/src/session/reminders.ts`、`system.ts`、调用点 `prompt.ts`、组装点 `llm/request.ts`。所有行号均经真实读取核对,未凭印象。

---

# 一、动态提醒注入 Reminders(`reminders.ts`)

**解决什么问题**:在多轮(多 step)的 agent 循环里,模型容易"忘记"当前所处的工作模式(plan/build)与约束。Reminders 在每一个 assistant step 开始前,把"临时的、与当前状态强相关的指令"以合成(synthetic)text part 的形式追加到**最后一条 user 消息**上,让约束始终贴在模型注意力的尾部。

## 1.1 子设计:每个 step 都重新 apply,而非一次性注入

**行号**:调用点 `prompt.ts:1233-1237`;函数体 `reminders.ts:15-90`。

```ts
// prompt.ts:1233 —— 位于 step 循环内部,每生成一条 assistant 消息前都调一次
msgs = yield* SessionReminders.apply({ messages: msgs, agent, session }).pipe(...)
```

```ts
// reminders.ts:23 —— 每次都重新定位"最后一条 user 消息"
const userMessage = input.messages.findLast((msg) => msg.info.role === "user")
if (!userMessage) return input.messages
```

**为什么每轮重做**:
- agent 状态会在循环中变化(如从 plan 切到 build),只有每轮重判才能注入"切换提醒"(`build-switch`)。`reminders.ts:37-38` 显式检查历史里"是否曾经是 plan"且"现在是 build"。
- `findLast` 每轮重取当前最尾 user 消息,保证提醒永远挂在"最新上下文"而不是历史某条旧消息上。
- 提醒是 `synthetic: true`(`reminders.ts:34/45/64/86`),属于运行时合成,不持久化为真实用户输入,因此可以安全地反复重算。

**防什么坑**:防"状态漂移"——长循环中模型逐渐淡忘模式约束;一次性注入会让提醒在几轮后被埋进上下文中段、被新内容稀释,且无法响应 plan→build 这类运行中切换。

## 1.2 子设计:按 agent 条件注入 + `experimentalPlanMode` flag 双分支

**行号**:flag 总开关 `reminders.ts:26`;旧路径 `26-49`;新路径 `51-89`。

```ts
// reminders.ts:26 —— 用 runtime flag 把整套逻辑劈成两条实现路径
if (!flags.experimentalPlanMode) {
  if (input.agent.name === "plan") {            // 27: 当前是 plan agent → 注入 plan 提醒
    userMessage.parts.push({ ... text: PROMPT_PLAN, synthetic: true })   // 28-35
  }
  const wasPlan = input.messages.some(            // 37: 历史里出现过 plan assistant
    (msg) => msg.info.role === "assistant" && msg.info.agent === "plan")
  if (wasPlan && input.agent.name === "build") {  // 38: 曾 plan 现 build → 注入切换提醒
    userMessage.parts.push({ ... text: BUILD_SWITCH, synthetic: true })  // 39-46
  }
  return input.messages                           // 48: 旧路径就此返回
}
```

**防什么坑**:
- **flag 隔离实验路径**:`experimentalPlanMode` 把"带 plan 文件落盘"的新行为(1.3)与稳定旧行为彻底隔离,实验功能崩坏不影响默认用户。防"实验代码污染主流程"。
- **条件注入**:只有 `agent.name === "plan"` 才推 plan 提醒,只有"曾 plan→现 build"才推切换提醒。防"无差别注入"——给 build agent 塞 plan 约束会直接矛盾、误导模型。
- `wasPlan` 用 `.some` 扫历史而非看当前,防"切换瞬间漏提醒"——切到 build 的第一轮就必须告诉模型"你刚从 plan 模式出来"。

## 1.3 子设计:plan 模式落盘感知(experimental 新路径)

**行号**:plan→非 plan 的收尾 `reminders.ts:51-68`;进入/保持 plan `70-89`。

```ts
// reminders.ts:51-52 —— 离开 plan:上一条 assistant 是 plan,当前不是
const assistantMessage = input.messages.findLast((msg) => msg.info.role === "assistant")
if (input.agent.name !== "plan" && assistantMessage?.info.agent === "plan") {
  const plan = Session.plan(input.session, ctx)           // 54: 约定的 plan 文件路径
  const exists = yield* fsys.existsSafe(plan)             // 55: 探测文件是否真存在
  ... text: exists
        ? `${BUILD_SWITCH}\n\nA plan file exists at ${plan}. You should execute on the plan...`
        : BUILD_SWITCH                                     // 61-63: 按落盘与否给不同提醒
}
```

```ts
// reminders.ts:70 —— 守卫:既不是 plan、也不是刚从 plan 出来 → 无需提醒
if (input.agent.name !== "plan" || assistantMessage?.info.agent === "plan") return input.messages

// reminders.ts:75 —— 进入/保持 plan:确保目录存在,die 兜底
if (!exists) yield* fsys.ensureDir(path.dirname(plan)).pipe(Effect.catch(Effect.die))

// reminders.ts:81-85 —— 模板占位符按"文件是否已存在"渲染不同动作指令
text: PLAN_MODE.replace("${planInfo}", () =>
  exists
    ? `A plan file already exists at ${plan}. You can read it and make incremental edits using the edit tool.`
    : `No plan file exists yet. You should create your plan at ${plan} using the write tool.`)
```

**防什么坑**:
- 提醒文本随 **文件系统真实状态**(`existsSafe`)变化,告诉模型该用 `write`(新建)还是 `edit`(增量改)。防"模型瞎猜文件状态"导致用错工具、覆盖已有 plan。
- `Effect.catch(Effect.die)`(`75`)在建目录失败时直接 die 而非吞错。防"目录不存在却继续往不存在路径写"的静默失败。
- 离开 plan 时若 plan 文件存在,提醒里直接拼出"去执行该文件里的计划"(`62`)。防"build 阶段忘了 plan 产物存在、从头重想"。

## 1.4 子设计:提醒挂在 user 消息 parts,而非 system

**行号**:四处 push 均指向 `userMessage`:`reminders.ts:28-35 / 39-46 / 66 / 88`。

```ts
userMessage.parts.push({ messageID: userMessage.info.id, type: "text", text: ..., synthetic: true })
```

**为什么挂 user 而非 system**:
- **注意力近因效应**:user 消息是对话最尾部,模型对"最近输入"的服从度高于靠前的 system。把临时、强时效的约束放在尾部,比埋进 system 头部更可能被执行。
- **system 应保持稳定**:system 是按模型族路由的固定 prompt(见第二部分),应可缓存、跨轮不变;把多变的运行时提醒塞进 system 会破坏 prompt 缓存并污染"稳定基线"。
- **`synthetic: true` 标记**:`reminders.ts:34/45/64/86` 让这些 part 可被 UI/持久化区分为"系统合成"而非用户真实输入。防"合成提醒被当成用户原话回显/计费/污染历史"。

**防什么坑**:防"约束被放在模型注意力盲区"(system 头部),同时防"运行时噪声污染可缓存的 system 基线"。

### Reminders 子设计清单

| # | 子设计 | 行号 | 防什么坑 |
|---|--------|------|----------|
| 1.1 | 每 step 重新 apply + findLast 重定位 | prompt.ts:1233-1237;reminders.ts:23 | 状态漂移、提醒被稀释、漏响应运行中切换 |
| 1.2 | flag 双分支 + 按 agent 条件注入 | reminders.ts:26,27,37-38 | 实验污染主流程、无差别注入矛盾约束、切换漏提醒 |
| 1.3 | plan 落盘感知(existsSafe + ensureDir die) | reminders.ts:51-68,70-89 | 模型瞎猜文件状态、用错工具、目录静默失败 |
| 1.4 | 提醒挂 user.parts + synthetic 标记 | reminders.ts:28-35,39-46,66,88 | 约束落进注意力盲区、运行时噪声污染缓存基线、合成被当真用户输入 |

---

# 二、系统提示构成与路由 System(`system.ts`)

**解决什么问题**:不同模型族(BEAST/codex/gpt/gemini/claude/...)对指令的服从度、格式偏好、工具调用风格差异巨大;同一份 prompt 无法通吃。System 机制负责①按模型 id 路由不同底座 prompt,②注入运行时 environment 与 skills,③以固定顺序组装成最终 system。

## 2.1 子设计:`provider()` 按模型 id 字符串路由底座 prompt

**行号**:`system.ts:25-39`;消费点 `llm/request.ts:60`。

```ts
// system.ts:25-39
export function provider(model: Provider.Model) {
  if (model.api.id.includes("gpt-4") || model.api.id.includes("o1") || model.api.id.includes("o3"))
    return [PROMPT_BEAST]                                  // 26-27
  if (model.api.id.includes("gpt")) {                      // 28
    if (model.api.id.includes("codex")) return [PROMPT_CODEX]  // 29-30
    return [PROMPT_GPT]                                    // 32
  }
  if (model.api.id.includes("gemini-")) return [PROMPT_GEMINI]  // 34
  if (model.api.id.includes("claude"))  return [PROMPT_ANTHROPIC] // 35
  if (model.api.id.toLowerCase().includes("trinity")) return [PROMPT_TRINITY] // 36
  if (model.api.id.toLowerCase().includes("kimi"))    return [PROMPT_KIMI]    // 37
  return [PROMPT_DEFAULT]                                  // 38: 兜底
}
```

```ts
// llm/request.ts:60 —— agent 自带 prompt 时优先,否则用模型族路由
...(input.agent.prompt ? [input.agent.prompt] : SystemPrompt.provider(input.model)),
```

**为什么不同族要不同 prompt**:
- gpt-4/o1/o3 走 **BEAST**(更强约束/防偷懒的"野兽模式"提示),因为这些模型倾向"过早收尾、不彻底完成任务"。
- codex 单独分支(`29`),因为 codex 系列的工具/编辑格式与通用 gpt 不同。
- claude 走专门的 anthropic prompt(`35`),与 OpenAI 系格式偏好不同。
- 兜底 `PROMPT_DEFAULT`(`38`)保证未知模型也有可用 prompt。

**精妙点 / 防什么坑**:
- 匹配顺序是有意的:`gpt-4/o1/o3` 必须排在泛 `gpt` 之前(`26` vs `28`),否则 `gpt-4` 会被泛 `gpt` 分支先吞掉,拿不到 BEAST。`codex` 嵌在 `gpt` 内层(`29`)同理。**防"宽匹配吃掉窄匹配"的路由顺序坑**。
- 用 `includes` 子串匹配而非精确等值:防"模型 id 带版本后缀(如 `gpt-4-0613`)就匹配失败"。
- 部分用 `toLowerCase()`(trinity/kimi,`36-37`):防大小写差异漏匹配。
- `agent.prompt` 优先于族路由(request.ts:60):防"自定义 agent 的专属 prompt 被模型族默认 prompt 覆盖"。

## 2.2 子设计:`environment()` 注入运行时信息

**行号**:`system.ts:55-92`。

```ts
// system.ts:61-72
return [
  [
    `You are powered by the model named ${model.api.id}. The exact model ID is ${model.providerID}/${model.api.id}`,
    `Here is some useful information about the environment you are running in:`,
    `<env>`,
    `  Working directory: ${ctx.directory}`,            // 66
    `  Workspace root folder: ${ctx.worktree}`,          // 67
    `  Is directory a git repo: ${ctx.project.vcs === "git" ? "yes" : "no"}`,  // 68
    `  Platform: ${process.platform}`,                   // 69
    `  Today's date: ${new Date().toDateString()}`,      // 70
    `</env>`,
  ].join("\n"),
  ... // 73-90: project references 块(可选)
].filter((part): part is string => part !== undefined)   // 91
```

**注入了什么**:模型自我认知(`model.api.id`/全限定 id,`63`)、工作目录、工作区根、是否 git 仓库、平台、当前日期;以及可选的 **project references**(`73-90`,按 name 排序、过滤掉无 description 的)。

**防什么坑**:
- `<env>` XML 标签包裹(`65/71`):防结构化信息被模型当成自然语句误读,边界清晰。
- 明确告知 `model.api.id`(`63`):防模型对"我是谁"产生幻觉(常见的自报错误模型名)。
- `Today's date`(`70`)运行时取:防模型用训练截止日期做时间判断(过期/算错时差)。
- references 块对无 description 的过滤(`59`)且按 name 排序(`79`):防噪声引用与非确定性排序,排序稳定有利于 prompt 缓存。
- 整体 `.filter(!== undefined)`(`91`):references 为空时返回 `undefined`,被过滤掉,防"空标签块污染 prompt"。

## 2.3 子设计:`skills()` 注入可用技能清单

**行号**:`system.ts:94-106`。

```ts
// system.ts:94-105
skills: Effect.fn("SystemPrompt.skills")(function* (agent: Agent.Info) {
  if (Permission.disabled(["skill"], agent.permission).has("skill")) return  // 95: 权限关了直接不注入
  const list = yield* skill.available(agent)                                  // 97
  return [
    "Skills provide specialized instructions and workflows for specific tasks.",
    "Use the skill tool to load a skill when a task matches its description.",
    // 102-103 注释:在 system 里给"更啰嗦"版本、工具描述里给"更简洁"版本,模型吸收更好
    Skill.fmt(list, { verbose: true }),                                       // 104
  ].join("\n")
})
```

**防什么坑**:
- 权限守卫(`95`):skill 权限被禁则整段不注入并 `return undefined`。防"给无权使用 skill 的 agent 注入 skill 说明",也避免无效 token。
- `verbose: true`(`104`)+ 注释(`102-103`):刻意把详细版放 system、精简版放 tool description。防"两头都简洁导致模型不知道何时该 load skill",也防"两头都啰嗦"重复浪费 token——这是经实测调过的注意力分配。
- 与 environment 分离为独立 Effect:便于 `prompt.ts:1309` 的 `Effect.all` 并行求值。

## 2.4 子设计:三段式组装顺序 `[...env, ...instructions, ...skills]`

**行号**:组装 `prompt.ts:1309-1317`;底座拼接 `llm/request.ts:58-66`。

```ts
// prompt.ts:1309-1315 —— 三段并行求值后按固定顺序拼接
const [skills, env, instructions, modelMsgs] = yield* Effect.all([
  sys.skills(agent), sys.environment(model), instruction.system().pipe(Effect.orDie), ...
])
const system = [...env, ...instructions, ...(skills ? [skills] : [])]   // 1315
if (format.type === "json_schema") system.push(STRUCTURED_OUTPUT_SYSTEM_PROMPT)  // 1317
```

```ts
// llm/request.ts:58-66 —— 最外层再前置"模型族底座 prompt"
const system = [[
  ...(input.agent.prompt ? [input.agent.prompt] : SystemPrompt.provider(input.model)),  // 60 底座在最前
  ...input.system,                                                                       // 61 上面的三段
  ...(input.user.system ? [input.user.system] : []),                                     // 62 用户级覆盖在最后
].filter((x) => x).join("\n")]
```

**为什么这样排**(从外到内的完整顺序:**底座 → env → instructions → skills →(结构化输出)→ 用户 system**):
- **底座 prompt 最前**(request.ts:60):模型族通用人格/规则是一切基础,放最前奠定基调。
- **environment 次之**(1315 的 `...env`):先让模型知道"我是谁、在哪、什么时间",后续 instructions 才有上下文锚点。
- **instructions 居中**:项目级/用户自定义规则(AGENTS.md 等),建立在 env 之上、约束在 skills 之前。
- **skills 靠后**(1315):skills 是"按需 load 的工具说明",属于参考资料性质,放后面避免占据开头注意力;且仅当存在时 `(skills ? [skills] : [])` 才加入。
- **结构化输出 prompt 最后 push**(1317):只有 json_schema 模式才追加,放末尾贴近"输出格式要求该被最后看到"的近因。
- **用户级 system 兜底在最尾**(request.ts:62):用户显式 system 优先级最高,放最后做覆盖。

**防什么坑**:
- 固定顺序 + `Effect.all` 并行:防"三段求值顺序耦合导致不确定性",顺序由数组拼接而非求值时机决定。
- `(skills ? [skills] : [])` 与 `filter(x => x)`(request.ts:64):防 undefined/空串混入产生空行污染。
- request.ts:74-78 把 plugin transform 后多出的块重新压成"header + 其余"两段:防"插件注入打散了底座 header 的缓存键",保住第一块稳定以利缓存。

### System 子设计清单

| # | 子设计 | 行号 | 防什么坑 |
|---|--------|------|----------|
| 2.1 | provider() 模型 id 子串路由 + 顺序敏感 | system.ts:25-39;request.ts:60 | 宽匹配吃窄匹配、版本后缀漏匹配、大小写漏匹配、agent 自定义被覆盖 |
| 2.2 | environment() 运行时信息 + `<env>` 标签 | system.ts:55-92 | 自我认知幻觉、日期用训练截止、信息被当自然语句、空引用块污染 |
| 2.3 | skills() 权限守卫 + verbose 注入 | system.ts:94-106 | 无权 agent 被注入、注意力分配失衡、无效 token |
| 2.4 | 底座→env→instructions→skills 固定顺序组装 | prompt.ts:1309-1317;request.ts:58-78 | 求值顺序不确定、空串污染、插件破坏缓存 header |

---

## 取证备注

- 全部行号基于真实读取的源码核对(reminders.ts 共 92 行、system.ts 共 117 行);未读到的部分(prompt/*.txt 实际文案)仅作机制推断,未当作确证文案引用。
- 关键交叉点:`SessionReminders.apply` 在 step 循环内(prompt.ts:1233);`SystemPrompt.provider` 实际消费在 llm/request.ts:60,与 prompt.ts:1315 的 env/instructions/skills 三段在 request.ts 中再被前置底座 prompt 包裹。
