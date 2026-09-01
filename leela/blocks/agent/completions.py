"What the inline AI panel was asked, what answered, and whether the answer was taken."

from __future__ import annotations
from collections import Counter

from fastcore.all import L, Path

from ... import leela_cfg
from ..search.signals import Signals

__all__ = ['KINDS', 'FIELDS', 'SNIPPET_FIELDS', 'VERDICTS', 'completions_dir', 'completions', 'summary', 'judgements']

#: `stale` is a replace that could not be applied because the selection moved under it. It is not
#: an accept and it is not a discard, and counting it as either would flatter or libel the model.
KINDS = ('ask', 'reply', 'error', 'replace', 'discard', 'stale', 'abandon')

#: What became of a suggestion. One ask can report a `stale` and then a verdict, and the last one
#: is what became of it.
VERDICTS = ('replace', 'discard', 'stale', 'abandon')

FIELDS = ('session', 'ask_id', 'kind', 'mode', 'model', 'lang', 'path', 'chars', 'ms',
          'tools', 'steps', 'instruction', 'text', 'reply')

#: The selection and the suggestion are the person's code. The instruction is theirs too, but it is
#: the label on the judgement, so it is kept for the same reason search keeps the query.
SNIPPET_FIELDS = ('text', 'reply')

def completions_dir(): return Path(leela_cfg)/'ai-events'

def completions(dir=None):
    "The event store for the inline panel."
    return Signals(dir=dir or completions_dir(), kinds=KINDS, fields=FIELDS,
                   snippet_fields=SNIPPET_FIELDS)

def summary(rows, recent=20):
    "What was asked and how often the answer was taken, per model."
    rows = L(rows)
    asks = {r['ask_id']: r for r in rows if r.get('kind') == 'ask' and r.get('ask_id')}
    replies = {r['ask_id']: r for r in rows if r.get('kind') == 'reply' and r.get('ask_id')}
    took, left, by_model = 0, 0, {}
    seen = []
    # One outcome per ask, and the last. An outcome with no id has no identity to be superseded by.
    outcomes = {}
    for r in rows:
        if r.get('kind') in ('replace', 'discard', 'stale'):
            outcomes[r.get('ask_id') or f'-{len(outcomes)}'] = r
    for r in outcomes.values():
        kind = r.get('kind')
        ask, reply = asks.get(r.get('ask_id'), {}), replies.get(r.get('ask_id'), {})
        model = reply.get('model') or ask.get('model') or 'unknown'
        m = by_model.setdefault(model, {'model': model, 'replaced': 0, 'discarded': 0, 'stale': 0})
        m[{'replace': 'replaced', 'discard': 'discarded', 'stale': 'stale'}[kind]] += 1
        if kind == 'replace': took += 1
        elif kind == 'discard': left += 1
        seen.append({'at': r.get('at'), 'kind': kind, 'model': model, 'ms': reply.get('ms'),
                     'tools': reply.get('tools'), 'lang': ask.get('lang'), 'path': ask.get('path'),
                     'instruction': ask.get('instruction'), 'ask_id': r.get('ask_id')})
    for m in by_model.values():
        decided = m['replaced'] + m['discarded']
        m['accept_rate'] = round(m['replaced'] / decided, 3) if decided else None
    decided = took + left
    return {'asks': len(asks), 'answered': len(replies), 'replaced': took, 'discarded': left,
            'accept_rate': round(took / decided, 3) if decided else None,
            'models': sorted(by_model.values(), key=lambda m: -(m['replaced'] + m['discarded'])),
            'kinds': dict(Counter(r.get('kind') for r in rows)),
            'recent': list(reversed(seen))[:recent]}


def judgements(rows, snippets=True, limit=200):
    "One row per ask: what was asked, what came back, and what became of it. `snippets` keeps the text."
    rows = L(rows)
    asks = {r['ask_id']: r for r in rows if r.get('kind') == 'ask' and r.get('ask_id')}
    held, out = {}, []
    def code(text, reply): return ('kept' if snippets else 'withheld') if (
        text is not None or reply is not None) else 'not kept'
    for r in rows:
        kind, aid = r.get('kind'), r.get('ask_id') or ''
        if kind == 'ask' and aid in asks: continue
        if aid in asks:
            held.setdefault(aid, {})[
                'verdict' if kind in VERDICTS else 'error' if kind == 'error' else kind] = r
            continue
        out.append({'ask_id': aid, 'orphan': True, 'at': r.get('at'), 'kind': kind,
                    'mode': r.get('mode'), 'instruction': r.get('instruction') or '',
                    'lang': r.get('lang'), 'path': r.get('path'), 'chars': r.get('chars'),
                    'model': r.get('model'), 'ms': r.get('ms'), 'tools': r.get('tools'),
                    'code': code(r.get('text'), r.get('reply')),
                    'text': r.get('text') if snippets else None,
                    'reply': r.get('reply') if snippets else None})
    for aid, ask in asks.items():
        got = held.get(aid, {})
        reply, verdict, error = got.get('reply', {}), got.get('verdict'), got.get('error')
        # an errored ask reads as errored, not as one nobody answered
        first = error if (error and (verdict or {}).get('kind') in (None, 'abandon')) else verdict
        out.append({
            'ask_id': aid, 'orphan': False, 'at': ask.get('at'),
            'kind': (first or reply or ask).get('kind'),
            'mode': ask.get('mode'), 'instruction': ask.get('instruction') or '',
            'lang': ask.get('lang'), 'path': ask.get('path'), 'chars': ask.get('chars'),
            'model': reply.get('model'), 'ms': reply.get('ms'), 'tools': reply.get('tools'),
            'code': code(ask.get('text'), reply.get('reply')),
            'text': ask.get('text') if snippets else None,
            'reply': reply.get('reply') if snippets else None})
    # file order, which is write order: `at` comes from the browser's clock and a late flush reorders it
    return list(reversed(out))[:limit]
