"""What `Ctx` costs, measured rather than asserted.

Run: `uv run python tools/bench_ctx.py`. Attribute access is nanoseconds. A route handler is
milliseconds. Read the last section, which prices the access counts of a real request against
the work that request does.
"""

import statistics
import sys
import timeit
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from leela.core import Ctx  # noqa: E402
from leela.workspace import Workspace  # noqa: E402

N, REPEAT = 2_000_000, 7


def bench(label, stmt, env, n=N):
    "Best-of-REPEAT ns/op. Best, not mean: the floor is the signal, the rest is scheduler noise."
    ts = timeit.repeat(stmt, globals=env, number=n, repeat=REPEAT)
    per = [t/n*1e9 for t in ts]
    return label, min(per), statistics.median(per)


def main():
    ws = Workspace(roots=[])
    full = Ctx(ws, name='bench')
    narrow = Ctx(ws, name='git', caps=('fs', 'journal'))
    ws.ai  # build the Assistant once, so the lazy row measures delegation and not construction
    env = dict(ws=ws, ctx=full, narrow=narrow, Ctx=Ctx)

    print(f'python {sys.version.split()[0]}  n={N:,}  best of {REPEAT}\n')

    rows = [
        bench('ws.fs            (today)', 'ws.fs', env),
        bench('ctx.fs           (eager capability)', 'ctx.fs', env),
        bench('narrow.fs        (eager, narrowed)', 'narrow.fs', env),
        bench('ws.ai            (today, lazy property)', 'ws.ai', env),
        bench('ctx.ai           (lazy capability)', 'ctx.ai', env),
        bench('ctx.session.tabs (session state)', 'ctx.session.tabs', env),
    ]
    w = max(len(r[0]) for r in rows)
    print(f'{"":<{w}}   {"best":>9}  {"median":>9}')
    for label, best, med in rows:
        print(f'{label:<{w}}   {best:>7.2f}ns  {med:>7.2f}ns')

    base = dict(rows_ := {r[0].split()[0]: r[1] for r in rows})  # noqa: F841
    print(f'\neager overhead : {rows_["ctx.fs"] - rows_["ws.fs"]:+.2f} ns/access')
    print(f'lazy overhead  : {rows_["ctx.ai"] - rows_["ws.ai"]:+.2f} ns/access')

    # Defining `Ctx.__getattr__` switches CPython to the hooked attribute path, so the
    # undeclared-capability message costs something even when it never fires.
    hook = Ctx.__getattr__
    del Ctx.__getattr__
    try:
        off = [bench('ctx.fs  without the hook', 'ctx.fs', env),
               bench('ctx.ai  without the hook', 'ctx.ai', env)]
    finally:
        Ctx.__getattr__ = hook
    print(f'\nerror-hook cost: eager {rows_["ctx.fs"] - off[0][1]:+.2f}ns   '
          f'lazy {rows_["ctx.ai"] - off[1][1]:+.2f}ns')

    c_full = bench('Ctx(ws)', 'Ctx(ws)', env, n=200_000)
    c_narrow = bench("Ctx(ws, caps=('fs',))", "Ctx(ws, caps=('fs','journal'))", env, n=200_000)
    print(f'\nconstruction   : full {c_full[1]:.0f}ns   narrowed {c_narrow[1]:.0f}ns')
    for nblocks in (12, 20):
        print(f'  {nblocks} blocks per workspace: {c_full[1]*nblocks/1000:.1f}µs at connect time')

    # Ten capability reads is a busy handler, and the request also does file IO, JSON
    # encoding and template rendering.
    per_req = (rows_['ctx.fs'] - rows_['ws.fs']) * 10
    print(f'\nper request, 10 capability reads: {per_req:+.1f} ns '
          f'({per_req/1e6:+.6f} ms)')
    print('a trivial FastHTML fragment render is ~0.5-2 ms, so this is ~1e-5 of it.')

    fresh = Workspace(roots=[])
    t = timeit.timeit(lambda: Ctx(fresh, name='x'), number=1000)/1000*1e9
    print(f'\nCtx over a cold workspace: {t:.0f}ns, and _ai is '
          f'{"still None" if fresh._ai is None else "BUILT — laziness broken"}')


if __name__ == '__main__':
    main()
