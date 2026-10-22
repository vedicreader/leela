"Books of verses through lekhaka, the vault's privacy floor and the send log."

from __future__ import annotations

import json, threading

import pytest
from starlette.testclient import TestClient

from leela.app import ide_app
from tests.blocks.test_vault_screens import INVOICE, Reader, _wait, mkpdf, rws  # noqa: F401

H, V1, V2a, V2, V4 = 'अथ प्रथमोऽध्यायः', 'धर्मक्षेत्रे कुरुक्षेत्रे ।\nसमवेता युयुत्सवः ॥१॥', 'मामकाः पाण्डवाश्चैव ।', 'किमकुर्वत सञ्जय ॥२॥', 'ध्ार्म ॥४॥'
PAGES = [[dict(kind='heading', text=H), dict(kind='verse', n='१', text=V1), dict(kind='verse', n=None, text=V2a)],
         [dict(kind='verse', n='॥२॥', text=V2), dict(kind='verse', n='४', text=V4), dict(kind='colophon', text='इति प्रथमोऽध्यायः')]]

class Verses(Reader):
    "A vision reader that knows each page by its image and answers that page's verse blocks, as lekhaka's own tests do; `gate` holds the second page."
    def __init__(self, model, runtime, src, gate=None):
        from vishalakshi.read import render
        super().__init__(model, runtime)
        self.by, self.gate = {render(src, i, 200): items for i, items in enumerate(PAGES)}, gate
    def __call__(self, msgs):
        self.sent.append(msgs[0])
        items = self.by[msgs[0]]
        if self.gate and items is PAGES[1]: self.gate.wait(10)
        return json.dumps({'items': items}, ensure_ascii=False)

@pytest.fixture
def bws(rws):
    "A two-page book (an Open text layer the model reads past) and a hosted and a local verse reader."
    src = rws.proj/'gita.pdf'
    src.write_bytes(mkpdf(['Bhagavad Gita chapter one', 'Bhagavad Gita chapter one continued']))
    rws.readers |= {'vh': Verses('vh', 'hosted', src), 'vl': Verses('vl', 'litert', src)}
    rws.book = src
    return rws

def _book(ws, c, **kw):
    r = c.post('/vault/book', json=dict(src=str(ws.book), model='vh', counts='5', **kw))
    assert r.status_code == 200, r.text
    j = _wait(ws, r.text)
    assert j.status == 'complete', j.error
    return j

def test_a_book_job_reads_every_page_by_model_and_its_chapters_come_from_the_pages(bws):
    with TestClient(ide_app(bws)) as c:
        j = _book(bws, c)
        doc, shelf = j.result['doc_id'], j.result['shelf']
        assert (j.result['chapters'], j.result['verses']) == (1, 3) and j.result['problems'] == 3
        assert len(bws.readers['vh'].sent) == 2, 'parse llm: every page went to the model'
        b = c.get('/vault/book', params=dict(doc=doc, shelf=shelf)).json()
        ch = b['chapters'][0]
        assert b['ok'] and (ch['heading'], ch['colophon']) == (H, 'इति प्रथमोऽध्यायः')
        assert [v['n'] for v in ch['verses']] == [1, 2, 4] and ch['verses'][1]['text'].startswith('मामकाः')
        assert [(v['page'], v['block']) for v in ch['verses']] == [(0, 1), (1, 0), (1, 1)], 'each verse knows the block it was read from'
        assert ch['verses'][2]['text'] == 'धार्म ॥४॥', 'the akṣara is mended'
        probs = {p['text']: p for p in b['probs']}
        assert probs['verse 4 after 2']['page'] == 1, 'the page is split off the text, 0-based'
        meta = c.get('/vault/doc', params=dict(doc=doc, shelf=shelf)).json()['doc']['meta']['book']
        assert 'chapters' not in meta, 'the chapters are not stored: they are assembled when asked'
        assert meta['counts'] == [5] and meta['script'] == 'Devanagari'

