# 父设计二 · OpenCode：配置驱动的 arity 前缀规则引擎

> 源码取证基准：commit `cd292a4`。
> - 规则引擎：`packages/opencode/src/permission/index.ts`（230 行，`evaluate` 在 39-49，`ask` 在 78+）。
> - 命令 arity 字典：`packages/opencode/src/permission/arity.ts`（163 行，含生成 prompt 原文）。
> - schema：`packages/core/src/v1/config/permission.ts`（50 行）。

## 这个父设计解决什么问题

OpenCode 和 Hermes 一样跑在用户主机、没有 OS 沙箱（已核查：全仓无 seatbelt/bwrap）。但它对"识别危险"这件事做了**相反的选择**：它根本不维护"危险命令黑名单"，而是认为——**危险是主观的、因人因项目而异的，应该由用户用配置声明，而不是由工具硬编码猜测**。

于是问题从"如何认出危险命令"变成了两个更工程化的子问题：

1. 用户怎么用**有限的规则**覆盖**无限的命令变体**？（不能要求用户为 `git checkout main`、`git checkout dev`、`git checkout feat/x` 各写一条规则）
2. 多条规则冲突时，谁说了算？

OpenCode 的答法是**命令 arity 前缀归约 + 通配符 last-match-wins 规则引擎 + 逐工具三态裁决**。这是一套"把人类的授权意图，精确映射到机器的命令匹配"的设计。

## 数据结构设计

### 结构一：逐工具的权限 schema（per-tool ask/allow/deny）

权限不是一张全局表，而是**挂在每个工具上的一个规则**：

```typescript
// packages/core/src/v1/config/permission.ts
const Action = Schema.Literals(["ask", "allow", "deny"])      // 三态裁决
const Object = Schema.Record(Schema.String, Action)           // { "命令模式": 动作 }
const Rule  = Schema.Union([Action, Object])                  // 要么整体一个动作，要么按模式细分

const InputObject = {
  read, edit, glob, grep, list, bash, task,
  external_directory, todowrite, question,
  webfetch, websearch, lsp, doom_loop, skill, ...
}   // 每个工具一个 Rule
```

**为什么逐工具**：不同工具的危险维度根本不同。`read` 的危险是"读到敏感文件"，`bash` 的危险是"跑破坏性命令"，`webfetch` 的危险是"把数据外传"。把它们拆成独立的权限键，用户能精细控制——比如"`edit` 一律 allow（信任 agent 改代码）但 `bash` 一律 ask（命令必须过眼）"。

每个工具的值可以是：
- 单个 `Action`（`bash: "ask"` —— 所有 bash 命令都问）；
- 或一个 `{模式: 动作}` 字典（`bash: { "git *": "allow", "rm *": "deny", "*": "ask" }`）。

### 结构二：命令 arity 字典（把命令归约成"人类能懂的最短前缀"）

这是 OpenCode 最有辨识度的数据结构。它解决"无限命令变体 → 有限规则"的核心难题：

```typescript
// packages/opencode/src/permission/arity.ts
const ARITY: Record<string, number> = {
  git: 2,              // git checkout main → 取前 2 个 token "git checkout"
  "git config": 3,     // git config user.name → 前 3 个
  npm: 2,              // npm install
  "npm run": 3,        // npm run dev
  docker: 2,
  "docker compose": 3,
  rm: 1, ls: 1, cat: 1, // 单 token 命令
  // …约 130 条，覆盖主流工具链
}

export function prefix(tokens: string[]) {
  for (let len = tokens.length; len > 0; len--) {
    const arity = ARITY[tokens.slice(0, len).join(" ")]
    if (arity !== undefined) return tokens.slice(0, arity)  // 最长前缀匹配胜出
  }
  return tokens.slice(0, 1)   // 字典没有 → 默认取第一个 token
}
```

**设计精髓——"arity = 几个 token 定义了这条命令的语义"**：
- `git checkout main` 的语义由 `git checkout`（2 个 token）决定，`main` 只是参数。所以 `git` 的 arity 是 2 → 归约成 `git checkout`。
- 规则 `bash: { "git checkout": "allow" }` 一条，就覆盖了 `git checkout` 后面跟任何分支名。
- **flag 永不计入 token**（生成 prompt 原文：`Flags NEVER count as tokens`），`git -v checkout main` 仍归约成 `git checkout`。

这个字典是用 LLM 生成的（arity.ts 里保留了完整生成 prompt），规则是"最长匹配前缀胜出""只在更长前缀的 arity 不同时才单列"。它把"用户想授权的那个**人类概念上的命令**"从一长串带参数带 flag 的 shell 串里精确抠出来。

### 结构三：有序规则集 + pending 队列

```typescript
interface State {
  pending: Map<ID, PendingEntry>   // 等待用户答复的请求(Deferred 异步阻塞)
  approved: Rule[]                 // 运行时累积的"本次已批"规则
}
type Ruleset = Rule[]              // 规则是有序数组，顺序决定优先级
```

规则集是**有序数组**而非字典——因为匹配靠 `findLast`，顺序即优先级（见流程）。运行时用户每批一次，规则就追加进 `approved`，后续同类请求直接命中、不再问。

## 处理流程分析（三段式）

### 第一段：命令归约（bash 专属，token → arity 前缀）

