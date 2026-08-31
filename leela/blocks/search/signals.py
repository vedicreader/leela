"""What a search was asked, what it showed, and what turned out to be worth opening.

The event log is the exact record and the vault holds one document per session. `docs/search.md`
says why there are two.
"""

from __future__ import annotations
import json, os, time
from collections import Counter, defaultdict

from fastcore.all import L, Path

from ... import errstr, leela_cfg

__all__ = ['KINDS', 'FIELDS', 'KEEP_DAYS', 'Signals', 'events_dir', 'search_vault_path']

#: What the client may report. A kind not named here is dropped rather than stored unvalidated.
KINDS = ('query', 'leg', 'impression', 'preview', 'open', 'refine', 'mode', 'abandon')

#: The columns of one event. Anything else the client sends is dropped, so a future field cannot
#: quietly become personal data nobody agreed to keep.
FIELDS = ('session', 'query_id', 'kind', 'q', 'mode', 'scope', 'exts', 'leg', 'ms', 'n', 'rank',
          'key', 'path', 'line', 'symbol', 'sources', 'score', 'why', 'dwell', 'text', 'shown')

#: Text fields, kept only when `search.snippets` is on.
SNIPPET_FIELDS = ('text',)

KEEP_DAYS = 90

def events_dir(): return Path(leela_cfg)/'search-events'

def search_vault_path():
    "The telemetry vault: `$LEELA_SEARCH_VAULT`, else its own file beside the memory vault."
    env = os.getenv('LEELA_SEARCH_VAULT')
    return Path(env) if env else Path.home()/'.vishalakshi'/'search.db'

def _num(v, default=0.0):
    try: return float(v)
    except (TypeError, ValueError): return default

