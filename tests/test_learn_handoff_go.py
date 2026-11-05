"A hand-off from abhyasa with `go=1` opens the notebook at once, at its cell: the learning copy of a notebook walk runs in the folder of the learner's notebook, in that project. It adds no folder by itself."
import json, sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import pytest
from starlette.testclient import TestClient
from leela.blocks.runtime.app import copy_folder
from learn_data import JID, rig  # noqa: F401

def project(tmp):
    "A learner's checkout with `nbs/15_DDPM.ipynb` and the course package beside it."
    p = tmp/'course'; (p/'nbs').mkdir(parents=True); (p/'.git').mkdir(); (p/'miniai').mkdir()
    nb = p/'nbs'/'15_DDPM.ipynb'
    nb.write_text(json.dumps(dict(cells=[dict(cell_type='markdown', metadata={}, source='## Imports')], metadata={}, nbformat=4, nbformat_minor=5)))
    return p, nb

def copy_walk(lr, j, tmp, nb):
    "Walk `j` as a notebook walk of `nb`, with abhyasa's learning copy of it in `<assets>/walks/<walk id>/`."
    d = tmp/'assets'/'walks'/JID; d.mkdir(parents=True)
    c = d/nb.name
    c.write_text(json.dumps(dict(cells=[dict(cell_type='markdown', metadata={}, source='Back to the walk'), dict(cell_type='markdown', metadata={}, source='## Imports')],
                                 metadata=dict(abhyasa=dict(walk=JID, copy_of=str(nb))), nbformat=4, nbformat_minor=5)))
    lr.put_journey({**j, 'notebook': dict(path=str(nb), copy=str(c))})
    return c

def _open_url(text):
    "The `/hub/open` request the 409 page's Open button posts, as a dict of lists."
    u = text.split('data-url="', 1)[1].split('"', 1)[0].replace('&amp;', '&')
    assert urlsplit(u).path == '/hub/open'
    return parse_qs(urlsplit(u).query)

def test_go_in_a_folder_window_asks_on_a_409_page_and_adds_nothing(rig, tmp_path_factory):
    """`/learn?go` added the project and abhyasa's copies folder to the window by itself."""
    c, ws, lr, j, root = rig
    t = tmp_path_factory.mktemp('learner')
    p, nb = project(t)
    copy = copy_walk(lr, j, t, nb)
    was, roots = (copy.read_bytes(), nb.read_bytes()), list(ws.fs.roots)
    r = c.get(f'/learn?walk={JID}&step=0&cell=1&go=1', follow_redirects=False)
    assert r.status_code == 409 and f'This lesson is in {p.name}' in r.text, r.text
    assert _open_url(r.text) == {'path': [str(p.resolve())], 'file': [str(copy)], 'folder': ['1'], 'also': [str(copy.parent.resolve())]}, 'one question adds both'
    assert list(ws.fs.roots) == roots and ws.tab is None and (copy.read_bytes(), nb.read_bytes()) == was
    assert not (copy.parent/'.venv').exists() and not (root/'lessons').exists()

def test_go_in_the_project_window_opens_the_copy_in_the_project_of_the_notebook(rig, tmp_path_factory):
    "With both folders open, one GET: the copy is the open tab, its kernel runs in the folder of the notebook and the project surfaces follow it."
    c, ws, lr, j, root = rig
    t = tmp_path_factory.mktemp('learner')
    p, nb = project(t)
    copy = copy_walk(lr, j, t, nb)
    ws.add_root(p); ws.add_root(copy.parent)
    r = c.get(f'/learn?walk={JID}&step=0&cell=1&go=1', follow_redirects=False)
    assert r.status_code == 303 and r.headers['location'] == '/?cell=1'
    assert ws.tab.path == str(copy.resolve()) and ws.cwd_for(ws.tab) == nb.parent.resolve() and ws.project_root == p.resolve()

@pytest.fixture
def loose_rig(tmp_path, tmp_path_factory, monkeypatch):
    "`rig` on the loose window."
    from abhyasa.learner import Learning
    from leela.app import ide_app
    from leela.blocks.memory.memory import Memory
    from leela.core.projects import loose_root
    from leela.workspace import Workspace
    from learn_data import walk
    monkeypatch.setattr('leela.blocks.learn.learn.LESSONS', tmp_path_factory.mktemp('home')/'Learning'/'Leela lessons')
    ws = Workspace(roots=[], approvals='auto', python=sys.executable); ws.add_root(loose_root(), loose=True)
    monkeypatch.setattr(ws, 'memory', Memory(path=tmp_path/'vault.db', offline=True))
    lr = Learning(ws.memory._store('learning')); j = walk(lr)
    try:
        with TestClient(ide_app(ws), base_url='http://127.0.0.1:5011') as c: yield c, ws, lr, j, tmp_path
    finally: ws.shutdown_now()

