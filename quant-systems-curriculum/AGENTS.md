# AGENTS.md — 量化系统底层修炼｜OS & C++ 专栏系统说明

## 这是什么

用户对标**幻方 / 九坤 / 灵均 / 明汯**这类头部量化私募**低延迟交易系统 / HPC / 高频研究**岗位的 C++ & Linux OS 学习专栏，沉淀到独立 Notion 数据库《量化系统底层修炼｜OS & C++》。

源大纲：`大纲_量化OS与Cpp学习路线.md`（A 档深度，已用官方一手技术文档校准）。
证据留痕：`证据_一手出处核验.md`（Rigtorp / LMAX / kernel 文档 / cppreference 出处对照）。

**不是** AI 科普，**不是** Transformer 课程（隔壁 ai-teacher），**不是** Agent 经验（隔壁 agent-notes）。三者独立 DB，互不干扰。

## 内容流（铁律：绝不自动产出）

同 agent-notes，唯一合法流程：用户口述/确认范围 → 我整理润色 → **用户人工确认** → 同步 Notion。
禁止 cron 定时自动生成课时、禁止替用户编造内容、禁止跳过确认直接同步。
（本专栏是学习大纲驱动，可由用户指定「把大纲第 N 阶段拆成课时」批量产出，但每批仍需用户确认后才 sync。）

## 目录

- 项目根：`~/hermes-workspace/quant-systems-curriculum/`
- 源大纲：`大纲_量化OS与Cpp学习路线.md` ｜ 证据：`证据_一手出处核验.md`
- Notion 配置：`.openclaw/notion_quant_curriculum.json`（**database_id: `38fd8689-fc19-81f8-a78b-d867a22736b5`**）
- 同步引擎：`scripts/sync_to_notion.py`（从 agent-notes 复用最新版，含 table/language-alias/parent-title 全部修复，唯一合法 Notion 写入口）
- 课时 Markdown：`notes/YYYY-MM-DD-slug.md`（总纲页用 `notes/总纲_*.md`）
- **始终用 `/opt/homebrew/bin/python3`**，不用系统 python。

## Notion 数据库字段（5 个领域维度 + 稳定脊柱）

领域维度（全是单选 select，除 Tags）：
- **Part**（部分，单选）：`C++` / `OS` / `综合`
- **Stage**（阶段，单选）：对应大纲阶段，如 `C4·内存模型与并发`、`O4·中断与内核旁路`。命名 = 大纲阶段号·阶段名。
- **Difficulty**（难度，单选）：`🟢入门` / `🟡进阶` / `🔴硬核` / `⚫天花板`（沿用大纲 emoji 标注）
- **Tier**（档位，单选）：`C·研究员` / `B·HPC平台` / `A·低延迟核心`（这个知识点要求到哪一档）
- **Tags**（多选）：自由打标，如 `无锁,SPSC,cache-line,面试高频`

稳定脊柱：`Name`（标题）/ `Topic` / `Lesson Date` / `Status` / `Source`(固定 `quant-curriculum`) / `Discord Message` / `Parent item`(自关联缩进树)。

## 同步命令

```bash
/opt/homebrew/bin/python3 ~/hermes-workspace/quant-systems-curriculum/scripts/sync_to_notion.py \
  --file notes/YYYY-MM-DD-slug.md \
  --title "课时标题" --topic "课时标题" \
  --part "C++" --stage "C4·内存模型与并发" \
  --difficulty "🔴硬核" --tier "A·低延迟核心" \
  --tags "无锁,SPSC,面试高频" \
  --lesson-date "YYYY-MM-DD" \
  --parent-title "【总纲】第一部分 C++ 学习路线"
```

`--file` 必须是 flag（不能位置传参）。脚本按 Name 幂等 upsert（同标题先归档再建，可安全重同步修正稿）。

## Sub-item 缩进树结构

- **一棵树 = 大纲一个部分**，目前两个总纲根页：`【总纲】第一部分 C++ 学习路线`、`【总纲】第二部分 操作系统(Linux)学习路线`。
- 各阶段课时用 `--parent-title "总纲标题"` 挂到对应总纲根页下，形成缩进树。
- 子设计（阶段内的具体知识点）= 课时页内的 H2/H3 标题，不再拆独立页。

### ⚠️ 坑：总纲页必须先建好正文，再挂子课时

`--parent-title` 指向一个**还不存在**的总纲页时，引擎会幂等**创建一个空占位根页**（无正文）。若此时先挂了子课时，之后再给总纲页写正文（用 `--file ... --title "【总纲】..."`），upsert 会**归档旧空占位、新建带正文的页 → page_id 变了**，导致已挂的子课时变孤儿（仍指向旧 id）。
**正确顺序**：先 sync 总纲页正文（建立稳定 page_id），再 sync 子课时带 `--parent-title` 挂上去。若顺序错了，重新 sync 一遍子课时即可自愈（`--parent-title` 会按 Name 重新找到新总纲页）。

## 公式格式硬约束

同 ai-teacher：LaTeX 用 `$...$` / `$$...$$`，禁塞代码块，禁 Unicode 上下标。
代码块语言用全名（`cpp`/`bash`/`python`），引擎已带 alias 映射但仍建议用全名。

## 图文并茂（图片直传 Notion，2026-06-30 新增）

课时**必须图文并茂**——读者按「懂数据结构与算法的大一新生」对待，讲透机制、少做类比、关键结构都配图。

- **写法**：markdown 里正常用 `![图说明](../assets/xxx.png)` 引用本地图，**路径相对该 .md 文件所在目录**（notes/ 下的课时引用 `../assets/`）。
- **同步引擎已支持**：`sync_to_notion.py` 解析到独立成行的 `![](...)` 会自动走 Notion **File Upload API** 上传图片，转成真 image block，由 Notion 自家 S3 托管——**不依赖外部图床、不会过期、不暴露本机路径**。alt 文本作为图注 caption。
- **画图**：用 `/opt/homebrew/bin/python3` + matplotlib（已装，中文字体用 `Hiragino Sans GB` / `Songti SC`，`axes.unicode_minus=False`）。画图脚本放 `scripts/draw_*.py`，输出到 `assets/`。**避免 µ/✓/✗ 等 Hiragino 缺字形字符**（用 us / [好] / [坏] 替代），否则出豆腐块。
- **画原理本身，不画拟人类比**：环形结构、指针推进快照、cache line 布局、happens-before 时序——直接把数据结构和机制画出来。范例见 `scripts/draw_spsc.py`（5 张图）。
- **assets/ 纳入 git**（已确认不被 gitignore），图和课时一起版本化。
- 验证：同步后回读页面 `blocks/{pid}/children`，确认 `type==image` 的块数等于课时图数，且 url 含 `prod-files-secure`（= Notion 自托管成功）。

## 数据/证据纪律

- 技术知识点本身用官方一手技术文档核验，出处写进课时页脚 + `证据_一手出处核验.md`。
- 「要求到哪一档（Tier）」是领域经验判断，非真实 JD 原文——课时里如做此类标定须诚实标注。
- 禁用 SEO 营销农场「年薪百万面经」类二手内容作证据源。

*最后更新：2026-06-30（建库 + fork agent-notes 引擎 + 端到端验证通过）*
