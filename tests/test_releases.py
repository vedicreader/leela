"""The release pipeline: what it runs, what it refuses to run, and what it leaves behind.

The steps here are `echo` and `exit 3` rather than `nbdev_prepare`, because the pipeline's
job is the sequencing and the recording -- nbdev's commands are nbdev's to get right. What
matters is that a green step starts the next one, a red step stops the run with its output
kept, and the transcript survives the pty the step was running on.
"""

import asyncio

import pytest

from leela.releases import Release, ReleaseError, default_steps, nbdev_project


def project(root, steps=None, nbdev=False):
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
    """Both ways of configuring nbdev count.

    Every `*easy` package in this workspace uses `[tool.nbdev]` in `pyproject.toml` and has
    no `settings.ini` at all, so a detector that knew only the classic file would decide
    none of them were nbdev projects.
    """
    classic = tmp_path/'classic'
    classic.mkdir()
    (classic/'settings.ini').write_text('[DEFAULT]\nlib_name = thing\nnbs_path = nbs\n')
    assert nbdev_project(classic)
    assert nbdev_project(project(tmp_path/'modern', nbdev=True))
    assert not nbdev_project(project(tmp_path/'plain'))


def test_an_nbdev_project_gets_the_nbdev_pipeline_as_its_default(tmp_path):
    steps = default_steps(project(tmp_path/'nb', nbdev=True))
    assert [s.cmd for s in steps] == ['nbdev_prepare', 'nbdev_bump_version',
                                      'nbdev_release_gh', 'nbdev_pypi']
    assert steps[2].needs == ['GITHUB_TOKEN'], 'the panel can warn before the step fails'
    plain = default_steps(project(tmp_path/'plain'))
    assert 'nbdev' not in ' '.join(s.cmd for s in plain)


def test_a_saved_plan_replaces_the_default_and_survives_a_reload(tmp_path):
    root = project(tmp_path/'p')
    r = Release(root)
    r.save([{'id': 'one', 'label': 'first', 'cmd': 'echo hi'}])
    assert [s.cmd for s in Release(root).steps] == ['echo hi']
    with pytest.raises(ReleaseError, match='at least one step'):
        r.save([{'id': 'empty', 'label': 'nothing', 'cmd': '   '}])


def test_a_green_step_starts_the_next_one_and_a_red_one_stops_the_run(tmp_path):
    root = project(tmp_path/'p', steps=[
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
    # publishing after a failed prepare is not a convenience, so the third never ran
    assert 'gamma' not in r.tail()


def test_the_transcript_covers_the_whole_release_not_just_the_last_step(tmp_path):
    """Each step is its own pty, so the pipeline keeps the log rather than the terminal.

    A panel opened during step three has to be able to read the failure in step two, which
    is the only reason anyone opens it.
    """
    root = project(tmp_path/'p', steps=[
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
    root = project(tmp_path/'p', steps=[{'id': 'a', 'label': 'first', 'cmd': 'echo alpha'}])
    r = Release(root)

    async def go():
        await r.start()
        await settle(r)
        q = r.subscribe()                     # subscribing only after everything finished
        return (await asyncio.wait_for(q.get(), 1)).decode('utf-8', 'replace')
    assert 'alpha' in run(go())


def test_one_step_at_a_time(tmp_path):
    root = project(tmp_path/'p', steps=[{'id': 'a', 'label': 'first', 'cmd': 'sleep 2'}])
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
    root = project(tmp_path/'p', steps=[
        {'id': 'a', 'label': 'first', 'cmd': 'sh -c "exit 1"'},
        {'id': 'b', 'label': 'second', 'cmd': 'echo beta'},
    ])
    r = Release(root)

    async def go():
        await r.start()
        await settle(r)
        r.skip('a')
        await r.start()                       # continues from the step after the skipped one
        await settle(r)
        return r.state()

    state = run(go())
    assert [s['status'] for s in state['steps']] == ['skipped', 'passed']
    assert state['done']
    assert r.reset()['steps'][0]['status'] == 'pending'


def test_a_missing_command_is_reported_as_a_failed_step_not_a_crash(tmp_path):
    root = project(tmp_path/'p', steps=[{'id': 'a', 'label': 'first', 'cmd': 'leela-no-such-command'}])
    r = Release(root)

    async def go():
        await r.start()
        await settle(r)
        return r.state()
    assert run(go())['steps'][0]['status'] == 'failed'


def test_the_keys_a_step_needs_are_reported_before_it_runs(tmp_path, monkeypatch):
    root = project(tmp_path/'p', steps=[
        {'id': 'gh', 'label': 'release', 'cmd': 'echo x', 'needs': ['LEELA_TEST_TOKEN']}])
    r = Release(root)
    assert r.needs() == ['LEELA_TEST_TOKEN']
    assert r.state()['steps'][0]['missing'] == ['LEELA_TEST_TOKEN']
    monkeypatch.setenv('LEELA_TEST_TOKEN', 'set-in-the-environment')
    assert r.state()['steps'][0]['missing'] == []
