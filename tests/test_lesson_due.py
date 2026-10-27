import shutil, subprocess, time
from pathlib import Path
import pytest
from abhyasa.model import recall, understanding
from abhyasa.store import Learning
from leela.blocks.memory.memory import Memory, _open_lock
from test_lesson_run import lesson_client

ROOT = Path(__file__).parents[1]

@pytest.fixture
def due_store(lesson_client, monkeypatch, tmp_path):
    client, ws, _, _ = lesson_client
    monkeypatch.setattr(ws.memory, 'path', tmp_path/'learning.db')
    lr = Learning(ws.memory._store('learning'))
    now = time.time()
    for name, due, seen in [('Later', now-100, 1), ('Earlier', now-86400, 2), ('Future', now+86400, 1), ('Unseen', now-100, 0)]:
        c = lr.put(name, seen=seen, due=due, last=now-172800, stability=.5, misses=2)
        lr.record(concept=c.slug, question='Old question', answer='Old answer')
        lr.record(concept=c.slug, question=f'Question for {name}', answer='Saved answer', thinking='Saved thinking', actual='Saved actual')
    return client, ws, lr

def test_due_returns_latest_attempts_most_overdue_first(due_store):
    client, ws, lr = due_store
    r = client.get('/lesson/due')
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [r['slug'] for r in rows] == ['earlier', 'later']
    for row in rows:
        c = lr.concept(row['slug'])
        assert row['name'] == c.name and row['question'] == f'Question for {c.name}'
        assert (row['answer'], row['thinking'], row['actual']) == ('Saved answer', 'Saved thinking', 'Saved actual')
        assert row['why'] == f'due for review: recall about {recall(c):.0%}'
        assert row['reason'] == understanding(c).reasons[0]

def test_due_empty_and_missing_attempt(due_store):
    client, ws, lr = due_store
    for c in lr.concepts(): lr.update(c.slug, due=time.time()+86400)
    assert client.get('/lesson/due').json() == []
    lr.put('No attempt', seen=1, due=time.time()-1, last=time.time(), stability=1)
    row, = client.get('/lesson/due').json()
    assert row['slug'] == 'no-attempt'
    assert all(row[k] == '' for k in ('question', 'answer', 'thinking', 'actual', 'reason'))

def test_due_uses_learning_opener_and_read_lock(due_store, monkeypatch):
    client, ws, lr = due_store
    opened, original = [], Memory._store
    def checked(self, name):
        assert self.path.resolve().is_relative_to(ws.memory.path.parent.resolve())
        opened.append(name)
        return original(self, name)
    monkeypatch.setattr(Memory, '_store', checked)
    original_concepts = Learning.concepts
    def locked(self, *args, **kwargs):
        assert _open_lock(ws.memory.path).locked()
        return original_concepts(self, *args, **kwargs)
    monkeypatch.setattr(Learning, 'concepts', locked)
    assert client.get('/lesson/due').status_code == 200
    assert opened == ['learning']

def test_due_store_failure_can_retry(due_store, monkeypatch):
    client, _, _ = due_store
    with monkeypatch.context() as patch:
        def locked(*args): raise PermissionError('locked')
        patch.setattr(Memory, '_store', locked)
        r = client.get('/lesson/due')
        assert r.status_code == 400 and r.json()['ok'] is False
        assert 'locked or unreadable' in r.json()['error']
    assert len(client.get('/lesson/due').json()) == 2

def test_due_status_count_hidden_zero_and_refresh_contract():
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    source = ROOT/'leela/blocks/learn/review.js'
    assert source.is_file(), 'Review client has not been added'
    script = '''const vm = require('vm'), fs = require('fs'), item = {hidden: true, textContent: ''};
const ctx = {$: s => s === '#lessondue' ? item : null, api: async () => ctx.rows}; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
(async () => { ctx.rows = [{}, {}]; await ctx.refreshLessonDue();
if (item.hidden || item.textContent !== '2 due') throw Error(JSON.stringify(item));
ctx.rows = []; await ctx.refreshLessonDue();
if (!item.hidden || item.textContent !== '') throw Error(JSON.stringify(item)); })().catch(e => {console.error(e); process.exitCode=1;});'''
    r = subprocess.run([node, '-e', script, str(source)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    boot = (ROOT/'leela/static/js/boot.js').read_text()
    assert 'setInterval(whenVisible(refreshLessonDue), 600000)' in boot
    assert 'refreshLessonDue()' in (ROOT/'leela/blocks/nb/lesson.js').read_text()
