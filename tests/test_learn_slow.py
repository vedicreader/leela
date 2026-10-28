"The /learn side page in a browser: the step page, the split pane, nested back, the reload restore, the origin check and the lookup page."

import pytest

pytestmark = pytest.mark.slow

import asyncio, json, os, sys
from pathlib import Path

pytest.importorskip('playwright.async_api')
from playwright.async_api import async_playwright   # noqa: E402

import test_web_slow   # noqa: E402
from test_web_slow import _free_port, _serve, _launch, _started, fake_kernels, fake_model   # noqa: E402
from abhyasa.store import Learning   # noqa: E402
from leela.blocks.memory.memory import Memory   # noqa: E402
from leela.workspace import Workspace   # noqa: E402
from learn_data import JID, walk   # noqa: E402

SHOTS = Path(__file__).parents[1]/'target/learn-shots'
VIEW = {'width': 1440, 'height': 900}
STEP0, STEP1 = f'/learn?walk={JID}&step=0', f'/learn?walk={JID}&step=1'
HEAD = '#editor2 .lee-split-trail'
SAVED = "localStorage.getItem('lee-editor-split')"

def _ws(root, monkeypatch):
    "A workspace on `root` alone, with an offline vault in `root` that holds the walk `JID`."
    ws = Workspace(roots=[root], approvals='auto', python=sys.executable)
    monkeypatch.setattr(ws, 'memory', Memory(path=root/'vault.db', offline=True))
    monkeypatch.setattr(ws.search, 'prefer_kosha', False)   # no code index outside `root`
    walk(Learning(ws.memory._store('learning')))
    return ws

def _watch(pg, base):
    "The console errors, page errors, failed requests and error responses of Leela's own pages."
    # `/git/file` answers 400 for a file outside any repository, as `notes.txt` in `tmp_path` is; the editor catches it
    bad, own = [], lambda u: (u or '').startswith(base) and 'favicon' not in u and '/git/file?' not in u
    def con(m):
        u = (m.location or {}).get('url', '')
        if m.type == 'error' and (not u or own(u)): bad.append(f'console: {m.text} at {u}')
    pg.on('console', con)
    pg.on('pageerror', lambda e: bad.append(f'pageerror: {e}'))
    pg.on('requestfailed', lambda r: own(r.url) and bad.append(f'failed: {r.url} {r.failure}'))
    pg.on('response', lambda r: own(r.url) and r.status >= 400 and bad.append(f'{r.status}: {r.url}'))
    return bad

async def _ide(pg, base):
    await pg.goto(base + '/', wait_until='networkidle')
    await pg.wait_for_function('window.lee && lee.keys.length')
    if await pg.locator('.lee-modal').count(): await pg.keyboard.press('Escape')

async def _on_learn(fn, ws, ide=True):
    "`_on_page` for a prepared workspace: headless, local requests only, one browser closed in a finally."
    if test_web_slow.CHROMIUM and 'Google Chrome' in test_web_slow.CHROMIUM: pytest.skip('LEELA_CHROMIUM names a Chrome install')
    real_kernels = fake_kernels(); fake_model(ws)
    port = _free_port(); base = f'http://127.0.0.1:{port}'
    srv = _serve(ws, port)
    try:
        await _started(srv)
        async with async_playwright() as pw:
            b = await _launch(pw)
            try:
                ctx = await b.new_context(viewport=VIEW)
                async def local(r):
                    if r.request.url.startswith(base): await r.continue_()
                    else: await r.abort()
                await ctx.route('**/*', local)
                pg = await ctx.new_page(); pg.set_default_timeout(15000)
                bad = _watch(pg, base)
                if ide: await _ide(pg, base)
                await fn(pg, base)
                assert bad == [], bad
            finally: await b.close()
    finally:
        srv.should_exit = True
        ws.shutdown_now()
        real_kernels()

