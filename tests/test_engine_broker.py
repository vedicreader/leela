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

class FakeBackend:
    "What `RishiBackend` looks like to the broker before it has built a chat."
    def __init__(self, spec, **kw): self.spec, self.kw, self.chat = spec, dict(kw), None
    def _runtime_kw(self): return dict(self.kw)
    def start(self): self.chat = object(); return self.chat      # a chat now holds the engine
    def close(self): self.chat = None

@pytest.fixture
def broker(monkeypatch):
    "A broker whose engines are `FakeEngine`s, so no test loads a model or needs a backend installed."
    monkeypatch.setattr(eng, '_chat_cls', lambda runtime: FakeChat)
    return EngineBroker(max_engines=2)

def spec(model='qwen', runtime='mlx', ctx=8000): return ModelSpec(model, runtime, model, ctx=ctx)

def test_two_workspaces_on_one_model_share_one_engine(broker):
    s = spec()
    a, b = FakeBackend(s), FakeBackend(s)
    assert broker.attach(a) is broker.attach(b)
    assert a.kw['engine'] is b.kw['engine']
    assert broker.status()['live'] == 1
    assert broker.status()['engines'][0]['users'] == 2

def test_a_different_build_is_a_different_engine(broker):
    "What splits an engine: the options it was built from, not just the model id."
    s = spec()
    small = FakeBackend(s, eng_kw={'max_num_tokens': 4096})
    big = FakeBackend(s, eng_kw={'max_num_tokens': 32768})
    broker.attach(small); broker.attach(big)
    assert small.kw['engine'] is not big.kw['engine']
    assert broker.status()['live'] == 2

def test_the_engine_is_built_from_the_options_that_name_it(broker):
    be = FakeBackend(spec(), adapter_path='/tmp/lora', sp='not an engine option')
    engine = broker.attach(be)
    assert engine.kw['adapter_path'] == '/tmp/lora'
    assert 'sp' not in engine.kw

def test_a_remote_model_has_no_engine_to_share(broker):
    be = FakeBackend(ModelSpec('gpt', 'remote', 'openai/gpt-5', ctx=128_000))
    assert broker.attach(be) is None
    assert 'engine' not in be.kw and broker.status()['live'] == 0

def test_a_missing_backend_is_rishis_error_to_raise(monkeypatch):
    "The broker must not be what reports an uninstalled runtime; it just has nothing to share."
    def boom(runtime): raise ImportError("The 'mlx' runtime is unavailable")
    monkeypatch.setattr(eng, '_chat_cls', boom)
    be = FakeBackend(spec())
    assert EngineBroker(max_engines=2).attach(be) is None
    assert 'engine' not in be.kw

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

def test_a_live_engine_is_never_evicted(monkeypatch):
    monkeypatch.setattr(eng, '_chat_cls', lambda runtime: FakeChat)
    b = EngineBroker(max_engines=1)
    live = FakeBackend(spec('a'))
    b.attach(live); live.start()                    # a chat is on it now
    with pytest.raises(RuntimeError, match='engine limit reached'):
        b.attach(FakeBackend(spec('b')))
    assert not live.kw['engine'].closed

def test_drop_releases_one_runtimes_engines(monkeypatch):
    "Changing the LiteRT accelerator has to take the engines built on the old one with it."
    monkeypatch.setattr(eng, '_chat_cls', lambda runtime: FakeChat)
    b = EngineBroker(max_engines=4)
    lit, mlx = FakeBackend(spec('gemma', 'litert')), FakeBackend(spec('qwen', 'mlx'))
    b.attach(lit); b.attach(mlx)
    b.drop('litert')
    assert lit.kw.get('engine') is None and mlx.kw['engine'] is not None
    assert [e['runtime'] for e in b.status()['engines']] == ['mlx']

def test_close_releases_everything(monkeypatch):
    monkeypatch.setattr(eng, '_chat_cls', lambda runtime: FakeChat)
    b = EngineBroker(max_engines=4)
    a = FakeBackend(spec('a')); b.attach(a); a.start()
    engine = a.kw['engine']
    b.close()
    assert engine.closed and b.status()['live'] == 0

def test_engine_kw_takes_only_what_builds_an_engine(monkeypatch):
    "Rishi's chats take engine and conversation options through one signature; only the first split."
    monkeypatch.setattr(eng, '_chat_cls', lambda runtime: FakeChat)
    kw = eng.engine_kw('mlx', {'adapter_path': '/tmp/a', 'sp': 'ignored', 'eng_kw': {'draft_model': 'd'}})
    assert kw == {'adapter_path': '/tmp/a', 'draft_model': 'd'}

def test_the_key_ignores_options_the_engine_is_not_built_from(monkeypatch):
    monkeypatch.setattr(eng, '_chat_cls', lambda runtime: FakeChat)
    s = spec()
    assert eng.engine_key(s, {'sp': 'one'}) == eng.engine_key(s, {'sp': 'two'})
    assert eng.engine_key(s, {'eng_kw': {'max_num_tokens': 1}}) != eng.engine_key(s, {'eng_kw': {'max_num_tokens': 2}})
