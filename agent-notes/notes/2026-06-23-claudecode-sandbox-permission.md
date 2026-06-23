# 父设计三 · Claude Code：OS 级沙箱（seatbelt / bubblewrap）+ 多模式权限引擎

> 源码取证基准：Claude Code 官方不开源。证据取自 v2.1.161 原生二进制 `bin/claude.exe`（GIT_SHA `6a550ae`，BUILD 2026-06-02），用 `strings` 抠出嵌入的逻辑常量、错误消息、deobfuscate 出的函数体；辅以 `sdk-tools.d.ts` 类型定义。**第三方 Rust 复刻 `soongenwong/claudecode` 不作为官方证据**，仅在思路印证处标注引用。
> 函数名（`bk_`/`oN6`/`UVK`/`bN`/`zK3` 等）是压缩后的混淆名，逻辑结构为一手，仅符号名不可读。

## 这个父设计解决什么问题

Hermes（父设计一）和 OpenCode（父设计二）都赌"软门拦得住"——它们的安全边界是**进程内字符串匹配**，一旦黑名单漏了一条、或配置写松了，恶意命令直达真实文件系统。Claude Code 走了**纵深防御**：它不只在执行前判断"该不该放行"（这层它也有，且做得比前两家更精细），还在执行时套一层 **OS 内核级沙箱**，让"即使前面所有软门都被骗过，进程也炸不出沙箱"。

它要解决三个递进问题：
1. 如何把"命令该不该放行"判断得足够细——细到能识别 `cd /untrusted && git status` 这种"看似无害、实则会执行目标目录里恶意 git hook"的复合攻击？
2. 软门之外，如何用 OS 机制（macOS seatbelt / Linux seccomp+bubblewrap）做一道**不依赖"识别得准"**的硬隔离？
3. 这两层如何配合 6 种权限模式，让用户在"全人工审批"到"全自动"之间自由滑动？

## 数据结构设计

### 结构一：四态裁决 + 规则的 deny/ask/allow 三层优先级

Claude Code 的裁决不是三态而是**四态**，多出关键的 `passthrough`：

```
behavior: "deny" | "ask" | "allow" | "passthrough"
```

- `deny`：拒绝。
- `ask`：弹人工审批。
- `allow`：放行。
- `passthrough`（精髓）：**"这一层规则没意见，把决定权交给下一层"**。它区分了"明确放行"和"我不管，问别人"——让多层规则能链式委托，而不是每层都被迫表态。

规则匹配严格按 **deny > ask > allow** 优先级（`oN6` 函数）：先查 deny 规则命中即拒、再查 ask、再查 allow，全不中则 `passthrough`。**deny 永远压过 allow**——这意味着用户写一条 `allow: "git *"` 也无法覆盖 `deny: "git push --force"`，安全侧永远优先。规则用 `Tool(specifier)` 语法（如 `Bash(npm run test:*)`、`Read(./secret/**)`），存于 settings 的 `permissions.allow` / `permissions.deny` 数组。

### 结构二：命令 AST + 子命令分解（应对复合命令攻击）

这是 Claude Code 比前两家精细得多的地方。它不把 bash 命令当字符串，而是**解析成 AST**，拆出每个子命令单独裁决：

```
bk_(command) 流程里：
  ZM_(command) → AST            // tree-sitter 解析 bash
  eM_ → { kind, commands[], bareAssignmentNames }
  kind === "too-complex" → 直接 ask（解析不了的命令不放行）
  否则把 commands[] 逐个子命令求值，再按最严结果聚合
```

聚合用一张**风险优先级表**：`{ deny:3, ask:2, passthrough:1, allow:0 }`——多个子命令的裁决取**最高风险**胜出。`a && b` 里只要 `b` 该 deny，整条就 deny。这堵死了"用合法命令做前缀、把危险命令藏在 `&&`/`;`/管道后面"的绕过——而 Hermes 的整串正则匹配、OpenCode 的前缀归约都更容易被复合命令骗过。

### 结构三：seatbelt / bubblewrap 沙箱配置 + 环境变量洗白名单

OS 沙箱层的数据结构是平台相关的 profile：

- **macOS**：seatbelt profile，S-表达式语法 `(allow file-read*)` / `(deny file-write* ...)` / `(deny network*)`，由 `sandbox-exec` 加载。
- **Linux**：bubblewrap（`bwrap`）做 namespace 隔离 + seccomp-bpf 过滤系统调用（`apply-seccomp` 二进制），unix socket 阻断需 `@anthropic-ai/sandbox-runtime` 全局安装。

配套一个**环境变量洗白正则**（防止借环境变量逃逸）：

```javascript
$K3 = /^(LD_|DYLD_|PATH$)/   // 沙箱内剥离 LD_PRELOAD/LD_LIBRARY_PATH/DYLD_*/PATH
```

防什么：`LD_PRELOAD` 能让进程加载任意 `.so` 劫持库函数，`DYLD_*` 是 macOS 等价物，`PATH` 改写能让 `git` 指向恶意脚本。沙箱内必须把这几类**注入型环境变量**洗掉，否则沙箱内的进程能通过预加载库逃逸。

### 结构四：6 种权限模式

```typescript
mode: "default" | "acceptEdits" | "plan" | "bypassPermissions" | "dontAsk" | "auto"
```

- `default`：每个危险操作都问。
- `acceptEdits`：自动接受文件编辑，但命令仍问。
- `plan`：只读规划，不执行任何写操作（最严）。
- `bypassPermissions`：全自动放行（最松，对应别家的 yolo）。
- `dontAsk` / `auto`：自动模式变体（auto 配合沙箱，自动放行被沙箱兜住的命令）。

