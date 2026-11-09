"""The RC explorable in the real Learn tab: Show me, the gate, the ghost curve and Ask about this."""
import pytest

from tests.test_learn_tab_pages_slow import OUT, _run

pytestmark = pytest.mark.slow

DEMO = '.abh [data-rupaka]'
PATHS = "() => { const q = c => document.querySelector(`.abh [data-rupaka] path.${c}`); return [q('gh')?.getAttribute('d') || '', q('ln')?.getAttribute('d') || ''] }"


def _env(monkeypatch):
    from abhyasa.learner import temp_learning
    from leela.blocks.learn import host
    from tools.seed_learn_demo import circuits
    lr = temp_learning()
    assert circuits(lr, say=lambda *a: None)
    monkeypatch.setattr(host, 'learn_store', lambda ws, vault=None, write=False: ('test', lr))
    monkeypatch.setattr(host, 'HOSTS', ('127.0.0.1', 'localhost', '::1'))
    return lr


def test_rc_demo_shows_a_ghost_after_the_gate_and_asks_the_agent(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    import rupaka
    print(rupaka.__file__)
    lr = _env(monkeypatch)
    async def scenario(pg, ws, port):
        async def shot(name):
            for mode in ('light', 'dark'):
                await pg.evaluate(f"applyTheme('leela:{mode}:relaxed')"); await pg.wait_for_timeout(500)
                await pg.screenshot(path=f'{OUT}/a2-{name}-{mode}.png')
            await pg.evaluate("applyTheme('leela:light:relaxed')")
        ws.open_learn('workspace', '/c/rc-circuit'); ws.save(); await pg.evaluate('mountTab()')
        await pg.locator('.abh #show-demo').wait_for(timeout=30000)
        assert await pg.locator('.abh .rk-err').count() == 0
        await shot('concept')
        await pg.locator('.abh #show-demo').click()
        demo = pg.locator(DEMO).first
        await demo.wait_for(timeout=30000)
        await pg.locator(f'{DEMO} path.ln').first.wait_for(state='attached')
        assert await pg.locator(f'{DEMO} path.gh').count() == 2 and await pg.locator('.abh .rk-err').count() == 0
        gh, ln = await pg.evaluate(PATHS)
        assert gh == '' and ln.startswith('M')
        sl = pg.locator(f'{DEMO} input[type=range]')
        assert await sl.count() == 3 and await sl.nth(2).is_disabled()
        await demo.scroll_into_view_if_needed()
        await shot('demo-before')
        await pg.locator(f'{DEMO} .opts button', has_text='40 ms').click()
        await pg.locator(f'{DEMO} button.go').click()
        await pg.locator(f'{DEMO} .verdict').filter(has_text='That is right.').wait_for(timeout=10000)
        assert await sl.nth(2).is_enabled()
        await shot('gate-answered')
        await sl.nth(2).evaluate("el => { el.value = 4; el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})) }")
        await pg.wait_for_function("() => !!document.querySelector('.abh [data-rupaka] path.gh')?.getAttribute('d')", timeout=10000)
        gh2, ln2 = await pg.evaluate(PATHS)
        assert gh2 == ln and ln2 != ln and gh2.startswith('M')
        await shot('ghost')
        await pg.locator(f'{DEMO} .rk-askopen').click()
        await pg.locator(f'{DEMO} .rk-asker input[type=text]').fill('Why is the ghost curve higher?')
        await pg.locator(f'{DEMO} .rk-asker form button[type=submit]').click()
        await pg.wait_for_function("() => document.querySelector('#agentlog').innerText.includes('About the demo')", timeout=15000)
        said = await pg.evaluate("() => document.querySelector('#agentlog').innerText")
        assert 'Why is the ghost curve higher?' in said and 'C = 4' in said, said
        assert await pg.locator(f'{DEMO} p.rk-note').inner_text() == 'Sent to the tutor.'
        await shot('asked')
    _run(tmp_path, scenario, dict(width=1500, height=1000))
