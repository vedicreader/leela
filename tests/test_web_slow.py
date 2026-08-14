"The web IDE in a browser: keys, themes, the vault reader and interventions."

import pytest

pytestmark = pytest.mark.slow

pytestmark = pytest.mark.slow

import asyncio
import socket
import threading

import pytest

pytest.importorskip('playwright.async_api')
from playwright.async_api import async_playwright   # noqa: E402

from leela.blocks.runtime.kernels import KernelPool                # noqa: E402
from leela.app import ide_app                   # noqa: E402
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

async def _on_page(fn):
    "Boot the app, open it in chromium, hand the page to `fn`, and return what it returns."
    fake_kernels()
    ws = Workspace(roots=[], approvals='auto')
    port = _free_port()
    srv = _serve(ws, port)
    await asyncio.sleep(1.2)
    try:
        async with async_playwright() as pw:
            try: b = await pw.chromium.launch()
            except Exception as e: pytest.skip(f'no chromium for playwright: {e}')
            pg = await b.new_page()
            await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
            await pg.wait_for_function('window.lee && lee.keys.length')
            try: return await fn(pg)
            finally: await b.close()
    finally:
        srv.should_exit = True

def _run(fn): return asyncio.run(_on_page(fn))

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

def test_typing_in_a_filter_box_types_rather_than_firing_actions():
    "The reported bug: focus the variable filter, type keys that are vars-scope bindings, get text."
    async def go(pg):
        await pg.evaluate("leeAct('focus_vars')")
        await pg.type('#varfilter', 'og/123')
        return await pg.input_value('#varfilter')
    assert _run(go) == 'og/123'

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

def test_research_actions_open_the_in_app_workspace_not_native_prompts():
    async def go(pg):
        await pg.evaluate("leeAct('research')")
        await pg.wait_for_selector('.lee-research-body')
        return await pg.locator('.lee-research-command').inner_text()
    text = _run(go)
    assert 'Search' in text and 'Read URL' in text and 'Research' in text

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

from leela.workspace import Workspace

pytest.importorskip('playwright.sync_api')

FAMILIES = ['leela', 'cursor', 'vscode', 'jetbrains', 'solarized', 'gruvbox', 'nord', 'dracula']

@pytest.fixture
def proj_web_th(tmp_path):
    (tmp_path/'main.py').write_text('x = 1\n')
    return tmp_path

def _open(pw, url):
    page = pw.chromium.launch(headless=True).new_page(viewport={'width': 1440, 'height': 900})
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
            browser = pw.chromium.launch(headless=True)
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

def test_the_bundle_parses(proj_web_th):
    "`node` is blocked here, so the browser is the syntax check."
    ws = Workspace(roots=[proj_web_th])
    with serve(ws) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            page = pw.chromium.launch(headless=True).new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(f'{url}/leestatic/nothing-here')
            page.add_script_tag(url=f'{url}/leestatic/lee-ide.js')
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

import pytest

from conftest import serve

from leela.workspace import Workspace

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

import asyncio

from leela.core.ui import bar
from leela.app import _assigned_lines, _inline_values, ide_app
from leela.workspace import Workspace, _EnvClient

from tests.assets import JS, CSS, SERVER, EDITOR

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

def test_final_expression_gets_a_minimal_inline_result_marker():
    outputs = [{'output_type': 'execute_result', 'data': {'text/plain': 'x    int64\ny    object'}}]
    values = _inline_values('df.dtypes', [], outputs)
    assert values == [{'line': 1, 'name': 'df', 'value': 'x    int64\ny    object',
                       'type': 'result', 'shape': None, 'dtype': None,
                       'is_grid': False, 'is_container': False, 'accessor': ['_']}]

def test_the_runtime_picker_controls_execution_not_only_the_variable_tree():
    ws = Workspace(roots=[])
    picked = type('Picked', (), {'base': 'http://picked'})()
    ws.pool.kernels['picked'] = picked
    ws.watch_env(picked.base)
    assert asyncio.run(ws.runtime()) is picked

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

def test_variable_header_does_not_duplicate_the_sort_dropdown_with_a_button():
    assert 'sort' not in {b.action for b in bar('vars')}
    assert "id='varsort'" in SERVER

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

def test_picking_a_kernel_returns_variables_to_that_kernel():
    ws = Workspace(roots=[])
    ws.watch_env('http://127.0.0.1:9999')
    asyncio.run(ws.set_kernel(kind='ipykernel', restart=False))
    assert ws.env_base is None

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

