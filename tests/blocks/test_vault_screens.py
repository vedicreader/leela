"The vault screens: the Read sheet, its send line, the document view's routes, and the keys that reach them."

from __future__ import annotations

import json, time

import pytest
from fastcore.all import AttrDict
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.workspace import Workspace

INVOICE = 'INVOICE Invoice number 42 Bill to ACME Ltd\nQty Unit price Subtotal Tax Total due 100.00 Payment terms 30 days'
EMAIL = 'Write to jane.doe@example.com about the lease and the deposit please, before the end of the month'
PASSPORT = ('PASSPORT Republic of India Passport No. K1234567 Surname DOE Given names JANE\nNationality INDIAN '
            'Date of birth 01/01/1990 Place of issue Chennai Date of expiry 01/01/2030')

def mkpdf(pages):
    "A minimal PDF, one page per string; an empty string is a page with no text layer."
    objs, kids = ['<< /Type /Catalog /Pages 2 0 R >>', None, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'], []
    for t in pages:
        body = ('BT /F1 12 Tf 72 720 Td 14 TL ' + ' '.join(f'({l}) Tj T*' for l in t.split('\n')) + ' ET') if t else ''
        objs.append(f'<< /Length {len(body)} >>\nstream\n{body}\nendstream')
        objs.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> '
                    f'/Contents {len(objs)} 0 R >>')
        kids.append(len(objs))
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    out, offs = b'%PDF-1.4\n', []
    for i, o in enumerate(objs, 1): offs.append(len(out)); out += f'{i} 0 obj\n{o}\nendobj\n'.encode()
    x = len(out)
    out += f'xref\n0 {len(objs) + 1}\n0000000000 65535 f \n'.encode() + b''.join(f'{o:010} 00000 n \n'.encode() for o in offs)
    return out + f'trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n'.encode()

class Reader:
    "A page reader that keeps every page image it was sent. `runtime` places it on or off this machine."
    def __init__(self, model, runtime): self.model, self.runtime, self.sent = model, runtime, []
    def __call__(self, msgs):
        self.sent.append(msgs[0])
        return json.dumps({'items': [{'kind': 'prose', 'text': f'read by {self.model}'}]})

@pytest.fixture
def rws(tmp_path, monkeypatch):
    "A workspace, a 3-page PDF in it (text, a blank page, an email), and two stub readers."
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'vault.db'))
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    (proj := tmp_path/'proj').mkdir()
    (proj/'scan.pdf').write_bytes(mkpdf([INVOICE, '', EMAIL]))
    (proj/'passport.pdf').write_bytes(mkpdf([PASSPORT, '']))
    readers = {'hosted': Reader('hosted', 'hosted'), 'local': Reader('local', 'litert')}
    import leela.blocks.memory.memory as mm, leela.blocks.vault.app as va
    monkeypatch.setattr(mm, 'read_chat', lambda m: readers.get(m))
    def rid(name):
        if name and name not in readers: raise mm.VaultRefused(f'{name} is not available here', 'model_unavailable')
        return name or None
    monkeypatch.setattr(va, 'reader_id', rid)
    def spec(name):
        if name not in readers: raise mm.VaultRefused(f'{name} is not available here', 'model_unavailable')
        return AttrDict(name=name, local=readers[name].runtime == 'litert', model_id=name, runtime=readers[name].runtime, ctx=8000)
    monkeypatch.setattr(va, 'chat_spec', spec)
    ws = Workspace(roots=[str(proj)]); ws._state_path = tmp_path/'workspace.json'
    ws.readers, ws.proj = readers, proj
    return ws

def _wait(ws, html):
    jid = html.split('id="job-', 1)[1].split('"', 1)[0]
    for _ in range(400):
        j = ws.jobs.get(jid)
        if not j.active: return j
        time.sleep(.05)
    raise AssertionError('the read never finished')

