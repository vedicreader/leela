"The /learn side page in a browser: the step page, the split pane, nested back, the reload restore, the origin check and the lookup page."

import pytest

pytestmark = pytest.mark.slow

import asyncio, json, os, re, sys
from pathlib import Path

pytest.importorskip('playwright.async_api')
from playwright.async_api import async_playwright   # noqa: E402

import test_web_slow   # noqa: E402
from test_web_slow import _free_port, _serve, _launch, _started, fake_kernels, fake_model   # noqa: E402
from abhyasa.learner import Learning   # noqa: E402
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
    monkeypatch.setattr('leela.blocks.learn.learn.LESSONS', root.parent/f'{root.name}-home'/'Learning'/'Leela lessons')   # never the owner's folder
    ws = Workspace(roots=[root], approvals='auto', python=sys.executable)
    monkeypatch.setattr(ws, 'memory', Memory(path=root/'vault.db', offline=True))
    monkeypatch.setattr(ws.search, 'prefer_kosha', False)   # no code index outside `root`
    walk(Learning(ws.memory._store('learning')))
    return ws

def _watch(pg, base):
    "The console errors, page errors, failed requests and error responses of Leela's own pages."
    # `/git/file` answers 400 for a file outside any repository, as every file in `tmp_path` is; the editor catches it. `/git/notebook` answers 200 there.
    bad, own = [], lambda u: (u or '').startswith(base) and 'favicon' not in u and '/git/file?' not in u
    def con(m):
        u = (m.location or {}).get('url', '')
        if m.type == 'error' and (not u or own(u)): bad.append(f'console: {m.text} at {u}')
    pg.on('console', con)
    pg.on('pageerror', lambda e: bad.append(f'pageerror: {e}'))
    # core.js TAB_READS: a read about the tab on screen is aborted when that tab redraws or closes, by design
    ended = lambda r: 'ERR_ABORTED' in (r.failure or '') and re.match(r'/(lsp/(symbols|inlay-hints|hover)|lint|git/file|outline|editor/packages)(\?|$)', r.url[len(base):])
    pg.on('requestfailed', lambda r: own(r.url) and not ended(r) and bad.append(f'failed: {r.url} {r.failure}'))
    pg.on('response', lambda r: own(r.url) and r.status >= 400 and bad.append(f'{r.status}: {r.url}'))
    return bad

async def _ide(pg, base):
    await pg.goto(base + '/', wait_until='networkidle')
    await pg.wait_for_function('window.lee && lee.keys.length')
    if await pg.locator('.lee-modal').count(): await pg.keyboard.press('Escape')

async def _on_learn(fn, ws, ide=True, serve=_serve):
    "`_on_page` for a prepared workspace: headless, local requests only, one browser closed in a finally. `serve(ws, port)` starts the server."
    if test_web_slow.CHROMIUM and 'Google Chrome' in test_web_slow.CHROMIUM: pytest.skip('LEELA_CHROMIUM names a Chrome install')
    real_kernels = fake_kernels(); fake_model(ws)
    port = _free_port(); base = f'http://127.0.0.1:{port}'
    srv = serve(ws, port)
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
    "Light and dark screenshots when `LEELA_SHOTS=1`: the IDE through `applyTheme`, a learn page through the cached theme its first paint reads."
    if os.environ.get('LEELA_SHOTS') != '1': return
    SHOTS.mkdir(parents=True, exist_ok=True)
    for mode in ('light', 'dark'):
        await pg.emulate_media(color_scheme=mode)
        if ide: await pg.evaluate('m => applyTheme(`leela:${m}:relaxed`)', mode)
        else: await pg.evaluate("m => localStorage.setItem('lee-theme', `leela:${m}:relaxed`)", mode); await pg.reload(wait_until='networkidle')
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

BG = 'getComputedStyle(document.body).backgroundColor'