class Signals:
    "One day's file of search events, the metrics fitted from them, and the session documents."
    def __init__(self, dir=None, vault=None, keep_days=KEEP_DAYS,
                 kinds=KINDS, fields=FIELDS, snippet_fields=SNIPPET_FIELDS):
        # The columns are the caller's: a second surface logs different events through the same
        # store, and `summary` and `remember` below stay search's alone.
        self.dir, self.vault_path, self.keep_days = Path(dir or events_dir()), vault, keep_days
        self.kinds, self.fields, self.snippet_fields = tuple(kinds), tuple(fields), tuple(snippet_fields)
        self.note = ''
    def _file(self, day=None): return self.dir/f'{day or time.strftime("%Y-%m-%d")}.jsonl'
    def files(self): return L(sorted(self.dir.glob('*.jsonl'))) if self.dir.is_dir() else L()
    def _clean(self, row, snippets=False):
        "One event, reduced to the fields this version stores."
        if not isinstance(row, dict) or row.get('kind') not in self.kinds: return None
        out = {k: row[k] for k in self.fields if k in row and row[k] is not None}
        if not snippets:
            for k in self.snippet_fields: out.pop(k, None)
        out['kind'] = row['kind']
        out['at'] = round(_num(row.get('at'), 0) or time.time(), 3)
        return out
    def record(self, rows, snippets=False):
        "Append a batch. Never raises: telemetry that breaks a search is worse than no telemetry."
        kept = L(self._clean(r, snippets) for r in (rows or ())).filter()
        if not kept: return 0
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            with open(self._file(), 'a', encoding='utf-8') as f:
                for row in kept: f.write(json.dumps(row) + '\n')
            self.prune()
            return len(kept)
        except Exception as e:
            self.note = f'could not record search events ({errstr(e)})'
            return 0
    def prune(self):
        "Keep the newest `keep_days` files. A day is one file, so this is a listing and a delete."
        old = self.files()[:-self.keep_days] if self.keep_days else L()
        for p in old:
            try: p.unlink()
            except OSError: pass
        return len(old)
    def read(self, days=30):
        "Every event in the newest `days` files, oldest first, skipping any line that is not one."
        for p in self.files()[-max(1, int(days)):]:
            try: text = p.read_text(encoding='utf-8')
            except OSError: continue
            for line in text.splitlines():
                if not line.strip(): continue
                try: row = json.loads(line)
                except ValueError: continue
                if isinstance(row, dict) and row.get('kind') in self.kinds: yield row
    def purge(self):
        "Delete every event file. The vault documents are the person's to remove separately."
        n = 0
        for p in self.files():
            try: p.unlink(); n += 1
            except OSError: pass
        return n
    def summary(self, days=30, recent=12):
        """The numbers that tune a ranker: where the opened hit sat, which leg found it, and how
        often a search was abandoned or retyped instead."""
        queries, opens, previews, per = {}, L(), L(), {}
        kinds, modes, legs = Counter(), defaultdict(Counter), defaultdict(Counter)
        latency = defaultdict(list)
        for row in self.read(days):
            kind = row['kind']
            kinds[kind] += 1
            qid = str(row.get('query_id') or '')
            held = per.setdefault(qid, {'q': '', 'mode': '', 'at': 0.0, 'n': 0, 'ms': 0,
                                        'previewed': 0, 'opened': [], 'abandoned': False})
            if kind == 'query':
                modes[str(row.get('mode') or '')]['searches'] += 1
                held |= {'q': str(row.get('q') or ''), 'mode': str(row.get('mode') or ''),
                         'at': _num(row.get('at'))}
            if kind == 'impression':
                queries[qid] = row
                held |= {'n': int(_num(row.get('n'))), 'ms': int(_num(row.get('ms')))}
            if kind == 'leg':
                legs[str(row.get('leg') or '')]['found'] += int(_num(row.get('n')))
                latency[str(row.get('leg') or '')].append(_num(row.get('ms')))
            if kind == 'preview':
                previews.append(row)
                held['previewed'] += 1
            if kind == 'abandon': held['abandoned'] = True
            if kind == 'open':
                opens.append(row)
                modes[str(row.get('mode') or '')]['opens'] += 1
                held['opened'].append({'rank': int(_num(row.get('rank'))),
                                       'path': str(row.get('path') or ''),
                                       'symbol': str(row.get('symbol') or ''),
                                       'sources': list(row.get('sources') or ())})
                for leg in (row.get('sources') or ()): legs[str(leg)]['won'] += 1
        ranks = L(int(_num(r.get('rank'), 0)) for r in opens)
        searched = max(kinds['query'], len(queries))
        at = lambda k: round(len(ranks.filter(lambda r: r < k))/len(ranks), 3) if ranks else 0.0
        return {
            'days': days, 'events': sum(kinds.values()), 'kinds': dict(kinds),
            'searches': searched, 'opens': len(opens), 'previews': len(previews),
            'abandon_rate': round(kinds['abandon']/searched, 3) if searched else 0.0,
            'refine_rate': round(kinds['refine']/searched, 3) if searched else 0.0,
            'open_rate': round(len(opens)/searched, 3) if searched else 0.0,
            'mrr': round(sum(1/(1 + r) for r in ranks)/len(ranks), 3) if ranks else 0.0,
            'success_at': {'1': at(1), '3': at(3), '10': at(10)},
            'rank_opens': dict(Counter(ranks)),
            'legs': {k: dict(v) for k, v in sorted(legs.items())},
            'leg_ms': {k: round(sum(v)/len(v)) for k, v in sorted(latency.items()) if v},
            'modes': {k: dict(v) for k, v in sorted(modes.items()) if k},
            'recent': sorted((dict(v, query_id=k) for k, v in per.items() if v['q']),
                             key=lambda r: r['at'], reverse=True)[:recent],
            'note': self.note}
    @staticmethod
    def _document(session):
        "One search session as prose, since that is what a vault can answer questions about."
        q = str(session.get('q') or '').strip()
        shown = session.get('shown') or []
        row = lambda h, mark='': (f"{mark}{h.get('rank', 0) + 1}. {h.get('symbol') or ''} "
                                  f"{h.get('path') or h.get('package') or ''}:{h.get('line') or 0}"
                                  f" · {' + '.join(h.get('sources') or [])}").strip()
        opened = [h for h in shown if h.get('opened')]
        seen = [h for h in shown if h.get('previewed') and not h.get('opened')]
        parts = [f'## Query\n\n{q}\n',
                 f"mode {session.get('mode') or 'all'} · scope {session.get('scope') or 'project'}"
                 f"{' · files ' + session['exts'] if session.get('exts') else ''}\n",
                 '## Opened\n\n' + ('\n'.join(row(h) for h in opened) or 'nothing'),
                 '## Previewed\n\n' + ('\n'.join(row(h) for h in seen) or 'nothing'),
                 '## Shown\n\n' + ('\n'.join(row(h) for h in shown[:20]) or 'nothing')]
        return '\n\n'.join(parts)
    def remember(self, session, memory=None):
        "One document per search session, in its own vault. Returns the doc, or None with a note."
        q = str((session or {}).get('q') or '').strip()
        if not q: return None
        try:
            from ..memory.memory import Memory
            from ..research.research import Doc
            mem = memory or Memory(shelf='searches', path=self.vault_path or search_vault_path())
            key = f"{session.get('session') or ''}:{session.get('query_id') or ''}"
            doc = Doc(title=f'Search: {q[:80]}', url=f'search://{key}', kind='search',
                      text=self._document(session))
            out = mem.remember(doc, query=q, force=True,
                               extra_meta={'search': {k: session.get(k) for k in
                                                      ('mode', 'scope', 'exts', 'opened', 'shown_n')}})
            self.note = mem.note
            return out
        except Exception as e:
            self.note = f'could not write the search vault ({errstr(e)})'
            return None
