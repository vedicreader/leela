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

async def _on_page(fn, roots=()):
    "Boot the app, open it in chromium, hand the page to `fn`, and return what it returns."
    fake_kernels()
    ws = Workspace(roots=list(roots), approvals='auto')
    port = _free_port()
    srv = _serve(ws, port)
    await asyncio.sleep(1.2)
    try:
        async with async_playwright() as pw:
            b = await _launch(pw)
            pg = await b.new_page()
            await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
            await pg.wait_for_function('window.lee && lee.keys.length')
            try: return await fn(pg)
            finally: await b.close()
    finally:
        srv.should_exit = True

def _run(fn, roots=()): return asyncio.run(_on_page(fn, roots))

def test_python_errors_and_warnings_get_real_codemirror_squiggles():
    async def go(pg):
        await pg.evaluate("""() => {
          const host = document.createElement('div'); host.id = 'lint-test';
          host.style.height = '120px'; document.body.appendChild(host);
          window._lintTestView = LeeCM.create(host, {doc: 'if True print(1)', lang: 'python'});
        }""")
        await pg.wait_for_selector('#lint-test .cm-lintRange-error')
        await pg.evaluate("LeeCM.setDoc(window._lintTestView, 'value is 1')")
        await pg.wait_for_selector('#lint-test .cm-lintRange-warning')
        return await pg.locator('#lint-test .cm-lintRange-warning').count()
    assert _run(go) >= 1

def test_kernel_picker_owns_focus_and_arrow_navigation():
    async def go(pg):
        await pg.evaluate("leeAct('pick_kernel')")
        await pg.wait_for_selector('.lee-modalbox[role="dialog"]')
        first = await pg.evaluate("document.activeElement?.classList.contains('lee-mrow')")
        before = await pg.evaluate("document.activeElement?.textContent")
        await pg.keyboard.press('ArrowDown')
        after = await pg.evaluate("document.activeElement?.textContent")
        await pg.keyboard.press('Tab')
        trapped = await pg.evaluate("!!document.activeElement?.closest('.lee-modalbox')")
        return first, before, after, trapped
    first, before, after, trapped = _run(go)
    assert first and before != after and trapped

def test_hyper_enter_dispatches_run_above_in_the_browser():
    async def go(pg):
        return await pg.evaluate("""() => {
          const chord = lee.keys.find(k => k.action === 'run_above').chords[0];
          const event = {isComposing:false, key:'Enter', code:'Enter', repeat:false,
            ctrlKey:true, altKey:true, shiftKey:true, metaKey:false};
          return {hyper: chord.hyper, matches: chordMatches(chord, event)};
        }""")
    result = _run(go)
    assert result == {'hyper': True, 'matches': True}

def test_every_hyper_default_matches_its_physical_browser_event():
    async def go(pg):
        return await pg.evaluate("""() => lee.keys.flatMap(k => k.chords
          .filter(c => c.hyper).map(c => ({action:k.action, code:c.code,
            matches:chordMatches(c, {isComposing:false, key:c.key, code:c.code, repeat:false,
              ctrlKey:true, altKey:true, shiftKey:true, metaKey:false})})))""")
    rows = _run(go)
    assert rows and all(r['code'] and r['matches'] for r in rows), rows

def test_results_are_folded_marked_and_dropped_when_they_go_stale():
    async def go(pg):
        await pg.evaluate("leeAct('focus_vars')")
        await pg.type('#varfilter', 'og/123')
        return await pg.input_value('#varfilter')
    assert _run(go) == 'og/123'
    async def go(pg):
        await pg.evaluate("leeAct('research')")
        await pg.wait_for_selector('.lee-research-body')
        return await pg.locator('.lee-research-command').inner_text()
    text = _run(go)
    assert 'Search' in text and 'Read URL' in text and 'Research' in text
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


def test_a_scoped_letter_still_fires_when_no_text_field_has_it():
    "The other half of contextual: a bare letter in the pane (not an input) still runs its action."
    async def go(pg):
        await pg.evaluate("leeAct('focus_files')")
        return await pg.evaluate("""() => new Promise(res => {
            const orig = ACTIONS.add_root; ACTIONS.add_root = () => { ACTIONS.add_root = orig; res(true); };
            document.dispatchEvent(new KeyboardEvent('keydown', {key:'o', bubbles:true, cancelable:true}));
            setTimeout(() => res(false), 200);
        })""")
    assert _run(go) is True

def test_platform_preferences_chord_opens_settings_from_the_editor():
    async def go(pg):
        await pg.evaluate("leeAct('focus_editor')")
        await pg.evaluate("""() => {
          const e = new KeyboardEvent('keydown', {key:',', code:'Comma',
            metaKey: MAC, ctrlKey: !MAC, bubbles:true, cancelable:true});
          (document.activeElement || document.body).dispatchEvent(e);
        }""")
        await pg.wait_for_selector('.lee-settings-modal .lee-modalbox')
        return await pg.locator('[data-pref="fontFamily"]').evaluate('el => el.tagName')
    assert _run(go) == 'SELECT'

def test_bundled_code_fonts_load_and_ligatures_reach_codemirror():
    async def go(pg):
        await pg.evaluate("leeAct('settings')")
        await pg.wait_for_selector('.lee-settings-modal #settingspreview .cm-content')
        await pg.select_option('[data-pref="fontFamily"]', 'Fira Code')
        await pg.uncheck('[data-pref="ligatures"]')
        disabled = await pg.evaluate("getComputedStyle(document.querySelector('#settingspreview .cm-content')).fontFeatureSettings")
        await pg.check('[data-pref="ligatures"]')
        return disabled, await pg.evaluate("""async () => {
          await document.fonts.ready;
          const style=getComputedStyle(document.querySelector('#settingspreview .cm-content'));
          return {loaded:document.fonts.check('13px "Fira Code"'),family:style.fontFamily,
            features:style.fontFeatureSettings};
        }""")
    disabled,result=_run(go)
    assert 'liga' in disabled and (' 0' in disabled or 'off' in disabled)
    assert result['loaded'] and 'Fira Code' in result['family']
    assert 'liga' in result['features'] and 'calt' in result['features']
    assert result['features'] != disabled

def test_user_checkbox_settings_survive_close_and_reopen(tmp_path, monkeypatch):
    import leela.blocks.settings.settings as settings_module
    monkeypatch.setattr(settings_module, 'USER_SETTINGS_FILE', tmp_path/'settings.json')
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

def test_function_keys_are_left_to_the_os_and_browser():
    async def go(pg):
        await pg.evaluate("leeAct('focus_editor')")
        return await pg.evaluate("""() => {
            let ran = false; const orig = ACTIONS.run_cell; ACTIONS.run_cell = () => { ran = true; };
            const e = new KeyboardEvent('keydown', {key:'F5', bubbles:true, cancelable:true});
            (document.activeElement || document.body).dispatchEvent(e);
            ACTIONS.run_cell = orig;
            return {ran, prevented: e.defaultPrevented};
        }""")
    assert _run(go) == {'ran': False, 'prevented': False}

