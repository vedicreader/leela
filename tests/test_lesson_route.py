import json, shutil, subprocess
from pathlib import Path
import pytest
from abhyasa.learner import slugify
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.nb.lesson import lesson_notebook
from leela.blocks.nb.nb import Cell, Notebook
from leela.workspace import Workspace

@pytest.mark.parametrize('name', ['Softmax', '../x', '/etc/x', 'सॉफ्टमैक्स'])
def test_new_lesson_creates_a_file_and_opens_a_normal_tab(tmp_path, name):
    ws = Workspace(roots=[tmp_path])
    path = tmp_path/'lessons'/f'{slugify(name)}.ipynb'
    with TestClient(ide_app(ws)) as c:
        r = c.post('/lesson/new', json={'name': name})
        assert r.status_code == 200, r.text
        assert path.is_file() and path.stem.isascii()
        nb = Notebook.load(path)
        assert nb.meta['lesson'] == {'v': 1, 'name': name}
        assert [cell.cell_type for cell in nb.cells] == ['markdown', 'markdown', 'markdown', 'code', 'markdown']
        assert [cell.source for cell in nb.cells] == [cell.source for cell in lesson_notebook(name).cells]
        assert nb[2].extra['lesson']['for'] == nb[4].extra['lesson']['for'] == nb[3].id
        assert ws.tab.path == str(path) and ws.tab.kind == 'notebook' and not ws.tab.scratch
        assert str(path) in r.text and 'id="tabbar"' in r.text
        state = c.get('/tab/state').json()
        assert state['path'] == str(path) and len(state['cells']) == 5 and not state['stale']
    assert list(tmp_path.rglob('*.ipynb')) == [path]

def test_duplicate_lesson_names_preserve_existing_files(tmp_path):
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as c:
        assert c.post('/lesson/new', params={'name': 'Softmax'}).status_code == 200
        path = tmp_path/'lessons'/'softmax.ipynb'
        before = path.read_bytes()
        for suffix in ('-2', '-3'):
            r = c.post('/lesson/new', json={'name': 'Softmax'})
            assert r.status_code == 200, r.text
            assert ws.tab.path == str(path.with_stem('softmax' + suffix))
            assert path.read_bytes() == before
        assert len(ws.tabs) == 3

def test_lesson_creation_uses_the_active_workspace_root(tmp_path):
    roots = [tmp_path/'one', tmp_path/'two']
    for p in roots: p.mkdir()
    ws = Workspace(roots=roots)
    ws.activate_root(roots[1])
    with TestClient(ide_app(ws)) as c:
        r = c.post('/lesson/new', json={'name': 'Active'})
        assert r.status_code == 200, r.text
        assert ws.tab.path == str(roots[1]/'lessons'/'active.ipynb')
    assert not (roots[0]/'lessons').exists()

@pytest.mark.parametrize('name', ['', '   ', None, 42])
def test_lesson_creation_refuses_a_missing_name(tmp_path, name):
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as c:
        r = c.post('/lesson/new', json={'name': name})
        assert r.status_code == 400 and r.json()['error']
    assert not (tmp_path/'lessons').exists()

def test_lesson_creation_requires_an_open_folder():
    with TestClient(ide_app(Workspace(roots=[]))) as c:
        r = c.post('/lesson/new', json={'name': 'Nowhere'})
        assert r.status_code == 400 and r.json()['error']

@pytest.mark.parametrize('kind', ['file', 'symlink'])
def test_lesson_creation_refuses_an_invalid_lessons_directory(tmp_path, kind):
    root, outside = tmp_path/'root', tmp_path/'outside'
    root.mkdir(); outside.mkdir()
    folder = root/'lessons'
    if kind == 'file': folder.write_text('keep')
    else: folder.symlink_to(outside, target_is_directory=True)
    with TestClient(ide_app(Workspace(roots=[root]))) as c:
        r = c.post('/lesson/new', json={'name': 'Safe'})
        assert r.status_code == 400 and r.json()['error']
    assert list(outside.iterdir()) == []
    if kind == 'file': assert folder.read_text() == 'keep'

def test_lesson_creation_skips_directories_and_dangling_links(tmp_path):
    folder = tmp_path/'lessons'
    folder.mkdir()
    (folder/'x.ipynb').mkdir()
    link = folder/'x-2.ipynb'
    link.symlink_to(tmp_path/'missing.ipynb')
    with TestClient(ide_app(Workspace(roots=[tmp_path]))) as c:
        r = c.post('/lesson/new', json={'name': 'x'})
        assert r.status_code == 200, r.text
        assert (folder/'x-3.ipynb').is_file()
    assert link.is_symlink() and not (tmp_path/'missing.ipynb').exists()

def test_an_open_lesson_picks_up_an_agent_edit_through_disk_reload(tmp_path):
    path = tmp_path/'lesson.ipynb'
    lesson_notebook('Softmax').save(path)
    ws = Workspace(roots=[tmp_path])
    ws.open(path)
    with TestClient(ide_app(ws)) as c:
        before = c.get('/tab/state').json()
        nb = Notebook.load(path)
        nb.cells.append(Cell(source='Agent demo added on disk', cell_type='markdown'))
        nb.save(path)
        watch = c.get('/tab/watch', params={'path': str(path)}).json()
        stale = c.get('/tab/state', params={'path': str(path)}).json()
        assert watch['disk_version'] != before['disk_version']
        assert stale['stale'] and stale['disk_version'] == before['disk_version']
        assert c.post('/tab/reload', json={'path': str(path)}).json()['paths'] == [str(path)]
        after = c.get('/tab/state', params={'path': str(path)}).json()
        assert not after['stale'] and after['disk_version'] == watch['disk_version']
        assert len(after['cells']) == 6 and after['cells'][-1]['source'] == 'Agent demo added on disk'

@pytest.mark.parametrize('name', ['Softmax & ../x', None, ''])
def test_new_lesson_action_uses_the_input_sheet_and_tab_strip(tmp_path, name):
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    src = Path(__file__).parents[1]/'leela'/'static'/'js'/'actions.js'
    script = '''
const vm = require('vm'), fs = require('fs'), calls = [], dialogs = [];
const ctx = {window: {}, CM_EDIT: {}, inputDialog: async (...args) => { dialogs.push(args); return JSON.parse(process.argv[2]); },
  htmx: {ajax: async (...args) => calls.push(args)}, refreshFileTree: async () => calls.push('refresh')};
vm.createContext(ctx); vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
(async () => { await vm.runInContext("ACTIONS.new_lesson()", ctx); console.log(JSON.stringify({calls, dialogs})); })()
  .catch(e => { console.error(e); process.exit(1); });
'''
    r = subprocess.run([node, '-e', script, str(src), json.dumps(name)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out['dialogs'][0][:2] == ['new lesson notebook', 'name']
    if not name: assert out['calls'] == []
    else:
        from urllib.parse import parse_qs, urlparse
        method, url, opts = out['calls'][0]
        assert method == 'POST' and urlparse(url).path == '/lesson/new'
        assert parse_qs(urlparse(url).query) == {'name': [name]}
        assert opts == {'target': '#tabbar', 'swap': 'outerHTML'}
        assert out['calls'][1] == 'refresh'
