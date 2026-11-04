"The web IDE in a browser: keys, themes, the vault reader and interventions."

import pytest

pytestmark = pytest.mark.slow

import asyncio
import os as _os
import socket
import threading


pytest.importorskip('playwright.async_api')
from playwright.async_api import async_playwright   # noqa: E402

from leela.blocks.runtime.kernels import KernelPool                # noqa: E402
from leela.app import ide_app
from leela.core.web import IDE_BUNDLES                   # noqa: E402
from leela.workspace import Workspace               # noqa: E402
from conftest import FakeKernel                     # noqa: E402

def fake_kernels():
    "Every `KernelPool` hands out a `FakeKernel` until the returned function is called; a later test in the worker gets real kernels again."
    real = {n: KernelPool.__dict__.get(n) for n in ('get', 'peek', 'close_all')}   # None: inherited, so the override is deleted
    async def _get(self, key, **kw): return self.kernels.setdefault(key, FakeKernel())
    KernelPool.get = _get
    KernelPool.peek = lambda self, key: self.kernels.get(key)
    KernelPool.close_all = lambda self: asyncio.sleep(0)
    def restore():
        for n, f in real.items():
            if f is None: delattr(KernelPool, n)
            else: setattr(KernelPool, n, f)
    return restore

def fake_model(ws):
    """Point every job at the scripted backend, so no browser test builds a real engine."""
    from tests.fakemodel import install
    return install(ws, [])

def _free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

def _serve(ws, port):
    "Run the real app on a background thread so Playwright can drive it like any other site."
    import uvicorn
    cfg = uvicorn.Config(ide_app(ws), host='127.0.0.1', port=port, log_level='error')
    srv = uvicorn.Server(cfg)
    threading.Thread(target=srv.run, daemon=True).start()
    return srv

CHROMIUM = _os.environ.get('LEELA_CHROMIUM')

async def _launch(pw, browser='chromium'):
    "`browser`, or a skip. `LEELA_CHROMIUM` names the binary where playwright cannot find its own."
    kw = {}
    if browser == 'chromium':
        if CHROMIUM: kw['executable_path'] = CHROMIUM
        if _os.geteuid() == 0: kw['args'] = ['--no-sandbox']
    try: return await getattr(pw, browser).launch(**kw)
    except Exception as e: pytest.skip(f'no {browser} for playwright: {e}')

def _launch_sync(pw):
    "The blocking twin of `_launch`, for the sync-API tests."
    kw = {'executable_path': CHROMIUM} if CHROMIUM else {}
    if _os.geteuid() == 0: kw['args'] = ['--no-sandbox']
    kw['headless'] = True
    try: return pw.chromium.launch(**kw)
    except Exception as e: pytest.skip(f'no chromium for playwright: {e}')

async def _started(srv, secs=20):
    "Wait on the server saying it is up, rather than on a fixed sleep in every test."
    for _ in range(int(secs/.02)):
        if srv.started: return
        await asyncio.sleep(.02)
    raise RuntimeError('the app never started')

async def _on_page(fn, roots=(), dpr=None, real_models=False, browser='chromium'):
    """Boot the app, open it in `browser`, hand the page to `fn`, and return what it returns."""
    real_kernels = fake_kernels()
    ws = Workspace(roots=list(roots), approvals='auto')
    if not real_models: fake_model(ws)
    port = _free_port()
    srv = _serve(ws, port)
    await _started(srv)
    try:
        async with async_playwright() as pw:
            b = await _launch(pw, browser)
            pg = await b.new_page(**({'device_scale_factor': dpr} if dpr else {}))
            await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
            await pg.wait_for_function('window.lee && lee.keys.length')
            try: return await fn(pg)
            finally: await b.close()
    finally:
        srv.should_exit = True
        #: The workspace holds the kernels, the agent and every turn thread it started. Asking the
        #: server to exit released none of that, so each streaming test left about seven threads
        #: and a gigabyte behind and the run was OOM-killed a third of the way in.
        ws.shutdown_now()
        real_kernels()

def _run(fn, roots=(), dpr=None, real_models=False, browser='chromium'):
    return asyncio.run(_on_page(fn, roots, dpr, real_models, browser))


def test_tab_takes_the_completion_that_is_on_screen():
    """Tab accepted a ghost suggestion and otherwise indented, and `completionKeymap` does not bind Tab at all, so an open completion list was indented past rather than accepted."""
    import json
    async def go(pg):
        await pg.route('**/complete*', lambda route: asyncio.ensure_future(route.fulfill(
            status=200, content_type='application/json',
            body=json.dumps({'from': 0, 'matches': ['sanskrit_parse'], 'graph': []}))))
        await pg.evaluate("""() => {
          const host = document.createElement('div'); host.id = 'tab-complete';
          host.style.cssText = 'width:420px;height:120px'; document.body.appendChild(host);
          window._tabView = LeeCM.create(host, {doc: 'sanskrit', lang: 'python', completeUrl: '/complete'});
          window._tabView.focus(); window._tabView.dispatch({selection: {anchor: 8}});
        }""")
        await pg.keyboard.type('_')
        await pg.wait_for_selector('.cm-tooltip-autocomplete')
        await pg.keyboard.press('Tab')
        await pg.wait_for_timeout(150)
        accepted = await pg.evaluate("() => LeeCM.getDoc(window._tabView)")
        # and where nothing is offered at all, Tab is still indent
        await pg.evaluate("""() => {
          const host = document.createElement('div'); host.id = 'tab-plain';
          host.style.cssText = 'width:420px;height:120px'; document.body.appendChild(host);
          window._plainView = LeeCM.create(host, {doc: 'x = 1', lang: 'python'});
          window._plainView.focus(); window._plainView.dispatch({selection: {anchor: 0}});
        }""")
        await pg.keyboard.press('Tab')
        await pg.wait_for_timeout(100)
        indented = await pg.evaluate("() => LeeCM.getDoc(window._plainView)")
        await pg.evaluate("() => { document.getElementById('tab-complete').remove(); document.getElementById('tab-plain').remove(); }")
        return {'accepted': accepted, 'indented': indented}
    out = _run(go)
    assert out['accepted'] == 'sanskrit_parse', 'Tab accepts the open completion'
    assert out['indented'].startswith((' ', '\t')), 'and still indents when nothing is offered'


def test_saving_the_file_in_a_split_pane_does_not_read_as_a_disk_conflict(tmp_path):
    """Every edit in a split pane raised "changed on disk after this browser draft began"."""
    a, b = tmp_path/'primary.py', tmp_path/'secondary.py'
    a.write_text('a = 1\n'); b.write_text('b = 1\n')

    async def go(pg):
        out = {}
        await pg.evaluate(f"leeOpenFile({str(b)!r})")     # both are tabs; `a` is the one on screen
        await pg.evaluate(f"leeOpenFile({str(a)!r})")
        await pg.wait_for_function("() => lee.editors.get('file') && lee.path")
        await pg.evaluate(f"mountSecondary({str(b)!r}, 'vertical')")   # what the split picker calls
        await pg.wait_for_function("() => lee.editors.get('secondary')")
        out['base'] = await pg.evaluate(f"draftBaseFor({str(b)!r})")
        out['primary_version'] = await pg.evaluate("lee.diskVersion")
        # Type into the split pane and save it the way its own autosave would.
        await pg.evaluate("""(path) => {
            lee.activeEditor = 'secondary';
            LeeCM.setDoc(lee.editors.get('secondary'), 'b = 2\\n');
            rememberBuffer(path, {path, kind: 'text', text: 'b = 2\\n'});
        }""", str(b))
        out['saved'] = await pg.evaluate("saveTab(true)")
        out['conflict'] = await pg.evaluate("!!document.querySelector('.lee-save-conflict')")
        return out

    out = _run(go, roots=[tmp_path])
    assert out['base'] != out['primary_version'] or not out['primary_version'], \
        "the split pane's draft was based on the tab's version, which is a different file"
    assert not out['conflict'], 'saving the split pane raised the disk-conflict modal'
    assert out['saved'] is True, 'and the save itself was refused'
    assert b.read_text() == 'b = 2\n', 'the split pane never reached disk'


def test_the_right_tools_minimise_sits_on_the_tab_row():
    """The tab bar was a grid of five columns, three tabs and two buttons. The Review tab made six children, so the minimise wrapped onto a second row below the agent tab."""
    async def go(pg):
        await pg.evaluate('leePane("right", true)')
        await pg.wait_for_selector('.lee-righttabs .lee-pane-min', state='visible')
        return await pg.evaluate("""() => {
            const bar = document.querySelector('.lee-righttabs').getBoundingClientRect();
            return [...document.querySelectorAll('.lee-righttabs > *')].map(x => {
                const r = x.getBoundingClientRect();
                return {cls: x.className, top: r.top - bar.top, bottom: bar.bottom - r.bottom, clipped: x.scrollWidth > x.clientWidth};
            });
        }""")
    kids = _run(go)
    assert any('lee-pane-min' in k['cls'] for k in kids), kids
    off = [k for k in kids if abs(k['top']) > .5 or k['bottom'] < -.5 or k['clipped']]
    assert off == [], off


def test_the_keymap_answers_every_chord_it_claims_in_one_browser_session():
    """One page for the whole keymap, because booting one per chord is the cost of this file."""
    async def go(pg):
        out = {}
        out['keymap'] = await pg.evaluate("""() => {
          const fire = (init, target) => {
            const e = new KeyboardEvent('keydown', {bubbles:true, cancelable:true, ...init});
            (target || document.activeElement || document.body).dispatchEvent(e); return e;
          };
          window._fire = fire;
          window._traps = (name, init) => {
            let ran = false; const orig = ACTIONS[name]; ACTIONS[name] = () => { ran = true; };
            const e = fire(init); ACTIONS[name] = orig;
            return {ran, prevented: e.defaultPrevented,
                    action: lee.lastKeyEvent && lee.lastKeyEvent.action};
          };
          const chord = lee.keys.find(k => k.action === 'run_above').chords[0];
          const hyper = {isComposing:false, repeat:false, ctrlKey:true, altKey:true,
                         shiftKey:true, metaKey:false};
          return {
            runAbove: {hyper: chord.hyper,
                       matches: chordMatches(chord, {...hyper, key:'Enter', code:'Enter'})},
            hypers: lee.keys.flatMap(k => k.chords.filter(c => c.hyper).map(c => ({action:k.action,
              code:c.code, matches:chordMatches(c, {...hyper, key:c.key, code:c.code})}))),
            mac: MAC,
            cmd_s: fire({key:'s', code:'KeyS', metaKey:true}, document).defaultPrevented,
            cmd_r: fire({key:'r', code:'KeyR', metaKey:true}, document).defaultPrevented,
            ctrl_s: fire({key:'s', code:'KeyS', ctrlKey:true}, document).defaultPrevented};
        }""")
        await pg.evaluate("leeAct('focus_editor')")
        out['editor'] = await pg.evaluate("""() => ({
          f5: window._traps('run_cell', {key:'F5'}),
          moveUp: window._traps('cell_move_up', {key:'ArrowUp', code:'ArrowUp', altKey:true,
                                                 shiftKey:true}),
          kind: lee.kind,
          below: window._traps('cell_below', {key:'ArrowDown', code:'ArrowDown', altKey:true,
                                              metaKey:MAC, ctrlKey:!MAC}),
          advance: window._traps('run_advance', {key:'Enter', shiftKey:true})})""")
        out['editorRows'] = await pg.locator('#keytoast .lee-krow').count()
        out['editorKeys'] = await pg.locator('#keytoast').inner_text()
        await pg.evaluate("leeAct('focus_exec')")
        out['exec'] = await pg.evaluate("""() => Object.assign(
          window._traps('exec_run', {key:'Enter', code:'Enter', metaKey:MAC, ctrlKey:!MAC}),
          {scope: lee.scope})""")
        await pg.evaluate("leeAct('focus_files')")
        out['letters'] = await pg.evaluate("""async () => {
          const press = (key, name) => new Promise(res => {
            const orig = ACTIONS[name];
            ACTIONS[name] = () => { ACTIONS[name] = orig; res(true); };
            document.dispatchEvent(new KeyboardEvent('keydown', {key, bubbles: true, cancelable: true,
              shiftKey: key === key.toUpperCase() && key.length === 1 && /[A-Z]/.test(key)}));
            setTimeout(() => { ACTIONS[name] = orig; res(false); }, 200);
          });
          return {o: await press('o', 'open_folder'), O: await press('O', 'add_root')};
        }""")
        out['fileKeys'] = await pg.locator('#keytoast').inner_text()
        out['fileScope'] = await pg.locator('#keyscope').inner_text()
        return out
    got = _run(go)
    keymap, editor = got['keymap'], got['editor']
    assert {'hyper': keymap['runAbove']['hyper'], 'matches': keymap['runAbove']['matches']} == \
        {'hyper': True, 'matches': True}
    assert keymap['hypers'] and all(r['code'] and r['matches'] for r in keymap['hypers']), keymap['hypers']
    assert keymap['cmd_s'] is keymap['mac']
    assert keymap['ctrl_s'] is (not keymap['mac'])
    assert keymap['cmd_r'] is False, 'Cmd+R remains Chrome reload and is never an app binding'
    assert (editor['f5']['ran'], editor['f5']['prevented']) == (False, False), \
        'a function key is left to the os and the browser'
    assert editor['kind'] != 'notebook' and (editor['moveUp']['ran'], editor['moveUp']['prevented']) == (False, False), \
        'a cell move outside a notebook took the chord from the editor'
    assert (editor['below']['ran'], editor['below']['prevented'], editor['below']['action']) == \
        (True, True, 'cell_below')
    assert editor['advance']['ran'] is True, \
        'shift+enter (run_advance) was swallowed by the text-field guard'
    assert got['exec']['ran'] and got['exec']['prevented'] and got['exec']['scope'] == 'exec'
    assert got['letters']['o'] is True, 'a folder opens in a window of its own'
    assert got['letters']['O'] is True, 'and the shifted letter adds one to this window'
    assert got['editorRows'] <= 12
    assert 'run and select below' in got['editorKeys']
    assert 'merge cell above' not in got['editorKeys'], \
        'help-only commands belong in the full keymap overlay'
    assert 'open / toggle folder' in got['fileKeys'] and 'next item' in got['fileKeys'] \
        and 'new file' in got['fileKeys']
    assert 'expand / enter folder' not in got['fileKeys'], \
        'help-only movement stays in the full keymap overlay'
    assert 'files' in got['fileScope']


