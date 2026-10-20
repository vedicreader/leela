"Durable prose memory over a vishalakshi vault."

from __future__ import annotations
import functools, hashlib, json, os, re, threading, time, uuid
from collections import Counter
from fastcore.all import AttrDict, L, Path, first, risinstance

from ... import errstr

try: from ramabana.vault import safe_shelf as _safe_shelf
except ImportError:
    def _safe_shelf(name=None, default='main'): return re.sub(r'[^a-z0-9_]+', '_', str(name or default).lower()).strip('_') or default

__all__ = ['Memory', 'memory_path', 'memory_shelf', 'safe_shelf', 'shared_encoder', 'source_kind', 'source_keys',
           'GLOBAL', 'ACQUIRE', 'PII_GATES', 'PII_LABELS', 'pii_gate', 'PrivacyBlocked', 'withheld_why',
           'VaultRefused', 'read_chat', 'page_list', 'withhold_local', 'query_refusal', 'index_workers']

GLOBAL = 'leela'

#: What a hosted model gets of a Personal document: as it is, masked, or withheld.
PII_GATES = ('off', 'redact', 'refuse')
PII_LABELS = dict(off='as is (not recommended)', redact='masked', refuse='withheld')

def pii_gate(v, default='redact'):
    "A stored or posted policy, refused rather than silently read as `off`."
    g = str(v or default).strip().lower()
    if g not in PII_GATES: raise ValueError(f'pii must be one of {", ".join(PII_GATES)}')
    return g

class PrivacyBlocked(PermissionError):
    "A send refused for a document's level: `kind` is `pii_blocked` or `local_only`, `refs` what was withheld, `attachments` the prompt-bar chips it came from."
    def __init__(self, why, kind='pii_blocked', refs=(), attachments=()):
        super().__init__(why); self.kind, self.refs, self.attachments = kind, list(refs), list(attachments)

class VaultRefused(Exception):
    "A vault request a screen can answer: `kind` from the screens table, `code` the HTTP status."
    def __init__(self, why, kind, code=400, **extra): super().__init__(why); self.kind, self.code, self.extra = kind, code, extra

def read_chat(model):
    "The reader a page read goes through for `model`; None lets vishalakshi build it. Tests put a stand-in here."
    return None

def page_list(spec):
    "Pages as a person writes them, 1-based (`'1-3,7'`), as the 0-based list vishalakshi takes. Empty is None: every page."
    out = []
    for part in str(spec or '').replace(' ', '').split(','):
        if not part: continue
        a, _, b = part.partition('-')
        if not (a.isdigit() and (not b or b.isdigit())) or int(a) < 1: raise VaultRefused(f'{part!r} is not a page or a range like 3-9', 'bad_request')
        out += range(int(a) - 1, int(b or a))
    return sorted(set(out)) or None

#: The presets a book of verses is read with, and the script each prints in.
VERSE_SCRIPT = {'sanskrit': 'Devanagari', 'tamil': 'Tamil'}

class _Read:
    "A vault whose read already ran, for `lekhaka.read_book`: Leela reads with progress, cancel and the privacy gate, and lekhaka assembles."
    def __init__(self, v, did): self.v, self.did = v, did
    def read_doc(self, *a, **kw): return dict(doc_id=self.did)
    def pages(self, did): return self.v.pages(did)

def _prob_page(s):
    "A lekhaka problem as `(page, text)`: `'12: verse 5 after 3'` and `'chapter 2: … (12)'` name a 0-based page, the rest none."
    if m := re.match(r'(\d+): (.*)', s, re.S): return int(m[1]), m[2]
    if m := re.match(r'(.*) \((\d+)\)$', s, re.S): return int(m[2]), m[1]
    return None, s

def counts_list(spec):
    "Verses per chapter as a person writes them, `'47, 72 43'`; empty is None."
    xs = [x for x in re.split(r'[\s,]+', str(spec or '').strip()) if x]
    if not all(re.fullmatch(r'[1-9]\d*', x) for x in xs): raise VaultRefused('verses per chapter are whole numbers, like 47,72,43', 'bad_request')
    return [int(x) for x in xs] or None

def withhold_local(o, v):
    "`o`, what a retrieval returned, with every Local-only row withheld: what a stored `off` still keeps from a hosted model."
    from vishalakshi.ask import send_rule
    from vishalakshi.pii import CTX_ROWS, ROW_KIDS, ROW_LABEL, ROW_META, ROW_TEXT, held
    @functools.cache
    def lv(store, did):
        try: return (v if store in (None, '', v.name) else v.shelf(store)).level(did).level
        except Exception: return 'open'
    def fix(r, f, g):
        if x := r.get(f): r[f] = type(x)(g(str(y)) for y in x) if isinstance(x, (list, tuple)) else g(str(x))
    def row(r, gone=False):
        if not isinstance(r, dict): return r
        did = first(str(x).split('#')[0] for k in ('doc_id', 'node_id', 'id', 'ref') if (x := r.get(k)))
        gone = gone or (bool(did) and send_rule(lv(r.get('store'), did), False, 'off') == 'withheld')
        out = type(r)(r)
        if gone:
            # a name the detector cannot see rides in a title as easily as in the text
            for f in (*ROW_TEXT, *ROW_LABEL, *ROW_META): fix(out, f, lambda s: held({'local': 1}))
            out['pii'] = {'local': 1}
        for f in ROW_KIDS:
            if isinstance(k := out.get(f), dict): out[f] = row(k, gone)
            elif isinstance(k, (list, tuple, L)): out[f] = type(k)(row(x, gone) for x in k)
        return out
    if isinstance(o, (list, tuple, L)): return type(o)(row(r) for r in o)
    if not isinstance(o, dict): return o
    ks = [k for k in CTX_ROWS if isinstance(o.get(k), (list, tuple, L))]
    if not ks and not isinstance(o.get('doc'), dict): return row(o)
    out = type(o)(o)
    for k in ks: out[k] = type(o[k])(row(r) for r in o[k])
    if isinstance(out.get('doc'), dict): out['doc'] = row(out['doc'])
    return out

def query_refusal(q):
    "Why a query may not go to the web, naming the identifying kinds it holds; None when it may."
    from vishalakshi.pii import pii_report
    rep = pii_report(str(q or ''), ner=False)
    if not rep.identifying: return None
    return (f"the query holds personal information ({', '.join(sorted(rep.identifying))}), and a web search sends it as typed. "
            'Nothing was searched. Ask again without it.')

def _resolved(src):
    p = Path(str(src)).expanduser()
    try: return str(p.resolve())
    except OSError: return str(p)

_PASSES = {}

@functools.lru_cache(maxsize=256)
def _render(src, mtime, page, w):
    "One page as image bytes and their type, held in memory only: a render on disk is a copy no level guards."
    from vishalakshi.read import IMG_EXTS, render
    p = Path(src)
    if p.suffix.lower() in IMG_EXTS:
        if page: raise IndexError(f'{p.name} is one page')
        return p.read_bytes(), f"image/{p.suffix.lower().lstrip('.').replace('jpg', 'jpeg')}"
    if not w: return render(p, page, dpi=110), 'image/png'
    from pdflite import pdf_doc
    return pdf_doc(p).render_page_fit(page, w, w * 2, format='png'), 'image/png'

#: The vault readers a person can point at something, each named for what it reads.
ACQUIRE = ('grab', 'web', 'crawl', 'note', 'harvest', 'github', 'arxiv', 'youtube', 'pdf')

def source_kind(source):
    "What a document's `source` actually is: a file on disk, a web page, or neither of those."
    s = str(source or '')
    if s.startswith(('http://', 'https://')): return 'url'
    if s.startswith(('/', '~')): return 'file'
    if len(s) > 2 and s[1] == ':' and s[2] in '\\/': return 'file'
    return 'synthetic'

