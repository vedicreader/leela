"""Capture the code search dialog: the keyboard model, the weights panel, and the search log.

A real server, the real client JS, and a seeded event log, so the panel is photographed with
numbers in it rather than empty. `rg` answers on this repository, so the results are real.

    python tools/searchshots.py      # writes docs/screenshots/search-*.png
"""

from __future__ import annotations
import asyncio, os, sys, tempfile, threading, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
# Before leela is imported: `leela_cfg` binds at import, and a screenshot run must not write its
# seeded event log into the person's own config dir.
os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp(prefix='leela-shots-'))
os.environ.setdefault('LEELA_SEARCH_VAULT', os.environ['XDG_CONFIG_HOME'] + '/search.db')

from leela.app import ide_app                                             # noqa: E402
from leela.blocks.search.signals import Signals                           # noqa: E402
from leela.workspace import Workspace                                     # noqa: E402
from tools.shots import fake_kernels                                      # noqa: E402

OUT = ROOT/'docs'/'screenshots'
PORT = 5179
CHROME = os.environ.get('LEELA_CHROMIUM')

#: A day of searching, so the panel and the log are photographed with numbers in them.
SEEDED = [('openLocation', 'all', 14, 0, 2), ('def relevance', 'all', 9, 1, 1),
          ('searchSignals', 'rg', 6, 0, 3), ('Weights', 'all', 11, 4, 2),
          ('kosha status', 'context', 5, None, 1), ('mountCodeSurface', 'all', 7, 2, 1)]

def seed():
    "One event log with a day of searching in it, written where the app will read it."
    s, now = Signals(), time.time()
    rows = []
    for i, (q, mode, n, rank, previews) in enumerate(SEEDED):
        qid, at = f'seed:{i}', now - (len(SEEDED) - i) * 420
        rows.append({'kind': 'query', 'query_id': qid, 'q': q, 'mode': mode, 'at': at})
        for leg, ms in (('files', 8), ('rg', 41), ('symbols', 120), ('fts', 260), ('ann', 900)):
            rows.append({'kind': 'leg', 'query_id': qid, 'leg': leg, 'ms': ms, 'n': n//2, 'at': at})
        rows.append({'kind': 'impression', 'query_id': qid, 'n': n, 'ms': 940, 'at': at + 1})
        for p in range(previews):
            rows.append({'kind': 'preview', 'query_id': qid, 'rank': p, 'dwell': 900 + p * 300, 'at': at + 2})
        if rank is None: rows.append({'kind': 'abandon', 'query_id': qid, 'n': n, 'at': at + 6})
        else: rows.append({'kind': 'open', 'query_id': qid, 'rank': rank, 'mode': mode,
                           'path': f'/leela/blocks/search/search.py', 'symbol': q.split()[-1],
                           'sources': ['rg', 'symbols'] if rank < 2 else ['ann'], 'at': at + 5})
    s.record(rows)
    return s

def serve(ws):
    import uvicorn
    srv = uvicorn.Server(uvicorn.Config(ide_app(ws), host='127.0.0.1', port=PORT, log_level='error'))
    threading.Thread(target=srv.run, daemon=True).start()
    return srv

async def shoot():
    OUT.mkdir(parents=True, exist_ok=True)
    fake_kernels()
    print('seeded', len(seed().files()), 'event file(s)')
    ws = Workspace(roots=[], approvals='auto')
    ws.add_root(str(ROOT/'leela'))
    serve(ws)
    await asyncio.sleep(1.5)
    shots = []
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        b = await pw.chromium.launch(**({'executable_path': CHROME} if CHROME else {}),
                                     args=['--no-sandbox'] if os.geteuid() == 0 else [])
        pg = await b.new_page(viewport={'width': 1600, 'height': 950}, device_scale_factor=2)
        await pg.goto(f'http://127.0.0.1:{PORT}/', wait_until='networkidle')
        await pg.wait_for_function('window.lee && lee.keys.length')
        await pg.evaluate("document.querySelectorAll('.lee-modal').forEach(m => m.remove())")
        async def shot(name):
            await pg.wait_for_timeout(400)
            await pg.screenshot(path=str(OUT/f'{name}.png'))
            shots.append(OUT/f'{name}.png')

        await pg.evaluate("async () => { await prefSet('search', 'lastMode', 'rg'); codeSearch(); }")
        await pg.fill('#cs', 'mountCodeSurface')
        await pg.wait_for_selector('.lee-search-result')
        await pg.wait_for_timeout(600)
        await shot('search-results')                    # a result selected, its preview beside it

        await pg.keyboard.press('ArrowDown')
        await pg.keyboard.press('ArrowDown')
        await shot('search-arrows')                     # the arrows move the selection, not the focus

        await pg.keyboard.press('Tab')
        await pg.wait_for_timeout(900)
        await shot('search-tab-mode')                   # tab switched the mode and marked the rail

        await pg.keyboard.press('Shift+Tab')            # back to a mode with matches in it
        await pg.wait_for_selector('.lee-search-result')
        await pg.keyboard.press('Enter')                # enter steps into the results
        await pg.wait_for_timeout(300)
        await pg.click('#cstune')
        await pg.wait_for_selector('.lee-weight')
        await shot('search-weights')                    # every weight `all` pays

        await pg.evaluate("() => { const el = $('[data-weight=\"legAnn\"]'); el.value = 300; el.dispatchEvent(new Event('input')); }")
        await pg.wait_for_timeout(400)
        await shot('search-weights-tuned')              # the same results, re-ranked as it is dragged

        await pg.click('#cslog')
        await pg.wait_for_selector('.lee-search-log')
        await shot('search-log')                        # what was searched, shown, previewed, opened
        await b.close()
    for p in shots: print(p)
    return shots

if __name__ == '__main__': asyncio.run(shoot())
