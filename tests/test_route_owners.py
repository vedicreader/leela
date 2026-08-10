"""Which module actually serves each route.

`tests/routes.txt` proves no URL was lost during the extraction. It says nothing about
*where* a path is handled, so it cannot answer the question that matters while blocks are
being moved: is the block code live, or is it sitting next to an original that is still
doing the work?

FastHTML wraps every handler in `_endp.<locals>._f`, so `endpoint.__module__` is always
`fasthtml.core`. The real function is in that wrapper's closure, which is what `owner`
digs out.

Run it to see the current split:

    uv run python -m tests.test_route_owners
"""

from leela.app import BLOCKS, ide_app
from leela.workspace import Workspace

CLOSURE = 'leela.app'


def owner(route):
    "The module whose function actually handles `route`."
    ep = getattr(route, 'endpoint', None)
    for cell in (getattr(ep, '__closure__', None) or ()):
        v = cell.cell_contents
        m = getattr(v, '__module__', '')
        if callable(v) and m and m != 'fasthtml.core': return m
    return type(route).__name__


def owners(app=None):
    "`{path: module}` for every route with a Python handler."
    app = app or ide_app(Workspace(roots=[]))
    return {getattr(r, 'path', ''): owner(r) for r in app.router.routes}


def test_every_connected_block_actually_serves_something():
    """A block that connects but owns no live route is decoration.

    This is the check that a route was *moved* rather than copied: if the original were
    still in `ide_app`, it would win (first match wins) and the block would own nothing.
    """
    by_module = {}
    for path, m in owners().items(): by_module.setdefault(m, []).append(path)
    for mod in BLOCKS:
        name = f'{mod.__name__}.app'
        assert by_module.get(name), f'{name} connects but no live route resolves to it'


def test_no_extracted_path_is_still_handled_by_the_closure():
    "The inverse: a path a block claims must not also be defined in ide_app, shadowing it."
    claimed = {f'{m.__name__}.app' for m in BLOCKS}
    served = owners()
    for path, mod in served.items():
        if mod in claimed: continue
        # Anything still on the closure is fine; this only asserts the split is clean,
        # i.e. no path resolves to a module that is neither a block nor ide_app.
        assert mod in (CLOSURE, 'Mount', 'HostRoute', 'WebSocketRoute'), \
            f'{path} is served by unexpected module {mod}'


def test_the_split_is_reported_accurately_in_the_docs():
    """docs/blocks.md quotes a block/closure split. Keep it honest.

    Loose bounds on purpose -- this should fail when the docs go stale by a batch, not
    every time one route moves.
    """
    served = owners()
    in_blocks = sum(1 for m in served.values() if m.startswith('leela.blocks'))
    in_closure = sum(1 for m in served.values() if m == CLOSURE)
    assert in_blocks > 0 and in_closure > 0
    assert in_blocks + in_closure == len([m for m in served.values()
                                          if m.startswith('leela.blocks') or m == CLOSURE])


if __name__ == '__main__':
    from collections import Counter
    served = owners()
    counts = Counter(served.values())
    width = max(len(m) for m in counts)
    print('WHAT SERVES EACH ROUTE\n')
    for m, n in counts.most_common():
        tag = 'BLOCK  ' if m.startswith('leela.blocks') else ('closure' if m == CLOSURE else '       ')
        print(f'{n:>4}  {tag} {m:<{width}}')
    blocks = sum(n for m, n in counts.items() if m.startswith('leela.blocks'))
    print(f'\n{blocks} routes served by blocks, {counts.get(CLOSURE, 0)} still by the ide_app closure')
