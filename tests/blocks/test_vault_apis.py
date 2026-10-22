"""Calling a described API with the caller's own key, and reaching the news shelf from a turn."""

from __future__ import annotations

import pytest

from leela.blocks.agent.ai import WorkspaceHost, api_context, ide_tools
from leela.blocks.vault.spec import Creds, SpecError, env_status, expand
from leela.workspace import Workspace


class _Store:
    "Enough of `EnvStore` to keep a value: leela's real one writes to the keychain."
    def __init__(self): self.kv = {}
    def get(self, key, secret=True): return self.kv.get(key, '')
    def set(self, key, value, secret=True): self.kv[key] = str(value); return {'key': key}
    def unset(self, key): return {'key': key, 'removed': bool(self.kv.pop(key, None))}


# ── the environment behind a header ─────────────────────────────────────────


def test_what_is_missing_here_is_reported_rather_than_sent():
    headers = {'Authorization': 'Bearer ${COSTING_TOKEN}'}
    assert env_status(headers, {}) == {'COSTING_TOKEN': False}
    assert expand(headers, {'COSTING_TOKEN': 'k1'}) == {'Authorization': 'Bearer k1'}
    with pytest.raises(SpecError) as e: expand(headers, {})
    assert 'COSTING_TOKEN' in str(e.value)


# ── where they are kept ─────────────────────────────────────────────────────


def test_the_index_is_header_names_and_the_values_are_kept_elsewhere(tmp_path):
    "The file says which specs are keyed. A secret in it would be a secret in a config folder."
    p = tmp_path/'c.json'
    Creds(path=p, store=_Store()).set('stripe', {'Authorization': 'Bearer sk_live_supersecret'})
    assert 'Authorization' in p.read_text() and 'sk_live_supersecret' not in p.read_text()


def test_an_index_written_before_there_was_a_policy_still_reads(tmp_path):
    p = tmp_path/'c.json'
    p.write_text('{"stripe": ["Authorization"]}')
    assert Creds(path=p, store=_Store()).policies()['stripe'] == dict(
        headers=['Authorization'], refs=[], reach='cloud')


# ── the host that calls ─────────────────────────────────────────────────────

class FakeClient:
    def __init__(self, headers): self.headers = dict(headers)
    def get_balance(self, **kw): return {'ok': 'get_balance'}
    def list_repos(self, **kw): return {'ok': 'list_repos'}

def host(tmp_path, **kw):
    h = WorkspaceHost(Workspace(roots=[tmp_path]), **kw)
    h.specs.update(stripe=object(), github=object())
    return h

@pytest.fixture
def kept(tmp_path, monkeypatch):
    "Credentials in a store that is not the machine's keychain, for the length of a test."
    from leela.blocks.vault import spec as S
    monkeypatch.setattr(S, 'CREDS', Creds(path=tmp_path/'apicreds.json', store=_Store()))
    return S.CREDS

def test_a_key_reaches_the_spec_it_belongs_to(tmp_path, monkeypatch, kept):
    "One host holds many specs; an unguarded `headers` would send stripe's key to github."
    monkeypatch.setattr('fastspec.oapi.OpenAPIClient',
                        lambda parsed, headers=None, **kw: FakeClient(headers or {}))
    h = host(tmp_path)
    h.api_creds('stripe', {'Authorization': 'Bearer sk_live_1'})
    assert h.api_call('get_balance', name='stripe') == {'ok': 'get_balance'}
    assert h._client('stripe', h.specs['stripe']).headers['Authorization'] == 'Bearer sk_live_1'
    assert 'Authorization' not in h._client('github', h.specs['github']).headers


# ── who may see what it answers ─────────────────────────────────────────────

def test_a_local_only_api_refuses_a_hosted_model_and_sends_nothing(tmp_path, monkeypatch, kept):
    monkeypatch.setattr('fastspec.oapi.OpenAPIClient',
                        lambda parsed, headers=None, **kw: FakeClient(headers or {}))
    h = host(tmp_path)
    h.api_creds('stripe', {}, reach='local')
    h.model_local = lambda: (False, 'claude-opus-5')
    with pytest.raises(SpecError) as e: h.api_call('get_balance', name='stripe')
    assert 'claude-opus-5' in str(e.value)
    assert h.api_fetch('get_balance', 'stripe') == {'ok': 'get_balance'}, 'the page is ungated'


