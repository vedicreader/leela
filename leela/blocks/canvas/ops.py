"Every change to a canvas goes through one function, whether a person or the helper asked for it."

from __future__ import annotations
import re
from fastcore.all import first, ifnone
from .doc import Brick, KINDS, brick_id

__all__ = ['apply_op', 'OPS']

OPS = ('insert', 'replace', 'remove', 'bind', 'move', 'kind', 'answer', 'replace_selection', 'run', 'values', 'read')

def _at(canvas, op):
    "Where a new brick goes: after a named brick, at an index, or at the end."
    if op.get('after'):
        i = canvas.index(op['after'])
        if i is not None: return i + 1
    return int(op['at']) if isinstance(op.get('at'), int) else len(canvas)

def apply_op(canvas, runtime, op):
    "Apply one op and report what changed. `touched` is what the client must redraw."
    kind = op.get('op')
    if kind not in OPS: return {'ok': False, 'error': f'no op named {kind}'}
    return globals()[f'_{kind}'](canvas, runtime, op)

def _insert(canvas, runtime, op):
    b = Brick(kind=op.get('kind', 'text'), body=op.get('body', ''), attrs=dict(op.get('attrs') or {}),
              binds=dict(op.get('binds') or {}), props=dict(op.get('props') or {}))
    canvas.insert(_at(canvas, op), b)
    out = {'ok': True, 'touched': [b.id], 'brick': b.dict(), 'at': canvas.index(b.id)}
    if b.runs and b.body.strip() and runtime is not None:   # code arrives to be run, whoever wrote it
        r = runtime.run(b)
        out |= {'run': r, **runtime.react(canvas.bricks, r['defs'], skip=[b.id])}
    return out

def _replace(canvas, runtime, op):
    b = canvas.by_id(op.get('id'))
    if b is None: return {'ok': False, 'error': 'no such brick'}
    for k in ('body', 'attrs', 'binds', 'props'):
        if k in op: setattr(b, k, op[k])
    return {'ok': True, 'touched': [b.id], 'brick': b.dict()}

def _remove(canvas, runtime, op):
    b = canvas.remove(op.get('id'))
    return {'ok': bool(b), 'removed': op.get('id')} if b else {'ok': False, 'error': 'no such brick'}

def _bind(canvas, runtime, op):
    b = canvas.by_id(op.get('id'))
    if b is None: return {'ok': False, 'error': 'no such brick'}
    port, expr = op.get('port'), (op.get('expr') or '').strip()
    if expr: b.binds[port] = expr
    else: b.binds.pop(port, None)
    return {'ok': True, 'touched': [b.id], 'brick': b.dict(), 'ports': runtime.bindings(b) if runtime else {}}

def _move(canvas, runtime, op):
    b = canvas.remove(op.get('id'))
    if b is None: return {'ok': False, 'error': 'no such brick'}
    canvas.insert(int(op.get('to', len(canvas))), b)
    return {'ok': True, 'touched': [b.id], 'order': [x.id for x in canvas]}

def _kind(canvas, runtime, op):
    b = canvas.by_id(op.get('id'))
    if b is None or op.get('kind') not in KINDS: return {'ok': False, 'error': 'no such brick or kind'}
    b.kind = op['kind']
    return {'ok': True, 'touched': [b.id], 'brick': b.dict()}

def _answer(canvas, runtime, op):
    "Prose the helper wrote, attached to the ask that wanted it. One reply per ask, replaced on rerun."
    of = op.get('of')
    b = canvas.reply_to(of)
    if b is None:
        b = Brick(kind='reply', body=op.get('markdown', ''), attrs={'of': of})
        canvas.insert(_at(canvas, {'after': of}), b)
    else: b.body = op.get('markdown', '')
    return {'ok': True, 'touched': [b.id], 'brick': b.dict(), 'at': canvas.index(b.id)}

def _find(body, was, nth=0):
    """Where the selection sits in the body. It came from rendered prose, so the emphasis markers
    are gone from it, and the same words may appear more than once: `nth` says which one."""
    hits = [(m.start(), len(m.group())) for m in re.finditer(re.escape(was), body)]
    if not hits:
        plain = re.sub(r'[*_`]', '', was)
        words = [re.escape(w) for w in plain.split()]
        if not words: return None
        pat = r'[*_`]*' + r'[\s*_`]+'.join(words) + r'[*_`]*'
        hits = [(m.start(), len(m.group())) for m in re.finditer(pat, body)]
    return hits[min(nth, len(hits) - 1)] if hits else None

def _replace_selection(canvas, runtime, op):
    "Rewrite the selected span, and only that span. A selection that cannot be found changes nothing."
    b = canvas.by_id(op.get('id'))
    if b is None: return {'ok': False, 'error': 'no such brick'}
    was, now = op.get('was') or op.get('selection') or '', op.get('text', '')
    if not was: return {'ok': False, 'error': 'nothing was selected'}
    at = _find(b.body, was, int(op.get('nth') or 0))
    if at is None: return {'ok': False, 'error': 'that selection is no longer in this brick'}
    i, n = at
    b.body = b.body[:i] + now + b.body[i + n:]
    return {'ok': True, 'touched': [b.id], 'brick': b.dict()}

def _run(canvas, runtime, op):
    b = canvas.by_id(op.get('id'))
    if b is None or not b.runs: return {'ok': False, 'error': 'not a code brick'}
    r = runtime.run(b)
    settle = runtime.react(canvas.bricks, r['defs'], skip=[b.id])
    return {'ok': r['ok'], 'touched': [b.id], 'run': r, **settle}

def _values(canvas, runtime, op):
    names = op.get('names') or [n for n in runtime.ns if not n.startswith('_')]
    return {'ok': True, 'values': {n: runtime.value(n) for n in names}}

def _read(canvas, runtime, op): return {'ok': True, 'canvas': canvas.dict()}
