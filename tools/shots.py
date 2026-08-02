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
import asyncio, os, sys
from pathlib import Path

os.environ.setdefault('TEXTUAL_ANIMATIONS', 'none')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leela.kernels import ExecOutcome, KernelPool          # noqa: E402
from leela.tui.app import IdeApp, screen_capture           # noqa: E402
from leela.workspace import Workspace                      # noqa: E402
from tests.fakemodel import Step, install                  # noqa: E402

OUT = Path(__file__).resolve().parent.parent/'docs'/'screenshots'
ROOT = Path(__file__).resolve().parent.parent


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
    ws.open(str(nbp))
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
    finally:
        nbp.unlink(missing_ok=True)

    for name, (svg, text) in shots.items():
        (OUT/f'{name}.svg').write_text(svg)
        (OUT/f'{name}.txt').write_text(text)
        print(f'{OUT/name}.svg')
    return shots


if __name__ == '__main__':
    asyncio.run(shoot())
