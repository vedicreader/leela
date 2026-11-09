import threading
import pytest
from leela.blocks.vault.jobs import Jobs, JobError

def _jobs(tmp_path, fn):
    j = Jobs(tmp_path/'jobs.db')
    j.register('k', fn)
    return j

def test_start_once_returns_the_active_job_with_the_same_key(tmp_path):
    go, seen = threading.Event(), []
    def run(job, report): seen.append(job.id); go.wait(5); return {}
    j = _jobs(tmp_path, run)
    a = j.start_once('k', 'goal', vault='v', also=dict(settings={'a': 1}))
    b = j.start_once('k', 'goal', vault='v', also=dict(settings={'a': 2}))
    c = j.start_once('k', 'goal', vault='w')
    go.set()
    assert a.id == b.id != c.id

def test_start_once_after_the_job_finished_starts_a_new_one(tmp_path):
    j = _jobs(tmp_path, lambda job, report: {})
    a = j.start_once('k', 'g')
    while j.get(a.id).active: threading.Event().wait(.01)
    assert j.start_once('k', 'g').id != a.id

def test_held_objects_are_taken_once_and_dropped_on_a_failed_launch(tmp_path):
    seen = []
    def run(job, report): seen.append(j.take(job.id)); return {}
    j = _jobs(tmp_path, run)
    a = j.start_once('k', 'g', held=dict(ai=1, lr=2))
    while j.get(a.id).active: threading.Event().wait(.01)
    assert seen == [dict(ai=1, lr=2)] and j.take(a.id) is None
    def boom(jid, fresh=True): raise JobError('no')
    j.launch = boom
    with pytest.raises(JobError): j.start_once('k', 'h', held=dict(x=1))
    assert not j._held
