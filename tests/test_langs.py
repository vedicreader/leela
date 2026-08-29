"Running a notebook in a language that is not Python: its metadata, its runtime, its server."

import asyncio, json, re, shutil
from pathlib import Path

import pytest

from leela.blocks.lsp.lsp import LspService, PyrightService, SERVERS, find_server
from leela.blocks.nb.nb import Notebook, Cell
from leela.blocks.runtime.kernels import (KernelPool, KernelStartError, Kernel, installed_spec,
                                          kernelspec_for)
from leela.blocks.runtime.runners import (CargoRunner, NodeRunner, rust_chunks, rust_source,
                                          runner_for, scratch_root)
from leela.core.langs import LANGS, lang_named, lang_of_ext, servers_for
from leela.app import ide_app
from leela.workspace import Workspace
from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent

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

def test_a_notebook_that_names_no_language_is_python(tmp_path):
    p = tmp_path/'plain.ipynb'
    Notebook([Cell(source='1+1')], p).save()
    assert Notebook.load(p).lang == 'python'
    assert Notebook.blank().lang == 'python'

def test_metadata_that_is_not_a_mapping_opens_as_a_notebook_without_a_language(tmp_path):
    p = tmp_path/'broken.ipynb'
    p.write_text(json.dumps({'cells': [], 'metadata': ['not', 'a', 'mapping'],
                             'nbformat': 4, 'nbformat_minor': 5}))
    assert Notebook.load(p).lang == 'python'

def test_language_info_alone_names_the_language(tmp_path):
    "Not every writer fills in a kernelspec, and nbformat readers look in both places."
    p = tmp_path/'info.ipynb'
    p.write_text(json.dumps({'cells': [], 'metadata': {'language_info': {'name': 'javascript'}},
                             'nbformat': 4, 'nbformat_minor': 5}))
    assert Notebook.load(p).lang == 'javascript'

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

# the registry ----------------------------------------------------------------------------------

def test_every_language_leela_offers_can_be_started_somehow():
    "A language with neither a kernel name nor a runner is a row nothing can act on."
    for l in LANGS.values(): assert l.kernel or l.runner, f'{l.id} has no way to run'

def test_a_kernelspec_alias_resolves_to_its_language():
    assert lang_named('python3') is LANGS['python']
    assert lang_named('Rust') is LANGS['rust']
    assert lang_named('cobol') is None
    assert lang_named('') is None

def test_extensions_map_to_one_language_each():
    assert lang_of_ext('.rs') == 'rust'
    assert lang_of_ext('.MJS') == 'javascript'
    assert lang_of_ext('.tsx') == 'typescript'
    assert lang_of_ext('.zig') is None

def test_the_browser_and_the_server_agree_on_which_languages_are_served():
    "`core.js` cannot import Python, so it carries a copy. This is what keeps the copy honest."
    src = (ROOT/'leela/static/js/core.js').read_text()
    m = re.search(r'const LSP_LANGS = \[(.*?)\];', src, re.S)
    assert m, 'LSP_LANGS is gone from core.js'
    assert sorted(re.findall(r"'([^']+)'", m.group(1))) == sorted(LANGS)

# language servers ------------------------------------------------------------------------------

def test_the_python_server_list_is_unchanged_and_still_leads_with_basedpyright():
    assert SERVERS == servers_for('python')
    assert SERVERS[0][0] == 'basedpyright-langserver'

def test_the_old_name_still_names_the_service():
    assert PyrightService is LspService

def test_a_language_with_no_server_installed_says_so_rather_than_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, 'which', lambda name: None)
    s = LspService(tmp_path, 'rust')
    assert not s.available
    assert 'rust' in s.note
    assert s.diagnostics(str(tmp_path/'a.rs'), 'fn main() {}')[0] == []

def test_a_language_leela_knows_no_server_for_says_that_instead(tmp_path):
    assert 'no language server' in LspService(tmp_path, 'cobol').note

def test_a_language_server_is_rooted_in_the_checkout_being_worked_in(tmp_path):
    """A server reads the project's configuration from its root, and a folder of clones holds no
    `Cargo.toml` and no `pyproject.toml`. One service per language *and* root, so moving to a file
    in another repo starts that repo's server instead of going on asking one rooted beside them."""
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


def test_each_language_asks_for_its_own_servers(monkeypatch):
    asked = []
    monkeypatch.setattr(shutil, 'which', lambda name: asked.append(name) or None)
    find_server('rust')
    assert asked == ['rust-analyzer']
    asked.clear()
    find_server('javascript')
    assert asked[0] == 'typescript-language-server'

# choosing a runtime ----------------------------------------------------------------------------

def _spec_dir(tmp_path, name, language):
    "A Jupyter kernelspec store holding one kernel, the way an installed kernel registers itself."
    d = tmp_path/'jupyter'/'kernels'/name
    d.mkdir(parents=True)
    (d/'kernel.json').write_text(json.dumps(
        {'argv': ['true', '-f', '{connection_file}'], 'display_name': name, 'language': language}))
    return tmp_path/'jupyter'

