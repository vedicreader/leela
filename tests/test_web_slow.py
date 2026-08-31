"The web IDE in a browser: keys, themes, the vault reader and interventions."

import pytest

pytestmark = pytest.mark.slow

import asyncio
import os as _os
from pathlib import Path
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

PARENT = Path(__file__).parent
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

async def _on_page(fn, roots=(), dpr=None):
    "Boot the app, open it in chromium, hand the page to `fn`, and return what it returns."
    fake_kernels()
    ws = Workspace(roots=list(roots), approvals='auto')
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

def _run(fn, roots=(), dpr=None): return asyncio.run(_on_page(fn, roots, dpr))

def test_a_standalone_code_surface_lints_finds_navigates_and_fits_its_own_text():
    """Every editor Leela mounts outside a tab, in one page session: the lint squiggles, the sticky
    gutter, mod-click to a definition, the dotted chain under the cursor, the snippet box a rendered
    code fence gets, and find over the whole document rather than the visible lines. Each step drops
    its host again, so the next one is not clicking through the last one's fixed overlay.
    """
    async def go(pg):
        out = {}
        await pg.evaluate("""() => {
          const host = document.createElement('div'); host.id = 'lint-test';
          host.style.height = '120px'; document.body.appendChild(host);
          window._lintTestView = LeeCM.create(host, {doc: 'if True print(1)', lang: 'python'});
        }""")
        await pg.wait_for_selector('#lint-test .cm-lintRange-error')
        await pg.evaluate("LeeCM.setDoc(window._lintTestView, 'value is 1')")
        await pg.wait_for_selector('#lint-test .cm-lintRange-warning')
        out['warnings'] = await pg.locator('#lint-test .cm-lintRange-warning').count()
        await pg.evaluate("() => document.getElementById('lint-test').remove()")

        out['gutters'] = await pg.evaluate("""() => {
          const make = (id, merge = false) => {
            const host = document.createElement('div'); host.id = id; host.style.cssText = 'width:320px;height:120px;overflow:auto'; document.body.appendChild(host);
            const doc = 'value = ' + 'x'.repeat(500);
            if (merge) LeeCM.createMerge(host, {left:doc, right:doc, settings:{wordWrap:'off'}}); else LeeCM.create(host, {doc, lineNums:true, settings:{wordWrap:'off'}});
            const rows = [...host.querySelectorAll('.cm-editor')].map(editor => {
              const inner = editor.querySelector('.cm-scroller'), gutter = editor.querySelector('.cm-gutters');
              editor.querySelector('.cm-content').style.minWidth = '1200px';
              const scroller = inner; scroller.scrollLeft = 240;
              const before = scroller.getBoundingClientRect(), after = gutter.getBoundingClientRect(), style = getComputedStyle(gutter);
              return {delta: Math.round(after.left - before.left), background: style.backgroundColor, position: style.position, left: style.left};
            });
            host.remove();
            return rows;
          };
          return [...make('gutter-test'), ...make('merge-gutter-test', true)];
        }""")

        out['definition'] = await pg.evaluate("""() => {
          const host=document.createElement('div');host.id='definition-test';host.style.height='100px';
          document.body.appendChild(host);window._definition='';
          const v=LeeCM.create(host,{doc:'target_name = 1',lang:'python',
            onDefinition:name=>window._definition=name});
          const r=v.coordsAtPos(4);
          v.contentDOM.dispatchEvent(new MouseEvent('mousedown',{
            clientX:r.left+1,clientY:(r.top+r.bottom)/2,metaKey:MAC,ctrlKey:!MAC,
            button:0,bubbles:true,cancelable:true}));
          host.remove();
          return window._definition;
        }""")

        out['dotted'] = await pg.evaluate("""() => {
          const host = document.createElement('div'); host.id = 'dotted-test';
          host.style.height = '100px'; document.body.appendChild(host);
          const v = LeeCM.create(host, {doc: 'from nbdev.showdoc import show_doc\\nfastcore.test.test_eq(a.b().c)\\n', lang: 'python'});
          const at = n => { LeeCM.setCursor(v, n); return dottedAtCursor(v); };
          const line2 = v.state.doc.line(2).from, text = v.state.doc.line(2).text;
          const got = {
            showdoc: at(v.state.doc.line(1).text.indexOf('showdoc') + 2),
            nbdev: at(v.state.doc.line(1).text.indexOf('nbdev') + 2),
            imported: at(v.state.doc.line(1).text.indexOf('show_doc') + 2),
            sub: at(line2 + text.indexOf('test.') + 1),
            leaf: at(line2 + text.indexOf('test_eq') + 1),
            root: at(line2 + 1),
            call: at(line2 + text.indexOf('c)') + 1)
          };
          host.remove();
          return got;
        }""")

        await pg.evaluate("""() => {
          const host = document.createElement('div');
          host.id = 'md-code-test';
          host.style.cssText = 'position:fixed;inset:40px 20px auto 20px;width:600px';
          document.body.appendChild(host);
          for (const n of [1, 3, 6, 12])
            mountCodeSurface(host, Array.from({length: n}, (_, i) => `x${i} = ${i}`).join('\\n'), 'python');
        }""")
        await pg.wait_for_selector('#md-code-test .lee-code-editor .cm-editor')
        await pg.wait_for_timeout(400)
        out['blocks'] = await pg.evaluate("""() => {
            const rows = [...document.querySelectorAll('#md-code-test .lee-code-editor')]
              .map(el => {
                const s = el.querySelector('.cm-scroller');
                return {lines: el.querySelectorAll('.cm-line').length,
                        over: s.scrollHeight - s.clientHeight,
                        stripe: !!el.querySelector('.cm-lee-overview'),
                        marked: el.classList.contains('has-overview') ||
                                !!el.querySelector('.has-overview')};
              });
            document.getElementById('md-code-test').remove();
            return rows;
          }""")

        out['snippet'] = await pg.evaluate("""() => {
          const s = getComputedStyle(document.documentElement);
          const size = parseFloat(s.getPropertyValue('--lee-code-size'));
          const ratio = parseFloat(s.getPropertyValue('--lee-code-line-height'));
          const host = document.createElement('div');
          host.style.cssText = 'position:fixed;inset:40px 20px auto 20px;width:600px';
          document.body.appendChild(host);
          mountCodeSurface(host, Array.from({length: 12}, (_, i) => `x${i} = ${i}`).join('\\n'), 'python');
          const line = host.querySelector('.cm-line');
          const got = {size, ratio, drawn: line.getBoundingClientRect().height,
                  assumed: 19, over: (() => {
                    const sc = host.querySelector('.cm-scroller');
                    return sc.scrollHeight - sc.clientHeight;
                  })()};
          host.remove();
          return got;
        }""")

        await pg.evaluate("""() => {
          const host = document.createElement('div'); host.id = 'search-test';
          host.style.cssText = 'height:120px;position:fixed;inset:80px 20px auto 20px'; document.body.appendChild(host);
          const lines = Array.from({length: 400}, (_, i) => i === 350 ? 'whole-file-target' : `line ${i}`);
          window._searchTestView = LeeCM.create(host, {doc: lines.join('\\n'), lang: 'python', lineNums: true});
          LeeCM.focus(window._searchTestView);
        }""")
        out['claimed'] = await pg.evaluate("""() => {
          const event = new KeyboardEvent('keydown', {key:'f', code:'KeyF', metaKey:MAC, ctrlKey:!MAC,
            bubbles:true, cancelable:true});
          document.activeElement.dispatchEvent(event); return event.defaultPrevented;
        }""")
        await pg.wait_for_selector('#search-test .cm-search input[main-field]')
        search = pg.locator('#search-test .cm-search input[main-field]')
        await search.fill('whole-file-target')
        await search.dispatch_event('change')
        await search.press('Enter')
        out['found'] = await pg.evaluate("""() => ({
          selection: LeeCM.selection(window._searchTestView).text,
          top: document.querySelector('#search-test .cm-scroller').scrollTop,
          doc: LeeCM.getDoc(window._searchTestView)
        })""")
        await search.fill('missing-target')
        await search.dispatch_event('change')
        await search.press('Enter')
        out['unchanged'] = await pg.evaluate('LeeCM.getDoc(window._searchTestView)')
        await search.press('Escape')
        out['closed'] = await pg.locator('#search-test .cm-search').count()
        out['merge'] = await pg.evaluate("""() => {
          const host = document.createElement('div'); host.id = 'merge-search-test'; host.style.height = '120px';
          document.body.appendChild(host); window._mergeSearch = LeeCM.createMerge(host, {left:'left target', right:'right target'});
          const editor = host.querySelector('.cm-editor'); editor.querySelector('.cm-content').focus();
          const event = new KeyboardEvent('keydown', {key:'f', code:'KeyF', metaKey:MAC, ctrlKey:!MAC,
            bubbles:true, cancelable:true}); editor.querySelector('.cm-content').dispatchEvent(event);
          return event.defaultPrevented;
        }""")
        await pg.wait_for_selector('#merge-search-test .cm-search input[main-field]')
        return out
    got = _run(go)
    assert got['warnings'] >= 1

    rows = got['gutters']
    assert len(rows) == 3 and all(row['position'] == 'sticky' and row['left'] == '0px' and abs(row['delta']) <= 1 for row in rows)
    assert all(row['background'] not in ('rgba(0, 0, 0, 0)', 'transparent') for row in rows)

    assert got['definition'] == 'target_name'

    dotted = got['dotted']
    assert dotted['showdoc'] == 'nbdev.showdoc' and dotted['nbdev'] == 'nbdev', 'leftwards only'
    assert dotted['imported'] == 'show_doc', 'the name being imported has no chain of its own'
    assert dotted['sub'] == 'fastcore.test' and dotted['leaf'] == 'fastcore.test.test_eq'
    assert dotted['root'] == 'fastcore'
    assert dotted['call'] == 'c', 'a call is not a module, so the chain stops at the bracket'

    assert len(got['blocks']) == 4
    for b in got['blocks']:
        assert b['over'] <= 0, f"a {b['lines']}-line block overflows by {b['over']}px, so it draws a bar"
        assert not b['stripe'], 'a read-only snippet gets no overview stripe'
        assert not b['marked'], 'and nothing hides a bar on it'

    d = got['snippet']
    assert d['size'] * d['ratio'] != d['assumed'], \
        f"a line is {d['size']}x{d['ratio']}={d['size'] * d['ratio']}px, which the old box called 19"
    assert d['drawn'] > d['assumed'], f"a drawn line is {d['drawn']}px, taller than the 19 assumed"
    assert d['over'] <= 0, f'and the box no longer overflows by {d["over"]}px'

    assert got['claimed'] and got['merge'] and got['found']['selection'] == 'whole-file-target'
    assert got['unchanged'] == got['found']['doc'] and got['closed'] == 0

def test_tab_takes_the_completion_that_is_on_screen():
    """Tab accepted a ghost suggestion and otherwise indented, and `completionKeymap` does not bind
    Tab at all, so an open completion list was indented past rather than accepted. Every editor
    people arrive from accepts it with Tab, and indenting is what Tab does when nothing is offered.
    """
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

def test_changing_a_routed_job_model_saves_it_and_a_refusal_says_so():
    """Changing the subagent model did nothing and said nothing. The routed jobs are rows this file
    draws, with no id of their own, and `paintModelPickers` built `'#' + ''` for each -- a
    SyntaxError, not a selector. It took `loadAgentModels` down, and `leeAgentModel` reloaded the
    panel before reporting, so the reload's failure threw the refusal away before anyone saw it.
    """
    async def go(pg):
        errors = []
        pg.on('pageerror', lambda e: errors.append(str(e)))
        await pg.evaluate("() => leeLoadModels()")
        await pg.wait_for_selector('#jobmodels [data-job="subagent"]', state='attached')
        picked = await pg.evaluate("""async () => {
          const sel = document.querySelector('#jobmodels [data-job="subagent"]');
          const before = sel.value;
          const other = [...sel.options].map(o => o.value).find(v => v !== before);
          sel.previousElementSibling.click();                       // the picker the person clicks
          await new Promise(r => setTimeout(r, 150));
          const row = [...document.querySelectorAll('.lee-model-menu [data-value]')]
                        .find(r => r.dataset.value === other);
          row.click();
          await new Promise(r => setTimeout(r, 400));
          return {before, other, value: sel.value, label: sel.previousElementSibling.textContent};
        }""")
        refused = await pg.evaluate("""async () => {
          await window.leeAgentModel('subagent', 'no-such-model-anywhere');
          return document.querySelector('#status')?.textContent || '';
        }""")
        return {'picked': picked, 'refused': refused, 'errors': errors}
    out = _run(go)
    assert out['errors'] == [], out['errors']
    assert out['picked']['value'] == out['picked']['other'], 'the choice lands on the select'
    assert out['picked']['other'].split(' ')[0] in out['picked']['label'], 'and the picker says so'
    assert 'no-such-model-anywhere' in out['refused'], f"a refusal is reported: {out['refused']!r}"

def test_the_modals_the_editor_opens_own_their_focus_and_their_controls():
    """One page for every overlay a person reaches from the editing surface: the kernel picker traps
    focus and answers the arrows, the platform preferences chord opens settings from a focused cell,
    the bundled code fonts load and their ligatures reach CodeMirror, completion opens on the real
    extension rather than only the endpoint, help on a selection is previewed before it replaces
    anything, and opening a folder is an in-app browser rather than a native prompt.
    """
    async def go(pg):
        out = {}
        await pg.evaluate("leeAct('pick_kernel')")
        await pg.wait_for_selector('.lee-modalbox[role="dialog"]')
        out['first'] = await pg.evaluate("document.activeElement?.classList.contains('lee-mrow')")
        out['before'] = await pg.evaluate("document.activeElement?.textContent")
        await pg.keyboard.press('ArrowDown')
        out['after'] = await pg.evaluate("document.activeElement?.textContent")
        await pg.keyboard.press('Tab')
        out['trapped'] = await pg.evaluate("!!document.activeElement?.closest('.lee-modalbox')")
        await pg.keyboard.press('Escape')
        await pg.wait_for_selector('.lee-modalbox[role="dialog"]', state='detached')

        await pg.evaluate("leeAct('focus_editor')")
        await pg.evaluate("""() => {
          const e = new KeyboardEvent('keydown', {key:',', code:'Comma',
            metaKey: MAC, ctrlKey: !MAC, bubbles:true, cancelable:true});
          (document.activeElement || document.body).dispatchEvent(e);
        }""")
        await pg.wait_for_selector('.lee-settings-modal .lee-modalbox')
        out['fontControl'] = await pg.locator('[data-pref="fontFamily"]').evaluate('el => el.tagName')

        await pg.wait_for_selector('.lee-settings-modal #settingspreview .cm-content')
        await pg.select_option('[data-pref="fontFamily"]', 'Fira Code')
        await pg.uncheck('[data-pref="ligatures"]')
        out['disabled'] = await pg.evaluate("getComputedStyle(document.querySelector('#settingspreview .cm-content')).fontFeatureSettings")
        await pg.check('[data-pref="ligatures"]')
        out['font'] = await pg.evaluate("""async () => {
          await document.fonts.ready;
          const style=getComputedStyle(document.querySelector('#settingspreview .cm-content'));
          return {loaded:document.fonts.check('13px "Fira Code"'),family:style.fontFamily,
            features:style.fontFeatureSettings};
        }""")
        await pg.click('.lee-settings-modal [data-cancel]')
        await pg.wait_for_selector('.lee-settings-modal', state='detached')

        await pg.evaluate("leeAct('focus_exec')")
        await pg.keyboard.type('d')
        await pg.keyboard.press('Alt+/')
        await pg.wait_for_selector('.cm-tooltip-autocomplete')
        out['completion'] = await pg.locator('.cm-tooltip-autocomplete').inner_text()

        await pg.route('**/complete/selection', lambda route: route.fulfill(
            status=200, content_type='application/json',
            body='{"ok":true,"text":"concise replacement","mode":"summary","model":"local-summary"}'))
        await pg.evaluate("leeAct('new_notebook')")
        await pg.wait_for_selector('.lee-cell .cm-editor')
        await pg.evaluate("""() => {
          const view = lee.editors.get(lee.cells[0].id);
          LeeCM.setDoc(view, 'This is a long selected passage.');
          LeeCM.setSelection(view, 0, LeeCM.getDoc(view).length);
          showSelectionHelp();
        }""")
        await pg.wait_for_selector('.lee-selection-tools')
        await pg.click('[data-summary]')
        await pg.wait_for_selector('.lee-selection-reply:not(.loading)')
        out['helpBefore'] = await pg.evaluate("LeeCM.getDoc(lee.editors.get(lee.cells[0].id))")
        out['suggestion'] = await pg.locator('.lee-selection-reply pre').inner_text()
        await pg.click('[data-replace]')
        out['helpAfter'] = await pg.evaluate("LeeCM.getDoc(lee.editors.get(lee.cells[0].id))")

        await pg.evaluate("leeAct('add_root')")
        await pg.wait_for_selector('.lee-folderlist')
        await pg.wait_for_function("document.querySelector('#folderpath').value.length > 0")
        out['folderPath'] = await pg.input_value('#folderpath')
        out['folderRows'] = await pg.locator('.lee-folderrow').count()
        return out
    got = _run(go)
    assert got['first'] and got['before'] != got['after'] and got['trapped']
    assert got['fontControl'] == 'SELECT'
    assert 'liga' in got['disabled'] and (' 0' in got['disabled'] or 'off' in got['disabled'])
    assert got['font']['loaded'] and 'Fira Code' in got['font']['family']
    assert 'liga' in got['font']['features'] and 'calt' in got['font']['features']
    assert got['font']['features'] != got['disabled']
    assert 'df' in got['completion'] and 'df_norm' in got['completion']
    assert got['helpBefore'] == 'This is a long selected passage.'
    assert got['suggestion'] == 'concise replacement'
    assert got['helpAfter'] == 'concise replacement'
    assert got['folderPath'].startswith('/') and got['folderRows'] >= 0

def test_the_keymap_answers_every_chord_it_claims_in_one_browser_session():
    """One page for the whole keymap, because booting one per chord is the cost of this file.

    A keymap edit left a bare letter silently unbound, a hyper default matched no event the browser
    actually sends, the text-field guard swallowed shift+enter in the editing panes, Cmd+R stopped
    being Chrome's reload, and the contextual panel grew into a copy of the full overlay.
    """
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

