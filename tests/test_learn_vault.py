import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from abhyasa.learner import Learning
from leela.app import ide_app
from leela.blocks.learn.tools import learn_store
from leela.blocks.memory.vaults import LEARN
from leela.hub import LoopbackHostGuard


def _walk(path, jid='old'):
    lr = Learning(str(path))
    lr.put_journey(dict(id=jid, title=jid.title(), goal='learn', steps=[]))
    return lr


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
    assert out == {'ok': True, 'vault': LEARN}
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
    assert backup.read_bytes() == before and src.read_bytes() == before
    assert learn_store(ws)[1].journey('old')


def test_second_import_does_not_duplicate(ws, tmp_path, monkeypatch):
    src = tmp_path/'standalone.db'; _walk(src)
    monkeypatch.setenv('ABHYASA_VAULT', str(src))
    learn_store(ws)
    with _client(ws) as cl:
        first = cl.post('/vault/learn-import', data={'choice': 'copy'}, headers=_headers()).json()
        second = cl.post('/vault/learn-import', data={'choice': 'copy'}, headers=_headers()).json()
    assert first['ok'], first
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
