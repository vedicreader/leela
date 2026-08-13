"""Queued work: what a clip puts in the shelf, and what survives a restart.

Feature flows. Each test drives a whole path; the job runner is threaded, so `_finish` waits on
the row rather than on a sleep of hopeful length.
"""

import time

import pytest
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.jobs.jobs import JobError, Jobs
from leela.workspace import Workspace

SPEC = '''openapi: 3.0.0
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


@pytest.fixture
def proj(tmp_path):
    p = tmp_path/'proj'
    (p/'src').mkdir(parents=True)
    (p/'notes.md').write_text('# Notes\n\nDurable prose about recall and ranking.\n')
    (p/'minute.md').write_text('# Minute\n\nSigned by Dr Charles Babbage.\n')
    (p/'src'/'m.py').write_text('def f(x):\n    return x + 1\n')
    (p/'api.yaml').write_text(SPEC)
    return p


@pytest.fixture
def ws(proj): return Workspace(roots=[proj])


def _finish(jobs, jid, tries=120):
    for _ in range(tries):
        j = jobs.get(jid)
        if not j.active: return j
        time.sleep(0.05)
    raise AssertionError(f'job {jid} never finished: {jobs.get(jid).dict()}')


def test_a_folder_of_documents_clips_and_stays_searchable(ws, proj):
    job = _finish(ws.jobs, ws.jobs.start('clip', str(proj)).id)
    assert job.status == 'complete' and job.progress == 1.0
    assert len(job.result['files']) == 2, 'the two markdown files; .py is not a document'
    assert job.current == '2 of 2'

    assert [s['store'] for s in ws.memory.shelves()] == ['proj']
    assert ws.memory.search('recall and ranking')

    # The badge names what it looked for, and never claims more than it covers.
    pii = job.result['pii']
    assert 'titled names' in pii['covers']
    assert pii['kinds'].get('person') == 1, 'Dr Charles Babbage, from minute.md'


def test_a_codebase_clips_as_a_pointer_not_as_prose(ws, proj):
    "Kosha owns code. Copying source into the shelf would age into a snapshot of the index."
    before = ws.memory.shelves()[0]['docs'] if ws.memory.shelves() else 0
    job = _finish(ws.jobs, ws.jobs.start('clip_codebase', str(proj)).id)
    assert job.status == 'complete'
    assert job.result['types']['.py'] == 1, 'it counted the source'

    after = ws.memory.shelves()[0]['docs']
    assert after == before + 1, 'exactly one pointer document, not one per file'
    titles = [d['title'] for d in ws.memory.documents()]
    assert any(t.startswith('Codebase: ') for t in titles)
    assert not any(t == 'm.py' for t in titles), 'the source itself did not land in the shelf'


def test_a_yaml_api_spec_clips_one_section_per_operation(ws, proj):
    "ramabana's `load_spec` is JSON only, and specifications in the world are YAML."
    job = _finish(ws.jobs, ws.jobs.start('clip_api_spec', str(proj/'api.yaml')).id)
    assert job.status == 'complete', job.error
    assert job.result['title'] == 'Widgets'
    assert job.result['operations'] == 3
    assert job.result['groups'] == ['widgets']

    doc = next(d for d in ws.memory.documents() if str(d['title']).startswith('API: '))
    text = ws.memory.exact_text(doc.get('doc_id') or doc.get('id'))
    body = text if isinstance(text, str) else str(text)
    # One `##` section per operation, headed by verb and path, so an endpoint is retrievable on
    # its own. The name in the signature is fastspec's, derived from the path -- not `operationId`.
    for want in ('## GET /widgets', '## POST /widgets', '## GET /widgets/{id}', 'required: id'):
        assert want in body, f'{want} is not in the clipped spec'
    assert body.count('\n## ') == 3, 'three operations, three sections'


def test_a_restart_requeues_what_can_resume_and_fails_the_rest(tmp_path):
    """A job still marked `running` in a fresh process is not running.

    Leaving it that way is how a panel shows a spinner nothing will ever stop.
    """
    jobs = Jobs(tmp_path/'jobs.db')
    jobs.register('resumable', lambda job, report: {'ok': True})
    jobs.register('oneshot', lambda job, report: {'ok': True})

    a = jobs.new('resumable', 'x', _resume={'done': ['one']})
    b = jobs.new('oneshot', 'y')
    for j in (a, b): jobs.update(j.id, status='running')

    out = Jobs(tmp_path/'jobs.db', memory=None)
    out._handlers = dict(jobs._handlers)
    got = out.recover()
    assert got['resumed'] == [a.id] and got['failed'] == [b.id]
    assert 'restart' in out.get(b.id).error
    assert _finish(out, a.id).status == 'complete'


def test_a_failed_job_says_why_and_can_be_retried(tmp_path):
    jobs = Jobs(tmp_path/'jobs.db')
    state = {'fail': True}

    def flaky(job, report):
        if state['fail']: raise ValueError('the disk was not there')
        return {'ok': True}

    jobs.register('flaky', flaky)
    j = _finish(jobs, jobs.start('flaky').id)
    assert j.status == 'error' and 'the disk was not there' in j.error

    state['fail'] = False
    assert _finish(jobs, jobs.launch(j.id).id).status == 'complete'

    with pytest.raises(JobError): jobs.new('nosuchkind')


def test_the_progress_fragment_stops_asking_when_the_job_is_done(ws, proj):
    "The loop terminates by construction: the finished card omits the attributes."
    with TestClient(ide_app(ws)) as c:
        r = c.post('/clip', params={'target': str(proj/'notes.md'), 'origin': 'tab'})
        assert r.status_code == 200
        assert 'hx-get' in r.text.lower() and 'load delay' in r.text.lower()

        jid = ws.jobs.all()[0].id
        assert _finish(ws.jobs, jid).status == 'complete'
        done = c.get(f'/jobs/{jid}').text
        assert 'hx-get' not in done.lower(), 'a finished card must not schedule another request'
        assert 'complete' in done


def test_a_script_runs_on_a_cadence_without_a_shell(ws):
    """The general case behind the clip kinds: run a command, keep the output, no shell.

    `shlex` splits the target, so a quoted argument stays one argument and a `;` is an argument
    rather than a second command.
    """
    import sys
    job = _finish(ws.jobs, ws.jobs.start('script', f'{sys.executable} -c "print(6*7)"').id)
    assert job.status == 'complete', job.error
    assert job.result['returncode'] == 0 and '42' in job.result['stdout']
    assert job.result['argv'][-1] == 'print(6*7)', 'one argument, not three'

    bad = _finish(ws.jobs, ws.jobs.start('script', f'{sys.executable} -c "raise SystemExit(3)"').id)
    assert bad.status == 'error'
    assert 'exited 3' in bad.error
    assert bad.error.startswith('JobError: '), 'the type name appears once, as everywhere else'
