# AI 研究摘要

这个仓库包含一组 Python 脚本和一个 Python 刷新入口（`refresh.py`），以及一个已经生成好的静态网页，用来跟踪 Anthropic、OpenAI、Cursor 的 AI 研究更新。刷新流程支持 Codex CLI 和 Claude Code CLI 两种 Agent。

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

- 摘要页面每篇文章提供独立总结页的链接（“阅读总结”），点击在新标签页打开。
- 完整总结页用 HTML 文件本身保存在 `site/summaries/`。
- 除非明确要求重写，否则不覆盖已存在的 `site/summaries/*.html`。
- 摘要与总结的写作标准分别在 [`prompts/summary.md`](prompts/summary.md)、[`prompts/digest.md`](prompts/digest.md)，是脚本和刷新流程共用的唯一来源。

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

它们都调用 `refresh.py`，也可以直接运行并传参：

```bat
python refresh.py --agent codex
python refresh.py --agent claude
python refresh.py --summary-only      :: 只生成摘要，跳过独立总结页
python refresh.py --dry-run           :: 只列出将处理的新文章，不调用 Agent、不写文件
```

`refresh.py` 串联各脚本执行同一套流程：

1. 抓取各来源页面（OpenAI 走本地 Chrome），只发现 2026-01-01 之后的文章。
2. 如果没有新文章，直接重新生成 `site/index.html`。
3. 如果发现新文章，对每篇抽取正文、生成中文摘要并写入 `site/articles.json`；默认再生成独立总结页（已存在则跳过），最后重新渲染页面。

确定性的抓取/渲染由脚本完成；只有摘要和总结这类需要判断力的步骤才调用 Codex/Claude CLI（提示词见 `prompts/`）。

## 单篇生成（方便测试）

不想跑整套刷新、只想对单篇文章迭代摘要或总结时，可以用下面两个脚本（默认走 `claude --print`，输出干净便于捕获，可 `--agent codex`；`--dry-run` 仍会抓取正文以拼出真实 prompt，但不调用 Agent、不写文件；`--no-render` 跳过重新渲染 `index.html`）：

```bat
:: 只生成索引摘要（摘要），写入 site/articles.json
python scripts\generate_summary.py --url "https://www.anthropic.com/research/<slug>"

:: 为指定文章生成独立总结页（总结）到 site/summaries/，已存在则需 --force
python scripts\generate_digest.py --url "https://www.anthropic.com/research/<slug>"
```

摘要与总结的写作标准分别在 `prompts/summary.md`、`prompts/digest.md`。

## 数据

文章元数据和中文摘要保存在：

[site/articles.json](site/articles.json)

网页是纯静态文件，不需要启动服务器。发布到 GitHub 后，如果希望直接在线访问，可以启用 GitHub Pages，并将发布目录指向 `site/`。
