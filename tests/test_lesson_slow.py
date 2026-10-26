import asyncio, json, os
from pathlib import Path
import pytest
from test_completion_caret_slow import _real_page

pytestmark = pytest.mark.slow
SHOTS = Path(__file__).parents[1]/'target/learn/sliceE'

def test_lesson_reveal_confidence_and_saved_state(tmp_path, monkeypatch):
    monkeypatch.setenv('PLAYWRIGHT_BROWSERS_PATH', str(Path.home()/'Library/Caches/ms-playwright'))
    home = tmp_path/'home'
    (home/'Library').mkdir(parents=True)
    (home/'Library/Keychains').symlink_to(Path.home()/'Library/Keychains', target_is_directory=True)
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path/'xdg-data'))
    assert Path(os.environ['XDG_CONFIG_HOME']).is_relative_to('/private/var') or 'leela-test' in os.environ['XDG_CONFIG_HOME']
    async def go(pg):
        await pg.set_viewport_size({'width': 1440, 'height': 1100})
        pg.set_default_timeout(15000)
        await pg.evaluate("() => { leeAct('new_lesson'); }")
        await pg.locator('.lee-modal input').fill('Reveal practice')
        await pg.locator('.lee-modal input').press('Enter')
        await pg.wait_for_function("lee.cells.length === 5 && lee.cells[2].extra?.lesson?.role === 'prediction'")
        pred = pg.locator('.lee-cell[data-i="2"]')
        assert await pred.locator('.lee-confidence').inner_text() == 'Sure?\nnot\na little\nhalf\nfairly\nvery'
        assert await pred.locator('.lee-confidence button[aria-pressed="true"]').count() == 0
        assert await pred.locator('.lee-md-cell').evaluate("e => getComputedStyle(e, '::before').content") == '"Your guess: what will the code below print?"'
        await pred.locator('.lee-md-cell').dblclick()
        await pg.keyboard.type('one\nwrong')
        await pred.get_by_role('button', name='fairly', exact=True).click()
        await pg.wait_for_function('lee.cells[2].extra.lesson.confidence === 70')
        await pred.get_by_role('button', name='fairly', exact=True).click()
        await pg.wait_for_function('lee.cells[2].extra.lesson.confidence == null')
        await pred.get_by_role('button', name='fairly', exact=True).click()
        await pg.wait_for_function('lee.cells[2].extra.lesson.confidence === 70')
        # Sample in the page: a poll from here can miss a two-second run, and a reveal drawn mid-run is the bug.
        await pg.evaluate("""() => { window._sawRunning = false; window._revealWhileRunning = false;
            window._sampler = setInterval(() => { const c = lee.cells[3]; if (!c?.running) return;
              window._sawRunning = true; if (document.querySelector('.lee-reveal')) window._revealWhileRunning = true; }, 10); }""")
        await pg.evaluate("() => { const v = ensureCellMounted(3); LeeCM.setDoc(v, 'import time\\nprint(\"one\", flush=True)\\ntime.sleep(2)\\nprint(\"two\")'); window._lessonRun = runCell(3, false); }")
        assert (await pg.evaluate('window._lessonRun') or {}).get('ok', True) is not False, 'the run was refused'
        await pg.evaluate('clearInterval(window._sampler)')
        seen = await pg.evaluate('[window._sawRunning, window._revealWhileRunning]')
        assert seen == [True, False], f'saw the cell running, and a reveal while it ran: {seen}'
        reveal = pg.locator('.lee-reveal')
        await reveal.wait_for()
        text = 'one\nYou wrote wrong. It printed two.\nYou were sure, and it went another way. That is the part worth a look.'
        assert await reveal.inner_text() == text
        assert await reveal.locator('.lee-reveal-save').count() == 0
        assert await reveal.evaluate("e => getComputedStyle(e).fontFamily === getComputedStyle(document.body).fontFamily && !/mono|Menlo|Consolas/i.test(getComputedStyle(e).fontFamily)")
        assert await reveal.evaluate("e => e.previousElementSibling.id.startsWith('out-')")
        assert await pg.evaluate('saveTab(true)')
        path = Path(await pg.evaluate('lee.path'))
        disk = json.loads(path.read_text())
        assert disk['cells'][2]['metadata']['lesson']['confidence'] == 70
        assert disk['cells'][3]['metadata']['lesson']['confidence'] == 70
        bgs = {}
        for mode in ('light', 'dark'):
            await pg.evaluate("m => { document.documentElement.dataset.theme = 'leela'; document.documentElement.dataset.mode = m; }", mode)
            await reveal.scroll_into_view_if_needed()
            await pg.wait_for_timeout(800)   # the theme switch is a CSS transition; shoot after it ends
            bgs[mode] = await pg.evaluate("() => [getComputedStyle(document.body).backgroundColor, JSON.stringify(document.documentElement.dataset), document.documentElement.className]")
            SHOTS.mkdir(parents=True, exist_ok=True)
            await pg.screenshot(path=str(SHOTS/f'reveal-{mode}.png'))
        assert bgs['light'][0] != bgs['dark'][0], bgs
        await pg.reload(wait_until='networkidle')
        await pg.wait_for_function('lee.cells.length === 5')
        await pg.evaluate('ensureCellMounted(3)')
        await pg.locator('.lee-reveal').wait_for()
        assert await pg.locator('.lee-reveal').inner_text() == text
        assert await pg.locator('.lee-confidence button[aria-pressed="true"]').inner_text() == 'fairly'
        await pg.route('**/nb/edit', lambda route: route.fulfill(status=400, content_type='application/json', body='{"ok": false, "error": "Confidence save refused for this test."}'))
        await pg.locator('.lee-confidence').get_by_role('button', name='very', exact=True).click()
        await pg.wait_for_function("!document.querySelector('.lee-confidence button:disabled') && lee.cells[2].extra.lesson.confidence === 70")
        assert await pg.locator('.lee-confidence button[aria-pressed="true"]').inner_text() == 'fairly'
        await pg.unroute('**/nb/edit')
        await pg.evaluate("() => { const v = ensureCellMounted(3); v.dispatch({changes: {from: v.state.doc.length, insert: '\\n# changed'}}); }")
        assert await pg.locator('.lee-reveal').count() == 0
        await pg.evaluate("p => takeDiskVersion(p)", str(path))
        await pg.evaluate('ensureCellMounted(3)')
        await pg.locator('.lee-reveal').wait_for()
        disk = json.loads(path.read_text())
        disk['cells'][3]['execution_count'] += 1
        path.write_text(json.dumps(disk))
        await pg.evaluate("p => takeDiskVersion(p)", str(path))
        await pg.reload(wait_until='networkidle')
        await pg.wait_for_function('lee.cells.length === 5')
        await pg.evaluate('ensureCellMounted(3)')
        assert await pg.locator('.lee-reveal').count() == 0
        assert await pg.evaluate('lessonRevealActions(lee.cells[3], document.createElement("div")) === undefined')
    asyncio.run(_real_page(go, tmp_path))
