"Pipelines: releases, deploys, drive, infrastructure and package state."

import asyncio
import os
import pytest
from leela.blocks.pipelines.pipelines import Release, ReleaseError
from leela.blocks.stack.packages import FAMILY, blame, frames

def project_releas(root, steps=None, nbdev=False):
    root.mkdir(parents=True, exist_ok=True)
    (root/'pyproject.toml').write_text('[project]\nname = "p"\nversion = "0"\n'
                                       + ('\n[tool.nbdev]\n' if nbdev else ''))
    if steps is not None:
        import json
        (root/'.leela').mkdir(exist_ok=True)
        (root/'.leela'/'release.json').write_text(json.dumps({'steps': steps}))
    return root

def run(coro): return asyncio.run(coro)

async def settle(r, timeout=15):
    "Wait for the pipeline to stop moving -- steps hand off to each other in the background."
    for _ in range(int(timeout * 50)):
        if not r.active: return
        await asyncio.sleep(.02)
    raise AssertionError(f'{r.active} never finished')


def test_a_green_step_starts_the_next_one_and_a_red_one_stops_the_run(tmp_path):
    root = project_releas(tmp_path/'p', steps=[
        {'id': 'a', 'label': 'first', 'cmd': 'echo alpha'},
        {'id': 'b', 'label': 'second', 'cmd': 'sh -c "exit 3"'},
        {'id': 'c', 'label': 'third', 'cmd': 'echo gamma'},
    ])
    r = Release(root)
    async def go():
        await r.start()
        await settle(r)
        return r.state()
    state = run(go())
    assert [s['status'] for s in state['steps']] == ['passed', 'failed', 'pending']
    assert state['failed'] == 'b' and not state['running']
    assert next(s for s in state['steps'] if s['id'] == 'b')['code'] == 3
    assert 'gamma' not in r.tail()

def test_a_completed_release_is_not_quietly_released_a_second_time(tmp_path):
    "`start` runs on to the end, and that end uploads to PyPI, so only `reset` allows a second."
    r = Release(project_releas(tmp_path/'p', steps=[{'id': 'gh', 'label': 'release', 'cmd': 'echo release'}]))
    async def go():
        await r.start(); await settle(r)
        with pytest.raises(ReleaseError, match='already run'): await r.start()
        r.reset()
        await r.start(); await settle(r)
    run(go())
    assert r.state()['steps'][0]['status'] == 'passed'
    assert r.tail().count('❯ echo release') == 1, 'reset clears the transcript with the results'


def test_each_package_gets_its_own_pipeline(tmp_path):
    """One pipeline per package, and the terminal that watches one is keyed the same way."""
    import subprocess
    from starlette.testclient import TestClient
    from leela.app import ide_app
    from leela.workspace import Workspace
    a, b = project_releas(tmp_path/'a'), project_releas(tmp_path/'b')
    for r in (a, b): subprocess.run(['git', 'init', '-b', 'main'], cwd=r, check=True, capture_output=True)
    with TestClient(ide_app(Workspace(roots=[a, b]))) as client:
        first = client.get('/releases', params={'repo': str(a)}).json()
        second = client.get('/releases', params={'repo': str(b)}).json()
        again = client.get('/releases', params={'repo': str(a)}).json()
    assert first['root'] == str(a) and second['root'] == str(b), (first['root'], second['root'])
    assert again['root'] == str(a), 'asking for one package does not move the other'


def test_the_projects_own_console_script_beats_a_system_one_with_the_other_spelling(tmp_path):
    "The reported failure, exactly: `nbdev_prepare` from a Python 3.8."
    venv_bin = tmp_path/'proj'/'.venv'/'bin'; venv_bin.mkdir(parents=True)
    hyphen = venv_bin/'nbdev-prepare'; hyphen.write_text('#!/bin/sh\nexit 0\n'); hyphen.chmod(0o755)
    system = tmp_path/'system'; system.mkdir()
    underscore = system/'nbdev_prepare'; underscore.write_text('#!/bin/sh\nexit 0\n'); underscore.chmod(0o755)
    root = project_releas(tmp_path/'proj', steps=[{'id': 'p', 'label': 'prepare', 'cmd': 'nbdev_prepare'}])
    p = Release(root, python=str(venv_bin/'python'))
    env = {'PATH': str(system) + os.pathsep + str(venv_bin)}
    assert p._resolve(['nbdev_prepare'], env) == [str(hyphen)], 'the project answers first'
    assert Release(root)._resolve(['nbdev_prepare'], env) == [str(underscore)]


TRACEBACK = '''
❯ python deploy.py deploy
Traceback (most recent call last):
  File "/work/kalpa/deploy.py", line 12, in deploy
    cf.setup_tunnel(domain, sub)
  File "/venv/lib/python3.12/site-packages/cfeasy/core.py", line 110, in setup_tunnel
    tid = first(t)['id'] if (t := exists(self.tunnels())) else self.create_tunnel(tname)['id']
  File "/venv/lib/python3.12/site-packages/cfeasy/core.py", line 57, in tunnels
    aid = account_id or self.account_id()
cloudflare.AuthenticationError: Authentication error [code: 10000]
'''

def make_checkout(root, name):
    (root/name/name).mkdir(parents=True)
    (root/name/name/'__init__.py').write_text('')
    (root/name/name/'core.py').write_text('x = 1\n')
    return root/name


def test_the_deepest_frame_of_yours_is_the_one_to_open(tmp_path):
    "Your deploy calls cfeasy and both are yours -- the one that raised is the one to open."
    checkout = make_checkout(tmp_path, 'cfeasy')
    b = blame(TRACEBACK, checkouts=[checkout])
    assert b['package'] == 'cfeasy' and b['line'] == 57 and b['fn'] == 'tunnels'
    assert b['error'].startswith('cloudflare.AuthenticationError')
    assert b['open'] == str(checkout/'cfeasy'/'core.py'), 'opened where a fix would land'
    assert b['checkout'] == str(checkout)


def test_a_traceback_blames_the_deepest_frame_that_is_yours():
    text = 'Traceback:\n  File "/usr/lib/python3.12/json/decoder.py", line 1, in decode\nValueError: bad'
    b = blame(text)
    assert b['package'] == '' and b['open'] == ''
    assert b['error'] == 'ValueError: bad', 'the exception is still worth reporting'
    got = frames(TRACEBACK)
    assert [f['line'] for f in got] == [12, 110, 57]
    assert got[0]['fn'] == 'deploy'
    for name in ('gheasy', 'dockeasy', 'vpseasy', 'cfeasy'):
        assert name in FAMILY
    b = blame(VENV_TRACEBACK)
    assert b['package'] == 'cfeasy', 'the deepest frame that is actually one of yours'
    assert b['line'] == 110 and b['fn'] == 'setup_tunnel'
    assert b['error'].startswith('TypeError')
    only_theirs = '\n'.join(l for l in VENV_TRACEBACK.splitlines() if 'cfeasy' not in l)
    assert blame(only_theirs)['package'] == ''


VENV_TRACEBACK = '''  File "<string>", line 4, in <module>
  File "/home/you/code/leela/.venv/lib/python3.12/site-packages/cfeasy/core.py", line 110, in setup_tunnel
    tid = first(t)['id']
  File "/home/you/code/leela/.venv/lib/python3.12/site-packages/cloudflare/_client.py", line 1431, in _validate_headers
    raise TypeError("Could not resolve authentication method.")
TypeError: Could not resolve authentication method.
'''


