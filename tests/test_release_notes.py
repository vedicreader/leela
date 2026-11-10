"The release step needs notes before it runs, and every step gets a terminal type."

import asyncio
import subprocess
import time
import pytest
from fastcore.xtras import Path

pullup_pipeline = pytest.importorskip('pullup.pipeline')
if not hasattr(pullup_pipeline, 'write_changelog'): pytest.skip('pullup is older than the release-notes support', allow_module_level=True)

from starlette.testclient import TestClient
from leela.app import ide_app
from leela.workspace import Workspace
from leela.blocks.pipelines.deploys import Deploy
from leela.blocks.pipelines.pipelines import Pipeline, Release

MARK = '<!-- do not remove -->\n'

def git(root, *args): return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout

def project(tmp_path, changelog=None, repo=True, name='fossick'):
    "An nbdev project in a folder of its own, with a repository of its own."
    root = tmp_path.resolve()/name
    root.mkdir(parents=True)
    (root/'pyproject.toml').write_text('[project]\nname = "demo"\nversion = "0.2.0"\n\n[tool.nbdev]\nlib_name = "demo"\n')
    (root/'settings.ini').write_text('[DEFAULT]\nlib_name = demo\nnbs_path = nbs\nversion = 0.2.0\n')
    if changelog is not None: (root/'CHANGELOG.md').write_text(changelog)
    if repo:
        git(root, 'init', '-b', 'main')
        git(root, 'config', 'user.email', 'test@example.com'); git(root, 'config', 'user.name', 'Test')
        git(root, 'add', '.'); git(root, 'commit', '-m', 'start')
    return root

@pytest.fixture
def fake(tmp_path, monkeypatch):
    "A stand-in for nbdev-release-gh that records its arguments and TERM. Nothing here can reach the real one."
    out = tmp_path.resolve()/'out'; out.mkdir()
    exe = out/'nbdev-release-gh'
    exe.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$OUT/calls.txt"\nprintf "%s\\n" "$TERM" >> "$OUT/term.txt"\n')
    exe.chmod(0o755)
    monkeypatch.setenv('OUT', str(out)); monkeypatch.delenv('TERM', raising=False)
    monkeypatch.setattr(Release, '_resolve', lambda self, argv, env: [str(exe), *argv[1:]])
    return out

def calls(out):
    "One line per run of the fake: the arguments it got."
    return (out/'calls.txt').read_text().splitlines() if (out/'calls.txt').exists() else []

def served(tmp_path): return TestClient(ide_app(Workspace(roots=[tmp_path.resolve()])))

def wait(client, root, timeout=20):
    "Poll the panel's state until the step has stopped moving."
    end = time.time() + timeout
    while time.time() < end:
        st = client.get('/releases', params={'repo': str(root)}).json()
        if not st['running']: return st
        time.sleep(.05)
    raise AssertionError('the step never finished')

def act(client, root, **kw): return client.post('/releases/action', json={'repo': str(root), **kw})

def row(st, step='gh'): return next(r for r in st['steps'] if r['id'] == step)

def test_every_pipeline_kind_gives_its_steps_a_terminal_type(tmp_path, monkeypatch):
    monkeypatch.delenv('TERM', raising=False)
    root = project(tmp_path)
    for cls in (Release, Deploy, Pipeline): assert cls(root)._env()['TERM'] == 'xterm-256color', cls
    monkeypatch.setenv('TERM', 'dumb')
    assert Release(root)._env()['TERM'] == 'xterm-256color'
    monkeypatch.setenv('TERM', 'screen')
    assert Release(root)._env()['TERM'] == 'screen'

def test_with_no_entry_the_step_waits_for_notes_instead_of_running(tmp_path, fake):
    root = project(tmp_path, f'# Release notes\n\n{MARK}\n## 0.1.0\n\n- old\n')
    with served(tmp_path) as client:
        st = act(client, root, op='start', step='gh', auto=True).json()
        assert not calls(fake), 'the step did not run'
        assert row(st)['status'] == 'needs_notes' and st['failed'] == '' and not st['running']
        assert st['notes']['version'] == '0.2.0' and st['notes']['heading'] == '## 0.2.0'
        assert row(st, 'pypi')['status'] == 'pending', 'and nothing after it ran'
        assert client.get('/releases', params={'repo': str(root)}).json()['notes']['version'] == '0.2.0', 'cancel is a click in the panel: the server keeps asking until there are notes'

