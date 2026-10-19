"Workflow jobs and the clips and judgements they store."

import pytest
import os, time
from starlette.testclient import TestClient
from leela.app import ide_app
from leela.blocks.vault.jobs import JobError, Jobs
from leela.workspace import Workspace


OPENAPI = '''openapi: 3.0.0
info: {title: Widgets, version: "2.1"}
paths:
  /widgets:
    get: {operationId: listWidgets, summary: List widgets, tags: [widgets]}
    post: {operationId: makeWidget, summary: Create a widget, tags: [widgets]}
  /widgets/{id}:
    get:
      operationId: getWidget
      summary: One widget
      tags: [widgets]
      parameters: [{name: id, in: path, required: true}]
'''

DISCOVERY = '''{"discoveryVersion": "v1", "title": "Drive", "version": "v3",
  "baseUrl": "https://www.googleapis.com/drive/v3/",
  "resources": {"files": {"methods": {
    "list": {"id": "drive.files.list", "path": "files", "httpMethod": "GET"},
    "get": {"id": "drive.files.get", "path": "files/{fileId}", "httpMethod": "GET",
            "parameters": {"fileId": {"type": "string", "required": true, "location": "path"}}}}}}}
'''

@pytest.fixture
def proj(tmp_path):
    p = tmp_path/'proj'
    (p/'src').mkdir(parents=True)
    (p/'notes.md').write_text('# Notes\n\nDurable prose about recall and ranking.\n')
    (p/'minute.md').write_text('# Minute\n\nSigned by Dr Charles Babbage.\n')
    (p/'src'/'m.py').write_text('def f(x):\n    return x + 1\n')
    (p/'api.yaml').write_text(OPENAPI)
    (p/'drive.json').write_text(DISCOVERY)
    return p

@pytest.fixture
def ws(proj): return Workspace(roots=[proj])

def _finish(jobs, jid, tries=200):
    for _ in range(tries):
        j = jobs.get(jid)
        if not j.active: return j
        time.sleep(0.05)
    raise AssertionError(f'job {jid} never finished: {jobs.get(jid).dict()}')

def _run(ws, kind, target=''): return _finish(ws.jobs, ws.jobs.start(kind, target).id)

def test_the_three_clip_kinds_each_store_the_shape_that_suits_them(ws, proj):
    "A document is prose, a codebase is a pointer, a spec is one section per operation."
    job = _run(ws, 'clip', str(proj))
    assert job.status == 'complete' and job.progress == 1.0
    assert len(job.result['files']) == 2, 'the markdown; .py and .json are not documents'
    assert 'titled names' in job.result['pii']['covers'], 'the badge never claims more'
    assert job.result['pii']['kinds'].get('person') == 1, 'Dr Charles Babbage, from minute.md'
    assert ws.memory.search('recall and ranking')
    before = ws.memory.shelves()[0]['docs']
    job = _run(ws, 'clip_codebase', str(proj))
    assert job.status == 'complete' and job.result['types']['.py'] == 1
    assert ws.memory.shelves()[0]['docs'] == before + 1, 'one pointer, not one document per file'
    titles = [d['title'] for d in ws.memory.documents()]
    assert any(t.startswith('Codebase: ') for t in titles)
    assert 'm.py' not in titles, 'the source itself did not land in the shelf'
    job = _run(ws, 'clip_api_spec', str(proj/'api.yaml'))
    assert job.status == 'complete', job.error
    assert (job.result['title'], job.result['operations']) == ('Widgets', 3)
    body = str(ws.memory.exact_text(_titled(ws, 'API: Widgets')))
    for want in ('## GET /widgets', '## POST /widgets', '## GET /widgets/{id}', 'required: id'):
        assert want in body, f'{want} is not addressable on its own'
    job = _run(ws, 'clip_api_spec', str(proj/'drive.json'))
    assert job.status == 'complete', job.error
    assert (job.result['title'], job.result['operations']) == ('Drive', 2)
    assert 'files/{fileId}' in str(ws.memory.exact_text(_titled(ws, 'API: Drive')))

