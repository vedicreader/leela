"""Calling a described API with the caller's own key, and reaching the news shelf from a turn.

Nothing here reaches the network or the machine's keychain: `Creds` is given a store that keeps
what it is handed, and the assertions are about which headers reach which spec and what a tool
is allowed to say about them.
"""

from __future__ import annotations

import pytest
from fasthtml.common import to_xml

from leela.blocks.agent.ai import WorkspaceHost, ide_tools
from leela.blocks.vault import ui
from leela.blocks.vault.spec import Creds, cred_key, parse_headers, redact
from leela.workspace import Workspace


class _Store:
    "Enough of `EnvStore` to keep a value: leela's real one writes to the keychain."
    def __init__(self): self.kv = {}
    def get(self, key, secret=True): return self.kv.get(key, '')
    def set(self, key, value, secret=True): self.kv[key] = str(value); return {'key': key}
    def unset(self, key): return {'key': key, 'removed': bool(self.kv.pop(key, None))}


def creds(tmp_path): return Creds(path=tmp_path/'apicreds.json', store=_Store())


# ── headers ─────────────────────────────────────────────────────────────────

def test_headers_are_one_per_line_and_rubbish_is_dropped():
    assert parse_headers('Authorization: Bearer sk_live_1\nX-Api-Key: k2') == {
        'Authorization': 'Bearer sk_live_1', 'X-Api-Key': 'k2'}
    assert parse_headers('Authorization: Bearer a:b:c')['Authorization'] == 'Bearer a:b:c'
    assert parse_headers('no colon here') == {} and parse_headers('') == {}

def test_a_secret_is_shown_by_its_tail_only():
    assert redact('sk_live_abcdefgh') == '…efgh' and redact('xy') == '…'

def test_one_spec_is_one_key_whatever_its_name_looks_like():
    assert cred_key('Azure OpenAI') == cred_key('azure-openai') != cred_key('stripe')
    assert cred_key('stripe').startswith('LEELA_API_')


# ── where they are kept ─────────────────────────────────────────────────────

def test_credentials_outlive_the_session_that_set_them(tmp_path):
    store = _Store()
    Creds(path=tmp_path/'c.json', store=store).set('stripe', {'Authorization': 'Bearer sk_live_1'})
    again = Creds(path=tmp_path/'c.json', store=store)
    assert again.get('stripe') == {'Authorization': 'Bearer sk_live_1'}

def test_the_index_is_header_names_and_the_values_are_kept_elsewhere(tmp_path):
    "The file says which specs are keyed. A secret in it would be a secret in a config folder."
    p = tmp_path/'c.json'
    Creds(path=p, store=_Store()).set('stripe', {'Authorization': 'Bearer sk_live_supersecret'})
    assert 'Authorization' in p.read_text() and 'sk_live_supersecret' not in p.read_text()

def test_clearing_a_key_forgets_the_spec_entirely(tmp_path):
    c = creds(tmp_path)
    c.set('stripe', {'Authorization': 'Bearer x'})
    assert c.set('stripe', None) == [] and c.get('stripe') == {}

def test_an_empty_header_set_is_a_deletion_rather_than_an_empty_row(tmp_path):
    c = creds(tmp_path)
    c.set('gitlab', {'PRIVATE-TOKEN': 't'})
    c.set('gitlab', {})
    assert c.keyed() == {}

def test_what_is_reported_is_header_names_and_never_values(tmp_path):
    c = creds(tmp_path)
    c.set('stripe', {'Authorization': 'Bearer sk_live_1', 'X-Api-Key': 'k'})
    assert c.keyed() == {'stripe': ['Authorization', 'X-Api-Key']}

def test_credentials_need_a_spec_to_belong_to(tmp_path):
    with pytest.raises(ValueError): creds(tmp_path).set('  ', {'A': 'b'})


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

def test_a_key_set_on_the_page_reaches_a_host_that_is_already_running(tmp_path, monkeypatch, kept):
    "The workbench writes to the store; a client built before that captured the old headers."
    monkeypatch.setattr('fastspec.oapi.OpenAPIClient',
                        lambda parsed, headers=None, **kw: FakeClient(headers or {}))
    h = host(tmp_path)
    h.api_call('get_balance', name='stripe')          # a client built before there was a key
    kept.set('stripe', {'Authorization': 'Bearer sk_live_1'})
    assert h._client('stripe', h.specs['stripe']).headers['Authorization'] == 'Bearer sk_live_1'


