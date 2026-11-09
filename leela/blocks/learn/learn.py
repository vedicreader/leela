import json, os, re
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit
from fastcore.basics import AttrDict
from fastcore.xdg import xdg_config_home
from packaging.utils import canonicalize_name
import abhyasa.show  # adds Learning.demo
from abhyasa.contract import validate_nb_spec, vault_key
from abhyasa.path import walk_state
from abhyasa.learner import slugify
from abhyasa.stagekit import is_local
from ..fs.fs import MAX_EDIT_BYTES
from ..nb.nb import Cell

__all__ = ['LESSONS', 'PKG', 'Taken', 'project_root', 'copy_root', 'doc_notebook', 'abhyasa_address', 'abhyasa_vault', 'abhyasa_url', 'walk_url', 'show_link', 'other_vault', 'not_found', 'Refused', 'vault_memory', 'learn_ref', 'handoff_memory', 'handoff_store', 'walk_memory', 'find_step', 'passages', 'is_local', 'open_step', 'pane_url', 'pkg_names',
           'lookup', 'scratch_cell']

LESSONS = Path(os.getenv('LEELA_LESSONS') or Path.home()/'Learning'/'Leela lessons').expanduser().absolute()

def pane_url(url) -> str|None:
    "`url` with `pane=1` in its query, when it is a local path; else None."
    if not is_local(url): return None
    p = urlsplit(url)
    q = [x for x in p.query.split('&') if x and not x.startswith('pane=')] + ['pane=1']
    return urlunsplit(('', '', p.path, '&'.join(q), p.fragment))

def abhyasa_address() -> dict:
    "Abhyasa's address file when the process that wrote it still runs; empty for no file, a dead pid or a bad file."
    f = os.getenv('ABHYASA_ADDRESS_FILE') or xdg_config_home()/'abhyasa'/'serving.json'
    try: d = json.loads(Path(f).read_text())
    except (OSError, ValueError): return {}
    if not (isinstance(d, dict) and type(pid := d.get('pid')) is int and pid > 0 and isinstance(d.get('vault'), str)): return {}
    try: os.kill(pid, 0)   # a SIGKILL leaves the file
    except PermissionError: pass
    except (OSError, OverflowError): return {}
    return d

def abhyasa_vault() -> str:
    "The `vault` in abhyasa's address file when the process that wrote it still runs; '' for no file, a dead pid or a bad file."
    return abhyasa_address().get('vault', '')

def abhyasa_url(path) -> str|None:
    "The link to the local `path` on the abhyasa that runs; None when it does not run or its `url` is not http on this computer, with a port."
    try: u = urlsplit(url := abhyasa_address().get('url')); ok = u.scheme == 'http' and u.hostname in ('127.0.0.1', 'localhost', '::1') and u.port is not None
    except (ValueError, TypeError, AttributeError): ok = False
    return ok and f"{url.rstrip('/')}{path}" or None

def walk_url(walk, step) -> str|None:
    "The link to `step` of `walk` on the abhyasa that runs, as `abhyasa_url`."
    return abhyasa_url(f"/w/{quote(walk, safe='')}/{step}")

def show_link(said, slug, name) -> dict|None:
    "For a \"show me …\" to the guide, abhyasa's `show_reply`, the hand-off to the demo of the idea `slug` in abhyasa: `{title, href}`, `href` None when abhyasa does not run; None for any other line."
    from abhyasa.show import show_reply
    if (words := show_reply(said)) is None: return None
    return dict(title=name, href=abhyasa_url(f"/c/{quote(slug, safe='')}?show={quote(words)}"))

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
    "`lessons` in the project folder, or `LESSONS` with no folder open or a project folder that holds it; and whether the lesson there is a loose file, `LESSONS` not being a root."
    root = session.project_root
    if root is not None and root != fs.loose and not LESSONS.resolve().is_relative_to(root): return root/'lessons', False
    if _linked(LESSONS): raise ValueError('The lessons folder is a symbolic link. Leela does not write a lesson through a link.')
    if fs.covers(LESSONS.resolve()): return LESSONS, False
    LESSONS.mkdir(parents=True, exist_ok=True)
    return LESSONS, True

