"Pipelines: releases, deploys, drive, infrastructure and package state."

import asyncio
import os
import pytest
from leela.blocks.pipelines.pipelines import (APP_STEPS, Release, ReleaseError, app_project,
    default_steps, fastship_project, nbdev_project, release_flow)
import ast
from leela.blocks.pipelines.deploys import DEPLOY_KEYS, Deploy, DeployError, deploy_template
from leela.blocks.drive.drive import PARTS, Drive, context, parts
from leela.blocks.stack.infra import Infra, InfraError
from leela.blocks.stack.packages import FAMILY, blame, checkout_for, frames, survey

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

def test_nbdev_is_recognised_from_settings_ini_and_from_pyproject(tmp_path):
    "Both ways of configuring nbdev count."
    classic = tmp_path/'classic'
    classic.mkdir()
    (classic/'settings.ini').write_text('[DEFAULT]\nlib_name = thing\nnbs_path = nbs\n')
    assert nbdev_project(classic)
    assert nbdev_project(project_releas(tmp_path/'modern', nbdev=True))
    assert not nbdev_project(project_releas(tmp_path/'plain'))

def test_an_nbdev_project_gets_the_nbdev_pipeline_as_its_default(tmp_path):
    steps = default_steps(project_releas(tmp_path/'nb', nbdev=True))
    assert [s.cmd for s in steps] == ['nbdev_prepare', 'nbdev_bump_version',
                                      'nbdev_release_gh', 'nbdev_pypi']
    assert steps[2].needs == ['GITHUB_TOKEN'], 'the panel can warn before the step fails'
    plain = default_steps(project_releas(tmp_path/'plain'))
    assert 'nbdev' not in ' '.join(s.cmd for s in plain)

def test_a_python_package_that_is_not_nbdev_gets_the_fastship_pipeline(tmp_path):
    "The flow the pipeline runs is the one the project is, and fastship bumps after releasing."
    root = project_releas(tmp_path/'plain')
    assert fastship_project(root) and release_flow(root) == 'fastship'
    steps = default_steps(root)
    assert [s.id for s in steps] == ['test', 'changelog', 'gh', 'pypi', 'bump']
    assert [s.cmd for s in steps][1:] == ['ship-changelog', 'ship-gh --no_changelog --no_editor --yes',
                                          'ship-pypi', 'ship-bump']
    assert steps[2].needs == ['GITHUB_TOKEN'], 'the panel can warn before the step fails'
    assert Release(root).state()['flow'] == 'fastship'

def test_a_project_with_no_pyproject_stays_on_the_plain_pipeline(tmp_path):
    "fastship reads pyproject.toml. Without one there is nothing for it to release."
    root = tmp_path/'bare'
    root.mkdir()
    assert not fastship_project(root) and release_flow(root) == 'plain'
    assert [s.id for s in default_steps(root)] == ['test', 'build', 'gh', 'pypi']

def test_nbdev_still_wins_over_fastship(tmp_path):
    root = project_releas(tmp_path/'nb', nbdev=True)
    assert not fastship_project(root) and release_flow(root) == 'nbdev'

def test_the_app_bundle_is_spliced_in_after_the_release_it_attaches_to(tmp_path):
    "The release has to exist before assets upload, and the version has to be the released one."
    root = project_releas(tmp_path/'app')
    (root/'setup_app.py').write_text('')
    (root/'tools').mkdir()
    (root/'tools'/'build_release.py').write_text('')
    assert app_project(root)
    assert [s.id for s in default_steps(root)] == ['test', 'changelog', 'gh', 'pypi',
                                                   'app', 'assets', 'bump']
    nb = project_releas(tmp_path/'nbapp', nbdev=True)
    (nb/'setup_app.py').write_text('')
    (nb/'tools').mkdir()
    (nb/'tools'/'build_release.py').write_text('')
    # nbdev bumps before it releases, so the app still goes last, after `pypi`.
    assert [s.id for s in default_steps(nb)] == ['prepare', 'bump', 'gh', 'pypi', 'app', 'assets']
    assert Release(root).state()['app'] is True
    assert [s.needs for s in APP_STEPS] == [[], ['GITHUB_TOKEN']]

def test_a_saved_plan_replaces_the_default_and_survives_a_reload(tmp_path):
    root = project_releas(tmp_path/'p')
    r = Release(root)
    r.save([{'id': 'one', 'label': 'first', 'cmd': 'echo hi'}])
    assert [s.cmd for s in Release(root).steps] == ['echo hi']
    with pytest.raises(ReleaseError, match='at least one step'):
        r.save([{'id': 'empty', 'label': 'nothing', 'cmd': '   '}])

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

