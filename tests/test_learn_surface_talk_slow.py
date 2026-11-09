import re

import pytest

from tools.isolate import isolate

isolate()
pytestmark = pytest.mark.slow

from pathlib import Path
from tests.test_learn_tab_pages_slow import SHELL, _run

OUT = str(Path(__file__).resolve().parents[1]/'target')
MATH = 'The score is $x^2 + y^2 = z^2$ here.'
PLAN = '{"title": "Fractions", "subject": "maths", "steps": [{"name": "Equal parts", "statement": "A fraction names equal parts: $\\\\frac{1}{2}$ is one of two.", "ways": ["words"]}, {"name": "Adding fractions", "statement": "Fractions with one denominator add by adding numerators.", "ways": ["words"]}]}'


def _env(monkeypatch):
    from abhyasa.agent_tools import create_walk
    from abhyasa.learner import temp_learning
    from abhyasa.show import talk_from_walk
    from leela.blocks.learn import host
    from rupaka.spec import gallery
    lr = temp_learning()
    jid = create_walk(lr, lambda p, sp='': PLAN, 'fractions', settings={})['walk']
    steps = lr.journey(jid).steps
    lr.put_demo(gallery()['softmax-temperature'], steps[1]['slug'])
    lr.walk_step(jid, 1, check=dict(way='demo', kind='demo', depth=2, why=''))
    t = talk_from_walk(lr, lambda p, sp='': '{}', jid, fill=False)
    monkeypatch.setattr(host, 'learn_store', lambda ws, vault=None, write=False: ('test', lr))
    monkeypatch.setattr(host, 'HOSTS', ('127.0.0.1', 'localhost', '::1'))
    return lr, jid, t.id


async def _open(pg, ws, path, sel):
    await pg.evaluate('p => leeLearnOpen(p)', path)
    await pg.locator(sel).first.wait_for(timeout=30000)
    await pg.wait_for_timeout(800)


def _watch(pg):
    bad = []
    pg.on('pageerror', lambda e: bad.append(str(e)))
    pg.on('response', lambda r: bad.append((r.status, r.url)) if r.status >= 400 and '/git/file' not in r.url else None)
    return bad


