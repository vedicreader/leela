"""Switching editors does not detach the runtime or erase in-flight notebook state."""

import json
import re

from starlette.testclient import TestClient

from leela.app import ide_app
from leela.workspace import Workspace

from tests.assets import JS


def _nb(path, source):
    path.write_text(json.dumps({'nbformat': 4, 'nbformat_minor': 5, 'metadata': {}, 'cells': [{
        'cell_type': 'code', 'source': source, 'metadata': {}, 'outputs': [],
        'execution_count': None, 'id': path.stem,
    }]}))


def test_explicit_reload_invalidates_the_notebook_cache_and_reads_agent_changes(tmp_path):
    a = tmp_path/'a.ipynb'; _nb(a, 'value = "before"')
    ws = Workspace(roots=[tmp_path]); ws.open(a)
    with TestClient(ide_app(ws)) as client:
        assert client.get('/tab/state').json()['cells'][0]['source'] == 'value = "before"'
        _nb(a, 'value = "agent edit"')
        # The normal state endpoint intentionally preserves the live editor object.
        assert client.get('/tab/state').json()['cells'][0]['source'] == 'value = "before"'
        assert client.post('/tab/reload', json={'path': str(a)}).json()['ok']
        assert client.get('/tab/state').json()['cells'][0]['source'] == 'value = "agent edit"'


def test_browser_drafts_survive_reload_independently_of_server_memory():
    assert "const DRAFT_DB = 'leela-editor-drafts'" in JS
    assert 'indexedDB.open(DRAFT_DB, 1)' in JS
    assert 'await restoreDrafts(st)' in JS
    assert "window.addEventListener('pagehide', snapshotCurrentDraft)" in JS
    assert 'await clearDrafts(path)' in JS


def test_identical_crash_drafts_are_cleaned_instead_of_triggering_conflict_autosave():
    restore = JS[JS.index('async function restoreDrafts'):JS.index('window.lee = lee')]
    assert 'let recovered = false' in restore
    assert 'if (!recovered) await clearDrafts(documentKey)' in restore
    assert "row.payload.text !== st.text" in restore


def test_keep_draft_pauses_automatic_conflict_retries_until_an_explicit_save():
    conflict = JS[JS.index('function showSaveConflict'):JS.index('async function saveAllTabs')]
    assert 'heldSaveConflicts.add(lee.path)' in conflict
    assert "automatic retries paused" in conflict
    autosave = JS[JS.index('function scheduleAutoSave'):JS.index('function markDirty')]
    assert 'lee.heldSaveConflicts.has(lee.path)' in autosave


def test_client_reload_clears_both_document_caches_before_mounting():
    reload_code = JS[JS.index('async function takeDiskVersion'):JS.index('async function stopAgent')]
    assert "await post('/tab/reload', {path})" in reload_code
    assert 'lee.buffers.delete(key)' in reload_code
    assert 'await takeDiskVersion(e.path)' in reload_code


def test_browser_watch_detects_an_external_file_write(tmp_path):
    a = tmp_path/'a.py'; a.write_text('before = True\n')
    ws = Workspace(roots=[tmp_path]); ws.open(a)
    with TestClient(ide_app(ws)) as client:
        before = client.get('/tab/watch').json()
        a.write_text('after = True\n')
        after = client.get('/tab/watch').json()
    assert before['path'] == str(a)
    assert before['disk_version'] != after['disk_version']
    assert 'setInterval(watchOpenFile, 1000)' in JS
    watch = JS[JS.index('async function watchOpenFile'):JS.index('async function takeDiskVersion')]
    assert "classList.contains('dirty')" in watch and 'await takeDiskVersion(lee.path)' in watch


def test_same_named_files_in_different_roots_keep_absolute_identity(tmp_path):
    one,two=tmp_path/'ramabana',tmp_path/'rishi';one.mkdir();two.mkdir()
    a,b=one/'00_core.ipynb',two/'00_core.ipynb';_nb(a,'RAMABANA');_nb(b,'RISHI')
    ws=Workspace(roots=[one,two])
    with TestClient(ide_app(ws)) as client:
        client.post('/tab/open',params={'path':str(a)})
        client.post('/tab/open',params={'path':str(b)})
        assert client.get('/tab/state').json()['cells'][0]['source']=='RISHI'
        client.post('/tab/open',params={'path':str(a)})
        assert client.get('/tab/state').json()['cells'][0]['source']=='RAMABANA'
    assert len(ws.tabs)==2 and {t.path for t in ws.tabs}=={str(a.resolve()),str(b.resolve())}
    from fasthtml.common import to_xml
    from leela.app import _tab_bar
    tabs=to_xml(_tab_bar(ws));assert 'ramabana/00_core.ipynb' in tabs and 'rishi/00_core.ipynb' in tabs
    assert 'leeOpenFile' in JS and 'pendingFocusPath === st.path' in JS
    assert 'version!==openFileVersion' in JS and "mountTab(path)" in JS