def test_the_transcript_covers_the_whole_release_not_just_the_last_step(tmp_path):
    "Each step is its own pty, so the pipeline keeps the log rather than the terminal."
    root = project_releas(tmp_path/'p', steps=[
        {'id': 'a', 'label': 'first', 'cmd': 'echo alpha'},
        {'id': 'b', 'label': 'second', 'cmd': 'echo beta'},
    ])
    r = Release(root)
    async def go():
        await r.start()
        await settle(r)
    run(go())
    tail = r.tail()
    assert 'alpha' in tail and 'beta' in tail
    assert '❯ echo alpha' in tail and '✓ first exited 0' in tail

def test_a_late_viewer_is_replayed_what_it_missed(tmp_path):
    root = project_releas(tmp_path/'p', steps=[{'id': 'a', 'label': 'first', 'cmd': 'echo alpha'}])
    r = Release(root)
    async def go():
        await r.start()
        await settle(r)
        q = r.subscribe()
        return (await asyncio.wait_for(q.get(), 1)).decode('utf-8', 'replace')
    assert 'alpha' in run(go())

def test_one_step_at_a_time(tmp_path):
    root = project_releas(tmp_path/'p', steps=[{'id': 'a', 'label': 'first', 'cmd': 'sleep 2'}])
    r = Release(root)
    async def go():
        await r.start()
        try:
            with pytest.raises(ReleaseError, match='still running'):
                await r.start()
        finally:
            r.stop()
    run(go())

def test_skipping_is_a_decision_and_resetting_forgets_the_attempt(tmp_path):
    root = project_releas(tmp_path/'p', steps=[
        {'id': 'a', 'label': 'first', 'cmd': 'sh -c "exit 1"'},
        {'id': 'b', 'label': 'second', 'cmd': 'echo beta'},
    ])
    r = Release(root)
    async def go():
        await r.start()
        await settle(r)
        r.skip('a')
        await r.start()
        await settle(r)
        return r.state()
    state = run(go())
    assert [s['status'] for s in state['steps']] == ['skipped', 'passed']
    assert state['done']
    assert r.reset()['steps'][0]['status'] == 'pending'

def test_a_missing_command_is_reported_as_a_failed_step_not_a_crash(tmp_path):
    root = project_releas(tmp_path/'p', steps=[{'id': 'a', 'label': 'first', 'cmd': 'leela-no-such-command'}])
    r = Release(root)
    async def go():
        await r.start()
        await settle(r)
        return r.state()
    assert run(go())['steps'][0]['status'] == 'failed'

def test_the_keys_a_step_needs_are_reported_before_it_runs(tmp_path, monkeypatch):
    root = project_releas(tmp_path/'p', steps=[
        {'id': 'gh', 'label': 'release', 'cmd': 'echo x', 'needs': ['LEELA_TEST_TOKEN']}])
    r = Release(root)
    assert r.needs() == ['LEELA_TEST_TOKEN']
    assert r.state()['steps'][0]['missing'] == ['LEELA_TEST_TOKEN']
    monkeypatch.setenv('LEELA_TEST_TOKEN', 'set-in-the-environment')
    assert r.state()['steps'][0]['missing'] == []

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

def project_deploy(root, name='app'):
    root.mkdir(parents=True, exist_ok=True)
    (root/'pyproject.toml').write_text(f'[project]\nname = "{name}"\nversion = "0"\n')
    return root

def test_the_default_stages_are_the_projects_own_deploy_script(tmp_path):
    "Leela runs `deploy.py`, it does not drive vpseasy from inside the editor."
    state = Deploy(project_deploy(tmp_path/'p')).state()
    assert [s['cmd'] for s in state['steps']] == ['python deploy.py env', 'python deploy.py compose',
                                                  'python deploy.py deploy']
    assert state['kind'] == 'deploy'
    assert 'HCLOUD_TOKEN' in state['steps'][-1]['needs']

def test_the_target_reports_what_is_missing_before_anything_runs(tmp_path):
    t = Deploy(project_deploy(tmp_path/'p')).target()
    assert not t['script'] and not t['compose']
    assert set(t['missing']) >= {'HCLOUD_TOKEN', 'CLOUDFLARE_API_TOKEN'}
    assert t['keys']['HCLOUD_TOKEN'] is True and t['keys']['PORT'] is False, 'secret vs variable'

