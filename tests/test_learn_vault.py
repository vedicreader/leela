import json, sqlite3, time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from abhyasa.learner import Learning
from leela.app import ide_app
from leela.blocks.learn.tools import learn_store
from leela.blocks.memory.vaults import LEARN
from leela.hub import LoopbackHostGuard


def _walk(path, jid='old'):
    from vishalakshi import Vault
    lr = Learning(Vault(str(path), offline=True))
    lr.put_journey(dict(id=jid, title=jid.title(), goal='learn', steps=[]))
    return lr


def _wait(ws, out):
    end = time.monotonic() + 30
    while time.monotonic() < end:
        if not (job := ws.jobs.get(out['index'])).active: return job
        time.sleep(.05)
    raise AssertionError('index job did not finish')


def _client(ws): return TestClient(LoopbackHostGuard(ide_app(ws)), base_url='http://127.0.0.1')


def _headers(): return {'sec-fetch-site': 'same-origin', 'origin': 'http://127.0.0.1'}


@pytest.fixture(autouse=True)
def _abhyasa_config(abhyasa_cfg): pass


def test_first_use_creates_one_managed_learn_entry(ws):
    a, _ = learn_store(ws)
    b, _ = learn_store(ws)
    rows = [r for r in ws.vaults if r.name == LEARN]
    assert a == b == LEARN and len(rows) == 1
    saved = json.loads(ws.vaults.file.read_text())
    assert [r['name'] for r in saved['vaults']].count(LEARN) == 1


def test_learn_store_ignores_the_active_vault(ws):
    active = ws.vaults.active
    name, lr = learn_store(ws, write=True)
    lr.put_journey(dict(id='managed', title='Managed', goal='learn', steps=[]))
    assert name == LEARN and lr.journey('managed')
    assert Learning(active.path).journey('managed') is None


def test_attach_uses_existing_file_without_changing_it(ws, tmp_path, monkeypatch):
    src = tmp_path/'standalone.db'; _walk(src)
    before = src.read_bytes(); monkeypatch.setenv('ABHYASA_VAULT', str(src))
    learn_store(ws)
    with _client(ws) as cl:
        offer = cl.get('/vault/learn-import').json()
        out = cl.post('/vault/learn-import', data={'choice': 'attach'}, headers=_headers()).json()
    assert offer['found'] and offer['learn_exists']
    assert out == {'ok': True, 'vault': LEARN, 'choice': 'attach', 'access': 'admin'}
    assert Path(ws.vaults.get(LEARN).path).resolve() == src.resolve()
    assert src.read_bytes() == before


def test_copy_backs_up_source_and_copies_learning(ws, tmp_path, monkeypatch):
    src = tmp_path/'standalone.db'; _walk(src)
    before = src.read_bytes(); monkeypatch.setenv('ABHYASA_VAULT', str(src))
    learn_store(ws)
    with _client(ws) as cl:
        out = cl.post('/vault/learn-import', data={'choice': 'copy'}, headers=_headers()).json()
    assert out['ok'], out
    backup = Path(out['backup'])
    assert out['ok'] and out['vault'] == LEARN
    assert src.read_bytes() == before and sqlite3.connect(backup).execute("select count(*) from learning_docs where kind='journey'").fetchone()[0] == 1
    _wait(ws, out)
    assert learn_store(ws)[1].journey('old')


def test_second_import_does_not_duplicate(ws, tmp_path, monkeypatch):
    src = tmp_path/'standalone.db'; _walk(src)
    monkeypatch.setenv('ABHYASA_VAULT', str(src))
    learn_store(ws)
    with _client(ws) as cl:
        first = cl.post('/vault/learn-import', data={'choice': 'copy'}, headers=_headers()).json()
        second = cl.post('/vault/learn-import', data={'choice': 'copy'}, headers=_headers()).json()
    assert first['ok'], first
    _wait(ws, first)
    assert not second['ok'] and second['kind'] == 'already_imported'
    assert len(learn_store(ws)[1].journeys()) == 1
    assert len(list(tmp_path.glob('standalone.*.backup.db'))) == 1


