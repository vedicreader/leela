"Requests a notebook page sends land on the notebook and cells they were made in, and a late response never undoes newer work."

import asyncio, json
import pytest

pytestmark = pytest.mark.slow

pytest.importorskip('playwright.async_api')

import test_web_slow as web   # noqa: E402

BROWSERS = pytest.mark.parametrize('browser', ['chromium', 'webkit'])
#: Waits for a tab's fold writes; `lee.headingSync` was one promise before they were chained per tab.
SYNCED = "k => typeof headingSynced === 'function' ? headingSynced(k) : lee.headingSync"
FOLDS = "p => api('/tab/state?path=' + encodeURIComponent(p)).then(s => s.cells.map(c => !!c.extra?.heading_collapsed))"
DIRTY = "document.querySelector('.lee-tab.active').classList.contains('dirty')"

def _nb(p, cells):
    p.write_text(json.dumps({'cells': [{'cell_type': t, 'source': s, 'id': i, 'metadata': {},
        **({'outputs': [], 'execution_count': None} if t == 'code' else {})} for i, t, s in cells],
        'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    return p

def _pair(tmp_path):
    a = _nb(tmp_path/'a.ipynb', [('h', 'markdown', '# A'), ('x', 'code', 'x'), ('y', 'code', 'y')])
    return a, _nb(tmp_path/'b.ipynb', [('p', 'markdown', '# B'), ('q', 'code', 'q')])

def _cells(p): return {c['id']: c for c in json.loads(p.read_text())['cells']}
def _src(p, cid): return ''.join(_cells(p)[cid]['source'])

async def _open(pg, p):
    first = next(iter(_cells(p)))
    await pg.evaluate('p => leeOpenFile(p)', str(p))
    await pg.wait_for_function("([p, id]) => lee.tabKey === p && !!document.querySelector(`#editor .lee-cell[data-id=\"${id}\"]`)", arg=[str(p), first])

async def _type(pg, cid, text):
    await pg.evaluate("id => { const i = lee.cells.findIndex(c => c.id === id), v = ensureCellMounted(i); LeeCM.focus(v); LeeCM.setCursor(v, v.state.doc.length); }", cid)
    await pg.keyboard.type(text)

def _holding(pg, url, when=lambda r: True, response=False):
    "Hold the first request to `url` that `when` picks: its request before the server, or with `response`, its answer after it."
    seen, release = asyncio.Event(), asyncio.Event()
    async def hold(route):
        if seen.is_set() or not when(route.request): return await route.continue_()
        if not response:
            seen.set(); await release.wait()
            return await route.continue_()
        got = await route.fetch(); seen.set(); await release.wait()
        await route.fulfill(response=got)
    return pg.route(url, hold), seen, release

def op(name): return lambda r: (r.post_data_json or {}).get('op') == name

@BROWSERS
def test_a_fold_sent_just_before_a_tab_switch_lands_on_its_own_notebook(tmp_path, browser):
    a, b = _pair(tmp_path)
    async def go(pg):
        await _open(pg, b); await _open(pg, a)
        routed, seen, release = _holding(pg, '**/nb/edit', op('heading')); await routed
        await pg.click('.lee-cell[data-i="0"] .lee-heading-caret')
        await seen.wait()
        await _open(pg, b)
        release.set(); await pg.evaluate(SYNCED, str(a))
        other = await pg.evaluate(FOLDS, str(b))
        await _open(pg, a)
        page = await pg.evaluate("""() => [lee.cells[0].extra?.heading_collapsed === true,
          document.querySelector('#editor .lee-cell[data-id="h"]').classList.contains('heading-collapsed')]""")
        await pg.evaluate('saveTab(true)')
        return other, page
    other, page = web._run(go, roots=[tmp_path], browser=browser)
    assert other == [False, False], 'the fold landed on the notebook switched to'
    assert page == [True, True], page
    assert _cells(a)['h']['metadata'].get('heading_collapsed') is True and not _cells(b)['p']['metadata']

@BROWSERS
def test_a_fold_clicked_while_a_save_is_out_keeps_the_tab_dirty_until_it_is_saved(tmp_path, browser):
    a, _ = _pair(tmp_path)
    async def go(pg):
        await _open(pg, a)
        routed, seen, release = _holding(pg, '**/nb/save', response=True); await routed
        await pg.evaluate('() => { window.__saving = saveTab(false); }')
        await seen.wait()
        await pg.click('.lee-cell[data-i="0"] .lee-heading-caret')
        await pg.evaluate(SYNCED, str(a))
        release.set(); await pg.evaluate('window.__saving')
        dirty = await pg.evaluate(DIRTY)
        unsaved = _cells(a)['h']['metadata'].get('heading_collapsed')
        await pg.evaluate('saveTab(true)')
        return dirty, unsaved
    dirty, unsaved = web._run(go, roots=[tmp_path], browser=browser)
    assert dirty and not unsaved, 'the save that predates the fold marked the tab clean'
    assert _cells(a)['h']['metadata'].get('heading_collapsed') is True

@BROWSERS
def test_an_older_source_write_that_arrives_last_does_not_replace_the_newer_one(tmp_path, browser):
    "The first mirror of a cell's text reaches the server after the second."
    a, _ = _pair(tmp_path)
    async def go(pg):
        await _open(pg, a)
        routed, seen, release = _holding(pg, '**/tab/buffer'); await routed
        await _type(pg, 'x', ' # first')
        await seen.wait()
        async with pg.expect_response('**/tab/buffer'): await _type(pg, 'x', ' # second')
        async with pg.expect_response('**/tab/buffer'): release.set()
        await pg.evaluate("post('/tabs/save-all')")
        return await pg.evaluate("LeeCM.getDoc(lee.editors.get('x'))")
    page = web._run(go, roots=[tmp_path], browser=browser)
    assert page == 'x # first # second' and _src(a, 'x') == 'x # first # second', (page, _src(a, 'x'))

@BROWSERS
def test_typing_while_an_older_edit_is_out_is_not_reverted_by_its_response(tmp_path, browser):
    a, _ = _pair(tmp_path)
    async def go(pg):
        await _open(pg, a)
        routed, seen, release = _holding(pg, '**/nb/edit', op('insert'), response=True); await routed
        await pg.evaluate("() => { focusCell(0); leeAct('cell_above'); }")
        await seen.wait()
        await _type(pg, 'x', ' # typed')
        release.set()
        await pg.wait_for_function('lee.cells.length === 4')
        await pg.wait_for_timeout(200)
        text = await pg.evaluate("LeeCM.getDoc(lee.editors.get('x'))")
        await pg.evaluate('saveTab(true)')
        return text
    text = web._run(go, roots=[tmp_path], browser=browser)
    assert text == 'x # typed' and _src(a, 'x') == 'x # typed', (text, _src(a, 'x'))

@BROWSERS
def test_an_edit_answered_after_a_tab_switch_stays_with_its_own_notebook(tmp_path, browser):
    a, b = _pair(tmp_path)
    async def go(pg):
        await _open(pg, b); await _open(pg, a)
        routed, seen, release = _holding(pg, '**/nb/edit', op('insert'), response=True); await routed
        await pg.evaluate("() => { focusCell(0); leeAct('cell_above'); }")
        await seen.wait()
        await _open(pg, b)
        async with pg.expect_response('**/nb/edit'): release.set()
        await pg.wait_for_timeout(200)
        on_b = await pg.evaluate("[lee.tabKey, lee.cells.map(c => c.id), [...document.querySelectorAll('#editor .lee-cell')].length]")
        await _open(pg, a)
        return on_b, await pg.evaluate('lee.cells.length')
    on_b, on_a = web._run(go, roots=[tmp_path], browser=browser)
    assert on_b == [str(b), ['p', 'q'], 2] and on_a == 4, (on_b, on_a)

@BROWSERS
def test_a_save_answered_after_a_tab_switch_leaves_the_next_tab_its_own_disk_version(tmp_path, browser):
    a, b = _pair(tmp_path)
    async def go(pg):
        await _open(pg, b); await _open(pg, a)
        routed, seen, release = _holding(pg, '**/nb/save', response=True); await routed
        await _type(pg, 'x', ' # mine')
        await pg.evaluate('() => { window.__saving = saveTab(false); }')
        await seen.wait()
        await _open(pg, b)
        release.set(); await pg.evaluate('window.__saving')
        return await pg.evaluate("p => api('/tab/state?path=' + encodeURIComponent(p)).then(s => [s.disk_version, lee.diskVersion])", str(b))
    want, held = web._run(go, roots=[tmp_path], browser=browser)
    assert held == want, 'the notebook on screen took the version of the file the old tab saved'

@BROWSERS
def test_reloading_from_disk_drops_a_cell_mirror_that_had_not_been_posted(tmp_path, browser):
    a, _ = _pair(tmp_path)
    async def go(pg):
        await _open(pg, a)
        await pg.evaluate("""p => { const v = ensureCellMounted(1); v.dispatch({changes: {from: v.state.doc.length, insert: ' # dropped'}});
          return takeDiskVersion(p); }""", str(a))
        await pg.wait_for_timeout(400)
        return await pg.evaluate("p => api('/tab/state?path=' + encodeURIComponent(p)).then(s => [s.cells[1].source, s.dirty])", str(a))
    assert web._run(go, roots=[tmp_path], browser=browser) == ['x', False]

@BROWSERS
def test_typing_during_a_git_revert_is_kept_over_the_file_it_wrote(tmp_path, browser):
    f = tmp_path/'f.py'; f.write_text('a = 1\n')
    async def go(pg):
        await pg.evaluate('p => leeOpenFile(p)', str(f))
        await pg.wait_for_function("p => lee.tabKey === p && lee.editors.get('file')", arg=str(f))
        had = await pg.evaluate("""() => { const v = lee.editors.get('file'), had = LeeCM.getDoc(v);
          v.dispatch({changes: {from: had.length, insert: 'b = 2\\n'}}); return had; }""")
        f.write_text('a = 0\n')
        await pg.evaluate('([p, had]) => refreshFileChanges(p, true, had)', [str(f), had])
        return await pg.evaluate("LeeCM.getDoc(lee.editors.get('file'))")
    assert web._run(go, roots=[tmp_path], browser=browser) == 'a = 1\nb = 2\n'