def test_the_scaffold_writes_a_script_that_imports_the_libraries_it_claims(tmp_path):
    root = project_deploy(tmp_path/'p', 'kalpa')
    out = Deploy(root).scaffold(domain='example.com', subdomain='kalpa')
    text = (root/'deploy.py').read_text()
    ast.parse(text)
    for imported in ('from dockeasy import', 'from cfeasy import CF', 'from vpseasy import'):
        assert imported in text
    for cmd in ('env', 'compose', 'deploy', 'nuke'):
        assert f"cmd == '{cmd}'" in text
    assert 'kalpa.example.com' in text, "the host is this project's, not a placeholder"
    assert any(p.endswith('deploy.py') for p in out['written'])
    assert Deploy(root).target()['script']

def test_the_scaffold_declares_the_schema_and_the_workflow_together(tmp_path):
    "The three files have to agree: the workflow's `env:` is the schema it just wrote."
    pytest.importorskip('gheasy')
    root = project_deploy(tmp_path/'p')
    Deploy(root).scaffold(domain='example.com')
    from gheasy.core import GheasyConfig
    schema = GheasyConfig.load(str(root)).env_schema
    assert set(schema) >= set(DEPLOY_KEYS)
    workflow = (root/'.github'/'workflows'/'deploy.yml').read_text()
    for key, default in DEPLOY_KEYS.items():
        assert f'{key}: ${{{{ {"secrets" if default is None else "vars"}.{key} }}}}' in workflow

def test_a_deploy_script_is_not_overwritten_by_accident(tmp_path):
    root = project_deploy(tmp_path/'p')
    (root/'deploy.py').write_text('# mine\n')
    with pytest.raises(DeployError, match='already has a deploy.py'):
        Deploy(root).scaffold(domain='example.com')
    assert (root/'deploy.py').read_text() == '# mine\n'
    Deploy(root).scaffold(domain='example.com', force=True)
    assert 'vpseasy' in (root/'deploy.py').read_text()

def test_a_deploy_needs_somewhere_to_go(tmp_path):
    with pytest.raises(DeployError, match='domain is required'):
        Deploy(project_deploy(tmp_path/'p')).scaffold(domain='')

def test_a_deploy_says_where_it_goes_and_what_is_still_missing():
    assert "host = 'example.com'" in deploy_template('app', 'example.com', '')
    assert "host = 'app.example.com'" in deploy_template('app', 'example.com', 'app')
    assert {p.package for p in PARTS} == {'dockeasy', 'vpseasy', 'cfeasy', 'gheasy'}
    for p in PARTS:
        assert p.doc and p.code and p.id
        assert p.package in p.code, f'{p.id} claims {p.package} but does not import it'
    st = Infra(FakeStore_infra()).status()
    assert set(st) == {'vpseasy', 'cfeasy', 'hcloud_token', 'cf_token', 'keys'}
    assert not st['hcloud_token'] and not st['cf_token']
    assert Infra(FakeStore_infra(HCLOUD_TOKEN='x')).status()['hcloud_token']
    assert st['keys'] == ['HCLOUD_TOKEN', 'CLOUDFLARE_API_TOKEN'], 'the panel can say which to set'
    infra = Infra(FakeStore_infra())
    with pytest.raises(InfraError, match='HCLOUD_TOKEN is not set'):
        infra.servers()
    with pytest.raises(InfraError, match='CLOUDFLARE_API_TOKEN is not set'):
        infra.tunnels()


def project_drive(root, name='kalpa'):
    root.mkdir(parents=True, exist_ok=True)
    (root/'pyproject.toml').write_text(f'[project]\nname = "{name}"\nversion = "0"\n')
    return root

class FakeStore_drive:
    def __init__(self, **values): self.values = values
    def get(self, key, secret=True): return self.values.get(key, '')
    def values_for(self, keys): return {}


def test_the_host_is_split_into_the_arguments_cfeasy_takes(tmp_path):
    "setup_tunnel wants a zone and a subdomain, and DOMAIN is written as one host."
    ctx = context(project_drive(tmp_path/'p'), FakeStore_drive(DOMAIN='kalpa.sankalpa.sh'))
    assert ctx['domain'] == 'sankalpa.sh' and ctx['subdomain'] == 'kalpa'
    assert ctx['tunnel'] == 'kalpa_sankalpa.sh'
    apex = context(project_drive(tmp_path/'q'), FakeStore_drive(DOMAIN='sankalpa.sh'))
    assert apex['domain'] == 'sankalpa.sh' and apex['subdomain'] == ''

