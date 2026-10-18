"Fixing a page and reviewing changes: re-read, history, cancel, proofread, the Review queue, personal information findings and As sent."

from __future__ import annotations

import json, threading, time

import pytest
from starlette.testclient import TestClient

from leela.app import ide_app
from tests.blocks.test_vault_screens import EMAIL, INVOICE, Reader, _wait, mkpdf, rws  # noqa: F401

PLAIN = 'Some plain words here about the weather and the garden in the spring time'

class Fixed(Reader):
    "A reader that answers `text`, with `box` on its one block, after `gate` opens."
    def __init__(self, model, runtime, text, box=None, gate=None):
        super().__init__(model, runtime); self.text, self.box, self.gate = text, box, gate
    def __call__(self, msgs):
        self.sent.append(msgs[0])
        if self.gate: self.gate.wait(10)
        return json.dumps({'items': [dict(kind='prose', text=self.text, **({'box': self.box} if self.box else {}))]})

def _doc(rws, c, name='scan.pdf', **kw):
    j = _wait(rws, c.post('/vault/read', json=dict(src=str(rws.proj/name), **kw)).text)
    assert j.status == 'complete', j.error
    return j.result['doc_id'], j.result['shelf']

@pytest.fixture
def plain(rws):
    "An Open 3-page PDF (text, blank, text) and readers that change two words of the first page."
    (rws.proj/'plain.pdf').write_bytes(mkpdf([INVOICE, '', PLAIN]))
    two = INVOICE.replace('ACME', 'ACMEX').replace('Payment', 'Paymnt').replace('\n', ' ')
    rws.readers |= {'p1': Fixed('p1', 'litert', two), 'p2': Fixed('p2', 'litert', two),
                    'p3': Fixed('p3', 'litert', INVOICE.replace('Ltd', 'Limited').replace('\n', ' '))}
    return rws

def _changes(c, doc, shelf, **kw): return c.get('/vault/changes', params=dict(doc=doc, shelf=shelf, **kw)).json()['changes']

def _proof(rws, c, doc, shelf, readers='p1,p2', pages='1', **kw):
    r = c.post('/vault/proofread', json=dict(doc=doc, shelf=shelf, readers=readers, pages=pages, **kw))
    assert r.status_code == 200, r.text
    return _wait(rws, r.text)

def _text(c, doc, shelf, page=0): return c.get('/vault/page', params=dict(doc=doc, shelf=shelf, page=page)).json()

# ── re-read and history ─────────────────────────────────────────────────────

def test_a_re_read_files_a_new_version_and_history_diffs_any_two(plain):
    with TestClient(ide_app(plain)) as c:
        doc, shelf = _doc(plain, c, 'plain.pdf')
        j = _wait(plain, c.post('/vault/reparse', json=dict(doc=doc, shelf=shelf, pages='1', model='hosted')).text)
        assert j.status == 'complete' and j.result['pages'] == [0] and j.result['model_pages'] == 1
        assert len(plain.readers['hosted'].sent) == 1, 'only the page asked for was sent'
        p = _text(c, doc, shelf)
        assert p['text'] == 'read by hosted' and p['versions'] == [1, 2] and p['route'] == 'model'
        hist = c.get('/vault/pages', params=dict(doc=doc, shelf=shelf, history=True)).json()['pages']
        assert [h['version'] for h in hist if h['page'] == 0] == [1, 2]
        d = c.get('/vault/page/diff', params=dict(doc=doc, shelf=shelf, page=0, a=1, b=2)).json()
        assert d['ok'] and any(r['kind'] == 'add' and 'read by hosted' in r['text'] for r in d['rows'])
        assert c.get('/vault/page/diff', params=dict(doc=doc, shelf=shelf, page=0, a=1, b=9)).json()['kind'] == 'not_found'

