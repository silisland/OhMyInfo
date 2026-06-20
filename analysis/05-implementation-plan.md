# Plan: OhMyInfo MVP — 个人技术情报系统 Phase 1

> 基于 40+ 开源项目的最佳实践
> 参考项目: Horizon, TechSentry, Signal, Sentinel Feed

---

## 概述

**目标**: 用 2-3 周时间搭建 OhMyInfo MVP，覆盖 8-10 个数据源，AI 自动处理生成中文日报

**技术栈**: Python + GitHub Actions + GitHub Pages + LLM API

**成本**: $0-2/月 (仅 LLM API 费用)

---

## TODOs

### P0: 核心采集系统

- [ ] **src/collectors/__init__.py**: 定义统一采集器接口和基类
  - `Collector` 抽象类: `fetch() → List[Article]`, `name`, `health()`
  - `Article` 数据类: `title`, `url`, `source`, `published_at`, `summary`, `content`, `score`, `category`
  - 错误处理/重试/速率限制基类

- [ ] **src/collectors/hacker_news.py**: Hacker News 采集器
  - 使用 Firebase API: `https://hacker-news.firebaseio.com/v0/`
  - 获取 Top 30 故事, 每个获取详情
  - 无需 API Key

- [ ] **src/collectors/github_trending.py**: GitHub Trending 采集器
  - 解析 `https://github.com/trending` 页面
  - 每日/每周/每月排行榜
  - 提取语言, stars, 描述, README 片段

- [ ] **src/collectors/reddit.py**: Reddit 采集器
  - 使用公共 JSON API
  - 默认源: r/MachineLearning, r/programming, r/AI, r/LocalLLaMA
  - 按分数过滤 (≥ 100 upvotes)

- [ ] **src/collectors/arxiv.py**: arXiv 采集器
  - 使用 arXiv RSS: cs.AI, cs.LG, cs.CL
  - 解析标题, 摘要, 作者, 链接

- [ ] **src/collectors/devto.py**: Dev.to 采集器 (P1)
  - Dev.to API: `https://dev.to/api/articles?top=1&per_page=20`

### P0: 内容处理 Pipeline

- [ ] **src/processors/dedup.py**: 去重模块
  - URL 精确去重 (哈希集合)
  - 模糊标题去重 (TF-IDF 余弦相似度 > 0.85)
  - 跨源合并 (同一文章出现在多个源)

- [ ] **src/processors/classifier.py**: 分类模块
  - 5 个固定分类: `major-release`, `tools-release`, `research-frontier`, `industry-business`, `policy-regulation`
  - 规则分类 (关键词匹配) + LLM 分类 fallback

- [ ] **src/processors/scorer.py**: 评分模块
  - 规则评分 (新鲜度 0-30 + 源权威 0-20 + 互动 0-25 + 新颖 0-15 + 业务影响 0-10)
  - LLM 评分 (可选, 增强模式)
  - 综合评分 0-100

- [ ] **src/processors/summarizer.py**: AI 摘要与翻译
  - LLM 调用生成中文摘要 (2-3 句)
  - 配置化: 支持 OpenAI / Gemini / Claude / DeepSeek
  - 缓存机制: 同一文章不重复摘要

- [ ] **src/processors/pipeline.py**: Pipeline 编排器
  - 串联各步骤: 采集 → 去重 → 分类 → 评分 → 摘要 → 输出
  - 并行执行采集步骤
  - 错误隔离: 单源失败不影响其他源

### P0: 输出与部署

- [ ] **src/output/markdown_generator.py**: 日报 Markdown 生成
  - 按分类渲染日报
  - 热度排序
  - 含评分、标签、原文链接、中文摘要

- [ ] **src/output/site_generator.py**: 静态站点生成
  - 首页: 今日日报 + 趋势速览
  - 分类页: 按分类过滤
  - 详情页: 文章详情 + 跨源关联
  - 主题切换 (暗色/亮色)

- [ ] **.github/workflows/daily-digest.yml**: GitHub Actions 工作流
  - 每 6 小时触发 (cron)
  - 手动触发支持 (workflow_dispatch)
  - 运行 Pipeline → 生成站点 → 部署到 GitHub Pages
  - 失败通知

- [ ] **gh-pages/index.html**: GitHub Pages 静态网站
  - TypeScript + React 前端仪表盘 或 纯 HTML/CSS/JS
  - 响应式设计, 移动端适配
  - 技术雷达 SVG 可视化
  - 搜索与过滤

