"""Durable prose memory over a vishalakshi vault.

The vault is one corpus with shelves: a global `leela` shelf for agent notes and state,
and a per-workspace shelf for pages and research. Search, trees and topics are Vault's;
this module is the adapter that keeps leela's `note` status string and workspace API.
"""

from __future__ import annotations
import hashlib, os, re, time, uuid
from fastcore.all import Path, first

from ... import errstr

try: from ramabana.vault import safe_shelf as _safe_shelf
except ImportError:  # ramabana < shelf helper; keep one local sanitiser
    def _safe_shelf(name=None, default='main'): return re.sub(r'[^a-z0-9_]+', '_', str(name or default).lower()).strip('_') or default

__all__ = ['Memory', 'memory_path', 'memory_shelf', 'safe_shelf', 'GLOBAL']

GLOBAL = 'leela'


def memory_path(path=None):
    "Vault file: `$VISHALAKSHI_VAULT`, else `~/.vishalakshi/vault.db`."
    if path: return Path(path)
    env = os.getenv('VISHALAKSHI_VAULT')
    return Path(env) if env else Path.home()/'.vishalakshi'/'vault.db'


def safe_shelf(name=None):
    "SQL-safe shelf id; prefers ramabana's helper when present."
    return _safe_shelf(name, 'main')


def memory_shelf(root=None):
    "Per-workspace shelf name; falls back to `main` with no project open."
    if root is None: return 'main'
    name = safe_shelf(Path(root).resolve().name)
    return 'main' if name == GLOBAL else name


def _offline(): return os.getenv('LEELA_MEMORY_OFFLINE', '').lower() in ('1', 'true', 'yes')


def _registered_encoder(path, store):
    "Encoder that wrote `store`, read from the registry without opening a Vault."
    import sqlite3
    p = Path(path)
    if not p.is_file(): return None
    try:
        with sqlite3.connect(f'file:{p}?mode=ro', uri=True) as c:
            r = c.execute('select encoder from vault_stores where store=?', (store,)).fetchone()
        return r[0] if r else None
    except Exception: return None


