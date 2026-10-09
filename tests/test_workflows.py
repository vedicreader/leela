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
    got = fresh.recover()
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