def test_every_keymap_action_and_menu_row_has_a_handler_on_the_loaded_page():
    """`leeAct` answers `no handler for ...` for a name absent from `ACTIONS`, and a native menu's JS row calls a global."""
    from leela.core.keys import KEYS
    from leela.blocks.keys.menus import BAR, Js, MenuItem
    keyed = sorted({k.action for k in KEYS})
    rows = [r for _, rs in BAR for r in rs]
    barred = sorted({r.action for r in rows if not isinstance(r, Js) and isinstance(r, MenuItem) and r.action})
    exprs = sorted({r.expr for r in rows if isinstance(r, Js)})
    assert keyed and barred and exprs
    assert 'new_lesson' in keyed and 'new_lesson' in barred
    async def go(pg):
        return await pg.evaluate("""([keyed, barred, exprs]) => ({
          keyed: keyed.filter(a => typeof ACTIONS[a] !== 'function'),
          barred: barred.filter(a => typeof ACTIONS[a] !== 'function'),
          exprs: exprs.filter(e => typeof window[e.split('(')[0]] !== 'function')})""", [keyed, barred, exprs])
    got = _run(go)
    assert got == {'keyed': [], 'barred': [], 'exprs': []}, got


def test_a_link_in_the_desktop_shell_goes_to_the_system_browser_and_never_through_window_open():
    """A scripted `window.open` is `WKNavigationTypeOther`, so in the packaged app it opens nothing and returns null."""
    async def go(pg):
        posted = []
        async def fulfil(route):
            posted.append(route.request.post_data)
            await route.fulfill(status=200, content_type='application/json', body='{}')
        await pg.route('**/browser/external', lambda route: asyncio.ensure_future(fulfil(route)))
        async def settled(n):
            for _ in range(100):
                if len(posted) >= n: break
                await pg.wait_for_timeout(30)
        await pg.evaluate("""() => {
          window._opened = []; window.open = (...a) => { window._opened.push(a[0]); return null; };
          lee.inShell = true;
          const d = document.createElement('div'); d.innerHTML = '<a id="lka" href="https://example.com/a">a</a>';
          document.body.appendChild(d); routeMarkdownLinks(d);
        }""")
        await pg.evaluate("() => document.getElementById('lka').click()")
        await settled(1)
        out = {'shell_opened': await pg.evaluate('window._opened'), 'shell_posted': list(posted)}
        await pg.evaluate("() => { lee.inShell = false; window._opened.length = 0; }")
        await pg.evaluate("() => openExternal('https://example.com/b')")
        await settled(2)
        out |= {'page_opened': await pg.evaluate('window._opened'), 'page_posted': list(posted)}
        return out
    got = _run(go)
    assert got['shell_opened'] == [], 'the shell must not script a window it cannot open'
    assert len(got['shell_posted']) == 1 and 'example.com/a' in got['shell_posted'][0], got['shell_posted']
    assert got['page_opened'] == ['https://example.com/b'], 'a plain page still tries window.open first'
    assert len(got['page_posted']) == 2 and 'example.com/b' in got['page_posted'][1], 'and falls back to the route when it returns null'


def test_markdown_links_never_navigate_the_desktop_shell(tmp_path):
    base = tmp_path/'docs #100%'; base.mkdir()
    target = tmp_path/'reply.py'; target.write_text('reply = 1\n')
    async def go(pg):
        posted = []
        async def fulfil(route):
            posted.append(route.request.post_data_json['url'])
            await route.fulfill(status=200, content_type='application/json', body='{}')
        await pg.route('**/browser/external', fulfil)
        url = pg.url
        await pg.evaluate("""([base, root]) => {
          lee.inShell = true; window._linkFiles = []; window._realLinkOpen = leeOpenFile;
          window._linkWindows = []; window.open = url => { window._linkWindows.push(url); return null; };
          window.leeOpenFile = async path => {
            window._linkFiles.push(path);
            if (path.endsWith('missing.py')) throw new Error('not found');
          };
          const d = document.createElement('div'); d.id = 'link-test'; d.dataset.mdBase = base;
          const links = {relative:'nested/../file%20name%23%3F.py?q=1#part', root:root,
            missing:'missing.py', script:'javascript:window._linkExecuted=true', file:'file:///tmp/x',
            protocol:'//example.com/a', malformed:'bad%path', web:'https://example.com/meta'};
          for (const [id, href] of Object.entries(links)) {
            const a = document.createElement('a'); a.id = 'link-' + id; a.href = href;
            a.textContent = id; d.append(a, document.createElement('br'));
          }
          document.body.append(d);
          const reply = document.createElement('div'); reply.className = 'lee-reply';
          reply.innerHTML = '<a id="link-reply" href="reply.py?x=1#part">reply</a>';
          document.body.append(reply); routeMarkdownLinks(d); routeMarkdownLinks(reply);
        }""", [str(base), str(target)])
        for name, path in [('relative', str(base/'file name#?.py')), ('root', str(target)), ('reply', 'reply.py')]:
            await pg.locator('#link-' + name).click()
            await pg.wait_for_timeout(80)
            assert pg.url == url, f'{name} navigated the app window to {pg.url}'
            assert await pg.evaluate('window._linkFiles.at(-1)') == path
        await pg.locator('#link-missing').click()
        await pg.wait_for_function("document.getElementById('status').textContent.includes('not found')")
        assert await pg.locator('#status').inner_text() == f'could not open {base}/missing.py: not found'
        for name, href in [('script', 'javascript:window._linkExecuted=true'), ('file', 'file:///tmp/x'),
                           ('protocol', '//example.com/a')]:
            await pg.locator('#link-' + name).click()
            assert await pg.locator('#status').inner_text() == f'will not open {href}'
            assert pg.url == url
        assert not await pg.evaluate('Boolean(window._linkExecuted)')
        await pg.locator('#link-malformed').click()
        assert 'could not open bad%path:' in await pg.locator('#status').inner_text()
        for modifier in ['Meta', 'Shift', 'Alt']:
            await pg.locator('#link-web').click(modifiers=[modifier])
        await pg.evaluate("""() => document.getElementById('link-web').dispatchEvent(
          new MouseEvent('click', {bubbles:true, cancelable:true, ctrlKey:true}))""")
        await pg.locator('#link-web').click(button='middle')
        await pg.wait_for_function('window._linkFiles.length === 4')
        for _ in range(100):
            if len(posted) == 5: break
            await pg.wait_for_timeout(30)
        assert posted == ['https://example.com/meta'] * 5
        assert await pg.evaluate('window._linkWindows') == []
        await pg.locator('#link-relative').click(button='middle')
        assert await pg.evaluate('window._linkFiles.at(-1)') == str(base/'file name#?.py')
        await pg.evaluate('window.leeOpenFile = window._realLinkOpen')
        await pg.locator('#link-reply').click()
        await pg.wait_for_function('(path) => lee.path === path && lee.kind === "text"', arg=str(target))
        assert await pg.evaluate('LeeCM.getDoc(lee.editors.get("file"))') == 'reply = 1\n'
        await pg.locator('#link-missing').click()
        await pg.wait_for_function("document.getElementById('status').textContent.includes('FileNotFoundError')")
        assert f'could not open {base}/missing.py:' in await pg.locator('#status').inner_text()
        assert 'err' in await pg.locator('#status').get_attribute('class')
        assert pg.url == url
    _run(go, roots=[tmp_path])


def test_every_editor_refuses_the_systems_own_autocorrect():
    """WKWebView hands a `contenteditable` to NSSpellChecker and a browser does not, so the packaged app curled quotes, corrected identifiers, and offered inline predictions under CodeMirror."""
    async def go(pg):
        return await pg.evaluate("""() => {
          const el = document.createElement('div'); document.body.appendChild(el);
          const v = createEditor(el, {doc: 'x = 1', lang: 'python'});
          const named = n => v.contentDOM.getAttribute(n);
          return {spellcheck: named('spellcheck'), autocorrect: named('autocorrect'),
                  autocapitalize: named('autocapitalize'),
                  writingsuggestions: named('writingsuggestions'),
                  everyMounted: [...document.querySelectorAll('.cm-content')]
                    .every(n => n.getAttribute('spellcheck') === 'false'
                                && n.getAttribute('writingsuggestions') === 'false')};
        }""")
    out = _run(go)
    assert out['spellcheck'] == 'false', out
    assert out['autocorrect'] == 'off' and out['autocapitalize'] == 'off', out
    # An inline prediction is taken with Tab, which is the key the completion list wants.
    assert out['writingsuggestions'] == 'false', out
    assert out['everyMounted'], 'an editor on the page was left with the system text checker on'


from conftest import serve


pytest.importorskip('playwright.sync_api')


@pytest.fixture
def proj_web_th(tmp_path):
    (tmp_path/'main.py').write_text('x = 1\n')
    return tmp_path

def _open(pw, url):
    page = _launch_sync(pw).new_page(viewport={'width': 1440, 'height': 900})
    page.goto(url, wait_until='networkidle')
    if page.locator('.lee-modal').count(): page.keyboard.press('Escape')
    return page


_NO_SAVED_THEME = ("() => post('/settings/save', {scope: 'user', language: '',"
                   " section: 'appearance', values: {theme: ''}})")


def test_the_theme_is_kept_in_settings_and_not_only_in_this_origin(proj_web_th):
    """The packaged app takes whatever port it is given when 5001 is busy, and `localStorage` is per origin, so a theme kept only there is gone on the next launch."""
    ws = Workspace(roots=[proj_web_th])
    with serve(ws) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            page = _open(pw, url)
            def theme_setting():
                for _ in range(50):
                    value = page.evaluate("() => api('/settings')")['effective']['appearance']['theme']
                    if value: return value
                    page.wait_for_timeout(100)
                return ''
            page.evaluate(_NO_SAVED_THEME)
            page.evaluate('leeEditorSettings()')
            page.wait_for_selector('.lee-settings-modal')
            page.click('[data-settings-page="appearance"]')
            page.click('.lee-theme-mode[data-theme-mode="dark"]')
            page.click('.lee-theme-choice[data-theme="nord"]')
            page.click('[data-save]')
            page.wait_for_function("!document.querySelector('.lee-settings-modal')")
            said = page.locator('#status').inner_text()
            assert 'no settings saved' not in said and 'saved to user' in said, said
            d = page.evaluate("() => api('/settings?language=python')")
            assert d['effective']['appearance']['theme'].startswith('nord:dark:'), d['effective']['appearance']
            assert 'appearance' not in ((d['user'].get('languages') or {}).get('python') or {}), \
                'a theme is not language-scoped'

            page.evaluate("localStorage.removeItem('lee-theme')")   # what a new origin looks like
            page.reload(wait_until='networkidle')
            if page.locator('.lee-modal').count(): page.keyboard.press('Escape')
            page.wait_for_function("document.documentElement.dataset.theme === 'nord'")
            assert page.evaluate('document.documentElement.dataset.mode') == 'dark'

            page.evaluate(_NO_SAVED_THEME)
            page.evaluate("localStorage.setItem('lee-theme', 'gruvbox:dark:tight')")
            page.reload(wait_until='networkidle')
            if page.locator('.lee-modal').count(): page.keyboard.press('Escape')
            page.wait_for_function("document.documentElement.dataset.theme === 'gruvbox'")
            assert theme_setting() == 'gruvbox:dark:tight', 'the cached theme is migrated, not dropped'
            page.evaluate(_NO_SAVED_THEME)


_OPEN_SETTINGS = {
    'palette': lambda page: (page.keyboard.press('ControlOrMeta+Shift+P'), page.wait_for_selector('#cp'),
                             page.fill('#cp', 'settings'),
                             page.locator('#cplist .lee-mrow', has_text=__import__('re').compile(r'^settings')).first.click()),
    'key': lambda page: page.keyboard.press('ControlOrMeta+Comma'),
    'menu': lambda page: page.evaluate("leeAct('settings')"),
}

@pytest.mark.parametrize('fam,mode,bg,route', [('github', 'dark', '#0d1117', 'palette'), ('github', 'light', '#ffffff', 'key'),
                                               ('ember', 'dark', '#221d18', 'menu'), ('dusk', 'light', '#e6eaf0', 'palette')])