def test_the_right_panels_filter_search_look_up_and_remember():
    """One page for the panels beside the editor: the variable filter takes what is typed, research
    lists the commands it runs, an expandable result opens in a floating lens under the expression
    that made it, unified search previews highlighted code and hands a location back on a click,
    the tree's own menu discovers the actions and their chords, and durable memory reads its shelf
    and offers to purge it.
    """
    async def go(pg):
        out = {}
        await pg.click('#filetree', button='right')
        await pg.wait_for_selector('.lee-ctxmenu')
        out['ctxmenu'] = await pg.locator('.lee-ctxmenu').inner_text()
        await pg.evaluate('closeMenu()')
        await pg.wait_for_selector('.lee-ctxmenu', state='detached')

        await pg.evaluate("leeAct('focus_vars')")
        await pg.type('#varfilter', 'og/123')
        out['filter'] = await pg.input_value('#varfilter')

        await pg.evaluate("leeAct('research')")
        await pg.wait_for_selector('.lee-research-body')
        out['research'] = await pg.locator('.lee-research-command').inner_text()
        await pg.keyboard.press('Escape')
        await pg.wait_for_selector('.lee-research-body', state='detached')

        await pg.evaluate("""() => openValueLens({name:'result', type:'list', value:"[{'path': '/tmp/a'}]",
          is_container:true, accessor:['_']}, document.querySelector('#kpill'), "_hits[0]['path']")""")
        await pg.wait_for_selector('.lee-value-lens')
        out['lensRows'] = await pg.locator('.lee-value-row').count()
        await pg.click('.lee-value-row')
        await pg.wait_for_function("document.querySelector('.lee-value-kids')?.textContent.includes('no children')")
        out['lensHead'] = await pg.locator('.lee-inline-head').inner_text()
        await pg.evaluate("() => document.querySelector('.lee-value-lens')?.remove()")

        await pg.route('**/code/status', lambda route: route.fulfill(status=200, content_type='application/json',
          body='{"ok":true,"files":274,"packages":152,"graph_nodes":8088,"stale_files":0}'))
        await pg.route('**/search/stream?*', lambda route: route.fulfill(
            status=200, content_type='text/event-stream', body=_SEARCH_STREAM))
        await pg.evaluate("leeAct('code_search')")
        await pg.fill('#cs', 'runtime_engine')
        await pg.wait_for_selector('.lee-search-result')
        await pg.wait_for_selector('.lee-search-preview .cm-editor')
        out['modes'] = await pg.locator('.lee-searchrail').inner_text()
        out['preview'] = await pg.locator('.lee-search-preview').inner_text()
        out['scopeNote'] = await pg.locator('#csscopenote').inner_text()
        out['searchRows'] = await pg.locator('.lee-search-result').count()
        await pg.click('.lee-search-result')
        out['location'] = await pg.evaluate('lee.pendingLocation')
        out['searchOpen'] = await pg.locator('.lee-code-search-modal').count()

        one = lambda route: route.fulfill(status=200, content_type='application/json', body='''{
          "path":"/tmp/memory.db","documents":1,"nodes":3,"chunks":4,"note":"ready",
          "items":[{"id":"abc","title":"Agent memory","source":"https://example.com","kind":"page","pages":1,"meta":{}}]
        }''')
        await pg.route('**/memory/info', one)
        await pg.click('[data-right="memory"]')
        await pg.click('[data-memory-view="sources"]')
        await pg.wait_for_selector('.lee-memory-doc')
        out['memoryStatus'] = await pg.locator('#memorystatus').inner_text()
        out['memoryBody'] = await pg.locator('#memorybody').inner_text()

        # a shelf with something worth dropping on it, which is a different answer from the server
        await pg.unroute('**/memory/info', one)
        await pg.route('**/memory/info', lambda route: route.fulfill(status=200, content_type='application/json', body='''{
          "path":"/tmp/memory.db","documents":2,"nodes":5,"chunks":8,"note":"ready","items":[
            {"id":"bad","title":"Bad result","source":"https://bad.example","kind":"page","pages":1,"meta":{}},
            {"id":"good","title":"Useful result","source":"https://good.example","kind":"page","pages":1,"meta":{}}
          ]}'''))
        await pg.evaluate('leeMemoryHome()')
        await pg.wait_for_function("document.querySelectorAll('.lee-memory-doc').length === 2")
        await pg.click('.lee-memory-nav .warn')
        await pg.wait_for_selector('.lee-memory-purge-list')
        out['purgeRows'] = await pg.locator('.lee-memory-purge-list').inner_text()
        out['purgeAll'] = await pg.locator('[data-all]').inner_text()
        return out
    got = _run(go)
    assert 'open file' in got['ctxmenu'] and ('⌘p' in got['ctxmenu'] or 'ctrl+p' in got['ctxmenu'])
    assert 'new file' in got['ctxmenu'] and '\nn\n' in '\n' + got['ctxmenu'] + '\n'
    assert 'open folder' in got['ctxmenu']
    assert got['filter'] == 'og/123'
    assert 'Search' in got['research'] and 'Read URL' in got['research'] and 'Research' in got['research']
    assert got['lensRows'] == 1
    assert "_hits[0]['path']" in got['lensHead']
    assert got['modes'].splitlines()[:2] == ['all', '1']
    assert got['searchRows'] == 1
    assert 'runtime_engine' in got['preview'] and 'symbols + rg' in got['preview']
    assert got['scopeNote'] == 'searched proj'
    assert (got['location']['path'], got['location']['line']) == ('/tmp/engine.py', 17)
    assert got['searchOpen'] == 0
    assert '1 docs' in got['memoryStatus'] and '3 sections' in got['memoryStatus']
    assert 'Agent memory' in got['memoryBody'] and 'example.com' in got['memoryBody']
    assert 'Bad result' in got['purgeRows'] and 'Useful result' in got['purgeRows']
    assert got['purgeAll'] == 'purge everything'

def test_the_agent_routes_are_served_and_a_result_is_an_inline_value():
    outputs = [{'output_type': 'execute_result', 'data': {'text/plain': 'x    int64\ny    object'}}]
    values = _inline_values('df.dtypes', [], outputs)
    assert values == [{'line': 1, 'name': 'df', 'value': 'x    int64\ny    object',
                       'type': 'result', 'shape': None, 'dtype': None,
                       'is_grid': False, 'is_container': False, 'accessor': ['_']}]
    served = {getattr(r, 'path', '') for r in ide_app(Workspace(roots=[])).routes}
    for route in ('/agent/branches', '/agent/fork', '/agent/revise', '/agent/rollback-turn',
                  '/agent/state/template', '/agent/state/bootstrap', '/agent/state/suggest',
                  '/agent/state/diagnostics', '/agent/state/update', '/agent/compaction'):
        assert route in served, route


def test_user_checkbox_settings_survive_close_and_reopen(tmp_path, monkeypatch):
    import leela.blocks.settings.settings as settings_module
    monkeypatch.setattr(settings_module, 'user_settings_file', lambda: tmp_path/'settings.json')
    async def go(pg):
        await pg.evaluate("leeAct('settings')")
        await pg.wait_for_selector('[data-pref="ligatures"]')
        await pg.select_option('[data-settings-scope]', 'user')
        await pg.uncheck('[data-pref="ligatures"]')
        await pg.check('[data-pref="useTabs"]')
        await pg.click('[data-save]')
        await pg.wait_for_selector('.lee-settings-modal', state='detached')
        await pg.evaluate("leeAct('settings')")
        await pg.wait_for_selector('[data-pref="ligatures"]')
        return (await pg.is_checked('[data-pref="ligatures"]'),
                await pg.is_checked('[data-pref="useTabs"]'))
    assert _run(go) == (False, True)
    saved = settings_module.Settings(user_path=tmp_path/'settings.json').raw('user')
    assert saved.get('editor', {}) == {'ligatures': False, 'useTabs': True}


def test_a_key_can_be_set_from_inside_leela_when_the_shell_gives_the_wrong_answer(tmp_path, monkeypatch):
    """The escape hatch, end to end. Asking the shell is a guess about a machine; where it guesses
    wrong every hosted model refuses every turn, and there has to be a way in that does not involve
    a terminal. What a secret is set to never comes back from the server, so the row says `set`."""
    import leela
    monkeypatch.setattr(leela, 'leela_cfg', tmp_path)
    async def go(pg):
        out = {}
        await pg.evaluate("leeAct('settings')")
        await pg.wait_for_selector('[data-settings-page="environment"]')
        await pg.click('[data-settings-page="environment"]')
        await pg.wait_for_selector('[data-env-list] .lee-env-row')
        await pg.fill('[data-env-key]', 'OPENAI_API_KEY')
        await pg.fill('[data-env-value]', 'sk-typed-into-leela')
        await pg.click('[data-env-save]')
        await pg.wait_for_selector('[data-env-remove="OPENAI_API_KEY"]')
        row = pg.locator('.lee-env-row', has=pg.locator('[data-env-remove="OPENAI_API_KEY"]'))
        out['row'] = await row.inner_text()
        out['refused'] = ''
        await pg.fill('[data-env-key]', 'not a name')
        await pg.fill('[data-env-value]', 'x')
        await pg.click('[data-env-save]')
        await pg.wait_for_function("document.querySelector('#status')?.textContent.includes('environment variable')", timeout=8000)
        out['refused'] = await pg.evaluate("document.querySelector('#status')?.textContent || ''")
        await pg.click('[data-env-remove="OPENAI_API_KEY"]')
        await pg.wait_for_selector('[data-env-remove="OPENAI_API_KEY"]', state='detached')
        return out
    out = _run(go)
    assert 'OPENAI_API_KEY' in out['row'] and 'set' in out['row']
    assert 'sk-typed-into-leela' not in out['row'], 'the value of a secret stays on the server'
    assert 'environment variable name' in out['refused'], 'a name a shell cannot export is refused, and says why'
    from leela.core.envs import stored_env
    assert stored_env() == {}, 'and removing it takes it back out of the file'

def test_the_model_picker_opens_where_it_belongs_and_chooses_by_keyboard():
    """A native `<select>` hands its menu to the platform, and WKWebView drew a list this long at
    the top of the screen rather than under the control. The menu is Leela's now, so it can be
    placed, filtered and driven from the keyboard -- and the select stays underneath it as the
    value, the id and the change event every other caller reads."""
    async def go(pg):
        out = {}
        await pg.wait_for_selector('[data-model-pick]')
        button = pg.locator('[data-model-pick="agentmodel"]')
        out['label'] = (await button.inner_text()).strip()
        out['select_hidden'] = await pg.evaluate("$('#agentmodel').hidden")
        await button.click()
        await pg.wait_for_selector('.lee-model-menu .lee-model-row')
        out['rows'] = await pg.locator('.lee-model-row').count()
        # measured after the open animation, which translates the box while it runs
        await pg.evaluate("() => Promise.all(document.querySelector('.lee-model-menu')"
                          ".getAnimations().map(a => a.finished))")
        # the fault this test is about: a menu with nothing to do with where its control is
        out['place'] = await pg.evaluate("""() => {
          const m = document.querySelector('.lee-model-menu').getBoundingClientRect();
          const b = document.querySelector('[data-model-pick]').getBoundingClientRect();
          return {gap: Math.round(Math.min(Math.abs(m.top - b.bottom), Math.abs(b.top - m.bottom))),
                  dx: Math.round(Math.abs(m.left - b.left)), top: Math.round(m.top),
                  inside: m.left >= 0 && m.right <= innerWidth && m.top >= 0 && m.bottom <= innerHeight};
        }""")
        await pg.keyboard.type('gpt')
        await pg.wait_for_function("document.querySelectorAll('.lee-model-row').length > 0")
        out['filtered'] = await pg.evaluate(
            "[...document.querySelectorAll('.lee-model-row')].every(r => /gpt/i.test(r.textContent))")
        await pg.keyboard.press('ArrowDown')
        out['active'] = await pg.evaluate("!!document.querySelector('.lee-model-row.active')")
        # A long list has to scroll inside the menu, and scrolling it is not a reason to take it
        # away: closing on every scroll event closed it the moment the list was used.
        out['scroll'] = await pg.evaluate("""async () => {
          const list = document.querySelector('.lee-model-list');
          for (let i = 0; i < 60; i++) {   // enough rows that it must scroll
            const o = document.createElement('option'); o.value = `filler-${i}`; o.textContent = `filler-${i}`;
            $('#agentmodel').appendChild(o);
          }
          const f = document.querySelector('[data-model-filter]');
          f.value = '';                                  // the arrows test left a filter on it
          f.dispatchEvent(new Event('input'));
          const box = document.querySelector('.lee-model-list');
          const room = box.scrollHeight > box.clientHeight;
          box.scrollTop = 80;
          box.dispatchEvent(new Event('scroll', {bubbles: true}));
          await new Promise(r => setTimeout(r, 60));
          return {room, moved: box.scrollTop > 0, open: !!document.querySelector('.lee-model-menu')};
        }""")
        await pg.keyboard.press('Escape')
        out['closed'] = await pg.evaluate("!document.querySelector('.lee-model-menu')")
        # Choosing one goes through the select's own change event, which is the single path that
        # saves it: the picker must not become a second way of doing the same thing.
        await button.click()
        await pg.wait_for_selector('.lee-model-menu .lee-model-row')
        wanted = await pg.evaluate(
            "() => [...$('#agentmodel').options].map(o => o.value).find(v => v !== $('#agentmodel').value)")
        out['wanted'] = wanted
        if wanted:
            await pg.fill('[data-model-filter]', wanted)
            async with pg.expect_response(lambda r: '/agent/model' in r.url) as saved:
                await pg.keyboard.press('Enter')
            out['saved'] = (await saved.value).ok
            out['value'] = await pg.evaluate("$('#agentmodel').value")
            out['button'] = (await button.inner_text()).strip()
        return out
    out = _run(go)
    assert out['select_hidden'], 'the native menu is what was wrong; the select itself still carries the value'
    assert out['rows'] > 0 and out['label']
    assert out['place']['inside'], f"the menu is off screen: {out['place']}"
    assert out['place']['gap'] <= 8 and out['place']['dx'] <= 8, \
        f"the menu is not against its control: {out['place']}"
    assert out['filtered'], 'typing filters the list'
    assert out['active'], 'the arrows move a highlighted row'
    assert out['scroll']['room'], 'a list longer than the menu scrolls inside it'
    assert out['scroll']['moved'], 'and it actually moves'
    assert out['scroll']['open'], 'scrolling the list is not a reason to close the menu'
    assert out['closed'], 'escape closes it'
    if out['wanted']:
        assert out['saved'], 'the choice reaches /agent/model'
        assert out['value'] == out['wanted'], 'and the select carries it, for every reader of it'
        assert out['wanted'].split('/')[-1][:6] in out['button'], 'the control shows what was chosen'

def test_settings_say_which_layer_a_value_comes_from_and_offer_to_clear_it(tmp_path, monkeypatch):
    """A `languages.python` block in the user file beats the plain user section, and a workspace
    file beats both, so "I saved it to user and nothing happened" is a fair thing to think. The
    server has always worked out which layer supplies each key; nothing showed it."""
    import json
    import leela.blocks.settings.settings as settings_module
    user = tmp_path/'settings.json'
    user.write_text(json.dumps({'editor': {'fontFamily': 'JetBrains Mono', 'useTabs': False},
                                'languages': {'python': {'editor': {'useTabs': True}}}}))
    monkeypatch.setattr(settings_module, 'user_settings_file', lambda: user)
    async def go(pg):
        out = {}
        await pg.evaluate("() => leeAct('settings')")
        await pg.wait_for_selector('[data-pref="useTabs"]')
        await pg.select_option('[data-settings-scope]', 'user')
        await pg.select_option('[data-settings-language]', '')          # reloads the modal
        await pg.wait_for_selector('[data-pref="useTabs"]')
        out['plain'] = await pg.evaluate(
            "() => $('[data-pref=\"useTabs\"]').closest('label').querySelector('[data-origin]')?.textContent || ''")
        out['banner_all'] = await pg.evaluate("() => !$('[data-settings-shadow]').hidden")
        await pg.select_option('[data-settings-language]', 'python')
        await pg.wait_for_selector('[data-pref="useTabs"]')
        out['py'] = await pg.evaluate(
            "() => $('[data-pref=\"useTabs\"]').closest('label').querySelector('[data-origin]')?.textContent || ''")
        return out
    out = _run(go)
    assert out['plain'] == 'from user:python', 'the layer in charge is named on the control'
    assert out['banner_all'], 'and saying it wins over what you are about to save is the whole point'
    assert out['py'] == 'from user:python', 'still named when that is the layer being edited'
    # what the button does, asked of the server the button asks
    s = settings_module.Settings(user_path=user)
    assert s.raw('user')['languages']['python']['editor'] == {'useTabs': True}
    s.reset('user', 'editor', 'python')
    assert not (s.raw('user').get('languages', {}).get('python') or {}).get('editor'), 'cleared'
    assert s.effective('python')['editor']['useTabs'] is False, 'and the user value is back in charge'

def test_tabs_and_panes_overflow_switch_and_come_back_where_they_were_left():
    """One page for the shell's layout. Tabs past the strip's width belong in the overflow menu and
    nowhere else, `mod+e` is the switcher's chord, `sessionStorage` died with the window so every
    reopened tab came back at line 1, `leeDock` opens the bottom pane to show its tab so a restore
    has to run before the hiding, and a minimised files pane must keep its grid column.
    """
    async def go(pg):
        out = {}
        # One tab first: with more than one open the chord cycles to the next instead of listing.
        await pg.evaluate("leeAct('new_notebook')")
        await pg.wait_for_selector('.lee-tab')
        await pg.evaluate("leeAct('recent_tabs')")
        await pg.wait_for_selector('.lee-recent-list')
        out['heading'] = await pg.locator('.lee-mhead').inner_text()
        out['binding'] = await pg.evaluate("lee.keys.find(k => k.action === 'recent_tabs').key")
        await pg.keyboard.press('Escape')
        await pg.wait_for_selector('.lee-recent-list', state='detached')

        for _ in range(6):
            await pg.evaluate("leeAct('new_notebook')")
            await pg.wait_for_timeout(80)
        await pg.wait_for_function("document.querySelectorAll('.lee-tab').length === 7")
        await pg.evaluate('layoutTabs()')
        out['hidden'] = await pg.locator('.lee-tab.overflowed').count()
        out['label'] = await pg.locator('#taboverflow').inner_text()
        await pg.click('#taboverflow')
        await pg.wait_for_selector('.lee-ctxmenu')
        out['rows'] = await pg.locator('.lee-ctxmenu .lee-menuitem').count()
        await pg.evaluate('closeMenu()')
        await pg.wait_for_selector('.lee-ctxmenu', state='detached')

        out['remembered'] = await pg.evaluate("""() => {
          const out = {};
          lee.path = '/w/notes.py'; lee.kind = 'text'; lee.tabKey = lee.path;
          const host = document.createElement('div'); host.style.height = '80px';
          document.body.appendChild(host);
          const v = LeeCM.create(host, {doc: 'one\\ntwo\\nthree\\n', lang: 'python'});
          lee.editors.set('file', v);
          LeeCM.setCursor(v, v.state.doc.line(3).from);
          localStorage.removeItem('lee-tab-locations');
          saveTabLocation();
          out.stored = JSON.parse(localStorage.getItem('lee-tab-locations') || '[]');
          out.session = sessionStorage.getItem('lee-tab-locations');
          leeRight('vars'); leeDock('term');
          out.right = localStorage.getItem('lee-right-view');
          out.dock = localStorage.getItem('lee-dock-view');
          leeRight('agent'); leeDock('exec');
          return out;
        }""")
        out['restored'] = await pg.evaluate("""() => {
          localStorage.setItem('lee-dock-view', 'term');
          localStorage.setItem('lee-pane-bottom', 'hidden');
          localStorage.setItem('lee-right-view', 'vars');
          initSplits();
          const out = {dock: $('#bottomdock').classList.contains('dock-term'),
                       hidden: $('#shell').classList.contains('no-bottom'),
                       right: $('#right').classList.contains('right-vars')};
          localStorage.removeItem('lee-pane-bottom'); localStorage.removeItem('lee-dock-view');
          localStorage.removeItem('lee-right-view');
          leePane('bottom', true); leeDock('exec'); leeRight('agent');
          return out;
        }""")
        await pg.evaluate("leePane('left', false)")
        out['minimised'] = await pg.evaluate("""() => ({
          left: getComputedStyle(document.querySelector('#left')).display,
          leftVisibility: getComputedStyle(document.querySelector('#left')).visibility,
          keysVisibility: getComputedStyle(document.querySelector('#keytoast')).visibility,
          editorWidth: document.querySelector('#editor').getBoundingClientRect().width,
          restoreVisible: !!document.querySelector('.restore-left')?.getClientRects().length,
          shellHidden: document.querySelector('#shell').classList.contains('no-left')
        })""")
        return out
    got = _run(go)
    assert got['hidden'] > 0 and got['label'].startswith('+')
    assert got['rows'] == got['hidden']
    assert 'Recent files' in got['heading']
    assert got['binding'] == 'mod+e'

    remembered = dict(got['remembered']['stored'])
    assert '/w/notes.py' in remembered, 'keyed by the file, so every tab has its own'
    assert remembered['/w/notes.py']['pos'] > 0 and 'scroll' in remembered['/w/notes.py']
    remembered = got['remembered']
    assert remembered['session'] is None, 'and it no longer goes somewhere that dies with the window'
    assert remembered['right'] == 'vars' and remembered['dock'] == 'term'

    restored = got['restored']
    assert restored['dock'] and restored['right'], 'the tabs the last session had open are the ones showing'
    assert restored['hidden'], 'and a pane it had minimised is still minimised'

    r = got['minimised']
    assert r['left'] != 'none', 'the hidden grid item must retain its column placement'
    assert r['leftVisibility'] == r['keysVisibility'] == 'hidden'
    assert r['editorWidth'] > 300 and r['restoreVisible'] and r['shellHidden']


