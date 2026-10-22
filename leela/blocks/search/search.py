"Predictable human search (rg unless a mode is picked), semantic agent search, and every hit."

from __future__ import annotations
from kunda.pythons import clean_env
import ast, json, re, subprocess, threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import wraps
from inspect import isroutine
from fastcore.all import L, Path, first, ifnone, store_attr
from fastcore.aio import athreaded
from fastcore.parallel import threaded

from ... import Dictable, errstr
from ..fs.fs import LANGS
from ..nb.nb import cell_at, cell_lines, cell_of, read_cells, source_spans

__all__ = ['Hit', 'Cluster', 'Search', 'Weights', 'DEMOTED', 'SETTING_WEIGHTS']

_CODE_SUFFIXES = frozenset(LANGS) | {'.txt', '.rst', '.cfg', '.ini'}
MAX_SCAN_BYTES = 2_000_000

_DEF_RE = re.compile(r'^(\s*)(?:async\s+)?(def|class)\s+(\w+)')

def _is_nb(path): return str(path).lower().endswith('.ipynb')

_SIM_COLS = ['content', 'path', 'metadata']

def _receiver(code, pos):
    "`(type_name, typed_fragment, replace_from)` for an attribute expression at `pos`."
    before=(code or '')[:pos]
    m=re.search(r'([_A-Za-z]\w*)\.([_A-Za-z]\w*)$', before)
    if not m: return '', '', pos
    obj,frag=m.groups(); typ=''
    pats=(rf'\b{re.escape(obj)}\s*:\s*([_A-Za-z]\w*)',
        rf'\b{re.escape(obj)}\s*=\s*([_A-Za-z]\w*)\s*\(')
    for pat in pats:
        if ms:=re.findall(pat,before): typ=ms[-1]
    if not typ and obj[:1].isupper(): typ=obj
    return typ,frag,m.start(2)

def _get(row, key, default=None):
    "Dict or attribute row: kosha returns AttrDict/SimpleNamespace, store rows are dicts."
    if isinstance(row, dict): return row.get(key, default)
    return getattr(row, key, default)

def _meta(row):
    "Chunk metadata as a dict. kosha's `repo_context` decodes the JSON column; raw row reads do not."
    m = _get(row, 'metadata') or {}
    if isinstance(m, str):
        try: m = json.loads(m)
        except Exception: m = {}
    return m or {}

@dataclass
class Hit(Dictable):
    "One search result. `line` is 1-indexed; `kind` names the backend that produced it."
    path: str
    line: int
    text: str
    kind: str = 'scan'
    symbol: str = ''
    score: float = 0.0
    callers: list = None
    why: dict = None
    package: str = ''
    module: str = ''
    sources: list = field(default_factory=list)
    cell: str = ''
    cell_index: int = -1
    cell_line: int = 0
    column: int = 0

#: Paths that are never the answer to a code search, whatever matched in them.
DEMOTED = re.compile(r'(^|/)(node_modules|dist|build|vendor|third_party)(/|$)|\.min\.(js|css)$')

#: Settings key -> weight field. The settings file is camelCase and says which leg it means; the
#: dataclass is named for the feature. One table, so neither spelling has to guess the other.
SETTING_WEIGHTS = {'legFiles': 'files', 'legSymbols': 'symbols', 'legRg': 'rg', 'legFts': 'fts',
    'legAnn': 'ann', 'legRank': 'leg_rank', 'symbolExact': 'symbol_exact',
    'symbolPart': 'symbol_part', 'queryInText': 'text', 'queryInFilename': 'filename',
    'demoteNoise': 'demote'}

@dataclass
class Weights(Dictable):
    "What `all` pays for each signal."
    files: float = 110.0
    symbols: float = 100.0
    rg: float = 80.0
    fts: float = 60.0
    ann: float = 40.0
    symbol_exact: float = 120.0
    symbol_part: float = 55.0
    text: float = 40.0
    filename: float = 20.0
    leg_rank: float = 10.0
    demote: float = 25.0
    @classmethod
    def load(cls, values=None):
        "A `search` settings section, by either spelling, ignoring everything that is not a weight."
        ok = {}
        for k, v in (values or {}).items():
            name = SETTING_WEIGHTS.get(k, k if k in cls.__dataclass_fields__ else '')
            if not name: continue
            try: ok[name] = float(v)
            except (TypeError, ValueError): continue
        return cls(**ok)
    def settings(self):
        "The weights under the names the settings file uses."
        return {k: getattr(self, name) for k, name in SETTING_WEIGHTS.items()}
    def leg(self, name): return float(getattr(self, name, self.ann))
    def score(self, why):
        "The score of one feature vector. The same arithmetic the weights panel does live."
        out = self.leg(why.get('leg', ''))
        for k, v in why.items():
            if k != 'leg': out += getattr(self, k, 0.0) * float(v)
        return out

@dataclass
class Cluster:
    "One ANN cluster: a centroid key, how many chunks it holds, and a sample of them."
    centroid: int
    size: int
    members: list = field(default_factory=list)
    label: str = ''
    def __post_init__(self):
        if not self.label:
            syms = [m.symbol.rsplit('.', 1)[-1] for m in self.members if m.symbol]
            self.label = min(syms, key=len) if syms else f'cluster {self.centroid}'
    @property
    def files(self):
        "Distinct files the cluster spans. A cluster crossing many files is the interesting kind."
        return sorted({m.path for m in self.members})
    def dict(self):
        return {'centroid': self.centroid, 'size': self.size, 'label': self.label,
            'files': self.files, 'members': [m.dict() for m in self.members]}

class _Serial:
    "A Kosha handle held behind litesearch's own connection locks."
    _PLAIN = (str, bytes, bool, int, float, complex, Path, type(None))
    def __init__(self, inner, dbs=None):
        self.__dict__['inner'] = inner
        self.__dict__['dbs'] = tuple(dbs) if dbs is not None else tuple(
            db for db in (getattr(inner, 'codedb', None), getattr(inner, 'envdb', None)) if db is not None)
    def _held(self):
        from contextlib import ExitStack
        from litesearch.core import db_lock
        stack = ExitStack()
        for db in self.dbs: stack.enter_context(db_lock(db))
        return stack
    def _locked(self, attr):
        @wraps(attr)
        def call(*a, **kw):
            with self._held():
                out = attr(*a, **kw)
                # a lazy row iterator would otherwise do its reading after the lock was dropped
                return list(out) if isinstance(out, Iterator) else out
        return call
    def __call__(self, *a, **kw): return self._locked(self.inner)(*a, **kw)
    def __getattr__(self, name):
        attr = getattr(self.inner, name)
        if isinstance(attr, (self._PLAIN, type)): return attr
        if isroutine(attr): return self._locked(attr)
        return _Serial(attr, self.dbs) if callable(attr) or hasattr(attr, '__dict__') else attr