class Memory:
    "MemoryPort over a vishalakshi vault: one store per project, one shared by all of them."

    def __init__(self, shelf=GLOBAL, path=None, encoder=None, offline=None, kosha=None, **_):
        # `kosha` is accepted and ignored: prose uses the vault encoder, code stays in Search.
        self.shelf_name = shelf or GLOBAL
        self.path, self.encoder = memory_path(path), encoder
        self.offline = _offline() if offline is None else bool(offline)
        self._stores, self.note = {}, 'vault not opened yet'

    def _store(self, name):
        "Open one shelf directly — never via the root vault, which would load another encoder."
        if name not in self._stores:
            from vishalakshi import Vault
            store = 'store' if name in (None, '', 'main') else safe_shelf(name)
            enc = None if self.offline else (_registered_encoder(self.path, store) or self.encoder)
            self._stores[name] = Vault(self.path, store=store, encoder=enc, offline=self.offline)
            self.note = f'vault at {self.path} · {self.shelf_name}'
        return self._stores[name]

    def _open(self): return self._store(self.shelf_name)
    def _agent(self): return self._store(GLOBAL)

    @property
    def vault(self):
        "Project store, for handing to ramabana's VaultHost."
        return self._open()

    @staticmethod
    def _text(doc):
        sections = list(getattr(doc, 'sections', None) or [])
        if sections:
            return '\n\n'.join(f"## {s.get('title') or f'Article {i + 1}'}\n\n{s.get('text') or ''}"
                for i, s in enumerate(sections))
        return str(getattr(doc, 'text', '') or '')

    def remember(self, doc, query='', force=False, extra_meta=None):
        "Ingest one document; Vault content-addresses `source|title`."
        text = self._text(doc).strip()
        if doc is None or not text: return None
        content_hash = hashlib.sha1(text.encode()).hexdigest()
        source = getattr(doc, 'url', '') or f'memory:{content_hash}'
        title = getattr(doc, 'title', '') or source or 'Web page'
        # dict literal so `extra_meta` can override these keys
        meta = {'url': getattr(doc, 'url', ''), 'query': query, 'remembered_at': time.time(), 'source_text': text,
            'sections': len(getattr(doc, 'sections', None) or []), 'content_hash': content_hash, **(extra_meta or {})}
        kind = getattr(doc, 'kind', '') or 'web'
        try:
            v = self._open()
            # Title change under the same source: drop the old id so Vault's address can move.
            if not force:
                prev = first(d for d in v.sources() if str(d.get('source')) == source)
                if prev and prev.get('title') != title: v.forget(prev['id'])
                elif prev and (dict(prev.get('meta') or {}).get('content_hash') != content_hash
                               or v.document(prev['id']).text.strip() != text): force = True
            out = v.add(text, title, source=source, kind=kind, meta=meta, force=force)
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
        from ..research.research import Doc
        content_hash = hashlib.sha1(text.encode()).hexdigest()
        doc = Doc(title=title, url=f'agent-state://{content_hash[:16]}', text=text, kind='agent-state')
        agent_meta = dict(meta or {})
        previous = self.agent_states(1)
        if previous: agent_meta.setdefault('parent_revision', previous[0]['id'])
        agent_meta.setdefault('author', 'user')
        agent_meta.setdefault('revision', len(self.agent_states(10_000)) + 1)
        return self._remember_agent(doc, query='agent starting state', extra_meta={'agent': agent_meta, 'source_text': text})

    def remember_agent_note(self, title, text, previous_id=''):
        "Create or replace one editable note; return the new durable document identity."
        text, title = str(text or '').strip(), str(title or '').strip() or 'Untitled note'
        if not text: return None
        from ..research.research import Doc
        doc = Doc(title=title, url=f'agent-note://{uuid.uuid4().hex}', text=text, kind='agent-note')
        note_meta = {'agent_note': {'author': 'user', 'edited_at': time.time()}, 'source_text': text}
        saved = self._remember_agent(doc, query='agent memory note', extra_meta=note_meta)
        if saved and previous_id and str(previous_id) != str(saved.get('doc_id')): self.forget(previous_id)
        return saved

    def _remember_agent(self, doc, query='', extra_meta=None):
        "Agent notes/state always address the global shelf."
        shelf = self.shelf_name
        self.shelf_name = GLOBAL
        try: return self.remember(doc, query=query, force=True, extra_meta=extra_meta)
        finally: self.shelf_name = shelf

    def remember_research(self, query, docs, digest):
        "Store source documents plus one query-rooted brief."
        saved = [self.remember(doc, query=query) for doc in docs or ()]
        if digest:
            from ..research.research import Doc
            key = hashlib.sha1(query.encode()).hexdigest()[:16]
            brief = Doc(title=f'Research: {query}', url=f'research://{key}', text=digest, kind='research')
            saved.append(self.remember(brief, query=query))
        return [x for x in saved if x]

    @staticmethod
    def _newest(rows, limit):
        return sorted((dict(d) for d in rows), key=lambda d: d.get('added_at') or '', reverse=True)[:max(1, int(limit))]

    def agent_states(self, limit=40): return self._newest(self._agent().sources(kind='agent-state'), limit)
    def agent_notes(self, limit=200): return self._newest(self._agent().sources(kind='agent-note'), limit)

    def documents(self, limit=80):
        try: return self._newest(self._open().sources(), limit)
        except Exception as e:
            self.note = f'could not list memory ({errstr(e)})'
            return []

    def document_text(self, doc_id):
        try: return str(self._open().document(str(doc_id)).text or '').strip()
        except Exception:
            try: return str(self._agent().document(str(doc_id)).text or '').strip()
            except Exception as e:
                self.note = f'could not read remembered document ({errstr(e)})'
                return ''

    def exact_text(self, doc_id):
        "Authored Markdown when stored; otherwise the reconstructed document text."
        doc_id = str(doc_id)
        for src in (self._agent, self._open):
            try: note = first(d for d in src().sources() if str(d.get('id')) == doc_id)
            except Exception: note = None
            if note is None: continue
            exact = (note.get('meta') or {}).get('source_text')
            return str(exact) if exact is not None else self.document_text(doc_id)
        return self.document_text(doc_id)

    def agent_state_text(self, doc_id): return self.exact_text(doc_id)

    def forget(self, doc_id):
        doc_id = str(doc_id)
        for opener in (self._open, self._agent):
            try:
                ids = {str(d['id']) for d in opener().sources()}
                if doc_id in ids:
                    opener().forget(doc_id)
                    self.note = 'forgot document'
                    return True
            except Exception as e:
                self.note = f'could not forget document ({errstr(e)})'
                return False
        self.note = 'document not found'
        return False

    def purge(self, ids=None):
        docs = [*self.documents(limit=100_000), *self.agent_notes(10_000), *self.agent_states(10_000)]
        wanted = {str(x) for x in (ids if ids is not None else [d['id'] for d in docs])}
        seen, removed = set(), 0
        for doc in docs:
            i = str(doc['id'])
            if i in wanted and i not in seen and self.forget(i):
                seen.add(i)
                removed += 1
        suffix = '' if removed == 1 else 's'
        self.note = f'purged {removed} remembered document{suffix}'
        return removed

    def toc(self, doc=None, depth=3):
        try:
            rows = self._open().toc(doc, max_depth=max(1, min(6, int(depth))))
            return list(rows)
        except Exception as e:
            self.note = f'could not read memory tree ({errstr(e)})'
            return []

    def read(self, node_id, max_chars=40_000):
        try: return dict(self._open().read(node_id, max_chars=max_chars))
        except Exception as e:
            self.note = f'could not read memory section ({errstr(e)})'
            return {}

    def search(self, query, limit=8):
        query = (query or '').strip()
        if not query: return []
        try:
            rows = self._open().search(query, limit=max(1, int(limit)))
            self.note = f'{len(rows)} memory hits'
            return [dict(r) for r in rows]
        except Exception as e:
            self.note = f'memory search failed ({errstr(e)})'
            return []

    def context(self, query, sections=6, related=6, max_read=6000):
        "Whole sections plus related paths; never leaks other shelves or kosha code."
        try:
            r = self._open().context(query, sections=sections, related=related, max_read=max_read, shelves=0, code=0)
            self.note = f'{len(r.results)} memory sections'
            return dict(query=query, results=[dict(x) for x in r.results], related=[dict(x) for x in r.related])
        except Exception as e:
            self.note = f'memory context failed ({errstr(e)})'
            return dict(query=query, results=[], related=[])

    def clusters(self, limit=20):
        try:
            rows = self._open().topic_tree(limit=max(1, int(limit)))
            self.note = f'{len(rows)} topics' if rows else 'no topics yet'
            return dict(note=self.note, method='topic_tree' if rows else None, clusters=[dict(c) for c in rows])
        except Exception as e:
            self.note = f'memory clustering unavailable ({errstr(e)})'
            return dict(note=self.note, method=None, clusters=[])

    def status(self):
        try: st = self._open().stats()
        except Exception: st = {}
        return dict(path=str(self.path), documents=st.get('docs', 0), nodes=st.get('nodes', 0),
            chunks=st.get('chunks', 0), note=self.note)

    # -- the vault surface behind clip. Not in `MemoryPort`: these reach the vault block's own
    # routes, not the shared memory ones, so the port stays what the browser needs.

    def shelves(self):
        "Every shelf in the vault with its document count, this workspace's first."
        try: rows = [dict(s) for s in self._open().shelves()]
        except Exception as e:
            self.note = f'vault shelves unavailable ({errstr(e)})'
            return []
        mine = safe_shelf(self.shelf_name)
        return sorted(rows, key=lambda r: (str(r.get('store')) != mine, str(r.get('store'))))

    def ref(self, doc_id, shelf=None):
        "`store|doc_id` — a doc id is content-addressed per shelf, so it is not unique alone."
        return f'{safe_shelf(shelf or self.shelf_name)}|{doc_id}'

    def clip(self, paths, shelf=None, meta=None, force=False):
        "Ingest files into a shelf as prose. Returns one row per file, skips included."
        paths = [str(p) for p in ([paths] if isinstance(paths, (str, Path)) else paths)]
        if not paths: return []
        v = self._store(shelf or self.shelf_name)
        try: out = v.add_files(paths, meta=dict(meta or {}), force=force)
        except Exception as e:
            self.note = f'clip failed ({errstr(e)})'
            return []
        self.note = f'clipped {len(paths)} file(s) into {v.name}'
        return [dict(r) for r in (out or [])]

    def note_pointer(self, title, text, shelf=None, meta=None):
        "One document standing for something not stored as prose — a code index, an API spec."
        v = self._store(shelf or self.shelf_name)
        if meta is None: return dict(v.note(text, title=title))
        return dict(v.add(text, title, source=f'pointer:{uuid.uuid4().hex[:12]}', meta=dict(meta)))

    def set_meta(self, doc_id, shelf=None, **kv): return self._store(shelf or self.shelf_name).set_meta(doc_id, **kv)

    def pii(self, doc_id, shelf=None, ner=True):
        """The PII report for one document, or why there is none.

        Coverage is pattern kinds plus *titled* names -- `Dr Charles Babbage`, not `Ada Lovelace`.
        A bare name or unstructured address is never masked; surfaces showing this must say so.
        """
        try: return dict(self._store(shelf or self.shelf_name).pii(doc_id, ner=ner))
        except Exception as e: return dict(note=f'pii unavailable ({errstr(e)})', has_pii=False)

    def noisy_candidates(self, shelf=None, k=20, min_score=1.0):
        "Documents the vault thinks are diluting retrieval, ranked, with the features that say so."
        v = self._store(shelf or self.shelf_name)
        try: return [dict(r) for r in v.suggest_noisy(k=k, min_score=min_score)]
        except Exception as e:
            self.note = f'noise ranking unavailable ({errstr(e)})'
            return []

    def mark_noisy(self, doc_id, shelf=None, noisy=True, reason=''):
        "Judgements live in `doc_marks`, keyed (doc_id, store), so re-ingesting cannot erase them."
        return dict(self._store(shelf or self.shelf_name).mark_noisy(doc_id, noisy=noisy, reason=reason))

    def watch(self, target, action='url', every='1d', note=None, shelf=None, **params):
        # A mutable page is content-addressed on `source|title`, so without `force` it reports
        # "already ingested" for ever and the watch never refreshes anything.
        if action in ('url', 'arxiv', 'youtube'): params.setdefault('force', True)
        v = self._store(shelf or self.shelf_name)
        return dict(v.watch(target, action=action, every=every, note=note, **params))

    def watches(self, shelf=None, due_only=False):
        try: return [dict(w) for w in self._store(shelf or self.shelf_name).watches(due_only=due_only)]
        except Exception as e:
            self.note = f'watches unavailable ({errstr(e)})'
            return []

    def unwatch(self, watch_id, shelf=None): return self._store(shelf or self.shelf_name).unwatch(watch_id)

    def poll(self, shelf=None):
        "Run every watch that has come due. The tick a scheduler calls."
        try: return dict(self._store(shelf or self.shelf_name).poll())
        except Exception as e: return dict(note=f'poll failed ({errstr(e)})', ran=0, checked=0)