def test_selected_text_ai_help_is_previewed_before_replace_or_discard():
    async def go(pg):
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
        before = await pg.evaluate("LeeCM.getDoc(lee.editors.get(lee.cells[0].id))")
        suggestion = await pg.locator('.lee-selection-reply pre').inner_text()
        await pg.click('[data-replace]')
        after = await pg.evaluate("LeeCM.getDoc(lee.editors.get(lee.cells[0].id))")
        return before, suggestion, after
    before, suggestion, after = _run(go)
    assert before == 'This is a long selected passage.'
    assert suggestion == 'concise replacement'
    assert after == 'concise replacement'

def test_platform_mod_enter_runs_the_exec_editor():
    "Exercise the reported chord on the actual focused CodeMirror exec surface."
    async def go(pg):
        await pg.evaluate("leeAct('focus_exec')")
        return await pg.evaluate("""() => {
            let ran = false; const orig = ACTIONS.exec_run; ACTIONS.exec_run = () => { ran = true; };
            const e = new KeyboardEvent('keydown', {key:'Enter', code:'Enter',
                metaKey: MAC, ctrlKey: !MAC, bubbles:true, cancelable:true});
            document.activeElement.dispatchEvent(e);
            ACTIONS.exec_run = orig;
            return {ran, prevented:e.defaultPrevented, scope:lee.scope};
        }""")
    assert _run(go) == {'ran': True, 'prevented': True, 'scope': 'exec'}

def test_platform_find_searches_the_complete_codemirror_document():
    async def go(pg):
        await pg.evaluate("""() => {
          const host = document.createElement('div'); host.id = 'search-test';
          host.style.cssText = 'height:120px;position:fixed;inset:80px 20px auto 20px'; document.body.appendChild(host);
          const lines = Array.from({length: 400}, (_, i) => i === 350 ? 'whole-file-target' : `line ${i}`);
          window._searchTestView = LeeCM.create(host, {doc: lines.join('\\n'), lang: 'python', lineNums: true});
          LeeCM.focus(window._searchTestView);
        }""")
        claimed = await pg.evaluate("""() => {
          const event = new KeyboardEvent('keydown', {key:'f', code:'KeyF', metaKey:MAC, ctrlKey:!MAC,
            bubbles:true, cancelable:true});
          document.activeElement.dispatchEvent(event); return event.defaultPrevented;
        }""")
        await pg.wait_for_selector('#search-test .cm-search input[main-field]')
        search = pg.locator('#search-test .cm-search input[main-field]')
        await search.fill('whole-file-target')
        await search.dispatch_event('change')
        await search.press('Enter')
        found = await pg.evaluate("""() => ({
          selection: LeeCM.selection(window._searchTestView).text,
          top: document.querySelector('#search-test .cm-scroller').scrollTop,
          doc: LeeCM.getDoc(window._searchTestView)
        })""")
        await search.fill('missing-target')
        await search.dispatch_event('change')
        await search.press('Enter')
        unchanged = await pg.evaluate('LeeCM.getDoc(window._searchTestView)')
        await search.press('Escape')
        closed = await pg.locator('#search-test .cm-search').count()
        merge = await pg.evaluate("""() => {
          const host = document.createElement('div'); host.id = 'merge-search-test'; host.style.height = '120px';
          document.body.appendChild(host); window._mergeSearch = LeeCM.createMerge(host, {left:'left target', right:'right target'});
          const editor = host.querySelector('.cm-editor'); editor.querySelector('.cm-content').focus();
          const event = new KeyboardEvent('keydown', {key:'f', code:'KeyF', metaKey:MAC, ctrlKey:!MAC,
            bubbles:true, cancelable:true}); editor.querySelector('.cm-content').dispatchEvent(event);
          return event.defaultPrevented;
        }""")
        await pg.wait_for_selector('#merge-search-test .cm-search input[main-field]')
        return claimed, found, unchanged, closed, merge
    claimed, found, unchanged, closed, merge = _run(go)
    assert claimed and merge and found['selection'] == 'whole-file-target'
    assert unchanged == found['doc'] and closed == 0

def test_horizontal_editor_scroll_keeps_the_gutter_fixed_and_opaque():
    async def go(pg):
        return await pg.evaluate("""() => {
          const make = (id, merge = false) => {
            const host = document.createElement('div'); host.id = id; host.style.cssText = 'width:320px;height:120px;overflow:auto'; document.body.appendChild(host);
            const doc = 'value = ' + 'x'.repeat(500);
            if (merge) LeeCM.createMerge(host, {left:doc, right:doc, settings:{wordWrap:'off'}}); else LeeCM.create(host, {doc, lineNums:true, settings:{wordWrap:'off'}});
            return [...host.querySelectorAll('.cm-editor')].map(editor => {
              const inner = editor.querySelector('.cm-scroller'), gutter = editor.querySelector('.cm-gutters');
              editor.querySelector('.cm-content').style.minWidth = '1200px';
              const scroller = inner; scroller.scrollLeft = 240;
              const before = scroller.getBoundingClientRect(), after = gutter.getBoundingClientRect(), style = getComputedStyle(gutter);
              return {delta: Math.round(after.left - before.left), background: style.backgroundColor, position: style.position, left: style.left};
            });
          };
          return [...make('gutter-test'), ...make('merge-gutter-test', true)];
        }""")
    rows = _run(go)
    assert len(rows) == 3 and all(row['position'] == 'sticky' and row['left'] == '0px' and abs(row['delta']) <= 1 for row in rows)
    assert all(row['background'] not in ('rgba(0, 0, 0, 0)', 'transparent') for row in rows)

def test_option_shift_arrows_reach_cell_movement():
    async def go(pg):
        await pg.evaluate("leeAct('focus_editor')")
        return await pg.evaluate("""() => {
            let ran = false; const orig = ACTIONS.cell_move_up; ACTIONS.cell_move_up = () => { ran = true; };
            const e = new KeyboardEvent('keydown', {key:'ArrowUp', code:'ArrowUp', altKey:true,
                shiftKey:true, bubbles:true, cancelable:true});
            (document.activeElement || document.body).dispatchEvent(e);
            ACTIONS.cell_move_up = orig;
            return {ran, prevented:e.defaultPrevented, action:lee.lastKeyEvent.action};
        }""")
    assert _run(go) == {'ran': True, 'prevented': True, 'action': 'cell_move_up'}

def test_minimising_files_hides_the_activity_rail_and_keys_completely():
    async def go(pg):
        await pg.evaluate("leePane('left', false)")
        return await pg.evaluate("""() => ({
          left: getComputedStyle(document.querySelector('#left')).display,
          leftVisibility: getComputedStyle(document.querySelector('#left')).visibility,
          keysVisibility: getComputedStyle(document.querySelector('#keytoast')).visibility,
          editorWidth: document.querySelector('#editor').getBoundingClientRect().width,
          restoreVisible: !!document.querySelector('.restore-left')?.getClientRects().length,
          shellHidden: document.querySelector('#shell').classList.contains('no-left')
        })""")
    r = _run(go)
    assert r['left'] != 'none', 'the hidden grid item must retain its column placement'
    assert r['leftVisibility'] == r['keysVisibility'] == 'hidden'
    assert r['editorWidth'] > 300 and r['restoreVisible'] and r['shellHidden']

