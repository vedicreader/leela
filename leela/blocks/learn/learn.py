import json, os, re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from fastcore.basics import AttrDict
from fastcore.xdg import xdg_config_home
from packaging.utils import canonicalize_name
import abhyasa.journey  # adds Learning.journey
import abhyasa.demo  # adds Learning.demo
from abhyasa.contract import validate_nb_spec, vault_key
from abhyasa.journey import walk_state
from abhyasa.store import slugify
from abhyasa.stagekit import is_local
from ..fs.fs import MAX_EDIT_BYTES
from ..nb.nb import Cell

__all__ = ['LESSONS', 'PKG', 'Taken', 'abhyasa_vault', 'other_vault', 'not_found', 'find_step', 'passages', 'is_local', 'open_step', 'pane_url', 'pkg_names',
           'lookup', 'scratch_cell']

LESSONS = Path.home()/'Learning'/'Leela lessons'

def pane_url(url) -> str|None:
    "`url` with `pane=1` in its query, when it is a local path; else None."
    if not is_local(url): return None
    p = urlsplit(url)
    q = [x for x in p.query.split('&') if x and not x.startswith('pane=')] + ['pane=1']
    return urlunsplit(('', '', p.path, '&'.join(q), p.fragment))

def abhyasa_vault() -> str:
    "The `vault` in abhyasa's address file when the process that wrote it still runs; '' for no file, a dead pid or a bad file."
    f = os.getenv('ABHYASA_ADDRESS_FILE') or xdg_config_home()/'abhyasa'/'serving.json'
    try: d = json.loads(Path(f).read_text())
    except (OSError, ValueError): return ''
    if not (isinstance(d, dict) and type(pid := d.get('pid')) is int and pid > 0 and isinstance(d.get('vault'), str)): return ''
    try: os.kill(pid, 0)   # a SIGKILL leaves the file
    except PermissionError: pass
    except (OSError, OverflowError): return ''
    return d['vault']

def other_vault(q, path) -> str|None:
    "The one line for a link `q` whose `v` is not the key of Leela's vault `path`; None for no `v` or the same key."
    if not q.v or q.v == vault_key(path): return None
    there = abhyasa_vault()
    return f"abhyasa uses {f'the vault at {there}' if there else 'another vault'}. Leela uses {path}. Start both with the same vault."

def not_found(q, path) -> str:
    "The one line for a walk that is not in the vault `path`; a link with no `v` keeps the line of 0.0.12."
    return f'This walk is not in the vault at {path}. abhyasa and Leela must use the same vault.' if q.v else 'This walk is not in your learning store.'

def find_step(lr, q) -> AttrDict:
    "The step, the done walk, the topic or the missing walk that the `read_handoff` result `q` names. A step has `nb`, checked by `validate_nb_spec`, and its `demo`, or None."
    if not q.walk:
        c = lr.concept(slugify(q.topic))
        return AttrDict(kind='topic', name=c.name if c else q.topic, concept=c)
    j = lr.journey(q.walk)
    if j is None: return AttrDict(kind='missing')
    i = walk_state(j).current if q.step is None else q.step
    if i is None: return AttrDict(kind='done', j=j)
    if i >= len(j.steps): raise ValueError(f'step: this walk has no step {i}')
    s = j.steps[i]
    c, nb = lr.concept(s['slug']), validate_nb_spec(s['nb']) if s.get('nb') else None
    d = lr.demo(nb['demo']) if nb and nb['demo'] else None
    return AttrDict(kind='step', j=j, i=i, step=s, name=c.name if c else s['slug'], nb=nb, demo=d.spec if d and isinstance(d.get('spec'), dict) and d.spec.get('id') else None)

def passages(j, r) -> list:
    "The passage `r` of a step of walk `j` and at most 2 more from `r.also`, each with its `source_of` line: `text`, `label`, `title`, `place`, `url` and `date`."
    from abhyasa.sources import source_of
    also = r.get('also') if isinstance(r.get('also'), list) else []
    return [AttrDict(source_of(x, j), text=x['text']) for x in [r, *also[:2]] if isinstance(x, dict) and isinstance(x.get('text'), str) and x['text'].strip()]

class Taken(Exception): "The lesson's file name holds something that is not that lesson."

