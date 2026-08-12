"""The web frontend's keymap, exercised against the real client JS in a real browser.

`test_keymap.py` proves the table is coherent. The browser handler is a separate contract --
it dispatches in `lee-ide.js`, from
the Python key table as JSON, with scope tracking and a clear idea of when a chord
is the browser's and when it is the IDE's. Two things it got wrong, and these tests pin:

- a bare-letter binding (`o` opens a folder, `/` filters) fired even while the cursor was
  in a native text field, so typing into a filter box ran IDE actions instead of typing;
- on a Mac, Cmd matched every `ctrl+` binding, so Cmd+R/Cmd+S/Cmd+Space were the IDE's
  rather than the browser's and OS's.

These boot the actual app with a fake kernel and drive it with Playwright, which is the
only place the JS runs at all.
"""

import asyncio
import socket
import threading

import pytest

pytest.importorskip('playwright.async_api')
from playwright.async_api import async_playwright   # noqa: E402

from leela.kernels import KernelPool                # noqa: E402
from leela.web.app import ide_app                   # noqa: E402
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
        await pg.evaluate("leeAct('focus_vars')")            # scope -> vars, cursor -> #varfilter
        await pg.type('#varfilter', 'og/123')                # o=sort, g=grid, /=filter, 1/2/3=profiles
        return await pg.input_value('#varfilter')
    assert _run(go) == 'og/123'


def test_a_scoped_letter_still_fires_when_no_text_field_has_it():
    "The other half of contextual: a bare letter in the pane (not an input) still runs its action."
    async def go(pg):
        await pg.evaluate("leeAct('focus_files')")           # scope -> files, cursor -> the tree (a div)
        # `o` is add_root in files; we only need to know the handler ran, not that a picker opened.
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
    import leela.settings as settings_module
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
    # Settings default to All languages; only deviations from defaults are persisted.
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
    """Exercise the reported chord on the actual focused CodeMirror exec surface."""
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
    """Drive CodeMirror's real completion extension, not only the Python endpoint."""
    async def go(pg):
        await pg.evaluate("leeAct('focus_exec')")
        await pg.keyboard.type('d')
        await pg.keyboard.press('Alt+/')
        await pg.wait_for_selector('.cm-tooltip-autocomplete')
        return await pg.locator('.cm-tooltip-autocomplete').inner_text()
    text = _run(go)
    assert 'df' in text and 'df_norm' in text


def test_editing_panes_keep_their_cursor_safe_chords():
    """The guard must not touch the editing panes. Their editors are contenteditable, so a
    naive `is this a text field?` check would swallow `shift+enter` (run and advance) -- the
    scope, not the DOM node, is what says a chord is safe here."""
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


def test_unified_code_search_previews_highlighted_code_and_opens_locations():
    async def go(pg):
        await pg.route('**/code/status', lambda route: route.fulfill(status=200, content_type='application/json',
          body='{"ok":true,"files":274,"packages":152,"graph_nodes":8088,"stale_files":0}'))
        await pg.route('**/search?*', lambda route: route.fulfill(status=200, content_type='application/json', body='''{
          "backend":"all","note":"rg + symbols + fts + ann","hits":[{
            "path":"/tmp/engine.py","line":17,"text":"def runtime_engine():\\n    return 42",
            "kind":"symbol","symbol":"runtime_engine","score":220,"sources":["symbols","rg"]
          }]}'''))
        await pg.evaluate("leeAct('code_search')")
        await pg.fill('#cs', 'runtime_engine')
        await pg.wait_for_selector('.lee-search-result')
        await pg.click('.lee-search-result')
        await pg.wait_for_selector('.lee-search-preview .cm-editor')
        modes = await pg.locator('.lee-searchmodes').inner_text()
        preview = await pg.locator('.lee-search-preview').inner_text()
        await pg.dblclick('.lee-search-result')
        location = await pg.evaluate('lee.pendingLocation')
        return modes, preview, location
    modes, preview, location = _run(go)
    assert modes.splitlines()[0] == 'context'
    assert 'runtime_engine' in preview and 'symbols + rg' in preview
    assert location == {'path': '/tmp/engine.py', 'line': 17}


def test_research_memory_is_a_first_class_right_panel():
    async def go(pg):
        await pg.route('**/memory/info', lambda route: route.fulfill(status=200, content_type='application/json', body='''{
          "path":"/tmp/memory.db","documents":1,"nodes":3,"chunks":4,"note":"ready",
          "items":[{"id":"abc","title":"Agent memory","source":"https://example.com","kind":"page","pages":1,"meta":{}}]
        }'''))
        await pg.click('[data-right="memory"]')
        # Memory opens on agent notes; research sources are the adjacent view.
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