def _est(c, src, **kw): return c.post('/vault/read', json=dict(src=str(src), estimate=True, **kw)).json()

def test_the_estimate_counts_pages_and_what_needs_a_model_and_suggests_from_the_type(rws):
    with TestClient(ide_app(rws)) as c:
        e = _est(c, rws.proj/'scan.pdf', model='hosted')
        assert e['ok'] and e['pages'] == 3 and e['need'] == [1], 'the blank page is the one a model must read'
        assert e['type']['doctype'] == 'invoice' and e['type']['preset'] == 'tables'
        assert e['remembered'] is None
        p = _est(c, rws.proj/'passport.pdf', model='hosted')
        assert p['type']['level'] == 'local' and p['level'] == 'local' and p['type']['vision'] == 'local'
        assert not p['check_ok'] and p['kind'] == 'local_only'

def test_a_read_files_every_page_with_its_route_and_remembers_the_choice_for_the_folder(rws):
    with TestClient(ide_app(rws)) as c:
        r = c.post('/vault/read', json=dict(src=str(rws.proj/'scan.pdf'), model='hosted', preset='tables', hint='an invoice'))
        assert r.status_code == 200, r.text
        j = _wait(rws, r.text)
        assert j.status == 'complete', j.error
        assert len(rws.readers['hosted'].sent) == 1, 'only the blank page went to the model'
        doc, shelf = j.result['doc_id'], j.result['shelf']
        pages = c.get('/vault/pages', params=dict(doc=doc, shelf=shelf)).json()['pages']
        assert [p['route'] for p in pages] == ['text', 'model', 'text']
        assert c.get('/vault/page', params=dict(doc=doc, shelf=shelf, page=1)).json()['text'] == 'read by hosted'
        assert rws.vault_read[str(rws.proj.resolve())]['preset'] == 'tables'
        assert 'allow' not in rws.vault_read[str(rws.proj.resolve())]
        again = Workspace(roots=[str(rws.proj)]).restore_settings(rws.state())
        assert again.vault_read == rws.vault_read, 'the choice outlives the session'
        assert _est(c, rws.proj/'scan.pdf')['remembered']['model'] == 'hosted'
        d = c.get('/vault/doc', params=dict(doc=doc, shelf=shelf)).json()
        assert d['paged'] == 3 and d['level']['level'] == 'personal', 'page 3 holds an email'

def test_a_bad_saved_choice_is_dropped_rather_than_breaking_the_restore(rws):
    w = Workspace(roots=[str(rws.proj)]).restore_settings({'vault_read': {'/a': {'parse': 'nonsense'}, '/b': 'x',
                                                                         '/c': {'parse': 'llm', 'allow': True}}})
    assert w.vault_read == {'/c': {'parse': 'llm', 'preset': 'generic', 'model': '', 'hint': ''}}

def test_a_personal_page_image_is_not_sent_to_a_hosted_reader_without_saying_so_first(rws):
    with TestClient(ide_app(rws)) as c:
        src = str(rws.proj/'scan.pdf')
        chk = c.post('/vault/send-check', json=dict(src=src, parse='llm', model='hosted')).json()
        assert not chk['check_ok'] and chk['kind'] == 'pii_blocked' and [w['page'] for w in chk['withheld']] == [2]
        r = c.post('/vault/read', json=dict(src=src, parse='llm', model='hosted'))
        assert r.status_code == 400 and r.json()['kind'] == 'pii_blocked' and r.json()['pages'] == [2]
        assert rws.readers['hosted'].sent == [], 'the refusal came before any page went anywhere'
        j = _wait(rws, c.post('/vault/read', json=dict(src=src, parse='llm', model='hosted', partial=True)).text)
        assert j.status == 'complete' and len(rws.readers['hosted'].sent) == 2 and j.result['blocked'] == [2]
        assert c.post('/vault/send-check', json=dict(src=src, parse='llm', model='local')).json()['check_ok'], \
            'a reader on this machine reads every page whole'