def test_a_notebook_recovers_its_drafts_and_answers_the_editing_chords():
    """One page for the work a person does inside a cell. A draft in IndexedDB has to come back
    before the mount and go away again when it matches the disk, `mod+c` is cell copy only when no
    source text is selected, indent and outdent are Leela's own bindings rather than CodeMirror's,
    and the split chord makes one cell per symbol.
    """
    async def go(pg):
        out = {}
        out['recovered'] = await pg.evaluate("""async () => {
          await clearDrafts('recovery.py');
          await draftPut({key:'recovery.py', document:'recovery.py', payload:{path:'recovery.py', kind:'text', text:'unsaved browser work'},
                          baseDiskVersion:'old:1', updatedAt:Date.now()});
          const state = {path:'recovery.py', title:'recovery.py', kind:'text', text:'disk version'};
          const recovered = await restoreDrafts(state);
          const rows = await draftsFor('recovery.py'), base = lee.draftBases.get('recovery.py') || '';
          await clearDrafts('recovery.py');
          return {recovered, text:state.text, base, rows:rows.length};
        }""")
        out['identical'] = await pg.evaluate("""async () => {
          await clearDrafts('already-saved.py');
          await draftPut({key:'already-saved.py', document:'already-saved.py',
            payload:{path:'already-saved.py', kind:'text', text:'same on disk'},
            baseDiskVersion:'stale:1', updatedAt:Date.now()});
          const state = {path:'already-saved.py', title:'already-saved.py', kind:'text', text:'same on disk'};
          const recovered = await restoreDrafts(state);
          return {recovered, rows:(await draftsFor('already-saved.py')).length};
        }""")
        await pg.evaluate("leeAct('new_notebook')")
        await pg.wait_for_selector('.lee-cell .cm-editor')
        out['copy'] = await pg.evaluate("""() => {
          const view=lee.editors.get(lee.cells[0].id), fire=()=>{
            const e=new KeyboardEvent('keydown',{key:'c',code:'KeyC',metaKey:MAC,ctrlKey:!MAC,bubbles:true,cancelable:true});
            view.contentDOM.dispatchEvent(e);return e.defaultPrevented;};
          LeeCM.setDoc(view,'alpha = 1');LeeCM.setSelection(view,0,0);lee.cellClipboard=null;
          const wholePrevented=fire(),whole=lee.cellClipboard?.cell?.source;
          LeeCM.setSelection(view,0,5);lee.cellClipboard=null;
          const textPrevented=fire(),selectedCopied=!!lee.cellClipboard;
          return {wholePrevented,whole,textPrevented,selectedCopied};
        }""")
        chord = """(key, code, hyper) => {
            const e = new KeyboardEvent('keydown', {key, code, metaKey: MAC,
                ctrlKey: !MAC || hyper, altKey: !!hyper, shiftKey: !!hyper,
                bubbles: true, cancelable: true});
            document.activeElement.dispatchEvent(e);
            return e.defaultPrevented;
        }"""
        out['cell'] = await pg.evaluate("""(chordSrc) => {
          const chord = eval(chordSrc);
          const v = lee.editors.get(lee.cells[0].id);
          LeeCM.setDoc(v, 'x = 1'); LeeCM.setSelection(v, 0, 0); LeeCM.focus(v);
          const prevented = chord(']', 'BracketRight', false);
          const indented = LeeCM.getDoc(v), matched = lee.lastKeyEvent.action;
          chord('[', 'BracketLeft', false);
          // `lastKeyEvent` is what the router matched. Without it the document would still change,
          // because CodeMirror's own keymap answers these two, and the test would prove nothing.
          return {prevented, indented, matched, back: lee.lastKeyEvent.action,
                  outdented: LeeCM.getDoc(v)};
        }""", chord)
        await pg.evaluate("""() => {
          const v = lee.editors.get(lee.cells[0].id);
          LeeCM.setDoc(v, '#| export\\nimport os\\n\\ndef f():\\n    return 1\\n\\nclass C: pass\\n');
          LeeCM.focus(v);
        }""")
        out['split'] = await pg.evaluate("""() => {
          const e = new KeyboardEvent('keydown', {key: '/', code: 'Slash', altKey: true,
            shiftKey: true, bubbles: true, cancelable: true});
          document.activeElement.dispatchEvent(e);
          return {prevented: e.defaultPrevented, matched: lee.lastKeyEvent.action};
        }""")
        await pg.wait_for_function('lee.cells.length === 3')
        out['sources'] = await pg.evaluate("lee.cells.map(c => c.source)")
        # The file editor: the same view identity `curEditor` and the router both resolve for a
        # python file, which is the other surface indent has to serve.
        out['file'] = await pg.evaluate("""(chordSrc) => {
          const chord = eval(chordSrc);
          const host = document.createElement('div');
          host.style.cssText = 'height:160px;position:fixed;inset:40px 20px auto 20px';
          document.body.appendChild(host);
          const v = LeeCM.create(host, {doc: 'def f():\\nx = 1\\n', lang: 'python', lineNums: true});
          lee.editors.set('file', v); lee.kind = 'file'; lee.activeEditor = 'primary';
          LeeCM.setSelection(v, 0, LeeCM.getDoc(v).length); LeeCM.focus(v);
          const prevented = chord(']', 'BracketRight', true);      // hyper+] : re-indent
          return {prevented, reindented: LeeCM.getDoc(v), matched: lee.lastKeyEvent.action};
        }""", chord)
        return out
    got = _run(go)
    assert got['recovered'] == {'recovered': True, 'text': 'unsaved browser work',
                                'base': 'old:1', 'rows': 1}
    assert got['identical'] == {'recovered': False, 'rows': 0}
    assert got['copy'] == {'wholePrevented': True, 'whole': 'alpha = 1',
                           'textPrevented': False, 'selectedCopied': False}
    cell, file = got['cell'], got['file']
    assert cell['prevented'] is True, 'Leela owns the chord once it names it'
    assert cell['matched'] == 'indent_more' and cell['back'] == 'indent_less', \
        'the router matched Leela\'s bindings, not CodeMirror\'s own'
    assert cell['indented'] == '    x = 1', f"cell indent gave {cell['indented']!r}"
    assert cell['outdented'] == 'x = 1', f"cell outdent gave {cell['outdented']!r}"
    assert file['prevented'] is True
    assert file['matched'] == 'indent_selection', 'hyper+] is Leela\'s alone; CodeMirror binds mod+alt+\\'
    assert file['reindented'] == 'def f():\n    x = 1\n', f"reindent gave {file['reindented']!r}"
    assert got['split'] == {'prevented': True, 'matched': 'cell_split_symbols'}
    assert got['sources'] == ['#| export\nimport os',
                              '#| export\ndef f():\n    return 1',
                              '#| export\nclass C: pass']


def test_a_completion_on_a_cells_last_line_is_drawn_whole():
    """It was cut off at the code box, and what escaped was painted over by the next cell.

    Two clippers: `overflow` on `.lee-cm`, and the paint containment `content-visibility: auto`
    brings to `.lee-cell`, which also makes each cell a stacking context the next one paints over.
    The check is what the person sees: the list is taller than the box, and the point two thirds
    of the way down it belongs to the list.
    """
    async def go(pg):
        await pg.evaluate("leeAct('new_notebook')")
        await pg.wait_for_selector('.lee-cell .cm-editor')
        await pg.evaluate("""() => {
          const view = lee.editors.get(lee.cells[0].id);
          LeeCM.setDoc(view, ['x = 1', 'y = 2', 'd'].join(String.fromCharCode(10)));
          LeeCM.setSelection(view, LeeCM.getDoc(view).length, LeeCM.getDoc(view).length);
          view.focus();
        }""")
        await pg.keyboard.press('Alt+/')
        await pg.wait_for_selector('.cm-tooltip-autocomplete')
        return await pg.evaluate("""() => {
          const tip = document.querySelector('.cm-tooltip-autocomplete');
          const box = tip.closest('.lee-cm'), cell = tip.closest('.lee-cell');
          const t = tip.getBoundingClientRect(), b = box.getBoundingClientRect();
          const at = document.elementFromPoint(t.left + t.width / 2, t.top + t.height * 2 / 3);
          return {overflow: getComputedStyle(box).overflow,
                  visibility: getComputedStyle(cell).contentVisibility,
                  below: t.bottom - b.bottom, height: t.height,
                  hits: !!(at && at.closest('.cm-tooltip-autocomplete'))};
        }""")
    out = _run(go)
    assert out['overflow'] == 'visible' and out['visibility'] == 'visible', out
    assert out['height'] > 0 and out['below'] > 0, 'the list is taller than the box that holds it'
    assert out['hits'], 'the point two thirds down the list is the list, not what is drawn over it'

def test_a_streaming_reply_repaints_while_it_streams():
    """The pane sat still through a burst of chunks and then jumped a paragraph at a time.

    `renderMarkdown` aborted the render already on the wire on every call, so a reply arriving
    faster than one round trip only painted when the model paused: 320 chunks repainted twice.
    A render in flight is left to land now, and one more runs after it if the text moved on.
    """
    async def go(pg):
        return await pg.evaluate("""async () => {
          const el = document.createElement('div');
          document.querySelector('#agentlog').appendChild(el);
          let paints = 0;
          new MutationObserver(() => paints++).observe(el, {childList: true});
          let text = '';
          for (let i = 0; i < 80; i++) {
            text += 'a streamed sentence about the kernel and its outputs. ';
            renderMarkdown(el, text);
            await new Promise(r => setTimeout(r, 12));
          }
          await new Promise(r => setTimeout(r, 500));
          return {paints, tail: el.textContent.trim().endsWith('outputs.')};
        }""")
    out = _run(go)
    assert out['paints'] >= 5, f"the reply painted {out['paints']} times while 80 chunks arrived"
    assert out['tail'], 'and what is on screen at the end is the whole reply'

def test_a_burst_of_chunks_is_painted_once_a_frame():
    "One wake of the feed hands over every row since the last. They belong in one paint, not eight."
    async def go(pg):
        return await pg.evaluate("""async () => {
          const log = document.querySelector('#agentlog'); log.innerHTML = '';
          const card = agentTurnCard({prompt: 'probe', model: ''}); log.appendChild(card);
          const root = document.createElement('div'); root.className = 'lee-agent-timeline';
          turnBody(card).appendChild(root);
          const tl = agentTimeline(root);
          let calls = 0;
          const real = tl.chunk.bind(tl); tl.chunk = t => { calls++; return real(t); };
          let pending = '', frame = 0;
          const flush = () => { frame = 0; const t = pending; pending = ''; if (t) tl.chunk(t); };
          for (let i = 0; i < 8; i++) { pending += 'row ' + i + ' '; frame ||= requestAnimationFrame(flush); }
          await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
          return {calls, text: root.querySelector('.lee-timeline-prose')?.dataset.markdown || ''};
        }""")
    out = _run(go)
    assert out['calls'] == 1, f'eight rows in one frame painted {out["calls"]} times'
    assert out['text'].split() == ['row', '0', 'row', '1', 'row', '2', 'row', '3', 'row', '4',
                                   'row', '5', 'row', '6', 'row', '7'], out['text']

def test_a_code_block_is_mounted_once_however_often_the_reply_around_it_repaints():
    """A reply is re-rendered whole on every chunk, and every render rebuilt its code surfaces.

    Measured on one nine-second turn ending in eight blocks: 455 CodeMirror views constructed and
    447 thrown away, 1.7s of main thread, in the faster of the two engines Leela runs in. The
    packaged app runs the slower one, and this was the jitter in the agent pane. Surfaces are keyed
    by the code they hold and re-parented now, so only a block whose text moved is built again.
    """
    async def go(pg):
        return await pg.evaluate("""async () => {
          const el = document.createElement('div'); el.className = 'lee-reply';
          document.querySelector('#agentlog').appendChild(el);
          let built = 0;
          const real = window.createEditor;
          window.createEditor = (...a) => { built++; return real(...a); };
          const block = n => '```python\\ndef f' + n + '(x):\\n    return x + ' + n + '\\n```';
          let text = block(1) + '\\n\\n' + block(2) + '\\n\\nand then ';
          try {
            for (let i = 0; i < 12; i++) {
              text += 'one more word ';
              renderMarkdown(el, text, false, null, 8);
              await new Promise(r => setTimeout(r, 40));
            }
            await new Promise(r => setTimeout(r, 700));
          } finally { window.createEditor = real; }
          return {built, surfaces: el.querySelectorAll('.lee-code-surface').length,
                  bare: el.querySelectorAll('pre > code').length,
                  text: el.textContent.includes('def f2')};
        }""")
    out = _run(go)
    assert out['surfaces'] == 2 and out['bare'] == 0, f'two fences, two surfaces: {out}'
    assert out['text'], 'and the code is still the code'
    assert out['built'] == 2, f'two code blocks were mounted {out["built"]} times over 12 repaints'

def test_a_long_reply_is_not_re_rendered_from_the_top_ten_times_a_second():
    """Every pass over a streaming reply costs the whole reply: a `/markdown/render` round trip that
    parses and highlights the document again, an `innerHTML` write, and a re-measure of every code
    surface in it. At a fixed 100ms gap a 12,000-character answer paid that thirty times, over an
    average of six thousand characters, which is the pane going stiff exactly when the model is
    writing its longest answer.

    The gap grows with the text now. What keeps the words arriving at the rate they were written is
    the unparsed tail after the prose, which costs a `textContent` write and no parse, and which
    `seal` renders properly and removes at the end of the stretch.
    """
    async def go(pg):
        return await pg.evaluate("""async () => {
          const log = document.querySelector('#agentlog');
          dropCodeSurfaces(log); log.innerHTML = ''; lee.agentView = 'live';
          const card = agentTurnCard({prompt: 'probe', model: ''}); log.appendChild(card);
          const root = document.createElement('div'); root.className = 'lee-agent-timeline';
          turnBody(card).appendChild(root);
          const tl = agentTimeline(root);
          let renders = 0, live = 0;
          const real = window.fetch;
          window.fetch = (u, o) => { if (String(u).includes('/markdown/render')) renders++; return real(u, o); };
          const sentence = '## a heading\\n\\nthe kernel wrote its outputs into the pane and the reader '
            + 'read them one paragraph after another without ever reaching the end of what the model '
            + 'had to say about the notebook it had just run. ';
          try {
            for (let i = 0; i < 60; i++) {
              tl.chunk(sentence);
              live = Math.max(live, root.querySelector('.lee-agent-reply-tail')?.textContent.length || 0);
              await new Promise(r => setTimeout(r, 50));
            }
            tl.seal();
            await new Promise(r => setTimeout(r, 900));
          } finally { window.fetch = real; }
          const prose = root.querySelector('.lee-timeline-prose');
          return {renders, live, chars: prose.dataset.markdown.length,
                  tail: !!root.querySelector('.lee-agent-reply-tail'),
                  headings: prose.querySelectorAll('h2').length,
                  shown: (prose.textContent.match(/one paragraph after another/g) || []).length};
        }""")
    out = _run(go)
    assert out['chars'] > 9000, f'the probe has to be a long reply for this to mean anything: {out}'
    assert 3 <= out['renders'] <= 16, f"{out['chars']} characters were re-rendered {out['renders']} times"
    assert out['live'] > 0, 'nothing was on screen between one render and the next'
    assert not out['tail'], 'the unparsed tail outlived the stretch of prose it belonged to'
    assert out['headings'] >= 1, f'the sealed reply is not rendered markdown: {out}'
    assert out['shown'] == 60, f"the sealed reply is {out['shown']} of its 60 chunks: {out}"

def test_the_live_agent_pane_keeps_a_bounded_number_of_turns():
    """Folding hides a turn from layout and frees nothing. Every turn of a session stayed in the
    live pane holding its rendered replies and a CodeMirror view per code block in them, so a long
    day's conversation was hundreds of live views carried through every paint.

    The pane keeps the last `LIVE_TURNS`, tears down what it drops, and says where they went. A turn
    holding a checkpoint nobody has answered is never dropped: its buttons are the only way that run
    continues.
    """
    async def go(pg):
        return await pg.evaluate("""async () => {
          const log = document.querySelector('#agentlog');
          dropCodeSurfaces(log); log.innerHTML = ''; approvalCards.clear(); lee.agentView = 'live';
          let torn = 0;
          const real = window.dropCodeSurfaces;
          window.dropCodeSurfaces = n => { if (n?.classList?.contains('lee-agent-turn')) torn++; return real(n); };
          try {
            for (let i = 0; i < 40; i++) {
              const card = agentTurnCard({prompt: 'turn ' + i, model: '', turnId: 't' + i});
              log.appendChild(card);
              if (i === 1) {
                const held = document.createElement('div'); held.className = 'lee-approval proposed';
                turnBody(card).appendChild(held);
              }
              trimAgentLog(log);
            }
          } finally { window.dropCodeSurfaces = real; }
          const ids = [...log.querySelectorAll('.lee-agent-turn')].map(c => c.dataset.turn);
          return {kept: ids.length, torn, newest: ids.at(-1), checkpoint: ids.includes('t1'),
                  note: !!log.querySelector('.lee-agent-trimmed')};
        }""")
    out = _run(go)
    assert out['newest'] == 't39', f'the turn being written was dropped: {out}'
    assert out['kept'] <= 31, f'forty turns left {out["kept"]} in the pane'
    assert out['checkpoint'], 'a turn holding an unanswered checkpoint was dropped'
    assert out['torn'] >= 8, f'the turns it dropped kept their code surfaces: {out}'
    assert out['note'], 'nothing on screen said where the earlier turns went'

def test_the_agent_pane_follows_the_stream_without_dragging_a_reader_off_what_they_are_reading():
    """Every paint in the pane wrote `scrollTop = scrollHeight`, and wrote it *before* the markdown
    render it had just asked for had landed: the pane was measured short, jumped when the text
    arrived, and took the reader with it however far up they had scrolled.

    Stickiness follows the reader now. The last step is the one that made this worth scoping: a
    checkpoint's proposal editor re-renders as a person types in it, and it must not re-pin the log.
    """
    async def go(pg):
        return await pg.evaluate("""async () => {
          const log = document.querySelector('#agentlog');
          dropCodeSurfaces(log); log.innerHTML = '';
          const card = agentTurnCard({prompt: 'probe', model: ''}); log.appendChild(card);
          const root = document.createElement('div'); root.className = 'lee-agent-timeline';
          turnBody(card).appendChild(root);
          const tl = agentTimeline(root);
          const settle = () => new Promise(r => setTimeout(r, 700));
          const scrollTo = at => { log.scrollTop = at; log.dispatchEvent(new Event('scroll')); };
          tl.chunk('a filler paragraph about kernels and their outputs.\\n\\n'.repeat(120));
          await settle();
          stickAgentLog(log, true);
          const bottom = log.scrollTop;
          scrollTo(0);                                  // the reader goes back up to read
          tl.chunk('another sentence arrives while they read. ');
          await settle();
          const held = log.scrollTop;
          scrollTo(log.scrollHeight);                   // and comes back down to follow again
          tl.chunk('and one more after that. ');
          await settle();
          const followed = log.scrollHeight - log.scrollTop - log.clientHeight;
          // A checkpoint's own editor rendering is not the stream painting.
          const box = document.createElement('div');
          box.className = 'lee-approval';
          card.appendChild(box);
          const inner = document.createElement('div'); box.appendChild(inner);
          scrollTo(0);
          renderMarkdown(inner, 'a proposal the person is editing', false, null, 8);
          await settle();
          return {bottom, held, followed, afterProposal: log.scrollTop};
        }""")
    out = _run(go)
    assert out['bottom'] > 100, f'the pane has to be scrollable for this to mean anything: {out}'
    assert out['held'] == 0, f'a reader who scrolled up was dragged to {out["held"]}'
    assert out['followed'] <= 60, f'a reader at the bottom stopped following: {out["followed"]}px short'
    assert out['afterProposal'] == 0, 'typing in a checkpoint re-pinned the log to the bottom'

def test_every_editor_refuses_the_systems_own_autocorrect():
    """WKWebView hands a `contenteditable` to NSSpellChecker and a browser does not, so the packaged
    app curled quotes and corrected identifiers under CodeMirror. `leela/desktop.py` turns it off
    for the process; this is the same refusal on the view, for every editor Leela builds.
    """
    async def go(pg):
        return await pg.evaluate("""() => {
          const el = document.createElement('div'); document.body.appendChild(el);
          const v = createEditor(el, {doc: 'x = 1', lang: 'python'});
          const named = n => v.contentDOM.getAttribute(n);
          return {spellcheck: named('spellcheck'), autocorrect: named('autocorrect'),
                  autocapitalize: named('autocapitalize'),
                  everyMounted: [...document.querySelectorAll('.cm-content')]
                    .every(n => n.getAttribute('spellcheck') === 'false')};
        }""")
    out = _run(go)
    assert out['spellcheck'] == 'false', out
    assert out['autocorrect'] == 'off' and out['autocapitalize'] == 'off', out
    assert out['everyMounted'], 'an editor on the page was left with the system spell checker on'

