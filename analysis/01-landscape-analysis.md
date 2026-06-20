# OhMyInfo — 技术信息差消除工具 · 行业全景分析

> 分析基于 40+ 个开源项目的调研 (2026年6月)
> 涵盖 AI 聚合、技术雷达、日报推送、情报监控四大领域

---

## 一、问题定义与市场背景

### 1.1 核心痛点

- **信息超载**: 每天 500+ AI 相关文章发布，但大多数人只读 3 篇
- **信息碎片**: 信息分散在 Hacker News、GitHub Trending、Reddit、arXiv、Twitter/X、RSS、微信公众号等 10+ 平台
- **语言壁垒**: 多数高质量技术内容为英文，中文开发者存在阅读障碍
- **被动获取**: 依赖主动搜索和推送算法，缺乏个性化、结构化的信息获取方式
- **FOMO 焦虑**: 害怕错过重要技术更新，导致大量时间浪费在刷信息流上

### 1.2 目标用户画像

| 用户类型 | 需求特点 | 关注内容 |
|---------|---------|---------|
| **开发者 (主力)** | 跟踪技术趋势，发现新工具 | GitHub Trending, HN, Reddit, arXiv, 博客 |
| **技术管理者** | 团队技术选型决策，行业动态 | 技术雷达, 行业分析, 竞品动态 |
| **AI 从业者** | 跟踪模型发布、论文、框架更新 | arXiv, HuggingFace, GitHub, 实验室博客 |
| **创业者/产品经理** | 发现商业机会，竞品监控 | Product Hunt, funding, startup radar |
| **技术学习者** | 系统化学习路径，技能提升 | 技术教程, skill gap analysis, 学习路径 |

---

## 二、开源项目全景图

### 2.1 项目分类总览

```
                          开源技术信息聚合生态
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
    AI 聚合摘要          技术雷达/趋势         个性化学习/发现
        │                     │                     │
   ┌────┴────┐          ┌────┴────┐          ┌────┴────┐
   │        │            │        │            │        │
 日报推送  情报平台    代码分析  生态跟踪   技能分析  好奇引擎
```

### 2.2 按 Star 数量的热门项目排名

| 项目 | Stars | 语言 | 核心功能 | 中文支持 |
|------|-------|------|---------|---------|
| **TrendRadar** (sansan0) | ⭐ 54K+ | Python | AI 舆情监控 + 多平台聚合 + 多渠道推送 | ✅ 原生中文 |
| **finaldie/auto-news** | ⭐ 884 | Python | 多源聚合 + LLM 分析 + Notion 集成 | ❌ |
| **zalando/tech-radar** | ⭐ 1.9K | JS | 技术雷达可视化 (ThoughtWorks 风格) | ❌ |
| **Thysrael/Horizon** | ⭐ ~800 | Python | AI 评分 + 双语日报 + GitHub Pages | ✅ 中英双语 |
| **CondenseIt** | ⭐ ~500 | Python | 本地 LLM + 偏好学习 + 多样化源 | ❌ |
| **News Diet** | ⭐ ~400 | Python | Ollama 本地评分 + RSS 管理 | ❌ |
| **Sentinel Feed** | ⭐ ~300 | TypeScript | 7 源 15 分钟更新 + 雷达/地图/列表视图 | ❌ |
| **Repodar** | ⭐ ~200 | Python | GitHub 生态雷达 + 爆发检测 | ❌ |

### 2.3 从技术架构看演进趋势

```
Generation 1 (2020-2022)           Generation 2 (2023-2024)
┌─────────────────────┐           ┌─────────────────────────┐
│ RSS Reader          │           │ RSS + Crawler + LLM     │
│ 规则过滤            │           │ AI 评分/摘要            │
│ 手动配置            │           │ GitHub Actions 定时     │
│ 无个性化            │           │ 邮件/Web 推送           │
│ e.g. Tiny RSS       │           │ e.g. auto-news, NewsDiet│
└─────────────────────┘           └─────────────────────────┘

Generation 3 (2024-2025)           Generation 4 (2025-2026)
┌─────────────────────────┐       ┌────────────────────────────┐
│ Multi-Agent Pipeline    │       │ 个性化智能体                │
│ 多维评分 (ML+规则)      │       │ 自适应学习                  │
│ 双语/多语言             │       │ 多智能体协作                │
│ 偏好学习                │       │ 知识图谱                    │
│ 多渠道推送              │       │ 主动发现 vs 被动聚合        │
│ e.g. Horizon, Sipply    │       │ e.g. Signex, Devloop, DMN   │
│ TechSentry, IntelBrief  │       │ StackPulse                  │
└─────────────────────────┘       └────────────────────────────┘
```

---

## 三、关键发现与成功经验

### 3.1 架构模式：分层 Pipeline 是标配

几乎所有成功的项目都采用 **Pipeline 架构**：

```
Fetch ──→ Dedup ──→ Score/Filter ──→ Enrich ──→ Summarize ──→ Deliver
  │          │           │              │            │            │
  │          │           │              │            │            └─→ Email/Web/IM/GitHub Pages
  │          │           │              │            └─→ LLM 摘要 / 中文翻译
  │          │           │              └─→ 背景搜索 / 社区讨论
  │          │           └─→ AI 评分 / ML 模型 / 规则过滤
  │          └─→ URL 去重 / 相似度去重
  └─→ RSS / HN / GitHub / Reddit / arXiv / Twitter / 微信
```

### 3.2 成功项目的共同特征