def test_counts_that_differ_are_a_problem_and_bad_counts_are_refused(bws):
    with TestClient(ide_app(bws)) as c:
        j = _wait(bws, c.post('/vault/book', json=dict(src=str(bws.book), model='vh', counts='5')).text)
        b = c.get('/vault/book', params=dict(doc=j.result['doc_id'], shelf=j.result['shelf'])).json()
        assert any(p['text'] == 'chapter 1: 3 verses, the plan has 5' and p['page'] is None for p in b['probs'])
        for bad in ('3,x', '0', '-2'):
            assert c.post('/vault/book', json=dict(src=str(bws.book), model='vh', counts=bad)).json()['kind'] == 'bad_request'

def test_a_book_answers_the_kind_its_screen_offers(bws):
    with TestClient(ide_app(bws)) as c:
        src = str(bws.book)
        assert c.post('/vault/book', json=dict(src=src)).json()['kind'] == 'model_unavailable'
        assert c.post('/vault/book', json=dict(src=src, model='nope')).json()['kind'] == 'model_unavailable'
        assert c.post('/vault/book', json=dict(src=src, model='vh', preset='tables')).json()['kind'] == 'bad_request'
        assert c.post('/vault/book', json=dict(model='vh')).json()['kind'] == 'bad_request'
        r = c.get('/vault/book', params=dict(doc='nope'))
        assert r.status_code == 404 and r.json()['kind'] == 'not_found'
        doc = _wait(bws, c.post('/vault/read', json=dict(src=str(bws.proj/'scan.pdf'))).text).result['doc_id']
        assert c.get('/vault/book', params=dict(doc=doc)).json()['kind'] == 'not_found', 'read, but not as a book'

def test_a_personal_page_is_not_sent_for_a_book_without_saying_so(bws):
    with TestClient(ide_app(bws)) as c:
        r = c.post('/vault/book', json=dict(src=str(bws.proj/'scan.pdf'), model='vh'))
        assert r.status_code == 400 and r.json()['kind'] == 'pii_blocked' and r.json()['pages'] == [2]
        assert bws.readers['vh'].sent == []

def test_the_book_of_a_filed_document_reads_it_again_and_keeps_its_history(bws):
    with TestClient(ide_app(bws)) as c:
        doc = _wait(bws, c.post('/vault/read', json=dict(src=str(bws.book))).text).result['doc_id']
        j = _book(bws, c)
        assert j.result['doc_id'] == doc and j.params.get('again'), 'the same document, read again'
        p = c.get('/vault/page', params=dict(doc=doc, page=0)).json()
        assert p['versions'] == [1, 2] and p['route'] == 'model'
        j = _wait(bws, c.post('/vault/book', json=dict(doc=doc, model='vl', preset='tamil')).text)
        assert j.status == 'complete' and c.get('/vault/doc', params=dict(doc=doc)).json()['doc']['meta']['book']['script'] == 'Tamil'
        b = c.get('/vault/book', params=dict(doc=doc)).json()
        assert not any('mended' in p['text'] for p in b['probs']), 'Tamil is not mended as Devanagari'

def test_a_problem_is_checked_dismissed_and_opened_again_and_its_state_outlives_a_re_read(bws):
    with TestClient(ide_app(bws)) as c:
        j = _book(bws, c)
        doc, shelf = j.result['doc_id'], j.result['shelf']
        probs = c.get('/vault/book/problems', params=dict(doc=doc, shelf=shelf)).json()['problems']
        assert len(probs) == 3 and all(p['state'] == 'open' and p['doc'] == doc for p in probs)
        a, b = probs[0]['id'], probs[1]['id']
        assert c.post('/vault/book/probs/accept', json=dict(doc=doc, shelf=shelf, ids=a)).json()['probs'][0]['state'] == 'checked'
        assert c.post('/vault/book/probs/reject', json=dict(doc=doc, shelf=shelf, ids=b)).json()['probs'][0]['state'] == 'dismissed'
        assert [p['id'] for p in c.get('/vault/book/problems').json()['problems']] == [probs[2]['id']], 'across every book, open only'
        c.post('/vault/book/probs/undo', json=dict(doc=doc, shelf=shelf, ids=a))
        assert len(c.get('/vault/book/problems', params=dict(doc=doc, shelf=shelf)).json()['problems']) == 2
        _book(bws, c)
        st = {p['id']: p['state'] for p in c.get('/vault/book/problems', params=dict(doc=doc, shelf=shelf, state='')).json()['problems']}
        assert st[b] == 'dismissed', 'the same problem read again keeps its verdict'
        r = c.post('/vault/book/probs/accept', json=dict(doc=doc, shelf=shelf, ids='gone'))
        assert r.status_code == 409 and r.json()['kind'] == 'stale' and r.json()['ids'] == ['gone']

