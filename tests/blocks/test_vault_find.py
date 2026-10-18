"One home: scoped find and ask, global search rows, types, fields, and the agent's vault policy."

from __future__ import annotations

import json

import pytest
from fastcore.all import AttrDict
from starlette.testclient import TestClient

from leela.app import ide_app
from tests.blocks.test_vault_review import PLAIN
from tests.blocks.test_vault_screens import EMAIL, INVOICE, _wait, mkpdf, rws  # noqa: F401
from tests.blocks.test_vault_block import CONTACT, HOSTED, LOCAL, _filed, _host, _vref, pws  # noqa: F401

class AskChat:
    "A chat for Find > Ask that keeps every prompt and streams `answer` in two pieces."
    def __init__(self, name, runtime, answer): self.model, self.runtime, self.answer, self.prompts, self.use = name, runtime, answer, [], None
    def __call__(self, prompt, stream=False, **kw):
        self.prompts.append(prompt)
        if not stream: return {'role': 'assistant', 'content': self.answer}
        h = len(self.answer) // 2
        return iter([self.answer[:h], self.answer[h:]])

@pytest.fixture
def fws(rws, monkeypatch):
    "The screens workspace, an Open PDF beside the Personal one, and ask chats on and off this machine."
    import leela.blocks.vault.app as va
    (rws.proj/'plain.pdf').write_bytes(mkpdf([INVOICE, '', PLAIN]))
    chats = {'hosted': AskChat('hosted', 'hosted', 'It is about the weather [1]. Mail jane.doe@example.com'),
             'local': AskChat('local', 'litert', 'It is about the weather [1].')}
    def spec(name):
        if name not in ('hosted', 'local'): raise va.VaultRefused(f'{name} is not available here', 'model_unavailable')
        return AttrDict(name=name, local=name == 'local', model_id=name, runtime=chats[name].runtime, ctx=8000)
    monkeypatch.setattr(va, 'chat_spec', spec)
    monkeypatch.setattr(va, 'ask_chat', lambda s: lambda *a, **kw: chats[s.name])
    rws.chats = chats
    return rws

def _doc(ws, c, name):
    j = _wait(ws, c.post('/vault/read', json=dict(src=str(ws.proj/name))).text)
    assert j.status == 'complete', j.error
    return j.result['doc_id'], j.result['shelf']

def _events(c, url, **kw):
    out, name = [], ''
    with c.stream('POST', url, json=kw) as r:
        assert r.status_code == 200, r.read()
        for line in r.iter_lines():
            if line.startswith('event: '): name = line[7:].strip()
            elif line.startswith('data: '): out.append((name, json.loads(line[6:])))
    return out

# ── find ────────────────────────────────────────────────────────────────────

def test_find_keeps_to_its_scope(fws):
    with TestClient(ide_app(fws)) as c:
        plain, shelf = _doc(fws, c, 'plain.pdf')
        scan, _ = _doc(fws, c, 'scan.pdf')
        m = fws.vaults.memory(None)
        assert {h['doc_id'] for h in m.find('invoice', 20)} == {plain, scan}, 'the whole vault holds both'
        assert {h['doc_id'] for h in m.find('invoice', 20, plain, shelf)} == {plain}
        assert {h['page'] for h in m.find('weather garden', 20, plain, shelf, [2])} == {2}
        html = c.get('/vault/view/find', params=dict(q='weather', doc=plain, shelf=shelf, title='plain', scope='pages', pages='3')).text
        assert 'p. 3' in html and 'this document: plain' in html and 'data-find-ask' in html
        bad = c.get('/vault/view/find', params=dict(q='x', doc='nope', title='t', scope='doc')).text
        assert 'data-kind="not_found"' in bad, 'a title it merely contains is not the document'

# ── ask ─────────────────────────────────────────────────────────────────────

