# 指令文件发现与就近注入(Instruction)

> 源码取证基准:`packages/opencode/src/session/instruction.ts`(241 行,完整读毕),辅以调用方
> `packages/opencode/src/tool/read.ts` 与 `packages/opencode/src/session/prompt.ts`,以及底层
> `packages/core/src/fs-util.ts` 的 `findUp/globUp` 实现。以下所有行号均指 `instruction.ts`,
> 跨文件引用处单独标注文件名。

## 这个父设计解决什么问题

让项目级/全局级的「指令文件」(`AGENTS.md` / `CLAUDE.md` / `CONTEXT.md` 及配置里声明的本地文件、远程 URL)
**持续、按需、不重复、就近** 地进入模型上下文——既要保证规则一直在场(系统提示里全局注入),又要在 agent
读到某个子目录文件时把「那个目录的局部规则」临时贴上去(就近注入),同时严防「同一份指令在一次对话里被反复灌进上下文」
导致的 token 浪费与上下文污染。它与「上下文压缩」是同级的上下文工程父设计:压缩管「怎么把已有上下文变小」,
本机制管「怎么把外部规则精准地放进上下文且不冗余」。

整体分两条注入路径:

1. **系统提示路径**(`system()` → `prompt.ts:1312`):每轮组装系统提示时,把全局 + 项目根 + 配置声明的指令文件全量注入。
2. **就近注入路径**(`resolve()` → `read.ts:300/356`):当 agent 用 `read` 工具读某文件时,沿目录链向上找局部指令文件,
   以 `<system-reminder>` 形式拼进该次 read 的工具输出里。

---

## 子设计 1:`extract()` —— 从历史消息回放「已加载指令」并跳过被压缩的部分

**源码行号:** 17–32(其中第 22 行跳过、第 23–24 行 loaded 元数据)

**关键代码:**
```ts
if (part.type === "tool" && part.tool === "read" && part.state.status === "completed") {
  if (part.state.time.compacted) continue            // 22:被压缩的 read 输出不算数
  const loaded = part.state.metadata?.loaded          // 23:read 工具回填的「本次注入了哪些指令文件」
  if (!loaded || !Array.isArray(loaded)) continue
  for (const p of loaded) if (typeof p === "string") paths.add(p)
}
```

`loaded` 元数据从哪来:`read.ts:300` 调 `instruction.resolve(...)` 拿到本次就近注入的指令列表,
`read.ts:315/365` 把它们的路径写进 `metadata.loaded`,`read.ts:356` 同时把内容塞进 `<system-reminder>`。
`extract()` 就是反向把历史消息里所有 read 工具「曾经注入过的指令路径」收集成一个集合,供 `resolve()`(行 185)做去重。

**防什么坑:**
- **防重复注入同一份指令**:一旦某指令在历史某次 read 里已注入,`resolve()` 第 196 行 `already.has(found)` 就跳过,
  避免一份 `AGENTS.md` 在长对话里被反复贴几十次,白烧 token、稀释注意力。
- **第 22 行 `compacted` 跳过是关键精妙点**:上下文压缩会把旧的 read 工具输出标记为 `compacted`(其 `<system-reminder>`
  内容已被压缩抹掉,不在模型上下文里了)。如果仍把它算作「已加载」,模型上下文里其实已经看不到这份指令,却被当成"还在场"而不再注入
  → **指令静默丢失**。跳过 compacted,让被压缩冲掉的指令在下次 read 时 **重新就近注入**,实现「压缩后自愈」。

---

## 子设计 2:`systemPaths()` —— 三来源优先级 + 「首个匹配胜出 break」

**源码行号:** 110–153;三来源分别在 115–120(全局)、122–133(项目)、135–150(配置);`break` 在 118、130

