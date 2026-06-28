"""Generate the standalone digest page (总结) for ONE article — for testing.

Runs extract, asks the agent CLI to write a self-contained HTML digest following
prompts/digest.md, and saves it to site/summaries/{slug}.html. Existing pages are
kept unless --force is given.

    python scripts/generate_digest.py --url "https://www.anthropic.com/research/..."
    python scripts/generate_digest.py --url "<URL>" --agent claude --force
    python scripts/generate_digest.py --url "<URL>" --dry-run    # just print the prompt
"""

from __future__ import annotations

import argparse
import sys

from agent_cli import extract_html, load_prompt, run_agent
from extract_article import extract
from render_site import default_site_dir, load_articles, render_page, summary_slug


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def build_prompt(meta: dict) -> str:
    return (
        f"{load_prompt('digest.md')}\n\n## 文章\n"
        f"标题：{meta['title']}\n"
        f"来源：{meta['source_name']}\n"
        f"日期：{meta['date']}\n"
        f"分类：{meta['category']}\n"
        f"URL：{meta['url']}\n\n"
        f"正文：\n{meta['article_text']}\n"
    )


def make_digest(meta: dict, agent: str) -> str:
    """Call the agent to produce the standalone digest HTML for an extracted article."""
    html = extract_html(run_agent(build_prompt(meta), agent))
    if "<html" not in html.lower():
        raise ValueError("agent output did not look like an HTML document")
    return html


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the standalone digest page (总结) for one article.")
    parser.add_argument("--url", required=True, help="Article URL.")
    parser.add_argument("--agent", choices=["codex", "claude"], default="claude",
                        help="Agent CLI to call. Default claude (--print gives clean output for capture).")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing digest page.")
    parser.add_argument("--dry-run", action="store_true", help="Print the assembled prompt and exit; do not call the agent.")
    parser.add_argument("--no-render", action="store_true", help="Do not re-render site/index.html afterward.")
    args = parser.parse_args()

    site = default_site_dir()
    slug = summary_slug(args.url)
    if not slug:
        print(f"generate_digest.py: could not derive a slug from {args.url}", file=sys.stderr)
        return 1
    out_path = site / "summaries" / f"{slug}.html"
    if out_path.exists() and not args.force and not args.dry_run:
        print(f"generate_digest.py: {out_path} already exists. Use --force to overwrite.", file=sys.stderr)
        return 1

    try:
        meta = extract(args.url)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"generate_digest.py: {exc}", file=sys.stderr)
        return 1
    if not meta.get("article_text"):
        print(f"generate_digest.py: no article text extracted for {args.url}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(build_prompt(meta))
        return 0

    try:
        html = make_digest(meta, args.agent)
    except (RuntimeError, ValueError) as exc:
        print(f"generate_digest.py: {exc}", file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path}")
    if not args.no_render:
        (site / "index.html").write_text(render_page(load_articles(site / "articles.json"), site), encoding="utf-8")
        print("Re-rendered site/index.html (阅读总结 link shows once the article is in articles.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
