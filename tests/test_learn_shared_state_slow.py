"One state for the code, the picture and the numbers: a run moves the demo, a slider rewrites the number in the code. Real browser, real kernel."
import pytest

from tests.test_learn_live_cell_slow import OUT, _out, _run, _type

pytestmark = pytest.mark.slow

async def _shot(pg, name):
    "The code and the demo of the step in one picture: the page is zoomed out so both show."
    await pg.evaluate("() => { const a = document.querySelector('.abh'); a.style.zoom = '.62'; a.parentElement.scrollTop = 0; document.querySelector('.abh .lee-livecell').scrollIntoView(); }")
    for mode in ('light', 'dark'):
        await pg.evaluate(f"applyTheme('leela:{mode}:relaxed')"); await pg.wait_for_timeout(400)
        await pg.screenshot(path=f'{OUT}/b2-{name}-{mode}.png')
    await pg.evaluate("() => { document.querySelector('.abh').style.zoom = ''; applyTheme('leela:light:relaxed'); }")

ST = "() => JSON.parse(JSON.stringify(document.querySelector('.abh [data-rupaka]').rupaka.st))"
CODE = "() => document.querySelector('.abh .lee-livecell .lv-ed .cm-content, .abh .lee-livecell .lv-ta').innerText || document.querySelector('.abh .lv-ta')?.value"


def _env(monkeypatch):
    from abhyasa.learner import temp_learning
    from leela.blocks.learn import host
    from tools.seed_learn_demo import circuits, LOWPASS
    lr = temp_learning(); assert circuits(lr, say=lambda *a: None)
    monkeypatch.setattr(host, 'learn_store', lambda ws, vault=None, write=False: ('test', lr))
    monkeypatch.setattr(host, 'HOSTS', ('127.0.0.1', 'localhost', '::1'))
    return lr, LOWPASS


