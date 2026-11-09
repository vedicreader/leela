import pytest

from tests.test_learn_tab_pages_slow import OUT, _env, _run

pytestmark = pytest.mark.slow

PAINTED = "() => { const c = document.querySelector('.abh #graph canvas'); if (!c || !window.abhyasaGraph) return false; const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; for (let i = 3; i < d.length; i += 4) if (d[i]) return true; return false }"


def test_graph_draws_in_the_tab_with_layouts_find_and_theme(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        bad = []
        pg.on('pageerror', lambda e: bad.append(str(e)))
        pg.on('response', lambda r: bad.append((r.status, r.url)) if r.status >= 400 and '/git/file' not in r.url else None)
        await pg.evaluate("applyTheme('leela:light:relaxed')")
        await pg.evaluate("leeLearnOpen('/graph')")
        await pg.wait_for_function(PAINTED, timeout=30000)
        assert ws.tab.page == '/library/graph'
        for mode in ('path', 'rings', 'groups', 'force'):
            await pg.locator(f'.abh #levers input[name=mode][value={mode}]').check(force=True)
            await pg.wait_for_timeout(400)
            assert await pg.evaluate(PAINTED), mode
        await pg.locator('.abh #levers input[name=q]').fill('equal')
        await pg.wait_for_timeout(300)
        assert await pg.locator('.abh #levers ul.found li a').count()
        await pg.locator('.abh #levers input[name=q]').fill('')
        await pg.wait_for_timeout(500)
        await pg.screenshot(path=f'{OUT}/p1-graph-light.png')
        swatch = "() => getComputedStyle(document.querySelectorAll('.abh #levers .legend i')[3]).backgroundColor"
        before = await pg.evaluate(swatch)
        await pg.evaluate("applyTheme('leela:dark:relaxed')")
        await pg.wait_for_timeout(600)
        assert await pg.evaluate(swatch) != before
        assert await pg.evaluate(PAINTED)
        await pg.screenshot(path=f'{OUT}/p1-graph-dark.png')
        await pg.evaluate("leeLearnOpen('/')")
        await pg.locator('.abh main').first.wait_for()
        await pg.evaluate("leeLearnOpen('/graph')")
        await pg.wait_for_function(PAINTED, timeout=30000)
        assert not bad, bad
    _run(tmp_path, scenario)