def test_a_new_theme_is_picked_from_every_route_painted_everywhere_and_kept(proj_web_th, fam, mode, bg, route):
    """The settings modal is the one picker, reached from the palette, its key and the app menu; the choice paints the chrome, the terminal and the first paint after a reload."""
    ws = Workspace(roots=[proj_web_th])
    with serve(ws) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            page = _open(pw, url)
            page.evaluate(_NO_SAVED_THEME)
            page.evaluate("leeAct('terminal')")
            page.wait_for_function("lee.terms.size > 0", timeout=10000)
            _OPEN_SETTINGS[route](page)
            page.wait_for_selector('.lee-settings-modal')
            page.click('[data-settings-page="appearance"]')
            page.click(f'.lee-theme-mode[data-theme-mode="{mode}"]')
            page.click(f'.lee-theme-choice[data-theme="{fam}"]')
            painted = "getComputedStyle(document.documentElement).getPropertyValue('--lee-bg').trim()"
            assert page.evaluate(painted) == bg, 'the choice previews before it is saved'
            assert page.evaluate("[...lee.terms.values()][0].view.term.options.theme.background") == bg
            page.click('[data-save]')
            page.wait_for_function("!document.querySelector('.lee-settings-modal')")
            assert page.evaluate("() => api('/settings')")['effective']['appearance']['theme'].startswith(f'{fam}:{mode}:')
            page.evaluate("localStorage.removeItem('lee-theme')")
            page.reload(wait_until='networkidle')
            if page.locator('.lee-modal').count(): page.keyboard.press('Escape')
            assert page.evaluate("[document.documentElement.dataset.theme, document.documentElement.dataset.mode]") == [fam, mode]
            assert page.evaluate(painted) == bg
            page.evaluate(_NO_SAVED_THEME)

def test_the_native_window_takes_the_theme_background_from_every_paint(proj_web_th):
    """The desktop window kept kavacha's fixed dark colour, which showed on open and on resize; every paint now sends `--lee-bg` over the bridge."""
    ws = Workspace(roots=[proj_web_th])
    with serve(ws) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            page = _launch_sync(pw).new_page()
            # pywebview injects `window.pywebview.api` after load and then fires `pywebviewready`.
            page.add_init_script("window.__bg = []; setTimeout(() => { window.pywebview = {api: {set_background: c => (window.__bg.push(c), Promise.resolve(true))}};"
                                 " window.dispatchEvent(new Event('pywebviewready')); }, 300);")
            page.goto(url, wait_until='load')
            painted = "getComputedStyle(document.documentElement).getPropertyValue('--lee-bg').trim()"
            page.wait_for_function("window.__bg.length > 0", timeout=15000)
            assert page.evaluate("window.__bg.at(-1)") == page.evaluate(painted), 'the first paint, once the bridge is up'
            page.evaluate("applyTheme('ember:dark:tight')")
            assert page.evaluate("window.__bg.at(-1)") == '#221d18'
            page.emulate_media(color_scheme='dark')
            page.evaluate("applyTheme('dusk:system:relaxed')")
            assert page.evaluate("window.__bg.at(-1)") == '#252a33'
            page.emulate_media(color_scheme='light')
            page.wait_for_function("window.__bg.at(-1) === '#e6eaf0'", timeout=5000)

@pytest.mark.parametrize('cached,want', [('retired:dark:tight', ['cursor', 'dark', 'tight']), ('cursor:bogus:x', ['cursor', 'light', 'tight']),
                                         ('ember', ['cursor', 'light', 'tight']), ('dark', ['leela', 'dark', 'relaxed'])])
def test_a_cached_theme_this_build_does_not_draw_paints_the_default(proj_web_th, cached, want):
    """`lee-theme` from a newer build, or a hand edit, named a family no stylesheet rule draws, and the first paint was unstyled."""
    ws = Workspace(roots=[proj_web_th])
    with serve(ws) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            page = _launch_sync(pw).new_page()
            page.add_init_script(f"if (!sessionStorage.seeded) {{ localStorage.setItem('lee-theme', {cached!r}); sessionStorage.seeded = 1; }}")
            # Read before the bundles run, which would repaint whatever the first paint got wrong.
            page.route('**/lee-ide.js*', lambda r: r.abort())
            page.goto(url, wait_until='domcontentloaded')
            d = page.evaluate("Object.values(({theme, mode, density} = document.documentElement.dataset, {theme, mode, density}))")
            assert d == want
            assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--lee-bg').trim()")

HANDLER_ATTRS = ('onclick', 'oninput', 'onchange', 'onkeydown', 'onsubmit')

def test_every_name_the_painted_page_reaches_for_resolves_in_the_shared_scope():
    """The whole of what a page load promises, in one page load."""
    async def go(pg):
        out = {}
        for op in ("leeRight('agent')", "leeRight('git')", "leeRight('vars')", "leePane('left', true)"):
            await pg.evaluate(op)
        await pg.wait_for_timeout(800)
        out['dead'] = await pg.evaluate("""(attrs) => {
          const skip = new Set(['if','return','for','while','switch','catch','typeof','function',
                                'new','delete','await','throw','void']);
          const named = attrs.flatMap(a => [...document.querySelectorAll(`[${a}]`)]
            .flatMap(el => [...el.getAttribute(a).matchAll(/(^|[^.\\w$])([A-Za-z_$][\\w$]*)\\s*\\(/g)]
              .map(m => m[2])));
          return [...new Set(named)].filter(n => !skip.has(n) && typeof window[n] !== 'function').sort();
        }""", list(HANDLER_ATTRS))
        out['actions'] = await pg.evaluate("""() => {
          const out = {notFn: [], missing: []};
          for (const [name, f] of Object.entries(ACTIONS)) {
            if (typeof f !== 'function') { out.notFn.push(name); continue; }
            const m = /^\\s*\\(\\s*\\)\\s*=>\\s*([A-Za-z_$][\\w$]*)\\s*\\(\\s*\\)\\s*$/.exec(f.toString());
            if (m && typeof window[m[1]] !== 'function' && typeof eval(`typeof ${m[1]}`) !== 'function')
              out.missing.push(`${name} -> ${m[1]}`);
          }
          out.count = Object.keys(ACTIONS).length;
          return out;
        }""")
        out['hits'] = await pg.evaluate("""() => {
          const pkg = [{path: '/v/site-packages/chonkie/types/document.py', line: 23, module: 'chonkie.types.document'},
                       {path: '/v/site-packages/prompt_toolkit/document.py', line: 79, module: 'prompt_toolkit.document'}];
          const proj = [{path: '/w/leela/blocks/git/app.py', line: 4},
                        {path: '/w/leela/blocks/fs/app.py', line: 9},
                        {path: '/w/leela/blocks/agent/turns.py', line: 1}];
          return {pkg: pkg.map(h => hitWhere(h, pkg)), proj: proj.map(h => hitWhere(h, proj))};
        }""")
        # `lee.cells` and `lee.editors` are replaced from here down, so nothing that mounts a tab
        # may follow.
        out['find'] = await pg.evaluate("""() => {
          const out = {};
          lee.kind = 'notebook';
          lee.editors = new Map();
          lee.cells = [{id: 'a', source: 'def area(r):\\n'}, {id: 'b', source: '    return r * r\\n'}];
          const at = flags => { lee.findFlags = flags; };
          at({}); out.plain = findMatches('r').length;
          at({word: true}); out.word = findMatches('r').length;
          at({case: true}); out.cased = findMatches('R').length;
          at({regex: true}); out.regex = findMatches('r \\\\* r').length;
          at({regex: true}); out.empty = findMatches('x*').length;
          at({regex: true}); out.broken = findMatches('([');
          at({}); out.cells = findMatches('r').map(h => h.doc);
          // A text tab with nothing open has no document to walk, and must not throw looking.
          lee.kind = 'text'; lee.cells = [];
          out.closed = findMatches('r').length;
          return out;
        }""")
        await pg.evaluate("""() => {
          window.__copied = [];
          navigator.clipboard.writeText = t => { window.__copied.push(t); return Promise.resolve(); };
          window.__paths = [];
          window.api = url => { window.__paths.push(url); return Promise.resolve(
            {ok: true, absolute: '/w/proj/pkg/mod.py', relative: 'pkg/mod.py'}); };
        }""")
        out['copied'] = await pg.evaluate("""async () => {
          const out = {};
          out.dispatch = ['copy_rel_path', 'copy_abs_path'].every(a => typeof ACTIONS[a] === 'function');
          // a right-click on a tree row: the tree selection is the target
          const row = document.createElement('div');
          row.className = 'lee-node sel'; row.dataset.path = '/w/proj/pkg/mod.py';
          document.body.appendChild(row);
          lee.menuSurface = 'file';
          await copyFilePath('relative');
          await copyFilePath('absolute');
          out.fromTree = [...window.__copied];
          out.asked = window.__paths.every(u => u.includes('/fs/paths?path='));
          row.remove(); window.__copied = [];
          // and a right-click on a tab: its `title` is the path, read without waiting for a select
          const tab = document.createElement('div');
          tab.className = 'lee-tab'; tab.dataset.i = '7'; tab.title = '/w/proj/other.py';
          document.body.appendChild(tab);
          lee.menuSurface = 'tab'; lee.menuTab = 7;
          await copyFilePath('relative');
          out.fromTab = [...window.__copied];
          tab.remove(); lee.menuSurface = null; lee.menuTab = null;
          return out;
        }""")
        return out
    got = _run(go)
    assert got['dead'] == [], f"inline handlers with no such function: {got['dead']}"

    actions = got['actions']
    assert actions['count'] > 60, actions['count']
    assert actions['notFn'] == [], actions['notFn']
    assert actions['missing'] == [], actions['missing']

    hits = got['hits']
    assert hits['pkg'] == ['chonkie.types.document', 'prompt_toolkit.document'], hits['pkg']
    assert hits['proj'] == ['git/app.py', 'fs/app.py', 'turns.py'], hits['proj']
    assert len(set(hits['pkg'])) == 2 and len(set(hits['proj'])) == 3, 'every row is distinguishable'

    find = got['find']
    assert find['plain'] == 6, 'area, the parameter, both r of return, and the two in the body'
    assert find['word'] == 3, 'only the standalone r, so not the ones inside area and return'
    assert find['cased'] == 0, 'match case means no hit for R'
    assert find['regex'] == 1
    assert find['broken'] is None, 'a pattern that will not compile is not the same as no matches'
    assert 0 < find['empty'] < 5000, 'an empty match must advance rather than spin'
    assert find['cells'] == [0, 0, 1, 1, 1, 1], 'two hits in the first cell, four in the second'
    assert find['closed'] == 0

    copied = got['copied']
    assert copied['dispatch'], 'both actions are reachable from the shared dispatch table'
    assert copied['fromTree'] == ['pkg/mod.py', '/w/proj/pkg/mod.py'], copied['fromTree']
    assert copied['asked'], 'the server is asked, since only it knows the open folders'
    assert copied['fromTab'] == ['pkg/mod.py'], copied['fromTab']

def test_the_shell_boots_from_three_tags_in_order_and_paints_without_a_page_error():
    """Three tags, one scope."""
    real_kernels = fake_kernels()
    ws = Workspace(roots=[], approvals='auto')
    port = _free_port()
    srv = _serve(ws, port)
    errors, resources, bad, tags = [], [], [], []
    async def go():
        await _started(srv)
        async with async_playwright() as pw:
            b = await _launch(pw)
            pg = await b.new_page()
            pg.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
            pg.on('console', lambda m: m.type == 'error' and (
                resources if 'Failed to load resource' in m.text else errors).append(m.text))
            def note(r):
                name = r.url.split('?')[0].rsplit('/', 1)[-1]
                if name in IDE_BUNDLES and r.status != 200: bad.append((name, r.status))
            pg.on('response', note)
            await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
            await pg.wait_for_function('window.lee && lee.keys.length')
            tags.extend(await pg.evaluate("""(names) => [...document.scripts]
                .map(s => s.src.split('?')[0].split('/').pop())
                .filter(n => names.includes(n))""", list(IDE_BUNDLES)))
            for op in ("leeRight('agent')", "leeRight('git')", "leeRight('vars')", 'showHelp()'):
                await pg.evaluate(op)
                await pg.wait_for_timeout(400)
            await b.close()
    try: asyncio.run(go())
    finally: srv.should_exit = True; real_kernels()
    assert bad == [], bad
    assert tags == list(IDE_BUNDLES), f'tag order {tags}, expected {list(IDE_BUNDLES)}'
    assert errors == [], f'the client reported {len(errors)} javascript problems: {errors[:5]}'


def test_the_tree_selects_more_than_one_row_and_the_clipboard_acts_on_all_of_them(tmp_path):
    """Multi-select by mouse, then one operation over the whole selection, on a real tree."""
    for name in ('a.py', 'b.py', 'c.py'): (tmp_path/name).write_text('x = 1\n')
    (tmp_path/'dest').mkdir()
    async def go(pg):
        # The root renders collapsed and fetches its children on the first click, so the rows this
        # test is about do not exist until it is opened.
        await pg.click('.lee-node.lee-dir.lee-root > summary')
        await pg.wait_for_selector('.lee-node.lee-file')
        pick = """(name) => {
          const n = [...document.querySelectorAll('.lee-node.lee-file')]
            .find(x => x.dataset.path.endsWith(name));
          n.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, metaKey: true}));
          return n.classList.contains('marked');
        }"""
        marked = [await pg.evaluate(pick, 'a.py'), await pg.evaluate(pick, 'b.py')]
        opened = await pg.evaluate("lee.tabs ? lee.tabs.length : 0")
        await pg.evaluate("leeAct('file_cut')")
        cut = await pg.evaluate("lee.fileClip.paths.length")
        await pg.evaluate("""() => {
          const d = [...document.querySelectorAll('.lee-node.lee-dir')]
            .find(x => x.dataset.path.endsWith('dest'));
          selectTreeNode(d, true);
        }""")
        await pg.evaluate("leeAct('file_paste')")
        await pg.wait_for_function("!lee.fileClip")
        return marked, opened, cut
    marked, opened, cut = _run(go, roots=[tmp_path])
    assert marked == [True, True], 'a meta-click marks the row'
    assert opened == 0, 'and does not open it'
    assert cut == 2, 'the clipboard took the whole selection'
    assert (tmp_path/'dest'/'a.py').is_file() and (tmp_path/'dest'/'b.py').is_file()
    assert not (tmp_path/'a.py').exists() and not (tmp_path/'b.py').exists()
    assert (tmp_path/'c.py').is_file(), 'the row that was not selected stays put'