def test_split_state_reads_an_inactive_file_without_changing_active_tab(tmp_path):
    a,b=tmp_path/'a.py',tmp_path/'b.py';a.write_text('A');b.write_text('B')
    ws=Workspace(roots=[tmp_path]);ws.open(a);ws.open(b);ws.activate(0)
    with TestClient(ide_app(ws)) as client:
        state=client.get('/tab/state',params={'path':str(b)}).json()
    assert state['text']=='B' and ws.tab.path==str(a.resolve())
    assert 'function leeSplit' in JS and 'mountSecondary' in JS and 'lee-editor-split' in JS


def test_tab_state_reuses_the_live_notebook_instead_of_reloading_disk(tmp_path):
    a, b = tmp_path/'a.ipynb', tmp_path/'b.py'
    _nb(a, 'value = "live buffer"')
    b.write_text('pass\n')
    ws = Workspace(roots=[tmp_path]); ws.open(a)
    with TestClient(ide_app(ws)) as client:
        assert client.get('/tab/state').json()['cells'][0]['source'] == 'value = "live buffer"'
        client.post('/tab/open', params={'path': str(b)})
        _nb(a, 'value = "changed on disk"')
        client.post('/tab/select', params={'i': 0})
        assert client.get('/tab/state').json()['cells'][0]['source'] == 'value = "live buffer"'


def test_remove_root_route_never_deletes_the_folder(tmp_path):
    root = tmp_path/'project'; root.mkdir(); kept = root/'keep.py'; kept.write_text('x = 1\n')
    ws = Workspace(roots=[root])
    with TestClient(ide_app(ws)) as client:
        assert client.post('/fs/remove-root', json={'path': str(root)}).json()['ok']
    assert root.exists() and kept.read_text() == 'x = 1\n'
    assert root not in ws.fs.roots


def test_variable_tree_keeps_separate_view_state_per_runtime():
    vars_code = JS[JS.index('async function leeVars'):JS.index('function varRow')]
    assert 'lee.varStates.set(lee.varRuntime' in vars_code
    assert 'lee.varStates.get(runtime)' in vars_code
    assert 'open: new Set(lee.varOpen)' in vars_code
    assert "filter: $('#varfilter')?.value" in vars_code


def test_save_refuses_to_overwrite_a_disk_change_after_the_draft_started(tmp_path):
    a = tmp_path/'a.py'; a.write_text('before = True\n')
    ws = Workspace(roots=[tmp_path]); ws.open(a)
    with TestClient(ide_app(ws)) as client:
        state = client.get('/tab/state').json()
        client.post('/tab/buffer', json={'path': str(a), 'kind': 'text', 'text': 'browser = True\n',
                                         'base_disk_version': state['disk_version']})
        a.write_text('external = True\n')
        refused = client.post('/nb/save', json={'text': 'browser = True\n',
                                                'base_disk_version': state['disk_version']})
        assert refused.status_code == 409
        assert a.read_text() == 'external = True\n'
        forced = client.post('/nb/save', json={'text': 'browser = True\n',
                                               'base_disk_version': state['disk_version'], 'force': True})
        assert forced.status_code == 200
    assert a.read_text() == 'browser = True\n'


def test_unsaved_text_file_buffer_survives_a_tab_round_trip(tmp_path):
    a, b = tmp_path/'a.py', tmp_path/'b.py'
    a.write_text('disk = True\n'); b.write_text('pass\n')
    ws = Workspace(roots=[tmp_path]); ws.open(a)
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state')
        client.post('/tab/buffer', json={'path': str(a), 'kind': 'text', 'text': 'unsaved = True\n'})
        client.post('/tab/open', params={'path': str(b)})
        client.post('/tab/select', params={'i': 0})
        assert client.get('/tab/state').json()['text'] == 'unsaved = True\n'
    assert a.read_text() == 'disk = True\n'


def test_save_all_persists_inactive_tab_buffers(tmp_path):
    a, b = tmp_path/'a.py', tmp_path/'b.py'
    a.write_text('old_a = True\n'); b.write_text('old_b = True\n')
    ws = Workspace(roots=[tmp_path]); ws.open(a); ws.open(b)
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state')
        client.post('/tab/buffer', json={'path': str(a), 'kind': 'text', 'text': 'new_a = True\n'})
        client.post('/tab/buffer', json={'path': str(b), 'kind': 'text', 'text': 'new_b = True\n'})
        response = client.post('/tabs/save-all')
        assert response.status_code == 200 and response.json()['saved'] == 2
    assert a.read_text() == 'new_a = True\n'
    assert b.read_text() == 'new_b = True\n'


