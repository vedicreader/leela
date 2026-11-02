import asyncio, json, os
from pathlib import Path
import pytest
from test_completion_caret_slow import _real_page

pytestmark = pytest.mark.slow
SHOTS = Path(__file__).parents[1]/'target/learn/sliceF'

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
        await pg.wait_for_function("document.activeElement?.closest('.lee-cell')?.dataset.i === '2' && document.activeElement.classList.contains('cm-content')")
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
        assert (await reveal.inner_text()).startswith(text)
        assert await reveal.get_by_role('button', name='Save card', exact=True).count() == 1
        assert await reveal.evaluate("e => getComputedStyle(e).fontFamily === getComputedStyle(document.body).fontFamily && !/mono|Menlo|Consolas/i.test(getComputedStyle(e).fontFamily)")
        assert await reveal.evaluate("e => e.previousElementSibling.id.startsWith('out-')")
        assert await pg.evaluate('saveTab(true)')
        path = Path(await pg.evaluate('lee.path'))
        disk = json.loads(path.read_text())
        assert disk['cells'][2]['metadata']['lesson']['confidence'] == 70
        assert disk['cells'][3]['metadata']['lesson']['confidence'] == 70
        await pg.route('**/lesson/save', lambda route: route.fulfill(status=400, content_type='application/json', body='{"ok": false, "error": "Vault locked for this test."}'))
        async with pg.expect_response('**/lesson/save'):
            await reveal.get_by_role('button', name='Save card', exact=True).click()
        await pg.wait_for_function("document.querySelector('.lee-reveal-save button')?.disabled === false")
        assert await reveal.get_by_role('button', name='Save card', exact=True).count() == 1
        await pg.unroute('**/lesson/save')
        saves = []
        pg.on('request', lambda r: saves.append(r) if r.url.endswith('/lesson/save') else None)
        await reveal.get_by_role('button', name='Save card', exact=True).evaluate("e => { e.click(); e.click(); if (!e.disabled) throw Error('Save card was not disabled while posting'); }")
        await pg.wait_for_function("document.querySelector('.lee-reveal-save')?.textContent.startsWith('Saved. Next review ')")
        assert len(saves) == 1
        saved_text = await reveal.locator('.lee-reveal-save').inner_text()
        assert saved_text.strip() in ('Saved. Next review today.', 'Saved. Next review tomorrow.'), saved_text
        assert await reveal.get_by_role('button', name='Save card', exact=True).count() == 0
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
        assert (await pg.locator('.lee-reveal').inner_text()).startswith(text)
        assert await pg.locator('.lee-reveal-save').inner_text() == saved_text
        assert await pg.get_by_role('button', name='Save card', exact=True).count() == 0
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

def test_lesson_due_review_question_before_last_answer(tmp_path, monkeypatch):
    import time
    from abhyasa.learner import Learning
    from leela.blocks.memory.memory import Memory
    monkeypatch.setenv('PLAYWRIGHT_BROWSERS_PATH', str(Path.home()/'Library/Caches/ms-playwright'))
    home = tmp_path/'home'
    (home/'Library').mkdir(parents=True)
    (home/'Library/Keychains').symlink_to(Path.home()/'Library/Keychains', target_is_directory=True)
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path/'xdg-data'))
    memory = Memory(path=tmp_path/'learning.db', offline=True)
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(memory.path))
    lr = Learning(memory._store('learning'))
    lr.put('Recall practice', seen=1, due=time.time()-86400, last=time.time()-172800, stability=.5, misses=2)
    lr.record(concept='recall-practice', question='What will the function print?', answer='My saved answer',
              thinking='I traced the function.', actual='The actual output')
    async def go(pg):
        await pg.set_viewport_size({'width': 1440, 'height': 1100})
        pg.set_default_timeout(15000)
        due = pg.locator('#lessondue')
        await pg.wait_for_function("document.querySelector('#lessondue')?.textContent === '1 due'")
        await pg.evaluate('leePane("right", false)')
        await due.click()
        pane = pg.locator('.lee-lesson-review')
        await pane.wait_for(state='visible')
        await pane.locator('summary').click()
        assert 'What will the function print?' in await pane.inner_text()
        assert 'due for review: recall about ' in await pane.inner_text()
        assert 'missed the last 2 times' in await pane.inner_text()
        assert 'My saved answer' not in await pane.text_content()
        assert 'I traced the function.' not in await pane.text_content()
        assert 'The actual output' not in await pane.text_content()
        assert await pane.evaluate("e => getComputedStyle(e).fontFamily === getComputedStyle(document.body).fontFamily && !/mono|Menlo|Consolas/i.test(getComputedStyle(e).fontFamily)")
        shots = Path(__file__).parents[1]/'target/learn/sliceG'
        shots.mkdir(parents=True, exist_ok=True)
        for mode in ('light', 'dark'):
            await pg.evaluate("m => { document.documentElement.dataset.theme = 'leela'; document.documentElement.dataset.mode = m; }", mode)
            await pg.wait_for_timeout(800)
            await pg.screenshot(path=str(shots/f'review-question-{mode}.png'))
        await pane.get_by_role('button', name='Show my last answer', exact=True).click()
        revealed = await pane.inner_text()
        assert all(s in revealed for s in ('My saved answer', 'I traced the function.', 'The actual output'))
        await pg.screenshot(path=str(shots/'review-answer-dark.png'))
        await pg.route('**/lesson/due', lambda route: route.fulfill(status=400, content_type='application/json', body='{"ok":false,"error":"Review vault locked for this test."}'))
        await pg.evaluate('refreshLessonDue()')
        assert 'Review vault locked for this test.' in await pane.inner_text()
        await pg.unroute('**/lesson/due')
        await pane.get_by_role('button', name='Try again', exact=True).click()
        await pane.locator('summary').wait_for()
        assert 'My saved answer' not in await pane.text_content()
        await pg.route('**/lesson/due', lambda route: route.fulfill(status=200, content_type='application/json', body='[]'))
        await pg.evaluate('refreshLessonDue()')
        assert await due.is_hidden() and await due.text_content() == ''
        assert await pane.locator('#lessonreviewbody').inner_text() == 'Nothing to learn or review right now.'
    asyncio.run(_real_page(go, tmp_path))

