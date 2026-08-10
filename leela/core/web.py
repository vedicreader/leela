"""The web vocabulary every block shares: error shape, streaming frames, static URLs.

These were module-level helpers in `leela/app.py` with leading underscores, which was
right while there was one web module. Blocks need them, and a block importing a private
name out of the module it is being extracted from is not an improvement -- so they move
here and lose the underscore.

`leela/app.py` re-exports the old names, because `tests/` and any external caller
import some of them from there.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastcore.aio import athreaded
from fastcore.basics import first
from fasthtml.common import JSONResponse
from starlette.staticfiles import StaticFiles

from .. import errstr

__all__ = ['asset_dir', 'static_dirs', 'Assets', 'asset', 'fail', 'sse', 'off_loop',
           'diff_payload', 'found']


def asset_dir(name):
    "One of leela's asset dirs, in a normal install, py2app Resources, or a py2exe distribution."
    import sys
    candidates = [Path(__file__).parent.parent/name]
    if getattr(sys, 'frozen', False):
        exe = Path(sys.executable).resolve()
        candidates += [exe.parent/'leela'/name, exe.parent.parent/'Resources'/'leela'/name]
    return next((p for p in candidates if p.exists()), candidates[0])


def static_dirs():
    """The asset dirs behind `/leestatic`, in lookup order: authored first, vendored second.

    `static/` is leela's own hand-written `lee-ide.js` and `lee-ide.css`; `vendor/` is what
    esbuild produced or npm supplied -- CodeMirror, xterm, htmx, the woff2 faces. Separating
    them means a search of leela's browser code cannot hit 2MB of minified third-party
    output, and `.gitignore` and the packaging manifests describe directories instead of
    listing filenames.
    """
    return [asset_dir('static'), asset_dir('vendor')]


def asset(name):
    "A static URL that changes when the local asset does, preventing mixed JS/CSS revisions."
    p = first(d/name for d in static_dirs() if (d/name).is_file())
    return f'/leestatic/{name}?v={p.stat().st_mtime_ns if p else 0}'


class Assets:
    """Serve one URL prefix from several directories, first match winning.

    Starlette's `Mount` does not fall through when the app behind it 404s, so two mounts on
    `/leestatic` would shadow rather than combine. Resolving the directory here keeps every
    asset URL -- including the `/leestatic/fonts/*.woff2` that `lee-ide.css` names -- exactly
    as it was when both trees lived in one folder.
    """

    def __init__(self, *dirs):
        self.dirs = [Path(d) for d in dirs]
        self.apps = [StaticFiles(directory=str(d)) for d in self.dirs]

    async def __call__(self, scope, receive, send):
        # `Mount` leaves `scope['path']` absolute and reports the matched prefix as `root_path`,
        # which is what `StaticFiles` strips to find the file. Removing the prefix here agrees
        # with it either way: if a Starlette version rewrites `path` to be mount-relative
        # instead, `removeprefix` finds nothing to remove and the result is the same.
        rel = scope['path'].removeprefix(scope.get('root_path') or '').lstrip('/')
        served = first(a for d, a in zip(self.dirs, self.apps) if (d/rel).is_file())
        return await (served or self.apps[0])(scope, receive, send)   # else the first one 404s


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
