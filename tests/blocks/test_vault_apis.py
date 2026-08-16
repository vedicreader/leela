"""Calling a described API with the caller's own key, and reaching the news shelf from a turn.

Nothing here reaches the network or the machine's keychain: `Creds` is given a store that keeps
what it is handed, and the assertions are about which headers reach which spec and what a tool
is allowed to say about them.
"""

from __future__ import annotations

import pytest
from fasthtml.common import to_xml

from leela.blocks.agent.ai import WorkspaceHost, api_context, ide_tools
from leela.blocks.vault import ui
from leela.blocks.vault.spec import (Creds, SpecError, cred_key, env_status, env_vars, expand,
                                     parse_headers, redact)
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

def test_a_variable_reference_names_something_rather_than_carrying_it_so_it_stays_whole():
    assert redact('Bearer ${COSTING_TOKEN}') == 'Bearer ${COSTING_TOKEN}'


# ── the environment behind a header ─────────────────────────────────────────

def test_only_a_braced_name_is_a_reference():
    "A bare `$NAME` would claim any dollar inside a literal secret."
    assert env_vars({'A': 'Bearer ${T}', 'B': '$PLAIN'}) == ['T']

def test_what_is_missing_here_is_reported_rather_than_sent():
    headers = {'Authorization': 'Bearer ${COSTING_TOKEN}'}
    assert env_status(headers, {}) == {'COSTING_TOKEN': False}
    assert expand(headers, {'COSTING_TOKEN': 'k1'}) == {'Authorization': 'Bearer k1'}
    with pytest.raises(SpecError) as e: expand(headers, {})
    assert 'COSTING_TOKEN' in str(e.value) and 'nothing was sent' in str(e.value)

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

def test_the_index_records_which_variables_back_a_header_and_not_what_they_hold(tmp_path):
    p = tmp_path/'c.json'
    Creds(path=p, store=_Store()).set('costing', {'Authorization': 'Bearer ${COSTING_TOKEN}'})
    assert Creds(path=p, store=_Store()).policies()['costing']['refs'] == ['COSTING_TOKEN']

def test_an_index_written_before_there_was_a_policy_still_reads(tmp_path):
    p = tmp_path/'c.json'
    p.write_text('{"stripe": ["Authorization"]}')
    assert Creds(path=p, store=_Store()).policies()['stripe'] == dict(
        headers=['Authorization'], refs=[], reach='cloud')

def test_reach_outlives_the_key_because_a_keyless_api_is_worth_marking(tmp_path):
    c = creds(tmp_path)
    c.set('azure-prices', {}, reach='local')
    assert c.keyed() == {} and c.reach('azure-prices') == 'local'

def test_setting_a_key_leaves_the_reach_alone(tmp_path):
    c = creds(tmp_path)
    c.set('costing', {}, reach='local')
    c.set('costing', {'X-Api-Key': 'k'})
    assert c.reach('costing') == 'local'


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

def test_a_header_may_name_a_variable_and_the_call_carries_what_it_holds(tmp_path, monkeypatch, kept):
    monkeypatch.setattr('fastspec.oapi.OpenAPIClient',
                        lambda parsed, headers=None, **kw: FakeClient(headers or {}))
    monkeypatch.setenv('LEELA_TEST_TOKEN', 'k1')
    h = host(tmp_path)
    h.api_creds('stripe', {'Authorization': 'Bearer ${LEELA_TEST_TOKEN}'})
    assert h._client('stripe', h.specs['stripe']).headers['Authorization'] == 'Bearer k1'

def test_a_variable_nothing_sets_refuses_the_call_rather_than_sending_the_reference(tmp_path, monkeypatch, kept):
    monkeypatch.setattr('fastspec.oapi.OpenAPIClient',
                        lambda parsed, headers=None, **kw: FakeClient(headers or {}))
    monkeypatch.delenv('LEELA_TEST_TOKEN', raising=False)
    h = host(tmp_path)
    h.api_creds('stripe', {'Authorization': 'Bearer ${LEELA_TEST_TOKEN}'})
    with pytest.raises(SpecError) as e: h.api_call('get_balance', name='stripe')
    assert 'LEELA_TEST_TOKEN' in str(e.value)