def test_editor_contextual_keys_are_a_short_cheat_sheet_not_the_full_keymap():
    async def go(pg):
        await pg.evaluate("leeAct('focus_editor')")
        return await pg.locator('#keytoast .lee-krow').count(), await pg.locator('#keytoast').inner_text()
    count, text = _run(go)
    assert count <= 12
    assert 'run and select below' in text
    assert 'merge cell above' not in text, 'help-only commands belong in the full keymap overlay'

def test_file_scope_populates_the_contextual_keys_panel():
    async def go(pg):
        await pg.evaluate("leeAct('focus_files')")
        return await pg.locator('#keytoast').inner_text(), await pg.locator('#keyscope').inner_text()
    text, scope = _run(go)
    assert 'open / toggle folder' in text and 'next item' in text and 'new file' in text
    assert 'expand / enter folder' not in text, 'help-only movement stays in the full keymap overlay'
    assert 'files' in scope

def test_platform_mod_option_down_reaches_insert_cell_below():
    async def go(pg):
        await pg.evaluate("leeAct('focus_editor')")
        return await pg.evaluate("""() => {
            let ran = false; const orig = ACTIONS.cell_below; ACTIONS.cell_below = () => { ran = true; };
            const e = new KeyboardEvent('keydown', {key:'ArrowDown', code:'ArrowDown', altKey:true,
                metaKey: MAC, ctrlKey: !MAC, bubbles:true, cancelable:true});
            (document.activeElement || document.body).dispatchEvent(e);
            ACTIONS.cell_below = orig;
            return {ran, prevented:e.defaultPrevented, action:lee.lastKeyEvent.action};
        }""")
    assert _run(go) == {'ran': True, 'prevented': True, 'action': 'cell_below'}

def test_kernel_completion_opens_in_the_web_editor():
    "Drive CodeMirror's real completion extension, not only the Python endpoint."
    async def go(pg):
        await pg.evaluate("leeAct('focus_exec')")
        await pg.keyboard.type('d')
        await pg.keyboard.press('Alt+/')
        await pg.wait_for_selector('.cm-tooltip-autocomplete')
        return await pg.locator('.cm-tooltip-autocomplete').inner_text()
    text = _run(go)
    assert 'df' in text and 'df_norm' in text

def test_editing_panes_keep_their_cursor_safe_chords():
    "The guard must not touch the editing panes. Their editors are contenteditable, so a"
    async def go(pg):
        await pg.evaluate("leeAct('focus_editor')")
        return await pg.evaluate("""() => {
            let ran = null; const orig = ACTIONS.run_advance; ACTIONS.run_advance = () => { ran = true; };
            const e = new KeyboardEvent('keydown', {key:'Enter', shiftKey:true, bubbles:true, cancelable:true});
            (document.activeElement || document.body).dispatchEvent(e);
            ACTIONS.run_advance = orig;
            return ran === true;
        }""")
    assert _run(go) is True, 'shift+enter (run_advance) was swallowed by the text-field guard'

def test_mod_is_command_on_mac_and_control_elsewhere():
    async def go(pg):
        return await pg.evaluate("""() => {
            const fire = (init) => { const e = new KeyboardEvent('keydown',
                {bubbles:true, cancelable:true, ...init}); document.dispatchEvent(e); return e.defaultPrevented; };
            return {mac: MAC,
                    cmd_s: fire({key:'s', code:'KeyS', metaKey:true}),
                    cmd_r: fire({key:'r', code:'KeyR', metaKey:true}),
                    ctrl_s: fire({key:'s', code:'KeyS', ctrlKey:true})};
        }""")
    r = _run(go)
    assert r['cmd_s'] is r['mac']
    assert r['ctrl_s'] is (not r['mac'])
    assert r['cmd_r'] is False, 'Cmd+R remains Chrome reload and is never an app binding'

def test_file_tree_right_click_discovers_actions_and_their_chords():
    async def go(pg):
        await pg.click('#filetree', button='right')
        await pg.wait_for_selector('.lee-ctxmenu')
        return await pg.locator('.lee-ctxmenu').inner_text()
    text = _run(go)
    assert 'open file' in text and ('⌘p' in text or 'ctrl+p' in text)
    assert 'new file' in text and '\nn\n' in '\n' + text + '\n'
    assert 'open folder' in text

def test_tab_strip_keeps_some_files_visible_and_moves_the_rest_to_overflow():
    async def go(pg):
        for _ in range(7):
            await pg.evaluate("leeAct('new_notebook')")
            await pg.wait_for_timeout(80)
        await pg.wait_for_function("document.querySelectorAll('.lee-tab').length === 7")
        await pg.evaluate('layoutTabs()')
        hidden = await pg.locator('.lee-tab.overflowed').count()
        label = await pg.locator('#taboverflow').inner_text()
        await pg.click('#taboverflow')
        await pg.wait_for_selector('.lee-ctxmenu')
        rows = await pg.locator('.lee-ctxmenu .lee-menuitem').count()
        return hidden, label, rows
    hidden, label, rows = _run(go)
    assert hidden > 0 and label.startswith('+')
    assert rows == hidden

def test_indexeddb_draft_round_trip_restores_text_before_mount():
    async def go(pg):
        return await pg.evaluate("""async () => {
          await clearDrafts('recovery.py');
          await draftPut({key:'recovery.py', document:'recovery.py', payload:{path:'recovery.py', kind:'text', text:'unsaved browser work'},
                          baseDiskVersion:'old:1', updatedAt:Date.now()});
          const state = {path:'recovery.py', title:'recovery.py', kind:'text', text:'disk version'};
          const recovered = await restoreDrafts(state);
          const rows = await draftsFor('recovery.py'), base = lee.draftBases.get('recovery.py') || '';
          await clearDrafts('recovery.py');
          return {recovered, text:state.text, base, rows:rows.length};
        }""")
    assert _run(go) == {'recovered': True, 'text': 'unsaved browser work', 'base': 'old:1', 'rows': 1}

def test_identical_indexeddb_draft_is_cleaned_without_marking_the_file_recovered():
    async def go(pg):
        return await pg.evaluate("""async () => {
          await clearDrafts('already-saved.py');
          await draftPut({key:'already-saved.py', document:'already-saved.py',
            payload:{path:'already-saved.py', kind:'text', text:'same on disk'},
            baseDiskVersion:'stale:1', updatedAt:Date.now()});
          const state = {path:'already-saved.py', title:'already-saved.py', kind:'text', text:'same on disk'};
          const recovered = await restoreDrafts(state);
          return {recovered, rows:(await draftsFor('already-saved.py')).length};
        }""")
    assert _run(go) == {'recovered': False, 'rows': 0}