def test_ask_streams_and_cites_the_page_it_drew_on(fws):
    with TestClient(ide_app(fws)) as c:
        plain, shelf = _doc(fws, c, 'plain.pdf')
        ev = _events(c, '/vault/ask', q='weather garden', doc=plain, shelf=shelf, model='local')
        names = [n for n, _ in ev]
        assert names[0] == 'send' and names[-1] == 'done' and 'reset' in names and names.count('chunk') == 2
        ans = dict(ev)['answer']
        assert ans['answer'].startswith('It is about the weather') and ans['cited'][0]['doc'] == plain
        assert ans['cited'][0]['page'] == 2 and 'weather' in ans['cited'][0]['quote'], 'the citation lands on the page that matched'
        pg = dict(_events(c, '/vault/ask', q='weather garden', doc=plain, shelf=shelf, pages='1', model='local'))['answer']
        assert all(x['page'] == 0 for x in pg['cited']), 'a page scope keeps its citations in range'

def test_ask_masks_a_personal_document_and_withholds_a_local_only_one_from_a_hosted_model(fws):
    with TestClient(ide_app(fws)) as c:
        scan, shelf = _doc(fws, c, 'scan.pdf')
        hosted = fws.chats['hosted']
        ev = _events(c, '/vault/ask', q='lease deposit', doc=scan, shelf=shelf, model='hosted')
        assert 'jane.doe@example.com' not in hosted.prompts[-1], 'a hosted model gets a Personal page masked'
        assert all('jane.doe' not in d['text'] for n, d in ev if n == 'chunk'), 'what streams is masked too'
        assert 'jane.doe' not in dict(ev)['answer']['answer']
        assert 'masked' in dict(ev)['send']['why']
        c.post('/vault/privacy', json=dict(doc=scan, shelf=shelf, level='local'))
        chk = c.post('/vault/send-check', json=dict(ask=True, doc=scan, shelf=shelf, model='hosted')).json()
        assert chk['ok'] and not chk['check_ok'] and chk['kind'] == 'local_only' and 'withheld' in chk['why']
        ev = _events(c, '/vault/ask', q='lease deposit', doc=scan, shelf=shelf, model='hosted')
        assert 'Write to' not in hosted.prompts[-1] and 'withheld' in hosted.prompts[-1]
        assert not dict(ev)['send']['check_ok']
        assert c.post('/vault/send-check', json=dict(ask=True, doc=scan, shelf=shelf, model='local')).json()['check_ok']

@pytest.mark.parametrize('args,kind', [(dict(q=''), 'bad_request'), (dict(q='x', pages='2'), 'bad_request'),
                                       (dict(q='x', doc='nope'), 'not_found'), (dict(q='x', model='nonesuch'), 'model_unavailable')])
def test_ask_refuses_before_streaming_with_a_kind(fws, args, kind):
    with TestClient(ide_app(fws)) as c:
        r = c.post('/vault/ask', json=dict(model='local') | args)
        assert r.json()['ok'] is False and r.json()['kind'] == kind

# ── global search ───────────────────────────────────────────────────────────

def test_global_search_carries_at_most_five_vault_rows_and_skips_them_for_a_pattern(fws):
    with TestClient(ide_app(fws)) as c:
        plain, _ = _doc(fws, c, 'plain.pdf')
        def stream(**kw):
            out, name = [], ''
            with c.stream('GET', '/search/stream', params=dict(q='weather garden', **kw)) as r:
                for line in r.iter_lines():
                    if line.startswith('event: '): name = line[7:].strip()
                    elif line.startswith('data: '): out.append((name, json.loads(line[6:])))
            return out
        ev = stream()
        assert [n for n, _ in ev][-2:] == ['vault', 'done']
        rows = dict(ev)['vault']['hits']
        assert rows and len(rows) <= 5 and rows[0]['doc'] == plain and rows[0]['page'] == 2
        assert 'vault' not in [n for n, _ in stream(regex='true')], 'a literal pattern is a code question'

# ── types ───────────────────────────────────────────────────────────────────