def test_the_snippet_shown_is_the_snippet_run(tmp_path):
    root = project_drive(tmp_path/'p')
    steps = {s.id: s for s in parts(root, FakeStore_drive(DOMAIN='kalpa.example.com'), python='/usr/bin/python3')}
    tunnel = steps['tunnel']
    assert tunnel.argv[:2] == ['/usr/bin/python3', '-c']
    assert tunnel.argv[2] == tunnel.meta['code'], 'the panel shows argv[2] itself'
    assert "setup_tunnel('example.com', 'kalpa' or None, tunnel_name='kalpa_example.com')" in tunnel.argv[2]
    assert tunnel.needs == ['CLOUDFLARE_API_TOKEN']
    assert tunnel.meta['writes'] == ['CF_TUNNEL_TOKEN'], 'so the panel can draw the hand-off'

def test_a_part_is_an_ordinary_pipeline_step(tmp_path):
    "Same runner as a release and a deploy -- which is what makes the comparison fair."
    root = project_drive(tmp_path/'p')
    state = Drive(root, env=FakeStore_drive()).state()
    assert state['kind'] == 'drive'
    assert [s['id'] for s in state['steps']] == [p.id for p in PARTS]
    assert state['context']['app'] == 'kalpa'
    assert all('code' in s['meta'] for s in state['steps'])

def test_the_snippets_follow_the_values_until_a_plan_is_saved(tmp_path):
    "Setting DOMAIN is often the fix for the part that just failed, so the next run must"
    root = project_drive(tmp_path/'p')
    store = FakeStore_drive()
    d = Drive(root, env=store)
    assert "setup_tunnel('', '' or None" in d.state()['steps'][2]['meta']['code']
    store.values['DOMAIN'] = 'kalpa.example.com'
    assert "setup_tunnel('example.com', 'kalpa'" in d.state()['steps'][2]['meta']['code']
    d.save([{'id': 'mine', 'label': 'mine', 'cmd': 'echo hello'}])
    store.values['DOMAIN'] = 'other.example.com'
    assert [s['id'] for s in d.state()['steps']] == ['mine'], 'a saved plan is not re-rendered'

def test_running_one_part_runs_only_that_part(tmp_path):
    "The normal move here is one library call; carrying on would defeat the point."
    root = project_drive(tmp_path/'p')
    d = Drive(root, env=FakeStore_drive())
    d.save([{'id': 'a', 'label': 'first', 'cmd': 'echo alpha'},
            {'id': 'b', 'label': 'second', 'cmd': 'echo beta'}])
    async def go():
        await d.start('a', False)
        for _ in range(400):
            if not d.active: break
            await asyncio.sleep(.02)
        return d.state()
    state = asyncio.run(go())
    assert [s['status'] for s in state['steps']] == ['passed', 'pending']
    assert 'beta' not in d.tail()

class FakeStore_infra:
    def __init__(self, **values): self.values = values
    def get(self, key, secret=True): return self.values.get(key, '')


def test_the_token_does_not_outlive_the_call(monkeypatch):
    "It is put in the environment because vpseasy reads it from there, and taken out again."
    monkeypatch.delenv('HCLOUD_TOKEN', raising=False)
    infra = Infra(FakeStore_infra(HCLOUD_TOKEN='secret-value'))
    seen = {}
    class FakeHetzner:
        def __init__(self): seen['env'] = os.environ.get('HCLOUD_TOKEN')
        def servers(self): return [{'name': 'kalpa', 'ip': '1.2.3.4', 'status': 'running'}]
    import leela.blocks.stack.infra as mod
    monkeypatch.setattr(mod.Infra, '_hetzner', lambda self: FakeHetzner())
    assert infra.servers()[0]['name'] == 'kalpa'
    assert os.environ.get('HCLOUD_TOKEN') is None

def test_one_provider_being_down_does_not_hide_the_other(monkeypatch):
    infra = Infra(FakeStore_infra(HCLOUD_TOKEN='x'))
    monkeypatch.setattr(Infra, 'servers', lambda self: [{'name': 'kalpa'}])
    monkeypatch.setattr(Infra, 'tunnels', lambda self: (_ for _ in ()).throw(InfraError('no CF token')))
    monkeypatch.setattr(Infra, 'zones', lambda self: (_ for _ in ()).throw(InfraError('no CF token')))
    out = infra.overview()
    assert out['servers']['rows'] == [{'name': 'kalpa'}] and not out['servers']['error']
    assert out['tunnels']['error'] == 'no CF token' and out['tunnels']['rows'] == []

