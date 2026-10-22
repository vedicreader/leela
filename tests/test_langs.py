"Running a notebook in a language that is not Python: its metadata, its runtime, its server."

import json, shutil

import pytest

from leela.blocks.nb.nb import Notebook, Cell
from leela.blocks.runtime.runners import CargoRunner, NodeRunner, rust_chunks
from leela.app import ide_app
from leela.workspace import Workspace
from starlette.testclient import TestClient

# the notebook carries its language ------------------------------------------------------------

def test_a_notebook_keeps_the_language_it_was_saved_with(tmp_path):
    "The fault: `save` wrote cells only, so a Rust notebook was Python again the next time it opened."
    p = tmp_path/'ownership.ipynb'
    nb = Notebook([Cell(source='let x = 1;')], p)
    nb.set_lang('rust', display='Rust', kernel='rust')
    nb.save()
    written = json.loads(p.read_text())
    assert written['metadata']['kernelspec']['language'] == 'rust'
    assert Notebook.load(p).lang == 'rust'


def test_undo_puts_the_language_back(tmp_path):
    "The fault: the undo snapshot copied cells and dirty, so undo left the new language behind."
    nb = Notebook([Cell(source='x')], tmp_path/'u.ipynb')
    nb.insert(1)                       # a checkpoint taken while the notebook is still Python
    nb.set_lang('rust')
    nb.insert(1)
    nb.undo()
    assert nb.lang == 'rust', 'the undo after set_lang keeps it'
    nb.undo()
    assert nb.lang == 'python', 'the undo back past set_lang drops it'

def test_a_saved_notebook_is_still_valid_nbformat(tmp_path):
    nbformat = pytest.importorskip('nbformat')
    p = tmp_path/'valid.ipynb'
    nb = Notebook([Cell(source='println!("hi");')], p)
    nb.set_lang('rust')
    nb.save()
    nbformat.validate(nbformat.read(str(p), as_version=4))

# language servers ------------------------------------------------------------------------------


def test_a_language_server_is_rooted_in_the_checkout_being_worked_in(tmp_path):
    """A server reads the project's configuration from its root, and a folder of clones holds no `Cargo.toml` and no `pyproject.toml`."""
    import subprocess
    orgs = tmp_path/'orgs'
    a, b = orgs/'repo-a', orgs/'repo-b'
    for d in (a, b):
        d.mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(d)], check=True)
        (d/'main.py').write_text('x = 1\n')
    ws = Workspace(roots=[orgs])
    ws.open(a/'main.py')
    first_service = ws.lsp_for('python')
    assert first_service.root == a, 'the checkout, not the folder holding it'
    ws.open(b/'main.py')
    second = ws.lsp_for('python')
    assert second.root == b and second is not first_service, 'the other repo gets its own'
    ws.open(a/'main.py')
    assert ws.lsp_for('python') is first_service, 'and coming back reuses the first, not a third'


_real_reaper = Workspace._start_reaper

def _two_repos(tmp_path):
    import subprocess
    a, b = tmp_path/'orgs'/'repo-a', tmp_path/'orgs'/'repo-b'
    for d in (a, b):
        d.mkdir(parents=True); subprocess.run(['git', 'init', '-q', str(d)], check=True); (d/'main.py').write_text('x = 1\n')
    return Workspace(roots=[tmp_path/'orgs']), a, b

def test_a_language_server_nobody_has_used_for_a_while_is_closed(tmp_path):
    "Working in many repos left one basedpyright running per repo until Leela quit."
    from leela.blocks.lsp.lsp import LSP_IDLE
    ws, a, b = _two_repos(tmp_path)
    ws.open(a/'main.py'); sa = ws.lsp_for('python')
    ws.open(b/'main.py'); sb = ws.lsp_for('python')
    closed = []
    sa.close = lambda: closed.append('a')
    sa.used -= LSP_IDLE + 1
    ws.open(b/'main.py'); assert ws.lsp_for('python') is sb
    assert closed == ['a'] and list(ws._lsps.values()) == [sb], 'the next request anywhere closes it'
    ws.open(a/'main.py')
    assert ws.lsp_for('python') is not sa, 'and coming back starts a fresh one'

def test_a_server_in_use_or_used_recently_is_kept(tmp_path):
    from leela.blocks.lsp.lsp import LSP_IDLE
    import time
    ws, a, b = _two_repos(tmp_path)
    ws.open(a/'main.py'); sa = ws.lsp_for('python')
    ws.open(b/'main.py'); sb = ws.lsp_for('python')
    now = time.monotonic()
    sa.used, sa.busy = now - LSP_IDLE - 1, 1
    assert ws.reap_lsps(now) == [], 'a request still running is never cut off'
    sa.busy = 0
    sb.used = now - LSP_IDLE + 60
    assert ws.reap_lsps(now) == [sa], 'only the one unused past the limit goes'