def test_a_pane_in_a_dark_ide_on_a_light_os_is_dark_and_follows_the_ide(tmp_path, monkeypatch):
    async def go(pg, base):
        await pg.emulate_media(color_scheme='light')
        await pg.evaluate("applyTheme('leela:dark:relaxed')")
        await pg.evaluate("localStorage.setItem('lee-theme', 'leela:light:relaxed')")   # the frame's own first paint reads light
        frame = await _side(pg, tmp_path)
        ide = 'rgb(13, 17, 23)'   # the theme change is a CSS transition: wait for its end colour, not for a fixed time
        await pg.wait_for_function(f"getComputedStyle(document.querySelector('#editor')).backgroundColor === {ide!r}")
        assert await frame.evaluate('[document.documentElement.dataset.theme, document.documentElement.dataset.mode, document.documentElement.style.colorScheme]') == ['leela', 'dark', 'dark']
        await frame.wait_for_function(f'{BG} === {ide!r}')
        await pg.evaluate("applyTheme('leela:light:relaxed')")
        await frame.wait_for_function(f"{BG} === 'rgb(255, 255, 255)' && document.documentElement.dataset.mode === 'light'")
    asyncio.run(_on_learn(go, _ws(tmp_path, monkeypatch)))

def test_a_long_step_page_in_a_tab_of_its_own_scrolls(tmp_path, monkeypatch):
    ws = _ws(tmp_path, monkeypatch)
    lr = Learning(ws.memory._store('learning')); j = walk(lr)
    lr.put_journey({**j, 'id': 'long-0001', 'steps': [{**j.steps[0], 'read': {**j.steps[0]['read'], 'text': '\n\n'.join(f'line {i}' for i in range(200))}}]})
    async def go(pg, base):
        await pg.goto(base + '/learn?walk=long-0001&step=0', wait_until='networkidle')
        assert await pg.evaluate('document.scrollingElement.scrollHeight > document.scrollingElement.clientHeight')
        await pg.evaluate('window.scrollTo(0, 600)')
        assert await pg.evaluate('document.scrollingElement.scrollTop') == 600
    asyncio.run(_on_learn(go, ws, ide=False))

def test_a_step_page_in_a_tab_of_its_own_uses_the_saved_theme(tmp_path, monkeypatch):
    from leela.blocks.settings.settings import theme_backgrounds
    (tmp_path/'.leela').mkdir(exist_ok=True)
    (tmp_path/'.leela/settings.json').write_text(json.dumps({'appearance': {'theme': 'nord:dark:tight'}}))
    want = theme_backgrounds()['nord']['dark'].lstrip('#')
    rgb = 'rgb({}, {}, {})'.format(*(int(want[i:i + 2], 16) for i in (0, 2, 4)))
    async def go(pg, base):
        await pg.emulate_media(color_scheme='light')
        await pg.goto(base + STEP0, wait_until='networkidle')
        assert await pg.evaluate('[document.documentElement.dataset.theme, document.documentElement.dataset.mode, document.documentElement.dataset.density]') == ['nord', 'dark', 'tight']
        assert await pg.evaluate(BG) == rgb
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
        assert not await frame.locator('h1').is_visible()   # the split head shows the title
        await frame.locator('blockquote').click(); await pg.keyboard.press('Escape')
        await frame.wait_for_url('**step=0**'); await frame.wait_for_load_state('load')
        assert await frame.locator('blockquote').inner_text() == 'Softmax maps scores to weights.'
        await pg.wait_for_function(f"!document.querySelector('{HEAD} a')")
        assert json.loads(await pg.evaluate(SAVED))['page'] == STEP0
        await frame.locator('blockquote').click(); await pg.keyboard.press('Escape')
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