def test_missing_standalone_vault_is_typed(ws, tmp_path, monkeypatch):
    monkeypatch.setenv('ABHYASA_VAULT', str(tmp_path/'missing.db'))
    with _client(ws) as cl:
        offer = cl.get('/vault/learn-import').json()
        out = cl.post('/vault/learn-import', data={'choice': 'copy'}, headers=_headers()).json()
    assert offer['found'] is False
    assert out['ok'] is False and out['kind'] == 'none_found'


def test_cross_site_import_is_refused(ws, tmp_path, monkeypatch):
    src = tmp_path/'standalone.db'; _walk(src)
    before = src.read_bytes(); monkeypatch.setenv('ABHYASA_VAULT', str(src))
    with _client(ws) as cl:
        r = cl.post('/vault/learn-import', data={'choice': 'attach'}, headers={'sec-fetch-site': 'cross-site', 'origin': 'http://evil.test'})
    assert r.status_code in (403, 421)
    assert ws.vaults.get(LEARN) is None and src.read_bytes() == before


def _src(tmp_path, monkeypatch, walks=1, name='standalone.db'):
    src = tmp_path/name
    if walks:
        for i in range(walks): _walk(src, f'w{i}')
    else: Learning(str(src))
    monkeypatch.setenv('ABHYASA_VAULT', str(src))
    return src


def _post(cl, choice, **h): return cl.post('/vault/learn-import', data={'choice': choice}, headers={**_headers(), **h})


def test_offer_names_what_was_found_and_the_three_actions(ws, tmp_path, monkeypatch):
    src = _src(tmp_path, monkeypatch, walks=2)
    with _client(ws) as cl: r = cl.get('/learn/import')
    assert r.status_code == 200 and 'text/html' in r.headers['content-type'] and not r.text.lstrip().lower().startswith('<!doctype')
    assert '2 walks' in r.text and 'standalone.db' in r.text and tmp_path.name in r.text and str(tmp_path) not in r.text
    for c in ('attach', 'copy', 'skip'): assert f'value="{c}"' in r.text
    assert 'hx-post="/vault/learn-import"' in r.text and ws.vaults.get(LEARN) is None


def test_no_offer_for_an_empty_or_missing_standalone_vault(ws, tmp_path, monkeypatch):
    _src(tmp_path, monkeypatch, walks=0)
    with _client(ws) as cl:
        a = cl.get('/learn/import')
        monkeypatch.setenv('ABHYASA_VAULT', str(tmp_path/'missing.db'))
        b = cl.get('/learn/import')
    assert a.status_code == b.status_code == 204 and a.text == b.text == ''


def test_offer_survives_an_empty_learn_vault_made_on_first_use(ws, tmp_path, monkeypatch):
    _src(tmp_path, monkeypatch); learn_store(ws)
    with _client(ws) as cl: assert cl.get('/learn/import').status_code == 200


def test_no_offer_after_attach_or_copy_and_the_offer_is_not_a_second_import(ws, tmp_path, monkeypatch):
    _src(tmp_path, monkeypatch)
    with _client(ws) as cl:
        assert _post(cl, 'attach').json()['ok']
        assert cl.get('/learn/import').status_code == 204 and cl.get('/learn/import?again=1').text.count('value="copy"') == 0


def test_attach_folds_an_alias_of_the_same_file(ws, tmp_path, monkeypatch):
    src = _src(tmp_path, monkeypatch); ws.vaults.attach(src, name='old')
    with _client(ws) as cl: out = _post(cl, 'attach').json()
    rows = [r for r in ws.vaults if Path(r.path).resolve() == src.resolve()]
    assert out['ok'] and [r.name for r in rows] == [LEARN] and ws.vaults.get('old') is None


def test_attach_after_an_empty_learn_vault_exists(ws, tmp_path, monkeypatch):
    src = _src(tmp_path, monkeypatch); learn_store(ws)
    with _client(ws) as cl: assert _post(cl, 'attach').json()['ok']
    assert Path(ws.vaults.get(LEARN).path).resolve() == src.resolve() and learn_store(ws)[1].journey('w0')


