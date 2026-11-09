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
        ws.open_walk('workspace', jid, 0); ws.save(); await pg.locator('#modeswitch [data-mode=learn]').click()
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


def test_keys_search_toasts_and_the_reserved_strip_in_the_learn_tab(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        ws.open_walk('workspace', jid, 0); ws.save(); await pg.locator('#modeswitch [data-mode=learn]').click()
        await pg.locator('.abh #check .check').wait_for(timeout=30000); await pg.wait_for_timeout(800)
        assert await pg.evaluate("getComputedStyle(document.querySelector('.lee-learn-tab')).getPropertyValue('--learn-bottom').trim()") in ('0px', '')
        await pg.evaluate("() => { document.activeElement.blur?.(); window.hints = 0; document.querySelector('#hint').addEventListener('click', () => window.hints++) }")
        tabs = await pg.locator('.lee-tab').count()
        await pg.evaluate("() => document.body.focus()")
        await pg.keyboard.press('Alt+KeyW'); await pg.wait_for_timeout(500)
        assert await pg.evaluate('window.hints') == 1
        assert await pg.locator('.lee-tab').count() == tabs and ws.tab.kind == 'learn'
        await pg.evaluate("() => leeLearnOpen('/')"); await pg.locator('.abh main').first.wait_for(); await pg.wait_for_timeout(800)
        tabs = await pg.locator('.lee-tab').count()
        await pg.keyboard.press('Alt+KeyW'); await pg.wait_for_timeout(500)
        assert await pg.locator('.lee-tab').count() == tabs and ws.tab.kind == 'learn'
        assert await pg.evaluate("getComputedStyle(document.querySelector('.abh .kf-pill')).display") == 'none'
        was = await pg.evaluate("!document.querySelector('#kf-panel').hidden")
        await pg.locator('[data-learn-keys]').click(); await pg.wait_for_timeout(300)
        assert await pg.evaluate("!document.querySelector('#kf-panel').hidden") != was
        await pg.keyboard.press('Escape')
        await pg.locator('.lee-learn-find input').fill('fractions')
        await pg.evaluate("leeLearnNav('/graph')"); await pg.locator('.abh #graph canvas').wait_for(timeout=30000); await pg.wait_for_timeout(500)
        assert await pg.locator('.lee-learn-find input').input_value() == ''
        css = (await pg.evaluate("fetch('/learn/abh-surface?path=/t/x').then(r => r.json())"))['css']
        await pg.evaluate("u => new Promise(ok => document.head.append(Object.assign(document.createElement('link'), {rel: 'stylesheet', href: u, onload: ok})))", [u for u in css if 'learn-talk' in u][0])
        await pg.evaluate("document.querySelector('.abh').classList.add('lee-presenting'); document.querySelector('.abh').insertAdjacentHTML('beforeend', '<div class=undo-bar>Added a slide.</div>')")
        assert await pg.evaluate("getComputedStyle(document.querySelector('.abh .undo-bar')).display") == 'none'
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_the_bar_holds_one_row_at_1100(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        ws.open_walk('workspace', jid, 0); ws.save(); await pg.locator('#modeswitch [data-mode=learn]').click()
        await pg.locator('.abh #check .check').wait_for(timeout=30000)
        for w in (1100, 860):
            await pg.set_viewport_size(dict(width=w, height=700)); await pg.wait_for_timeout(600)
            bar = await pg.evaluate(BAR)
            assert bar['rows'] and bar['inside'] and bar['h'] < 45 and bar['more'], (w, bar)
            assert await pg.evaluate("() => document.querySelector('#header').getBoundingClientRect().height") < 45
            await pg.screenshot(path=f'{OUT}/m2-learn-{w}.png')
    _run(tmp_path, scenario, dict(width=1500, height=900))


HEAD = """() => { const h = document.querySelector('#header'), hb = h.getBoundingClientRect(), vis = [...h.children].filter(e => e.offsetParent && e.getBoundingClientRect().width), r = vis.map(e => [e.id || e.className.toString().split(' ')[0], e.getBoundingClientRect()]);
  return {h: hb.height, w: hb.width, vw: innerWidth, sw: document.documentElement.scrollWidth, rows: Math.max(...r.map(x => x[1].top)) < Math.min(...r.map(x => x[1].bottom)),
    out: r.filter(x => x[1].right > innerWidth + 1 || x[1].left < -1).map(x => x[0]), cut: r.filter(x => x[0] !== 'tabbar' && x[1].right > hb.right + 1).map(x => x[0]),
    kernel: !!document.querySelector('#header > .lee-pill:last-child') && document.querySelector('#header > .lee-pill:last-child').getBoundingClientRect().right <= innerWidth,
    sw_text: document.querySelector('#modeswitch').getBoundingClientRect().width, names: r.map(x => x[0])} }"""


def test_the_title_bar_holds_one_row_from_1100_to_720(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        ws.open_walk('workspace', jid, 0); ws.save(); bad = []
        for mode in ('code', 'learn'):
            await pg.locator(f'#modeswitch [data-mode={mode}]').click(); await pg.wait_for_timeout(1000)
            for w in (1100, 1000, 860, 720):
                await pg.set_viewport_size(dict(width=w, height=800)); await pg.wait_for_timeout(500)
                b = await pg.evaluate(HEAD)
                bad.append((mode, w, b)) if not (b['h'] < 45 and b['rows'] and not b['out'] and not b['cut'] and b['kernel'] and b['sw'] <= w) else None
                await pg.screenshot(path=f'{OUT}/v1-title-{mode}-{w}.png')
        assert not bad, '\n'.join(map(str, bad))
    _run(tmp_path, scenario, dict(width=1500, height=900))


AGENT = "() => ({label: document.querySelector('#agentmode')?.textContent, setup: [...document.querySelectorAll('#agentlog [data-setup]')].filter(e => e.offsetParent).length, starters: [...document.querySelectorAll('#agentlog .lee-agent-starters button')].filter(e => e.offsetParent).length})"


def test_the_agent_pane_follows_the_mode_both_ways_and_after_a_reload(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        a = await pg.evaluate(AGENT)
        assert a['label'] == 'Code' and a['setup'] == 3 and a['starters'] == 0, a
        await pg.locator('#modeswitch [data-mode=learn]').click()
        await pg.locator('.abh main').first.wait_for(timeout=30000)
        await pg.wait_for_function("document.querySelector('#agentmode').textContent === 'Learn'")
        a = await pg.evaluate(AGENT)
        assert a['setup'] == 0 and a['starters'] == 3, a
        assert ws.threads.active.ai.mode == 'learn' and ws.mode == 'learn'
        for mode in ('light', 'dark'):
            await pg.evaluate(f"applyTheme('leela:{mode}:relaxed')"); await pg.wait_for_timeout(300)
            await pg.screenshot(path=f'{OUT}/v1-agent-learn-{mode}.png')
        await pg.reload(wait_until='networkidle'); await pg.wait_for_function('window.lee && lee.keys.length')
        await pg.evaluate("leeRight('agent')"); await pg.wait_for_function("document.querySelector('#agentmode')?.textContent === 'Learn'")
        a = await pg.evaluate(AGENT)
        assert a['setup'] == 0 and a['starters'] == 3, a
        await pg.locator('#modeswitch [data-mode=code]').click()
        await pg.wait_for_function("document.querySelector('#agentmode').textContent === 'Code'")
        a = await pg.evaluate(AGENT)
        assert a['setup'] == 3 and a['starters'] == 0, a
        assert ws.threads.active.ai.mode == 'code' and ws.mode == 'code'
        for mode in ('light', 'dark'):
            await pg.evaluate(f"applyTheme('leela:{mode}:relaxed')"); await pg.wait_for_timeout(300)
            await pg.screenshot(path=f'{OUT}/v1-agent-code-{mode}.png')
        await pg.reload(wait_until='networkidle'); await pg.wait_for_function('window.lee && lee.keys.length')
        await pg.evaluate("leeRight('agent')"); await pg.wait_for_function("document.querySelector('#agentmode')?.textContent === 'Code'")
        a = await pg.evaluate(AGENT)
        assert a['setup'] == 3 and a['starters'] == 0, a
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_a_refused_switch_leaves_the_agent_pane_as_it_was(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    from leela.blocks.agent.threads import TurnError
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        await pg.locator('#modeswitch [data-mode=learn]').click()
        await pg.wait_for_function("document.querySelector('#agentmode').textContent === 'Learn'")
        def refuse(mode): raise TurnError('thread_busy', 'The mode cannot change during a turn. Wait for it to finish, then try again.', 'x')
        ws.threads.active.set_mode = refuse
        before = await pg.evaluate(AGENT); docks = await pg.evaluate(DOCKS)
        await pg.locator('#modeswitch [data-mode=code]').click(); await pg.wait_for_timeout(1000)
        assert 'cannot change during a turn' in await pg.locator('#status').inner_text()
        assert await pg.evaluate(AGENT) == before and await pg.evaluate(DOCKS) == docks and ws.mode == 'learn'
        assert await pg.locator('#modeswitch .active').inner_text() == 'Learn'
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_code_with_only_the_learn_tab_shows_the_first_run_page_and_stays_code(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        ws.close(0); ws.open_walk('workspace', jid, 0); ws.mode = 'learn'; ws.save()
        assert [t.kind for t in ws.tabs] == ['learn']
        await pg.reload(wait_until='networkidle'); await pg.wait_for_function('window.lee && lee.keys.length')
        await pg.locator('.abh main').first.wait_for(timeout=30000)
        assert (await pg.evaluate(DOCKS))['mode'] == 'learn'
        await pg.locator('#modeswitch [data-mode=code]').click(); await pg.wait_for_timeout(1500)
        d = await pg.evaluate(DOCKS)
        assert d['mode'] == 'code' and d['files'] and not d['bar'] and ws.mode == 'code' and ws.tab is None, d
        ways = await pg.locator('#editor .lee-first .lee-first-way strong').all_inner_texts()
        assert ways == ['Open a folder', 'Learn something', 'Write or run code'], ways
        assert await pg.locator('.abh').count() == 0 and await pg.locator('#agentmode').inner_text() == 'Code'
        for mode in ('light', 'dark'):
            await pg.evaluate(f"applyTheme('leela:{mode}:relaxed')"); await pg.wait_for_timeout(300)
            await pg.screenshot(path=f'{OUT}/v1-code-empty-{mode}.png')
        await pg.reload(wait_until='networkidle'); await pg.wait_for_function('window.lee && lee.keys.length'); await pg.wait_for_timeout(800)
        d = await pg.evaluate(DOCKS)
        assert d['mode'] == 'code' and await pg.locator('#editor .lee-first').count() == 1 and ws.tab is None, d
        await pg.locator('.lee-tab', has_text='Learn').click()
        await pg.wait_for_function("document.querySelector('#shell').dataset.mode === 'learn'"); await pg.locator('.abh main').first.wait_for(timeout=30000)
        assert ws.mode == 'learn' and ws.threads.active.ai.mode == 'learn'
        await pg.locator('#modeswitch [data-mode=code]').click(); await pg.locator('#editor .lee-first').wait_for()
        await pg.locator('#first-learn').click()
        await pg.locator('.abh main').first.wait_for(timeout=30000)
        await pg.wait_for_function("document.querySelector('#agentmode').textContent === 'Learn'")
        d = await pg.evaluate(DOCKS)
        assert d['mode'] == 'learn' and d['bar'] and ws.mode == 'learn' and ws.tab.kind == 'learn', d
    _run(tmp_path, scenario, dict(width=1500, height=900))


GRID = "() => { const s = document.querySelector('#shell'), b = document.querySelector('.lee-body'); return {cls: [...s.classList].filter(c => /^(no-|expand-)/.test(c)).sort(), cols: getComputedStyle(b).gridTemplateColumns, handle: s.hasAttribute('data-nohandle')} }"
WATCH = """() => { window.__shell = []; const grab = () => { const s = document.querySelector('#shell'); if (s) window.__shell.push([...s.classList].filter(c => /^no-/.test(c)).sort().join(' ') + '|' + s.hasAttribute('data-nohandle')); };
  new MutationObserver(grab).observe(document, {subtree: true, attributes: true, attributeFilter: ['class', 'data-nohandle'], childList: true}); document.addEventListener('DOMContentLoaded', grab); }"""


def test_each_mode_keeps_its_own_docks_and_a_reload_paints_them_at_once(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        ws.open_walk('workspace', jid, 0); ws.save()
        await pg.evaluate("leePane('left', false); leePane('bottom', true)"); await pg.wait_for_timeout(700)
        code = await pg.evaluate(GRID)
        assert 'no-left' in code['cls'] and 'no-bottom' not in code['cls'], code
        await pg.locator('#modeswitch [data-mode=learn]').click(); await pg.locator('.abh main').first.wait_for(timeout=30000); await pg.wait_for_timeout(800)
        learn = await pg.evaluate(GRID)
        assert 'no-bottom' in learn['cls'] and learn['handle'], learn
        await pg.evaluate("leePane('left', true)"); await pg.wait_for_timeout(700)
        await pg.locator('#modeswitch [data-mode=code]').click(); await pg.wait_for_timeout(1200)
        assert await pg.evaluate(GRID) == code
        await pg.locator('#modeswitch [data-mode=learn]').click(); await pg.wait_for_timeout(1200)
        again = await pg.evaluate(GRID)
        assert 'no-left' not in again['cls'] and 'no-bottom' in again['cls'], again
        await pg.locator('[data-learn-fit]').click(); await pg.wait_for_timeout(700)
        wide = await pg.evaluate(GRID)
        assert 'no-left' in wide['cls'] and 'no-bottom' in wide['cls'], wide
        await pg.locator('#modeswitch [data-mode=code]').click(); await pg.wait_for_timeout(1200)
        assert await pg.evaluate(GRID) == code
        await pg.locator('#modeswitch [data-mode=learn]').click(); await pg.wait_for_timeout(1200)
        assert await pg.evaluate(GRID) == wide
        for mode in ('light', 'dark'):
            await pg.evaluate(f"applyTheme('leela:{mode}:relaxed')"); await pg.wait_for_timeout(300)
            await pg.screenshot(path=f'{OUT}/v1-learn-wide-{mode}.png')
        html = await (await pg.request.get(f'http://127.0.0.1:{port}/')).text()
        shell = html[html.rindex('<', 0, html.index('id="shell"')): html.index('>', html.index('id="shell"'))]
        assert 'no-left' in shell and 'no-bottom' in shell and 'data-mode="learn"' in shell and 'no-right' not in shell, shell
        await pg.add_init_script(f'({WATCH})()')
        await pg.reload(wait_until='networkidle'); await pg.wait_for_function('window.lee && lee.keys.length'); await pg.wait_for_timeout(800)
        seen = await pg.evaluate('window.__shell')
        assert seen and set(seen) == {'no-bottom no-left|true'}, seen
        assert await pg.evaluate(GRID) == wide
        await pg.locator('#modeswitch [data-mode=code]').click(); await pg.wait_for_timeout(1200)
        assert await pg.evaluate(GRID) == code
        await pg.reload(wait_until='networkidle'); await pg.wait_for_function('window.lee && lee.keys.length'); await pg.wait_for_timeout(800)
        assert await pg.evaluate(GRID) == code
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_a_refused_tab_click_changes_neither_the_tab_nor_the_mode_and_an_idle_one_switches(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    from leela.blocks.agent.threads import TurnError
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        ws.open_walk('workspace', jid, 0); ws.activate(0); ws.save()
        await pg.reload(wait_until='networkidle'); await pg.wait_for_function('window.lee && lee.keys.length')
        assert ws.mode == 'code' and ws.tab.kind == 'text'
        def refuse(mode): raise TurnError('thread_busy', 'The mode cannot change during a turn. Wait for it to finish, then try again.', 'x')
        real = ws.threads.active.set_mode; ws.threads.active.set_mode = refuse
        before, docks = await pg.evaluate(AGENT), await pg.evaluate(DOCKS)
        await pg.locator('.lee-tab', has_text='Learn').click(); await pg.wait_for_timeout(1200)
        assert 'cannot change during a turn' in await pg.locator('#status').inner_text()
        assert ws.mode == 'code' and ws.tab.kind == 'text' and await pg.locator('.lee-tab.active').get_attribute('data-kind') == 'text'
        assert await pg.evaluate(DOCKS) == docks and await pg.evaluate(AGENT) == before and await pg.locator('.abh').count() == 0
        del ws.threads.active.set_mode
        await pg.locator('.lee-tab', has_text='Learn').click()
        await pg.locator('.abh main').first.wait_for(timeout=30000)
        await pg.wait_for_function("document.querySelector('#agentmode').textContent === 'Learn'")
        assert ws.mode == 'learn' and ws.tab.kind == 'learn' and (await pg.evaluate(DOCKS))['mode'] == 'learn'
        await pg.locator('.lee-tab', has_text='lesson.py').click()
        await pg.wait_for_function("document.querySelector('#shell').dataset.mode === 'code'")
        assert ws.mode == 'code' and ws.tab.kind == 'text' and ws.threads.active.ai.mode == 'code'
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_the_header_is_the_same_height_on_first_load_and_after_a_reload(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        H = "() => [document.querySelector('#header').getBoundingClientRect().height, [...document.querySelectorAll('#shell > *')].map(e => Math.round(e.getBoundingClientRect().height))]"
        ws.open_walk('workspace', jid, 0); ws.save()
        for mode in ('code', 'learn'):
            await pg.locator(f'#modeswitch [data-mode={mode}]').click(); await pg.wait_for_timeout(1500)
            first = await pg.evaluate(H)
            await pg.reload(wait_until='networkidle'); await pg.wait_for_function('window.lee && lee.keys.length'); await pg.wait_for_timeout(1500)
            assert await pg.evaluate(H) == first, mode
    _run(tmp_path, scenario, dict(width=1500, height=900))
