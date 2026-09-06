"Giving a document a canvas: where a block sits when nobody has placed it."

from __future__ import annotations
import math
from fastcore.all import L

from .context import body_text
from .doc import Doc

__all__ = ['arrange', 'measure', 'W', 'GAP', 'PAD']

W, GAP, PAD = 380, 26, 30
#: Header, padding, and the line box the prototype's 13px type actually occupies.
HEAD, LINE, CHROME = 27, 21, 22

def measure(b, w=W):
    "About how tall a block draws. Close enough to lay out; the page corrects it on render."
    per = max(20, int((w - CHROME) / 7.1))
    rows = sum(max(1, math.ceil(len(l) / per)) for l in (body_text(b) or ' ').splitlines() or [' '])
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

def arrange(doc, w=W, cols=6, tall=560, force=False):
    """Place every block that has no geometry, frame by frame, and fit the frames round them.

    `force` re-places blocks that were already positioned, which is what a person means by
    "tidy the canvas". Without it, anything already moved by hand stays where it was put.
    """
    groups, order = {}, []
    for b in doc.blocks:
        if b.kind in ('edge', 'frame'): continue
        groups.setdefault(b.frame, []).append(b)
        if b.frame not in order: order.append(b.frame)
    x, y, row_h = PAD, PAD, 0
    for fid in order:
        members = [(b, measure(b, w)) for b in groups[fid]]
        packed = _columns(members, tall)
        fw = len(packed) * w + (len(packed) - 1) * GAP + 2 * PAD
        if x > PAD and x + fw > cols * (w + GAP) + 2 * PAD:
            x, y, row_h = PAD, y + row_h + GAP * 2, 0
        cx, fh = x + PAD, 0
        for col in packed:
            cy = y + PAD + HEAD
            for b, bh in col:
                if force or not b.placed: b.place(cx, cy, w, bh)
                cy += (b.h or bh) + GAP
            fh = max(fh, cy - y)
            cx += w + GAP
        if (f := doc.by_id(fid)) is not None and f.kind == 'frame':
            if force or not f.placed: f.place(x, y, fw, fh + PAD)
        row_h = max(row_h, fh + PAD)
        x += fw + GAP
    return doc