# ── the page ────────────────────────────────────────────────────────────────

def test_the_panel_shows_the_header_names_and_none_of_the_secret():
    out = to_xml(ui.creds_panel({'stripe': ['Authorization']}))
    assert 'stripe' in out and 'Authorization' in out

def test_the_panel_says_what_no_credentials_means():
    assert '401' in to_xml(ui.creds_panel({}))

def test_the_specs_view_offers_somewhere_to_put_a_key(tmp_path):
    from leela.blocks.memory.memory import Memory
    m = Memory(shelf='main', path=tmp_path/'v.db', offline=True)
    assert '/vault/apis/creds' in to_xml(ui.specs_view(m, 'workspace', creds={}))


# ── the same shelf, as tools ────────────────────────────────────────────────

@pytest.fixture
def newsy(tmp_path):
    "A workspace whose news shelf has two stories on it."
    ws = Workspace(roots=[tmp_path])
    for title, source, feed, when, summary in (
            ('Rates hold', 'https://blog.test/1', 'A blog', '2026-08-14T09:00:00+00:00', 'The bank waited.'),
            ('A quiet day', 'https://journal.test/2', 'A journal', '2026-08-15T09:00:00+00:00', 'Rates were dull.')):
        ws.memory.file_news(f'# {title}\n\n{feed}\n\n{summary}\n', title=title, source=source,
                            meta=dict(feed=feed, published=when, summary=summary, author=''))
    return ws

def named(tools): return {t.__name__ for t in tools}

def test_the_feeds_are_reachable_from_a_turn(tmp_path):
    "Feed items are on the `news` shelf, and the memory tools read the main one."
    assert {'news_feeds', 'news_latest', 'news_story', 'news_follow', 'news_unfollow',
            'news_refresh', 'api_keys'} <= named(ide_tools(Workspace(roots=[tmp_path])))

def test_the_three_that_write_go_in_front_of_the_user():
    from leela.blocks.agent.ai import WRITE_TOOLS
    assert {'news_follow', 'news_unfollow', 'news_refresh'} <= set(WRITE_TOOLS)

def test_the_latest_is_newest_first_and_says_where_each_story_came_from(newsy):
    tools = {t.__name__: t for t in ide_tools(newsy)}
    out = tools['news_latest']()
    assert out.index('A quiet day') < out.index('Rates hold')
    assert 'A journal' in out and 'The bank waited.' in out

def test_the_latest_narrows_by_headline_and_by_source(newsy):
    tools = {t.__name__: t for t in ide_tools(newsy)}
    assert 'Rates hold' in tools['news_latest'](match='hold')
    assert 'A quiet day' not in tools['news_latest'](match='hold')
    assert 'Rates hold' not in tools['news_latest'](feed='A journal')

def test_a_story_opens_in_full_which_memory_read_cannot_do(newsy):
    "`memory_read` reads the main shelf; a feed item is on `news`."
    tools = {t.__name__: t for t in ide_tools(newsy)}
    import json
    doc = json.loads(tools['news_latest'](limit=1))[0]['doc_id']
    assert 'Rates were dull.' in tools['news_story'](doc)

def test_asking_for_a_story_that_is_not_there_says_so_rather_than_raising(newsy):
    tools = {t.__name__: t for t in ide_tools(newsy)}
    assert 'no such item' in tools['news_story']('nope').lower()

def test_what_is_followed_is_reported_without_reading_anything(tmp_path):
    tools = {t.__name__: t for t in ide_tools(Workspace(roots=[tmp_path]))}
    assert tools['news_feeds']() and 'not following' in tools['news_unfollow']('https://x.test')

def test_an_unkeyed_spec_is_something_to_explain_rather_than_retry(tmp_path):
    tools = {t.__name__: t for t in ide_tools(Workspace(roots=[tmp_path]))}
    assert 'api_load' in tools['api_keys']()

def test_api_keys_reports_the_header_name_and_not_the_value(tmp_path, kept):
    ws = Workspace(roots=[tmp_path])
    ws.__dict__.setdefault('_api_specs', {})['stripe'] = object()
    kept.set('stripe', {'Authorization': 'Bearer sk_live_supersecret'})
    out = {t.__name__: t for t in ide_tools(ws)}['api_keys']()
    assert 'Authorization' in out and 'sk_live_supersecret' not in out