def test_a_language_with_no_kernel_installed_names_what_would_install_one(monkeypatch):
    monkeypatch.setattr('leela.blocks.runtime.kernels.installed_kernels', dict)
    with pytest.raises(KernelStartError) as e: installed_spec('rust')
    assert 'evcxr_jupyter' in str(e.value)

def test_an_installed_kernelspec_is_found_by_its_language(tmp_path, monkeypatch):
    monkeypatch.setenv('JUPYTER_PATH', str(_spec_dir(tmp_path, 'evcxr', 'rust')))
    assert kernelspec_for('rust') == 'evcxr'
    assert installed_spec('rust').language == 'rust'

def test_the_pool_runs_rust_itself_when_no_rust_kernel_is_installed(monkeypatch):
    monkeypatch.setattr('leela.blocks.runtime.kernels.installed_kernels', dict)
    pool = KernelPool()
    assert pool._class_for({'lang': 'rust'}) is CargoRunner
    assert pool._class_for({'lang': 'javascript'}) is NodeRunner
    assert pool._class_for({'lang': 'python'}) is Kernel
    assert pool._class_for({}) is Kernel

def test_an_installed_kernel_wins_over_leelas_own_runner(tmp_path, monkeypatch):
    monkeypatch.setenv('JUPYTER_PATH', str(_spec_dir(tmp_path, 'evcxr', 'rust')))
    assert KernelPool()._class_for({'lang': 'rust'}) is Kernel

def test_a_language_with_neither_falls_through_to_the_kernel_that_reports_it(monkeypatch):
    monkeypatch.setattr('leela.blocks.runtime.kernels.installed_kernels', dict)
    assert KernelPool()._class_for({'lang': 'typescript'}) is Kernel
    assert runner_for('typescript') is None

def test_a_kernel_in_another_language_is_never_asked_to_chdir_in_python():
    "The fault this guards: `runtime()` used to send `os.chdir` to whatever it got back."
    k = Kernel(lang='rust')
    assert not k.inspect, 'dhrishti reads Python namespaces, so a Rust kernel gets no inspector'
    assert asyncio.run(k.chdir('/tmp')) is False

# how a Rust cell is split ----------------------------------------------------------------------

def test_a_brace_inside_a_string_does_not_end_a_chunk():
    assert rust_chunks('let s = "a { b";\nlet t = 2;') == ['let s = "a { b";', 'let t = 2;']

def test_a_function_body_stays_one_chunk():
    assert rust_chunks('fn f() {\n  let x = 1;\n}\nf();') == ['fn f() {\n  let x = 1;\n}', 'f();']

def test_a_comment_is_carried_with_its_chunk():
    assert rust_chunks('// why\nlet x = 1;') == ['// why\nlet x = 1;']

def test_the_generated_crate_puts_definitions_outside_main():
    src = rust_source(['fn f() {}'], ['f();'])
    assert src.index('fn f() {}') < src.index('fn main()')
    assert 'f();' in src.split('fn main()')[1]

def test_a_cell_is_split_into_what_outlives_it_and_what_does_not():
    r = CargoRunner(key='split')
    deps, items, stmts = r._split('use std::fmt;\nstruct P;\nlet n = 1;\nprintln!("{}", n);')
    assert items == ['use std::fmt;', 'struct P;']
    assert stmts == ['let n = 1;', 'println!("{}", n);']
    assert deps == {}

def test_a_trailing_expression_without_a_semicolon_is_printed():
    _, _, stmts = CargoRunner(key='trail')._split('let v = vec![1];\nv.len()')
    assert stmts[-1] == 'println!("{:?}", v.len());'

def test_a_trailing_statement_is_not_printed():
    _, _, stmts = CargoRunner(key='trail2')._split('let v = vec![1];')
    assert stmts == ['let v = vec![1];']

def test_a_dependency_directive_is_taken_out_of_the_source():
    r = CargoRunner(key='dep')
    deps, items, stmts = r._split('//! dep: rand = "0.8"\nlet x = 1;')
    assert deps == {'rand': '"0.8"'}
    assert 'dep:' not in ' '.join(stmts)

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
async def test_a_rust_definition_is_there_in_the_next_cell(tmp_path, monkeypatch):
    r = await _rust(tmp_path, monkeypatch)
    try:
        assert (await r.execute('fn double(x: i32) -> i32 { x * 2 }')).ok
        res = await r.execute('println!("{}", double(21));')
        assert res.ok
        assert _outputs(res, 'stream')[0]['text'].strip() == '42'
    finally: await r.shutdown()

