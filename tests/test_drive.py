"""Driving the packages a call at a time: what is rendered, and what runs.

The library calls belong to dockeasy, vpseasy, cfeasy and gheasy and are tested there. What
is here is the seam: that the snippet the panel shows is the snippet that runs, that this
project's values are in it, and that a part is a normal pipeline step so everything else
already works.
"""

import pytest

from leela.drive import PARTS, Drive, context, parts


def project(root, name='kalpa'):
    root.mkdir(parents=True, exist_ok=True)
    (root/'pyproject.toml').write_text(f'[project]\nname = "{name}"\nversion = "0"\n')
    return root


class FakeStore:
    def __init__(self, **values): self.values = values
    def get(self, key, secret=True): return self.values.get(key, '')
    def values_for(self, keys): return {}


def test_every_part_names_the_package_it_drives():
    "The panel groups by this, and a part whose package is a guess is not a diagnostic."
    assert {p.package for p in PARTS} == {'dockeasy', 'vpseasy', 'cfeasy', 'gheasy'}
    for p in PARTS:
        assert p.doc and p.code and p.id
        assert p.package in p.code, f'{p.id} claims {p.package} but does not import it'


def test_the_host_is_split_into_the_arguments_cfeasy_takes(tmp_path):
    "setup_tunnel wants a zone and a subdomain, and DOMAIN is written as one host."
    ctx = context(project(tmp_path/'p'), FakeStore(DOMAIN='kalpa.sankalpa.sh'))
    assert ctx['domain'] == 'sankalpa.sh' and ctx['subdomain'] == 'kalpa'
    assert ctx['tunnel'] == 'kalpa_sankalpa.sh'
    apex = context(project(tmp_path/'q'), FakeStore(DOMAIN='sankalpa.sh'))
    assert apex['domain'] == 'sankalpa.sh' and apex['subdomain'] == ''


def test_the_snippet_shown_is_the_snippet_run(tmp_path):
    root = project(tmp_path/'p')
    steps = {s.id: s for s in parts(root, FakeStore(DOMAIN='kalpa.example.com'), python='/usr/bin/python3')}
    tunnel = steps['tunnel']
    assert tunnel.argv[:2] == ['/usr/bin/python3', '-c']
    assert tunnel.argv[2] == tunnel.meta['code'], 'the panel shows argv[2] itself'
    assert "setup_tunnel('example.com', 'kalpa' or None, tunnel_name='kalpa_example.com')" in tunnel.argv[2]
    assert tunnel.needs == ['CLOUDFLARE_API_TOKEN']
    assert tunnel.meta['writes'] == ['CF_TUNNEL_TOKEN'], 'so the panel can draw the hand-off'


def test_a_part_is_an_ordinary_pipeline_step(tmp_path):
    "Same runner as a release and a deploy -- which is what makes the comparison fair."
    root = project(tmp_path/'p')
    state = Drive(root, env=FakeStore()).state()
    assert state['kind'] == 'drive'
    assert [s['id'] for s in state['steps']] == [p.id for p in PARTS]
    assert state['context']['app'] == 'kalpa'
    assert all('code' in s['meta'] for s in state['steps'])


def test_the_snippets_follow_the_values_until_a_plan_is_saved(tmp_path):
    """Setting DOMAIN is often the fix for the part that just failed, so the next run must
    use it -- but an edited plan is the user's and is left alone."""
    root = project(tmp_path/'p')
    store = FakeStore()
    d = Drive(root, env=store)
    assert "setup_tunnel('', '' or None" in d.state()['steps'][2]['meta']['code']
    store.values['DOMAIN'] = 'kalpa.example.com'
    assert "setup_tunnel('example.com', 'kalpa'" in d.state()['steps'][2]['meta']['code']

    d.save([{'id': 'mine', 'label': 'mine', 'cmd': 'echo hello'}])
    store.values['DOMAIN'] = 'other.example.com'
    assert [s['id'] for s in d.state()['steps']] == ['mine'], 'a saved plan is not re-rendered'


def test_running_one_part_runs_only_that_part(tmp_path):
    "The normal move here is one library call; carrying on would defeat the point."
    import asyncio
    root = project(tmp_path/'p')
    d = Drive(root, env=FakeStore())
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
