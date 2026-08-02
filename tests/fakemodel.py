"""A model that isn't one: a scripted backend for driving the IDE in tests and screenshots.

Streaming is the one feature whose whole value is *when* things appear, so testing it
against a blocking fake would test nothing. `ScriptedBackend` emits tokens with a delay
between them and calls its tools for real, which is enough to make both frontends behave
exactly as they do against a live model -- and enough for a screenshot taken mid-turn to
show a turn that is genuinely mid-flight rather than a mock-up of one.

Not in `conftest.py` because the screenshot scripts import it too, and a conftest is not
importable from outside its own directory.
"""

from __future__ import annotations
import time

from leela.agent.backend import Backend, Usage
from leela.agent.models import ModelSpec

__all__ = ['SPEC', 'ScriptedBackend', 'Step', 'install']

SPEC = ModelSpec('scripted', 'scripted', 'scripted/model', ctx=8000)


class Step:
    """One thing the scripted model does: call a tool, or say something.

    `tool` is a `(name, kwargs)` pair and is called through the agent's real tool list, so
    the activity feed, the approval gate and the file snapshots all run for real -- the
    only fiction is which tool the model decided to call.
    """

    def __init__(self, text='', tool=None, pause=0.0):
        self.text, self.tool, self.pause = text, tool, pause


class ScriptedBackend(Backend):
    """Plays a list of `Step`s, streaming its words one at a time.

    `token_delay` is what makes a screenshot possible: with it at zero the turn finishes
    before the first repaint and every capture shows a completed answer, which is the one
    thing a streaming screenshot must not show.
    """

    kind = 'scripted'

    def __init__(self, spec=SPEC, steps=(), token_delay=0.02, **kw):
        super().__init__(spec, **kw)
        self.steps, self.token_delay = list(steps), token_delay
        self.hist_, self.sent = [], []

    def _start(self): return self
    def _close(self): pass
    def _oneshot(self, prompt, sp, max_tokens): return 'a one-shot answer'
    def _usage(self): return Usage(model=self.spec.model_id, input=1840, output=96, total=1936,
                                   cached=1200, cost=0.0031, turns=1)

    @property
    def hist(self): return self.hist_

    def _replace_hist(self, summary, keep): self.hist_ = [{'role': 'user', 'content': summary}] + list(keep)

    def spawn(self, sp='', tools=(), **kw):
        return ScriptedBackend(self.spec, steps=[Step(text='three places, all in leela/agent/')],
                               token_delay=0, shared=True)

    def _tool(self, name):
        return next((t for t in self.tools if getattr(t, '__name__', '') == name), None)

    def _run(self, msg):
        "Walk the script, calling tools for real and yielding the words of every text step."
        self.sent.append(msg)
        self.hist_.append({'role': 'user', 'content': str(msg)})
        for s in self.steps:
            if s.pause: time.sleep(s.pause)
            if s.tool:
                name, kw = s.tool
                if (f := self._tool(name)) is not None:
                    self.hist_.append({'role': 'assistant', 'content': f'[{name}]'})
                    self.hist_.append({'role': 'tool', 'content': str(f(**kw))[:400]})
            for w in s.text.split(' '):
                if not w: continue
                if self.token_delay: time.sleep(self.token_delay)
                yield w + ' '

    def _send(self, msg, **kw):
        out = ''.join(self._run(msg))
        self.hist_.append({'role': 'assistant', 'content': out})
        return out

    def _stream(self, msg, **kw):
        out = []
        for w in self._run(msg):
            out.append(w)
            yield w
        self.hist_.append({'role': 'assistant', 'content': ''.join(out)})


def install(ws, steps, token_delay=0.02):
    """Point every job on `ws`'s agent at one `ScriptedBackend`, and hand it back.

    The routing table is pointed at it too, so every surface that names the model -- the
    status line, `/model`, the trail modal -- says the same thing. Leaving them disagreeing
    would make a screenshot lie about which model answered.
    """
    a = ws.ai
    be = ScriptedBackend(steps=steps, token_delay=token_delay)
    be.tools = a.tools
    a.routing.turn = SPEC.name
    a.routing._cache[SPEC.name] = SPEC
    for j in a.routing.policy: a.routing.policy[j] = SPEC.name
    a._be = lambda job='turn': be
    a._be_or_none = lambda job='turn': be
    return be
