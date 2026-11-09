import pytest

from tools.isolate import isolate

isolate()
pytestmark = pytest.mark.slow

from tests.test_learn_tab_pages_slow import _env, _run


def test_page_report_aborts_nothing_in_tab_or_on_leave(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        failed, sent = [], []
        pg.on('request', lambda r: sent.append(r.url) if 'learn/tab/page' in r.url else None)
        pg.on('requestfailed', lambda r: failed.append((r.method, r.url, r.failure)))
        ws.open_walk('workspace', jid); ws.save(); await pg.evaluate('mountTab()')
        await pg.locator('.abh #check .check').wait_for(timeout=30000)
        await pg.wait_for_load_state('networkidle')
        for path in ('/', '/search?q=fraction', '/'):
            await pg.evaluate(f"leeLearnNav('{path}')"); await pg.wait_for_timeout(800)
        await pg.evaluate("""() => { const f = window.fetch; window.fetch = (u, o) => { const r = f(u, o); if (String(u).includes('/learn/tab/page')) setTimeout(() => location.reload(), 0); return r; }; }""")
        await pg.evaluate("leeLearnNav('/search?q=whole')")
        await pg.wait_for_timeout(2500)
        assert len(sent) >= 4, sent
        assert not [f for f in failed if 'learn/tab/page' in f[1]], failed
    _run(tmp_path, scenario)
