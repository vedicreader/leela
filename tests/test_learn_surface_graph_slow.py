import time

import pytest

from tests.test_learn_tab_pages_slow import OUT, _env, _learn, _run

pytestmark = pytest.mark.slow

DAY = 86400.
PAINTED = "() => { const c = document.querySelector('.abh #graph canvas'); if (!c || !window.abhyasaGraph) return false; const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; for (let i = 3; i < d.length; i += 4) if (d[i]) return true; return false }"
STILL = "() => window.abhyasaGraph && !window.abhyasaGraph.moving"
PIX = "() => document.querySelector('.abh #graph canvas').toDataURL()"
MODE = "() => window.abhyasaGraph.mode"
POS = "() => Object.fromEntries(window.abhyasaGraph.vis.map(n => [n.id, [Math.round(n.x), Math.round(n.y)]]))"
BOX = "s => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.top, r.width, r.height] }"
SWATCH = "() => [...document.querySelectorAll('.abh #levers .legend i')].map(i => getComputedStyle(i).backgroundColor)"
AT = "id => { const g = window.abhyasaGraph, n = g.nodes.find(n => n.id === id), r = document.querySelector('.abh #graph canvas').getBoundingClientRect(); return [r.left + g.t.applyX(n.x), r.top + g.t.applyY(n.y)] }"

MATHS = [('Counting', ()), ('Fractions', ('counting',)), ('Equal parts', ('counting',)), ('Adding fractions', ('fractions', 'equal-parts')),
         ('Ratios', ('fractions',)), ('Percentages', ('ratios', 'adding-fractions')), ('Decimals', ('fractions',))]
PHYS = [('Speed', ()), ('Acceleration', ('speed',)), ('Force', ('acceleration',)), ('Energy', ('force',)), ('Momentum', ('force', 'speed'))]


def _seed(lr):
    "Twelve concepts in two subjects with prerequisites, mixed depths, and one review due now."
    now = time.time()
    for subject, rows in (('maths', MATHS), ('physics', PHYS)):
        for name, pre in rows: lr.put(name, f'{name} in one line.', subject, prereqs=list(pre))
    lr.put('Ratios', 'Ratios in one line.', 'maths', slug='ratios', related=['decimals'])
    depth = dict(counting=(5, 9), fractions=(4, 7), ratios=(3, 5), speed=(3, 4), acceleration=(2, 3), force=(1, 2), momentum=(1, 1), energy=(0, 0))
    for slug, (f, seen) in depth.items(): lr.update(slug, floor=f, ceiling=6, seen=seen, last=now - 2 * DAY, due=now + (5 + f) * DAY, stability=5.)
    lr.update('adding-fractions', floor=2, ceiling=6, seen=3, last=now - 9 * DAY, due=now - 3600, stability=2.)
    return lr


async def _open_graph(pg):
    await _learn(pg)
    await pg.evaluate("applyTheme('leela:light:relaxed')")
    await pg.evaluate("leeLearnOpen('/graph')")
    await pg.wait_for_function(PAINTED, timeout=30000)
    await pg.wait_for_function(STILL, timeout=15000)
    await pg.wait_for_timeout(900)


def test_graph_fills_the_tab_in_both_themes_and_widths(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch); _seed(lr)
    async def scenario(pg, ws, port):
        bad = []
        pg.on('pageerror', lambda e: bad.append(str(e)))
        pg.on('response', lambda r: bad.append((r.status, r.url)) if r.status >= 400 and '/git/file' not in r.url else None)
        await _open_graph(pg)
        assert await pg.evaluate("() => document.querySelector('.abh').classList.contains('wide')")
        assert await pg.evaluate("() => window.abhyasaGraph.vis.length") >= 11
        g, c, p = [await pg.evaluate(BOX, s) for s in ('.abh #graph', '.abh #graph canvas', '.abh #levers')]
        assert c[3] >= g[3] - 4 and c[3] > 600, (g, c)
        assert p[0] >= c[0] + c[2] - 2 and abs(p[1] - c[1]) < 20 and p[2] > 200, (c, p)
        assert await pg.evaluate("() => document.querySelector('.abh #graph .grip').getBoundingClientRect().height") > 600
        await pg.screenshot(path=f'{OUT}/f5-graph-light.png')
        await pg.evaluate("applyTheme('leela:dark:relaxed')"); await pg.wait_for_timeout(700)
        assert await pg.evaluate(PAINTED)
        await pg.screenshot(path=f'{OUT}/f5-graph-dark.png')
        await pg.evaluate("applyTheme('leela:light:relaxed')"); await pg.wait_for_timeout(500)
        await pg.set_viewport_size(dict(width=1290, height=900)); await pg.wait_for_timeout(900)
        assert not await pg.evaluate("() => document.querySelector('.abh').classList.contains('wide')")
        g, c, p = [await pg.evaluate(BOX, s) for s in ('.abh #graph', '.abh #graph canvas', '.abh #levers')]
        assert p[1] >= c[1] + c[3] - 2 and c[3] > 300, (c, p)
        await pg.screenshot(path=f'{OUT}/f5-graph-narrow-light.png')
        assert not bad, bad
    _run(tmp_path, scenario, viewport=dict(width=1500, height=900))


