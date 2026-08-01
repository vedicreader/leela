"""Code search for the IDE, over kosha when it is usable and a plain scan when it is not.

kosha gives the good answer -- FTS5 plus embeddings plus a call graph, over the
repo *and* the installed packages, so "where is this pattern already used" finds
prior art in dependencies too. kosha is a hard dependency, so the import always
works; what is *not* guaranteed is a built index and an embedding model on disk,
neither of which exists on a fresh checkout or an offline machine.

So the backend is chosen at call time and reported to the UI. A search box that
silently returns nothing because a model failed to download is worse than one
that says it is running a literal scan. `Search.backend` is what the frontends
display.
"""

from __future__ import annotations
import json, re
from dataclasses import dataclass, field
import numpy as np
from fastcore.all import L

from . import Dictable, errstr
from .fs import LANGS

__all__ = ['Hit', 'Cluster', 'Search']

_CODE_SUFFIXES = frozenset(LANGS) | {'.txt', '.rst', '.cfg', '.ini'}
MAX_SCAN_BYTES = 2_000_000

# usearch builds clusters out of the HNSW graph's upper levels, so a small index has
# no structure to cut and raises outright. Measured: ~300 vectors still fails, ~1000
# succeeds. Below this we do not even try, and fall back to plain k-NN.
MIN_CLUSTERABLE = 1000


def _meta(row):
    "Chunk metadata as a dict. kosha's `repo_context` decodes the JSON column; raw row reads do not."
    m = row.get('metadata') or {}
    if isinstance(m, str):
        try: m = json.loads(m)
        except Exception: m = {}
    return m or {}


@dataclass
class Hit(Dictable):
    'One search result. `line` is 1-indexed; `kind` names the backend that produced it.'
    path: str
    line: int
    text: str
    kind: str = 'scan'
    symbol: str = ''
    score: float = 0.0
    callers: list = None


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
    "Search the open folders; uses kosha when it is available and falls back to a literal scan."

    def __init__(self, sandbox, prefer_kosha=True):
        self.fs = sandbox
        self.prefer_kosha = prefer_kosha
        self._k = None
        self._k_tried = False
        self._k_note = 'kosha not tried yet'   # why the index is unavailable, remembered across calls
        self.backend = 'scan'
        self.note = ''

    # -- kosha ---------------------------------------------------------------
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
            from kosha import Kosha
            k = Kosha(install_skill=False)
            k.status()                     # touches the db and the encoder; fails fast if either is missing
            self._k = k
            self.backend, self.note = 'kosha', 'repo + installed packages'
        except Exception as e:
            self._k_note = f'kosha unavailable ({type(e).__name__})'
            self.note = self._k_note + '; literal scan'
        return self._k

    def _kosha_hits(self, q, limit):
        k = self._kosha()
        if k is None: return None
        try: rows = k.context(q, graph=True, limit=limit)
        except Exception as e:
            self.note = f'kosha search failed ({type(e).__name__}); literal scan'
            self._k = None
            return None
        out = L()
        for r in rows:
            m = r.get('metadata') or {}
            out.append(Hit(path=str(m.get('path') or ''), line=int(m.get('lineno') or 1),
                           text=(r.get('content') or '').strip().split('\n')[0][:200],
                           kind='kosha', symbol=str(m.get('mod_name') or ''),
                           score=float(r.get('pagerank') or 0.0),
                           callers=[str(c) for c in (r.get('callers') or [])][:5]))
        return out

    # -- literal scan --------------------------------------------------------
    def _scan(self, q, limit, regex=False):
        "Grep the open folders. Always available, and the only backend that sees uncommitted edits."
        try: pat = re.compile(q if regex else re.escape(q), re.I)
        except re.error as e:
            self.note = f'bad pattern: {e}'
            return L()
        out = L()
        for p in self.fs.walk().filter(lambda p: p.suffix.lower() in _CODE_SUFFIXES):
            try:
                if p.stat().st_size > MAX_SCAN_BYTES: continue
                text = p.read_text(encoding='utf-8', errors='ignore')
            except OSError: continue
            for i, line in enumerate(text.split('\n'), 1):
                if pat.search(line):
                    out.append(Hit(path=str(p), line=i, text=line.strip()[:200], kind='scan'))
                    if len(out) >= limit: return out
        return out

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
        return L(self._hit(rows[k], 'ann', dists.get(k, 0.0)) for k in keys if k in rows)

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
        return L(self._hit(rows[m], 'cluster') for m in members if m in rows)

    # -- api -----------------------------------------------------------------
    def search(self, q, limit=60, regex=False, force_scan=False):
        """Hits for `q`, best backend first.

        A short or punctuation-heavy query goes straight to the scan: kosha is a semantic
        index and answers those poorly, while a literal grep is exactly right for them.
        """
        q = (q or '').strip()
        if not q: return L()
        if force_scan or regex or len(q) < 4 or not re.search(r'[a-zA-Z]{3}', q):
            self.backend = 'scan'
            return self._scan(q, limit, regex)
        if (hits := self._kosha_hits(q, limit)) is not None and len(hits):
            self.backend = 'kosha'
            return hits
        self.backend = 'scan'
        return self._scan(q, limit, regex)

    def symbols(self, path):
        """Defs and classes in one file, for an outline. Methods are included, not just
        top-level names -- an outline that stops at the class line is not an outline.
        `score` carries the indent depth so the UI can nest them."""
        try: text = self.fs.read(path)
        except Exception: return L()
        out = L()
        for i, line in enumerate(text.split('\n'), 1):
            if (m := re.match(r'^(\s*)(?:async\s+)?(def|class)\s+(\w+)', line)):
                out.append(Hit(path=str(path), line=i, text=line.strip()[:200],
                               kind='symbol', symbol=m.group(3), score=float(len(m.group(1)))))
        return out
