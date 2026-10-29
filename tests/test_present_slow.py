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
    await pg.wait_for_function(f'() => ({MSG})().includes("ZeroDivisionError")', timeout=60000)
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
    # Run saves a notebook with unsaved edits before it runs (`motion.js:94`), so the check stops at the first Run
    assert out['file_at_run'] == before, 'starting, moving, notes and the palette chord write nothing'


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