def _titled(ws, prefix):
    d = next(d for d in ws.memory.documents() if str(d['title']).startswith(prefix))
    return d.get('doc_id') or d.get('id')

def test_a_job_row_survives_a_restart_a_failure_and_an_L(tmp_path):
    "What the row guarantees, without a workspace."
    from fastcore.all import L
    jobs = Jobs(tmp_path/'jobs.db')
    fails = {'now': True}
    def flaky(job, report):
        if fails['now']: raise ValueError('the disk was not there')
        return dict(results=L([dict(status='ok'), dict(status='ok')]))
    jobs.register('resumable', lambda job, report: dict(ok=True))
    jobs.register('oneshot', lambda job, report: dict(ok=True))
    jobs.register('flaky', flaky)
    a, b = jobs.new('resumable', 'x', _resume={'done': ['one']}), jobs.new('oneshot', 'y')
    for j in (a, b): jobs.update(j.id, status='running', owner=None)   # a quit left them, and their process with them
    fresh = Jobs(tmp_path/'jobs.db')
    fresh._handlers = dict(jobs._handlers)
    got = fresh.recover(delay=0)
    assert (got['resumed'], got['failed']) == ([a.id], [b.id])
    assert 'restart' in fresh.get(b.id).error
    assert _finish(fresh, a.id).status == 'complete'
    j = _finish(jobs, jobs.start('flaky').id)
    assert j.status == 'error'
    assert j.error == 'ValueError: the disk was not there', 'the type name appears once'
    fails['now'] = False
    j = _finish(jobs, jobs.launch(j.id).id)
    assert j.result['results'] == [dict(status='ok')] * 2, 'stored as rows, not as a repr'
    with pytest.raises(JobError): jobs.new('nosuchkind')


def _interrupted(path, kind='clip', **params):
    "A resumable row a quit left running, in a jobs file of its own; the process that owned it is gone."
    jobs = Jobs(path)
    jobs.register(kind, lambda job, report: None)
    job = jobs.new(kind, 'x', _resume={'done': ['one']}, **params)
    jobs.update(job.id, status='running', owner=None)
    return job

def test_a_resumed_job_waits_out_the_launch_and_runs_once_however_many_workspaces_recover_it(tmp_path):
    "Every workspace shares one jobs file and calls `recover`; a resumed clip forked a pool per core before the first paint."
    import threading
    job, ran = _interrupted(tmp_path/'jobs.db'), []
    def slow(job, report): ran.append(job.id); time.sleep(.3); return {}
    sites = [Jobs(tmp_path/'jobs.db') for _ in range(3)]
    for s in sites: s.register('clip', slow)
    for s in sites: assert s.recover(delay=.4)['resumed'] in ([job.id], [])
    assert sites[0].get(job.id).status == 'queued' and not ran, 'nothing starts before the delay'
    assert _finish(sites[0], job.id).status == 'complete'
    assert ran == [job.id], 'one claim per row'
    assert not any(t.name.startswith('leela-job') for t in threading.enumerate() if t.is_alive())

def test_a_running_job_is_left_alone_by_a_later_workspace(tmp_path):
    "Opening a folder rebuilds a workspace, and its `recover` must neither restart nor fail what this process runs."
    job = _interrupted(tmp_path/'jobs.db', kind='book')
    first = Jobs(tmp_path/'jobs.db'); gate = __import__('threading').Event()
    first.register('book', lambda job, report: gate.wait(5) and {})
    first.recover(delay=0)
    later = Jobs(tmp_path/'jobs.db'); later.register('book', lambda job, report: {})
    assert later.recover(delay=0) == dict(resumed=[], failed=[], cancelled=[])
    assert later.get(job.id).status == 'running'
    gate.set(); assert _finish(first, job.id).status == 'complete'

def _dead_pid():
    import subprocess, sys
    p = subprocess.Popen([sys.executable, '-c', 'pass']); p.wait()
    return p.pid