@pytest.mark.slow
@pytest.mark.asyncio
async def test_a_borrow_error_comes_back_as_the_cell_error_with_its_code(tmp_path, monkeypatch):
    "The compiler is what teaches Rust, so its diagnostic has to survive into the notebook."
    r = await _rust(tmp_path, monkeypatch)
    try:
        res = await r.execute('let s = String::from("hi");\nlet t = s;\nprintln!("{}", s);')
        assert not res.ok
        err = _outputs(res, 'error')[0]
        assert err['ename'] == 'E0382'
        assert 'value borrowed here after move' in '\n'.join(err['traceback'])
    finally: await r.shutdown()

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
async def test_rust_without_cargo_says_so_before_it_starts_anything(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    monkeypatch.setattr(shutil, 'which', lambda name: None)
    monkeypatch.setattr('leela.TOOL_DIRS', ())
    with pytest.raises(KernelStartError) as e: await CargoRunner(key='nocargo').start()
    assert 'rustup.rs' in str(e.value)

@pytest.mark.slow
@pytest.mark.asyncio
async def test_a_javascript_binding_is_there_in_the_next_cell(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    if not shutil.which('node'): pytest.skip('node is not installed')
    r = await NodeRunner(key='test-js').start()
    try:
        assert (await r.execute('let total = 0;\nfunction add(n) { total += n; return total }')).ok
        res = await r.execute('add(20); add(22)')
        assert res.ok
        assert _outputs(res, 'execute_result')[0]['data']['text/plain'] == '42'
    finally: await r.shutdown()

@pytest.mark.slow
@pytest.mark.asyncio
async def test_javascript_console_output_and_errors_arrive_as_notebook_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    if not shutil.which('node'): pytest.skip('node is not installed')
    r = await NodeRunner(key='test-js2').start()
    try:
        res = await r.execute('console.log("one"); console.error("two");')
        assert [(o['name'], o['text'].strip()) for o in _outputs(res, 'stream')] == \
               [('stdout', 'one'), ('stderr', 'two')]
        bad = await r.execute('null.oops')
        assert not bad.ok
        assert _outputs(bad, 'error')[0]['ename'] == 'TypeError'
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

def test_two_notebooks_do_not_share_one_scratch_project(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    assert scratch_root('rust', 'a.ipynb') != scratch_root('rust', 'b.ipynb')
    assert scratch_root('rust', 'a.ipynb') == scratch_root('rust', 'a.ipynb')

# choosing the language from the browser ---------------------------------------------------------

def _open(tmp_path, name='n.ipynb'):
    p = tmp_path/name
    Notebook([Cell(source='1')], p).save()
    ws = Workspace(roots=[tmp_path])
    ws.open(p)
    return p, ws

def test_setting_the_language_writes_the_notebook_and_says_what_runs_each_one(tmp_path):
    p, ws = _open(tmp_path)
    with TestClient(ide_app(ws)) as client:
        before = client.post('/nb/language', json={'path': str(p)}).json()
        assert before['lang'] == 'python'
        assert {l['id'] for l in before['langs']} == set(LANGS)
        assert all(l['how'] for l in before['langs']), 'every row says how it would run'
        r = client.post('/nb/language', json={'path': str(p), 'lang': 'rust'}).json()
    assert r['lang'] == 'rust'
    assert Notebook.load(p).lang == 'rust', 'the choice is in the file, not only in the session'

def test_a_language_leela_does_not_know_is_refused(tmp_path):
    p, ws = _open(tmp_path)
    with TestClient(ide_app(ws)) as client:
        r = client.post('/nb/language', json={'path': str(p), 'lang': 'cobol'})
    assert r.status_code != 200 or 'cobol' in r.text

def test_a_notebook_that_was_never_saved_keeps_its_language_in_memory(tmp_path):
    "The fault: `save` raised `notebook has no path`, so a new notebook could not be made Rust."
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as client:
        client.post('/tab/new', params={'kind': 'notebook'})
        client.get('/tab/state')
        r = client.post('/nb/language', json={'lang': 'rust'})
    assert r.status_code == 200, r.text
    assert r.json()['lang'] == 'rust'

def test_changing_the_language_drops_the_runtime_the_old_one_was_using(tmp_path):
    "A Python kernel cannot run the Rust cells the notebook now holds, so it must not be reused."
    p, ws = _open(tmp_path)
    closed = []
    async def close(key): closed.append(key)
    ws.pool.close = close
    with TestClient(ide_app(ws)) as client:
        client.get('/tab/state', params={'path': str(p)})
        client.post('/nb/language', json={'path': str(p), 'lang': 'javascript'})
    assert closed == [ws.kernel_key(ws.tab)]

def test_the_action_is_unbound_so_it_costs_no_chord():
    "Rarer actions ship with a button and a palette entry, and leave the chord space alone."
    from leela.core.keys import DEFAULTS
    row = next(k for k in DEFAULTS if k.action == 'notebook_language')
    assert row.key == ''
