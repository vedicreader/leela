"One loaded model engine per (runtime, model, chat class, engine options), shared by every workspace."
import inspect, os, threading, time, weakref

__all__ = ['EngineBroker', 'engine_broker', 'engine_key', 'engine_kw']

#: Both moved out of `rishi.core` to rishi's own namespace in 0.1.32. `rishi.core` still carries
#: `resolve_runtime`, which raises where these two answer, so the import is the whole change.
def _chat_cls(runtime):
    from rishi import get_runtime
    return get_runtime(runtime)

def _model_id(spec):
    from rishi import split_runtime
    return split_runtime(spec.model_id)[1]

def _model_cls(spec, kw):
    "The chat class rishi will build for this model, which is not always its runtime's own."
    cls = _chat_cls(spec.runtime)
    if cls.__new__ is object.__new__: return cls   # no `__new__` of its own is nowhere to re-route
    return type(cls.__new__(cls, _model_id(spec), **kw))

def engine_kw(runtime, kw, cls=None):
    "The part of a backend's runtime kwargs the engine is built from."
    if (create := getattr(cls or _chat_cls(runtime), 'create_engine', None)) is None: return {}
    params = set(inspect.signature(create).parameters)
    out = {k: v for k, v in kw.items() if k in params or k == 'backend'}   # litert takes `backend` via **kw
    out.update(kw.get('eng_kw') or {})
    return out

def engine_key(spec, kw, cls=None):
    "What splits an engine: the runtime, the model id, the chat class, and the engine options."
    cls = cls or _model_cls(spec, kw)
    eng = engine_kw(spec.runtime, kw, cls)
    return (spec.runtime, _model_id(spec), cls.__qualname__,
            tuple(sorted((k, repr(v)) for k, v in eng.items())))

class _Loaded:
    "One engine, who is using it, and when it was last handed out."
    def __init__(self, engine, key):
        self.engine, self.key, self.used = engine, key, time.time()
        self.users = weakref.WeakSet()

class EngineBroker:
    "Process ceiling across the model engines of every workspace. Evicts idle engines, never a live one."
    def __init__(self, max_engines=None):
        self.max_engines = int(max_engines or os.environ.get('LEELA_MAX_ENGINES', 3))
        self.engines, self._cls, self._lock = {}, {}, threading.RLock()

    def attach(self, be):
        "Give `be` the shared engine for its model, loading it if it is the first asker."
        spec = getattr(be, 'spec', None)
        if spec is None or not getattr(spec, 'local', False): return None    # nothing to load remotely
        if getattr(be, 'chat', None) is not None: return None                # already built its own
        kw = be._runtime_kw()
        if kw.get('engine') is not None: return kw['engine']
        try:    # an uninstalled runtime is rishi's error to raise, not ours
            if not hasattr(_chat_cls(spec.runtime), 'create_engine'): return None  # a server; rishi dials it
            cls = self._cls_for(spec, kw)
        except ImportError: return None
        key = engine_key(spec, kw, cls)
        with self._lock:
            loaded = self.engines.get(key)
            if loaded is None:
                self._make_room()
                loaded = self.engines[key] = _Loaded(self._build(spec, kw, cls), key)
            loaded.used = time.time()
            loaded.users.add(be)
            be.kw['engine'] = loaded.engine
            return loaded.engine

    def _cls_for(self, spec, kw):
        "The chat class for one model, resolved once."
        k = (spec.runtime, _model_id(spec), repr(kw.get('model_path')), repr(kw.get('vlm')))
        if k not in self._cls: self._cls[k] = _model_cls(spec, kw)
        return self._cls[k]

    def _build(self, spec, kw, cls):
        return cls.create_engine(model_id=_model_id(spec), **engine_kw(spec.runtime, kw, cls))

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

    def _desc(self, loaded): return {'runtime': loaded.key[0], 'model': loaded.key[1]}

    def drop(self, runtime=None):
        "Close the idle engines of `runtime`, or of every runtime, and say which went."
        with self._lock:
            gone = [l for l in self.engines.values()
                    if (runtime is None or l.key[0] == runtime) and not self._live(l)]
            for l in gone: self._close(l)
        return [self._desc(l) for l in gone]

    def status(self):
        "What is loaded, for the runtime pane."
        with self._lock:
            return {'live': len(self.engines), 'limit': self.max_engines,
                    'engines': [{**self._desc(l), 'in_use': self._live(l),
                                 'users': len(l.users), 'idle_for': round(time.time() - l.used)}
                                for l in self.engines.values()]}

    def close(self):
        "Release every engine, live or not, and say which went. For daemon shutdown, and for a forced clear."
        with self._lock:
            gone = list(self.engines.values())
            for l in gone: self._close(l)
        return [self._desc(l) for l in gone]

_BROKER = None

def engine_broker():
    "The daemon's engine broker, made on first use."
    global _BROKER
    if _BROKER is None: _BROKER = EngineBroker()
    return _BROKER