模式是一条从"全人工"到"全自动"的光谱，**且和沙箱联动**：`auto` 模式下"被沙箱保护的命令自动放行、逃出沙箱的命令才问人"——这是软门与硬墙配合的关键设计。

## 处理流程分析（三段式）

### 第一段：精细化软门裁决（执行前，`bk_`）

命令进来后：

1. **AST 解析**：`ZM_` 用 tree-sitter 解析。解析失败/过于复杂 → 直接 `ask`（**"看不懂就问"**，不赌）。
2. **空变量路径守卫**（一手原文）：检测 `rm -rf $UNSET/*` 这类——当 `$UNSET` 为空时展开成 `rm -rf /*`。这种命令**"requires explicit approval and cannot be auto-allowed by permission rules"**，即任何 allow 规则都救不了它，必须人工。这正是 OpenCode/Hermes 容易漏的变量展开攻击。
3. **逐子命令规则匹配**：每个子命令走 `oN6`（exact）/`UVK`（prefix），deny>ask>allow>passthrough。
4. **cd-git 复合攻击检测**（一手原文）：识别 `cd /some/dir && git ...`——因为 git 会执行**目标目录里的 hook / fsmonitor**，攻击者可在不受信目录放恶意 `.git/hooks/`。命中即强制 `ask`，理由是"changes directory before running git, which can execute untrusted hooks from the target directory"。还有一条专测"先创建 `.git/HEAD`/`objects`/`refs`/`hooks` 再跑 git"的构造攻击。**这种攻击模型 Hermes/OpenCode 完全没覆盖**。

### 第二段：OS 沙箱决策与执行（`bN` / `zK3`）

软门放行后，决定**在不在沙箱里跑**：

```javascript
function bN(H) {  // 是否需要沙箱执行
  if (沙箱未启用) return false
  if (H.dangerouslyDisableSandbox && 允许非沙箱命令) return false  // 逃生舱
  if (命中 excludedCommands) return false                          // 白名单豁免
  return true
}
```

核心规则（一手原文）：**"All bash commands invoked by the model must run in the sandbox unless they are explicitly listed in excludedCommands."** 默认全员进沙箱，只有用户显式列进 `excludedCommands` 的才豁免。`zK3` 用 prefix/exact/wildcard 三种方式匹配豁免列表。

沙箱内：文件系统按 profile 限制读写范围、网络默认 deny（可选开 in-process TLS termination 让 per-request filter 看到 HTTPS body 做内容级过滤）、seccomp 过滤危险 syscall、`$K3` 洗掉注入型环境变量。

### 第三段：失败降级与逃生舱

- **沙箱不可用降级**（一手原文）：Linux 上若 `apply-seccomp` 二进制缺失，打印 "unix socket blocking disabled. Install @anthropic-ai/sandbox-runtime globally for full protection"——**沙箱是尽力而为，缺依赖时降级而非硬失败**。这是工程妥协，也是潜在弱点（降级后保护打折）。
- **`dangerouslyDisableSandbox` 逃生舱**：命令可带此标志请求出沙箱跑，但仅当 `areUnsandboxedCommandsAllowed()` 为真时生效。命名里大写的 `dangerously` 是有意的"摩擦设计"——逼用户意识到风险。

## 反直觉 / 踩坑

- **三家最锋利的分野：只有 Claude Code 有第三层硬隔离**。Hermes/OpenCode 的安全 = "识别准确性"，Claude Code 多了一层**不依赖识别准确性**的 OS 墙——seatbelt 不关心命令是不是恶意，只管"这进程能不能写 `~/.ssh`、能不能联网"。这是从"信任模型不作恶"到"假设模型会作恶"的范式跃迁。
- **沙箱有逃生舱和降级路径，不是铁桶**：`dangerouslyDisableSandbox` + 缺依赖降级，意味着实战中沙箱可能没真正生效。"有沙箱"不等于"安全"，要确认它真的在跑（CLI 的 `sandbox enabled` 状态、依赖装全）。
- **AST 子命令分解是软门做对的关键**：把复合命令拆开逐个最严裁决，是前两家用整串匹配/前缀归约都做不到的。复合命令、变量展开、cd-git hook 是三类真实攻击面，Claude Code 显式覆盖了，**这恰恰反衬出纯黑名单/纯前缀方案的盲区**。
- **平台依赖重**：seatbelt 仅 macOS、bwrap+seccomp 仅 Linux、WSL 下部分功能直接不支持。跨平台一致性是代价。

## 适用边界

- Claude Code 这套**适合"既要自动化效率、又要在不受信代码/环境里跑 agent"的场景**——沙箱兜底让"放宽审批"变得有资格。
- 工程成本最高（三层 + 平台适配 + 依赖管理），对"跑在自己信任主机、只防手滑"的轻量需求是过度设计——那种场景 Hermes 的黑名单足够。
- **关键启发**：是否放宽 agent 审批（开 auto/bypass），取决于**有没有第三层隔离**。有沙箱（或自己用 Docker/受限用户）才有资格自动化；没有就老老实实人工过审高危操作。

## 关联

- 父设计一（Hermes）/ 父设计二（OpenCode）：都只有"识别+审批"软门，无 OS 沙箱。Claude Code 补上的正是它们缺的第三层。
- 总纲提炼的"三层纵深"（识别→审批→隔离）：Claude Code 是唯一三层全点亮的，但每层都有缝（黑名单外的命令靠沙箱兜、沙箱有逃生舱靠审批兜）——**纵深防御的价值正在于"每层的缝不重叠"**。
- 与 **Tool Use** / **Multi-Agent** 正交关联同总纲。
