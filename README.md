# AI 研究摘要

这个仓库包含一个 Codex 工作区 Skill，以及一个已经生成好的静态网页，用来跟踪 Anthropic、OpenAI 和 Cursor 的 AI 研究更新。

## 摘要网页

打开生成后的网页：

[site/index.html](site/index.html)

网页功能：

- 每篇文章都有中文简介。
- 简介分为“结论 / 关键数据 / 价值”三行显示。
- 每篇文章标注来源：Anthropic、OpenAI、Cursor。
- 可以按来源过滤，也可以用关键词搜索。
- 来源标识可跳转到对应来源主页，“阅读原文”可跳转到单篇文章。

## 信息来源

- [Anthropic Economic Futures](https://www.anthropic.com/economic-futures)
- [OpenAI Research Index](https://openai.com/research/index/)
- [Cursor Research](https://cursor.com/blog/topic/research)

## 刷新

在仓库根目录运行：

```bat
Refresh.cmd
```

这个脚本会执行完整刷新流程：

1. 发现当前三个来源的文章。
2. 如果没有新文章，直接重新生成 `site/index.html`。
3. 如果发现新文章，调用 `codex exec` 和工作区 Skill `$economic-futures-summary`，让 Codex 抽取正文、生成“结论 / 关键数据 / 价值”、更新 `site/articles.json`，并重新生成 `site/index.html`。

`Refresh.cmd` 是入口包装脚本，会显式调用 Windows PowerShell 5.x 执行 `Refresh.ps1`。实际刷新逻辑在 `Refresh.ps1` 中，脚本依赖本机已安装 Python、已安装并登录 Codex CLI，且 `codex exec` 可用。

## 数据

文章元数据和中文摘要保存在：

[site/articles.json](site/articles.json)

网页是纯静态文件，不需要启动服务器。发布到 GitHub 后，如果希望直接在线访问，可以启用 GitHub Pages，并将发布目录指向 `site/`。
