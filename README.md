# AI 研究摘要

[直接查看索引网页](https://tifish.github.io/AIResearchSummary/)

这个仓库包含一组 Python 脚本和一个 Python 刷新入口（`refresh.py`），以及一个已经生成好的静态网页，用来跟踪 Anthropic、OpenAI、Cursor 的 AI 研究更新。刷新流程直接以 headless 方式调用本机 Antigravity CLI（`agy`，不依赖 SDK 包），复用你已有的本机登录，默认使用 **Gemini 4 Neon (High)**（`gemini-4-neon-high`）生成摘要、总结与译文。

## 依赖

依赖 Python 官方 MCP SDK（固定 `mcp==1.30.0`）、BeautifulSoup 和 certifi，以及 PATH 中可用的 Node.js/npm（`npx`）。首次运行前安装：

```bat
python -m pip install -r requirements.txt
```

在日常已登录的 Chrome 中安装并连接 **Browser MCP 扩展**，保持浏览器和扩展连接可用。脚本直接启动自己的 `npx --yes @browsermcp/mcp@2.5.0` stdio 客户端，不修改全局 MCP 配置；首次使用 npx 需要联网下载该固定版本。

抓取分两步：

- **发现**（抓列表页）走 Browser MCP 渲染，并自动点击“Load more”翻页，按来源现有最新文章的月份停止（翻到该月份之前即停；最早只追溯到 2026-01）；失败时回退静态抓取。
- **抽取正文**优先静态 HTTP，抓不到时（如 OpenAI 反爬）再回退 Browser MCP。普通公开页面的 HTTP 抓取不受影响。
- 每次浏览器抓取创建独立客户端和后台任务标签页，复用扩展所连浏览器的登录状态；每条页面命令显式指定任务标签页，不切换用户当前标签页或抢前台焦点。正常结束或异常时只关闭自己创建的标签页，然后断开自己的客户端；不关闭用户浏览器、其他任务标签页或共享 daemon。
- 完整 HTML 在页面中冻结为快照，按 4,000 字符分块传回，校验每块长度、总长度和校验和后解码；支持反斜杠、多行、中文和 emoji，避免 MCP 单次响应截断导致正文缺失。

无需 Playwright 安装、旧扩展 token 或远程调试端口。旧的 `AIRS_CHROME_CDP` / `AIRS_CHROME_CHANNEL` 已不再使用；历史 `.chrome-profile/` 数据保留，但脚本不再访问它。扩展断开或页面要求人工验证时，浏览器抓取可能失败；发现流程仍可回退静态首屏，但该回退不保证覆盖完整分页。

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

## 文章总结与译文

- 摘要页面每篇文章提供独立页面的链接，点击在新标签页打开。包含译文的页面显示“总结与译文”；旧页面在重生成前仍显示“阅读总结”。
- 独立页面先给出不含原文图片的精炼中文总结，再按原文结构提供完整中文译文；原文题图、图表和表格截图只放在译文区块，并按原始位置保留。原文为同一图提供亮色/暗色资源时，页面只保留一个图位并随站点主题切换对应版本。HTML 文件保存在 `site/summaries/`。
- 除非明确要求重写，否则不覆盖已存在的 `site/summaries/*.html`。
- 摘要、总结与译文的写作标准在 [`prompts/article.md`](prompts/article.md)，是脚本和刷新流程共用的唯一来源。
- 独立页面也提供返回索引页和打开原文的链接。

## 信息来源

- [Anthropic Research](https://www.anthropic.com/research)
- [OpenAI Research Index](https://openai.com/research/index)
- [Cursor Blog · Research](https://cursor.com/blog/topic/research)

## 刷新

统一使用 Antigravity CLI（`agy`）的 **Gemini 4 Neon (High)**（`gemini-4-neon-high`）生成文章；首次使用前请先运行一次交互式 `agy` 完成登录。

在仓库根目录运行刷新入口：

```bat
Refresh.cmd                            :: 使用本机 Antigravity CLI（默认 gemini-4-neon-high）
```

也可以直接运行 `refresh.py` 并传参：

```bat
python refresh.py                      :: 默认使用 Antigravity 的 gemini-4-neon-high
                                       :: 可选：set AIRS_AGY_MODEL=... 覆盖模型 slug（默认 gemini-4-neon-high）
                                       :: 可选：set AIRS_AGY_BIN=... 指定 agy 可执行文件；默认用 PATH 中的 agy
                                       :: 可选：set AIRS_AGY_TIMEOUT=... 单篇生成超时秒数（默认 600）
python refresh.py --jobs 20            :: 生成摘要+总结与译文的并发数（默认 12；每抓到一篇就入队生成）
python refresh.py --fetch-delay 3      :: 抓取正文之间的间隔秒数（默认 1.5，抓网页是串行的，可拉长）
python refresh.py --discover-only      :: 只做发现，列出文章（步骤一，不生成）
python refresh.py --url <文章URL>      :: 只对单篇生成摘要、总结和译文（步骤二，测试用）
python refresh.py --missing-digests    :: 只补缺失的独立总结与译文页；默认刷新也会自动补
python refresh.py --dry-run            :: 只列出将处理的新文章，不调用 Agent、不写文件
```

`refresh.py` 串联各脚本执行同一套流程：

1. 发现各来源的文章列表（都走 Browser MCP、自动 Load more 翻页；按来源现有最新月份控制翻页深度），只取 2026-01-01 之后的文章。
2. 检查 `site/articles.json` 中已收录文章的独立总结与译文页；如果 `site/summaries/<slug>.html` 不存在，默认刷新会重新抓正文并一次性重生成索引摘要和独立页面，不需要额外参数。
3. 如果没有新文章、也没有缺失的独立页面，直接重新生成 `site/index.html`。
4. **抓网页与生成是流水线执行的**：抽取正文仍然是**串行**的，且每篇之间有间隔（`--fetch-delay`，默认 1.5s，对来源站点友好）；但每抽取成功一篇，就立即加入生成队列。生成摘要+总结与译文是**并行**的——每篇用一次 Agent 调用同时产出（默认 12 并发，`--jobs` 可调，只受服务速率限制、瞬时错误自动重试）。每篇生成完成后会立即写入 `site/articles.json` 与 `site/summaries/`，全部结束后重新渲染页面。

确定性的抓取/渲染由脚本完成；只有摘要、总结和译文这类需要判断力的步骤才调用 Antigravity CLI（提示词见 `prompts/article.md`）。

## 分步测试

离线回归（不联网、不打开浏览器、不调用模型、不写正式数据）：

```bat
python -m unittest discover -s tests -v
```

可选真实浏览器验证（连接扩展后手动运行，只读取真实研究列表、在自己的空白标签页构造分页夹具，不调用模型、不写正式文章数据）：

```bat
python tests\verify_browser_live.py
```

该验证检查真实 Anthropic Load more / 日期截止、长 HTML 完整性、异常清理、客户端断开及任务标签页消失。详细迁移验收记录见 [tests/browser_migration_validation.md](tests/browser_migration_validation.md)。

可以把流程的两步分开测试。

**步骤一 · 获取文章列表（发现）**

```bat
python refresh.py --discover-only                  :: 列出各来源发现到的文章（[NEW] 标记未收录的）
python refresh.py --discover-only --sources cursor :: 只看某个来源
python scripts\discover_articles.py --all          :: 看完整的发现 JSON（含 source_errors）
```

**步骤二 · 生成摘要、总结和译文（支持单篇）**

```bat
python refresh.py --url "https://www.anthropic.com/research/<slug>"   :: 对单篇生成摘要+总结与译文
python refresh.py --url "<URL>" --dry-run                             :: 只打印将发送的 prompt（仍会抓取正文）
```

摘要、总结与译文的写作标准在 `prompts/article.md`。

## 数据

文章元数据和中文摘要保存在：

[site/articles.json](site/articles.json)

网页是纯静态文件，不需要启动服务器。发布到 GitHub 后，如果希望直接在线访问，可以启用 GitHub Pages，并将发布目录指向 `site/`。
