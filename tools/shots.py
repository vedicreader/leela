"""Capture the IDE mid-stream, for docs and for looking at.

Streaming is the one feature whose value is entirely *when* things appear, so a
screenshot of it has to be taken while a turn is genuinely in flight. That is what
`tests.fakemodel.ScriptedBackend` is for: it calls the agent's real tools and emits its
words one at a time with a delay, so the app under capture is doing exactly what it does
against a live model.

    python tools/shots.py            # writes docs/screenshots/stream-*.svg

Kernels are faked here for the same reason `tests/conftest.py` fakes them: a real
ipykernel puts a pid in the status line and three seconds on every run, and none of that
is what the picture is about.
"""

from __future__ import annotations
import asyncio, json, os, sys
from pathlib import Path

os.environ.setdefault('TEXTUAL_ANIMATIONS', 'none')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leela.kernels import ExecOutcome, KernelPool          # noqa: E402
from leela.nb import Cell, Notebook                        # noqa: E402
from leela.tui.app import IdeApp, screen_capture           # noqa: E402
from leela.workspace import Workspace                      # noqa: E402
from tests.fakemodel import Step, install                  # noqa: E402

OUT = Path(__file__).resolve().parent.parent/'docs'/'screenshots'
ROOT = Path(__file__).resolve().parent.parent


class FakeSession:
    """Just enough `AgentSession` for `inspect_python` to be offered and to answer.

    Present so the capture goes through the real tool, the real recorder and the real
    activity line — the only fiction is where the numbers come from, exactly as with the
    kernel above.
    """
    class _R:
        def __init__(self, v): self.error, self.stdout, self.result = None, '', type('V', (), {'value': v})()
    _ANS = {'df.shape': '(200, 2)', 'len(df)': '200', 'keep': '1'}

    def run(self, code, scope='overlay'):
        return self._R(self._ANS.get(code.strip(), 'None'))

    def view(self, profile='minimal'):
        V = type('V', (), {})
        def mk(n, t, v):
            o = V(); o.name, o.type, o.value = n, t, v; return o
        return [('', [mk('df', 'DataFrame', 'DataFrame [200×2]'), mk('keep', 'int', '1')])]


class FakeKernel:
    "Enough kernel to draw the IDE. Nothing here is what the screenshots are about."
    alive, base, boot_error, pid = True, 'http://127.0.0.1:8400', None, 4242
    async def execute(self, code, on_output=None, **kw): return ExecOutcome(ok=True, execution_count=1)
    async def api(self, path, params=None, timeout=None):
        if path.endswith('/rows'): return {'groups': [{'label': '', 'nodes': [
            {'name': 'ws', 'type': 'Workspace', 'value': 'Workspace(1 root)', 'shape': None,
             'is_container': True, 'is_grid': False, 'accessor': ['ws']},
            {'name': 'agent', 'type': 'Assistant', 'value': '16 tools · 6 skills', 'shape': None,
             'is_container': True, 'is_grid': False, 'accessor': ['agent']}]}]}
        return {}
    async def complete(self, *a, **kw): return []
    async def interrupt(self): pass
    async def restart(self): pass
    async def shutdown(self): pass


def fake_kernels():
    async def _get(self, key, **kw): return self.kernels.setdefault(key, FakeKernel())
    KernelPool.get = _get
    KernelPool.peek = lambda self, key: self.kernels.get(key)
    KernelPool.close_all = lambda self: asyncio.sleep(0)


# The script the fake model plays. Shaped like a real answer to a real question: look
# around, read a file, fetch a page, then say what it found. `read_url` is pointed at a
# local file so the capture never depends on a network round trip.
STEPS = [
    Step(tool=('search_code', {'query': 'Approvals'}), pause=0.35),
    Step(tool=('view_file', {'path': str(ROOT/'leela/agent/hitl.py'), 'start': 1, 'end': 30}), pause=0.35),
    Step(tool=('read_skill', {'name': 'exhash'}), pause=0.35),
    Step(text='Approval lives in `leela/agent/hitl.py`. The gate returns an `Ask` rather than a bool, '
              'which is what lets the reason a person gives travel back to the model instead of being '
              'flattened to "denied" — `Ask.__bool__` is falsy when refused, so both backends keep '
              'working while `reply()` carries the sentence. The exchange is written into this '
              'notebook as markdown cells.', pause=0.2),
]

# A second scene: the agent notices three independent questions and fans them out to
# sub-agents rather than working through them itself, then inspects live state read-only.
SUB_STEPS = [
    Step(tool=('inspect_python', {'code': 'df.shape'}), pause=0.35),
    Step(tool=('delegate_parallel', {'questions': json.dumps([
        'which files import fastllm?',
        'where is compaction triggered?',
        'what shape is df, and what is keep?'])}), pause=0.5),
    Step(text='Three answers, none of which cost you their working: fastllm is imported in '
              '`backend.py`, `models.py` and `fastllm_hitl.py`; compaction fires from '
              '`Agent._prepare` once the turn model crosses its threshold; and `df` is (200, 2). '
              'The sub-agents ran read-only against your live kernel while your cell was still going.',
         pause=0.2),
]

