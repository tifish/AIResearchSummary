---
name: economic-futures-summary
description: 维护一个中文静态摘要网页，用于跟踪 Anthropic Economic Futures、OpenAI Research Index 和 Cursor Research 的 AI 研究文章。Use when Codex needs to fetch these sources, detect newly published articles, summarize only new articles in Chinese, update site/articles.json, and render site/index.html with source labels and original article links.
---

# AI 研究摘要

## 概览

使用这个 Skill 维护一个本地中文摘要网页，覆盖 Anthropic、OpenAI 和 Cursor 的 AI 研究文章。生成的网站默认放在工作区根目录的 `site/` 下，是可以直接打开的静态 HTML 文件。

## 工作流程

1. 发现候选文章：

```powershell
python .agents\skills\economic-futures-summary\scripts\discover_articles.py
```

脚本会比较配置来源列表和 `site/articles.json`，只输出 URL 尚未记录的新文章。可以用 `--sources anthropic`、`--sources openai` 或 `--sources cursor` 限制来源。

2. 对每篇新文章抽取正文：

```powershell
python .agents\skills\economic-futures-summary\scripts\extract_article.py "https://www.anthropic.com/research/example"
```

使用脚本返回的来源、来源名称、标题、日期、分类、URL、正文哈希和正文文本。OpenAI 文章页可能拒绝普通脚本请求，因此抽取脚本会对 OpenAI URL 回退使用 RSS 元数据。不要重新总结已经存在于 `site/articles.json` 的文章。

3. 为每篇新文章写入一条中文记录到 `site/articles.json`：

```json
{
  "source": "anthropic",
  "source_name": "Anthropic",
  "url": "https://www.anthropic.com/research/example",
  "title": "Original Anthropic title",
  "date": "Jan 15, 2026",
  "category": "Economic Research",
  "summary_zh": "结论：一句话说明核心结论。关键数据：列出最重要的数字、样本量、benchmark、日期或测量结果。",
  "value_zh": "一句话说明这篇文章为什么值得读。",
  "added_at": "2026-05-13T00:00:00+08:00",
  "source_hash": "sha256..."
}
```

`summary_zh` 和 `value_zh` 要简洁、具体、非宣传化。`summary_zh` 必须包含“结论：”和“关键数据：”；关键数据优先使用原文中的数字、样本量、benchmark 结果、日期、比例或其他可验证测量。优先解释发现、数据集、方法、政策意义或实践影响，不要只是复述标题。

4. 渲染网页：

```powershell
python .agents\skills\economic-futures-summary\scripts\render_site.py
```

直接打开 `site/index.html` 即可，不需要开发服务器。

也可以在工作区根目录快速刷新：

```powershell
.\Refresh.cmd
```

`Refresh.cmd` 是入口包装脚本，会显式调用 Windows PowerShell 5.x 执行 `Refresh.ps1`。`Refresh.ps1` 会先运行发现脚本；如果没有新文章，只重新渲染页面；如果发现新文章，会调用 `codex exec` 使用本 Skill 自动抽取、总结、更新 `site/articles.json` 并重新渲染页面。

## 输出规则

- 除非用户明确要求重写，否则保留已有记录。
- 渲染页面按发布日期倒序排列。
- 原文链接必须使用 `target="_blank"` 和 `rel="noopener noreferrer"`。
- 支持的来源 id 是 `anthropic`、`openai`、`cursor`。
- 页面必须支持按全部来源或单一来源过滤，来源过滤要和搜索框联动。
- 每篇文章开头的来源标识要链接到对应来源主页，“阅读原文”链接要指向单篇文章 URL。
- 当摘要中存在“结论 / 关键数据 / 价值”三段时，渲染页面要分行显示。
- 如果某个来源页面结构变化导致发现不到文章，先检查页面结构，再修改脚本。
- 如果单篇文章无法抓取，跳过该文章，报告原因，并保持已有 `articles.json` 不变。

## 脚本

- `scripts/discover_articles.py`：抓取配置来源的索引页，输出新文章候选 JSON。
- `scripts/extract_article.py`：抓取单篇文章，输出可抽取的元数据和正文 JSON。
- `scripts/render_site.py`：把 `site/articles.json` 渲染为 `site/index.html`。
- `scripts/read_new_count.py`：供兼容脚本从 discovery JSON 中读取 `new_count`。
- `..\..\..\Refresh.ps1`：执行完整刷新流程，并在发现新文章时调用 `codex exec`。
