import pytest

from tests.test_learn_agent_pane import _skip, _wait, pane  # noqa: F401
from tests.test_learn_tab_pages_slow import OUT, _env, _run

pytestmark = pytest.mark.slow

IDLE = "() => !document.querySelector('.abh[aria-busy]')"
POSTS = "window.__posts = []; const f = window.fetch; window.fetch = (u, o) => { if (o?.method === 'POST') window.__posts.push(String(u)); return f(u, o); }"
SAID = "() => document.querySelector('#agentlog').innerText"


async def _open(pg, ws, jid):
    ws.open_walk('workspace', jid); ws.save(); await pg.evaluate('mountTab()')
    await pg.locator('.abh #check .check').wait_for(timeout=30000)
    await pg.wait_for_function(IDLE, timeout=30000)
    await pg.evaluate(POSTS)


def test_the_button_turns_learn_mode_on_and_sends_the_question(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        await _open(pg, ws, jid)
        assert not await pg.evaluate('!!lee.agentLearnMode')
        await pg.locator('[data-learn-ask]').click()
        await pg.wait_for_function("() => document.querySelector('#agentlog').innerText.includes(\"I don't get this\")", timeout=15000)
        assert await pg.evaluate('lee.agentLearnMode') is True
        assert any(u.endswith('/agent/learn-mode') for u in await pg.evaluate('window.__posts'))
        assert await pg.locator('#agentprompt').input_value() == ''
        await pg.screenshot(path=f'{OUT}/p10-ask-button.png')
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_the_chord_asks_and_a_draft_or_a_busy_agent_sends_nothing(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        await _open(pg, ws, jid)
        await pg.locator('#agentprompt').fill('my own draft')
        await pg.keyboard.press('Control+Alt+Shift+Meta+KeyE')
        await pg.wait_for_function("() => /Send or clear your message/.test(document.body.innerText)", timeout=5000)
        assert await pg.locator('#agentprompt').input_value() == 'my own draft'
        assert not any(u.endswith('/agent/learn-mode') for u in await pg.evaluate('window.__posts'))
        await pg.locator('#agentprompt').fill('')
        await pg.evaluate('lee.agentBusy = true')
        await pg.keyboard.press('Control+Alt+Shift+Meta+KeyE')
        await pg.wait_for_function("() => /The agent is working/.test(document.body.innerText)", timeout=5000)
        assert not any(u.endswith('/agent/learn-mode') for u in await pg.evaluate('window.__posts'))
        await pg.evaluate('lee.agentBusy = false')
        await pg.keyboard.press('Control+Alt+Shift+Meta+KeyE')
        await pg.wait_for_function("() => document.querySelector('#agentlog').innerText.includes(\"I don't get this\")", timeout=15000)
        assert await pg.evaluate('lee.agentLearnMode') is True
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_the_palette_has_ask_about_this_page(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        await _open(pg, ws, jid)
        await pg.evaluate('palette()')
        await pg.locator('#cp').fill('ask about')
        assert 'Ask about this page' in await pg.locator('#cplist').inner_text()
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_change_with_the_builder_fills_a_draft_and_fetches_no_builder_page(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        seen = []
        pg.on('request', lambda r: seen.append(r.url) if '/build' in r.url else None)
        await _open(pg, ws, jid)
        await pg.locator('[data-learn-change]').click()
        await pg.wait_for_function('lee.agentLearnMode === true', timeout=15000)
        box = pg.locator('#agentprompt')
        assert await box.input_value() == 'Change this walk: '
        assert await box.evaluate('e => [e.selectionStart, e.selectionEnd, document.activeElement === e]') == [18, 18, True]
        assert 'Change this walk' not in await pg.evaluate(SAID)
        await pg.screenshot(path=f'{OUT}/p10-change-draft.png')
        await box.fill('')
        await pg.evaluate("document.querySelector('.abh main').insertAdjacentHTML('beforeend', '<a id=\"bb\" class=\"btn quiet build-beside\" href=\"/build/open?walk=x\">Change with the builder</a>')")
        await pg.locator('#bb').click()
        await pg.wait_for_function("() => document.querySelector('#agentprompt').value === 'Change this walk: '", timeout=5000)
        assert not seen, seen
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_the_open_page_loads_again_when_the_walk_changes_and_keeps_scroll_and_focus(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        await _open(pg, ws, jid)
        for _ in range(100):
            if ws.fs_watch.subs: break
            await pg.wait_for_timeout(100)
        await pg.evaluate("document.querySelector('.abh').style.paddingBottom = '3000px'")
        await pg.locator('.abh #ans').focus()
        top = await pg.evaluate("""() => { let e = document.querySelector('.abh'); while (e && !(e.scrollHeight > e.clientHeight + 500 && /auto|scroll/.test(getComputedStyle(e).overflowY))) e = e.parentElement;
            window.__sc = e; if (e) e.scrollTop = 400; return e ? e.scrollTop : -1 }""")
        assert top > 0, top
        reloads = []
        pg.on('request', lambda r: reloads.append(r.url) if f'/w/{jid}/0' in r.url else None)
        ws.fs_watch.announce_learn('some-other-walk')
        await pg.wait_for_timeout(800)
        assert not reloads, 'a change to another walk leaves this page alone'
        ws.fs_watch.announce_learn(jid)
        for _ in range(100):
            if reloads: break
            await pg.wait_for_timeout(100)
        assert reloads
        await pg.evaluate("() => leeAbhSettled(document.querySelector('.abh'))")
        await pg.wait_for_timeout(300)
        assert await pg.evaluate("window.__sc.scrollTop") == top
        assert await pg.evaluate("document.activeElement.id") == 'ans'
        await pg.screenshot(path=f'{OUT}/p10-reload.png')
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_a_typed_answer_is_not_wiped_by_the_reload(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        await _open(pg, ws, jid)
        for _ in range(100):
            if ws.fs_watch.subs: break
            await pg.wait_for_timeout(100)
        await pg.locator('.abh #ans').fill('half an answer')
        ws.fs_watch.announce_learn(jid)
        await pg.wait_for_function("() => /The plan changed/.test(document.body.innerText)", timeout=5000)
        assert await pg.locator('.abh #ans').input_value() == 'half an answer'
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_a_finished_change_job_and_each_hand_change_announce_the_walk(pane, monkeypatch):
    told = []
    monkeypatch.setattr(pane.ws.fs_watch, 'announce_learn', told.append)
    slug = pane.lr.journey(pane.jid).steps[1]['slug']
    pane.reply['text'] = _skip(slug)
    _wait(pane.ws, pane.tools['change_walk'](jid=pane.jid, instruction='skip the second idea'))
    assert told == [pane.jid]
    pane.tools['keep_idea'](jid=pane.jid, idea='1')
    pane.tools['move_idea'](jid=pane.jid, idea='2', to=1)
    pane.tools['list_versions'](jid=pane.jid)
    assert told == [pane.jid] * 3
    pane.tools['change_walk'](jid='nope', instruction='x')
    assert told == [pane.jid] * 3


def test_closing_a_side_walk_keeps_its_result_and_returns_to_the_step(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        back = []
        async def kept(route):
            back.append(route.request.method)
            await route.fulfill(status=302, headers={'Location': f'/learn/abh/w/{jid}/0?pane=1'})
        await pg.route('**/rh/back/**', kept)
        await _open(pg, ws, jid)
        await pg.evaluate("jid => abhyasaPane.open(`/w/${jid}/1`)", jid)
        await pg.wait_for_function("() => !document.querySelector('.abh[aria-busy]') && !document.querySelector('[data-learn-back]').disabled", timeout=15000)
        await pg.evaluate("abhyasaPane.close()")
        await pg.wait_for_function("() => document.querySelector('[data-learn-back]').disabled", timeout=15000)
        assert back == ['POST']
        await pg.locator('.abh #check .check').wait_for(timeout=15000)
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_explain_on_a_step_asks_the_agent_and_does_not_navigate(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        await _open(pg, ws, jid)
        before = await pg.evaluate("location.href + document.querySelector('.abh h1')?.textContent")
        await pg.locator('.abh [data-act=explain]').click()
        await pg.wait_for_function("() => document.querySelector('#agentlog').innerText.includes('Explain this step')", timeout=15000)
        assert await pg.evaluate('lee.agentLearnMode') is True
        assert await pg.evaluate("location.href + document.querySelector('.abh h1')?.textContent") == before
        await pg.screenshot(path=f'{OUT}/p10-explain.png')
        await pg.evaluate('lee.agentBusy = true')
        await pg.locator('.abh [data-act=explain]').click()
        await pg.wait_for_function("() => /The agent is working/.test(document.body.innerText)", timeout=5000)
    _run(tmp_path, scenario, dict(width=1500, height=900))
