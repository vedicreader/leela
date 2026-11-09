"Learn takes the open folders of a workspace, and files or folders that the learner attaches, as sources; Abhyasa's rules still refuse what it refuses."
import json, tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from abhyasa.learner import temp_learning, use_settings, roots
from abhyasa.sources import root_docs, path_docs
from leela.blocks.learn import tools as T
from leela.blocks.settings import settings as S
from leela.blocks.settings.settings import Settings

TOGGLE = dict(on=False)


@pytest.fixture
def home(monkeypatch):
    "A temporary home folder, so that folders inside it pass `source_root_why`."
    h = Path(tempfile.mkdtemp()).resolve()
    monkeypatch.setenv('HOME', str(h))
    return h


@pytest.fixture
def learn(ws, home, monkeypatch):
    "`ws` over an isolated Learn store, with the setting `workspace_folders` that `TOGGLE` says, and no open folder."
    lr = temp_learning()
    ws.vaults.learn()
    monkeypatch.setattr(ws.vaults, 'memory', lambda name: SimpleNamespace(_store=lambda shelf: lr.v))
    TOGGLE['on'] = False
    monkeypatch.setattr(S.Settings, 'effective', lambda self, *a, **k: {'learn': dict(workspace_folders=TOGGLE['on'])})
    for r in list(ws.fs.roots): ws.drop_root(r)
    ws.learn_src = {}
    return SimpleNamespace(ws=ws, lr=lr, home=home)


def _folder(home, name, **files):
    d = home/name; d.mkdir()
    for n, text in (files or dict(a='alpha text')).items(): (d/f'{n}.md').write_text(text)
    return d


def test_the_toggle_is_a_learn_row_that_is_off_and_saves(tmp_path, monkeypatch):
    from copy import deepcopy
    from leela.blocks.learn.app import learn_rows
    for n in ('DEFAULT_SETTINGS', '_ENUMS', '_RANGES', 'USER_ONLY', 'SECTIONS'): monkeypatch.setattr(S, n, deepcopy(getattr(S, n)))
    row = next(r for r in learn_rows() if r['key'] == 'workspace_folders')
    assert (row['dflt'], row['kind'], row['label']) == (False, 'bool', 'Use the folders of this workspace as sources')
    S.register_section('learn', learn_rows(), 'abhyasa')
    s = Settings(None, user_path=tmp_path/'u.json')
    assert s.effective()['learn']['workspace_folders'] is False
    s.save('user', 'learn', dict(workspace_folders=True))
    assert s.effective()['learn']['workspace_folders'] is True


def test_toggle_off_is_the_old_behaviour(learn):
    d = _folder(learn.home, 'proj'); learn.ws.add_root(str(d))
    assert T.learn_sources(learn.ws) == [] and 'sources.roots' not in T.learn_settings(learn.ws) and T.sources_line(learn.ws) == ''
    assert T.sync_sources(learn.ws) == [] and root_docs(learn.lr, 'proj') == []


def test_toggle_on_lists_the_workspace_folders_and_adds_them_to_the_roots_and_files_them(learn):
    a, b = _folder(learn.home, 'one', x='one text'), _folder(learn.home, 'two', y='two text')
    for d in (a, b): learn.ws.add_root(str(d))
    TOGGLE['on'] = True
    rows = T.sync_sources(learn.ws)
    assert [(r.name, r.origin, r.on, r.why, r.filed) for r in rows] == [('one', 'workspace', True, '', True), ('two', 'workspace', True, '', True)]
    assert [d.title for d in root_docs(learn.lr, 'one')] == ['one/x'] and [d.title for d in root_docs(learn.lr, 'two')] == ['two/y']
    given = T.learn_settings(learn.ws)['sources.roots'].splitlines()
    assert str(a) in given and str(b) in given
    with use_settings(T.learn_settings(learn.ws)): assert {str(a), str(b)} <= set(roots())
    assert 'Workspace folders as sources: on' in T.sources_line(learn.ws) and 'one, two' in T.sources_line(learn.ws)


def test_one_folder_chosen_and_the_choice_is_kept_for_this_workspace(learn):
    a, b = _folder(learn.home, 'one', p='first text'), _folder(learn.home, 'two', q='second text')
    for d in (a, b): learn.ws.add_root(str(d))
    TOGGLE['on'] = True
    T.sync_sources(learn.ws)
    rows = T.learn_untick(learn.ws, str(b))
    assert [(r.name, r.on, r.filed) for r in rows] == [('one', True, True), ('two', False, False)]
    assert root_docs(learn.lr, 'two') == [] and root_docs(learn.lr, 'one')
    assert str(b) not in T.learn_settings(learn.ws)['sources.roots']
    saved = learn.ws.state()['learn_src']
    assert saved['off'] == [str(b)] and json.loads(json.dumps(saved)) == saved
    other = type(learn.ws).__new__(type(learn.ws)); other.restore_settings({'learn_src': saved})
    assert other.learn_src['off'] == [str(b)]
    rows = T.learn_untick(learn.ws, str(b), True)
    assert (rows[1].on, bool(root_docs(learn.lr, 'two'))) == (True, True)


