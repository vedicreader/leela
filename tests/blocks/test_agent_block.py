"""The agent block's routes, now that they are its own rather than `ide_app`'s.

Route presence used to be asserted by grepping `getsource(ide_app)`, which said nothing about
whether the route was reachable and broke the moment the routes moved. Ask the app instead.
"""

from __future__ import annotations
from fastcore.basics import first
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.workspace import Workspace

EXECUTION = ('/agent/run-policy', '/agent/tool-preview', '/agent/retry-tool', '/agent/rollback-tool',
             '/agent/steer', '/agent/state/save', '/agent/state/load')

def paths(app): return {getattr(r, 'path', '') for r in app.routes}

def test_the_execution_surface_is_reachable(tmp_path):
    "Run policies, previews, steering and state memory, each as a live route."
    got = paths(ide_app(Workspace(roots=[tmp_path])))
    missing = [p for p in EXECUTION if p not in got]
    assert missing == [], missing

def test_every_agent_route_comes_from_the_block(tmp_path):
    "A route left behind in `ide_app` is a route the block cannot own."
    from leela.app import ide_app as _f
    import inspect
    assert "rt('/agent" not in inspect.getsource(_f), 'an /agent route is still in ide_app'
    served = [p for p in paths(ide_app(Workspace(roots=[tmp_path]))) if p.startswith('/agent')]
    assert len(served) > 60, len(served)

def test_the_block_declares_what_it_touches():
    from leela.blocks import agent as block
    from leela.core import CAPABILITIES
    assert set(block.CAPS) <= set(CAPABILITIES)
    assert {'ai', 'memory', 'docs'} <= set(block.CAPS)

def test_tool_groups_cover_the_families_the_picker_shows():
    from leela.blocks.agent.turns import TOOL_GROUPS, tool_group
    assert tool_group('search_code') == 'Repository' and tool_group('run_python') == 'Runtime'
    assert tool_group('web_search') == 'Web' and tool_group('edit_cell') == 'Notebook'
    assert tool_group('something_else') == 'Other'
    assert set(TOOL_GROUPS) == {'Repository', 'Runtime', 'Web'}

def test_history_groups_untagged_turns_by_the_gap_between_them():
    "Old history has no session id, so a 30 minute gap is what separates one context from the next."
    from leela.blocks.agent.turns import history_sessions
    turns = [{'at': 0}, {'at': 60}, {'at': 60 + 1801}, {'at': 5000, 'session': 's1'}]
    got = history_sessions(turns)
    assert [len(g['turns']) for g in got] == [1, 1, 2]
    assert got[0]['id'] == 's1'

#: routes that resolve a thread before doing anything else. `/agent/turn` validates its input
#: first, so an empty prompt is a 400 there rather than a refusal about the conversation.
THREAD_ROUTES = ('/agent/approve', '/agent/command', '/agent/history', '/agent/steer')

def test_an_unknown_conversation_is_refused_with_a_code_and_a_sentence(tmp_path):
    """Thread-aware routes answer `code` and `message`, never `error`. A client reading only
    `error` showed a person the word "Conflict" instead of the sentence it was sent.
    """
    app = ide_app(Workspace(roots=[tmp_path]))
    served = paths(app)
    with TestClient(app) as client:
        for path in THREAD_ROUTES:
            assert path in served, path
            r = client.post(path, json={'thread': 'no-such-thread', 'text': 'x'})
            body = r.json()
            assert r.status_code == 409, (path, r.status_code, body)
            assert body.get('code') == 'thread_not_found', (path, body)
            assert body.get('message') and 'error' not in body, (path, body)


