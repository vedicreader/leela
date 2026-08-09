"""Structural notebook edits are fast, preserve position, and report what happened."""

import json
from pathlib import Path

from starlette.testclient import TestClient

from leela.web.app import ide_app
from leela.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT/'leela/web/static/lee-ide.js').read_text()
CSS = (ROOT/'leela/web/static/lee-ide.css').read_text()


def _notebook(path):
    path.write_text(json.dumps({'nbformat': 4, 'nbformat_minor': 5, 'metadata': {}, 'cells': [
        {'cell_type': 'code', 'source': f'value_{i} = {i}', 'metadata': {}, 'outputs': [],
         'execution_count': None, 'id': f'cell-{i}'} for i in range(12)
    ]}))


def test_type_change_accepts_all_live_sources_in_one_request(tmp_path):
    p = tmp_path/'work.ipynb'; _notebook(p)
    ws = Workspace(roots=[tmp_path]); ws.open(p)
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state')
        sources = [{'i': i, 'source': f'edited_{i} = {i}'} for i in range(12)]
        d = client.post('/nb/edit', json={'op': 'type', 'i': 7, 'cycle': True,
                                          'sources': sources}).json()
    assert d['cells'][7]['cell_type'] == 'markdown'
    assert d['cells'][0]['source'] == 'edited_0 = 0'
    assert d['cells'][11]['source'] == 'edited_11 = 11'


def test_structural_edits_preserve_scroll_selection_cursor_and_visual_anchor():
    edit = JS[JS.index('async function nbEdit'):JS.index('async function toggleComment')]
    assert 'scrollTop = host?.scrollTop' in edit
    assert 'selectedId = lee.cells[lee.sel]?.id' in edit
    assert 'host.scrollTop = scrollTop' in edit
    assert 'anchored.getBoundingClientRect().top - anchor.top' in edit
    assert 'LeeCM.setCursor' in edit
    assert 'patchNotebook(host, before, r.cells, d.op)' in edit
    assert "{...d, sources: cur}" in edit


def test_type_split_insert_and_delete_actions_give_feedback_and_focus():
    actions = JS[JS.index('const ACTIONS'):JS.index("for (let i = 1")]
    assert 'is now ${r.cells[at]?.cell_type' in actions
    assert "status('cell split', 'ok')" in actions
    assert "status('cell inserted below', 'ok')" in actions
    assert "status('cell deleted', 'ok')" in actions
    assert 'focusCell(at + 1)' in actions


def test_cell_clipboard_survives_tabs_and_pastes_full_cells_with_new_ids(tmp_path):
    actions = JS[JS.index('const ACTIONS'):JS.index("for (let i = 1")]
    clipboard = JS[JS.index('function cellClipboardPayload'):JS.index('async function moveCellTo')]
    assert 'cell_copy: () => copyCell(lee.sel)' in actions
    assert 'more cell actions' in JS and "openMenu('cell'" in JS
    assert 'cell_cut: () => cutCell(lee.sel)' in actions
    assert 'cell_paste_above: () => pasteCell(lee.sel)' in actions
    assert 'lee.cellClipboard = {cells, cell: cells[0], from:' in clipboard
    assert "op: 'paste_many'" in clipboard and "op: 'delete_many'" in clipboard
    assert "op: 'paste_many'" in clipboard and 'LeeCM.getDoc(view)' in clipboard

    a = tmp_path/'a.ipynb'; b = tmp_path/'b.ipynb'; _notebook(a); _notebook(b)
    ws = Workspace(roots=[tmp_path]); ws.open(a)
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state')
        payload = client.post('/nb/edit', json={'op': 'paste', 'i': 1, 'cell': {
            'source': 'moved = True', 'cell_type': 'code', 'id': 'old-id',
            'outputs': [{'output_type': 'stream', 'text': 'yes\n'}], 'execution_count': 4,
        }}).json()
    pasted = payload['cells'][1]
    assert pasted['source'] == 'moved = True' and pasted['outputs'][0]['text'] == 'yes\n'
    assert pasted['id'] != 'old-id' and pasted['running'] is False


def test_unsaved_buffers_survive_tab_switches_without_waiting_for_a_save():
    assert 'function rememberBuffer(key, payload)' in JS
    assert "post('/tab/buffer', {...payload, base_disk_version:" in JS
    assert 'persistDraft(key, payload)' in JS
    assert "lee.dirtyBuffers.has(key) ? lee.buffers.get(key)" in JS
    assert 'bufferTimers' in JS


def test_exec_newline_and_file_tree_parent_are_real_actions_not_noops():
    actions = JS[JS.index('const ACTIONS'):JS.index("for (let i = 1")]
    assert "LeeCM.insert(v, '\\n')" in actions
    assert 'up_dir:       treeCollapse' in actions
    tree = JS[JS.index('function treeCollapse'):JS.index('async function refreshFileTree')]
    assert "closest('.lee-node.lee-dir')" in tree
    assert 'exec_newline: () => {}' not in actions
    assert 'up_dir:       () => {}' not in actions


