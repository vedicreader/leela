"The walk and the app rig that the /learn tests share."
import sys
import pytest
from starlette.testclient import TestClient
from abhyasa.learner import Learning
from leela.app import ide_app
from leela.blocks.memory.memory import Memory
from leela.workspace import Workspace

__all__ = ['JID', 'NB_JID', 'walk', 'nb_walk', 'rig']

JID, NB_JID = 'attention-ab12', 'comic-ab12'

def walk(lr):
    lr.put('Softmax'); lr.put('Attention')
    steps = [dict(slug='softmax', status='todo', read=dict(section='2 Background', text='Softmax maps scores to weights.'),
                  note='Watch the sum.', check=dict(kind='short', way='words')),
             dict(slug='attention', status='todo', read=dict(section='', text='<script>x()</script> Attention mixes values.'),
                  note='', check=dict(kind='short', way='words'), leela=True)]
    return lr.put_journey(dict(id=JID, title='Attention', goal='', steps=steps, mode='walk', tool=True))

def nb_walk(lr, requires=('torch', 'diffusers'), demo=''):
    "A one-step walk whose step runs in Leela: a passage with one more from the web, and the notebook spec `nb`."
    lr.put('Caption')
    nb = dict(task='Write `caption(ep)`. It gives the summary of one episode.', fname='caption', stub='def caption(ep):\n    ...',
              tests=[dict(test="assert caption({'desc': 'a'}) == 'a'", say='one episode', shown=True)], **(dict(requires=list(requires)) if requires else {}),
              data=[dict(name='EPISODES', path='~/data/episodes.json', what='episodes', need=False)],
              run=dict(say='Run it on all episodes.', makes='captions.jsonl', minutes=2, predict='How many episodes have no place?'), demo=demo)
    read = dict(text='A caption is one line.', title='Comic notes', section='2 Captions', src='vault:notes',
                also=[dict(text='A caption names who acts.', src='web', site='example.org', url='https://example.org/c', title='Captions', at=1793300000)])
    steps = [dict(slug='caption', status='todo', read=read, note='Keep it short.', check=dict(kind='notebook'), nb=nb)]
    return lr.put_journey(dict(id=NB_JID, title='Comic', goal='A comic', steps=steps, mode='walk'))

@pytest.fixture
def rig(tmp_path, tmp_path_factory, monkeypatch):
    monkeypatch.setattr('leela.blocks.learn.learn.LESSONS', tmp_path_factory.mktemp('home')/'Learning'/'Leela lessons')
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable)
    monkeypatch.setattr(ws, 'memory', Memory(path=tmp_path/'vault.db', offline=True))
    lr = Learning(ws.memory._store('learning')); j = walk(lr)
    try:
        with TestClient(ide_app(ws), base_url='http://127.0.0.1:5011') as c: yield c, ws, lr, j, tmp_path
    finally: ws.shutdown_now()