def test_a_re_read_of_a_personal_document_is_refused_for_a_hosted_model_before_any_image_goes(rws):
    with TestClient(ide_app(rws)) as c:
        doc, shelf = _doc(rws, c)
        r = c.post('/vault/reparse', json=dict(doc=doc, shelf=shelf, pages='1', model='hosted'))
        assert r.status_code == 400 and r.json()['kind'] == 'pii_blocked' and r.json()['pages'] == [0]
        assert rws.readers['hosted'].sent == [], 'reparse gates every page at the document level, and so does the check'
        chk = c.post('/vault/send-check', json=dict(doc=doc, shelf=shelf, pages='1', model='hosted')).json()
        assert chk['ok'] and not chk['check_ok'] and 'withheld' in chk['why']
        j = _wait(rws, c.post('/vault/reparse', json=dict(doc=doc, shelf=shelf, pages='1', model='hosted', partial=True)).text)
        assert j.status == 'complete' and j.result['blocked'] == [0] and rws.readers['hosted'].sent == []
        j = _wait(rws, c.post('/vault/reparse', json=dict(doc=doc, shelf=shelf, pages='1', model='local')).text)
        assert j.result['pages'] == [0] and len(rws.readers['local'].sent) == 1, 'a reader on this machine reads it'

def test_a_re_read_answers_the_kind_its_screen_offers(rws, tmp_path):
    with TestClient(ide_app(rws)) as c:
        doc, shelf = _doc(rws, c)
        post = lambda **kw: c.post('/vault/reparse', json=dict(doc=doc, shelf=shelf, **kw)).json()
        assert post(model='')['kind'] == 'model_unavailable'
        assert post(model='nonesuch')['kind'] == 'model_unavailable'
        assert post(model='local', pages='x')['kind'] == 'bad_request'
        assert post(model='local', preset='bogus')['kind'] == 'bad_request'
        assert c.post('/vault/reparse', json=dict(doc='nope', model='local')).json()['kind'] == 'not_found'

# ── cancel and resume ───────────────────────────────────────────────────────

def test_cancel_keeps_the_pages_read_and_resume_reads_exactly_the_rest(plain):
    gate = threading.Event()
    plain.readers['p1'].gate = gate
    with TestClient(ide_app(plain)) as c:
        doc, shelf = _doc(plain, c, 'plain.pdf')
        r = c.post('/vault/proofread', json=dict(doc=doc, shelf=shelf, readers='p1', pages='1-3', agree=1))
        jid = r.text.split('id="job-', 1)[1].split('"', 1)[0]
        assert 'data-job-cancel' in r.text, 'a running page job offers cancel'
        for _ in range(200):
            if plain.readers['p1'].sent: break
            time.sleep(.02)
        card = c.post(f'/jobs/{jid}/cancel').text
        assert 'cancelling' in card
        gate.set()
        j = _wait(plain, r.text)
        assert j.status == 'cancelled' and j.result['cancelled'] and j.result['unread'] == [1, 2]
        assert len(plain.readers['p1'].sent) == 1
        assert 'resume' in c.get(f'/jobs/{jid}').text
        j = _wait(plain, c.post(f'/jobs/{jid}/retry').text)
        assert j.status == 'complete' and j.params['pages'] == [1, 2] and len(plain.readers['p1'].sent) == 3
        assert c.post(f'/jobs/{jid}/cancel').json()['kind'] == 'bad_request', 'a finished job cannot be cancelled'
        assert c.post('/jobs/nope/cancel').json()['ok'] is False

def test_a_cancel_that_lands_after_the_last_page_is_a_complete_run(plain):
    gate = threading.Event()
    plain.readers['p1'].gate = gate
    with TestClient(ide_app(plain)) as c:
        doc, shelf = _doc(plain, c, 'plain.pdf')
        r = c.post('/vault/proofread', json=dict(doc=doc, shelf=shelf, readers='p1', pages='1', agree=1))
        jid = r.text.split('id="job-', 1)[1].split('"', 1)[0]
        for _ in range(200):
            if plain.readers['p1'].sent: break
            time.sleep(.02)
        c.post(f'/jobs/{jid}/cancel'); gate.set()
        assert _wait(plain, r.text).status == 'complete'