def test_stale_empty_buffer_cache_cannot_blank_server_cell_source_after_run():
    mount = JS[JS.index('function mountCell'):JS.index('function renderOutputs')]
    run = JS[JS.index('async function runCell'):JS.index('async function askCell')]
    assert 'lee.dirtyBuffers.has(key) ? lee.buffers.get(key) : c.source' in mount
    assert 'Object.assign(c, r.cell)' in run
    assert 'lee.cells[i] = r.cell' not in run


def test_remounted_running_cells_restore_their_local_indicators():
    mount = JS[JS.index('function mountCell'):JS.index('function renderOutputs')]
    assert 'if (c.running)' in mount
    assert "setCellState(c, 'running'" in mount
    assert "notice.hidden = false" in mount


def test_a_finished_background_run_does_not_paint_the_new_tab():
    run = JS[JS.index('async function runCell'):JS.index('async function askCell')]
    ask = JS[JS.index('async function askCell'):JS.index('/* ---------------------------------------------------------- running files */')]
    assert 'lee.path === runPath' in run and 'lee.cells[i]?.id === cellId' in run
    assert 'lee.path !== runPath' in ask and 'lee.cells[i]?.id !== cellId' in ask


def test_cell_runs_carry_document_and_cell_identity_and_reject_stale_positions(tmp_path):
    notebook = tmp_path/'ordered.ipynb'; _nb(notebook, 'class Definition: pass')
    ws = Workspace(roots=[tmp_path]); ws.open(notebook)
    with TestClient(ide_app(ws)) as client:
        state = client.get('/tab/state').json()
        response = client.post('/nb/run/stream', json={
            'path': str(notebook), 'i': 0, 'id': 'a-cell-that-moved', 'source': 'pass',
        })
    assert response.status_code == 409
    assert 'id: cellId' in JS and "path: runPath || lee.tabKey || ''" in JS


# ---------------------------------------------------------------- the tab strip itself

def test_a_tab_can_be_dragged_to_a_new_position_and_the_same_document_stays_active(tmp_path):
    "The strip is the user's arrangement of their own work, so the order is server state."
    a, b, c = (tmp_path/f'{n}.py' for n in 'abc')
    for p in (a, b, c): p.write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path])
    for p in (a, b, c): ws.open(p)
    ws.activate(0)                                  # a.py is on screen
    with TestClient(ide_app(ws)) as client:
        assert client.post('/tab/move?i=0&j=2').status_code == 200
    assert [t.title for t in ws.tabs] == ['b.py', 'c.py', 'a.py']
    assert ws.tab.title == 'a.py', 'the dragged tab is still the one being edited'


def test_moving_a_tab_nowhere_or_out_of_range_is_a_no_op(tmp_path):
    a, b = (tmp_path/f'{n}.py' for n in 'ab')
    for p in (a, b): p.write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path])
    for p in (a, b): ws.open(p)
    before = list(ws.tabs)
    ws.move_tab(1, 1); ws.move_tab(9, 0); ws.move_tab(0, 9)
    assert [t.title for t in ws.tabs] == [t.title for t in ([before[1], before[0]])], 'only the clamped move applied'


def test_middle_click_closes_a_tab_the_way_a_browser_does():
    assert "document.addEventListener('auxclick'" in JS
    aux = JS[JS.index("document.addEventListener('auxclick'"):]
    aux = aux[:aux.index("document.addEventListener('dragstart'")]
    assert 'e.button !== 1' in aux, 'middle button only'
    assert 'closeTerm(term.dataset.term)' in aux, 'terminal tabs too'
    assert 'closeTab(+tab.dataset.i)' in aux
    assert 'e.preventDefault()' in aux, 'button 1 pastes or autoscrolls otherwise'


def test_the_tab_menu_offers_the_bulk_closes_and_they_run_right_to_left():
    from leela.blocks.keys.menus import MENUS
    actions = [i.action for i in MENUS['tab']]
    assert actions[-3:] == ['close_others', 'close_right', 'close_saved']
    body = JS[JS.index('async function closeTabs('):JS.index('function moveTab(')]
    assert '.reverse()' in body, 'tabs are addressed by index; close the highest first'
    assert "await htmxPost('/tab/close?i=' + i)" in body, 'each swap is awaited'
    assert 'dataset.gitDiff' in body, 'browser-only diff tabs are not server tabs'
    assert 'confirmDialog' in body, 'unsaved work is still asked about'


def test_the_activity_panels_have_keys_and_reach_the_palette():
    from leela.core.keys import lookup
    for action, panel in (('panel_git', 'git'), ('panel_releases', 'releases'), ('panel_deploys', 'deploys')):
        key = lookup(action)
        assert key.scope == 'global' and key.keys, f'{action} is bound'
        assert re.search(rf"{action}:\s*\(\) => leeLeft\('{panel}'\)", JS), f'{action} opens the {panel} panel'
    # The palette and the keybinding editor are both built from the keymap, so a new action
    # is searchable by having been declared -- this is what that depends on.
    assert 'lee.keys.filter(k => k.label)' in JS