def test_read_only_source_is_not_attached_and_says_why(ws, tmp_path, monkeypatch):
    src = _src(tmp_path, monkeypatch); src.chmod(0o444)
    try:
        with _client(ws) as cl:
            out = _post(cl, 'attach').json()
            assert cl.get('/learn/import').status_code == 200
        assert not out['ok'] and out['kind'] == 'read_only' and 'Back up and copy' in out['error']
        assert ws.vaults.get(LEARN) is None
    finally: src.chmod(0o644)


def test_learn_writes_on_a_read_only_learn_vault_raise(ws):
    ws.vaults.learn(); ws.vaults.set_access(LEARN, 'read')
    with pytest.raises(PermissionError, match='read-only'): learn_store(ws, write=True)


def test_read_only_source_copies_and_stays_untouched(ws, tmp_path, monkeypatch):
    src = _src(tmp_path, monkeypatch); before = src.read_bytes(); src.chmod(0o444)
    try:
        with _client(ws) as cl: out = _post(cl, 'copy').json()
        assert out['ok'], out
        _wait(ws, out)
        assert src.read_bytes() == before and learn_store(ws, write=True)[1].journey('w0')
    finally: src.chmod(0o644)


def test_failed_backup_changes_nothing_and_says_why(ws, tmp_path, monkeypatch):
    src = _src(tmp_path, monkeypatch); before = src.read_bytes()
    def boom(*a, **k): raise OSError('disk full')
    monkeypatch.setattr('leela.blocks.vault.app._backup', boom)
    with _client(ws) as cl:
        out = _post(cl, 'copy').json()
        assert cl.get('/learn/import').status_code == 200
    assert not out['ok'] and out['kind'] == 'backup_failed' and 'disk full' in out['error'] and str(tmp_path) not in out['error']
    assert src.read_bytes() == before and not list(tmp_path.glob('*.backup.db'))
    assert not (ws.vaults.get(LEARN) and ws.vaults.get(LEARN).imported_from)


def test_partial_copy_is_rolled_back(ws, tmp_path, monkeypatch):
    import sqlite3
    src = _src(tmp_path, monkeypatch)
    con = sqlite3.connect(src); con.execute('alter table learning_nodes add column extra text'); con.commit(); con.close()
    before = src.read_bytes()
    with _client(ws) as cl:
        out = _post(cl, 'copy').json()
        again = cl.get('/learn/import')
    assert not out['ok'] and out['kind'] == 'copy_failed' and 'undone' in out['error'] and 'backup' in out['error']
    assert src.read_bytes() == before and learn_store(ws)[1].journeys() == []
    assert not ws.vaults.get(LEARN).imported_from and again.status_code == 200


def test_copy_keeps_the_learn_vault_encoder_stamp(ws, tmp_path, monkeypatch):
    import sqlite3
    src = _src(tmp_path, monkeypatch)
    con = sqlite3.connect(src); con.execute("update store_meta set encoder='other/encoder' where name='learning'"); con.commit(); con.close()
    with _client(ws) as cl: out = _post(cl, 'copy').json()
    _wait(ws, out)
    assert out['ok'] and learn_store(ws)[1].journey('w0')


def test_copy_refuses_a_learn_vault_that_already_holds_learning(ws, tmp_path, monkeypatch):
    _src(tmp_path, monkeypatch)
    lr = learn_store(ws, write=True)[1]; lr.put_journey(dict(id='mine', title='Mine', goal='g', steps=[]))
    with _client(ws) as cl: out = _post(cl, 'copy').json()
    assert not out['ok'] and out['kind'] == 'learn_not_empty' and lr.journey('mine')


def test_skip_starts_empty_and_the_offer_waits_to_be_asked(ws, tmp_path, monkeypatch):
    src = _src(tmp_path, monkeypatch); before = src.read_bytes()
    with _client(ws) as cl:
        out = _post(cl, 'skip').json()
        quiet = cl.get('/learn/import')
        asked = cl.get('/learn/import?again=1')
        later = _post(cl, 'attach').json()
    assert out == {'ok': True, 'vault': LEARN, 'choice': 'skip'} and quiet.status_code == 204 and 'value="copy"' in asked.text
    assert later['ok'] and src.read_bytes() == before