def test_open_as_a_lesson_from_the_pane(tmp_path, monkeypatch):
    p = str((tmp_path/'lessons'/f'{JID}-0.ipynb').resolve())
    async def go(pg, base):
        frame = await _side(pg, tmp_path)
        await frame.get_by_role('button', name='Open as a lesson').click()
        await frame.wait_for_url('**/learn/open'); await frame.wait_for_load_state('load')
        assert await frame.locator('main.lee-learn > p.lee-learn-line').inner_text() == 'Opened in Leela.'
        assert await frame.evaluate("document.documentElement.classList.contains('in-pane')")
        await pg.wait_for_function(f"document.querySelector('{HEAD} strong')?.textContent === 'Attention'")   # the pane head keeps the step's title
        await _shoot(pg, 'opened-pane', ide=True)
        await pg.wait_for_function(f'(JSON.parse({SAVED} || "null") || {{}}).page === {json.dumps(STEP0)}')   # a reload mounts the step, not POST-only /learn/open
        await pg.wait_for_function('p => lee.path === p', arg=p)
        assert await pg.evaluate("!document.querySelector('#editor2').hidden && !!document.querySelector('#editor2 iframe')")
        q = pg.locator('.lee-cell[data-i="0"] .lee-md-cell blockquote')
        await q.wait_for()
        assert await q.evaluate("e => { const s = getComputedStyle(e); return [s.marginLeft, s.borderLeftWidth, s.textAlign]; }") == ['0px', '2px', 'start']   # the step reads as a quote, not an indented block
        await _shoot(pg, 'opened-lesson', ide=True)
        assert Path(p).is_file()
        await frame.get_by_role('link', name='Back to the step').click()
        await frame.wait_for_url('**step=0**pane=1**'); await frame.wait_for_load_state('load')
        assert await frame.get_by_role('button', name='Open as a lesson').count() == 1
    asyncio.run(_on_learn(go, _ws(tmp_path, monkeypatch)))

def test_option_s_opens_the_lesson_in_a_tab_and_in_the_pane(tmp_path, monkeypatch):
    p = str((tmp_path/'lessons'/f'{JID}-0.ipynb').resolve())
    OPENED = 'main.lee-learn > p.lee-learn-line'
    async def go(pg, base):
        await pg.goto(base + STEP0, wait_until='networkidle')
        await pg.locator('blockquote').click(); await pg.keyboard.press('Alt+s')
        await pg.wait_for_url(base + '/'); await pg.wait_for_function('p => window.lee && lee.path === p', arg=p)   # a tab of its own goes to the IDE
        await _ide(pg, base)
        frame = await _side(pg, tmp_path)
        await frame.locator('blockquote').click(); await frame.locator('body').press('Alt+s')
        await frame.wait_for_url('**/learn/open'); await frame.wait_for_load_state('load')
        assert await frame.locator(OPENED).inner_text() == 'Opened in Leela.'
        await pg.wait_for_function('p => lee.path === p', arg=p)
    asyncio.run(_on_learn(go, _ws(tmp_path, monkeypatch), ide=False))

SCRATCH = """p => fetch('/learn/scratch', {method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({path: p, snippet: 'print("scratch 7c1")'})}).then(r => r.status)"""

def test_a_scratch_cell_appears_in_the_open_notebook_with_no_other_edit(tmp_path, monkeypatch):
    from leela.blocks.nb.lesson import lesson_notebook
    p = (tmp_path/'lesson.ipynb').resolve(); lesson_notebook('Doubling').save(p)
    async def go(pg, base):
        await pg.evaluate('p => leeOpenFile(p)', str(p))
        await pg.wait_for_selector('.lee-cell')
        await pg.evaluate('document.activeElement?.blur()')
        assert await pg.evaluate(SCRATCH, str(p)) == 200
        await pg.wait_for_function("[...document.querySelectorAll('.lee-cell')].some(c => c.textContent.includes('scratch 7c1'))")
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
        assert r.status == 200 and r.headers['content-type'].startswith('text/html')
        assert await pg.locator('form[action="/learn/lookup"] input[type=search].lee-input[placeholder="What to look for"]').count() == 1
        assert await pg.locator('main.lee-learn > p.lee-learn-line').first.inner_text() in ('No code index yet.', 'Nothing found.')
        await _ide(pg, base)
        frame = await _side(pg, tmp_path, '/learn/lookup?q=x', 'Look up code')
        assert await frame.locator('input[type=search]').count() == 1
        assert await pg.evaluate("!document.activeElement || document.activeElement.tagName !== 'IFRAME'"), 'the pane took focus from the IDE'
        await _shoot(pg, 'lookup-pane', ide=True)
    asyncio.run(_on_learn(go, _ws(tmp_path, monkeypatch), ide=False))