async def _shoot(pg, name, ide=False):
    "Light and dark screenshots when `LEELA_SHOTS=1`: the IDE through `applyTheme`, a learn page through the colour scheme its stylesheet follows."
    if os.environ.get('LEELA_SHOTS') != '1': return
    SHOTS.mkdir(parents=True, exist_ok=True)
    for mode in ('light', 'dark'):
        await pg.emulate_media(color_scheme=mode)
        if ide: await pg.evaluate('m => applyTheme(`leela:${m}:relaxed`)', mode)
        await pg.wait_for_timeout(800)   # the theme change is a CSS transition
        await pg.screenshot(path=str(SHOTS/f'{name}-{mode}.png'))

async def _side(pg, root, url=STEP0, title='Softmax'):
    "Open a text file, then `url` as the side page; the frame once it has said where it is."
    f = root/'notes.txt'; f.write_text('hello\n')
    await pg.evaluate('p => leeOpenFile(p)', str(f))
    await pg.wait_for_selector('.cm-content')
    assert await pg.evaluate('([u, t]) => window.leeSidePage.open(u, t)', [url, title]) is True
    frame = await (await pg.wait_for_selector('#editor2 iframe')).content_frame()
    await frame.wait_for_url('**pane=1**'); await frame.wait_for_load_state('load')
    return frame

def test_step_page_in_a_tab_of_its_own(tmp_path, monkeypatch):
    async def go(pg, base):
        await pg.goto(base + STEP0, wait_until='networkidle')
        assert await pg.locator('h1').inner_text() == 'Attention'
        assert await pg.locator('.lee-learn-section').inner_text() == '2 Background'
        assert await pg.locator('blockquote').inner_text() == 'Softmax maps scores to weights.'
        assert await pg.locator('.lee-learn-note').inner_text() == 'Watch the sum.'
        assert await pg.get_by_role('button', name='Open as a lesson').count() == 1
        font = await pg.evaluate('getComputedStyle(document.body).fontFamily')
        assert font and 'Times' not in font and font.strip('"') != 'serif', font
        assert not await pg.evaluate("document.documentElement.classList.contains('in-pane')")
        await _shoot(pg, 'step-page')
    asyncio.run(_on_learn(go, _ws(tmp_path, monkeypatch), ide=False))

def test_side_page_opens_in_the_split(tmp_path, monkeypatch):
    async def go(pg, base):
        frame = await _side(pg, tmp_path)
        assert await pg.evaluate("!document.querySelector('#editor2').hidden && document.querySelector('#editorstage').classList.contains('split')")
        assert 'pane=1' in frame.url and STEP0.split('?')[1] in frame.url
        assert await frame.evaluate("document.documentElement.classList.contains('in-pane')")
        assert await frame.locator('blockquote').inner_text() == 'Softmax maps scores to weights.'
        await pg.wait_for_function(f"document.querySelector('{HEAD} strong')?.textContent === 'Attention'")
        assert json.loads(await pg.evaluate(SAVED)) == {'page': STEP0, 'title': 'Attention', 'direction': 'vertical'}
        await _shoot(pg, 'ide-with-side-page', ide=True)
    asyncio.run(_on_learn(go, _ws(tmp_path, monkeypatch)))

def test_escape_goes_back_along_the_trail_then_closes(tmp_path, monkeypatch):
    async def go(pg, base):
        frame = await _side(pg, tmp_path)
        await pg.wait_for_function(f"document.querySelector('{HEAD} strong')?.textContent === 'Attention'")
        await frame.evaluate("u => parent.postMessage({type: 'rh:open', url: u}, location.origin)", STEP1)
        await frame.wait_for_url('**step=1**'); await frame.wait_for_load_state('load')
        assert 'Attention mixes values.' in await frame.locator('blockquote').inner_text()
        await frame.evaluate("([u, t]) => parent.postMessage({type: 'rh:at', url: u, title: 'Attention', trail: t}, location.origin)",
                             [STEP1, [['Softmax', STEP0]]])
        await pg.wait_for_function(f"document.querySelector('{HEAD} a')?.textContent === 'Softmax'")
        await frame.locator('h1').click(); await pg.keyboard.press('Escape')
        await frame.wait_for_url('**step=0**'); await frame.wait_for_load_state('load')
        assert await frame.locator('blockquote').inner_text() == 'Softmax maps scores to weights.'
        await pg.wait_for_function(f"!document.querySelector('{HEAD} a')")
        assert json.loads(await pg.evaluate(SAVED))['page'] == STEP0
        await frame.locator('h1').click(); await pg.keyboard.press('Escape')
        await pg.wait_for_function("!document.querySelector('#editor2 iframe') && document.querySelector('#editor2').hidden")
        assert await pg.evaluate(SAVED) is None
    asyncio.run(_on_learn(go, _ws(tmp_path, monkeypatch)))

