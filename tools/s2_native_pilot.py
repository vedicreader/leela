r"""S2 native pilot: Abhyasa's `walk_from_topic` run as a `ctx.jobs` job, on the `oneshot` of a real Leela `Assistant`.

The workspace, its `Jobs`, and the `Assistant` are Leela's own classes. The model behind the `Assistant` is a deterministic `FakeBackend` on a hosted `ModelSpec`, so no key is read and nothing leaves the machine. A live route is a separate run that needs a supplied credential and is not done here.

Run: `uv run python tools/s2_native_pilot.py [ABHYASA_PATH]`; `ABHYASA_PATH` defaults to the sibling `abhyasa-native-learn` worktree.
"""
import importlib.util, os, sys, tempfile, threading, time
from pathlib import Path
from fastcore.script import call_parse

HERE = Path(__file__).resolve().parent
ABHYASA = HERE.parent.parent/'abhyasa-native-learn'
GOAL, KIND = 'learn fractions', 's2_walk'
PLAN = r'''{"title": "Fractions", "subject": "maths", "steps": [
 {"name": "Equal parts", "statement": "A fraction names equal parts of a whole thing.", "ways": ["words"]},
 {"name": "Adding fractions", "statement": "Fractions with one denominator add by adding numerators.", "ways": ["words"]}]}'''
#: the `Jobs` status that each scenario ends in
EXPECT = dict(ok='complete', before='cancelled', during='cancelled', withheld='error')

class Stopped(BaseException):
    "Ends the walk at a safe point after the job card's Stop; `BaseException` so no `except Exception` inside the walk swallows it."

def setup(abhyasa=ABHYASA):
    "Isolate every store, then put this checkout and the Abhyasa worktree first on `sys.path`. Call it before the first import of `leela`, `abhyasa`, `ramabana` or `vishalakshi`; under pytest, `tests/conftest.py` has already isolated."
    spec = importlib.util.spec_from_file_location('leela_isolate', HERE/'isolate.py')
    iso = importlib.util.module_from_spec(spec); spec.loader.exec_module(iso)
    if 'leela' in sys.modules:
        cfg = os.environ.get('RAMABANA_CONFIG')
        if not cfg or any(Path(cfg).resolve().is_relative_to(s) for s in iso.REAL_STORES): raise RuntimeError('leela is imported and its stores are not isolated')
    else:
        if (late := {'abhyasa', 'ramabana', 'vishalakshi'} & set(sys.modules)): raise RuntimeError(f'isolate before importing {sorted(late)}')
        iso.isolate()
    sys.path[:0] = [str(HERE.parent), str(Path(abhyasa).resolve())]
    import abhyasa as ab
    if not Path(ab.__file__).resolve().is_relative_to(Path(abhyasa).resolve()): raise RuntimeError(f'abhyasa came from {ab.__file__}, not {abhyasa}')

def workspace():
    "A `Workspace` on a new temporary folder; its `jobs` is the `ctx.jobs` that `vault/app.py` registers kinds on."
    from leela.workspace import Workspace
    return Workspace(roots=[Path(tempfile.mkdtemp()).resolve()])

def plan_backend():
    "A `FakeBackend` on a hosted `ModelSpec`, so the privacy guard treats it as a model off this machine. Its `oneshot` answers `PLAN`, records each prompt in `asked`, and runs `during()` inside the call."
    from ramabana.core import ModelSpec
    from ramabana.testing import FakeBackend
    class Plan(FakeBackend):
        during = None
        def _oneshot(self, prompt, sp, max_tokens):
            self.asked.append((prompt, sp))
            if self.during: self.during()
            return PLAN
    be = Plan(ModelSpec('s2-hosted', 'claude', 'claude-s2', ctx=8000))   # `HOSTED` runtimes are claude, copilot and remote
    be.asked = []
    if be.spec.local: raise RuntimeError('the pilot spec must be a hosted model')
    return be

def assistant(ws, be):
    "A real `Assistant` on `ws` whose every job routes to `be`, the way `ramabana.testing.fake_agent` routes an `Agent`."
    from leela.blocks.agent.ai import Assistant
    a = Assistant(ws, engines=False, extensions=False, profile='full', global_skills=False)
    a._beat = None
    a.routing.turn, a.routing.policy = be.spec.name, {}
    a.routing._cache[be.spec.name] = be.spec
    a._be = a._be_or_none = lambda job='turn': be
    return a

def register(ws, agent, lr, gate=None):
    "Register the `s2_walk` kind on `ws.jobs`. Its handler passes `agent.oneshot` to `walk_from_topic` as the `ask`, behind the session guard `ws.vault_pii`, and checks `ws.jobs.stopping` before and after each call."
    from abhyasa.models import guard
    from abhyasa.path import walk_from_topic
    def prepare(p, sp, b): return guard(p, b.spec, ws.vault_pii), guard(sp, b.spec, ws.vault_pii)
    def walk_job(job, report):
        if gate: gate.wait(5)
        def ask(prompt, sp=''):
            if ws.jobs.stopping(job.id): raise Stopped()
            report(progress=.3, current='asking the model')
            out = agent.oneshot(prompt, sp, 'plan', 2048, prepare=prepare, wait=True, strict=True)
            if ws.jobs.stopping(job.id): raise Stopped()
            return out
        try: walk = walk_from_topic(lr, ask, job.target)
        except Stopped: return dict(cancelled=True)
        return dict(walk=walk.get('id'), steps=len(walk.get('steps') or []))
    ws.jobs.register(KIND, walk_job)

def settled(ws, jid, secs=10):
    "The row of `jid` once it is no longer active, or None after `secs`."
    end = time.time() + secs
    while time.time() < end:
        if not (j := ws.jobs.get(jid)).active: return j
        time.sleep(.02)

def scenario(ws, agent, be, kind):
    "Run one `ctx.jobs` job to its end: `ok`; `before` (Stop before the first call); `during` (Stop inside the first call); `withheld` (the guard refuses the goal). Return `(lr, row)`."
    from abhyasa.learner import temp_learning
    lr, gate, holder = temp_learning(), threading.Event(), []
    be.asked.clear()
    be.during = (lambda: ws.jobs.cancel(holder[0])) if kind == 'during' else None
    register(ws, agent, lr, gate)
    goal, ws.vault_pii = ('teach me for jane.doe@example.com', 'refuse') if kind == 'withheld' else (GOAL, 'redact')
    try:
        holder.append(ws.jobs.start(KIND, goal, _cancel=True).id)
        if kind == 'before': ws.jobs.cancel(holder[0])
        gate.set()
        return lr, settled(ws, holder[0])
    finally: ws.vault_pii = 'redact'

@call_parse
def main(
    abhyasa:str=str(ABHYASA),  # the Abhyasa worktree whose `walk_from_topic` runs
):
    "Isolate, build a workspace and an `Assistant`, and run the four scenarios as `ctx.jobs` jobs."
    setup(abhyasa)
    ws = workspace(); be = plan_backend(); agent = assistant(ws, be)
    print('jobs', type(ws.jobs).__module__, type(ws.jobs).__name__, 'agent', type(agent).__module__, type(agent).__name__)
    for kind, status in EXPECT.items():
        lr, row = scenario(ws, agent, be, kind)
        print(kind, row and row.status, 'calls', len(be.asked), 'journeys', len(lr.journeys()), 'result', row and row.result, 'error', row and row.error)
        assert row and row.status == status, f'{kind}: expected {status}'