def test_go_in_the_loose_window_opens_a_loose_tab_and_offers_both_folders(loose_rig, tmp_path_factory):
    from leela.core.projects import loose_root
    c, ws, lr, j, root = loose_rig
    t = tmp_path_factory.mktemp('learner'); p, nb = project(t); copy = copy_walk(lr, j, t, nb)
    r = c.get(f'/learn?walk={JID}&step=0&cell=1&go=1', follow_redirects=False)
    assert r.status_code == 303 and list(ws.fs.roots) == [loose_root()] and ws.tab.path == str(copy.resolve())
    assert ws.offers == {str(copy.resolve()): str(p.resolve())} and ws.offer_also == {str(copy.resolve()): [str(copy.parent.resolve())]}, 'the project, not the copies folder'
    st = c.get('/tab/state').json()
    assert st['offer'] == str(p.resolve()) and st['also'] == [str(copy.parent.resolve())]
    c.post('/tab/offer/dismiss', params={'path': str(copy.resolve())})
    assert ws.offers == {} and ws.offer_also == {}

def test_a_link_from_another_site_gets_the_page(rig, tmp_path_factory):
    "A link that the browser marks as from another site opens nothing: it gets the step page with its button."
    c, ws, lr, j, root = rig
    t = tmp_path_factory.mktemp('learner'); p, nb = project(t); copy = copy_walk(lr, j, t, nb)
    r = c.get(f'/learn?walk={JID}&step=0&go=1', headers={'sec-fetch-site': 'cross-site'}, follow_redirects=False)
    assert r.status_code == 200 and 'Open as a lesson' in r.text and not any(x.path == str(copy.resolve()) for x in ws.tabs) and p.resolve() not in ws.fs.roots

def test_reopening_the_copy_from_the_tree_keeps_the_folder(rig, tmp_path_factory):
    "A copy opened again in another way runs in the folder of the notebook too: its metadata names it."
    c, ws, lr, j, root = rig
    t = tmp_path_factory.mktemp('learner'); p, nb = project(t); copy = copy_walk(lr, j, t, nb)
    ws.add_root(p); ws.add_root(copy.parent)
    tab = ws.open(copy)
    assert tab.cwd == str(nb.parent.resolve()) and ws.project_root == p.resolve()

def test_a_folder_of_copies_gets_no_environment(rig, tmp_path_factory):
    "The walk folder of the copies is never a project: Leela offers no .venv there and refuses to make one."
    c, ws, lr, j, root = rig
    t = tmp_path_factory.mktemp('learner'); p, nb = project(t); copy = copy_walk(lr, j, t, nb)
    assert copy_folder(copy.parent) and not copy_folder(p)
    ws.add_root(copy.parent); ws.activate_root(copy.parent)
    assert c.get('/runtime/info').json()['needs_create'] is False
    assert c.post('/runtime/create').status_code >= 400 and not (copy.parent/'.venv').exists()

def test_go_opens_a_notebook_of_the_vault_in_its_project(rig, tmp_path_factory, monkeypatch):
    "`doc=…&go=1` opens the notebook that the vault names, in its own project, at the cell; a doc that is not there says so in one line."
    c, ws, lr, j, root = rig
    t = tmp_path_factory.mktemp('learner'); p, nb = project(t)
    monkeypatch.setattr('abhyasa.path.nb_file', lambda lr, doc, shelf='store': (shelf, str(nb)) if doc == 'nb1' else None)
    r = c.get('/learn?doc=nb1&shelf=notebooks&cell=0&go=1', follow_redirects=False)
    assert r.status_code == 409 and _open_url(r.text) == {'path': [str(p.resolve())], 'file': [str(nb.resolve())], 'folder': ['1']} and ws.tab is None and p.resolve() not in ws.fs.roots
    r = c.post('/learn/open', data=dict(doc='nb1', shelf='notebooks', cell='0'), follow_redirects=False)
    assert r.status_code == 409 and p.resolve() not in ws.fs.roots, 'the POST route asks the same way'
    ws.add_root(p)
    r = c.get('/learn?doc=nb1&shelf=notebooks&cell=0&go=1', follow_redirects=False)
    assert r.status_code == 303 and r.headers['location'] == '/?cell=0' and ws.tab.path == str(nb.resolve())
    assert ws.cwd_for(ws.tab) == nb.parent.resolve()
    r = c.get('/learn?doc=nope&shelf=notebooks&go=1', follow_redirects=False)
    assert r.status_code == 400 and 'not in your learning store' in r.text