def test_a_cancelled_read_keeps_its_pages_and_resumes_without_allow_once(rws):
    "Four workers read at once, so the pages in flight finish; the rest are left unread for a resume."
    gate = threading.Event()
    (rws.proj/'six.pdf').write_bytes(mkpdf([PLAIN] * 6))
    rws.readers['g'] = g = Fixed('g', 'hosted', 'read by g', gate=gate)
    with TestClient(ide_app(rws)) as c:
        r = c.post('/vault/read', json=dict(src=str(rws.proj/'six.pdf'), parse='llm', model='g', allow=True))
        jid = r.text.split('id="job-', 1)[1].split('"', 1)[0]
        for _ in range(200):
            if len(g.sent) >= 4: break
            time.sleep(.02)
        c.post(f'/jobs/{jid}/cancel'); gate.set()
        j = _wait(rws, r.text)
        assert j.status == 'cancelled' and j.result['unread'] == [4, 5] and len(g.sent) == 4 and j.result['doc_id']
        assert 'allow' not in j.params, 'allow once was spent by the cancelled run'
        j = _wait(rws, c.post(f'/jobs/{jid}/retry').text)
        assert j.status == 'complete' and len(g.sent) == 6 and j.params['pages'] == [4, 5]
        pages = c.get('/vault/pages', params=dict(doc=j.result['doc_id'], shelf=j.result['shelf'])).json()['pages']
        assert [p['route'] for p in pages] == ['model'] * 6, 'the resume did not file the text layer over the pages already read'

# ── proofread and the queue ─────────────────────────────────────────────────

def test_proofreaders_file_changes_proposed_where_they_agree(plain):
    with TestClient(ide_app(plain)) as c:
        doc, shelf = _doc(plain, c, 'plain.pdf')
        e = c.post('/vault/proofread', json=dict(doc=doc, shelf=shelf, readers='p1,p2', pages='1', estimate=True)).json()
        assert e['ok'] and e['check_ok'] and len(e['lines']) == 2 and e['pages'] == [0]
        j = _proof(plain, c, doc, shelf, 'p1,p2,p3')
        assert j.status == 'complete' and j.result['changes'] == 3 and j.result['proposed'] == 2
        cs = _changes(c, doc, shelf)
        assert sorted(x['state'] for x in cs) == ['doubt', 'proposed', 'proposed'] and not any(x['stale'] for x in cs)
        assert {x['after'] for x in cs if x['state'] == 'proposed'} == {'ACMEX', 'Paymnt'}
        assert set(cs[0]['by']) <= {'p1', 'p2', 'p3'} and cs[0]['title'] and cs[0]['doc'] == doc
        assert any(x['doc'] == doc for x in c.get('/vault/changes').json()['changes']), 'the queue spans every document'
        assert _changes(c, doc, shelf, state='doubt')[0]['after'] == 'Limited'
        assert plain.vault_read[str(plain.proj.resolve())]['readers'] == ['p1', 'p2', 'p3']
        e = c.post('/vault/proofread', json=dict(doc=doc, shelf=shelf, estimate=True)).json()
        assert e['remembered']['readers'] == ['p1', 'p2', 'p3'] and e['remembered']['agree'] == 2

def test_a_hosted_proofreader_never_sees_a_personal_page(rws):
    with TestClient(ide_app(rws)) as c:
        doc, shelf = _doc(rws, c)
        r = c.post('/vault/proofread', json=dict(doc=doc, shelf=shelf, readers='hosted', pages='3'))
        assert r.status_code == 400 and r.json()['kind'] == 'pii_blocked' and rws.readers['hosted'].sent == []
        j = _wait(rws, c.post('/vault/proofread', json=dict(doc=doc, shelf=shelf, readers='hosted,local', pages='3', partial=True, agree=1)).text)
        assert j.status == 'complete' and rws.readers['hosted'].sent == [] and len(rws.readers['local'].sent) >= 1
        assert [b['reader'] for b in j.result['blocked']] == ['hosted']

