# AI Research 门户

投研合伙人的 AI 研究门户网站。当前首个页签「核心论文链接」汇总少样本学习 / 世界模型的核心论文，每条均经一手源核对（arXiv 摘要页 / Crossref DOI）。

## 定位
- 沉淀 AI 研究的核心论文源、框架笔记
- 通过 frp 穿透到外网，登记在「价值雷达」(合伙人驾驶舱) 项目卡片，可点击跳转

## 架构
- `app.py` — Flask 后端，本地端口 5056（环境变量 `AI_RESEARCH_PORT` 可覆盖）
- `static/index.html` — 响应式前端（PC 侧栏 / 手机底 tabbar）
- `data/papers.json` — 论文数据源，含 `verified` 字段标注核对来源

## API
- `GET /` — 前端页面
- `GET /healthz` — 健康检查
- `GET /api/papers` — 论文数据 JSON

## 端口
- 本地 5056 → frpc 远端 6018（`quant-industry`/合伙人段顺延）

## 常驻
- launchd: `~/Library/LaunchAgents/com.hermes.ai-research-web.plist`（KeepAlive + RunAtLoad）
- 重启: 查 PID → kill → launchd 自动拉起（勿用 kickstart，会被网关拦）

## 数据严谨性
- 每篇论文带 `verified` 字段说明核对方式，未核对的一律进 `pending` 区诚实标注，不摆未核实内容
- arXiv ID 经 arxiv.org 摘要页标题核对；期刊论文经 Crossref 核对 DOI/作者/年份

## 扩展
- 新增页签：在 `static/index.html` 的 nav/tabbar/tab-pane 三处加对应块
- 新增论文：编辑 `data/papers.json`，API 现读现解析无需重启