| 特征 | 说明 | 代表项目 |
|------|------|---------|
| **零成本运行** | 基于 GitHub Actions 定时触发，无需服务器 | Horizon, TechSentry, ai-news-dashboard |
| **AI 评分** | 使用 LLM 或 ML 模型进行内容质量评分 (0-10) | Horizon (LLM), Sipply (TF-IDF+Ridge) |
| **多渠道推送** | 邮件 + 微信/飞书/钉钉 + Web + GitHub Pages | TrendRadar, TechSentry |
| **中文原生支持** | 自动翻译 + 中文摘要生成 | TechSentry, Intel Briefing, Horizon |
| **渐进式个性化** | 从简单配置到偏好学习再到自适应 | Signex, CondenseIt |
| **低门槛部署** | Docker 一键部署 / GitHub Actions Fork 即用 | Horizon, Signal |
| **可扩展源** | 插件式数据源架构 | Signal, Signex, Sentinel Feed |

### 3.3 中文生态的特殊性

中国开发者面临的特殊问题：

1. **微信生态封闭** — 大量高质量内容在微信公众号中
   - 解决方案：RSSHub + mp.weixin.qq.com 转换
   - 代表项目：lindong28/ai-radar (微信文章解读模块)
   
2. **墙内访问限制** — 部分国际源无法直接访问
   - 解决方案：国内 CDN 镜像 + 代理
   
3. **中文偏好** — 自动英文翻译为中文是刚需
   - 解决方案：LLM 实时翻译 (Gemini/GPT-4o-mini 成本低)
   
4. **国内推送渠道** — 微信、飞书、钉钉优先
   - 代表项目：TrendRadar (支持 7 种国内推送方式)

### 3.4 哪些项目最值得参考

| 学习维度 | 最佳参考项目 | 理由 |
|---------|-------------|------|
| **全栈架构** | Horizon (Thysrael/Horizon) | 完整 Pipeline + 双语 + GitHub Pages |
| **AI 评分系统** | Sipply (fanyang-888) | TF-IDF + Ridge ML 模型, 可复现 |
| **中文生态** | TechSentry (qingni/TechSentry) | GitHub+ HN + Trending → 中文 → 微信 |
| **技术雷达** | Sentinel Feed, Repodar | 多维可视化, 雷达/地图/列表 |
| **偏好学习** | CondenseIt, Signex | 星级评分反馈循环, 自适应排序 |
| **轻量部署** | feed-curator (rizumita) | Claude Code 本身当运行时, 零额外 API |
| **个性化学习** | Devloop, Pathweaver AI | 技能图谱 + 推荐学习内容 |
| **好奇发现** | Default Mode Network | 树搜索 + 多巴胺评分, 意外发现 |

---

## 四、项目风险与挑战

### 4.1 常见失败模式

| 风险 | 描述 | 缓解策略 |
|------|------|---------|
| **内容源失效** | RSS 源变化、API 降级、网站改版 | 多源冗余 + 健康监控 + 自动告警 |
| **AI 成本失控** | LLM API 调用过多导致费用飙升 | 预过滤 + 本地模型 (Ollama) + 缓存 |
| **信息过载** | 聚合太多源反而增加认知负担 | 严格评分 + 个性化阈值 + 用户反馈 |
| **个性化冷启动** | 新用户无偏好数据时推荐不准确 | GitHub 集成自动分析 + 兴趣问卷 |
| **维护成本高** | 需要持续更新爬虫规则 | 选择稳定 API 源 > HTML 解析 |

### 4.2 技术债务预警

- 避免过度依赖特定 LLM 供应商 (OpenAI/Anthropic)
- 数据存储方案应预留迁移路径 (避免 MongoDB Lock-in)
- UI 设计应考虑移动端优先 (国内用户手机阅读为主)

---

## 五、关键技术选型参考

### 5.1 推荐技术栈

| 层级 | 推荐方案 | 备选 |
|------|---------|------|
| **定时任务** | GitHub Actions | Vercel Cron, Railway Cron |
| **数据源采集** | feedparser + httpx + GitHub API | Scrapy, Trafilatura |
| **数据存储** | SQLite (轻量) / PostgreSQL (生产) | JSON 文件, MongoDB |
| **AI 摘要/评分** | GPT-4o-mini / Gemini / Claude Haiku | Ollama 本地模型, DeepSeek |
| **ML 评分** | TF-IDF + Ridge Regression | SBERT, LLM-as-judge |
| **前端展示** | GitHub Pages + 静态 HTML | React/Vite, Vue, Next.js |
| **推送渠道** | Email (Resend) + 微信/飞书 Bot | Telegram, Slack, Webhook |
| **翻译** | LLM 自带 / DeepL API | LibreTranslate |

### 5.2 成本参考 (月费)

| 方案 | 成本 | 说明 |
|------|------|------|
| **纯免费方案** | $0 | GitHub Actions + Ollama + GitHub Pages |
| **入门方案** | ~$2-5 | LLM API (GPT-4o-mini) 用于评分 |
| **标准方案** | ~$10-20 | 多 LLM + 邮件推送 + 域名 |
| **高级方案** | ~$50+ | GPU 本地模型 + VPS 部署 |

---

## 六、总结

当前开源生态已经成熟到可以 **以极低成本 (甚至 $0) 构建一个个人技术情报系统**。关键在于：

1. **不要重新发明轮子** — 借鉴 Horizon/TechSentry 的 Pipeline 架构
2. **中文优先** — 国内用户需要中文摘要和国内推送渠道
3. **个性化 + 自动化** — 从被动获取转向主动发现
4. **渐进式增强** — 从简单 RSS 聚合起步，逐步加入 AI 评分、ML 模型、偏好学习

> OhMyInfo 可以定位为 **"消除技术信息差的 AI 助手"**，融合 Tech Radar 的可视化 + AI News Aggregator 的自动化 + 个性化学习的闭环。