async def _still(pg): await pg.wait_for_function(STILL, timeout=15000); await pg.wait_for_timeout(300)


async def _drag(pg, x, y, dx, dy):
    await pg.mouse.move(x, y); await pg.mouse.down()
    for i in range(1, 11): await pg.mouse.move(x + dx * i / 10, y + dy * i / 10)
    await pg.mouse.up()


def test_graph_layouts_keys_find_drag_divider_theme_and_click(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch); _seed(lr)
    async def scenario(pg, ws, port):
        bad = []
        pg.on('pageerror', lambda e: bad.append(str(e)))
        pg.on('response', lambda r: bad.append((r.status, r.url)) if r.status >= 400 and '/git/file' not in r.url else None)
        await _open_graph(pg)
        await pg.evaluate("window.__same = 1")
        seen = {await pg.evaluate(MODE): await pg.evaluate(POS)}
        for mode, name in (('path', 'Path'), ('rings', 'Rings'), ('groups', 'Groups'), ('force', 'Free')):
            await pg.locator('.abh #levers .mode', has_text=name).click(); await _still(pg)
            assert await pg.evaluate(MODE) == mode
            pos = await pg.evaluate(POS)
            if mode != 'force': assert all(pos[k] != seen['force'][k] for k in ('counting', 'speed')), mode
            seen[mode] = pos
        assert len({str(v) for v in seen.values()}) == 4
        for key, mode in (('Digit2', 'path'), ('Digit3', 'rings'), ('Digit4', 'groups'), ('Digit1', 'force')):
            await pg.locator('.abh #graph').focus(); await pg.keyboard.press(key); await _still(pg)
            assert await pg.evaluate(MODE) == mode, key
        await pg.locator('#agentprompt').focus(); await pg.keyboard.press('Digit3'); await pg.wait_for_timeout(700)
        assert await pg.evaluate(MODE) == 'force' and await pg.locator('#agentprompt').input_value() == '3'
        await pg.locator('#agentprompt').fill('')
        await pg.locator('#modebar [data-learn-home]').first.focus(); await pg.keyboard.press('Digit2'); await pg.wait_for_timeout(700)
        assert await pg.evaluate(MODE) == 'force'

        await _still(pg); await pg.wait_for_timeout(600); before = await pg.evaluate(PIX)
        await pg.locator('.abh #levers input[name=q]').fill('adding'); await pg.wait_for_timeout(400)
        assert await pg.locator('.abh #levers ul.found li a').count() == 1
        assert await pg.evaluate(PIX) != before
        await pg.locator('.abh #levers input[name=q]').fill(''); await _still(pg); await pg.wait_for_timeout(400)
        assert await pg.evaluate(PIX) == before and not await pg.locator('.abh #levers ul.found li').count()

        x, y = await pg.evaluate(AT, 'counting')
        await _drag(pg, x, y, -90, -70); await _still(pg)
        x2, y2 = await pg.evaluate(AT, 'counting')
        assert abs(x2 - (x - 90)) < 8 and abs(y2 - (y - 70)) < 8, ((x, y), (x2, y2))
        assert await pg.evaluate("() => location.pathname") == '/' and ws.tab.page == '/library/graph'

        g = await pg.evaluate(BOX, '.abh #levers'); r = await pg.evaluate(BOX, '.abh #graph .grip')
        await _drag(pg, r[0] + r[2] / 2, r[1] + r[3] / 2, -120, 0); await pg.wait_for_timeout(500)
        g2 = await pg.evaluate(BOX, '.abh #levers')
        assert 100 < g2[2] - g[2] < 140, (g, g2)
        assert (await pg.evaluate(BOX, '.abh #graph canvas'))[2] < 800
        await pg.locator('.abh #graph .grip').dblclick(); await pg.wait_for_timeout(500)
        assert abs((await pg.evaluate(BOX, '.abh #levers'))[2] - g[2]) < 4

        sw, px = await pg.evaluate(SWATCH), await pg.evaluate(PIX)
        await pg.evaluate("applyTheme('leela:dark:relaxed')"); await pg.wait_for_timeout(700)
        assert await pg.evaluate(SWATCH) != sw and await pg.evaluate(PIX) != px
        assert await pg.evaluate("window.__same") == 1
        await pg.evaluate("applyTheme('leela:light:relaxed')"); await pg.wait_for_timeout(500)

        x, y = await pg.evaluate(AT, 'adding-fractions')
        await pg.mouse.move(x, y); await pg.mouse.click(x, y)
        for _ in range(60):
            if ws.tab.page.startswith('/c/'): break
            await pg.wait_for_timeout(150)
        assert ws.tab.kind == 'learn' and ws.tab.page == '/c/adding-fractions', ws.tab.page
        await pg.locator('.abh h1', has_text='Adding fractions').wait_for(timeout=15000)
        assert await pg.evaluate("window.__same") == 1
        assert not bad, bad
    _run(tmp_path, scenario, viewport=dict(width=1500, height=900))