def test_the_palette_lists_commands_and_hands_a_file_query_to_the_opener(tmp_path):
    """Twenty file rows under the matching commands flooded the palette; one row now hands the query to ⌘P."""
    (tmp_path/'zqxw_notes.py').write_text('x = 1\n')
    rows = "() => [...document.querySelectorAll('#cplist .lee-mrow')].map(r => r.textContent)"
    async def go(pg):
        finds = []
        pg.on('request', lambda r: finds.append(r.url) if '/fs/find' in r.url else None)
        await pg.keyboard.press('ControlOrMeta+Shift+P')
        await pg.wait_for_selector('#cp', timeout=3000)
        await pg.fill('#cp', 'save')
        saved = await pg.evaluate(rows)
        await pg.fill('#cp', 'zqxw')
        await pg.wait_for_timeout(400)
        only = await pg.evaluate(rows)
        asked = list(finds)
        await pg.fill('#cp', '')
        empty = await pg.evaluate(rows)
        await pg.fill('#cp', 'zqxw')
        await pg.press('#cp', 'Enter')
        await pg.wait_for_function("() => [...document.querySelectorAll('#qolist .lee-mrow')].some(r => r.textContent.includes('zqxw_notes.py'))", timeout=5000)
        prefilled, focused = await pg.evaluate("[document.querySelector('#qo').value, document.activeElement?.id]")
        await pg.press('#qo', 'Enter')
        await pg.wait_for_function("() => (lee.path || '').endsWith('zqxw_notes.py')", timeout=5000)
        return saved, only, asked, empty, prefilled, focused, await pg.evaluate("!!document.querySelector('#cp, #qo')")
    saved, only, asked, empty, prefilled, focused, still_open = _run(go, roots=[tmp_path])
    assert saved[0].startswith('save') and saved[-1].startswith('Open file matching “save”'), saved
    assert not any('zqxw_notes.py' in r for r in only) and len(only) == 1, only
    assert not asked, 'the palette searched files itself'
    assert any(r.startswith('new lesson notebook') for r in empty), empty
    assert not any(r.startswith('Open file') for r in empty), 'an empty query offers no hand-off'
    assert (prefilled, focused) == ('zqxw', 'qo')
    assert not still_open, 'opening the file closes both'

def test_the_palette_creates_a_lesson_notebook_and_cancel_creates_nothing(tmp_path):
    async def go(pg):
        await pg.evaluate('palette()')
        await pg.fill('#cp', 'new lesson notebook')
        await pg.press('#cp', 'Enter')
        await pg.wait_for_selector('#dialoginput')
        await pg.click('#dialogcancel')
        assert not (tmp_path/'lessons').exists()
        await pg.evaluate("void leeAct('new_lesson')")
        await pg.fill('#dialoginput', 'सॉफ्टमैक्स')
        await pg.press('#dialoginput', 'Enter')
        await pg.wait_for_function("() => lee.path.includes('/lessons/') && lee.cells.length === 5")
        return await pg.evaluate('({path: lee.path, count: lee.cells.length, kind: lee.kind})')
    got = _run(go, roots=[tmp_path])
    from abhyasa.learner import slugify
    path = tmp_path/'lessons'/f'{slugify("सॉफ्टमैक्स")}.ipynb'
    assert got == {'path': str(path), 'count': 5, 'kind': 'notebook'}
    assert path.is_file()

def test_the_file_opener_lists_the_project_and_adds_hidden_folders_on_request(tmp_path):
    """Hidden folders are a second batch behind a checkbox, so the project's own files are never waiting on `.venv`."""
    (tmp_path/'zqxw_main.py').write_text('x = 1\n')
    (tmp_path/'.claude').mkdir(); (tmp_path/'.claude'/'zqxw_hidden.py').write_text('x = 1\n')
    names = "() => [...document.querySelectorAll('#qolist .lee-mrow')].map(r => r.firstChild.textContent)"
    async def go(pg):
        await pg.keyboard.press('ControlOrMeta+P')
        await pg.wait_for_selector('#qo', timeout=3000)
        await pg.fill('#qo', 'zqxw')
        await pg.wait_for_function(f"() => ({names})().includes('zqxw_main.py')", timeout=5000)
        await pg.wait_for_timeout(800)
        before = await pg.evaluate(names)
        await pg.check('#qoall')
        await pg.wait_for_function(f"() => ({names})().includes('zqxw_hidden.py')", timeout=5000)
        after = await pg.evaluate(names)
        focused = await pg.evaluate('document.activeElement.id')
        await pg.route(lambda u: 'more=1' in u, lambda r: r.fulfill(json={'hits': [], 'partial': True}))
        await pg.fill('#qo', 'zqxw_m')
        await pg.wait_for_selector('#qonote:not([hidden])', timeout=5000)
        note = await pg.text_content('#qonote')
        await pg.uncheck('#qoall')
        await pg.wait_for_function(f"() => !({names})().includes('zqxw_hidden.py')", timeout=5000)
        cleared = await pg.evaluate("document.querySelector('#qonote').hidden")
        return before, after, focused, note, cleared
    before, after, focused, note, cleared = _run(go, roots=[tmp_path])
    assert before == ['zqxw_main.py'], before
    assert after == ['zqxw_main.py', 'zqxw_hidden.py'], 'the project batch first, the hidden one after it'
    assert focused == 'qo', 'the box hands typing back to the query'
    assert 'incomplete' in note, 'a hidden search cut off by its time limit says so'
    assert cleared, 'the next search clears the warning'


def test_a_hidden_search_the_opener_moved_past_stops_on_the_server(tmp_path, monkeypatch):
    """Each hidden walk ran to its ten-second limit after the opener had moved on, and ticking the box refetched the query on screen."""
    import leela.blocks.fs.fs as fsmod
    (tmp_path/'zqxw_main.py').write_text('x = 1\n')
    stopped = []
    async def endless(*a, **kw):
        try: await asyncio.Event().wait()
        except asyncio.CancelledError: stopped.append(1); raise
    monkeypatch.setattr(fsmod, 'fda', endless)
    async def until(cond):
        for _ in range(60):
            if cond(): return
            await asyncio.sleep(.1)
    async def go(pg):
        mains = []
        pg.on('request', lambda r: mains.append(r.url) if 'q=zq1' in r.url and 'more=1' not in r.url else None)
        await pg.keyboard.press('ControlOrMeta+P')
        await pg.wait_for_selector('#qo', timeout=3000)
        await pg.fill('#qo', 'zq1')
        await pg.wait_for_timeout(400)
        async with pg.expect_request(lambda r: 'more=1' in r.url and 'q=zq1' in r.url): await pg.check('#qoall')
        await pg.fill('#qo', 'zqxw')
        await until(lambda: stopped)
        typed_past = len(stopped)
        await pg.wait_for_timeout(600)
        await pg.keyboard.press('Escape')
        await until(lambda: len(stopped) > typed_past)
        return len(mains), typed_past, len(stopped)
    mains, typed_past, closed = _run(go, roots=[tmp_path])
    assert mains == 1, 'ticking the box fetches only the hidden batch for a query already on screen'
    assert typed_past == 1, 'typing past a hidden search stops its walk on the server'
    assert closed == 2, 'closing the opener stops the walk in flight'


def test_a_draft_from_a_version_the_file_no_longer_has_is_discarded(tmp_path):
    """Drafts are keyed by path and cell id, and both survive a rewrite by another tool, so a draft left over an older version landed back on the file that replaced it."""
    f = tmp_path/'note.py'; f.write_text('from disk\n')
    async def go(pg):
        await pg.evaluate("path => leeOpenFile(path)", str(f))
        await pg.wait_for_function("() => lee.path && lee.diskVersion")
        stale = await pg.evaluate("""async (path) => {
          await draftPut({key: path, document: path, baseDiskVersion: 'a version that is gone',
                          payload: {path, title: path, kind: 'text', text: 'a draft of the old file'},
                          updatedAt: Date.now()});
          await mountTab();
          return {doc: LeeCM.getDoc(lee.editors.get('file')), rows: (await draftsFor(path)).length};
        }""", str(f))
        kept = await pg.evaluate("""async (path) => {
          await draftPut({key: path, document: path, baseDiskVersion: lee.diskVersion,
                          payload: {path, title: path, kind: 'text', text: 'my unsaved edit'},
                          updatedAt: Date.now()});
          await mountTab();
          return LeeCM.getDoc(lee.editors.get('file'));
        }""", str(f))
        return stale, kept
    stale, kept = _run(go, roots=[tmp_path])
    assert stale['doc'].strip() == 'from disk', stale
    assert stale['rows'] == 0, 'the draft it could not place is dropped, not left to come back'
    assert kept.strip() == 'my unsaved edit', 'a draft of the version in hand is still the users work'

def test_one_broken_step_of_boot_costs_itself_and_nothing_below_it(tmp_path):
    """`boot` was a single sequence of awaits, so a throw anywhere in it took every step below with it: the pills were never repainted, the file watcher and the polls never started, and nothing said why."""
    async def go(pg):
        return await pg.evaluate("""async () => {
          window.checkProjectRuntime = () => { throw new Error('a step that fails'); };
          const watch = window.watchFiles, pills = window.refreshProjectPills, log = window.runLogLoop;
          window.__ran = [];
          window.watchFiles = () => { window.__ran.push('watcher'); return watch(); };
          window.refreshProjectPills = () => { window.__ran.push('pills'); return pills(); };
          window.runLogLoop = () => { window.__ran.push('runlog'); return log(); };
          await boot();
          return {ran: window.__ran, status: document.querySelector('#status')?.textContent || ''};
        }""")
    d = _run(go, roots=[tmp_path])
    assert d['ran'] == ['pills', 'runlog', 'watcher'], 'every step below the one that threw still runs'
    assert 'ready' in d['status'], 'and boot finishes'

def test_boot_finishes_in_a_webview_without_requestidlecallback(tmp_path):
    """WebKit has never shipped `requestIdleCallback`, and `boot` referenced it bare, which is a ReferenceError rather than a falsy value."""
    async def go(pg):
        return await pg.evaluate("""async () => {
          delete window.requestIdleCallback;                 // the webview Leela ships in
          const watch = window.watchFiles, pills = window.refreshProjectPills;
          window.__ran = [];
          window.watchFiles = () => { window.__ran.push('watcher'); return watch(); };
          window.refreshProjectPills = () => { window.__ran.push('pills'); return pills(); };
          await boot();
          return {ran: window.__ran, status: document.querySelector('#status')?.textContent || ''};
        }""")
    d = _run(go, roots=[tmp_path])
    assert d['ran'] == ['pills', 'watcher'], 'the steps below it run in a webview that lacks it'
    assert 'ready' in d['status']


def _nb_merge_text(cells):
    "A notebook whose cells are `(id, source)` pairs, written the way nbformat writes them."
    import json
    return json.dumps({'cells': [{'id': i, 'cell_type': 'code', 'metadata': {}, 'execution_count': 1,
                                  'outputs': [{'output_type': 'stream', 'name': 'stdout', 'text': ['old\n']}],
                                  'source': [src]} for i, src in cells],
                       'metadata': {'kernelspec': {'name': 'python3'}}, 'nbformat': 4, 'nbformat_minor': 5},
                      indent=1) + '\n'

def _conflicted_notebook_repo(tmp_path):
    "A repository mid-merge: two cells both sides changed, one cell only theirs added, one untouched."
    import subprocess
    root = tmp_path/'repo'; root.mkdir()
    run = lambda *a: subprocess.run(['git', *a], cwd=root, check=True, capture_output=True, text=True)
    run('init', '-q', '-b', 'main')
    run('config', 'user.email', 't@example.com'); run('config', 'user.name', 'T')
    nb = root/'n.ipynb'
    nb.write_text(_nb_merge_text([('a', 'x = 1'), ('b', 'y = 1'), ('d', 'z = 1')]))
    run('add', 'n.ipynb'); run('commit', '-qm', 'base')
    run('checkout', '-qb', 'other')
    nb.write_text(_nb_merge_text([('a', 'x = 3'), ('b', 'y = 3'), ('d', 'z = 1'), ('c', 'theirs_only = 1')]))
    run('commit', '-qam', 'theirs')
    run('checkout', '-q', 'main')
    nb.write_text(_nb_merge_text([('a', 'x = 2'), ('b', 'y = 2'), ('d', 'z = 1')]))
    run('commit', '-qam', 'ours')
    merge = subprocess.run(['git', 'merge', 'other'], cwd=root, capture_output=True, text=True)
    assert merge.returncode != 0, 'the merge is supposed to conflict'
    return root, nb

