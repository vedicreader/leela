"The handoff routes read the vault the link names, else the Learn vault, else the active vault; filing writes beside the walk."
import sys, time
import pytest
from starlette.testclient import TestClient
from abhyasa.contract import vault_key
from abhyasa.learner import Learning
from leela.app import ide_app
from leela.blocks.learn.learn import Refused, handoff_memory, handoff_store, walk_memory
from leela.blocks.memory.memory import Memory, learning_store
from leela.workspace import Workspace
from learn_data import JID, walk
from test_lesson_run_filing import NB, STEP, result
from leela.blocks.nb.lesson import step_lesson

def lr_of(ws, name): return Learning(learning_store(ws.vaults.memory(name)))

@pytest.fixture
def rig2(tmp_path, tmp_path_factory, monkeypatch):
    "A workspace whose active vault holds no walk, a managed Learn vault that holds one, and an attached read-only vault with a second."
    monkeypatch.setattr('leela.blocks.learn.learn.LESSONS', tmp_path_factory.mktemp('home')/'Learning'/'Leela lessons')
    monkeypatch.delenv('ABHYASA_ADDRESS_FILE', raising=False)
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path_factory.mktemp('cfg')))
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable)
    monkeypatch.setattr(ws, 'memory', Memory(path=tmp_path/'vault.db', offline=True))
    ws.vaults.own = ws.memory
    ws.vaults.create(tmp_path/'learn'/'vault.db', name='learn', agent=True)
    walk(lr_of(ws, 'learn'))
    ws.vaults.create(tmp_path/'other'/'vault.db', name='other')
    other = lr_of(ws, 'other'); other.put('Elsewhere')
    other.put_journey(dict(id='elsewhere-ab12', title='Elsewhere', goal='', steps=[dict(slug='elsewhere', status='todo', read=dict(section='', text='Only in other.'), note='', check=dict(kind='short', way='words'))], mode='walk'))
    ws.vaults.set_access('other', 'read')
    try:
        with TestClient(ide_app(ws), base_url='http://127.0.0.1:5011') as c: yield c, ws, tmp_path
    finally: ws.shutdown_now()

def test_a_link_with_no_key_reads_the_learn_vault_not_the_active_one(rig2):
    c, ws, _ = rig2
    assert ws.vaults.active.name == 'workspace' and lr_of(ws, 'workspace').journey(JID) is None
    assert 'Softmax maps scores to weights.' in c.get(f'/learn?walk={JID}&step=0').text
    assert c.post('/learn/open', data=dict(walk=JID, step='0'), follow_redirects=False).status_code == 303

def test_a_link_keyed_to_the_learn_vault_or_an_attached_vault_reads_that_vault(rig2):
    c, ws, _ = rig2
    ref = lambda n: ws.vaults.get(n)
    assert 'Softmax maps scores' in c.get(f'/learn?walk={JID}&step=0&v={vault_key(ref("learn").path)}').text
    ok = vault_key(ref('other').path)
    assert 'Only in other.' in c.get(f'/learn?walk=elsewhere-ab12&step=0&v={ok}').text
    assert 'This walk is not in the vault at' in c.get(f'/learn?walk={JID}&step=0&v={ok}').text   # the other vault has no such walk
    assert c.post('/learn/open', data=dict(walk='elsewhere-ab12', step='0', v=ok), follow_redirects=False).status_code == 303
    assert vault_key(ws.memory.path) != ok and handoff_memory(ws, vault_key(ws.memory.path))[0] == 'workspace'

def test_an_unknown_key_gets_the_plain_refusal_and_reads_nothing(rig2, monkeypatch):
    c, ws, _ = rig2
    other = next(k for k in ('0a1b2c3d', '0a1b2c3e') if k not in {vault_key(r.path) for r in ws.vaults})
    monkeypatch.setattr('leela.blocks.learn.app.read_step', lambda *a: pytest.fail('read the store'))
    line = f'Leela uses {ws.vaults.memory("learn").path}. Start both with the same vault.'
    assert line in c.get(f'/learn?walk={JID}&v={other}').text
    assert line in c.post('/learn/open', data=dict(walk=JID, v=other)).text
    assert line in c.post('/learn/env', data=dict(walk=JID, v=other)).text
    with pytest.raises(Refused, match='Start both with the same vault'): handoff_store(ws, other)

def test_without_a_learn_vault_the_active_vault_answers(tmp_path, monkeypatch):
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable)
    monkeypatch.setattr(ws, 'memory', Memory(path=tmp_path/'vault.db', offline=True))
    try:
        assert ws.vaults.get('learn') is None
        name, lr = handoff_store(ws, '')
        assert name == 'workspace' and isinstance(lr, Learning) and handoff_memory(ws, vault_key(ws.memory.path))[0] == 'workspace'
        assert ws.vaults.get('learn') is None, 'a handoff never makes the Learn vault'
    finally: ws.shutdown_now()

def test_due_cards_come_from_the_learn_vault(rig2):
    c, ws, _ = rig2
    now = time.time()
    for name, vault in (('InLearn', 'learn'), ('InActive', 'workspace')):
        lr = lr_of(ws, vault)
        k = lr.put(name, seen=1, due=now-100, last=now-172800, stability=.5, misses=2)
        lr.record(concept=k.slug, question=f'Question for {name}', answer='a')
    assert [r['slug'] for r in c.get('/lesson/due').json()] == ['inlearn']

def test_a_result_is_filed_in_the_vault_that_holds_the_walk_and_a_read_only_vault_refuses(rig2):
    c, ws, tmp = rig2
    from leela.blocks.nb.lesson import file_result_in
    nb = step_lesson('Caption', dict(STEP, walk='elsewhere-ab12'), NB, file='e-0.ipynb'); nb.save(p := tmp/'e-0.ipynb')
    folder = tmp/'e-0.result'; folder.mkdir(); result(folder)
    assert walk_memory(ws, 'elsewhere-ab12').path == ws.vaults.memory('other').path
    with pytest.raises(Refused, match='read-only'): file_result_in(ws, p)
    assert lr_of(ws, 'other').attempts(limit=5) == []
    ws.vaults.set_access('other', 'admin')
    assert file_result_in(ws, p).startswith('Sent to your walk')
    a, = lr_of(ws, 'other').attempts(limit=5)
    assert a.kind == 'run' and lr_of(ws, 'learn').attempts(limit=5) == [] and lr_of(ws, 'workspace').attempts(limit=5) == []
    nb2 = step_lesson('Caption', dict(STEP, walk=JID), NB, file='l-0.ipynb'); nb2.save(q := tmp/'l-0.ipynb')
    f2 = tmp/'l-0.result'; f2.mkdir(); result(f2)
    assert file_result_in(ws, q).startswith('Sent to your walk')
    assert [x.kind for x in lr_of(ws, 'learn').attempts(limit=5)] == ['run']
