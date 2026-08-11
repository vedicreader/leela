"""Notebook execution feedback stays tied to the kernel and source that produced it."""

# drives a real browser through playwright, so it is out of the default run. `pytest -m slow` or `-m ""` includes it.
import pytest

pytestmark = pytest.mark.slow

import asyncio

from leela.core.buttons import bar
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
    # Deliberately disagree: the regression was Variables independently peeking here
    # instead of following the runtime used by notebook/file execution.
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