def test_range_and_cell_structure_actions_are_reachable_from_the_shared_dispatch():
    actions = JS[JS.index('const ACTIONS'):JS.index("for (let i = 1")]
    assert "run_above:    () => runRange(0, lee.sel" in actions
    assert "run_below:    () => runRange(lee.sel" in actions
    for op in ('duplicate', 'merge_above', 'merge_below', 'clear_cell'):
        assert f"op: '{op}'" in actions
    range_run = JS[JS.index('async function runRange'):JS.index('async function restartRunAll')]
    assert "c.cell_type !== 'code'" in range_run
    assert 'o.output_type === \'error\'' in range_run


def test_cell_controls_form_an_attached_header_above_the_editor_not_an_overlay():
    cell = JS[JS.index('function cellEl'):JS.index('async function moveCellTo')]
    assert '<div class="lee-cell-chrome">' in cell
    assert '<div class="lee-cellmain"><div class="lee-cell-chrome">' in cell
    assert cell.index('lee-model-running') < cell.index('lee-cellbtns') < cell.index('lee-cm')
    chrome_start = CSS.index('.lee-cell-chrome {\n  position: relative')
    chrome = CSS[chrome_start:CSS.index('.lee-cell-state {', chrome_start)]
    assert 'position: relative' in chrome and 'width: 100%' in chrome
    assert 'border-bottom: 0' in chrome and 'border-radius: 5px 5px 0 0' in chrome
    assert 'position: absolute' not in chrome


def test_prompt_cell_uses_the_normal_plain_text_editor_surface():
    mount = JS[JS.index('function mountCell'):JS.index('function renderOutputs')]
    assert "c.cell_type === 'markdown' ? 'markdown' : ''" in mount
    assert '.lee-cell.prompt .lee-cm' not in CSS
    assert '.lee-cell.prompt .lee-gutter' not in CSS


def test_each_cell_exposes_a_persisted_compaction_choice():
    assert 'lee-cell-context' in JS
    assert "op: 'context'" in JS
    assert "['auto', 'keep', 'discard']" in JS


def test_structural_edits_patch_cells_without_remounting_unchanged_editors():
    patch = JS[JS.index('function patchNotebook'):JS.index('function ensureCellMounted')]
    assert 'oldEls = new Map' in patch
    assert 'host.appendChild(el)' in patch
    assert 'if (!el || changed)' in patch
    assert 'LeeCM.destroy(view)' in patch
    assert "host.innerHTML = ''" not in patch


def test_cell_handlers_resolve_the_current_index_after_a_move():
    cell = JS[JS.index('function cellEl'):JS.index('function setCellCollapsed')]
    mounted = JS[JS.index('function mountCell'):JS.index('function renderOutputs')]
    assert 'selectCell(+d.dataset.i)' in cell
    assert "moveCellTo(from, +d.dataset.i)" in cell
    assert "findIndex(cell => cell.id === c.id)" in mounted


def test_cell_focus_never_animates_the_notebook_scroll():
    focus = JS[JS.index('function focusCell'):JS.index('function autoSaveEnabled')]
    assert "scrollIntoView({block: 'nearest', inline: 'nearest'})" in focus
    assert "behavior: 'smooth'" not in focus


def test_repeated_run_gestures_do_not_queue_duplicate_work():
    run = JS[JS.index('async function runCell'):JS.index('async function askCell')]
    exec_run = JS[JS.index('async function runExec'):JS.index('function recall')]
    assert 'if (c.running)' in run and 'is already running' in run
    assert 'if (lee.execBusy)' in exec_run and 'finally { lee.execBusy = false; }' in exec_run


def test_saved_runs_are_yellow_history_not_green_current_kernel_success():
    cell = JS[JS.index('const cellState'):JS.index('/* The per-cell controls')]
    assert "!c.fresh ? 'previous'" in cell
    assert "saved output from a previous kernel" in cell
    assert 'function markPreviousRuns()' in cell
    assert '.lee-cell-state.previous' in CSS
    assert '.lee-cell-time.previous' in CSS


def test_cell_chrome_shows_live_and_last_execution_time():
    cell = JS[JS.index('function setCellState'):JS.index('/* The per-cell controls')]
    run = JS[JS.index('async function runCell'):JS.index('/* Running a prompt cell')]
    prompt = JS[JS.index('async function askCell'):JS.index('/* ---------------------------------------------------------- running files */')]
    assert 'function formatCellTime' in cell and 'function setCellTime' in cell
    assert 'id="time-${c.id}"' in JS and 'execution_ms' in JS
    assert 'setInterval(() => setCellTime' in run and 'clearInterval(cellClock)' in run
    assert 'setCellTime(c, elapsed, true)' in prompt


def test_cell_output_colours_distinguish_results_warnings_logs_and_errors():
    output = JS[JS.index('function outputTone'):JS.index('function paintSel')]
    assert "return 'error'" in output and "? 'warning' : 'log'" in output
    assert "return 'result'" in output and "return 'output'" in output
    for selector in ('.lee-out.output', '.lee-out.warning', '.lee-out.log', '.lee-out.error'):
        assert selector in CSS