def test_another_processs_live_job_survives_recover_and_a_dead_ones_is_recovered(tmp_path):
    "Every folderless workspace shares `jobs/no-folder.db`; a second Leela's `recover` failed or cancelled what the first was running."
    import socket, threading
    from leela.blocks.vault.jobs import owner_alive
    db, gate, host = tmp_path/'jobs.db', threading.Event(), socket.gethostname()
    first = Jobs(db, owner=f'{host}:{os.getpid()}:first')
    second = Jobs(db, owner=f'{host}:{os.getpid()}:second')
    for j in (first, second): j.register('book', lambda job, report: gate.wait(5) and {})
    live = first.start('book', 'x')
    queued = first.new('book', 'y')            # not yet launched: owned from `new`, so not an orphan either
    dead = first.new('book', 'z', _resume={'done': []})
    first.update(dead.id, status='running', owner=f'{host}:{_dead_pid()}:gone')
    got = second.recover(delay=0)
    assert got['resumed'] == [dead.id] and not got['failed'] and not got['cancelled']
    assert first.get(live.id).status == 'running' and first.get(live.id).owner == first.owner
    assert first.get(queued.id).status == 'queued'
    assert first.get(dead.id).owner == second.owner
    gate.set()
    assert _finish(first, live.id).status == 'complete' and _finish(second, dead.id).status == 'complete'
    assert not owner_alive(None, time.time()) and owner_alive(f'{host}:{os.getpid()}:x', time.time())
    assert owner_alive('elsewhere:1:x', time.time()) and not owner_alive('elsewhere:1:x', time.time() - 999), 'another host: the beat alone'

def test_a_stale_heartbeat_is_recovered_and_the_old_run_can_no_longer_write(tmp_path):
    "A live pid with a stale beat is taken over; the original run is told to stop and its writes land nowhere."
    import threading
    db, started, gate = tmp_path/'jobs.db', threading.Event(), threading.Event()
    first, second = Jobs(db, owner='h:1:first', stale=3600), Jobs(db, owner='h:1:second', stale=3600)
    seen = {}
    def slow(job, report):
        started.set(); gate.wait(5)
        seen['stopping'] = first.stopping(job.id)
        report(current='the old run talking')
        return {}
    first.register('clip', slow); second.register('clip', lambda job, report: gate.wait(5) and {})
    jid = first.start('clip', 'x', _resume={'done': []}).id
    assert started.wait(5)
    assert second.recover(delay=0)['resumed'] == [], 'a fresh beat is a live owner'
    first.update(jid, beat_at=time.time() - 7200)
    assert second.recover(delay=0)['resumed'] == [jid]
    gate.set()
    j = _finish(second, jid)
    time.sleep(.2)
    assert seen['stopping'] and j.status == 'complete' and j.owner == second.owner and second.get(jid).current != 'the old run talking'

def test_the_heartbeat_moves_while_a_job_runs_and_stops_with_it(tmp_path):
    import threading
    gate = threading.Event()
    jobs = Jobs(tmp_path/'jobs.db', stale=0.2); jobs.register('book', lambda job, report: gate.wait(5) and {})
    jid = jobs.start('book', 'x').id
    b0 = jobs.get(jid).beat_at; time.sleep(.3)
    assert jobs.get(jid).beat_at > b0 and jobs.alive(jobs.get(jid))
    gate.set(); _finish(jobs, jid); time.sleep(.15)
    assert not [t for t in threading.enumerate() if t.name == f'leela-job-beat-{jid}']

def test_the_stale_window_comes_from_the_environment(tmp_path, monkeypatch):
    from leela.blocks.vault.jobs import STALE
    monkeypatch.setenv('LEELA_JOB_STALE', '30'); assert Jobs(tmp_path/'a.db').stale == 30
    monkeypatch.setenv('LEELA_JOB_STALE', 'soon'); assert Jobs(tmp_path/'b.db').stale == STALE
    monkeypatch.delenv('LEELA_JOB_STALE'); assert Jobs(tmp_path/'c.db', stale=5).stale == 5

