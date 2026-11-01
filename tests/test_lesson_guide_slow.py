import asyncio, json, os
from pathlib import Path
import pytest
from test_completion_caret_slow import _real_page

pytestmark = pytest.mark.slow
TOKEN = r'\bar\alpha_t'
SECOND = r'\mathbf{x}_0'
TRAPS = 'Costs `$5 and $7` and \\$3 or `![x](` here.\n\n$$ q=' + TOKEN + ' $$\n\nThen $s=' + SECOND + '+\\epsilon$ is noise.\n\n![A noisy cat](cat.png)'
ASK = "I don't get alpha bar"

def _lesson(tmp_path, monkeypatch, source):
    from leela.blocks.nb.lesson import lesson_notebook
    monkeypatch.setenv('PLAYWRIGHT_BROWSERS_PATH', str(Path.home()/'Library/Caches/ms-playwright'))
    home = tmp_path/'home'
    (home/'Library').mkdir(parents=True)
    (home/'Library/Keychains').symlink_to(Path.home()/'Library/Keychains', target_is_directory=True)
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path/'xdg-data'))
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'learning.db'))
    nb = lesson_notebook('Noise')
    nb[1].source = source
    path = tmp_path/'noise.ipynb'; nb.save(path)
    return path

async def _ask(pg, path, board, posted, formulas=True, streamed=False, ready=''):
    await pg.set_viewport_size({'width': 1440, 'height': 1100})
    pg.set_default_timeout(15000)
    await pg.evaluate('p => leeOpenFile(p)', str(path))
    await pg.wait_for_function('lee.cells.length === 5')
    cell = pg.locator('.lee-cell[data-i="1"]')
    if formulas: await cell.locator('[data-guide-id="f1"]').wait_for()
    else: await cell.locator('[data-guide-id="passage"]').wait_for(state='attached')
    steps = [('step', dict(step=s, k=k, tier='tutor', demo_open=False)) for k, s in enumerate(board['steps'], 1)] if streamed else []
    async def fake(route):
        posted.append(json.loads(route.request.post_data))
        await route.fulfill(status=200, content_type='text/event-stream', body=''.join(f'event: {e}\ndata: {json.dumps(d)}\n\n' for e, d in steps + [('board', board)]))
    await pg.route('**/nb/guide/stream', fake)
    if formulas: await pg.wait_for_function("[...document.querySelectorAll('.lee-cell[data-i=\"1\"] [data-guide-id^=f]')].every(e => e.dataset.parts)")
    if ready: await pg.wait_for_function(ready)
    await cell.locator('.lee-guide').click()
    await pg.locator('.lee-modal input').fill(ASK)
    await pg.locator('.lee-modal input').press('Enter')
    return cell

def _board(strokes, say='Alpha bar is the share of the picture left.'):
    return dict(tier='tutor', steps=[dict(n=1, say=say, strokes=strokes)], sources=[], end="In the tutor's own words.", failed=False, dropped=0, demo_open=False, notes=[], ok=True)

GEOM = """id => { const r = e => { const b = e.getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom]; };
  const part = document.getElementById(id), whole = document.querySelector('.lee-cell[data-i="1"] [data-guide-id="' + arguments[1] + '"]'), mark = document.querySelector('.board-hl .board-marker'),
        ring = document.querySelector('#board-layer g[data-op="circle"] path');
  return {part: r(part), whole: r(whole), mark: mark && r(mark), markPath: mark?.getAttribute('d')?.length || 0, ring: ring && r(ring), ringPath: ring?.getAttribute('d')?.length || 0,
          off: document.querySelector('.lee-guide-out') === null}; }"""

def test_the_board_draws_a_mark_over_the_formula_part_the_tutor_names(tmp_path, monkeypatch):
    path = _lesson(tmp_path, monkeypatch, 'Alpha bar is the share left.\n\n$$ q=' + TOKEN + ' $$\n\n![A noisy cat](cat.png)')
    posted = []
    board = _board([dict(op='circle', at=dict(a='f1', tex=TOKEN))])
    async def go(pg):
        cell = await _ask(pg, path, board, posted, streamed=True)
        formula = cell.locator('[data-guide-id="f1"]')
        ids = await cell.evaluate("c => [...c.querySelectorAll('[data-guide-id]')].map(e => e.dataset.guideId)")
        assert {'passage', 'f1', 'img1'} <= set(ids) and len(ids) == len(set(ids)), ids
        parts = json.loads(await formula.get_attribute('data-parts'))
        part_id = next(i for t, i in parts if t == TOKEN)
        await pg.wait_for_function('window.abhyasaBoard?.state?.done === true && window.abhyasaBoard.state.streaming === false')
        assert [a['id'] for a in posted[0]['anchors']] == ['f1', 'img1'] and posted[0]['said'] == ASK
        assert TOKEN in posted[0]['anchors'][0]['parts'] and posted[0]['anchors'][1]['text'] == 'A noisy cat'
        got = await pg.evaluate(GEOM.replace('arguments[1]', "'f1'"), part_id)
        px0, py0, px1, py1 = got['part']; wx0, _, wx1, _ = got['whole']
        assert got['markPath'] > 0 and got['ringPath'] > 0 and got['off'], got
        mx0, my0, mx1, my1 = got['mark']
        assert abs(mx0 - px0) < 20 and abs(mx1 - px1) < 20 and my0 < py1 and my1 > py0, 'the marker lies over the part'
        assert (px1 - px0) < (wx1 - wx0) * .6, 'the part is smaller than the whole formula, so the mark is on the token and not on the formula'
        rx0, ry0, rx1, ry1 = got['ring']
        assert rx0 < px0 and rx1 > px1 and ry0 < py0 and ry1 > py1 and (rx1 - rx0) < (wx1 - wx0), 'the ring surrounds the part, not the whole formula'
    asyncio.run(_real_page(go, tmp_path))

