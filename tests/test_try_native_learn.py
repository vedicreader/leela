"""The owner's try-it launcher: demo seed, the import offer on a copied vault, and the refusals."""
import importlib.util, os, socket
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from abhyasa.learner import Learning, temp_learning
from leela.app import ide_app
from leela.hub import LoopbackHostGuard

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('try_native_learn', ROOT/'tools'/'try_native_learn.py')
tnl = importlib.util.module_from_spec(spec); spec.loader.exec_module(tnl)
from tools.seed_learn_demo import seed, seeded


def test_seed_makes_walk_course_talk_and_attempts_over_days():
    lr, out = temp_learning(), []
    jid = seed(lr, say=out.append)
    j = lr.journey(jid)
    assert len(j.steps) == 3 and all(s['read']['text'] and s['read']['url'].startswith('https://') for s in j.steps)
    assert len(lr.courses()) == 1 and len(lr.talks()) == 1 and len(lr.talks()[0].slides) >= 4
    assert any(s['check'].get('kind') == 'demo' for s in j.steps)
    ats = lr.attempts()
    assert len(ats) >= 4 and (max(a.at for a in ats) - min(a.at for a in ats)) > 3*86400
    assert 'DEMO DATA' in out[-1]


def test_seed_twice_adds_nothing():
    lr, out = temp_learning(), []
    a = seed(lr, say=out.append)
    n = (len(lr.journeys()), len(lr.talks()), len(lr.courses()), len(lr.attempts()), len(lr.concepts()))
    b = seed(lr, say=out.append)
    assert a == b == seeded(lr) and n == (len(lr.journeys()), len(lr.talks()), len(lr.courses()), len(lr.attempts()), len(lr.concepts()))
    assert 'already' in out[-1]


def test_seed_leaves_a_vault_with_learning_alone():
    lr, out = temp_learning(), []
    lr.put_journey(dict(id='mine', title='Mine', goal='', steps=[]))
    assert seed(lr, say=out.append) is None and [j.id for j in lr.journeys()] == ['mine'] and 'own' in out[-1]


def _walk(path):
    from vishalakshi import Vault
    Learning(Vault(str(path), offline=True)).put_journey(dict(id='old', title='Old', goal='learn', steps=[]))


def test_copied_vault_is_the_standalone_vault_and_the_offer_shows(ws, tmp_path, monkeypatch):
    src, state = tmp_path/'mine.db', tmp_path/'state'
    _walk(src); before = src.read_bytes()
    monkeypatch.setenv('ABHYASA_VAULT', '/nowhere/real.db'); monkeypatch.setenv('VISHALAKSHI_VAULT', str(state/'vault'/'vault.db'))
    dest = tnl.standalone(state, src)
    assert dest == state/'standalone'/'vault.db' and dest.is_file() and os.environ['ABHYASA_VAULT'] == str(dest)
    assert src.read_bytes() == before
    with TestClient(LoopbackHostGuard(ide_app(ws)), base_url='http://127.0.0.1') as cl: r = cl.get('/learn/import')
    assert r.status_code == 200 and '1 walk' in r.text
    for c in ('attach', 'copy', 'skip'): assert f'value="{c}"' in r.text


def test_no_copy_never_keeps_an_inherited_vault_path(tmp_path, monkeypatch):
    monkeypatch.setenv('ABHYASA_VAULT', '/nowhere/real.db'); monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'v'/'vault.db'))
    assert tnl.standalone(tmp_path, None) == tmp_path/'v'/'vault.db' and os.environ['ABHYASA_VAULT'] == str(tmp_path/'v'/'vault.db')


def test_copy_takes_the_wal_files_and_refuses_to_overwrite(tmp_path):
    src = tmp_path/'a.db'
    for sfx in ('', '-wal', '-shm'): Path(f'{src}{sfx}').write_bytes(b'x'+sfx.encode())
    tnl.copy_vault(src, tmp_path/'o'/'b.db')
    assert [(tmp_path/'o'/f'b.db{s}').read_bytes() for s in ('', '-wal', '-shm')] == [b'x', b'x-wal', b'x-shm']
    with pytest.raises(SystemExit): tnl.copy_vault(src, tmp_path/'o'/'b.db')
    with pytest.raises(SystemExit): tnl.copy_vault(tmp_path/'none.db', tmp_path/'c.db')