def test_a_retry_claims_a_running_row_whose_owner_died(tmp_path):
    jobs = Jobs(tmp_path/'jobs.db'); jobs.register('book', lambda job, report: {})
    jid = jobs.new('book', 'x').id
    jobs.update(jid, status='running', owner=f'{__import__("socket").gethostname()}:{_dead_pid()}:gone')
    assert _finish(jobs, jobs.launch(jid).id).status == 'complete'
    live = jobs.new('book', 'y').id; jobs.update(live, status='running')
    with pytest.raises(JobError): jobs.launch(live)

def test_a_job_cancelled_before_it_resumes_never_starts(tmp_path):
    job, ran = _interrupted(tmp_path/'jobs.db', _cancel=True), []
    jobs = Jobs(tmp_path/'jobs.db'); jobs.register('clip', lambda job, report: ran.append(1))
    jobs.recover(delay=.3); jobs.cancel(job.id); time.sleep(.6)
    assert (jobs.get(job.id).status, ran) == ('cancelled', [])

def _gated_mem(started, gate):
    class Mem:
        got = []
        def clip(self, batch, **kw):
            Mem.got.append(list(map(str, batch))); started.set(); gate.wait(10)
            return [dict(doc_id=None)] * len(batch)
    return Mem

def test_a_cancel_from_another_workspace_stops_a_running_clip_started_without_the_flag(tmp_path):
    "The stop lived in one `Jobs` object's memory, so a cancel from a second workspace on the shared jobs file was lost; a clip from before `_cancel` refused it."
    import threading
    from functools import partial
    from leela.blocks.vault.clip import clip_docs
    from leela.blocks.vault.ui import job_card
    from fasthtml.common import to_xml
    (root := tmp_path/'notes').mkdir()
    for i in range(5): (root/f'n{i}.md').write_text('words')
    started, gate = threading.Event(), threading.Event()
    Mem = _gated_mem(started, gate)
    db = tmp_path/'jobs'/'no-folder.db'
    a, b = Jobs(db), Jobs(db)
    a.register('clip', lambda job, report: clip_docs(Mem(), job, report, partial(a.stopping, job.id)))
    jid = a.new('clip', str(root)).id
    assert 'data-job-cancel' in to_xml(job_card(a.get(jid))), 'a clip without `_cancel` offers cancel'
    a.launch(jid); assert started.wait(10)
    assert b.cancel(jid).cancel_at and a.stopping(jid)
    gate.set()
    j = _finish(a, jid)
    assert j.status == 'cancelled' and len(Mem.got) == 1 and len(j.result['unread']) == 4, 'stopped after the one file in flight'
    assert not a.stopping(a.launch(jid).id), 'a retry is a fresh run'
    assert _finish(a, jid).status == 'complete' and not b.stopping('no-such-job')
    with pytest.raises(JobError): b.cancel(jid)

def test_a_cancel_then_a_restart_leaves_the_clip_cancelled_not_resumed(tmp_path):
    job, ran = _interrupted(tmp_path/'jobs.db'), []
    Jobs(tmp_path/'jobs.db').cancel(job.id)
    nxt = Jobs(tmp_path/'jobs.db'); nxt.register('clip', lambda job, report: ran.append(1))
    assert nxt.recover(delay=0)['cancelled'] == [job.id]
    time.sleep(.2)
    assert (nxt.get(job.id).status, ran) == ('cancelled', [])
    from leela.blocks.vault.ui import job_card
    from fasthtml.common import to_xml
    assert '/retry' in to_xml(job_card(nxt.get(job.id))), 'a clip cancelled across a quit can still be resumed'

def test_a_cancel_from_another_workspace_lands_on_a_queued_resume(tmp_path):
    job, ran = _interrupted(tmp_path/'jobs.db'), []
    a = Jobs(tmp_path/'jobs.db'); a.register('clip', lambda job, report: ran.append(1))
    a.recover(delay=.3); Jobs(tmp_path/'jobs.db').cancel(job.id); time.sleep(.6)
    assert (a.get(job.id).status, ran) == ('cancelled', [])