def test_history_says_which_app_started_each_conversation(tmp_path):
    """Leela and the ramabana CLI append to one log. The filter that hides the CLI's conversations
    needs to tell them apart, and only Leela marks the sessions it started, so anything unmarked
    is the CLI's.
    """
    from leela.blocks.agent.turns import history_sessions, mark_surface, surfaces
    assert surfaces(tmp_path) == {} and surfaces(None) == {}
    assert mark_surface(tmp_path, '') == {} and mark_surface(None, 's1') == {}
    mark_surface(tmp_path, 'mine', 'agent')
    mark_surface(tmp_path, 'mine', 'agent')            # marking twice writes one row
    assert surfaces(tmp_path) == {'mine': 'agent'}

    turns = [{'session': 'mine', 'at': 1}, {'session': 'theirs', 'at': 2}]
    got = {g['id']: g['app'] for g in history_sessions(turns, (), surfaces(tmp_path))}
    assert got == {'mine': 'leela', 'theirs': 'ramabana'}
    # a kernel-run row with no turns is grouped too, and answers the same question
    only = history_sessions([], [{'id': 'theirs', 'code': 2}], surfaces(tmp_path))
    assert only[0]['app'] == 'ramabana'
    # unmarked history from before this existed reads as the CLI's rather than crashing
    assert all(g['app'] == 'ramabana' for g in history_sessions(turns))


def test_every_routed_job_says_where_its_model_is_spent():
    """The settings pane renders three model controls server-side and the rest from
    `/agent/models`. One copy of the text, because two drifted apart the first time.
    """
    from leela.agent.core import JOBS
    from leela.blocks.agent.models import JOB_HELP
    from leela.app import help_mark
    assert set(JOBS) <= set(JOB_HELP), f'no help for {set(JOBS) - set(JOB_HELP)}'
    assert 'falls back to oneshot' in JOB_HELP['classify']
    # nothing calls the oneshot job directly: it is only what the unset cheap jobs fall back to
    assert 'Nothing calls it directly' in JOB_HELP['oneshot']
    assert 'follows the turn model' in JOB_HELP['summary']
    assert JOB_HELP['turn'] in str(help_mark('turn')) and 'lee-hint' in str(help_mark('turn'))
    assert str(help_mark('nosuchjob'))                 # an unknown job renders, saying nothing


def test_a_tool_installed_into_a_frozen_app_is_actually_found(tmp_path, monkeypatch):
    """The Tools row installs into `extras_site`, because the bundle is signed and read-only, and
    `find_server` looked only on PATH. So in a packaged app the language server installed, worked,
    and was found by nothing: the row went on offering to install it forever."""
    import leela
    from leela.blocks.lsp import lsp
    bin_dir = tmp_path/'extras'/'bin'
    bin_dir.mkdir(parents=True)
    monkeypatch.setattr(leela, 'extras_bin', lambda: bin_dir)
    monkeypatch.setattr(lsp.shutil, 'which', lambda name: None)
    assert lsp.find_server() == (None, None), 'nothing on PATH and nothing installed'
    server = bin_dir/'basedpyright-langserver'
    server.write_text('#!/bin/sh\nexec cat\n')
    assert lsp.find_server() == (None, None), 'a file that cannot be run is not a server'
    server.chmod(0o755)
    name, argv = lsp.find_server()
    assert name == 'basedpyright-langserver'
    assert argv == [str(server), '--stdio'], 'and it is driven the way that server wants'

def test_the_tools_row_reports_what_it_would_install_and_what_is_here(monkeypatch):
    "The row is what a person clicks to get a language server, so it has to answer for one."
    from leela.blocks.agent import models
    monkeypatch.setattr('leela.blocks.lsp.lsp.find_server', lambda: ('basedpyright-langserver', []))
    row = first(r for r in models.tool_rows() if r['value'] == 'langserver')
    assert row['available'] is True and row['found'] == 'basedpyright-langserver'
    assert row['mb'] and row['blurb'] and row['label']
    assert any('basedpyright' in r for r in row['requirements']), 'named, so the install is pinned'
    monkeypatch.setattr('leela.blocks.lsp.lsp.find_server', lambda: (None, None))
    assert first(r for r in models.tool_rows() if r['value'] == 'langserver')['available'] is False
