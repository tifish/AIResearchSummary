# AI 研究摘要

这个仓库包含一组脚本和一份刷新说明（`refresh-prompt.md`），以及一个已经生成好的静态网页，用来跟踪 Anthropic、OpenAI、Cursor 的 AI 研究更新。刷新流程支持 Codex CLI 和 Claude Code CLI 两种 Agent。

## 依赖

Anthropic、Cursor 用静态 HTTP 抓取 + BeautifulSoup 解析；OpenAI 有反爬/JS 渲染，改用本地 Chrome 渲染抓取（Playwright 驱动本机已安装的 Google Chrome）。首次运行前安装依赖：

```bat
python -m pip install -r requirements.txt
```

OpenAI 走本地 Chrome，需要本机已安装 Google Chrome。可选环境变量：

- `AIRS_CHROME_CDP`：挂到已运行的 Chrome（先 `chrome --remote-debugging-port=9222`），最能绕过 Cloudflare。
- `AIRS_CHROME_HEADLESS=1`：无头模式（默认有头，便于通过人机校验）。
- `AIRS_CHROME_PROFILE`：自定义 Chrome 用户数据目录（默认 `.chrome-profile/`，会保留 Cloudflare 通行 cookie）。

## 摘要网页

打开生成后的网页：

[site/index.html](site/index.html)

网页功能：

- 每篇文章都有中文简介。
- 简介分为“结论 / 关键数据 / 价值”三行显示。
- 每篇文章标注来源。
- 可以按来源过滤，也可以用关键词搜索。
- 来源标识可跳转到对应来源主页，“阅读原文”可跳转到单篇文章。

## 文章总结

- 摘要页面每篇文章提供总结页面的链接，点击打开新的 tab 页面。
- 完整总结页用 HTML 文件本身保存。
- 除非用户明确要求重写，否则不要覆盖已经存在的 `site/summaries/*.html`。
- 独立总结页的内容质量标准：

  - 开头必须有“一句话总括”，说明文章真正的贡献，而不是复述标题。
  - 每个关键数据和结论尽量用一两句话讲清楚，并解释它为什么改变读者对 AI 影响的理解。
  - 每个小段的标题是总结，中间是关键数据和趋势，最后一句话给出结论和洞见。
  - 结尾用 3-5 条“最值得带走的洞见”综合全文。

## 信息来源

- [Anthropic Research](https://www.anthropic.com/research)
- [OpenAI Research Index](https://openai.com/research/index)
- [Blog · Cursor](https://cursor.com/blog/topic/research)

## 刷新

在仓库根目录运行下面任一入口：

```bat
Refresh-Codex.cmd      :: 使用 Codex CLI（codex exec）
Refresh-Claude.cmd     :: 使用 Claude Code CLI（claude --print）
```

也可以显式向 `Refresh.ps1` 传 Agent 名：

```powershell
.\Refresh.ps1 -Agent codex
.\Refresh.ps1 -Agent claude
```

这些脚本都执行同一套完整刷新流程：

1. 使用静态 HTTP 抓取两个来源的页面，只发现 2026-01-01 之后的文章。
2. 如果没有新文章，直接重新生成 `site/index.html`。
3. 如果发现新文章，更新摘要页面，并生成文章总结，已有总结页面不需要重复生成。

主要的功能在脚本代码中实现，只有必须用到 AI 的功能，例如生成文章摘要和总结，才调用 Codex/Claude Code。

## 数据

文章元数据和中文摘要保存在：

[site/articles.json](site/articles.json)

网页是纯静态文件，不需要启动服务器。发布到 GitHub 后，如果希望直接在线访问，可以启用 GitHub Pages，并将发布目录指向 `site/`。