def test_a_jobs_file_from_before_the_cancel_column_migrates_in_place(tmp_path):
    import json, sqlite3
    db = tmp_path/'jobs.db'
    with sqlite3.connect(db) as c:
        c.execute('''create table jobs(id text primary key, kind text, target text, params text, status text,
            progress real, current text, result text, error text, created_at real, started_at real, finished_at real)''')
        c.execute("insert into jobs values('clip-old','clip','x',?,'running',.5,'','','',1,1,null)", (json.dumps({'_resume': {'done': ['a']}}),))
    jobs, again = Jobs(db), Jobs(db)
    assert jobs.get('clip-old').cancel_at is None and jobs.get('clip-old').resumable
    assert jobs.get('clip-old').owner is None, 'a row from before owners has none'
    with sqlite3.connect(db) as c: c.execute('alter table jobs add column from_a_later_build text')
    assert jobs.get('clip-old').id == 'clip-old', 'a column this build does not know is ignored'
    assert again.cancel('clip-old').cancel_at and jobs.stopping('clip-old')
    nxt = Jobs(db); nxt.register('clip', lambda job, report: {})
    assert nxt.recover(delay=0)['cancelled'] == ['clip-old'], 'and is an orphan to the next recover'

def test_a_job_whose_pool_the_quit_reaps_stays_resumable(tmp_path):
    "Killing a clip's workers breaks its pool; recorded as an error, the next launch would not resume it."
    from kavacha.window import quitting
    jobs = Jobs(tmp_path/'jobs.db')
    def broken(job, report):
        report(params=dict(job.params, _resume={'done': ['a']}))
        quitting.set(); raise RuntimeError('A process in the process pool was terminated abruptly')
    jobs.register('clip', broken)
    try:
        jid = jobs.start('clip', 'x').id
        for _ in range(100):
            if quitting.is_set() and not [t for t in __import__('threading').enumerate() if t.name == f'leela-job-{jid}']: break
            time.sleep(.05)
        j = jobs.get(jid)
        assert (j.status, j.resumable, j.error) == ('running', True, '')
    finally: quitting.clear()
    nxt = Jobs(tmp_path/'jobs.db'); nxt.register('clip', lambda job, report: {})
    assert nxt.recover(delay=10)['resumed'] == [jid], 'the next launch resumes it'

def test_bulk_jobs_and_the_pools_they_fork_run_at_background_priority(tmp_path):
    "A resumed clip's 14 fork workers took the machine; background priority makes their CPU and disk yield."
    import os, sys, multiprocessing as mp
    if sys.platform != 'darwin': pytest.skip('macOS priority classes')
    def probe(job, report):
        q = mp.get_context('fork').SimpleQueue()
        p = mp.get_context('fork').Process(target=lambda: q.put(os.getpriority(os.PRIO_DARWIN_PROCESS, 0))); p.start(); p.join(10)
        return dict(thread=os.getpriority(os.PRIO_DARWIN_THREAD, 0), child=q.get())
    jobs = Jobs(tmp_path/'jobs.db')
    for k in ('clip', 'git_clone'): jobs.register(k, probe)
    bulk, user = (_finish(jobs, jobs.start(k).id).result for k in ('clip', 'git_clone'))
    assert (bulk['thread'], bulk['child']) == (1, 1)
    assert (user['thread'], user['child']) == (0, 0), 'what a person waits on is not throttled'