def test_a_conflicted_notebook_is_merged_cell_by_cell_in_the_browser(tmp_path):
    """The text panes showed a conflicted notebook as JSON with markers through it, which is neither a notebook nor anything a person can answer."""
    import json
    root, nb = _conflicted_notebook_repo(tmp_path)
    assert '<<<<<<<' in nb.read_text(), 'precondition: the file on disk is marked up'
    async def go(pg):
        await pg.evaluate("p => showGitConflict(p)", str(nb))
        await pg.wait_for_selector('.lee-modal-nbmerge .lee-nbmerge-row')
        opened = await pg.evaluate("""() => ({
          rows: $$('.lee-modal-nbmerge .lee-nbmerge-row').length,
          context: $('.lee-modal-nbmerge .lee-nbmerge-context summary').textContent,
          left: $('.lee-modal-nbmerge [data-nb-left]').textContent,
          blocked: $('.lee-modal-nbmerge [data-nb-apply]').disabled,
          text: $('.lee-modal-nbmerge .lee-nbmerge-rows').innerText})""")
        take = """([k, c]) => document.querySelector(`[data-key="${k}"][data-choice="${c}"]`).click()"""
        await pg.evaluate(take, ['a', 'ours'])
        await pg.evaluate(take, ['b', 'both'])
        half = await pg.evaluate("() => ({left: $('.lee-modal-nbmerge [data-nb-left]').textContent, blocked: $('.lee-modal-nbmerge [data-nb-apply]').disabled})")
        await pg.evaluate(take, ['c', 'theirs'])
        ready = await pg.evaluate("() => ({left: $('.lee-modal-nbmerge [data-nb-left]').textContent, blocked: $('.lee-modal-nbmerge [data-nb-apply]').disabled})")
        await pg.evaluate("() => $('.lee-modal-nbmerge [data-nb-apply]').click()")
        await pg.wait_for_selector('.lee-modal-nbmerge', state='detached')
        await pg.wait_for_function("() => gitUI.snapshot && gitUI.snapshot.changes")
        return opened, half, ready, await pg.evaluate("() => api('/git/info')")
    opened, half, ready, info = _run(go, roots=[root])
    assert opened['rows'] == 3, f'three cells owe an answer: {opened}'
    assert '1 settled cell' in opened['context'], opened['context']
    assert 'z = 1' not in opened['text'], 'the settled cell is folded away until it is asked for'
    assert 'x = 2' in opened['text'] and 'x = 3' in opened['text'], 'both sides of a contested cell are shown'
    assert opened['blocked'] and '3 of 3' in opened['left'], opened
    assert half['blocked'] and '1 of 3' in half['left'], half
    assert not ready['blocked'] and 'all 3' in ready['left'], ready
    book = json.loads(nb.read_text())
    assert [''.join(c['source']) for c in book['cells']] == \
        ['x = 2', 'y = 2', 'y = 3', 'z = 1', 'theirs_only = 1'], book['cells']
    assert book['metadata']['kernelspec']['name'] == 'python3', 'the notebook keeps its own metadata'
    assert not [c for c in info['changes'] if c['conflicted']], 'the merge has nothing left to settle'


def test_a_git_diff_tab_paints_its_code_in_the_themes_token_colours(tmp_path):
    """Diff lines were green and red text; the code in them now takes `lee-hl.css` colours, and the mark keeps the change's."""
    import subprocess
    def git(*a): subprocess.run(['git', *a], cwd=tmp_path, check=True, capture_output=True)
    git('init', '-q', '-b', 'main'); git('config', 'user.email', 'a@b'); git('config', 'user.name', 'c')
    (tmp_path/'app.py').write_text('value = 1\n'); git('add', '.'); git('commit', '-qm', 'one')
    (tmp_path/'app.py').write_text('import os\nvalue = "two"\n')
    async def go(pg):
        await pg.evaluate("""async () => { const d = noteHl(await api('/git/diff?path=app.py'));
            await openGitDiffTab({kind: 'changes-unstaged', path: 'app.py', base: 'index', head: 'worktree', baseLabel: 'index',
              headLabel: 'working tree', left: d.left, right: d.right, patch: d.content || d.text, rawPatch: d.text, group: 'unstaged'}); }""")
        await pg.wait_for_selector('.lee-patch-line.add.hl .hl-keyword', timeout=5000)
        return await pg.evaluate("""() => { const line = document.querySelector('.lee-patch-line.add.hl'),
            key = line.querySelector('.hl-keyword'), mark = line.querySelector('.lee-patch-mark'), c = e => getComputedStyle(e).color;
            return {key: c(key), mark: c(mark), text: c(line), plain: !!document.querySelector('.lee-patch-line.hunk:not(.hl)')}; }""")
    got = _run(go, roots=[tmp_path])
    assert got['key'] not in (got['mark'], got['text']), got
    assert got['plain'], 'the hunk header is not coloured as code'


def test_a_folder_opens_before_its_git_marks_arrive(tmp_path, monkeypatch):
    """In the Mac app the first expand waited seconds on `git status`; now the rows come first and the marks follow."""
    import subprocess, time
    def git(*a): subprocess.run(['git', *a], cwd=tmp_path, check=True, capture_output=True)
    git('init', '-q', '-b', 'main'); git('config', 'user.email', 'a@b'); git('config', 'user.name', 'c')
    (tmp_path/'pkg').mkdir(); (tmp_path/'pkg'/'a.py').write_text('x = 1\n'); git('add', '.'); git('commit', '-qm', 'one')
    (tmp_path/'pkg'/'a.py').write_text('x = 2\n')
    from leela.blocks.fs import ui
    real = ui.GitRepo.decorations
    def slow(self): time.sleep(2); return real(self)   # what `git status` costs inside the Mac app
    monkeypatch.setattr(ui.GitRepo, 'decorations', slow)
    async def go(pg):
        pkg = '#filetree .lee-dir[data-path$="/pkg"]'
        if not await pg.evaluate("!!document.querySelector('.lee-node.lee-dir.lee-root[open]')"):
            await pg.click('.lee-node.lee-dir.lee-root > summary')
        await pg.wait_for_selector(pkg, timeout=5000)
        await pg.wait_for_function("!document.querySelector('#filetree .htmx-request, #filetree .htmx-swapping, #filetree .htmx-settling')")   # a click before htmx binds `click once` opens an empty folder
        ui._TREE.clear()   # the page loaded only once the boot paint had warmed it; the case is a cold one
        t = time.perf_counter()
        await pg.click(pkg + ' > summary')
        await pg.wait_for_selector(f'{pkg} .lee-file[data-path$="a.py"]', timeout=5000)
        shown = time.perf_counter() - t
        marked_early = await pg.evaluate(f"!!document.querySelector('{pkg} .lee-file.git-modified')")
        await pg.wait_for_selector(f'{pkg} .lee-file.git-modified .lee-tree-git', timeout=8000)
        folder = await pg.evaluate(f"document.querySelector('{pkg}').classList.contains('git-modified')")
        return shown, marked_early, folder
    shown, marked_early, folder = _run(go, roots=[tmp_path])
    assert shown < 1.2, f'the rows waited {shown:.2f}s for git'
    assert not marked_early, 'the mark came from the delayed request, after the rows'
    assert folder, 'the folder takes the strongest state under it'


# ── the vault: the Read sheet, its send line, and the document view ─────────

@pytest.fixture
def vault_proj(tmp_path, monkeypatch):
    "A folder holding a 3-page PDF (text, a blank page, an email), and a hosted stub reader that keeps what it was sent."
    from tests.blocks.test_vault_screens import EMAIL, INVOICE, Reader, mkpdf
    import leela.blocks.memory.memory as mm, leela.blocks.vault.app as va
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'vault.db'))
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    (proj := tmp_path/'proj').mkdir()
    (proj/'scan.pdf').write_bytes(mkpdf([INVOICE, '', EMAIL]))
    hosted = Reader('hosted', 'hosted')
    monkeypatch.setattr(mm, 'read_chat', lambda m: hosted if m == 'hosted' else None)
    monkeypatch.setattr(va, 'reader_id', lambda n: n or None)
    return proj, hosted

def test_a_pdf_read_from_the_sheet_opens_on_its_pages_and_j_k_move_through_them(vault_proj):
    proj, hosted = vault_proj
    src = str((proj/'scan.pdf').resolve())
    async def go(pg):
        await pg.evaluate('src => leeVaultReadSheet(src)', src)
        await pg.wait_for_selector('[data-vault-sheet] [data-send]:not(:empty)')
        out = {'line': await pg.inner_text('[data-send]'), 'est': await pg.inner_text('[data-est]')}
        await pg.click('[data-read]')
        await pg.wait_for_selector('.lee-vault-docview .lee-vault-thumb', timeout=20000)
        await pg.wait_for_function("() => document.querySelector('[data-pagetext]')?.textContent.includes('page 1')")
        out['thumbs'] = await pg.locator('.lee-vault-thumb').count()
        out['img'] = await pg.evaluate("() => new Promise(r => { const i = document.querySelector('[data-pageimg]');"
                                       " i.complete ? r(i.naturalWidth) : i.onload = () => r(i.naturalWidth); })")
        out['scope'] = await pg.evaluate("() => { const v = document.querySelector('.lee-vault-docview'); v.focus();"
                                         " return document.activeElement === v; }")
        await pg.keyboard.press('j')
        await pg.wait_for_function("() => document.querySelector('.lee-vault-docview').dataset.page === '1'")
        await pg.keyboard.press('j'); await pg.keyboard.press('k')
        await pg.wait_for_function("() => document.querySelector('.lee-vault-docview').dataset.page === '1'")
        await pg.keyboard.press('k'); await pg.keyboard.press(']')
        await pg.wait_for_function("() => document.querySelector('.lee-vault-docview').dataset.page === '1'")
        out['flag'] = await pg.evaluate("() => document.querySelector('.lee-vault-thumb.active')?.dataset.flagged")
        out['level'] = await pg.evaluate("() => document.querySelector('[data-vault-level]')?.value")
        return out
    got = _run(go, roots=[proj])
    assert 'nothing leaves this machine' in got['line'] and '3 pages' in got['est']
    assert got['thumbs'] == 3 and got['img'] > 100 and got['scope']
    assert got['flag'] == '1', '] lands on the flagged (blank) page'
    assert got['level'] == 'personal', 'the email on page 3 makes it Personal'
    assert hosted.sent == []

def test_the_send_line_turns_red_for_a_personal_page_and_the_read_button_says_what_it_will_do(vault_proj):
    proj, hosted = vault_proj
    src = str((proj/'scan.pdf').resolve())
    async def go(pg):
        await pg.evaluate('src => leeVaultReadSheet(src)', src)
        await pg.wait_for_selector('[data-vault-sheet] [data-send]:not(:empty)')
        await pg.evaluate("""() => { const f = document.querySelector('[data-vault-sheet]'), s = f.elements.model;
          const o = document.createElement('option'); o.value = 'hosted'; o.textContent = 'hosted · hosted: stub'; s.appendChild(o);
          s.value = 'hosted'; f.elements.parse.value = 'llm'; f.elements.parse.dispatchEvent(new Event('change', {bubbles: true})); }""")
        await pg.wait_for_selector('[data-send].blocked')
        out = {'line': await pg.inner_text('[data-send]'), 'button': await pg.inner_text('[data-read]'),
               'allow': await pg.is_visible('[data-allow]')}
        await pg.click('[data-read]')
        await pg.wait_for_selector('.lee-vault-docview .lee-vault-thumb', timeout=20000)
        return out
    got = _run(go, roots=[proj])
    assert 'hosted' in got['line'] and '1 personal page withheld' in got['line']
    assert got['button'].startswith('Read, keeping') and got['allow']
    assert len(hosted.sent) == 2, 'the open pages went; the personal one stayed home'

def test_a_type_the_words_settle_picks_the_preset_over_the_folders_choice(vault_proj):
    proj, hosted = vault_proj
    src = str((proj/'scan.pdf').resolve())
    async def go(pg):
        await pg.evaluate(JOB, ['/vault/read', {'src': src, 'preset': 'generic'}])
        await pg.evaluate('src => leeVaultReadSheet(src)', src)
        await pg.wait_for_selector('[data-vault-sheet] [data-est]:not(:empty)')
        return {'preset': await pg.input_value('[data-vault-sheet] [name=preset]'), 'est': await pg.inner_text('[data-est]')}
    got = _run(go, roots=[proj])
    assert got['preset'] == 'tables' and 'preset tables suggested' in got['est'], 'an invoice reads as tables though the folder remembers generic'

def test_hyper_v_opens_the_vault_tab(tmp_path, monkeypatch):
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'vault.db'))
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    async def go(pg):
        await pg.evaluate("""() => document.body.dispatchEvent(new KeyboardEvent('keydown', {bubbles: true, cancelable: true,
          key: 'V', code: 'KeyV', ctrlKey: true, altKey: true, shiftKey: true, metaKey: true}))""")
        await pg.wait_for_selector('#vaultwb .lee-wb-tab.active', timeout=15000)
        return await pg.inner_text('#vaultwb .lee-wb-tab.active')
    assert _run(go, roots=[tmp_path]) == 'library'