# ── who may see what it answers ─────────────────────────────────────────────

def test_a_local_only_api_refuses_a_hosted_model_and_sends_nothing(tmp_path, monkeypatch, kept):
    monkeypatch.setattr('fastspec.oapi.OpenAPIClient',
                        lambda parsed, headers=None, **kw: FakeClient(headers or {}))
    h = host(tmp_path)
    h.api_creds('stripe', {}, reach='local')
    h.model_local = lambda: (False, 'claude-opus-5')
    with pytest.raises(SpecError) as e: h.api_call('get_balance', name='stripe')
    assert 'local-only' in str(e.value) and 'claude-opus-5' in str(e.value)
    assert h.api_fetch('get_balance', 'stripe') == {'ok': 'get_balance'}, 'the page is ungated'

def test_a_local_model_may_call_it_and_a_cloud_reach_gates_nobody(tmp_path, monkeypatch, kept):
    monkeypatch.setattr('fastspec.oapi.OpenAPIClient',
                        lambda parsed, headers=None, **kw: FakeClient(headers or {}))
    h = host(tmp_path)
    h.api_creds('stripe', {}, reach='local')
    h.model_local = lambda: (True, 'qwen3-4b')
    assert h.api_call('get_balance', name='stripe') == {'ok': 'get_balance'}
    h.api_creds('stripe', {}, reach='cloud')
    h.model_local = lambda: (False, 'claude-opus-5')
    assert h.api_call('get_balance', name='stripe') == {'ok': 'get_balance'}


# ── what the briefing says ──────────────────────────────────────────────────

def test_a_loaded_spec_is_named_in_the_briefing_rather_than_looked_up(tmp_path, kept):
    h = host(tmp_path)
    h.spec_info = {'stripe': dict(title='Stripe', operations=2, groups=['balance'])}
    kept.set('stripe', {'Authorization': 'Bearer k'}, reach='local')
    out = api_context(h)
    assert 'stripe' in out and 'Stripe — 2 operations' in out and 'balance' in out
    assert 'Authorization' in out and 'local-only' in out and 'Bearer k' not in out

def test_no_spec_loaded_costs_the_briefing_nothing():
    assert api_context(WorkspaceHost(Workspace(roots=[]))) == ''


# ── the page ────────────────────────────────────────────────────────────────

def test_the_panel_shows_the_header_names_and_none_of_the_secret():
    out = to_xml(ui.creds_panel({'stripe': dict(headers=['Authorization'], refs=[], reach='cloud')}))
    assert 'stripe' in out and 'Authorization' in out

def test_the_panel_says_which_variable_is_missing_and_which_api_is_local_only():
    out = to_xml(ui.creds_panel({'costing': dict(headers=['Authorization'],
                                                 refs=['LEELA_NOT_SET_ANYWHERE'], reach='local')}))
    assert 'LEELA_NOT_SET_ANYWHERE' in out and 'not set' in out and 'local only' in out

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
            'news_refresh', 'api_access'} <= named(ide_tools(Workspace(roots=[tmp_path])))

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
    out = tools['api_access']()
    assert 'api_load' in out and 'azure-retail-prices.json' in out, 'and a keyless one to try'

def test_api_access_reports_the_header_name_and_not_the_value(tmp_path, kept):
    ws = Workspace(roots=[tmp_path])
    ws.__dict__.setdefault('_api_specs', {})['stripe'] = object()
    kept.set('stripe', {'Authorization': 'Bearer sk_live_supersecret'})
    out = {t.__name__: t for t in ide_tools(ws)}['api_access']()
    assert 'Authorization' in out and 'sk_live_supersecret' not in out
