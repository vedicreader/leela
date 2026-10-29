"A notebook presented in a real page: the presenter screen, the audience window over the server relay, demos, live runs, and a clean exit."

import pytest

pytestmark = pytest.mark.slow

import asyncio, base64, json
from pathlib import Path

pytest.importorskip('playwright.async_api')

from test_completion_caret_slow import _real_page   # noqa: E402
from rupaka.spec import demo, gate, is_, readout, slider   # noqa: E402

SHOTS = Path(__file__).parents[1]/'target'/'present-shots'
DOT = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')
PNG = {'output_type': 'display_data', 'metadata': {}, 'data': {'image/png': base64.b64encode(DOT).decode()}}
MDOUT = {'output_type': 'display_data', 'metadata': {}, 'data': {'text/markdown': '**md out**', 'text/plain': 'md'}}
WIDGET = {'output_type': 'display_data', 'metadata': {}, 'data': {'application/vnd.jupyter.widget-view+json': {'model_id': 'm', 'version_major': 2, 'version_minor': 0}}}
md = lambda src, t, i: {'cell_type': 'markdown', 'id': i, 'metadata': {'slideshow': {'slide_type': t}}, 'source': src}
code = lambda src, t, i, outs=(): {'cell_type': 'code', 'id': i, 'metadata': {'slideshow': {'slide_type': t}},
                                   'execution_count': None, 'outputs': list(outs), 'source': src}
CELLS = [md('# Intro\n\n![dot](images/dot.png)', 'slide', 'm0'), md('plain continued text', '-', 'm1'),
         md('appears later', 'fragment', 'm2'), md('SPEAKER-SECRET-ONE', 'notes', 'm3'),
         code("print('hi')", 'subslide', 'c4', [PNG, MDOUT]), md('SKIPPED-TEXT', 'skip', 'm5'),
         md('# Second\n\nsecond body', 'slide', 'm6'), md('SPEAKER-SECRET-TWO', 'notes', 'm7'),
         code("import time\nfor i in range(3):\n    print('tick', i, flush=True)\n    time.sleep(0.8)", 'slide', 'c8'),
         code('1/0', 'slide', 'c9')]
META = {'kernelspec': {'name': 'python3', 'display_name': 'Python 3', 'language': 'python'}}
STYLES = r"""() => { const pick = el => { const s = getComputedStyle(el); return ['font-family', 'font-size', 'line-height',
    'color', 'background-color', 'margin-top', 'overflow', 'text-transform', 'letter-spacing'].map(k => s.getPropertyValue(k)).join('|'); };
  let h = document.getElementById('probe-h1'), p = document.getElementById('probe-pre');
  if (!h) { h = document.body.appendChild(document.createElement('h1')); h.id = 'probe-h1'; h.textContent = 'h';
            p = document.body.appendChild(document.createElement('pre')); p.id = 'probe-pre'; p.textContent = 'p'; }
  return [pick(document.documentElement), pick(document.body), pick(h), pick(p)]; }"""
READY = '() => document.querySelector(".lee-present[data-ready]")'
AT = '() => [lee.present.at.slide, lee.present.at.step]'
SLIDE = '.lee-present .lee-slide'
MSG = "() => document.querySelector('.lee-present-msg').textContent"
STATUS = "() => document.getElementById('status').textContent"
BLOCKS = "() => [...document.querySelectorAll('.lee-slide .lee-block')].map(b => b.outerHTML)"
ENDS = "() => ['prev', 'next'].map(n => document.querySelector(`.lee-present-strip [data-${n}]`).disabled)"
DRAWER = '''() => { const b = document.querySelector('.lee-present-strip [data-notes]'), d = document.querySelector('.lee-present-notes');
  return {expanded: b.getAttribute('aria-expanded'), controls: b.getAttribute('aria-controls'), id: d.id, hidden: d.hidden,
          close: !!d.querySelector('button[data-close]'), head: d.querySelector('h2')?.textContent, focus: document.activeElement === b}; }'''
HINT = 'Move the audience window to the projector. In that window, press F for full screen.'

def _nb(path, cells): path.write_text(json.dumps({'cells': cells, 'metadata': META, 'nbformat': 4, 'nbformat_minor': 5}))

async def _open(pg, path, n):
    await pg.evaluate('p => leeOpenFile(p)', str(path))
    await pg.wait_for_function(f'() => document.querySelectorAll(".lee-cell").length === {n}')

async def _start(pg, key='Alt+KeyR'):
    await pg.evaluate('() => { selectCell(0); focusCell(0); }')
    await pg.keyboard.press(key)
    await pg.wait_for_function(READY, timeout=20000)

async def _end(pg):
    await pg.click('.lee-present-strip [data-end]')
    assert await pg.text_content('.lee-present-strip [data-end]') == 'End now?'
    await pg.click('.lee-present-strip [data-end]')
    await pg.wait_for_function('() => !document.querySelector(".lee-present")')

async def _walk(pg, root):
    out, asked = {}, []
    pg.on('request', lambda r: asked.append(r.url))
    await _open(pg, root/'deck.ipynb', 10)
    await pg.evaluate("""() => { const v = ensureCellMounted(1);
      v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: 'UNSAVED-EDIT'}}); }""")
    before = await pg.evaluate(STYLES)
    await _start(pg)
    out['during'] = await pg.evaluate(STYLES)
    out['n'] = await pg.evaluate('() => lee.present.deck.slides.length')
    await pg.wait_for_function(f'() => document.querySelector("{SLIDE}").textContent.includes("UNSAVED-EDIT")')
    await pg.wait_for_function(f'() => [...document.querySelectorAll("{SLIDE} img")].some(i => i.getAttribute("src").startsWith("/present/img/") && i.naturalWidth > 0)')
    await pg.wait_for_function('() => document.querySelectorAll(".lee-cell .lee-reply-actions").length > 0')
    out['actions'] = await pg.evaluate('() => [document.querySelectorAll(".lee-present .lee-reply-actions").length, document.querySelectorAll(".lee-cell .lee-reply-actions").length]')
    out['start'] = await pg.evaluate(AT)
    out['ends0'], out['where0'] = await pg.evaluate(ENDS), await pg.text_content('.lee-present-strip [data-where]')
    leak = [await pg.text_content(SLIDE)]
    out['drawer0'] = await pg.evaluate(DRAWER)
    await pg.keyboard.press('KeyN')
    await pg.wait_for_selector('.lee-present-notes:not([hidden])')
    out['notes'] = await pg.text_content('.lee-present-notes')
    out['drawer'] = await pg.evaluate(DRAWER)
    await pg.keyboard.press('ArrowRight'); await pg.keyboard.press('ArrowRight')
    await pg.wait_for_function(f'() => ({AT})()[0] === 1')
    out['ends1'] = await pg.evaluate(ENDS)
    await pg.wait_for_function(f'() => document.querySelector("{SLIDE} strong")?.textContent === "md out"')
    await pg.keyboard.press('ControlOrMeta+Shift+KeyP')
    await pg.wait_for_timeout(300)
    out['palette'] = await pg.evaluate('() => [!!document.querySelector(".lee-modal"), !!lee.present]')
    await pg.keyboard.press('ArrowRight')
    await pg.wait_for_function(f'() => ({AT})()[0] === 2')
    await pg.wait_for_function('() => document.querySelector(".lee-present-notes").textContent.includes("SPEAKER-SECRET-TWO")')
    leak.append(await pg.text_content(SLIDE))
    await pg.keyboard.press('Escape')
    out['esc'] = await pg.evaluate('() => [document.querySelector(".lee-present-notes").hidden, !!lee.present]')
    out['esc_drawer'] = await pg.evaluate(DRAWER)
    await pg.keyboard.press('KeyN'); await pg.wait_for_selector('.lee-present-notes:not([hidden])')
    await pg.focus('.lee-present-notes [data-close]'); await pg.keyboard.press('Space')
    out['closed_drawer'] = [await pg.evaluate(DRAWER), await pg.evaluate(AT)]
    await pg.focus('.lee-present-strip [data-prev]'); await pg.keyboard.press('Space')
    await pg.wait_for_function(f'() => ({AT})()[0] === 1')
    out['space_on_button'] = await pg.evaluate(AT)
    await pg.evaluate('() => lee.present.root.focus()')
    await pg.keyboard.press('ArrowRight'); await pg.keyboard.press('ArrowRight')
    await pg.wait_for_function(f'() => ({AT})()[0] === 3')
    out['file_at_run'] = (root/'deck.ipynb').read_bytes(), (root/'deck.ipynb').stat().st_mtime_ns
    await pg.click('.lee-present-strip [data-run="c8"]')
    await pg.wait_for_function(f'() => document.querySelector("{SLIDE}").textContent.includes("tick 2")', timeout=60000)
    out['notebook_out'] = await pg.evaluate('() => document.getElementById("out-c8").textContent')
    await pg.evaluate('() => lee.present.root.focus()')
    await pg.keyboard.press('ArrowRight')
    await pg.wait_for_function(f'() => ({AT})()[0] === 4')
    out['ends_last'] = await pg.evaluate(ENDS)
    await pg.click('.lee-present-strip [data-run="c9"]')
    # Task 7 on purpose: a failure opens the private error panel, not the status message
    await pg.wait_for_function('''() => !document.querySelector('.lee-present-err').hidden && document.querySelector('.lee-present-err').textContent.includes('ZeroDivisionError')''', timeout=60000)
    out['file_after_runs'] = (root/'deck.ipynb').read_bytes(), (root/'deck.ipynb').stat().st_mtime_ns
    await _end(pg)
    out['closed'] = await pg.evaluate('''() => ({focus: document.activeElement.closest('.lee-cell')?.dataset.i, sel: String(lee.sel),
      talk: document.documentElement.classList.contains('talk'), present: lee.present})''')
    out['after'] = await pg.evaluate(STYLES)
    await pg.evaluate('() => { presentNotebook(); presentNotebook(); }')
    await pg.wait_for_function(READY, timeout=20000)
    await pg.wait_for_timeout(300)
    out['reopen'] = await pg.evaluate('() => document.querySelectorAll(".lee-present").length')
    await _end(pg)
    await pg.evaluate('p => leeOpenFile(p)', str(root/'plain.py'))
    await pg.wait_for_function('() => lee.kind === "text"')
    said = {}
    async def route(name, act):
        await pg.evaluate("() => status('')"); await act(); await pg.wait_for_timeout(200)
        said[name] = await pg.evaluate(STATUS)
    await route('toolbar', lambda: pg.click('#toolbar [data-action="present_notebook"]'))
    async def menu():
        await pg.evaluate("() => openMenu('tab', 120, 120)"); await pg.click('.lee-ctxmenu [data-action="present_notebook"]')
    await route('menu', menu)
    async def pal():
        await pg.keyboard.press('ControlOrMeta+Shift+KeyP'); await pg.wait_for_selector('#cp')
        await pg.keyboard.type('present notebook as slides'); await pg.keyboard.press('Enter')
    await route('palette', pal)
    await route('key', lambda: pg.keyboard.press('Alt+KeyR'))
    out.update(said=said, before=before, leak=leak, asked=asked)
    return out