def test_allow_once_is_spent_by_the_read_it_was_given_to(rws):
    with TestClient(ide_app(rws)) as c:
        src = str(rws.proj/'scan.pdf')
        assert c.post('/vault/send-check', json=dict(src=src, parse='llm', model='hosted', allow=True)).json()['check_ok']
        j = _wait(rws, c.post('/vault/read', json=dict(src=src, parse='llm', model='hosted', allow=True)).text)
        assert j.status == 'complete' and len(rws.readers['hosted'].sent) == 3 and 'allow' not in j.params
        rws.readers['hosted'].sent.clear()
        j = _wait(rws, c.post(f'/jobs/{j.id}/retry').text)
        assert len(rws.readers['hosted'].sent) == 2, 'a retry asks again; the personal page stays home'

def test_a_local_only_choice_or_type_is_applied_before_any_page_is_sent(rws):
    rws.vault_pii = 'off'    # `read_doc` skips its own type check under off; the read must not
    with TestClient(ide_app(rws)) as c:
        j = _wait(rws, c.post('/vault/read', json=dict(src=str(rws.proj/'passport.pdf'), model='hosted', partial=True)).text)
        assert j.status == 'complete' and rws.readers['hosted'].sent == [] and j.result['level'] == 'local'
        r = c.post('/vault/read', json=dict(src=str(rws.proj/'scan.pdf'), parse='llm', model='hosted', level='local'))
        assert r.json()['kind'] == 'local_only', r.json()
        j = _wait(rws, c.post('/vault/read', json=dict(src=str(rws.proj/'scan.pdf'), parse='llm', model='hosted',
                                                         level='local', partial=True)).text)
        assert rws.readers['hosted'].sent == [] and j.result['level'] == 'local'
        j = _wait(rws, c.post('/vault/read', json=dict(src=str(rws.proj/'scan.pdf'), parse='llm', model='local')).text)
        assert len(rws.readers['local'].sent) == 3, 'Local only pages go to a reader on this machine'

def test_no_model_means_nothing_leaves_whatever_route_started_the_read(rws):
    with TestClient(ide_app(rws)) as c:
        e = _est(c, rws.proj/'scan.pdf')
        assert e['check_ok']
        j = _wait(rws, c.post('/clip', data=dict(target=str(rws.proj/'scan.pdf'))).text)
        assert j.kind == 'read' and j.status == 'complete' and j.params.get('model') is None
        assert not any(r.sent for r in rws.readers.values())
        assert c.post('/vault/read', json=dict(src=str(rws.proj/'scan.pdf'), parse='llm')).json()['kind'] == 'model_unavailable'

def test_refusals_carry_the_kind_their_screen_offers(rws):
    with TestClient(ide_app(rws)) as c:
        src = str(rws.proj/'scan.pdf')
        r = c.post('/vault/read', json=dict(src=src, model='nonesuch'))
        assert r.json()['kind'] == 'model_unavailable'
        e = _est(c, src, model='nonesuch')
        assert e['ok'] and e['kind'] == 'model_unavailable' and e['pages'] == 3, 'the sheet keeps the pages and asks for another model'
        assert c.post('/vault/read', json=dict(src=str(rws.proj/'gone.pdf'), estimate=True)).json()['kind'] == 'not_found'
        (rws.proj/'notes.md').write_text('# n\n')
        assert c.post('/vault/read', json=dict(src=str(rws.proj/'notes.md'), estimate=True)).json()['kind'] == 'unsupported'
        assert c.post('/vault/read', json=dict(src=src, parse='bogus')).json()['kind'] == 'bad_request'
        assert c.post('/vault/read', json=dict(src=src, pages='x-')).json()['kind'] == 'bad_request'

