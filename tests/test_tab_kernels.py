"""Notebook kernels are private by default; source files deliberately share by project."""

import asyncio

from leela.workspace import Workspace


def _notebook(path):
    path.write_text('{"nbformat":4,"nbformat_minor":5,"metadata":{},"cells":[]}')


def test_each_notebook_has_a_distinct_kernel_key(tmp_path):
    a, b = tmp_path/'a.ipynb', tmp_path/'b.ipynb'
    _notebook(a); _notebook(b)
    ws = Workspace(roots=[tmp_path])
    ta = ws.open(a); tb = ws.open(b)
    assert ta.private_kernel and tb.private_kernel
    assert ws.kernel_key(ta) == f'tab:{a}'
    assert ws.kernel_key(tb) == f'tab:{b}'
    assert ws.kernel_key(ta) != ws.kernel_key(tb)


def test_source_files_share_the_folder_kernel(tmp_path):
    a, b = tmp_path/'a.py', tmp_path/'b.py'
    a.write_text('a = 1\n'); b.write_text('b = 2\n')
    ws = Workspace(roots=[tmp_path])
    ta = ws.open(a); tb = ws.open(b)
    assert not ta.private_kernel and not tb.private_kernel
    assert ws.kernel_key(ta) == ws.kernel_key(tb) == str(tmp_path)


def test_a_notebook_can_explicitly_attach_to_the_folder_kernel(tmp_path):
    p = tmp_path/'analysis.ipynb'; _notebook(p)
    ws = Workspace(roots=[tmp_path]); tab = ws.open(p)
    tab.private_kernel = False
    assert ws.kernel_key(tab) == str(tmp_path)


def test_notebook_kernel_cwd_is_the_notebook_directory(tmp_path):
    one, two = tmp_path/'one', tmp_path/'two'
    one.mkdir(); two.mkdir(); nbs = two/'nbs'; nbs.mkdir()
    p = nbs/'analysis.ipynb'; _notebook(p)
    ws = Workspace(roots=[one, two]); tab = ws.open(p)
    assert ws.cwd_for(tab) == nbs

    seen = {}
    async def get(key, **kwargs): seen.update(key=key, **kwargs); return object()
    ws.pool.get = get
    asyncio.run(ws.kernel(tab))
    assert seen['cwd'] == nbs and seen['name'] == 'two'


def test_notebook_parent_paths_match_jupyter_and_pycharm(tmp_path):
    project = tmp_path/'project'; nbs = project/'nbs'; nbs.mkdir(parents=True)
    p = nbs/'analysis.ipynb'; _notebook(p)
    ws = Workspace(roots=[project]); tab = ws.open(p)
    assert (ws.cwd_for(tab)/'..').resolve() == project.resolve()


def test_existing_notebook_kernel_moves_to_corrected_cwd_without_losing_namespace(tmp_path):
    project = tmp_path/'project'; nbs = project/'nbs'; nbs.mkdir(parents=True)
    p = nbs/'analysis.ipynb'; _notebook(p)
    ws = Workspace(roots=[project]); tab = ws.open(p)
    calls = []
    class Result:
        ok=True; error=''
    class Existing:
        cwd=project
        async def execute(self, code): calls.append(code); return Result()
    kernel=Existing()
    async def get(key, **kwargs): return kernel
    ws.pool.get=get
    assert asyncio.run(ws.runtime(tab)) is kernel
    assert kernel.cwd == nbs and calls and 'chdir' in calls[0]


def test_private_notebook_can_override_cwd_inside_an_open_folder(tmp_path):
    sub = tmp_path/'nbs'; sub.mkdir()
    p = tmp_path/'analysis.ipynb'; _notebook(p)
    ws = Workspace(roots=[tmp_path]); tab = ws.open(p)
    tab.cwd = str(sub)
    assert ws.cwd_for(tab) == sub


def test_workspace_state_persists_an_explicit_attachment_without_running_state(tmp_path):
    p = tmp_path/'analysis.ipynb'; _notebook(p)
    ws = Workspace(roots=[tmp_path]); tab = ws.open(p)
    tab.private_kernel = False; tab.running = 2
    state = ws.state()
    assert state['version'] == 2
    assert state['tabs'][0]['private_kernel'] is False
    assert 'running' not in state['tabs'][0]
