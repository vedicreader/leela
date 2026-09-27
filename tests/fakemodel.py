"A model that isn't one: a scripted backend for driving the IDE in tests and screenshots."

from __future__ import annotations
import time

from leela.agent.runtime import Backend, Usage
from leela.agent.core import ModelSpec

__all__ = ['SPEC', 'WIDE', 'ScriptedBackend', 'Step', 'install']

SPEC = ModelSpec('scripted', 'scripted', 'scripted/model', ctx=8000)
WIDE = ModelSpec('scripted', 'scripted', 'scripted/model', ctx=128_000)   # the same model on a full window: seeds and inlined skills fit

class Step:
    "One thing the scripted model does: call a tool, or say something."
    def __init__(self, text='', tool=None, pause=0.0):
        self.text, self.tool, self.pause = text, tool, pause

class ScriptedBackend(Backend):
    "Plays a list of `Step`s, streaming its words one at a time."
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
    SUB_ANSWERS = {
        'import': 'three files: leela/agent/backend.py, models.py, fastllm_hitl.py',
        'compaction': 'leela/agent/chat.py:compact(), fired from _prepare() at the threshold',
        'shape': 'df is (200, 2); `keep` is an int',
    }
    def spawn(self, sp='', tools=(), **kw):
        answers = self.SUB_ANSWERS
        class Sub(ScriptedBackend):
            def _run(self, msg):
                q = str(msg).lower()
                hit = next((v for k, v in answers.items() if k in q), 'nothing found')
                for w in hit.split(' '): yield w + ' '
        return Sub(self.spec, token_delay=0, shared=True)
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

def install(ws, steps, token_delay=0.02, spec=SPEC):
    "Point every job on `ws`'s agent at one `ScriptedBackend`, and hand it back. `spec` sizes the window the agent budgets for."
    a = ws.ai
    ws._inline_ai = a
    be = ScriptedBackend(spec=spec, steps=steps, token_delay=token_delay)
    be.tools = a.tools
    a.routing.turn = spec.name
    a.routing._cache[spec.name] = spec
    for j in a.routing.policy: a.routing.policy[j] = spec.name
    a._be = lambda job='turn': be
    a._be_or_none = lambda job='turn': be
    return be