MATHS = dict(text='Weights $w_i$ sum to 1.\n\n$$\\sum_i w_i = 1$$\n\n```python\nprint(1 < 2)\n```', note='Watch **the sum**.')

def test_a_step_page_draws_its_maths_and_moves_between_steps(tmp_path, monkeypatch):
    ws = _ws(tmp_path, monkeypatch)
    lr = Learning(ws.memory._store('learning')); j = lr.journey(JID)
    lr.put_journey({**j, 'steps': [{**j.steps[0], 'read': dict(section='2 Background', text=MATHS['text']), 'note': MATHS['note']}, j.steps[1]]})
    async def go(pg, base):
        await pg.goto(base + STEP0, wait_until='networkidle')
        await pg.wait_for_selector('blockquote .katex'); await pg.wait_for_selector('blockquote .katex-display')
        assert await pg.locator('blockquote pre code').inner_text() == 'print(1 < 2)\n'
        assert await pg.locator('.lee-learn-note strong').inner_text() == 'the sum'
        assert await pg.locator('.lee-learn-steps span').inner_text() == 'Idea 1 of 2' and await pg.get_by_role('link', name='Previous idea').count() == 0
        await _shoot(pg, 'step-maths')
        await _ide(pg, base)
        frame = await _side(pg, tmp_path)
        await frame.wait_for_selector('blockquote .katex')
        await frame.get_by_role('link', name='Next idea').click()
        await frame.wait_for_url('**step=1**pane=1**'); await frame.wait_for_load_state('load')
        assert 'Attention mixes values.' in await frame.locator('blockquote').inner_text()
        assert await frame.locator('.lee-learn-steps span').inner_text() == 'Idea 2 of 2'
        await pg.wait_for_function(f"(JSON.parse({SAVED} || 'null') || {{}}).page?.includes('step=1')")
        await frame.get_by_role('link', name='Previous idea').click()
        await frame.wait_for_url('**step=0**pane=1**')
    asyncio.run(_on_learn(go, ws, ide=False))

WIDTH = "document.querySelector('#editor').getBoundingClientRect().width / document.querySelector('#editorstage').getBoundingClientRect().width"

def test_the_split_resizes_by_drag_and_keys_and_keeps_its_size(tmp_path, monkeypatch):
    async def go(pg, base):
        await _side(pg, tmp_path)
        bar = pg.locator('.lee-editor-splitter')
        assert abs(await pg.evaluate(WIDTH) - .5) < .02
        box, stage = await bar.bounding_box(), await pg.locator('#editorstage').bounding_box()
        await pg.mouse.move(box['x'] + 1, box['y'] + 40); await pg.mouse.down()
        await pg.mouse.move(stage['x'] + stage['width'] * .65, box['y'] + 40, steps=8)   # across the side page's frame
        await pg.mouse.up()
        assert abs(await pg.evaluate(WIDTH) - .65) < .03, await pg.evaluate(WIDTH)
        await bar.focus(); await pg.keyboard.press('ArrowLeft'); await pg.keyboard.press('ArrowLeft')
        assert abs(await pg.evaluate(WIDTH) - .55) < .03 and await bar.get_attribute('aria-valuenow') == '55'
        for _ in range(12): await pg.keyboard.press('ArrowLeft')
        assert await bar.get_attribute('aria-valuenow') == '20' and await pg.evaluate("localStorage.getItem('lee-editor-split-size')") == '20'
        assert not await pg.evaluate("document.querySelector('#editor2').hidden"), 'an arrow key on the splitter reached another binding'
        await pg.keyboard.press('ArrowRight'); await pg.keyboard.press('ArrowRight')
        await pg.reload(wait_until='networkidle'); await pg.wait_for_function('window.lee && lee.keys.length')
        await pg.wait_for_function("document.querySelector('#editor2 iframe')")
        assert abs(await pg.evaluate(WIDTH) - .30) < .03, await pg.evaluate(WIDTH)
        await pg.evaluate('leeCloseSplit()'); await pg.evaluate('([u, t]) => window.leeSidePage.open(u, t)', [STEP0, 'Softmax'])
        await pg.wait_for_function("document.querySelector('#editor2 iframe')")
        assert abs(await pg.evaluate(WIDTH) - .30) < .03, 'closing the split forgot its size'
        await _shoot(pg, 'split-resized', ide=True)
    asyncio.run(_on_learn(go, _ws(tmp_path, monkeypatch)))