def test_a_judgement_round_trips_from_the_row_that_carried_it(ws, proj):
    "The tidy row posts `noisy` as a form string, and `keep` must not arrive as `drop`."
    with TestClient(ide_app(ws)) as c:
        ws.memory.clip([proj/'notes.md'])
        doc = (ws.memory.documents() or [{}])[0]
        did = doc.get('doc_id') or doc.get('id')
        assert 'vaulttidy' in c.get('/vault/tidy/list').text
        dropped = c.post('/vault/noisy', data=dict(doc=did, noisy='true'))
        assert dropped.status_code == 200 and 'dropped from search' in dropped.text
        assert ws.memory._open().marks(did).get('noisy') == 1
        kept = c.post('/vault/noisy', data=dict(doc=did, noisy='false'))
        assert kept.status_code == 200 and 'kept' in kept.text
        assert ws.memory._open().marks(did).get('noisy') == 0, 'keep must clear, not set'
        badge = c.get('/vault/pii/badge', params=dict(doc=did))
        assert badge.status_code == 200 and 'lee-pii' in badge.text

def test_a_folder_clip_skips_virtualenvs_dot_folders_build_output_and_tests(tmp_path):
    "A clip of a project folder walked `.aeneas-venv`'s site-packages and every test fixture into the vault; `docs/` and `examples/` are clipped."
    from leela.blocks.vault.clip import _files, acquire_one, clip_docs, clip_tree
    from leela.blocks.vault.jobs import Job
    root = tmp_path/'docs'
    for f in ('a.md', 'B.MD', 'sub/c.txt', '.notes.md', '.aeneas-venv/lib/site-packages/pkg/README.md', '.git/x.md',
              'build/b.md', 'dist/d.md', 'tests/t.md', 'test/t.md', 'node_modules/n/r.md', '__pycache__/p.md', 'sub/m.py',
              'docs/guide.md', 'sub/doc/d.rst', 'examples/ex.md', 'sub/example/e.txt'):
        (root/f).parent.mkdir(parents=True, exist_ok=True); (root/f).write_text('words')
    (root/'sub'/'venv-link').symlink_to(root/'.aeneas-venv', target_is_directory=True)
    kept = [str(root/f) for f in ('B.MD', 'a.md', 'docs/guide.md', 'examples/ex.md', 'sub/c.txt', 'sub/doc/d.rst', 'sub/example/e.txt')]
    assert [str(f) for f in _files(root)] == kept, 'a root named docs is still walked'
    lone = root/'.aeneas-venv'/'lib'/'site-packages'/'pkg'/'README.md'
    assert _files(lone) == [lone], 'a file named outright is clipped wherever it lives'
    class Mem:
        def __init__(self): self.got = []
        def clip(self, batch, **kw): self.got += map(str, batch); return [dict(doc_id=None)] * len(batch)
    m = Mem(); out = clip_tree(m, Job('clip_tree-1', 'clip_tree', str(root)), lambda **kw: None)
    assert sorted(m.got) == sorted(kept) and out['n'] == 7, 'a folder import walks as a clip does'
    reports = []
    for kind, params, fn in (('clip', {}, clip_docs), ('acquire', dict(action='clip'), acquire_one)):
        m = Mem(); stale = str(root/'build'/'b.md')
        job = Job(f'{kind}-1', kind, str(root), params=dict(params, _resume=dict(done=[kept[0], stale])))
        out = fn(m, job, lambda **kw: reports.append(kw))
        assert m.got == kept[1:] and out['n'] == 7 and out['files'] == kept[:1] + kept[1:], kind
        assert all(round(r['progress'], 6) <= 0.95 for r in reports) and reports[-1]['current'] == '7 of 7'

