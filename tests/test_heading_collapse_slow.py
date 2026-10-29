"A folded Markdown heading hides its section, keeps the fold in the .ipynb, and moves as one block."

import json
import pytest

pytestmark = pytest.mark.slow

pytest.importorskip('playwright.async_api')

import test_web_slow as web   # noqa: E402
import test_present_slow as present   # noqa: E402

BROWSERS = pytest.mark.parametrize('browser', ['chromium', 'webkit'])

#: `## Part` folds cells 3 and 4. Cell 4's `### Aside` is not its first line, so it folds nothing.
CELLS = [('markdown', '# Intro\n\ntext'), ('code', 'a = 1'), ('markdown', '## Part'), ('code', 'b = 2'),
         ('markdown', 'hidden prose\n\n### Aside'), ('markdown', '## Next'), ('code', 'c = 3')]
HIDDEN = "() => [...document.querySelectorAll('#editor .lee-cell.heading-hidden')].map(e => +e.dataset.i)"
SHOWN = "i => { const e = document.querySelector(`#editor .lee-cell[data-i=\"${i}\"]`); return !!e && e.offsetHeight > 0; }"

def _nb(p, cells=CELLS, folded=(2,)):
    p.write_text(json.dumps({'cells': [
        {'cell_type': t, 'source': s.splitlines(True), 'id': f'c{i}', 'metadata': {'heading_collapsed': True} if i in folded else {},
         **({'outputs': [], 'execution_count': None} if t == 'code' else {})} for i, (t, s) in enumerate(cells)],
        'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    return p

def _saved(p): return json.loads(p.read_text())['cells']

async def _open(pg, p, n=len(CELLS)):
    await pg.evaluate('p => leeOpenFile(p)', str(p))
    await pg.wait_for_selector(f'#editor .lee-cell[data-i="{n-1}"]', state='attached')

@BROWSERS
def test_a_saved_fold_opens_folded_and_the_caret_writes_it_back(tmp_path, browser):
    p = _nb(tmp_path/'fold.ipynb')
    async def go(pg):
        out = {}
        await _open(pg, p)
        out['open'] = {'hidden': await pg.evaluate(HIDDEN), 'badge': await pg.inner_text('.lee-cell[data-i="2"] .lee-heading-badge'),
                       'shown': await pg.evaluate(SHOWN, 2)}
        await pg.click('.lee-cell[data-i="2"] .lee-heading-badge')
        out['expanded'] = await pg.evaluate(HIDDEN)
        await pg.evaluate('saveTab(true)')
        out['file_open'] = _saved(p)[2]['metadata']
        await pg.click('.lee-cell[data-i="0"] .lee-heading-caret')
        out['top'] = await pg.evaluate(HIDDEN)
        await pg.evaluate('saveTab(true)')
        out['file_shut'] = _saved(p)[0]['metadata']
        await pg.reload(wait_until='networkidle'); await pg.wait_for_function('window.lee && lee.keys.length')
        await _open(pg, p)
        out['reloaded'] = await pg.evaluate(HIDDEN)
        return out
    got = web._run(go, roots=[tmp_path], browser=browser)
    assert got['open'] == {'hidden': [3, 4], 'badge': '2 cells hidden', 'shown': True}, got['open']
    assert got['expanded'] == [] and 'heading_collapsed' not in got['file_open'], got
    assert got['top'] == [1, 2, 3, 4, 5, 6] and got['file_shut'].get('heading_collapsed') is True, got
    assert got['reloaded'] == [1, 2, 3, 4, 5, 6], got['reloaded']

@BROWSERS
def test_the_outline_folds_exactly_the_section_and_only_first_line_headings(tmp_path, browser):
    p = _nb(tmp_path/'toc.ipynb', folded=())
    async def go(pg):
        await _open(pg, p)
        await pg.evaluate("document.querySelector('.lee-nb-toc').open = true")
        rows = await pg.evaluate("""() => [...document.querySelectorAll('.lee-toc-row')].map(r =>
          [r.querySelector('.lee-toc-jump').textContent, !!r.querySelector('.lee-toc-fold')])""")
        fold = '.lee-toc-row:nth-child(2) .lee-toc-fold'
        await pg.click(fold)
        shut = [await pg.evaluate(HIDDEN), await pg.inner_text(fold)]
        await pg.click(fold)
        return rows, shut, [await pg.evaluate(HIDDEN), await pg.inner_text(fold)]
    rows, shut, back = web._run(go, roots=[tmp_path], browser=browser)
    assert rows == [['Intro', True], ['Part', True], ['Aside', False], ['Next', True]], rows
    assert shut == [[3, 4], '+'] and back == [[], '−'], (shut, back)

@BROWSERS
def test_stepping_and_run_advance_skip_a_folded_section(tmp_path, browser):
    p = _nb(tmp_path/'step.ipynb')
    async def go(pg):
        await _open(pg, p)
        await pg.evaluate('focusCell(2)'); await pg.keyboard.press('Control+Shift+ArrowDown')
        await pg.wait_for_function('lee.sel !== 2')
        down = await pg.evaluate('lee.sel')
        await pg.keyboard.press('Control+Shift+ArrowUp'); await pg.wait_for_function('lee.sel !== 5')
        up = await pg.evaluate('lee.sel')
        await pg.evaluate('focusCell(2)'); await pg.keyboard.press('Shift+Enter')
        await pg.wait_for_function('lee.sel !== 2')
        return down, up, await pg.evaluate('lee.sel'), await pg.evaluate(HIDDEN)
    down, up, advanced, hidden = web._run(go, roots=[tmp_path], browser=browser)
    assert (down, up, advanced, hidden) == (5, 2, 5, [3, 4])

@BROWSERS
def test_run_all_runs_folded_cells_and_slides_keep_them(tmp_path, browser):
    p = _nb(tmp_path/'run.ipynb')
    async def go(pg):
        await _open(pg, p)
        await pg.evaluate("leeAct('run_all')")
        await pg.wait_for_function('lee.cells[6].execution_count != null', timeout=30000)
        ran = [await pg.evaluate('lee.cells[3].execution_count'), await pg.evaluate(HIDDEN)]
        await pg.evaluate('presentNotebook()'); await pg.wait_for_function(present.READY, timeout=20000)
        shown = [c for s in await present._slides(pg) for c, _ in s['blocks']]
        return ran, shown
    ran, shown = web._run(go, roots=[tmp_path], browser=browser)
    assert ran[0] is not None and ran[1] == [3, 4], ran
    assert {'c3', 'c4'} <= set(shown), shown

@BROWSERS
def test_a_find_hit_in_a_folded_section_unfolds_it_and_selects_the_match(tmp_path, browser):
    p = _nb(tmp_path/'find.ipynb')
    async def go(pg):
        await _open(pg, p)
        before = await pg.evaluate(HIDDEN)
        await pg.evaluate('focusCell(0)'); await pg.evaluate("leeAct('find_in_file')")
        await pg.fill('#leefindq', 'b = 2'); await pg.press('#leefindq', 'Enter')
        await pg.wait_for_function('lee.sel === 3')
        await pg.wait_for_function("(v => v && !v.state.selection.main.empty)(lee.editors.get('c3'))")
        picked = await pg.evaluate("(v => v.state.sliceDoc(v.state.selection.main.from, v.state.selection.main.to))(lee.editors.get('c3'))")
        return before, picked, await pg.evaluate(HIDDEN), await pg.evaluate(SHOWN, 3)
    assert web._run(go, roots=[tmp_path], browser=browser) == ([3, 4], 'b = 2', [], True)

@BROWSERS
def test_insert_below_a_folded_heading_lands_after_its_section_and_shows(tmp_path, browser):
    p = _nb(tmp_path/'ins.ipynb')
    async def go(pg):
        await _open(pg, p)
        await pg.evaluate('focusCell(2)'); await pg.evaluate("leeAct('cell_below')")
        await pg.wait_for_function('lee.cells.length === 8')
        return (await pg.evaluate('[lee.sel, lee.cells.map(c => c.id)]'), await pg.evaluate(SHOWN, 5))
    (sel, ids), shown = web._run(go, roots=[tmp_path], browser=browser)
    assert sel == 5 and ids[:5] == ['c0', 'c1', 'c2', 'c3', 'c4'] and ids[6:] == ['c5', 'c6'] and shown, (sel, ids, shown)

SECTIONS = [('markdown', '# A'), ('code', 'a = 1'), ('markdown', '## P'), ('code', 'p = 1'),
            ('markdown', '## Q'), ('code', 'q = 1'), ('markdown', '## R')]

@BROWSERS
def test_moving_a_folded_heading_moves_its_section_past_the_next_one(tmp_path, browser):
    p = _nb(tmp_path/'move.ipynb', SECTIONS, folded=(2, 4))
    async def go(pg):
        await _open(pg, p, len(SECTIONS))
        await pg.evaluate('focusCell(2)'); await pg.evaluate("leeAct('cell_move_down')")
        await pg.wait_for_function("lee.cells[2].id === 'c4'")
        moved = await pg.evaluate('[lee.sel, lee.cells.map(c => c.id)]')
        await pg.evaluate('saveTab(true)')
        on_disk = [c['id'] for c in _saved(p)]
        await pg.evaluate("leeAct('notebook_undo')"); await pg.wait_for_function("lee.cells[2].id === 'c2'")
        return moved, on_disk, await pg.evaluate('lee.cells.map(c => c.id)'), await pg.evaluate(HIDDEN)
    moved, on_disk, undone, hidden = web._run(go, roots=[tmp_path], browser=browser)
    order = ['c0', 'c1', 'c4', 'c5', 'c2', 'c3', 'c6']
    assert moved == [4, order] and on_disk == order, (moved, on_disk)
    assert undone == [f'c{i}' for i in range(7)] and hidden == [3, 5], (undone, hidden)

NESTED = [('markdown', '# Top'), ('code', 't = 1'), ('markdown', '## Sub'), ('code', 's = 1'),
          ('markdown', '## Sib'), ('code', 'b = 1'), ('markdown', '# Other'), ('code', 'o = 1')]

@BROWSERS
def test_a_nested_fold_hides_its_own_cells_and_the_outer_one_hides_all(tmp_path, browser):
    p = _nb(tmp_path/'nest.ipynb', NESTED)
    async def go(pg):
        await _open(pg, p, len(NESTED))
        inner = await pg.evaluate(HIDDEN)
        await pg.click('.lee-cell[data-i="0"] .lee-heading-caret'); outer = await pg.evaluate(HIDDEN)
        await pg.click('.lee-cell[data-i="0"] .lee-heading-caret')
        return inner, outer, await pg.evaluate(HIDDEN)
    assert web._run(go, roots=[tmp_path], browser=browser) == ([3], [1, 2, 3, 4, 5], [3])

@BROWSERS
def test_a_cell_the_agent_adds_into_a_folded_section_is_shown(tmp_path, browser, monkeypatch):
    from leela.blocks.agent.ai import WorkspaceHost
    p, held, real = _nb(tmp_path/'agent.ipynb'), {}, web.fake_model
    monkeypatch.setattr(web, 'fake_model', lambda ws: (held.setdefault('ws', ws), real(ws))[1])
    async def go(pg):
        await _open(pg, p)
        WorkspaceHost(held['ws']).nb_add_cell(str(p), 'z = 9', 4)
        await pg.evaluate('p => takeDiskVersion(p)', str(p))
        await pg.wait_for_function('lee.cells.length === 8')
        at = await pg.evaluate("lee.cells.findIndex(c => c.source === 'z = 9')")
        return at, await pg.evaluate(SHOWN, at), await pg.evaluate(HIDDEN)
    at, shown, hidden = web._run(go, roots=[tmp_path], browser=browser)
    assert at == 4 and shown and hidden == [], (at, shown, hidden)
    assert 'heading_collapsed' not in _saved(p)[2]['metadata']

@BROWSERS
def test_a_fold_clicked_while_an_insert_awaits_its_response_survives_it(tmp_path, browser):
    "The insert's response predates the fold, and the fold's index meant another cell once the insert landed."
    import asyncio
    p = _nb(tmp_path/'race.ipynb', folded=())
    async def go(pg):
        await _open(pg, p)
        seen, release = asyncio.Event(), asyncio.Event()
        async def hold(route):
            if (route.request.post_data_json or {}).get('op') != 'insert': return await route.continue_()
            resp = await route.fetch(); seen.set(); await release.wait()
            await route.fulfill(response=resp)
        await pg.route('**/nb/edit', hold)
        await pg.evaluate("() => { focusCell(0); leeAct('cell_above'); }")
        await seen.wait()
        await pg.click('.lee-cell[data-i="2"] .lee-heading-caret')
        await pg.evaluate('headingSynced()')
        release.set()
        await pg.wait_for_function('lee.cells.length === 8')
        page = await pg.evaluate("""() => [lee.cells.find(c => c.id === 'c2').extra?.heading_collapsed,
          document.querySelector('#editor .lee-cell[data-id="c2"]').classList.contains('heading-collapsed')]""")
        await pg.evaluate('saveTab(true)')
        return page
    page = web._run(go, roots=[tmp_path], browser=browser)
    saved = {c['id']: c['metadata'] for c in _saved(p)}
    assert page == [True, True], page
    assert saved['c2'].get('heading_collapsed') is True and not any('heading_collapsed' in m for k, m in saved.items() if k != 'c2'), saved