def test_lesson_predict_logs_a_gate(tmp_path, monkeypatch):
    from abhyasa.learner import Learning
    from leela.blocks.memory.memory import Memory
    from leela.blocks.nb.lesson import fence, lesson_notebook
    monkeypatch.setenv('PLAYWRIGHT_BROWSERS_PATH', str(Path.home()/'Library/Caches/ms-playwright'))
    home = tmp_path/'home'
    (home/'Library').mkdir(parents=True)
    (home/'Library/Keychains').symlink_to(Path.home()/'Library/Keychains', target_is_directory=True)
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path/'xdg-data'))
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'learning.db'))
    gate = dict(type='gate', id='g1', prompt='What is half of 8?', options=[2, 4, 6], answer={'is': 4}, why='Why?')
    nb = lesson_notebook('Halves')
    nb[1].source = 'Pick one.\n\n' + fence(dict(id='halves', blocks=[dict(type='stack', blocks=[gate])]))
    path = tmp_path/'halves.ipynb'; nb.save(path)
    async def go(pg):
        await pg.set_viewport_size({'width': 1440, 'height': 1100})
        pg.set_default_timeout(15000)
        await pg.evaluate('p => leeOpenFile(p)', str(path))
        await pg.wait_for_function('lee.cells.length === 5')
        demo = pg.locator('.lee-cell[data-i="1"] .lee-rupaka')
        await demo.locator('button.go').wait_for()
        look = await demo.evaluate('''h => { const r = h.shadowRoot, s = getComputedStyle, p = document.body.appendChild(document.createElement('span'));
          p.style.font = '11px var(--lee-sans)'; const want = s(p).fontFamily; p.remove();
          return [s(r.querySelector('.opts button')).fontFamily === want, s(r.querySelector('.opts button')).fontSize, s(r.querySelector('.rk')).fontSize,
                  s(document.documentElement).getPropertyValue('--lee-code-size').trim()]; }''')
        assert look[0] and look[1] == '11px' and look[2] == look[3], look   # the gate takes Leela's font and sizes, not rupaka's serif page
        await pg.locator('.lee-cell[data-i="2"] .lee-md-cell').dblclick()
        await pg.wait_for_function("document.activeElement?.closest('.lee-cell')?.dataset.i === '2' && document.activeElement.classList.contains('cm-content')")
        await pg.keyboard.type('four')
        await pg.wait_for_function("lee.cells[2].source === 'four' || lee.editors.get(lee.cells[2].id) && LeeCM.getDoc(lee.editors.get(lee.cells[2].id)) === 'four'")
        await demo.locator('.opts button').nth(1).click()
        await demo.locator('textarea').fill('Half of 8 is 4.')
        refused = 'This demo changed. Run the cell again, then try.'
        await pg.route('**/lesson/predict', lambda route: route.fulfill(status=409, content_type='application/json', body=json.dumps({'ok': False, 'error': refused})))
        async with pg.expect_response('**/lesson/predict'):
            await demo.locator('button.go').click()
        note, verdict, lock = demo.locator('p.note'), demo.locator('p.verdict'), demo.locator('button.go')
        await note.filter(has_text=refused).wait_for()
        assert await note.inner_text() == refused
        assert await lock.is_enabled() and await verdict.is_hidden()
        assert await demo.locator('.opts button').nth(1).get_attribute('aria-checked') == 'true'
        assert await demo.locator('textarea').input_value() == 'Half of 8 is 4.'
        await pg.unroute('**/lesson/predict')
        async with pg.expect_response('**/lesson/predict') as got:
            await lock.click()
        resp = await got.value
        assert resp.status == 200, await resp.text()
        body = await resp.json()
        assert body['logged'] is True and body['message'].startswith('Saved. Next review '), body
        assert set(json.loads(resp.request.post_data)) == {'path', 'cell_id', 'demo', 'gate', 'picked', 'ans', 'ok', 'why', 'src'}
        await pg.wait_for_function("document.querySelector('#status')?.textContent.startsWith('Saved. Next review ')")
        await verdict.wait_for()
        assert (await verdict.inner_text()).startswith('You said 4. That is right.')
        assert await lock.is_hidden() and await note.is_hidden()
    asyncio.run(_real_page(go, tmp_path))
    rows = Learning(Memory(path=tmp_path/'learning.db', offline=True)._store('learning')).attempts('halves', limit=10)
    assert len(rows) == 1
    assert (bool(rows[0].correct), rows[0].depth, rows[0].answer, rows[0].thinking, rows[0].gate) == (True, 3, '4', 'Half of 8 is 4.', 'g1')