def test_asking_for_status_does_not_count_as_use(tmp_path):
    "The settings panel asks for status; that must not keep an idle server alive."
    from starlette.testclient import TestClient
    ws, a, _ = _two_repos(tmp_path)
    ws.open(a/'main.py'); sa = ws.lsp_for('python'); sa.used = 1.0
    with TestClient(ide_app(ws)) as c: c.get('/lsp/status')
    assert sa.used == 1.0

def test_a_closed_server_forgets_its_documents_and_answers_waiting_requests(tmp_path):
    "A server started again after a close is sent `didOpen`, not `didChange` for a file it never saw."
    import queue
    from leela.blocks.lsp.lsp import LspService
    s = LspService(tmp_path)
    s._versions['file:///x.py'] = 3
    waiting = s._pending[7] = queue.Queue(1)
    s.close()
    assert s._versions == {} and s._pending == {}
    assert 'error' in waiting.get_nowait()

def test_after_shutdown_no_server_is_started_and_the_reaper_stops(tmp_path):
    import asyncio
    ws, a, _ = _two_repos(tmp_path)
    _real_reaper(ws)
    ws.open(a/'main.py'); sa = ws.lsp_for('python')
    closed = []; sa.close = lambda: closed.append(1)
    asyncio.run(ws.shutdown())
    ws._reaper.join(2)
    assert not ws._reaper.is_alive() and closed == [1], 'shutdown wakes the reaper and closes every server'
    late = ws.lsp_for('python')
    assert not late.available and ws._lsps == {}, 'a request after shutdown gets nothing to leak'



# how a Rust cell is split ----------------------------------------------------------------------

def test_a_brace_inside_a_string_does_not_end_a_chunk():
    assert rust_chunks('let s = "a { b";\nlet t = 2;') == ['let s = "a { b";', 'let t = 2;']


def test_a_trailing_expression_without_a_semicolon_is_printed():
    _, _, stmts = CargoRunner(key='trail')._split('let v = vec![1];\nv.len()')
    assert stmts[-1] == 'println!("{:?}", v.len());'


# the runners, against the real toolchains -------------------------------------------------------

pytestmark = []

def _outputs(res, kind):
    return [o for o in res.outputs if o['output_type'] == kind]

async def _rust(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    if not shutil.which('cargo'): pytest.skip('cargo is not installed')
    return await CargoRunner(key='test-rust').start()


@pytest.mark.slow
@pytest.mark.asyncio
async def test_a_cell_that_does_not_compile_leaves_the_crate_as_it_was(tmp_path, monkeypatch):
    "The fault this guards: a bad definition stayed in the crate and every later cell failed too."
    r = await _rust(tmp_path, monkeypatch)
    try:
        assert (await r.execute('fn ok() -> i32 { 7 }')).ok
        assert not (await r.execute('fn bad() -> i32 { "not an i32" }')).ok
        res = await r.execute('println!("{}", ok());')
        assert res.ok, 'the working definition survived the broken one'
        assert _outputs(res, 'stream')[0]['text'].strip() == '7'
    finally: await r.shutdown()


@pytest.mark.slow
@pytest.mark.asyncio
async def test_a_top_level_await_keeps_its_binding_and_its_value(tmp_path, monkeypatch):
    "A cell wrapped for `await` used to lose both: `let` scoped to the wrapper, value not returned."
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    if not shutil.which('node'): pytest.skip('node is not installed')
    r = await NodeRunner(key='test-js3').start()
    try:
        res = await r.execute('const {join} = await import("node:path"); join("a", "b")')
        assert res.ok
        assert _outputs(res, 'execute_result')[0]['data']['text/plain'] == 'a/b'
        assert _outputs(await r.execute('join("x", "y")'), 'execute_result')[0]['data']['text/plain'] == 'x/y'
    finally: await r.shutdown()


# choosing the language from the browser ---------------------------------------------------------


def test_a_notebook_that_was_never_saved_keeps_its_language_in_memory(tmp_path):
    "The fault: `save` raised `notebook has no path`, so a new notebook could not be made Rust."
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        client.post('/tab/new', params={'kind': 'notebook'})
        client.get('/tab/state')
        r = client.post('/nb/language', json={'lang': 'rust'})
    assert r.status_code == 200, r.text
    assert r.json()['lang'] == 'rust'