**关键代码:**
```ts
for (const file of globalFiles) {                      // 115:全局来源
  if (yield* fs.existsSafe(file)) { paths.add(path.resolve(file)); break }  // 118
}
// The first project-level match wins so we don't stack AGENTS.md/CLAUDE.md from every ancestor. (122)
if (!Flag.OPENCODE_DISABLE_PROJECT_CONFIG) {
  for (const file of instructionFiles) {               // 124:["AGENTS.md","CLAUDE.md","CONTEXT.md"]
    const matches = yield* fs.findUp(file, ctx.directory, ctx.worktree)...
    if (matches.length > 0) { matches.forEach(item => paths.add(path.resolve(item))); break }  // 128-130
  }
}
if (config.instructions) {                             // 135:配置来源(本地文件/glob,远程 URL 在此被 continue 跳过留给 system())
  for (const raw of config.instructions) {
    if (raw.startsWith("https://") || raw.startsWith("http://")) continue   // 137
    const instruction = raw.startsWith("~/") ? path.join(global.home, raw.slice(2)) : raw  // 138:~ 展开
    ... // 绝对路径走 glob,相对路径走 relative()(globUp 向上找)
  }
}
```

**优先级与语义(逐条核实):**
- **全局来源(115)**:`~/.config/opencode/AGENTS.md` 与 `~/.claude/CLAUDE.md`。第 118 行 `break` ——
  全局只认 **第一个存在的文件**,AGENTS.md 优先于 Claude 的 CLAUDE.md,二者不叠加。
- **项目来源(124)**:按文件名列表顺序 `AGENTS.md → CLAUDE.md → CONTEXT.md`(第 67 行注释 `CONTEXT.md` 已 deprecated),
  对每个文件名用 `findUp` 从当前目录向上找到 worktree 根。第 130 行 `break` 在 **文件名维度** 命中即停。
- **配置来源(135)**:`config.instructions` 里声明的本地文件,**不 break,全部累加**(用户显式声明的就要全收);
  远程 URL 在这里被跳过(137),交由 `system()`(158–160)走 fetch 分支。

**防什么坑(对 break 的精确解读):**
- 第 130 行 break 防的是 **跨命名约定的叠加**:若仓库同时放了 `AGENTS.md` 和 `CLAUDE.md`(从别的工具迁移过来常见),
  只认排在前面的 `AGENTS.md`,**不会把两套可能矛盾的规则同时灌进系统提示**,避免规则打架 + token 翻倍。
- 注意一个 **必须如实标注的细节**:`findUp`(`fs-util.ts:132-143`)本身会 **累加所有祖先目录** 里同名文件
  (`result.push` 遍历到 stop,见 137 行),所以第 129 行 `matches.forEach` 会把 monorepo 各层的同名 `AGENTS.md` 全部加入。
  因此第 122 行注释说的「不 stack 每个祖先的 AGENTS.md/CLAUDE.md」**严格说是指不 stack 不同命名约定**(AGENTS vs CLAUDE),
  **而非不 stack 同名文件的不同层级**——同名文件的层级叠加是 `findUp` 的预期行为(子目录覆盖父目录的语义靠就近排序实现)。
  这是初步识别里需要修正的一处:break 防的是「命名约定堆叠」,不是「祖先层级堆叠」。

---

## 子设计 3:`resolve()` —— 向上 walk 就近遍历 + 四重跳过 + claims 去重

**源码行号:** 179–221;walk 循环 194–218;四重跳过 196;claims 去重 201–209

**关键代码:**
```ts
const sys = yield* systemPaths()        // 184:系统提示已注入的,就近不再重复
const already = extract(messages)        // 185:历史已就近注入过的(见子设计1)
const root = path.resolve(yield* InstanceState.directory)  // 188
let current = path.dirname(target)       // 191:从被读文件所在目录起步
// Walk upward from the file being read and attach nearby instruction files once per message. (193)
while (current.startsWith(root) && current !== root) {       // 194:只在 root 内、且不含 root 本身
  const found = yield* find(current)     // 195:该目录有无 AGENTS/CLAUDE/CONTEXT.md
  if (!found || found === target || sys.has(found) || already.has(found)) {  // 196:四重跳过
    current = path.dirname(current); continue
  }
  let set = s.claims.get(messageID) ?? (新建并 set)          // 201-205
  if (set.has(found)) { current = path.dirname(current); continue }  // 206:本消息内去重
  set.add(found)                          // 211
  const content = yield* read(found)
  if (content) results.push({ filepath: found, content: `Instructions from: ${found}\n${content}` })  // 213-214
  current = path.dirname(current)
}
```