def _linked(p) -> bool:
    "Whether `p`, or a folder above it that does not hold the home folder, is a symbolic link."
    return any(x.is_symlink() for x in (p, *p.parents) if not Path.home().is_relative_to(x))

def lessons_folder(session, fs) -> tuple[Path, bool]:
    "`lessons` in the project folder, or `LESSONS` with no folder open or a project folder that holds it; and whether this call made `LESSONS` a root."
    root = session.project_root
    if root is not None and root != fs.loose and not LESSONS.resolve().is_relative_to(root): return root/'lessons', False
    if _linked(LESSONS): raise ValueError('The lessons folder is a symbolic link. Leela does not write a lesson through a link.')
    if fs.covers(LESSONS.resolve()): return LESSONS, False
    LESSONS.mkdir(parents=True, exist_ok=True)
    session.add_root(LESSONS)
    return LESSONS, True

def open_step(session, fs, v, q) -> Path:
    "The path of the lesson for the `find_step` result `v` of the handoff `q`, written when missing and reopened when its meta names the same step or topic; `Taken` for any other file there. A reopened lesson whose tool environment is ready and not in its meta gets it there. A refusal or a failed write closes a `LESSONS` root it opened."
    from ..nb.lesson import lesson_notebook, save_lesson
    from ..nb.nb import Notebook
    ready = None
    if v.kind == 'step':
        r, what, file = v.step.get('read') or {}, 'step', f'{q.walk}-{v.i}.ipynb'
        step = dict(walk=q.walk, step=v.i, section=r.get('section') or '', text=r.get('text') or '', note=v.step.get('note') or '')
        if v.get('nb'):
            from abhyasa.contract import handoff
            from .tools import tool_key, tool_kernel
            from ..nb.lesson import step_lesson
            env = tool_key(v.nb['requires']) if v.nb.get('requires') else None
            ready = env if env and tool_kernel(env) else None
            nb = step_lesson(v.name, step, v.nb, passages(v.j, r), demo=v.demo, env=ready, file=file, setup=handoff(q.walk, v.i, v=q.v) if env and not ready else None)
        else: nb = lesson_notebook(v.name, step=step)
        mine = lambda m: isinstance(w := m.get('walk'), dict) and (w.get('walk'), w.get('step')) == (q.walk, v.i)
    else:
        if not (slug := slugify(q.topic)): raise ValueError('topic: give a name with a letter or a digit')
        what, file, nb = 'idea', f'{slug}.ipynb', lesson_notebook(v.name)
        nb.meta['lesson']['topic'] = slug
        mine = lambda m: m.get('topic') == slug and 'walk' not in m
    def pick(folder):
        p = folder/file
        if not (p.exists() or p.is_symlink()): return p
        if p.is_file() and not p.is_symlink() and p.stat().st_size > MAX_EDIT_BYTES:
            raise Taken(f'{p.name} is in the lessons folder and is too large for Leela to check. Move it or rename it, then open the lesson again.')
        try: m = p.is_file() and not p.is_symlink() and Notebook.load(fs._check(p, must_exist=True)).meta.get('lesson')
        except Exception: m = None
        if isinstance(m, dict) and mine(m): return p
        raise Taken(f'{p.name} is in the lessons folder and is not the lesson for this {what}. Move it or rename it, then open the lesson again.')
    folder, made = lessons_folder(session, fs)
    try: p = save_lesson(fs, folder, pick, nb)
    except Exception:
        if made: session.drop_root(folder, closed=False)
        raise
    if ready and Notebook.load(p).meta['lesson'].get('env') != ready:
        from ..nb.lesson import bind_env
        docs = getattr(session, 'docstore', None)
        bind_env(fs, p, ready, docs.docs.get(str(p)) if docs else None)
    return p

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
    return dict(name=m.get('name', ''), package=r.get('package', ''), path=(m.get('path') or '').rpartition('site-packages/')[2], line=m.get('lineno'),
                doc=(m.get('docstring') or '').strip().split('\n')[0], snippet='\n'.join((r.get('content') or '').splitlines()[:12]))

def scratch_cell(nb, snippet:str):
    "Append a code cell that holds `snippet` and has the lesson role `scratch`; other cells stay as they are."
    return nb.insert(len(nb.cells), Cell(source=snippet, extra={'lesson': {'role': 'scratch'}}))
