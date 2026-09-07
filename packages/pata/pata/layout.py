"Giving a document a second view: where a brick sits when nobody has placed it."

from __future__ import annotations
import math
from fastcore.all import L

from .context import body_text
from .doc import W

__all__ = ['arrange', 'measure', 'GAP', 'PAD']

GAP, PAD = 26, 30
#: Header, padding, and the line box the prototype's 13px type occupies.
HEAD, LINE, CHROME = 27, 21, 22

def measure(b, w=W, values=None):
    "About how tall a brick draws. Close enough to lay out; the page corrects it on render."
    per = max(20, int((w - CHROME) / 7.1))
    text = body_text(b, values) or ' '
    rows = sum(max(1, math.ceil(len(l) / per)) for l in text.splitlines() or [' '])
    return HEAD + CHROME + min(rows, 26) * LINE

def _columns(items, tall):
    "Balanced columns, document order down each. Greedy filling leaves the last column near empty."
    total = sum(bh + GAP for _, bh in items)
    n = max(1, math.ceil(total / tall))
    per, cols, cur, h = total / n, [], [], 0
    for b, bh in items:
        if cur and h + (bh + GAP) / 2 > per and len(cols) < n - 1: cols, cur, h = cols + [cur], [], 0
        cur.append((b, bh))
        h += bh + GAP
    return cols + ([cur] if cur else [])

def arrange(doc, w=W, cols=6, tall=560, force=False, values=None, keep=False):
    """Place every brick that has no `prop x`, region by region, and fit the regions round them.

    `force` re-places bricks a person had moved, which is what "tidy the canvas" means. `keep`
    writes the result into the file; without it the layout stays a property of the view.
    """
    groups, order = {}, []
    for b in doc.bricks:
        if b.region not in order: order.append(b.region)
        if b.heading or b.kind == 'reply': continue     # the region label says one; the ask shows the other
        groups.setdefault(b.region, []).append(b)
    x, y, row_h, rects = PAD, PAD, 0, {}
    for name in order:
        if not groups.get(name): continue
        packed = _columns([(b, measure(b, w, values)) for b in groups[name]], tall)
        rw = len(packed) * w + (len(packed) - 1) * GAP + 2 * PAD
        if x > PAD and x + rw > cols * (w + GAP) + 2 * PAD: x, y, row_h = PAD, y + row_h + GAP * 2, 0
        cx, rh = x + PAD, 0
        for col in packed:
            cy = y + PAD + HEAD
            for b, bh in col:
                if force or b.props.get('x') is None: b.place(cx, cy, w, keep)
                cy += bh + GAP
            rh = max(rh, cy - y)
            cx += w + GAP
        rects[name] = {'title': name, 'x': x, 'y': y, 'w': rw, 'h': rh + PAD}
        row_h = max(row_h, rh + PAD)
        x += rw + GAP
    doc.layout = rects
    return doc
