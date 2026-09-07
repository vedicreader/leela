"What one question is allowed to see, resolved explicitly enough to draw."

from __future__ import annotations
import re
from dataclasses import dataclass, field, replace
from fastcore.all import L, first

from .doc import Canvas, Brick, MODES, upstream

__all__ = ['SCOPES', 'REF_KINDS', 'Spec', 'Item', 'spec_of', 'resolve', 'render', 'weigh',
           'strip_work_log', 'members', 'body_text']

#: How a question gathers context before its pins are added.
SCOPES = ('none', 'page', 'region', 'upstream', 'doc')
#: A pin that is not a brick id names something outside the document, `kind:ref`.
REF_KINDS = ('file', 'vault', 'url', 'var', 'sel')

#: The fold a Ramabana turn appends to a reply. `calls` already holds it.
WORK_LOG = re.compile(r'\n*<details>\s*<summary>\s*what i did[^<]*</summary>[\s\S]*</details>\s*\Z', re.I)

def strip_work_log(text): return WORK_LOG.sub('', str(text or '')).rstrip()

@dataclass
class Spec:
    "A question's context rule, written on the brick as attributes and `pin`/`mute` directives."
    scope: str = 'page'
    pins: list = field(default_factory=list)
    mutes: list = field(default_factory=list)
    budget: int | None = None
    goal: bool = True
    def __post_init__(self):
        if self.scope not in SCOPES: self.scope = 'page'

@dataclass
class Item:
    "One thing in the basket, with the rule that put it there."
    ref: str
    kind: str
    label: str
    text: str
    why: str
    region: str = ''
    mode: str = 'auto'
    pinned: bool = False
    clipped: bool = False
    @property
    def chars(self): return len(self.text)
    def dict(self): return {**self.__dict__, 'chars': self.chars}

def spec_of(b):
    "The `Spec` a brick carries. An `ask` that says nothing reads the document above it."
    if b is None: return Spec()
    return Spec(scope=b.scope or 'page', pins=list(b.pins), mutes=list(b.mutes), budget=b.budget,
                goal=b.attrs.get('goal') != 'off')

def body_text(b, values=None, doc=None):
    "One brick as the model reads it."
    out = []
    if b.kind == 'goal':
        bits = [f'{k}: {v}' for k, v in b.attrs.items()
                if k in ('measure', 'baseline', 'target', 'by')]
        out = [b.body] + ([' | '.join(bits)] if bits else [])
    elif b.kind == 'task':
        out = [f"[{b.attrs.get('status', 'todo')}] {b.body}"]
        if b.attrs.get('owner'): out.append(f"owner: {b.attrs['owner']}")
    elif b.kind == 'source':
        where = b.attrs.get('url') or b.attrs.get('path') or ''
        out = [f'{b.title} <{where}>'.strip(), b.body]
    elif b.kind == 'bundle':
        out = [f'change: {b.title}'.strip(), b.body]
        out += [f'{k}: {v}' for k, v in b.attrs.items()
                if k in ('goal', 'contributes', 'paths', 'refs', 'covers')]
    elif b.kind == 'snippet':
        out = [f"{b.attrs.get('path', '')} {b.attrs.get('symbol') or b.attrs.get('lines') or ''}".strip(),
               b.body]
    elif b.kind == 'diff':
        out = [f"{b.attrs.get('path', '')} +{b.attrs.get('added', 0)} -{b.attrs.get('removed', 0)}",
               b.body]
    elif b.kind in ('brick', 'sim', 'data'):
        out = [b.title or b.attrs.get('src', b.kind)]
        out += [f'bind {k} = {v}' for k, v in b.binds.items()]
    elif b.heading: return ''
    else: out = [b.body]
    if b.runs and (t := str((values or {}).get(b.id) or '').strip()):
        out.append(f'<output>\n{t}\n</output>')
    if b.kind == 'reply' and (r := strip_work_log(b.body).strip()): out = [f'<answer>\n{r}\n</answer>']
    return '\n'.join(x for x in out if str(x).strip())

def _label(b):
    if b.kind == 'diff': return b.attrs.get('path', 'diff')[:60]
    lines = [l for l in (b.title or b.body or b.attrs.get('src', '')).strip().splitlines()
             if not l.lstrip().startswith('#|')]
    return (lines[0].lstrip('# ') if lines else b.kind)[:60]

