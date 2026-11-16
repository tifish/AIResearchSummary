"""Regressions for category labels embedded in OpenAI listing titles."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import discover_articles as discover


class OpenAIScienceTitlesTests(unittest.TestCase):
    def test_science_category_does_not_leak_into_title(self):
        title = "Our new blog for science"
        for suffix in (" - Science -", " - Science - Nov 15, 2026"):
            with self.subTest(suffix=suffix):
                markup = (
                    '<a href="/index/our-new-blog-for-science" '
                    f'aria-label="{title}{suffix}">'
                    '<span>Science</span><time>Nov 15, 2026</time></a>'
                )
                article, = discover.parse_openai_articles(markup)
                self.assertEqual(article["title"], title)
                self.assertEqual(article["category"], "Science")
                self.assertEqual(article["date"], "Nov 15, 2026")


if __name__ == "__main__":
    unittest.main()