def test_the_page_sends_the_anchors_it_drew_when_code_and_escapes_hold_dollars(tmp_path, monkeypatch):
    from leela.blocks.nb.lesson import check_anchors, guide_context
    from leela.blocks.nb.nb import Notebook
    path = _lesson(tmp_path, monkeypatch, TRAPS)
    posted = []
    board = _board([dict(op='circle', at=dict(a='f2', tex=SECOND))])
    async def go(pg):
        cell = await _ask(pg, path, board, posted)
        await pg.wait_for_function('window.abhyasaBoard?.state?.done === true')
        dom = await cell.evaluate("""c => ({formulas: [...c.querySelectorAll('.katex')].length, ids: [...c.querySelectorAll('[data-guide-id]')].map(e => e.dataset.guideId),
          tex: [...c.querySelectorAll('[data-guide-id^=f]')].map(e => [e.dataset.guideId, e.dataset.tex.trim(), JSON.parse(e.dataset.parts).map(p => p[0])]),
          imgs: [...c.querySelectorAll('img[data-guide-id]')].map(e => e.outerHTML), code: [...c.querySelectorAll('code')].map(e => e.textContent)})""")
        assert dom['formulas'] == 2 and dom['tex'][0][:2] == ['f1', 'q=' + TOKEN] and dom['tex'][1][:2] == ['f2', 's=' + SECOND + '+\\epsilon'], dom
        assert '$5 and $7' in dom['code'], dom
        sent = posted[0]['anchors']
        assert [a['id'] for a in sent] == ['f1', 'f2', 'img1'], sent
        assert [(a['id'], a['text'], a['parts']) for a in sent[:2]] == [(i, t, p) for i, t, p in dom['tex']] and sent[2] == dict(id='img1', text='A noisy cat'), dom['imgs']
        assert SECOND in sent[1]['parts'] and len(sent[1]['parts']) > 1, sent[1]
        nb = Notebook.load(path)
        ctx = guide_context(nb.meta['lesson'], nb[1], anchors=check_anchors(sent))
        assert [a['id'] for a in ctx['anchors']] == ['passage', 'f1', 'f2', 'img1'], 'the server adds no formula or figure of its own'
        formula = cell.locator('[data-guide-id="f2"]')
        part_id = next(i for t, i in json.loads(await formula.get_attribute('data-parts')) if t == SECOND)
        got = await pg.evaluate(GEOM.replace('arguments[1]', "'f2'"), part_id)
        px0, py0, px1, py1 = got['part']; wx0, _, wx1, _ = got['whole']
        assert got['markPath'] > 0 and got['off'], got
        mx0, my0, mx1, my1 = got['mark']
        assert abs(mx0 - px0) < 20 and abs(mx1 - px1) < 20 and my0 < py1 and my1 > py0, 'the marker lies over the part of the second formula'
        assert (px1 - px0) < (wx1 - wx0) * .8, 'the mark is on the part, not the whole second formula'
    asyncio.run(_real_page(go, tmp_path))

def test_the_page_sends_the_demo_ids_that_board_js_gives_the_rupaka_demo(tmp_path, monkeypatch):
    from leela.blocks.nb.lesson import fence
    spec = dict(id='noise', state=dict(t=500), blocks=[dict(type='slider', bind='t', label='Step t', min=0, max=1000, step=10), dict(type='readout', label='Now', text='t is {t}')])
    path = _lesson(tmp_path, monkeypatch, f'Move the slider.\n\n{fence(spec)}')
    posted = []
    rendered = "[...(document.querySelector('.lee-cell[data-i=\"1\"] .lee-rupaka')?.shadowRoot?.children || [])].some(n => n.rupaka && n.querySelector('[data-rk-type=readout]'))"
    async def go(pg):
        cell = await _ask(pg, path, _board([]), posted, formulas=False, ready=rendered)
        await pg.wait_for_function('window.abhyasaBoard?.state')
        sent = posted[0]['demo']
        assert [a['id'] for a in sent['anchors']] == ['demo', 'in:t', 'out:1'], sent
        assert sent['demo']['inputs']['t']['value'] == 500 and len(sent['demo']['readouts']) == 1, sent
        from leela.blocks.nb.lesson import check_demo
        assert check_demo(sent)['anchors'] == sent['anchors'], 'the server takes what board.js sends as it is'
        ids = await cell.evaluate("c => [...c.querySelector('.lee-rupaka').shadowRoot.querySelectorAll('[data-guide-id]')].map(e => e.dataset.guideId)")
        assert {'in:t', 'out:1'} <= set(ids), ids
    asyncio.run(_real_page(go, tmp_path))