def test_standard_copy_is_cell_copy_only_when_source_text_is_not_selected():
    async def go(pg):
        await pg.evaluate("leeAct('new_notebook')")
        await pg.wait_for_selector('.lee-cell .cm-editor')
        return await pg.evaluate("""() => {
          const view=lee.editors.get(lee.cells[0].id), fire=()=>{
            const e=new KeyboardEvent('keydown',{key:'c',code:'KeyC',metaKey:MAC,ctrlKey:!MAC,bubbles:true,cancelable:true});
            view.contentDOM.dispatchEvent(e);return e.defaultPrevented;};
          LeeCM.setDoc(view,'alpha = 1');LeeCM.setSelection(view,0,0);lee.cellClipboard=null;
          const wholePrevented=fire(),whole=lee.cellClipboard?.cell?.source;
          LeeCM.setSelection(view,0,5);lee.cellClipboard=null;
          const textPrevented=fire(),selectedCopied=!!lee.cellClipboard;
          return {wholePrevented,whole,textPrevented,selectedCopied};
        }""")
    assert _run(go) == {'wholePrevented': True, 'whole': 'alpha = 1',
                        'textPrevented': False, 'selectedCopied': False}

def test_modifier_click_invokes_definition_navigation_in_code_editors():
    async def go(pg):
        await pg.evaluate("""() => {
          const host=document.createElement('div');host.id='definition-test';host.style.height='100px';
          document.body.appendChild(host);window._definition='';
          window._definitionView=LeeCM.create(host,{doc:'target_name = 1',lang:'python',
            onDefinition:name=>window._definition=name});
        }""")
        return await pg.evaluate("""() => {
          const r=window._definitionView.coordsAtPos(4);
          window._definitionView.contentDOM.dispatchEvent(new MouseEvent('mousedown',{
            clientX:r.left+1,clientY:(r.top+r.bottom)/2,metaKey:MAC,ctrlKey:!MAC,
            button:0,bubbles:true,cancelable:true}));
          return window._definition;
        }""")
    assert _run(go) == 'target_name'

def test_a_turn_that_fans_out_shows_one_readable_row_per_subagent():
    """The runstrip was a single 34px line whatever it held, so a root and its subagents spilled out
    of it over the conversation, and a `.lee-spacer` beside them left each row 118px of a 420px pane
    -- every row reading `openai/gpt-5.6-luna suba…` and none of them saying what it was asked."""
    async def go(pg):
        return await pg.evaluate("""() => {
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
          lee.agentRuns = []; updateAgentRunstrip({runs: []});
          return {one, many};
        }""")
    got = _run(go)
    one, many = got['one'], got['many']
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

