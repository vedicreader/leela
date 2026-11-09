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


def test_tab_handlers_on_the_editor_belong_to_their_kind(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    from nbformat import v4, write
    lr, jid, slug = _env(tmp_path, monkeypatch)
    nb = tmp_path/'n.ipynb'; write(v4.new_notebook(cells=[v4.new_code_cell('1')]), str(nb))
    txt = tmp_path/'t.txt'; txt.write_text('hello\n')
    async def scenario(pg, ws, port):
        kinds = {}
        await pg.evaluate("""() => { window.hits = []; for (const k of ['notebook', 'file', 'text', 'web', 'learn']) registerTabHandlers(k, {click: () => hits.push(k), submit: () => hits.push(k + ':submit')}); }""")
        async def show(open_):
            open_(); ws.save(); await pg.evaluate('mountTab()'); await pg.wait_for_timeout(600)
            kind = await pg.evaluate('lee.kind'); await pg.evaluate("hits.length = 0; document.getElementById('editor').click()")
            return kind, await pg.evaluate('hits.slice()')
        for _ in range(2):
            for name, open_ in (('notebook', lambda: ws.open(nb)), ('text', lambda: ws.open(txt)), ('web', lambda: ws.open_web(f'http://127.0.0.1:{port}/')), ('learn', lambda: ws.open_walk('workspace', jid))):
                kind, hits = await show(open_)
                kinds[name] = kind
                assert hits == [kind], (name, kind, hits)
        assert kinds['notebook'] == 'notebook' and kinds['learn'] == 'learn' and kinds['web'] == 'web', kinds
    _run(tmp_path, scenario)