def test_reload_restores_a_local_page_and_drops_any_other(tmp_path, monkeypatch):
    async def go(pg, base):
        await _side(pg, tmp_path)
        await pg.wait_for_function(f"document.querySelector('{HEAD} strong')?.textContent === 'Attention'")
        await pg.reload(wait_until='networkidle'); await pg.wait_for_function('window.lee && lee.keys.length')
        await pg.wait_for_function("document.querySelector('#editor2 iframe')?.getAttribute('src')?.includes('pane=1')")
        src = await pg.evaluate("document.querySelector('#editor2 iframe').getAttribute('src')")
        assert src == STEP0 + '&pane=1', src
        assert json.loads(await pg.evaluate(SAVED))['page'] == STEP0
        await pg.evaluate("localStorage.setItem('lee-editor-split', JSON.stringify({page: 'https://evil.example/'}))")
        await pg.reload(wait_until='networkidle'); await pg.wait_for_function('window.lee && lee.keys.length')
        await pg.wait_for_function(f'{SAVED} === null')
        assert await pg.evaluate("!document.querySelector('#editor2 iframe') && document.querySelector('#editor2').hidden")
    asyncio.run(_on_learn(go, _ws(tmp_path, monkeypatch)))

STATE = f"""() => {{ const f = document.querySelector('#editor2 iframe');
  return [lee.sidePage?.url, lee.sidePage?.title, f?.contentWindow.location.href, {SAVED}, document.querySelector('{HEAD}')?.textContent]; }}"""
SEND = """([origin, u]) => { const w = document.querySelector('#editor2 iframe').contentWindow;
  for (const data of [{type: 'rh:open', url: u}, {type: 'rh:at', url: u, title: 'Evil', trail: [['x', '/x']]}, {type: 'rh:close'}])
    window.dispatchEvent(new MessageEvent('message', {data, origin, source: w})); }"""

def test_a_message_from_another_origin_changes_nothing(tmp_path, monkeypatch):
    async def go(pg, base):
        frame = await _side(pg, tmp_path)
        await pg.wait_for_function(f"document.querySelector('{HEAD} strong')?.textContent === 'Attention'")
        before = await pg.evaluate(STATE)
        await pg.evaluate(SEND, ['https://evil.example', STEP1])
        await pg.wait_for_timeout(700)
        assert await pg.evaluate(STATE) == before and 'step=0' in frame.url
        # the same event from this origin does act, so the check above reached the handler
        await pg.evaluate("""o => window.dispatchEvent(new MessageEvent('message', {origin: o, source: document.querySelector('#editor2 iframe').contentWindow,
            data: {type: 'rh:at', url: '/learn?walk=attention-ab12&step=0', title: 'Control', trail: []}}))""", base)
        await pg.wait_for_function(f"document.querySelector('{HEAD} strong')?.textContent === 'Control'")
    asyncio.run(_on_learn(go, _ws(tmp_path, monkeypatch)))

def test_lookup_page_in_the_pane(tmp_path, monkeypatch):
    async def go(pg, base):
        r = await pg.goto(base + '/learn/lookup?q=x&pane=1', wait_until='networkidle')
        assert r.status == 200
        if r.headers['content-type'].startswith('text/plain'): assert await pg.locator('body').inner_text() == 'No code index for this yet.'
        else: assert await pg.locator('form[action="/learn/lookup"] input[type=search]').count() == 1
        await _ide(pg, base)
        frame = await _side(pg, tmp_path, '/learn/lookup?q=x', 'Look up code')
        assert 'No code index for this yet.' in await frame.locator('body').inner_text() or await frame.locator('input[type=search]').count() == 1
        await _shoot(pg, 'lookup-pane', ide=True)
    asyncio.run(_on_learn(go, _ws(tmp_path, monkeypatch), ide=False))