def test_the_book_exports_as_markdown(bws):
    with TestClient(ide_app(bws)) as c:
        j = _book(bws, c)
        q = dict(doc=j.result['doc_id'], shelf=j.result['shelf'])
        md = c.get('/vault/book.md', params=q)
        assert md.status_code == 200 and H in md.text
        r = c.post('/vault/book.md', json=q).json()
        assert r['ok'] and (bws.proj/'gita.BOOK.md').read_text() == md.text

def test_a_cancelled_book_keeps_the_pages_read_and_resumes_on_the_rest(bws):
    gate = threading.Event()
    bws.readers['vh'].gate = gate
    with TestClient(ide_app(bws)) as c:
        html = c.post('/vault/book', json=dict(src=str(bws.book), model='vh')).text
        jid = html.split('id="job-', 1)[1].split('"', 1)[0]
        import time
        for _ in range(200):
            if len(bws.readers['vh'].sent) >= 2: break
            time.sleep(.02)
        r = c.post('/vault/read', json=dict(src=str(bws.book), model='vh'))
        assert r.status_code == 409 and r.json()['kind'] == 'busy', 'a read of the same file waits for the book'
        c.post(f'/jobs/{jid}/cancel'); gate.set()
        j = _wait(bws, html)
        assert j.status in ('cancelled', 'complete') and j.result['chapters'] >= 1
        if j.status == 'cancelled':
            assert c.post(f'/jobs/{jid}/retry').status_code == 200
            j = _wait(bws, html)
            assert j.params['resume'] == j.result['doc_id']
        assert c.get('/vault/book', params=dict(doc=j.result['doc_id'], shelf=j.result['shelf'])).json()['verses'] == 3

def test_a_decision_waits_while_a_book_runs_on_the_document(bws):
    gate = threading.Event()
    with TestClient(ide_app(bws)) as c:
        doc = _wait(bws, c.post('/vault/read', json=dict(src=str(bws.book))).text).result['doc_id']
        bws.readers['vh'].gate = gate
        html = c.post('/vault/book', json=dict(doc=doc, model='vh')).text
        r = c.post('/vault/page/revert', json=dict(doc=doc, page=0, version=1))
        gate.set()
        assert r.status_code == 409 and r.json()['kind'] == 'busy'
        _wait(bws, html)

def test_a_book_choice_is_remembered_only_for_a_verse_preset():
    from leela.blocks.vault.app import read_choice
    assert read_choice(dict(preset='sanskrit', book=True))['book'] is True
    assert 'book' not in read_choice(dict(preset='generic', book=True))

def test_the_estimate_says_whether_the_type_is_settled(bws):
    "The Read sheet lets a settled or sensitive type pick the preset; an unsure guess leaves the folder's choice."
    with TestClient(ide_app(bws)) as c:
        t = c.post('/vault/read', json=dict(src=str(bws.proj/'scan.pdf'), estimate=True)).json()['type']
        assert (t['doctype'], t['preset'], t['decisive']) == ('invoice', 'tables', True)
        t = c.post('/vault/read', json=dict(src=str(bws.book), estimate=True)).json()['type']
        assert not t['decisive'] and t['preset'] == 'generic'

# ── the send log and the vault's floor ──────────────────────────────────────