# ── calling one from the page ───────────────────────────────────────────────


def _client(tmp_path):
    from starlette.testclient import TestClient
    from leela.app import ide_app
    ws = Workspace(roots=[tmp_path])
    return ws, TestClient(ide_app(ws))

def _load(c, ex):
    return c.get('/vault/view/specs', params={'src': ex.path, 'name': ex.name})

def test_the_page_and_the_agent_hold_the_same_spec(tmp_path):
    "A spec loaded on the page is the one `api_call` reaches; two copies would answer differently."
    from leela.blocks.vault.spec import EXAMPLES
    ws, client = _client(tmp_path)
    with client as c: html = _load(c, EXAMPLES[1]).text
    assert 'frankfurter' in sorted(ws.__dict__.get('_api_specs') or {})
    assert '/vault/apis/call' in html and 'latest' in html, 'and it offers the call'


# ── the same shelf, as tools ────────────────────────────────────────────────

@pytest.fixture
def newsy(tmp_path):
    "A workspace following one source, whose news shelf has two stories on it: the news tools follow the source, not the shelf."
    ws = follow(Workspace(roots=[tmp_path]))
    for title, source, feed, when, summary in (
            ('Rates hold', 'https://blog.test/1', 'A blog', '2026-08-14T09:00:00+00:00', 'The bank waited.'),
            ('A quiet day', 'https://journal.test/2', 'A journal', '2026-08-15T09:00:00+00:00', 'Rates were dull.')):
        ws.memory.file_news(f'# {title}\n\n{feed}\n\n{summary}\n', title=title, source=source,
                            meta=dict(feed=feed, published=when, summary=summary, author=''))
    return ws


def follow(ws, url='https://example.test/feed.xml', title='Example'):
    "One followed source on `ws`, filed without reading it: the tools follow the list, not the network."
    from leela.blocks.vault.news import Feed
    ws.feeds.rows.append(Feed(url=url, title=title)); ws.feeds.save()
    return ws


def test_the_news_tools_that_write_are_refused_when_nobody_approves_and_reading_is_not():
    from leela.blocks.agent.ai import Interventions, WRITE_TOOLS
    gate = Interventions(tools=WRITE_TOOLS, mode='ask')
    for tool in ('news_follow', 'news_unfollow', 'news_refresh'):
        assert gate.request(tool, {'url': 'https://example.test/feed.xml'}, timeout=.2).answer is False, tool
    assert gate.request('news_latest', {}, timeout=.2).answer is True


def test_a_story_opens_in_full_which_memory_read_cannot_do(newsy):
    "`memory_read` reads the main shelf; a feed item is on `news`."
    tools = {t.__name__: t for t in ide_tools(newsy)}
    import json
    doc = json.loads(tools['news_latest'](limit=1))[0]['doc_id']
    assert 'Rates were dull.' in tools['news_story'](doc)


def test_the_api_paragraph_says_what_api_access_used_to(tmp_path, kept):
    "The briefing carries it: header names, never a value; what is unkeyed; and not to load a spec twice."
    ws = Workspace(roots=[tmp_path]); h = WorkspaceHost(ws)
    assert api_context(h) == ''                                  # nothing loaded: nothing said
    ws.__dict__.setdefault('_api_specs', {})['stripe'] = object()
    ws.__dict__.setdefault('_api_spec_info', {})['stripe'] = {'title': 'Stripe', 'operations': 3, 'groups': ['charges']}
    kept.set('stripe', {'Authorization': 'Bearer sk_live_supersecret'})
    ctx = api_context(h)
    assert 'Authorization' in ctx and 'sk_live_supersecret' not in ctx
    assert 'api_access' not in {t.__name__ for t in ide_tools(ws)}
