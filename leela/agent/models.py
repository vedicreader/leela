"""Which model, and — the part nobody else does — which model *for what*.

Every coding agent in the reference set switches models because a person asked: tau has
`/model`, aai-coding has a table of short names, fastllm knows every model's price and
context window. None of them decide.

leela can, because it does not have one undifferentiated chat. It already knows what kind
of question it is asking, in separate code paths: an inline completion is not a prompt
cell, and a compaction summary is not either. So the routing key is the **job**, and the
policy is a dict:

    turn        -> whatever you configured; this is the work
    completion  -> local, always. Four lines of code, fires constantly, must feel instant
    classify    -> local, always. One label out; a frontier model is pure waste
    summary     -> local by default. It reads a transcript we are already holding
    subagent    -> local by default. Fan-out burns tool results, not reasoning

Two things are deliberately *not* here. There is no classifier that reads the user's
prompt and picks a model: that spends a model call and a second of latency to save a
fraction of a cent, and makes the agent's behaviour unpredictable in a way nobody asked
for. And there is no second model catalog -- fastllm's `get_model_info` already carries
context windows, pricing and capabilities for every model it can reach, so `ModelSpec`
looks them up rather than restating them.

The local engine is loaded anyway, for completions. That is what makes routing free
rather than a trade: summaries and fan-out run on a model that is already resident, and a
laptop with no API key still gets a working agent, only slower.
"""

from __future__ import annotations
import os
from dataclasses import dataclass, field

from . import agent_err

__all__ = ['JOBS', 'LOCAL', 'CLOUD', 'MODELS', 'DEFAULT_POLICY', 'DFLT_LOCAL_CTX', 'ModelSpec',
           'Routing', 'resolve', 'model_note', 'local_ctx']

# The jobs the harness distinguishes. Adding one means adding a caller; the policy just
# falls back to `turn` for anything it has not been told about.
JOBS = ('turn', 'completion', 'classify', 'summary', 'subagent')

# Local models, run by rishi over litert on this machine. Names are rishi's own.
LOCAL = {
    'gemma-e2b': 'litert-community/gemma-4-E2B-it-litert-lm',
    'gemma-e4b': 'litert-community/gemma-4-E4B-it-litert-lm',
    'gemma-12b': 'litert-community/gemma-4-12B-it-litert-lm',
}

# Cloud models, reached by fastllm. Short names in aai-coding's style, because
# `leela --model sonnet` is what a person actually types. Any full 'vendor/model' spec
# works too, so this table never has to be complete to be useful.
CLOUD = {
    'sonnet':   'anthropic/claude-sonnet-5',
    'opus':     'anthropic/claude-opus-4-8',
    'fable':    'anthropic/claude-fable-5',
    'haiku':    'anthropic/claude-haiku-4-5',
    'gpt':      'openai/gpt-5.6-terra',
    'gpt-mini': 'openai/gpt-5.6-luna',
    'gemini':   'gemini/models/gemini-3.1-pro-preview',
    'flash':    'gemini/models/gemini-3.5-flash',
    'deepseek': 'deepseek/deepseek-v4-pro',
    'kimi':     'moonshot/kimi-k2.6',
    'glm':      'fireworks_ai/accounts/fireworks/models/glm-5p2',
}

MODELS = {**{k: ('rishi', v) for k, v in LOCAL.items()}, **{k: ('fastllm', v) for k, v in CLOUD.items()}}

# The default local model. Small on purpose: it is doing completions and summaries, and
# the whole value of routing is that this one is cheap enough to leave running.
DFLT_LOCAL = 'gemma-e2b'

# What each job runs on when nothing says otherwise. `turn` is None meaning "whatever the
# workspace was opened with", so `leela --model sonnet` moves the work and leaves the
# cheap jobs where they are.
DEFAULT_POLICY = {'turn': None, 'completion': DFLT_LOCAL, 'classify': DFLT_LOCAL,
                  'summary': DFLT_LOCAL, 'subagent': DFLT_LOCAL}

# Context windows for the local models, which are in no pricing table.
#
# These are the numbers compaction counts down from, and they were wrong in the expensive
# direction: 32k for the gemma-3n bundles, which are commonly built with a 4096-token KV
# cache. The engine then refuses the turn outright -- "input token IDs exceed the maximum
# 4096, got 5092" -- at a point where leela still believed it was at 15% of the window and
# had therefore never compacted. Under-stating the window costs an early compaction;
# over-stating it costs the turn, so these now err small.
#
# `LEELA_LOCAL_CTX` overrides them for a bundle built with a bigger cache
# (`LEELA_LOCAL_CTX=8192`, or `LEELA_LOCAL_CTX=gemma-e4b:8192,gemma-12b:32000`), and
# `RishiBackend` narrows it further if the engine will say what it really is.
_LOCAL_CTX = {'gemma-e2b': 4_096, 'gemma-e4b': 4_096, 'gemma-12b': 32_000}
DFLT_LOCAL_CTX = 4_096