NB2 = """{"cells":[
 {"cell_type":"markdown","metadata":{},"source":"## three questions at once\\n\\nIndependent questions go to sub-agents, whose working is thrown away."},
 {"cell_type":"code","execution_count":2,"metadata":{},"outputs":[
   {"output_type":"stream","name":"stdout","text":"(200, 2)\\n"}],
  "source":"import pandas as pd\\ndf = pd.DataFrame({'a': range(200), 'b': range(200)})\\nprint(df.shape)"},
 {"cell_type":"markdown","metadata":{"leela":{"kind":"prompt","reply":"","calls":[]}},
  "source":"which files import fastllm, where does compaction fire, and what shape is df?"}
],"metadata":{},"nbformat":4,"nbformat_minor":5}"""

NB = """{"cells":[
 {"cell_type":"markdown","metadata":{},"source":"## how approval works\\n\\nA question for the agent, answered in the document."},
 {"cell_type":"code","execution_count":1,"metadata":{},"outputs":[
   {"output_type":"stream","name":"stdout","text":"16 tools, 6 skills\\n"}],
  "source":"from leela.workspace import Workspace\\nws = Workspace(roots=['.'])\\nprint(len(ws.ai.tools), 'tools,', len(ws.ai.skills), 'skills')"},
 {"cell_type":"markdown","metadata":{"leela":{"kind":"prompt","reply":"","calls":[]}},
  "source":"where is approval handled, and how does the reason get back to the model?"}
],"metadata":{},"nbformat":4,"nbformat_minor":5}"""


async def shoot():
    OUT.mkdir(parents=True, exist_ok=True)
    fake_kernels()
    ws = Workspace(roots=[], approvals='auto')
    ws.add_root(str(ROOT/'leela'))
    (nbp := ROOT/'leela'/'_shot.ipynb').write_text(NB)
    nbp2 = ROOT/'leela'/'_shot2.ipynb'
    ws.open(str(nbp))
    # Build the assistant with a session in hand, so the session tool group is offered.
    from leela.ai import Assistant
    ws._ai = Assistant(ws, session=FakeSession(), on_compact=ws._compacted)
    ws.approvals.host = ws._ai.host
    app = IdeApp(ws)
    shots = {}

    def snap(name, title):
        shots[name] = screen_capture(app, title)

    try:
        async with app.run_test(size=(170, 48)) as pilot:
            for _ in range(10): await pilot.pause()
            install(ws, STEPS, token_delay=0.02)
            v = app._view()
            v.focus_cell(2)                      # the prompt cell
            for _ in range(4): await pilot.pause()

            run = asyncio.create_task(app.action_run_cell())

            await asyncio.sleep(0.75)
            for _ in range(4): await pilot.pause()
            snap('stream-1-tools', 'leela — the agent working, in the notebook')

            await asyncio.sleep(0.6)
            for _ in range(4): await pilot.pause()
            snap('stream-2-more', 'leela — a skill being read')

            await asyncio.sleep(1.3)
            for _ in range(4): await pilot.pause()
            snap('stream-3-answer', 'leela — the answer streaming into the cell')

            for _ in range(60):
                await asyncio.sleep(0.1)
                await pilot.pause()
                if not ws.ai.busy: break
            for _ in range(8): await pilot.pause()
            snap('stream-4-done', 'leela — the finished cell')

            app.action_agent_tools()             # the full trail, with usage
            for _ in range(8): await pilot.pause()
            snap('stream-5-trail', 'leela — what the agent did')
            await run
            await pilot.press('escape')
            for _ in range(4): await pilot.pause()

            # -- scene two: fan-out, in a notebook of its own so the frame is not
            # three-quarters full of scene one --------------------------------
            # Loaded straight into the open view rather than through a second tab: the
            # tab machinery is not what the picture is about, and switching tabs mid-capture
            # left the old notebook on screen with the new turn's activity under it.
            nbp2.write_text(NB2)
            await v.load(Notebook.load(nbp2))
            v.focus_cell(len(v.nb) - 1)
            for _ in range(4): await pilot.pause()
            install(ws, SUB_STEPS, token_delay=0.02)
            run2 = asyncio.create_task(app.action_run_cell())

            await asyncio.sleep(1.05)
            for _ in range(4): await pilot.pause()
            snap('sub-1-fanout', 'leela — three questions fanned out to sub-agents')

            for _ in range(60):
                await asyncio.sleep(0.1)
                await pilot.pause()
                if not ws.ai.busy: break
            for _ in range(8): await pilot.pause()
            snap('sub-2-done', 'leela — the answers, without their working')
            await run2
    finally:
        nbp.unlink(missing_ok=True)
        nbp2.unlink(missing_ok=True)

    for name, (svg, text) in shots.items():
        (OUT/f'{name}.svg').write_text(svg)
        (OUT/f'{name}.txt').write_text(text)
        print(f'{OUT/name}.svg')
    return shots


if __name__ == '__main__':
    asyncio.run(shoot())
