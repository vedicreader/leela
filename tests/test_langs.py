"Running a notebook in a language that is not Python: its metadata, its runtime, its server."

import asyncio, json, os, shutil

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

FAKE_LSP = '''import sys, json
def read():
    n = 0
    while True:
        l = sys.stdin.buffer.readline()
        if not l: sys.exit()
        if l in (b'\\r\\n', b'\\n'): break
        if l.lower().startswith(b'content-length'): n = int(l.split(b':')[1])
    return json.loads(sys.stdin.buffer.read(n))
while True:
    m = read()
    if 'id' in m and 'method' in m:
        b = json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': {}}).encode()
        sys.stdout.buffer.write(b'Content-Length: %d\\r\\n\\r\\n' % len(b) + b); sys.stdout.buffer.flush()
    if m.get('method') == 'exit': sys.exit()
'''

def test_a_service_held_across_shutdown_cannot_start_a_server_nothing_will_stop(tmp_path, monkeypatch):
    "A request thread already holding the service called `start` after `shutdown` had closed it, and the process it spawned outlived the app."
    import asyncio, sys
    from leela.blocks.lsp import lsp as lspmod
    (tmp_path/'fake_lsp.py').write_text(FAKE_LSP)
    monkeypatch.setattr(lspmod, 'find_server', lambda lang: ('fake', [sys.executable, str(tmp_path/'fake_lsp.py')]))
    ws, a, _ = _two_repos(tmp_path)
    ws.open(a/'main.py'); held = ws.lsp_for('python')
    try:
        assert held.available
        asyncio.run(ws.shutdown())
        assert not held.start() and not held.alive, 'a server was started after shutdown'
    finally: held.close()

def test_shutdown_now_from_inside_a_running_loop_still_tears_the_workspace_down(tmp_path):
    "`asyncio.run` refused inside a loop and the error was swallowed, so nothing the workspace started was ever stopped."
    import asyncio
    ws, a, _ = _two_repos(tmp_path)
    ws.open(a/'main.py'); sa = ws.lsp_for('python')
    async def go(): ws.shutdown_now(); return ws._down
    assert asyncio.run(go()), 'the teardown never ran'
    assert sa.retired

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


def test_a_rust_cell_run_twice_defines_its_items_once():
    "A second run of the same cell put `fn f` in main.rs twice, and rustc answered E0428."
    from leela.blocks.runtime.runners import merge_items
    a = ['#[derive(Debug)]\npub struct P { x: i32 }', 'impl P {\n    fn get(&self) -> i32 { self.x }\n}', 'pub(crate) fn f() -> i32 { 1 }', 'use std::fmt;']
    assert merge_items(a, a) == a
    b = merge_items(a, ['fn f() -> i32 { 2 }', 'impl P {\n    fn put(&mut self) {}\n}'])
    assert b[2] == 'fn f() -> i32 { 2 }' and len(b) == 5, 'a new body replaces the old one in place; an impl with other methods is kept'

FAKE_CARGO = """#!/bin/sh
mkdir -p target/debug
if grep -q SLEEP src/main.rs; then body='sleep 30 & echo $! > child.pid; exec sleep 30'; else body='echo ran'; fi
printf '#!/bin/sh\\n%s\\n' "$body" > target/debug/leela_cell; chmod +x target/debug/leela_cell
"""

async def _fake_rust(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path/'data'))
    bin_ = tmp_path/'bin'; bin_.mkdir(); (bin_/'cargo').write_text(FAKE_CARGO); (bin_/'cargo').chmod(0o755)
    subprocess.run([str(bin_/'cargo')], cwd=tmp_path, capture_output=True)   # macOS scans a new executable on its first run
    monkeypatch.setenv('PATH', f"{bin_}:{os.environ['PATH']}")
    return await CargoRunner(cwd=tmp_path, key=str(tmp_path)).start()

@pytest.mark.asyncio
async def test_a_rust_cell_run_twice_builds_one_definition(tmp_path, monkeypatch):
    r = await _fake_rust(tmp_path, monkeypatch)
    try:
        for _ in range(2): assert (await r.execute('fn f() -> i32 { 1 }\nf()')).ok
        assert (r.dir/'src'/'main.rs').read_text().count('fn f()') == 1
    finally: await r.shutdown()

@pytest.mark.asyncio
@pytest.mark.parametrize('how', ['interrupt', 'restart'])
async def test_stop_and_restart_end_a_rust_cell_and_its_children(tmp_path, monkeypatch, how):
    "Stop called a no-op interrupt and Restart only forgot the tool, so the program and what it started ran on."
    import psutil
    r = await _fake_rust(tmp_path, monkeypatch)
    try:
        run = asyncio.ensure_future(r.execute('let SLEEP = 1;'))
        for _ in range(400):
            if (tmp_path/'child.pid').exists() and (tmp_path/'child.pid').read_text().strip(): break
            await asyncio.sleep(.05)
        child, main = int((tmp_path/'child.pid').read_text()), r.proc.pid
        await getattr(r, how)()
        await asyncio.wait_for(run, 10)
        def dead(pid):
            try: return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
            except psutil.NoSuchProcess: return True
        for _ in range(100):
            if dead(child) and dead(main): break
            await asyncio.sleep(.05)
        assert dead(main) and dead(child), 'the program and its child are gone'
    finally: await r.shutdown()


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


