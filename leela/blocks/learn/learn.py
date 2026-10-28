import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from fastcore.basics import AttrDict
from packaging.utils import canonicalize_name
import abhyasa.journey  # adds Learning.journey
from abhyasa.journey import walk_state
from abhyasa.store import slugify
from ..nb.nb import Cell

__all__ = ['LESSONS', 'PKG', 'Taken', 'find_step', 'is_local', 'open_step', 'pane_url', 'pkg_names', 'lookup', 'scratch_cell']

LESSONS = Path.home()/'Learning'/'Leela lessons'

# a copy of abhyasa.core.pane.is_local: abhyasa.core imports abhyasa's web UI (leela-reuse.md 5)
_BAD = re.compile(r'[\x00-\x1f\x7f\\]')
def is_local(url) -> bool:
    "Whether `url` is a path in this app: one `/` at the start, no scheme, no host, no backslash and no control character."
    return isinstance(url, str) and url.startswith('/') and not url.startswith('//') and not _BAD.search(url)

def pane_url(url) -> str|None:
    "`url` with `pane=1` in its query, when it is a local path; else None."
    if not is_local(url): return None
    p = urlsplit(url)
    q = [x for x in p.query.split('&') if x and not x.startswith('pane=')] + ['pane=1']
    return urlunsplit(('', '', p.path, '&'.join(q), p.fragment))

def find_step(lr, q) -> AttrDict:
    "The step, the done walk, the topic or the missing walk that the `read_handoff` result `q` names."
    if not q.walk:
        c = lr.concept(slugify(q.topic))
        return AttrDict(kind='topic', name=c.name if c else q.topic, concept=c)
    j = lr.journey(q.walk)
    if j is None: return AttrDict(kind='missing')
    i = walk_state(j).current if q.step is None else q.step
    if i is None: return AttrDict(kind='done', j=j)
    if i >= len(j.steps): raise ValueError(f'step: this walk has no step {i}')
    s = j.steps[i]
    c = lr.concept(s['slug'])
    return AttrDict(kind='step', j=j, i=i, step=s, name=c.name if c else s['slug'])

class Taken(Exception): "The lesson's file name holds something that is not that lesson."

def lessons_folder(session, fs) -> Path:
    "`lessons` in the project folder; `LESSONS` with no folder open or a project folder that holds it, made and opened as a root when no root covers it."
    root = session.project_root
    if root is not None and root != fs.loose and not LESSONS.resolve().is_relative_to(root): return root/'lessons'
    if LESSONS.is_symlink(): raise ValueError('The lessons folder is a symbolic link. Leela does not write a lesson through a link.')
    if not fs.covers(LESSONS.resolve()):
        LESSONS.mkdir(parents=True, exist_ok=True)
        session.add_root(LESSONS)
    return LESSONS

def open_step(session, fs, v, q) -> Path:
    "The path of the lesson for the `find_step` result `v` of the handoff `q`, written when missing and reopened when its meta names the same step or topic; `Taken` for any other file there."
    from ..nb.lesson import lesson_notebook, save_lesson
    from ..nb.nb import Notebook
    if v.kind == 'step':
        r, what, file = v.step.get('read') or {}, 'step', f'{q.walk}-{v.i}.ipynb'
        nb = lesson_notebook(v.name, step=dict(walk=q.walk, step=v.i, section=r.get('section') or '', text=r.get('text') or '', note=v.step.get('note') or ''))
        mine = lambda m: isinstance(w := m.get('walk'), dict) and (w.get('walk'), w.get('step')) == (q.walk, v.i)
    else:
        if not (slug := slugify(q.topic)): raise ValueError('topic: give a name with a letter or a digit')
        what, file, nb = 'idea', f'{slug}.ipynb', lesson_notebook(v.name)
        nb.meta['lesson']['topic'] = slug
        mine = lambda m: m.get('topic') == slug and 'walk' not in m
    def pick(folder):
        p = folder/file
        if not (p.exists() or p.is_symlink()): return p
        try: m = p.is_file() and not p.is_symlink() and Notebook.load(fs._check(p, must_exist=True)).meta.get('lesson')
        except Exception: m = None
        if isinstance(m, dict) and mine(m): return p
        raise Taken(f'{p.name} is in the lessons folder and is not the lesson for this {what}. Move it or rename it, then open the lesson again.')
    return save_lesson(fs, lessons_folder(session, fs), pick, nb)

PKG = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}(\[[A-Za-z0-9._,-]{1,64}\])?((==|>=|<=|~=|<|>)[A-Za-z0-9.*+!-]{1,32})?')
_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')

def pkg_names(names) -> list[str]:
    "The sorted distribution names in the requirement strings `names`, with no extra or version. `ValueError` for more than 5 names or one that does not match `PKG`."
    names = list(names)
    if len(names) > 5: raise ValueError('package: give at most 5 names')
    if bad := [n for n in names if not (isinstance(n, str) and PKG.fullmatch(n))]: raise ValueError(f'package: {bad[0]!r} is not a package name')
    return sorted({_NAME.match(n)[0] for n in names})

def _indexed_as(k, names) -> list[str]:
    "`names` as the index `k` holds them, matched by their normalized form; the names as given when none is in the index."
    want = {canonicalize_name(n) for n in names}
    return sorted(s for s in k.pkgs2consider() if _NAME.fullmatch(s) and canonicalize_name(s) in want) or names

def lookup(k, q:str, packages=(), limit:int=8) -> list[dict]:
    "Rows of the kosha handle `k` for `q`, only from `packages` when given; empty for an empty `q` or no handle."
    names = pkg_names(packages)
    if not q or k is None: return []
    from kosha.core import filt2wh
    rows = k.env_context(q, limit=limit, where=filt2wh({'package': _indexed_as(k, names)}, 'env') if names else None)
    return [_row(r) for r in rows]

def _row(r) -> dict:
    m = r.get('metadata') or {}
    return dict(name=m.get('name', ''), package=r.get('package', ''), path=m.get('path', ''), line=m.get('lineno'),
                doc=(m.get('docstring') or '').strip().split('\n')[0], snippet='\n'.join((r.get('content') or '').splitlines()[:12]))

def scratch_cell(nb, snippet:str):
    "Append a code cell that holds `snippet` and has the lesson role `scratch`; other cells stay as they are."
    return nb.insert(len(nb.cells), Cell(source=snippet, extra={'lesson': {'role': 'scratch'}}))
