"""Tests for failures that never raised, and for the window that made them happen.

The report these come from: a local Gemma refusing a turn with *"input token IDs exceed
the maximum number of tokens 4096, got 5092"*, and none of it reaching the IDE. Two
separate faults behind that one sentence:

- leela believed the model's window was 32k, so compaction never came near firing and the
  conversation was allowed to grow until the engine refused it;
- the refusal happened in C++, printed to a file descriptor, and returned -- so no
  exception existed for any `except` in the harness to catch, and the frontends had
  nothing to show.

Both are tested here without a model: the first is arithmetic, and the second is a fake
backend that writes to fd 2 exactly the way litert does.
"""

import os
import sys

import pytest

from leela.agent.runtime import Backend, Usage
from leela.agent.runtime import Compactor, RESERVE, threshold
from leela.agent.core import DFLT_LOCAL_CTX, env, local_ctx, resolve
from leela.agent.runtime import captured, interesting
from leela.agent.runtime import capture as native_capture


# ---- the window ------------------------------------------------------------
def test_a_small_window_is_not_swamped_by_the_reserve():
    """The 16k reserve is bigger than a 4k local model's entire context.

    `max(1, 4096 - 16384)` is 1, so every conversation is instantly "due" and the agent
    compacts two messages, forever. Capping the reserve at a quarter of the window keeps
    the idea (leave room for a reply) without inverting it.
    """
    assert threshold(4096) == 4096 - 1024
    assert threshold(200_000) == 200_000 - RESERVE      # unchanged where there is room
    assert threshold(0) is None


def test_recent_is_capped_by_the_window_too():
    """20k of "recent" on a 4k model means nothing is ever old enough to summarise.

    This is the other half of the same failure: with the whole conversation inside the
    keep-recent budget, `compact()` reports "everything is recent; nothing to compact" and
    returns -- right up to the point where the engine refuses the turn.
    """
    c = Compactor()
    assert c.budget(4096) == 2048
    assert c.budget(200_000) == c.keep_recent


def test_the_local_window_errs_small_and_can_be_overridden(monkeypatch):
    "Under-stating a window costs one early compaction; over-stating it costs the turn."
    monkeypatch.delenv('LEELA_LOCAL_CTX', raising=False)
    assert local_ctx('gemma-e2b') == 16384
    assert resolve('gemma-e2b').ctx == 16384
    assert local_ctx('something-else') == DFLT_LOCAL_CTX
    monkeypatch.setenv('LEELA_LOCAL_CTX', '8192')
    assert local_ctx('gemma-e2b') == 8192
    monkeypatch.setenv('LEELA_LOCAL_CTX', 'gemma-e4b:16384,gemma-12b:32000')
    assert local_ctx('gemma-e4b') == 16384
    assert local_ctx('gemma-e2b') == 16384, 'a per-model override must not move the others'


def test_leela_environment_names_override_legacy_ramabana_names(monkeypatch):
    monkeypatch.setenv('LEELA_MODEL', 'current')
    monkeypatch.setenv('RAMABANA_MODEL', 'legacy')
    assert env('MODEL') == 'current'
    monkeypatch.delenv('LEELA_MODEL')
    assert env('MODEL') == 'legacy'


# ---- what the engine says on its way past ----------------------------------
GEMMA = ('E0000 00:00:1234.567 llm_engine.cc:412] input token IDs exceed the maximum '
         'number of tokens 4096, got 5092\n')


def _native_write(text):
    "Write straight to fd 2, the way a C++ engine does -- around Python's sys.stderr, not through it."
    os.write(2, text.encode())


def test_a_native_complaint_is_captured_and_still_printed():
    "Captured for the IDE, and teed to where it was going, because a terminal session still wants it."
    with captured() as cap:
        _native_write(GEMMA)
    assert 'exceed the maximum number of tokens 4096' in cap.text
    assert cap.problems, 'a line saying "exceed" is a problem, not chatter'


