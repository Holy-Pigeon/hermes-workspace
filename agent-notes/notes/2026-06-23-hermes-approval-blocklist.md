# 父设计一 · Hermes：硬编码模式黑名单 + 两级审批门

> 源码取证基准：`tools/approval.py`（1645 行，本机 editable 安装 `/Users/xiaogexu/.hermes/hermes-agent/`，版本 0.15.1）。
> 以下行号均指 `approval.py`。辅证：`tools/tirith_security.py`（独立策略扫描器，37 行入口）。

## 这个父设计解决什么问题

Hermes 跑在用户**真实主机**上（不是容器、不是受限用户），terminal 工具直通 shell。它没有 OS 级沙箱兜底（已核查：全仓无 seatbelt/bwrap/seccomp 调用）。这意味着**唯一的防线就是"在命令执行前，靠字符串匹配认出危险并拦下"**。这个父设计要回答：如何用一套进程内的规则，在零配置前提下，区分出"不可逆的灾难命令"（直接拒）、"有风险但可能合理的命令"（问人），和"日常安全命令"（放行）——并且要扛得住模型用 Unicode 全角字符、ANSI 转义序列做混淆绕过。

核心设计是**两级正则黑名单 + 三态审批决策 + 反混淆归一化**。

## 数据结构设计

### 结构一：两级正则模式表

危险识别不是一张表，而是**两张优先级不同的表**，对应两种处理后果：

```python
# 第一级：HARDLINE — 不可逆灾难，无条件拒绝，连 --yolo 都不能绕
HARDLINE_PATTERNS = [
    (r'\brm\s+(-[^\s]*\s+)*(/|/\*|/ \*)(\s|$)', "recursive delete of root filesystem"),
    (r'\brm\s+(-[^\s]*\s+)*(/home|/root|/etc|/usr|/var|/bin|/sbin|/boot|/lib...)',
     "recursive delete of system directory"),
    # …共 12 条
]

# 第二级：DANGEROUS — 有风险但可能合理，命中后弹人工审批
DANGEROUS_PATTERNS = [ … ]   # 共 47 条：git push --force、dd、mkfs、chmod -R 777、
                              # curl|bash、:(){ :|:& };:（fork bomb）、数据库 DROP 等
```

**为什么分两级**：这是整个设计的灵魂。`rm -rf /` 和 `git push --force` 不是同一种危险——前者**不可逆且永无正当理由**（在 agent 里跑），后者**有风险但用户可能真的想 force push**。把它们塞进同一张表只能要么全拒（误伤合理操作）要么全问（灾难命令也给了放行的机会）。分级让"决策后果"和"危险等级"对齐：HARDLINE → 关死，DANGEROUS → 交给人。

每条都是 `(正则, 人类可读描述)` 二元组，描述同时充当 `pattern_key`（审批作用域的去重键）。

### 结构二：审批决策的三态作用域 + YOLO 旁路

命中 DANGEROUS 后，审批结果不是布尔，而是带作用域的枚举：

```python
result: "once" | "session" | "always" | "deny"
```

- `once`：只批这一次，下次同样命令再问。
- `session`：本会话内该 pattern_key 不再问（`_session_approved[session_key].add(pattern_key)`）。
- `always`：永久放行（`_permanent_approved`）。
- `deny`：拒绝执行。

配套一个**会话级 YOLO 旁路**（`_session_yolo: set[str]`）：用户主动 `/yolo` 后，本会话所有 DANGEROUS 静默放行——**但 HARDLINE 不受 YOLO 影响**（见处理流程第 3 步）。这是"用户可以授权放宽风险门，但不能授权放宽灾难门"的设计表达。

### 结构三：线程安全的审批队列

```python
_lock = threading.Lock()
_gateway_queues: dict[str, list[_ApprovalEntry]]   # session → 待批队列(FIFO)
class _ApprovalEntry:
    __slots__ = ("event", "data", "result")        # threading.Event 阻塞 agent 线程
```

每个待批命令是一个 `_ApprovalEntry`，持有一个 `threading.Event`。**agent 线程命中 DANGEROUS 后阻塞在 `event.wait()`**，直到用户从 gateway 发 `/approve`（解析最老的，FIFO）或 `/approve all`（一次清空队列）调 `event.set()` 唤醒。这套设计支持**并行 subagent / execute_code 并发阻塞**——每个线程各自一个 Event，互不干扰。

## 处理流程分析（三段式）

### 第一段：反混淆归一化（`_normalize_command_for_detection`，行 485-500）

匹配前先把命令"洗干净"，这是抗绕过的关键：