def test_a_narrow_split_keeps_the_cell_bar_off_the_gutter(tmp_path, monkeypatch):
    from leela.blocks.nb.nb import Notebook
    p = tmp_path/'n.ipynb'; Notebook.blank().save(p)
    async def go(pg, base):
        await pg.evaluate("localStorage.setItem('lee-editor-split-size', '25')")
        await pg.evaluate('p => leeOpenFile(p)', str(p)); await pg.wait_for_selector('.lee-cell .lee-cell-chrome')
        assert await pg.evaluate('([u, t]) => window.leeSidePage.open(u, t)', [STEP0, 'Softmax']) is True
        await pg.wait_for_function("document.querySelector('#editor2 iframe')")
        await pg.evaluate("for (const t of document.querySelectorAll('.lee-cell-time')) { t.hidden = false; t.textContent = '66ms'; }")
        bad = await pg.evaluate("""() => [...document.querySelectorAll('#editor .lee-cell')].flatMap(c => {
            const g = c.querySelector('.lee-gutter').getBoundingClientRect(), bar = c.querySelector('.lee-cell-chrome');
            return [...bar.children].filter(x => x.getBoundingClientRect().width && x.getBoundingClientRect().left < g.right - .5).map(x => x.className); })""")
        assert bad == [], bad
    asyncio.run(_on_learn(go, _ws(tmp_path, monkeypatch)))

def test_a_web_link_on_a_step_opens_outside_the_pane_and_the_page(tmp_path, monkeypatch):
    ws = _ws(tmp_path, monkeypatch)
    lr = Learning(ws.memory._store('learning')); j = lr.journey(JID)
    lr.put_journey({**j, 'steps': [{**j.steps[0], 'note': 'Read [the paper](https://example.org/paper).'}, j.steps[1]]})
    async def go(pg, base):
        asked = []   # the harness aborts outside requests, so a popup ends on an error page; its request shows where it went
        pg.context.on('request', lambda r: 'example.org' in r.url and asked.append(r.url))
        await pg.goto(base + STEP0, wait_until='networkidle')
        async with pg.expect_popup() as pop: await pg.get_by_role('link', name='the paper').click()
        await pg.wait_for_timeout(300)
        assert asked == ['https://example.org/paper'] and pg.url == base + STEP0, (asked, pg.url)
        await (await pop.value).close()
        await _ide(pg, base)
        frame = await _side(pg, tmp_path)
        async with pg.expect_popup() as pop: await frame.get_by_role('link', name='the paper').click()
        await pg.wait_for_timeout(300)
        assert asked == ['https://example.org/paper'] * 2, asked
        await (await pop.value).close()
        assert 'step=0' in frame.url and await frame.locator('blockquote').count() == 1, 'the site loaded in the pane'
        await _shoot(pg, 'pane-link', ide=True)
    asyncio.run(_on_learn(go, ws, ide=False))