def test_htmx_post_gets_the_result_line_and_json_gets_the_same_dict(ws, tmp_path, monkeypatch):
    _src(tmp_path, monkeypatch)
    with _client(ws) as cl:
        r = _post(cl, 'skip', **{'hx-request': 'true'})
        j = _post(cl, 'skip')
    assert r.status_code == 200 and 'id="learnimport"' in r.text and 'Learn starts empty' in r.text
    assert j.json()['choice'] == 'skip'


def test_failed_import_line_shows_the_error_and_the_actions_again(ws, tmp_path, monkeypatch):
    _src(tmp_path, monkeypatch)
    monkeypatch.setattr('leela.blocks.vault.app._backup', lambda *a, **k: (_ for _ in ()).throw(OSError('disk full')))
    with _client(ws) as cl: r = _post(cl, 'copy', **{'hx-request': 'true'})
    assert r.status_code == 200 and 'disk full' in r.text and 'value="attach"' in r.text


def test_agent_write_tools_report_read_only_on_the_learn_vault(ws):
    from types import SimpleNamespace
    from leela.blocks.learn.tools import learn_tools
    ws.vaults.learn(); ws.vaults.set_agent(LEARN, False)
    ai = SimpleNamespace(ws=ws, mode='learn', session_id='s', oneshot=lambda *a, **k: '', spec_or_none=lambda job='turn': None)
    tool = {f.__name__: f for f in learn_tools(ai)}['note_confusion']
    r = tool(slug='x', note='y') if 'slug' in tool.__annotations__ else tool(**{k: 'x' for k in tool.__annotations__})
    assert r['status'] == 'error' and 'read_only' in json.dumps(r)


def _same_file_src(ws, monkeypatch):
    p = Path(ws.vaults.get('workspace').path); _walk(p, 'w0')
    monkeypatch.setenv('ABHYASA_VAULT', str(p))
    return p


def test_same_file_offer_has_no_attach_and_says_why(ws, monkeypatch):
    _same_file_src(ws, monkeypatch)
    with _client(ws) as cl: r = cl.get('/learn/import')
    assert r.status_code == 200 and 'workspace vault file' in r.text
    assert 'value="attach"' not in r.text and 'value="copy"' in r.text and 'value="skip"' in r.text


def test_same_file_attach_is_refused_without_a_second_row(ws, monkeypatch):
    p = _same_file_src(ws, monkeypatch)
    with _client(ws) as cl: out = _post(cl, 'attach').json()
    assert not out['ok'] and out['kind'] == 'same_file' and ws.vaults.get(LEARN) is None
    assert [r.name for r in ws.vaults if Path(r.path).resolve() == p.resolve()] == ['workspace']


def test_same_file_copy_makes_a_separate_vault_and_the_offer_does_not_return(ws, monkeypatch):
    p = _same_file_src(ws, monkeypatch); before = len(list(ws.vaults))
    with _client(ws) as cl:
        out = _post(cl, 'copy').json(); _wait(ws, out)
        again = cl.get('/learn/import'); asked = cl.get('/learn/import?again=1')
    assert out['ok'] and Path(ws.vaults.get(LEARN).path).resolve() != p.resolve() and len(list(ws.vaults)) == before + 1
    assert again.status_code == 204 and 'value="copy"' not in asked.text and learn_store(ws)[1].journey('w0')


def test_copy_queues_an_index_job_and_the_result_says_so(ws, tmp_path, monkeypatch):
    _src(tmp_path, monkeypatch)
    with _client(ws) as cl:
        out = _post(cl, 'copy').json()
        line = _post(cl, 'copy', **{'hx-request': 'true'}).text
    assert out['ok'] and out['index'].startswith('learn_index-') and out['indexing'].startswith('indexing 0 of ')
    job = _wait(ws, out)
    assert job.status == 'complete' and job.result['indexed'] == job.result['total'] > 0
    assert ws.vaults.memory(LEARN)._store('learning').db._ann_meta('learning')['ndim']