def test_a_notebook_presents_as_slides_and_leaves_the_ide_as_it_found_it(tmp_path):
    "Task 4 on purpose: one line of 5 slides drawn by the shared renderer, notes in a drawer, End twice, and no reveal.js."
    (tmp_path/'images').mkdir(); (tmp_path/'images'/'dot.png').write_bytes(DOT)
    _nb(tmp_path/'deck.ipynb', CELLS); (tmp_path/'plain.py').write_text('x = 1\n')
    before = (tmp_path/'deck.ipynb').read_bytes(), (tmp_path/'deck.ipynb').stat().st_mtime_ns
    out = asyncio.run(_real_page(lambda pg: _walk(pg, tmp_path), tmp_path))
    assert out['n'] == 5 and out['start'] == [0, 0]
    assert out['actions'][0] == 0 < out['actions'][1], 'the notebook keeps its edit buttons and the slide has none'
    assert not any('SPEAKER-SECRET' in t or 'SKIPPED-TEXT' in t for t in out['leak']), out['leak']
    assert 'SPEAKER-SECRET-ONE' in out['notes'] and "print('hi')" in out['notes'] and 'The room can see these notes' in out['notes']
    assert out['palette'] == [False, True], 'no palette behind the presentation'
    assert out['esc'] == [True, True], 'Esc closes the drawer and never ends'
    assert (out['ends0'], out['ends1'], out['ends_last']) == ([True, False], [False, False], [False, True]), 'Previous and Next are off at the ends'
    assert out['where0'] == '1 / 5 · step 1 / 2', out['where0']
    d0, d = out['drawer0'], out['drawer']
    assert d0['expanded'] == 'false' and d0['controls'] == d0['id'] != '' and d0['hidden'], d0
    assert d['expanded'] == 'true' and d['close'] and d['head'] == 'Speaker notes' and not d['hidden'], d
    assert out['esc_drawer']['expanded'] == 'false', out['esc_drawer']
    c, at = out['closed_drawer']
    assert c['hidden'] and c['expanded'] == 'false' and c['focus'] and at == [2, 0], 'Close closes the drawer, moves nothing, and gives focus to Notes'
    assert out['space_on_button'] == [1, 0], 'Space on a focused button presses it'
    assert 'tick 2' in out['notebook_out']
    assert out['closed'] == {'focus': out['closed']['sel'], 'sel': out['closed']['sel'], 'talk': False, 'present': None}
    assert out['before'] == out['during'] == out['after'], 'the presentation restyled the IDE'
    assert out['reopen'] == 1
    assert set(out['said'].values()) == {'only a notebook can be presented as slides'}, out['said']
    assert not [u for u in out['asked'] if 'reveal' in u or '/present/notes' in u or '/present/state' in u], out['asked']
    assert out['file_at_run'] == before, 'starting, moving, notes and the palette chord write nothing'
    assert out['file_after_runs'] == before, 'Task 7: Run in a presentation saves nothing, the unsaved edit included'


LONG = '# Long\n\n' + '\n\n'.join(f'line {i} of a slide written far longer than one page holds' for i in range(20))
TEXT = f"() => parseFloat(getComputedStyle(document.querySelector('{SLIDE} p')).fontSize)"
ALIGN = f"() => [...document.querySelectorAll('{SLIDE} h1, {SLIDE} p')].slice(0, 2).map(e => getComputedStyle(e).textAlign)"

def test_a_long_slide_shrinks_to_the_floor_and_text_is_left(tmp_path):
    "Task 4 on purpose: no slide scrolls; a slide too long at the floor is named to the presenter; the align toggle left with reveal.js."
    _nb(tmp_path/'deck.ipynb', [md(LONG, 'slide', 'l0'), md('# Short\n\nsmall text', 'slide', 's1')])
    async def go(pg):
        out = {}
        await _open(pg, tmp_path/'deck.ipynb', 2)
        await _start(pg)
        await pg.wait_for_function(f'() => ({MSG})().includes("Slide 1 has more than fits. Split it or trim it.")')
        out['align'] = await pg.evaluate(ALIGN)
        out['clip'] = await pg.evaluate(f"() => getComputedStyle(document.querySelector('{SLIDE}')).overflow")
        out['floor_px'] = await pg.evaluate(f"() => parseFloat(getComputedStyle(document.querySelector('{SLIDE} p')).fontSize)")
        await pg.keyboard.press('ArrowRight')
        await pg.wait_for_function(f'() => ({AT})()[0] === 1')
        small = await pg.evaluate(TEXT)
        await pg.click('.lee-present-strip [data-bigger]'); await pg.click('.lee-present-strip [data-bigger]')
        await pg.wait_for_timeout(200)
        out['ratio'], out['msg'] = await pg.evaluate(TEXT) / small, await pg.evaluate(MSG)
        for _ in range(30): await pg.click('.lee-present-strip [data-smaller]')
        out['floor'] = await pg.evaluate(MSG)
        for _ in range(30): await pg.click('.lee-present-strip [data-bigger]')
        out['ceiling'] = await pg.evaluate(MSG)
        await _end(pg)
        await pg.evaluate('() => presentNotebook("beginning")')
        await pg.wait_for_function(READY, timeout=20000)
        out['remembered'] = await pg.evaluate('() => lee.present.text')
        return out
    out = asyncio.run(_real_page(go, tmp_path))
    assert out['align'] == ['left', 'left'] and out['clip'] == 'hidden', out
    assert 19.5 <= out['floor_px'] <= 21, out['floor_px']
    assert abs(out['ratio'] - 1.2) < .02 and out['msg'] == 'text 120%', out
    assert (out['floor'], out['ceiling'], out['remembered']) == ('text 50%', 'text 250%', 2.5)


WALK = '''k => { const bad = '<img src=x onerror=alert(1)><a href="javascript:x">J</a><svg><script>window.hit=1</script></svg>' +
  '<img src="https://evil.example/a"><img src="/present/img/' + 'a'.repeat(64) + '?k=other"><img src="data:image/png;base64,iVBORw0KGgo=">' +
  '<p class="lee-present stage-blank keep" onclick="x()">ok</p><a href="https://example.com/">web</a>';
  const box = document.createElement('div'); box.append(slidesSafe(bad, k));
  return {html: box.innerHTML, imgs: [...box.querySelectorAll('img')].map(i => i.getAttribute('src')), hit: window.hit}; }'''

