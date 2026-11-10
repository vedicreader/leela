import pytest

from tests.test_learn_tab_pages_slow import OUT, _env, _learn, _run

pytestmark = pytest.mark.slow

BTN = '#modebar [data-learn-ideas]'
POP = '.lee-learn-ideas'
STATE = "() => { const r = document.querySelector('.abh #rail'); return {abh: document.querySelector('.abh').clientWidth, rail: r && getComputedStyle(r).display, btn: !document.querySelector('%s').hidden, text: document.querySelector('%s').textContent} }" % (BTN, BTN)


async def _walk(pg, ws, jid):
    ws.open_walk('workspace', jid); ws.save(); await _learn(pg)
    await pg.locator('.abh #check .check').wait_for(timeout=30000)
    await pg.wait_for_load_state('networkidle'); await pg.wait_for_timeout(800)


async def _shots(pg, name):
    for mode in ('light', 'dark'):
        await pg.evaluate(f"applyTheme('leela:{mode}:relaxed')"); await pg.wait_for_timeout(400)
        await pg.screenshot(path=f'{OUT}/ui1-{name}-{mode}.png')
    await pg.evaluate("applyTheme('leela:light:relaxed')")


def test_ideas_button_follows_the_outline_and_its_links_stay_in_the_tab(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        await pg.evaluate("applyTheme('leela:light:relaxed')")
        await _walk(pg, ws, jid)
        for w, shown in ((1500, False), (1100, False), (940, True), (900, True), (720, True)):
            await pg.set_viewport_size(dict(width=w, height=900)); await pg.wait_for_timeout(500)
            st = await pg.evaluate(STATE)
            assert st['btn'] == shown and (st['rail'] == 'none') == shown, (w, st)
            assert (st['abh'] < 940) == shown, (w, st)
            if shown: assert st['text'] == 'Ideas (2)', st
            await _shots(pg, f'walk-{w}')
        await pg.locator(BTN).click()
        pop = pg.locator(POP); await pop.wait_for()
        await pg.wait_for_timeout(300)
        assert await pg.locator(BTN).get_attribute('aria-expanded') == 'true'
        assert await pop.locator('li.c').count() == 2 and await pop.locator('li.c.on').count() == 1
        assert await pop.locator('li.on a').get_attribute('aria-current') == 'step'
        assert await pop.locator('a').nth(0).evaluate('e => document.activeElement === e')
        await _shots(pg, 'popover-720')
        await pg.keyboard.press('ArrowDown')
        assert await pop.locator('a').nth(1).evaluate('e => document.activeElement === e')
        await pg.keyboard.press('Escape'); await pop.wait_for(state='detached')
        assert await pg.locator(BTN).evaluate('e => document.activeElement === e')
        assert await pg.locator(BTN).get_attribute('aria-expanded') == 'false'
        await pg.locator(BTN).click(); await pop.wait_for()
        await pg.mouse.click(5, 450); await pop.wait_for(state='detached')
        seen = []
        pg.on('framenavigated', lambda f: seen.append(f.url) if f == pg.main_frame else None)
        marker = await pg.evaluate("() => (window.__same = Math.random())")
        await pg.locator(BTN).click(); await pop.wait_for()
        want = await pop.locator('li.c:not(.on) a').get_attribute('href')
        await pop.locator('li.c:not(.on) a').click(); await pop.wait_for(state='detached')
        await pg.wait_for_function("() => document.querySelector('.abh #rail li.on#rail-1')", timeout=30000)
        await pg.locator('.abh #check .check').wait_for(timeout=30000)
        assert await pg.evaluate('window.__same') == marker and not seen, seen
        assert await pg.evaluate('lee.learnPage') == want, want
        assert await pg.locator(BTN).is_visible()
        await pg.set_viewport_size(dict(width=1500, height=900)); await pg.wait_for_timeout(500)
        assert not await pg.locator(BTN).is_visible() and await pg.locator('.abh #rail').is_visible()
    _run(tmp_path, scenario, dict(width=1500, height=900))