def withheld_why(what, chk):
    "Why `what` was not sent, in `reach_refusal`'s words."
    from vishalakshi.pii import LEVEL_LABELS
    lv = first(chk.withheld).level if chk.withheld else 'personal'
    fix = 'change its level in the vault' if lv == 'local' else 'change vault privacy in agent settings'
    return (f'{what} is {LEVEL_LABELS[lv]} in the vault and this conversation runs on {chk.model}, which is not a '
            f'model on this machine. Nothing was sent. Switch to a local model, or {fix}.')

def source_keys(src):
    "The spellings a vault may have filed `src` under: as given, expanded and resolved."
    s = str(src or '')
    if not s or source_kind(s) == 'url': return [s] if s else []
    p = Path(s).expanduser()
    try: r = str(p.resolve())
    except OSError: r = str(p)
    return list(dict.fromkeys([s, str(p), r]))

def _added_epoch(at):
    "`added_at` as a timestamp. Unreadable means *unknown*, and unknown must not mean stale."
    if isinstance(at, (int, float)): return float(at)
    from datetime import datetime, timezone
    try: dt = datetime.fromisoformat(str(at))
    except Exception: return float('inf')
    return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).timestamp()

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

def index_workers():
    "Parse workers for one clip: `$LEELA_INDEX_WORKERS`, else at most two, so a resumed clip cannot fork a pool per core."
    v = os.getenv('LEELA_INDEX_WORKERS', '').strip()
    return int(v) if v.isdigit() else min(2, (os.cpu_count() or 1)//4)

def _offline(): return os.getenv('LEELA_MEMORY_OFFLINE', '').lower() in ('1', 'true', 'yes')

_ENC_LOCK, _ENCODERS = threading.Lock(), {}
_OPEN_LOCKS = {}

def _open_lock(path):
    "One lock per vault file, for the threads that open shelves over it."
    with _ENC_LOCK: return _OPEN_LOCKS.setdefault(str(Path(path).resolve()), threading.Lock())

def shared_encoder(enc=None, offline=False):
    "One built encoder per (name, offline); `mk_encoder` loads a fresh ~1GB matrix on every call."
    if enc is not None and not isinstance(enc, str): return enc
    key = (enc, bool(offline))
    with _ENC_LOCK:   # held across the load: two shelves opening at once must not both fetch it
        if key not in _ENCODERS:
            from vishalakshi.core import mk_encoder
            _ENCODERS[key] = mk_encoder(enc, offline=offline)
        return _ENCODERS[key]

def _registered_encoder(path, store):
    "Encoder that wrote `store`, read from the registry without opening a Vault."
    import sqlite3
    p = Path(path)
    if not p.is_file(): return None
    try:
        with sqlite3.connect(f'file:{p}?mode=ro', uri=True) as c:
            for q in ('select encoder from store_meta where name=?', 'select encoder from vault_stores where store=?'):
                try: r = c.execute(q, (store,)).fetchone()
                except sqlite3.OperationalError: r = None
                if r and r[0]: return r[0]
        return None
    except Exception: return None


def _why_no_vault(e):
    "Why memory could not take something, in terms of what to do about it."
    missing = getattr(e, 'name', '') or ''
    if isinstance(e, ImportError) and missing in ('litert_lm', 'rishi', 'vishalakshi'):
        return ('memory needs the LiteRT runtime here, and it is not installed. '
                'Install it under Models in the settings pane, and memory comes back.')
    return f'memory ingest failed ({errstr(e)})'

class Memory:
    "MemoryPort over a vishalakshi vault: one store per project, one shared by all of them."
    def __init__(self, shelf=GLOBAL, path=None, encoder=None, offline=None, kosha=None, **_):
        self.shelf_name = shelf or GLOBAL
        self.path, self.encoder = memory_path(path), encoder
        self.offline = _offline() if offline is None else bool(offline)
        self._stores, self.note, self._srcs = {}, 'vault not opened yet', (None, {})
    def sources(self):
        "`{source: (shelf, doc_id)}` over every shelf, read off the file; cached until the file or its WAL changes."
        import apsw
        try: seal = tuple(f.stat().st_mtime_ns if f.exists() else 0 for f in (self.path, Path(f'{self.path}-wal')))
        except OSError: return {}
        if not seal[0]: return {}
        if self._srcs[0] == seal: return self._srcs[1]
        out = {}
        # apsw, the SQLite the shelves run on: a second SQLite in the process (stdlib `sqlite3`) drops
        # their POSIX locks when it closes, and racing a shelf's open on another thread is a bus error
        with _open_lock(self.path):
            c = apsw.Connection(str(self.path), flags=apsw.SQLITE_OPEN_READONLY)
            try:
                try: names = [r[0] for r in c.execute('select name from store_meta')]
                except apsw.SQLError: names = []
                for n in names:
                    p = '' if n == 'store' else f'{n}_'
                    try: rows = c.execute(f'select source, id from "{p}docs" order by added_at').fetchall()
                    except apsw.SQLError: continue
                    # litesearch 0.1.50 files a copy of stored text as a row in `sources`, not in `docs`
                    try: rows += c.execute(f'select source, doc_id from "{p}sources" order by added_at').fetchall()
                    except apsw.SQLError: pass
                    out.update({s: (self._shelf_name(n), d) for s, d in rows if s})
            finally: c.close()
        self._srcs = (seal, out)
        return out
    def by_source(self, src):
        "`(shelf, doc_id)` of the document filed from `src`, or None."
        srcs = self.sources()
        return first(srcs[k] for k in source_keys(src) if k in srcs)
    def _store(self, name):
        "Open one shelf directly, never via the root vault, which would load another encoder."
        # Under the file's lock: the poll tick runs on its own thread, and two threads opening a
        # shelf over the same file at once built two Vaults, honker's native open racing an apsw
        # `execute` on the other. That is a bus error, not an exception. The lock is the file's,
        # not this object's: every workspace root has a Memory, all over the one vault.db.
        with _open_lock(self.path):
            if name not in self._stores:
                from vishalakshi import Vault
                store = 'store' if name in (None, '', 'main') else safe_shelf(name)
                enc = None if self.offline else (_registered_encoder(self.path, store) or self.encoder)
                self._stores[name] = Vault(self.path, store=store, encoder=shared_encoder(enc, self.offline),
                                           offline=self.offline)
                self.note = f'vault at {self.path} · {self.shelf_name}'
            return self._stores[name]
    def _open(self): return self._store(self.shelf_name)
    def _agent(self): return self._store(GLOBAL)
    def _shelf(self, shelf=None):
        "The store an explicit shelf names, defaulting to this workspace's."
        return self._store(shelf or self.shelf_name)
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
        meta = {'url': getattr(doc, 'url', ''), 'query': query, 'remembered_at': time.time(), 'source_text': text,
            'sections': len(getattr(doc, 'sections', None) or []), 'content_hash': content_hash, **(extra_meta or {})}
        kind = getattr(doc, 'kind', '') or 'web'
        try:
            v = self._open()
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
            self.note = _why_no_vault(e)
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
    def document_text(self, doc_id, shelf=None):
        if shelf:
            try: return str(self._shelf(shelf).document(str(doc_id)).text or '').strip()
            except Exception as e:
                self.note = f'could not read remembered document ({errstr(e)})'
                return ''
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
        removed = sum(bool(self.forget(i))
                      for i in dict.fromkeys(str(d['id']) for d in docs) if i in wanted)
        suffix = '' if removed == 1 else 's'
        self.note = f'purged {removed} remembered document{suffix}'
        return removed
    def toc(self, doc=None, depth=3, pii='off'):
        gate = pii_gate(pii)
        try:
            rows = self._open().toc(doc, max_depth=max(1, min(6, int(depth))), pii=gate)
            return list(rows)
        except Exception as e:
            self.note = f'could not read memory tree ({errstr(e)})'
            return []
    def read(self, node_id, max_chars=40_000, pii='off'):
        gate = pii_gate(pii)
        try: return dict(self._open().read(node_id, max_chars=max_chars, pii=gate))
        except Exception as e:
            self.note = f'could not read memory section ({errstr(e)})'
            return {}
    def search(self, query, limit=8, pii='off'):
        query, gate = (query or '').strip(), pii_gate(pii)
        if not query: return []
        try:
            rows = self._open().search(query, limit=max(1, int(limit)), pii=gate)
            self.note = f'{len(rows)} memory hits'
            return [dict(r) for r in rows]
        except Exception as e:
            self.note = f'memory search failed ({errstr(e)})'
            return []
    def context(self, query, sections=6, related=6, max_read=6000, pii='off'):
        "Whole sections plus related paths; never leaks other shelves or kosha code."
        gate = pii_gate(pii)
        try:
            r = self._open().context(query, sections=sections, related=related, max_read=max_read,
                                     shelves=0, code=0, pii=gate)
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
    def shelves(self):
        "Every shelf in the vault with its document count, this workspace's first."
        try: rows = [dict(s) for s in self._open().shelves()]
        except Exception as e:
            self.note = f'vault shelves unavailable ({errstr(e)})'
            return []
        mine = safe_shelf(self.shelf_name)
        return sorted(rows, key=lambda r: (str(r.get('store')) != mine, str(r.get('store'))))
    def ref(self, doc_id, shelf=None):
        "`store|doc_id`: a doc id is content-addressed per shelf, so it is not unique alone."
        return f'{safe_shelf(shelf or self.shelf_name)}|{doc_id}'
    def _shelf_name(self, store):
        "One name per shelf: `shelves()` calls the unprefixed store `store`, a shelf argument calls it."
        return 'main' if store in (None, '', 'store', 'main') else safe_shelf(store)
    def _populated(self):
        "Every shelf worth reading: this workspace's, plus any other that actually holds documents."
        return L(self.shelf_name, *[s['store'] for s in self.shelves() if s.get('docs')]).map(self._shelf_name).unique()
    def _across(self, shelves, f, note):
        "`f(name, store)` over each shelf, stamped with its shelf. One unreadable shelf is counted, not raised."
        out, failed = [], L()
        for name in L(shelves if shelves is not None else self._populated()).map(self._shelf_name).unique():
            try: out += [dict(r, shelf=name) for r in f(name, self._store(name))]
            except Exception as e: failed.append(errstr(e))
        self.note = note(len(out)) + (f' · {len(failed)} unreadable ({failed[0]})' if failed else '')
        return out
    def all_documents(self, limit=200, shelves=None, kind=None):
        "Every document, newest first, with its shelf. `doc_id` beside `id`: `sources` and `clip`."
        rows = self._across(shelves, lambda n, v: v.sources(kind), lambda n: f'{n} documents')
        return [dict(r, doc_id=r.get('doc_id') or r.get('id')) for r in self._newest(rows, limit)]
    def reindex_changed(self, shelves=None, limit=2000):
        "Re-clip every filed document whose file on disk is newer than the vault's copy."
        checked, done, missing, unknown, failed = 0, [], [], [], []
        for row in self.all_documents(limit=limit, shelves=shelves):
            src = str(row.get('source') or '')
            if source_kind(src) != 'file': continue
            checked += 1
            p = Path(src).expanduser()
            if not p.is_file(): missing.append(src); continue
            at = _added_epoch(row.get('added_at'))
            if at == float('inf'): unknown.append(src); continue
            if p.stat().st_mtime <= at + 1: continue
            try: self.clip([p], shelf=row.get('shelf'), force=True); done.append(src)
            except Exception as e: failed.append(f'{src}: {errstr(e)}')
        self.note = f'reindexed {len(done)} of {checked} filed documents'
        return dict(checked=checked, reindexed=len(done), paths=done,
                    missing=missing, unknown=unknown, failed=failed)
    def search_all(self, query, limit=20, shelves=None, pii='off'):
        "Search every populated shelf and merge."
        query, gate = (query or '').strip(), pii_gate(pii)
        if not query: return []
        names = shelves if shelves is not None else self._populated()
        per = max(3, int(limit) // max(1, len(names)))
        rows = self._across(names, lambda n, v: v.search(query, limit=per, pii=gate),
                            lambda n: f'{n} hits for {query!r}')
        return sorted(rows, key=lambda r: -(r.get('score') or 0))[:max(1, int(limit))]
    def document(self, doc_id, shelf=None):
        "One document's row, or `{}`."
        try: return dict(self._shelf(shelf).doc(doc_id) or {})
        except Exception as e:
            self.note = f'could not read document ({errstr(e)})'
            return {}
    def shelf_toc(self, doc_id, shelf=None, depth=3, pii='off'):
        "One document's section tree, in whichever shelf holds it."
        gate = pii_gate(pii)
        try: return [dict(r) for r in self._shelf(shelf).toc(doc_id, max_depth=max(1, min(6, int(depth))), pii=gate)]
        except Exception as e:
            self.note = f'could not read the section tree ({errstr(e)})'
            return []
    def sections(self, doc_id, shelf=None, depth=6, pii='off'):
        "`toc` flattened: each document is a row whose `tree` holds the nesting, walked once here."
        out = []
        def walk(items, at=0):
            for x in L(items or ()).filter(risinstance(dict)):
                if tree := x.get('tree'):
                    walk([tree], at); continue
                if node := x.get('id') or x.get('node_id'):
                    pages = x.get('pages') if isinstance(x.get('pages'), (list, tuple)) else None
                    out.append({'node_id': node, 'title': x.get('title') or 'Untitled section',
                        'level': x.get('level', at), 'depth': at, 'chunks': x.get('nchunks') or 0,
                        'page': (pages[0] + 1) if pages else None, 'summary': x.get('summary') or ''})
                walk(x.get('children'), at + 1)
        walk(self.shelf_toc(doc_id, shelf, depth, pii=pii))
        return out
    def shelf_text(self, ref, shelf=None, max_chars=60_000):
        "The readable text behind a reference, in whichever shelf holds it: a whole document, or one section."
        ref = str(ref)
        if '#' in ref: return str(self.shelf_read(ref, shelf, max_chars).get('text') or '').strip()
        try: return str(self._shelf(shelf).document(ref).text or '').strip()[:max_chars]
        except Exception as e:
            self.note = f'could not read document ({errstr(e)})'
            return ''
    def shelf_read(self, node_id, shelf=None, max_chars=40_000, pii='off'):
        "One section, in whichever shelf holds it."
        gate = pii_gate(pii)
        try: return dict(self._shelf(shelf).read(node_id, max_chars=max_chars, pii=gate) or {})
        except Exception as e:
            self.note = f'could not read section ({errstr(e)})'
            return {}
    def related(self, node_id, shelf=None):
        "Sections the vault thinks sit near this one."
        try: return [dict(r) for r in self._shelf(shelf).related(node_id)]
        except Exception: return []
    def move(self, doc_id, target, shelf=None):
        "Move a document to another shelf."
        name = safe_shelf(target)
        out = dict(self._shelf(shelf).reshelf(doc_id, shelf=name))
        self.note = f'moved to {name}'
        return dict(out, moved_to=name, note=self.note)
    def drop_shelf(self, shelf):
        "Drop an empty shelf. `Vault.drop_shelf` deletes a populated one without asking."
        name = safe_shelf(shelf)
        if self._shelf_name(name) in (self._shelf_name(self.shelf_name), GLOBAL):
            raise ValueError(f'{name} is in use by this workspace')
        row = first(s for s in self.shelves() if s.get('store') == name)
        if row is None: raise KeyError(name)
        if row.get('docs'): raise ValueError(f'{name} still holds {row["docs"]} documents')
        out = dict(self._open().drop_shelf(name))
        self._stores.pop(name, None)
        self.note = f'dropped {name}'
        return out
    def mark_not_pii(self, doc_id, shelf=None, clear=True, reason=''):
        "Override the PII report, or restore detection. Via `doc_marks`: `meta` is erased on re-ingest."
        return dict(self._shelf(shelf).mark_not_pii(doc_id, clear=clear, reason=reason))
    def mark_pii(self, doc_id, shelf=None, force=True, reason=''):
        "The other override: private though the arithmetic found nothing. A name and an address are not patterns."
        return dict(self._shelf(shelf).mark_pii(doc_id, force=force, reason=reason))
    def pii_evidence(self, doc_id, shelf=None):
        "Recognised PII spans by page. Returned, never written back: that would store it twice."
        from vishalakshi.pii import pii_report
        v, out, seen = self._shelf(shelf), [], set()
        try: rows = v.store(where='doc_id=?', where_args=[str(doc_id)], select='content,page,node_id')
        except Exception as e:
            self.note = f'pii evidence unavailable ({errstr(e)})'
            return []
        ner = str(self.document(doc_id, shelf).get('kind') or '').lower() != 'code'
        for row in rows:
            for start, end, kind, value in pii_report(row.get('content') or '', ner=ner).spans:
                key = (kind, value, row.get('page'))
                if key in seen: continue
                seen.add(key)
                out.append({'kind': kind, 'value': value, 'page': (row.get('page') or 0) + 1,
                            'node_id': row.get('node_id'), 'start': start, 'end': end})
        return out
    def clip(self, paths, shelf=None, meta=None, force=False, stop=None):
        "Ingest files into a shelf as prose: one row per file filed, skips included; given `stop`, `cancelled` and `unread` say what it left."
        paths = [str(p) for p in ([paths] if isinstance(paths, (str, Path)) else paths)]
        if not paths: return []
        v = self._shelf(shelf)
        # one batch for vishalakshi, which asks `stop` before it and before each file
        cb = dict(stop=stop, batch=len(paths)) if stop is not None else {}
        try: out = v.add_files(paths, meta=dict(meta or {}), force=force, n_workers=index_workers(), **cb)
        except Exception as e:
            from ..vault.jobs import quitting
            # Swallowed, the batch would be recorded as clipped and never resumed.
            if quitting(): raise
            self.note = f'clip failed ({errstr(e)})'
            return []
        self.note = f'clipped {len(paths)} file(s) into {v.name}'
        rows = L(dict(r) for r in (out or []))
        rows.cancelled, rows.unread = bool(getattr(out, 'cancelled', False)), L(getattr(out, 'unread', None) or [])
        return rows
    def acquire(self, action, target, shelf=None, **params):
        "Bring one source in, through whichever vault reader can actually read it."
        if action not in ACQUIRE: raise ValueError(f'unknown acquisition {action!r}')
        v = self._shelf(shelf)
        if action == 'github': params.setdefault('n_workers', index_workers())
        out = getattr(v, action)(target, **params)
        self.note = f'{action}: {target}'
        if isinstance(out, dict): return dict(out)
        # a crawl's `L` carries what a stop left unfiled on the list itself
        return {'documents': [dict(r) for r in L(out)], **{k: getattr(out, k) for k in ('cancelled', 'unread') if hasattr(out, k)}}
    def file_news(self, text, title, source, shelf='news', meta=None):
        "One feed item as an ordinary document, which is what makes it searched and cited like the rest."
        return dict(self._shelf(shelf).add(text, title, source=source, kind='news', meta=dict(meta or {})))
    def vault_stats(self, shelves=None):
        "Documents, sections and chunks across every shelf worth reading, plus the encoder behind them."
        names = L(shelves if shelves is not None else self._populated()).map(self._shelf_name).unique()
        out, enc = dict(docs=0, nodes=0, chunks=0, shelves=len(names)), ''
        for name in names:
            try: st = self._store(name).stats()
            except Exception: continue
            for k in ('docs', 'nodes', 'chunks'): out[k] += int(st.get(k) or 0)
            enc = enc or str(st.get('encoder') or '')
        return dict(out, encoder=enc or ('offline' if self.offline else 'unknown'), path=str(self.path))
    def note_pointer(self, title, text, shelf=None, meta=None):
        "One document standing for something not stored as prose: a code index, an API spec."
        v = self._shelf(shelf)
        if meta is None: return dict(v.note(text, title=title))
        return dict(v.add(text, title, source=f'pointer:{uuid.uuid4().hex[:12]}', meta=dict(meta)))
    def set_meta(self, doc_id, shelf=None, **kv): return self._shelf(shelf).set_meta(doc_id, **kv)
    def send_check(self, doc_id, shelf=None, local=False, model='', policy='redact', image=False):
        "vishalakshi's `send_check` on one document, for a turn model Leela has already placed on or off this machine."
        return self.check([str(doc_id).split('#')[0]], (), shelf, local, model, policy, image)
    def check(self, refs=(), pages=(), shelf=None, local=False, model='', policy='redact', image=False, allow=False):
        "vishalakshi's `send_check` over documents or `(doc, page)` pairs on one shelf, for a model Leela has placed on or off this machine."
        # `send_check` places a built chat by its runtime, so Leela's own verdict travels as one
        turn = AttrDict(model=model or 'an unresolved model', runtime='litert' if local else 'hosted')
        return self._shelf(shelf).send_check(refs=list(refs) or None, pages=list(pages) or None, model=turn,
                                             policy=pii_gate(policy), image=image, allow=allow)
    def doc_id(self, doc, shelf=None):
        "The id of the document `doc` names exactly: `Vault.doc` would also take a title it merely contains."
        d = self._shelf(shelf).doc(str(doc or ''))
        if not d or d['id'] != str(doc): raise VaultRefused(f'no document {doc}', 'not_found', 404)
        return d['id']
    def scope(self, doc=None, shelf=None, pages=None):
        "A chunk-store `WHERE` for one document or pages of it (0-based); None is the whole vault."
        if not doc:
            if pages: raise VaultRefused('a page range needs a document', 'bad_request')
            return None
        w = "doc_id='{}'".format(self.doc_id(doc, shelf).replace("'", "''"))
        return w + (f" AND page IN ({','.join(str(int(p)) for p in pages)})" if pages else '')
    def find(self, q, limit=20, doc=None, shelf=None, pages=None):
        "Hits from the whole vault, one document, or pages of it."
        if not doc: return self.search_all(q, limit, [shelf] if shelf else None)
        w = self.scope(doc, shelf, pages)
        if not (q or '').strip(): return []
        return [dict(r, shelf=self._shelf_name(shelf or self.shelf_name)) for r in self._shelf(shelf).search(q, limit=limit, where=w)]
    def ask_check(self, doc=None, shelf=None, pages=None, local=False, model='', policy='redact'):
        "Where an answer's sections may go before it is asked: the scope's documents, or pages, at their levels."
        from vishalakshi.ask import send_line
        self.scope(doc, shelf, pages)
        if doc:
            d = self.doc_id(doc, shelf)
            return self.check([] if pages else [d], [(d, p) for p in pages or ()], shelf, local, model, policy)
        rows = L()
        for n in self._populated():
            try: rows += self.check([r['id'] for r in self._store(n).sources()], (), n, local, model, policy).rows
            except Exception: continue
        wh = rows.filter(lambda i: i.how == 'withheld')
        return AttrDict(ok=not wh, local=local, model=model, kind=None if not wh else 'local_only' if all(i.level == 'local' for i in wh) else 'pii_blocked',
                        rows=rows, withheld=wh, masked=rows.filter(lambda i: i.how == 'masked'), send=rows.filter(lambda i: i.how != 'withheld'),
                        kinds={}, why=send_line(rows, model, local))
    def ask(self, q, doc=None, shelf=None, pages=None, model=None, mk_chat=None, pii='redact', pii_model=None):
        "A cited answer from the whole vault, one document or pages of it. Each citation carries its shelf, a 0-based page in scope and a quote."
        v, w = self._shelf(shelf), self.scope(doc, shelf, pages)
        kw = dict(where=w, shelves=0, related=0) if w else {}
        out = v.ask(q, model=model, mk_chat=mk_chat, pii=pii, pii_model=pii_model, code=0, **kw)
        res, cites = list(out.context.results), []
        for c in out.cited:
            r = res[c['n'] - 1] if 0 < c['n'] <= len(res) else {}
            store, did = r.get('store') or v.name, c.get('doc_id')
            if not did: continue
            sv = v if store == v.name else v.shelf(store)
            wh = "node_id='{}'".format(str(c['node_id']).replace("'", "''")) + (f" AND page IN ({','.join(map(str, pages))})" if pages else '')
            hit = first(sv.search(q, limit=1, where=wh)) if c.get('node_id') else None
            pg = hit.get('page') if hit else (r.get('pages') or [None])[0]
            if pages and pg not in pages: pg = pages[0]
            cites.append(dict(n=c['n'], doc=did, shelf=self._shelf_name(store), title=c.get('title') or c.get('breadcrumb') or did, page=pg,
                              quote=' '.join(str((hit or {}).get('snippet') or '').split())[:80]))
        return dict(answer=out.answer or '', cited=cites, refused=bool(out.get('refused')), level=out.get('level'), model=out.model,
                    send=dict(why=out.send.why, kind=out.send.kind, ok=out.send.ok) if out.get('send') else None)
    def typed(self, rows):
        "Rows with each document's type, proposed type and level, read on the shelf that holds it."
        def one(r):
            m = r.get('meta') or {}
            try: lv = self._store(r.get('shelf') or self.shelf_name).level(str(r.get('doc_id') or r.get('id')))
            except Exception: lv = {}
            return dict(r, doctype=m.get('doctype') or lv.get('doctype'), proposed=m.get('doctype_proposed'), level=lv.get('level'))
        return [one(r) for r in rows]
    def types(self, shelf=None):
        "Documents whose type is a guess waiting on a person, surest first."
        def f(n, v):
            for r in v.proposed_types():
                m = r['meta'] or {}
                yield dict(doc=r['id'], title=r['title'], proposed=m.get('doctype_proposed'), doctype=m.get('doctype'),
                           score=m.get('doctype_score'), by=m.get('doctype_by'))
        return self._across([shelf] if shelf else None, lambda n, v: list(f(n, v)), lambda n: f'{n} types to decide')
    TYPE_KEYS = ('doctype', 'doctype_proposed', 'doctype_by', 'doctype_score')
    def judge_type(self, doc, verdict, shelf=None, doctype=None, was=None):
        "`accept` a proposal (or `doctype` instead), `reject` it, or `undo` back to `was`. Answers what it was before, for an undo."
        from varga import DOCTYPES
        v = self._shelf(shelf)
        did = self.doc_id(doc, shelf)
        m = v.doc(did)['meta']
        prev = {k: m.get(k) for k in self.TYPE_KEYS}
        if verdict == 'undo':
            if not isinstance(was, dict): raise VaultRefused('undo needs what it was', 'bad_request')
            v.set_meta(did, **{k: was.get(k) for k in self.TYPE_KEYS})
        elif doctype and doctype not in DOCTYPES and doctype != 'other': raise VaultRefused(f'{doctype} is not a type', 'bad_request')
        elif not m.get('doctype_proposed') and not (verdict == 'accept' and doctype):
            raise VaultRefused('nothing is proposed for this document now', 'stale', 409)
        elif verdict == 'accept': v.accept_type(did, doctype or None)
        else: v.reject_type(did)
        return dict(doc=did, was=prev, doctype=v.doc(did)['meta'].get('doctype'))
    def guess_types(self, shelf=None):
        "Type every untyped document from its cues alone: no model is asked, so nothing leaves this machine."
        out = self._across([shelf] if shelf else None, lambda n, v: [dict(r) for r in v.categorize_all(llm='never').results], lambda n: f'{n} typed')
        return dict(typed=sum(bool(r.get('saved')) for r in out), proposed=sum(bool(r.get('proposed')) for r in out), checked=len(out))
    def guess_type(self, doc, shelf=None):
        "Type one document from its cues, unless a type is already there: a person's accept is not overwritten."
        v = self._shelf(shelf)
        if (v.doc(str(doc)) or {}).get('meta', {}).get('doctype'): return None
        return dict(v.categorize(str(doc), llm='never'))
    @staticmethod
    def _versions(v, did):
        "`{page: version}` of a read document; `{}` for one never read page by page."
        try: return {p['page']: p['version'] for p in v.pages(did)}
        except Exception: return {}
    def fields(self, doc, shelf=None):
        "What was extracted from a document: each field's value, page, block, quote and the warnings `check_fields` gave it."
        v, did = self._shelf(shelf), self.doc_id(doc, shelf)
        m = v.doc(did)['meta']
        if 'extracted' not in m: return dict(extracted=False, schema=None, doctype=m.get('doctype'), fields=[])
        src, errs = m.get('extracted_src') or {}, m.get('extracted_errors') or []
        cur, seen = self._versions(v, did), m.get('extracted_versions') or {}
        def one(f, x):
            s = src.get(f) or {}
            return dict(field=f, value=x, page=s.get('page'), block=s.get('block'), quote=s.get('quote'),
                        stale=s.get('page') is not None and str(s.get('page')) in seen and seen[str(s.get('page'))] != cur.get(s.get('page')),
                        errors=[e.get('why') for e in errs if e.get('field') == f])
        return dict(extracted=True, schema=m.get('extracted_as'), doctype=m.get('doctype'), model=m.get('extracted_by'),
                    at=m.get('extracted_at'), fields=[one(f, x) for f, x in (m.get('extracted') or {}).items()])
    def extract(self, doc, shelf=None, model=None, chat_kw=None, pii='redact', name=''):
        "Fields with the page and quote each was read from, saved on the document beside the warnings `check_fields` gave."
        from varga.schema import SCHEMAS
        v, did = self._shelf(shelf), self.doc_id(doc, shelf)
        dt = v.doc(did)['meta'].get('doctype')
        # with a type, its schema; without one, cues only: a confident model verdict must not overwrite what a person accepted
        out = v.extract(did, schema=dt if dt in SCHEMAS else None, model=model, chat_kw=chat_kw, save=True, cite=True, pii=pii, llm='never')
        if out.get('refused'): raise PrivacyBlocked(f"{out.get('title') or did} was not sent to {name or model or 'the model'}: it is "
                                                    f"{out.get('level') or 'personal'} and that model is hosted", out.get('kind') or 'pii_blocked', [did])
        if out.get('skipped'): raise VaultRefused(str(out.skipped), 'failed', 422)
        errs = [dict(field=e['field'], value=str(e.get('value')), why=e['why']) for e in out.get('errors') or []]
        v.set_meta(did, extracted_errors=errs, extracted_at=time.time(), extracted_by=name or out.get('model'),
                   extracted_versions={str(k): n for k, n in self._versions(v, did).items()})
        return dict(doc_id=did, schema=out.schema, fields=len(out.fields or {}), errors=len(errs), level=out.get('level'))
    def pii(self, doc_id, shelf=None, ner=True):
        "The PII report for one document, or why there is none."
        try: return dict(self._shelf(shelf).pii(doc_id, ner=ner))
        except Exception as e: return dict(note=f'pii unavailable ({errstr(e)})', has_pii=False)
    def text_pass(self, src, shelf=None, parse='auto'):
        "Each page of a PDF or page image as `read_doc` has it before any model reads it: text layer, local OCR, route and flags."
        from vishalakshi.read import IMG_EXTS, read_doc
        p = Path(_resolved(src))
        if not p.is_file(): raise VaultRefused(f'no file at {src}', 'not_found', 404)
        if p.suffix.lower() not in ('.pdf', *IMG_EXTS): raise VaultRefused(f'{p.name} is not a PDF or a page image', 'unsupported')
        ocr = parse if parse in ('auto', 'ocr') else 'text'
        key = (str(p), p.stat().st_mtime_ns, ocr)
        if key not in _PASSES: _PASSES[key] = read_doc(p, ocr, pages=[], out=self._shelf(shelf).assets(p.stem))
        return _PASSES[key]
    def read_plan(self, src, shelf=None, parse='auto', model=None, pages=None, pii='redact', allow=False, level=None, name=''):
        "What a read of `src` sends where, page by page, by `read_doc`'s rules: the line above the Read button."
        from vishalakshi.ask import model_local, send_line, send_rule
        from vishalakshi.pii import pii_report, top, type_policy
        p, v = _resolved(src), self._shelf(shelf)
        rows, want = self.text_pass(p, shelf, parse), None if pages is None else set(pages)
        need = [r for r in rows if (want is None or r.page in want) and (parse == 'llm' or (parse == 'auto' and (r.route == 'scanned' or bool(r.flags))))]
        tp = type_policy(text='\n\n'.join(r.text for r in rows)[:6000])
        d = v.doc(p)
        doc = d['id'] if d and d['source'] == p else None
        cur = v.level(doc).level if doc else v.floor()
        # a sensitive type raises the level whatever `pii` says: `read_doc` skips that step under `off`
        lv0, chat = top(cur, level, tp.level), read_chat(model)
        loc = model_local(chat if chat is not None else model) if model or chat is not None else True
        items = L()
        for r in need:
            rep = pii_report(r.text, ner=True) if r.text.strip() else None
            lv = top(lv0, 'personal' if rep and rep.has_pii else 'open')
            how = send_rule(lv, loc, pii, allow, image=True) if model or chat is not None else 'kept'
            items.append(AttrDict(page=r.page, level=lv, how=how, kinds=dict(rep.identifying) if rep and rep.has_pii else {}))
        wh, kinds = items.filter(lambda i: i.how == 'withheld'), dict(sum((Counter(i.kinds) for i in items), Counter()))
        why = (send_line(items, name or str(model), loc) if model or chat is not None else
               f"No model chosen. {len(rows)} page{'' if len(rows) == 1 else 's'} keep their text layer and local OCR; nothing leaves this machine.")
        pick = lambda how: [dict(page=i.page, level=i.level) for i in items if i.how == how]
        return AttrDict(ok=not wh, kind=None if not wh else 'local_only' if all(i.level == 'local' for i in wh) else 'pii_blocked',
                        why=why, local=loc, model=name or model, kinds=kinds, send=pick('whole') + pick('masked'), withheld=pick('withheld'),
                        src=p, doc=doc, pages=len(rows), need=[r.page for r in need], level=lv0, current=cur,
                        flags={r.page: list(r.flags) for r in rows if r.flags}, routes=dict(Counter(r.route for r in rows)),
                        type=dict(doctype=tp.doctype, preset=tp.preset, level=tp.level, vision=tp.vision, sensitive=tp.sensitive,
                                  decisive=bool(tp.decisive), score=tp.score))
    def read_file(self, src, shelf=None, parse='auto', model=None, preset='generic', hint='', pages=None, pii='redact', allow=False, level=None, progress=None):
        "Read `src` into the vault page by page. The level the read needs is set before any page image is sent; no model means nothing leaves."
        from vishalakshi.pii import LEVELS
        v, p = self._shelf(shelf), _resolved(src)
        # a shelf first written here starts at the vault's floor, not below it
        if LEVELS.index(fl := self.floor()) > LEVELS.index(v.floor()): v.set_floor(fl, by='leela')
        plan = self.read_plan(p, shelf, parse, model, pages, pii, allow, level)
        if LEVELS.index(plan.level) > LEVELS.index(plan.current):
            if not plan.doc: v.read_doc(p, parse='text', pages=[])
            v.set_level(p, plan.level, reason='set before the read')
        chat = read_chat(model)
        if not model and chat is None: pages = []
        out = dict(v.read_doc(p, parse=parse, model=model or None, preset=preset, hint=hint, pages=pages, chat=chat, pii=pii, allow=allow, progress=progress))
        return dict(out, shelf=self._shelf_name(shelf or self.shelf_name), level=v.level(out['doc_id']).level)
    def set_book(self, doc, shelf=None, preset='sanskrit', counts=None):
        "Mark a read document a book of verses. Only how to assemble it is kept: the chapters are assembled from the pages whenever asked."
        v, did = self._shelf(shelf), self.doc_id(doc, shelf)
        old = v.doc(did)['meta'].get('book') or {}
        v.set_meta(did, book=dict(preset=preset, script=VERSE_SCRIPT[preset], counts=counts, at=time.time(), states=old.get('states') or {},
                                  versions={str(k): n for k, n in self._versions(v, did).items()}))
        return self.book(did, shelf)
    def book(self, doc, shelf=None):
        "A book's chapters and problems as its pages read now; a problem keeps the state a person gave it, and `changed` names pages read again since."
        from lekhaka import bad_aksharas, fix_aksharas, read_book, vnum
        v, did = self._shelf(shelf), self.doc_id(doc, shelf)
        b = v.doc(did)['meta'].get('book')
        if not b: raise VaultRefused('this document was not read as a book of verses', 'not_found', 404)
        o, ps = read_book(None, vault=_Read(v, did), preset=b['preset'], script=b['script'], counts=b.get('counts'), fix=False), v.pages(did)
        at = {(p.page, vnum(x.get('n'))): i for p in ps for i, x in enumerate(p.blocks or []) if x.get('kind') in ('verse', None)}
        probs = list(o.probs)
        for c in o.chapters:
            for x in c['verses']:
                x['block'] = at.get((x['page'], x['n']))
                if b['script'] == 'Devanagari' and (bad := bad_aksharas(x['text'])):
                    probs.append(f"{x['page']}: verse {x['n']}: {', '.join(bad)}, mended"); x['text'] = fix_aksharas(x['text'])
        seen, rows = Counter(), []
        for t in probs:
            pg, txt = _prob_page(t)
            pid = hashlib.sha1(f'{t}\0{seen[t]}'.encode()).hexdigest()[:10]; seen[t] += 1
            rows.append(dict(id=pid, page=pg, text=txt, state=b['states'].get(pid, 'open')))
        cur = self._versions(v, did)
        return dict(doc=did, title=v.doc(did)['title'], preset=b['preset'], counts=b.get('counts'), at=b.get('at'), chapters=o.chapters, probs=rows,
                    verses=sum(len(c['verses']) for c in o.chapters), changed=sorted(k for k, n in cur.items() if b['versions'].get(str(k)) != n))
    def judge_probs(self, doc, ids, verdict, shelf=None):
        "`accept` says a problem is checked, `reject` that it is none, `undo` opens it again. `stale` names ids the pages no longer give."
        v, did = self._shelf(shelf), self.doc_id(doc, shelf)
        ids = [i for i in ids if i]
        if not ids: raise VaultRefused('no problem chosen', 'bad_request')
        have = {r['id'] for r in self.book(did, shelf)['probs']}
        if bad := [i for i in ids if i not in have]: raise VaultRefused('the pages were read again: these problems are gone', 'stale', 409, ids=bad)
        b = v.doc(did)['meta']['book']
        st = dict(b.get('states') or {})
        for i in ids:
            if verdict == 'undo': st.pop(i, None)
            else: st[i] = 'checked' if verdict == 'accept' else 'dismissed'
        v.set_meta(did, book=dict(b, states=st))
        return dict(probs=[r for r in self.book(did, shelf)['probs'] if r['id'] in ids])
    def book_problems(self, doc=None, shelf=None, state='open'):
        "Problems in `state` in one book, or in every book in the vault."
        def f(n, v, d):
            if not (d.get('meta') or {}).get('book'): return []
            b = self.book(d['id'], n)
            return [dict(r, doc=d['id'], title=b['title']) for r in b['probs'] if not state or r['state'] == state]
        if doc: return [dict(r, shelf=self._shelf_name(shelf or self.shelf_name)) for r in f(shelf, self._doc(doc, shelf), dict(self.document(doc, shelf)))]
        return self._across(None, lambda n, v: [r for d in v.sources(None) for r in f(n, v, dict(d, id=d.get('doc_id') or d.get('id')))],
                            lambda n: f'{n} problems')
    def book_md(self, doc, shelf=None):
        from lekhaka import book_md
        b = self.book(doc, shelf)
        return book_md(b['chapters'], b['title'])
    def save_book_md(self, doc, shelf=None):
        "The book as markdown beside the file it was read from."
        src = Path(str(self.document(doc, shelf).get('source') or ''))
        if not src.is_file(): raise VaultRefused('this document was not read from a file on this machine', 'not_found', 404)
        out = src.with_name(f'{src.stem}.BOOK.md')
        out.write_text(self.book_md(doc, shelf))
        return str(out)
    def sends(self, doc=None, shelf=None, limit=100):
        "What left this machine and for which model, newest first, with each document's title: one document, or every shelf."
        def f(v, rows):
            titles = {}
            def t(did): return titles.setdefault(did, (v.doc(did) or {}).get('title') or did)
            return [dict(r, title=t(r['doc_id'])) for r in rows]
        if doc:
            v = self._doc(doc, shelf)
            return [dict(r, shelf=self._shelf_name(shelf or self.shelf_name)) for r in f(v, v.sends(str(doc), limit))]
        return sorted(self._across(None, lambda n, v: f(v, v.sends(None, limit)), lambda n: f'{n} sends'), key=lambda r: -r['at'])[:limit]
    def floor(self):
        "The vault's privacy floor: the highest any of its shelves holds."
        from vishalakshi.pii import top
        return top(*[self._store(n).floor() for n in self._populated()])
    def set_floor(self, level, by):
        "Set every shelf's floor. Only a person lowers one."
        for n in self._populated(): self._store(n).set_floor(level, by=by)
        return self.floor()
    def pages(self, doc, shelf=None, history=False):
        "A read document's pages, 0-based, latest version each or every version."
        return [dict(r, flags=r['flags'] if isinstance(r['flags'], list) else json.loads(r['flags'] or '[]'))
                for r in self._shelf(shelf).pages(str(doc), history=history)]
    def page(self, doc, page, shelf=None, version=None):
        "One read page: its text, blocks, route, flags and the versions it has."
        rows = [r for r in self.pages(doc, shelf, history=True) if r['page'] == int(page)]
        if not rows: raise VaultRefused(f'page {int(page) + 1} was never read', 'not_found', 404)
        r = first(x for x in rows if x['version'] == int(version)) if version else rows[-1]
        if r is None: raise VaultRefused(f'page {int(page) + 1} has no version {version}', 'not_found', 404)
        return dict(r, blocks=json.loads(r.get('blocks') or 'null'), versions=[x['version'] for x in rows])
    def page_image(self, doc, page, shelf=None, w=0):
        "`(bytes, type)` of one page of a document's source, rendered in memory."
        row = self.document(doc, shelf)
        if not row: raise VaultRefused(f'no document {doc}', 'not_found', 404)
        src = Path(str(row.get('source') or ''))
        try: mtime = src.stat().st_mtime_ns
        except OSError: raise VaultRefused(f'{src} is no longer on disk', 'render_failed', 422) from None
        try: return _render(str(src), mtime, int(page), max(0, min(2000, int(w or 0))))
        except Exception as e: raise VaultRefused(f'page {int(page) + 1} would not render ({errstr(e)})', 'render_failed', 422) from e
    def level(self, doc, shelf=None):
        "A document's privacy level, with what decided it."
        try: return dict(self._shelf(shelf).level(str(doc)))
        except ValueError as e: raise VaultRefused(str(e), 'not_found', 404) from e
    def set_level(self, doc, level=None, shelf=None, reason='', by='person'):
        "Set a document's level, or None to let detection decide. Only a person lowers one."
        if not self._shelf(shelf).doc(str(doc)): raise VaultRefused(f'no document {doc}', 'not_found', 404)
        self._shelf(shelf).set_level(str(doc), level or None, reason=reason, by=by)
        return self.level(doc, shelf)
    def _doc(self, doc, shelf=None):
        v = self._shelf(shelf)
        if not v.doc(str(doc)): raise VaultRefused(f'no document {doc}', 'not_found', 404)
        return v
    def reparse(self, doc, shelf=None, pages=None, model=None, preset=None, hint=None, pii='redact', allow=False, progress=None):
        "Read `pages` of a read document again by `model`; each new text is a new version."
        out = dict(self._doc(doc, shelf).reparse(str(doc), pages=pages, model=model, preset=preset, hint=hint, chat=read_chat(model),
                                                 pii=pii, allow=allow, progress=progress))
        return dict(out, shelf=self._shelf_name(shelf or self.shelf_name))
    def proofread(self, doc, readers, shelf=None, pages=None, agree=2, pii='redact', allow=False, progress=None):
        "Each reader reads the pages again; their word changes are filed for review."
        chats = {r: c for r in readers if (c := read_chat(r)) is not None}
        out = dict(self._doc(doc, shelf).proofread(str(doc), list(readers), pages=pages, agree=agree, chats=chats or None,
                                                   pii=pii, allow=allow, progress=progress))
        return dict(out, shelf=self._shelf_name(shelf or self.shelf_name))
    def page_check(self, doc, pages, readers, shelf=None, pii='redact', allow=False):
        "Where page images of `doc` go for each reader `(id, name)`, at the document's level, as `reparse` and `proofread` gate them."
        v = self._doc(doc, shelf)
        lv = v.level(str(doc)).level
        pgs = [(str(doc), p) for p in (pages if pages is not None else [r.page for r in v.pages(str(doc))])]
        lines, wh, kinds, kind = [], set(), Counter(), None
        for rid, name in readers:
            c = v.send_check(pages=pgs, model=read_chat(rid) or rid, policy=pii, allow=allow, image=True, level=lv)
            lines.append(c.why.replace(str(c.model), name, 1) if c.model and name else c.why)
            wh |= {w.page for w in c.withheld}; kinds.update(c.kinds); kind = kind or c.kind
        return AttrDict(ok=not wh, kind=kind, why=' '.join(lines), lines=lines, withheld=sorted(wh), kinds=dict(kinds), level=lv,
                        pages=[p for _, p in pgs])
    def as_sent(self, doc, page, shelf=None, pii='redact'):
        "One page's text as a hosted model receives it in an answer or an agent turn: whole, masked through the gate, or withheld."
        from vishalakshi.ask import send_rule
        from vishalakshi.pii import gated, held
        v, r = self._doc(doc, shelf), self.page(doc, page, shelf)
        lv = v.level(str(doc), page=int(page))
        how = send_rule(lv.level, False, pii)
        text = (r['text'] if how == 'whole' else held(lv.kinds or {lv.level: 1}) if how == 'withheld' else
                gated({'doc_id': str(doc), 'store': v.name, 'text': r['text']}, 'redact', vault=v, ner=True)['text'])
        return dict(text=text, how=how, level=lv.level, kinds=dict(lv.kinds), version=r['version'])
    def page_diff(self, doc, page, a, b, shelf=None):
        "Two versions of one page as diff rows."
        from ...core.web import diff_payload
        return diff_payload(self.page(doc, page, shelf, a)['text'], self.page(doc, page, shelf, b)['text'], 'page.md')
    def page_crop(self, doc, page, box, shelf=None):
        "The part of a page a change sits in, as PNG; the whole page without a box."
        from vishalakshi.read import crop
        b, mime = self.page_image(doc, page, shelf)
        return (crop(b, box), 'image/png') if box else (b, mime)
    def _paged(self, f, doc=None, shelf=None):
        "`f(v, doc_row)` for one document, or for every paged document on every shelf."
        if doc: return [dict(r, shelf=self._shelf_name(shelf or self.shelf_name)) for r in f(self._doc(doc, shelf), dict(self.document(doc, shelf)))]
        def each(n, v):
            return [r for d in v.sources(None) if str(d.get('kind')) in ('pdf', 'image') for r in f(v, dict(d, id=d.get('doc_id') or d.get('id')))]
        return self._across(None, each, lambda n: f'{n} rows to review')
    def changes(self, doc=None, shelf=None, state=None, page=None):
        "Proofreading changes still to decide, or in `state`. `stale` where the page has a newer version than the change was made against."
        def f(v, d):
            cur = {p.page: p.version for p in v.pages(d['id'])}
            rows = v.changes(d['id'], state or None, page)
            if not state: rows = rows.filter(lambda c: c.state in ('proposed', 'doubt'))
            return [dict(c, doc=d['id'], title=d.get('title') or '', stale=cur.get(c.page) != c.version) for c in rows]
        return self._paged(f, doc, shelf)
    def _decided(self, doc, ids, shelf, states=('proposed', 'doubt')):
        "The changes `ids` names, refused as `stale` when one is gone, decided already, or made against an older page."
        v, ids = self._doc(doc, shelf), [i for i in ids if i]
        if not ids: raise VaultRefused('no change chosen', 'bad_request')
        cs, cur = {c.id: c for c in v.changes(str(doc))}, {p.page: p.version for p in v.pages(str(doc))}
        bad = [i for i in ids if i not in cs or cs[i].state not in states or (cs[i].state in ('proposed', 'doubt') and cur.get(cs[i].page) != cs[i].version)]
        if bad: raise VaultRefused('the page was read or decided again since: proofread it again', 'stale', 409, ids=bad)
        return v, [cs[i] for i in ids], cur
    def accept_changes(self, doc, ids, shelf=None, after=None, edits=None):
        "Apply changes as one new version per page. `edits` (`{id: after}`), or `after` for a single change, replaces proposed text first."
        v, cs, _ = self._decided(doc, ids, shelf)
        edits = dict(edits or {})
        if after is not None:
            if len(cs) != 1: raise VaultRefused('an edit is for one change', 'bad_request')
            edits[cs[0].id] = after
        if bad := [i for i in edits if i not in {c.id for c in cs}]: raise VaultRefused('an edit names a change not being accepted', 'bad_request', ids=bad)
        for i, a in edits.items():
            if not (o := v.edit_change(str(doc), i, a)).get('ok'): raise VaultRefused(o['error'], o['kind'], 409 if o['kind'] == 'stale' else 404, ids=o.get('ids') or [i])
        return dict(v.accept(str(doc), [c.id for c in cs]))
    def reject_changes(self, doc, ids, shelf=None):
        v, cs, _ = self._decided(doc, ids, shelf)
        return dict(rejected=v.reject(str(doc), [c.id for c in cs]))
    def undo_changes(self, doc, ids, shelf=None):
        "Undo one decision. A reject goes back to what it was; an accept files the page's text from before it as a new version and its changes are open again."
        v, ids = self._doc(doc, shelf), [i for i in ids if i]
        if not ids: raise VaultRefused('no change chosen', 'bad_request')
        o = v.undo_decision(str(doc), ids)
        # a change gone from the queue (proofread again since) is stale to the screen, as `_decided` has it
        if not o.get('ok'): raise VaultRefused(o['error'], 'stale', 409, ids=o.get('ids') or [])
        return dict(undone=len(o['undone']), ids=o['undone'], pages=o['pages'])
    def revert_page(self, doc, page, version, shelf=None):
        "File an old version of a page as its newest, and re-index."
        o = self._doc(doc, shelf).revert_page(str(doc), int(page), int(version))
        if not o.get('ok'): raise VaultRefused(o['error'], o['kind'], 404)
        return dict(page=o['page'], version=o['version'])
    def proof_md(self, doc, shelf=None): return self._doc(doc, shelf).proof_md(str(doc))
    def save_proof_md(self, doc, shelf=None):
        "PROOFREAD.md beside the file the document was read from."
        src = Path(str(self.document(doc, shelf).get('source') or ''))
        if not src.is_file(): raise VaultRefused('this document was not read from a file on this machine', 'not_found', 404)
        out = src.with_name(f'{src.stem}.PROOFREAD.md')
        out.write_text(self.proof_md(doc, shelf))
        return str(out)
    def findings(self, doc=None, shelf=None, state=None, page=None):
        "Filed personal-information findings with masked previews, never the values."
        return self._paged(lambda v, d: [dict(r, doc=d['id'], title=d.get('title') or '') for r in v.findings(d['id'], state or None, page)], doc, shelf)
    def judge_pii(self, doc, ids, verdict, shelf=None):
        "`accept` says personal, `reject` says not, `undo` hands the finding back to detection. Each moves every occurrence of the value."
        v, ids = self._doc(doc, shelf), [i for i in ids if i]
        if not ids: raise VaultRefused('no finding chosen', 'bad_request')
        out = (v.accept_pii(str(doc), ids) if verdict == 'accept' else v.reject_pii(str(doc), ids, by='person') if verdict == 'reject'
               else v.reset_pii(str(doc), ids, by='person'))
        if not out.get('ok'): raise VaultRefused(out.get('error') or 'these findings are gone', out.get('kind') or 'stale', 409, ids=out.get('ids') or [])
        return dict(ok=True, privacy=dict(out['privacy']))
    def scan_pii(self, doc, shelf=None): return dict(self._doc(doc, shelf).scan_pii(str(doc)))
    def noisy_candidates(self, shelf=None, k=20, min_score=1.0):
        "Documents the vault thinks are diluting retrieval, ranked, with the features that say so."
        v = self._shelf(shelf)
        try: return [dict(r) for r in v.suggest_noisy(k=k, min_score=min_score)]
        except Exception as e:
            self.note = f'noise ranking unavailable ({errstr(e)})'
            return []
    def mark_noisy(self, doc_id, shelf=None, noisy=True, reason=''):
        "Judgements live in `doc_marks`, keyed (doc_id, store), so re-ingesting cannot erase them."
        return dict(self._shelf(shelf).mark_noisy(doc_id, noisy=noisy, reason=reason))
    def watch(self, target, action='url', every='1d', note=None, shelf=None, **params):
        if action in ('url', 'arxiv', 'youtube'): params.setdefault('force', True)
        v = self._shelf(shelf)
        return dict(v.watch(target, action=action, every=every, note=note, **params))
    def watches(self, shelf=None, due_only=False):
        try: return [dict(w) for w in self._shelf(shelf).watches(due_only=due_only)]
        except Exception as e:
            self.note = f'watches unavailable ({errstr(e)})'
            return []
    def unwatch(self, watch_id, shelf=None): return self._shelf(shelf).unwatch(watch_id)
    def poll(self, shelf=None):
        "Run every watch that has come due. The tick a scheduler calls."
        try: return dict(self._shelf(shelf).poll(connect=not self.offline))
        except Exception as e: return dict(note=f'poll failed ({errstr(e)})', ran=0, checked=0)