async def _shot(pg, aud, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    await pg.wait_for_timeout(500)
    await pg.screenshot(path=str(SHOTS/f'presenter-{name}.png'))
    if aud: await aud.screenshot(path=str(SHOTS/f'audience-{name}.png'))

RECT = "s => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom].map(Math.round); }"
FITS = '''() => { const s = document.querySelector('.lee-present-strip'), w = innerWidth;
  return {over: s.scrollWidth > s.clientWidth + 1, out: [...s.querySelectorAll('button')].filter(b => b.getBoundingClientRect().right > w + .5).map(b => b.textContent)}; }'''

def test_the_audience_window_follows(tmp_path):
    cells = [md('# Intro\n\nbody text', 'slide', 'a0'), md('FRAG-TEXT', 'fragment', 'a1'), md('SPEAKER-SECRET', 'notes', 'a2'),
             md('# Code\n\nwhat it prints', 'slide', 'b0'), code("print('hello room')", '-', 'b1', [{'output_type': 'stream', 'name': 'stdout', 'text': 'hello room\n'}]),
             md('# Widget', 'slide', 'w0'), code('w', '-', 'w1', [WIDGET])]
    _nb(tmp_path/'deck.ipynb', cells)
    async def go(pg):
        out, pages, methods = {}, [], []
        pg.context.on('page', lambda p: pages.append(p))
        await _open(pg, tmp_path/'deck.ipynb', 7)
        await _start(pg)
        async with pg.context.expect_page() as pop:
            await pg.click('.lee-present-strip [data-audience]')
        aud = await pop.value
        aud.on('request', lambda r: methods.append((r.method, r.url)))
        await aud.wait_for_function('() => document.querySelector(".lee-stage .lee-slide")?.textContent.includes("Intro")', timeout=20000)
        out['hint'] = await pg.evaluate(MSG)
        out['aud_text'] = await aud.evaluate('() => document.body.textContent')
        await pg.wait_for_function('() => document.querySelector(".lee-present-strip [data-conn]").textContent === "Audience window: connected"')
        out['address'] = await aud.evaluate('() => location.search'), await pg.evaluate('() => [lee.present.ak, lee.present.key]')
        out['same0'] = (await pg.evaluate(BLOCKS)) == (await aud.evaluate(BLOCKS))
        await pg.evaluate('() => lee.present.root.focus()')
        await pg.keyboard.press('ArrowRight')
        await aud.wait_for_function('() => !document.querySelector(".lee-slide .lee-frag-hidden") && document.querySelector(".lee-slide").textContent.includes("FRAG-TEXT")')
        out['same1'] = (await pg.evaluate(BLOCKS)) == (await aud.evaluate(BLOCKS))
        out['leak'] = await aud.evaluate('() => document.body.textContent')
        out['walk'] = await aud.evaluate(WALK, await aud.evaluate('() => sessionStorage.getItem("lee-present-k")'))
        await pg.evaluate('() => applyTheme("leela:dark:relaxed")')
        await aud.wait_for_function('() => document.documentElement.dataset.mode === "dark" && document.documentElement.dataset.theme === "leela"')
        out['dark_bg'] = await aud.evaluate("() => [getComputedStyle(document.body).backgroundColor, getComputedStyle(document.documentElement).getPropertyValue('--lee-bg').trim()]")
        await _shot(pg, aud, 'dark')
        await pg.evaluate('() => applyTheme("cursor:light:tight")')
        await aud.wait_for_function('() => document.documentElement.dataset.mode === "light" && document.documentElement.dataset.theme === "cursor"')
        await _shot(pg, aud, 'light')
        geo = [await pg.evaluate(RECT, SLIDE), await aud.evaluate(RECT, '.lee-slide')]
        await pg.keyboard.press('KeyN')
        await _shot(pg, aud, 'light-notes')
        geo += [await pg.evaluate(RECT, SLIDE), await aud.evaluate(RECT, '.lee-slide'), await pg.evaluate(RECT, '.lee-present-notes'),
                await pg.evaluate('() => innerWidth')]
        out['geo'] = geo
        await pg.keyboard.press('Escape')
        await pg.evaluate('() => lee.present.root.focus()')
        await pg.keyboard.press('ArrowRight')
        await aud.wait_for_function('() => document.querySelector(".lee-slide").textContent.includes("hello room")')
        out['code_px'] = await aud.evaluate("() => parseFloat(getComputedStyle(document.querySelector('.lee-slide .lee-out pre, .lee-slide .lee-out')).fontSize)")
        out['narrow'] = {}
        for w in (1024, 720):
            await pg.set_viewport_size({'width': w, 'height': 640}); await pg.wait_for_timeout(300)
            out['narrow'][w] = await pg.evaluate(FITS)
            if w == 1024: await _shot(pg, None, 'narrow-1024')
        await pg.set_viewport_size({'width': 1280, 'height': 720})
        await pg.evaluate('() => lee.present.root.focus()')
        await pg.keyboard.press('ArrowRight')
        await aud.wait_for_function('() => document.querySelector(".lee-slide").textContent.includes("This output type is not shown in presentations.")')
        n = len(pages)
        await pg.click('.lee-present-strip [data-audience]'); await pg.wait_for_timeout(500)
        out['second_click_pages'] = len(pages) - n
        await aud.close()
        await pg.wait_for_function('() => document.querySelector(".lee-present-strip [data-conn]").textContent === "Audience window: not connected"', timeout=20000)
        await pg.evaluate('() => { window._open = window.open; window.open = () => null; }')
        await pg.click('.lee-present-strip [data-audience]')
        out['blocked'] = [await pg.evaluate(MSG), await pg.locator('.lee-present-strip [data-audience]').count()]
        await pg.evaluate('() => { window.open = window._open; }')
        async with pg.context.expect_page() as pop:
            await pg.click('.lee-present-strip [data-audience]')
        aud = await pop.value
        await aud.wait_for_function('() => document.querySelector(".lee-slide")?.textContent.includes("This output type")', timeout=20000)
        await _end(pg)
        await aud.wait_for_function('() => document.querySelector(".lee-end")?.textContent.includes("The presentation has ended.")')
        out['end'] = await aud.text_content('.lee-end')
        SHOTS.mkdir(parents=True, exist_ok=True); await aud.screenshot(path=str(SHOTS/'audience-end-light.png'))
        out['methods'] = methods
        return out
    out = asyncio.run(_real_page(go, tmp_path))
    assert out['hint'] == HINT and 'audience window' in out['hint'], out['hint']
    assert 'projector' not in out['aud_text'], 'the hint is for the presenter only'
    p0, a0, p1, a1, n1, w = out['geo']
    assert a0 == a1, 'the audience canvas does not change when notes open'
    assert p1[2] <= n1[0] and p1[2] - p1[0] < p0[2] - p0[0] and p1[0] >= 0 and n1[2] <= w, ('the drawer makes room and the slide scales', out['geo'])
    assert out['narrow'] == {1024: {'over': False, 'out': []}, 720: {'over': False, 'out': []}}, ('the strip wraps instead of clipping', out['narrow'])
    (search, (ak, key)) = out['address']
    assert search == f'?k={ak}' and key not in search, 'the audience window holds the audience key only'
    assert out['same0'] and out['same1'], 'both windows draw the same slide markup'
    assert 'SPEAKER-SECRET' not in out['leak']
    w = out['walk']
    assert w['imgs'] == ['data:image/png;base64,iVBORw0KGgo='] and w['hit'] is None, w
    assert all(x not in w['html'] for x in ('onerror', 'javascript', 'svg', 'script', 'evil.example', 'onclick', 'lee-present', 'stage-blank')), w
    assert 'class="keep"' in w['html'] and 'rel="noopener noreferrer"' in w['html'] and 'target="_blank"' in w['html'], w
    assert out['dark_bg'][0] != 'rgba(0, 0, 0, 0)', out['dark_bg']
    assert out['code_px'] >= 22, out['code_px']
    assert out['second_click_pages'] == 0, 'a second click focuses the open window'
    assert out['blocked'] == ['The browser blocked the window. Click again.', 1]
    assert 'deck' in out['end'] and 'The presentation has ended.' in out['end']
    assert {m for m, _ in out['methods']} == {'GET'}, out['methods']


SPEC = demo('d1', title='Weights', state={'x': 2}, blocks=[slider('x', label='x', min=0, max=4, step=1),
            gate('g1', 'Which one?', ['one', 'two'], is_('two'), why='because'), readout('x is {x}')])
SHADOW = "s => document.querySelector('.lee-stage .lee-rupaka')?.shadowRoot?.querySelector(s)"
DEMO_PX = '''r => { const host = document.querySelector(r + ' .lee-slide .lee-rupaka'), sr = host.shadowRoot, px = s => { const e = sr.querySelector(s); return e && parseFloat(getComputedStyle(e).fontSize); };
  const ta = sr.querySelector('.rk-gate textarea');
  return {body: parseFloat(getComputedStyle(document.querySelector(r + ' .lee-slide')).fontSize), rk: px('.rk'), button: px('.rk-gate .opts button'), verdict: px('.verdict'),
          readout: px('.rk-readout, .rk-b:last-child'), lbl: px('.rk-lbl'), kbd: sr.querySelector('kbd') ? getComputedStyle(sr.querySelector('kbd')).display : 'none',
          why: !ta || getComputedStyle(ta).display === 'none'}; }'''

def test_a_demo_in_the_room_has_no_answers_and_shows_the_verdict(tmp_path):
    _nb(tmp_path/'deck.ipynb', [md(f'# Demo\n\n```rupaka\n{json.dumps(SPEC)}\n```', 'slide', 'd0')])
    async def go(pg):
        out = {}
        await _open(pg, tmp_path/'deck.ipynb', 1)
        await _start(pg)
        await pg.wait_for_function('() => document.querySelector(".lee-present .lee-rupaka")?.shadowRoot?.querySelector(".rk-gate")', timeout=20000)
        async with pg.context.expect_page() as pop:
            await pg.click('.lee-present-strip [data-audience]')
        aud = await pop.value
        await aud.wait_for_function(f'() => ({SHADOW})(".rk-gate")', timeout=20000)
        out['deck'] = await aud.evaluate('() => fetch("/present/deck?k=" + sessionStorage.getItem("lee-present-k")).then(r => r.text())')
        out['inert'] = await aud.evaluate(f'() => ({SHADOW})(".rk-gate").inert')
        move = 'm => fetch("/present/move", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({...m, k: lee.present.key})}).then(r => r.status)'
        out['posts'] = [await pg.evaluate(move, dict(t='demo', slug='d1', state={'x': 3}, gates={'g1': 'done'}, pick={'g1': 1}))]
        await aud.wait_for_function(f'() => ({SHADOW})(".rk-readout, .readout")?.textContent.includes("x is 3") || ({SHADOW})(".rk")?.textContent.includes("x is 3")')
        out['before'] = await aud.evaluate(f'() => ({SHADOW})(".rk").textContent')
        out['posts'].append(await pg.evaluate(move, dict(t='answers', slide='s1', slug='d1', gates={'g1': {'is': 'two'}})))
        await aud.wait_for_function(f'() => ({SHADOW})(".verdict:not([hidden])")?.textContent.includes("You said")')
        out['verdict'] = await aud.evaluate(f'() => ({SHADOW})(".verdict").textContent')
        await aud.reload()
        await aud.wait_for_function(f'() => ({SHADOW})(".verdict:not([hidden])")?.textContent.includes("You said")', timeout=20000)
        await aud.wait_for_timeout(300)
        out['aud_px'] = await aud.evaluate(DEMO_PX, '.lee-stage')
        out['pres_px'] = await pg.evaluate(DEMO_PX, '.lee-present')
        SHOTS.mkdir(parents=True, exist_ok=True); await aud.screenshot(path=str(SHOTS/'audience-demo-light.png'))
        await pg.screenshot(path=str(SHOTS/'presenter-demo-light.png'))
        return out
    out = asyncio.run(_real_page(go, tmp_path))
    assert '"answer"' not in out['deck'] and out['inert'] is True
    assert out['posts'] == [200, 200] and 'You said' not in out['before']
    assert 'You said' in out['verdict'] and 'two' in out['verdict']
    a, p = out['aud_px'], out['pres_px']
    assert all(v >= a['body'] - .5 for v in (a['rk'], a['button'], a['verdict'], a['readout'])), ('demo text is at least slide-body size', a)
    assert a['kbd'] == 'none' and a['why'] is True, ('the room copy has no key labels and no empty explanation box', a)
    assert (p['body'], p['rk'], p['button'], p['lbl']) == (a['body'], a['rk'], a['button'], a['lbl']), ('the presenter demo has the room sizes', p, a)


KEY_CELLS = [md('# One', 'slide', 'k0'), md('# Two', 'slide', 'k1'), md('two a', 'fragment', 'k2'), md('two b', 'fragment', 'k3'),
             md('# Three', 'slide', 'k4'), md('three a', 'fragment', 'k5'), md('# Four', 'slide', 'k6'),
             md(f'# Demo\n\n```rupaka\n{json.dumps(SPEC)}\n```', 'slide', 'k7')]
#: the place on the server, read from the `state` of a new room stream after this presenter's posts
SERVER = '''async () => { const p = lee.present; await p.chain; return await new Promise(ok => { const es = new EventSource('/present/room?k=' + p.ak);
  es.addEventListener('state', e => { es.close(); const a = JSON.parse(e.data).at; ok([+a.slide.slice(1) - 1, a.step, a.blank]); }); }); }'''
LOOK = '''() => { const p = lee.present, c = p.root.querySelector('.lee-slide'), a = document.activeElement;
  return {at: [p.at.slide, p.at.step], blank: c.classList.contains('blank'), laser: p.root.classList.contains('lee-laser'),
          notes: !p.root.querySelector('.lee-present-notes').hidden, full: !!document.fullscreenElement,
          focus: a === p.root ? 'root' : a?.matches?.('[data-notes]') ? 'notes' : a?.closest?.('.lee-rupaka') ? 'demo' : a?.tagName || ''}; }'''
#: a synthetic keydown, for pairs a real keyboard cannot type; true when nothing called `preventDefault`
KEY = "o => lee.present.root.dispatchEvent(new KeyboardEvent('keydown', {bubbles: true, cancelable: true, composed: true, ...o}))"
CLICKS = '''() => { const c = window._clicks ||= {prev: 0, next: 0};
  if (!window._counted) { window._counted = 1; for (const n of ['prev', 'next']) document.querySelector(`.lee-present-strip [data-${n}]`).addEventListener('click', () => c[n]++); }
  return {...c}; }'''
FIELDS = '''() => { const d = lee.present.root.appendChild(document.createElement('div')); d.className = 't-fields';
  d.innerHTML = '<input value="i"><textarea>t</textarea><select><option>a</option><option>b</option></select>' +
    '<div contenteditable="true"><p>c<span tabindex="-1" data-nested>n</span></p></div>'; }'''
SLIDER = "() => document.querySelector('.lee-present .lee-rupaka').shadowRoot.querySelector('input')"

async def _to(pg, slide):
    await pg.evaluate('() => lee.present.root.focus()')
    for _ in range(12):
        if (await pg.evaluate(AT))[0] == slide: return
        await pg.keyboard.press('ArrowRight')
    raise AssertionError(f'never reached slide {slide}')

def test_clicker_keys(tmp_path):
    "Each key of the key map moves one step or toggles one thing; a held key, a focused button, a field, a demo, a modifier and the editor underneath do not move."
    _nb(tmp_path/'deck.ipynb', KEY_CELLS)
    async def go(pg):
        out = {}
        await _open(pg, tmp_path/'deck.ipynb', 8)
        src = await pg.evaluate('() => ensureCellMounted(0).state.doc.toString()')
        await _start(pg)
        await pg.keyboard.press('ArrowRight'); await pg.keyboard.press('ArrowRight')
        out['interior'] = await pg.evaluate(AT)
        out['walk'] = []
        for k in ('PageDown', 'PageUp', 'Space', 'Shift+Space', 'ArrowRight', 'ArrowLeft', 'ArrowDown', 'ArrowUp'):
            await pg.keyboard.press(k); out['walk'].append([k, await pg.evaluate(AT), (await pg.evaluate(SERVER))[:2]])
        for _ in range(3): await pg.keyboard.down('ArrowRight')
        await pg.keyboard.up('ArrowRight')
        out['held'] = [await pg.evaluate(AT), (await pg.evaluate(SERVER))[:2]]
        await pg.keyboard.press('ArrowLeft')
        await pg.evaluate(CLICKS)
        await pg.focus('.lee-present-strip [data-next]')
        for _ in range(3): await pg.keyboard.down('Enter')
        await pg.keyboard.up('Enter')
        out['enter_held'] = [await pg.evaluate(AT), await pg.evaluate(CLICKS)]
        await pg.focus('.lee-present-strip [data-prev]'); await pg.keyboard.press('Space')
        out['space_prev'] = [await pg.evaluate(AT), await pg.evaluate(CLICKS)]
        out['shift_space'] = [await pg.evaluate(AT), await pg.evaluate(CLICKS)]
        await pg.focus('.lee-present-strip [data-next]'); await pg.keyboard.press('Shift+Space')
        out['shift_space'] += [await pg.evaluate(AT), await pg.evaluate(CLICKS)]
        await pg.evaluate('() => lee.present.root.focus()')
        out['code_not_key'] = [await pg.evaluate(KEY, {'code': 'KeyB', 'key': 'x'}), await pg.evaluate(LOOK)]
        await pg.evaluate(KEY, {'code': 'KeyB', 'key': 'x'})
        out['browser_owned'] = [await pg.evaluate(KEY, {'code': c, 'key': c[-1].lower(), m: True}) for c in ('KeyW', 'KeyR', 'KeyL') for m in ('metaKey', 'ctrlKey')]
        before = await pg.evaluate(LOOK)
        out['ignored'] = [await pg.evaluate(KEY, o) for o in (
            {'code': 'KeyB', 'key': 'B', 'shiftKey': True}, {'code': 'KeyN', 'key': 'N', 'shiftKey': True}, {'code': 'KeyF', 'key': 'F', 'shiftKey': True},
            {'code': 'KeyB', 'key': 'b', 'altKey': True}, {'code': 'KeyB', 'key': 'b', 'modifierAltGraph': True}, {'code': 'KeyB', 'key': 'b', 'isComposing': True},
            {'code': 'KeyB', 'key': 'Process'}, {'code': 'KeyB', 'key': 'b', 'repeat': True})]
        out['ignored_look'] = [before, await pg.evaluate(LOOK)]
        await pg.evaluate(FIELDS)
        out['fields'] = {}
        for sel in ('input', 'textarea', 'select', '[data-nested]'):
            await pg.focus(f'.t-fields {sel}')
            if sel == '[data-nested]': await pg.evaluate("() => getSelection().collapse(document.querySelector('.t-fields [data-nested]').firstChild, 1)")
            was = await pg.evaluate(LOOK)
            # Space on a select opens the browser's own picker, which takes the keys after it
            for k in ('ArrowRight', 'PageDown', 'KeyB', 'KeyX', 'KeyN', 'KeyF') + (() if sel == 'select' else ('Space',)): await pg.keyboard.press(k)
            now = await pg.evaluate(LOOK)
            await pg.keyboard.press('Escape')
            out['fields'][sel] = [was, now, await pg.evaluate(LOOK)]
        out['typed'] = await pg.evaluate("() => [document.querySelector('.t-fields input').value, document.querySelector('.t-fields [data-nested]').textContent]")
        await pg.evaluate("() => document.querySelector('.t-fields').remove()")
        await _to(pg, 4)
        await pg.wait_for_function(f'() => ({SLIDER})()', timeout=20000)
        await pg.evaluate(f'() => ({SLIDER})().focus()')
        was = [await pg.evaluate(f'() => ({SLIDER})().value'), await pg.evaluate(LOOK)]
        for k in ('ArrowRight', 'KeyB', 'KeyX', 'Space'): await pg.keyboard.press(k)
        out['demo'] = was + [await pg.evaluate(f'() => ({SLIDER})().value'), await pg.evaluate(LOOK)]
        await pg.evaluate('() => { lee.present.root.focus(); ensureCellMounted(0).focus(); }')
        await pg.keyboard.type('zz'); await pg.keyboard.press('Backspace'); await pg.keyboard.press('Enter'); await pg.keyboard.press('KeyQ')
        out['editor'] = [src, await pg.evaluate('() => ensureCellMounted(0).state.doc.toString()'), await pg.evaluate('() => lee.present.root.contains(document.activeElement)')]
        return out
    out = asyncio.run(_real_page(go, tmp_path))
    assert out['interior'] == [1, 1]
    for (k, at, server), want in zip(out['walk'], [[1, 2], [1, 1]] * 4):
        assert at == server == want, (k, at, server)
    assert out['held'] == [[1, 2], [1, 2]], 'a held key moves once'
    at, clicks = out['enter_held']
    assert (at, clicks['next']) == ([1, 2], 1), ('Enter held on a focused button presses it once', out['enter_held'])
    assert out['space_prev'] == [[1, 1], {'prev': 1, 'next': 1}], 'Space on a focused button presses only the button'
    a0, c0, a1, c1 = out['shift_space']
    assert a1[1] - a0[1] == c1['next'] - c0['next'] <= 1 and c1['prev'] == c0['prev'], ('Shift+Space on a focused button never also moves back', out['shift_space'])
    prevented, look = out['code_not_key']
    assert prevented is False and look['blank'] and not look['laser'], ('the key is its e.code, not its e.key', out['code_not_key'])
    assert out['browser_owned'] == [True] * 6, 'Cmd or Ctrl with W, R and L stay with the browser'
    assert out['ignored'] == [True] * 7 + [False], out['ignored']
    b, a = out['ignored_look']
    assert a == b and not (a['blank'] or a['notes'] or a['full'] or a['laser']), out['ignored_look']
    for sel, (was, now, esc) in out['fields'].items():
        assert now['at'] == was['at'] and not (now['blank'] or now['laser'] or now['notes'] or now['full']), (sel, was, now)
        assert esc['focus'] == 'root', ('Esc leaves the field', sel, esc)
    assert out['typed'][0] != 'i' and out['typed'][1] != 'n', ('the keys reached the fields', out['typed'])
    v0, l0, v1, l1 = out['demo']
    assert v1 != v0 and l1['at'] == l0['at'] == [4, 0] and not (l1['blank'] or l1['laser']) and l1['focus'] == 'demo', out['demo']
    src, now, inside = out['editor']
    assert now == src and inside, ('no key reaches the editor under the presentation', out['editor'])

PROBE = '''(() => { const E = window.EventSource; if (!E) return;
  window.EventSource = class extends E { constructor(...a) { super(...a); window._leeES = this;
    queueMicrotask(() => this.addEventListener('state', () => (window._leeAtState ||= []).push(!!document.querySelector('.lee-stage > .lee-slide .stage-dot.on')))); } };
  window._leeShown = 0;
  const tick = () => { const c = document.querySelector('body[data-page="audience"] .lee-stage > .lee-slide');
    if (c && c.querySelector('.lee-slide-body') && !c.classList.contains('blank')) window._leeShown++;
    requestAnimationFrame(tick); };
  requestAnimationFrame(tick); })()'''

def test_esc_never_ends_the_presentation(tmp_path):
    "Esc closes one thing at a time, in the key map order, and gives focus back; nothing underneath sees it; F leaves full screen; no stray key ends the show."
    _nb(tmp_path/'deck.ipynb', KEY_CELLS)
    async def go(pg):
        out, esc = {}, {}
        await _open(pg, tmp_path/'deck.ipynb', 8)
        await pg.evaluate("""() => { const d = document.body.appendChild(document.createElement('details')); d.className = 'lee-dismissable'; d.id = 't-details';
          d.innerHTML = '<summary>s</summary>x'; d.open = true; }""")
        await _start(pg)
        async def press(name, key='Escape'):
            await pg.keyboard.press(key); await pg.wait_for_timeout(50); esc[name] = await pg.evaluate(LOOK)
        await pg.keyboard.press('KeyN'); await pg.keyboard.press('KeyX')
        await pg.focus('.lee-present-notes [data-close]')
        await press('notes')
        await press('laser')
        await _to(pg, 4)
        await pg.wait_for_function(f'() => ({SLIDER})()', timeout=20000)
        await pg.evaluate(f'() => ({SLIDER})().focus()')
        await press('demo')
        await press('nothing')
        await pg.keyboard.press('KeyN')
        await pg.evaluate('() => showHelp()'); await pg.wait_for_selector('.lee-modal')
        out['help'] = await pg.evaluate("() => ({top: document.querySelector('.lee-modal .lee-dim').textContent, notes: Object.fromEntries([...document.querySelectorAll('.lee-modal .lee-help-scope')].map(s => [s.querySelector('h4').firstChild.textContent, s.querySelector('.lee-help-note')?.textContent || '']))})")
        await press('modal')
        out['modal'] = await pg.evaluate("() => !!document.querySelector('.lee-modal')")
        await pg.keyboard.press('KeyX')
        await pg.keyboard.press('KeyF'); await pg.wait_for_function('() => !!document.fullscreenElement')
        await press('in_full')
        if await pg.evaluate('() => !!document.fullscreenElement'):
            await pg.keyboard.press('KeyF'); await pg.wait_for_function('() => !document.fullscreenElement')
        await pg.keyboard.press('KeyF'); await pg.wait_for_function('() => !!document.fullscreenElement')
        await pg.keyboard.press('KeyF'); await pg.wait_for_function('() => !document.fullscreenElement')
        await pg.keyboard.press('Escape'); esc['just_left'] = await pg.evaluate(LOOK)
        await pg.wait_for_timeout(450)
        await press('later')
        for k in ('Alt+KeyR', 'Alt+KeyW', 'Alt+KeyT', 'Slash', 'ControlOrMeta+Shift+KeyP'): await pg.keyboard.press(k)
        await pg.wait_for_timeout(300)
        out['stray'] = await pg.evaluate("() => [!!lee.present, document.querySelectorAll('.lee-present').length, !!document.querySelector('.lee-modal, #cp')]")
        out['under'] = await pg.evaluate("() => document.getElementById('t-details').open")
        out['deck'] = await pg.evaluate('() => fetch("/present/deck?k=" + lee.present.ak).then(r => r.status)')
        out['esc'] = esc
        return out
    out = asyncio.run(_real_page(go, tmp_path))
    e = out['esc']
    assert e['notes']['notes'] is False and e['notes']['laser'] is True and e['notes']['focus'] == 'notes', ('Esc closes Notes first', e['notes'])
    assert e['laser']['laser'] is False and e['laser']['notes'] is False and e['laser']['focus'] == 'notes', ('then the laser', e['laser'])
    assert e['demo']['focus'] == 'root' and e['demo']['at'] == [4, 0], ('then focus leaves the demo', e['demo'])
    assert e['nothing'] == e['demo'], 'with nothing open, nothing happens'
    assert out['modal'] is False and e['modal']['notes'] is True and e['modal']['focus'] == 'root', ('a dialog takes Esc for itself', e['modal'])
    assert e['in_full']['notes'] is True and e['in_full']['laser'] is True, ('Esc in full screen belongs to the browser', e['in_full'])
    assert e['just_left']['notes'] is True and e['just_left']['laser'] is True, ('Esc just after leaving full screen does nothing', e['just_left'])
    assert e['later']['notes'] is False and e['later']['laser'] is True, e['later']
    assert out['stray'] == [True, 1, False], out['stray']
    assert out['under'] is True, 'an Esc handler underneath the presentation acted'
    assert out['deck'] == 200
    h = out['help']
    assert h['top'] == 'Every key outside the present section can be rebound. Each of those keys also has a button.', h
    assert h['notes'].pop('present') == 'These keys work only during a presentation. They cannot be rebound. Laser and blank have no button.', h
    assert h['notes'] and not any(h['notes'].values()), h

LASER = [md('# Alpha\n\nbody a', 'slide', 'l0'), md('# Beta\n\nbody b', 'slide', 'l1'), md('# Gamma', 'slide', 'l2')]
BOX = "s => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; }"
DOTS = '''r => { const d = document.querySelector(r + ' .lee-slide > .stage-dot'), b = document.querySelector(r + ' .lee-slide > .stage-blank');
  return {on: !!d?.classList.contains('on'), shown: !!d && getComputedStyle(d).display !== 'none' && +getComputedStyle(d).opacity > 0 && d.classList.contains('on'),
          left: d?.style.left, top: d?.style.top, blank: document.querySelector(r + ' .lee-slide').classList.contains('blank'),
          card: b && getComputedStyle(b).display !== 'none' ? b.textContent : null}; }'''

def test_laser_and_blank_reach_both_windows(tmp_path):
    "The laser follows the scaled slide, coalesces behind a slow server and goes off on every way out; blank shows on both windows and survives a reconnect."
    _nb(tmp_path/'deck.ipynb', LASER)
    async def go(pg):
        out, moves = {}, []
        pg.on('request', lambda r: moves.append(json.loads(r.post_data)) if r.method == 'POST' and r.url.endswith('/present/move') else None)
        pts = lambda: [m for m in moves if m.get('t') == 'point']
        async def settle(n=None, quiet=.6):
            for _ in range(100):
                k = len(moves); await asyncio.sleep(quiet)
                if len(moves) == k and (n is None or k > n): return
            raise AssertionError('no new move reached the server, or the moves never stopped')
        await pg.context.add_init_script(PROBE)
        await pg.set_viewport_size({'width': 1000, 'height': 700})
        await _open(pg, tmp_path/'deck.ipynb', 3)
        await _start(pg)
        async with pg.context.expect_page() as pop:
            await pg.click('.lee-present-strip [data-audience]')
        aud = await pop.value
        await aud.wait_for_function('() => document.querySelector(".lee-stage .lee-slide")?.textContent.includes("Alpha")', timeout=20000)
        await pg.wait_for_function('() => document.querySelector(".lee-present-strip [data-conn]").textContent === "Audience window: connected"')
        await pg.evaluate('() => lee.present.root.focus()')
        x, y, w, h = await pg.evaluate(BOX, SLIDE)
        at = lambda fx, fy: (x + w*fx, y + h*fy)
        out['scale'] = await pg.evaluate("() => +getComputedStyle(document.querySelector('.lee-present .lee-stage')).getPropertyValue('--slide-scale')")
        await pg.keyboard.press('KeyX')
        n = len(moves); await pg.mouse.move(*at(.25, .75)); await settle(n)
        out['point'] = pts()[-1]
        await aud.wait_for_function("() => document.querySelector('.lee-slide > .stage-dot.on')")
        out['dots'] = [await pg.evaluate(DOTS, '.lee-present'), await aud.evaluate(DOTS, '.lee-stage')]
        async def slow(route): await asyncio.sleep(.5); await route.continue_()
        await pg.route('**/present/move', slow)
        n = len(pts())
        for i in range(30): await pg.mouse.move(*at(.1 + i*.02, .5))
        await settle(quiet=1.2)
        out['slow'] = [len(pts()) - n, pts()[-1]]
        await pg.unroute('**/present/move')
        n = len(moves)
        await pg.evaluate('''() => { const c = document.querySelector('.lee-present .lee-slide'), r = c.getBoundingClientRect();
          c.dispatchEvent(new PointerEvent('pointermove', {clientX: r.right + 40, clientY: r.top - 40, bubbles: true})); }''')
        await settle(n); out['clamp'] = moves[-1]
        off = {}
        async def way(name, act):
            n = len(moves); await pg.mouse.move(*at(.5, .5)); await settle(n)
            n = len(moves); await act(); await settle(n)
            off[name] = [moves[-1], await pg.evaluate('() => lee.present.root.classList.contains("lee-laser")')]
            await aud.wait_for_function("() => !document.querySelector('.lee-slide > .stage-dot.on')")
        sx, sy, sw, sh = await pg.evaluate(BOX, '.lee-present-strip')
        await way('leave', lambda: pg.mouse.move(sx + sw/2, sy + sh/2))
        await way('cancel', lambda: pg.evaluate("() => document.querySelector('.lee-present .lee-slide').dispatchEvent(new PointerEvent('pointercancel', {bubbles: true}))"))
        await way('blur', lambda: pg.evaluate("() => dispatchEvent(new Event('blur'))"))
        await way('esc', lambda: pg.keyboard.press('Escape'))
        await pg.keyboard.press('KeyX')
        await way('toggle', lambda: pg.keyboard.press('KeyX'))
        out['off'] = off
        await pg.keyboard.press('KeyX')
        n = len(moves); await pg.mouse.move(*at(.4, .4)); await settle(n)
        await pg.keyboard.press('KeyB')
        await aud.wait_for_function("() => document.querySelector('.lee-stage > .lee-slide').classList.contains('blank')")
        n = len(pts()); await pg.mouse.move(*at(.6, .6)); await pg.mouse.move(*at(.7, .3)); await asyncio.sleep(.5)
        out['blank'] = [await pg.evaluate(DOTS, '.lee-present'), await aud.evaluate(DOTS, '.lee-stage'), [m for m in pts()[n:] if 'x' in m]]
        await pg.keyboard.press('ArrowRight')
        await aud.wait_for_function("() => document.querySelector('.lee-stage > .lee-slide').textContent.includes('Beta')")
        await pg.set_viewport_size({'width': 900, 'height': 650}); await pg.wait_for_timeout(300)
        out['moved_blank'] = [await pg.evaluate(DOTS, '.lee-present'), await aud.evaluate(DOTS, '.lee-stage')]
        await aud.reload()
        await aud.wait_for_function("() => document.querySelector('.lee-stage > .lee-slide')?.textContent.includes('Beta')", timeout=20000)
        await aud.wait_for_timeout(300)
        out['reload'] = [await aud.evaluate(DOTS, '.lee-stage'), await aud.evaluate('() => window._leeShown')]
        await pg.keyboard.press('KeyB')
        await aud.wait_for_function("() => !document.querySelector('.lee-stage > .lee-slide').classList.contains('blank')")
        out['unblank'] = [await pg.evaluate(DOTS, '.lee-present'), await aud.evaluate(DOTS, '.lee-stage')]
        x, y, w, h = await pg.evaluate(BOX, SLIDE)
        for i in range(6): await pg.mouse.move(*at(.3 + i*.05, .5))
        await aud.wait_for_function("() => document.querySelector('.lee-slide > .stage-dot.on')")
        k = len(await aud.evaluate('() => window._leeAtState || []'))
        await aud.evaluate("() => { window._leeES.close(); window._leeES.dispatchEvent(new Event('error')); }")
        await aud.wait_for_function(f'() => (window._leeAtState || []).length > {k}', timeout=20000)
        out['again'] = await aud.evaluate('() => window._leeAtState.at(-1)')
        return out
    out = asyncio.run(_real_page(go, tmp_path))
    assert out['scale'] != 1, out['scale']
    p = out['point']
    assert abs(p['x'] - .25) < .01 and abs(p['y'] - .75) < .01 and set(p) == {'t', 'x', 'y', 'k'}, ('the point is relative to the scaled slide', p)
    assert all(len(str(v).split('.')[-1]) <= 4 for v in (p['x'], p['y'])), ('points are rounded', p)
    for d in out['dots']: assert d['shown'] and abs(float(d['left'].rstrip('%')) - p['x']*100) < .01, ('both windows show the dot', out['dots'])
    n, last = out['slow']
    assert 1 <= n <= 4 and abs(last['x'] - .68) < .01 and abs(last['y'] - .5) < .01, ('only the newest unsent point goes, behind a slow server', out['slow'])
    assert (out['clamp']['x'], out['clamp']['y']) == (1, 0), out['clamp']
    for name, (m, laser) in out['off'].items():
        assert m.get('off') is True, (name, m)
        assert laser is (name not in ('esc', 'toggle')), (name, laser)
    pd, ad, sent = out['blank']
    assert pd['blank'] and ad['blank'] and pd['card'] == ad['card'] == 'deck', ('blank shows on both windows', out['blank'])
    assert not pd['shown'] and not ad['shown'] and sent == [], ('blank hides the laser', out['blank'])
    assert all(d['blank'] for d in out['moved_blank']), 'a move and a resize keep blank'
    d, shown = out['reload']
    assert d['blank'] and not d['on'] and shown == 0, ('a reloaded audience is blank at once and shows no dot', out['reload'])
    assert not any(d['blank'] for d in out['unblank'])
    assert out['again'] is False, 'a reconnecting audience drops the dot it had'

def test_an_external_link_opens_one_tab_in_a_browser(tmp_path):
    "`window.open(..., 'noopener')` returns null even when the tab opened, so a browser also asked the server to open it: two tabs, the notes page among them."
    async def go(pg):
        await pg.evaluate("""() => { window._posts = []; const f = window.fetch;
            window.fetch = (u, o) => { if (String(u).includes('/browser/external')) window._posts.push(String(u)); return f(u, o); }; }""")
        async with pg.context.expect_page() as popup:
            await pg.evaluate("u => openExternal(u)", 'about:blank#leela-external-test')
        await popup.value
        await pg.wait_for_timeout(300)
        return await pg.evaluate('() => window._posts')
    assert asyncio.run(_real_page(go, tmp_path, 'chromium')) == []

import re, socket, sys, threading   # noqa: E402
from playwright.async_api import async_playwright   # noqa: E402
from test_web_slow import _free_port, _launch, _started, fake_model   # noqa: E402
from leela.app import ide_app   # noqa: E402
from leela.workspace import Workspace   # noqa: E402

RELOAD = KEY_CELLS[:7]
#: frames in which the presenter canvas shows a slide while it is not blank
LIT = '''(() => { window._leeLit = 0; const tick = () => { const c = document.querySelector('.lee-present .lee-slide:not(.lee-measure)');
  if (c && c.querySelector('.lee-slide-body') && !c.classList.contains('blank')) window._leeLit++; requestAnimationFrame(tick); };
  requestAnimationFrame(tick); })()'''
#: every room stream the page opened, to count the ones still open
ROOMS = '''(() => { const E = window.EventSource; if (!E) return; window._leeRooms = [];
  window.EventSource = class extends E { constructor(...a) { super(...a); if (String(a[0]).includes('/present/room')) window._leeRooms.push(this); } }; })()'''
#: the server's place and look, read from the `state` of a new room stream after this presenter's posts
STATE = '''async () => { const p = lee.present; await p.chain; return await new Promise(ok => { const es = new EventSource('/present/room?k=' + p.ak);
  es.addEventListener('state', e => { es.close(); const d = JSON.parse(e.data); ok({at: d.at, theme: d.look.theme}); }); }); }'''
#: what `/present/events` says first: the live id, and the count of room streams
LIVE = '''() => new Promise(ok => { const es = new EventSource('/present/events'), got = {};
  setTimeout(() => { es.close(); ok({stalled: true}); }, 8000);
  es.addEventListener('presentation', e => { got.id = JSON.parse(e.data).id; if (!got.id) { es.close(); ok(got); } });
  es.addEventListener('audience', e => { got.n = JSON.parse(e.data).n; es.close(); ok(got); }); })'''
OFFER = "() => { const m = document.querySelector('.lee-modal'); return m && [m.querySelector('.lee-mhead').textContent, m.querySelector('.lee-dialogcopy').textContent, m.querySelector('#dialogyes').textContent]; }"
AUD_BLANK = "() => document.querySelector('.lee-stage > .lee-slide')?.classList.contains('blank')"

async def _audience(pg, text):
    async with pg.context.expect_page() as pop:
        await pg.click('.lee-present-strip [data-audience]')
    aud = await pop.value
    await aud.wait_for_function(f'() => document.querySelector(".lee-stage .lee-slide")?.textContent.includes("{text}")', timeout=20000)
    await pg.wait_for_function('() => document.querySelector(".lee-present-strip [data-conn]").textContent === "Audience window: connected"')
    return aud

async def _tab(pg, copy=False):
    "A second IDE tab of the same browser; `copy` opens it with an opener, so the browser copies this tab's `sessionStorage` into it."
    async with pg.context.expect_page() as pop:
        await pg.evaluate('c => { window.open(location.href, "_blank", c ? "" : "noopener"); }', copy)
    t = await pop.value
    await t.wait_for_load_state('networkidle'); await t.wait_for_function('window.lee && lee.keys.length', timeout=20000)
    return t

def test_a_reloaded_presenter_comes_back_as_the_server_holds_it(tmp_path):
    "Mid-beat, blank, a size and a look the presenter never drew: a reload shows the server's state, posts nothing, keeps the stored deck, and the audience follows the next key."
    _nb(tmp_path/'deck.ipynb', RELOAD)
    async def go(pg):
        out, posts = {}, []
        for s in (PROBE, LIT): await pg.context.add_init_script(s)
        await _open(pg, tmp_path/'deck.ipynb', 7)
        await _start(pg)
        aud = await _audience(pg, 'One')
        await pg.evaluate('() => lee.present.root.focus()')
        await pg.keyboard.press('ArrowRight'); await pg.keyboard.press('ArrowRight')
        await pg.click('.lee-present-strip [data-bigger]')
        await pg.evaluate('() => applyTheme("leela:dark:relaxed")')
        await pg.wait_for_function('async () => (await (' + STATE + ')()).theme === "leela:dark:relaxed"')
        # the server's last acknowledged state differs from what this page drew: blank, size 13 and another look
        await pg.evaluate('''async () => { const p = lee.present; await p.chain; const k = p.key, j = b => fetch(b[0], {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...b[1], k})});
          await j(['/present/at', {slide: 's2', step: 1, blank: true, size: 13}]); await j(['/present/move', {t: 'look', theme: 'cursor:dark:tight'}]); }''')
        await aud.wait_for_function(AUD_BLANK)
        out['before'] = await pg.evaluate(STATE)
        key, t0 = await pg.evaluate('() => lee.present.key'), await pg.evaluate('() => Date.now()')
        _nb(tmp_path/'deck.ipynb', RELOAD + [md('# Added on disk', 'slide', 'k9')])
        pg.on('request', lambda r: posts.append(r.url) if r.method == 'POST' and '/present/' in r.url else None)
        await pg.reload()
        await pg.wait_for_function(READY, timeout=20000)
        await pg.wait_for_timeout(600)
        out['after'] = await pg.evaluate('''() => { const p = lee.present; return {at: [p.at.slide, p.at.step], blank: p.root.querySelector('.lee-slide').classList.contains('blank'),
          text: p.text, look: p.look, slides: p.deck.slides.length, where: p.root.querySelector('[data-where]').textContent, lit: window._leeLit,
          conn: p.root.querySelector('[data-conn]').textContent}; }''')
        out['same_key'], out['older'] = await pg.evaluate('() => lee.present.key') == key, await pg.evaluate('() => lee.present.started') < t0
        out['posts'], out['server'] = list(posts), await pg.evaluate(STATE)
        await aud.evaluate('() => sessionStorage.clear()')   # the audience key comes from the address, not from storage
        await aud.reload()
        await aud.wait_for_function(f'() => ({AUD_BLANK})() && document.querySelector(".lee-stage .lee-slide").textContent.includes("Two")', timeout=20000)
        await aud.wait_for_timeout(300)
        out['aud_shown'] = await aud.evaluate('() => window._leeShown')
        await pg.evaluate('() => lee.present.root.focus()')
        await pg.keyboard.press('KeyB'); await pg.keyboard.press('ArrowRight')
        await aud.wait_for_function(f'() => !({AUD_BLANK})() && !document.querySelector(".lee-stage .lee-frag-hidden") && document.querySelector(".lee-stage .lee-slide").textContent.includes("two b")')
        out['next'] = await pg.evaluate(STATE)
        return out
    out = asyncio.run(_real_page(go, tmp_path))
    assert out['before'] == {'at': {'slide': 's2', 'step': 1, 'blank': True, 'size': 13}, 'theme': 'cursor:dark:tight'}, out['before']
    a = out['after']
    assert a['at'] == [1, 1] and a['blank'] and a['text'] == 1.3 and a['look'] == 'cursor:dark:tight', a
    assert a['slides'] == 4 and a['where'] == '2 / 4 · step 2 / 3', ('navigation comes from the stored deck, not the changed notebook', a)
    assert a['lit'] == 0, 'the reloaded presenter never drew the slide unblanked'
    assert a['conn'] == 'Audience window: connected' and out['same_key'] and out['older'], out
    assert out['posts'] == [u for u in out['posts'] if u.endswith('/present/resume')] and len(out['posts']) == 1, ('a reload writes nothing first', out['posts'])
    assert out['server'] == out['before'], 'the server keeps blank, size and look'
    assert out['aud_shown'] == 0, 'a reloaded audience never paints a slide while blank'
    assert out['next'] == {'at': {'slide': 's2', 'step': 2, 'blank': False, 'size': 13}, 'theme': 'cursor:dark:tight'}, out['next']

def test_another_tab_gets_presenter_control_only_by_taking_over(tmp_path):
    "A new IDE tab gets nothing; a tab that copied this tab's storage asks first; Take over moves the presenter screen and closes the old one."
    _nb(tmp_path/'deck.ipynb', LASER)
    async def go(pg):
        out = {}
        await _open(pg, tmp_path/'deck.ipynb', 3)
        await _start(pg)
        fresh = await _tab(pg); await fresh.wait_for_timeout(1500)
        out['fresh'] = await fresh.evaluate("() => [!!document.querySelector('.lee-present'), !!document.querySelector('.lee-modal')]")
        await fresh.close()
        cp = await _tab(pg, copy=True)
        await cp.wait_for_selector('.lee-modal #dialogyes', timeout=20000)
        out['offer'] = [await cp.evaluate(OFFER), await cp.evaluate("() => !!document.querySelector('.lee-present')")]
        await pg.evaluate('() => lee.present.root.focus()'); await pg.keyboard.press('ArrowRight')
        out['still'] = (await pg.evaluate(SERVER))[:2]
        await cp.click('#dialogyes')
        await cp.wait_for_function(READY, timeout=20000)
        out['taken'] = await cp.evaluate(AT)
        await pg.wait_for_function('() => !lee.present', timeout=20000)
        await pg.wait_for_function(f'() => ({STATUS})() === "The presentation moved to another tab."')
        await cp.evaluate('() => lee.present.root.focus()'); await cp.keyboard.press('ArrowRight')
        out['moves'] = (await cp.evaluate(SERVER))[:2]
        return out
    out = asyncio.run(_real_page(go, tmp_path))
    assert out['fresh'] == [False, False], 'a new tab has no presenter key and asks nothing'
    (head, copy, yes), shown = out['offer']
    assert head == 'Present from this tab?' and yes == 'Take over' and 'other tab stops presenting' in copy and not shown, out['offer']
    assert out['still'] == [1, 0], 'the first tab keeps control while the copy asks'
    assert out['taken'] == [1, 0] and out['moves'] == [2, 0]

def test_a_stale_presenter_closes_on_reconnect_when_it_missed_the_end(tmp_path):
    "A presenter that slept through the replacing start learns the new id when its event stream connects again, and closes without touching the new show."
    _nb(tmp_path/'deck.ipynb', LASER)
    async def go(pg):
        out = {}
        await _open(pg, tmp_path/'deck.ipynb', 3)
        await _start(pg)
        await pg.evaluate('() => lee.present.events.close()')
        other = await _tab(pg)
        await _open(other, tmp_path/'deck.ipynb', 3); await _start(other)
        await other.evaluate('() => lee.present.root.focus()'); await other.keyboard.press('ArrowRight')
        out['other'] = (await other.evaluate(SERVER))[:2]
        out['missed'] = await pg.evaluate('() => !!lee.present')
        await pg.evaluate("() => lee.present.events.dispatchEvent(new Event('error'))")
        await pg.wait_for_function('() => !lee.present', timeout=20000)
        await pg.wait_for_function(f'() => ({STATUS})() === "Another presentation started."')
        await pg.wait_for_timeout(500)
        out['offer'] = await pg.evaluate(OFFER)
        out['kept'] = [(await other.evaluate(SERVER))[:2], await other.evaluate('() => !!lee.present')]
        out['records'] = await pg.evaluate('() => Object.keys(sessionStorage).filter(k => k.startsWith("lee-present:"))')
        # a stale record, as a tab holds after a sleep: the reload asks once, gets 403, drops the record and touches nothing
        await pg.evaluate('''() => sessionStorage.setItem('lee-present:0123456789abcdef', JSON.stringify({key: '0'.repeat(32), boot: '', path: '', at: {slide: 2, step: 0}}))''')
        await pg.reload(); await pg.wait_for_function('window.lee && lee.keys.length'); await pg.wait_for_timeout(1500)
        out['stale'] = await pg.evaluate("() => [!!lee.present, Object.keys(sessionStorage).filter(k => k.startsWith('lee-present:')), !!document.querySelector('.lee-modal')]")
        out['kept'] += [(await other.evaluate(SERVER))[:2], await other.evaluate('() => !!lee.present')]
        return out
    out = asyncio.run(_real_page(go, tmp_path))
    assert out['other'] == [1, 0] and out['missed'] is True, out
    assert out['offer'] is None and out['records'] == [], 'no restart is offered while another presentation is live, and the record is gone'
    assert out['stale'] == [False, [], False], out['stale']
    assert out['kept'] == [[1, 0], True, [1, 0], True]

def test_reconnect_storms_keep_one_audience_connection(tmp_path):
    "Many errors at once give one room stream; a failed deck fetch is not a bad link; nothing connects after the end; the count stays right."
    _nb(tmp_path/'deck.ipynb', LASER)
    async def go(pg):
        out, failed = {}, []
        for s in (PROBE, ROOMS): await pg.context.add_init_script(s)
        await _open(pg, tmp_path/'deck.ipynb', 3)
        await _start(pg)
        aud = await _audience(pg, 'Alpha')
        async def once(route):
            if failed: return await route.continue_()
            failed.append(1); await route.fulfill(status=503, body='busy')
        await aud.route(re.compile(r'/present/deck\?'), once)
        await aud.evaluate("() => { const s = window._leeES; s.close(); for (let i = 0; i < 6; i++) s.dispatchEvent(new Event('error')); }")
        await aud.wait_for_timeout(4000)
        out['storm'] = [*await aud.evaluate("() => [window._leeRooms.filter(e => e.readyState !== 2).length, !!document.querySelector('.lee-end')]"), len(failed)]
        # checked here: leaked streams take the browser's six connections to the host, and every later step would stall
        assert out['storm'] == [1, False, 1], ('one room stream after the storm, and a 503 deck is no bad link', out['storm'])
        out['live'] = await pg.evaluate(LIVE)
        await pg.evaluate('() => lee.present.root.focus()'); await pg.keyboard.press('ArrowRight')
        await aud.wait_for_function("() => document.querySelector('.lee-stage .lee-slide').textContent.includes('Beta')")
        await _end(pg)
        await aud.wait_for_function("() => document.querySelector('.lee-end')")
        n = await aud.evaluate('() => window._leeRooms.length')
        await aud.evaluate("() => window._leeRooms.at(-1).dispatchEvent(new Event('error'))")
        await aud.wait_for_timeout(2500)
        out['after_end'] = await aud.evaluate(f"() => [window._leeRooms.filter(e => e.readyState !== 2).length, window._leeRooms.length - {n}]")
        out['card'] = await aud.text_content('.lee-end')
        return out
    out = asyncio.run(_real_page(go, tmp_path))
    assert out['live'] == {'id': out['live']['id'], 'n': 1}, out['live']
    assert out['after_end'] == [0, 0] and 'The presentation has ended.' in out['card'], out

def test_a_lost_presenter_key_says_so_and_offers_a_deliberate_restart(tmp_path):
    "With the tab's storage cleared, a reload cannot control the live show: it says so, changes nothing, and Start again begins a new one at the same slide."
    _nb(tmp_path/'deck.ipynb', LASER)
    async def go(pg):
        out = {}
        await _open(pg, tmp_path/'deck.ipynb', 3)
        await _start(pg)
        await pg.evaluate('() => lee.present.root.focus()'); await pg.keyboard.press('ArrowRight')
        await pg.evaluate(SERVER)
        id0 = await pg.evaluate('() => lee.present.id')
        await pg.evaluate('() => sessionStorage.clear()')
        await pg.reload(); await pg.wait_for_function('window.lee && lee.keys.length')
        await pg.wait_for_selector('.lee-modal #dialogyes', timeout=20000)
        out['offer'] = [await pg.evaluate(OFFER), await pg.evaluate('() => !!lee.present'), (await pg.evaluate(LIVE))['id'] == id0]
        await pg.click('#dialogyes')
        await pg.wait_for_function(READY, timeout=20000)
        out['again'] = [await pg.evaluate(AT), await pg.evaluate('() => lee.present.id') != id0]
        return out
    out = asyncio.run(_real_page(go, tmp_path))
    (head, copy, yes), shown, live = out['offer']
    assert head == 'This tab lost its presenter key' and yes == 'Start again' and 'from slide 2' in copy and not shown and live, out['offer']
    assert out['again'] == [[1, 0], True]

def _serve_loop(ws, port):
    "`_serve` with its loop kept, so a test can drop every open connection the way a stopped server does."
    import uvicorn
    srv, box = uvicorn.Server(uvicorn.Config(ide_app(ws), host='127.0.0.1', port=port, log_level='error')), {}
    async def main(): box['loop'] = asyncio.get_running_loop(); await srv.serve()
    threading.Thread(target=asyncio.run, args=(main(),), daemon=True).start()
    return srv, box

def _listening(port):
    with socket.socket() as s: return s.connect_ex(('127.0.0.1', port)) == 0

async def _restartable(fn, root):
    "`_real_page` whose `fn(pg, restart)` can stop the server and start a new one on the same port, as a restart of Leela does."
    (root/'.venv').symlink_to(Path(sys.prefix))
    wss, port, cur = [], _free_port(), {}
    async def up():
        ws = Workspace(roots=[str(root)], approvals='auto'); fake_model(ws); wss.append(ws)
        cur['srv'], cur['box'] = _serve_loop(ws, port); await _started(cur['srv'])
    async def restart():
        srv, loop = cur['srv'], cur['box']['loop']
        srv.should_exit = True
        for _ in range(500):
            if not _listening(port): break
            await asyncio.sleep(.02)
        # no new connection reaches it now; the open streams drop, as they do when the process ends
        loop.call_soon_threadsafe(lambda: [c.transport.abort() for c in list(srv.server_state.connections)])
        await asyncio.sleep(.5); await up()
    await up()
    try:
        async with async_playwright() as pw:
            b = await _launch(pw)
            try:
                pg = await b.new_page()
                await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
                await pg.wait_for_function('window.lee && lee.keys.length')
                return await fn(pg, restart)
            finally: await b.close()
    finally:
        cur['srv'].should_exit = True
        for ws in wss: ws.shutdown_now()

def test_a_server_restart_says_so_in_both_windows(tmp_path):
    "The restarted server holds no show: the presenter closes at once and offers Start again after a confirmed 410; the audience says Leela restarted."
    _nb(tmp_path/'deck.ipynb', LASER)
    async def go(pg, restart):
        out = {}
        await _open(pg, tmp_path/'deck.ipynb', 3)
        await _start(pg)
        aud = await _audience(pg, 'Alpha')
        await pg.evaluate('() => lee.present.root.focus()'); await pg.keyboard.press('ArrowRight')
        await pg.evaluate(SERVER)
        id0 = await pg.evaluate('() => lee.present.id')
        await restart()
        await pg.wait_for_selector('.lee-modal #dialogyes', timeout=30000)
        out['pres'] = [await pg.evaluate(OFFER), await pg.evaluate('() => !!lee.present')]
        await aud.wait_for_function("() => document.querySelector('.lee-end')", timeout=30000)
        out['aud'] = await aud.text_content('.lee-end')
        await pg.click('#dialogyes')
        await pg.wait_for_function(READY, timeout=20000)
        out['again'] = [await pg.evaluate(AT), await pg.evaluate('() => lee.present.id') != id0]
        return out
    out = asyncio.run(_restartable(go, tmp_path))
    (head, copy, yes), shown = out['pres']
    assert head == 'Leela restarted' and 'from slide 2' in copy and 'audience window must open again' in copy and yes == 'Start again' and not shown, out['pres']
    assert 'The presentation has ended.' in out['aud'] and 'Leela restarted' in out['aud'], out['aud']
    assert out['again'] == [[1, 0], True]

RUN_CELLS = [md('# Run', 'slide', 'r0'), code("import time\nfor i in range(4):\n    print('tick', i, flush=True)\n    time.sleep(0.8)", '-', 'r1'),
             md('# Fail', 'slide', 'r2'), code("n = globals().get('n', 0) + 1\nprint('before', n, flush=True)\nimport time; time.sleep(0.6)\nraise ValueError(f'RUN-{n}')", '-', 'r3'),
             md('# Loop', 'slide', 'r4'), code('while True: pass', '-', 'r5'),
             md('# Other', 'slide', 'r6'), code("print('other done')", '-', 'r7', [{'output_type': 'stream', 'name': 'stdout', 'text': 'OLD-OUT\n'}]),
             md('# Die', 'slide', 'r8'), code('import os\nos._exit(1)', '-', 'r9'),
             md('# Big', 'slide', 'r10'), code("from IPython.display import HTML, display\ndisplay(HTML('<script>window.hit = 1</script><b>BOLD-OUT</b>'))\nprint('<\\\\' * 150000)", '-', 'r11')]
AUD_HAS = "s => !!document.querySelector('.lee-stage > .lee-slide')?.textContent.includes(s)"
PRES_HAS = "s => !!document.querySelector('.lee-present .lee-slide:not(.lee-measure)')?.textContent.includes(s)"
AUD_TEXT = "() => document.querySelector('.lee-stage > .lee-slide').textContent"
#: text in an output box, not in the code above it
AUD_OUT = "s => [...document.querySelectorAll('.lee-stage > .lee-slide .lee-out')].some(e => e.textContent.includes(s))"
PRES_OUT = "s => [...document.querySelectorAll('.lee-present .lee-slide:not(.lee-measure) .lee-out')].some(e => e.textContent.includes(s))"
ERRP = "() => { const e = document.querySelector('.lee-present-err'); return e && !e.hidden ? e.textContent : ''; }"
#: the output of each code cell the server holds, from the `state` of a new room stream
OUTS = '''async () => { const p = lee.present; await p.chain; return await new Promise(ok => { const es = new EventSource('/present/room?k=' + p.ak);
  es.addEventListener('state', e => { es.close(); ok(Object.fromEntries(JSON.parse(e.data).outs.map(o => [o.cell, o.html]))); }); }); }'''

def _disk(*ps): return [(p.read_bytes(), p.stat().st_mtime_ns) for p in ps]
async def _run(pg, cell): await pg.click(f'.lee-present-strip [data-run="{cell}"]')
async def _outs(pg, cond, t=60):
    for _ in range(int(t*2)):
        if cond(o := await pg.evaluate(OUTS)): return o
        await asyncio.sleep(.5)
    raise AssertionError(f'the server never held the output: {o}')

def test_a_run_in_a_presentation_writes_no_file_and_streams_to_the_room(tmp_path):
    "Run in a show runs the live text and saves nothing, with autosave on in every mode; output streams to the room; a failure keeps its traceback private."
    deck, empty = tmp_path/'deck.ipynb', tmp_path/'empty.ipynb'
    _nb(deck, RUN_CELLS); empty.touch()
    async def go(pg):
        out, saves = {}, []
        pg.on('request', lambda r: saves.append(r.url) if r.method == 'POST' and 'save' in r.url else None)
        await _open(pg, deck, len(RUN_CELLS))
        await pg.evaluate('''() => { lee.filePrefs.autoSave = 'off'; const v = ensureCellMounted(6);
          v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: '# Other\\n\\nUNSAVED-EDIT'}}); }''')
        await pg.wait_for_function("() => document.querySelector('.lee-tab.active.dirty')")
        out['before'] = _disk(deck, empty)
        await _start(pg)
        await pg.evaluate('''async () => { const f = lee.filePrefs, wait = ms => new Promise(r => setTimeout(r, ms));
          Object.assign(f, {autoSave: 'afterDelay', autoSaveDelay: 100}); markDirty(); await wait(600);
          f.autoSave = 'onFocusChange'; document.querySelector('.cm-editor').dispatchEvent(new FocusEvent('focusout', {bubbles: true})); await wait(300);
          f.autoSave = 'onWindowChange'; dispatchEvent(new Event('blur')); await wait(300); f.autoSave = 'afterDelay'; }''')
        aud = await _audience(pg, 'Run')
        await _run(pg, 'r1')
        await aud.wait_for_function(AUD_HAS, arg='tick 0', timeout=60000)
        out['streaming'] = [await aud.evaluate(AUD_HAS, 'tick 3'), await pg.evaluate('''() => !document.querySelector('.lee-present-strip [data-stop="r1"]').hidden''')]
        await aud.wait_for_function(AUD_HAS, arg='tick 3', timeout=60000)
        await _to(pg, 1)
        await _run(pg, 'r3')
        await pg.wait_for_function(f'() => ({ERRP})().includes("RUN-1")', timeout=60000)
        await aud.wait_for_function(AUD_HAS, arg='before 1')
        out['room'], out['panel'] = await aud.evaluate(AUD_TEXT), await pg.evaluate(ERRP)
        out['pres'] = await pg.evaluate("() => document.querySelector('.lee-present .lee-slide:not(.lee-measure)').textContent")
        await _to(pg, 5)
        await _run(pg, 'r11')
        await aud.wait_for_function(AUD_OUT, arg='Output is too long for the room screen.', timeout=60000)
        out['big'] = [await aud.evaluate(AUD_OUT, 'BOLD-OUT'), await aud.evaluate('() => window.hit'), await pg.evaluate(PRES_OUT, 'Output is too long for the room screen.'),
                      await aud.evaluate("() => document.querySelector('.lee-stage > .lee-slide .lee-out').textContent.length")]
        await pg.wait_for_timeout(1500)
        out['disk'], out['pref'], out['saves'] = _disk(deck, empty), await pg.evaluate('() => lee.filePrefs.autoSave'), list(saves)
        return out
    out = asyncio.run(_real_page(go, tmp_path))
    assert out['streaming'] == [False, True], ('the room sees the first line while the cell still runs, and Stop shows', out['streaming'])
    assert 'before 1' in out['room'] and not any(x in out['room'] or x in out['pres'] for x in ('RUN-1', 'Traceback', 'ValueError: ')), out['room']
    assert 'ValueError: RUN-1' in out['panel'] and 'The room cannot see this error.' in out['panel'], out['panel']
    assert out['disk'] == out['before'], 'no Run, autosave or audience window wrote the notebook or the placeholder'
    assert out['saves'] == [] and out['pref'] == 'afterDelay', (out['saves'], out['pref'])
    bold, hit, clipped, n = out['big']
    assert bold is True and hit is None and clipped is True and n < 70000, ('a script in output never runs, and long output is clipped on both screens', out['big'])

def test_a_zero_byte_notebook_runs_in_a_presentation_and_stays_zero_bytes(tmp_path):
    "Run in a show does not make a zero-byte notebook, or any other placeholder, into valid JSON."
    blank, other = tmp_path/'blank.ipynb', tmp_path/'other.ipynb'; blank.touch(); other.touch()
    async def go(pg):
        await _open(pg, blank, 1)
        await pg.evaluate('''() => { const v = ensureCellMounted(0); v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: "print('blank ran')"}}); }''')
        await _start(pg)
        await pg.click('.lee-present-strip [data-run]')
        await pg.wait_for_function(PRES_OUT, arg='blank ran', timeout=60000)
        await pg.wait_for_timeout(500)
        return [blank.stat().st_size, other.stat().st_size]
    assert asyncio.run(_real_page(go, tmp_path)) == [0, 0]

def test_stop_show_error_restart_and_a_dead_kernel(tmp_path):
    "Show error shows the last failed run only; Stop ends a long cell; a restart, and Stop on a cell whose kernel died, clear every code cell on both screens."
    _nb(tmp_path/'deck.ipynb', RUN_CELLS)
    async def go(pg):
        out = {}
        await _open(pg, tmp_path/'deck.ipynb', len(RUN_CELLS))
        await _start(pg)
        aud = await _audience(pg, 'Run')
        await _to(pg, 1)
        await _run(pg, 'r3')
        await pg.wait_for_function(f'() => ({ERRP})().includes("RUN-1")', timeout=60000)
        g1 = await pg.evaluate('() => lee.present.err.gen')
        await _run(pg, 'r3')
        out['rerun_panel'] = await pg.evaluate(ERRP)
        await pg.wait_for_function(f'() => ({ERRP})().includes("RUN-2")', timeout=60000)
        out['late'] = await pg.evaluate('''g => fetch('/present/show-error', {method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({k: lee.present.key, cell: 'r3', gen: g})}).then(r => r.json())''', g1)
        await pg.click('.lee-present-err [data-show-error]')
        await aud.wait_for_function(AUD_HAS, arg='RUN-2')
        out['shown'] = await aud.evaluate(AUD_TEXT)
        await _to(pg, 2)
        await _run(pg, 'r5')
        await pg.wait_for_selector('.lee-present-strip [data-stop="r5"]:not([hidden])')
        out['run_off'] = await pg.evaluate('''() => document.querySelector('.lee-present-strip [data-run="r5"]').disabled''')
        await pg.wait_for_timeout(800)
        await pg.click('.lee-present-strip [data-stop="r5"]')
        await pg.wait_for_function(f'() => ({ERRP})().includes("KeyboardInterrupt")', timeout=30000)
        await pg.wait_for_function('''() => !document.querySelector('.lee-present-strip [data-run="r5"]').disabled && document.querySelector('.lee-present-strip [data-stop="r5"]').hidden''')
        await _to(pg, 3)
        await aud.wait_for_function(AUD_HAS, arg='OLD-OUT')
        await pg.evaluate('() => ACTIONS.restart()')
        await aud.wait_for_function(f'() => !({AUD_HAS})("OLD-OUT")', timeout=30000)
        out['restart'] = [await pg.evaluate(ERRP), await pg.evaluate(PRES_HAS, 'OLD-OUT'), await _outs(pg, lambda o: o.get('r3') == '')]
        await _run(pg, 'r7')
        await aud.wait_for_function(AUD_OUT, arg='other done', timeout=60000)
        await _to(pg, 4)
        await _run(pg, 'r9')
        # kunda does not see the kernel process go during a run, so the run waits; Stop finds the kernel gone and restarts it by force
        await pg.wait_for_selector('.lee-present-strip [data-stop="r9"]:not([hidden])')
        await pg.wait_for_timeout(1500)
        await pg.click('.lee-present-strip [data-stop="r9"]')
        out['dead'] = await _outs(pg, lambda o: o.get('r7') == '')
        await pg.evaluate('() => lee.present.root.focus()'); await pg.keyboard.press('ArrowLeft')
        await aud.wait_for_function(AUD_HAS, arg='Other')
        out['dead_room'], out['dead_pres'] = await aud.evaluate(AUD_OUT, 'other done'), await pg.evaluate(PRES_OUT, 'other done')
        return out
    out = asyncio.run(_real_page(go, tmp_path))
    assert out['rerun_panel'] == '', 'a new run of the cell closes the old error'
    assert out['late'] == {'ok': True, 'stale': True}, out['late']
    assert 'RUN-2' in out['shown'] and 'RUN-1' not in out['shown'], out['shown']
    assert out['run_off'] is True
    panel, old, outs = out['restart']
    assert panel == '' and old is False and set(outs.values()) == {''} and {'r1', 'r3', 'r5', 'r7', 'r9'} <= set(outs), out['restart']
    assert out['dead']['r7'] == '' and out['dead_room'] is False and out['dead_pres'] is False, out

def test_output_for_another_slide_and_every_reconnect_get_the_latest(tmp_path):
    "Output that arrives while its slide is away shows when it returns; a reloaded audience and a reloaded presenter get the latest; a changed cell cannot run."
    _nb(tmp_path/'deck.ipynb', RUN_CELLS)
    async def go(pg):
        out = {}
        await _open(pg, tmp_path/'deck.ipynb', len(RUN_CELLS))
        await _start(pg)
        aud = await _audience(pg, 'Run')
        await _run(pg, 'r1')
        await aud.wait_for_function(AUD_HAS, arg='tick 0', timeout=60000)
        await _to(pg, 1)
        await aud.wait_for_function(AUD_HAS, arg='Fail')
        await aud.reload()
        await aud.wait_for_function(AUD_HAS, arg='Fail', timeout=20000)
        await _outs(pg, lambda o: 'tick 3' in o.get('r1', ''))
        await pg.evaluate('() => lee.present.root.focus()'); await pg.keyboard.press('ArrowLeft')
        await aud.wait_for_function(AUD_HAS, arg='tick 3')
        out['back'] = await pg.evaluate(PRES_HAS, 'tick 3')
        await _run(pg, 'r1')
        await aud.wait_for_function(f'() => ({AUD_HAS})("tick 0") && !({AUD_HAS})("tick 3")', timeout=60000)
        await aud.reload()
        await aud.wait_for_function(AUD_HAS, arg='tick ', timeout=20000)
        out['aud_reload'] = await aud.evaluate(AUD_TEXT)
        await pg.reload()
        await pg.wait_for_function(READY, timeout=20000)
        await aud.wait_for_function(AUD_HAS, arg='tick 3', timeout=60000)
        await pg.wait_for_function(PRES_HAS, arg='tick 3', timeout=30000)
        await pg.evaluate('''() => { const v = ensureCellMounted(7); v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: "print('changed')"}}); }''')
        await _to(pg, 3)
        out['stale'] = await pg.evaluate('''() => { const b = document.querySelector('.lee-present-strip [data-run="r7"]'); return [b.disabled, b.title]; }''')
        return out
    out = asyncio.run(_real_page(go, tmp_path))
    assert out['back'] is True
    assert 'tick 0' in out['aud_reload'] and 'tick 3' not in out['aud_reload'], out['aud_reload']
    assert out['stale'][0] is True and 'changed' in out['stale'][1], out['stale']

DEMO2 = demo('d2', title='Weights', state={'x': 2}, blocks=[slider('x', label='x', min=0, max=4, step=1),
             gate('g1', 'Which one?', ['one', 'two'], is_('two'), again=True), readout('x is {x}')])
PSHADOW = "s => document.querySelector('.lee-present .lee-slide:not(.lee-measure) .lee-rupaka')?.shadowRoot?.querySelector(s)"
SLIDE_TO = f'''v => {{ const i = ({PSHADOW})('input[type=range]'); i.value = v; i.dispatchEvent(new Event('input', {{bubbles: true}})); }}'''
LOCK = f'''() => {{ const g = ({PSHADOW})('.rk-gate'); [...g.querySelectorAll('.opts button')].find(x => x.textContent.startsWith('two')).click(); g.querySelector('button.go').click(); }}'''
AGAIN = f'''() => [...({PSHADOW})('.rk-gate').querySelectorAll('button')].find(x => x.textContent === 'Try another').click()'''

def test_a_demo_is_mirrored_and_its_answers_follow_the_settle(tmp_path):
    "The presenter's own demo drives the room copy; answers go only after the gate settles; Try another reopens the room's gate; a reload restores both."
    _nb(tmp_path/'deck.ipynb', [md(f'# Demo\n\n```rupaka\n{json.dumps(DEMO2)}\n```', 'slide', 'd0'), md('# After', 'slide', 'd1')])
    pv, av = f'() => ({PSHADOW})(".verdict:not([hidden])")?.textContent || ""', f'() => ({SHADOW})(".verdict:not([hidden])")?.textContent || ""'
    async def go(pg):
        out, moves, asked = {}, [], []
        def seen(r):
            asked.append(r.url)
            if r.method == 'POST' and '/present/move' in r.url: moves.append(json.loads(r.post_data))
        pg.on('request', seen)
        await _open(pg, tmp_path/'deck.ipynb', 2)
        await _start(pg)
        await pg.wait_for_function(f'() => ({PSHADOW})(".rk-gate")', timeout=20000)
        aud = await _audience(pg, 'Demo')
        await aud.wait_for_function(f'() => ({SHADOW})(".rk-gate")', timeout=20000)
        await pg.evaluate(SLIDE_TO, 3)
        await aud.wait_for_function(f'() => ({SHADOW})(".rk").textContent.includes("x is 3")')
        out['inert'] = await aud.evaluate(f'() => ({SHADOW})(".rk-gate").inert')
        await pg.evaluate(LOCK)
        await aud.wait_for_function(f'() => ({av})().includes("You said")')
        out['verdict'] = await aud.evaluate(av)
        await pg.evaluate(AGAIN)
        await aud.wait_for_function(f'() => !({av})()')
        out['reopened'] = await aud.evaluate(f'() => !({SHADOW})(".rk-gate button.go").hidden')
        await pg.evaluate(LOCK)
        await aud.wait_for_function(f'() => ({av})().includes("You said")')
        n = len(moves)
        await pg.reload()
        await pg.wait_for_function(READY, timeout=20000)
        await pg.wait_for_function(f'() => ({pv})().includes("You said")', timeout=20000)
        await pg.wait_for_timeout(500)
        out['restored'] = await pg.evaluate(f'''() => ({{x: ({PSHADOW})('input[type=range]').value, inert: ({PSHADOW})('.rk-gate').inert}})''')
        out['reload_moves'] = moves[n:]
        await pg.evaluate(SLIDE_TO, 4)
        await aud.wait_for_function(f'() => ({SHADOW})(".rk").textContent.includes("x is 4")')
        await pg.wait_for_timeout(300)
        out['kept'] = await aud.evaluate(av)
        await aud.reload()
        await aud.wait_for_function(f'() => ({av})().includes("You said") && ({SHADOW})(".rk").textContent.includes("x is 4")', timeout=20000)
        out['moves'], out['asked'] = moves, asked
        return out
    out = asyncio.run(_real_page(go, tmp_path))
    assert out['inert'] is True and 'You said' in out['verdict'] and 'two' in out['verdict'] and out['reopened'] is True, out
    ms = out['moves']
    done = [i for i, m in enumerate(ms) if m['t'] == 'demo' and m['gates'].get('g1') == 'done']
    answers = [i for i, m in enumerate(ms) if m['t'] == 'answers']
    assert done and answers and done[0] < answers[0], ('the done snapshot goes before its answers', ms)
    assert all(any(d < a for d in done) for a in answers) and all(m['gates'] == {'g1': {'is': 'two'}} for m in ms if m['t'] == 'answers'), ms
    assert any(m['t'] == 'demo' and 'g1' not in m['gates'] for m in ms[done[0]:]), 'Try another sends a snapshot with the gate open'
    assert all(set(m['gates'].values()) <= {'done'} and set(m) - {'k'} == {'t', 'slug', 'state', 'gates', 'pick'} for m in ms if m['t'] == 'demo'), 'a demo move has no answer'
    assert out['restored'] == {'x': '3', 'inert': False} and out['reload_moves'] == [], out
    assert 'You said' in out['kept'], 'a reloaded presenter keeps the settled gate done for the room'
    assert not [u for u in out['asked'] if '/lesson/predict' in u]
