"What one prompt block is allowed to see, resolved explicitly enough to draw."

from __future__ import annotations
import re
from dataclasses import dataclass, field, replace
from fastcore.all import L, first

from .doc import Doc, Block, MODES, short

__all__ = ['SCOPES', 'REF_KINDS', 'Spec', 'Item', 'spec_of', 'resolve', 'render', 'weigh',
           'strip_work_log', 'members', 'body_text']

#: The fold a Ramabana turn appends to a reply. `calls` already holds it, and feeding it forward
#: puts whole tool transcripts in the next prompt's context.
WORK_LOG = re.compile(r'\n*<details>\s*<summary>\s*what i did[^<]*</summary>[\s\S]*</details>\s*\Z', re.I)

def strip_work_log(text): return WORK_LOG.sub('', str(text or '')).rstrip()

#: How a prompt block gathers context before its pins are added.
SCOPES = ('none', 'page', 'frame', 'upstream', 'doc')
#: A pin that is not a block id names something outside the document, `kind:ref`.
REF_KINDS = ('file', 'vault', 'url', 'var', 'sel')

@dataclass
class Spec:
    "A prompt block's context rule. Persisted in its props under `context`."
    scope: str = 'page'
    pins: list = field(default_factory=list)
    mutes: list = field(default_factory=list)
    budget: int | None = None
    goal: bool = True
    def __post_init__(self):
        if self.scope not in SCOPES: self.scope = 'page'
    def dict(self):
        d = {'scope': self.scope}
        if self.pins: d['pins'] = list(self.pins)
        if self.mutes: d['mutes'] = list(self.mutes)
        if self.budget: d['budget'] = self.budget
        if not self.goal: d['goal'] = False
        return d
    @classmethod
    def from_dict(cls, d):
        d = dict(d or {})
        return cls(scope=str(d.get('scope') or 'page'), pins=list(d.get('pins') or []),
                   mutes=list(d.get('mutes') or []), budget=d.get('budget'),
                   goal=bool(d.get('goal', True)))

@dataclass
class Item:
    "One thing in the basket, with the rule that put it there."
    ref: str
    kind: str
    label: str
    text: str
    why: str
    pinned: bool = False
    clipped: bool = False
    @property
    def chars(self): return len(self.text)
    def dict(self): return {**self.__dict__, 'chars': self.chars}

def spec_of(b):
    "The `Spec` a block carries, defaulting for a block that has never been configured."
    return Spec.from_dict(b.props.get('context')) if b is not None else Spec()

def body_text(b, doc=None):
    "One block as the model reads it: source, then whatever that flavour produced."
    out = []
    if b.kind == 'goal':
        bits = [f"{k}: {b.get(k)}" for k in ('measure', 'baseline', 'target', 'by') if b.get(k)]
        out = [b.source] + ([' | '.join(bits)] if bits else [])
    elif b.kind == 'task':
        out = [f"[{b.get('status', 'todo')}] {b.source}"]
        if b.get('owner'): out.append(f"owner: {b.get('owner')}")
    elif b.kind == 'source':
        out = [f"{b.title} <{b.get('url') or b.get('path') or ''}>", str(b.get('text') or '')]
    elif b.kind == 'data':
        out = [b.source or str(b.get('name') or b.get('path') or ''), str(b.get('preview') or '')]
    elif b.kind == 'frame':
        out = [b.title]
    else: out = [b.source]
    if b.kind == 'code' and (t := _out_text(b)): out.append(f'<output{_attrs(b, doc)}>\n{t}\n</output>')
    if b.kind == 'prompt' and (r := strip_work_log(b.get('reply')).strip()):
        out.append(f'<answer>\n{r}\n</answer>')
    return '\n'.join(x for x in out if str(x).strip())

def _out_text(b):
    rows = []
    for o in b.outputs:
        d = o.get('data') or {}
        rows.append(o.get('text') or d.get('text/plain') or o.get('evalue') or '')
    return '\n'.join(str(r) for r in rows if r).strip()

def _attrs(b, doc=None):
    bits = [f'{k}="{b.get(k)}"' for k in ('execution_count', 'execution_ms') if b.get(k) is not None]
    if doc.stale(b.id) if doc is not None else b.stale: bits.append('stale="true"')
    return (' ' + ' '.join(bits)) if bits else ''

def _label(b):
    head = (b.title or b.source or '').strip().splitlines()
    return (head[0] if head else b.kind)[:60]

def members(doc, b, scope):
    "The blocks a scope offers, before pins, mutes and the budget."
    if scope == 'none': return L()
    at = doc.index(b.id)
    if scope == 'page': return L(doc.blocks[:at if at >= 0 else len(doc)])
    if scope == 'doc': return L(x for x in doc.blocks if x.id != b.id)
    if scope == 'frame':
        if not b.frame: return L(doc.blocks[:at if at >= 0 else len(doc)])
        return L(x for x in doc.blocks if x.id == b.frame or (x.frame == b.frame and x.id != b.id))
    ids = set(doc.reachable(b.id, back=True))
    return L(x for x in doc.blocks if x.id in ids)