当 agent 要跑 bash，命令先经 `prefix()` 归约：`["git","checkout","main"]` → `["git","checkout"]`。这一步把"待匹配对象"从**完整命令串**降维成**人类授权概念**。其余工具（read/edit/webfetch…）的 pattern 是文件路径或 URL，不走 arity，直接进规则匹配。

### 第二段：规则求值（`evaluate`，last-match-wins）

核心就 10 行，但每一行都是设计决策：

```typescript
export function evaluate(permission, pattern, ...rulesets): Rule {
  return rulesets.flat()
    .findLast((rule) =>
      Wildcard.match(permission, rule.permission) &&   // 工具名匹配(支持 *)
      Wildcard.match(pattern, rule.pattern))           // 命令/路径模式匹配(支持 *)
    ?? { action: "ask", permission, pattern: "*" }      // 兜底：没规则就问
}
```

三个关键决策：
1. **`findLast`（最后匹配胜出）**：多条规则都匹配时，**靠后的赢**。这让用户能"先宽后窄"地叠规则——前面写 `"*": "allow"`，后面写 `"rm *": "deny"`，结果是"除了 rm 都放行"。规则顺序 = 优先级，符合人类"后说的算"的直觉。
2. **默认 `ask`**：任何没被规则覆盖的命令，**默认问人**而不是默认放行。这是"default safe"——配置的缺失倾向于安全侧。（注意：用户若写 `bash: "allow"` 就把默认翻成了放行，安全责任转移到用户。）
3. **deny 短路**（在 `ask` 循环里）：一条命令可能含多个子命令（`patterns` 数组），**任一子命令命中 deny 就立即整体拒绝**，不给"部分放行"的机会。

### 第三段：异步审批与运行时学习

```typescript
for (const pattern of request.patterns) {
  const rule = evaluate(request.permission, pattern, ruleset, approved)
  if (rule.action === "deny") return new DeniedError(...)   // 短路拒绝
  if (rule.action === "ask")  needsAsk = true               // 标记需问
}
// needsAsk → 创建 Deferred，挂进 pending，事件总线推 permission.asked，阻塞等 reply
```

- **Deferred 异步阻塞**：用 Effect 的 `Deferred` 而非线程 Event（OpenCode 是 TS/单线程异步），等用户从前端答复。
- **运行时学习**：用户批准时可选"记住"，规则追加进 `state.approved`，下次 `evaluate` 把它和静态 `ruleset` 一起 flat 求值——**本次会话内同类命令不再问**。这是 arity 归约的回报：批准一次 `git checkout`，整个会话所有 `git checkout *` 都自动放行，因为它们归约到同一个前缀。
- **退出兜底**：finalizer 在服务销毁时把所有 pending 的 Deferred `fail(RejectedError)`，防止挂死（与 Hermes 的会话边界清理同构）。

## 反直觉 / 踩坑

- **安全性完全压在"默认配置"和"用户配置"上**：引擎本身是中立的——`evaluate` 默认 `ask` 是安全的，但只要用户图省事写一句 `bash: "allow"`，整套防护瞬间归零。**OpenCode 把"安全 vs 便利"的权衡完全交给了用户**，工具不替你兜底（对比 Hermes 的 HARDLINE 即使 yolo 也拦）。这是"可控"的代价：可控意味着可以被配置得很不安全。
- **arity 字典是"已知命令"的封闭集**：字典没收录的命令默认 arity=1（只取第一个 token）。冷门 CLI（如某个自研工具 `mytool deploy prod`）会被归约成 `mytool`——可能过宽（一条 `mytool: allow` 放行了 `mytool destroy`）。字典需要持续维护跟上工具生态。
- **last-match-wins 的规则顺序是隐式陷阱**：用户若不理解"后面的规则覆盖前面的"，把 `"*": "allow"` 写在最后，会**意外覆盖掉前面所有的 deny**。顺序敏感的配置容易写错。
- **bash 的 V2 core 目前是 stub**：`packages/core/src/tool/bash.ts` 里有一串 TODO（`Port tree-sitter bash parser-based approval reduction`、`Port BashArity reusable command-prefix approvals`）——说明 arity 归约这套在新架构里**尚未完全迁移**，是已知的 parity 债务。引用时注意版本。

## 适用边界

- OpenCode 这套**适合"用户愿意花时间配规则"的场景**——团队把权限规则 checkin 进项目配置，复用性极好（一次配置全队生效）。
- 对"开箱即用、零配置就要有保护"的需求，它不如 Hermes 的黑名单——**默认 `ask` 虽安全但会高频打断**，用户为了不被打断容易过度放宽。
- 同样**不能替代 OS 沙箱**。规则引擎是"识别+审批"层，破了就直达真实文件系统。

## 关联

- 父设计一（Hermes）：对照"硬编码黑名单（工具替你判断危险）"vs"配置规则集（你自己声明危险）"。Hermes 默认更安全但不灵活，OpenCode 更灵活但安全靠用户。
- 父设计三（Claude Code）：Claude Code 的 `permissions.allow/deny`（`Tool(specifier)` 语法）在思路上接近 OpenCode 的规则集，但额外叠了 OS 沙箱。
- arity 归约思想可迁移到任何"把无限命令变体映射到有限授权概念"的场景。