def test_run_picker_connects_the_variable_panel_to_the_started_runtime():
    run_app = JS[JS.index('async function runApp'):JS.index('/* Which live namespace')]
    assert "await post('/envs/watch', {base: s.base})" in run_app
    assert 'paintEnv(s.label)' in run_app

def test_code_cells_show_run_state_and_inline_pills():
    assert 'setCellState(c, \'running\')' in JS
    assert "setCellState(c, r.ok ? 'done' : 'error'" in JS
    assert 'LeeCM.setInlineValues(v, r.inline || [])' in JS
    assert '.lee-cell-state.done' in CSS
    assert '.cm-lee-inline-value' in CSS
    assert 'lee-inline-open' in EDITOR and 'lee-inline-open' in JS
    assert 'openValueLens' in JS and 'copy value' in JS
    assert 'lee-inline-popover' in JS and '.lee-value-lens' in CSS

def test_variable_polling_coalesces_slow_refreshes_instead_of_flooding_the_page():
    vars_fn = JS[JS.index('async function leeVars'):JS.index('function varRow')]
    assert 'if (lee.varsBusy)' in vars_fn
    assert 'lee.varsPending = true' in vars_fn
    assert 'finally {' in vars_fn and 'queueMicrotask(leeVars)' in vars_fn

def test_rishi_markdown_display_outputs_stream_render_and_can_become_cells():
    output = JS[JS.index('function outputEl'):JS.index('function paintSel')]
    run = JS[JS.index('async function runCell'):JS.index('async function askCell')]
    assert "data['text/markdown']" in output
    assert "renderMarkdown(d, data['text/markdown'])" in output
    assert "d.classList.add('lee-md-output')" in output
    assert "postEvents('/nb/run/stream'" in run and "event === 'output'" in run
    assert 'edit as markdown cell' in JS

def test_large_outputs_are_folded_before_the_browser_parses_them():
    assert 'MAX_OUTPUT_CHARS = 60000' in JS
    assert 'render large rich output' in JS
    assert 'show ${(text.length - MAX_OUTPUT_CHARS).toLocaleString()} more characters' in JS

def test_inline_values_disappear_as_soon_as_the_source_changes():
    field = EDITOR[EDITOR.index('const inlineField'):EDITOR.index('export function setInlineValues')]
    assert 'if (tr.docChanged) values = Decoration.none' in field

pytestmark = pytest.mark.slow

import pytest

from conftest import serve as _server

from leela.app import ide_app
from leela.workspace import Workspace

@pytest.mark.skipif(__import__('importlib').util.find_spec('playwright') is None, reason='playwright is not installed')
def test_browser_can_change_control_open_layered_state_and_find_agent_commands(tmp_path):
    from playwright.sync_api import sync_playwright
    ws = Workspace(roots=[tmp_path])
    with _server(ws) as url, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
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
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url, wait_until='networkidle')
        if page.locator('.lee-modal').count(): page.keyboard.press('Escape')
        page.fill('#agentprompt', 'create the requested file')
        page.evaluate("leeAct('agent_send')")
        page.wait_for_function('!window.lee.agentBusy')
        undo = page.locator('.lee-response-revision [data-undo]')
        revise = page.locator('.lee-response-revision [data-revise]')
        assert not errors, errors
        assert undo.is_enabled() and revise.is_enabled()
        assert undo.evaluate('(el) => typeof el.onclick') == 'function', undo.evaluate('(el) => el.outerHTML')
        with page.expect_response(lambda r: '/agent/turn-transaction' in r.url) as transaction_response:
            undo.click()
        assert transaction_response.value.ok, transaction_response.value.text()
        with page.expect_response(lambda r: '/agent/rollback-turn' in r.url) as response:
            page.get_by_role('button', name='restore files').click()
        assert response.value.ok, response.value.text()
        page.wait_for_timeout(100)
        assert path.read_text() == 'before\n', page.locator('#status').inner_text()
        revise.click(); page.wait_for_selector('[data-revision]')
        page.fill('[data-revision]', 'User-authored corrected response.')
        page.click('[data-apply]'); page.wait_for_timeout(100)
        assert page.locator('.lee-agent-reply').last.get_attribute('data-user-revised') == '1'
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

def test_action_protocol_routes_and_response_revision_are_present():
    from inspect import getsource
    source = getsource(ide_app)
    for route in ('/agent/branches', '/agent/fork', '/agent/revise', '/agent/rollback-turn',
                  '/agent/state/template', '/agent/state/bootstrap', '/agent/state/suggest',
                  '/agent/state/diagnostics', '/agent/state/update', '/agent/compaction'):
        assert route in source