**就近遍历逻辑:** 从「被 read 的文件」所在目录开始(191),逐级 `path.dirname` 向上(217),
直到触达项目 root。`current !== root`(194)**故意排除 root 本身**——因为 root 级别的 `AGENTS.md` 已由
`systemPaths()` 全量注入到系统提示了,就近路径不该再碰它。

**第 196 行四重跳过,逐个防坑:**
- `!found`:本层没指令文件,跳过。
- `found === target`:agent 读的就是指令文件本身时,不要把它再当指令贴一遍。
- `sys.has(found)`:**防与系统提示重复**——已在系统提示全量注入的,就近路径不再贴。
- `already.has(found)`:**防与历史就近注入重复**(依赖子设计 1 的 compacted 跳过,被压缩的会重新放行)。

**claims Map 去重(201–209):** `claims: Map<MessageID, Set<string>>`(行 74)记录
**「每条 assistant 消息」内,每个指令文件只附一次**。`already`(extract)管的是 **跨历史消息** 的去重(已落盘到 metadata 的),
而 claims 管的是 **同一条消息正在处理过程中、还没落盘** 的去重——一条 assistant 消息可能连续调用多次 `read`(读多个子目录文件),
若它们的祖先目录共享同一份 `AGENTS.md`,claims 保证这份指令在 **本条消息** 里只贴一次,而不是每次 read 都贴。
两层去重叠加,堵住了「同消息内」和「跨消息间」两个不同时间尺度的重复。

---

## 子设计 4:`system()` —— 并发读取 + 远程指令 5s 超时兜底

**源码行号:** 155–169(并发 162–163);`fetch` 超时在 95–103(第 97 行 timeout、98 行 catch)

**关键代码:**
```ts
const files = yield* Effect.forEach(Array.from(paths), read, { concurrency: 8 })   // 162:本地文件并发 8
const remote = yield* Effect.forEach(urls, fetch, { concurrency: 4 })              // 163:远程 URL 并发 4
return [
  ...paths.flatMap((item,i) => files[i] ? [`Instructions from: ${item}\n${files[i]}`] : []),  // 166:空内容过滤
  ...urls.flatMap((item,i) => remote[i] ? [`Instructions from: ${item}\n${remote[i]}`] : []), // 167
]
// fetch:
const res = yield* http.execute(HttpClientRequest.get(url)).pipe(
  Effect.timeout(5000),                  // 97:远程 5s 硬超时
  Effect.catch(() => Effect.succeed(null)),  // 98:任何失败/超时 → null
)
if (!res) return ""                      // 100:降级为空字符串
```

**防什么坑:**
- **并发 8/4(162-163)**:多份指令文件 + 多个远程 URL 顺序读会拉长每轮系统提示组装的延迟;并发化把 IO 等待压平。
  远程并发更保守(4 vs 8),避免对外部服务器突发过多连接。
- **远程 5s 超时 + catch 兜底(97-98)**:**这是整个机制的可用性命门**。系统提示组装在每轮请求的关键路径上
  (`prompt.ts:1309-1315` 的 `Effect.all`),如果某个远程指令 URL 挂掉/慢响应,**会阻塞整个对话轮次**。
  5s 硬超时 + 失败返回 `null` → 空串,保证 **远程指令是「尽力而为」而非「强依赖」**:拿不到就当这条指令不存在,
  对话照常进行,绝不因为一个外部 URL 让 agent 卡死。
- **第 166-167 行空内容过滤**:`files[i] ?`、`remote[i] ?` 把读失败/超时降级出来的空串剔除,
  避免往系统提示里塞 `Instructions from: <url>\n`(只有标题没内容)这种噪声头。

---

## 子设计 5:`clear()` —— 每条消息处理完清理 claims

**源码行号:** 105–108(定义);claims 结构定义在 73–74

**关键代码:**
```ts
const clear = Effect.fn("Instruction.clear")(function* (messageID: MessageID) {
  const s = yield* InstanceState.get(state)
  s.claims.delete(messageID)             // 107:删掉这条消息的去重记录
})
```

