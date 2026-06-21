# 🔭 OhMyInfo — 消除技术信息差

> **信息差是这个时代最大的效率杀手。OhMyInfo 的目标是让你永远站在技术前沿。**

> ⚠️ **项目阶段: 研究/规划中** — 已完成 40+ 开源项目的调研分析，产出详尽的方案文档。代码实现尚未开始，欢迎参与。

在 AI 时代，新技术每天都在涌现 —— 新的模型、框架、工具、论文、最佳实践。但大多数人因为信息获取渠道分散、语言障碍、时间有限，无法及时了解和掌握这些技术，导致效率低下。

OhMyInfo 是一个 **开源的个人技术情报系统** 的研究蓝图与设计方案。它不是你又一个需要刷的信息流，而是你的 **技术雷达 + AI 分析师 + 个性化学习助手**。

---

## 📋 目录

- [🎯 核心问题](#-核心问题)
- [🔍 我们做了什么](#-我们做了什么)
- [📊 调研结果概览](#-调研结果概览)
- [🏗️ 推荐方案](#️-推荐方案)
- [📚 文档导航](#-文档导航)
- [🚀 快速开始](#-快速开始)
- [🤝 参与贡献](#-参与贡献)

---

## 🎯 核心问题

### 信息差正在拉大你的效率差距

```
你每天花 30 分钟刷的信息流
    ↓
80% 是噪音 (重复、无关、娱乐)
15% 有点用但记不住
5% 真正有价值但分散在各处
    ↓
一周后你只记得不到 1%
```

### 为什么现有方案不够好？

| 问题 | 传统方案 | 差距 |
|------|---------|------|
| **信息碎片化** | 手动关注多个源 (HN, GitHub, Reddit...) | 时间成本高, 容易遗漏 |
| **语言障碍** | 英文内容为主 | 阅读速度降低 50%+ |
| **噪音过大** | 算法推荐追求时长 | 有用信息淹没在海量内容中 |
| **缺乏个性化** | 统一推送 | 与个人技术栈/兴趣不匹配 |
| **被动获取** | 等推送/自己去刷 | 无法主动发现未知但重要的技术 |

---

## 🔍 我们做了什么

### 大规模开源调研

我们系统性调研了 **40+ 个开源项目**，覆盖全球范围内的技术信息聚合工具：

| 调研维度 | 覆盖范围 |
|---------|---------|
| **AI 新闻聚合器** | Horizon, Sipply, Signal, auto-news, News Diet... |
| **技术雷达** | Sentinel Feed, Repodar, Open Tech Matrix, Zalando Tech Radar... |
| **日报推送系统** | TechSentry, Intel Briefing, ai-news-dashboard, Keep Up Daily... |
| **个性化学习** | Signex, Devloop, Default Mode Network, Pathweaver... |
| **中文生态** | TrendRadar (54K⭐), 伯乐Skill, Echo Trending, AI Daily Frontier... |
| **版本追踪** | StackPulse, repo-radar, ai-landscape-digest... |

### 产出分析文档 (共 6 份)

```
analysis/
├── 01-landscape-analysis.md      # 行业全景分析 (40+ 项目分类、排名、演进)
├── 02-solution-dimensions.md     # 7 维决策矩阵 (采集/处理/个性化/推送/部署/AI/变现)
├── 03-architecture-patterns.md   # 6 种架构模式深度解析 (含 Mermaid 图)
├── 04-recommendation.md          # 推荐方案与渐进式演进路径
├── 05-implementation-plan.md     # 详细实施计划 (TODO 清单)
└── 06-project-review.md          # 项目审查报告 (可行性/Bug/不合理分析)
```

---

## 📊 调研结果概览

### 技术演进 4 代

```
Gen 1 (2020-2022)        Gen 2 (2023-2024)        Gen 3 (2024-2025)        Gen 4 (2025-2026)
┌──────────────┐       ┌────────────────┐       ┌────────────────┐       ┌────────────────────┐
│ RSS Reader   │ ──→   │ RSS + LLM 摘要  │ ──→   │ ML 评分 + 聚类  │ ──→   │ 多 Agent + 知识图谱 │
│ 规则过滤     │       │ GitHub Actions  │       │ 双语自动翻译    │       │ 自适应学习          │
│ 无个性       │       │ 邮件推送        │       │ 多渠道推送      │       │ 主动发现            │
│ TinyRSS 等   │       │ auto-news 等    │       │ Horizon 等      │       │ Signex, Devloop     │
└──────────────┘       └────────────────┘       └────────────────┘       └────────────────────┘
```

### 最佳参考项目 Top 5

| 排名 | 项目 | ⭐ | 核心亮点 | 学习价值 |
|------|------|----|---------|---------|
| 🥇 | **Horizon** | ~800 | 完整 Pipeline + 中英双语 + GitHub Pages | **全栈架构最佳参考** |
| 🥈 | **TechSentry** | ~200 | 中文优先 + 微信推送 + 模块化采集 | **中文生态最佳参考** |
| 🥉 | **Signal** | ~300 | 可扩展源架构 + 完整 Web UI + 偏好学习 | **工程实现最佳参考** |
| 4 | **Sipply** | — | ML 评分模型 (Pearson r=0.75) + 11 阶段 Pipeline | **评分系统最佳参考** |
| 5 | **Sentinel Feed** | ~300 | 3 种可视化视图 + 7 源 15 分钟更新 | **可视化最佳参考** |

### 关键成功经验

```
所有成功项目的共同特征:

✅ 零成本运行 ── GitHub Actions + Pages, Docker 一键部署
✅ AI 评分 ──── LLM 或 ML 模型进行多维内容评分
✅ 多渠道推送 ── 邮件/微信/飞书/钉钉/Web
✅ 中文原生支持 ─ 自动翻译 + 中文摘要
✅ 渐进式个性 ── 从关键词到隐式学习的渐进路径
✅ 模块化架构 ── 每个采集器/处理器独立可测试
```

---

## 🏗️ 推荐方案

### 推荐路径: 渐进式演进

```
Phase 1: MVP · 轻量聚合 + AI 摘要 ── 预估 4-6 周 · $0-2/月
  ├── 8-10 核心数据源 → AI 评分/摘要 → 中文日报 → GitHub Pages
  └── 参考: Horizon + TechSentry

Phase 2: v1.0 · 技术雷达 + 个性化 ── 预估 6-8 周 · $5/月
  ├── Tech Radar 可视化 + 邮件推送 + 用户画像 + 20+ 源
  └── 参考: Sentinel Feed + Signal

Phase 3: v2.0 · 智能学习系统 ── 预估 8-12 周 · $10/月
  ├── 隐式学习 + 技能图谱 + 主动发现
  └── 参考: Signex + Devloop
```

### MVP 核心功能

```
每日 Pipeline (GitHub Actions, 每 6 小时):

  采集     →   去重     →   评分     →   摘要     →   推送
  ─────         ─────         ─────         ─────         ─────
  Hacker News   URL 去重      规则评分      LLM 中文      GitHub Pages
  GitHub Trend  模糊去重      AI 评分       2-3 句        Web 日报
  Reddit        跨源合并      (可选)                      全文存档
  arXiv
  Dev.to
```

### 成本估算 (MVP)

> 估算基于以下假设：每日 4 次运行、每次处理 ~50 篇文章、使用 GPT-4o-mini + Gemini Flash。
> 实际成本会随文章量和 LLM 使用频率线性变化。使用规则评分模式可降至 $0。

| 项目 | 月费 |
|------|------|
| GitHub Actions (托管) | **$0** (免费额度 2000 分钟/月, 预计使用 ~600 分钟) |
| GitHub Pages (托管) | **$0** (免费带宽 100GB/月) |
| LLM API (GPT-4o-mini + Gemini) | **~$1.8** |
| 数据源 API | **$0** (全部免费) |
| **总计** | **~$1.8/月** |

---

## 📚 文档导航

| 文档 | 内容 | 适合谁 |
|------|------|--------|
| **[`OriginGoal.md`](./OriginGoal.md)** | 原始需求 (3 句话) | 所有人 |
| **[`analysis/01-landscape-analysis.md`](./analysis/01-landscape-analysis.md)** | 40+ 项目的全景分析、分类、排名、演进趋势 | 决策者 |
| **[`analysis/02-solution-dimensions.md`](./analysis/02-solution-dimensions.md)** | 7 个维度的方案对比、决策矩阵 | 架构师 |
| **[`analysis/03-architecture-patterns.md`](./analysis/03-architecture-patterns.md)** | 6 种架构模式、数据流图、参考实现 | 开发者 |
| **[`analysis/04-recommendation.md`](./analysis/04-recommendation.md)** | 推荐方案、产品定位、竞品差异 | 产品经理 |
| **[`analysis/05-implementation-plan.md`](./analysis/05-implementation-plan.md)** | 详细 TODO 清单、项目结构、技术选型 | 实施团队 |
| **[`analysis/06-project-review.md`](./analysis/06-project-review.md)** | 项目可行性/Bug/不合理设计审查 | 所有人 |

---

## 🚀 快速开始

> ⚠️ **当前项目处于研究/规划阶段，没有可运行的代码。** 以下是指引你如何参与或启动实施的步骤。

```bash
# 1. 克隆项目
git clone https://github.com/your-org/OhMyInfo.git
cd OhMyInfo

# 2. 从分析文档开始阅读
open analysis/01-landscape-analysis.md    # 了解全景
open analysis/04-recommendation.md        # 了解推荐方案
open analysis/05-implementation-plan.md   # 查看实施计划
```

### 如果你是想直接使用工具

项目尚未实现。建议先试用参考项目的在线实例：
- **Horizon**: `https://github.com/Thysrael/Horizon` — 最接近 OhMyInfo 理念的成熟项目
- **TechSentry**: `https://github.com/qingni/TechSentry` — 中文友好的技术情报工具

### 如果你是想参与开发

- 阅读 [05-implementation-plan.md](./analysis/05-implementation-plan.md) 了解 TODO 清单
- 阅读 [06-project-review.md](./analysis/06-project-review.md) 了解已知问题
- 从 P0 模块开始 (src/collectors/) 贡献代码

### 前置条件 (实施阶段)

- Python 3.11+
- GitHub 账号 (用于 Actions + Pages)
- LLM API Key (可选, 规则模式可无 Key 运行)

---

## 🤝 参与贡献

OhMyInfo 是一个开放的研究项目。我们欢迎各种形式的贡献：

- 💡 **想法与建议**: 开 Issue 讨论
- 🔍 **新增调研**: 发现了新的好项目? 提交 PR 更新分析文档
- 📝 **文档改进**: 优化分析报告的可读性和完整性
- 🚀 **代码贡献**: 按照 05-implementation-plan.md 的 TODO 清单实施

---

## 📄 许可

MIT License — 你可以自由使用、修改、分发本项目的研究成果。

---

> **消除信息差不是工具的问题, 是习惯的问题。OhMyInfo 的目标不是给你更多信息, 而是给你刚好够用、恰好相关的信息。**