def notebook_copy(j) -> Path|None:
    "abhyasa's learning copy of the notebook of walk `j`, or None."
    try: from abhyasa.contract import notebook_copy as copy_of
    except ImportError: return None
    return copy_of(j)

def project_root(session, fs, nb) -> tuple[Path, list]:
    "The learner's notebook `nb`, and its project (its checkout, else its folder) in a list when no root covers it: Leela runs the notebook there, in that project's environment. Adds nothing."
    from ...core.projects import workspace_for
    nb = Path(nb).resolve()
    if not nb.is_file() or nb.suffix != '.ipynb': raise ValueError(f'{nb.name} is not a notebook on this computer.')
    if fs.covers(nb): return nb, []
    if (d := workspace_for(nb)) is None: raise ValueError(f'Leela does not open a folder as large as the one that holds {nb.name}.')
    return nb, [d]

def copy_root(session, fs, copy) -> tuple[Path, list]:
    "`copy`, and the folders no root covers of the project of the notebook it copies and of the copy itself, project first. Adds nothing."
    from abhyasa.contract import copy_home
    if _linked(copy): raise ValueError('The learning copy is in a symbolic link. Leela does not open a lesson through a link.')
    need = project_root(session, fs, home/copy.name)[1] if (home := copy_home(copy)) is not None else []
    return copy, need + ([] if fs.covers(copy.parent.resolve()) else [copy.parent.resolve()])

def doc_notebook(lr, q) -> Path:
    "The file of the notebook `q.doc` on vault shelf `q.shelf`. `ValueError` when it is not a notebook on this computer."
    from abhyasa.path import nb_file
    if not (f := nb_file(lr, q.doc, q.shelf or 'store')): raise ValueError('This notebook is not in your learning store, or its file is not on this computer.')
    return Path(f[1])

def open_step(session, fs, v, q) -> tuple[Path, list]:
    """The path of the lesson for the `find_step` result `v` of the handoff `q`, and the folders it needs that no root covers: abhyasa's learning copy for a notebook walk, else the lesson, written when missing and reopened when its meta names the same step or topic; `Taken` for any other file there. With no folder open the lesson is a loose file in `LESSONS`. A reopened lesson whose tool environment is ready and not in its meta gets it in the file and the open tab."""
    from ..nb.lesson import lesson_notebook, save_lesson
    from ..nb.nb import Notebook
    if v.kind == 'step' and (copy := notebook_copy(v.j)): return copy_root(session, fs, copy)
    ready = None
    if v.kind == 'step':
        r, what, file = v.step.get('read') or {}, 'step', f'{q.walk}-{v.i}.ipynb'
        step = dict(walk=q.walk, step=v.i, section=r.get('section') or '', text=r.get('text') or '', note=v.step.get('note') or '', slug=v.step.get('slug') or '')
        if v.get('nb'):
            from abhyasa.contract import handoff
            from .toolenv import tool_key, tool_kernel
            from ..nb.lesson import step_lesson
            env = tool_key(v.nb['requires']) if v.nb.get('requires') else None
            ready = env if env and tool_kernel(env) else None
            nb = step_lesson(v.name, step, v.nb, passages(v.j, r), demo=v.demo, env=ready, file=file, setup=handoff(q.walk, v.i, v=q.v) if env and not ready else None, back=walk_url(q.walk, v.i))
        else: nb = lesson_notebook(v.name, step=step)
        mine = lambda m: isinstance(w := m.get('walk'), dict) and (w.get('walk'), w.get('step')) == (q.walk, v.i)
    else:
        if not (slug := slugify(q.topic)): raise ValueError('topic: give a name with a letter or a digit')
        what, file, nb = 'idea', f'{slug}.ipynb', lesson_notebook(v.name)
        nb.meta['lesson']['topic'] = slug
        mine = lambda m: m.get('topic') == slug and 'walk' not in m
    folder, loose = lessons_folder(session, fs)
    def pick(folder):
        p = folder/file
        if not (p.exists() or p.is_symlink()): return p
        if p.is_file() and not p.is_symlink() and p.stat().st_size > MAX_EDIT_BYTES:
            raise Taken(f'{p.name} is in the lessons folder and is too large for Leela to check. Move it or rename it, then open the lesson again.')
        try: m = p.is_file() and not p.is_symlink() and Notebook.load(p if loose else fs._check(p, must_exist=True)).meta.get('lesson')
        except Exception: m = None
        if isinstance(m, dict) and mine(m): return p
        raise Taken(f'{p.name} is in the lessons folder and is not the lesson for this {what}. Move it or rename it, then open the lesson again.')
    if loose:
        from ...core.projects import loose_root
        made = fs.loose is None and session.add_root(loose_root(), loose=True)
        try:
            if not ((p := pick(folder)).exists() or p.is_symlink()): nb.save(p)
            fs.admit(p)
        except Exception:
            if made: session.drop_root(made, closed=False)
            raise
    else: p = save_lesson(fs, folder, pick, nb)
    if ready and Notebook.load(p).meta['lesson'].get('env') != ready:
        from ..nb.lesson import bind_env
        bind_env(fs, p, ready, session)
    return p, []

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


