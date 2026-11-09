import pytest

from tests.test_learn_tab_pages_slow import OUT, _env, _learn, _run

pytestmark = pytest.mark.slow

SHOWN = "() => ['left', 'bottom'].map(w => !document.querySelector('#shell').classList.contains('no-' + w))"
CARD = """() => { const h = innerHeight; return ['#send', '#hint', '.abh .check .conf, .abh .check [name=confidence], .abh #check'].map(s => { const e = document.querySelector('.abh ' + s.replace(/^\\.abh /, '')); if (!e) return [s, 'none']; const r = e.getBoundingClientRect(); return [s, r.bottom <= h && r.height > 0] }) }"""


def test_learn_tab_takes_the_room_and_gives_it_back(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        assert await pg.evaluate(SHOWN) == [True, True]
        before = await pg.evaluate("() => [localStorage.getItem('lee-pane-left'), localStorage.getItem('lee-pane-bottom')]")
        await pg.evaluate("applyTheme('leela:light:relaxed')")
        ws.open_walk('workspace', jid); ws.save(); await _learn(pg)
        await pg.locator('.abh #check .check').wait_for(timeout=30000)
        await pg.wait_for_timeout(800)
        assert await pg.evaluate(SHOWN) == [False, False]
        assert await pg.evaluate("() => [localStorage.getItem('lee-pane-left'), localStorage.getItem('lee-pane-bottom')]") == before
        assert await pg.evaluate("() => document.querySelector('.abh').classList.contains('wide')")
        for sel in ('#send', '#hint', '#ans'):
            box = await pg.locator(f'.abh {sel}').first.bounding_box()
            assert box and box['y'] + box['height'] <= 900, (sel, box)
        await pg.screenshot(path=f'{OUT}/p1-step-wide-light.png')
        await pg.evaluate("applyTheme('leela:dark:relaxed')"); await pg.wait_for_timeout(400)
        await pg.screenshot(path=f'{OUT}/p1-step-wide-dark.png')
        await pg.evaluate("applyTheme('leela:light:relaxed')")
        await pg.evaluate("leeLearnOpen('/')"); await pg.locator('.abh main').first.wait_for(); await pg.wait_for_timeout(800)
        await pg.screenshot(path=f'{OUT}/p1-today-wide-light.png')
        await pg.evaluate("applyTheme('leela:dark:relaxed')"); await pg.wait_for_timeout(400)
        await pg.screenshot(path=f'{OUT}/p1-today-wide-dark.png')
        assert await pg.evaluate(SHOWN) == [False, False]
        await pg.reload(wait_until='networkidle'); await pg.wait_for_function('window.lee && lee.keys.length')
        await pg.locator('.abh main').first.wait_for(timeout=30000); await pg.wait_for_timeout(500)
        assert await pg.evaluate(SHOWN) == [False, False]
        await pg.locator('[data-learn-fit]').click()
        assert await pg.evaluate(SHOWN) == [True, True]
        await pg.locator('[data-learn-fit]').click()
        assert await pg.evaluate(SHOWN) == [False, False]
        await pg.locator('.lee-tab', has_text='lesson.py').click(); await pg.wait_for_timeout(800)
        assert await pg.evaluate(SHOWN) == [True, True]
        assert await pg.evaluate("() => [localStorage.getItem('lee-pane-left'), localStorage.getItem('lee-pane-bottom')]") == before
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_a_pane_the_user_hid_stays_hidden_after_the_learn_tab(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        await pg.evaluate("leePane('left', false)")
        ws.open_walk('workspace', jid); ws.save(); await _learn(pg)
        await pg.locator('.abh main').first.wait_for(timeout=30000); await pg.wait_for_timeout(500)
        assert await pg.evaluate(SHOWN) == [False, False]
        await pg.locator('.lee-tab', has_text='lesson.py').click(); await pg.wait_for_timeout(800)
        assert await pg.evaluate(SHOWN) == [False, True]
    _run(tmp_path, scenario, dict(width=1500, height=900))
