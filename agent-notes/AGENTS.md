# AGENTS.md — Agent 经验沉淀 系统说明

## 这是什么

用户的个人 **agent 实战经验库**，沉淀到独立 Notion 数据库《Agent 经验沉淀》。
侧重 **agent 原理理解**：上下文管理、agent loop、工具调用、记忆系统、多智能体协作等机制层认知。

**不是** AI 科普，**不是** Transformer 课程（那是隔壁 ai-teacher 项目，互不干扰）。
这里记的是「用户自己用 agent 踩出来的、带机制理解的实战心得」。

## 内容流（铁律：绝不自动产出）

唯一合法流程：

1. **用户口述** 一条经验 / 一段聊天 / 一个踩坑（哪怕只有一句话）。
2. **我 review + 提炼**：补全机制原理、整理成 `TEMPLATE.md` 的结构、润色文案。
3. **用户人工确认**：把润色稿发给用户看，用户拍板「可以」才进下一步。**未经确认绝不同步**。
4. **同步到 Notion**：保存 Markdown 到 `notes/YYYY-MM-DD-slug.md`，调用 `scripts/sync_to_notion.py`。

**禁止**：禁止 cron 定时自动生成经验；禁止我替用户编造"经验"；禁止跳过用户确认直接同步。
经验是用户的，我是编辑 + 排版工，不是作者。

## 目录

- 项目根：`~/hermes-workspace/agent-notes/`
- 条目模板：`TEMPLATE.md`
- Notion 配置：`.openclaw/notion_agent_notes.json`（database_id: `387d8689-fc19-8191-94e9-cc2ad595d91b`）
- 同步引擎：`scripts/sync_to_notion.py`（从 ai-teacher 复用，唯一合法 Notion 写入口）
- 条目 Markdown：`notes/YYYY-MM-DD-slug.md`
- **始终用 `/opt/homebrew/bin/python3`**（带 ssl/代理容错），不用系统 python。

## Notion 数据库字段

- **Name**（标题）/ **Topic**（主题）
- **Category**（主题分类，单选）：**只能从下方 9 类 canonical taxonomy 选一个**，禁止随手新造分类（见「分类 Taxonomy」节）
- **Tags**（多选标签）：一条经验常跨多个点，自由打标
- **Maturity**（成熟度，单选）：验证过 / 经验法则 / 待验证 —— 体现实战可信度
- **Lesson Date**（记录日期）/ **Status** / **Source**（固定 agent-notes）

## 同步命令

```bash
/opt/homebrew/bin/python3 ~/hermes-workspace/agent-notes/scripts/sync_to_notion.py \
  --file ~/hermes-workspace/agent-notes/notes/YYYY-MM-DD-slug.md \
  --title "经验标题" \
  --topic "经验标题" \
  --category "上下文管理" \
  --tags "上下文窗口,截断,成本" \
  --maturity "验证过" \
  --lesson-date "YYYY-MM-DD"
```

脚本按 Name 幂等 upsert（同标题先归档再建，可安全重同步修正稿）。

## 公式格式硬约束

同 ai-teacher：LaTeX 用 `$...$` / `$$...$$`，禁塞代码块，禁 Unicode 上下标。
（agent 经验里数学少，但偶有复杂度/概率表达式时遵守此约束。）

## 分类 Taxonomy（Category 唯一合法取值）

Category 字段为单选，**只能从以下 9 类选一个**。这是 canonical 命名，禁止随手新造或改写——
一条经验若跨多类，挑「最核心的机制层」归类，其余维度用 Tags 表达。

| # | Category（canonical） | 覆盖范围 |
|---|---|---|
| 1 | **Context Engineering** | 给模型组织上下文：compaction、context rot、注意力预算、prompt 拼装、检索注入、上下文窗口管理 |
| 2 | **Tool Use** | 让模型调用工具：MCP / Shell / Browser / File / IDE 等所有工具调用机制 |
| 3 | **Agent Loop** | 控制循环：ReAct 循环、停止条件、错误重试、循环预算 |
| 4 | **Planning & Reasoning** | 拆任务、规划、反思：todo 分解、计划模式、self-reflection |
| 5 | **Memory** | 管理记忆：长期/短期记忆、向量库、记忆写回与召回 |
| 6 | **Multi-Agent** | 多子任务协作：subagent、编排、并行 workstream、上下文隔离 |
| 7 | **Permissions & Sandbox** | 控制权限、安全、沙箱、回滚 |
| 8 | **Telemetry & Feedback** | 记录用户反馈和执行轨迹，用来改进产品和训练模型 |
| 9 | **Product & UX** | 把模型能力变成桌面端用户体验 |

新增第 10+ 类前必须先问用户拍板，不得自行扩充。

## 条目结构

见 `TEMPLATE.md`。核心七段：一句话结论 → 场景触发 → **机制原理（灵魂）** → 我的做法 → 反直觉/踩坑 → 适用边界 → 关联。
机制原理段是本栏目区别于普通"操作笔记"的关键：必须讲清「为什么 agent 会这样表现」。

*最后更新：2026-06-22（新增 9 类 canonical taxonomy）*