def test_a_pipeline_terminal_follows_the_package_it_was_opened_for(tmp_path):
    """Moving between packages showed the first package's release log, and closing the terminal

    was the only way to see the one you were looking at. The record was keyed by kind alone, so
    there was one `release` terminal for the whole window holding the socket opened with whichever
    package came first. The server always kept one pipeline per package.
    """
    a, b = tmp_path/'alpha', tmp_path/'beta'
    for d in (a, b): d.mkdir()
    async def go(pg):
        out = {}
        await pg.evaluate(f"openReleaseTerm({str(a)!r}, 'release')")
        await pg.wait_for_function("lee.terms.size === 1")
        await pg.evaluate(f"openReleaseTerm({str(b)!r}, 'release')")
        await pg.wait_for_function("lee.terms.size === 2")
        out['ids'] = await pg.evaluate("[...lee.terms.keys()]")
        out['labels'] = await pg.evaluate("[...lee.terms.values()].map(t => t.label)")
        out['cwds'] = await pg.evaluate("[...lee.terms.values()].map(t => t.cwd)")
        out['showing'] = await pg.evaluate("lee.activeTerm")
        # back to the first package: the record is re-shown, not rebuilt, and none is added
        await pg.evaluate(f"openReleaseTerm({str(a)!r}, 'release')")
        out['after_back'] = await pg.evaluate("[lee.terms.size, lee.activeTerm]")
        # the same package by a path with a trailing slash is the same package
        await pg.evaluate(f"openReleaseTerm({str(a)!r} + '/', 'release')")
        out['after_slash'] = await pg.evaluate("lee.terms.size")
        return out
    out = _run(go, roots=[tmp_path])
    assert out['ids'] == [f'release:{a}', f'release:{b}'], out['ids']
    assert out['labels'] == ['release · alpha', 'release · beta'], out['labels']
    assert out['cwds'] == [str(a), str(b)], 'each socket is told its own package'
    assert out['showing'] == f'release:{b}', 'the one just opened is the one on screen'
    assert out['after_back'] == [2, f'release:{a}'], out['after_back']
    assert out['after_slash'] == 2, 'a trailing slash is not a second package'

def test_the_agent_pane_draws_its_runs_its_steers_and_its_work_logs():
    """The runstrip was a single 34px line whatever it held, so a root and its subagents spilled out
    of it over the conversation, and a `.lee-spacer` beside them left each row 118px of a 420px pane
    -- every row reading `openai/gpt-5.6-luna suba…` and none of them saying what it was asked. A
    refused approval is a synthetic `user_steering` call, which every surface drew as an ordinary
    tool row with the direction given hidden behind a chevron. A steer appended to the log sat below
    every chunk and tool row that followed, and one taken straight to a waiting approval was never
    recorded at all, live or on replay. And `ask_cell` stores its work log twice, so the second copy
    came out as literal `<details>` tags under accordions already holding it.
    """
    async def go(pg):
        out = {}
        out['runstrip'] = await pg.evaluate("""() => {
          const now = Date.now() / 1000 - 75;
          leeRight('agent'); leePane('right', true);
          const measure = () => {
            const strip = $('#agentrunstrip'), pane = $('#right').getBoundingClientRect();
            const box = strip.getBoundingClientRect();
            return {height: Math.round(box.height),
                    contained: strip.scrollHeight <= strip.clientHeight + 1,
                    inside: box.left >= pane.left - 1 && box.right <= pane.right + 1,
                    fanned: strip.classList.contains('fanned'),
                    rows: [...$$('.lee-agent-run', strip)].map(r => ({
                      width: Math.round(r.getBoundingClientRect().width),
                      text: r.textContent.trim()}))};
          };
          const root = {id: 'r0', kind: 'root', model: 'openai/gpt-5.6-luna', started: now,
                        state: 'working', children: []};
          lee.agentRuns = [root];
          updateAgentRunstrip({runs: lee.agentRuns});
          const one = measure();
          root.children = [
            {id: 'c1', kind: 'child', model: 'openai/gpt-5.6-luna', started: now, state: 'working',
             question: 'review the refactor for missing cases', children: []},
            {id: 'c2', kind: 'child', model: 'openai/gpt-5.6-luna', started: now, state: 'working',
             question: 'check the recovery path', children: []}];
          updateAgentRunstrip({runs: lee.agentRuns});
          const many = measure();
          // a delegate that answered, and a root that has not
          root.children[0].state = 'completed'; root.children[0].ended = now + 12;
          root.children[1].question = '';
          updateAgentRunstrip({runs: lee.agentRuns});
          const mixed = {rows: measure().rows, send: $('#agentsend').textContent.trim(),
                         hidden: $('#agentrunstrip').hidden};
          // everything over: nothing is running, so nothing says it is
          for (const r of [root, ...root.children]) { r.state = 'completed'; r.ended = now + 20; }
          updateAgentRunstrip({runs: lee.agentRuns});
          const over = {hidden: $('#agentrunstrip').hidden, send: $('#agentsend').textContent.trim()};
          lee.agentRuns = []; updateAgentRunstrip({runs: []});
          return {one, many, mixed, over};
        }""")
        out['steps'] = await pg.evaluate("""() => {
          const draw = a => {
            const row = document.createElement('details'); renderAgentStep(row, a);
            return {cls: row.className, copy: $('.lee-agent-step-copy', row).textContent.trim(),
                    meta: $('.lee-agent-step-meta', row).textContent.trim(),
                    detail: (row.textContent || '')};
          };
          const rejected = 'The user rejected this tool call. Do not retry this call or an equivalent action unless the user explicitly asks for it later.';
          return {
            bare: draw({tool: 'user_steering', kind: 'tool', done: true, ok: true,
                        args: {instruction: rejected}}),
            said: draw({tool: 'user_steering', kind: 'tool', done: true, ok: true,
                        args: {instruction: rejected + ' User direction: use the other file instead'}}),
            stopped: draw({tool: 'user_steering', kind: 'tool', done: true, ok: true,
                           args: {instruction: 'The user stopped this turn. Do not run this call or any other one.'}}),
            tool: draw({tool: 'run_shell', kind: 'shell', summary: 'run_shell(command)', done: true, ok: true, secs: 1.2,
                        args: {command: 'ls'}})
          };
        }""")
        out['inside'] = await pg.evaluate("""() => {
          const log = $('#agentlog'); log.innerHTML = ''; lee.agentTimeline = null;
          const root = document.createElement('div'); root.className = 'lee-agent-timeline';
          log.appendChild(root);
          const timeline = agentTimeline(root); lee.agentTimeline = timeline;
          timeline.chunk('reading the file');
          setQueuedSteer('', 'use the other file');      // taken straight to a waiting approval
          timeline.chunk('using the other one');
          const inTurn = [...root.children].map(c => c.dataset?.steer || c.className.split(' ').pop());
          // once the turn is over the timeline is gone, and a steer has nowhere but the log
          lee.agentTimeline = null;
          setQueuedSteer('', 'and afterwards');
          const out = {inTurn, afterwards: log.lastElementChild?.dataset?.steer || '',
                       stranded: root.nextElementSibling?.dataset?.steer === 'use the other file'};
          log.innerHTML = ''; lee.agentTimeline = null;
          return out;
        }""")
        out['message'] = await pg.evaluate("""() => {
          const log = $('#agentlog'); log.innerHTML = '';
          // never queued: the server took it and returned an empty `queued_steer`
          setQueuedSteer('', 'use the other file');
          const after = log.children.length;
          // the local reply and the feed event both arrive with the same text
          setQueuedSteer('', 'use the other file');
          const out = {drawn: after, deduped: log.children.length,
                       text: log.lastElementChild?.textContent || ''};
          // a steer that is queued keeps its cancellable card instead
          setQueuedSteer('and then stop', 'and then stop');
          out.queued = Boolean($('#agentqueuedsteer'));
          out.cancellable = Boolean($('#agentqueuedsteer [data-cancel-steer]'));
          // taken by the agent: the card stays as the message it is, without the cancel
          setQueuedSteer('');
          out.kept = Boolean($('#agentqueuedsteer'));
          out.stillCancellable = Boolean($('#agentqueuedsteer [data-cancel-steer]'));
          log.innerHTML = '';
          return out;
        }""")
        out['replayed'] = await pg.evaluate("""() => {
          const host = document.createElement('div'); document.body.appendChild(host);
          renderTurns(host, [{prompt: 'rename the widget', reply: '', timeline: [
            {event: 'chunk', data: {text: 'reading '}},
            {event: 'steer', data: {text: 'use the other file', queued_steer: ''}},
            {event: 'chunk', data: {text: 'using it'}}]}], 'Recovered conversation');
          const root = $('.lee-agent-timeline', host);
          const out = {kinds: [...root.children].map(c => c.className.split(' ')[0]),
                       text: [...root.children].map(c => c.textContent.trim())};
          host.remove();
          return out;
        }""")
        out['worklog'] = await pg.evaluate(_WORK_LOG_CELL)
        out['group'] = await pg.evaluate(_PAYLOAD_GROUP)
        return out
    got = _run(go)
    one, many = got['runstrip']['one'], got['runstrip']['many']
    assert one['height'] == 34 and not one['fanned'], 'one run is still one line'
    assert len(many['rows']) == 3 and many['fanned']
    assert many['height'] > one['height'], 'the strip grows to hold its rows'
    assert many['contained'], 'rather than spilling them over the conversation above it'
    assert many['inside'], 'and it stays inside the pane'
    assert all(r['width'] > one['rows'][0]['width'] for r in many['rows']), \
        'the rows take the width the two buttons used to sit in'
    asked = [r['text'] for r in many['rows'][1:]]
    assert any('review the refactor' in t for t in asked) and any('check the recovery' in t for t in asked), \
        'and each row leads with what its subagent was asked, which is all that tells them apart'

    mixed, over = got['runstrip']['mixed'], got['runstrip']['over']
    assert not mixed['hidden'] and mixed['send'] == 'Steer after this call', \
        'a root still working holds the strip and the composer'
    assert not any('agent working' in r['text'] for r in mixed['rows'][1:]), \
        'a delegate with no question of its own does not borrow the root line and read as the agent'
    assert any('delegated' in r['text'] for r in mixed['rows'][1:]), 'it says what it is instead'
    assert over['hidden'], 'with every run ended there is nothing in flight to report'
    assert over['send'] == 'Send', 'and what is typed next is a turn, not a steer at a finished run'

    steps = got['steps']
    assert steps['said']['copy'] == 'You use the other file instead', 'what the person actually said'
    assert steps['bare']['copy'] == 'You rejected that call'
    assert steps['stopped']['copy'] == 'You stopped the turn'
    assert all(steps[k]['meta'] == 'steered' for k in ('bare', 'said', 'stopped'))
    assert all('lee-agent-steer-step' in steps[k]['cls'] for k in ('bare', 'said', 'stopped'))
    assert 'Do not retry this call' in steps['said']['detail'], 'the whole instruction is still there to open'
    assert 'lee-agent-steer-step' not in steps['tool']['cls'], 'an ordinary tool row is untouched'
    assert steps['tool']['copy'] == 'run_shell(command)' and steps['tool']['meta'] == '1.2s'

    inside = got['inside']
    assert inside['inTurn'][1] == 'use the other file', 'the steer sits between the prose either side of it'
    assert len(inside['inTurn']) == 3 and inside['inTurn'][2].startswith('lee-'), 'and the work after it follows'
    assert not inside['stranded'], 'rather than after the whole turn'
    assert inside['afterwards'] == 'and afterwards', 'with the log as the fallback when no turn is open'

    message = got['message']
    assert message['drawn'] == 1, 'what the person said is in the log'
    assert message['deduped'] == 1, 'and the same steer arriving twice is one message, not two'
    assert 'use the other file' in message['text']
    assert message['queued'] and message['cancellable'], 'a queued steer is still cancellable'
    assert message['kept'] and not message['stillCancellable'], 'once taken it is a message, not a pending one'

    replayed = got['replayed']
    assert 'lee-user-message' in replayed['kinds'], 'the steer is a message from the person, drawn as one'
    at = replayed['kinds'].index('lee-user-message')
    assert 0 < at < len(replayed['kinds']) - 1, 'in the place it happened, not before or after the turn'
    assert 'use the other file' in replayed['text'][at]

    worklog = got['worklog']
    assert 'the answer is four' in worklog['text'], worklog['text']
    assert '<details>' not in worklog['text'] and '<summary>' not in worklog['text'], worklog['text']
    assert 'what I did' not in worklog['text'] and '[kosha]' not in worklog['text'], worklog['text']
    assert worklog['rows'] == 1 and worklog['replyRows'] == 0, worklog
    assert worklog['kept'], 'the cell keeps the trail, so saving the notebook keeps the record'

    group = got['group']
    assert group['rows'] == ['Read · a/b.py', 'Load skill · write_docs'], group
    assert group['group'] and '2 steps' in group['summary'], group


def test_a_conversation_folds_its_turns_and_keeps_each_ones_own_controls():
    """Every turn painted the same flat run of siblings into one log, so there was nothing to fold
    and nothing that knew where a turn ended. Folding a turn the agent is blocked on would hide the
    only controls that let it continue, so a card holding a proposed checkpoint refuses, and the
    bulk fold has to inherit that refusal. `addResponseRevision` ran only from the live `done`
    handler, so undo, restore and revise disappeared on every history toggle, resume, thread switch
    and resync. `.lee-btn` had no disabled appearance, so a dead Undo was pixel-identical to a live
    one. And a feed left following paints a second turn into the card already on screen, where
    resolving a bar to the first `.lee-turn-answer` had it acting on the first turn's text.
    """
    async def go(pg):
        out = {}
        out['fold'] = await pg.evaluate("""() => {
          const log = $('#agentlog'); log.innerHTML = ''; lee.agentThread = 'fold-test';
          localStorage.removeItem('lee-agent-folded:fold-test');
          renderTurns(log, [{prompt: 'rename the widget', reply: 'renamed it', turn_id: 't1',
                             capabilities: {revisable: true, known: true}},
                            {prompt: 'and the tests', reply: 'done', turn_id: 't2',
                             capabilities: {known: true}}], '');
          const cards = $$('.lee-agent-turn', log);
          const out = {cards: cards.length, titles: cards.map(c => $('.lee-agent-turn-title', c).textContent)};

          foldAgentTurn(cards[0], true);
          out.folded = cards[0].classList.contains('folded');
          out.hidden = $('.lee-agent-turn-body', cards[0]).getBoundingClientRect().height === 0;
          out.pressed = $('.lee-agent-turn-fold', cards[0]).getAttribute('aria-expanded');
          out.remembered = localStorage.getItem('lee-agent-folded:fold-test');

          // a checkpoint the run is blocked on
          const ask = document.createElement('div'); ask.className = 'lee-approval proposed';
          $('.lee-agent-turn-body', cards[1]).appendChild(ask);
          foldAgentTurns(true);
          out.blockedStayedOpen = !cards[1].classList.contains('folded');
          unfoldForApproval(ask);
          out.unfolded = !cards[1].classList.contains('folded');

          log.innerHTML = ''; localStorage.removeItem('lee-agent-folded:fold-test'); lee.agentThread = '';
          return out;
        }""")
        out['bars'] = await pg.evaluate("""() => {
          const host = document.createElement('div'); host.id = 'agentlog-probe'; document.body.appendChild(host);
          renderTurns(host, [
            {prompt: 'rename it', reply: 'renamed', turn_id: 't1',
             capabilities: {revisable: true, branchable: true, undoable: true, known: true, files: ['a.py']}},
            {prompt: 'run the tests', reply: '', turn_id: 't2', activity: [{tool: 'run_shell', summary: 'run_shell', done: true, ok: true}],
             capabilities: {revisable: false, branchable: true, undoable: true, known: true, files: ['b.py']}},
            {prompt: 'an old one', reply: 'from before a restart', turn_id: 't3', capabilities: {known: false}}], '');
          const bars = $$('.lee-response-revision', host);
          const read = b => ({turn: b.dataset.turn,
                              off: [...b.querySelectorAll('button')].filter(x => x.disabled).map(x => x.textContent),
                              why: $('[data-unsay]', b).title});
          const out = {n: bars.length, rows: bars.map(read)};
          host.remove();
          return out;
        }""")
        out['pair'] = await pg.evaluate("""() => {
          const host = document.createElement('div'); document.body.appendChild(host);
          const card = agentTurnCard({prompt: 'first', turnId: 't1'}), body = turnBody(card);
          host.appendChild(card);
          const one = document.createElement('div'); one.className = 'lee-reply'; body.appendChild(one);
          renderMarkdown(one, 'the first answer');
          addResponseRevision(one, 't1', 'the first answer', {revisable: true, branchable: true, known: true});
          const two = document.createElement('div'); two.className = 'lee-reply'; body.appendChild(two);
          renderMarkdown(two, 'the second answer');
          addResponseRevision(two, 't2', 'the second answer', {revisable: true, branchable: true, known: true});
          const out = $$('.lee-response-revision', card).map(b => ({turn: b.dataset.turn, raw: turnReplyText(b)}));
          host.remove();
          return out;
        }""")
        out['newest'] = await pg.evaluate("""() => {
          const log = document.querySelector('#agentlog');
          log.innerHTML = ''; log.dataset.foldScope = 'fold-test';
          renderTurns(log, [1, 2, 3, 4].map(n => ({turn_id: `t${n}`, prompt: `question ${n}`,
                                                   model: 'm', timeline: []})), 'conversation');
          const read = () => [...log.querySelectorAll('.lee-agent-turn')]
            .map(c => ({turn: c.dataset.turn, folded: c.classList.contains('folded')}));
          const painted = read();
          // and the next turn beginning folds the one that was open
          log.appendChild(agentTurnCard({prompt: 'question 5', model: 'm', turnId: 't5'}));
          foldOlderTurns(log);
          return {painted, after: read()};
        }""")
        out['blocked'] = await pg.evaluate("""() => {
          const log = document.querySelector('#agentlog');
          log.innerHTML = ''; log.dataset.foldScope = 'fold-approval-test';
          const blocked = agentTurnCard({prompt: 'needs approval', model: 'm', turnId: 'a1'});
          turnBody(blocked).innerHTML = '<div class="lee-approval proposed">approve?</div>';
          const newer = agentTurnCard({prompt: 'later', model: 'm', turnId: 'a2'});
          const newest = agentTurnCard({prompt: 'newest', model: 'm', turnId: 'a3'});
          log.append(blocked, newer, newest);
          foldOlderTurns(log);
          return [...log.querySelectorAll('.lee-agent-turn')]
            .map(c => ({turn: c.dataset.turn, folded: c.classList.contains('folded')}));
        }""")
        out['look'] = await pg.evaluate("""() => {
          const log = $('#agentlog'); log.innerHTML = '';
          renderTurns(log, [
            {prompt: 'rename it', reply: 'renamed', turn_id: 's:turn_000001',
             capabilities: {revisable: true, branchable: true, undoable: true, known: true, files: ['a.py']}},
            {prompt: 'an old one', reply: 'from before a restart', turn_id: 's:turn_000002',
             capabilities: {known: false}}], '', false);
          const bars = $$('.lee-response-revision', log);
          const look = b => ({
            buttons: [...b.querySelectorAll('button')].map(x => ({label: x.textContent, off: x.disabled,
                                                                  faded: Number(getComputedStyle(x).opacity) < .9})),
            note: $('[data-unavailable]', b)?.textContent || '',
            noteShown: ($('[data-unavailable]', b)?.getBoundingClientRect().height || 0) > 0});
          return {live: look(bars[0]), dead: look(bars[1])};
        }""")
        await pg.click('.lee-response-revision [data-revise]')
        await pg.wait_for_timeout(300)
        out['revised'] = await pg.evaluate("() => !!$('[data-revision]')")
        return out
    got = _run(go)
    fold = got['fold']
    assert fold['cards'] == 2 and fold['titles'][0] == 'rename the widget'
    assert fold['folded'] and fold['hidden'] and fold['pressed'] == 'false'
    assert 't1' in (fold['remembered'] or ''), 'a fold is remembered per conversation'
    assert fold['blockedStayedOpen'], 'fold-all leaves the turn holding an unanswered checkpoint'
    assert fold['unfolded']

    bars = got['bars']
    assert bars['n'] == 3, 'including the turn that ended on a tool call and left no prose'
    assert [r['turn'] for r in bars['rows']] == ['t1', 't2', 't3']
    assert bars['rows'][0]['off'] == [], 'everything this turn can still do is offered'
    assert bars['rows'][1]['off'] == ['Edit what agent remembers'], 'no answer to edit, but files to restore'
    assert len(bars['rows'][2]['off']) == 3, 'a turn this process holds no boundary for offers nothing'
    assert 'not run in this session' in bars['rows'][2]['why'], 'and says which of the two reasons it is'

    assert [b['turn'] for b in got['pair']] == ['t1', 't2']
    assert got['pair'][0]['raw'] == 'the first answer' and got['pair'][1]['raw'] == 'the second answer'

    newest = got['newest']
    assert [c['folded'] for c in newest['painted']] == [True, True, True, False], newest['painted']
    assert [c['folded'] for c in newest['after']] == [True, True, True, True, False], newest['after']
    assert [c['folded'] for c in got['blocked']] == [False, True, False], got['blocked']

    look = got['look']
    assert [b['off'] for b in look['live']['buttons']] == [False] * 3
    assert not any(b['faded'] for b in look['live']['buttons']), 'a control that works is drawn full strength'
    assert not look['live']['note'], 'and the row says nothing about availability'
    assert [b['off'] for b in look['dead']['buttons']] == [True] * 3
    assert all(b['faded'] for b in look['dead']['buttons']), 'an unavailable control is muted, not just inert'
    assert look['dead']['noteShown'] and 'not run in this session' in look['dead']['note'], \
        'and the reason is on the row, not in a tooltip'
    assert got['revised'], 'an available control still opens its editor on a real click'