def test_vault_settings_is_a_left_aligned_tab_and_library_starts_with_its_documents(tmp_path, monkeypatch):
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'vault.db'))
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    box = "s => { const r = document.querySelector(s).getBoundingClientRect(); return {x: r.x, w: r.width, y: r.y, b: r.bottom}; }"
    async def go(pg):
        await pg.set_viewport_size({'width': 1400, 'height': 900})
        await pg.evaluate("() => leeVaultWorkbench('library')")
        await pg.wait_for_selector('.lee-wb-library .lee-wb-docs')
        out = {'docs': await pg.evaluate(box, '.lee-wb-docs'), 'tall': await pg.evaluate('() => innerHeight'),
               'folded': await pg.locator('.lee-wb-library [data-vault-floor]').count()}
        await pg.click('#vaultwb .lee-wb-tab:has-text("settings")')
        await pg.wait_for_selector('.lee-wb-settings [data-vault-floor]')
        out |= {k: await pg.evaluate(box, s) for k, s in (('body', '#vaultwbbody'), ('floor', '[data-vault-floor]'),
                ('row', '.lee-vault-row'), ('vaults', '[data-set="vaults"]'), ('privacy', '[data-set="privacy"]'))}
        out['visible'] = await pg.locator('[data-vault-floor]').is_visible() and await pg.locator('.lee-vault-row').first.is_visible()
        await pg.fill('[data-set="vaults"] [name=path]', str(tmp_path/'missing'/'x.db'))
        await pg.click('[data-set="vaults"] button:has-text("attach")')
        await pg.wait_for_selector('#status.lee-status.err', timeout=5000)
        out['said'] = await pg.inner_text('#status')
        out['kept'] = await pg.input_value('[data-set="vaults"] [name=path]')
        return out
    got = _run(go, roots=[tmp_path])
    assert got['folded'] == 0 and got['docs']['y'] < got['tall'] / 2, 'the documents start in the top half of Library'
    assert got['visible']
    assert got['row']['w'] < got['body']['w'] / 2, 'a vault row is compact, not a full-width bar'
    assert got['row']['x'] - got['body']['x'] < 40, 'the vault row sits at the left edge'
    assert got['floor']['x'] - got['privacy']['x'] < 60, 'the floor select sits at the left of its section'
    assert got['privacy']['x'] > got['vaults']['x'] + 200 and abs(got['privacy']['y'] - got['vaults']['y']) < 4, 'privacy is the second column'
    assert got['said'] and got['kept'].endswith('x.db'), 'a refused attach says why and keeps what was typed'

# ── the vault: fixing a page, and the Review queue ──────────────────────────

@pytest.fixture
def review_proj(tmp_path, monkeypatch):
    "An Open PDF and a Personal one, a hosted reader, and proofreaders on this machine that change two words of page 1."
    from tests.blocks.test_vault_screens import EMAIL, INVOICE, Reader, mkpdf
    from tests.blocks.test_vault_review import PLAIN, Fixed
    import leela.blocks.memory.memory as mm, leela.blocks.vault.app as va
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'vault.db'))
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    (proj := tmp_path/'proj').mkdir()
    (proj/'plain.pdf').write_bytes(mkpdf([INVOICE, '', PLAIN]))
    (proj/'scan.pdf').write_bytes(mkpdf([INVOICE, '', EMAIL]))
    two = INVOICE.replace('ACME', 'ACMEX').replace('Payment', 'Paymnt').replace('\n', ' ')
    readers = {'hosted': Reader('hosted', 'hosted'), 'p1': Fixed('p1', 'litert', two), 'p2': Fixed('p2', 'litert', two),
               'p3': Fixed('p3', 'litert', INVOICE.replace('Ltd', 'Limited').replace('\n', ' '))}
    monkeypatch.setattr(mm, 'read_chat', lambda m: readers.get(m))
    monkeypatch.setattr(va, 'reader_id', lambda n: n or None)
    return proj, readers

#: Start a job from the page and wait on it, so a test sets the scene through the routes a screen uses.
JOB = """async ([url, body]) => {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const id = ((await r.text()).match(/id="job-([^"]+)"/) || [])[1];
  for (let i = 0; i < 400; i++) {
    await new Promise(res => setTimeout(res, 100));
    const j = (await (await fetch('/jobs?limit=40')).json()).jobs.find(x => x.id === id);
    if (j && !j.active) return j;
  }
}"""
PAGE = "([d, s]) => fetch(`/vault/page?doc=${d}&shelf=${s}&page=0`).then(r => r.json())"

def test_r_re_reads_a_page_h_shows_its_versions_and_m_shows_it_as_sent(review_proj):
    proj, readers = review_proj
    src = str((proj/'plain.pdf').resolve())
    async def go(pg):
        j = await pg.evaluate(JOB, ['/vault/read', {'src': src}])
        await pg.evaluate('([d, s]) => leeOpenVaultDoc(d, s, "", "plain")', [j['result']['doc_id'], j['result']['shelf']])
        await pg.wait_for_function("() => document.querySelector('[data-pagetext]')?.textContent.includes('v1')")
        await pg.focus('.lee-vault-docview'); await pg.keyboard.press('r')
        await pg.wait_for_selector('[data-vault-pagesheet="reparse"]')
        out = {'pages': await pg.input_value('[data-vault-pagesheet] [name=pages]')}
        await pg.evaluate("""() => { const f = document.querySelector('[data-vault-pagesheet]'), s = f.elements.model0;
          s.add(new Option('hosted · hosted: stub', 'hosted')); s.value = 'hosted'; s.dispatchEvent(new Event('change', {bubbles: true})); }""")
        await pg.wait_for_function("() => document.querySelector('[data-vault-pagesheet] [data-send]').textContent.includes('hosted.')")
        out['line'] = await pg.inner_text('[data-vault-pagesheet] [data-send]')
        await pg.click('[data-vault-pagesheet] [data-go]')
        await pg.wait_for_function("() => !document.querySelector('[data-vault-pagesheet]') && "
                                   "document.querySelector('[data-pagetext]')?.textContent.includes('read by hosted')", timeout=20000)
        out['head'] = await pg.inner_text('.lee-vault-pagehead')
        await pg.focus('.lee-vault-docview'); await pg.keyboard.press('h')
        await pg.wait_for_selector('[data-vault-history] .lee-drow.add')
        out['diff'] = await pg.inner_text('[data-vault-history] [data-diff]')
        await pg.keyboard.press('Escape')
        await pg.wait_for_function("() => !document.querySelector('[data-vault-history]')")
        await pg.focus('.lee-vault-docview'); await pg.keyboard.press('j'); await pg.keyboard.press('j')
        await pg.wait_for_function("() => document.querySelector('.lee-vault-docview').dataset.page === '2'")
        await pg.keyboard.press('m')
        await pg.wait_for_selector('[data-sent]')
        out['sent'] = await pg.inner_text('.lee-vault-pagetext')
        return out
    got = _run(go, roots=[proj])
    assert got['pages'] == '1' and 'hosted' in got['line'] and '1 page open' in got['line']
    assert 'v2' in got['head'] and 'model' in got['head']
    assert 'read by hosted' in got['diff']
    assert 'as sent' in got['sent'] and 'whole' in got['sent'] and 'weather' in got['sent']
    assert len(readers['hosted'].sent) == 1

def test_review_keys_stage_accept_reject_and_undo(review_proj):
    proj, readers = review_proj
    src = str((proj/'plain.pdf').resolve())
    async def go(pg):
        j = await pg.evaluate(JOB, ['/vault/read', {'src': src}])
        doc, shelf = j['result']['doc_id'], j['result']['shelf']
        await pg.evaluate(JOB, ['/vault/proofread', {'doc': doc, 'shelf': shelf, 'readers': 'p1,p2,p3', 'pages': '1'}])
        await pg.evaluate('([d, s]) => leeVaultReview(d, s)', [doc, shelf])
        await pg.wait_for_selector('.lee-review-row')
        count = "n => document.querySelector('[data-count=\"proof\"]')?.textContent === n"
        out = {'before': await pg.inner_text('[data-count="proof"]'),
               'scope': await pg.evaluate("() => { const r = document.querySelector('.lee-vault-review'); r.focus(); return document.activeElement === r; }")}
        await pg.keyboard.press('a')
        await pg.wait_for_selector('.lee-review-row.staged')
        out['staged'] = await pg.inner_text('[data-staged]')
        await pg.keyboard.press('x')
        await pg.wait_for_function(count, arg='2')
        out['rejected'] = await pg.evaluate("() => [...document.querySelectorAll('.lee-review-row ins')].map(e => e.textContent)")
        await pg.focus('.lee-vault-review'); await pg.keyboard.press('A')
        await pg.wait_for_function(count, arg='0')
        out['accepted'] = (await pg.evaluate(PAGE, [doc, shelf]))['text']
        await pg.focus('.lee-vault-review'); await pg.keyboard.press('u')
        await pg.wait_for_function(PAGE.replace('r.json())', 'r.json()).then(p => p.version === 3)'), arg=[doc, shelf])
        out['undone'] = (await pg.evaluate(PAGE, [doc, shelf]))['text']
        await pg.wait_for_function(count, arg='2')
        await pg.focus('.lee-vault-review'); await pg.keyboard.press('u')
        await pg.wait_for_function(count, arg='3')
        await pg.focus('.lee-vault-review'); await pg.keyboard.press('d')
        await pg.wait_for_selector('[data-review-doubts]:checked')
        out['doubts'] = await pg.locator('.lee-review-row').count()
        return out
    got = _run(go, roots=[proj])
    assert got['before'] == '3' and got['scope'] and 'staged' in got['staged']
    assert 'Limited' not in got['rejected'], 'a staged the first change and moved on; x rejected the doubt it moved to'
    assert 'ACMEX' in got['accepted'] and 'Paymnt' in got['accepted'], 'A applied the page: the staged change and the other proposed one'
    assert 'ACMEX' not in got['undone'] and 'Paymnt' not in got['undone'], 'u reverted the accept as a new version, its changes open again'
    assert got['doubts'] == 1, 'the second u put the rejected doubt back'

def test_personal_info_review_a_and_x_change_the_count(review_proj):
    proj, readers = review_proj
    src = str((proj/'scan.pdf').resolve())
    async def go(pg):
        j = await pg.evaluate(JOB, ['/vault/read', {'src': src}])
        ds = [j['result']['doc_id'], j['result']['shelf']]
        await pg.evaluate('([d, s]) => leeVaultReview(d, s)', ds)
        await pg.wait_for_selector('[data-review-mode="pii"]')
        await pg.click('[data-review-mode="pii"]')
        await pg.wait_for_selector('.lee-review-row')
        n = lambda: pg.evaluate("() => +document.querySelector('[data-count=\"pii\"]').textContent")
        out = {'before': await n(), 'preview': await pg.inner_text('.lee-review-row.active code')}
        fewer = "n => +document.querySelector('[data-count=\"pii\"]').textContent < n"
        await pg.focus('.lee-vault-review'); await pg.keyboard.press('x')
        await pg.wait_for_function(fewer, arg=out['before'])
        out['after_x'] = await n()
        await pg.focus('.lee-vault-review'); await pg.keyboard.press('u')
        await pg.wait_for_function("n => +document.querySelector('[data-count=\"pii\"]').textContent === n", arg=out['before'])
        await pg.focus('.lee-vault-review'); await pg.keyboard.press('a')
        await pg.wait_for_function(fewer, arg=out['before'])
        out['level'] = await pg.evaluate("([d, s]) => fetch(`/vault/privacy?doc=${d}&shelf=${s}`).then(r => r.json()).then(r => r.level)", ds)
        return out
    got = _run(go, roots=[proj])
    assert got['before'] >= 1 and got['after_x'] < got['before']
    assert 'jane.doe@example.com' not in got['preview'] and '•' in got['preview']
    assert got['level'] == 'personal'


# ── the vault: one home with scoped find and ask, types, fields, and the prompt bar ──

@pytest.fixture
def find_proj(tmp_path, monkeypatch):
    "An Open PDF, an ask chat and an extract chat on this machine, and every read proposing a type for Review > Types."
    from tests.blocks.test_vault_screens import INVOICE, mkpdf
    from tests.blocks.test_vault_review import PLAIN
    from tests.blocks.test_vault_find import AskChat, FieldChat
    from fastcore.all import AttrDict
    import leela.blocks.memory.memory as mm, leela.blocks.vault.app as va, vishalakshi.ask as vk
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'vault.db'))
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    (proj := tmp_path/'proj').mkdir()
    (proj/'plain.pdf').write_bytes(mkpdf([INVOICE, '', PLAIN]))
    chat = AskChat('local', 'litert', 'It is about the weather [1].')
    monkeypatch.setattr(va, 'chat_spec', lambda n: AttrDict(name=n or 'local', local=True, model_id='local', runtime='litert', ctx=8000))
    monkeypatch.setattr(va, 'ask_chat', lambda s: lambda *a, **kw: chat)
    monkeypatch.setattr(vk, 'CHAT', FieldChat)
    monkeypatch.setattr(mm.Memory, 'guess_type', lambda self, doc, shelf=None: self.set_meta(doc, shelf, doctype_proposed='receipt', doctype_score=.4))
    return proj