**防什么坑:**
- **防内存无界增长**:`claims` 是 `Map<MessageID, Set<string>>`,每条 assistant 消息都会塞一个 entry。
  长会话下消息成百上千,若不清理,这个 Map 会一直涨 → **内存泄漏**。消息处理完即 `delete`,把生命周期收敛到「单条消息」。
- **语义边界正确性**:claims 的去重语义本就是「**单条消息内** 只附一次」(见子设计 3)。一旦这条消息处理完,
  它的去重记录就 **不应再影响下一条消息**——下一条消息是新的注入时机,该重新评估要不要就近注入。
  `clear` 保证 claims 的作用域严格等于「一条消息」,跨消息的去重交给 `extract/already`(已落盘 metadata)那条更持久的链路。
  两者职责不混淆。

---

## 子设计 6:`globalFiles` / `instructionFiles` 受 `disableClaudeCodePrompt` 控制 —— 兼容 Claude Code 生态

**源码行号:** 60–68(`globalFiles` 60–63、`instructionFiles` 64–68);flag 取值在 58

**关键代码:**
```ts
const flags = yield* RuntimeFlags.Service                  // 58
const globalFiles = [
  path.join(global.config, "AGENTS.md"),                   // 61:OpenCode 原生全局指令
  ...(!flags.disableClaudeCodePrompt ? [path.join(global.home, ".claude", "CLAUDE.md")] : []),  // 62
]
const instructionFiles = [
  "AGENTS.md",                                             // 65:原生项目指令
  ...(!flags.disableClaudeCodePrompt ? ["CLAUDE.md"] : []),  // 66:兼容 Claude Code
  "CONTEXT.md",  // deprecated                             // 67
]
```

**防什么坑 / 解决什么问题:**
- **生态迁移零成本**:大量用户从 Anthropic 官方 Claude Code 迁移而来,本地已有 `~/.claude/CLAUDE.md`(全局)和
  仓库里的 `CLAUDE.md`(项目)。默认 `!disableClaudeCodePrompt` 为真 → OpenCode **直接读这两份现成文件**,
  用户无需把规则手动迁移成 `AGENTS.md` 就能开箱即用。
- **可关闭、避免冲突**:某些用户的 `CLAUDE.md` 是给 Claude Code 专用的、与 OpenCode 语义不符,
  或不想让两套工具的指令互相串味。打开 `disableClaudeCodePrompt` flag 后,全局(62)和项目(66)两处的
  CLAUDE.md 同时从候选列表里消失,**只走 OpenCode 原生的 AGENTS.md**,给出干净的逃生出口。
- **优先级隐含在顺序里**:全局里 AGENTS.md 排在 CLAUDE.md 前(配合子设计 2 的 break,AGENTS.md 命中就不读 CLAUDE.md);
  项目里同理。即「原生约定优先,Claude 约定兜底」。

---

## 补充发现(初步清单之外、值得记一笔的子设计)

- **B1 · `relative()` 受 `OPENCODE_DISABLE_PROJECT_CONFIG` 双分支(79–89)**:project-config 被禁时,
  配置型相对指令的搜索根从「项目目录」切换到「全局 config 目录」(87)。防止在禁用项目配置的安全/沙箱场景下,
  仍从用户仓库里捞指令文件——**信任边界收口**。`systemPaths` 第 123 行的项目来源同样被这个 flag 整段跳过。
- **B2 · `~/` 家目录展开(138)**:`config.instructions` 里写 `~/notes.md` 会被展开成绝对路径,
  防止把字面量 `~` 当成当前目录下的怪文件名去 glob。
- **B3 · 配置型指令「绝对路径走 glob、相对路径走 globUp」分流(139–147)**:绝对路径直接在其 dirname 里 glob basename(支持通配),
  相对路径则沿目录链向上找(`relative` → `globUp`)。**一套配置语法兼顾「精确文件」与「就近模式」两种意图**。
- **B4 · `read()` 与 `fetch()` 全程 `Effect.catch` 降级为空(92、98/101)**:本地文件读失败也返回空串而非抛错。
  与子设计 4 的空内容过滤(166-167)配合,贯彻「指令是增强项,任何单点失败都不该让对话崩」的容错哲学。
