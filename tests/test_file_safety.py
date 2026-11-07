"Data a person keeps: settings files, the trash, file history and the go-to-file walk."
import json
import pytest
from fastcore.all import Path
from starlette.testclient import TestClient
from leela.blocks.settings.settings import BrokenSettings, Settings

def test_a_settings_file_that_does_not_parse_is_never_saved_over(tmp_path):
    "A typo wiped every user setting at the next save: the broken file read as {}, and {} plus one change was written over it."
    user = tmp_path/'settings.json'; broken = '{"editor": {"fontSize": 15,}}'
    user.write_text(broken)
    s = Settings(user_path=user)
    with pytest.raises(BrokenSettings, match='not valid JSON'): s.save('user', 'editor', {'tabSize': 2})
    with pytest.raises(BrokenSettings): s.reset('user', 'editor')
    assert user.read_text() == broken, 'the file is left as it was'
    assert (tmp_path/'settings.json.bad').read_text() == broken
    d = s.describe()
    assert 'settings.json.bad' in d['problems']['user'] and d['effective']['editor']['fontSize'] == 13, 'reads stay lenient'
    user.write_text('{"editor": {"fontSize": 15}}')
    assert s.save('user', 'editor', {'tabSize': 2})['problems'] == {}
    assert json.loads(user.read_text())['editor'] == {'fontSize': 15, 'tabSize': 2}

def test_the_workspace_layer_and_odd_files_are_refused_too(tmp_path):
    root = tmp_path/'p'; (root/'.leela').mkdir(parents=True)
    ws = root/'.leela'/'settings.json'; ws.write_text('[1, 2]')
    s = Settings(root, tmp_path/'user.json')
    with pytest.raises(BrokenSettings, match='JSON object'): s.save('workspace', 'editor', {'tabSize': 2})
    assert ws.read_text() == '[1, 2]'
    ws.write_bytes(b'{"editor": "\xff"}')
    with pytest.raises(BrokenSettings): s.save('workspace', 'editor', {'tabSize': 2})
    ws.write_text('{"languages": []}')
    with pytest.raises(BrokenSettings, match='languages'): s.save('workspace', 'editor', {'tabSize': 2}, language='python')
    ws.write_text('')
    s.save('workspace', 'editor', {'tabSize': 2})
    assert json.loads(ws.read_text()) == {'editor': {'tabSize': 2}}, 'an empty file holds nothing to lose'

def test_the_settings_route_answers_the_refusal(ws, cfg_home):
    from leela.app import ide_app
    user = Path(cfg_home)/'settings.json'; user.write_text('{oops')
    with TestClient(ide_app(ws)) as c:
        r = c.post('/settings/save', json={'scope': 'user', 'section': 'editor', 'values': {'tabSize': 2}})
        assert r.status_code == 400 and 'not valid JSON' in r.json()['error']
        assert 'user' in c.get('/settings').json()['problems']
    assert user.read_text() == '{oops'

def test_go_to_file_and_replace_say_when_the_walk_was_cut(tmp_path, monkeypatch):
    "Go-to-file stopped at 20000 files and said `partial: False`, and replace searched the same 20000 without a word."
    from leela.app import ide_app
    from leela.workspace import Workspace
    root = tmp_path/'big'; root.mkdir()
    for i in range(12): (root/f'm{i:02}.py').write_text('old = 1\n')
    monkeypatch.setattr('leela.blocks.fs.app.FIND_LIMIT', 5); monkeypatch.setattr('leela.blocks.fs.fs.WALK_LIMIT', 5)
    with TestClient(ide_app(Workspace(roots=[str(root)]))) as c:
        assert c.get('/fs/find', params={'q': 'm'}).json()['partial'] is True
        s = c.post('/replace/preview', json={'find': 'old', 'replace': 'new'}).json()['summary']
        assert s['partial'] is True and s['searched'] == 5 and s['files'] == 5
        monkeypatch.setattr('leela.blocks.fs.app.FIND_LIMIT', 50); monkeypatch.setattr('leela.blocks.fs.fs.WALK_LIMIT', 50)
        assert c.get('/fs/find', params={'q': 'm11'}).json()['partial'] is False
        assert c.post('/replace/preview', json={'find': 'old', 'replace': 'new'}).json()['summary']['partial'] is False

