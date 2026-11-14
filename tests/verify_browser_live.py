"""Opt-in integration check. Never invoked by unittest discovery or refresh.

Requires the user's connected Browser MCP extension. No model calls or article
data writes. Only this script's two background tabs are operated on and closed.
Tab inventory is read solely to verify cleanup/focus; user URLs are not logged.
"""
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from browser_mcp import BrowserPage, MCPClient
from browser_fetch import _click_load_more, _wait_for_content_ready
from discover_articles import parse_anthropic_articles, parse_date


def inventory(client):
    output = client.call('tab list')
    tabs, active = set(), set()
    for line in output.splitlines():
        match = re.match(r'^[ *]+(\d+)\b', line)
        if match:
            tabs.add(match[1])
            if re.search(r'\([^)]*\bactive\b[^)]*\)$', line):
                active.add(match[1])
    return tabs, active


def dates(markup):
    return [d for a in parse_anthropic_articles(markup) if (d := parse_date(a['date']))]


def main():
    observer = MCPClient(45)
    report = {}
    try:
        initial, initial_active = inventory(observer)
        owned = []
        clients = []
        with BrowserPage() as page:
            owned.append(page.tab)
            clients.append(page.client)
            page.goto('https://www.anthropic.com/research')
            _wait_for_content_ready(page, 45000)
            before = page.content()
            cutoff = min(dates(before))
            stop = lambda h: bool(dates(h)) and min(dates(h)) < cutoff
            clicks = _click_load_more(page, 2, 45000, stop)
            after = page.content()
            assert clicks == 1 and stop(after), 'Real page pagination/date cutoff failed'
            assert len(parse_anthropic_articles(after)) > len(parse_anthropic_articles(before))
            _, active = inventory(observer)
            assert active == initial_active, 'Active browser tab changed during real fetch'
            report['real_page'] = {
                'url': 'https://www.anthropic.com/research',
                'before_articles': len(parse_anthropic_articles(before)),
                'after_articles': len(parse_anthropic_articles(after)),
                'cutoff': str(cutoff), 'oldest_after': str(min(dates(after))),
                'clicks': clicks, 'html_length': len(after), 'transfer': page.transfer_stats,
                'active_tab_unchanged': True,
            }
        assert not clients[-1].thread.is_alive()
        assert owned[-1] not in inventory(observer)[0]

        class ExpectedFailure(Exception):
            pass

        try:
            with BrowserPage() as page:
                owned.append(page.tab)
                clients.append(page.client)
                # Deterministic delayed Load more and long Unicode DOM, wholly
                # inside an owned blank tab, without a fixture web server.
                sample = '正文😀\\"\n'
                page.evaluate(r"""sample => {
                    document.body.innerHTML = '<main><h1>Fixture</h1><pre></pre><a href="#new" data-date="2026-11-01">New</a></main><button>Load more</button>';
                    document.querySelector('pre').textContent=sample.repeat(20000);
                    document.querySelector('button').onclick=()=>setTimeout(()=>{
                        document.querySelector('main').insertAdjacentHTML('beforeend','<a href="#old" data-date="2026-09-30">Old</a>');
                    },250);
                    return true;
                }""", [sample])
                clicks = _click_load_more(page, 100, 10000, lambda h: 'data-date="2026-09-30"' in h)
                markup = page.content()
                assert clicks == 1
                from bs4 import BeautifulSoup
                assert BeautifulSoup(markup, 'html.parser').pre.get_text() == sample * 20000
                assert markup.endswith('</html>')
                _, active = inventory(observer)
                assert active == initial_active, 'Active browser tab changed in fixture'
                report['fixture'] = {'clicks': clicks, 'transfer': page.transfer_stats,
                                     'exact_unicode_text_match': True, 'active_tab_unchanged': True}
                raise ExpectedFailure('verify exception cleanup')
        except ExpectedFailure:
            pass
        final_tabs, final_active = inventory(observer)
        assert not (set(owned) & final_tabs), 'Owned task tab leaked'
        assert all(not c.thread.is_alive() and c.closed for c in clients), 'Client thread leaked'
        assert final_active == initial_active
        report['cleanup'] = {'owned_tabs_closed': len(owned), 'clients_disconnected': len(clients),
                             'exception_cleanup': True, 'active_tab_unchanged': True,
                             'preexisting_tabs_still_present': len(initial & final_tabs),
                             'preexisting_tabs_before': len(initial)}
        print(json.dumps(report, ensure_ascii=True, indent=2))
    finally:
        observer.close()


if __name__ == '__main__':
    main()
