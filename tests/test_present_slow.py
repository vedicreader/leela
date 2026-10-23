"A notebook presented as slides in a real page: keys, notes page, live runs, and a clean exit."

import pytest

pytestmark = pytest.mark.slow

import asyncio, base64, json

pytest.importorskip('playwright.async_api')

from test_completion_caret_slow import _real_page   # noqa: E402

DOT = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')
PNG = {'output_type': 'display_data', 'metadata': {}, 'data': {'image/png': base64.b64encode(DOT).decode()}}
MDOUT = {'output_type': 'display_data', 'metadata': {}, 'data': {'text/markdown': '**md out**', 'text/plain': 'md'}}
md = lambda src, t, i: {'cell_type': 'markdown', 'id': i, 'metadata': {'slideshow': {'slide_type': t}}, 'source': src}
code = lambda src, t, i, outs=(): {'cell_type': 'code', 'id': i, 'metadata': {'slideshow': {'slide_type': t}},
                                   'execution_count': None, 'outputs': list(outs), 'source': src}
CELLS = [md('# Intro\n\n![dot](images/dot.png)', 'slide', 'm0'), md('plain continued text', '-', 'm1'),
         md('appears later', 'fragment', 'm2'), md('SPEAKER-SECRET-ONE', 'notes', 'm3'),
         code("print('hi')", 'subslide', 'c4', [PNG, MDOUT]), md('SKIPPED-TEXT', 'skip', 'm5'),
         md('# Second\n\nsecond body', 'slide', 'm6'), md('SPEAKER-SECRET-TWO', 'notes', 'm7'),
         code("import time\nfor i in range(3):\n    print('tick', i, flush=True)\n    time.sleep(0.8)", 'slide', 'c8'),
         code('1/0', 'slide', 'c9')]
STYLES = r"""() => { const pick = el => { const s = getComputedStyle(el); return ['font-family', 'font-size', 'line-height',
    'color', 'background-color', 'margin-top', 'overflow', 'text-transform', 'letter-spacing'].map(k => s.getPropertyValue(k)).join('|'); };
  let h = document.getElementById('probe-h1'), p = document.getElementById('probe-pre');
  if (!h) { h = document.body.appendChild(document.createElement('h1')); h.id = 'probe-h1'; h.textContent = 'h';
            p = document.body.appendChild(document.createElement('pre')); p.id = 'probe-pre'; p.textContent = 'p'; }
  return [pick(document.documentElement), pick(document.body), pick(h), pick(p)]; }"""
AT = '() => { const i = lee.present.reveal.getIndices(); return [i.h, i.v || 0, i.f ?? -1]; }'
STATUS = "() => document.getElementById('status').textContent"
READY = '() => lee.present?.reveal && document.querySelector(".lee-present .reveal.ready")'

async def _state(pg): return await pg.evaluate("fetch('/present/state').then(r => r.json())")