def test_a_cancelled_split_drag_leaves_the_side_page_clickable(tmp_path, monkeypatch):
    async def go(pg, base):
        frame = await _side(pg, tmp_path)
        box = await pg.locator('.lee-editor-splitter').bounding_box()
        await pg.mouse.move(box['x'] + 1, box['y'] + 40); await pg.mouse.down()
        assert await pg.evaluate("document.querySelector('#editorstage').classList.contains('split-dragging')")
        await pg.evaluate("document.querySelector('.lee-editor-splitter').dispatchEvent(new PointerEvent('pointercancel', {pointerId: 1, bubbles: true}))")
        assert not await pg.evaluate("document.querySelector('#editorstage').classList.contains('split-dragging')"), 'the frame stayed deaf to the pointer'
        assert await pg.evaluate("getComputedStyle(document.querySelector('#editor2 iframe')).pointerEvents") != 'none'
        await pg.mouse.up()
    asyncio.run(_on_learn(go, _ws(tmp_path, monkeypatch)))

def test_an_ide_chord_pressed_in_the_pane_runs_in_the_ide(tmp_path, monkeypatch):
    async def go(pg, base):
        frame = await _side(pg, tmp_path)
        await frame.locator('blockquote').click()
        mod = 'Meta' if await pg.evaluate("navigator.platform.startsWith('Mac')") else 'Control'
        await frame.locator('body').press(f'{mod}+Shift+P')
        await pg.wait_for_function("lee.lastKeyEvent?.action === 'palette'")
        assert await pg.locator('.lee-modal').count() >= 1, 'the palette did not open'
    asyncio.run(_on_learn(go, _ws(tmp_path, monkeypatch)))

def _guarded(ws, port):
    "`_serve` behind the `LoopbackHostGuard` that `leela` itself puts in front of the app."
    import threading, uvicorn
    from leela.app import ide_app
    from leela.hub import LoopbackHostGuard
    srv = uvicorn.Server(uvicorn.Config(LoopbackHostGuard(ide_app(ws)), host='127.0.0.1', port=port, log_level='error'))
    threading.Thread(target=srv.run, daemon=True).start()
    return srv

def test_set_up_turns_the_step_page_ready_by_itself_and_open_ends_on_the_ide_with_the_lesson(tmp_path, monkeypatch):
    "Chromium posted both buttons with `Origin: null` and got 421; Set up gave a static page that never said when it was done; Open opened nothing on screen."
    import threading
    from leela.blocks.learn import tools
    from test_learn_tools import fake
    from learn_data import NB_JID, nb_walk
    ws = _ws(tmp_path, monkeypatch)
    nb_walk(Learning(ws.memory._store('learning')), requires=['httpx'])
    go, real = threading.Event(), tools.make_tool_env
    monkeypatch.setattr(tools, 'make_tool_env', lambda names: go.wait(30) and real(names, run=fake(lambda c: 0), uv='/u/uv'))
    monkeypatch.setattr(tools, 'index_env', lambda key: None)
    monkeypatch.setattr(tools.shutil, 'which', lambda name: '/u/uv')
    async def go_(pg, base):
        step = f'{base}/learn?walk={NB_JID}&step=0'
        await pg.goto(step, wait_until='networkidle')
        async with pg.expect_response(lambda r: r.url.endswith('/learn/env')) as r: await pg.get_by_role('button', name='Set up the environment').click()
        assert (await r.value).status == 303
        await pg.wait_for_url(step)
        env = pg.locator('[data-env-state]')
        assert await env.get_attribute('data-env-state') == 'installing' and 'so far' in await env.inner_text()
        go.set()
        await pg.wait_for_selector('[data-env-state=ready]', timeout=15000)
        assert await env.inner_text() == 'The environment for this lesson is ready. The lesson runs now.' and pg.url == step
        main = pg.get_by_role('button', name='Open as a lesson')
        assert 'go' in (await main.get_attribute('class')).split()
        async with pg.expect_response(lambda r: r.url.endswith('/learn/open')) as r: await main.click()
        assert (await r.value).status == 303
        await pg.wait_for_url(base + '/')
        lesson = str((tmp_path/'lessons'/f'{NB_JID}-0.ipynb').resolve())
        await pg.wait_for_function('p => window.lee && lee.tabKey === p', arg=lesson)
        assert f'{NB_JID}-0' in await pg.locator('.lee-tab.active').inner_text() and ws.tab.path == lesson
    asyncio.run(_on_learn(go_, ws, ide=False, serve=_guarded))