def members(doc, b, scope):
    "The bricks a scope offers, before pins, mutes and the budget."
    if scope == 'none': return L()
    at = doc.index(b.id)
    if at is None: at = len(doc)
    if scope == 'page': return L(doc.bricks[:at])
    if scope == 'doc': return L(x for x in doc.bricks if x.id != b.id)
    if scope == 'region': return L(x for x in doc.in_region(b.region) if x.id != b.id)
    return upstream(doc.bricks, b.id)

def _is_ref(r): return isinstance(r, str) and r.split(':', 1)[0] in REF_KINDS

def _ref_item(ref, lookup):
    got = lookup(ref) if lookup else None
    if got is None:
        return Item(ref=ref, kind=ref.split(':', 1)[0], label=ref, text='', why='pin', pinned=True,
                    clipped=True)
    if isinstance(got, Item): return got
    return Item(ref=ref, kind=ref.split(':', 1)[0], label=ref, text=str(got), why='pin', pinned=True)

def resolve(
    doc,             # the document
    bid,             # which brick asks
    spec=None,       # the rule, else the one the brick carries
    values=None,     # `{brick id: output text}` from the live namespace
    lookup=None,     # `lookup(ref)` for a pin the document does not own
    extra=(),        # items the host adds, such as live variables
):
    "The exact basket for question `bid`, in the order the model reads it."
    b = doc.by_id(bid)
    if b is None: raise KeyError(bid)
    spec = spec or spec_of(b)
    mutes, items, seen = set(spec.mutes), [], {b.id}
    def take(x, why, pinned=False):
        if x.id in seen or x.id in mutes: return
        if not (t := body_text(x, values, doc)).strip(): return
        seen.add(x.id)
        items.append(Item(ref=x.id, kind=x.kind, label=_label(x), text=t, why=why,
                          region=x.region, mode=x.mode, pinned=pinned or x.mode == 'keep'))
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

#: What one item costs beyond its own text: the `<cell>` wrapper `render` puts round it.
WRAP = 60

def _fit(items, budget):
    "Trim to `budget`. Pins and `keep` never drop; `discard` goes first, then the oldest `auto`."
    if not budget: return items
    total = sum(i.chars + WRAP for i in items)
    if total <= budget: return items
    order = sorted((i for i, it in enumerate(items) if not it.pinned),
                   key=lambda i: (items[i].mode != 'discard', i))
    drop, n = set(), 0
    while total > budget and n < len(order):
        total -= items[order[n]].chars + WRAP
        drop.add(order[n])
        n += 1
    kept = [it for i, it in enumerate(items) if i not in drop]
    if sum(i.chars + WRAP for i in kept) > budget and kept:
        share = max(200, budget // max(1, len(kept)) - WRAP)
        kept = [replace(it, text=it.text[:share] + '\n…', clipped=True) if it.chars > share else it
                for it in kept]
    return kept

def render(items, doc=None):
    "The basket as `<cell>` markup, which is Leela’s own notebook context shape."
    out = []
    for it in items:
        if not it.text.strip(): continue
        attr = (f'id="{it.ref}" type="{it.kind}" compact="{"keep" if it.pinned else "auto"}" '
                f'why="{it.why}"')
        if it.region: attr += f' region="{it.region}"'
        if it.clipped: attr += ' clipped="true"'
        out.append(f'<cell {attr}>\n{it.text}\n</cell>')
    if doc is not None and (links := _links(doc, {i.ref for i in items if i.text.strip()})):
        out.append('<links>\n' + '\n'.join(links) + '\n</links>')
    return '\n'.join(out)

def _links(doc, ids):
    "Relations the AST cannot see, for the pairs that both made it into the basket."
    return [f'{b.id} {rel} {other}' for b in doc.bricks if b.id in ids
            for rel, targets in b.links.items() for other in targets if other in ids]

def weigh(items):
    "What the panel prints above the basket: how many bricks, how many characters, what was cut."
    return {'blocks': len(items), 'chars': sum(i.chars + WRAP for i in items),
            'pinned': sum(1 for i in items if i.pinned),
            'missing': [i.ref for i in items if i.kind == 'missing'],
            'clipped': [i.ref for i in items if i.clipped and i.kind != 'missing']}
