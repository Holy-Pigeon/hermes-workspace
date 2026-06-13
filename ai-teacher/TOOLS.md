# TOOLS.md - AI Teacher 环境配置

---

## 📁 文件位置

| 文件 | 用途 |
|------|------|
| `AGENTS.md` | 核心教学指令（唯一系统提示词） |
| `taught_topics.json` | 已讲授知识点记录（去重用） |
| `IDENTITY.md` | 身份定义（参考） |
| `SOUL.md` | 价值观（参考） |
| `USER.md` | 用户信息 |
| `HEARTBEAT.md` | 主动检查策略 |

---

## 🔧 技能依赖

无需特殊技能，核心能力是教学输出（不依赖任何 skills 软链接）。

---

## 📊 定时任务配置

**Cron Job**：每 6 小时推送一次知识点

由 Hermes cron 系统管理（job_id: a68017b6a6c9），schedule `0 8,14,20 * * *`，每天 8/14/20 点推送，投递到 Discord #ai-learn。

---

## 📝 去重文件格式

**taught_topics.json**:

```json
{
  "taught_topics": [
    {
      "topic": "具体知识点名称",
      "category": "类目编号 + 名称",
      "taught_at": "2026-03-18T12:00:00Z"
    }
  ],
  "total_count": 0,
  "last_updated": "2026-03-18T12:00:00Z"
}
```

---

*最后更新：2026-03-18*