def test_port_5001_and_a_busy_port_are_refused_and_a_free_one_is_not_5001():
    with pytest.raises(SystemExit): tnl.pick_port(5001)
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); s.listen()
        with pytest.raises(SystemExit): tnl.pick_port(s.getsockname()[1])
    assert tnl.pick_port(None) not in (None, 5001)


def test_state_folder_under_a_real_store_is_refused_before_anything_is_made():
    real = Path.home()/'.config'/'leela'/'try-native-learn-test'
    with pytest.raises(SystemExit, match='real store'): tnl.main(['--state', str(real)])
    assert not real.exists()
    with pytest.raises(SystemExit, match='real store'): tnl.main(['--state', str(Path.home()/'.vishalakshi')])


def test_check_refuses_port_5001_after_the_state_is_judged(tmp_path):
    with pytest.raises(SystemExit, match='port 5001'): tnl.check(tnl.parse(['--state', str(tmp_path), '--port', '5001']))


def test_isolated_stores_are_all_under_the_state_folder_and_none_is_real(tmp_path, monkeypatch):
    iso = tnl.load_isolate()
    for k in ('HF_HOME', 'LITESEARCH_CACHE'): monkeypatch.setenv(k, os.environ.get(k, ''))
    env = {k: Path(v) for k, v in tnl.stores(iso, tmp_path).items() if k != 'LEELA_MEMORY_OFFLINE'}
    assert all(v.is_relative_to(tmp_path) for v in env.values()) and not tnl.refused(env.values(), iso.REAL_STORES)


def test_banner_names_url_state_vault_model_and_twelve_lines_to_try():
    t = tnl.banner('http://127.0.0.1:9/', '/s', ('learn', '/s/leela/learn/vault.db'), True, True, False)
    assert 'http://127.0.0.1:9/' in t and '/s/leela/learn/vault.db' in t and 'canned replies, nothing leaves this machine' in t and 'demo data' in t
    assert len([l for l in t.split('what to try\n')[1].splitlines() if l.strip()]) == 12


from tests.test_learn_abh_research import web, _create, _gather  # noqa: F401
from tests.test_learn_abh_models import served  # noqa: F401


def test_banner_says_web_research_off_by_default_and_on_with_web():
    a = ('http://127.0.0.1:9/', '/s', ('learn', '/s/v.db'), True, True, False)
    assert 'web research: off (add --web to let the agent search the web)' in tnl.banner(*a)
    assert "web research: ON: topic words are sent to the web search through Leela's privacy guard" in tnl.banner(*a, web=True)
    assert tnl.parse(['--web']).web and not tnl.parse([]).web


def test_preview_off_agent_walk_never_touches_the_web_and_says_why(web, monkeypatch):
    s = web; s['ws'].learn_research = False
    job = _create(s, monkeypatch)
    assert job.status == 'complete' and not s['searched'] and not s['read'] and 'research' not in job.result['data']


def test_preview_off_find_a_source_says_research_is_off_in_words(web):
    s = web; s['ws'].learn_research = False
    out = _gather(s)
    assert out.passages == 0 and 'off in this preview' in out.why and not s['searched'] and not s['read']
    from leela.blocks.learn.tools import learn_web
    for f, arg in zip(learn_web(s['ws']), (('q', 3), ('https://example.org/x',))):
        with pytest.raises(LookupError, match='off in this preview'): f(*arg)


def test_web_on_the_agent_walk_searches_through_the_patched_fetcher(web, monkeypatch):
    s = web; s['ws'].learn_research = True
    job = _create(s, monkeypatch)
    assert job.status == 'complete' and s['searched'] and 'got a source' in job.result['data']['research']
