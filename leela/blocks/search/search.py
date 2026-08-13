"""Predictable human search, semantic agent search.

The browser's default searches current files with ``rg`` and therefore sees unsaved-to-index
edits; its FTS and ANN modes activate only when a person explicitly selects them. The inline
coding agent has a different contract: its natural-language query goes through Kosha's repo +
environment context first, then falls back to current files when the index has no live result.
Every result reports its backend.
"""

from __future__ import annotations
import json, re, shutil, subprocess
from dataclasses import dataclass, field
import numpy as np
from fastcore.all import L, Path
from fastcore.aio import athreaded
from fastcore.parallel import threaded

from ... import Dictable, errstr
from ..fs.fs import LANGS
from ..nb.spans import cell_at, cell_lines, cell_of, read_cells, source_spans

__all__ = ['Hit', 'Cluster', 'Search']

_CODE_SUFFIXES = frozenset(LANGS) | {'.txt', '.rst', '.cfg', '.ini'}
MAX_SCAN_BYTES = 2_000_000

# One pattern for every outline, notebook or not, so a method in a cell nests exactly as a
# method in a module does -- group 1 is the indent the UI reads as depth.
_DEF_RE = re.compile(r'^(\s*)(?:async\s+)?(def|class)\s+(\w+)')

def _is_nb(path): return str(path).lower().endswith('.ipynb')

# usearch builds clusters out of the HNSW graph's upper levels, so a small index has
# no structure to cut and raises outright. Measured: ~300 vectors still fails, ~1000
# succeeds. Below this we do not even try, and fall back to plain k-NN.
MIN_CLUSTERABLE = 1000


def _receiver(code, pos):
    "`(type_name, typed_fragment, replace_from)` for an attribute expression at `pos`."
    before=(code or '')[:pos]
    m=re.search(r'([_A-Za-z]\w*)\.([_A-Za-z]\w*)$', before)
    if not m: return '', '', pos
    obj,frag=m.groups(); typ=''
    # `p: Path`, `p = Path(...)`, and a class name used directly cover the useful
    # static cases without executing incomplete editor input.
    pats=(rf'\b{re.escape(obj)}\s*:\s*([_A-Za-z]\w*)',
          rf'\b{re.escape(obj)}\s*=\s*([_A-Za-z]\w*)\s*\(')
    for pat in pats:
        if ms:=re.findall(pat,before): typ=ms[-1]
    if not typ and obj[:1].isupper(): typ=obj
    return typ,frag,m.start(2)


def _meta(row):
    "Chunk metadata as a dict. kosha's `repo_context` decodes the JSON column; raw row reads do not."
    m = row.get('metadata') or {}
    if isinstance(m, str):
        try: m = json.loads(m)
        except Exception: m = {}
    return m or {}


@dataclass
class Hit(Dictable):
    """One search result. `line` is 1-indexed; `kind` names the backend that produced it.

    A hit in a notebook needs three more numbers, because `line` there is a line of JSON and
    there is no editor showing the file: `cell` and `cell_index` say which cell to select and
    `cell_line` where to go inside it. `cell` is empty for a notebook older than nbformat 4.5,
    whose cells have no ids, which is why the index is carried as well. All three stay at their
    defaults for an ordinary file and for a notebook hit that could not be placed -- an
    unplaceable hit says so instead of sending the reader to a line chosen at random.
    """
    path: str
    line: int
    text: str
    kind: str = 'scan'
    symbol: str = ''
    score: float = 0.0
    callers: list = None
    package: str = ''
    sources: list = field(default_factory=list)  # backends that independently found this location
    cell: str = ''
    cell_index: int = -1
    cell_line: int = 0


@dataclass
class Cluster:
    'One ANN cluster: a centroid key, how many chunks it holds, and a sample of them.'
    centroid: int
    size: int
    members: list = field(default_factory=list)

    @property
    def label(self):
        "A name for the cluster: the shortest symbol in it usually reads as the family name."
        syms = [m.symbol.rsplit('.', 1)[-1] for m in self.members if m.symbol]
        return min(syms, key=len) if syms else f'cluster {self.centroid}'

    @property
    def files(self):
        "Distinct files the cluster spans -- a cluster crossing many files is the interesting kind."
        return sorted({m.path for m in self.members})

    def dict(self):
        return {'centroid': self.centroid, 'size': self.size, 'label': self.label,
                'files': self.files, 'members': [m.dict() for m in self.members]}