def test_slash_finds_in_the_document_and_a_citation_opens_its_page_image(find_proj):
    src = str((find_proj/'plain.pdf').resolve())
    async def go(pg):
        j = await pg.evaluate(JOB, ['/vault/read', {'src': src}])
        await pg.evaluate('([d, s]) => leeOpenVaultDoc(d, s, "", "plain")', [j['result']['doc_id'], j['result']['shelf']])
        await pg.wait_for_function("() => document.querySelector('[data-pagetext]')?.textContent.includes('v1')")
        await pg.focus('.lee-vault-docview'); await pg.keyboard.press('/')
        await pg.wait_for_selector('[data-vault-find][data-mounted]')
        out = {'scope': await pg.evaluate("() => document.querySelector('[data-find-scope]').selectedOptions[0].textContent")}
        await pg.fill('[data-vault-find] [name=q]', 'weather garden')
        await pg.wait_for_function("() => document.querySelector('.lee-wb-find [data-send]')?.textContent.includes('on this machine')")
        await pg.click('[data-find-ask]')
        await pg.wait_for_selector('[data-answer]:not(.asking)')
        out['answer'] = await pg.inner_text('[data-answer]')
        out['cite'] = await pg.inner_text('[data-cite]')
        await pg.click('[data-cite]')
        await pg.wait_for_function("() => document.querySelector('.lee-vault-docview')?.dataset.page === '2'")
        out['img'] = await pg.evaluate("() => new Promise(r => { const i = document.querySelector('[data-pageimg]');"
                                       " i.complete && i.naturalWidth ? r(i.src) : i.onload = () => r(i.src); })")
        await pg.wait_for_selector('.lee-vault-marked')
        out['marked'] = await pg.inner_text('.lee-vault-marked')
        return out
    got = _run(go, roots=[find_proj])
    assert got['scope'] == 'this document: plain'
    assert 'weather' in got['answer'] and 'p. 3' in got['cite']
    assert 'page=2' in got['img'] and 'weather' in got['marked']

def test_review_types_a_accepts_and_x_rejects(find_proj):
    async def go(pg):
        for name in ('plain.pdf', 'other.pdf'):
            await pg.evaluate(JOB, ['/vault/read', {'src': str((find_proj/name).resolve())}])
        await pg.evaluate('() => leeVaultReview()')
        await pg.wait_for_selector('[data-review-mode="types"]')
        await pg.click('[data-review-mode="types"]')
        await pg.wait_for_selector('.lee-review-type')
        n = "n => document.querySelector('[data-count=\"types\"]').textContent === n"
        out = {'before': await pg.inner_text('[data-count="types"]')}
        await pg.focus('.lee-vault-review'); await pg.keyboard.press('a')
        await pg.wait_for_function(n, arg='1')
        await pg.focus('.lee-vault-review'); await pg.keyboard.press('x')
        await pg.wait_for_function(n, arg='0')
        out['library'] = await pg.evaluate("() => fetch('/vault/view/library').then(r => r.text())")
        return out
    (find_proj/'other.pdf').write_bytes((find_proj/'plain.pdf').read_bytes().replace(b'garden', b'meadow'))
    got = _run(go, roots=[find_proj])
    assert got['before'] == '2' and got['library'].count('>receipt<') == 1

def test_a_field_click_lands_on_its_page_in_the_fields_drawer(find_proj):
    src = str((find_proj/'plain.pdf').resolve())
    async def go(pg):
        j = await pg.evaluate(JOB, ['/vault/read', {'src': src}])
        d, s = j['result']['doc_id'], j['result']['shelf']
        await pg.evaluate(JOB, ['/vault/extract', {'doc': d, 'shelf': s, 'model': 'local'}])
        await pg.evaluate('([d, s]) => leeOpenVaultDoc(d, s, "", "plain")', [d, s])
        await pg.wait_for_function("() => document.querySelector('[data-pagetext]')?.textContent.includes('v1')")
        await pg.focus('.lee-vault-docview'); await pg.keyboard.press('j'); await pg.keyboard.press('j')
        await pg.wait_for_function("() => document.querySelector('.lee-vault-docview').dataset.page === '2'")
        await pg.click('[data-vault-act="fields"]')
        await pg.wait_for_selector('[data-field]')
        out = {'warn': await pg.inner_text('.lee-vault-field.warn')}
        await pg.wait_for_function("() => document.querySelector('[data-extract] [data-send]')?.textContent.length")
        out['line'] = await pg.inner_text('[data-extract] [data-send]')
        await pg.click('.lee-vault-field:has-text("number")')
        await pg.wait_for_function("() => document.querySelector('.lee-vault-docview').dataset.page === '0'")
        await pg.wait_for_selector('.lee-vault-marked')
        out['marked'] = await pg.inner_text('.lee-vault-marked')
        return out
    got = _run(go, roots=[find_proj])
    assert 'calendar date' in got['warn'] and 'on this machine' in got['line']
    assert 'Invoice number 42' in got['marked']

# ── the vault: books of verses and the send log ─────────────────────────────

@pytest.fixture
def book_proj(tmp_path, monkeypatch):
    "A two-page book of verses and a hosted vision reader that answers each page's verse blocks."
    from tests.blocks.test_vault_screens import mkpdf
    from tests.blocks.test_vault_book import Verses
    import leela.blocks.memory.memory as mm, leela.blocks.vault.app as va
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'vault.db'))
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    (proj := tmp_path/'proj').mkdir()
    (proj/'gita.pdf').write_bytes(mkpdf(['Bhagavad Gita chapter one', 'Bhagavad Gita chapter one continued']))
    vh = Verses('vh', 'hosted', proj/'gita.pdf')
    monkeypatch.setattr(mm, 'read_chat', lambda m: vh if m == 'vh' else None)
    monkeypatch.setattr(va, 'reader_id', lambda n: n or None)
    return proj

def test_the_chapters_drawer_lists_verse_numbers_and_a_verse_opens_its_page(book_proj):
    src = str((book_proj/'gita.pdf').resolve())
    async def go(pg):
        await pg.evaluate('src => leeVaultReadSheet(src)', src)
        await pg.wait_for_selector('[data-vault-sheet] [data-est]:not(:empty)')
        out = {'hidden': await pg.is_hidden('[data-book]')}
        await pg.select_option('[data-vault-sheet] [name=preset]', 'sanskrit')
        await pg.wait_for_selector('[data-book]:not([hidden])')
        await pg.keyboard.press('Escape')
        j = await pg.evaluate(JOB, ['/vault/book', {'src': src, 'model': 'vh', 'counts': '5'}])
        await pg.evaluate('([d, s]) => leeOpenVaultDoc(d, s, "", "gita")', [j['result']['doc_id'], j['result']['shelf']])
        await pg.wait_for_selector('[data-vault-act="chapters"]')
        await pg.click('[data-vault-act="chapters"]')
        await pg.wait_for_selector('[data-verse]')
        out['verses'] = await pg.evaluate("() => [...document.querySelectorAll('[data-verse]')].map(b => b.textContent)")
        out['probs'] = await pg.inner_text('[data-book-probs]')
        await pg.click('[data-verse="0.2"]')
        await pg.wait_for_function("() => document.querySelector('.lee-vault-docview').dataset.page === '1'")
        await pg.wait_for_selector('.lee-vault-marked')
        out['marked'] = await pg.inner_text('.lee-vault-marked')
        await pg.click('[data-book-md]')
        await pg.wait_for_selector('[data-book-preview]')
        out['md'] = await pg.inner_text('[data-book-preview]')
        return out
    got = _run(go, roots=[book_proj])
    assert got['hidden'], 'a book of verses is offered for a verse preset only'
    assert got['verses'] == ['1', '2', '4'] and got['probs'].startswith('3 problems')
    assert '॥४॥' in got['marked'], 'the verse lands on its block'
    assert '## अथ प्रथमोऽध्यायः' in got['md']

def test_review_verses_a_and_x_check_problems_and_u_opens_one_again(book_proj):
    src = str((book_proj/'gita.pdf').resolve())
    async def go(pg):
        j = await pg.evaluate(JOB, ['/vault/book', {'src': src, 'model': 'vh', 'counts': '5'}])
        await pg.evaluate('([d, s]) => leeVaultReview(d, s, "", "book")', [j['result']['doc_id'], j['result']['shelf']])
        await pg.wait_for_selector('.lee-review-prob')
        n = "n => document.querySelector('[data-count=\"book\"]')?.textContent === n"
        out = {'before': await pg.inner_text('[data-count="book"]'), 'pages': await pg.evaluate(
            "() => [...document.querySelectorAll('.lee-review-page')].map(e => e.textContent)")}
        await pg.focus('.lee-vault-review'); await pg.keyboard.press('a')
        await pg.wait_for_function(n, arg='2')
        await pg.focus('.lee-vault-review'); await pg.keyboard.press('x')
        await pg.wait_for_function(n, arg='1')
        await pg.focus('.lee-vault-review'); await pg.keyboard.press('u')
        await pg.wait_for_function(n, arg='2')
        await pg.focus('.lee-vault-review'); await pg.keyboard.press('e')
        await pg.wait_for_selector('.lee-vault-docview')
        return out
    got = _run(go, roots=[book_proj])
    assert got['before'] == '3' and 'page 2' in got['pages'] and 'the whole book' in got['pages']

def test_the_send_log_shows_what_a_hosted_reader_was_sent(book_proj):
    src = str((book_proj/'gita.pdf').resolve())
    async def go(pg):
        j = await pg.evaluate(JOB, ['/vault/book', {'src': src, 'model': 'vh'}])
        await pg.evaluate("() => leeVaultWorkbench('settings')")
        await pg.wait_for_selector('.lee-wb-settings')
        out = {'floor': await pg.input_value('[data-vault-floor]')}
        await pg.click('text=what left this machine')
        await pg.wait_for_selector('[data-vault-sends] tbody tr')
        out['row'] = await pg.inner_text('[data-vault-sends] tbody tr')
        await pg.click('[data-send-doc]')
        await pg.wait_for_selector('.lee-vault-docview [data-vault-sent-log]')
        await pg.click('[data-vault-sent-log]')
        await pg.wait_for_selector('[data-vault-sends] tbody tr')
        out['doc'] = await pg.inner_text('.lee-mhead')
        return out
    got = _run(go, roots=[book_proj])
    assert got['floor'] == 'open'
    assert 'gita' in got['row'] and 'vh' in got['row'] and '1, 2' in got['row']
    assert 'this document' in got['doc']

def test_a_local_only_attachment_turns_its_chip_red_and_the_turn_is_not_sent(tmp_path, monkeypatch):
    import sys
    from ramabana.core import ModelSpec
    from tests.fakemodel import install
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'vault.db'))
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    monkeypatch.setattr(sys.modules[__name__], 'fake_model',
                        lambda ws: install(ws, [], spec=ModelSpec('hosted-scripted', 'remote', 'scripted/model', ctx=8000)))
    (proj := tmp_path/'proj').mkdir()
    (proj/'contact.md').write_text('# Contact\n\nWrite to jane.doe@example.com about the lease.\n')
    async def go(pg):
        await pg.evaluate(JOB, ['/clip', {'target': str((proj/'contact.md').resolve()), 'kind': 'clip'}])
        doc = await pg.evaluate("() => fetch('/vault/documents').then(r => r.json()).then(d => d.documents[0])")
        await pg.evaluate("d => fetch('/vault/privacy', {method: 'POST', headers: {'Content-Type': 'application/json'},"
                          " body: JSON.stringify({doc: d.doc_id, shelf: d.shelf, level: 'local'})})", doc)
        await pg.evaluate("d => { leeRight('agent'); attachVaultRef({doc: d.doc_id, shelf: d.shelf, vault: '', title: 'contact'}); paintAgentAttachments(); }", doc)
        await pg.wait_for_selector('.lee-agent-attachment.blocked')
        out = {'line': await pg.inner_text('#agentsendline')}
        await pg.fill('#agentprompt', 'summarise it')
        await pg.evaluate('() => sendAgent()')
        await pg.wait_for_function("() => document.querySelector('#status')?.textContent.includes('Local only')")
        out['prompt'] = await pg.input_value('#agentprompt')
        out['cards'] = await pg.locator('#agentlog .lee-agent-turn').count()
        out['chip'] = await pg.get_attribute('.lee-agent-attachment.blocked', 'title')
        return out
    got = _run(go, roots=[proj])
    assert 'Local only' in got['line'] and 'Nothing was sent' in got['chip']
    assert got['prompt'] == 'summarise it' and got['cards'] == 0

def _bare_machine(monkeypatch, tmp_path):
    "No Claude Code, no Codex, no local backend, no key, and an empty alias file: a fresh Linux box under WSL."
    import ramabana.core as rc, leela.blocks.agent.models as lm
    monkeypatch.setattr(rc, 'runtime_available', lambda r: r == 'remote')
    monkeypatch.setattr(rc, '_claude_login', lambda: False)
    monkeypatch.setattr(rc, '_codex_login', lambda: False)
    monkeypatch.setattr(lm, 'leela_cfg', tmp_path)
    lm.forget_probes(disk=True)

OPEN_SETTINGS = """async () => {
  leeRight('agent');
  const d = document.querySelector('.lee-agent-settings'); d.querySelector(':scope > summary').click();
  await new Promise(r => setTimeout(r, 100));
  const pop = d.querySelector('.lee-routing-popover'), r = pop.getBoundingClientRect();
  pop.scrollTop = 0;
  const first = document.querySelector('#inlinemodel').closest('label').getBoundingClientRect();
  const hit = document.elementFromPoint(first.left + first.width / 2, first.top + first.height / 2);
  return {open: d.open, top: r.top, bottom: r.bottom, vh: innerHeight, first: first.top, hit: pop.contains(hit)};
}"""