def test_proposed_types_are_accepted_rejected_picked_and_undone(fws):
    with TestClient(ide_app(fws)) as c:
        plain, shelf = _doc(fws, c, 'plain.pdf')
        m = fws.vaults.memory(None)
        assert m.document(plain, shelf)['meta'].get('doctype') == 'invoice', 'a read is typed from its words, no model asked'
        assert 'lee-vault-type' in c.get('/vault/view/library').text and '>invoice<' in c.get('/vault/view/library').text
        m.set_meta(plain, shelf, doctype=None, doctype_proposed='receipt', doctype_score=.3)
        t = c.get('/vault/types').json()
        assert [r['proposed'] for r in t['types']] == ['receipt'] and 'passport' in t['labels']
        a = c.post('/vault/types/accept', json=dict(doc=plain, shelf=shelf)).json()
        assert a['doctype'] == 'receipt' and a['was']['doctype_proposed'] == 'receipt'
        assert c.get('/vault/types').json()['types'] == []
        assert c.post('/vault/types/accept', json=dict(doc=plain, shelf=shelf)).json()['kind'] == 'stale'
        c.post('/vault/types/undo', json=dict(doc=plain, shelf=shelf, was=json.dumps(a['was'])))
        assert m.document(plain, shelf)['meta']['doctype_proposed'] == 'receipt' and not m.document(plain, shelf)['meta'].get('doctype')
        assert c.post('/vault/types/accept', json=dict(doc=plain, shelf=shelf, doctype='bogus')).json()['kind'] == 'bad_request'
        assert c.post('/vault/types/accept', json=dict(doc=plain, shelf=shelf, doctype='quote')).json()['doctype'] == 'quote'
        m.set_meta(plain, shelf, doctype_proposed='receipt')
        c.post('/vault/types/reject', json=dict(doc=plain, shelf=shelf))
        assert m.document(plain, shelf)['meta'].get('doctype') == 'quote' and c.get('/vault/types').json()['types'] == []

# ── fields ──────────────────────────────────────────────────────────────────

class FieldChat:
    "What `extract` builds: a chat whose structured reply quotes the document."
    def __init__(self, model=None, **kw): self.model, self.runtime, self.use = model, kw.get('runtime') or 'hosted', None
    def structured(self, prompt, schema, sp=''):
        FieldChat.prompts.append(prompt)
        return {'number': '42', 'number_quote': 'Invoice number 42', 'date': '32/13/2024', 'date_quote': '32/13/2024',
                'total': '100.00', 'total_quote': 'Total due 100.00'}
FieldChat.prompts = []

def test_fields_carry_page_quote_and_warnings_and_a_local_only_document_is_not_sent(fws, monkeypatch):
    import vishalakshi.ask as vk
    monkeypatch.setattr(vk, 'CHAT', FieldChat)
    with TestClient(ide_app(fws)) as c:
        plain, shelf = _doc(fws, c, 'plain.pdf')
        assert c.get('/vault/fields', params=dict(doc=plain, shelf=shelf)).json() | {} == \
            dict(ok=True, extracted=False, schema=None, doctype='invoice', fields=[])
        j = _wait(fws, c.post('/vault/extract', json=dict(doc=plain, shelf=shelf, model='local')).text)
        assert j.status == 'complete', j.error
        d = c.get('/vault/fields', params=dict(doc=plain, shelf=shelf)).json()
        f = {x['field']: x for x in d['fields']}
        assert d['extracted'] and d['schema'] == 'Invoice' and f['number']['page'] == 0 and f['number']['quote'] == 'Invoice number 42'
        assert f['total']['value'] == 100.0 and f['date']['errors'] and 'calendar date' in f['date']['errors'][0]
        c.post('/vault/privacy', json=dict(doc=plain, shelf=shelf, level='local'))
        FieldChat.prompts.clear()
        r = c.post('/vault/extract', json=dict(doc=plain, shelf=shelf, model='hosted'))
        assert r.status_code == 400 and r.json()['kind'] == 'local_only' and FieldChat.prompts == []
        assert c.post('/vault/send-check', json=dict(refs=plain, shelf=shelf, model='hosted')).json()['check_ok'] is False
        assert c.get('/vault/fields', params=dict(doc='nope')).json()['kind'] == 'not_found'

# ── the agent ───────────────────────────────────────────────────────────────