@pytest.mark.parametrize('url,data', [('/clip', dict(kind='clip')), ('/clip', dict(kind='clip_tree')), ('/vault/acquire', dict(action='clip'))])
def test_a_folder_clip_cancels_within_one_file_keeps_what_it_filed_and_resumes_the_rest(tmp_path, monkeypatch, url, data):
    "A folder clip had no stop: `Jobs.cancel` refused it and `clip_docs` never asked."
    import threading
    from leela.blocks.vault.clip import BATCH
    (root := tmp_path/'many').mkdir()
    for i in range(BATCH * 2 + 3): (root/f'n{i:02}.md').write_text(f'# Note {i}\n\nzqxw{i} about recall.\n')
    ws = Workspace(roots=[root])
    calls, started, gate, clip = [], threading.Event(), threading.Event(), ws.memory.clip
    def gated(batch, **kw):
        calls.append(list(map(str, batch)))
        if len(calls) == 1: started.set(); gate.wait(10)
        return clip(batch, **kw)
    monkeypatch.setattr(ws.memory, 'clip', gated)
    with TestClient(ide_app(ws)) as c:
        r = c.post(url, data=dict(data, target=str(root)))
        assert 'data-job-cancel' in r.text, 'a folder clip offers cancel'
        jid = r.text.split('id="job-', 1)[1].split('"', 1)[0]
        assert started.wait(10)
        card = c.post(f'/jobs/{jid}/cancel').text
        assert f'id="job-{jid}"' in card and 'cancelling after the files in flight' in card
        gate.set()
        j = _finish(ws.jobs, jid)
        assert j.status == 'cancelled' and j.result['cancelled'] and calls == [[str(root/'n00.md')]], 'stopped after the first file'
        assert len(j.result['unread']) == BATCH * 2 + 2 and ws.memory.search('zqxw0'), 'the batch done stays indexed'
        assert 'resume' in c.get(f'/jobs/{jid}').text and 'not clipped' in c.get(f'/jobs/{jid}').text
        assert f'id="job-{jid}"' in c.post(f'/jobs/{jid}/retry').text
        j = _finish(ws.jobs, jid)
        assert j.status == 'complete' and 'pages' not in j.params
        assert sorted(sum(calls, [])) == sorted(map(str, root.glob('*.md'))), 'the resume clips exactly the rest'
        assert c.post(f'/jobs/{jid}/cancel').json()['kind'] == 'bad_request', 'a finished clip cannot be cancelled'

def test_a_small_clip_cancelled_during_its_first_file_stops_there(tmp_path):
    "A clip of eight files or fewer was one batch, so a cancel always landed after the last file and it finished complete."
    from leela.blocks.vault.clip import clip_docs, clip_tree, BATCH
    from leela.blocks.vault.jobs import Job
    for i in range(3): (tmp_path/f'n{i}.md').write_text('words')
    for fn in (clip_docs, clip_tree):
        got = []
        class Mem:
            def clip(self, batch, **kw): got.append(list(batch)); return [{}] * len(batch)
        out = fn(Mem(), Job('clip-1', 'clip', str(tmp_path)), lambda **kw: None, lambda: bool(got))
        assert out['cancelled'] and len(got) == 1 and len(got[0]) == 1 and len(out['unread']) == 2, fn.__name__
    for i in range(3, 20): (tmp_path/f'n{i}.md').write_text('words')
    got = []
    clip_docs(Mem(), Job('clip-2', 'clip', str(tmp_path)), lambda **kw: None)
    assert [len(b) for b in got] == [1, 2, 4, BATCH, 5], 'batches grow to eight'

def test_a_clip_stopped_before_its_first_batch_files_nothing(tmp_path):
    from leela.blocks.vault.clip import clip_docs, clip_tree
    from leela.blocks.vault.jobs import Job
    (tmp_path/'a.md').write_text('words'); (tmp_path/'b.md').write_text('words')
    class Mem:
        got = []
        def clip(self, batch, **kw): self.got += batch; return []
    for fn in (clip_docs, clip_tree):
        out = fn(Mem(), Job('clip-1', 'clip', str(tmp_path)), lambda **kw: None, lambda: True)
        assert out['cancelled'] and len(out['unread']) == 2 and Mem.got == [], fn.__name__

def test_codebase_spec_and_web_acquisitions_offer_no_cancel_they_cannot_honour(ws, proj):
    with TestClient(ide_app(ws)) as c:
        r = c.post('/clip', data=dict(kind='clip_codebase', target=str(proj)))
        assert 'data-job-cancel' not in r.text
        jid = r.text.split('id="job-', 1)[1].split('"', 1)[0]
        assert not ws.jobs.get(jid).params.get('_cancel')
        _finish(ws.jobs, jid)