def test_the_send_log_lists_what_went_to_a_hosted_model_and_nothing_local(bws):
    with TestClient(ide_app(bws)) as c:
        assert c.get('/vault/sends').json() == {'ok': True, 'sends': []}
        j = _book(bws, c)
        doc = j.result['doc_id']
        s = c.get('/vault/sends').json()['sends']
        assert len(s) == 1 and s[0]['doc_id'] == doc and s[0]['pages'] == [0, 1] and s[0]['model'] == 'vh' and s[0]['title'] == 'gita'
        assert c.get('/vault/sends', params=dict(doc=doc, shelf=j.result['shelf'])).json()['sends'][0]['doc_id'] == doc
        _wait(bws, c.post('/vault/book', json=dict(doc=doc, model='vl')).text)
        assert len(c.get('/vault/sends').json()['sends']) == 1, 'a read on this machine sent nothing'
        assert c.get('/vault/sends', params=dict(doc='nope')).json()['kind'] == 'not_found'

def test_the_floor_raises_every_document_and_only_a_person_lowers_it(bws):
    with TestClient(ide_app(bws)) as c:
        doc = _wait(bws, c.post('/vault/read', json=dict(src=str(bws.book))).text).result['doc_id']
        assert c.post('/vault/access', json=dict(name='workspace')).json()['floor'] == 'open'
        r = c.post('/vault/access', json=dict(name='workspace', privacy='personal')).json()
        assert r['ok'] and r['floor'] == 'personal'
        assert c.get('/vault/privacy', params=dict(doc=doc)).json()['level'] == 'personal'
        e = c.post('/vault/read', json=dict(src=str(bws.proj/'scan.pdf'), estimate=True)).json()
        assert e['current'] == 'personal', 'a new read starts at the floor'
        assert c.post('/vault/access', json=dict(name='workspace', privacy='open')).json()['floor'] == 'open', 'the route is a person'
        assert c.post('/vault/access', json=dict(name='workspace', privacy='secret')).json()['kind'] == 'bad_request'
        assert c.post('/vault/access', json=dict(name='nope')).json()['kind'] == 'not_found'

def test_a_read_only_vault_keeps_its_floor(bws, tmp_path):
    from leela.blocks.memory.memory import Memory
    peer = tmp_path/'peer'/'vault.db'
    Memory(shelf='main', path=peer, offline=True)._open()
    bws.vaults.file = tmp_path/'vaults.json'
    bws.vaults.attach(str(peer), name='peer')
    with TestClient(ide_app(bws)) as c:
        r = c.post('/vault/access', json=dict(name='peer', privacy='local'))
        assert r.status_code == 403 and r.json()['kind'] == 'read_only'
        for route in ('/vault/book', '/vault/book/probs/accept', '/vault/book.md'):
            r = c.post(route, json=dict(src=str(bws.book), doc='x', ids='y', model='vh', vault='peer'))
            assert r.json()['kind'] in ('read_only', 'not_found'), (route, r.json())

ROUTES = [('get', '/vault/book', dict(doc='nope')), ('post', '/vault/book', dict(src='nope.pdf', model='vh')),
          ('get', '/vault/book/problems', dict(doc='nope')), ('get', '/vault/book/problems', dict(state='bogus')),
          ('post', '/vault/book/probs/accept', dict(doc='nope', ids='x')), ('post', '/vault/book/probs/bogus', dict(doc='nope')),
          ('get', '/vault/book.md', dict(doc='nope')), ('post', '/vault/book.md', dict(doc='nope')),
          ('get', '/vault/sends', dict()), ('get', '/vault/sends', dict(doc='nope')), ('post', '/vault/access', dict(name='nope'))]

@pytest.mark.parametrize('how,route,args', ROUTES)
def test_every_new_route_answers_ok_or_a_kind(bws, how, route, args):
    with TestClient(ide_app(bws)) as c:
        r = c.get(route, params=args) if how == 'get' else c.post(route, json=args)
        body = r.json()
        assert body.get('ok') is True or (body.get('ok') is False and body.get('kind') and body.get('error')), body