### P1: 配置系统

- [ ] **config/sources.yaml**: 数据源配置文件
  - 开关控制
  - 频率配置
  - 自定义 RSS 源添加

- [ ] **config/preferences.yaml**: 用户偏好配置
  - 感兴趣的关键词/领域
  - 排除关键词
  - 评分阈值
  - 语言偏好

- [ ] **config/llm.yaml**: LLM 配置
  - 提供商选择 (OpenAI/Gemini/Claude/Ollama)
  - 每个任务的模型映射
  - API Key 管理 (环境变量)

### P1: 监控与运维

- [ ] **src/monitor/health.py**: 源健康监控
  - 每次采集记录源状态
  - 失败告警
  - 健康报告

- [ ] **src/monitor/metrics.py**: 运行指标
  - 采集数量/时间
  - API 调用统计
  - 评分分布

### P2: 增强功能

- [ ] **src/collectors/rss_custom.py**: 自定义 RSS 采集器
  - 允许用户添加任意 RSS/Atom 源
  - OPML 导入支持

- [ ] **src/collectors/product_hunt.py**: Product Hunt 采集器
  - 当日热门产品
  - 需申请 Token

- [ ] **src/notifiers/email_notifier.py**: 邮件推送
  - 日报邮件模板
  - Resend / SMTP 支持

- [ ] **src/notifiers/wechat_notifier.py**: 微信推送
  - 企业微信 Bot
  - Server酱 / PushPlus 支持

---

## 项目结构

```
OhMyInfo/
├── .github/
│   └── workflows/
│       └── daily-digest.yml        # GitHub Actions 定时工作流
├── config/
│   ├── sources.yaml                # 数据源配置
│   ├── preferences.yaml            # 用户偏好
│   └── llm.yaml                    # LLM 模型配置
├── src/
│   ├── collectors/
│   │   ├── __init__.py             # 采集器接口定义
│   │   ├── hacker_news.py          # HN 采集器
│   │   ├── github_trending.py      # GitHub Trending 采集器
│   │   ├── reddit.py               # Reddit 采集器
│   │   ├── arxiv.py                # arXiv 采集器
│   │   ├── devto.py                # Dev.to 采集器
│   │   ├── rss_custom.py           # 自定义 RSS 采集器 (P2)
│   │   └── product_hunt.py         # Product Hunt 采集器 (P2)
│   ├── processors/
│   │   ├── __init__.py
│   │   ├── dedup.py                # 去重模块
│   │   ├── classifier.py           # 分类模块
│   │   ├── scorer.py               # 评分模块
│   │   ├── summarizer.py           # 摘要与翻译
│   │   └── pipeline.py             # Pipeline 编排
│   ├── output/
│   │   ├── markdown_generator.py   # 日报生成
│   │   └── site_generator.py       # 站点生成
│   ├── monitor/
│   │   ├── health.py               # 健康监控
│   │   └── metrics.py              # 指标统计
│   └── notifiers/
│       ├── email_notifier.py       # 邮件 (P2)
│       └── wechat_notifier.py      # 微信 (P2)
├── site/                           # 生成的静态站点
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── data/                           # 数据存档 (git 管理)
│   └── daily/
├── tests/
│   ├── test_collectors.py
│   ├── test_processors.py
│   └── test_output.py
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## 关键设计原则

1. **模块化**: 每个采集器/处理器独立可测试
2. **容错**: 单源失败不影响整体 Pipeline
3. **渐进增强**: 从规则引擎起步, 逐步加入 LLM/ML
4. **零成本运行**: 优先 GitHub Actions + 免费 API
5. **中文优先**: 所有输出默认为中文
6. **配置驱动**: 数据源、偏好、模型均可配置

---

## 技术风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| GitHub Trending 页面结构变化 | 采集失败 | HTML 解析 + API fallback |
| LLM API 费用超预期 | 成本上升 | 规则预过滤 + 本地模型 |
| GitHub Actions 运行时间超限 | 任务取消 | 优化采集效率, 分批处理 |
| 数据膨胀 | GitHub Pages 容量 | 保留最近 90 天数据, 自动清理 |

---

## 验证标准

- [ ] 每日自动采集 8+ 数据源
- [ ] AI 生成中文日报, 分类合理
- [ ] GitHub Pages 自动部署, 可公开访问
- [ ] 整体运行 < 5 分钟/次
- [ ] 日均 LLM 成本 < $0.10
- [ ] 手机端可正常阅读