class Search:
    "Human search uses explicit modes; inline-agent search uses Kosha with an rg fallback."

    def __init__(self, sandbox, prefer_kosha=True):
        self.fs = sandbox
        self.prefer_kosha = prefer_kosha
        self._k = None
        self._k_tried = False
        self._k_note = 'kosha not tried yet'   # why the index is unavailable, remembered across calls
        self.backend = 'scan'
        self.note = ''
        self._completion_cache = {}  # (receiver type, imported packages) -> patch detail rows
        self._agent_sync_tried = False # first agent retrieval refreshes stale repo/notebook chunks once

    # -- kosha ---------------------------------------------------------------
    def _make_kosha(self):
        "A fresh Kosha handle: separate SQLite connections for readers and the sync writer."
        from kosha import Kosha
        root=self.fs.roots[0] if self.fs.roots else None
        k=Kosha(dir=root,install_skill=False)
        k.status(pyproject=False)
        return k

    def _kosha(self):
        """The kosha handle, or None. Tried once: a failure here means no model or no
        index, and retrying it on every keystroke would stall the search box."""
        if self._k_tried: return self._k
        self._k_tried = True
        if not self.prefer_kosha:
            self._k_note = 'kosha disabled'
            return None
        try:
            # Deferred on purpose. kosha is a hard dependency, so this cannot fail for
            # want of a package -- but importing it pulls in the embedding stack, which
            # measurably slows every IDE launch for a feature most sessions never touch.
            # A packaged app's cwd is its launcher directory, not the project. Keep the
            # repository DB workspace-local and Kosha's environment DB shared through XDG.
            k=self._make_kosha()
            self._k = k
            self.backend, self.note = 'kosha', 'repo + installed packages'
        except Exception as e:
            self._k_note = f'kosha unavailable ({errstr(e)})'
            self.note = self._k_note + '; literal scan'
        return self._k

    def _context_rows(self, rows, default_kind='context'):
        out = L()
        for row in rows:
            m = _meta(row)
            path = str(m.get('path') or row.get('path') or '')
            try: local = bool(path) and self.fs.covers(Path(path).resolve())
            except Exception: local = False
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
        try: rows = k.repo_context(q, columns='content,path,metadata', limit=limit)
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
        k = self._kosha()
        if k is None or not package: return []
        try: return [dict(r) for r in k.public_api(package)]
        except Exception as e: self.note = f'package API failed ({errstr(e)})'; return []

    def completion_patches(self, code, pos, limit=50):
        """Methods dynamically patched onto the receiver type, from Kosha's code stores.

        Runtime completion remains authoritative. This fills its blind spot when a package
        adds methods dynamically (fastcore's `@patch`, for example) but that package or patch
        module has not yet been imported into the live kernel.
        """
        typ,frag,start=_receiver(code,pos)
        if not typ: return {'from':start,'matches':[],'details':[]}
        k=self._kosha()
        if k is None: return {'from':start,'matches':[],'details':[]}
        rows=[]
        # Kosha's graph-aware public API includes @patch-derived methods. The annotation
        # query also handles an index whose graph predates those patch edges.
        packages=set(re.findall(r'^\s*(?:from|import)\s+([\w.]+)',code or '',re.M))
        packages={p.split('.')[0] for p in packages}
        key=(typ,tuple(sorted(packages)))
        cached=self._completion_cache.get(key)
        if cached is not None:
            details=[x for x in cached if not frag or x['name'].startswith(frag)][:limit]
            return {'from':start,'matches':[x['name'] for x in details],'details':details}
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
            # Public API rows can contain ordinary functions; an explicit receiver
            # annotation is the proof it belongs after this dot.
            if content and not re.search(rf'^def\s+{re.escape(name)}\s*\(self\s*:\s*{re.escape(typ)}\b',content): continue
            if not name or name.startswith('_'): continue
            out[name]={'name':name,'type':typ,'symbol':m.get('mod_name') or name,
                       'doc':m.get('docstring') or 'dynamically patched method'}
        all_details=list(out.values())
        self._completion_cache[key]=all_details
        details=[x for x in all_details if not frag or x['name'].startswith(frag)][:limit]
        if details:self.note=f'Kosha graph · {len(details)} patched {typ} method(s)'
        return {'from':start,'matches':[x['name'] for x in details],'details':details}

    def merge_completions(self, code, pos, runtime=None, limit=50):
        "Merge live-kernel and Kosha graph completions, preserving runtime order."
        runtime=runtime or {'from':pos,'matches':[]}
        graph=self.completion_patches(code,pos,limit)
        start=min(int(runtime.get('from',pos)),int(graph.get('from',pos)))
        vals=[]
        for x in [*runtime.get('matches',[]),*graph.get('matches',[])]:
            if x not in vals: vals.append(x)
        return {'from':start,'matches':vals[:limit],'graph':graph.get('details',[])}

    def status(self):
        k = self._kosha()
        if k is None: return {'ok': False, 'note': self._k_note}
        try: return {'ok': True, **k.status(pyproject=False), 'root': str(k.root)}
        except Exception as e: return {'ok': False, 'note': errstr(e)}

    def _kosha_hits(self, q, limit):
        """Semantic repo + environment results for the coding agent.

        The interactive search box deliberately defaults to rg, but an agent's natural-language
        request is not a literal pattern. Only return paths that still exist so a stale index can
        never teach the model to invent a nearby path. The first agent retrieval also brings a
        missing/stale repository index current, including notebook cells; otherwise a fresh
        workspace silently falls through to literal search before Kosha has ever seen a file.
        """
        k = self._kosha()
        if k is None: return None
        if not self._agent_sync_tried:
            self._agent_sync_tried = True
            try:
                state = k.status(pyproject=False)
                if not state.get('files') or state.get('new_files') or state.get('stale_files'):
                    self._sync(notebooks=True, graph=True)
            except Exception: pass
        try: rows = k.context(q, graph=True, env=True, limit=limit)
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
                           score=float(r.get('pagerank') or 0.0),
                           callers=[str(c) for c in (r.get('callers') or [])][:5],
                           package=str(m.get('package') or '')))
        self.backend, self.note = 'kosha', 'semantic repo + installed packages · existing paths only'
        return out

    # -- scope and extensions ------------------------------------------------
    @staticmethod
    def clean_exts(exts):
        """`['py', '.TS']` -> `{'.py', '.ts'}`. Anything unusable is dropped, not guessed at.

        Accepting both spellings because a person types `py` and a glob says `*.py`, and being
        strict about the dot would only ever produce an empty result set with no explanation.
        """
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
        """Apply the extension and scope filters to hits an index produced.

        Applied *after* the fact for the indexed backends because Kosha answers about its whole
        corpus and cannot be asked to narrow. `_rg` gets the same restrictions as arguments
        instead, where ripgrep can act on them and skip the files entirely.
        """
        exts = self.clean_exts(exts)
        roots = [Path(r).resolve() for r in (roots or [])]
        if not exts and not roots: return hits

        def keep(h):
            if exts and Path(h.path).suffix.lower() not in exts: return False
            # An installed package lives outside every open folder by definition, so narrowing
            # the scope must never reach it: `merge dict` has to keep answering with
            # `fastcore.basics.merge` whether or not the search is confined to this checkout.
            # Scope is about which of *your* checkouts to look in, not about excluding the
            # environment -- that is what the mode buttons are for.
            if h.package or h.kind.startswith('env-'): return True
            return self._within(h.path, roots)

        out = L(h for h in hits if keep(h))
        dropped = len(hits) - len(out)
        if dropped: self.note = f'{self.note} · {dropped} filtered out'.lstrip(' ·')
        return out

    # -- literal search ------------------------------------------------------
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

    def _rg(self, q, limit, regex=False, exts=(), roots=None):
        """Fast, current-disk search. JSON output keeps colons and non-UTF8 paths unambiguous.

        `roots` narrows *which* folders are walked at all, rather than filtering the results
        afterwards -- with one checkout of any size that is the difference between a search that
        answers and one that times out. Extensions become `--glob` for the same reason.
        """
        exe = shutil.which('rg')
        if not exe:
            self.backend, self.note = 'scan', 'ripgrep is not installed; Python fallback'
            return self._scan(q, limit, regex, exts, roots)
        globs = [f'*{e}' for e in sorted(self.clean_exts(exts))]
        out = L()
        for root in (roots if roots is not None else self.fs.roots):
            cmd = [exe, '--json', '--ignore-case', '--max-filesize', str(MAX_SCAN_BYTES),
                   '--glob', '!{.git,.hg,.svn,.venv,venv,node_modules,__pycache__,dist,build}/**']
            for g in globs: cmd += ['--glob', g]
            if not regex: cmd.append('--fixed-strings')
            cmd += ['--', q, str(root)]
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            except Exception as e:
                self.note = f'ripgrep failed ({errstr(e)}); Python fallback'
                return self._scan(q, limit, regex)
            if p.returncode not in (0, 1):
                self.note = (p.stderr or 'ripgrep failed').strip()[:200]
                return L()
            for line in p.stdout.splitlines():
                try: msg = json.loads(line)
                except Exception: continue
                if msg.get('type') != 'match': continue
                d = msg.get('data') or {}
                path = (d.get('path') or {}).get('text') or ''
                text = (d.get('lines') or {}).get('text') or ''
                out.append(Hit(path=path, line=int(d.get('line_number') or 1),
                               text=text.rstrip('\r\n').strip()[:200], kind='rg'))
                if len(out) >= limit:
                    self.backend, self.note = 'rg', f'first {limit} matches on disk'
                    return out
        self.backend, self.note = 'rg', 'ripgrep · current files on disk'
        if globs: self.note += ' · ' + ' '.join(globs)
        return out

    def _indexed_hits(self, rows, kind, score_key=''):
        "Only indexed rows the workspace can actually open; Kosha may index a wider checkout."
        out = L()
        for row in rows:
            hit = self._hit(row, kind, (row.get(score_key) or 0.0) if score_key else 0.0)
            try: allowed = bool(hit.path) and self.fs.covers(Path(hit.path).resolve())
            except Exception: allowed = False
            if allowed: out.append(hit)
        return out

    def _fts(self, q, limit):
        "Kosha's lexical FTS5 leg only: no embedding and no vector search hidden behind it."
        k = self._kosha()
        if k is None: return None
        try:
            from kosha.core import filt2wh, parseq, pre
            raw, filters = parseq(q)
            fq = pre(raw, wide=True, extract_kw=False)
            rows = k.codedb.t.store.fts_search(
                fq, ['content', 'path', 'metadata'], 'rank', limit, where=filt2wh(filters, 'code'), quote=True)
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
        select = 'content, metadata, path'
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

    # -- ANN: nearest neighbours and cluster peers ---------------------------
    def _store(self):
        "kosha's repo store and its usearch index, or (None, None). Index keys are store rowids."
        k = self._kosha()
        if k is None:
            # say why *now*, or a stale note from an earlier call answers for us
            self.note = f'{self._k_note}; no vector index'
            return None, None
        try:
            st = k.code_st
            idx = st.db.get_index(st.name)
            if not idx.size: self.note = 'vector index is empty; run kosha sync'
            return (st, idx) if idx.size else (st, None)
        except Exception as e:
            self.note = f'no vector index ({errstr(e)})'
            return None, None

    @staticmethod
    def _rows(st, keys):
        "Store rows for a list of usearch keys (rowids), keyed by rowid."
        if not keys: return {}
        ks = ','.join(str(int(k)) for k in keys)
        rows = st.rows_where(f'rowid in ({ks})', select='rowid as rowid, content, metadata, path')
        return {r['rowid']: r for r in rows}

    @staticmethod
    def _hit(row, kind, score=0.0):
        m = _meta(row)
        return Hit(path=str(row.get('path') or m.get('path') or ''),
                   line=int(m.get('lineno') or 1),
                   text=(row.get('content') or '').strip().split('\n')[0][:200],
                   kind=kind, symbol=str(m.get('mod_name') or ''), score=float(score))

    def _anchor(self, path, line):
        """The store rowid whose chunk covers `path:line`, plus the store and index behind it.

        Every similarity query starts here, so the three lookups are done once together
        rather than each caller re-opening the store. Key is None when nothing covers it.
        """
        st, idx = self._store()
        if st is None: return None, None, None
        try: rows = st.rows_where('path = ?', [str(path)], select='rowid as rowid, metadata')
        except Exception: return None, None, None
        best, best_line = None, -1
        for r in rows:
            ln = int(_meta(r).get('lineno') or 0)
            if ln <= line and ln > best_line: best, best_line = r['rowid'], ln
        return best, st, idx

    @staticmethod
    def _cluster(idx, min_count, max_count):
        "usearch clustering with only the bounds the caller actually set."
        return idx.cluster(**{k: v for k, v in (('min_count', min_count), ('max_count', max_count)) if v})

    def similar(self, path, line=1, limit=15):
        """Functions nearest this one in embedding space -- 'what else looks like this'.

        Straight k-NN over kosha's HNSW index: take the vector already stored for the
        chunk covering `path:line` and ask usearch for its neighbours. No re-embedding,
        so this is cheap enough to run from a keystroke.
        """
        key, st, idx = self._anchor(path, line)
        if key is None:
            self.note = 'no indexed chunk at that location'
            return L()
        if idx is None: return L()
        try:
            res = idx.search(idx[key], count=limit + 1)
            rkeys = np.atleast_1d(res.keys).tolist()
            dists = dict(zip(rkeys, np.atleast_1d(res.distances).tolist()))
            keys = [k for k in rkeys if k != key][:limit]
        except Exception as e:
            self.note = f'similarity failed ({errstr(e)})'
            return L()
        rows = self._rows(st, keys)
        self.backend, self.note = 'ann', f'{len(keys)} neighbours by embedding distance'
        return self._place(L(self._hit(rows[k], 'ann', dists.get(k, 0.0)) for k in keys if k in rows))

    def clusters(self, min_count=None, max_count=None):
        """Cluster the whole indexed corpus with usearch, returning `Cluster`s.

        usearch clusters by cutting the HNSW graph's upper levels rather than running
        k-means, which is what makes it fast enough to do over a whole codebase. It
        needs a graph with levels to cut, so a small index raises `Index too small to
        cluster!` -- guarded here rather than left to surface as a crash.
        """
        st, idx = self._store()
        if idx is None: return L()
        if idx.size < MIN_CLUSTERABLE:
            self.note = f'index has {idx.size} chunks; clustering needs ~{MIN_CLUSTERABLE}'
            return L()
        try: cl = self._cluster(idx, min_count, max_count)
        except Exception as e:
            self.note = f'clustering failed ({errstr(e)})'
            return L()
        centroids, sizes = cl.centroids_popularity
        out = L()
        for c, n in zip(np.atleast_1d(centroids).tolist(), np.atleast_1d(sizes).tolist()):
            members = np.atleast_1d(cl.members_of(c)).tolist()
            rows = self._rows(st, members[:40])
            out.append(Cluster(centroid=c, size=n,
                               members=L(self._hit(rows[m], 'cluster') for m in members[:40] if m in rows)))
        self.backend, self.note = 'cluster', f'{len(out)} clusters over {idx.size} chunks'
        return out.sorted(key=lambda c: -c.size)

    def peers(self, path, line=1, limit=25, min_count=None, max_count=None):
        """The cluster this function belongs to -- its family, not a ranked list.

        k-NN answers "the 10 closest things"; a cluster answers "the group this belongs
        to", which is the more useful question when you are looking for every place a
        pattern was already implemented. Falls back to `similar()` when the index is too
        small to cluster, so the feature degrades instead of disappearing.
        """
        key, st, idx = self._anchor(path, line)
        if key is None:
            self.note = 'no indexed chunk at that location'
            return L()
        if idx is None or idx.size < MIN_CLUSTERABLE:
            if idx is not None: self.note = f'index too small to cluster ({idx.size}); showing nearest neighbours'
            return self.similar(path, line, limit)
        try:
            cl = self._cluster(idx, min_count, max_count)
            # queries[i] is a point, matches.keys[i] its centroid: one pass gives the whole map
            assign = dict(zip(np.atleast_1d(cl.queries).tolist(),
                              np.atleast_1d(cl.matches.keys).flatten().tolist()))
        except Exception as e:
            self.note = f'clustering failed ({type(e).__name__}); showing nearest neighbours'
            return self.similar(path, line, limit)
        centroid = assign.get(key)
        if centroid is None:
            self.note = 'chunk is not in any cluster; showing nearest neighbours'
            return self.similar(path, line, limit)
        members = [m for m in np.atleast_1d(cl.members_of(centroid)).tolist() if m != key][:limit]
        rows = self._rows(st, members)
        self.backend = 'cluster'
        self.note = f'cluster {centroid} · {len(members) + 1} members'
        return self._place(L(self._hit(rows[m], 'cluster') for m in members if m in rows))

    # -- code intelligence ---------------------------------------------------
    def definitions(self, name, path=None, limit=30):
        """Exact definitions for ``name``: Kosha metadata first, live files as fallback."""
        name = (name or '').strip()
        if not re.match(r'^[_A-Za-z]\w*$', name): return L()
        out = L()
        if (k := self._kosha()) is not None:
            try:
                rows = k.codedb.t.store.rows_where(
                    "json_extract(metadata, '$.name') = ?", [name],
                    select='content, metadata, path', limit=limit)
                out = self._indexed_hits(rows, 'definition')
            except Exception as e: self.note = f'Kosha definition lookup failed ({errstr(e)}); scanning files'
        if not out:
            for p in self.fs.walk().filter(lambda p: p.suffix.lower() in _CODE_SUFFIXES):
                for hit in self.symbols(p):
                    if hit.symbol == name: out.append(hit)
                    if len(out) >= limit: break
                if len(out) >= limit: break
        # Definitions in the current file are overwhelmingly the intended target, then
        # nearest definitions in that file, then the graph's cross-file candidates.
        here = str(Path(path).resolve()) if path else ''
        out = out.sorted(key=lambda h: (str(Path(h.path).resolve()) != here, h.line))
        self.backend, self.note = ('kosha', 'exact symbol metadata + code graph') if out else ('scan', 'no definition found')
        return self._place(out[:limit])

    def usages(self, name, limit=200):
        """Exact on-disk token occurrences; unlike the index this includes unsaved-to-index files."""
        name = (name or '').strip()
        if not re.match(r'^[_A-Za-z]\w*$', name): return L()
        return self._place(self._rg(rf'\b{re.escape(name)}\b', limit, regex=True))

    @athreaded
    def async_sync(self, notebooks=True, graph=True):
        "Awaitable index refresh, always executed by fastcore on a worker thread."
        return self._sync(notebooks, graph)

    @threaded(daemon=True)
    def sync(self, notebooks=True, graph=True):
        """Start an index refresh on a dedicated daemon thread and return that thread.

        Kosha can import an embedder, walk a repository, embed notebooks and rebuild a
        graph. None of that belongs on the UI loop or the user's kernel thread.
        The returned fastcore thread receives its result in `.result` when complete.
        """
        return self._sync(notebooks, graph)

    sync_background = sync

    def _sync(self, notebooks=True, graph=True):
        "Refresh Kosha's repository store, treating each notebook cell as its own chunk."
        # Never sync through the reader handle. litesearch uses WAL, so a dedicated
        # writer connection can commit while the long-lived reader keeps serving the
        # previous snapshot; new searches see commits as their read transactions begin.
        try:k=self._make_kosha()
        except Exception as e:return {'ok':False,'note':f'Kosha unavailable ({errstr(e)})'}
        try:
            from kosha.core import code_exts, file_parse
            # Widen Kosha's repository pass to notebooks, which are intentionally absent
            # from its default code_exts. Environment packages live in Kosha's shared DB
            # and are refreshed separately; syncing a project must not re-embed the world.
            exts = code_exts + (',.ipynb' if notebooks else '')
            # Kosha's own update path scopes the hash diff by file while preserving every
            # content hash. A manual `key_col="path"` upsert here used to collapse notebook
            # cells and could remove code chunks belonging to the same sync scope.
            if notebooks: k.update_repo(dir=k.root, exts=exts, verbose=False, embed=True)
            else: k.sync(dir=k.root, pyproject=False, in_parallel=True,
                         sync_graph=graph, verbose=False)
            indexed = sum(len(file_parse(Path(p))) for p in self.fs.walk()
                          if notebooks and p.suffix.lower() == '.ipynb')
            if graph and notebooks:
                try: k.graph.sync(dir=k.root, pkgs=[], force=False)
                except Exception: pass       # semantic chunks remain useful without graph edges
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

    # -- api -----------------------------------------------------------------
    def agent_search(self, q, limit=20):
        """Natural-language search for the inline agent: Kosha first, current disk fallback.

        This is separate from ``search`` because a human's search box must remain predictable
        (rg unless they select FTS/ANN), while the coding agent needs semantic retrieval before
        it knows the exact symbol or filename.
        """
        q = (q or '').strip()
        if not q: return L()
        hits = self._kosha_hits(q, limit)
        if hits: return self._place(hits)
        fallback = self._rg(q, limit)
        self.note = f'Kosha returned no existing paths; {self.note}'
        return self._place(fallback)

    def _all(self, q, limit, regex=False):
        "Search every available leg and rank one deduplicated result set."
        per = max(12, min(limit, 40))
        legs, notes = [], []
        for name, fn in (
            ('rg', lambda: self._rg(q, per, regex)),
            ('symbols', lambda: self._symbols(q, per)),
            ('fts', lambda: self._fts(q, per)),
            ('ann', lambda: self._ann(q, per)),
        ):
            try: rows = fn()
            except Exception as e:
                notes.append(f'{name} failed: {errstr(e)}')
                continue
            if rows is None:
                notes.append(f'{name} unavailable')
                continue
            legs.extend((name, h) for h in rows)

        query, leaf = q.lower(), re.split(r'::|\\|->|\.', q)[-1].lower()
        priority = {'symbols': 100, 'rg': 80, 'fts': 60, 'ann': 40}
        merged = {}
        for source, hit in legs:
            # Environment symbols have no workspace path to open, so package participates
            # in identity. Repo hits deduplicate when multiple engines found one location.
            key = (hit.path, int(hit.line), hit.package if hit.kind == 'env-symbol' else '')
            symbol, text, filename = hit.symbol.lower(), hit.text.lower(), Path(hit.path).name.lower()
            relevance = priority[source]
            if symbol and symbol.rsplit('.', 1)[-1] == leaf: relevance += 120
            elif leaf and leaf in symbol: relevance += 55
            if query and query in text: relevance += 40
            if leaf and leaf in filename: relevance += 20
            # Preserve an ANN/FTS score only as a small tie-breaker; their scales differ.
            relevance += min(10.0, abs(float(hit.score or 0.0)))
            if key not in merged or relevance > merged[key][0]:
                old_sources = merged[key][1].sources if key in merged else []
                hit.sources = list(dict.fromkeys([*old_sources, source]))
                hit.score = relevance
                merged[key] = (relevance, hit)
            else:
                merged[key][1].sources = list(dict.fromkeys([*merged[key][1].sources, source]))
        out = L(row[1] for row in sorted(merged.values(), key=lambda row: (-row[0], row[1].path, row[1].line)))
        self.backend = 'all'
        used = sorted({source for source, _ in legs})
        self.note = (' + '.join(used) if used else 'no available search backend')
        if notes and not used: self.note += ' · ' + '; '.join(notes[:2])
        return out[:limit]

    def search(self, q, limit=60, regex=False, force_scan=False, mode='rg', exts=(), roots=None):
        """Search explicitly: ripgrep by default, optional Kosha FTS or ANN.

        Search mode is never inferred from query length. That old policy made the same box
        silently switch corpora and ranking algorithms while a person typed. `rg` is simple,
        sees current files, and always wins unless the caller deliberately asks for an index.

        `exts` and `roots` narrow *what is searched* without changing which backend answers, so
        "only .py" and "only this checkout" mean the same thing in every mode. `roots` is the
        caller's to decide and is never taken from the browser directly: the sandbox is still the
        boundary, and this is a scope inside it. `env` is exempt from the scope, because installed
        packages live outside every root by definition and narrowing them to one would return
        nothing at all.
        """
        q = (q or '').strip()
        if not q: return L()
        if force_scan: mode = 'rg'
        # rg is asked to narrow; the index backends are told about it afterwards.
        if mode == 'rg': return self._place(self._rg(q, limit, regex, exts, roots))
        if mode == 'all': return self._place(self._keep(self._all(q, limit, regex), exts, roots))
        legs = {'context': self._context, 'repo': self._repo_context, 'env': self._env_context,
                'fts': self._fts, 'ann': self._ann, 'symbols': self._symbols}
        if mode in legs:
            hits = legs[mode](q, limit)
            if hits is None: return L()
            # Every mode passes the scope: `_keep` exempts package hits per *hit*, which is more
            # precise than exempting a whole mode -- `context` returns both kinds at once.
            return self._place(self._keep(hits, exts, roots))
        return self._place(self._rg(q, limit, regex, exts, roots))

    def symbols(self, path):
        """Defs and classes in one file, for an outline. Methods are included, not just
        top-level names -- an outline that stops at the class line is not an outline.
        `score` carries the indent depth so the UI can nest them."""
        if _is_nb(path): return self._nb_symbols(path)
        try: text = self.fs.read(path)
        except Exception: return L()
        out = L()
        for i, line in enumerate(text.split('\n'), 1):
            if (m := _DEF_RE.match(line)):
                out.append(Hit(path=str(path), line=i, text=line.strip()[:200],
                               kind='symbol', symbol=m.group(3), score=float(len(m.group(1)))))
        return out

    def _nb_symbols(self, path):
        """Defs and classes in a notebook's code cells, addressed by cell as well as by file line.

        A notebook read as text has no symbols at all: the line is `    "def f(x):\\n",` and the
        JSON quote defeats any anchored pattern, which is why every notebook used to look empty
        to ctrl+B, to Find Usages and to the structure panel. So the cells are read as cells and
        each one's source scanned as the code it is.

        Both coordinate systems are reported. The file line keeps callers that think in file
        lines working -- `/similar` anchors a Kosha chunk that way, and a diff is still of the
        file -- while the cell and the line inside it are what an editor can actually open.
        A cell whose file lines cannot be found is still returned when it has an id, because the
        cell coordinates are exact and only the file line is unknown; a cell with neither is
        dropped, since nothing could be done with it.
        """
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
                                   score=float(len(m.group(1))), cell=cid, cell_index=i, cell_line=n))
        return out

    def _place(self, hits):
        """Give every notebook hit the cell and in-cell line that make it openable.

        Any backend can return a hit in a `.ipynb` and none of them knows what a notebook is:
        ripgrep matched a line of JSON, and Kosha chunks a notebook by cell but records no line
        at all, so all of its notebook rows arrive as line 1. Both are corrected here, in one
        place, rather than in each of the five legs -- a hit only becomes openable at the point
        it is about to be handed to the browser.

        A line inside a cell's source is mapped by position; a hit with no usable line is placed
        by its text, and only when exactly one cell contains it. Anything else is left as it came
        in: the reader is shown an unplaced notebook hit rather than a confidently wrong one.
        """
        cache = {}
        for h in hits:
            if not _is_nb(h.path) or h.cell_index >= 0: continue
            if h.path not in cache:
                try: cache[h.path] = self.fs.read(h.path)
                except Exception: cache[h.path] = ''
            text = cache[h.path]
            at = cell_at(text, h.line) if int(h.line or 0) > 1 else None
            if at is None: at = cell_of(text, h.text)
            if at is None: continue
            h.cell, h.cell_index, h.cell_line = at['id'], at['index'], at['line']
            if int(h.line or 0) <= 1 and at['file_line']: h.line = at['file_line']
        return hits