def test_a_run_moves_the_demo_and_a_slider_rewrites_the_number_in_the_code(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid = _env(monkeypatch)
    async def scenario(pg, ws, port, bad):
        await pg.set_viewport_size(dict(width=1400, height=1500))
        await pg.evaluate("applyTheme('leela:light:relaxed')")
        ws.open_walk('workspace', jid); ws.save(); await pg.evaluate('mountTab()')
        await pg.evaluate('p => leeLearnOpen(p)', f'/w/{jid}/0')
        cell = pg.locator('.abh .lee-livecell.lv-on')
        await cell.wait_for(timeout=30000)
        demo = pg.locator('.abh [data-rupaka]').first
        await demo.wait_for(timeout=30000); await pg.locator('.abh [data-rupaka] .rk-slider').first.wait_for()
        await pg.wait_for_timeout(1500)                                     # the demo is bound to the cell
        # the cell first: a run with V = 9 moves the demo
        await _type(pg, ['V = 9', 'R = 3', 'I = V / R', 'print(I)'])
        await cell.locator('.lv-run').click(); await _out(pg, '3.0')
        await pg.wait_for_function("() => document.querySelector('.abh [data-rupaka]').rupaka.st.V === 9", timeout=10000)
        assert (await pg.evaluate(ST))['R'] == 3
        await _shot(pg, 'shared-run')
        # the picture next: lock in the prediction, then move R to 2
        await pg.locator('.abh [data-rupaka] .opts button').first.click()
        await pg.locator('.abh [data-rupaka] button.go').click()
        await pg.locator('.abh [data-rupaka] .verdict').wait_for(timeout=10000)
        sl = pg.locator('.abh [data-rupaka] .rk-slider input[type=range]').nth(1)
        await sl.evaluate("el => { el.value = 2; el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})) }")
        await pg.wait_for_function("() => /changed R to 2, run to see it/.test(document.querySelector('.abh .lv-state').textContent)", timeout=10000)
        assert 'R = 2' in await pg.evaluate(CODE) and 'V = 9' in await pg.evaluate(CODE)
        assert await pg.evaluate("() => document.querySelector('.abh .lv-out').classList.contains('lv-old')")      # the output is old until a run
        await _shot(pg, 'shared-slider')
        await cell.locator('.lv-run').click(); await _out(pg, '4.5')
        assert not await pg.evaluate("() => document.querySelector('.abh .lv-out').classList.contains('lv-old')")
        assert (await pg.evaluate(ST))['R'] == 2 and 'I' in await cell.locator('.lv-watch').text_content()
        # a name that the code does not set once to a plain number is not touched
        await _type(pg, ['V = 9', 'R = 3', 'R = R + 1', 'I = V / R', 'print(I)'])
        await sl.evaluate("el => { el.value = 5; el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})) }")
        await pg.wait_for_timeout(1200)
        assert 'R = 3' in await pg.evaluate(CODE) and not await pg.evaluate("() => document.querySelector('.abh .lv-out').classList.contains('lv-old')")
        assert not bad, bad
    _run(tmp_path, scenario)


def test_the_four_rungs_move_together_and_the_picture_rung_has_no_second_lock(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid = _env(monkeypatch)
    async def scenario(pg, ws, port, bad):
        await pg.set_viewport_size(dict(width=1400, height=1500))
        await pg.evaluate("applyTheme('leela:light:relaxed')")
        ws.open_learn('workspace', '/c/ohms-law'); ws.save(); await pg.evaluate('mountTab()')
        cell = pg.locator('.abh .ladder-rungs .lee-livecell.lv-on')
        await cell.wait_for(timeout=30000)
        await pg.locator('.abh .ladder-rungs [data-rupaka] .rk-slider').first.wait_for()
        assert await pg.locator('.abh .ladder-rungs [data-rupaka] .rk-gate').count() == 0     # the idea was passed, so no new lock
        assert await pg.locator('.abh .ladder-rungs [data-rupaka] .rk-slider input[type=range]').first.is_enabled()
        await pg.wait_for_timeout(1500)
        await _type(pg, ['V = 4', 'R = 2', 'I = V / R', 'print(I)'])
        await cell.locator('.lv-run').click(); await _out(pg, '2.0')
        await pg.wait_for_function("() => document.querySelector('.abh .ladder-rungs [data-rupaka]').rupaka.st.V === 4", timeout=10000)
        assert 'V' in await pg.locator('.abh .live-numbers').text_content()                   # the numbers rung
        sl = pg.locator('.abh .ladder-rungs [data-rupaka] .rk-slider input[type=range]').first
        await sl.evaluate("el => { el.value = 8; el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})) }")
        await pg.wait_for_function("() => /changed V to 8, run to see it/.test(document.querySelector('.abh .lv-state').textContent)", timeout=10000)
        await pg.evaluate("() => { const a = document.querySelector('.abh'); a.style.zoom = '.6'; document.querySelector('.abh .ladder-rungs').scrollIntoView(); }")
        await pg.screenshot(path=f'{OUT}/b2-ladder-light.png')
        assert not bad, bad
    _run(tmp_path, scenario)


def test_the_rc_filter_draws_the_guess_dashed_and_the_dot_rides_the_curve(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid = _env(monkeypatch)
    async def scenario(pg, ws, port, bad):
        await pg.set_viewport_size(dict(width=1400, height=1100))
        ws.open_learn('workspace', '/c/rc-low-pass-filter'); ws.save(); await pg.evaluate('mountTab()')
        await pg.locator('.abh #show-demo').wait_for(timeout=30000); await pg.locator('.abh #show-demo').click()
        D = '.abh [data-rupaka]'
        await pg.locator(f'{D} path.ln').first.wait_for(state='attached')
        assert await pg.locator(f'{D} path.gs').first.get_attribute('d') is None
        await pg.locator(f'{D} .opts button', has_text='It doubles').click()   # a wrong guess, so the dashed curve parts from the true one
        await pg.locator(f'{D} button.go').click()
        await pg.locator(f'{D} .verdict').wait_for(timeout=10000)
        assert (await pg.locator(f'{D} path.gs').first.get_attribute('d') or '').startswith('M')
        await pg.locator(f'{D} .rk-slider input[type=range]').nth(1).evaluate("el => { el.value = 2; el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})) }")
        dot = pg.locator(f'{D} .rk-point.drag').first
        before = (await pg.evaluate("() => document.querySelector('.abh [data-rupaka]').rupaka.st.lf"))
        await dot.focus(); await pg.keyboard.press('d')
        after = (await pg.evaluate("() => document.querySelector('.abh [data-rupaka]').rupaka.st.lf"))
        assert round(after - before, 6) == 0.1
        await pg.locator(f'{D} svg').first.scroll_into_view_if_needed()
        for mode in ('light', 'dark'):
            await pg.evaluate(f"applyTheme('leela:{mode}:relaxed')"); await pg.wait_for_timeout(400)
            await pg.locator(D).first.screenshot(path=f'{OUT}/b2-guess-{mode}.png')
        assert not bad, bad
    _run(tmp_path, scenario)
