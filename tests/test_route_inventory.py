"""The browser's URL surface, pinned.

`ide_app` registers ~180 routes inside one function. Moving them out into blocks is a
mechanical change with one dangerous failure mode: a route that quietly stops being
registered. Nothing else in the suite would notice -- most routes have no direct test, and
a missing one only shows up as a dead button in the browser.

So the surface itself is the fixture. `routes.txt` is the committed inventory; this
compares the live app against it and reports the difference as added/removed lines. A
route that moves between modules does not change the inventory, which is the point: the
whole extraction should run green from start to finish.

When a route is added or removed *on purpose*, regenerate:

    python -m tests.test_route_inventory

and commit the diff alongside the change, where it is reviewable.
"""

from pathlib import Path

from leela.app import ide_app
from leela.workspace import Workspace

INVENTORY = Path(__file__).parent/'routes.txt'

# Mount and WebSocketRoute carry no `methods`; they are still part of the surface, so they
# are recorded with their type instead. Everything else is `METHOD,METHOD PATH`.
def _row(r):
    path = getattr(r, 'path', '')
    ms = sorted(getattr(r, 'methods', None) or [])
    # HEAD is added by Starlette wherever GET is, and OPTIONS by any CORS layer. Neither is
    # a decision leela makes, so neither belongs in a fixture that exists to catch
    # accidental deletions.
    ms = [m for m in ms if m not in ('HEAD', 'OPTIONS')]
    return f"{','.join(ms) or type(r).__name__} {path}"


def inventory(app=None):
    "Every registered route as a sorted list of `METHODS PATH` lines."
    app = app or ide_app(Workspace(roots=[]))
    return sorted(_row(r) for r in app.router.routes)


def test_the_browser_url_surface_is_unchanged():
    have = inventory()
    want = [l for l in INVENTORY.read_text().splitlines() if l.strip()]
    gone, new = sorted(set(want) - set(have)), sorted(set(have) - set(want))
    assert not gone, ('routes disappeared from the app:\n  ' + '\n  '.join(gone) +
                      '\n\nIf this is deliberate, regenerate: python -m tests.test_route_inventory')
    assert not new, ('routes appeared that are not in the inventory:\n  ' + '\n  '.join(new) +
                     '\n\nIf this is deliberate, regenerate: python -m tests.test_route_inventory')


def test_every_route_is_registered_once():
    "A block registering a path a second time silently shadows the first one."
    rows = inventory()
    dupes = sorted({r for r in rows if rows.count(r) > 1})
    assert not dupes, 'the same method+path is registered twice:\n  ' + '\n  '.join(dupes)


if __name__ == '__main__':
    INVENTORY.write_text('\n'.join(inventory()) + '\n')
    print(f'wrote {INVENTORY} ({len(inventory())} routes)')