_SEARCH_HIT = ('{"path": "/tmp/engine.py", "line": 17, "text": "def runtime_engine():\\n    return 42",'
               ' "kind": "%s", "symbol": %s, "score": 220%s}')
_SEARCH_STREAM = (
    'event: start\ndata: {"legs": ["symbols", "rg"], "searched": ["/tmp/proj"]}\n\n'
    'event: leg\ndata: {"leg": "symbols", "hits": ['
    + (_SEARCH_HIT % ('symbol', '"runtime_engine"', ', "sources": ["symbols"]')) + ']}\n\n'
    'event: leg\ndata: {"leg": "rg", "hits": [' + (_SEARCH_HIT % ('text', 'null', '')) + ']}\n\n'
    'event: done\ndata: {}\n\n')


from conftest import serve


pytest.importorskip('playwright.sync_api')

FAMILIES = ['leela', 'cursor', 'vscode', 'jetbrains', 'solarized', 'gruvbox', 'nord', 'dracula']

@pytest.fixture
def proj_web_th(tmp_path):
    (tmp_path/'main.py').write_text('x = 1\n')
    return tmp_path

def _open(pw, url):
    page = _launch_sync(pw).new_page(viewport={'width': 1440, 'height': 900})
    page.goto(url, wait_until='networkidle')
    if page.locator('.lee-modal').count(): page.keyboard.press('Escape')
    return page

def _bg(page): return page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--lee-bg').trim()")

_NO_SAVED_THEME = ("() => post('/settings/save', {scope: 'user', language: '',"
                   " section: 'appearance', values: {theme: ''}})")

def test_every_family_repaints_and_the_picker_and_the_stored_preference_agree(proj_web_th):
    """Every family in every mode, the picker that offers them, the density that moves the header
    without moving the colours, and the pre-family preference a reload has to migrate rather than
    reset. One page, because each of the four is a handful of evaluates over the same shell.
    """
    ws = Workspace(roots=[proj_web_th])
    with serve(ws) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            page = _open(pw, url)
            # every assertion below is about the `lee-theme` cache, so the settings.json theme,
            # which outranks it, has to be out of the way first.
            page.evaluate(_NO_SAVED_THEME)
            seen = {}
            for family in FAMILIES:
                for mode in ('dark', 'light', 'system'):
                    page.evaluate('([f, m]) => applyTheme({family: f, mode: m})', [family, mode])
                    assert page.evaluate('document.documentElement.dataset.theme') == family
                    resolved = page.evaluate('document.documentElement.dataset.mode')
                    assert resolved in ('dark', 'light')
                    if mode != 'system': assert resolved == mode
                    assert page.evaluate('document.documentElement.style.colorScheme') == resolved
                    assert page.evaluate("localStorage.getItem('lee-theme')").startswith(f'{family}:{mode}:')
                    seen[family, resolved] = _bg(page)
            assert len(set(seen.values())) > len(FAMILIES)

            # the ask: cursor's tightness with leela's colours, so the header height moves and the
            # colours do not
            head = lambda: page.evaluate("document.querySelector('.lee-header').getBoundingClientRect().height")
            page.evaluate("applyTheme('leela:dark:relaxed')")
            relaxed, bg = head(), _bg(page)
            page.evaluate("applyTheme('leela:dark:tight')")
            assert page.evaluate('document.documentElement.dataset.density') == 'tight'
            assert head() < relaxed
            assert _bg(page) == bg
            page.reload(wait_until='networkidle')
            if page.locator('.lee-modal').count(): page.keyboard.press('Escape')
            assert page.evaluate('document.documentElement.dataset.density') == 'tight'

            page.evaluate('leeEditorSettings()')
            page.wait_for_selector('.lee-settings-modal')
            page.click('[data-settings-page="appearance"]')
            assert page.locator('.lee-theme-choice').count() == len(FAMILIES)
            assert page.locator('[data-theme-mode]').count() == 3
            assert page.locator('[data-theme-density]').count() == 2
            page.click('[data-theme-density="relaxed"]')
            assert page.evaluate('document.documentElement.dataset.density') == 'relaxed'
            page.click('.lee-theme-mode[data-theme-mode="dark"]')
            page.click('.lee-theme-choice[data-theme="nord"]')
            assert page.evaluate('document.documentElement.dataset.theme') == 'nord'
            assert page.evaluate('document.documentElement.dataset.mode') == 'dark'
            page.click('[data-cancel]')
            assert page.evaluate('document.documentElement.dataset.theme') != 'nord'

            page.evaluate(_NO_SAVED_THEME)   # the reloads above migrated the cache into settings
            page.evaluate("localStorage.setItem('lee-theme', 'dark')")
            page.reload(wait_until='networkidle')
            if page.locator('.lee-modal').count(): page.keyboard.press('Escape')
            assert page.evaluate('document.documentElement.dataset.theme') == 'leela'
            assert page.evaluate('document.documentElement.dataset.mode') == 'dark'
            assert page.evaluate('document.documentElement.dataset.density') == 'relaxed'
            page.wait_for_function("localStorage.getItem('lee-theme') === 'leela:dark:relaxed'")

            # the point of `system`: a machine that turns dark at sunset turns leela dark too
            page.emulate_media(color_scheme='light')
            page.evaluate("applyTheme('gruvbox:system')")
            assert page.evaluate('document.documentElement.dataset.mode') == 'light'
            light = _bg(page)
            page.emulate_media(color_scheme='dark')
            page.wait_for_function("document.documentElement.dataset.mode === 'dark'")
            assert _bg(page) != light


def test_the_theme_is_kept_in_settings_and_not_only_in_this_origin(proj_web_th):
    """The packaged app takes whatever port it is given when 5001 is busy, and `localStorage` is per
    origin, so a theme kept only there is gone on the next launch. Saving from the panel writes
    settings.json, counts as a saved setting, and holds for a browser that has never seen the
    origin. A theme that only ever lived in `localStorage` is migrated rather than dropped.
    """
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


def test_the_bundles_parse_and_share_one_scope(proj_web_th):
    """`node` is blocked here, so the browser is the syntax check. Loading them in order also
    proves the later ones can see what the first declared.
    """
    ws = Workspace(roots=[proj_web_th])
    with serve(ws) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            page = _launch_sync(pw).new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(f'{url}/leestatic/nothing-here')
            for name in IDE_BUNDLES: page.add_script_tag(url=f'{url}/leestatic/{name}')
            page.wait_for_timeout(200)
            assert not errors, errors


@pytest.fixture
def proj_web_va(tmp_path):
    (tmp_path/'notes.md').write_text('# Retrieval\n\nDurable notes about recall and ranking.\n')
    return tmp_path

def _vault(page):
    "The vault view, which lives behind the right pane's memory tab."
    page.click('.lee-righttab[data-right="memory"]')
    page.click('[data-memory-view="vault"]')
    page.wait_for_selector('#vaultpanel')

def test_a_clipped_file_lands_on_the_shelf_opens_as_a_reader_and_answers_review(proj_web_va):
    """The whole affordance in one session: right-click a file, clip it, watch it land, read it in
    the tab it opens as, and ask the ranker what it thinks of the shelf. Clipping is a real job with
    a real index behind it, so booting a page per step is most of what this file costs.
    """
    from playwright.sync_api import sync_playwright
    ws = Workspace(roots=[proj_web_va])
    with serve(ws) as url, sync_playwright() as pw:
        page = _open(pw, url)
        page.click('.lee-node.lee-root')
        page.wait_for_selector('.lee-node.lee-file')
        page.click('.lee-node.lee-file', button='right')
        page.wait_for_selector('.lee-ctxmenu')
        assert page.locator('.lee-menuitem', has_text='clip into the vault').count() == 1
        page.click('.lee-menuitem:has-text("clip into the vault")')
        page.wait_for_selector('#vaultpanel')
        assert page.locator('.lee-righttab[data-right="memory"].active').count() == 1
        assert page.locator('[data-memory-view="vault"].active').count() == 1, 'the nav follows'
        card = page.locator('#vaultjobs .lee-job').first
        card.wait_for()
        assert 'notes.md' in card.inner_text()
        page.wait_for_selector('#vaultjobs .lee-job.complete', timeout=20_000)
        assert ws.memory.documents(), 'the document reached the shelf'

        # memory -> vault -> a document -> its sections, which is the whole path a person takes
        _vault(page)
        assert page.locator('#vaulttidy').inner_text() == '', 'nothing is scored until asked for'
        page.wait_for_selector('.lee-vault-doc')
        assert 'notes' in page.locator('.lee-vault-doc').first.inner_text()
        page.click('.lee-vault-doc')
        page.wait_for_selector('.lee-vault-reader')
        assert page.locator('.lee-vault-section').count() >= 1, 'the section rail is drawn'
        page.wait_for_function("document.querySelector('.lee-vault-text')?.innerText.trim().length > 0")
        assert 'ranking' in page.locator('.lee-vault-text').inner_text().lower()
        assert 'no pattern found' in page.locator('.lee-vault-reader').inner_text()
        assert page.locator('.lee-tab', has_text='notes').count() >= 1, 'it is a tab, not a modal'

        # review swaps a list in; a shelf the ranker has no opinion about says so
        _vault(page)
        page.click('.lee-vault-tidy .lee-btn')
        page.wait_for_function("document.querySelector('#vaulttidy')?.innerText.trim().length > 0")
        rows = page.locator('.lee-tidy-row')
        if not rows.count():
            assert 'too small to have an opinion' in page.locator('#vaulttidy').inner_text()
            return
        rows.first.locator('button:has-text("keep")').click()
        page.wait_for_selector('.lee-tidy-row.judged')
        assert 'kept' in page.locator('.lee-tidy-row.judged').first.inner_text()


def test_a_pii_badge_loads_itself_and_says_what_it_found(proj_web_va):
    "The badge is lazy because a scan reads a whole document, and honest because coverage is partial."
    from playwright.sync_api import sync_playwright
    (proj_web_va/'minute.md').write_text('# Minute\n\nSigned by Dr Charles Babbage, ada@example.com.\n')
    ws = Workspace(roots=[proj_web_va])
    ws.memory.clip(list(proj_web_va.glob('*.md')))
    with serve(ws) as url, sync_playwright() as pw:
        page = _open(pw, url)
        doc = (ws.memory.documents() or [{}])[0]
        page.goto(f"{url}/vault/pii/badge?doc={doc.get('doc_id') or doc.get('id')}", wait_until='networkidle')
        badge = page.locator('.lee-pii')
        assert badge.count() == 1
        assert 'no pattern found' in badge.inner_text() or '×' in badge.inner_text()
        assert 'never looked for' in (badge.get_attribute('title') or ''), 'it must not imply "none"'


from leela.core.ui import bar
from leela.blocks.nb.nb import assigned_lines as _assigned_lines, inline_values as _inline_values
from leela.workspace import _EnvClient


def test_python_bindings_are_mapped_to_the_lines_that_create_them():
    source = """import pandas as pd
x, y = (2, 3)
if x:
    total: int = x + y

def local_scope():
    hidden = 99
"""
    assert _assigned_lines(source) == [(1, 'pd'), (2, 'x'), (2, 'y'), (4, 'total'),
                                        (6, 'local_scope')]

def test_inline_values_are_the_inspectors_real_display_values():
    groups = [{'nodes': [
        {'name': 'x', 'type': 'int', 'value': '2'},
        {'name': 'frame', 'type': 'DataFrame', 'value': 'DataFrame [17×4]'},
    ]}]
    values = _inline_values('x = 1\nframe = load()', groups)
    assert [(x['line'], x['name'], x['type'], x['value']) for x in values] == [
        (1, 'x', 'int', '2'),
        (2, 'frame', 'DataFrame', 'DataFrame [17×4]'),
    ]


def test_the_variable_panel_follows_the_runtime_the_picker_chose():
    ws = Workspace(roots=[])
    picked = type('Picked', (), {'base': 'http://picked'})()
    ws.pool.kernels['picked'] = picked
    ws.watch_env(picked.base)
    assert asyncio.run(ws.runtime()) is picked
    assert 'sort' not in {b.action for b in bar('vars')}
    ws = Workspace(roots=[])
    ws.watch_env('http://127.0.0.1:9999')
    asyncio.run(ws.set_kernel(kind='ipykernel', restart=False))
    assert ws.env_base is None


def test_external_inspected_runtimes_normalise_execution_as_notebook_output(monkeypatch):
    env = _EnvClient('http://picked', 'picked')
    async def fake_api(path, params=None, timeout=15):
        assert path == '/api/exec' and params['code'] == 'answer = 42'
        return {'ok': True, 'stdout': 'ready\n',
                'result': {'name': 'result', 'type': 'int', 'value': '42'}, 'error': None}
    monkeypatch.setattr(env, 'api', fake_api)
    result = asyncio.run(env.execute('answer = 42'))
    assert result.ok
    assert result.outputs[0]['text'] == 'ready\n'
    assert result.outputs[1]['data']['text/plain'] == '42'


def test_switching_tabs_returns_variables_to_that_notebooks_kernel(tmp_path):
    import json
    from starlette.testclient import TestClient
    for name in ('one.ipynb', 'two.ipynb'):
        (tmp_path/name).write_text(json.dumps({'nbformat': 4, 'nbformat_minor': 5,
                                               'metadata': {}, 'cells': []}))
    ws = Workspace(roots=[tmp_path]); ws.open(tmp_path/'one.ipynb'); ws.open(tmp_path/'two.ipynb')
    ws.watch_env('http://watched-app')
    with TestClient(ide_app(ws)) as client:
        client.post('/tab/select', params={'i': 0})
    assert ws.active == 0 and ws.env_base is None


def test_runtime_repairs_a_missing_dhrishti_inspector_without_restarting_namespace(tmp_path):
    path = tmp_path/'code.py'; path.write_text('kept = 42\n')
    ws = Workspace(roots=[tmp_path]); ws.open(path)
    class Kernel:
        inspect = True; base = None; boot_error = 'old dhrishti'; cwd = str(tmp_path)
        calls = 0
        async def bootstrap(self):
            self.calls += 1; self.base = 'http://repaired'; return self.base
    kernel = Kernel()
    async def get(tab=None): return kernel
    ws.kernel = get
    assert asyncio.run(ws.runtime()) is kernel
    assert kernel.base == 'http://repaired' and kernel.calls == 1 and kernel.boot_error is None

def test_variable_route_uses_the_same_selected_runtime_as_execution(tmp_path):
    from starlette.testclient import TestClient
    path = tmp_path/'code.py'; path.write_text('answer = 42\n')
    ws = Workspace(roots=[tmp_path]); ws.open(path)
    class SelectedRuntime:
        base = 'http://selected-runtime'
        python = str(tmp_path/'.venv/bin/python')
        cwd = str(tmp_path)
        async def api(self, route, params=None, timeout=15):
            assert route == '/api/rows'
            return {'groups': [{'label': 'selected venv', 'nodes': [
                {'name': 'answer', 'type': 'int', 'value': '42', 'accessor': ['answer']}
            ]}]}
    selected = SelectedRuntime()
    # `kernel_peek`, not `runtime`: a page load must not start a kernel, so `/vars` reads the one
    # already there. Stubbing `runtime` asserted the contract `475d960` retired.
    ws.kernel_peek = lambda tab=None: selected
    ws.inspector = lambda tab=None: None
    with TestClient(ide_app(ws)) as client:
        result = client.get('/vars').json()
    assert result['runtime'] == 'http://selected-runtime:live'
    assert result['inspector'] == 'dhrishti' and result['python'] == selected.python
    assert result['groups'][0]['nodes'][0]['name'] == 'answer'


from conftest import serve as _server


@pytest.mark.skipif(__import__('importlib').util.find_spec('playwright') is None, reason='playwright is not installed')
def test_browser_can_change_control_open_layered_state_and_find_agent_commands(tmp_path):
    from playwright.sync_api import sync_playwright
    ws = Workspace(roots=[tmp_path])
    with _server(ws) as url, sync_playwright() as pw:
        browser = _launch_sync(pw)
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        page.goto(url, wait_until='networkidle')
        if page.locator('.lee-modal').count(): page.keyboard.press('Escape')
        page.select_option('#agentcontrol', 'directed')
        page.wait_for_timeout(80)
        assert ws.approvals.control == 'directed'
        page.click('#agentstate')
        page.wait_for_selector('#agentstatelayer')
        assert page.locator('[data-bootstrap]').is_visible()
        assert 'Start with a worked template' in page.locator('.lee-agent-state-onboard').inner_text()
        assert page.locator('#agentstatelayer option').all_text_contents() == [
            'organization', 'project', 'task', 'preferences', 'branch', 'ephemeral']
        box = page.locator('.lee-agent-state-modal .lee-modalbox')
        initial = box.bounding_box()
        assert initial['width'] >= 1000 and initial['height'] >= 700
        assert page.locator('.lee-agent-state-editor .cm-editor').is_visible()
        assert page.locator('.lee-state-ref-tabs').is_visible()
        heading = page.locator('.lee-agent-state-modal .lee-mhead').bounding_box()
        page.mouse.move(heading['x'] + 180, heading['y'] + 12)
        page.mouse.down(); page.mouse.move(heading['x'] + 240, heading['y'] + 52, steps=4); page.mouse.up()
        moved = box.bounding_box()
        assert moved['x'] > initial['x'] and moved['y'] > initial['y']
        page.click('.lee-agent-state-modal .lee-modal-expand')
        expanded = box.bounding_box()
        assert expanded['width'] > initial['width'] and expanded['height'] > initial['height']
        page.select_option('#agentstatelayer', 'project')
        page.locator('.lee-agent-state-editor .cm-content').fill('# Goal\n\nKeep project architecture stable.')
        page.click('[data-add-tool]')
        assert page.locator('.lee-state-tool-list button').count() > 5
        page.click('[data-ref="preview"]')
        assert page.locator('#agentstatepreview').is_visible()
        page.click('[data-activate]')
        page.wait_for_timeout(100)
        assert ws.agent_state_layers['project']['text'].endswith('architecture stable.')
        page.evaluate("leeAct('palette')")
        page.fill('#cp', 'Agent: pause')
        assert 'Agent: pause after current call' in page.locator('#cplist').inner_text()
        palette = page.locator('.lee-modal').last.locator('.lee-modalbox')
        before_drag = palette.bounding_box(); grip = palette.locator('.lee-modal-grip').bounding_box()
        page.mouse.move(grip['x'] + 10, grip['y'] + 3); page.mouse.down()
        page.mouse.move(grip['x'] + 55, grip['y'] + 38, steps=3); page.mouse.up()
        after_drag = palette.bounding_box()
        assert after_drag['x'] > before_drag['x'] and after_drag['y'] > before_drag['y']
        browser.close()

