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
