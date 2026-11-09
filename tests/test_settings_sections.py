"A package registers a settings section; Learn's comes from Abhyasa's metadata and only the user's file sets it."
import json
from unittest.mock import MagicMock
from copy import deepcopy
import pytest
from leela.blocks.settings import settings as S
from leela.blocks.settings.settings import Settings, register_section
from leela.blocks.learn.app import learn_rows
from leela.blocks.learn.speech import speech_rows

ROWS = [dict(key='steps', dflt=7, kind='int', lo=3, hi=7), dict(key='mode', dflt='a', kind='choice', choices=('a', 'b')),
        dict(key='on', dflt=True, kind='bool'), dict(key='share', dflt=.5, kind='float', lo=0., hi=1.)]

@pytest.fixture
def reg(monkeypatch):
    for n in ('DEFAULT_SETTINGS', '_ENUMS', '_RANGES', 'USER_ONLY', 'SECTIONS'): monkeypatch.setattr(S, n, deepcopy(getattr(S, n)))

def _s(tmp_path, repo=None):
    if repo is not None:
        (tmp_path/'proj'/'.leela').mkdir(parents=True)
        (tmp_path/'proj'/'.leela'/'settings.json').write_text(json.dumps(repo))
    return Settings(tmp_path/'proj' if repo is not None else None, user_path=tmp_path/'user.json')

def test_a_section_saves_validates_describes_and_resets(reg, tmp_path):
    register_section('demo', ROWS, 'test', user_only=False)
    register_section('demo', ROWS, 'test', user_only=False)
    s = _s(tmp_path)
    assert s.effective()['demo'] == {'steps': 7, 'mode': 'a', 'on': True, 'share': .5}
    d = s.save('user', 'demo', {'steps': '4', 'mode': 'b', 'on': False})
    assert d['effective']['demo']['steps'] == 4 and d['origins']['demo']['steps'] == 'user' and d['origins']['demo']['share'] == 'default'
    assert {r['key'] for r in d['sections']['demo']} == {'steps', 'mode', 'on', 'share'}
    for bad in ({'steps': 9}, {'mode': 'c'}, {'share': 2}, {'nope': 1}): pytest.raises(ValueError, s.save, 'user', 'demo', bad)
    s.save('user', 'demo', {'steps': 3}, language='python')
    assert s.effective('python')['demo']['steps'] == 3 and s.describe('python')['origins']['demo']['steps'] == 'user:python'
    assert s.reset('user', 'demo')['effective']['demo']['steps'] == 7

def test_conflicting_registrations_are_refused(reg):
    register_section('demo', ROWS, 'test')
    for name, rows, owner in (('demo', ROWS[:2], 'test'), ('demo', ROWS, 'other'), ('editor', ROWS, 'test'), ('learning', ROWS, 'test'), ('languages', ROWS, 'test')):
        pytest.raises(ValueError, register_section, name, rows, owner)

def test_learn_comes_from_abhyasa_and_leaves_vault_and_host_owned_rows_out(reg, tmp_path):
    rows = learn_rows(); keys = {r['key'] for r in rows}
    assert {'walks.steps', 'checks.tries', 'review.solid', 'guide.point', 'research.on'} <= keys
    assert not [k for k in keys if k.split('.')[0] in ('learning', 'look', 'voice', 'stt', 'models', 'tokens', 'prompts', 'sources')]
    register_section('learn', rows, 'abhyasa')
    s = _s(tmp_path)
    for bad in ({'guide.point': 'x'}, {'walks.steps': 9}, {'links.pages': 51}, {'checks.tries': 0}): pytest.raises(ValueError, s.save, 'user', 'learn', bad)
    assert s.save('user', 'learn', {'guide.point': 'ring', 'links.pages': '20'})['effective']['learn']['links.pages'] == 20

def test_a_repo_cannot_set_learn_at_top_level_or_per_language(reg, tmp_path):
    register_section('learn', learn_rows(), 'abhyasa')
    s = _s(tmp_path, {'learn': {'walks.steps': 3}, 'languages': {'python': {'learn': {'checks.tries': 5}}}, 'editor': {'fontSize': 20}})
    assert s.effective('python')['learn']['walks.steps'] == 7 and s.effective('python')['learn']['checks.tries'] == 3
    assert s.effective()['editor']['fontSize'] == 20
    d = s.describe('python')
    assert d['ignored'] == ['learn.checks.tries', 'learn.walks.steps']
    assert d['origins']['learn']['walks.steps'] == 'default' and d['origins']['learn']['checks.tries'] == 'default'
    with pytest.raises(ValueError, match='user settings for all languages'): s.save('workspace', 'learn', {'walks.steps': 4})
    with pytest.raises(ValueError, match='user settings for all languages'): s.save('user', 'learn', {'walks.steps': 4}, language='python')
    assert json.loads((tmp_path/'proj'/'.leela'/'settings.json').read_text())['learn'] == {'walks.steps': 3}
    assert s.save('user', 'learn', {'walks.steps': 5})['effective']['learn']['walks.steps'] == 5