def test_copying_a_path_reaches_the_clipboard_from_the_tree_and_the_tab():
    """The action is dispatched from `lee-core.js` and defined in `lee-ide.js`, and it resolves its
    target from whichever menu opened. Both halves have to meet at call time."""
    async def go(pg):
        await pg.evaluate("""() => {
          window.__copied = [];
          navigator.clipboard.writeText = t => { window.__copied.push(t); return Promise.resolve(); };
          window.__paths = [];
          window.api = url => { window.__paths.push(url); return Promise.resolve(
            {ok: true, absolute: '/w/proj/pkg/mod.py', relative: 'pkg/mod.py'}); };
        }""")
        return await pg.evaluate("""async () => {
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
    got = _run(go)
    assert got['dispatch'], 'both actions are reachable from the shared dispatch table'
    assert got['fromTree'] == ['pkg/mod.py', '/w/proj/pkg/mod.py'], got['fromTree']
    assert got['asked'], 'the server is asked, since only it knows the open folders'
    assert got['fromTab'] == ['pkg/mod.py'], got['fromTab']

def test_a_refused_call_reads_as_the_person_on_every_surface():
    """Rejecting an approval makes ramabana a synthetic `user_steering` call, and every surface --
    the live timeline, a replayed turn, a notebook prompt cell -- drew it as an ordinary tool row:
    `user_steering(instruction='The user rejected this tool c…')`, with the direction actually
    given hidden behind a chevron."""
    async def go(pg):
        return await pg.evaluate("""() => {
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
    got = _run(go)
    assert got['said']['copy'] == 'You use the other file instead', 'what the person actually said'
    assert got['bare']['copy'] == 'You rejected that call'
    assert got['stopped']['copy'] == 'You stopped the turn'
    assert all(got[k]['meta'] == 'steered' for k in ('bare', 'said', 'stopped'))
    assert all('lee-agent-steer-step' in got[k]['cls'] for k in ('bare', 'said', 'stopped'))
    assert 'Do not retry this call' in got['said']['detail'], 'the whole instruction is still there to open'
    assert 'lee-agent-steer-step' not in got['tool']['cls'], 'an ordinary tool row is untouched'
    assert got['tool']['copy'] == 'run_shell(command)' and got['tool']['meta'] == '1.2s'

def test_a_steer_is_drawn_inside_the_turn_it_interrupted():
    """Appended to the log instead, the card sat below every chunk and tool row that followed --
    a note stuck to the bottom of the pane rather than a message in the conversation."""
    async def go(pg):
        return await pg.evaluate("""() => {
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
    got = _run(go)
    assert got['inTurn'][1] == 'use the other file', 'the steer sits between the prose either side of it'
    assert len(got['inTurn']) == 3 and got['inTurn'][2].startswith('lee-'), 'and the work after it follows'
    assert not got['stranded'], 'rather than after the whole turn'
    assert got['afterwards'] == 'and afterwards', 'with the log as the fallback when no turn is open'

def test_a_turn_folds_away_and_a_checkpoint_is_never_folded_behind():
    """Every turn painted the same flat run of siblings into one log, so there was nothing to fold
    and nothing that knew where a turn ended. Folding a turn the agent is blocked on would hide the
    only controls that let it continue, so a card holding a proposed checkpoint refuses.
    """
    async def go(pg):
        return await pg.evaluate("""() => {
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
    got = _run(go)
    assert got['cards'] == 2 and got['titles'][0] == 'rename the widget'
    assert got['folded'] and got['hidden'] and got['pressed'] == 'false'
    assert 't1' in (got['remembered'] or ''), 'a fold is remembered per conversation'
    assert got['blockedStayedOpen'], 'fold-all leaves the turn holding an unanswered checkpoint'
    assert got['unfolded']

def test_every_painted_turn_carries_what_can_still_be_done_to_it():
    """`addResponseRevision` ran only from the live `done` handler, so undo, restore and revise
    disappeared on every history toggle, resume, thread switch and resync. A turn that ended on a
    tool call has no prose and its files are still its own, so the bar is not gated on an answer.
    """
    async def go(pg):
        return await pg.evaluate("""() => {
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
    got = _run(go)
    assert got['n'] == 3, 'including the turn that ended on a tool call and left no prose'
    assert [r['turn'] for r in got['rows']] == ['t1', 't2', 't3']
    assert got['rows'][0]['off'] == [], 'everything this turn can still do is offered'
    assert got['rows'][1]['off'] == ['Edit what agent remembers'], 'no answer to edit, but files to restore'
    assert len(got['rows'][2]['off']) == 3, 'a turn this process holds no boundary for offers nothing'
    assert 'not run in this session' in got['rows'][2]['why'], 'and says which of the two reasons it is'

def test_two_turns_in_one_card_keep_their_own_controls():
    """A feed left following after `done` paints a turn another tab or the CLI started into the card
    already on screen, so one card can hold two answers. Resolving a bar to the first `.lee-turn-answer`
    in its card had the second turn's Undo and Revise acting on the first turn's text.
    """
    async def go(pg):
        return await pg.evaluate("""() => {
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
    got = _run(go)
    assert [b['turn'] for b in got] == ['t1', 't2']
    assert got[0]['raw'] == 'the first answer' and got[1]['raw'] == 'the second answer'

def test_a_saved_turn_replays_the_steer_that_interrupted_it():
    "A steer reaches the pane twice: live on the feed, and again whenever the turn is rebuilt."
    async def go(pg):
        return await pg.evaluate("""() => {
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
    got = _run(go)
    assert 'lee-user-message' in got['kinds'], 'the steer is a message from the person, drawn as one'
    at = got['kinds'].index('lee-user-message')
    assert 0 < at < len(got['kinds']) - 1, 'in the place it happened, not before or after the turn'
    assert 'use the other file' in got['text'][at]

def test_steering_taken_straight_to_a_waiting_approval_is_still_shown_as_a_message():
    """A steer typed against a pending approval answers it there and then, so it is never queued.
    There was no card to un-queue, and the transcript showed the agent obeying an instruction it
    never recorded anyone giving."""
    async def go(pg):
        return await pg.evaluate("""() => {
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
    got = _run(go)
    assert got['drawn'] == 1, 'what the person said is in the log'
    assert got['deduped'] == 1, 'and the same steer arriving twice is one message, not two'
    assert 'use the other file' in got['text']
    assert got['queued'] and got['cancellable'], 'a queued steer is still cancellable'
    assert got['kept'] and not got['stillCancellable'], 'once taken it is a message, not a pending one'

def test_the_caret_and_the_open_panels_are_remembered_past_the_window_closing():
    """`sessionStorage` dies with the window, so every reopened tab came back at line 1 and the
    right panel and dock always reset to agent and exec. All three belong to `localStorage`."""
    async def go(pg):
        return await pg.evaluate("""() => {
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
    got = _run(go)
    assert got['stored'][0][0] == '/w/notes.py', 'keyed by the file, so every tab has its own'
    assert got['stored'][0][1]['pos'] > 0 and 'scroll' in got['stored'][0][1]
    assert got['session'] is None, 'and it no longer goes somewhere that dies with the window'
    assert got['right'] == 'vars' and got['dock'] == 'term'

def test_a_minimised_pane_stays_minimised_even_though_its_tab_was_restored():
    "`leeDock` opens the bottom pane to show its tab, so the restore has to run before the hiding."
    async def go(pg):
        return await pg.evaluate("""() => {
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
    got = _run(go)
    assert got['dock'] and got['right'], 'the tabs the last session had open are the ones showing'
    assert got['hidden'], 'and a pane it had minimised is still minimised'

def test_the_cursor_carries_the_whole_dotted_chain_to_a_lookup():
    """`fastcore.test` is a module and nothing declares one, so the last name alone found whichever
    package happened to have a `def test`. Only leftwards: on `fastcore` the answer is the package.
    """
    async def go(pg):
        await pg.evaluate("""() => {
          const host = document.createElement('div'); host.id = 'dotted-test';
          host.style.height = '100px'; document.body.appendChild(host);
          window._dottedView = LeeCM.create(host, {doc: 'from nbdev.showdoc import show_doc\\nfastcore.test.test_eq(a.b().c)\\n', lang: 'python'});
        }""")
        return await pg.evaluate("""() => {
          const v = window._dottedView, at = n => { LeeCM.setCursor(v, n); return dottedAtCursor(v); };
          const line2 = v.state.doc.line(2).from, text = v.state.doc.line(2).text;
          return {
            showdoc: at(v.state.doc.line(1).text.indexOf('showdoc') + 2),
            nbdev: at(v.state.doc.line(1).text.indexOf('nbdev') + 2),
            imported: at(v.state.doc.line(1).text.indexOf('show_doc') + 2),
            sub: at(line2 + text.indexOf('test.') + 1),
            leaf: at(line2 + text.indexOf('test_eq') + 1),
            root: at(line2 + 1),
            call: at(line2 + text.indexOf('c)') + 1)
          };
        }""")
    got = _run(go)
    assert got['showdoc'] == 'nbdev.showdoc' and got['nbdev'] == 'nbdev', 'leftwards only'
    assert got['imported'] == 'show_doc', 'the name being imported has no chain of its own'
    assert got['sub'] == 'fastcore.test' and got['leaf'] == 'fastcore.test.test_eq'
    assert got['root'] == 'fastcore'
    assert got['call'] == 'c', 'a call is not a module, so the chain stops at the bracket'

def test_recent_files_is_an_mru_switcher_with_a_reliable_browser_chord():
    async def go(pg):
        await pg.evaluate("leeAct('new_notebook')")
        await pg.wait_for_selector('.lee-tab')
        await pg.evaluate("leeAct('recent_tabs')")
        await pg.wait_for_selector('.lee-recent-list')
        heading = await pg.locator('.lee-mhead').inner_text()
        binding = await pg.evaluate("lee.keys.find(k => k.action === 'recent_tabs').key")
        return heading, binding
    heading, binding = _run(go)
    assert 'Recent files' in heading
    assert binding == 'mod+e'

def test_expandable_expression_results_open_in_a_floating_value_lens():
    async def go(pg):
        await pg.evaluate("""() => openValueLens({name:'result', type:'list', value:"[{'path': '/tmp/a'}]",
          is_container:true, accessor:['_']}, document.querySelector('#kpill'), "_hits[0]['path']")""")
        await pg.wait_for_selector('.lee-value-lens')
        before = await pg.locator('.lee-value-row').count()
        await pg.click('.lee-value-row')
        await pg.wait_for_function("document.querySelector('.lee-value-kids')?.textContent.includes('no children')")
        return before, await pg.locator('.lee-inline-head').inner_text()
    count, heading = _run(go)
    assert count == 1
    assert "_hits[0]['path']" in heading

_SEARCH_HIT = ('{"path": "/tmp/engine.py", "line": 17, "text": "def runtime_engine():\\n    return 42",'
               ' "kind": "%s", "symbol": %s, "score": 220%s}')
_SEARCH_STREAM = (
    'event: start\ndata: {"legs": ["symbols", "rg"], "searched": ["/tmp/proj"]}\n\n'
    'event: leg\ndata: {"leg": "symbols", "hits": ['
    + (_SEARCH_HIT % ('symbol', '"runtime_engine"', ', "sources": ["symbols"]')) + ']}\n\n'
    'event: leg\ndata: {"leg": "rg", "hits": [' + (_SEARCH_HIT % ('text', 'null', '')) + ']}\n\n'
    'event: done\ndata: {}\n\n')

def test_unified_code_search_previews_highlighted_code_and_opens_locations():
    async def go(pg):
        await pg.route('**/code/status', lambda route: route.fulfill(status=200, content_type='application/json',
          body='{"ok":true,"files":274,"packages":152,"graph_nodes":8088,"stale_files":0}'))
        await pg.route('**/search/stream?*', lambda route: route.fulfill(
            status=200, content_type='text/event-stream', body=_SEARCH_STREAM))
        await pg.evaluate("leeAct('code_search')")
        await pg.fill('#cs', 'runtime_engine')
        await pg.wait_for_selector('.lee-search-result')
        await pg.wait_for_selector('.lee-search-preview .cm-editor')
        modes = await pg.locator('.lee-searchrail').inner_text()
        preview = await pg.locator('.lee-search-preview').inner_text()
        scope_note = await pg.locator('#csscopenote').inner_text()
        rows = await pg.locator('.lee-search-result').count()
        await pg.click('.lee-search-result')
        location = await pg.evaluate('lee.pendingLocation')
        return modes, preview, scope_note, rows, location, await pg.locator('.lee-code-search-modal').count()
    modes, preview, scope_note, rows, location, still_open = _run(go)
    assert modes.splitlines()[:2] == ['all', '1']
    assert rows == 1
    assert 'runtime_engine' in preview and 'symbols + rg' in preview
    assert scope_note == 'searched proj'
    assert (location['path'], location['line']) == ('/tmp/engine.py', 17)
    assert still_open == 0

def test_research_memory_is_a_first_class_right_panel():
    async def go(pg):
        await pg.route('**/memory/info', lambda route: route.fulfill(status=200, content_type='application/json', body='''{
          "path":"/tmp/memory.db","documents":1,"nodes":3,"chunks":4,"note":"ready",
          "items":[{"id":"abc","title":"Agent memory","source":"https://example.com","kind":"page","pages":1,"meta":{}}]
        }'''))
        await pg.click('[data-right="memory"]')
        await pg.click('[data-memory-view="sources"]')
        await pg.wait_for_selector('.lee-memory-doc')
        return await pg.locator('#memorystatus').inner_text(), await pg.locator('#memorybody').inner_text()
    status_text, body = _run(go)
    assert '1 docs' in status_text and '3 sections' in status_text
    assert 'Agent memory' in body and 'example.com' in body

def test_memory_purge_can_select_bad_results_or_clear_the_corpus():
    async def go(pg):
        await pg.route('**/memory/info', lambda route: route.fulfill(status=200, content_type='application/json', body='''{
          "path":"/tmp/memory.db","documents":2,"nodes":5,"chunks":8,"note":"ready","items":[
            {"id":"bad","title":"Bad result","source":"https://bad.example","kind":"page","pages":1,"meta":{}},
            {"id":"good","title":"Useful result","source":"https://good.example","kind":"page","pages":1,"meta":{}}
          ]}'''))
        await pg.click('[data-right="memory"]')
        await pg.click('[data-memory-view="sources"]')
        await pg.wait_for_selector('.lee-memory-doc')
        await pg.click('.lee-memory-nav .warn'); await pg.wait_for_selector('.lee-memory-purge-list')
        return await pg.locator('.lee-memory-purge-list').inner_text(), await pg.locator('[data-all]').inner_text()
    rows, all_label = _run(go)
    assert 'Bad result' in rows and 'Useful result' in rows
    assert all_label == 'purge everything'


def test_open_folder_is_an_in_app_browser_not_a_native_prompt():
    async def go(pg):
        await pg.evaluate("leeAct('add_root')")
        await pg.wait_for_selector('.lee-folderlist')
        await pg.wait_for_function("document.querySelector('#folderpath').value.length > 0")
        return await pg.input_value('#folderpath'), await pg.locator('.lee-folderrow').count()
    path, rows = _run(go)
    assert path.startswith('/') and rows >= 0

pytestmark = pytest.mark.slow

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

def test_every_family_repaints_and_resolves_a_mode(proj_web_th):
    ws = Workspace(roots=[proj_web_th])
    with serve(ws) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            page = _open(pw, url)
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

def test_following_the_system_flips_without_a_reload(proj_web_th):
    "The point of `system`: a machine that turns dark at sunset turns leela dark too."
    ws = Workspace(roots=[proj_web_th])
    with serve(ws) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = _launch_sync(pw)
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            page.emulate_media(color_scheme='light')
            page.goto(url, wait_until='networkidle')
            if page.locator('.lee-modal').count(): page.keyboard.press('Escape')
            page.evaluate("applyTheme('gruvbox:system')")
            assert page.evaluate('document.documentElement.dataset.mode') == 'light'
            light = _bg(page)
            page.emulate_media(color_scheme='dark')
            page.wait_for_function("document.documentElement.dataset.mode === 'dark'")
            assert _bg(page) != light

def test_density_and_palette_are_independent(proj_web_th):
    "The ask: cursor's tightness with leela's colours. Header height must move, colours must not."
    ws = Workspace(roots=[proj_web_th])
    with serve(ws) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            page = _open(pw, url)
            head = lambda: page.evaluate("document.querySelector('.lee-header').getBoundingClientRect().height")
            page.evaluate("applyTheme('leela:dark:relaxed')")
            relaxed, bg = head(), _bg(page)
            page.evaluate("applyTheme('leela:dark:tight')")
            assert page.evaluate('document.documentElement.dataset.density') == 'tight'
            assert head() < relaxed
            assert _bg(page) == bg
            page.reload(wait_until='networkidle')
            assert page.evaluate('document.documentElement.dataset.density') == 'tight'

def test_a_pre_family_preference_is_migrated_not_reset(proj_web_th):
    ws = Workspace(roots=[proj_web_th])
    with serve(ws) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            page = _open(pw, url)
            page.evaluate("localStorage.setItem('lee-theme', 'dark')")
            page.reload(wait_until='networkidle')
            assert page.evaluate('document.documentElement.dataset.theme') == 'leela'
            assert page.evaluate('document.documentElement.dataset.mode') == 'dark'
            assert page.evaluate('document.documentElement.dataset.density') == 'relaxed'
            page.wait_for_function("localStorage.getItem('lee-theme') === 'leela:dark:relaxed'")

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

def test_the_picker_lists_families_with_a_variant_control(proj_web_th):
    ws = Workspace(roots=[proj_web_th])
    with serve(ws) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            page = _open(pw, url)
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

pytestmark = pytest.mark.slow


pytest.importorskip('playwright.sync_api')

@pytest.fixture
def proj_web_va(tmp_path):
    (tmp_path/'notes.md').write_text('# Retrieval\n\nDurable notes about recall and ranking.\n')
    return tmp_path

def _vault(page):
    "The vault view, which lives behind the right pane's memory tab."
    page.click('.lee-righttab[data-right="memory"]')
    page.click('[data-memory-view="vault"]')
    page.wait_for_selector('#vaultpanel')

def test_clipping_a_tree_file_opens_the_vault_on_its_own_job(proj_web_va):
    "The whole affordance: right-click a file, clip it, and watch it land."
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

def test_review_is_asked_for_and_answers_even_when_there_is_nothing_to_drop(proj_web_va):
    "Review swaps a list in; a shelf the ranker has no opinion about says so."
    from playwright.sync_api import sync_playwright
    ws = Workspace(roots=[proj_web_va])
    ws.memory.clip([proj_web_va/'notes.md'])
    with serve(ws) as url, sync_playwright() as pw:
        page = _open(pw, url)
        _vault(page)
        assert page.locator('#vaulttidy').inner_text() == '', 'nothing is scored until asked for'
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

def test_a_document_in_the_panel_opens_as_a_reader_tab(proj_web_va):
    "The whole path a person takes: memory → vault → a document → its sections."
    from playwright.sync_api import sync_playwright
    ws = Workspace(roots=[proj_web_va])
    ws.memory.clip([proj_web_va/'notes.md'])
    with serve(ws) as url, sync_playwright() as pw:
        page = _open(pw, url)
        _vault(page)
        page.wait_for_selector('.lee-vault-doc')
        assert 'notes' in page.locator('.lee-vault-doc').first.inner_text()
        page.click('.lee-vault-doc')
        page.wait_for_selector('.lee-vault-reader')
        assert page.locator('.lee-vault-section').count() >= 1, 'the section rail is drawn'
        page.wait_for_function("document.querySelector('.lee-vault-text')?.innerText.trim().length > 0")
        assert 'ranking' in page.locator('.lee-vault-text').inner_text().lower()
        assert 'no pattern found' in page.locator('.lee-vault-reader').inner_text()
        assert page.locator('.lee-tab', has_text='notes').count() >= 1, 'it is a tab, not a modal'

pytestmark = pytest.mark.slow


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
    async def runtime(tab=None): return selected
    ws.runtime = runtime
    ws.inspector = lambda tab=None: None
    with TestClient(ide_app(ws)) as client:
        result = client.get('/vars').json()
    assert result['runtime'] == 'http://selected-runtime:live'
    assert result['inspector'] == 'dhrishti' and result['python'] == selected.python
    assert result['groups'][0]['nodes'][0]['name'] == 'answer'


pytestmark = pytest.mark.slow


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

def test_every_inline_handler_names_a_function_that_exists():
    """The server writes handler names into attributes as strings, so a renamed or dropped
    function is a dead control that no import error and no unit test ever reports.
    """
    async def go(pg):
        for op in ("leeRight('agent')", "leeRight('git')", "leeRight('vars')", "leePane('left', true)"):
            await pg.evaluate(op)
        await pg.wait_for_timeout(800)
        return await pg.evaluate("""(attrs) => {
          const skip = new Set(['if','return','for','while','switch','catch','typeof','function',
                                'new','delete','await','throw','void']);
          const named = attrs.flatMap(a => [...document.querySelectorAll(`[${a}]`)]
            .flatMap(el => [...el.getAttribute(a).matchAll(/(^|[^.\\w$])([A-Za-z_$][\\w$]*)\\s*\\(/g)]
              .map(m => m[2])));
          return [...new Set(named)].filter(n => !skip.has(n) && typeof window[n] !== 'function').sort();
        }""", list(HANDLER_ATTRS))
    dead = _run(go)
    assert dead == [], f'inline handlers with no such function: {dead}'

def test_the_shell_boots_and_paints_its_panels_without_a_page_error():
    """A syntax error or a bad reference in any module takes the whole shared-scope bundle down
    from its first line, and every later module with it. A failed optional request is not that:
    `/lsp/*` answers 400 without pyright installed, and the client carries on.
    """
    fake_kernels()
    ws = Workspace(roots=[], approvals='auto')
    port = _free_port()
    srv = _serve(ws, port)
    errors, resources = [], []
    async def go():
        await asyncio.sleep(1.2)
        async with async_playwright() as pw:
            b = await _launch(pw)
            pg = await b.new_page()
            pg.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
            pg.on('console', lambda m: m.type == 'error' and (
                resources if 'Failed to load resource' in m.text else errors).append(m.text))
            await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
            await pg.wait_for_function('window.lee && lee.keys.length')
            for op in ("leeRight('agent')", "leeRight('git')", "leeRight('vars')", 'showHelp()'):
                await pg.evaluate(op)
                await pg.wait_for_timeout(400)
            await b.close()
    try: asyncio.run(go())
    finally: srv.should_exit = True
    assert errors == [], f'the client reported {len(errors)} javascript problems: {errors[:5]}'

def test_every_dispatch_entry_is_callable_across_the_bundles():
    """`ACTIONS` became thunks so the client could be served as three script tags. A thunk hides
    a missing function until someone presses the key, so resolve every entry in the live page:
    each must be callable, and each name it wraps must exist in the shared scope.
    """
    async def go(pg):
        return await pg.evaluate("""() => {
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
    got = _run(go)
    assert got['count'] > 60, got['count']
    assert got['notFn'] == [], got['notFn']
    assert got['missing'] == [], got['missing']

def test_the_bundles_are_all_served_and_tagged_in_execution_order():
    """Three tags, one scope. `defer` executes them in document order, not response order, so
    the tag order is the contract; a 404 on any of them leaves the shell painted and inert.
    """
    fake_kernels()
    ws = Workspace(roots=[], approvals='auto')
    port = _free_port()
    srv = _serve(ws, port)
    bad, tags = [], []
    async def go():
        await asyncio.sleep(1.2)
        async with async_playwright() as pw:
            b = await _launch(pw)
            pg = await b.new_page()
            def note(r):
                name = r.url.split('?')[0].rsplit('/', 1)[-1]
                if name in IDE_BUNDLES and r.status != 200: bad.append((name, r.status))
            pg.on('response', note)
            await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
            await pg.wait_for_function('window.lee && lee.keys.length')
            tags.extend(await pg.evaluate("""(names) => [...document.scripts]
                .map(s => s.src.split('?')[0].split('/').pop())
                .filter(n => names.includes(n))""", list(IDE_BUNDLES)))
            await b.close()
    try: asyncio.run(go())
    finally: srv.should_exit = True
    assert bad == [], bad
    assert tags == list(IDE_BUNDLES), f'tag order {tags}, expected {list(IDE_BUNDLES)}'

def test_a_jump_hit_says_which_module_or_which_folder_it_is_in():
    """A package hit is its dotted module; two project files with one name grow their label until
    they differ. Rendered as the basename, `document.py` from chonkie and from prompt_toolkit were
    the same row twice, and this repository has 25 files called `app.py`.
    """
    async def go(pg):
        return await pg.evaluate("""() => {
          const pkg = [{path: '/v/site-packages/chonkie/types/document.py', line: 23, module: 'chonkie.types.document'},
                       {path: '/v/site-packages/prompt_toolkit/document.py', line: 79, module: 'prompt_toolkit.document'}];
          const proj = [{path: '/w/leela/blocks/git/app.py', line: 4},
                        {path: '/w/leela/blocks/fs/app.py', line: 9},
                        {path: '/w/leela/blocks/agent/turns.py', line: 1}];
          return {pkg: pkg.map(h => hitWhere(h, pkg)), proj: proj.map(h => hitWhere(h, proj))};
        }""")
    got = _run(go)
    assert got['pkg'] == ['chonkie.types.document', 'prompt_toolkit.document'], got['pkg']
    assert got['proj'] == ['git/app.py', 'fs/app.py', 'turns.py'], got['proj']
    assert len(set(got['pkg'])) == 2 and len(set(got['proj'])) == 3, 'every row is distinguishable'

def test_one_find_pane_matches_over_a_document_and_over_every_cell():
    """`findMatches` is the whole of the merged pane: escaping, whole word, regex, and the guard
    against an empty match spinning forever. Driven over cells because an unmounted cell needs no
    editor, and the document path is the same walk over one entry.
    """
    async def go(pg):
        return await pg.evaluate("""() => {
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
    got = _run(go)
    assert got['plain'] == 6, 'area, the parameter, both r of return, and the two in the body'
    assert got['word'] == 3, 'only the standalone r, so not the ones inside area and return'
    assert got['cased'] == 0, 'match case means no hit for R'
    assert got['regex'] == 1
    assert got['broken'] is None, 'a pattern that will not compile is not the same as no matches'
    assert 0 < got['empty'] < 5000, 'an empty match must advance rather than spin'
    assert got['cells'] == [0, 0, 1, 1, 1, 1], 'two hits in the first cell, four in the second'
    assert got['closed'] == 0


def test_indent_outdent_and_reindent_run_on_a_cell_and_on_a_file():
    """The real chords on the real focused CodeMirror, in both surfaces the user works in. All three
    commands already existed in `defaultKeymap`; what is new is Leela naming them, and a named chord
    is routed by Leela's own keydown handler instead, so the routing is what needs proving."""
    async def go(pg):
        chord = """(key, code, hyper) => {
            const e = new KeyboardEvent('keydown', {key, code, metaKey: MAC,
                ctrlKey: !MAC || hyper, altKey: !!hyper, shiftKey: !!hyper,
                bubbles: true, cancelable: true});
            document.activeElement.dispatchEvent(e);
            return e.defaultPrevented;
        }"""
        await pg.evaluate("leeAct('new_notebook')")
        await pg.wait_for_selector('.lee-cell .cm-editor')
        cell = await pg.evaluate("""(chordSrc) => {
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
        # The file editor: the same view identity `curEditor` and the router both resolve for a
        # python file, which is the other surface indent has to serve.
        file = await pg.evaluate("""(chordSrc) => {
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
        return cell, file
    cell, file = _run(go)
    assert cell['prevented'] is True, 'Leela owns the chord once it names it'
    assert cell['matched'] == 'indent_more' and cell['back'] == 'indent_less', \
        'the router matched Leela\'s bindings, not CodeMirror\'s own'
    assert cell['indented'] == '    x = 1', f"cell indent gave {cell['indented']!r}"
    assert cell['outdented'] == 'x = 1', f"cell outdent gave {cell['outdented']!r}"
    assert file['prevented'] is True
    assert file['matched'] == 'indent_selection', 'hyper+] is Leela\'s alone; CodeMirror binds mod+alt+\\'
    assert file['reindented'] == 'def f():\n    x = 1\n', f"reindent gave {file['reindented']!r}"


def test_the_chord_splits_a_cell_into_one_cell_per_def():
    "The keybinding, on a real cell, through the real edit route: what the user actually presses."
    async def go(pg):
        await pg.evaluate("leeAct('new_notebook')")
        await pg.wait_for_selector('.lee-cell .cm-editor')
        await pg.evaluate("""() => {
          const v = lee.editors.get(lee.cells[0].id);
          LeeCM.setDoc(v, '#| export\\nimport os\\n\\ndef f():\\n    return 1\\n\\nclass C: pass\\n');
          LeeCM.focus(v);
        }""")
        prevented = await pg.evaluate("""() => {
          const e = new KeyboardEvent('keydown', {key: '/', code: 'Slash', altKey: true,
            shiftKey: true, bubbles: true, cancelable: true});
          document.activeElement.dispatchEvent(e);
          return {prevented: e.defaultPrevented, matched: lee.lastKeyEvent.action};
        }""")
        await pg.wait_for_function('lee.cells.length === 3')
        return prevented, await pg.evaluate("lee.cells.map(c => c.source)")
    event, sources = _run(go)
    assert event == {'prevented': True, 'matched': 'cell_split_symbols'}
    assert sources == ['#| export\nimport os',
                       '#| export\ndef f():\n    return 1',
                       '#| export\nclass C: pass']


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


def test_a_code_block_in_rendered_markdown_has_no_scrollbar_of_its_own(tmp_path):
    """Every fenced block in rendered markdown is a real CodeMirror editor with a copy header, and a
    page of them each drew a thin vertical bar. Two causes: the box was `lines * 19px`, so wherever
    the real line height was not 19px it was a few pixels short of its own text, and the overview
    stripe ran inside each one, hiding and unhiding that bar as it decided whether it was needed."""
    async def go(pg):
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
        return await pg.evaluate("""() => [...document.querySelectorAll('#md-code-test .lee-code-editor')]
            .map(el => {
              const s = el.querySelector('.cm-scroller');
              return {lines: el.querySelectorAll('.cm-line').length,
                      over: s.scrollHeight - s.clientHeight,
                      stripe: !!el.querySelector('.cm-lee-overview'),
                      marked: el.classList.contains('has-overview') ||
                              !!el.querySelector('.has-overview')};
            })""")
        return None
    blocks = _run(go, roots=[tmp_path])
    assert len(blocks) == 4
    for b in blocks:
        assert b['over'] <= 0, f"a {b['lines']}-line block overflows by {b['over']}px, so it draws a bar"
        assert not b['stripe'], 'a read-only snippet gets no overview stripe'
        assert not b['marked'], 'and nothing hides a bar on it'


def test_the_snippet_box_is_not_short_of_its_own_text(tmp_path):
    """The box was `lines * 19px`, and a line is `--lee-code-size` by `--lee-code-line-height`,
    which are set from the editor preferences and are 13px by 1.5 by default: 19.5px. Every block
    was half a pixel per line short of its own text, which is a scroll bar with a full-height thumb,
    and more so for anyone who had changed either preference."""
    async def go(pg):
        return await pg.evaluate("""() => {
          const s = getComputedStyle(document.documentElement);
          const size = parseFloat(s.getPropertyValue('--lee-code-size'));
          const ratio = parseFloat(s.getPropertyValue('--lee-code-line-height'));
          const host = document.createElement('div');
          host.style.cssText = 'position:fixed;inset:40px 20px auto 20px;width:600px';
          document.body.appendChild(host);
          mountCodeSurface(host, Array.from({length: 12}, (_, i) => `x${i} = ${i}`).join('\\n'), 'python');
          const line = host.querySelector('.cm-line');
          return {size, ratio, drawn: line.getBoundingClientRect().height,
                  assumed: 19, over: (() => {
                    const sc = host.querySelector('.cm-scroller');
                    return sc.scrollHeight - sc.clientHeight;
                  })()};
        }""")
    d = _run(go, roots=[tmp_path])
    assert d['size'] * d['ratio'] != d['assumed'], \
        f"a line is {d['size']}x{d['ratio']}={d['size'] * d['ratio']}px, which the old box called 19"
    assert d['drawn'] > d['assumed'], f"a drawn line is {d['drawn']}px, taller than the 19 assumed"
    assert d['over'] <= 0, f'and the box no longer overflows by {d["over"]}px'
