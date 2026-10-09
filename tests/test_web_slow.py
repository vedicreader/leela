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
    async def _get(self, key, **kw): return self.kernels.setdefault(key, FakeKernel())
    KernelPool.get = _get
    KernelPool.peek = lambda self, key: self.kernels.get(key)
    KernelPool.close_all = lambda self: asyncio.sleep(0)

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

async def _launch(pw):
    "Chromium, or a skip. `LEELA_CHROMIUM` names the binary where playwright cannot find its own."
    kw = {'executable_path': CHROMIUM} if CHROMIUM else {}
    if _os.geteuid() == 0: kw['args'] = ['--no-sandbox']
    try: return await pw.chromium.launch(**kw)
    except Exception as e: pytest.skip(f'no chromium for playwright: {e}')

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

async def _on_page(fn, roots=(), dpr=None, real_models=False):
    """Boot the app, open it in chromium, hand the page to `fn`, and return what it returns."""
    fake_kernels()
    ws = Workspace(roots=list(roots), approvals='auto')
    if not real_models: fake_model(ws)
    port = _free_port()
    srv = _serve(ws, port)
    await _started(srv)
    try:
        async with async_playwright() as pw:
            b = await _launch(pw)
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

def _run(fn, roots=(), dpr=None, real_models=False):
    return asyncio.run(_on_page(fn, roots, dpr, real_models))


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
    assert (editor['moveUp']['ran'], editor['moveUp']['prevented'], editor['moveUp']['action']) == \
        (True, True, 'cell_move_up')
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
    fake_kernels()
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
    finally: srv.should_exit = True
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


def test_typing_in_a_code_brick_survives_the_insert_that_follows_it(tmp_path):
    """A `cvSync` keeps the element and hands it a new brick object, so a write to the captured one was gone at the next flush: the code you typed ran as an empty cell."""
    doc = tmp_path/'t.canvas.md'
    doc.write_text('---\ntitle: t\n---\n# T\n\nA paragraph to hang a gutter on.\n', encoding='utf-8')
    async def go(pg):
        await pg.goto(f'{pg.url.rstrip("/")}/canvas?path={doc}', wait_until='networkidle')
        await pg.wait_for_function('typeof cv != "undefined" && !!cv.canvas')
        a = pg.locator('.cv-brick').last
        await a.hover(); await a.locator('.cv-gadd').click()
        await pg.wait_for_selector('.cv-item')
        await pg.keyboard.type('code'); await pg.keyboard.press('Enter')
        await pg.wait_for_selector('.cv-brick[data-kind=code] textarea')
        await pg.keyboard.type('x = 41 + 1')
        code = pg.locator('.cv-brick[data-kind=code]').first
        await code.hover(); await code.locator('.cv-gadd').click()      # the op that flushes
        await pg.wait_for_selector('.cv-item')
        await pg.keyboard.press('Escape')
        return await pg.evaluate("() => cv.canvas.bricks.filter(b => b.kind == 'code').map(b => b.body)")
    assert _run(go, roots=[str(tmp_path)]) == ['x = 41 + 1']


CANVAS_WITH_TABLE = '''---
title: t
---
# T

| word | means |
|---|---|
| brick | one part of the document |
| prose | ordinary markdown between bricks |

A paragraph after the table.

```canvas code id=c1
total = 6 * 7
```
'''

def test_opening_a_canvas_runs_nothing_until_it_is_trusted(tmp_path):
    """A canvas is markdown, so it arrives from a clone or a paste."""
    doc = tmp_path/'t.canvas.md'
    doc.write_text(CANVAS_WITH_TABLE, encoding='utf-8')
    async def go(pg):
        await pg.goto(f'{pg.url.rstrip("/")}/canvas?path={doc}', wait_until='networkidle')
        await pg.wait_for_function('typeof cv != "undefined" && !!cv.canvas')
        before = await pg.evaluate('''() => ({trusted: cv.trusted, names: cv.names.length,
                                             bar: !$$("#cv-trust").hidden,
                                             says: $$("#cv-trust-count").textContent})''')
        await pg.locator('#cv-trust-run').click()
        await pg.wait_for_function('() => cv.trusted === true')
        after = await pg.evaluate('() => ({trusted: cv.trusted, hidden: $$("#cv-trust").hidden})')
        return before, after
    #: The kernels are fakes here, so nothing the cell defines comes back. What this holds is the
    #: gate: untrusted on open, one click to trust, and the bar gone after it.
    before, after = _run(go, roots=[str(tmp_path)])
    assert before == {'trusted': False, 'names': 0, 'bar': True, 'says': '1'}
    assert after == {'trusted': True, 'hidden': True}

def test_prose_nobody_edited_is_not_rewritten_by_a_blur(tmp_path):
    """Blur converted the rendered DOM back to markdown every time, and `cvMd` cannot draw a table, so focusing a table and leaving it flattened the table into its own text."""
    doc = tmp_path/'t.canvas.md'
    doc.write_text(CANVAS_WITH_TABLE, encoding='utf-8')
    async def go(pg):
        await pg.goto(f'{pg.url.rstrip("/")}/canvas?path={doc}', wait_until='networkidle')
        await pg.wait_for_function('typeof cv != "undefined" && !!cv.canvas')
        table = pg.locator('.cv-brick[data-kind=text]').first
        await table.click()                       # focus it, change nothing
        await pg.locator('#cv-doc').click()       # and blur it
        await pg.wait_for_timeout(300)
        await pg.evaluate('() => cvSave()')
        await pg.wait_for_function('() => cv.dirty === false')
        return None
    _run(go, roots=[str(tmp_path)])
    kept = doc.read_text(encoding='utf-8')
    assert '| word | means |' in kept and '|---|---|' in kept, kept
    assert '| brick | one part of the document |' in kept

def test_a_save_and_a_blur_do_not_race_each_other(tmp_path):
    "Clicking Save blurs the brick being edited, and the blur used to post alongside the save."
    doc = tmp_path/'t.canvas.md'
    doc.write_text('---\ntitle: t\n---\n# T\n\noriginal words here.\n', encoding='utf-8')
    async def go(pg):
        await pg.goto(f'{pg.url.rstrip("/")}/canvas?path={doc}', wait_until='networkidle')
        await pg.wait_for_function('typeof cv != "undefined" && !!cv.canvas')
        para = pg.locator('.cv-brick[data-kind=text] .cv-prose').last
        await para.click()
        await pg.keyboard.press('End')
        await pg.keyboard.type(' plus an edit')
        await pg.locator('#cv-save').click()       # blurs the paragraph as it saves
        await pg.wait_for_function('() => cv.dirty === false')
        return None
    _run(go, roots=[str(tmp_path)])
    kept = doc.read_text(encoding='utf-8')
    assert 'plus an edit' in kept, kept