@pytest.mark.skipif(__import__('importlib').util.find_spec('playwright') is None, reason='playwright is not installed')
def test_response_fork_and_turn_undo_execute_against_a_successful_turn(tmp_path):
    from playwright.sync_api import sync_playwright
    from tests.fakemodel import Step, install
    path = tmp_path/'changed.py'; path.write_text('before\n')
    ws = Workspace(roots=[tmp_path], approvals='auto')
    install(ws, [Step(tool=('create_file', {'path': str(path), 'text': 'after\n'})),
                 Step(text='Created and verified the file.')], token_delay=0)
    with _server(ws) as url, sync_playwright() as pw:
        browser = _launch_sync(pw)
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url, wait_until='networkidle')
        if page.locator('.lee-modal').count(): page.keyboard.press('Escape')
        page.fill('#agentprompt', 'create the requested file')
        page.evaluate("leeAct('agent_send')")
        page.wait_for_function("$$('#agentlog .lee-response-revision').length === 1")
        undo = page.locator('.lee-response-revision [data-undo]')
        revise = page.locator('.lee-response-revision [data-revise]')
        assert not errors, errors
        assert undo.is_enabled() and revise.is_enabled()
        # one delegated listener on the log, not a handler per button: the pane's contents are
        # replaced by every history toggle, resume and thread switch, and the log element is not
        assert page.evaluate("!!$('#agentlog')._leeRevisionsBound")
        with page.expect_response(lambda r: '/agent/turn-transaction' in r.url) as transaction_response:
            undo.click()
        assert transaction_response.value.ok, transaction_response.value.text()
        with page.expect_response(lambda r: '/agent/rollback-turn' in r.url) as response:
            page.click('#dialogyes')   # by id: the dialog's yes reads the same as the bar's button
        assert response.value.ok, response.value.text()
        page.wait_for_timeout(100)
        assert path.read_text() == 'before\n', page.locator('#status').inner_text()
        # marked, not deleted: `rollback_turn` restores files and leaves model history alone, so the
        # agent still carries the turn and the pane must not pretend it never happened
        assert page.locator('.lee-agent-turn .lee-turn-undone').count() > 0
        assert page.locator('.lee-response-revision.lee-turn-undone-bar').count() == 1
        assert '1 file restored' in page.locator('.lee-turn-undone-bar').inner_text()
        page.fill('#agentprompt', 'create the requested file again')
        page.evaluate("leeAct('agent_send')")
        page.wait_for_function('!window.lee.agentBusy')
        # `agentBusy` is cleared at the top of the `done` handler and the bar is painted below it,
        # so waiting on the flag alone races the control this test is about
        page.wait_for_function("$$('#agentlog .lee-response-revision').length === 2")
        # `.last`: the undone turn keeps its own revise button, inside the bar that explains it
        revise = page.locator('.lee-response-revision [data-revise]').last
        revise.click(); page.wait_for_selector('[data-revision]')
        page.fill('[data-revision]', 'User-authored corrected response.')
        page.click('[data-apply]'); page.wait_for_timeout(100)
        assert page.locator('.lee-agent-turn').last.locator('.lee-turn-answer').get_attribute('data-user-revised') == '1'
        assert ws.ai.current_branch_id.startswith('branch_')
        browser.close()

def test_agent_state_markdown_lint_reports_missing_charter_sections(tmp_path):
    from starlette.testclient import TestClient
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        diagnostics = client.post('/lint', json={'lang': 'markdown', 'path': '<agent-state>',
                                                  'code': '# Goal\n\nShip it.'}).json()['diagnostics']
    messages = [d['message'] for d in diagnostics]
    assert any('Hard boundaries' in m for m in messages)
    assert any('Tool practices' in m for m in messages)
    assert all(d['severity'] in {'info', 'warning', 'error'} for d in diagnostics)

HANDLER_ATTRS = ('onclick', 'oninput', 'onchange', 'onkeydown', 'onsubmit')

def test_every_name_the_painted_page_reaches_for_resolves_in_the_shared_scope():
    """The whole of what a page load promises, in one page load. The server writes handler names
    into attributes as strings and `ACTIONS` became thunks, so a renamed or dropped function is a
    dead control that no import error and no unit test ever reports. A jump hit rendered as its
    basename was `document.py` twice over. `findMatches` is the whole of the merged find pane. And
    copy path is dispatched from `lee-core.js`, defined in `lee-ide.js` and resolves its target from
    whichever menu opened, so both halves have to meet at call time.
    """
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
    """Three tags, one scope. `defer` executes them in document order, not response order, so the
    tag order is the contract, and a 404 on any of them leaves the shell painted and inert. A syntax
    error or a bad reference in any module takes the whole shared-scope bundle down from its first
    line, and every later module with it. A failed optional request is not that: `/lsp/*` answers
    400 without pyright installed, and the client carries on. One boot answers all three, because
    the listeners that catch them are the same ones.
    """
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
    """Multi-select by mouse, then one operation over the whole selection, on a real tree.

    A file row's own click handler stops there, so a held modifier has to be read in that handler
    or it never reaches the selection at all: this is the test that a meta-click marks instead of
    opening.
    """
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


_STRIPE_FIXTURE = r"""async () => {
  const settle = () => new Promise(r => setTimeout(r, 150));
  const pane = document.createElement('div');
  pane.id = 'stripe-pane';
  // `scrollbar-gutter: stable` is a bar in the flow, which is what macOS gives every WKWebView
  // under Appearance > Show scroll bars > Always, and what `.lee-md-preview` already asks for.
  // Chromium draws overlay bars on macOS whatever `::-webkit-scrollbar` says, so without this the
  // pane hands nothing back and there is nothing to reproduce.
  pane.style.cssText = 'position:fixed;top:0;left:0;width:520px;height:300px;overflow:auto;' +
                       'scrollbar-gutter:stable;background:#111';
  document.body.appendChild(pane);
  const prose = document.createElement('div');
  prose.id = 'stripe-prose';
  prose.style.cssText = 'font:13px/20px monospace;overflow-wrap:anywhere;color:#888';
  pane.appendChild(prose);
  const tall = async n => {
    prose.innerHTML = Array.from({length: 30},
      () => '<p style="margin:0">' + 'a'.repeat(n) + '</p>').join('');
    await settle();
    return prose.getBoundingClientRect().height;
  };
  // The line length that wraps at the width the bar leaves and fits at the width it gives back,
  // found rather than assumed: it is a font metric, and CI's is not this machine's.
  const one = await tall(4);
  let lo = 4, hi = 400;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; ((await tall(mid)) > one * 1.5 ? hi = mid : lo = mid); }
  const withBar = {h: await tall(hi), width: prose.clientWidth};
  pane.classList.add('has-overview'); await settle();
  const hidden = {h: prose.getBoundingClientRect().height, width: prose.clientWidth};
  pane.classList.remove('has-overview'); await settle();
  return {line: hi, withBar, hidden};
}"""

_STRIPE_WATCH = r"""async (fixture) => {
  const pane = document.getElementById('stripe-pane');
  // Between the two heights, so the pane overflows with the bar and fits without it.
  pane.style.height = (fixture.hidden.h + 200) + 'px';
  const host = document.createElement('div'); pane.appendChild(host);
  LeeCM.create(host, {doc: 'x = 1\ny = 2\n', lang: 'python',
                      settings: {overviewMode: 'always', wordWrap: 'viewport'}});
  let flips = 0, last = pane.classList.contains('has-overview');
  const mo = new MutationObserver(() => {
    const now = pane.classList.contains('has-overview');
    if (now !== last) { flips++; last = now; }
  });
  mo.observe(pane, {attributes: true, attributeFilter: ['class']});
  await new Promise(r => setTimeout(r, 1500));
  mo.disconnect();
  return {flips, shown: last, width: document.getElementById('stripe-prose').clientWidth};
}"""


def test_a_stripe_holds_its_pane_still_and_does_not_take_the_bar_back(tmp_path):
    """`has-overview` hides the bar, and where the platform draws that bar in the flow its width
    goes to the text. Wrapped text rewraps, `scrollHeight` moves, and that is the number the stripe
    decides on: it appeared, the pane got shorter, it went, the bar came back, and it flickered at
    frame rate. The rewrap here is 600px, so no hysteresis would have held it. Every editor in a
    scrolling panel resolves to that panel, so at `overviewMode: 'long'` a short one says `off`
    about the very pane a long one beside it is drawing over: the short editor's `off` was granted,
    the panel's bar came back, and the long editor's stripe stayed drawn beside it. Both watches
    take seconds of real frames, so they share one page.
    """
    async def go(pg):
        fixture = await pg.evaluate(_STRIPE_FIXTURE)
        watch = await pg.evaluate(_STRIPE_WATCH, fixture)
        await pg.evaluate("() => document.getElementById('stripe-pane').remove()")
        return fixture, watch, await pg.evaluate(_PANEL_PAIR)
    fixture, watch, got = _run(go, roots=[tmp_path])
    assert fixture['withBar']['h'] > fixture['hidden']['h'] + 100, \
        f'the fixture does not rewrap on the bar, so it proves nothing: {fixture}'
    assert watch['flips'] <= 2, f"the stripe flickered {watch['flips']} times in 1.5s"
    assert watch['width'] == fixture['withBar']['width'], \
        'showing the stripe handed the bar\'s width to the text'
    assert got['alone'] == {'bar': 0, 'held': got['alone']['held'], 'stripes': 1}, got
    assert got['alone']['held'].startswith('cm'), got
    for phase in ('alone', 'pair', 'scrolled'):
        d = got[phase]
        assert d['stripes'] == 1, f'{phase}: the long editor lost its stripe: {got}'
        assert d['bar'] == 0, f"{phase}: the panel drew its own bar beside the stripe: {got}"
    assert got['closed'] == {'bar': 0, 'held': got['closed']['held'], 'stripes': 1}, \
        f'closing the short editor must not disturb the one still drawing: {got}'


_WORK_LOG_CELL = r"""async () => {
  lee.kind = 'notebook';
  const trail = '<details><summary>what I did (1 steps)</summary>\n\n' +
    '- 🔍 Search code · offsetbox\n\n' +
    '  <details><summary>result</summary>\n\n  ```\n  [kosha] /a/b.py:1657\n  ```\n\n  </details>\n\n</details>';
  const host = document.createElement('div'); host.id = 'out-worklog'; document.body.appendChild(host);
  const cell = {id: 'worklog', cell_type: 'prompt', usage: {}, outputs: [],
                reply: 'the answer is four\n\n' + trail,
                calls: [{tool: 'search_code', kind: 'search', done: true, ok: true, secs: 0,
                         summary: 'Search code · offsetbox', args: {query: 'offsetbox'}}]};
  renderOutputs(cell);
  const reply = $('#out-worklog .lee-reply');
  for (let i = 0; i < 100 && !reply.childElementCount; i++) await new Promise(r => setTimeout(r, 50));
  const text = reply.textContent || '';
  return {text, kept: cell.reply.includes('<details>'),
          rows: $$('.lee-cell-agent-steps > details', host).length,
          replyRows: $$('details', reply).length};
}"""


_PAYLOAD_GROUP = r"""async () => {
  const md = ':::{.details}\n# what I did (2 steps)\n\n' +
    '```json\n{"name": "view_file", "args": {"path": "a/b.py"}, "result": "one"}\n```\n\n' +
    '```json\n{"name": "read_skill", "args": {"name": "write_docs"}, "result": "two"}\n```\n:::\n';
  const host = document.createElement('div'); document.body.appendChild(host);
  renderMarkdown(host, md);
  for (let i = 0; i < 100 && !$('.lee-agent-step', host); i++) await new Promise(r => setTimeout(r, 50));
  const group = $('details.lee-activity-group', host);
  return {group: !!group, summary: group ? (group.querySelector(':scope > summary').textContent || '') : '',
          rows: $$('.lee-agent-step', host).map(r => $('.lee-agent-step-copy', r).textContent.trim())};
}"""


# No element may draw its own scroll bar down the same edge a stripe is drawn on. The pane is found
# by where the bar lands, not named, because which element scrolls depends on the tab and the panel.
_STRIPE_CLASH = r"""async (plan) => {
  const desc = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
                     (el.className ? '.' + String(el.className).trim().split(/\s+/).join('.') : '');
  const bars = () => [...document.querySelectorAll('*')].filter(el =>
    el.offsetWidth - el.clientWidth > 2 && el.getBoundingClientRect().height > 60);
  const stripes = () => [...document.querySelectorAll('#nboverview, .cm-lee-overview')]
    .filter(c => !c.hidden && c.getBoundingClientRect().height > 20);
  const clash = () => stripes().flatMap(s => {
    const right = s.getBoundingClientRect().right;
    return bars().filter(b => Math.abs(b.getBoundingClientRect().right - right) < 24)
                 .map(b => desc(s) + ' beside ' + desc(b));
  });
  const pane = document.querySelector(plan.scroller);
  const seen = [], hit = new Set();
  for (let i = 0; i < plan.steps; i++) {
    pane.scrollTop = (i % 2 ? 1 : 3) * 400 + i * 90;
    await new Promise(r => setTimeout(r, 90));
    const c = clash(); c.forEach(x => hit.add(x));
    seen.push({stripes: stripes().length, clash: c.length});
  }
  return {frames: seen.length, bad: seen.filter(f => f.clash).length,
          striped: seen.filter(f => f.stripes).length, saw: [...hit],
          held: pane.dataset.leeOverview || ''};
}"""


def test_a_stripe_and_the_pane_scroll_bar_are_never_drawn_at_once(tmp_path):
    """`#editor` is the pane a file's stripe hides the bar of, and it is the pane a notebook's
    stripe hides too. The notebook painter runs on every scroll of every tab and asserted `off`,
    which took the class back off under a file's stripe: the stripe drew on regardless, the native
    bar returned beside it, and whose frame ran last decided which of the two you saw."""
    import json
    (tmp_path/'long.py').write_text(''.join(
        f'x{i} = {i}  # a comment long enough to be worth reading\n' for i in range(400)))
    src = json.loads((PARENT/'fixtures'/'leela_agent_sessions'/'agent_20260825-073912.ipynb').read_text())
    src['cells'] = [dict(c, id=f'r{r}k{k}') for r in range(3) for k, c in enumerate(src['cells'])]
    (tmp_path/'nb.ipynb').write_text(json.dumps(src))
    async def go(pg):
        # A bar in the flow, which is what macOS gives every pane under Appearance > Show scroll
        # bars > Always. Chromium draws overlay bars on macOS whatever `::-webkit-scrollbar` says,
        # so without this `#editor` hands nothing back and there is nothing to see.
        await pg.add_style_tag(content='#editor { scrollbar-gutter: stable; }')
        out = {}
        # The notebook on its own first, scrolled, which is where the fault was reported. Then the
        # file over it, so a stripe takes the pane over from one already holding it.
        for name, stripe in (('nb.ipynb', '#nboverview'), ('long.py', '#editor .cm-lee-overview')):
            await pg.evaluate("(p) => leeOpenFile(p)", str(tmp_path/name))
            await pg.wait_for_selector(stripe)
            await pg.wait_for_timeout(600)
            out[name] = await pg.evaluate(_STRIPE_CLASH, {'scroller': '#editor', 'steps': 24})
        return out
    got = _run(go, roots=[tmp_path])
    for name, d in got.items():
        assert d['striped'] == d['frames'], f'{name}: the stripe is not up for the whole watch: {d}'
        assert d['bad'] == 0, f"{name}: a bar was drawn beside the stripe in {d['bad']} of " \
                              f"{d['frames']} frames: {d['saw']}"
    assert got['nb.ipynb']['held'] == 'nb', f"the notebook's stripe does not hold its pane: {got}"
    assert got['long.py']['held'].startswith('cm'), f"the file's stripe does not hold its pane: {got}"


_PANEL_PAIR = r"""async () => {
  const panel = document.getElementById('agentlog');
  // The panel scrolls and its bar takes layout space, as it does under Show scroll bars > Always.
  panel.style.scrollbarGutter = 'stable';
  panel.innerHTML = '';
  const mount = n => {
    const host = document.createElement('div'); panel.appendChild(host);
    return LeeCM.create(host, {doc: Array.from({length: n}, (_, i) => `line ${i}`).join('\n'),
      lang: 'python', settings: {overviewMode: 'long', overviewThreshold: 120}});
  };
  const look = () => ({bar: panel.offsetWidth - panel.clientWidth,
                       held: panel.dataset.leeOverview || '',
                       stripes: [...panel.querySelectorAll('.cm-lee-overview')].filter(c => !c.hidden).length});
  mount(300);                                  // long enough for a stripe
  await new Promise(r => setTimeout(r, 500));
  const alone = look();
  const short = mount(5);                      // too short for one, and it says so about the panel
  await new Promise(r => setTimeout(r, 700));
  const pair = look();
  panel.scrollTop = 60; await new Promise(r => setTimeout(r, 400));
  const scrolled = look();
  LeeCM.destroy(short); await new Promise(r => setTimeout(r, 400));
  return {alone, pair, scrolled, closed: look()};
}"""


def test_a_draft_from_a_version_the_file_no_longer_has_is_discarded(tmp_path):
    """Drafts are keyed by path and cell id, and both survive a rewrite by another tool, so a draft
    left over an older version landed back on the file that replaced it. Recovering it also
    suppressed the reload that would have shown the new text."""
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
    """`boot` was a single sequence of awaits, so a throw anywhere in it took every step below with
    it: the pills were never repainted, the file watcher and the polls never started, and nothing
    said why. The steps below the failure are what this checks; the failure itself is reported."""
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
    """WebKit has never shipped `requestIdleCallback`, and `boot` referenced it bare, which is a
    ReferenceError rather than a falsy value. That is why the branch pill, the kernel poll, the run
    log and the file watcher all worked in Chrome and none of them worked in the packaged app."""
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

def test_an_emptied_rich_display_renders_as_nothing_not_as_its_placeholder():
    """Clearing a rich display is publishing an empty one of the same type: fastprogress ends a
    progress bar with `HTML('')`. Testing the string rather than the key sent that output down to
    its `text/plain`, which for any rich object is `<IPython.core.display.HTML object>` -- the line
    that appeared under a finished `cg.from_dir(...)`."""
    async def go(pg):
        return await pg.evaluate("""() => {
          const plain = '<IPython.core.display.HTML object>';
          const cleared = outputEl({output_type: 'display_data',
                                    data: {'text/html': '', 'text/plain': plain}});
          const shown = outputEl({output_type: 'display_data',
                                  data: {'text/html': '<b id="rich">bar</b>', 'text/plain': plain}});
          const md = outputEl({output_type: 'display_data',
                               data: {'text/markdown': '', 'text/plain': plain}});
          const only = outputEl({output_type: 'execute_result', data: {'text/plain': 'kept'}});
          return {cleared: cleared.textContent, clearedShadow: !!cleared.shadowRoot,
                  shown: shown.shadowRoot?.querySelector('#rich')?.textContent || '',
                  md: md.textContent, only: only.textContent};
        }""")
    d = _run(go)
    assert d['cleared'] == '' and d['clearedShadow'], 'the cleared display renders empty, not as a repr'
    assert d['shown'] == 'bar', 'and a display with content still renders it'
    assert d['md'] == '', 'the same holds for an emptied markdown display'
    assert d['only'] == 'kept', 'text is still what an output with only text says'

