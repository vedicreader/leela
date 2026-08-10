"""Does this implementation actually satisfy the port?

`isinstance(x, MemoryPort)` answers a narrow question: are the names present. It does not
notice a method that takes different arguments, and `runtime_checkable` Protocols
deliberately do not check signatures at all. For a swap where the alternate is a different
project by a different author, "the names are there" is not enough to act on.

So this checks three things and reports them as data rather than raising:

1. **presence** -- every member the port names exists
2. **kind** -- a member the port declares as an attribute is not a method, and vice versa;
   `Backend.ready` is a property, and a runtime that made it a method would break callers
3. **signature** -- every parameter leela actually passes at a call site is accepted, by
   name, in a way that does not depend on argument order

Signature checking is the part that earns this module. leela calls
`memory.search(query, limit=8)` and `memory.toc(doc=None, depth=3)`; an implementation
whose `search` takes `(q, n)` passes `isinstance` and fails at runtime on the first query.

Use it from a test, or from the command line once an alternate exists:

    python -m leela.conformance memory vishalakshi
"""

from __future__ import annotations

import inspect

from .core import ports

__all__ = ['PORTS', 'CALLS', 'check', 'report']

PORTS = {'memory': ports.MemoryPort, 'search': ports.SearchPort, 'runtime': ports.RuntimePort}

# The keyword arguments leela actually passes, per member. Taken from the call sites in
# leela/blocks/ and leela/agent/, not from the Protocol -- the Protocol says what may be
# called, this says what *is*, and only the second one breaks a user.
CALLS = {
    'memory': {
        'search': ('query', 'limit'), 'toc': ('doc', 'depth'), 'read': ('node_id', 'max_chars'),
        'context': ('query', 'sections', 'related', 'max_read'), 'clusters': ('limit',),
        'documents': ('limit',), 'forget': ('doc_id',), 'purge': ('ids',),
        'agent_notes': ('limit',), 'agent_states': ('limit',), 'agent_state_text': ('doc_id',),
        'exact_text': ('doc_id',), 'remember': ('doc', 'query', 'force', 'extra_meta'),
        'remember_research': ('query', 'docs', 'digest'),
        'remember_agent_note': ('title', 'text', 'previous_id'),
        'remember_agent_state': ('title', 'text', 'meta'),
    },
    'search': {
        'search': ('q', 'limit', 'regex', 'force_scan', 'mode'), 'agent_search': ('q', 'limit'),
        'similar': ('path', 'line', 'limit'),
        'peers': ('path', 'line', 'limit', 'min_count', 'max_count'),
        'clusters': ('min_count', 'max_count'), 'definitions': ('name', 'path', 'limit'),
        'usages': ('name', 'limit'), 'symbols': ('path',), 'package_api': ('package',),
        'completion_patches': ('code', 'pos', 'limit'),
        'merge_completions': ('code', 'pos', 'runtime', 'limit'),
        'sync': ('notebooks', 'graph'), 'async_sync': ('notebooks', 'graph'),
    },
    'runtime': {
        'oneshot': ('prompt', 'sp', 'max_tokens'), 'refresh': ('sp', 'tools'),
        'set_approve': ('approve',), 'restore_hist': ('hist',), 'replace_hist': ('summary', 'keep'),
    },
}


def _accepts(fn, names):
    "Parameter names `fn` can be given by keyword. `**kwargs` accepts anything."
    try: sig = inspect.signature(fn)
    except (TypeError, ValueError): return set(names)          # builtins: unknowable, assume ok
    ps = sig.parameters.values()
    if any(p.kind is p.VAR_KEYWORD for p in ps): return set(names)
    ok = {p.name for p in ps if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}
    return {n for n in names if n in ok}


def check(port, obj):
    """Compare `obj` against the named port. Returns a list of problem strings; empty is a pass.

    `obj` may be an instance or a class -- attributes declared by the port are checked with
    `hasattr` either way, which is why `Backend.ready` (a property on the class) is
    reported as an attribute rather than a missing method.
    """
    proto = PORTS.get(port)
    if proto is None: raise ValueError(f'unknown port {port!r}; known: {sorted(PORTS)}')
    problems, calls = [], CALLS.get(port, {})
    # Protocol members that are methods, as declared on the Protocol itself.
    declared_methods = {n for n in proto.__protocol_attrs__
                        if callable(getattr(proto, n, None))}

    # Checking a class rather than an instance cannot see attributes assigned in
    # `__init__` -- `Backend.spec` is real but invisible until one is built. Constructor
    # parameters count as satisfied, so a class can be checked without starting a model.
    init_params = set()
    if isinstance(obj, type):
        try: init_params = set(inspect.signature(obj.__init__).parameters)
        except (TypeError, ValueError): pass

    for name in sorted(proto.__protocol_attrs__):
        if not hasattr(obj, name):
            if name in init_params: continue
            problems.append(f'missing: {name}')
            continue
        member = getattr(obj, name)
        is_method = callable(member)
        if name in declared_methods and not is_method:
            problems.append(f'{name}: port declares a method, found {type(member).__name__}')
            continue
        if name not in declared_methods and is_method:
            problems.append(f'{name}: port declares an attribute, found a callable')
            continue
        if is_method and name in calls:
            want = calls[name]
            got = _accepts(member, want)
            if missing := [n for n in want if n not in got]:
                problems.append(f'{name}: leela passes {missing} which this does not accept')
    return problems


def report(port, obj, label=''):
    "A human-readable pass/fail block for one implementation."
    problems = check(port, obj)
    head = f'{port} <- {label or type(obj).__name__}'
    if not problems: return f'{head}: OK ({len(PORTS[port].__protocol_attrs__)} members)'
    return '\n'.join([f'{head}: {len(problems)} problem(s)'] + [f'  - {p}' for p in problems])


def _sample_args(port):
    """The cheapest real arguments each port's factory needs, for a command-line check.

    All three are constructible without touching a model or an index: `Search` opens no
    kernel, and `Backend.__init__` only records the spec -- `start()` is what would open a
    chat session. That is what makes checking an alternate a one-liner rather than a
    fixture.
    """
    if port == 'search':
        from .blocks.fs.fs import Sandbox
        return (Sandbox([]),), {}
    if port == 'runtime':
        from .agent.core import resolve
        return (resolve('gpt-mini'),), {}
    return (), {}


def _main(argv):
    from .core.providers import ProviderError, build
    if not argv or argv[0] not in PORTS:
        print(f'usage: python -m leela.conformance <{"|".join(PORTS)}> [provider]')
        return 2
    port = argv[0]
    name = argv[1] if len(argv) > 1 else None
    try:
        a, kw = _sample_args(port)
        obj = build(port, *a, override=name, **kw)
    except ProviderError as e:
        print(f'{port}: {e}')                    # the message is the point; a traceback is not
        return 2
    except Exception as e:
        print(f'{port}: could not build {name or "leela"} to check it '
              f'({type(e).__name__}: {e}); check it from a test instead')
        return 2
    print(report(port, obj, label=name))
    return 1 if check(port, obj) else 0


if __name__ == '__main__':
    import sys
    raise SystemExit(_main(sys.argv[1:]))
