"Routes over one canvas document: the basket, the changes, the review, the value, the page."

from __future__ import annotations

from fastcore.all import Path, first

from ...core.web import fail, off_loop
from .change import bundles, coverage, pr, review, state, value
from .context import SCOPES, Spec, resolve, spec_of, weigh
from .doc import Doc
from .explain import capture, explain, replay
from .layout import arrange
from .lit import lit

__all__ = ['CAPS', 'connect', 'SUFFIX']

CAPS = ('fs', 'ai')
#: What a canvas file is called. The document is markdown, so anything can read it.
SUFFIX = '.canvas.md'

def _load(fs, path):
    p = fs._check(path, must_exist=True)
    if not str(p).endswith(SUFFIX): raise ValueError(f'not a canvas: {p}')
    return arrange(Doc.load(p))

def connect(app, ctx):
    rt = app.route
    @rt('/canvas/state')
    def canvas_state(path: str):
        "The document as the browser draws it."
        try: return _load(ctx.fs, path).dict()
        except Exception as e: return fail(e)
    @rt('/canvas/context')
    def canvas_context(path: str, id: str, scope: str = '', budget: int = 0):
        "The exact basket one question will send, with the rule that put each item there."
        try:
            doc = _load(ctx.fs, path)
            base = spec_of(doc.by_id(id))
            spec = Spec(scope=scope or base.scope, pins=base.pins, mutes=base.mutes,
                        budget=budget or base.budget, goal=base.goal)
            items = resolve(doc, id, spec)
            return {'scopes': list(SCOPES), 'spec': spec.__dict__,
                    'items': [i.dict() for i in items], **weigh(items)}
        except Exception as e: return fail(e)
    @rt('/canvas/changes')
    def canvas_changes(path: str, base: str = ''):
        "Every change in the document, against what a diff says moved."
        try:
            doc = _load(ctx.fs, path)
            changed = _changed(doc, base)
            return {'changed': changed, **coverage(doc, changed),
                    'state': {b.id: state(b, changed) for b in bundles(doc)}}
        except Exception as e: return fail(e)
    @rt('/canvas/review')
    def canvas_review(path: str, id: str, base: str = ''):
        "One change as a document of its own, built from the diff."
        try:
            doc = _load(ctx.fs, path)
            return review(doc, id, _diff(doc, base)).dict()
        except Exception as e: return fail(e)
    @rt('/canvas/value')
    def canvas_value(path: str, base: str = ''):
        "Every goal, and every change that serves it."
        try:
            doc = _load(ctx.fs, path)
            return value(doc, _changed(doc, base)).dict()
        except Exception as e: return fail(e)
    @rt('/canvas/pr')
    def canvas_pr(path: str, id: str):
        "The pull request one change is worth. It opens nothing."
        try: return pr(_load(ctx.fs, path), id)
        except Exception as e: return fail(e)
    @rt('/canvas/page')
    async def canvas_page(path: str, out: str = '', base: str = ''):
        "The literate page, written beside the document unless `out` says otherwise."
        try:
            doc = _load(ctx.fs, path)
            root = Path(doc.path).parent
            dest = Path(out) if out else Path(doc.path).with_suffix('.html')
            p = await off_loop(lit, doc, dest, _changed(doc, base), str(root))
            return {'ok': True, 'path': str(p)}
        except Exception as e: return fail(e)
    @rt('/canvas/draft')
    async def canvas_draft(req):
        "Draft the missing snippet prose, and save the document with it."
        d = await req.json()
        try:
            doc = _load(ctx.fs, d.get('path') or '')
            ask = lambda prompt, brick: ctx.ai.ask(prompt)
            got = await off_loop(explain, doc, ask, str(Path(doc.path).parent),
                                 ('snippet', 'diff'), bool(d.get('overwrite')))
            doc.save()
            return {'ok': True, 'drafted': [b.id for b in got]}
        except Exception as e: return fail(e)

def _diff(doc, base=''):
    "The diff a review reads. Git is `gheasy`'s, so this asks it rather than shelling out."
    from gheasy.repo import GitRepo, repo_root
    root = repo_root(Path(doc.path).parent)
    if root is None: return ''
    return GitRepo(root).diff(left=base) if base else GitRepo(root).diff()

def _changed(doc, base=''):
    from .change import hunks
    return list(hunks(_diff(doc, base)))