def test_accepting_a_pages_changes_together_applies_both_and_undo_reverts_them_as_a_new_version(plain):
    with TestClient(ide_app(plain)) as c:
        doc, shelf = _doc(plain, c, 'plain.pdf')
        _proof(plain, c, doc, shelf)
        ids = ','.join(x['id'] for x in _changes(c, doc, shelf))
        r = c.post('/vault/changes/accept', json=dict(doc=doc, shelf=shelf, ids=ids)).json()
        assert r['ok'] and r['accepted'] == 2 and r['pages'] == [0]
        p = _text(c, doc, shelf)
        assert 'ACMEX' in p['text'] and 'Paymnt' in p['text'] and p['route'] == 'proof' and p['versions'] == [1, 2]
        assert _changes(c, doc, shelf) == []
        u = c.post('/vault/changes/undo', json=dict(doc=doc, shelf=shelf, ids=ids)).json()
        assert u['ok'] and u['pages'] == [0]
        p = _text(c, doc, shelf)
        assert 'ACMEX' not in p['text'] and 'ACME' in p['text'] and p['versions'] == [1, 2, 3], 'the revert is a version, not an erasure'
        assert p['route'] == 'revert'
        back = _changes(c, doc, shelf)
        assert len(back) == 2 and not any(x['stale'] for x in back), 'an undone accept puts its changes back in the queue, against the new version'
        assert c.post('/vault/changes/undo', json=dict(doc=doc, shelf=shelf, ids=ids)).json()['kind'] == 'stale', 'they are open, not decided'
        md = c.get('/vault/proof.md', params=dict(doc=doc, shelf=shelf))
        assert md.headers['content-type'].startswith('text/markdown') and '## Proposed' in md.text and 'ACMEX' in md.text
        saved = c.post('/vault/proof.md', json=dict(doc=doc, shelf=shelf)).json()
        assert saved['ok'] and (plain.proj/'plain.PROOFREAD.md').read_text().startswith('# Proofread')

def test_reject_undo_and_edit(plain):
    with TestClient(ide_app(plain)) as c:
        doc, shelf = _doc(plain, c, 'plain.pdf')
        _proof(plain, c, doc, shelf)
        a, b = _changes(c, doc, shelf)
        assert c.post('/vault/changes/reject', json=dict(doc=doc, shelf=shelf, ids=a['id'])).json()['rejected'] == 1
        assert [x['id'] for x in _changes(c, doc, shelf)] == [b['id']]
        assert c.post('/vault/changes/undo', json=dict(doc=doc, shelf=shelf, ids=a['id'])).json()['ok']
        assert {x['id']: x['state'] for x in _changes(c, doc, shelf)}[a['id']] == a['state'], 'an undone reject is back in the queue as it was'
        r = c.post('/vault/changes/accept', json=dict(doc=doc, shelf=shelf, ids=b['id'], after='Payments')).json()
        assert r['ok'] and 'Payments' in _text(c, doc, shelf)['text']
        assert c.post('/vault/changes/accept', json=dict(doc=doc, shelf=shelf, ids=f"{a['id']},{b['id']}", after='x')).json()['kind'] in ('bad_request', 'stale')

def test_a_change_against_an_older_page_is_stale_and_says_which(plain):
    with TestClient(ide_app(plain)) as c:
        doc, shelf = _doc(plain, c, 'plain.pdf')
        _proof(plain, c, doc, shelf)
        old = _changes(c, doc, shelf)
        _wait(plain, c.post('/vault/reparse', json=dict(doc=doc, shelf=shelf, pages='1', model='local')).text)
        assert all(x['stale'] for x in _changes(c, doc, shelf)), 'the queue greys them'
        r = c.post('/vault/changes/accept', json=dict(doc=doc, shelf=shelf, ids=old[0]['id']))
        assert r.status_code == 409 and r.json()['kind'] == 'stale' and r.json()['ids'] == [old[0]['id']]
        _proof(plain, c, doc, shelf)    # files fresh rows and drops the old ones
        r = c.post('/vault/changes/reject', json=dict(doc=doc, shelf=shelf, ids=old[0]['id'])).json()
        assert r['kind'] == 'stale', 'a gone id is stale, not silently nothing'
        assert c.post('/vault/changes/undo', json=dict(doc=doc, shelf=shelf, ids=old[0]['id'])).json()['kind'] == 'stale'