def test_go_to_file_reaches_past_twenty_thousand_files(tmp_path):
    from leela.blocks.fs.fs import FIND_LIMIT, Sandbox
    assert FIND_LIMIT >= 100_000
    root = tmp_path/'r'
    for d in range(3):
        (root/f'd{d}').mkdir(parents=True)
        for f in range(10): (root/f'd{d}'/f'f{f}.py').touch()
    files, cut = Sandbox([root]).walk_capped(None, False, 29)
    assert len(files) == 29 and cut
    assert Sandbox([root]).walk_capped(None, False, 30) == (sorted(root.rglob('*.py')), False)

def _trash(tmp_path, **kw):
    from leela.core.session import Trash
    t = Trash(tmp_path/'trash', **kw); t.prune()
    return t

def _aged(t, key, days):
    import os, time
    then = time.time() - days*86400
    os.utime(t.root/key, (then, then))

def test_the_trash_is_emptied_by_age_and_by_size(tmp_path):
    "The trash was never emptied: every deleted folder stayed on disk for ever."
    t = _trash(tmp_path, days=30, most=150, fresh=3600)
    keys = []
    for i, n in enumerate((100, 100, 100)):
        f = tmp_path/f'f{i}'; f.write_bytes(b'x'*n); keys.append(t.keep(f))
    _aged(t, keys[0], 40); _aged(t, keys[1], 2); _aged(t, keys[2], 1)
    t.prune()
    assert t.held(keys[0]) is None, 'past 30 days'
    assert t.held(keys[1]) is None and t.held(keys[2]) is not None, 'then the oldest, until the rest fit'
    big = tmp_path/'big'; big.write_bytes(b'x'*1000); k = t.keep(big); t.prune()
    assert t.held(k) is not None, 'the delete just made stays, whatever its size'

def test_a_folder_on_another_disk_goes_to_that_disks_trash_and_comes_back(tmp_path, monkeypatch):
    "A folder on another disk was copied across disks into the trash, byte by byte."
    from leela.core.session import Trash
    t = _trash(tmp_path)
    vol = tmp_path/'otherdisk'; (vol/'proj'/'pkg').mkdir(parents=True); (vol/'proj'/'pkg'/'a.py').write_text('x')
    monkeypatch.setattr(Trash, '_same_volume', lambda self, p: False)
    monkeypatch.setattr(Trash, '_volume_trash', lambda self, p: (vol/'.Trash-501').mkdir(exist_ok=True) or vol/'.Trash-501')
    moves = []
    import shutil
    real = shutil.move
    monkeypatch.setattr(shutil, 'move', lambda a, b: moves.append((a, b)) or real(a, b))
    key = t.keep(vol/'proj'/'pkg')
    assert moves[0][1].startswith(str(vol/'.Trash-501')), 'moved within its own disk'
    assert t.held(key).name == 'pkg' and not (vol/'proj'/'pkg').exists()
    t.restore(key, vol/'proj'/'pkg')
    assert (vol/'proj'/'pkg'/'a.py').read_text() == 'x' and not (t.root/f'{key}.where').exists()

def test_a_folder_on_another_disk_with_no_trash_there_is_refused(tmp_path, monkeypatch):
    from leela.core.session import Trash
    t = _trash(tmp_path)
    d = tmp_path/'pkg'; d.mkdir(); (d/'a.py').write_text('x')
    monkeypatch.setattr(Trash, '_same_volume', lambda self, p: False)
    monkeypatch.setattr(Trash, '_volume_trash', lambda self, p: None)
    with pytest.raises(OSError, match='another disk'): t.keep(d)
    assert (d/'a.py').read_text() == 'x'
    f = tmp_path/'one.txt'; f.write_text('y')
    assert t.held(t.keep(f)).read_text() == 'y', 'a single file may still be copied across'

def test_delete_route_refuses_a_cross_disk_folder_and_keeps_it(tmp_path, monkeypatch):
    from leela.app import ide_app
    from leela.workspace import Workspace
    from leela.core.session import Trash
    root = tmp_path/'p'; (root/'pkg').mkdir(parents=True); (root/'pkg'/'a.py').write_text('x')
    monkeypatch.setattr(Trash, '_same_volume', lambda self, p: False)
    monkeypatch.setattr(Trash, '_volume_trash', lambda self, p: None)
    with TestClient(ide_app(Workspace(roots=[str(root)]))) as c:
        r = c.post('/fs/delete', json={'path': str(root/'pkg')})
        assert r.status_code >= 400 and 'another disk' in r.text
    assert (root/'pkg'/'a.py').exists()