def test_htmx_copy_line_names_the_index_and_polls_the_job(ws, tmp_path, monkeypatch):
    _src(tmp_path, monkeypatch)
    with _client(ws) as cl: r = _post(cl, 'copy', **{'hx-request': 'true'})
    assert 'Search by meaning is being built.' in r.text and 'hx-get="/jobs/learn_index-' in r.text


def test_the_index_job_card_is_one_plain_line(ws, tmp_path, monkeypatch):
    _src(tmp_path, monkeypatch)
    with _client(ws) as cl:
        out = _post(cl, 'copy').json(); _wait(ws, out)
        card = cl.get(f"/jobs/{out['index']}").text
    assert 'Search by meaning is ready.' in card
    assert not any(x in card for x in ('>learn_index<', '>complete<', '<summary', '<pre'))
    from leela.blocks.vault.ui import _index_line
    assert _index_line(dict(active=True, current='indexing 3 of 101', status='running')) == 'Building search by meaning: 3 of 101.'
    assert 'stopped' in _index_line(dict(active=False, current='', status='cancelled'))


def test_copy_from_another_encoder_embeds_again_then_indexes(ws, tmp_path, monkeypatch):
    src = _src(tmp_path, monkeypatch)
    con = sqlite3.connect(src); con.execute("update store_meta set encoder='other/encoder' where name='learning'"); con.commit(); con.close()
    with _client(ws) as cl: out = _post(cl, 'copy').json()
    job = _wait(ws, out); v = ws.vaults.memory(LEARN)._store('learning')
    assert job.status == 'complete' and job.result['reencoded'] and job.result['indexed'] == job.result['total'] > 0
    assert {len(r['embedding']) for r in v.db.q('select embedding from learning where embedding is not null')} == {v.enc.dims * 2}


def test_failed_index_leaves_the_copy_intact_and_says_so(ws, tmp_path, monkeypatch):
    from apswutils.db import Table
    _src(tmp_path, monkeypatch)
    def boom(self, *a, **k): raise OSError('index disk full')
    monkeypatch.setattr(Table, 'rebuild_index', boom)
    with _client(ws) as cl: out = _post(cl, 'copy').json()
    job = _wait(ws, out)
    assert out['ok'] and job.status == 'error' and 'index disk full' in job.error
    assert learn_store(ws)[1].journey('w0') and ws.vaults.get(LEARN).imported_from


def test_index_that_cannot_start_leaves_the_copy_and_says_so(ws, tmp_path, monkeypatch):
    _src(tmp_path, monkeypatch)
    def boom(*a, **k): raise RuntimeError('no jobs')
    monkeypatch.setattr(ws.jobs, 'start', boom)
    with _client(ws) as cl: out = _post(cl, 'copy').json()
    assert out['ok'] and out['index'] is None and 'copy is complete' in out['index_error'] and learn_store(ws)[1].journey('w0')


def test_stopped_index_job_changes_no_embeddings(ws, tmp_path, monkeypatch):
    src = _src(tmp_path, monkeypatch)
    con = sqlite3.connect(src); con.execute("update store_meta set encoder='other/encoder' where name='learning'"); con.commit(); con.close()
    monkeypatch.setattr(ws.jobs, 'stopping', lambda jid: True)
    with _client(ws) as cl: out = _post(cl, 'copy').json()
    job = _wait(ws, out)
    assert job.status == 'cancelled' and job.result['cancelled'] and learn_store(ws)[1].journey('w0')


def _cited_walk(path):
    from vishalakshi import Vault
    v = Vault(str(path), offline=True)
    d = v.shelf('notebooks').add('Softmax turns scores into probabilities.\n\nIt is exp over a sum.', 'Softmax note', source='/n/softmax.md', kind='md', refresh=False)
    v.shelf('notebooks').add('Another note that no walk cites.', 'Other', source='/n/other.md', kind='md', refresh=False)
    lr = Learning(v)
    lr.put_journey(dict(id='cites', title='Cites', goal='learn', steps=[dict(slug='softmax', status='todo', read=dict(src='vault:notebooks', ref=d['doc_id'] + '#1', text='Softmax turns scores'))]))
    return d['doc_id']


