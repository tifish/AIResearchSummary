# Browser MCP migration verification

Executed on 2026-11-14 in `D:\Skills\AIResearchSummary`, using the project
`.venv` (Python 3.14), official `mcp==1.30.0`, Node.js/npm and
`npx --yes @browsermcp/mcp@2.5.0`. The client connected to the existing Browser
MCP daemon 2.5.0 and extension-connected daily browser. No global MCP settings,
legacy profile files, credentials, article data, or generated pages were changed.
No model generation was run. No other repository's modules or fetch entry points
were imported/executed; Theo's migration commit was read as a reference only.

## Offline regression

Command: `.venv\Scripts\python.exe -m unittest discover -s tests -v`

11 tests passed. Coverage includes multiline JS with line comments and literal
backslashes, actual emitted JS executed in Node, Unicode/emoji HTML serialization
over 300,000 characters, chunk and checksum validation, truncated response rejection,
date cutoff before additional clicks, no-growth stop, content stabilization,
normal/exception cleanup and failed-close reporting, command injection rejection,
static HTTP article priority, browser fallback for empty articles, and static
listing fallback when Browser MCP is unavailable.

## Live browser integration

Command: `.venv\Scripts\python.exe tests\verify_browser_live.py`

The script reads tab inventory without logging user tab titles/URLs. It operates
only on its own background tabs, and verifies the active browser tab remains
unchanged during both cases and after cleanup.

| Check | Result |
| --- | --- |
| Real page | `https://www.anthropic.com/research` |
| Parsed articles | 23 before, 46 after one real Load more click |
| Date stop | Initial oldest date 2026-09-23; after click 2026-06-03; callback stopped before a second click (safety limit 2) |
| Full real HTML | 438,219 Python characters; ASCII serialized length 490,711; 123 chunks; FNV-1a checksum 2,221,897,433 verified |
| Long controlled DOM | Own blank tab; delayed Load more appends older date; one click before cutoff (safety limit 100) |
| Unicode integrity | 20,000 repeats of Chinese + emoji + backslash + quote + newline; exact DOM text equality after transfer |
| Fixture transfer | 120,500 HTML characters; serialized length 600,518; 151 chunks; checksum 222,627,988 verified |
| Focus | Active tab IDs unchanged during real page, fixture and after cleanup |
| Cleanup | Both owned tabs absent afterward; both fetch client worker threads exited; one case deliberately raised an exception |
| Existing tabs | Final verification: the 1 preexisting tab remained; earlier verification also preserved all 3 then-existing tabs; no commands operated on them |

A separate `fetch_rendered('https://cursor.com/blog/topic/research')` invocation
also completed successfully, returning 256,729 HTML characters including the
closing `</html>`, then closing its own tab and disconnecting.

Lengths/checksums reflect those particular snapshots; live pages can change.
The transfer freezes a snapshot before chunking, so later DOM mutations do not
mix different versions of HTML. Unchanged snapshots may reuse an already verified
local copy after comparing the serialized length and checksum.

## Scheduled task

Updated only the prompt of `刷新 AIResearchSummary 文章` to explain Browser MCP,
background operation, explicit owned-tab targeting, cleanup and HTTP fallback.
Preserved the original prompt and appended migration-specific instructions.
Schedule stays daily 05:00 Asia/Shanghai; enabled stays true; title, project,
binding, session behavior and all other settings remain unchanged. Next scheduled
run returned by the service: `2026-11-14T21:00:00.000Z` (2026-11-15 05:00 local).
The task was not run for migration testing.

## Limits

- The browser and Browser MCP extension must remain connected; first npx install
  requires network access. Interactive challenges still require user intervention.
- No full refresh/model generation was run. OpenAI's current challenge behavior
  was not separately certified by this test; existing error/fallback rules remain.
- If discovery falls back to static HTTP, only the static first page is available.
- Existing 8-second readiness/Load more waits and the 100-click safety limit remain.
  Very slow sites may reach these bounds before all content appears.
- If the browser disconnects or the process is forcibly terminated, cleanup cannot
  guarantee tab removal. Close failures are reported; no browser/daemon-wide kill
  or cleanup of unrelated tabs is attempted.
- Snapshot checksums detect transfer corruption; FNV-1a is not a security hash.
