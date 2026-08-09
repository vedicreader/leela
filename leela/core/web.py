"""The web vocabulary every block shares: error shape, streaming frames, static URLs.

These were module-level helpers in `leela/web/app.py` with leading underscores, which was
right while there was one web module. Blocks need them, and a block importing a private
name out of the module it is being extracted from is not an improvement -- so they move
here and lose the underscore.

`leela/web/app.py` re-exports the old names, because `tests/` and any external caller
import some of them from there.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastcore.aio import athreaded
from fasthtml.common import JSONResponse

from .. import errstr

__all__ = ['static_dir', 'asset', 'fail', 'sse', 'off_loop', 'diff_payload', 'found']


def static_dir():
    "Web assets in a normal install, py2app Resources, or a py2exe distribution."
    import sys
    candidates = [Path(__file__).parent.parent/'web'/'static']
    if getattr(sys, 'frozen', False):
        exe = Path(sys.executable).resolve()
        candidates += [exe.parent/'leela'/'web'/'static',
                       exe.parent.parent/'Resources'/'leela'/'web'/'static']
    return next((p for p in candidates if p.exists()), candidates[0])


def asset(name):
    "A static URL that changes when the local asset does, preventing mixed JS/CSS revisions."
    p = static_dir()/name
    try: version = p.stat().st_mtime_ns
    except OSError: version = 0
    return f'/leestatic/{name}?v={version}'


def fail(err, code=400):
    "The IDE's JSON error shape. `err` is an exception (reported `Type: message`) or a ready string."
    return JSONResponse({'ok': False, 'error': errstr(err) if isinstance(err, Exception) else str(err)},
                        status_code=code)


def sse(event, data):
    "One server-sent event. Newlines in the payload would end the frame, so it goes as JSON."
    return f'event: {event}\ndata: {json.dumps(data)}\n\n'


@athreaded
def off_loop(fn, *a, **kw):
    "Run blocking research, indexing and model work on fastcore's worker thread."
    return fn(*a, **kw)


def diff_payload(was, now):
    "One text-vs-text comparison in the shape every diff surface in the client consumes."
    from ..diffs import diff_label, diff_rows, udiff
    return {'label': diff_label(was, now), 'rows': [r.dict() for r in diff_rows(udiff(was, now))]}


def found(search, hits):
    """A hit list plus the backend that produced it -- an empty result is never a mystery.

    Takes the search service rather than the workspace: a block that only searches should
    not need a whole `Workspace` to shape its reply, and this is the seam `SearchPort`
    substitutes at.
    """
    return {'backend': search.backend, 'note': search.note, 'hits': [h.dict() for h in hits]}
