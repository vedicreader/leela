"""Text comparison for the IDE: difflib, reached through fastcore where fastcore has it.

Three questions the IDE keeps asking turn out to be the same question, so they
live together:

- **what changed** -- `udiff` and `diff_rows`, over `fastcore.xtras.str_diff`.
  The IDE shows a diff in three places (unsaved edits, what the assistant did to
  a file, what lazygit moved underneath an open tab) and all three should look
  alike, which means one parser and one row shape rather than three renderers
  each doing their own `startswith('+')`.
- **did you mean** -- `did_you_mean`, for a `NameError` raised in a namespace the
  inspector can already see. The traceback knows the name that failed and the
  variable panel knows every name that exists; they only needed introducing.
- **is this the file I meant** -- `fuzzy_rank`, so quick-open ranks by how well a
  name matches instead of listing every substring hit in directory order.

Rendering deliberately stays in the frontends. This module hands back rows;
The browser paints them with CSS classes, and
neither has to know how a unified diff is spelled.
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from difflib import SequenceMatcher, get_close_matches
from fastcore.all import L
from fastcore.xtras import str_diff

from . import Dictable

__all__ = ['DiffRow', 'udiff', 'diff_rows', 'diff_stat', 'diff_label', 'closest', 'did_you_mean',
           'fuzzy_rank']


@dataclass
class DiffRow(Dictable):
    'One painted line of a unified diff.'
    kind: str          # 'head' | 'hunk' | 'add' | 'del' | 'ctx'
    text: str          # the line itself, with its +/-/space marker already stripped
    line: int = 0      # 1-based line in the *new* text; 0 where there is none (a deletion, a header)


def udiff(a, b, names=None, n=3):
    "Unified diff of `a` and `b`, `''` when they match. `names` is an optional `(old, new)` pair of labels."
    return str_diff(a or '', b or '', n=n, names=names)


_HUNK = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@')


def diff_rows(d):
    """A unified diff as rows a frontend can paint, each carrying its line number in the new text.

    That line number is what makes a diff clickable -- jump from a changed line to the
    place it lives. `str_diff` returns text, and the only place the new-side numbering
    appears is the hunk header, so it is tracked here once instead of being re-derived
    by every renderer.
    """
    out, n = L(), 0
    for line in (d or '').split('\n'):
        if not line and not out: continue                    # str_diff of equal texts is ''
        if line.startswith('@@'):
            m = _HUNK.match(line)
            n = int(m.group(1)) if m else 0
            out.append(DiffRow('hunk', line))
        elif line.startswith(('---', '+++')): out.append(DiffRow('head', line))
        elif line.startswith('+'): out.append(DiffRow('add', line[1:], n)); n += 1
        elif line.startswith('-'): out.append(DiffRow('del', line[1:]))
        else:
            out.append(DiffRow('ctx', line[1:] if line.startswith(' ') else line, n)); n += 1
    return out


def diff_stat(a, b):
    "`(added, removed)` line counts between `a` and `b`. `n=0` because context lines are not news."
    rs = diff_rows(udiff(a, b, n=0))
    return sum(r.kind == 'add' for r in rs), sum(r.kind == 'del' for r in rs)


def diff_label(a, b):
    "A short `+3 −1` summary of `a` -> `b`, or `''` when they are identical."
    add, rem = diff_stat(a, b)
    return ' '.join(p for p in (f'+{add}' if add else '', f'−{rem}' if rem else '') if p)


def closest(word, cands, n=3, cutoff=0.6):
    "The `n` candidates most like `word`, best first."
    return L(get_close_matches(str(word or ''), [str(c) for c in (cands or ())], n=n, cutoff=cutoff))


_NAMEERR = re.compile(r"name '([^']+)' is not defined")


def did_you_mean(err, names):
    """`err` with a suggestion appended, when it is a `NameError` and `names` holds something close.

    CPython prints its own suggestion, but only as part of a rendered traceback. The exec
    strip shows a single line -- `NameError: name 'df2' is not defined` -- which is exactly
    where the hint is missing and exactly where the IDE has the namespace to hand.
    Anything that is not a `NameError` comes back untouched.
    """
    if not err or not (m := _NAMEERR.search(err)): return err
    hits = closest(m.group(1), names)
    return err if not hits else f"{err}  ·  did you mean {' or '.join(repr(h) for h in hits)}?"


def _subseq(q, s):
    "Is `q` a subsequence of `s`? The fuzzy-finder membership test: same characters, same order."
    it = iter(s)
    return all(c in it for c in q)


def fuzzy_rank(q, items, key=str, limit=None):
    """`items` ranked by how well `q` matches, best first; anything that does not match at all is dropped.

    Quick-open should behave like a fuzzy finder -- `wapp` ought to find `web/app.py` --
    so membership is subsequence containment rather than substring. Ranking is then
    difflib's ratio against the *basename*, because a query almost always names the file
    and not the folders above it: that is what puts `app.py` above
    `some_long_app_helper.py` for `app`.
    """
    q = (q or '').strip().lower()
    items = L(items)
    if not q: return items if limit is None else items[:limit]
    scored = L()
    for it in items:
        s = str(key(it))
        low = s.lower()
        base = low.rsplit('/', 1)[-1]
        if not _subseq(q, low): continue
        score = max(SequenceMatcher(None, q, base).ratio(), SequenceMatcher(None, q, low).ratio() * .5)
        if q in base: score += 1.           # a contiguous hit in the name beats a scattered one
        if base.startswith(q): score += .5  # and a prefix beats a hit in the middle
        scored.append((score, len(s), it))
    ranked = scored.sorted(key=lambda t: (-t[0], t[1])).itemgot(2)
    return ranked if limit is None else ranked[:limit]