def test_a_decision_waits_while_a_job_runs_on_the_document(plain):
    gate = threading.Event()
    with TestClient(ide_app(plain)) as c:
        doc, shelf = _doc(plain, c, 'plain.pdf')
        _proof(plain, c, doc, shelf)
        cid = _changes(c, doc, shelf)[0]['id']
        plain.readers['p3'].gate = gate
        r = c.post('/vault/proofread', json=dict(doc=doc, shelf=shelf, readers='p3', pages='2', agree=1))
        busy = c.post('/vault/changes/accept', json=dict(doc=doc, shelf=shelf, ids=cid))
        again = c.post('/vault/reparse', json=dict(doc=doc, shelf=shelf, model='local'))
        gate.set(); _wait(plain, r.text)
        assert busy.status_code == 409 and busy.json()['kind'] == 'busy'
        assert again.json()['kind'] == 'busy'

def test_a_crop_is_the_part_of_the_page_its_box_names(rws):
    from PIL import Image
    import io
    with TestClient(ide_app(rws)) as c:
        doc, shelf = _doc(rws, c)
        full = Image.open(io.BytesIO(c.get('/vault/page/crop', params=dict(doc=doc, shelf=shelf, page=0)).content))
        r = c.get('/vault/page/crop', params=dict(doc=doc, shelf=shelf, page=0, box='0.1,0.1,0.5,0.3'))
        part = Image.open(io.BytesIO(r.content))
        assert r.headers['content-type'] == 'image/png' and part.width < full.width / 2 + 20 and part.height < full.height / 4
        assert c.get('/vault/page/crop', params=dict(doc=doc, shelf=shelf, page=0, box='a,b')).json()['kind'] == 'bad_request'

def test_a_change_read_by_model_carries_its_box(rws):
    box = [.1, .2, .6, .3]
    rws.readers['boxed'] = Fixed('boxed', 'litert', 'one two three', box=box)
    rws.readers['q1'] = Fixed('q1', 'litert', 'one too three')
    with TestClient(ide_app(rws)) as c:
        doc, shelf = _doc(rws, c, model='boxed')
        _wait(rws, c.post('/vault/proofread', json=dict(doc=doc, shelf=shelf, readers='q1', pages='2', agree=1)).text)
        (ch,) = _changes(c, doc, shelf)
        assert ch['page'] == 1 and ch['box'] == box and ch['after'] == 'too'

# ── personal information ────────────────────────────────────────────────────

def test_findings_show_masked_previews_and_a_person_decides_each(rws):
    with TestClient(ide_app(rws)) as c:
        doc, shelf = _doc(rws, c)
        fs = c.get('/vault/pii/findings', params=dict(doc=doc, shelf=shelf)).json()['findings']
        em = [f for f in fs if f['kind'] == 'email']
        assert em and em[0]['page'] == 2 and em[0]['state'] == 'found'
        assert 'jane.doe@example.com' not in json.dumps(fs), 'a preview, never the value'
        post = lambda v, ids: c.post(f'/vault/pii/findings/{v}', json=dict(doc=doc, shelf=shelf, ids=ids))
        r = post('reject', em[0]['id']).json()
        assert r['ok'] and r['privacy']['level'] == 'open', 'not personal: the email no longer makes it Personal'
        assert post('undo', em[0]['id']).json()['privacy']['level'] == 'personal'
        assert post('accept', em[0]['id']).json()['privacy']['level'] == 'personal'
        assert c.get('/vault/pii/findings', params=dict(doc=doc, shelf=shelf, state='accepted')).json()['findings']
        assert post('reject', 'gone').json()['kind'] == 'stale'
        assert post('bogus', em[0]['id']).json()['kind'] == 'not_found'
        assert c.post('/vault/pii/scan', json=dict(doc=doc, shelf=shelf)).json()['ok']