def test_demo_step_locks_in_and_asks_the_agent(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, tid = _env(monkeypatch)
    async def scenario(pg, ws, port):
        bad = _watch(pg)
        for mode in ('light', 'dark'):
            await pg.evaluate(f"applyTheme('leela:{mode}:relaxed')")
            await _open(pg, ws, f'/w/{jid}/1', '.abh .walk-demo [data-rupaka]')
            await pg.screenshot(path=f'{OUT}/p7-demo-{mode}.png')
            await pg.set_viewport_size(dict(width=1500, height=1700))
            await pg.locator('.abh .walk-demo').screenshot(path=f'{OUT}/p7-demo-card-{mode}.png')
            await pg.set_viewport_size(dict(width=1500, height=900))
        await pg.evaluate("applyTheme('leela:light:relaxed')")
        await pg.wait_for_timeout(1500)
        card = pg.locator('.abh .walk-demo')
        await card.locator('button', has_text='It falls').click()
        async with pg.expect_response(lambda r: r.url.endswith('/predict') and r.request.method == 'POST') as got:
            await card.locator('button', has_text='Lock in').click()
        r = await got.value
        assert r.ok and r.url.endswith(f'/w/{jid}/1/predict'), r.url
        await pg.wait_for_timeout(1200)
        assert [a for a in lr.attempts() if a.kind == 'demo']
        await pg.screenshot(path=f'{OUT}/p7-demo-locked-light.png')
        await pg.evaluate("window.__sent = []; window.sendAgent = () => { window.__sent.push($('#agentprompt').value) }; 0")
        await card.get_by_role('button', name='Ask about this').click()
        await card.get_by_label('Your question').fill('Why does Paris fall?')
        await card.get_by_role('button', name='Ask', exact=True).click()
        await pg.wait_for_function('window.__sent.length')
        sent = await pg.evaluate('window.__sent')
        assert 'Why does Paris fall?' in sent[0] and 'About the demo' in sent[0], sent
        assert await pg.locator('#agentprompt').count()
        assert not bad, bad
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_talk_pages_render_in_the_tab(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, tid = _env(monkeypatch)
    async def scenario(pg, ws, port):
        bad = _watch(pg)
        for mode in ('light', 'dark'):
            await pg.evaluate(f"applyTheme('leela:{mode}:relaxed')")
            await _open(pg, ws, '/talks', '.abh main')
            await pg.screenshot(path=f'{OUT}/p8-talks-{mode}.png')
            await _open(pg, ws, f'/t/{tid}', '.abh .slide, .abh #deck')
            await pg.screenshot(path=f'{OUT}/p8-talk-{mode}.png')
        assert not bad, bad
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_talk_editor_saves_slot_title_drag_and_add(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, tid = _env(monkeypatch)
    async def scenario(pg, ws, port):
        bad = _watch(pg)
        await _open(pg, ws, f'/t/{tid}', '.abh #deck > li')
        rows = pg.locator('.abh #deck > li.edit-row')
        n = await rows.count()
        assert n == len(lr.talk(tid).slides)
        async with pg.expect_response(lambda r: r.url.endswith(f'/t/{tid}/slot')) as got:
            await pg.locator('.abh input[name=minutes]').fill('20')
            await pg.locator('.abh input[name=minutes]').blur()
        assert (await got.value).ok and lr.talk(tid).minutes == 20
        first = rows.first
        await first.locator('summary').first.click()
        title = first.locator('input[name=title]')
        async with pg.expect_response(lambda r: '/slide' in r.url and r.request.method == 'POST') as got:
            await title.fill('Equal parts, in short')
        assert (await got.value).ok
        await pg.wait_for_timeout(900)
        assert lr.talk(tid).slides[0]['title'] == 'Equal parts, in short'
        assert await pg.locator('.abh #undo-bar').count()
        await first.locator('summary').first.click()
        ids = [s['id'] for s in lr.talk(tid).slides]
        a, b = await rows.nth(0).locator('.grip').bounding_box(), await rows.nth(2).bounding_box()
        await pg.mouse.move(a['x'] + 4, a['y'] + 8); await pg.mouse.down()
        await pg.mouse.move(a['x'] + 4, b['y'] + b['height'] - 6, steps=12); await pg.mouse.up()
        await pg.wait_for_timeout(1200)
        assert [s['id'] for s in lr.talk(tid).slides] != ids
        await pg.locator('.abh button', has_text='Add a slide').first.click()
        await pg.wait_for_function('n => document.querySelectorAll("#deck > li.edit-row").length === n + 1', arg=n)
        assert len(lr.talk(tid).slides) == n + 1
        await pg.wait_for_timeout(500)
        await pg.screenshot(path=f'{OUT}/p8-talk-edited-light.png')
        assert not bad, bad
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_present_runs_the_stage_in_the_tab_and_escape_leaves(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, tid = _env(monkeypatch)
    async def scenario(pg, ws, port):
        bad = _watch(pg)
        await pg.evaluate("applyTheme('leela:light:relaxed')")
        shell = await pg.evaluate(SHELL)
        for mode in ('light', 'dark'):
            await pg.evaluate(f"applyTheme('leela:{mode}:relaxed')")
            await _open(pg, ws, f'/t/{tid}', '.abh #deck > li')
            await pg.locator('.abh .talk-top button', has_text='Present').click()
            frame = pg.frame_locator('iframe.lee-present')
            await frame.locator('#talk.pv #stage').wait_for(timeout=30000)
            await frame.locator('#now').filter(has_text='slide').wait_for()
            was = await frame.locator('#now').text_content()
            box = await pg.locator('iframe.lee-present').bounding_box()
            assert box['width'] == 1500 and box['height'] == 900
            await pg.wait_for_timeout(800)
            await pg.screenshot(path=f'{OUT}/p8-present-{mode}.png')
            await pg.locator('iframe.lee-present').focus()
            await pg.keyboard.press('KeyD')
            await pg.wait_for_function("old => document.querySelector('iframe.lee-present').contentDocument.getElementById('now').textContent !== old", arg=was)
            assert lr.talk(tid).live
            await pg.keyboard.press('Escape')
            await pg.wait_for_selector('iframe.lee-present', state='detached')
            await pg.locator('.abh #deck > li').first.wait_for()
        await pg.evaluate("applyTheme('leela:light:relaxed')")
        await pg.locator('.abh .talk-top button', has_text='Present').click()
        frame = pg.frame_locator('iframe.lee-present')
        await frame.locator('#end-form button').click()
        await pg.wait_for_selector('iframe.lee-present', state='detached')
        await pg.wait_for_function("() => document.querySelector('.abh main')?.textContent.includes('After')")
        assert not lr.talk(tid).get('live')
        await pg.wait_for_timeout(600)
        await pg.screenshot(path=f'{OUT}/p8-after-light.png')
        assert await pg.evaluate(SHELL) == shell
        assert not bad, bad
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_maths_draws_on_a_concept_a_slide_and_the_stage(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, tid = _env(monkeypatch)
    slug = lr.journey(jid).steps[0]['slug']
    t = lr.talk(tid)
    lr.put_talk({**t, 'slides': [{**t['slides'][0], 'body': [MATH], 'title': 'Pythagoras $a^2$'}, *t['slides'][1:]]})
    async def scenario(pg, ws, port):
        bad = _watch(pg)
        await _open(pg, ws, f'/c/{slug}', '.abh main')
        await pg.wait_for_selector('.abh .katex', timeout=10000)
        await pg.screenshot(path=f'{OUT}/p8-math-concept-light.png')
        await _open(pg, ws, f'/t/{tid}', '.abh #deck > li')
        await pg.wait_for_selector('.abh #deck .katex', timeout=10000)
        await pg.locator('.abh .talk-top button', has_text='Present').click()
        frame = pg.frame_locator('iframe.lee-present')
        await frame.locator('#stage .katex').first.wait_for(timeout=10000)
        await pg.wait_for_timeout(600)
        await pg.screenshot(path=f'{OUT}/p8-math-present-light.png')
        await pg.keyboard.press('Escape')
        assert not bad, bad
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_make_it_again_and_the_talks_list_work_in_the_tab(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, tid = _env(monkeypatch)
    lr.walk_step(jid, 0, note='A new note for the first idea.')
    async def scenario(pg, ws, port):
        bad = _watch(pg)
        await pg.evaluate("applyTheme('leela:light:relaxed')")
        await _open(pg, ws, '/talks', f'.abh a[href="/t/{tid}"]')
        assert await pg.locator('.abh button, .abh input[type=submit]', has_text='Present').count()
        await pg.screenshot(path=f'{OUT}/p8-talks-list-light.png')
        await pg.locator(f'.abh a[href="/t/{tid}"]').first.click()
        again = pg.locator('.abh button', has_text='Make it again').first
        await again.evaluate("el => { el.closest('details').open = true }")
        await again.wait_for()
        await pg.screenshot(path=f'{OUT}/p8-talk-again-light.png')
        async with pg.expect_response(lambda r: r.url.endswith('/talk/new') and r.request.method == 'POST') as got:
            await again.click()
        assert (await got.value).ok
        await pg.locator('.abh .pending, .abh .talk-new, .abh [data-job]').first.wait_for(timeout=15000)
        assert not [b for b in bad if not isinstance(b, tuple)], bad
    _run(tmp_path, scenario, dict(width=1500, height=900))