def test_saving_notes_writes_commits_by_path_and_runs_the_step_quiet(tmp_path, fake):
    root = project(tmp_path, f'# Release notes\n\n{MARK}\n## 0.1.0\n\n- old\n')
    (root/'other.txt').write_text('staged by someone else'); git(root, 'add', 'other.txt')
    with served(tmp_path) as client:
        act(client, root, op='start', step='gh', auto=False)
        r = act(client, root, op='notes', text='- Fix the login error\n')
        assert r.status_code == 200, r.text
        st = wait(client, root)
    assert row(st)['status'] == 'passed' and st['notes'] is None
    assert calls(fake)[0].split() == ['--no-changelog', '--no-editor', '--yes']
    assert len(calls(fake)) == 2, 'the release carried on to the next step, which the fake also stood in for'
    assert (fake/'term.txt').read_text().split()[0] == 'xterm-256color'
    text = (root/'CHANGELOG.md').read_text()
    assert text.index('## 0.2.0') < text.index('## 0.1.0') and '- Fix the login error' in text
    assert git(root, 'log', '-1', '--format=%s').strip() == 'Release notes for 0.2.0'
    assert git(root, 'show', '--name-only', '--format=', 'HEAD').split() == ['CHANGELOG.md'], 'only that path is committed'
    assert git(root, 'diff', '--cached', '--name-only').split() == ['other.txt'], 'what someone else staged stays staged'

def test_empty_notes_are_refused_and_nothing_is_written(tmp_path, fake):
    root = project(tmp_path)
    with served(tmp_path) as client:
        act(client, root, op='start', step='gh', auto=False)
        r = act(client, root, op='notes', text='  \n ')
        assert r.status_code == 400 and r.json()['error'] == 'Write the release notes first.'
        assert row(client.get('/releases', params={'repo': str(root)}).json())['status'] == 'needs_notes'
    assert not (root/'CHANGELOG.md').exists() and not calls(fake)

def test_notes_with_no_step_waiting_are_refused(tmp_path, fake):
    root = project(tmp_path)
    with served(tmp_path) as client:
        r = act(client, root, op='notes', text='- x')
    assert r.status_code == 400 and r.json()['error'] == 'No step is waiting for release notes.'

def test_a_changelog_with_the_entry_skips_the_box_and_runs_with_the_three_flags(tmp_path, fake):
    root = project(tmp_path, f'# Release notes\n\n{MARK}\n## 0.2.0\n\n- done\n\n## 0.1.0\n\n- old\n')
    (root/'settings.ini').write_text((root/'settings.ini').read_text() + '# changed\n')   # pullup 0.0.14 runs nbdev-release-git on a clean tree
    with served(tmp_path) as client:
        act(client, root, op='start', step='gh', auto=False)
        st = wait(client, root)
    assert row(st)['status'] == 'passed' and st['notes'] is None
    assert calls(fake)[0].split() == ['--no-changelog', '--no-editor', '--yes']

def test_a_failed_commit_shows_its_reason_and_a_retry_checks_the_file_again(tmp_path, fake):
    root = project(tmp_path, f'{MARK}\n## 0.1.0\n\n- old\n')
    hook = root/'.git'/'hooks'/'pre-commit'
    hook.write_text('#!/bin/sh\necho "the hook says no" >&2\nexit 1\n'); hook.chmod(0o755)
    with served(tmp_path) as client:
        act(client, root, op='start', step='gh', auto=False)
        r = act(client, root, op='notes', text='- new')
        assert r.status_code == 400
        err = r.json()['error']
        assert 'git did not commit' in err and 'the hook says no' in err and 'CHANGELOG.md' in err
        assert not calls(fake), 'a failed commit does not release'
        hook.unlink()
        act(client, root, op='start', step='gh', auto=False)
        st = wait(client, root)
    assert row(st)['status'] == 'passed', 'the entry is in the file now, so a retry runs the step'

def test_a_project_that_is_not_a_repository_says_so_after_saving(tmp_path, fake):
    root = project(tmp_path, repo=False)
    rel = Release(root)
    asyncio.run(rel.start('gh', auto=False))
    with pytest.raises(Exception) as e: rel.save_notes('- new')
    assert 'not in a git repository' in e.value.said and (root/'CHANGELOG.md').read_text().count('- new') == 1

def test_skip_still_works_on_a_step_that_waits_for_notes(tmp_path, fake):
    root = project(tmp_path)
    with served(tmp_path) as client:
        act(client, root, op='start', step='gh', auto=False)
        st = act(client, root, op='skip', step='gh').json()
    assert row(st)['status'] == 'skipped' and st['notes'] is None

def test_a_release_json_that_names_its_own_command_is_left_alone(tmp_path, fake):
    root = project(tmp_path)
    (root/'.leela').mkdir()
    (root/'.leela'/'release.json').write_text('{"steps": [{"id": "gh", "label": "mine", "cmd": "nbdev-release-gh --token abc"}]}')
    with served(tmp_path) as client:
        act(client, root, op='start', step='gh', auto=False)
        st = wait(client, root)
    assert row(st)['status'] == 'passed' and st['notes'] is None
    assert calls(fake)[0].split() == ['--token', 'abc']

def test_the_panel_asks_for_notes_in_plain_words():
    js = (Path(__file__).resolve().parent.parent/'leela'/'blocks'/'pipelines'/'releases.js').read_text()
    for need in ('Release notes for ${esc(n.version)}', 'Save and release', 'Cancel', 'Write the release notes first.', "op: 'notes'"):
        assert need in js, need