def test_a_stored_off_still_withholds_a_local_only_document_from_a_hosted_model(pws):
    pws.vault_pii = 'off'
    _, shelf, doc = _filed(pws, 'contact.md', CONTACT, level='local')
    hosted, local = _host(pws), _host(pws, local=True)
    got = json.dumps(hosted.memory_search('lease contact'), default=str)
    assert 'jane.doe' not in got and 'Write to' not in got and 'withheld: local only' in got
    assert 'Write to' in json.dumps(local.memory_search('lease contact'), default=str), 'a model on this machine reads it whole'
    assert 'Write to' not in json.dumps(hosted.memory_read(f'{doc}#1'), default=str)
    rows = hosted.memory_documents()
    assert [r['level'] for r in rows] == ['local'] and 'Write to' not in json.dumps(rows)
    assert all(r.get('level') == 'local' for r in hosted.memory_sections(doc))

def test_a_web_query_holding_an_email_is_refused_and_names_the_kind(pws):
    from leela.blocks.memory.memory import PrivacyBlocked, query_refusal
    with pytest.raises(PrivacyBlocked, match='email'): _host(pws).web_search('who is jane.doe@example.com')
    with pytest.raises(PrivacyBlocked): _host(pws).research('call +44 20 7946 0958 about it')
    assert query_refusal('fastcore patch decorator') is None

def test_the_prompt_bar_check_and_the_turn_name_the_same_withheld_chip(pws):
    _, shelf, doc = _filed(pws, 'contact.md', CONTACT, level='local')
    ref = _vref(shelf, doc)
    chk = pws.attachment_check([ref, str(pws.fs.roots[0]/'contact.md')], HOSTED)
    assert not chk.ok and chk.kind == 'local_only' and chk.attachments == [ref]
    ok = pws.attachment_check([ref], LOCAL)
    assert ok.ok and 'on this machine' in ok.why
    (pws.fs.roots[0]/'notes.md').write_text('plain notes\n')
    assert 'none filed in the vault' in pws.attachment_check([str(pws.fs.roots[0]/'notes.md')], HOSTED).why

def test_a_turn_refusal_carries_the_chip_it_came_from(pws):
    from ramabana.core import ModelSpec
    from tests.fakemodel import Step, install
    _, shelf, doc = _filed(pws, 'contact.md', CONTACT, level='local')
    install(pws, [Step(text='I read it')], token_delay=0, spec=ModelSpec('hosted-scripted', 'remote', 'scripted/model', ctx=8000))
    with TestClient(ide_app(pws)) as c:
        r = c.post('/agent/turn', json={'prompt': 'summarise', 'attachments': [_vref(shelf, doc)]})
        assert r.status_code == 400 and r.json()['kind'] == 'local_only' and r.json()['attachments'] == [_vref(shelf, doc)]
        chk = c.post('/vault/send-check', json=dict(attach=json.dumps([_vref(shelf, doc)]))).json()
        assert chk['ok'] and not chk['check_ok'] and chk['attachments'] == [_vref(shelf, doc)] and chk['why'] == r.json()['line']

# ── keys and routes ─────────────────────────────────────────────────────────

def test_slash_and_a_find_and_ask_from_the_document_view():
    from leela.core.keys import DEFAULTS, _dupes, lookup
    assert (lookup('vault_find_doc').key, lookup('vault_ask_page').key) == ('/', 'a')
    assert lookup('vault_find_doc').scope == lookup('vault_ask_page').scope == 'vault'
    assert _dupes(DEFAULTS) == []

ROUTES = [('get', '/vault/types', dict(state='bogus')), ('post', '/vault/types/accept', dict(doc='nope')),
          ('post', '/vault/types/undo', dict(doc='nope', was='x')), ('post', '/vault/types/guess', dict()),
          ('get', '/vault/fields', dict(doc='nope')), ('post', '/vault/extract', dict(doc='nope', model='local')),
          ('post', '/vault/ask', dict(q='')), ('post', '/vault/send-check', dict(ask=True, doc='nope', model='local')),
          ('post', '/vault/send-check', dict(attach='{'))]

@pytest.mark.parametrize('how,route,args', ROUTES)
def test_every_new_route_answers_ok_or_a_kind(fws, how, route, args):
    with TestClient(ide_app(fws)) as c:
        r = c.get(route, params=args) if how == 'get' else c.post(route, json=args)
        body = r.json()
        assert body.get('ok') is True or (body.get('ok') is False and body.get('kind') and body.get('error')), body