def test_a_second_read_of_the_same_file_is_busy(rws, monkeypatch):
    import threading
    gate = threading.Event()
    orig = rws.readers['hosted'].__call__
    monkeypatch.setattr(Reader, '__call__', lambda self, msgs: (gate.wait(5), orig(msgs))[1])
    with TestClient(ide_app(rws)) as c:
        src = str(rws.proj/'scan.pdf')
        first = c.post('/vault/read', json=dict(src=src, model='hosted'))
        r = c.post('/vault/read', json=dict(src=src, model='hosted'))
        gate.set()
        assert r.status_code == 409 and r.json()['kind'] == 'busy' and r.json()['job'] in first.text
        _wait(rws, first.text)

def test_a_read_only_vault_refuses_a_read(rws, tmp_path):
    from leela.blocks.memory.memory import Memory
    peer = tmp_path/'peer'/'vault.db'
    Memory(shelf='main', path=peer, offline=True)._open()
    rws.vaults.file = tmp_path/'vaults.json'
    rws.vaults.attach(str(peer), name='peer')
    with TestClient(ide_app(rws)) as c:
        r = c.post('/vault/read', json=dict(src=str(rws.proj/'scan.pdf'), vault='peer'))
        assert r.status_code == 403 and r.json()['kind'] == 'read_only'

def _read(rws, c, **kw):
    j = _wait(rws, c.post('/vault/read', json=dict(src=str(rws.proj/'scan.pdf'), **kw)).text)
    return j.result['doc_id'], j.result['shelf']

def test_page_images_render_in_memory_and_a_bad_page_says_render_failed(rws):
    with TestClient(ide_app(rws)) as c:
        doc, shelf = _read(rws, c)
        img = c.get('/vault/page/img', params=dict(doc=doc, shelf=shelf, page=0, w=120))
        assert img.status_code == 200 and img.headers['content-type'] == 'image/png' and img.content[:4] == b'\x89PNG'
        assert c.get('/vault/page/img', params=dict(doc=doc, shelf=shelf, page=0)).content[:4] == b'\x89PNG'
        bad = c.get('/vault/page/img', params=dict(doc=doc, shelf=shelf, page=9))
        assert bad.status_code == 422 and bad.json()['kind'] == 'render_failed'
        assert c.get('/vault/page/img', params=dict(doc='nope', page=0)).json()['kind'] == 'not_found'
        assert c.get('/vault/page', params=dict(doc=doc, shelf=shelf, page=9)).json()['kind'] == 'not_found'
        assert not list(rws.proj.rglob('*.png')), 'no render is left on disk where a file tool could pick it up'

def test_a_person_sets_and_lowers_a_documents_level(rws):
    with TestClient(ide_app(rws)) as c:
        doc, shelf = _read(rws, c)
        assert c.get('/vault/privacy', params=dict(doc=doc, shelf=shelf)).json()['level'] == 'personal'
        r = c.post('/vault/privacy', json=dict(doc=doc, shelf=shelf, level='local')).json()
        assert r['ok'] and r['privacy']['level'] == 'local'
        assert c.post('/vault/privacy', json=dict(doc=doc, shelf=shelf, level='open')).json()['privacy']['level'] == 'open'
        assert c.post('/vault/privacy', json=dict(doc=doc, shelf=shelf, level='')).json()['privacy']['level'] == 'personal', \
            'empty hands it back to detection'
        assert c.post('/vault/privacy', json=dict(doc=doc, shelf=shelf, level='bogus')).json()['kind'] == 'bad_request'
        assert c.post('/vault/privacy', json=dict(doc='nope', level='local')).json()['kind'] == 'not_found'
        chk = c.post('/vault/send-check', json=dict(refs=doc, shelf=shelf, model='hosted')).json()
        assert chk['ok'] and chk['check_ok'] and chk['masked'], 'a personal document goes masked to a hosted model'

