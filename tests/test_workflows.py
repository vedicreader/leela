"Workflow jobs and the clips and judgements they store."

import pytest
import time
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
    for j in (a, b): jobs.update(j.id, status='running')
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
    "A resumable row a quit left running, in a jobs file of its own."
    jobs = Jobs(path)
    jobs.register(kind, lambda job, report: None)
    job = jobs.new(kind, 'x', _resume={'done': ['one']}, **params)
    jobs.update(job.id, status='running')
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
    assert later.recover(delay=0) == dict(resumed=[], failed=[])
    assert later.get(job.id).status == 'running'
    gate.set(); assert _finish(first, job.id).status == 'complete'

def test_a_job_cancelled_before_it_resumes_never_starts(tmp_path):
    job, ran = _interrupted(tmp_path/'jobs.db', _cancel=True), []
    jobs = Jobs(tmp_path/'jobs.db'); jobs.register('clip', lambda job, report: ran.append(1))
    jobs.recover(delay=.3); jobs.cancel(job.id); time.sleep(.6)
    assert (jobs.get(job.id).status, ran) == ('cancelled', [])

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
    "A clip of a project folder walked `.aeneas-venv`'s site-packages and every test fixture into the vault."
    from leela.blocks.vault.clip import _files, acquire_one, clip_docs
    from leela.blocks.vault.jobs import Job
    root = tmp_path/'docs'
    for f in ('a.md', 'B.MD', 'sub/c.txt', '.notes.md', '.aeneas-venv/lib/site-packages/pkg/README.md', '.git/x.md',
              'build/b.md', 'dist/d.md', 'tests/t.md', 'node_modules/n/r.md', '__pycache__/p.md', 'sub/m.py'):
        (root/f).parent.mkdir(parents=True, exist_ok=True); (root/f).write_text('words')
    (root/'sub'/'venv-link').symlink_to(root/'.aeneas-venv', target_is_directory=True)
    kept = [str(root/f) for f in ('B.MD', 'a.md', 'sub/c.txt')]
    assert [str(f) for f in _files(root)] == kept, 'a root named docs is still walked'
    lone = root/'.aeneas-venv'/'lib'/'site-packages'/'pkg'/'README.md'
    assert _files(lone) == [lone], 'a file named outright is clipped wherever it lives'
    class Mem:
        def __init__(self): self.got = []
        def clip(self, batch, **kw): self.got += map(str, batch); return [dict(doc_id=None)] * len(batch)
    reports = []
    for kind, params, fn in (('clip', {}, clip_docs), ('acquire', dict(action='clip'), acquire_one)):
        m = Mem(); stale = str(root/'build'/'b.md')
        job = Job(f'{kind}-1', kind, str(root), params=dict(params, _resume=dict(done=[kept[0], stale])))
        out = fn(m, job, lambda **kw: reports.append(kw))
        assert m.got == kept[1:] and out['n'] == 3 and out['files'] == kept[:1] + kept[1:], kind
        assert all(round(r['progress'], 6) <= 0.95 for r in reports) and reports[-1]['current'] == '3 of 3'
