import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent/'tools'))
import importlib.util, pytest
import s2_native_pilot as P

def _from_worktree(): return P.ABHYASA.is_dir() and (s := importlib.util.find_spec('abhyasa')) and Path(s.origin).resolve().is_relative_to(P.ABHYASA.resolve())

@pytest.mark.skipif(not _from_worktree(), reason='the pilot needs abhyasa from the sibling abhyasa-native-learn worktree, which is absent or not the abhyasa that is imported')
def test_walk_runs_as_a_stoppable_ctx_jobs_job_on_the_assistants_oneshot():
    P.setup()
    from abhyasa.learner import JobStopped
    from abhyasa.models import Withheld
    from ramabana.agent import Agent
    from leela.blocks.agent.ai import Assistant
    from leela.blocks.vault.jobs import Jobs
    ws = P.workspace(); be = P.plan_backend(); agent = P.assistant(ws, be)
    assert isinstance(agent, Assistant) and isinstance(ws.jobs, Jobs) and type(agent).oneshot is Agent.oneshot
    lr, row = P.scenario(ws, agent, be, 'ok')
    assert row.status == 'complete' and row.result['steps'] and len(be.asked) == 1 and lr.journeys()
    assert ws.jobs.get(row.id).kind == P.KIND and row.cancellable
    for kind in ('before', 'during'):
        lr, row = P.scenario(ws, agent, be, kind)
        assert row.status == 'cancelled' and not lr.journeys(), kind
        assert len(be.asked) == (kind == 'during'), 'Stop before the first call sends nothing; Stop inside it is caught before the walk commits'
    lr, row = P.scenario(ws, agent, be, 'withheld')
    assert row.status == 'error' and not be.asked and not lr.journeys() and 'jane.doe' not in row.error
