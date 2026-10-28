"The walk and the app rig that the /learn tests share."
import sys
import pytest
from starlette.testclient import TestClient
import abhyasa.journey  # adds Learning.journey and Learning.put_journey
from abhyasa.store import Learning
from leela.app import ide_app
from leela.blocks.memory.memory import Memory
from leela.workspace import Workspace

__all__ = ['JID', 'walk', 'rig']

JID = 'attention-ab12'

def walk(lr):
    lr.put('Softmax'); lr.put('Attention')
    steps = [dict(slug='softmax', status='todo', read=dict(section='2 Background', text='Softmax maps scores to weights.'),
                  note='Watch the sum.', check=dict(kind='short', way='words')),
             dict(slug='attention', status='todo', read=dict(section='', text='<script>x()</script> Attention mixes values.'),
                  note='', check=dict(kind='short', way='words'), leela=True)]
    return lr.put_journey(dict(id=JID, title='Attention', goal='', steps=steps, mode='walk', tool=True))

@pytest.fixture
def rig(tmp_path, tmp_path_factory, monkeypatch):
    monkeypatch.setattr('leela.blocks.learn.learn.LESSONS', tmp_path_factory.mktemp('home')/'Learning'/'Leela lessons')
    ws = Workspace(roots=[tmp_path], approvals='auto', python=sys.executable)
    monkeypatch.setattr(ws, 'memory', Memory(path=tmp_path/'vault.db', offline=True))
    lr = Learning(ws.memory._store('learning')); j = walk(lr)
    try:
        with TestClient(ide_app(ws), base_url='http://127.0.0.1:5011') as c: yield c, ws, lr, j, tmp_path
    finally: ws.shutdown_now()
