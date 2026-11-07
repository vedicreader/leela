"Every page bundle parses: one stray brace in update.js stopped lee-ide.js, and the whole IDE drew nothing."

import pytest
import asyncio
from pathlib import Path

pytest.importorskip('playwright.async_api')
from playwright.async_api import async_playwright   # noqa: E402
from test_web_slow import _launch   # noqa: E402

STATIC = Path(__file__).parent.parent/'leela'/'static'

async def _parse(srcs):
    async with async_playwright() as pw:
        b = await _launch(pw)
        try:
            pg = await b.new_page()
            return {n: await pg.evaluate("s => { try { new Function(s); return null } catch (e) { return String(e) } }", s) for n, s in srcs.items()}
        finally: await b.close()

def test_every_page_bundle_parses():
    srcs = {p.name: p.read_text() for p in STATIC.glob('lee-*.js')}
    assert {'lee-core.js', 'lee-ide.js', 'lee-agent.js'} <= set(srcs)
    bad = {n: e for n, e in asyncio.run(_parse(srcs)).items() if e}
    assert not bad, bad
