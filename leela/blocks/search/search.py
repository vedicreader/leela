"Predictable human search (rg unless a mode is picked), semantic agent search, and every hit."

from __future__ import annotations
import json, re, shutil, subprocess
from dataclasses import dataclass, field
from fastcore.all import L, Path, ifnone, store_attr
from fastcore.aio import athreaded
from fastcore.parallel import threaded

from ... import Dictable, errstr
from ..fs.fs import LANGS
from ..nb.nb import cell_at, cell_lines, cell_of, read_cells, source_spans

__all__ = ['Hit', 'Cluster', 'Search']

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
    "Dict or attribute row — kosha returns AttrDict/SimpleNamespace, store rows are dicts."
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
    package: str = ''
    sources: list = field(default_factory=list)
    cell: str = ''
    cell_index: int = -1
    cell_line: int = 0

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
        "Distinct files the cluster spans — a cluster crossing many files is the interesting kind."
        return sorted({m.path for m in self.members})
    def dict(self):
        return {'centroid': self.centroid, 'size': self.size, 'label': self.label,
            'files': self.files, 'members': [m.dict() for m in self.members]}

class Search:
    "Human search uses explicit modes; inline-agent search uses Kosha with an rg fallback."
    def __init__(self, sandbox, prefer_kosha=True):
        store_attr('prefer_kosha', fs=sandbox)
        self._k = None
        self._k_tried = False
        self._k_note = 'kosha not tried yet'
        self.backend = 'scan'
        self.note = ''
        self._completion_cache = {}
        self._agent_sync_tried = False
    def _make_kosha(self):
        "A fresh Kosha handle: separate SQLite connections for readers and the sync writer."
        from kosha import Kosha
        root=self.fs.roots[0] if self.fs.roots else None
        k=Kosha(dir=root,install_skill=False,busy_timeout=30000)
        k.status(pyproject=False)
        return k
    def _kosha(self):
        "The kosha handle, or None. Tried once, since retrying on every keystroke would stall the search."
        if self._k_tried: return self._k
        self._k_tried = True
        if not self.prefer_kosha:
            self._k_note = 'kosha disabled'
            return None
        try:
            k=self._make_kosha()
            self._k = k
            self.backend, self.note = 'kosha', 'repo + installed packages'
        except Exception as e:
            self._k_note = f'kosha unavailable ({errstr(e)})'
            self.note = self._k_note + '; literal scan'
        return self._k
    def _covers(self, path):
        "Whether the sandbox can open an indexed path. Kosha may index a wider checkout."
        try: return bool(path) and self.fs.covers(Path(path).resolve())
        except Exception: return False
    def _context_rows(self, rows, default_kind='context'):
        out = L()
        for row in rows:
            m = _meta(row)
            path = str(m.get('path') or row.get('path') or '')
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
        k = self._kosha()
        if k is None or not package: return []
        try: return [dict(r) for r in k.public_api(package)]
        except Exception as e: self.note = f'package API failed ({errstr(e)})'; return []
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
    def _rg(self, q, limit, regex=False, exts=(), roots=None):
        "Fast, current-disk search. JSON output keeps colons and non-UTF8 paths unambiguous."
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
            try: p = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
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
        hits = L(self._hit(r, kind, (r.get(score_key) or 0.0) if score_key else 0.0) for r in rows)
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
        k = self._kosha()
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
        "Code nearest the chunk at `path:line` — reuses the stored vector, never re-embeds."
        k = self._kosha()
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
        "Indexed repo grouped by embedding shape; labels come from litesearch c-TF-IDF."
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
        k = self._kosha()
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
    def definitions(self, name, path=None, limit=30):
        "Exact definitions for `name`: Kosha metadata first, live files as fallback."
        name = (name or '').strip()
        if not re.match(r'^[_A-Za-z]\w*$', name): return L()
        out = L()
        if (k := self._kosha()) is not None:
            try:
                rows = k.codedb.t.store.rows_where("json_extract(metadata, '$.name') = ?", [name],
                    select=', '.join(_SIM_COLS), limit=limit)
                out = self._indexed_hits(rows, 'definition')
            except Exception as e: self.note = f'Kosha definition lookup failed ({errstr(e)}); scanning files'
        if not out:
            for p in self.fs.walk().filter(lambda p: p.suffix.lower() in _CODE_SUFFIXES):
                for hit in self.symbols(p):
                    if hit.symbol == name: out.append(hit)
                    if len(out) >= limit: break
                if len(out) >= limit: break
        here = str(Path(path).resolve()) if path else ''
        out = out.sorted(key=lambda h: (str(Path(h.path).resolve()) != here, h.line))
        self.backend, self.note = ('kosha', 'exact symbol metadata + code graph') if out else ('scan', 'no definition found')
        return self._place(out[:limit])
    def usages(self, name, limit=200):
        "Exact on-disk token occurrences; unlike the index this includes unsaved-to-index files."
        name = (name or '').strip()
        if not re.match(r'^[_A-Za-z]\w*$', name): return L()
        return self._place(self._rg(rf'\b{re.escape(name)}\b', limit, regex=True))
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
            indexed = sum(len(file_parse(Path(p))) for p in self.fs.walk()
                if notebooks and p.suffix.lower() == '.ipynb')
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
    ALL_LEGS = ('symbols', 'rg', 'fts', 'ann')
    LEG_PRIORITY = {'symbols': 100, 'rg': 80, 'fts': 60, 'ann': 40}
    @staticmethod
    def hit_key(hit):
        "What makes two hits the same hit, so two engines finding one location merge into one row."
        return (hit.path, int(hit.line), hit.package if hit.kind == 'env-symbol' else '')
    def relevance(self, source, hit, q):
        "How `all` ranks one hit, shared so a leg reported on its own scores identically."
        query, leaf = q.lower(), re.split(r'::|\\|->|\.', q)[-1].lower()
        symbol, text, filename = hit.symbol.lower(), hit.text.lower(), Path(hit.path).name.lower()
        relevance = self.LEG_PRIORITY.get(source, 40)
        if symbol and symbol.rsplit('.', 1)[-1] == leaf: relevance += 120
        elif leaf and leaf in symbol: relevance += 55
        if query and query in text: relevance += 40
        if leaf and leaf in filename: relevance += 20
        return relevance + min(10.0, abs(float(hit.score or 0.0)))
    def _runners(self, q, limit, regex=False, exts=(), roots=None):
        "The `all` legs as callables, each returning hits or None. Only rg can be narrowed."
        return {'rg': lambda: self._rg(q, limit, regex, exts, roots),
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
        hits = self._place(self._keep(L(rows), exts, roots))
        for h in hits:
            h.score = self.relevance(name, h, q)
            h.sources = [name]
        return L(sorted(hits, key=lambda h: (-h.score, h.path, h.line))), ''
    def _all(self, q, limit, regex=False, legs=None):
        "Search every available leg -- `legs` narrows the fan-out -- and rank one deduplicated result."
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
            legs.extend((name, h) for h in rows)
        merged = {}
        for source, hit in legs:
            key = self.hit_key(hit)
            relevance = self.relevance(source, hit, q)
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
        "Defs and classes in one file, methods included; `score` carries the indent depth so the UI can."
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
                        score=float(len(m.group(1))), cell=cid, cell_index=i, cell_line=n))
        return out
    def _place(self, hits):
        "Give every notebook hit the cell and in-cell line that make it openable."
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