def test_a_full_reset_keeps_ramabanas_learning_and_a_legacy_snapshot_is_compacted(reg, tmp_path):
    register_section('learn', learn_rows(), 'abhyasa')
    s = _s(tmp_path)
    snapshot = {**{r['key']: r['dflt'] for r in learn_rows()}, 'checks.tries': 5}
    (tmp_path/'user.json').write_text(json.dumps({'learning': {'notes': [1]}, 'learn': snapshot, 'editor': {'fontSize': 12}}))
    assert s.raw('user')['learn'] == {'checks.tries': 5}
    s.reset('user')
    assert json.loads((tmp_path/'user.json').read_text()) == {'learning': {'notes': [1]}}

def test_learn_bound_uses_effective_cap_and_validates_the_whole_change(reg, tmp_path):
    rows = learn_rows()
    assert next(r for r in rows if r['key'] == 'links.pages')['hi_key'] == 'links.cap'
    register_section('learn', rows, 'abhyasa')
    s = _s(tmp_path)
    with pytest.raises(ValueError): s.save('user', 'learn', {'links.pages': 21})
    assert not s.user_path.exists()
    s.save('user', 'learn', {'links.cap': '30', 'links.pages': '25'})
    before = s.user_path.read_bytes()
    with pytest.raises(ValueError): s.save('user', 'learn', {'links.cap': 24})
    assert s.user_path.read_bytes() == before
    s.save('user', 'learn', {'links.cap': 12, 'links.pages': 10})
    with pytest.raises(ValueError): s.save('user', 'learn', {'links.pages': 13})

def test_learn_connect_registers_for_multiple_apps_without_writing(reg, tmp_path, monkeypatch):
    from fasthtml.common import FastHTML
    from leela.blocks.learn.app import connect
    p = tmp_path/'settings.json'
    monkeypatch.setattr(S, 'user_settings_file', lambda: p)
    for _ in range(2): connect(FastHTML(), MagicMock())
    assert S.SECTIONS['learn']['rows'] == learn_rows()
    assert S.SECTIONS['speech']['rows'] == speech_rows() and S.SECTIONS['speech']['owner'] == 'abhyasa'
    assert not p.exists()

def test_learn_missing_package_skips_registration(reg, monkeypatch, caplog):
    import builtins
    from fasthtml.common import FastHTML
    from leela.blocks.learn.app import connect
    original = builtins.__import__
    def missing(name, *args, **kwargs):
        if name == 'abhyasa.learner': raise ImportError('missing settings')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', missing)
    S.SECTIONS.pop('learn', None); S.SECTIONS.pop('speech', None)
    connect(FastHTML(), MagicMock())
    assert 'learn' not in S.SECTIONS and 'speech' not in S.SECTIONS
    assert any(r.levelname == 'WARNING' and 'Learn settings unavailable' in r.getMessage() for r in caplog.records)

def test_percent_conversion():
    import subprocess
    from pathlib import Path
    source = (Path(__file__).resolve().parent.parent/'leela/blocks/settings/prefs.js').read_text()
    start = source.index('function settingsPercent(')
    helper = source[start:source.index('\n}', start)+2]
    subprocess.run(['node', '-e', helper + r'''
const assert = require('node:assert/strict');
assert.equal(settingsPercent(1/3), 33);
assert.equal(settingsPercent(.29), 29);
assert.equal(settingsPercent(33, 1/3), 1/3);
assert.equal(settingsPercent(42, 1/3), .42);
assert.equal(settingsPercent(0, .5), 0);
'''], check=True)

def test_import_does_not_write_user_settings(tmp_path):
    import os, subprocess, sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    code = r'''
from tools.isolate import isolate
from pathlib import Path
import sys
base = isolate(sys.argv[1])
from leela.blocks.settings.settings import user_settings_file
from leela.blocks.learn.app import learn_rows
assert not Path(user_settings_file()).exists()
learn_rows()
assert not Path(user_settings_file()).exists()
'''
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join([str(root), *sys.path[1:], os.environ.get('PYTHONPATH', '')])}
    subprocess.run([sys.executable, '-c', code, str(tmp_path)], check=True, cwd=root, env=env)

def test_learn_page_text_says_the_settings_are_used():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent/'leela'
    for f in ('blocks/settings/prefs.js', 'static/lee-ide.js'):
        text = (root/f).read_text()
        assert 'These settings change the Learn pages and the Learn tools.' in text and 'speech input' not in text and 'are coming' not in text
