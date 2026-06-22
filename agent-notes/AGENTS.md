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
- **Category**（主题分类，单选）：上下文管理 / Agent Loop / 工具调用 / 记忆系统 / 多智能体 / Prompt 工程 / 模型选型 / 框架配置 / 其他
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

## 条目结构

见 `TEMPLATE.md`。核心七段：一句话结论 → 场景触发 → **机制原理（灵魂）** → 我的做法 → 反直觉/踩坑 → 适用边界 → 关联。
机制原理段是本栏目区别于普通"操作笔记"的关键：必须讲清「为什么 agent 会这样表现」。

*最后更新：2026-06-22*