def test_as_sent_shows_what_a_hosted_model_receives_of_a_page(rws):
    with TestClient(ide_app(rws)) as c:
        doc, shelf = _doc(rws, c)
        sent = lambda p: c.get('/vault/page', params=dict(doc=doc, shelf=shelf, page=p, view='sent')).json()
        s = sent(2)
        assert s['how'] == 'masked' and 'jane.doe@example.com' not in s['text'] and '[EMAIL' in s['text']
        assert sent(0)['how'] == 'whole' and 'ACME' in sent(0)['text']
        c.post('/vault/privacy', json=dict(doc=doc, shelf=shelf, level='local'))
        s = sent(0)
        assert s['how'] == 'withheld' and 'withheld' in s['text'] and 'ACME' not in s['text']
        rws.vault_pii = 'off'
        c.post('/vault/privacy', json=dict(doc=doc, shelf=shelf, level=''))
        assert sent(2)['how'] == 'whole', 'as is (not recommended) sends it whole'

# ── every route answers ok or a kind ────────────────────────────────────────

ROUTES = [('post', '/vault/reparse', dict(doc='nope', model='local')), ('post', '/vault/proofread', dict(doc='nope', readers='local')),
          ('get', '/vault/changes', dict(doc='nope')), ('post', '/vault/changes/accept', dict(doc='nope', ids='x')),
          ('post', '/vault/changes/reject', dict(doc='nope', ids='x')), ('post', '/vault/changes/undo', dict(doc='nope', ids='x')),
          ('get', '/vault/page/diff', dict(doc='nope', a=1, b=2)), ('get', '/vault/page/crop', dict(doc='nope')),
          ('get', '/vault/proof.md', dict(doc='nope')), ('post', '/vault/proof.md', dict(doc='nope')),
          ('get', '/vault/pii/findings', dict(doc='nope')), ('post', '/vault/pii/findings/accept', dict(doc='nope', ids='x')),
          ('post', '/vault/pii/scan', dict(doc='nope')), ('get', '/vault/page', dict(doc='nope', view='sent')),
          ('post', '/vault/send-check', dict(doc='nope', model='local')), ('post', '/jobs/nope/cancel', dict()),
          ('post', '/vault/page/revert', dict(doc='nope', page=0, version=1)), ('post', '/vault/page/revert', dict(doc='nope'))]

@pytest.mark.parametrize('how,route,args', ROUTES)
def test_every_new_route_answers_ok_or_a_kind(rws, how, route, args):
    with TestClient(ide_app(rws)) as c:
        r = c.get(route, params=args) if how == 'get' else c.post(route, json=args)
        body = r.json()
        assert body.get('ok') is True or (body.get('ok') is False and body.get('kind') and body.get('error')), body

def test_a_read_only_vault_refuses_every_decision(rws, tmp_path):
    from leela.blocks.memory.memory import Memory
    peer = tmp_path/'peer'/'vault.db'
    Memory(shelf='main', path=peer, offline=True)._open()
    rws.vaults.file = tmp_path/'vaults.json'
    rws.vaults.attach(str(peer), name='peer')
    with TestClient(ide_app(rws)) as c:
        for route in ('/vault/changes/accept', '/vault/pii/findings/reject', '/vault/reparse', '/vault/proofread'):
            r = c.post(route, json=dict(doc='x', ids='y', vault='peer', model='local', readers='local'))
            assert r.status_code == 403 and r.json()['kind'] == 'read_only', route

def test_staged_edits_apply_with_the_rest_of_their_page(plain):
    with TestClient(ide_app(plain)) as c:
        doc, shelf = _doc(plain, c, 'plain.pdf')
        _proof(plain, c, doc, shelf)
        a, b = _changes(c, doc, shelf)
        r = c.post('/vault/changes/accept', json=dict(doc=doc, shelf=shelf, ids=f"{a['id']},{b['id']}", edits=json.dumps({b['id']: 'Payments'}))).json()
        assert r['ok'] and r['accepted'] == 2
        t = _text(c, doc, shelf)['text']
        assert a['after'] in t and 'Payments' in t
        assert c.post('/vault/changes/accept', json=dict(doc=doc, shelf=shelf, ids=a['id'], edits='[1]')).json()['ok'] is False