def test_engine_chatter_is_not_reported_as_a_problem():
    "An engine that logs delegate creation on every call would otherwise bury the one line that matters."
    with captured() as cap:
        _native_write('INFO: Created TensorFlow Lite XNNPACK delegate for CPU.\n')
    assert cap.text and not cap.problems


def test_captured_output_is_deduplicated_and_trimmed():
    "A native layer will repeat itself once per token; a status bar cannot."
    assert interesting(GEMMA * 5) == [GEMMA.strip()]
    assert len(interesting('\n'.join(f'error {i}' for i in range(20)))) == 4


def test_the_descriptor_survives_an_exception_inside_the_block():
    "A broken stderr would be a far worse bug than the one this fixes."
    before = os.dup(2)
    try:
        with pytest.raises(ValueError):
            with captured():
                _native_write('something\n')
                raise ValueError('boom')
        _native_write('')                       # fd 2 is still writable
        assert sys.stderr is not None
    finally: os.close(before)


def test_an_exception_carries_what_the_engine_said():
    "So the reported failure is the engine's own words rather than a generic wrapper message."
    def boom():
        _native_write(GEMMA)
        raise RuntimeError('generate failed')
    with pytest.raises(RuntimeError) as e: native_capture(boom)
    assert 'exceed the maximum number of tokens' in getattr(e.value, 'native_output', '')


def test_capture_can_be_switched_off(monkeypatch):
    "Anything that moves a file descriptor needs a way out."
    monkeypatch.setenv('LEELA_NO_NATIVE_CAPTURE', '1')
    with captured() as cap: _native_write('x\n')
    assert cap.text == ''


# ---- and how the harness reports it ----------------------------------------
class MutteringBackend(Backend):
    "A backend that fails the way litert does: it prints, returns nothing, and raises nothing."

    kind = 'muttering'

    def __init__(self, spec, mode='empty', **kw):
        super().__init__(spec, **kw)
        self.mode = mode

    def _start(self): return self
    def _close(self): pass
    def _usage(self): return Usage(model=self.spec.model_id)

    def _mutter(self):
        "What `RishiBackend._native` does for real: keep what the engine said, and report it."
        self.last_native = GEMMA.strip()
        self.problem(f'{self.spec.name}: {GEMMA.strip()}')

    def _send(self, msg, **kw):
        self._mutter()
        return ''

    def _stream(self, msg, **kw):
        self._mutter()
        return iter(())

    def _oneshot(self, prompt, sp, max_tokens):
        self._mutter()
        raise RuntimeError('input too long')


@pytest.fixture
def muttering():
    from leela.agent.core import ModelSpec
    return MutteringBackend(ModelSpec('gemma-e2b', 'muttering', 'gemma/e2b', ctx=4096))


def test_a_silent_failure_is_reported_rather_than_shown_as_an_empty_answer(muttering):
    """The bug as the user met it: a turn that produced nothing and said nothing about it.

    A stream with no chunks used to end with a blank pane and a cheerful status line. Now
    the last thing the engine said comes out as the answer.
    """
    out = ''.join(muttering.stream('hello'))
    assert 'exceed the maximum number of tokens 4096' in out
    assert muttering.problems


def test_a_cheap_job_that_fails_still_says_so(muttering):
    """`oneshot` returns '' by contract -- completion, classification and compaction all
    need a value, not an exception -- so the failure has to be recorded somewhere else."""
    assert muttering.oneshot('summarise this') == ''
    assert any('input too long' in p for p in muttering.problems)


def test_problems_reach_the_agents_status(ws):
    "Which is what the frontends read, and what puts it on a status bar."
    from leela.agent.core import ModelSpec
    ai = ws.ai
    b = MutteringBackend(ModelSpec('gemma-e2b', 'muttering', 'gemma/e2b', ctx=4096))
    ai._backends[('muttering', 'gemma/e2b')] = b
    b.oneshot('anything')
    assert ai.problems and ai.problems[-1] in ai.status()['problems']
    ai.clear_problems()
    assert not ai.problems
