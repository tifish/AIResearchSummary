# AI 研究摘要

[直接查看索引网页](https://tifish.github.io/AIResearchSummary/)

这个仓库包含一组 Python 脚本和一个 Python 刷新入口（`refresh.py`），以及一个已经生成好的静态网页，用来跟踪 Anthropic、OpenAI、Cursor 的 AI 研究更新。刷新流程支持两种 Agent 后端，都复用你已有的登录、不按 token 计费：Codex CLI（`codex exec`），以及 Claude Agent SDK（`claude`，走 Claude Code 订阅，拿结构化结果、错误判断更稳）。

## 依赖

依赖 Playwright（驱动本机已安装的 Google Chrome）、BeautifulSoup 和 certifi。首次运行前安装：

```bat
python -m pip install -r requirements.txt
```

抓取分两步、用 Chrome 的程度不同：

- **发现**（抓列表页）走本地 Chrome 渲染，并自动点击“Load more”翻页，**按文章日期停止**（翻到 2026-01-01 之前即停）；失败时回退静态抓取。
- **抽取正文**优先静态 HTTP，抓不到时（如 OpenAI 反爬）再回退本地 Chrome。
- Chrome 固定**有头**运行、用固定的持久化目录 `.chrome-profile/`（保留 Cloudflare 通行 cookie）；需本机已安装 Google Chrome。

可选环境变量：

- `AIRS_CHROME_CDP`：挂到已运行的 Chrome（先 `chrome --remote-debugging-port=9222`），最能绕过 Cloudflare。

## 摘要网页

打开生成后的网页：

[site/index.html](site/index.html)

网页功能：

- 每篇文章都有中文简介。
- 简介分为“结论 / 关键数据 / 价值”三行显示。
- 每篇文章标注来源。
- 可以按来源过滤，也可以用关键词搜索。
- 顶部支持按年/按月过滤，也可以选择全部年份和全部月份。
- 页面支持亮色/暗色，默认跟随系统。
- 来源标识可跳转到对应来源主页，“阅读原文”可跳转到单篇文章。

## 文章总结

- 摘要页面每篇文章提供独立总结页的链接（“阅读总结”），点击在新标签页打开。
- 完整总结页用 HTML 文件本身保存在 `site/summaries/`。
- 除非明确要求重写，否则不覆盖已存在的 `site/summaries/*.html`。
- 摘要与总结的写作标准在 [`prompts/article.md`](prompts/article.md)，是脚本和刷新流程共用的唯一来源。
- 总结页面也提供返回索引页和打开原文的链接。

## 信息来源

- [Anthropic Research](https://www.anthropic.com/research)
- [OpenAI Research Index](https://openai.com/research/index)
- [Cursor Blog · Research](https://cursor.com/blog/topic/research)

## 刷新

在仓库根目录运行下面任一入口：

```bat
Refresh-Codex.cmd       :: 使用 Codex CLI（codex exec）
Refresh-Claude.cmd      :: 使用 Claude Agent SDK（订阅登录、不按 token 计费，结果更稳）
```

它们都调用 `refresh.py`，也可以直接运行并传参：

```bat
python refresh.py --agent codex
python refresh.py --agent claude       :: 走 Claude Agent SDK；需先 pip install claude-agent-sdk 且已登录 Claude Code
                                       :: 可选：set AIRS_CLAUDE_MODEL=sonnet 指定模型（默认用账号默认模型）
python refresh.py --jobs 20            :: 生成摘要+总结的并发数（默认 12；只受 API 速率限制，瞬时错误自动重试）
python refresh.py --fetch-delay 3      :: 抓取正文之间的间隔秒数（默认 1.5，抓网页是串行的，可拉长）
python refresh.py --discover-only      :: 只做发现，列出文章（步骤一，不生成）
python refresh.py --url <文章URL>      :: 只对单篇生成摘要和总结（步骤二，测试用）
python refresh.py --dry-run            :: 只列出将处理的新文章，不调用 Agent、不写文件
```

`refresh.py` 串联各脚本执行同一套流程：

1. 发现各来源的文章列表（都走本地 Chrome、自动 Load more 翻页），只取 2026-01-01 之后的文章。
2. 如果没有新文章，直接重新生成 `site/index.html`。
3. **抓网页与生成是分开的**：抽取正文是**串行**的，且每篇之间有间隔（`--fetch-delay`，默认 1.5s，对来源站点友好）；生成摘要+总结才**并行**——每篇用一次 Agent 调用同时产出（默认 12 并发，`--jobs` 可调，只受 API 速率限制、瞬时错误自动重试）。结果写入 `site/articles.json` 与 `site/summaries/`，最后重新渲染页面。

确定性的抓取/渲染由脚本完成；只有摘要和总结这类需要判断力的步骤才调用 Codex / Claude 后端（提示词见 `prompts/article.md`）。

## 分步测试

可以把流程的两步分开测试。

**步骤一 · 获取文章列表（发现）**

```bat
python refresh.py --discover-only                  :: 列出各来源发现到的文章（[NEW] 标记未收录的）
python refresh.py --discover-only --sources cursor :: 只看某个来源
python scripts\discover_articles.py --all          :: 看完整的发现 JSON（含 source_errors）
```

**步骤二 · 生成摘要和总结（支持单篇）**

```bat
python refresh.py --url "https://www.anthropic.com/research/<slug>"   :: 对单篇生成摘要+总结
python refresh.py --url "<URL>" --dry-run                             :: 只打印将发送的 prompt（仍会抓取正文）
:: --agent codex/claude 切换 Agent
```

摘要与总结的写作标准在 `prompts/article.md`。

## 数据

文章元数据和中文摘要保存在：

[site/articles.json](site/articles.json)

网页是纯静态文件，不需要启动服务器。发布到 GitHub 后，如果希望直接在线访问，可以启用 GitHub Pages，并将发布目录指向 `site/`。
