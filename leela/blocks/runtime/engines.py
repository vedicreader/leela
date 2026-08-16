"""One loaded model engine per (runtime, model, engine options), shared by every workspace.

Rishi's `ChatBroker` shares an engine between processes over a socket, and gives each client a
text-only conversation. Leela's workspaces are threads of one daemon and want tools and streaming, so
this takes the contract and not the transport: one engine, many chats, the engine outliving all of
them. `RishiBackend` already accepts `engine=`; this picks which one.

`RuntimeBroker` never evicts, because a kernel holds a namespace and losing it loses work. An engine
holds weights, so an idle one is a cache entry and closing it costs a reload. A live one is kept.
"""
import inspect, os, threading, time, weakref

__all__ = ['EngineBroker', 'engine_broker', 'engine_key', 'engine_kw']

def _chat_cls(runtime):
    from rishi.core import get_runtime
    return get_runtime(runtime)

def _model_id(spec):
    from rishi.core import split_runtime
    return split_runtime(spec.model_id)[1]

def engine_kw(runtime, kw):
    """The part of a backend's runtime kwargs the engine is built from: rishi takes engine and
    conversation options through one signature, so ask `create_engine` which are its own."""
    params = set(inspect.signature(_chat_cls(runtime).create_engine).parameters)
    out = {k: v for k, v in kw.items() if k in params or k == 'backend'}   # litert takes `backend` via **kw
    out.update(kw.get('eng_kw') or {})
    return out

def engine_key(spec, kw):
    """What splits an engine. Two workspaces on one model but different context limits or
    accelerators are two engines; sharing one hands the second a build it never asked for."""
    eng = engine_kw(spec.runtime, kw)
    return (spec.runtime, _model_id(spec), tuple(sorted((k, repr(v)) for k, v in eng.items())))

class _Loaded:
    "One engine, who is using it, and when it was last handed out."
    def __init__(self, engine, key):
        self.engine, self.key, self.used = engine, key, time.time()
        self.users = weakref.WeakSet()

class EngineBroker:
    "Process ceiling across the model engines of every workspace; evicts idle engines, never a live one."
    def __init__(self, max_engines=None):
        self.max_engines = int(max_engines or os.environ.get('LEELA_MAX_ENGINES', 3))
        self.engines, self._lock = {}, threading.RLock()

    def attach(self, be):
        "Give `be` the shared engine for its model, loading it if it is the first asker."
        spec = getattr(be, 'spec', None)
        if spec is None or not getattr(spec, 'local', False): return None    # nothing to load remotely
        if getattr(be, 'chat', None) is not None: return None                # already built its own
        kw = be._runtime_kw()
        if kw.get('engine') is not None: return kw['engine']
        try: key = engine_key(spec, kw)   # an uninstalled runtime is rishi's error to raise, not ours
        except ImportError: return None
        with self._lock:
            loaded = self.engines.get(key)
            if loaded is None:
                self._make_room()
                loaded = self.engines[key] = _Loaded(self._build(spec, kw), key)
            loaded.used = time.time()
            loaded.users.add(be)
            be.kw['engine'] = loaded.engine
            return loaded.engine

    def _build(self, spec, kw):
        return _chat_cls(spec.runtime).create_engine(model_id=_model_id(spec), **engine_kw(spec.runtime, kw))

    def _live(self, loaded):
        "An engine is live while any backend holding it still has a chat on it."
        return any(getattr(b, 'chat', None) is not None for b in loaded.users)

    def _make_room(self):
        "Close idle engines until one more fits."
        while len(self.engines) >= self.max_engines:
            idle = [l for l in self.engines.values() if not self._live(l)]
            if not idle: raise RuntimeError(
                f'model engine limit reached ({self.max_engines}); close a workspace on another model '
                'or set LEELA_MAX_ENGINES to a larger value')
            self._close(min(idle, key=lambda l: l.used))

    def _close(self, loaded):
        "Release one engine, and un-tell the backends that were going to build on it."
        self.engines.pop(loaded.key, None)
        for b in list(loaded.users):
            if getattr(b, 'kw', None) is not None: b.kw.pop('engine', None)
        if (c := getattr(loaded.engine, 'close', None)): c()

    def drop(self, runtime=None):
        "Close the idle engines of `runtime` (or all of them); what a changed accelerator needs."
        with self._lock:
            for l in [l for l in self.engines.values()
                      if (runtime is None or l.key[0] == runtime) and not self._live(l)]: self._close(l)
        return self

    def status(self):
        "What is loaded, for the runtime pane."
        with self._lock:
            return {'live': len(self.engines), 'limit': self.max_engines,
                    'engines': [{'runtime': l.key[0], 'model': l.key[1], 'in_use': self._live(l),
                                 'users': len(l.users), 'idle_for': round(time.time() - l.used)}
                                for l in self.engines.values()]}

    def close(self):
        "Release every engine, live or not. For daemon shutdown."
        with self._lock:
            for l in list(self.engines.values()): self._close(l)

_BROKER = None

def engine_broker():
    "The daemon's engine broker, made on first use."
    global _BROKER
    if _BROKER is None: _BROKER = EngineBroker()
    return _BROKER
