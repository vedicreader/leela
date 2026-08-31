"""What the inline AI panel was asked, what answered, and whether the answer was taken.

Accepting or discarding a suggestion is the plainest preference signal in the IDE: a person read
the proposal beside their own code and said yes or no. `blocks/search/signals.py` already stores
events of this shape, so this names the columns and reuses it.
"""

from __future__ import annotations
from collections import Counter

from fastcore.all import L, Path

from ... import leela_cfg
from ..search.signals import Signals

__all__ = ['KINDS', 'FIELDS', 'SNIPPET_FIELDS', 'completions_dir', 'completions', 'summary']

#: `stale` is a replace that could not be applied because the selection moved under it. It is not
#: an accept and it is not a discard, and counting it as either would flatter or libel the model.
KINDS = ('ask', 'reply', 'error', 'replace', 'discard', 'stale', 'abandon')

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
    """What was asked and how often the answer was taken, per model.

    Only the outcomes are counted, never the asks: an ask with no outcome is a panel still open or
    one abandoned, and dividing by it would report a rejection nobody made.
    """
    rows = L(rows)
    asks = {r['ask_id']: r for r in rows if r.get('kind') == 'ask' and r.get('ask_id')}
    replies = {r['ask_id']: r for r in rows if r.get('kind') == 'reply' and r.get('ask_id')}
    took, left, by_model = 0, 0, {}
    seen = []
    for r in rows:
        if (kind := r.get('kind')) not in ('replace', 'discard', 'stale'): continue
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