ROUTES = [('get', '/vault/pages', dict(doc='nope')), ('get', '/vault/page', dict(doc='nope', page=0)),
          ('get', '/vault/page/img', dict(doc='nope')), ('get', '/vault/privacy', dict(doc='nope')),
          ('post', '/vault/privacy', dict(doc='nope', level='local')), ('post', '/vault/send-check', dict()),
          ('post', '/vault/read', dict(src='')), ('get', '/vault/doc', dict(doc='nope'))]

@pytest.mark.parametrize('how,route,args', ROUTES)
def test_every_new_route_answers_ok_or_a_kind(rws, how, route, args):
    with TestClient(ide_app(rws)) as c:
        r = c.get(route, params=args) if how == 'get' else c.post(route, json=args)
        body = r.json()
        assert body.get('ok') is True or (body.get('ok') is False and body.get('kind') and body.get('error')), body

def test_a_failed_job_keeps_its_kind_for_the_card(rws):
    from leela.blocks.memory.memory import PrivacyBlocked
    def boom(job, report): raise PrivacyBlocked('withheld', 'local_only')
    rws.jobs.register('boom', boom)
    j = rws.jobs.start('boom')
    for _ in range(100):
        if not (j := rws.jobs.get(j.id)).active: break
        time.sleep(.02)
    assert j.result['kind'] == 'local_only'

# ── one home ────────────────────────────────────────────────────────────────

def test_the_vault_tab_has_one_home_and_the_old_view_names_still_open(rws):
    rws.open_vault_workbench()
    with TestClient(ide_app(rws)) as c:
        assert c.get('/vault/workbench').status_code == 200
        for old in ('browse', 'add', 'news', 'specs', 'topics', 'settings'):
            assert c.get(f'/vault/view/{old}').status_code == 200, old
        assert c.get('/vault/panel').status_code == 200

def test_a_reopened_vault_tab_lands_on_settings(rws):
    rws.open_vault_workbench()
    with TestClient(ide_app(rws)) as c:
        assert c.get('/vault/view/library').status_code == 200 and c.get('/vault/view/settings').status_code == 200
        assert c.get('/vault/workbench?view=settings').status_code == 200
        assert rws.tabs[rws.active].ref == 'settings', 'a reopened tab lands on Settings'

def test_every_route_a_settings_control_swaps_into_still_answers_and_acts(rws):
    rws.open_vault_workbench('settings')
    with TestClient(ide_app(rws)) as c:
        assert c.post('/vault/watch', data={'target': 'https://example.com/a', 'every': '1d'}).status_code == 200
        listed = c.get('/vault/watches').json()['watches']
        assert len(listed) == 1
        assert c.post('/vault/unwatch', data={'watch_id': listed[0]['id']}).status_code == 200
        assert c.get('/vault/watches').json()['watches'] == [], 'an unwatched target is gone'
        assert c.get('/vault/tidy/list').status_code == 200 and c.post('/vault/reindex').status_code == 200
        assert c.get('/vault/find').status_code == 200
        assert c.post('/vault/activate', data={'name': rws.vaults.active.name, 'wb': 'true'}).status_code == 200
        bad = c.post('/vault/attach', data={'path': str(rws.proj/'nope'/'x.db')})
        assert bad.status_code >= 400 and bad.json()['error'], 'a refused attach carries the error leeVaultSettled shows'

# ── keys ────────────────────────────────────────────────────────────────────

def test_a_stored_unbound_open_vault_moves_onto_hyper_v(tmp_path):
    from leela.core.keys import DEFAULTS, keymap_json, read_overrides
    p = tmp_path/'keys.json'
    p.write_text(json.dumps({'_help': keymap_json()['_help'],
                             'keys': {k.action: '' if k.action == 'open_vault' else k.key for k in DEFAULTS}}))
    assert read_overrides(p, notes=[])['open_vault'] == 'hyper+v'

def test_page_ranges_are_written_one_based_and_passed_zero_based():
    from leela.blocks.memory.memory import page_list
    assert page_list('1-3,7') == [0, 1, 2, 6] and page_list('') is None and page_list(' 2 ') == [1]