def local_ctx(name, dflt=DFLT_LOCAL_CTX):
    "The context window for a local model: `$LEELA_LOCAL_CTX` if it says, else the table."
    env = (os.environ.get('LEELA_LOCAL_CTX') or '').strip()
    if env:
        if env.isdigit(): return int(env)
        for part in env.split(','):
            k, _, v = part.partition(':')
            if k.strip() == name and v.strip().isdigit(): return int(v)
    return _LOCAL_CTX.get(name, dflt)


@dataclass(frozen=True)
class ModelSpec:
    """One model, resolved: which backend runs it, what to call it, and how big it is.

    `ctx` matters more than it looks -- it is the number compaction counts down from, and
    getting it wrong in either direction is expensive. Too small and the agent compacts a
    conversation that was fine; too large and the provider refuses a turn that could have
    been saved. So it is looked up from fastllm's model info rather than guessed, and only
    falls back to a default when the model is one fastllm has never heard of.
    """
    name: str                 # what the user types
    backend: str              # 'rishi' | 'fastllm'
    model_id: str             # what the backend is given
    ctx: int = 128_000        # context window in tokens
    note: str = ''            # anything worth showing about how this was resolved

    @property
    def local(self): return self.backend == 'rishi'

    def __str__(self): return f'{self.name} ({self.model_id})'


def _cloud_ctx(model_id):
    "Context window and a note for a cloud model, from fastllm's tables; silent about failure."
    try:
        from fastllm.types import get_model_info
        v, _, m = model_id.partition('/')
        info = get_model_info(m or v, v if m else None)
        n = info.get('max_input_tokens') or info.get('max_tokens')
        if n: return int(n), ''
        return 128_000, 'context window unknown, assuming 128k'
    except Exception as e:
        return 128_000, f'context window unknown ({agent_err(e)}), assuming 128k'


def resolve(name, default_local=DFLT_LOCAL):
    """A `ModelSpec` for `name`: a short name from the tables, or any full `vendor/model` spec.

    An unknown name with a `/` in it is taken at face value and handed to fastllm, which is
    the whole reason the tables do not need to be complete. An unknown name *without* one
    is an error rather than a guess -- silently running a typo on a frontier model is the
    kind of surprise that shows up on a bill.
    """
    if not name: name = default_local
    if name in MODELS:
        backend, mid = MODELS[name]
        if backend == 'rishi': return ModelSpec(name, backend, mid, local_ctx(name))
        ctx, note = _cloud_ctx(mid)
        return ModelSpec(name, backend, mid, ctx, note)
    if '/' in name:
        ctx, note = _cloud_ctx(name)
        return ModelSpec(name, 'fastllm', name, ctx, note)
    raise KeyError(f'unknown model {name!r}; known: {", ".join(sorted(MODELS))}, or a vendor/model spec')


def model_note(spec):
    "One line about a resolved model, for a status bar."
    where = 'local' if spec.local else 'cloud'
    return f'{spec.name} · {where} · {spec.ctx//1000}k ctx' + (f' · {spec.note}' if spec.note else '')


@dataclass
class Routing:
    """Job -> model. The policy, and the one place that decides what runs where.

    `turn` is the model the user chose; everything else defaults to the local one and can
    be overridden individually, so "use flash for summaries" is a line of config and not a
    code change. Environment overrides (`LEELA_MODEL`, `LEELA_MODEL_SUMMARY`, ...) exist
    because the first thing anyone does with a routing policy is try a different one.
    """
    turn: str = None
    policy: dict = field(default_factory=lambda: dict(DEFAULT_POLICY))
    default_local: str = DFLT_LOCAL

    def __post_init__(self):
        if not self.turn: self.turn = os.environ.get('LEELA_MODEL') or self.default_local
        for job in JOBS:
            if (v := os.environ.get(f'LEELA_MODEL_{job.upper()}')): self.policy[job] = v
        self._cache = {}

    def name_for(self, job='turn'):
        "The model name `job` runs on, falling back to the turn model for jobs with no policy."
        if job == 'turn': return self.turn
        return self.policy.get(job) or self.turn

    def spec(self, job='turn'):
        "The resolved `ModelSpec` for `job`. Cached: resolving a cloud model reads fastllm's tables."
        n = self.name_for(job)
        if n not in self._cache: self._cache[n] = resolve(n, self.default_local)
        return self._cache[n]

    def set(self, name, job='turn'):
        "Point `job` at `name`, validating it first so a typo fails here rather than mid-turn."
        spec = resolve(name, self.default_local)
        if job == 'turn': self.turn = name
        else: self.policy[job] = name
        self._cache[name] = spec
        return spec

    def backends(self):
        "The distinct backend/model pairs this policy needs, so an engine is built once and shared."
        return {(s.backend, s.model_id) for s in (self.spec(j) for j in JOBS)}

    def summary(self):
        "The whole policy in one block, for `/model` with no argument."
        return '\n'.join(f'{j:11} {model_note(self.spec(j))}' for j in JOBS)