class Search:
    "Human search uses explicit modes; inline-agent search uses Kosha with an rg fallback."
    def __init__(self, sandbox, prefer_kosha=True, focus=None):
        store_attr('prefer_kosha', fs=sandbox)
        self.focus = focus
        self._k = None
        self._k_tried = False
        self._k_root = None
        self._k_note = 'kosha not tried yet'
        self._k_lock = threading.RLock()
        self.backend = 'scan'
        self.note = ''
        self._completion_cache = {}
        self._agent_sync_tried = False
        self.weights = Weights()
    def _focus(self):
        "Where the person is working, when the workspace has said. See `Workspace.cwd_for`."
        try: return self.focus() if callable(self.focus) else self.focus
        except Exception: return None
    def kosha_root(self, path=None):
        "The checkout whose index answers for `path`: the nearest one at or above it."
        from ...core.projects import PROJECT_MARKERS, nearest_marked
        roots = L(self.fs.roots)
        here = path or self._focus()
        try: p = Path(here).resolve() if here else None
        except OSError: p = None
        stop = first(r for r in roots if p is not None and (Path(r) == p or Path(r) in p.parents))
        if p is None: return stop or first(roots)
        # The checkout answers, through the nearest `.kosha` at or above it; one below it, such as a
        # stray index in the package folder, never does. A folder outside every checkout answers for itself.
        c = nearest_marked(p, PROJECT_MARKERS, stop)[0]
        return nearest_marked(c or p, ('.kosha',), stop)[0] or c or stop or first(roots)
    def _make_kosha(self, root=None):
        "A fresh Kosha handle: separate SQLite connections for readers and the sync writer."
        from kosha import Kosha
        return _Serial(Kosha(dir=root or self.kosha_root(),install_skill=False,busy_timeout=30000))
    def _kosha(self, path=None):
        "The kosha handle for the checkout in hand, or None."
        root = self.kosha_root(path)
        with self._k_lock:
            if self._k_root is not None and root != self._k_root: self._k, self._k_tried = None, False
            if self._k_tried: return self._k
            self._k_tried, self._k_root = True, root
            if not self.prefer_kosha:
                self._k_note = 'kosha disabled'
                return None
            try:
                self._k = self._make_kosha(root)
                self.backend, self.note = 'kosha', f'{Path(root).name} + installed packages' if root else 'repo + installed packages'
            except Exception as e:
                self._k_note = f'kosha unavailable ({errstr(e)})'
                self.note = self._k_note + '; literal scan'
            return self._k
    @threaded(daemon=True)
    def warm(self):
        "Open an index that already exists before the first jump, and re-parse the files changed since."
        root = self.kosha_root()
        if not self.prefer_kosha or not root or not (Path(root)/'.kosha').is_dir(): return
        if (k := self._kosha()) is None: return
        try: st = k.status(pyproject=False)
        except Exception: return
        if st.get('stale_files') or st.get('new_files'): return self._sync(True, False)
    def _covers(self, path):
        "Whether the sandbox can open an indexed path. Kosha may index a wider checkout."
        try: return bool(path) and self.fs.covers(Path(path).resolve())
        except Exception: return False
    def _context_rows(self, rows, default_kind='context'):
        out = L()
        for row in rows:
            m = _meta(row)
            raw = str(m.get('path') or row.get('path') or '')
            path = self._here(raw) or raw
            local = self._covers(path)
            package = str(row.get('package') or m.get('package') or '')
            out.append(Hit(path=path, line=int(m.get('lineno') or 1),
                text=(row.get('content') or '').strip(),
                kind=default_kind if local else 'env-context',
                symbol=str(m.get('mod_name') or m.get('name') or ''),
                score=float(row.get('pagerank') or row.get('_rrf_score') or 0.0),
                callers=[str(c) for c in (row.get('callers') or [])][:8],
                package=package, sources=['kosha context']))
        return out
    def _context(self, q, limit):
        "Kosha's composed repo + environment retrieval, including graph context."
        k = self._kosha()
        if k is None: return None
        try: rows = k.context(q, graph=True, env=True, limit=limit)
        except Exception as e:
            self.note = f'Kosha context failed ({errstr(e)})'
            return None
        out = self._context_rows(rows)
        self.backend = 'context'
        local_n = sum(h.kind == 'context' for h in out)
        self.note = f'Kosha composed retrieval · {local_n} repo + {len(out)-local_n} environment'
        return out
    def _repo_context(self, q, limit):
        k = self._kosha()
        if k is None: return None
        try: rows = k.repo_context(q, columns=','.join(_SIM_COLS), limit=limit)
        except Exception as e: self.note = f'Kosha repo search failed ({errstr(e)})'; return None
        out = self._context_rows(rows, 'repo-context')
        self.backend, self.note = 'repo', f'Kosha code store · {len(out)} results'
        return out
    def _env_context(self, q, limit):
        k = self._kosha()
        if k is None: return None
        try: rows = k.env_context(q, columns='content,metadata,package', limit=limit)
        except Exception as e: self.note = f'Kosha environment search failed ({errstr(e)})'; return None
        out = self._context_rows(rows, 'env-context')
        self.backend, self.note = 'environment', f'Kosha environment store · {len(out)} results'
        return out
    def package_api(self, package):
        "A package's public API, each name carrying the file and line that define it."
        k = self._kosha()
        if k is None or not package: return []
        try: rows = [dict(r) for r in k.public_api(package, meta_cols='mod_name,docstring,path,lineno')]
        except Exception as e: self.note = f'package API failed ({errstr(e)})'; return []
        for r in rows:
            r['path'], r['line'] = self._here(str(r.pop('path', '') or '')), int(r.pop('lineno', 0) or 0)
        return rows
    def _here(self, place):
        "The project's own copy of an indexed package file."
        # One Kosha index serves every checkout, so a row can name another virtualenv's copy of
        # the same package, which the sandbox cannot open at all.
        parts = Path(place).parts if place else ()
        if 'site-packages' in parts:
            rest = parts[len(parts) - list(reversed(parts)).index('site-packages'):]
            for r in self.env_roots():
                if (mine := Path(r).joinpath(*rest)).is_file(): return str(mine)
        return place if place and Path(place).is_file() else ''
    def completion_patches(self, code, pos, limit=50):
        "Methods dynamically patched onto the receiver type, from Kosha's code stores."
        typ,frag,start=_receiver(code,pos)
        def result(rows=()):
            details=[x for x in rows if not frag or x['name'].startswith(frag)][:limit]
            return {'from':start,'matches':[x['name'] for x in details],'details':details}
        if not typ: return result()
        k=self._kosha()
        if k is None: return result()
        rows=[]
        packages=set(re.findall(r'^\s*(?:from|import)\s+([\w.]+)',code or '',re.M))
        packages={p.split('.')[0] for p in packages}
        key=(typ,tuple(sorted(packages)))
        cached=self._completion_cache.get(key)
        if cached is not None: return result(cached)
        for pkg in packages:
            try: rows += list(k.public_api(pkg,meta_cols='name,mod_name,docstring,path,lineno',limit=2000))
            except Exception: pass
        pats=[f'def %self:{typ}%',f'def %self: {typ}%']
        for st in (k.code_st,k.env_st):
            for pat in pats:
                try: rows += list(st.rows_where('content LIKE ?',[pat],select='content, metadata',limit=limit))
                except Exception: pass
        out={}
        for row in rows:
            m=_meta(row); name=str(m.get('name') or str(m.get('mod_name') or '').rsplit('.',1)[-1])
            content=str(row.get('content') or '')
            if content and not re.search(rf'^def\s+{re.escape(name)}\s*\(self\s*:\s*{re.escape(typ)}\b',content): continue
            if not name or name.startswith('_'): continue
            out[name]={'name':name,'type':typ,'symbol':m.get('mod_name') or name,
                'doc':m.get('docstring') or 'dynamically patched method'}
        self._completion_cache[key]=list(out.values())
        found=result(self._completion_cache[key])
        if found['details']:self.note=f'Kosha graph · {len(found["details"])} patched {typ} method(s)'
        return found
    def merge_completions(self, code, pos, runtime=None, limit=50):
        "Merge live-kernel and Kosha graph completions, preserving runtime order."
        runtime=runtime or {'from':pos,'matches':[]}
        graph=self.completion_patches(code,pos,limit)
        start=min(int(runtime.get('from',pos)),int(graph.get('from',pos)))
        vals=list(dict.fromkeys([*runtime.get('matches',[]),*graph.get('matches',[])]))
        return {'from':start,'matches':vals[:limit],'graph':graph.get('details',[])}
    def status(self):
        k = self._kosha()
        if k is None: return {'ok': False, 'note': self._k_note}
        try: return {'ok': True, **k.status(pyproject=False), 'root': str(k.root)}
        except Exception as e: return {'ok': False, 'note': errstr(e)}
    def _kosha_hits(self, q, limit):
        "Semantic repo + environment results for the coding agent, filtered to paths that still exist."
        k = self._kosha()
        if k is None: return None
        if not self._agent_sync_tried:
            self._agent_sync_tried = True
            try:
                state = k.status(pyproject=False)
                if not state.get('files') or state.get('new_files') or state.get('stale_files'): self._sync()
            except Exception: pass
        try: rows = k.context(q, graph=False, env=True, limit=limit)
        except Exception as e:
            self.note = f'kosha search failed ({type(e).__name__}); literal scan'
            return None
        out = L()
        for r in rows:
            m = r.get('metadata') or {}
            path = str(m.get('path') or '')
            if not path or not Path(path).exists(): continue
            out.append(Hit(path=path, line=int(m.get('lineno') or 1),
                text=(r.get('content') or '').strip().split('\n')[0][:200],
                kind='kosha', symbol=str(m.get('mod_name') or ''),
                package=str(m.get('package') or '')))
        self.backend, self.note = 'kosha', 'semantic repo + installed packages · existing paths only'
        return out
    @staticmethod
    def clean_exts(exts):
        "`['py', '.TS']` -> `{'.py', '.ts'}`. Anything unusable is dropped, not guessed at."
        out = set()
        for raw in (exts if isinstance(exts, (list, tuple, set)) else str(exts or '').split(',')):
            e = str(raw or '').strip().lower().lstrip('*')
            if not e or e in ('.',): continue
            out.add(e if e.startswith('.') else '.' + e)
        return out
    def _within(self, path, roots):
        "Whether a hit belongs to the searched scope. Roots are resolved; hits may not be."
        if not roots: return True
        try: p = Path(path).resolve()
        except OSError: return False
        return any(p == r or r in p.parents for r in roots)
    def _keep(self, hits, exts=(), roots=None):
        "Apply the extension and scope filters to hits an index produced, since Kosha cannot be asked to."
        exts = self.clean_exts(exts)
        roots = [Path(r).resolve() for r in (roots or [])]
        if not exts and not roots: return hits
        def keep(h):
            if exts and Path(h.path).suffix.lower() not in exts: return False
            if h.package or h.kind.startswith('env-'): return True
            return self._within(h.path, roots)
        out = L(h for h in hits if keep(h))
        dropped = len(hits) - len(out)
        if dropped: self.note = f'{self.note} · {dropped} filtered out'.lstrip(' ·')
        return out
    def _scan(self, q, limit, regex=False, exts=(), roots=None):
        "Python fallback when ripgrep is unavailable."
        try: pat = re.compile(q if regex else re.escape(q), re.I)
        except re.error as e:
            self.note = f'bad pattern: {e}'
            return L()
        want = self.clean_exts(exts) or _CODE_SUFFIXES
        scope = [Path(r).resolve() for r in (roots or [])]
        out = L()
        for p in self.fs.walk().filter(lambda p: p.suffix.lower() in want and self._within(p, scope)):
            try:
                if p.stat().st_size > MAX_SCAN_BYTES: continue
                text = p.read_text(encoding='utf-8', errors='ignore')
            except OSError: continue
            for i, line in enumerate(text.split('\n'), 1):
                if pat.search(line):
                    out.append(Hit(path=str(p), line=i, text=line.strip()[:200], kind='scan'))
                    if len(out) >= limit: return out
        return out
    def _rg(self, q, limit, regex=False, exts=(), roots=None, no_ignore=False, cased=False):
        "Fast, current-disk search through rgapi. `no_ignore` reaches into `.venv`."
        try: from rgapi import rg
        except ImportError:
            self.backend, self.note = 'scan', 'ripgrep is not installed; Python fallback'
            return self._scan(q, limit, regex, exts, roots)
        globs = [f'*{e}' for e in sorted(self.clean_exts(exts))]
        kw = dict(case_sensitive=bool(cased), max_filesize=MAX_SCAN_BYTES, timeout_ms=15_000,
                  max_results=limit, skip_dir=['__pycache__'])
        if globs: kw['ext'] = [g[2:] for g in globs]
        if no_ignore: kw['ignore'] = False
        out = L()
        for root in (roots if roots is not None else self.fs.roots):
            try: found = list(rg(q if regex else re.escape(q), root=str(root), **kw))
            except Exception as e:
                self.note = f'ripgrep failed ({errstr(e)}); Python fallback'
                return self._scan(q, limit, regex)
            for m in found:
                if getattr(m, 'kind', 'match') != 'match': continue
                path = Path(m.path)
                out.append(Hit(path=str(path if path.is_absolute() else Path(root)/path),
                    line=int(m.line_number or 1), text=(m.line or '').strip()[:200], kind='rg'))
                if len(out) >= limit:
                    self.backend, self.note = 'rg', f'first {limit} matches on disk'
                    return out
        self.backend, self.note = 'rg', 'ripgrep · current files on disk'
        if globs: self.note += ' · ' + ' '.join(globs)
        return out
    def _indexed_hits(self, rows, kind, score_key=''):
        "Only indexed rows the workspace can actually open; Kosha may index a wider checkout."
        hits = L(self._hit(r, kind, (r.get(score_key) or 0.0) if score_key else 0.0) for r in rows)
        for h in hits: h.path = self._here(h.path) or h.path
        return hits.filter(lambda h: self._covers(h.path))
    def _fts(self, q, limit):
        "Kosha's lexical FTS5 leg only: no embedding and no vector search hidden behind it."
        k = self._kosha()
        if k is None: return None
        try:
            from kosha.core import filt2wh, parseq, pre
            raw, filters = parseq(q)
            fq = pre(raw, wide=True, extract_kw=False)
            rows = k.codedb.t.store.fts_search(fq, _SIM_COLS, 'rank', limit,
                where=filt2wh(filters, 'code'), quote=True)
        except Exception as e:
            self.note = f'kosha FTS failed ({errstr(e)})'
            return None
        self.backend, self.note = 'fts', 'kosha FTS5 · indexed files'
        return self._indexed_hits(rows, 'fts', 'rank')
    def _symbols(self, q, limit):
        "Exact/fuzzy symbol names across this repo and Kosha's shared environment DB."
        k = self._kosha()
        if k is None: return None
        name = (q or '').strip()
        if not re.match(r'^[_A-Za-z][\w.:\\>\-]*$', name):
            self.note = 'symbol names only (letters, digits, _, or namespace separators)'
            return L()
        leaf = re.split(r'::|\\|->|\.', name)[-1]
        like = f'%{leaf}%'
        exact = "json_extract(metadata, '$.name') = ?"
        fuzzy = "json_extract(metadata, '$.name') LIKE ? OR json_extract(metadata, '$.mod_name') LIKE ?"
        try:
            def rows(st, env=False):
                cols = 'content, metadata' + (', package' if env else ', path')
                found = list(st.rows_where(exact, [leaf], select=cols, limit=limit))
                if len(found) < limit:
                    more = st.rows_where(f'NOT ({exact}) AND ({fuzzy})', [leaf, like, like],
                        select=cols, limit=limit - len(found))
                    found.extend(more)
                return found
            rr, er = rows(k.code_st), rows(k.env_st, True)
        except Exception as e:
            self.note = f'Kosha symbol search failed ({errstr(e)})'
            return None
        out = L()
        for row, env in [*((r, False) for r in rr), *((r, True) for r in er)]:
            m = _meta(row)
            out.append(Hit(path=str(m.get('path') or row.get('path') or ''),
                line=int(m.get('lineno') or 1), text=(row.get('content') or '').strip(),
                kind='env-symbol' if env else 'symbol',
                symbol=str(m.get('mod_name') or m.get('name') or ''),
                package=str(row.get('package') or m.get('package') or '')))
        self.backend = 'symbols'
        self.note = f'Kosha metadata · repo + {k.pkgs.count} indexed environment packages'
        return out[:limit]
    def _ann(self, q, limit):
        "Kosha hybrid FTS + HNSW search, used only when the caller explicitly selects ANN."
        k = self._kosha()
        if k is None: return None
        try: rows = k.repo_context(q, ann=True, limit=limit)
        except Exception as e:
            self.note = f'kosha ANN failed ({errstr(e)})'
            return None
        self.backend, self.note = 'ann', 'kosha FTS5 + HNSW embeddings · indexed files'
        return self._indexed_hits(rows, 'ann', 'pagerank')
    @staticmethod
    def _hit(row, kind, score=0.0):
        m = _meta(row)
        return Hit(path=str(_get(row, 'path') or m.get('path') or ''),
            line=int(m.get('lineno') or _get(row, 'lineno') or _get(row, 'line') or 1),
            text=str(_get(row, 'content') or _get(row, 'sig') or '').strip().split('\n')[0][:200],
            kind=kind or _get(row, 'kind') or 'ann',
            symbol=str(m.get('mod_name') or _get(row, 'mod_name') or ''),
            score=float(score if score else (_get(row, '_dist') or _get(row, 'dist') or 0.0)))
    def _anchor(self, path, line):
        "Store rowid covering `path:line`, preferring `Kosha.anchor` when the release has it."
        k = self._kosha(path)
        if k is None:
            self.note = f'{self._k_note}; no vector index'
            return None, None
        if hasattr(k, 'anchor'):
            try:
                key = k.anchor(path, line)
                return (int(key), k.code_st) if key is not None else (None, k.code_st)
            except Exception as e: self.note = f'anchor failed ({errstr(e)})'
        st = k.code_st
        p = Path(path)
        cand = str(p.resolve()) if p.exists() else str(p)
        try:
            rows = list(st.rows_where('path = ?', [cand], select='rowid as rowid, metadata'))
            if not rows:
                rows = list(st.rows_where('path like ?', [f'%/{p.name}'],
                    select='rowid as rowid, metadata'))
        except Exception: return None, st
        best, best_line = None, -1
        for r in rows:
            ln = int(_meta(r).get('lineno') or 0)
            if ln <= line and ln > best_line: best, best_line = r['rowid'], ln
        return best, st
    def _hits_from(self, rows, kind='ann'): return L(self._hit(r, getattr(r, 'kind', None) or kind) for r in (rows or ()))
    def similar(self, path, line=1, limit=15):
        "Code nearest the chunk at `path:line`, reusing the stored vector rather than re-embedding."
        k = self._kosha(path)
        if k is None: return L()
        if hasattr(k, 'similar'):
            try:
                hits = k.similar(path, line, limit=limit, graph=True)
                self.backend, self.note = 'ann', f'{len(hits)} neighbours by embedding distance'
                return self._hits_from(hits, 'ann')
            except Exception as e:
                self.note = f'similarity failed ({errstr(e)})'; return L()
        key, st = self._anchor(path, line)
        if key is None:
            self.note = 'no indexed chunk at that location'; return L()
        try: rows = st.ann_neighbors(key, limit=limit, columns=_SIM_COLS)
        except Exception as e:
            self.note = f'similarity failed ({errstr(e)})'; return L()
        self.backend, self.note = 'ann', f'{len(rows)} neighbours by embedding distance'
        return self._hits_from(rows, 'ann')
    def clusters(self, min_count=None, max_count=None, limit=None):
        "Indexed repo grouped by embedding distance; labels come from litesearch c-TF-IDF."
        k = self._kosha()
        if k is None: return L()
        if hasattr(k, 'code_clusters'):
            try:
                res = k.code_clusters(limit=limit, min_count=min_count, max_count=max_count)
                self.backend, self.note = res.method or 'cluster', res.note
                return L(Cluster(centroid=c.centroid, size=c.size, label=getattr(c, 'label', '') or '',
                    members=self._hits_from(c.members, 'cluster'))
                    for c in (res.clusters or ()))
            except Exception as e:
                self.note = f'clustering failed ({errstr(e)})'; return L()
        try: res = k.code_st.clusters(min_count=min_count, max_count=max_count, columns=_SIM_COLS)
        except Exception as e:
            self.note = f'clustering failed ({errstr(e)})'; return L()
        cs = res.clusters[:limit] if limit else res.clusters
        self.backend, self.note = res.method or 'cluster', res.note
        return L(Cluster(centroid=c.centroid, size=c.size, label=c.label or '',
            members=self._hits_from(c.members, 'cluster')) for c in cs)
    def peers(self, path, line=1, limit=25, min_count=None, max_count=None):
        "The cluster this chunk belongs to; degrades to nearest neighbours when too small."
        k = self._kosha(path)
        if k is None: return L()
        kw = {n: v for n, v in (('min_count', min_count), ('max_count', max_count)) if v is not None}
        if hasattr(k, 'peers'):
            try:
                res = k.peers(path, line, limit=limit, graph=True, **kw)
                self.backend, self.note = res.method or 'cluster', res.note
                return self._hits_from(res.hits, res.method or 'cluster')
            except Exception as e:
                self.note = f'clustering failed ({errstr(e)}); showing nearest neighbours'
                return self.similar(path, line, limit)
        key, st = self._anchor(path, line)
        if key is None:
            self.note = 'no indexed chunk at that location'; return L()
        try: res = st.peers(key, limit=limit, columns=_SIM_COLS, **kw)
        except Exception as e:
            self.note = f'clustering failed ({errstr(e)}); showing nearest neighbours'
            return self.similar(path, line, limit)
        self.backend, self.note = res.method or 'cluster', res.note
        return self._hits_from(res.hits, res.method or 'cluster')
    def _import_alias(self, name, path):
        if not path: return None
        try:
            text = self.fs.read(path); tree = ast.parse(text)
        except Exception: return None
        lines = text.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)): continue
            for alias in node.names:
                if alias.asname != name: continue
                original = alias.name
                line_no = alias.lineno
                source = lines[line_no - 1] if line_no <= len(lines) else ''
                start = len(source.encode()[:alias.col_offset].decode(errors='ignore'))
                end = len(source.encode()[:alias.end_col_offset].decode(errors='ignore'))
                segment = source[start:end]
                column = start + max(0, segment.rfind(name))
                hit = Hit(str(path), line_no, source.strip()[:200], 'definition', name, column=column)
                return original, hit
        return None

    def definitions(self, name, path=None, limit=30, _seen=None):
        "Exact definitions for `name`: Kosha metadata first, live files as fallback."
        name = (name or '').strip()
        if limit <= 0 or not re.match(r'^[_A-Za-z]\w*$', name): return L()
        seen = set(_seen or ())
        key = (str(path or ''), name)
        if key in seen: return L()
        seen.add(key)
        out = L()
        if (k := self._kosha(path)) is not None:
            try:
                rows = k.codedb.t.store.rows_where("json_extract(metadata, '$.name') = ?", [name],
                    select=', '.join(_SIM_COLS), limit=limit)
                out = self._indexed_hits(rows, 'definition')
            except Exception as e: self.note = f'Kosha definition lookup failed ({errstr(e)}); scanning files'
        if not out:
            # ripgrep picks the files that could define it, notebooks' JSON included; only those are parsed
            found = self._rg(rf'(?:def|class)\s+{re.escape(name)}\b', 2000, regex=True, cased=True)
            for p in L(list(dict.fromkeys(h.path for h in found))).map(Path).filter(lambda p: p.suffix.lower() in _CODE_SUFFIXES):
                for hit in self.symbols(p):
                    if hit.symbol == name: out.append(hit)
                    if len(out) >= limit: break
                if len(out) >= limit: break
        alias = self._import_alias(name, path)
        if alias:
            original, binding = alias
            targets = self.definitions(original, path, limit - 1, seen)
            merged = [*targets, binding, *out]
            out = L(dict(((h.path, h.line, h.symbol), h) for h in reversed(merged)).values())[::-1]
        here = str(Path(path).resolve()) if path else ''
        if not alias: out = out.sorted(key=lambda h: (str(Path(h.path).resolve()) != here, h.line))
        self.backend, self.note = ('kosha', 'exact symbol metadata') if out else ('scan', 'no definition found')
        return self._place(out[:limit])
    def usages(self, name, limit=200):
        "Exact on-disk token occurrences; unlike the index this includes unsaved-to-index files."
        name = (name or '').strip()
        if not re.match(r'^[_A-Za-z]\w*$', name): return L()
        return self._place(self._rg(rf'\b{re.escape(name)}\b', limit, regex=True))
    def env_roots(self):
        "The project interpreter's `site-packages`, which the project walk deliberately skips."
        from ..runtime.kernels import project_python
        py = project_python(self.fs.roots)
        if not py: return L()
        lib = Path(py).parent.parent/'lib'
        if not lib.is_dir(): return L()
        return L(p/'site-packages' for p in lib.iterdir() if (p/'site-packages').is_dir())
    def stdlib_root(self):
        "The project interpreter's own library, which a venv's `lib` does not hold. Asked once."
        if (got := getattr(self, '_stdlib', None)) is not None: return got
        from ..runtime.kernels import project_python
        self._stdlib = L()
        if py := project_python(self.fs.roots):
            try:
                r = subprocess.run([py, '-c', 'import sysconfig;print(sysconfig.get_paths()["stdlib"])'], env=clean_env(), stdin=subprocess.DEVNULL,
                                   capture_output=True, text=True, timeout=10)
                if (d := Path(r.stdout.strip() or '.')).is_dir(): self._stdlib = L(d)
            except Exception: pass
        return self._stdlib
    def module_roots(self, path=''):
        "Where a dotted module is looked up: the file's own folder, the environment, the stdlib, the project."
        env = self.env_roots()
        return L(*([Path(path).parent] if path else []), *env, *[r.parent for r in env],
                 *self.stdlib_root(), *self.fs.roots)
    def module_file(self, dotted, path=''):
        "The file a dotted module name names, as a module or as a package's `__init__`."
        dotted = dotted or ''
        up = len(dotted) - len(dotted.lstrip('.'))
        parts = dotted[up:].split('.')
        if not all(re.match(r'^[_A-Za-z]\w*$', p) for p in parts) or (up and not path): return None
        for root in ([self._rel_base(path, up)] if up else self.module_roots(path)):
            base = Path(root).joinpath(*parts)
            for cand in (base.with_suffix('.py'), base/'__init__.py'):
                if cand.is_file(): return cand
        return None
    def module_hit(self, dotted, path=''):
        "A dotted module name as a jump target: its file, opened at the top."
        # Nothing declares a module, so a symbol lookup on `test` finds somebody else's `def test`.
        f = self.module_file(dotted, path)
        return None if f is None else self._file_hit(f, dotted)
    def _file_hit(self, f, dotted, line=1, symbol=''):
        "A file as a jump target; one in `site-packages` carries its package and dotted module."
        env = first(r for r in self.env_roots() if str(f).startswith(str(r)))
        try:
            lines = f.read_text(errors='ignore').split('\n')
            text = lines[line - 1] if line > 1 else first(l for l in lines if l.strip()) or ''
        except Exception: text = ''
        mod = self.env_module(f)
        return Hit(str(f), line, text.strip()[:200], 'env-definition' if env else 'definition',
                   symbol=symbol or dotted, package=(mod or dotted).split('.')[0] if env else '',
                   module=mod or (dotted if env else ''))
    def _rel_base(self, path, level):
        "The folder a `level`-dot relative import starts from."
        base = Path(path).parent
        for _ in range(level - 1): base = base.parent
        return base
    def _rel_file(self, base, parts):
        d = base.joinpath(*parts)
        return first(c for c in (d.with_suffix('.py'), d/'__init__.py') if c.is_file())
    def _imports_at(self, path, line, cell_index):
        "The relative `from` imports spanning `line`; in a notebook, only the clicked cell's."
        try:
            if not _is_nb(path): tree = self._tree(path)
            else: tree = ast.parse(''.join(cell_lines(read_cells(self.fs.read(path))[cell_index]))) if cell_index >= 0 else None
        except Exception: return []
        return [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level and n.lineno <= line <= n.end_lineno] if tree else []
    def relative_target(self, name, path, line, cell_index=-1):
        "The file a relative import under the cursor names, else None; an empty list is a directory with nothing to open."
        if not (path and name and int(line or 0) > 0): return None
        for n in self._imports_at(path, int(line), cell_index):
            base, parts = self._rel_base(path, n.level), (n.module or '').split('.') if n.module else []
            if name in parts:
                parts = parts[:parts.index(name) + 1]
                if (f := self._rel_file(base, parts)) is None:
                    d = base.joinpath(*parts)
                    if not d.is_dir(): continue
                    if (f := first(sorted(d.glob('*.py')))) is None: return L()
                return L(self._file_hit(f, self.env_module(f) or f.stem))
            if (a := first(a for a in n.names if name in (a.name, a.asname) and a.name != '*')) is None: continue
            if not parts:
                if f := self._rel_file(base, [a.name]): return L(self._file_hit(f, self.env_module(f) or f.stem))
            elif f := self._rel_file(base, parts):
                if h := first(h for h in self.symbols(f) if h.symbol == a.name and h.score == 0):
                    return L(self._file_hit(f, self.env_module(f) or f.stem, h.line, a.name))
                if f.name == '__init__.py' and (g := self._rel_file(f.parent, [a.name])): return L(self._file_hit(g, self.env_module(g) or g.stem))
        return None
    def imported_module(self, name, path):
        "The dotted module a file's own imports bind `name` to, when that names a file."
        # `import json` makes `json` a module here whatever `def json` a package has, and the
        # file's imports are the only thing that can say so: a bare cursor carries no dot.
        if not name or (tree := self._tree(path)) is None: return ''
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    if a.asname == name: return a.name
                    if not a.asname and a.name.split('.')[0] == name: return name
            elif isinstance(n, ast.ImportFrom):
                for a in n.names:
                    if (a.asname or a.name) == name:
                        pre = '.' * n.level + (n.module or '')
                        return pre + ('' if pre.endswith('.') else '.') + a.name
        return ''
    def _code_cells(self, text):
        "A notebook's code cells as source strings; nbformat stores a source as a list of lines or as one string."
        return [''.join(cell_lines(c)) for c in (read_cells(text) or []) if str(c.get('cell_type') or 'code') == 'code']
    def _tree(self, path):
        "A file's syntax tree; a notebook's is its code cells parsed one by one, so a `%magic` costs only its own cell."
        if not path: return None
        try: text = self.fs.read(path)
        except Exception: return None
        if not _is_nb(path):
            try: return ast.parse(text)
            except SyntaxError: return None
        try: cells = self._code_cells(text)
        except Exception: return None
        body = []
        for src in cells:
            try: body += ast.parse(src).body
            except SyntaxError: pass
        return ast.Module(body=body, type_ignores=[])
    def absolute_source(self, name, path):
        "The module an absolute `from M import name` in the file names, else ''."
        if not name or (tree := self._tree(path)) is None: return ''
        return first(n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and not n.level and n.module
                     and any((a.asname or a.name) == name for a in n.names)) or ''
    def star_packages(self, path):
        "Top-level packages the file star-imports, in order: where a name it never imports by name comes from."
        if (tree := self._tree(path)) is None: return []
        return list(dict.fromkeys(n.module.split('.')[0] for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and not n.level and n.module and any(a.name == '*' for a in n.names)))
    def installed(self, module):
        "Whether a module's top-level package, namespace packages included, is in the project's `site-packages`."
        top = (module or '').split('.')[0]
        return bool(top) and any((Path(r)/top).is_dir() or (Path(r)/f'{top}.py').is_file() for r in self.env_roots())
    def import_package(self, name, path):
        "The package a file says `name` comes from, so a lookup goes to the one that was imported."
        if not path or not name: return ''
        try: text = self.fs.read(path)
        except Exception: return ''
        if _is_nb(path):
            try: text = '\n'.join(self._code_cells(text))
            except Exception: return ''
        word = re.escape(name)
        if m := re.search(rf'^\s*from\s+([\w.]+)\s+import\s+[^#\n]*\b{word}\b', text, re.M):
            return m.group(1).lstrip('.').split('.')[0]
        if re.search(rf'^\s*import\s+[\w.]*\b{word}\b', text, re.M): return name.split('.')[0]
        return ''
    #: Bundled stubs and vendored copies. Real code answers the question; these repeat it.
    VENDORED = ('/third_party/', 'typeshed', '/dist/dist/', '/site-packages/pip/_vendor/')
    def env_definitions(self, name, limit=12, path=''):
        "Where an installed package defines `name`: Kosha's environment index, else ripgrep."
        name = (name or '').strip()
        if not re.match(r'^[_A-Za-z]\w*$', name): return L()
        if indexed := self.env_symbols(name, limit, path): return indexed
        roots = scan = self.env_roots()
        if not roots: return L()
        if self._kosha(path or None) is not None:
            # the index holds methods too, so a miss is scanned for only in the packages the file names
            tops = [t for t in dict.fromkeys([self.absolute_source(name, path).split('.')[0],
                self.import_package(name, path), *self.star_packages(path)]) if t]
            if not (scan := L(Path(r)/t for r in roots for t in tops if (Path(r)/t).is_dir())): return L()
        word = re.escape(name)
        def hits(pattern):
            return self._rg(pattern, limit, regex=True, exts=('.py', '.pyi'), roots=scan,
                            no_ignore=True, cased=True)
        # column zero first. `def patch(self, ...)` in twelve packages is a method called patch, not
        # the thing that was clicked. An indented definition answers only when nothing else does.
        out = (hits(rf'^(?:async\s+def|def|class)\s+{word}\b|^{word}\s*(?::[^=]+)?=')
               or hits(rf'^\s+(?:async\s+def|def|class)\s+{word}\b'))
        for hit in out:
            hit.kind = 'env-definition'
            root = next((r for r in roots if str(hit.path).startswith(str(r))), None)
            rest = Path(hit.path).relative_to(root) if root else Path(hit.path)
            hit.package, hit.symbol = rest.parts[0].removesuffix('.py'), name
            hit.module = self.env_module(hit.path, roots)
        return self._env_ranked(out, name, path)
    def env_module(self, path, roots=None):
        "The dotted module a `site-packages` file is, so a hit reads `fastcore.basics`."
        p = Path(path)
        for r in (self.env_roots() if roots is None else roots):
            if not str(p).startswith(str(r)): continue
            try: parts = p.relative_to(r).with_suffix('').parts
            except ValueError: continue
            if parts and parts[-1] == '__init__': parts = parts[:-1]
            return '.'.join(parts)
        return ''
    def env_symbols(self, name, limit=12, path=''):
        "Kosha's environment store, which knows the package and the line without guessing; ranked before it is cut to `limit`."
        k = self._kosha(path or None)
        if k is None: return L()
        try:
            rows = list(k.env_st.rows_where("json_extract(metadata, '$.name') = ?", [name],
                select='content, metadata, package', limit=400))
        except Exception as e:
            self.note = f'Kosha environment lookup failed ({errstr(e)}); scanning site-packages'
            return L()
        out, roots, seen = L(), self.env_roots(), set()
        for row in rows:
            m = _meta(row)
            mn, line = str(m.get('mod_name') or ''), int(m.get('lineno') or 1)
            place = self._here(str(m.get('path') or ''))
            # a row indexed from a source checkout or another machine names the copy this project installed
            if not (place and self.env_module(place, roots)) and mn and (got := self._installed_copy(mn, name, roots, line)):
                place, line = got
            if not place or (place, line) in seen: continue
            seen.add((place, line))
            mod = self.env_module(place, roots)
            # a method's mod_name has its class between the module and the name
            nested = bool(mn and mod) and mn.removesuffix(f'.{name}') not in (mod, f'{mod}.__init__')
            out.append(Hit(path=place, line=line,
                text=(row.get('content') or '').strip().split('\n')[0][:200], kind='env-definition',
                symbol=name, score=4.0 if nested else 0.0,
                package=str(row.get('package') or m.get('package') or ''), module=mod))
        if out: self.backend, self.note = 'kosha', f'Kosha environment metadata · {len(out)} packages searched'
        return self._env_ranked(out, name, path)[:limit]
    def _installed_copy(self, mod_name, name, roots, line):
        "The file in `roots` an indexed `mod_name` lives in, with the line `name` is defined on there nearest `line`, or None."
        parts = [p for p in mod_name.split('.') if p != '__init__'][:-1]
        for i in range(len(parts), 0, -1):
            for r in roots:
                base = Path(r).joinpath(*parts[:i])
                if (f := first(c for c in (base.with_suffix('.py'), base/'__init__.py') if c.is_file())) is None: continue
                lines = [h.line for h in self.symbols(f) if h.symbol == name]
                return str(f), (min(lines, key=lambda n: abs(n - line)) if lines else line)
        return None
    def reexported_from(self, pkg, name, path=''):
        "The module a package's `__init__` star-imports or imports `name` from, when that module defines it at top level, else ''."
        f = self.module_file(pkg, path)
        if f is None or f.name != '__init__.py' or (tree := self._tree(f)) is None: return ''
        for n in ast.walk(tree):
            if not (isinstance(n, ast.ImportFrom) and n.level < 2 and any(a.name in ('*', name) for a in n.names)): continue
            if n.module: mod = f'{pkg}.{n.module}' if n.level else n.module
            elif n.level and any(a.name == name for a in n.names): mod = f'{pkg}.{name}'
            else: continue
            if (g := self.module_file(mod, path)) and any(h.symbol == name and h.score == 0 for h in self.symbols(g)): return mod
        return ''
    def _env_ranked(self, hits, name, path):
        "The module the file imported from, its package and the module that package re-exports it from, a package it star-imports, then real code, then the shallowest module."
        src, wanted, stars = self.absolute_source(name, path), self.import_package(name, path), self.star_packages(path)
        reexp = self.reexported_from(src, name, path) if src else ''
        def rank(h):
            pk = {h.package, (h.module or '').split('.')[0]}
            return (bool(src) and h.module != src,
                    bool(wanted) and wanted not in pk, bool(reexp) and h.module != reexp,
                    bool(stars) and not pk & set(stars), h.score > 0,
                    any(x in str(h.path) for x in self.VENDORED),
                    str(h.path).endswith('.pyi'), Path(h.path).name.startswith('_'), len(str(h.path)))
        return hits.sorted(key=rank)
    def at_definition(self, hits, path, line, cell_index=-1):
        "Is the cursor already standing on one of these definitions?"
        if not path or int(line or 0) <= 0: return False
        here = str(Path(path).resolve())
        for h in hits:
            if str(Path(h.path).resolve()) != here: continue
            if h.cell_index >= 0 or cell_index >= 0:
                if h.cell_index == cell_index and int(h.cell_line or 0) == int(line): return True
            elif int(h.line or 0) == int(line): return True
        return False
    def declaration_or_usages(self, name, path=None, line=0, cell_index=-1, limit=30, dotted=''):
        "Where `name` is declared, or who uses it when the cursor is already there. `cell_index` locates a notebook hit; `dotted` is the chain the cursor ends."
        if (hits := self.relative_target(name, path, line, cell_index)) is not None:
            self.backend, self.note = 'module', f'{name} is a relative import'
            return 'definition', hits
        if '.' in (dotted or '') and (m := self.module_hit(dotted, path or '')):
            self.backend, self.note = 'module', f'{dotted} is a module'
            return 'definition', L(m)
        # an absolute import of an installed package says which `name` this is, whatever the project defines
        if (src := self.absolute_source(name, path or '')) and self.installed(src):
            if (m := self.module_hit(f'{src}.{name}', path or '')) and not self.reexported_from(src, name, path or ''):
                self.backend, self.note = 'module', f'{src}.{name} is a module'
                return 'definition', L(m)
            if env := self.env_definitions(name, path=path or ''):
                self.note = f'defined in {env[0].package}, not in this project'
                return 'definition', env
        defs = self.definitions(name, path, limit)
        if defs and not self.at_definition(defs, path, line, cell_index): return 'definition', defs
        if not defs and (m := self.module_hit(self.imported_module(name, path or ''), path or '')):
            self.backend, self.note = 'module', f'{m.module or name} is a module'
            return 'definition', L(m)
        # nothing in the project defines it, so it is either a package's or nobody's. The usages
        # of a name the project only imports are import lines, which is the noise this replaces.
        if not defs and (env := self.env_definitions(name, path=path or '')):
            # the backend is whichever answered, the index or the scan; only the note is ours
            self.note = f'defined in {env[0].package}, not in this project'
            return 'definition', env
        if not defs and (m := self.module_hit(name, path or '')):
            self.backend, self.note = 'module', f'{name} is a module'
            return 'definition', L(m)
        return 'usages', self.usages(name)
    @athreaded
    def async_sync(self, notebooks=True, graph=True):
        "Awaitable index refresh, always executed by fastcore on a worker thread."
        return self._sync(notebooks, graph)
    @threaded(daemon=True)
    def sync(self, notebooks=True, graph=True):
        "Index refresh on a daemon thread; the returned fastcore thread carries its result in `.result`."
        return self._sync(notebooks, graph)
    sync_background = sync
    def _sync(self, notebooks=True, graph=True):
        "Refresh Kosha's repository store, treating each notebook cell as its own chunk."
        try:k=self._make_kosha()
        except Exception as e:return {'ok':False,'note':f'Kosha unavailable ({errstr(e)})'}
        try:
            from kosha.core import code_exts, file_parse
            exts = code_exts + (',.ipynb' if notebooks else '')
            if notebooks: k.update_repo(dir=k.root, exts=exts, verbose=False, embed=True)
            else: k.sync(dir=k.root, pyproject=False, sync_graph=graph, verbose=False)
            def cells(p):
                try: return len(file_parse(Path(p)))
                except Exception: return 0
            indexed = sum(cells(p) for p in self.fs.walk() if notebooks and p.suffix.lower() == '.ipynb')
            if graph and notebooks:
                try: k.graph.sync(dir=k.root, pkgs=[], force=False)
                except Exception: pass
        except Exception as e:
            return {'ok':False,'note':f'Kosha sync failed ({errstr(e)})'}
        self._completion_cache.clear()
        self._agent_sync_tried = True
        graph_note = 'graph enabled' if graph else 'graph unchanged'
        self.backend,self.note='kosha',f'index synced · {graph_note} · {indexed} notebook cells'
        status=k.status(pyproject=False)
        for db in (getattr(k,'codedb',None),getattr(k,'envdb',None),getattr(getattr(k,'graph',None),'db',None)):
            try:
                if db:db.close()
            except Exception:pass
        return {'ok':True,'note':self.note,'status':status,'notebook_cells':indexed}
    def agent_search(self, q, limit=20):
        "Natural-language search for the inline agent: Kosha first, current disk fallback."
        q = (q or '').strip()
        if not q: return L()
        hits = self._kosha_hits(q, limit)
        if hits: return self._place(hits)
        fallback = self._rg(q, limit)
        self.note = f'Kosha returned no existing paths; {self.note}'
        return self._place(fallback)
    ALL_LEGS = ('files', 'symbols', 'rg', 'fts', 'ann')
    @staticmethod
    def hit_key(hit):
        "What makes two hits the same hit, so two engines finding one location merge into one row."
        return (hit.path, int(hit.line), hit.package if hit.kind == 'env-symbol' else '')
    def features(self, source, hit, q, rank=0):
        "Why this hit ranks where it does, as the vector the weights are paid against."
        query, leaf = q.lower(), re.split(r'::|\\|->|\.', q)[-1].lower()
        symbol, text, filename = hit.symbol.lower(), hit.text.lower(), Path(hit.path).name.lower()
        exact = bool(symbol) and symbol.rsplit('.', 1)[-1] == leaf
        return {'leg': source,
            'symbol_exact': float(exact),
            'symbol_part': float(not exact and bool(leaf) and leaf in symbol),
            'text': float(bool(query) and query in text),
            'filename': float(bool(leaf) and leaf in filename),
            'leg_rank': 1.0 / (1 + max(0, int(rank))),
            'demote': -float(bool(DEMOTED.search(hit.path.replace('\\', '/'))))}
    def relevance(self, source, hit, q, rank=0):
        "How `all` ranks one hit, shared so a leg reported on its own scores identically."
        hit.why = self.features(source, hit, q, rank)
        return self.weights.score(hit.why)
    def _files(self, q, limit=40):
        "Workspace paths whose filename or relative path contains `q`."
        query, out = q.casefold(), L()
        for path in self.fs.walk():
            if query not in str(path).casefold(): continue
            out.append(Hit(str(path), 1, Path(path).name, kind='file'))
            if len(out) >= limit: break
        return out

    def _runners(self, q, limit, regex=False, exts=(), roots=None):
        "The `all` legs as callables, each returning hits or None. Only rg can be narrowed."
        return {'files': lambda: self._files(q, limit),
            'rg': lambda: self._rg(q, limit, regex, exts, roots),
            'symbols': lambda: self._symbols(q, limit),
            'fts': lambda: self._fts(q, limit),
            'ann': lambda: self._ann(q, limit)}
    def leg(self, name, q, limit=40, regex=False, exts=(), roots=None):
        "One backend of `all`, scored the way `all` scores it; `(hits, note)`, never raising."
        runners = self._runners(q, limit, regex, exts, roots)
        if name not in runners: return L(), f'unknown search leg {name!r}'
        try: rows = runners[name]()
        except Exception as e: return L(), f'{name} failed: {errstr(e)}'
        if rows is None: return L(), f'{name} unavailable'
        ranks = {id(h): i for i, h in enumerate(rows)}
        hits = self._place(self._keep(L(rows), exts, roots))
        for h in hits:
            h.score = self.relevance(name, h, q, ranks.get(id(h), 0))
            h.sources = [name]
        return L(sorted(hits, key=lambda h: (-h.score, h.path, h.line))), ''
    def _all(self, q, limit, regex=False, legs=None):
        "Search every available leg, narrowed by `legs`, and rank one deduplicated result."
        per = max(12, min(limit, 40))
        runners = self._runners(q, per, regex)
        wanted = L(ifnone(legs, self.ALL_LEGS)).filter(lambda n: n in runners)
        legs, notes = [], []
        for name in wanted:
            try: rows = runners[name]()
            except Exception as e:
                notes.append(f'{name} failed: {errstr(e)}')
                continue
            if rows is None:
                notes.append(f'{name} unavailable')
                continue
            legs.extend((name, rank, h) for rank, h in enumerate(rows))
        merged = {}
        for source, rank, hit in legs:
            key = self.hit_key(hit)
            relevance = self.relevance(source, hit, q, rank)
            if key not in merged or relevance > merged[key][0]:
                old_sources = merged[key][1].sources if key in merged else []
                hit.sources = list(dict.fromkeys([*old_sources, source]))
                hit.score = relevance
                merged[key] = (relevance, hit)
            else:
                merged[key][1].sources = list(dict.fromkeys([*merged[key][1].sources, source]))
        out = L(row[1] for row in sorted(merged.values(), key=lambda row: (-row[0], row[1].path, row[1].line)))
        self.backend = 'all'
        used = sorted({source for source, _, _ in legs})
        self.note = (' + '.join(used) if used else 'no available search backend')
        if notes and not used: self.note += ' · ' + '; '.join(notes[:2])
        return out[:limit]
    def search(self, q, limit=60, regex=False, force_scan=False, mode='rg', exts=(), roots=None, legs=None):
        "Search explicitly: ripgrep by default, optional Kosha FTS or ANN. Mode is never inferred."
        q = (q or '').strip()
        if not q: return L()
        if force_scan: mode = 'rg'
        if mode == 'all': return self._place(self._keep(self._all(q, limit, regex, legs), exts, roots))
        indexed = {'context': self._context, 'repo': self._repo_context, 'env': self._env_context,
            'fts': self._fts, 'ann': self._ann, 'symbols': self._symbols}
        if mode in indexed:
            hits = indexed[mode](q, limit)
            if hits is None: return L()
            return self._place(self._keep(hits, exts, roots))
        return self._place(self._rg(q, limit, regex, exts, roots))
    def symbols(self, path):
        "Defs and classes in one file, methods included. `score` carries the indent depth for the UI."
        if _is_nb(path): return self._nb_symbols(path)
        try: text = self.fs.read(path)
        except Exception: return L()
        out = L()
        for i, line in enumerate(text.split('\n'), 1):
            if (m := _DEF_RE.match(line)):
                out.append(Hit(path=str(path), line=i, text=line.strip()[:200],
                    kind='symbol', symbol=m.group(3), score=float(len(m.group(1))), column=m.start(3)))
        return out
    def _nb_symbols(self, path):
        "Defs and classes in a notebook's code cells, addressed by cell *and* by file line."
        try: text = self.fs.read(path)
        except Exception: return L()
        cells = read_cells(text)
        if cells is None: return L()
        spans, out = source_spans(text, cells), L()
        for i, (cell, span) in enumerate(zip(cells, spans)):
            if str(cell.get('cell_type') or 'code') != 'code': continue
            cid = str(cell.get('id') or '')
            if not span and not cid: continue
            for n, line in enumerate(cell_lines(cell), 1):
                if (m := _DEF_RE.match(str(line))):
                    out.append(Hit(path=str(path), line=(span[0] + n - 1) if span else 0,
                        text=str(line).strip()[:200], kind='symbol', symbol=m.group(3),
                        score=float(len(m.group(1))), cell=cid, cell_index=i, cell_line=n, column=m.start(3)))
        return out
    def _place(self, hits):
        "Give every notebook hit the cell and in-cell line that make it openable."
        cache = {}
        for h in hits:
            if not _is_nb(h.path) or h.cell_index >= 0: continue
            if h.path not in cache:
                try: text = self.fs.read(h.path)
                except Exception: text = ''
                cells = read_cells(text)
                cache[h.path] = (text, cells, source_spans(text, cells) if cells else None)
            text, cells, spans = cache[h.path]
            at = cell_at(text, h.line, cells, spans) if int(h.line or 0) > 1 else None
            if at is None: at = cell_of(text, h.text, cells, spans)
            if at is None: continue
            h.cell, h.cell_index, h.cell_line = at['id'], at['index'], at['line']
            if int(h.line or 0) <= 1 and at['file_line']: h.line = at['file_line']
        return hits