def test_typing_a_s_d_in_a_lesson_editor_while_a_board_plays_types_and_does_not_drive_the_board(tmp_path, monkeypatch):
    path = _lesson(tmp_path, monkeypatch, 'Alpha bar is the share left.')
    steps = [dict(n=i, say=' '.join(['word'] * 80), strokes=[]) for i in (1, 2, 3)]
    board = dict(_board([]), steps=steps)
    async def go(pg):
        await _ask(pg, path, board, [], formulas=False)
        await pg.wait_for_function('window.abhyasaBoard?.state?.i === 0')
        editor = "const v = lee.editors.get(lee.cells[3].id);"
        await pg.evaluate(f"() => {{ {editor} v.focus(); v.dispatch({{selection: {{anchor: v.state.doc.length}}}}); }}")
        before = await pg.evaluate('window.abhyasaBoard.state.i')
        await pg.keyboard.type('asd')
        await pg.wait_for_timeout(300)
        got = await pg.evaluate(f"() => {{ {editor} const s = window.abhyasaBoard.state; return {{text: v.state.doc.toString(), i: s && s.i, shown: !!s}}; }}")
        assert got['text'] == 'passasd', got
        assert got['shown'] and got['i'] == before == 0, got
    asyncio.run(_real_page(go, tmp_path))

def test_the_new_board_builds_its_panel_from_the_code_the_page_sends(tmp_path, monkeypatch):
    "abhyasa main's board: the page sends code1, and a panel row that marks the code draws in the side panel at the top right."
    path = _lesson(tmp_path, monkeypatch, 'The targets are the next tokens.\n\n$$ q=' + TOKEN + ' $$\n\n```python\nx = tensor([18, 47, 56])\n```')
    posted = []
    board = _board([dict(op='panel', title='tensors and targets', head='Make a question and its answer', cols=['Input', 'Target']),
                    dict(op='row', cells=['[18]'], to='47', at=dict(a='code1', text='tensor([18, 47, 56])'))], say='Each line makes one question.')
    async def go(pg):
        cell = await _ask(pg, path, board, posted, streamed=True)
        await pg.wait_for_function("window.abhyasaBoard?.state?.done === true && document.querySelector('#board-panel .board-row')")
        code = [a for a in posted[0]['anchors'] if a['id'].startswith('code')]
        assert code == [dict(id='code1', text='x = tensor([18, 47, 56])')], posted[0]['anchors']
        assert await cell.locator('.lee-md-cell [data-guide-id="code1"]').count() == 1
        p = await pg.evaluate("""() => { const p = document.getElementById('board-panel'), b = p.getBoundingClientRect(), e = document.getElementById('editorstage').getBoundingClientRect();
            return {title: p.querySelector('.board-panel-title')?.textContent, rows: [...p.querySelectorAll('.board-row')].map(r => r.textContent), box: [b.left, b.top, b.right, b.bottom], stage: [e.left, e.top, e.right, e.bottom],
                    hand: getComputedStyle(p).getPropertyValue('--hand'), font: [...document.fonts].some(f => f.family.replace(/["']/g, '') === 'Patrick Hand')}; }""")
        if (shot := os.environ.get('LEELA_SHOTS')): await pg.screenshot(path=f'{shot}/board-panel-in-the-ide.png')
        (l, t, r, b), (sl, st, sr, sb) = p['box'], p['stage']
        assert p['title'] == 'tensors and targets' and p['rows'] == ['[18]⟶47'], p
        assert sl <= l and r <= sr and st <= t < st + 40 and r > (sl + sr) / 2, 'the panel stands at the top right of the notebook area, under its tab bar, not over the side panes' 
        assert 'Patrick Hand' in p['hand'] and p['font'], 'the hand font of the paper comes from /leefonts/hand.css'
        assert await pg.evaluate("!!window.rupakaBoard && window.abhyasaBoard === window.rupakaBoard && !!document.querySelector('script[src^=\"/leeboard/board.js\"]')"), 'the board comes from rupaka, at /leeboard/'
        assert 'Browser voice' in (strip := await pg.locator('#guide-strip').inner_text()) and 'on this Mac' in strip and 'hosted' not in strip, strip
    asyncio.run(_real_page(go, tmp_path))
