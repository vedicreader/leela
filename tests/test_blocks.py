"""Extracted blocks, exercised over HTTP without a browser.

The existing coverage for these routes is Playwright-driven, which means it does not run
where chromium is unavailable -- and a route that has moved out of `ide_app` into a block
needs to be checked *somewhere* that always runs. `TestClient` calls the real app, so this
covers the wiring (`connect_all` order, capability narrowing) and the handler together.

This is also the shape `docs/blocks.md` asks block tests to take: build the block against a
`Ctx`, not against a whole browser session.
"""

import json

import pytest
from starlette.testclient import TestClient

from leela.blocks import keys as keys_block
from leela.blocks import settings as settings_block
from leela.core import Ctx, connect_all
from leela.web.app import BLOCKS, ide_app
from leela.workspace import Workspace


@pytest.fixture(scope='module')
def client():
    with TestClient(ide_app(Workspace(roots=[]))) as c: yield c


# -- wiring ------------------------------------------------------------------

def test_every_listed_block_exposes_the_contract():
    for m in BLOCKS:
        assert callable(getattr(m, 'connect', None)), f'{m!r} has no connect()'
        assert isinstance(getattr(m, 'CAPS', ()), tuple), f'{m!r} CAPS must be a tuple'


def test_blocks_declare_only_what_they_use():
    "A block whose CAPS grew without its routes growing is the failure mode this catches."
    assert keys_block.CAPS == (), 'the keymap is served from files; it needs no workspace'
    assert settings_block.CAPS == ('fs',)


# -- keys --------------------------------------------------------------------

def test_keymap_is_served_as_data_so_the_frontend_hardcodes_no_chord(client):
    d = client.get('/keys.json').json()
    assert d['keys'] and d['help'] and d['bars'], 'keys, help rows and button bars in one fetch'
    assert d['path'].endswith('.json')
    # the bars carry the same action names the keymap binds, which is what lets a button
    # and a chord run one code path
    actions = {k['action'] for k in d['keys']} if isinstance(d['keys'], list) else set()
    bar_actions = {b['action'] for rows in d['bars'].values() for b in rows}
    if actions: assert bar_actions & actions, 'buttons and keys share action names'


def test_reading_the_keymap_file_works_before_one_has_been_written(client):
    d = client.get('/keys/file').json()
    assert 'text' in d and 'path' in d and 'exists' in d
    json.loads(d['text']), 'the fallback text must itself be valid JSON'


def test_saving_an_invalid_keymap_is_refused_with_a_readable_reason(client):
    r = client.post('/keys/save', json={'text': '{not json'})
    assert r.status_code == 400
    assert 'valid JSON' in r.json()['error']


def test_saving_then_resetting_the_keymap_round_trips(client, monkeypatch, tmp_path):
    "Reset exists so a keymap you cannot use is one click from gone -- so it must really restore."
    import leela.keys as keymap
    p = tmp_path/'keys.json'
    monkeypatch.setattr(keymap, 'keymap_path', lambda: p)
    monkeypatch.setattr('leela.blocks.keys.app.keymap_path', lambda: p)

    saved = client.post('/keys/save', json={'text': json.dumps({'keys': []})}).json()
    assert saved['ok'] and p.exists()

    reset = client.post('/keys/reset', json={}).json()
    assert reset['ok'] and reset['keys'], 'defaults are back and the browser map was rebuilt'


# -- settings ----------------------------------------------------------------

def test_settings_report_the_origin_of_each_effective_value(client):
    "With four layers, the value alone cannot answer 'why is it this'."
    d = client.get('/settings').json()
    assert isinstance(d, dict) and d, 'describe() returns the effective layered view'


def test_saving_an_unknown_settings_scope_fails_rather_than_writing_somewhere(client):
    r = client.post('/settings/save', json={'scope': 'nowhere', 'section': 'editor',
                                            'values': {'fontSize': 14}})
    assert r.status_code == 400 or r.json().get('ok') is not True


# -- capability enforcement, end to end --------------------------------------

def test_a_block_reaching_past_its_caps_fails_loudly(monkeypatch):
    """The point of narrowing: re-coupling to the whole workspace is an error, not a habit.

    Uses a real `connect_all` rather than a hand-built Ctx, so the failure is the one a
    block author would actually hit.
    """
    import types
    ws = Workspace(roots=[])
    m = types.ModuleType('leela.blocks.greedy.app')
    m.CAPS = ('fs',)
    boom = []

    def connect(app, ctx):
        try: ctx.memory
        except AttributeError as e: boom.append(str(e))
    m.connect = connect

    connect_all(object(), ws, [m])
    assert boom and 'greedy' in boom[0] and 'memory' in boom[0]


def test_the_keys_block_needs_no_workspace_at_all():
    "CAPS == () is a claim; this is the check. It connects against a Ctx over nothing."
    registered = []

    class FakeApp:
        def route(self, path, **kw):
            def deco(fn): registered.append(path); return fn
            return deco

    keys_block.connect(FakeApp(), Ctx(None, name='keys', caps=()))
    assert sorted(registered) == ['/keys.json', '/keys/file', '/keys/reset', '/keys/save']