```python
command = strip_ansi(command)                    # 剥离全部 ANSI 转义(CSI/OSC/DCS/8-bit C1)
command = command.replace('\x00', '')            # 去 null 字节
command = unicodedata.normalize('NFKC', command) # Unicode 归一(全角→半角、半角片假名等)
```

**防什么坑**：模型（或注入的恶意 prompt）可能写 `ｒｍ -rf /`（全角字母）或在命令里塞 ANSI 转义序列，绕过朴素的 `rm` 正则。NFKC 归一把全角 `ｒｍ` 折叠成 ASCII `rm`，`strip_ansi` 抹掉转义噪音——**让混淆后的命令和原始命令在匹配前长得一样**。这是"识别层"最容易被忽略、却最致命的一环：黑名单写得再全，只要归一化漏了，全角绕过就能开后门。

### 第二段：分级裁决（先 HARDLINE 后 sudo guard 后 DANGEROUS）

执行前按**严格优先级**逐层过：

1. **HARDLINE 检查**（`detect_hardline_command`）：命中即返回 `_hardline_block_result`，消息明确写"cannot be executed via the agent — **not even with --yolo, /yolo, approvals.mode=off, or cron approve mode**"。这是**唯一一条 YOLO 也撬不开的门**。
2. **sudo stdin guard**（`_check_sudo_stdin_guard`）：当 `SUDO_PASSWORD` 未配置却出现 `sudo -S`（管道喂密码），判定为**模型在暴力猜密码**（迭代候选密码、读 "Sorry, try again" 反馈、再精炼），无条件拒。
3. **DANGEROUS 检查**（`detect_dangerous_command`）：命中后查作用域——已 `always`/本 session 已批/YOLO 开 → 放行；否则入队 `_ApprovalEntry`，阻塞 agent 线程等人工裁决。

**精妙点**：HARDLINE 排在 YOLO 旁路判断**之前**。代码结构强制保证"无论用户怎么放宽配置，`rm -rf /` 这类命令的拦截逻辑都先于任何旁路执行"——安全门的优先级被**写死在控制流里**，而不是靠配置项保证，配置写错也撬不动 HARDLINE。

### 第三段：审批桥接与会话边界清理

- **同步→异步桥**：agent 线程是同步的，gateway 是异步的。`register_gateway_notify` 注册回调把审批请求推给用户，agent 线程 `event.wait()` 阻塞，gateway 收到 `/approve` 后 `resolve_gateway_approval` 唤醒。
- **会话边界兜底**（`clear_session` / `unregister_gateway_notify`）：会话结束或被打断时，把所有阻塞中的 `_ApprovalEntry` 全部 `result="deny"; event.set()`——**防止 agent 线程永久挂死**等一个永远不会来的审批。这是并发设计里最容易漏的"清理路径"，Hermes 显式处理了。

## 反直觉 / 踩坑

- **黑名单的封闭世界假设是根本缺陷**：这套设计的安全性 = "12+47 条正则覆盖了所有危险命令" 这个假设的真假。但攻击面是**开放**的——`> /dev/sda`、`chmod 000 -R /`、把文件 base64 编码后 `curl` 外传，只要没列进表就一律放行。**黑名单永远在追赶，永远漏**。这是 Hermes 选择"零配置即有保护"必然付出的代价。
- **HARDLINE 的"连 yolo 都不能绕"是有意为之的家长式设计**：它假设"用户在 agent 里跑 `rm -rf /` 一定是 agent 出错或被注入，绝无真实意图"。代价是真有需求时得自己开终端跑——但这个权衡是对的，因为这类命令在 agent 上下文里 100% 是事故。
- **反混淆归一化容易被当成"过度设计"删掉**：维护者若不理解全角/ANSI 绕过，可能觉得"命令哪会有全角字符"而精简掉 `_normalize_command_for_detection`——这会**直接打开混淆后门**。这一层必须保留。

## 适用边界

- Hermes 这套**只适合"软门即唯一防线"的场景**——跑在信任主机、靠识别+审批拦截。**它不能替代 OS 沙箱**（对比父设计三）。在不受信环境跑 Hermes，应额外套 Docker / 受限用户。
- 两级黑名单的价值是**零配置兜底**，不是完备防护。把它理解成"防手滑、防明显事故的安全气囊"，而非"防蓄意攻击的防火墙"。

## 关联

- 父设计二（OpenCode）：走相反路线——**不预判危险**，把裁决权全交给用户配置规则。对照看"硬编码黑名单"vs"配置驱动规则集"的取舍。
- 父设计三（Claude Code）：在软门之下加 OS 级沙箱，补上 Hermes 缺的"第三层隔离"。
- `tirith_security.py`：Hermes 另有一个独立的 OPA/policy 风格安全扫描器，是黑名单之外的策略层补充（本文未展开）。