class Refused(Exception):
    "A handoff or a write the vault rules refuse; `str(e)` is the plain line."

def vault_memory(ws, ref):
    "The `Memory` of the registry row `ref`; the workspace's own for the workspace row."
    from ..memory.vaults import WORKSPACE
    return ws.memory if ref.name == WORKSPACE else ws.vaults.memory(ref.name)

def learn_ref(ws):
    "The managed Learn vault when it is set up; else the active vault, for a person who never set it up."
    from ..memory.vaults import LEARN
    return ws.vaults.get(LEARN) or ws.vaults.active

def handoff_memory(ws, v='', write=False):
    "`(vault name, Memory)` that the link key `v` names: the registry vault with that key, else the Learn vault. `Refused` with the plain line for an unknown key, or for `write` on a vault that is read-only."
    from ..memory.vaults import WORKSPACE
    ref = learn_ref(ws)
    if v:
        key = lambda r: vault_key(ws.memory.path if r.name == WORKSPACE else r.path)
        if key(ref) != v:
            if not (ref := next((r for r in ws.vaults if (r.name == WORKSPACE or r.exists) and key(r) == v), None)):
                raise Refused(other_vault(AttrDict(v=v), vault_memory(ws, learn_ref(ws)).path))
    if write and not ref.writable: raise Refused(f'The vault {ref.name} is read-only. Make it admin to save your work there.')
    return ref.name, vault_memory(ws, ref)

def handoff_store(ws, v='', write=False):
    "`(vault name, Learning)` that the link key `v` names, as `handoff_memory`."
    from abhyasa.learner import Learning
    from ..memory.memory import learning_store
    name, memory = handoff_memory(ws, v, write)
    return name, Learning(learning_store(memory))

def walk_memory(ws, walk, write=False):
    "The `Memory` of the vault that holds the walk `walk`: the Learn vault first, then the others; the Learn vault when none has it. `Refused` for `write` on a read-only vault."
    from abhyasa.learner import Learning
    from ..memory.memory import _open_lock, learning_store
    home = ref = learn_ref(ws)
    for r in ([home] + [r for r in ws.vaults if r.name != home.name]) if walk else ():
        try:
            m = vault_memory(ws, r)
            store = learning_store(m)
            with _open_lock(m.path): hit = Learning(store).journey(walk)
        except Exception: continue
        if hit: ref = r; break
    if write and not ref.writable: raise Refused(f'The vault {ref.name} is read-only. Make it admin to save your work there.')
    return vault_memory(ws, ref)