- **B5 · `find()` 复用 `instructionFiles` 顺序(171–177)**:就近 walk 时每层按 `AGENTS→CLAUDE→CONTEXT` 顺序取 **第一个存在的**(174 `return`),
  与系统提示的命名优先级保持一致,避免同一目录里两份指令都被就近注入。
- **B6 · 注入文本统一前缀 `Instructions from: <path>`(166/167/214)**:三条注入路径都打同样的来源标注头,
  让模型知道「这段规则来自哪个文件」,也便于人审与调试。

---

## 子设计清单(Notion sub-item 用)

| # | 子设计 | 源码行号(instruction.ts) | 一句话防什么坑 |
|---|--------|--------------------------|----------------|
| 1 | `extract()` 历史回放 + `loaded` 元数据 | 17–32(跳过 22,loaded 23–24) | 跨消息去重的数据源,防一份指令反复注入 |
| 1b | compacted 的 read 输出跳过 | 22 | 被压缩冲掉的指令在下次 read 时重新注入,防"压缩后指令静默丢失" |
| 2 | `systemPaths()` 三来源优先级 | 110–153 | 全局/项目/配置分层,来源清晰 |
| 2b | 项目来源「首个命名约定胜出」break | 124–132(break 130) | 防 AGENTS.md 与 CLAUDE.md 两套约定同时灌入打架(注:findUp 仍累加同名文件的各祖先层级) |
| 2c | 全局来源 break | 115–120(break 118) | 全局只认第一个存在的指令文件,不叠加 |
| 3 | `resolve()` 向上 walk 就近遍历 | 179–221(循环 194–218) | 读子目录文件时贴上"该处局部规则" |
| 3b | `current !== root` 排除根 | 194 | 根级指令已进系统提示,就近不重复 |
| 3c | 四重跳过(self/sys/already) | 196 | 防与系统提示、历史就近注入重复 |
| 3d | claims Map 单消息去重 | 73–74、201–211 | 同一条消息多次 read 共享祖先指令时只贴一次 |
| 4 | `system()` 并发读取 8/4 | 162–163 | 多文件/多 URL 并行,压平系统提示组装延迟 |
| 4b | 远程 fetch 5s 超时 + catch 兜底 | 95–103(97/98) | 外部 URL 慢/挂不阻塞对话轮次,降级为空 |
| 4c | 空内容过滤 | 166–167 | 剔除读失败的"只有标题没内容"噪声头 |
| 5 | `clear()` 每消息清 claims | 105–108 | 防 claims Map 无界增长 + 去重作用域收敛到单条消息 |
| 6 | CLAUDE.md 受 `disableClaudeCodePrompt` 控制 | 60–68(62/66) | 兼容 Claude Code 生态零成本迁移,且可一键关闭 |
| B1 | `relative()` / 项目来源受 `OPENCODE_DISABLE_PROJECT_CONFIG` | 79–89、123 | 禁用项目配置时把搜索根切到全局,信任边界收口 |
| B2 | `~/` 家目录展开 | 138 | 防把字面 `~` 当怪文件名 glob |
| B3 | 配置指令 绝对→glob / 相对→globUp 分流 | 139–147 | 一套语法兼顾精确文件与就近模式 |
| B4 | read/fetch 全程 catch 降级空串 | 92、98/101 | 单点 IO 失败不让对话崩 |
| B5 | `find()` 复用命名优先级 | 171–177 | 就近 walk 与系统提示命名优先级一致 |
| B6 | 统一 `Instructions from:` 前缀 | 166/167/214 | 标注来源,利于模型理解与调试 |

> 跨文件锚点:`read.ts:300` 调 `resolve` / `read.ts:315,365` 回填 `metadata.loaded` / `read.ts:356` 拼 `<system-reminder>`;
> `prompt.ts:1312` 在系统提示 `Effect.all` 里调 `instruction.system().pipe(Effect.orDie)`,`prompt.ts:1315` 把
> instructions 拼进 `system` 数组;`fs-util.ts:132-143` 的 `findUp` 累加全部祖先层级、`162-` 的 `globUp` 同理。