def test_the_review_and_page_keys_have_their_own_scopes():
    from pathlib import Path
    from leela.core.keys import DEFAULTS, _dupes, lookup
    assert _dupes(DEFAULTS) == []
    want = {'review_next': 'j', 'review_prev': 'k', 'review_accept': 'a', 'review_reject': 'x', 'review_accept_page': 'A',
            'review_accept_doc': 'alt+a', 'review_doubts': 'd', 'review_edit': 'e', 'review_undo': 'u'}
    assert {a: lookup(a).key for a in want} == want and {lookup(a).scope for a in want} == {'review'}
    assert {a: lookup(a).key for a in ('vault_reread', 'vault_history', 'vault_proofread', 'vault_as_sent')} == \
        {'vault_reread': 'r', 'vault_history': 'h', 'vault_proofread': 'p', 'vault_as_sent': 'm'}
    assert lookup('vault_review').label, 'the palette lists the review queue'
    km = (Path(__file__).resolve().parents[2]/'leela/blocks/keys/keymap.js').read_text()
    assert km.index("'.lee-vault-review'") < km.index("'.lee-vault-docview'") < km.index("'#editor,"), \
        'review and vault are matched before the editor that holds them'

def test_the_vault_tab_has_a_review_view(rws):
    rws.open_vault_workbench()
    with TestClient(ide_app(rws)) as c:
        assert '/vault/view/review' in c.get('/vault/workbench').text
        v = c.get('/vault/view/review', params=dict(doc='d1', shelf='main')).text
        assert 'lee-vault-review' in v and 'data-doc="d1"' in v

# ── vishalakshi's public seams, not its private tables ─────────────────────

def test_leela_reaches_no_private_vishalakshi_function():
    "Edits, undos and the way back to `found` went through `_proof_t`, `_file_pages` and `_judge` before 0.1.24 made them public."
    import inspect, re
    import leela.blocks.memory.memory as mm, leela.blocks.vault.app as va
    src = inspect.getsource(mm) + inspect.getsource(va)
    assert not re.findall(r'\._(?:proof_t|file_pages|judge|refile|pages_t|findings_t)\(', src)

def test_an_old_version_of_a_page_is_restored_as_its_newest(plain):
    with TestClient(ide_app(plain)) as c:
        doc, shelf = _doc(plain, c, 'plain.pdf')
        _wait(plain, c.post('/vault/reparse', json=dict(doc=doc, shelf=shelf, pages='1', model='hosted')).text)
        assert _text(c, doc, shelf)['text'] == 'read by hosted'
        r = c.post('/vault/page/revert', json=dict(doc=doc, shelf=shelf, page=0, version=1)).json()
        assert r['ok'] and r['version'] == 3
        p = _text(c, doc, shelf)
        assert 'ACME' in p['text'] and p['route'] == 'revert' and p['versions'] == [1, 2, 3], 'nothing is erased'
        assert c.get('/vault/search', params=dict(q='ACME')).json()['hits'], 'the document is re-indexed on the restored text'
        r = c.post('/vault/page/revert', json=dict(doc=doc, shelf=shelf, page=0, version=9))
        assert r.status_code == 404 and r.json()['kind'] == 'not_found'
        assert c.post('/vault/page/revert', json=dict(doc=doc, shelf=shelf, page=0)).json()['kind'] == 'bad_request'

def test_an_edit_to_a_decided_change_is_stale(plain):
    with TestClient(ide_app(plain)) as c:
        doc, shelf = _doc(plain, c, 'plain.pdf')
        _proof(plain, c, doc, shelf)
        a, b = _changes(c, doc, shelf)
        c.post('/vault/changes/reject', json=dict(doc=doc, shelf=shelf, ids=a['id']))
        r = c.post('/vault/changes/accept', json=dict(doc=doc, shelf=shelf, ids=a['id'], after='x'))
        assert r.status_code == 409 and r.json()['kind'] == 'stale' and r.json()['ids'] == [a['id']]