def _ref_item(ref, lookup):
    "A pin naming something outside the document, resolved by the host that owns it."
    got = lookup(ref) if lookup else None
    if got is None: return Item(ref=ref, kind=ref.split(':', 1)[0], label=ref, text='', why='pin',
                                pinned=True, clipped=True)
    return got if isinstance(got, Item) else Item(ref=ref, kind=ref.split(':', 1)[0], label=ref,
                                                  text=str(got), why='pin', pinned=True)

def _is_ref(r): return isinstance(r, str) and r.split(':', 1)[0] in REF_KINDS

def resolve(doc, bid, spec=None, lookup=None, extra=()):
    """The exact basket for prompt block `bid`, in the order the model will read it.

    Pure and inspectable: the same list draws the panel and builds the prompt, so what a person
    toggles is what the model gets. `lookup` resolves a `kind:ref` pin the document does not own.
    """
    b = doc.by_id(bid)
    if b is None: raise KeyError(bid)
    spec = spec or spec_of(b)
    mutes = set(spec.mutes)
    items, seen = [], {b.id}
    def take(x, why, pinned=False):
        if x.id in seen or x.id in mutes or x.kind == 'edge': return
        if not (t := body_text(x, doc)).strip(): return
        seen.add(x.id)
        items.append(Item(ref=x.id, kind=x.kind, label=_label(x), text=t, why=why,
                          pinned=pinned or x.mode == 'keep'))
    if spec.goal and (g := doc.goal_for(bid)) is not None and g.id not in mutes: take(g, 'goal', True)
    for r in spec.pins:
        if r in mutes: continue
        if _is_ref(r): items.append(_ref_item(r, lookup))
        elif (x := doc.by_id(r)) is not None: take(x, 'pin', True)
        else: items.append(Item(ref=r, kind='missing', label=r, text='', why='pin', pinned=True,
                                clipped=True))
    for x in members(doc, b, spec.scope): take(x, spec.scope)
    items += list(extra)
    return _fit(items, spec.budget)

#: What one item costs beyond its own text: the `<block>` wrapper `render` puts round it.
WRAP = 60

def _fit(items, budget):
    "Trim to `budget`. Pins and `keep` never drop; `discard` goes first, then the oldest `auto`."
    if not budget: return items
    total = sum(i.chars + WRAP for i in items)
    if total <= budget: return items
    order = [i for i, it in enumerate(items) if not it.pinned]
    order.sort(key=lambda i: (items[i].why != 'discard', i), reverse=False)
    drop, i = set(), 0
    while total > budget and i < len(order):
        total -= items[order[i]].chars + WRAP
        drop.add(order[i])
        i += 1
    kept = [it for n, it in enumerate(items) if n not in drop]
    over = sum(i.chars + WRAP for i in kept) - budget
    if over > 0 and kept:                   # every survivor is pinned, so clip rather than drop
        share = max(200, budget // max(1, len(kept)) - WRAP)
        kept = [replace(it, text=it.text[:share] + '\n…', clipped=True) if it.chars > share else it
                for it in kept]
    return kept

def render(items, doc=None):
    """The basket as the markup the model reads.

    `<cell>` with a `compact` attribute, which is Leela's own notebook context shape. Ramabana's
    `compact_notebook_context` sheds elements matching exactly that when a prompt overflows the
    window, so a document that renders anything else loses the safety net under the budget.
    """
    out = []
    for it in items:
        if not it.text.strip(): continue
        compact = 'keep' if it.pinned else 'auto'
        attr = f'id="{it.ref}" type="{it.kind}" compact="{compact}" why="{it.why}"'
        if it.clipped: attr += ' clipped="true"'
        out.append(f'<cell {attr}>\n{it.text}\n</cell>')
    if doc is not None and (links := _links(doc, {i.ref for i in items if i.text.strip()})):
        out.append('<links>\n' + '\n'.join(links) + '\n</links>')
    return '\n'.join(out)

def _links(doc, ids):
    return [f"{e.get('src')} {e.get('rel', 'feeds')} {e.get('dst')}" for e in doc.edges
            if e.get('src') in ids and e.get('dst') in ids]

def weigh(items):
    "What the panel prints above the basket: how many blocks, how many characters, what was cut."
    return {'blocks': len(items), 'chars': sum(i.chars + WRAP for i in items),
            'pinned': sum(1 for i in items if i.pinned),
            'missing': [i.ref for i in items if i.kind == 'missing'],
            'clipped': [i.ref for i in items if i.clipped and i.kind != 'missing']}