async def _walk(pg, root):
    out, opened = {}, []
    # the notes page opens as a browser tab, or through the server where the browser refuses a popup
    pg.context.on('request', lambda r: opened.append(f'{r.url} {r.post_data or ""}') if r.url.endswith('/browser/external') or '/present/notes' in r.url else None)
    await pg.route('**/browser/external', lambda r: asyncio.ensure_future(
        r.fulfill(status=200, content_type='application/json', body='{"ok": true}')))
    await pg.evaluate('p => leeOpenFile(p)', str(root/'deck.ipynb'))
    await pg.wait_for_function('() => document.querySelectorAll(".lee-cell").length === 10')
    await pg.evaluate("""() => { const v = ensureCellMounted(1);
      v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: 'UNSAVED-EDIT'}}); selectCell(0); focusCell(0); }""")
    before = await pg.evaluate(STYLES)
    await pg.keyboard.press('Alt+KeyR')
    await pg.wait_for_function(READY, timeout=20000)
    out['during'] = await pg.evaluate(STYLES)
    out['counts'] = await pg.evaluate('''() => ({h: document.querySelectorAll('.lee-present .slides > section').length,
      leaf: document.querySelectorAll('.lee-present .slides section:not(.stack)').length})''')
    await pg.wait_for_function('() => document.querySelector(".lee-present .slides").textContent.includes("UNSAVED-EDIT")')
    await pg.wait_for_function('() => [...document.querySelectorAll(".lee-present img")].some(i => i.getAttribute("src").startsWith("/file/raw/") && i.naturalWidth > 0)')
    await pg.wait_for_function('() => document.querySelector(".lee-present .lee-md-output strong")')
    out['counts_rendered'] = await pg.evaluate('''() => [document.querySelectorAll('.lee-present .slides section').length,
      document.querySelectorAll('.lee-present .slides section.stack').length]''')
    out['actions'] = await pg.evaluate('''() => [document.querySelectorAll('.lee-present .lee-reply-actions').length,
      document.querySelectorAll('.lee-cell .lee-reply-actions').length]''')
    out['leak'] = await pg.evaluate('() => document.querySelector(".lee-present .slides").textContent')
    for _ in range(100):
        if (await _state(pg))['live']: break
        await pg.wait_for_timeout(100)
    notes = await pg.context.browser.new_page()
    await notes.goto(pg.url.split('?')[0].rstrip('/') + '/present/notes')
    await notes.wait_for_function('() => document.getElementById("notes").textContent.includes("SPEAKER-SECRET-ONE")')
    out['next'] = await notes.evaluate('() => document.getElementById("next").textContent')
    out['start'] = await pg.evaluate(AT)
    await pg.keyboard.press('ArrowRight'); await pg.keyboard.press('ArrowRight')
    await pg.wait_for_function(f'() => ({AT})()[0] === 1')
    await notes.wait_for_function('() => document.getElementById("notes").textContent.includes("SPEAKER-SECRET-TWO")')
    await pg.keyboard.press('ControlOrMeta+Shift+KeyP')
    await pg.wait_for_timeout(300)
    out['palette'] = await pg.evaluate('() => [!!document.querySelector(".lee-modal"), !!lee.present]')
    await notes.keyboard.press('ArrowLeft')
    await pg.wait_for_function(f'() => ({AT})()[0] === 0')
    was = await pg.evaluate(AT)
    flat = {(0, 0): 0, (0, 1): 1, (1, 0): 2, (2, 0): 3, (3, 0): 4}[tuple(was[:2])]
    await notes.wait_for_function(f'() => document.getElementById("where").textContent === "slide {flat + 1} of 5"')
    out['notes_after_left'] = await notes.evaluate('() => document.getElementById("notes").textContent')
    out['left_at'] = was
    await notes.keyboard.press(' ')
    await pg.wait_for_function(f'w => JSON.stringify(({AT})()) !== JSON.stringify(w)', arg=was)
    out['space_from_notes'] = (was, await pg.evaluate(AT))
    await pg.evaluate('() => lee.present.reveal.slide(2, 0)')
    await pg.wait_for_function(f'() => ({AT})()[0] === 2')
    await pg.click('.lee-present-cell[data-cell-id="c8"] .lee-present-run button')
    await pg.wait_for_function('''() => { const c = document.querySelector('.lee-present-cell[data-cell-id="c8"]');
      return c.classList.contains('running') && c.querySelector('.lee-present-out').textContent.includes('tick 0'); }''', timeout=60000)
    await pg.wait_for_function('''() => { const c = document.querySelector('.lee-present-cell[data-cell-id="c8"]');
      return !c.classList.contains('running') && c.textContent.includes('tick 2'); }''', timeout=60000)
    out['notebook_out'] = await pg.evaluate('() => document.getElementById("out-c8").textContent')
    await pg.evaluate('() => lee.present.reveal.slide(3, 0)')
    await pg.wait_for_function(f'() => ({AT})()[0] === 3')
    await pg.click('.lee-present-cell[data-cell-id="c9"] .lee-present-run button')
    await pg.wait_for_function('() => document.querySelector(".lee-present-cell.failed[data-cell-id=c9]")', timeout=60000)
    out['error'] = await pg.evaluate('() => document.querySelector(".lee-present-cell[data-cell-id=c9]").textContent')
    await pg.keyboard.press('Escape')
    await pg.wait_for_function('() => !document.querySelector(".lee-present")')
    out['closed'] = await pg.evaluate('''() => ({focus: document.activeElement.closest('.lee-cell')?.dataset.i, sel: String(lee.sel),
      links: document.querySelectorAll('link[data-lee-present]').length, present: lee.present})''')
    out['after'] = await pg.evaluate(STYLES)
    await notes.wait_for_function('() => document.getElementById("state").textContent.includes("ended")')
    await pg.evaluate('() => { presentNotebook(); presentNotebook(); }')
    await pg.wait_for_function(READY, timeout=20000)
    await pg.wait_for_timeout(300)
    out['reopen'] = await pg.evaluate('''() => [document.querySelectorAll('.reveal').length, document.querySelectorAll('.lee-present').length,
      document.querySelectorAll('link[data-lee-present]').length]''')
    await pg.keyboard.press('Escape')
    await pg.wait_for_function('() => !document.querySelector(".lee-present")')
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
    out['said'], out['opened'], out['before'] = said, opened, before
    return out

@pytest.mark.parametrize('browser', ['chromium', 'webkit'])
def test_a_notebook_presents_as_slides_and_leaves_the_ide_as_it_found_it(tmp_path, browser):
    (tmp_path/'images').mkdir(); (tmp_path/'images'/'dot.png').write_bytes(DOT)
    meta = {'kernelspec': {'name': 'python3', 'display_name': 'Python 3', 'language': 'python'}}
    (tmp_path/'deck.ipynb').write_text(json.dumps({'cells': CELLS, 'metadata': meta, 'nbformat': 4, 'nbformat_minor': 5}))
    (tmp_path/'plain.py').write_text('x = 1\n')
    out = asyncio.run(_real_page(lambda pg: _walk(pg, tmp_path), tmp_path, browser))
    assert out['counts'] == {'h': 4, 'leaf': 5}, out['counts']
    assert out['counts_rendered'] == [6, 1], 'rendered content added no sections reveal would read as slides'
    assert out['start'] == [0, 0, -1], 'opens at the selected cell, before its fragment'
    assert out['actions'][0] == 0 < out['actions'][1], 'the notebook keeps its edit buttons and the deck has none'
    assert 'SPEAKER-SECRET' not in out['leak'] and 'SKIPPED-TEXT' not in out['leak']
    assert "print('hi')" in out['next']
    assert ('SPEAKER-SECRET-ONE' in out['notes_after_left']) == (out['left_at'][1] == 0), out['notes_after_left']
    assert out['palette'] == [False, True], 'no palette behind the deck'
    assert out['space_from_notes'][1] != out['space_from_notes'][0]
    assert 'tick 2' in out['notebook_out']
    assert 'ZeroDivisionError' in out['error']
    assert out['closed'] == {'focus': out['closed']['sel'], 'sel': out['closed']['sel'], 'links': 0, 'present': None}
    assert out['before'] == out['during'] == out['after'], 'the deck restyled the IDE'
    assert out['reopen'] == [1, 1, 2]
    assert set(out['said'].values()) == {'only a notebook can be presented as slides'}, out['said']
    assert any('/present/notes' in d for d in out['opened']), out['opened']


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