def test_deleting_refuses_a_server_this_token_cannot_see(monkeypatch):
    "A typo must not reach the provider's delete call at all."
    infra = Infra(FakeStore_infra(HCLOUD_TOKEN='x'))
    monkeypatch.setattr(Infra, 'servers', lambda self: [{'name': 'kalpa'}])
    with pytest.raises(InfraError, match='no server called ghost'):
        infra.delete_server('ghost')
    with pytest.raises(InfraError, match='name the server'):
        infra.delete_server('')

def test_records_mark_the_ones_that_belong_to_a_tunnel(monkeypatch):
    "The answer to 'why is this host serving something else' is usually in this column."
    infra = Infra(FakeStore_infra(CLOUDFLARE_API_TOKEN='x'))
    class FakeCF:
        def zone_id(self, name): return 'z' * 32
        def dns_records(self, zid):
            return [{'id': '1', 'type': 'CNAME', 'name': 'app.example.com',
                     'content': 'abc.cfargotunnel.com', 'proxied': True, 'ttl': 1},
                    {'id': '2', 'type': 'A', 'name': 'old.example.com',
                     'content': '1.2.3.4', 'proxied': False, 'ttl': 300}]
    monkeypatch.setattr(Infra, '_cf', lambda self: FakeCF())
    rows = {r['name']: r for r in infra.records('example.com')}
    assert rows['app.example.com']['tunnel'] and not rows['old.example.com']['tunnel']
    with pytest.raises(InfraError, match='choose a zone'):
        infra.records('')

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

def test_a_checkout_is_found_by_what_it_contains_not_by_its_name(tmp_path):
    "A repository can be called anything; `<root>/<name>/__init__.py` is what makes it the source."
    odd = tmp_path/'my-fork'
    (odd/'cfeasy').mkdir(parents=True)
    (odd/'cfeasy'/'__init__.py').write_text('')
    assert checkout_for('cfeasy', [odd]) == str(odd)
    assert checkout_for('vpseasy', [odd]) == ''

def test_the_deepest_frame_of_yours_is_the_one_to_open(tmp_path):
    "Your deploy calls cfeasy and both are yours -- the one that raised is the one to open."
    checkout = make_checkout(tmp_path, 'cfeasy')
    b = blame(TRACEBACK, checkouts=[checkout])
    assert b['package'] == 'cfeasy' and b['line'] == 57 and b['fn'] == 'tunnels'
    assert b['error'].startswith('cloudflare.AuthenticationError')
    assert b['open'] == str(checkout/'cfeasy'/'core.py'), 'opened where a fix would land'
    assert b['checkout'] == str(checkout)

def test_without_a_checkout_it_still_names_the_package(tmp_path):
    b = blame(TRACEBACK, checkouts=[])
    assert b['package'] == 'cfeasy' and b['open'].endswith('site-packages/cfeasy/core.py')
    assert b['checkout'] == ''

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


def test_a_checkout_shadowed_by_an_installed_copy_is_the_row_worth_seeing(tmp_path, monkeypatch):
    "An edit in the checkout does nothing until the environment is reinstalled."
    import leela.blocks.stack.packages as pkg
    checkout = make_checkout(tmp_path, 'cfeasy')
    monkeypatch.setattr(pkg, '_origin', lambda n: tmp_path/'venv'/'site-packages'/n if n == 'cfeasy' else None)
    rows = {r['name']: r for r in survey(['cfeasy', 'vpseasy'], [checkout])}
    assert rows['cfeasy']['shadowed'] and rows['cfeasy']['source'] == 'site-packages'
    assert rows['cfeasy']['checkout'] == str(checkout)
    assert not rows['vpseasy']['installed'] and not rows['vpseasy']['shadowed']

def test_a_package_run_from_its_checkout_is_not_shadowed(tmp_path, monkeypatch):
    import leela.blocks.stack.packages as pkg
    checkout = make_checkout(tmp_path, 'cfeasy')
    monkeypatch.setattr(pkg, '_origin', lambda n: checkout/'cfeasy')
    row = survey(['cfeasy'], [checkout])[0]
    assert row['source'] == 'checkout' and row['editable'] and not row['shadowed']


VENV_TRACEBACK = '''  File "<string>", line 4, in <module>
  File "/home/you/code/leela/.venv/lib/python3.12/site-packages/cfeasy/core.py", line 110, in setup_tunnel
    tid = first(t)['id']
  File "/home/you/code/leela/.venv/lib/python3.12/site-packages/cloudflare/_client.py", line 1431, in _validate_headers
    raise TypeError("Could not resolve authentication method.")
TypeError: Could not resolve authentication method.
'''
