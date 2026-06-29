"""Apply parallel-generated results to the site.

Reads the manifest (from prepare_batch.py) and a results JSON
(list of {"url", "summary_zh", "value_zh", "html"} produced by the Workflow):
upserts summaries into articles.json, writes each digest page (with nav injected),
and re-renders index.html.

    python scripts/apply_batch.py --manifest <manifest.json> --results <results.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent_cli import extract_html
from generate import upsert_summary
from render_site import default_site_dir, load_articles, prepare_digest_html, render_page


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply parallel-generated summaries/digests to the site.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--results", required=True)
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    raw = json.loads(Path(args.results).read_text(encoding="utf-8"))
    results = {r["url"]: r for r in raw if r and r.get("url")}
    state = Path(manifest["state_path"])
    site = Path(manifest["site_dir"])

    summaries = digests = skipped = 0
    for item in manifest["items"]:
        res = results.get(item["url"])
        if not res or not str(res.get("summary_zh", "")).strip():
            print(f"  no result for {item['url']} (skip)")
            skipped += 1
            continue
        record = json.loads(Path(item["input"]).read_text(encoding="utf-8"))
        upsert_summary(state, record, str(res["summary_zh"]).strip(), str(res.get("value_zh", "")).strip())
        summaries += 1
        html = str(res.get("html", ""))
        if "<html" in html.lower():
            html = prepare_digest_html(extract_html(html), item["url"])
            out = Path(item["out_file"])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(html, encoding="utf-8")
            digests += 1

    site_dir = default_site_dir()
    (site_dir / "index.html").write_text(render_page(load_articles(site_dir / "articles.json"), site_dir), encoding="utf-8")
    print(f"Applied {summaries} summaries, {digests} digest pages ({skipped} skipped); re-rendered index.html.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
