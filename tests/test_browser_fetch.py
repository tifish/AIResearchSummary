"""Offline regressions: no browser, network, model calls, or production data."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import browser_fetch as fetch
import browser_mcp as browser
import discover_articles as discover
import extract_article as extract


class TransferTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js required')
    def test_multiline_eval_round_trip_and_full_unicode_html(self):
        # Run the emitted eval argument as JS, including multiline comments,
        # literal backslashes, quotes, Unicode, and an astral character.
        markup = '<!DOCTYPE html>\n<html><main>' + ('正文😀\\"\n' * 15000) + '</main></html>'
        function = """(value) => {
            // Removing newlines naively would comment out the next statement.
            return {value, slash:/\\s+/.test(' '), literal:'\\\\n'};
        }"""
        command = browser.eval_command(function, [markup])
        self.assertEqual(len(command.splitlines()), 1)
        script = r"""
const input=JSON.parse(require('fs').readFileSync(0,'utf8'));
global.window=global;
global.document={doctype:null,documentElement:{outerHTML:input.markup}};
(async()=>{
 const result=await eval('('+input.command.slice(6,-1)+')')();
 const status=(eval('('+input.freeze+')'))('frozen');
 console.log(JSON.stringify({result,status,body:window.frozen}));
})();
"""
        output = subprocess.run(['node', '-e', script], input=json.dumps({
            'markup': markup, 'command': command, 'freeze': browser._FREEZE_HTML}),
            capture_output=True, text=True, encoding='utf-8', check=True)
        captured = json.loads(output.stdout)
        self.assertEqual(captured['result']['airsResult'], {'value': markup, 'slash': True, 'literal': '\\n'})
        self.assertTrue(captured['body'].isascii())
        self.assertGreater(captured['status']['length'], 300000)
        p = browser.BrowserPage()
        def evaluate(fn, args):
            if fn == browser._FREEZE_HTML:
                return captured['status']
            if 'slice' in fn:
                return captured['body'][args[1]:args[1]+args[2]]
            return True
        p.evaluate = Mock(side_effect=evaluate)
        self.assertEqual(p.content(), markup)
        self.assertGreater(p.transfer_stats['chunks'], 75)
        captured['status']['hash'] ^= 1
        p._html_cache = None
        with self.assertRaisesRegex(RuntimeError, 'integrity'):
            p.content()

    def test_truncated_json_and_short_chunk_fail(self):
        p = browser.BrowserPage()
        p.command = Mock(return_value='✓ select\n{"airsResult":"truncated')
        with self.assertRaisesRegex(RuntimeError, 'truncated'):
            p.evaluate('() => true')
        p.evaluate = Mock(side_effect=[{'length': 20, 'hash': 0}, 'short', True])
        with self.assertRaisesRegex(RuntimeError, 'Incomplete'):
            p.content()
        self.assertIn('delete window', p.evaluate.call_args[0][0])


class LifecycleTests(unittest.TestCase):
    def test_cleanup_success_and_exception_only_owned_tab(self):
        for failure in (False, True):
            client = Mock()
            client.call.return_value = '✓ tab new about:blank — tab 101'
            with patch.object(browser, 'MCPClient', return_value=client):
                try:
                    with browser.BrowserPage() as p:
                        p.command('get title')
                        if failure:
                            raise ValueError('test')
                except ValueError:
                    pass
            self.assertEqual([c.args[0] for c in client.call.call_args_list], [
                'tab new about:blank', 'tab select 101\nget title', 'tab close 101'])
            client.close.assert_called_once()
            self.assertNotIn(p, browser._PAGES)

    def test_close_failure_is_reported_and_disconnects(self):
        p = browser.BrowserPage()
        p.tab = '101'
        p.client = client = Mock()
        client.call.side_effect = RuntimeError('unavailable')
        with self.assertRaisesRegex(RuntimeError, '101'):
            p.close()
        self.assertEqual(client.call.call_count, 2)
        client.close.assert_called_once()

    def test_url_cannot_inject_command(self):
        p = browser.BrowserPage()
        for url in ('https://example.com\ntab close 7', 'https://example.com/"'):
            with self.assertRaises(ValueError):
                p.goto(url)


class PaginationTests(unittest.TestCase):
    def test_date_stop_is_primary_and_does_not_click_again(self):
        page = Mock()
        page.content.side_effect = ['2026-11-01', '2026-11-01', '2026-09-30']
        target = Mock()
        with patch.object(fetch, '_wait_for_load_more_target', return_value=target), \
             patch.object(fetch, '_wait_for_load_more_update', return_value=True):
            clicks = fetch._click_load_more(page, 100, 1000, lambda h: h < '2026-10-01')
        self.assertEqual(clicks, 1)
        target.click.assert_called_once()

    def test_no_growth_stops_and_initial_cutoff_never_clicks(self):
        page = Mock()
        page.content.return_value = 'same'
        target = Mock()
        with patch.object(fetch, '_wait_for_load_more_target', return_value=target), \
             patch.object(fetch, '_wait_for_load_more_update', return_value=False):
            self.assertEqual(fetch._click_load_more(page, 100, 1000), 1)
            self.assertEqual(fetch._click_load_more(page, 100, 1000, lambda _: True), 0)
        target.click.assert_called_once()

    def test_stable_content_waits_after_changes(self):
        page = Mock()
        page.evaluate.side_effect = [dict(textLength=n, hasArticle=True) for n in (310, 700, 700, 700)]
        with patch.object(fetch.time, 'monotonic', side_effect=[0, 0, .1, .2, .3, .4, .5, .6, .7, 1.3]):
            fetch._wait_for_content_ready(page, 8000)
        self.assertGreaterEqual(page.evaluate.call_count, 3)


class CallerTests(unittest.TestCase):
    def test_static_article_success_does_not_open_browser(self):
        result = {'article_text': 'readable'}
        with patch.object(extract, 'fetch_text', return_value='html'), \
             patch.object(extract, 'extract_from_markup', return_value=result), \
             patch.object(fetch, 'fetch_rendered') as render:
            self.assertEqual(extract.extract('https://example.com/article'), result)
            render.assert_not_called()

    def test_empty_static_article_falls_back_and_keeps_extraction(self):
        with patch.object(extract, 'fetch_text', return_value='empty'), \
             patch.object(extract, 'extract_from_markup', side_effect=[{'article_text': ''}, {'article_text': 'full'}]), \
             patch.object(fetch, 'fetch_rendered', return_value='rendered') as render:
            self.assertEqual(extract.extract('https://example.com/article')['article_text'], 'full')
            render.assert_called_once_with('https://example.com/article')

    def test_discovery_render_failure_keeps_static_fallback(self):
        with patch.object(fetch, 'fetch_rendered', side_effect=RuntimeError('offline')), \
             patch.object(discover, '_fetch_static', return_value='static') as static:
            self.assertEqual(discover.fetch_listing_html('anthropic'), 'static')
            static.assert_called_once()


if __name__ == '__main__':
    unittest.main()
