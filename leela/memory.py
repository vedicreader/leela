"""Durable web and research memory over litesearch's document tree.

The code index and this corpus deliberately share Kosha's resident embedder, but not its
code tables: source code is an AST-shaped corpus while pages are document trees.  One
Leela memory database persists fetched pages, research briefs, headings, sections and ANN
vectors across workspaces and sessions.
"""

from __future__ import annotations
import hashlib, json, time, threading, uuid
from fastcore.all import Path, L

from . import leela_cfg, errstr

__all__ = ['Memory', 'memory_path']

STORE = 'memory'
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _path_lock(path):
    "One re-entrant writer lock per shared SQLite/usearch corpus in this process."
    key = str(Path(path).resolve())
    with _LOCKS_GUARD: return _LOCKS.setdefault(key, threading.RLock())


def memory_path(path=None):
    p = Path(path or leela_cfg/'memory'/'web.db')
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class Memory:
    "Persistent document trees for pages and research, using Kosha's embedding model."

    def __init__(self, kosha=None, path=None):
        self.kosha, self.path = kosha, memory_path(path)
        self._lock = _path_lock(self.path)
        self._db = None
        self.note = 'memory not opened'

    def _open(self):
        if self._db is None:
            with self._lock:
                if self._db is None:
                    from litesearch import database
                    self._db = database(str(self.path))
                    # Creates memory_docs, memory_nodes and the ANN/FTS chunk store idempotently.
                    self._db.get_tree(STORE)
                    self.note = f'memory at {self.path}'
        return self._db

    def _k(self):
        try: return self.kosha() if callable(self.kosha) else self.kosha
        except Exception: return None

    def _doc_emb(self):
        k = self._k()
        return getattr(k, 'emb_doc', None)

    def _query_emb(self, query):
        k = self._k()
        fn = getattr(k, 'emb_query', None)
        if fn is None: return None
        v = fn(query)
        return v.tobytes() if hasattr(v, 'tobytes') else v

    @staticmethod
    def _pages(doc):
        sections = list(getattr(doc, 'sections', None) or [])
        if sections:
            text = '\n\n'.join(f"## {s.get('title') or f'Article {i + 1}'}\n\n{s.get('text') or ''}"
                               for i, s in enumerate(sections))
        else: text = str(getattr(doc, 'text', '') or '')
        return [(0, text)]

    def remember(self, doc, query='', force=False, extra_meta=None):
        "Ingest one fetched document as a heading tree; repeat URLs are content-addressed no-ops."
        if doc is None or not str(getattr(doc, 'text', '') or '').strip(): return None
        db = self._open()
        pages = self._pages(doc)
        content_hash = hashlib.sha1('\n\n'.join(text for _, text in pages).encode()).hexdigest()
        source = getattr(doc, 'url', '') or f'memory:{content_hash}'
        title = getattr(doc, 'title', '') or source or 'Web page'
        meta = {'url': getattr(doc, 'url', ''), 'query': query, 'remembered_at': time.time(),
                'sections': len(getattr(doc, 'sections', None) or []), 'content_hash': content_hash,
                **dict(extra_meta or {})}
        try:
            with self._lock:
                # A URL is a durable identity, but its contents can change. Rebuild only
                # when the remembered hash differs; routine rereads remain cheap no-ops.
                previous = list(db.q('select id, title, meta from memory_docs where source=:source limit 1',
                                     {'source': source}))
                if previous and not force:
                    try: force = (previous[0]['title'] != title or
                                  json.loads(previous[0]['meta'] or '{}').get('content_hash') != content_hash)
                    except Exception: force = False
                # litesearch's id includes title as well as source. If a page renamed,
                # remove the old identity before ingesting the replacement.
                if previous and previous[0]['title'] != title:
                    db.delete_doc(previous[0]['id'], store=STORE)
                    force = False
                out = db.add_doc(pages, title, source=source,
                                 kind=getattr(doc, 'kind', '') or 'web', store=STORE,
                                 emb_fn=self._doc_emb(), meta=meta, force=force)
            self.note = ('already remembered' if out.get('skipped') else
                         f"remembered {out.get('nodes', 0)} sections · {out.get('chunks', 0)} chunks")
            return dict(out, source=source)
        except Exception as e:
            self.note = f'memory ingest failed ({errstr(e)})'
            return None

    def remember_agent_state(self, title, text, meta=None):
        "Store an edited conversation summary as a reusable agent starting state."
        text, title = str(text or '').strip(), str(title or '').strip() or 'Agent state'
        if not text: return None
        from .research import Doc
        content_hash = hashlib.sha1(text.encode()).hexdigest()
        doc = Doc(title=title, url=f'agent-state://{content_hash[:16]}', text=text, kind='agent-state')
        agent_meta = dict(meta or {})
        previous = self.agent_states(1)
        if previous: agent_meta.setdefault('parent_revision', previous[0]['id'])
        agent_meta.setdefault('author', 'user')
        agent_meta.setdefault('revision', len(self.agent_states(10_000)) + 1)
        return self.remember(doc, query='agent starting state', force=True,
                             extra_meta={'agent': agent_meta, 'source_text': text})

    def agent_states(self, limit=40):
        "Reusable versioned conversation states, newest first."
        return [d for d in self.documents(limit=10_000) if d.get('kind') == 'agent-state'][:max(1, int(limit))]

    def document_text(self, doc_id):
        "Read every authored section of one remembered document in source order."
        try:
            with self._lock:
                rows = list(self._open().q('select id from memory_nodes where doc_id=:id and level>0 order by seq',
                                           {'id': str(doc_id)}))
            sections = [self.read(dict(row)['id']).get('text', '') for row in rows]
            return '\n\n'.join(str(text).strip() for text in sections if str(text).strip()).strip()
        except Exception as e:
            self.note = f'could not read remembered document ({errstr(e)})'
            return ''

    def exact_text(self, doc_id):
        "Original authored Markdown when available; tree reconstruction is the legacy fallback."
        doc_id = str(doc_id)
        note = next((doc for doc in self.documents(limit=10_000) if str(doc.get('id')) == doc_id), None)
        exact = (note or {}).get('meta', {}).get('source_text')
        return str(exact) if exact is not None else self.document_text(doc_id)

    def agent_state_text(self, doc_id):
        "Read the exact saved state Markdown, including headings and whitespace."
        return self.exact_text(doc_id)

    def agent_notes(self, limit=200):
        "User-authored memory notes available for explicit model-context routing."
        return [d for d in self.documents(limit=10_000) if d.get('kind') == 'agent-note'][:max(1, int(limit))]

    def remember_agent_note(self, title, text, previous_id=''):
        "Create or replace one editable note; return the new durable document identity."
        text, title = str(text or '').strip(), str(title or '').strip() or 'Untitled note'
        if not text: return None
        from .research import Doc
        doc = Doc(title=title, url=f'agent-note://{uuid.uuid4().hex}', text=text, kind='agent-note')
        saved = self.remember(doc, query='agent memory note', force=True,
                              extra_meta={'agent_note': {'author': 'user', 'edited_at': time.time()},
                                          'source_text': text})
        if saved and previous_id and str(previous_id) != str(saved.get('doc_id')):
            self.forget(previous_id)
        return saved

    def remember_research(self, query, docs, digest):
        "Store source documents plus one query-rooted brief that preserves their headings."
        saved = [self.remember(doc, query=query) for doc in docs or ()]
        if digest:
            from .research import Doc
            key = hashlib.sha1(query.encode()).hexdigest()[:16]
            saved.append(self.remember(Doc(title=f'Research: {query}', url=f'research://{key}',
                                           text=digest, kind='research'), query=query))
        return [x for x in saved if x]

    def documents(self, limit=80):
        db = self._open()
        try:
            with self._lock:
                rows = list(db.q('select id, title, source, kind, pages, meta, added_at from memory_docs '
                                 'order by added_at desc limit :n', {'n': max(1, int(limit))}))
            out = []
            for row in rows:
                item = dict(row)
                try: item['meta'] = json.loads(item.get('meta') or '{}')
                except Exception: item['meta'] = {}
                out.append(item)
            return out
        except Exception as e:
            self.note = f'could not list memory ({errstr(e)})'
            return []

    def forget(self, doc_id):
        "Delete one remembered document, its tree, chunks and ANN rows."
        try:
            with self._lock: self._open().delete_doc(str(doc_id), store=STORE)
            self.note = 'forgot document'
            return True
        except Exception as e: self.note = f'could not forget document ({errstr(e)})'; return False

    def purge(self, ids=None):
        "Forget selected documents, or the entire corpus when ids is None."
        docs = self.documents(limit=100_000)
        wanted = {str(x) for x in ids} if ids is not None else {str(d['id']) for d in docs}
        removed = 0
        for doc in docs:
            if str(doc['id']) in wanted and self.forget(doc['id']): removed += 1
        suffix = '' if removed == 1 else 's'
        self.note = f'purged {removed} remembered document{suffix}'
        return removed

    def toc(self, doc=None, depth=3):
        try:
            with self._lock: return self._open().toc(doc, store=STORE, max_depth=max(1, min(6, int(depth))))
        except Exception as e: self.note = f'could not read memory tree ({errstr(e)})'; return []

    def read(self, node_id, max_chars=40_000):
        try:
            with self._lock: return dict(self._open().read(node_id, store=STORE, max_chars=max_chars))
        except Exception as e: self.note = f'could not read memory section ({errstr(e)})'; return {}

    def search(self, query, limit=8):
        query = (query or '').strip()
        if not query: return []
        emb = self._query_emb(query)
        if emb is None:
            # Tree ingestion still provides a first-class FTS corpus if Kosha's embedder is unavailable.
            try:
                st = self._open().get_tree(STORE).store
                with self._lock:
                    rows = st.fts_search(query, ['content', 'node_id', 'heading', 'doc_id'], limit=limit)
                for row in rows: row['breadcrumb'] = row.get('heading') or ''
                self.note = 'memory FTS · embedding unavailable'
                return list(rows)
            except Exception as e: self.note = f'memory search failed ({errstr(e)})'; return []
        try:
            with self._lock:
                rows = self._open().sections(query, emb, limit=max(1, int(limit)), store=STORE)
            self.note = f'{len(rows)} memory sections · FTS + ANN'
            return [dict(r) for r in rows]
        except Exception as e: self.note = f'memory search failed ({errstr(e)})'; return []

    def context(self, query, sections=6, related=6, max_read=6000):
        "Whole operative sections plus vector-related paths, in the RegAffairs retrieval shape."
        emb = self._query_emb(query)
        if emb is None: return {'query': query, 'results': self.search(query, sections), 'related': []}
        try:
            with self._lock:
                result = self._open().context(query, emb, store=STORE, sections=sections,
                                              related=related, max_read=max_read, graph=False, vector=True)
            return {'query': query, 'results': [dict(x) for x in result.results],
                    'related': [dict(x) for x in result.related]}
        except Exception as e: self.note = f'memory context failed ({errstr(e)})'; return {'query': query, 'results': [], 'related': []}

    def clusters(self, limit=20):
        try:
            with self._lock:
                result = self._open().get_tree(STORE).store.clusters(min_size=2,
                    columns=['content', 'heading', 'doc_id', 'node_id'], members=10)
            self.note = result.note
            return {'note': result.note, 'method': result.method,
                    'clusters': [dict(c) for c in result.clusters[:max(1, int(limit))]]}
        except Exception as e:
            self.note = f'memory clustering unavailable ({errstr(e)})'
            return {'note': self.note, 'method': None, 'clusters': []}

    def status(self):
        docs = self.documents()
        try:
            with self._lock:
                g = self._open().get_tree(STORE)
                chunks, nodes = g.store.count, g.nodes.count
        except Exception: chunks = nodes = 0
        return {'path': str(self.path), 'documents': len(docs), 'nodes': nodes, 'chunks': chunks,
                'note': self.note}