def test_a_workspace_without_folders_has_no_rows_and_says_so(learn):
    TOGGLE['on'] = True
    assert T.sync_sources(learn.ws) == [] and 'sources.roots' not in T.learn_settings(learn.ws)
    assert 'none' in T.sources_line(learn.ws)


def test_a_folder_outside_home_is_refused_with_its_reason_and_never_read(learn, monkeypatch):
    out = Path(tempfile.mkdtemp()).resolve(); (out/'secret.md').write_text('private')
    hidden = _folder(learn.home, '.hid')
    learn.ws.add_root(str(out)); learn.ws.add_root(str(hidden))
    TOGGLE['on'] = True
    read = []
    import abhyasa.sources as A
    monkeypatch.setattr(A, '_file_tree', lambda *a, **k: read.append(a) or [])
    rows = T.sync_sources(learn.ws)
    assert [r.why for r in rows] == ['abhyasa reads only folders in your home folder.', 'abhyasa does not read a hidden folder or a link.']
    assert not any(r.filed for r in rows) and read == []
    assert 'sources.roots' not in T.learn_settings(learn.ws) and 'abhyasa reads only folders' in T.sources_line(learn.ws)


def test_an_attached_file_and_folder_are_filed_and_the_page_lists_them(learn):
    d, f = _folder(learn.home, 'notes', n='notes text'), learn.home/'one.md'
    f.write_text('single file text')
    rows = T.learn_attach(learn.ws, [str(d), str(f), {'kind': 'vault'}, str(learn.home/'missing')])
    assert [(r.name, r.kind, r.origin, r.filed) for r in rows] == [('notes', 'folder', 'attached', True), ('one.md', 'file', 'attached', True)]
    assert [x.title for x in root_docs(learn.lr, 'notes')] == ['notes/n'] and path_docs(learn.lr, f)
    from leela.blocks.learn.ui import SourcesPage
    from fasthtml.common import to_xml
    html = to_xml(SourcesPage(rows, False))
    assert 'notes' in html and 'one.md' in html and 'Remove' in html and 'is off' in html


def test_an_attached_path_outside_home_or_of_a_wrong_type_shows_its_reason(learn):
    out = Path(tempfile.mkdtemp()).resolve(); (out/'x.md').write_text('x')
    odd = learn.home/'pic.png'; odd.write_bytes(b'png')
    rows = T.learn_attach(learn.ws, [str(out), str(out/'x.md'), str(odd)])
    assert all(r.why and not r.filed for r in rows) and len(rows) == 3
    assert 'abhyasa reads only folders' in rows[0].why and 'abhyasa reads only files' in rows[1].why and 'abhyasa adds only these files' in rows[2].why
    assert path_docs(learn.lr, out/'x.md') == []


def test_remove_unfiles_from_learn_and_leaves_the_user_files_alone(learn):
    d, f = _folder(learn.home, 'notes', n='keep me'), learn.home/'one.md'
    f.write_text('single')
    T.learn_attach(learn.ws, [str(d), str(f)])
    assert [r.name for r in T.learn_untick(learn.ws, str(d))] == ['one.md']
    assert root_docs(learn.lr, 'notes') == [] and path_docs(learn.lr, f)
    assert T.learn_untick(learn.ws, str(f)) == [] and path_docs(learn.lr, f) == []
    assert (d/'n.md').read_text() == 'keep me' and f.read_text() == 'single' and sorted(p.name for p in d.iterdir()) == ['n.md']


def test_a_path_that_was_filed_by_hand_is_not_removed_with_the_attachment(learn):
    from abhyasa.sources import file_folder
    d = _folder(learn.home, 'notes', n='by hand')
    file_folder(learn.lr, d)
    T.learn_attach(learn.ws, [str(d)]); T.learn_untick(learn.ws, str(d))
    assert [x.title for x in root_docs(learn.lr, 'notes')] == ['notes/n']


def test_the_sources_page_routes_add_tick_and_remove(learn, monkeypatch):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    d = _folder(learn.home, 'notes'); learn.ws.add_root(str(d)); TOGGLE['on'] = True
    c = TestClient(ide_app(learn.ws), follow_redirects=False)
    r = c.post('/learn/sources/do', data=dict(action='tick', path=str(d), on='0'))
    assert r.status_code == 303 and learn.ws.learn_src['off'] == [str(d)]
    page = c.get('/learn/sources').text
    assert 'notes' in page and 'checked' not in page
    f = learn.home/'f.md'; f.write_text('hello')
    assert c.post('/learn/sources/do', data=dict(action='add', path=str(f))).status_code == 303 and learn.ws.learn_src['added'] == [str(f)]
    assert c.post('/learn/sources/do', data=dict(action='remove', path=str(f))).status_code == 303 and learn.ws.learn_src['added'] == []
    assert c.post('/learn/sources/do', data=dict(action='add', path='')).status_code == 400
    assert f.read_text() == 'hello'
