"Tests for the daemon-wide model engine broker."

from __future__ import annotations
import pytest

from leela.agent.core import ModelSpec
from leela.blocks.runtime import engines as eng
from leela.blocks.runtime.engines import EngineBroker

class FakeEngine:
    def __init__(self, **kw): self.kw, self.closed = kw, False
    def close(self): self.closed = True

class FakeChat:
    "A rishi chat class, as far as the broker can see: it knows how to build an engine."
    @classmethod
    def create_engine(cls, model_id=None, model_path=None, adapter_path=None, **kw):
        return FakeEngine(model_id=model_id, model_path=model_path, adapter_path=adapter_path, **kw)

class VlmChat(FakeChat):
    "The class a vision repo is re-dispatched to. Its loader is not the text one."
    @classmethod
    def create_engine(cls, model_id=None, model_path=None, adapter_path=None, **kw):
        return FakeEngine(model_id=model_id, vlm=True)

class DispatchingChat(FakeChat):
    "A runtime whose class picks its real class from the model, as `MlxChat.__new__` does."
    def __new__(cls, model=None, *, runtime=None, model_path=None, vlm=None, **kw):
        if cls is DispatchingChat and (vlm if vlm is not None else 'vl' in str(model or '')):
            return object.__new__(VlmChat)
        return object.__new__(cls)

class FakeBackend:
    "What `RishiBackend` looks like to the broker before it has built a chat."
    def __init__(self, spec, **kw):
        self.spec, self.kw, self.chat, self._tried = spec, dict(kw), None, False
    def _runtime_kw(self): return dict(self.kw)
    def close(self): self._tried, self.chat = True, None

def spec(model='qwen', runtime='mlx', ctx=8000): return ModelSpec(model, runtime, model, ctx=ctx)

def test_a_vision_model_is_built_by_the_class_that_will_receive_it(monkeypatch):
    """The broker asked `get_runtime('mlx')`, which cannot see the model, and built a text engine for a vision repo."""
    monkeypatch.setattr(eng, '_chat_cls', lambda runtime: DispatchingChat)
    b, be = EngineBroker(max_engines=2), FakeBackend(spec('qwen3-vl'))
    engine = b.attach(be)
    assert engine.kw.get('vlm'), 'the vision loader built it, not the runtime\'s own class'
    assert be.kw['engine'] is engine

def test_one_repo_down_two_loaders_is_two_engines(monkeypatch):
    "`vlm=False` takes a vision repo down the text loader. One key for both hands over the wrong one."
    monkeypatch.setattr(eng, '_chat_cls', lambda runtime: DispatchingChat)
    b = EngineBroker(max_engines=3)
    vis, txt = FakeBackend(spec('qwen3-vl')), FakeBackend(spec('qwen3-vl'), vlm=False)
    assert b.attach(vis) is not b.attach(txt)
    assert vis.kw['engine'].kw.get('vlm') and not txt.kw['engine'].kw.get('vlm')
    assert b.status()['live'] == 2, 'two loaders on one repo are two engines'

def test_an_idle_engine_is_evicted_before_a_new_one_loads(monkeypatch):
    "An engine holds no user state, so the ceiling is met by closing the least recently used."
    monkeypatch.setattr(eng, '_chat_cls', lambda runtime: FakeChat)
    b = EngineBroker(max_engines=1)
    first = FakeBackend(spec('a'))
    engine = b.attach(first)
    first.close()                                   # the workspace closed; the engine is now idle
    second = FakeBackend(spec('b'))
    b.attach(second)
    assert engine.closed, 'the idle engine should have been released'
    assert 'engine' not in first.kw, 'an evicted engine must not be handed out again'
    assert b.status()['live'] == 1

def test_two_chats_on_one_engine_take_turns_across_threads_and_refuse_on_one():
    """rishi 0.1.39's engine lock, as Leela relies on it. A shared-engine chat (`lend_model` → `mk_chat`, used by
    `ask_memory`) runs inside a tool call, where `ChatToolHandler` has let the engine go, so it takes the lock.
    Only a second chat stepping onto the engine *mid-stream on the turn's own thread* raises `EngineBusy`;
    Leela has no such path: its one-shots (`Workspace.ask`, titles, compaction) run from other threads or
    between sends, and other threads wait."""
    import threading, time
    from rishi.litert import EngineBusy, _Hold
    class Chat:
        def __init__(self, e): self.engine = e
    e = FakeEngine(); turn, lent = Chat(e), Chat(e)
    hold = _Hold(turn); hold.take()
    with pytest.raises(EngineBusy): _Hold(lent).take()      # mid-stream, same thread: refused at once
    hold.let_go()                                            # what the tool handler does while a tool runs
    with _Hold(lent): pass                                   # `ask_memory`'s chat, inside the tool call
    hold.take(); done = []
    def other():
        with _Hold(lent): done.append(1)
    t = threading.Thread(target=other, daemon=True); t.start(); time.sleep(0.05)
    assert not done, 'another thread waits its turn'
    hold.let_go(); t.join(2); assert done
