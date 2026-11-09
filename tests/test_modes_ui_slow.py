import pytest

from tools.isolate import isolate

isolate()
pytestmark = pytest.mark.slow

from tests.test_learn_tab_pages_slow import OUT, _env, _run

DOCKS = "() => { const s = document.querySelector('#shell'), on = c => !s.classList.contains(c), vis = q => { const e = document.querySelector(q); return !!e && getComputedStyle(e).display !== 'none' }; return {files: on('no-left'), exec: on('no-bottom'), left_handle: vis('.restore-left'), bottom_handle: vis('.restore-bottom'), mode: s.dataset.mode, bar: vis('#modebar'), tab: document.querySelector('.lee-tab.active')?.title || ''} }"
BAR = """() => { const bar = document.querySelector('#modebar'), r = [...bar.children].filter(e => e.offsetParent).map(e => e.getBoundingClientRect()), b = bar.getBoundingClientRect();
  return {h: b.height, rows: Math.max(...r.map(x => x.top)) < Math.min(...r.map(x => x.bottom)), inside: r.every(x => x.right <= b.right + 1 && x.left >= b.left - 1), more: [...bar.children].some(e => e.matches('[data-learn-more]') && e.offsetParent), lib: [...bar.querySelectorAll('.lee-learn-nav button')].some(e => e.textContent === 'Library' && e.offsetParent)} }"""
SWITCH = "m => document.querySelector(`#modeswitch [data-mode=${m}]`).click()"


async def _learn(pg):
    await pg.evaluate(SWITCH, 'learn')
    await pg.locator('.abh main').first.wait_for(timeout=30000); await pg.wait_for_timeout(800)


def test_the_switch_applies_each_modes_own_layout_and_the_tab(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        bad = []; pg.on('pageerror', lambda e: bad.append(str(e)))
        assert await pg.locator('#modeswitch [data-mode]').all_inner_texts() == ['Code', 'Learn']
        await pg.evaluate("leePane('bottom', false)")
        code = await pg.evaluate(DOCKS)
        assert code['mode'] == 'code' and code['files'] and not code['exec'] and not code['bar'], code
        for mode in ('light', 'dark'):
            await pg.evaluate(f"applyTheme('leela:{mode}:relaxed')"); await pg.wait_for_timeout(300)
            await pg.screenshot(path=f'{OUT}/m2-code-{mode}.png')
        ws.open_walk('workspace', jid, 1); ws.save(); await pg.evaluate('mountTab()')
        await pg.evaluate(SWITCH, 'code'); await pg.wait_for_timeout(800)
        await pg.evaluate("leePane('bottom', false)")
        await pg.locator('#modeswitch [data-mode=learn]').click()
        await pg.locator('.abh #check .check').wait_for(timeout=30000); await pg.wait_for_timeout(800)
        learn = await pg.evaluate(DOCKS)
        assert learn['mode'] == 'learn' and not learn['files'] and not learn['exec'] and learn['bar'], learn
        assert not learn['left_handle'] and not learn['bottom_handle'], learn
        assert ws.tab.kind == 'learn' and ws.mode == 'learn'
        assert await pg.locator('.lee-learn-tab > .lee-learn-bar').count() == 0
        assert await pg.locator('#modebar [data-learn-back]').count() == 1
        for mode in ('light', 'dark'):
            await pg.evaluate(f"applyTheme('leela:{mode}:relaxed')"); await pg.wait_for_timeout(300)
            await pg.screenshot(path=f'{OUT}/m2-learn-step-{mode}.png')
        tab = await pg.evaluate("() => { const r = document.querySelector('.lee-learn-tab').getBoundingClientRect(); return [r.bottom, innerHeight - 24] }")
        assert abs(tab[0] - tab[1]) <= 2, tab
        await pg.evaluate("leeLearnOpen('/')"); await pg.locator('.abh main').first.wait_for(); await pg.wait_for_timeout(800)
        for mode in ('light', 'dark'):
            await pg.evaluate(f"applyTheme('leela:{mode}:relaxed')"); await pg.wait_for_timeout(300)
            await pg.screenshot(path=f'{OUT}/m2-learn-home-{mode}.png')
        await pg.evaluate("applyTheme('leela:light:relaxed')")
        await pg.reload(wait_until='networkidle'); await pg.wait_for_function('window.lee && lee.keys.length')
        await pg.locator('.abh main').first.wait_for(timeout=30000); await pg.wait_for_timeout(500)
        again = await pg.evaluate(DOCKS)
        assert again['mode'] == 'learn' and not again['files'] and not again['exec'] and not again['left_handle'] and not again['bottom_handle'], again
        html = await (await pg.request.get(f'http://127.0.0.1:{port}/')).text()
        assert 'data-mode="learn"' in html and 'no-left' in html and 'data-nohandle' in html
        await pg.locator('#modeswitch [data-mode=code]').click(); await pg.wait_for_timeout(1000)
        back = await pg.evaluate(DOCKS)
        assert back['mode'] == 'code' and back['files'] and not back['exec'] and not back['bar'] and back['bottom_handle'], back
        assert back['tab'].endswith('lesson.py') and ws.mode == 'code'
        assert await pg.locator('.lee-tab', has_text='Learn').count() == 1
        assert not bad, bad
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_a_busy_turn_refuses_the_switch_with_one_line_and_changes_nothing(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    from leela.blocks.agent.threads import TurnError
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        def refuse(mode): raise TurnError('thread_busy', 'The mode cannot change during a turn. Wait for it to finish, then try again.', 'x')
        ws.threads.active.set_mode = refuse
        before = await pg.evaluate(DOCKS)
        await pg.locator('#modeswitch [data-mode=learn]').click(); await pg.wait_for_timeout(800)
        assert 'cannot change during a turn' in await pg.locator('#status').inner_text()
        assert await pg.evaluate(DOCKS) == before and ws.mode == 'code'
        assert await pg.locator('#modeswitch .active').inner_text() == 'Code'
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_the_bar_is_one_row_and_the_narrow_bar_folds_into_a_menu(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        ws.open_walk('workspace', jid, 0); ws.save(); await pg.evaluate('mountTab()')
        await pg.locator('.abh #check .check').wait_for(timeout=30000); await pg.wait_for_timeout(800)
        wide = await pg.evaluate(BAR)
        assert wide['rows'] and wide['inside'] and wide['h'] < 45 and not wide['more'] and wide['lib'], wide
        hdr = await pg.evaluate("() => document.querySelector('#header').getBoundingClientRect().height")
        assert hdr < 45
        await pg.set_viewport_size(dict(width=860, height=900)); await pg.wait_for_timeout(600)
        narrow = await pg.evaluate(BAR)
        assert narrow['rows'] and narrow['inside'] and narrow['h'] < 45 and narrow['more'] and not narrow['lib'], narrow
        await pg.screenshot(path=f'{OUT}/m2-learn-narrow-light.png')
        await pg.locator('[data-learn-more]').click()
        assert 'Library' in await pg.locator('.lee-ctxmenu').inner_text()
        await pg.locator('.lee-ctxmenu .lee-menuitem', has_text='Library').click()
        await pg.locator('.abh main').first.wait_for(); await pg.wait_for_timeout(500)
        hit = await pg.evaluate("() => { const g = ['.restore-left', '.restore-bottom'].map(s => document.querySelector(s)); return g.map(e => getComputedStyle(e).display) }")
        assert hit == ['none', 'none'], hit
    _run(tmp_path, scenario, dict(width=1500, height=900))