def _held(ws, doc):
    from leela.blocks.memory.memory import shelf_store
    db = shelf_store(ws.vaults.memory(LEARN), 'notebooks').db
    return [db.q('select count(*) n from notebooks_docs where id=?', [doc])[0]['n'], db.q('select count(*) n from notebooks where doc_id=?', [doc])[0]['n'],
            db.q('select count(*) n from notebooks_docs')[0]['n']]


def test_the_offer_says_it_copies_the_cited_documents_too_with_the_box_on(ws, tmp_path, monkeypatch):
    src = tmp_path/'standalone.db'; _cited_walk(src); monkeypatch.setenv('ABHYASA_VAULT', str(src))
    with _client(ws) as cl: html = cl.get('/learn/import').text
    assert 'also copy the 1 document your walks cite' in html and 'name="cited"' in html and 'checked' in html


def test_copy_brings_the_documents_the_walk_cites_and_only_those(ws, tmp_path, monkeypatch):
    src = tmp_path/'standalone.db'; doc = _cited_walk(src); before = src.read_bytes(); monkeypatch.setenv('ABHYASA_VAULT', str(src))
    learn_store(ws)
    with _client(ws) as cl: out = cl.post('/vault/learn-import', data={'choice': 'copy'}, headers=_headers()).json()
    assert out['ok'] and out['cited'] == 1, out
    job = _wait(ws, out)
    assert job.status == 'complete' and src.read_bytes() == before
    assert _held(ws, doc) == [1, 1, 1]
    assert learn_store(ws)[1].journey('cites')


def test_the_box_off_copies_no_documents(ws, tmp_path, monkeypatch):
    src = tmp_path/'standalone.db'; doc = _cited_walk(src); monkeypatch.setenv('ABHYASA_VAULT', str(src))
    learn_store(ws)
    with _client(ws) as cl: out = cl.post('/vault/learn-import', data={'choice': 'copy', 'form': '1'}, headers=_headers()).json()
    assert out['ok'] and out['cited'] == 0, out
    _wait(ws, out)
    assert _held(ws, doc) == [0, 0, 0] and learn_store(ws)[1].journey('cites')


def test_a_failed_copy_of_the_cited_documents_undoes_the_whole_copy(ws, tmp_path, monkeypatch):
    from leela.blocks.vault import app as vapp
    src = tmp_path/'standalone.db'; doc = _cited_walk(src); monkeypatch.setenv('ABHYASA_VAULT', str(src))
    learn_store(ws)
    real = vapp._copy_docs
    def boom(*a): real(*a); raise RuntimeError('disk full')
    monkeypatch.setattr(vapp, '_copy_docs', boom)
    with _client(ws) as cl: out = cl.post('/vault/learn-import', data={'choice': 'copy'}, headers=_headers()).json()
    assert not out['ok'] and out['kind'] == 'copy_failed'
    assert _held(ws, doc) == [0, 0, 0] and not learn_store(ws)[1].journeys()
    assert not ws.vaults.get(LEARN).imported_from


def test_the_learn_tab_asks_for_the_offer_before_home_and_not_now_decides_nothing(ws, tmp_path, monkeypatch):
    "The tab shows the offer on mount (Attach, Back up and copy, Start empty from the route's own forms) and `Not now` only sets a page flag, so the next open asks again."
    js = (Path(__file__).parents[1]/'leela'/'blocks'/'learn'/'walk.js').read_text()
    mount = js[js.index('async function learnMount'):][:200]
    assert 'await learnOffer(host)' in mount and "fetch('/learn/import')" in js
    later = js[js.index('const go = () =>'):][:90]
    assert 'leeLearnLater = true' in later and 'fetch(' not in later
    _src(tmp_path, monkeypatch); learn_store(ws)
    with _client(ws) as cl:
        r = cl.get('/learn/import')
        assert r.status_code == 200 and all(f'value="{c}"' in r.text for c in ('attach', 'copy', 'skip'))
        assert cl.get('/learn/import').status_code == 200   # nothing was decided by looking, or by Not now
        assert _post(cl, 'skip').json()['choice'] == 'skip' and cl.get('/learn/import').status_code == 204