def test_model_settings_open_from_every_route_on_a_machine_with_nothing_set_up(monkeypatch, tmp_path):
    "Short window, nothing installed, no key: settings, + model, the picker and the palette all open, and an Azure model can be added."
    _bare_machine(monkeypatch, tmp_path)
    async def go(pg):
        await pg.set_viewport_size({'width': 1280, 'height': 600})
        await pg.click('#agentchip > summary')   # the model picker lives in the chip's panel
        await pg.wait_for_selector('[data-model-pick="agentmodel"]')
        out = {'settings': await pg.evaluate(OPEN_SETTINGS)}
        await pg.click('.lee-routing-popover button:has-text("+ model")')
        await pg.wait_for_selector('.lee-modal #modelalias')
        await pg.wait_for_selector('.lee-modal [data-model-state]:not(:empty)')
        out['state'] = await pg.inner_text('.lee-modal [data-model-state]')
        out['runtimes'] = await pg.eval_on_selector_all('#modelruntime option:not([disabled])', 'os => os.map(o => o.value)')
        await pg.fill('#modelalias', 'Azure GPT'); await pg.fill('#modelid', 'gpt-4.1')
        await pg.click('#modelsave')
        await pg.wait_for_function("() => document.querySelector('.lee-modal [data-model-state]')?.classList.contains('warn')")
        out['refused'] = await pg.inner_text('.lee-modal [data-model-state]')
        await pg.select_option('#modelprovider', 'bedrock')   # a provider fills the hosted fields and chooses no model
        out['bedrock'] = await pg.evaluate("() => [modelkeyenv.value, modelapi.value, modelbase.placeholder, modelruntime.value, document.querySelector('.lee-modal details').open, modelid.value]")
        await pg.select_option('#modelprovider', 'azure')
        await pg.fill('#modelalias', 'azure-gpt')
        await pg.select_option('#modelruntime', 'remote')
        await pg.fill('#modelbase', 'https://myres.openai.azure.com/openai/v1')
        await pg.fill('#modelkeyenv', 'AZURE_OPENAI_API_KEY')
        await pg.fill('#modelvendor', 'openai'); await pg.fill('#modelapi', 'openai')
        await pg.click('#modelsave')
        await pg.wait_for_function("() => !document.querySelector('#modelalias') && document.querySelector('#agentmodel option[value=\"azure-gpt\"]')")
        await pg.click('[data-model-pick="agentmodel"]')
        await pg.wait_for_selector('.lee-model-menu')
        out['picker'] = await pg.eval_on_selector_all('.lee-model-row', 'bs => bs.map(b => b.dataset.value)')
        await pg.keyboard.press('Escape')
        await pg.evaluate("() => leeAct('setup_models')")
        await pg.wait_for_selector('.lee-setup-modal .lee-mhead')
        out['setup'] = await pg.inner_text('.lee-setup-modal .lee-mhead')
        await pg.click('#setupadd')
        await pg.wait_for_function("() => document.querySelectorAll('.lee-modal').length === 2 && !document.querySelector('.lee-modal #savedmodels').textContent.includes('loading')")
        out['saved'] = await pg.inner_text('.lee-modal #savedmodels')
        return out
    got = _run(go, real_models=True)
    s = got['settings']
    assert s['open'] and s['top'] >= 0 and s['bottom'] <= s['vh'] and s['first'] >= 0 and s['hit']
    assert 'no model is set up here' in got['state']
    assert 'name must use letters' in got['refused']
    assert got['runtimes'] == ['remote']
    assert got['bedrock'] == ['AWS_BEARER_TOKEN_BEDROCK', 'openai', 'https://bedrock-mantle.us-east-1.api.aws/v1', 'remote', True, 'gpt-4.1'], got['bedrock']
    assert 'azure-gpt' in got['picker']
    assert 'Set up a model' in got['setup'] and 'azure-gpt' in got['saved']

@pytest.mark.parametrize('fault', ['500', 'notok', 'slow'])
def test_add_model_opens_at_once_whatever_the_model_list_does(fault):
    "A model list that fails or never answers used to leave `+ model` drawing nothing at all."
    held = []
    async def go(pg):
        async def handle(route):
            if fault == '500': await route.fulfill(status=500, body='Internal Server Error')
            elif fault == 'notok': await route.fulfill(status=200, content_type='application/json',
                                                       body='{"ok": false, "error": "Internal Server Error", "runtimes": []}')
            else: held.append(route)   # never answered
        await pg.route('**/agent/models*', handle)
        await pg.evaluate("() => { leeAddModel(); }")
        await pg.wait_for_selector('.lee-modal #modelalias', timeout=2000)
        out = {'runtimes': await pg.eval_on_selector_all('#modelruntime option:not([disabled])', 'os => os.map(o => o.value)')}
        if fault != 'slow':
            await pg.wait_for_function("() => document.querySelector('.lee-modal [data-model-state]')?.textContent.includes('Internal Server Error')")
            # As at a boot whose model list failed: the select never got its picker.
            await pg.evaluate("() => { document.querySelector('[data-model-pick=\"agentmodel\"]').remove(); delete document.querySelector('#agentmodel').dataset.leePicked; leeLoadModels(); }")
            await pg.wait_for_function("() => document.querySelector('#status')?.textContent.includes('Internal Server Error')")
            out['picker'] = await pg.locator('[data-model-pick="agentmodel"]').count()
        out['state'] = await pg.inner_text('.lee-modal [data-model-state]')
        return out
    got = _run(go)
    assert got['runtimes'] == ['remote']
    if fault != 'slow': assert 'Internal Server Error' in got['state'] and got['picker'] == 1
    else: assert 'loading' in got['state']


def test_the_palette_opens_the_sub_agent_and_tool_call_controls_in_settings(tmp_path):
    """Sub-agent model, effort and tool calls, and the turn's tool calls, each have a palette row that opens settings on its control, and a change there is the server's."""
    rows = "() => [...document.querySelectorAll('#cplist .lee-mrow')].map(r => r.textContent)"
    async def pick(pg, q):
        await pg.keyboard.press('ControlOrMeta+Shift+P')
        await pg.wait_for_selector('#cp', timeout=3000)
        await pg.fill('#cp', q)
        await pg.press('#cp', 'Enter')
        await pg.wait_for_function("() => document.querySelector('.lee-agent-settings')?.open && !document.querySelector('#cp')", timeout=3000)
        return await pg.evaluate("() => document.activeElement?.id || document.activeElement?.dataset?.modelPick")
    async def go(pg):
        await pg.wait_for_selector('#subeffort', state='attached')
        await pg.keyboard.press('ControlOrMeta+Shift+P')
        await pg.wait_for_selector('#cp', timeout=3000)
        await pg.fill('#cp', 'Agent: ')
        listed = await pg.evaluate(rows)
        await pg.keyboard.press('Escape')
        out = {'listed': listed, 'effort': await pick(pg, 'sub-agent effort')}
        await pg.select_option('#subeffort', 'xhigh')
        await pg.wait_for_function("async () => (await (await fetch('/agent/subagent-settings')).json()).effort === 'xhigh'", timeout=5000)
        out['tools'] = await pick(pg, 'Agent: tool calls native')
        await pg.select_option('#toolmode', 'text')
        await pg.wait_for_function("async () => (await (await fetch('/agent/tool-mode')).json()).tools === 'text'", timeout=5000)
        out['subtools'] = await pick(pg, 'sub-agent tool calls')
        out['reasoning'] = await pg.eval_on_selector_all('#agentreasoning option', 'os => os.map(o => o.value)')
        out['models'] = await pg.locator('#jobmodels [data-job="subagent"]').count()
        return out
    got = _run(go, roots=[tmp_path])
    for name in ('sub-agent model', 'sub-agent effort', 'sub-agent tool calls native or text', 'tool calls native or text'):
        assert any(r.startswith(f'Agent: {name}') for r in got['listed']), (name, got['listed'])
    assert (got['effort'], got['tools'], got['subtools']) == ('subeffort', 'toolmode', 'subtools')
    assert got['reasoning'] == ['auto', 'low', 'medium', 'high', 'xhigh', 'max']
    assert got['models'] == 1, 'the routed-jobs row is the sub-agent model control'


def test_a_refresh_that_changes_one_variable_leaves_an_expanded_row_open_and_filled(monkeypatch):
    """A poll that finds nothing new repaints nothing, and one that finds a sibling changed patches that row in place: the expanded row keeps its element and its children instead of emptying while they are fetched again."""
    tick = [0]
    def node(name, value, container=False):
        return {'name': name, 'type': 'Response' if container else 'int', 'value': value, 'shape': None,
                'is_container': container, 'is_grid': False, 'accessor': [name]}
    class K(FakeKernel):
        async def api(self, path, params=None, timeout=15):
            if path.endswith('/api/rows'):
                return {'groups': [{'label': '', 'nodes': [node('tick', str(tick[0])), node('res', '<Response [200 OK]>', True), node('x', '1')]}]}
            if path.endswith('/api/expand'):
                await asyncio.sleep(.2)
                return [dict(node(f'attr{i}', 'v'), accessor=['res', f'attr{i}']) for i in range(35)]
            return await super().api(path, params, timeout)
    monkeypatch.setitem(globals(), 'FakeKernel', K)
    watch = """() => {
      const box = document.querySelector('#vars'); window._m = {replaced: 0, emptied: 0};
      new MutationObserver(() => window._m.replaced++).observe(box, {childList: true});
      window._kids = document.querySelector('#vars .lee-vkids:not(:empty)');
      setInterval(() => { if (!window._kids.children.length) window._m.emptied++; }, 5);
    }"""
    async def go(pg):
        await pg.wait_for_selector('#vars .lee-vrow', state='attached')
        await pg.evaluate("() => { leePane('right', true); leeRight('vars'); }")
        await pg.evaluate("() => document.querySelector('#vars .lee-vrow[data-name=res]').click()")
        await pg.wait_for_selector('#vars .lee-vkids .lee-vrow')
        await pg.evaluate(watch)
        for _ in range(3): await pg.evaluate('() => leeVars()')
        idle = await pg.evaluate('() => window._m.replaced')
        tick[0] += 1
        await pg.evaluate('() => leeVars()')
        await pg.wait_for_function("() => document.querySelector('#vars .lee-vrow[data-name=tick] .lee-vval').textContent === '1'")
        await pg.wait_for_timeout(400)
        return {'idle': idle, 'm': await pg.evaluate('() => window._m'),
                'same': await pg.evaluate("() => window._kids === document.getElementById('k-' + encodeURIComponent(JSON.stringify(['res'])))"),
                'kids': await pg.evaluate("() => window._kids.querySelectorAll('.lee-vrow').length")}
    got = _run(go)
    assert got['idle'] == 0, 'an unchanged poll must not touch the panel'
    assert got['m']['emptied'] == 0, 'the expanded row emptied while its children were fetched again'
    assert got['same'] and got['kids'] == 35


def test_a_hand_off_to_a_heading_cell_brings_it_into_view(tmp_path):
    """abhyasa opens a notebook at `/?cell=N`, the heading of an idea. The cell is selected and in view: `jumpToLine` scrolls only a code cell, so a heading stayed off screen. An index past the end changes nothing."""
    import json
    from playwright.sync_api import sync_playwright
    md = lambda k: dict(cell_type='markdown', metadata={}, id=f'c{k}', source=f'## Part {k}\n\nSome words about part {k}.')
    code = lambda k: dict(cell_type='code', metadata={}, id=f'c{k}', source='x = 1\n' * 8, execution_count=1,   # a long warning, as torchvision gives, draws late
                          outputs=[dict(output_type='stream', name='stderr', text='UserWarning: the default value will change.\n' * 25)])
    nb = tmp_path/'lesson.ipynb'
    nb.write_text(json.dumps(dict(cells=[code(k) if k % 2 else md(k) for k in range(40)], metadata={}, nbformat=4, nbformat_minor=5)))
    ws = Workspace(roots=[tmp_path]); ws.open(nb)
    seen = ("i => { const h = document.getElementById('editor').getBoundingClientRect(), c = document.querySelector(`.lee-cell[data-i=\"${i}\"]`);"
            " if (!c) return false; const r = c.getBoundingClientRect(); return r.top >= h.top && r.top < h.bottom; }")
    with serve(ws) as url, sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        try:
            pg = b.new_page(viewport={'width': 1440, 'height': 900}); errs = []
            pg.on('pageerror', lambda e: errs.append(str(e)))
            pg.goto(f'{url}/?cell=30', wait_until='networkidle')
            pg.wait_for_function("() => document.querySelector('.lee-cell.sel')?.dataset.i === '30'", timeout=15000)
            pg.wait_for_function(seen, arg=30, timeout=5000)
            pg.goto(f'{url}/?cell=99', wait_until='networkidle'); pg.wait_for_timeout(500)
            assert not [e for e in errs if 'state' in e], errs
            # A disk reload at boot (`takeDiskVersion`) mounts the tab again while the first mount runs: the place stays.
            again = b.new_context(viewport={'width': 1440, 'height': 900})
            again.add_init_script("document.addEventListener('DOMContentLoaded', () => { const g = window.api; let n = 0;"   # the second mount starts while the first one waits for its drafts
                                  " window.api = function(u) { const r = g.apply(this, arguments); if (String(u).startsWith('/tab/state') && !n++) r.then(() => setTimeout(() => window.mountTab(), 0)); return r; }; });")
            p2 = again.new_page(); p2.goto(f'{url}/?cell=30', wait_until='networkidle')
            p2.wait_for_function("() => document.querySelector('.lee-cell.sel')?.dataset.i === '30'", timeout=15000)
            p2.wait_for_timeout(800)
            assert p2.evaluate(seen, 30)
        finally: b.close()