def test_a_tab_comes_back_where_it_was_scrolled_to(tmp_path):
    """Two scrollers, and only the inner one was kept: a notebook scrolls in `#editor` while each
    cell's CodeMirror sits at zero, so every switch back landed at the top of the notebook."""
    import json
    cells = [{'cell_type': 'code', 'source': [f'x = {i}\n' * 4], 'metadata': {}, 'outputs': [],
              'execution_count': None} for i in range(60)]
    (tmp_path/'long.ipynb').write_text(json.dumps(
        {'cells': cells, 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    (tmp_path/'other.py').write_text('y = 1\n')
    async def go(pg):
        await pg.evaluate("p => leeOpenFile(p)", str(tmp_path/'long.ipynb'))
        await pg.wait_for_function("() => lee.path && lee.path.endsWith('long.ipynb') && lee.cells.length > 10")
        await pg.evaluate("() => { $('#editor').scrollTop = 700; }")
        await pg.wait_for_function("() => $('#editor').scrollTop > 0")
        went = await pg.evaluate("() => $('#editor').scrollTop")
        await pg.evaluate("p => leeOpenFile(p)", str(tmp_path/'other.py'))
        await pg.wait_for_function("() => lee.path && lee.path.endsWith('other.py')")
        await pg.evaluate("p => leeOpenFile(p)", str(tmp_path/'long.ipynb'))
        await pg.wait_for_function("() => lee.path && lee.path.endsWith('long.ipynb') && lee.cells.length > 10")
        await pg.wait_for_timeout(400)
        return went, await pg.evaluate("() => $('#editor').scrollTop")
    went, back = _run(go, roots=[tmp_path])
    assert went > 100, 'precondition: the notebook was scrolled'
    assert abs(back - went) < 80, f'came back at {back}, was left at {went}'

def test_all_repos_shows_a_folder_opened_after_the_page_was(tmp_path):
    """`gitUI.repos` was fetched once per page and nothing cleared it, so under All repos the window
    that had been open longest showed the least. A browser tab that reloads on open hid it."""
    import subprocess
    first, second = tmp_path/'first', tmp_path/'second'
    for r in (first, second):
        r.mkdir(); subprocess.run(['git', 'init', '-q', str(r)], check=True)
    async def go(pg):
        await pg.evaluate("() => { leePane('left', true); leeLeft('git'); }")
        await pg.evaluate("() => { gitUI.tab = 'repos'; renderGitPanel(); }")
        await pg.wait_for_function("() => gitUI.repos && gitUI.repos.repos")
        before = await pg.evaluate("() => gitUI.repos.repos.map(r => r.root)")
        await pg.evaluate("p => post('/fs/add-root', {path: p})", str(second))
        await pg.evaluate("p => leeActivateRoot(p)", str(second))   # this leaves the pane on Files
        await pg.evaluate("() => { leeLeft('git'); gitUI.tab = 'repos'; renderGitPanel(); }")
        await pg.wait_for_function("() => gitUI.repos && gitUI.repos.repos.length > 1", timeout=8000)
        return before, await pg.evaluate("() => gitUI.repos.repos.map(r => r.root)")
    before, after = _run(go, roots=[first])
    assert len(before) == 1 and len(after) == 2, (before, after)
    assert any(r.endswith('second') for r in after), 'the folder just opened is one of the repositories'

def test_the_editor_saves_as_you_go_after_a_run_and_across_a_tab_switch(tmp_path):
    """Two ways a tab sat dirty for minutes with nothing coming to save it. A run rewrites the
    outputs, which is a change to the document, and only typing scheduled a save. Switching tabs
    cancelled the save queued for the tab being left and put nothing in its place."""
    import json
    (tmp_path/'run.ipynb').write_text(json.dumps({'cells': [
        {'cell_type': 'code', 'source': ['1 + 1'], 'metadata': {}, 'outputs': [], 'execution_count': None}],
        'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    (tmp_path/'a.py').write_text('a = 1\n')
    (tmp_path/'b.py').write_text('b = 1\n')
    async def go(pg):
        await pg.evaluate("p => leeOpenFile(p)", str(tmp_path/'run.ipynb'))
        await pg.wait_for_function("() => lee.path.endsWith('run.ipynb') && lee.cells.length")
        await pg.evaluate("() => runCell(0, false)")
        await pg.wait_for_function("() => !$('.lee-tab.active.dirty')", timeout=8000)
        ran = (tmp_path/'run.ipynb').read_text()

        await pg.evaluate("p => leeOpenFile(p)", str(tmp_path/'a.py'))
        await pg.wait_for_function("() => lee.path.endsWith('a.py')")
        await pg.evaluate("() => { LeeCM.setDoc(lee.editors.get('file'), 'a = 99\\n'); markDirty(); }")
        await pg.evaluate("p => leeOpenFile(p)", str(tmp_path/'b.py'))   # inside the autosave delay
        await pg.wait_for_function("() => lee.path.endsWith('b.py')")
        await pg.wait_for_timeout(600)
        return ran
    ran = _run(go, roots=[tmp_path])
    assert '"execution_count": 1' in ran, 'the run is on disk without anybody pressing save'
    assert (tmp_path/'a.py').read_text() == 'a = 99\n', 'the tab that was left is written, not dropped'

def test_the_overview_stripe_follows_the_pane_it_was_measured_against(tmp_path):
    """The stripe is placed by measuring the pane, and it repainted on a window resize only. Opening
    or closing the agent pane moves the notebook's right edge without one, so the stripe stayed where
    that edge used to be, hanging in the middle of the page. It was 424px adrift."""
    import json
    cells = [{'cell_type': 'code', 'source': [f'x = {i}\n' * 6], 'metadata': {}, 'outputs': [],
              'execution_count': None} for i in range(40)]
    (tmp_path/'long.ipynb').write_text(json.dumps(
        {'cells': cells, 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    async def go(pg):
        await pg.evaluate("p => leeOpenFile(p)", str(tmp_path/'long.ipynb'))
        await pg.wait_for_function("() => lee.path.endsWith('long.ipynb') && lee.cells.length > 10")
        await pg.wait_for_timeout(600)
        gap = """() => { const c = $('#nboverview'), h = $('#editor');
                 if (!c || c.hidden) return null;
                 return Math.round(h.getBoundingClientRect().right - c.getBoundingClientRect().right); }"""
        opened = await pg.evaluate(gap)
        await pg.evaluate("() => leePane('right', true)")
        await pg.wait_for_timeout(600)
        wide = await pg.evaluate(gap)
        await pg.evaluate("() => leePane('right', false)")
        await pg.wait_for_timeout(600)
        return opened, wide, await pg.evaluate(gap)
    opened, wide, closed = _run(go, roots=[tmp_path], dpr=None)
    assert opened == 0, f'the stripe starts on the edge, not {opened}px from it'
    assert wide == 0 and closed == 0, f'and stays there through a pane opening and closing: {wide}, {closed}'

def test_a_project_file_mounts_before_the_answers_it_does_not_need(tmp_path):
    """`/editor/packages` starts an interpreter to read version metadata and `/git/file` is four git
    subprocesses, and the mount awaited both before creating the editor. A pyproject was a blank box
    for as long as they took, which read as a file that would not load."""
    (tmp_path/'pyproject.toml').write_text('[project]\nname = "x"\ndependencies = ["fastcore"]\n')
    import time
    async def go(pg):
        async def slow(route):
            await asyncio.sleep(1.5)
            await route.continue_()
        await pg.route('**/editor/packages*', slow)
        await pg.route('**/git/file*', slow)
        began = time.monotonic()
        await pg.evaluate("p => leeOpenFile(p)", str(tmp_path/'pyproject.toml'))
        await pg.wait_for_function(
            "() => lee.path && lee.path.endsWith('pyproject.toml') && lee.editors.get('file')", timeout=8000)
        mounted = time.monotonic() - began
        text = await pg.evaluate("() => LeeCM.getDoc(lee.editors.get('file'))")
        # and the answers still land, on the editor they were asked for
        await pg.wait_for_function("() => lee.fileGit && lee.fileGit.ranges", timeout=8000)
        return mounted, text
    mounted, text = _run(go, roots=[tmp_path])
    assert 'name = "x"' in text, 'the file is on screen'
    assert mounted < 1.0, f'the editor waited {mounted:.2f}s for answers it does not need'

def test_opening_a_file_does_not_wait_for_the_panel_beside_it(tmp_path):
    """`leeOpenFile` awaited `leeVars`, so a switch was not done until the variables panel had
    painted: 97ms of the 113 a switch into a 100-cell notebook cost in the engine the packaged app
    runs. The panel is beside the editor, not part of it."""
    import json
    cells = [{'cell_type': 'code', 'source': [f'x{i} = {i}\n'], 'metadata': {}, 'outputs': [],
              'execution_count': None} for i in range(12)]
    (tmp_path/'nb.ipynb').write_text(json.dumps(
        {'cells': cells, 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    (tmp_path/'other.py').write_text('y = 1\n')
    async def go(pg):
        await pg.evaluate("p => leeOpenFile(p)", str(tmp_path/'other.py'))
        await pg.wait_for_function("() => lee.path.endsWith('other.py')")
        # a panel that never answers must not hold the file off the screen
        await pg.evaluate("() => { window.__realVars = window.leeVars; window.leeVars = () => new Promise(() => {}); }")
        try:
            await asyncio.wait_for(
                pg.evaluate("p => leeOpenFile(p)", str(tmp_path/'nb.ipynb')), timeout=8)
        finally:
            await pg.evaluate("() => { window.leeVars = window.__realVars; }")
        return await pg.evaluate("() => [lee.path, lee.cells.length, $$('.lee-cell').length]")
    path, n, drawn = _run(go, roots=[tmp_path])
    assert path.endswith('nb.ipynb') and n == 12, 'the switch finished'
    assert drawn == 12, 'and the notebook is on screen'

def test_the_state_box_says_why_a_save_failed_and_names_what_it_activated(tmp_path):
    """Save and activate closed the box only when the request answered. A refusal, which is what the
    packaged app gets because it cannot reach memory at all, left the box open with no reason on it
    and no toast, so the button read as dead. The badge said `state active` for every state there
    could be, so it never said which charter the agent was carrying."""
    async def go(pg):
        await pg.evaluate("() => { leePane('right', true); leeRight('agent'); }")
        await pg.route('**/agent/state/save', lambda route: asyncio.ensure_future(
            route.fulfill(status=400, content_type='application/json',
                          body='{"ok": false, "error": "memory is unavailable here"}')))
        await pg.evaluate("() => leeAgentState()")
        await pg.wait_for_selector('[data-save]')
        await pg.evaluate("() => { document.querySelector('#agentstatetext').value = '# Kosha charter\\nrules for this workspace'; }")
        await pg.click('[data-save]')
        await pg.wait_for_function("() => document.querySelector('[data-state-help]')?.textContent.includes('memory is unavailable')",
                                   timeout=8000)
        open_after_refusal = await pg.evaluate("() => !!document.querySelector('[data-save]')")

        await pg.unroute('**/agent/state/save')
        await pg.click('[data-activate]')
        await pg.wait_for_function("() => !document.querySelector('[data-activate]')", timeout=8000)
        return open_after_refusal, await pg.evaluate("() => document.querySelector('#agentnames')?.textContent")
    still_open, badge = _run(go, roots=[tmp_path])
    assert still_open, 'a refused save keeps the state in front of the person who wrote it'
    assert badge == 'Kosha charter', f'the badge names the charter, not the word active: {badge!r}'

def test_running_cells_one_after_another_stays_quick(tmp_path):
    """Two things sat in front of a run. The stream waited out a 120ms output poll for a cell that
    printed nothing, and the run before it had only marked the tab dirty, so this run flushed the
    whole notebook to disk on the way in. On gheasy's 155-cell notebook that was 172ms a cell for
    work the kernel does in two."""
    import json, statistics
    cells = [{'cell_type': 'code', 'source': [f'z{i} = {i}'], 'metadata': {}, 'outputs': [],
              'execution_count': None} for i in range(8)]
    (tmp_path/'runs.ipynb').write_text(json.dumps(
        {'cells': cells, 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    async def go(pg):
        await pg.evaluate("p => leeOpenFile(p)", str(tmp_path/'runs.ipynb'))
        await pg.wait_for_function("() => lee.path.endsWith('runs.ipynb') && lee.cells.length === 8")
        await pg.evaluate("() => runCell(0, false)")          # this one starts the kernel
        await pg.wait_for_function("() => !lee.cells[0].running", timeout=60000)
        times = []
        for i in range(1, 7):
            times.append(await pg.evaluate(
                "async i => { const t = performance.now(); await runCell(i, false); return performance.now() - t; }", i))
        return times
    times = _run(go, roots=[tmp_path])
    median = statistics.median(times)
    assert median < 90, f'a cell that assigns a number took {median:.0f}ms: {[round(t) for t in times]}'

def test_running_a_cell_writes_the_notebook_once(tmp_path):
    """Marking the tab dirty after a run left the file to the autosave delay, and the next run
    flushed it on the way in, so every cell wrote the whole notebook twice. On a 184KB notebook that
    is two writes and two git refreshes per cell, against a run that takes twelve milliseconds."""
    import json
    cells = [{'cell_type': 'code', 'source': [f'z{i} = {i}'], 'metadata': {}, 'outputs': [],
              'execution_count': None} for i in range(6)]
    (tmp_path/'runs.ipynb').write_text(json.dumps(
        {'cells': cells, 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    async def go(pg):
        await pg.evaluate("p => leeOpenFile(p)", str(tmp_path/'runs.ipynb'))
        await pg.wait_for_function("() => lee.path.endsWith('runs.ipynb') && lee.cells.length === 6")
        await pg.evaluate("() => performance.clearResourceTimings()")
        # back to back, which is what pressing run repeatedly does: the flush on the way into a run
        # and the autosave the last one queued are both still owed
        for i in range(3):
            await pg.evaluate("i => runCell(i, false)", i)
            await pg.wait_for_function(f"() => !lee.cells[{i}].running", timeout=30000)
        await pg.wait_for_timeout(1500)          # past the autosave delay, so anything owed lands
        return await pg.evaluate("""() => ({
          saves: performance.getEntriesByType('resource').filter(e => e.name.includes('/nb/save')).length,
          dirty: !!$('.lee-tab.active.dirty')})""")
    out = _run(go, roots=[tmp_path])
    assert out['saves'] == 3, f"three cells, three writes, got {out['saves']}"
    assert not out['dirty'], 'and the tab is not left waiting to be saved'

def test_any_two_tabs_can_be_read_side_by_side(tmp_path):
    """The split offered text tabs only and refused everything else, so two notebooks -- which is
    what somebody merging them wants to see -- could not be put beside each other at all."""
    import json
    cells = [{'cell_type': 'code', 'source': ['first = 1'], 'metadata': {}, 'outputs': [], 'execution_count': 3},
             {'cell_type': 'markdown', 'source': ['## a heading'], 'metadata': {}}]
    (tmp_path/'left.ipynb').write_text(json.dumps(
        {'cells': cells, 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    (tmp_path/'right.py').write_text('side = 2\n')
    async def go(pg):
        await pg.evaluate("p => leeOpenFile(p)", str(tmp_path/'left.ipynb'))
        await pg.wait_for_function("() => lee.path.endsWith('left.ipynb') && lee.cells.length === 2")
        await pg.evaluate("p => leeOpenFile(p)", str(tmp_path/'right.py'))
        await pg.wait_for_function("() => lee.path.endsWith('right.py')")
        # the notebook is offered even though the tab in front is a file
        await pg.evaluate("() => leeSplit('vertical')")
        await pg.wait_for_selector('.lee-modallist .lee-mrow')
        offered = await pg.evaluate("() => [...$$('.lee-modallist .lee-mrow')].map(b => b.textContent)")
        await pg.evaluate("""() => { const row = [...$$('.lee-modallist .lee-mrow')]
          .find(b => b.textContent.includes('left.ipynb')); row.click(); }""")
        await pg.wait_for_selector('#editor2 .lee-split-cell')
        return offered, await pg.evaluate("""() => ({
          cells: $$('#editor2 .lee-split-cell').length,
          text: $('#editor2').innerText,
          split: $('#editorstage').classList.contains('split-vertical'),
          saved: JSON.parse(localStorage.getItem('lee-editor-split') || 'null')})""")
    offered, out = _run(go, roots=[tmp_path])
    assert any('left.ipynb' in o for o in offered), f'the notebook was not offered: {offered}'
    assert out['cells'] == 2 and out['split'], out
    assert 'first = 1' in out['text'] and 'a heading' in out['text'], 'the cells are what it shows'
    assert out['saved']['path'].endswith('left.ipynb'), 'and the pane comes back on the next load'

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
    """The text panes showed a conflicted notebook as JSON with markers through it, which is neither
    a notebook nor anything a person can answer. `.ipynb` now opens the cell view instead: two sides
    per contested cell, the settled cells folded away, and no apply until every row has an answer."""
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

def test_a_delegation_row_keeps_its_kind_on_one_line(tmp_path):
    """A step's summary is a grid, and a delegation has one child more than the others: the `open`
    button. With four positional columns the kind landed in the twelve pixel chevron column, where
    `delegate` wrapped one letter to a line and the chevron dropped to a row of its own."""
    async def go(pg):
        await pg.evaluate("() => { leePane('right', true); leeRight('agent'); }")
        return await pg.evaluate("""() => {
          const host = document.createElement('div'); host.style.width = '420px';
          document.querySelector('#agentlog').appendChild(host);
          const row = document.createElement('details'); host.appendChild(row);
          renderAgentStep(row, {kind: 'delegate', id: 'x', action_id: 'x', done: false,
            summary: 'Delegate: Review the exact open source notebook /Users/somebody/code/personal/orgs/rishi/nbs/00_core.ipynb and report'});
          const meta = row.querySelector('.lee-agent-step-meta');
          const chev = row.querySelector('.lee-agent-step-chevron');
          const open = row.querySelector('.lee-agent-step-open');
          const box = e => { const r = e.getBoundingClientRect(); return {w: Math.round(r.width), h: Math.round(r.height), top: Math.round(r.top), right: Math.round(r.right)}; };
          return {meta: box(meta), chev: box(chev), open: box(open), text: meta.textContent};
        }""")
    d = _run(go, roots=[tmp_path])
    assert d['text'] == 'delegate'
    assert d['meta']['h'] <= 20, f"the kind is stacked: {d['meta']}"
    assert d['meta']['w'] >= 40, f"the kind has no room: {d['meta']}"
    assert abs(d['meta']['top'] - d['chev']['top']) <= 4, 'the chevron is on the same row, not below'
    assert d['open']['right'] <= d['meta']['right'], 'and the open button comes before the kind'

SEARCH_STUB = """() => {
  window._opened = []; window._events = [];
  window.openLocation = hit => window._opened.push(hit);
  const hits = n => Array.from({length: n}, (_, i) => ({
    path: `/w/file${i}.py`, line: i + 1, text: `def thing${i}(): pass`, kind: 'symbol',
    symbol: `thing${i}`, score: 100 - i, sources: ['rg'], callers: [],
    why: {leg: 'rg', symbol_exact: i === 2 ? 1 : 0, text: 1, leg_rank: 1 / (1 + i), demote: 0}}));
  const real = window.api;
  window.api = (url, opts) => {
    if (url.startsWith('/search?')) {
      const mode = new URLSearchParams(url.split('?')[1]).get('mode');
      return Promise.resolve({backend: mode, note: '', hits: hits(mode === 'rg' ? 4 : 3),
                              searched: ['/w'], weights: {legRg: 80, symbolExact: 120}});
    }
    if (url.startsWith('/search/signals')) return Promise.resolve(
      {ok: true, telemetry: 'local', snippets: false, dir: '/w/events', vault: '/w/search.db',
       weights: {legRg: 80, symbolExact: 120}, defaults: {legRg: 80, symbolExact: 120},
       keys: {legRg: 'rg', symbolExact: 'symbol_exact'}, summary: {searches: 0}});
    if (url === '/search/events') { window._events.push(JSON.parse(opts.body)); return Promise.resolve({ok: true}); }
    if (url === '/code/status') return Promise.resolve({ok: true, files: 1, packages: 0, graph_nodes: 0});
    return real(url, opts);
  };
  prefSet('search', 'lastMode', 'rg');
  codeSearch();
}"""

def test_the_code_search_dialog_has_one_selection_and_one_keyboard():
    """Tab used to move DOM focus rather than the mode, because the dialog's own key handler ran
    after the modal's focus trap, so Enter landed on a focused rail button whose activation the
    handler then cancelled: the mode never changed and Enter did nothing. Selection and focus are
    one thing now -- focus stays in the query box, the selection is `aria-activedescendant`, Tab
    switches the mode, Enter steps into the results and then opens, and a click previews before it
    commits.
    """
    async def go(pg):
        await pg.evaluate(SEARCH_STUB)
        await pg.fill('#cs', 'thing')
        await pg.wait_for_function("() => $$('.lee-search-result').length === 4")
        out = {}
        out['starts_on_rg'] = await pg.evaluate("() => $('.lee-searchrail-mode.active').dataset.mode")

        await pg.keyboard.press('Tab')
        await pg.wait_for_function("() => $('.lee-searchrail-mode.active').dataset.mode === 'context'")
        out['tab_keeps_focus'] = await pg.evaluate("() => document.activeElement.id")
        out['tab_marks_the_rail'] = await pg.evaluate("() => !!$('.lee-searchrail-mode.cursor')")
        await pg.wait_for_function("() => $$('.lee-search-result').length === 3")

        # Enter on the rail steps into the results. It must not open anything.
        await pg.keyboard.press('Enter')
        out['enter_stays_open'] = await pg.evaluate("() => !!$('.lee-code-search-modal') && !window._opened.length")
        out['enter_leaves_the_rail'] = await pg.evaluate("() => !$('.lee-searchrail-mode.cursor')")

        # Arrows are always the results, wherever the rail cursor was.
        await pg.keyboard.press('ArrowDown')
        await pg.keyboard.press('ArrowDown')
        out['selected'] = await pg.evaluate("() => $$('.lee-search-result').findIndex(r => r.classList.contains('sel'))")
        out['activedescendant'] = await pg.evaluate("() => $('#cs').getAttribute('aria-activedescendant')")
        out['focus_after_arrows'] = await pg.evaluate("() => document.activeElement.id")

        await pg.keyboard.press('Enter')
        out['opened_by_enter'] = await pg.evaluate("() => window._opened.map(h => h.line)")

        # A click previews. The second click on the row it is previewing is what opens it.
        await pg.evaluate(SEARCH_STUB)
        await pg.fill('#cs', 'thing')
        await pg.wait_for_function("() => $$('.lee-search-result').length === 4")
        await pg.click('.lee-search-result:nth-child(3)')
        await pg.wait_for_function("() => $('#cspreviewtitle').textContent === 'thing2'")
        out['click_previews'] = await pg.evaluate("() => window._opened.length")
        await pg.click('.lee-search-result:nth-child(3)')
        out['click_again_opens'] = await pg.evaluate("() => window._opened.map(h => h.line)")

        out['events'] = await pg.evaluate(
            "() => window._events.flatMap(b => (b.events || []).map(e => e.kind))")
        out['session'] = await pg.evaluate(
            "() => (window._events.map(b => b.session).filter(Boolean).at(-1) || {}).q || ''")
        return out
    out = _run(go)
    assert out['starts_on_rg'] == 'rg'
    assert out['tab_keeps_focus'] == 'cs', 'Tab moves the mode, not the focus'
    assert out['tab_marks_the_rail'] and out['enter_leaves_the_rail']
    assert out['enter_stays_open'], 'Enter on the rail steps into the results, it does not open one'
    assert out['selected'] == 2 and out['activedescendant'] == 'cshit2'
    assert out['focus_after_arrows'] == 'cs', 'the arrows never take the focus out of the query box'
    assert out['opened_by_enter'] == [3], 'Enter in the results opens the selected hit'
    assert out['click_previews'] == 0, 'one click previews'
    assert out['click_again_opens'] == [3], 'the second click on the previewing row opens it'
    assert 'query' in out['events'] and 'impression' in out['events'] and 'open' in out['events']
    assert out['session'] == 'thing', 'closing the dialog files the session it just ran'


def test_the_inline_reply_stays_on_screen_and_escape_closes_it(tmp_path):
    """The panel was placed while it was still a loading skeleton and never placed again, so the
    answer grew off the bottom of the window and took the discard button with it. Escape only
    reached it while the focus was still inside, which the first click elsewhere ended."""
    import json
    cells = [{'cell_type': 'code', 'source': [f'x{i} = {i}\n'], 'metadata': {}, 'outputs': [],
              'execution_count': None} for i in range(40)]
    (tmp_path/'long.ipynb').write_text(json.dumps(
        {'cells': cells, 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    async def go(pg):
        await pg.route('**/complete/selection', lambda route: route.fulfill(
            status=200, content_type='application/json',
            body=json.dumps({'ok': True, 'mode': 'summary', 'model': 'local-summary',
                             'text': '\n'.join(f'line {i} of a long suggested replacement'
                                                for i in range(60))})))
        await pg.evaluate("p => leeOpenFile(p)", str(tmp_path/'long.ipynb'))
        await pg.wait_for_selector('.lee-cell .cm-editor')
        # A cell at the bottom of the window is the case that broke: the skeleton fits below it.
        await pg.evaluate("() => focusCell(lee.cells.length - 1)")
        await pg.wait_for_timeout(120)
        await pg.evaluate("""() => {
          const view = lee.editors.get(lee.cells[lee.sel].id);
          LeeCM.setSelection(view, 0, LeeCM.getDoc(view).length);
          showSelectionHelp();
        }""")
        await pg.wait_for_selector('.lee-selection-tools')
        await pg.click('[data-summary]')
        await pg.wait_for_selector('.lee-selection-reply:not(.loading)')
        await pg.wait_for_timeout(120)
        out = await pg.evaluate("""() => {
          const p = document.querySelector('.lee-selection-reply').getBoundingClientRect();
          const f = document.querySelector('.lee-selection-reply footer').getBoundingClientRect();
          return {top: p.top, bottom: p.bottom, height: p.height, footerBottom: f.bottom,
                  h: innerHeight};
        }""")
        # Focus is moved out of the panel first: that is what used to make Escape stop working.
        await pg.evaluate("() => document.activeElement.blur()")
        out['focus_left'] = await pg.evaluate(
            "() => !document.activeElement?.closest?.('.lee-selection-reply')")
        await pg.keyboard.press('Escape')
        await pg.wait_for_timeout(60)
        out['closed'] = await pg.evaluate("() => !document.querySelector('.lee-selection-reply')")
        return out
    out = _run(go, roots=[tmp_path])
    assert out['height'] > 200, f"precondition: the reply is tall enough to overflow, got {out}"
    assert out['top'] >= 0, f"the panel starts inside the window: {out}"
    assert out['bottom'] <= out['h'], f"the panel ends inside the window: {out}"
    assert out['footerBottom'] <= out['h'], f"the discard and replace buttons are reachable: {out}"
    assert out['focus_left'], 'precondition: the focus is no longer inside the panel'
    assert out['closed'], 'Escape closes the panel after the focus has left it'


def test_running_a_cell_near_the_bottom_leaves_room_under_the_next_one(tmp_path):
    """`scrollIntoView({block: 'nearest'})` parked the next cell flush against the bottom edge, so
    shift+enter showed the reader nothing of what they had just moved to."""
    import json
    cells = [{'cell_type': 'code', 'source': [f'x{i} = {i}\n'], 'metadata': {}, 'outputs': [],
              'execution_count': None} for i in range(60)]
    (tmp_path/'long.ipynb').write_text(json.dumps(
        {'cells': cells, 'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    async def go(pg):
        await pg.evaluate("p => leeOpenFile(p)", str(tmp_path/'long.ipynb'))
        await pg.wait_for_selector('.lee-cell .cm-editor')
        room = """() => {
          const host = document.querySelector('#editor');
          const cell = document.querySelector(`.lee-cell[data-i="${lee.sel}"]`);
          const b = host.getBoundingClientRect(), r = cell.getBoundingClientRect();
          return {under: b.bottom - r.bottom, over: r.top - b.top, sel: lee.sel,
                  scroll: host.scrollTop, box: b.height};
        }"""
        # Walk down until the selection has to move the view, which is where the fault showed.
        await pg.evaluate("() => leePane('bottom', false)")
        await pg.wait_for_timeout(200)
        for _ in range(30): await pg.evaluate("() => focusCell(lee.sel + 1)")
        await pg.wait_for_timeout(160)
        out = {'stepped': await pg.evaluate(room)}
        # A cell already comfortably on screen must not move the notebook at all.
        before = await pg.evaluate("() => document.querySelector('#editor').scrollTop")
        await pg.evaluate("() => focusCell(lee.sel)")
        await pg.wait_for_timeout(120)
        out['calm'] = await pg.evaluate("() => document.querySelector('#editor').scrollTop") == before
        # And the same holds with the bottom dock taking height off the notebook.
        await pg.evaluate("() => leePane('bottom', true)")
        await pg.wait_for_timeout(250)
        for _ in range(6): await pg.evaluate("() => focusCell(lee.sel + 1)")
        await pg.wait_for_timeout(160)
        out['docked'] = await pg.evaluate(room)
        return out
    out = _run(go, roots=[tmp_path])
    for name in ('stepped', 'docked'):
        got = out[name]
        assert got['under'] >= 20, f"{name}: the cell is flush against the bottom edge: {got}"
        assert got['over'] >= 0, f"{name}: the cell is not pushed off the top: {got}"
    assert out['calm'], 'selecting a cell that is already in view does not scroll the notebook'
    assert out['docked']['box'] < out['stepped']['box'], \
        f"precondition: the dock takes height off the notebook: {out['docked']} {out['stepped']}"


def test_the_inline_reply_says_what_it_looked_at_even_when_that_is_nothing(tmp_path):
    """An empty trail rendered as no trail at all, so a reader could not tell an answer written
    without looking anything up from a panel whose trail had stopped working."""
    import json
    (tmp_path/'a.py').write_text('x = 1\n')
    async def go(pg):
        out = {}
        for name, activity in (('used', [{'tool': 'view_file'}, {'tool': 'view_file'},
                                         {'tool': 'search_code'}, {'note': 'not a call'}]),
                               ('none', [])):
            def reply(a):
                body = json.dumps({'ok': True, 'text': 'rewritten', 'mode': 'instruction',
                                   'model': 'fake', 'activity': a})
                return lambda route, *_: route.fulfill(
                    status=200, content_type='application/json', body=body)
            await pg.route('**/complete/selection', reply(activity))
            await pg.evaluate("p => leeOpenFile(p)", str(tmp_path/'a.py'))
            await pg.wait_for_selector('#editor .cm-editor')
            await pg.evaluate("""() => {
              const view = lee.editors.get('file');
              LeeCM.setSelection(view, 0, LeeCM.getDoc(view).length);
              showSelectionHelp();
            }""")
            await pg.wait_for_selector('.lee-selection-tools')
            await pg.click('[data-ask]')
            await pg.fill('.lee-selection-tools input', 'tidy this')
            await pg.click('[data-send]')
            await pg.wait_for_selector('.lee-selection-reply:not(.loading)')
            out[name] = await pg.evaluate(
                "() => document.querySelector('.lee-selection-trail')?.innerText || ''")
            await pg.evaluate("() => document.querySelector('.lee-selection-reply')?.remove()")
        return out
    out = _run(go, roots=[tmp_path])
    assert 'view_file x2' in out['used'] and 'search_code' in out['used'], out['used']
    assert 'note' not in out['used'], 'only tool calls are named'
    assert 'without looking anything up' in out['none'], out['none']

def test_the_history_panel_shows_what_the_inline_panel_was_asked_and_whether_it_was_taken(tmp_path):
    """The completion log is preference data, so it has to be readable: the instruction, the model,
    the verdict, and the accept rate the verdicts add up to."""
    from playwright.sync_api import sync_playwright
    from leela.blocks.agent.completions import completions
    completions().record([
        {'kind': 'ask', 'ask_id': '1', 'instruction': 'add a docstring', 'model': 'fast', 'lang': 'python'},
        {'kind': 'reply', 'ask_id': '1', 'model': 'fast', 'ms': 800},
        {'kind': 'replace', 'ask_id': '1'},
        {'kind': 'ask', 'ask_id': '2', 'instruction': 'rename the widget', 'model': 'slow', 'lang': 'python'},
        {'kind': 'reply', 'ask_id': '2', 'model': 'slow', 'ms': 2400},
        {'kind': 'discard', 'ask_id': '2'}])
    fake_kernels()
    ws = Workspace(roots=[tmp_path])
    with _server(ws) as url, sync_playwright() as pw:
        browser = _launch_sync(pw)
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        page.goto(url, wait_until='networkidle')
        if page.locator('.lee-modal').count(): page.keyboard.press('Escape')
        page.click('#agenthistory')
        page.wait_for_selector('.lee-completions')
        rows = page.locator('.lee-completion-log > div')
        assert rows.count() == 2
        assert 'rename the widget' in rows.nth(0).inner_text() and 'slow' in rows.nth(0).inner_text()
        assert 'rejected' in rows.nth(0).inner_text()
        assert 'add a docstring' in rows.nth(1).inner_text() and 'accepted' in rows.nth(1).inner_text()
        models = page.locator('.lee-completion-models').inner_text()
        assert 'fast' in models and '100%' in models and '0%' in models
        note = page.locator('.lee-completions .lee-weight-note').inner_text()
        assert '2 asked' in note and 'accepted 50%' in note
        assert page.locator('.lee-completions [data-completion-pref="telemetry"]').input_value() == 'on'
        assert page.locator('.lee-completions [data-completions-purge]').count() == 1
        browser.close()


def test_agent_preferences_are_kept_in_settings_and_not_only_in_this_origin(tmp_path, monkeypatch):
    """The composer's notify box, reasoning picker and history filter, across a relaunch.

    `localStorage` is per origin and the packaged app takes whatever port is free, so a preference
    kept only there was gone at the next launch and read as its default: desktop notifications a
    person switched on came back off without anyone asking for it. Each is saved to settings.json,
    holds for a browser that has never seen the origin, and a value that only ever lived in the old
    per-origin key is migrated rather than dropped.
    """
    import leela.blocks.settings.settings as settings_module
    saved = tmp_path/'settings.json'
    monkeypatch.setattr(settings_module, 'user_settings_file', lambda: saved)
    (tmp_path/'main.py').write_text('x = 1\n')
    fake_kernels()
    ws = Workspace(roots=[tmp_path])
    with serve(ws) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            page = _open(pw, url)
            # headless chromium answers `denied` however the permission is granted, and the toggle
            # is only reached with a granted one
            page.add_init_script("Object.defineProperty(Notification, 'permission',"
                                 " {get: () => 'granted'})")
            page.reload(wait_until='networkidle')
            def agent_prefs(): return page.evaluate("() => api('/settings')")['effective']['agent']
            def threads():
                page.evaluate('leeAgentThreadsToggle(true)')
                page.wait_for_selector('#agentnotify')
            page.wait_for_function('window.lee && lee.settingsMeta')
            threads()
            page.check('#agentnotify')
            page.wait_for_function('() => lee.prefs.agent.notify === true')
            page.select_option('#agentreasoning', 'high')
            page.wait_for_function("() => lee.prefs.agent.reasoning === 'high'")
            got = agent_prefs()
            assert (got['notify'], got['reasoning']) == (True, 'high'), got

            page.evaluate('localStorage.clear()')   # what a new origin looks like
            page.reload(wait_until='networkidle')
            page.wait_for_function('window.lee && lee.settingsMeta')
            page.wait_for_function("() => document.querySelector('#agentreasoning')?.value === 'high'")
            threads()
            assert page.is_checked('#agentnotify'), 'notifications came back off at a new origin'

            saved.unlink()                          # a first launch, with an old cache to take from
            page.evaluate("localStorage.clear();"
                          " localStorage.setItem('lee-agent-notify', 'on');"
                          " localStorage.setItem('lee-agent-reasoning', 'low');"
                          " localStorage.setItem('leeHistoryLeelaOnly', '0')")
            page.reload(wait_until='networkidle')
            page.wait_for_function("() => lee.prefs?.agent?.reasoning === 'low'")
            got = agent_prefs()
            assert (got['notify'], got['reasoning'], got['historyLeelaOnly']) == (True, 'low', False), got

            saved.unlink()
            page.evaluate('localStorage.clear()')
            page.reload(wait_until='networkidle')
            page.wait_for_function('() => lee.prefs?.agent?.historyLeelaOnly === true')
            assert agent_prefs()['historyLeelaOnly'] is True, 'the filter is on unless it is turned off'


SEARCH_API_STUB = SEARCH_STUB.replace("prefSet('search', 'lastMode', 'rg');\n  codeSearch();", '')

def _relaunch(page):
    "A relaunch on a port nobody chose: the settings are still there, the origin's storage is not."
    page.evaluate('localStorage.clear()')
    page.reload(wait_until='networkidle')
    page.wait_for_function('window.lee && lee.settingsMeta')

def _settings_file(monkeypatch, tmp_path):
    import leela.blocks.settings.settings as settings_module
    saved = tmp_path/'settings.json'
    monkeypatch.setattr(settings_module, 'user_settings_file', lambda: saved)
    return saved

def test_the_dotfile_toggle_is_kept_in_settings_and_not_only_in_this_origin(tmp_path, monkeypatch):
    """Showing dotfiles came back off at every launch, because the port moves and `localStorage` is
    per origin. It is `workbench.showHiddenFiles` now, it holds for a browser that has never seen
    the origin, and a `lee-tree-hidden` that only ever lived in the old key is adopted, not dropped.
    """
    _settings_file(monkeypatch, tmp_path)
    (tmp_path/'.hidden.py').write_text('x = 1\n')
    fake_kernels()
    with serve(Workspace(roots=[tmp_path])) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            page = _open(pw, url)
            page.wait_for_function('window.lee && lee.settingsMeta')
            page.evaluate("localStorage.setItem('lee-tree-hidden', '1')")
            page.reload(wait_until='networkidle')
            page.wait_for_function('() => lee.prefs?.workbench?.showHiddenFiles === true')

            _relaunch(page)
            assert page.evaluate('() => treeHidden()') is True, 'the toggle came back off at a new origin'
            assert page.evaluate("() => $('[data-action=\"show_hidden\"]').classList.contains('on')"), \
                'the button does not say what the tree is doing'

            page.evaluate('() => toggleHidden()')
            page.wait_for_function('() => lee.prefs.workbench.showHiddenFiles === false')
            _relaunch(page)
            assert page.evaluate('() => treeHidden()') is False, 'turning it off did not last either'

def test_the_markdown_view_is_kept_in_settings_and_not_only_in_this_origin(tmp_path, monkeypatch):
    """Split, rendered or edit, chosen once and held across a relaunch. The setting names the views
    `source`, `preview` and `split`; the buttons and the stage's CSS say `edit`, `rendered` and
    `split`, and a `lee-md-view` from the old key is adopted through that mapping.
    """
    _settings_file(monkeypatch, tmp_path)
    md = tmp_path/'note.md'
    md.write_text('# Title\n\ntext\n')
    fake_kernels()
    with serve(Workspace(roots=[tmp_path])) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            page = _open(pw, url)
            page.wait_for_function('window.lee && lee.settingsMeta')
            def open_md():
                page.evaluate('p => leeOpenFile(p)', str(md))
                page.wait_for_selector('.lee-md-stage')
                return page.evaluate("() => $('.lee-md-stage').dataset.view")
            page.evaluate("localStorage.setItem('lee-md-view', 'rendered')")
            assert open_md() == 'rendered', 'the view the old key held was dropped'
            page.wait_for_function("() => lee.prefs.workbench.markdownView === 'preview'")

            _relaunch(page)
            assert open_md() == 'rendered', 'the view came back at the default at a new origin'

            page.click('[data-md-view="split"]')
            page.wait_for_function("() => lee.prefs.workbench.markdownView === 'split'")
            _relaunch(page)
            assert open_md() == 'split'
            assert page.evaluate("() => $('#mdview .lee-seg.active').dataset.mdView") == 'split', \
                'the buttons and the stage disagree about the view'

def test_a_pinned_pane_is_kept_in_settings_and_not_only_in_this_origin(tmp_path, monkeypatch):
    """A pane holds its pin across a relaunch. There was a `lee-pin-<pane>` key per pane and the
    setting is one list of the panes that are pinned, so the old keys are gathered into it once.
    Pinned is still the default: an empty list is a fresh install, not two panes somebody unpinned.
    """
    _settings_file(monkeypatch, tmp_path)
    (tmp_path/'main.py').write_text('x = 1\n')
    fake_kernels()
    with serve(Workspace(roots=[tmp_path])) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            page = _open(pw, url)
            page.wait_for_function('window.lee && lee.settingsMeta')
            assert page.evaluate("() => leePinned('left') && leePinned('right')"), 'pinned is the default'
            page.evaluate("localStorage.setItem('lee-pin-left', '0')")
            page.reload(wait_until='networkidle')
            page.wait_for_function("() => JSON.stringify(lee.prefs?.workbench?.pinnedPanes) === '[\"right\"]'")

            _relaunch(page)
            assert page.evaluate("() => [leePinned('left'), leePinned('right')]") == [False, True], \
                'the unpinned pane came back pinned at a new origin'
            assert page.evaluate("() => $('#shell').classList.contains('unpinned-left')"), \
                'the shell does not lay out the way the setting says'

            page.evaluate("() => leePinPane('left')")
            page.wait_for_function("() => JSON.stringify(lee.prefs.workbench.pinnedPanes) === '[\"left\",\"right\"]'")
            _relaunch(page)
            assert page.evaluate("() => leePinned('left')") is True, 'pinning it again did not last'

def test_the_search_dialog_reopens_on_the_choices_it_closed_on(tmp_path, monkeypatch):
    """The mode, the scope and the extension filter, across a relaunch rather than only across a
    reopen. All three were `localStorage`, so a moving port reset them; they are `search.last*` now,
    and the old keys are adopted before the dialog reads anything.
    """
    _settings_file(monkeypatch, tmp_path)
    (tmp_path/'main.py').write_text('x = 1\n')
    fake_kernels()
    with serve(Workspace(roots=[tmp_path])) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            page = _open(pw, url)
            page.wait_for_function('window.lee && lee.settingsMeta')
            def open_search():
                page.evaluate(SEARCH_API_STUB)
                page.evaluate('() => { codeSearch(); }')
                page.wait_for_selector('#csexts')
                return page.evaluate("() => [$('.lee-searchrail-mode.active').dataset.mode,"
                                     " $('#csscope').value, $('#csexts').value]")
            def close_search():
                page.keyboard.press('Escape')
                page.wait_for_selector('.lee-code-search-modal', state='detached')
            page.evaluate("localStorage.setItem('lee-search-mode', 'rg');"
                          " localStorage.setItem('lee-search-scope', 'workspace');"
                          " localStorage.setItem('lee-search-exts', 'py, ts')")
            assert open_search() == ['rg', 'workspace', 'py, ts'], 'what the old keys held was dropped'
            page.wait_for_function("() => lee.prefs.search.lastExts === 'py, ts'")
            close_search()

            _relaunch(page)
            assert open_search() == ['rg', 'workspace', 'py, ts'], 'the dialog reset at a new origin'

            page.click('[data-mode="context"]')
            page.select_option('#csscope', 'project')
            page.fill('#csexts', 'md')
            close_search()
            page.wait_for_function("() => lee.prefs.search.lastExts === 'md'")
            _relaunch(page)
            assert open_search() == ['context', 'project', 'md'], 'a change made in the dialog did not last'
