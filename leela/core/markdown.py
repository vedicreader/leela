"""Markdown as blocks, so a rendering can be read as a diff.

`mdhtml.blocks` reports the top-level source span of every construct, using the same
promotions the renderer applies, so the nth block is the nth element emitted. This module
returns records only; rendering stays in the browser.
"""

from __future__ import annotations
from difflib import SequenceMatcher
from fastcore.basics import first

__all__ = ['md_blocks', 'md_block_diff', 'md_change_kinds', 'MARKDOWN_SUFFIXES']

MARKDOWN_SUFFIXES = ('.md', '.markdown', '.mdown', '.mkd', '.mkdn')

# The element each block type renders as, for the browser's alignment check. An empty tuple
# means "not knowable" -- raw HTML, math and template blocks hold a place in the sequence but
# cannot be verified.
_MD_TAGS = {'paragraph': ('p',), 'code_block': ('pre',), 'list': ('ul', 'ol'), 'table': ('table',),
            'block_quote': ('blockquote',), 'thematic_break': ('hr',), 'figure': ('figure',),
            'html_block': (), 'math_block': (), 'template': ()}

# Definitions hold source lines but render no element of their own.
_MD_SILENT = frozenset({'link_ref', 'footnote_def'})

# Must stay identical to `to_mdhtml`'s options: if they drift the block sequence stops
# matching the element sequence.
_MD_OPTS = dict(math='on', implicit_figures=True)


def _tags(b):
    "The tags a block may render as; `('h2',)` for a level-2 heading, `()` when unknowable."
    if b.get('type') == 'heading':
        level = int(b.get('level') or 1)
        return (f'h{min(max(level, 1), 6)}',)
    return _MD_TAGS.get(str(b.get('type') or ''), ())


def md_blocks(text):
    "Every top-level block of `text`: 1-based inclusive source lines, expected tag, and code."
    text = str(text or '')
    try:
        from mdhtml import blocks
        found = blocks(text, **_MD_OPTS)
    except Exception: return []
    lines = text.split('\n')
    out = []
    for b in found:
        kind = str(b.get('type') or '')
        start, end = int(b.get('start') or 0), int(b.get('end') or 0)
        row = {'type': kind, 'from': start + 1, 'to': max(start + 1, end),
               'source': '\n'.join(lines[start:end]), 'tags': list(_tags(b)),
               'renders': kind not in _MD_SILENT}
        if kind == 'code_block': row |= {'lang': str(b.get('lang') or ''), 'code': str(b.get('text') or '')}
        out.append(row)
    return out


def md_change_kinds(blocks, ranges):
    "Mark each block of `blocks` with the kind of the changed line ranges it contains."
    # Git reports a pure deletion at the line that closed over it, so a removal lands on the
    # block that now sits there. A block no range touches is left alone.
    out = []
    for b in blocks:
        kinds = {str(r.get('kind') or 'modified') for r in ranges or ()
                 if int(r.get('from') or 0) <= b['to'] and int(r.get('to') or 0) >= b['from']}
        if not kinds: out.append(None)
        elif kinds == {'added'}: out.append('added')
        elif kinds == {'deleted'}: out.append('removed')
        else: out.append('modified')
    return out


def _line_stat(left, right):
    "Added and removed line counts between two texts, the way `git diff --stat` counts them."
    a, b = str(left or '').split('\n'), str(right or '').split('\n')
    added = removed = 0
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == 'equal': continue
        added += j2 - j1; removed += i2 - i1
    return added, removed


def _removed(b): return b | {'status': 'removed', 'old_from': b['from'], 'old_to': b['to']}


def _paired(new, old):
    "One block reported as the edited form of the block it replaced."
    row = new | {'status': 'modified', 'old': old['source'], 'old_from': old['from'], 'old_to': old['to']}
    if new['type'] == 'code_block': row |= {'old_code': old.get('code', '')}
    return row


def md_block_diff(left, right):
    "Two Markdown documents paired block against block, in the new document's order."
    old, new = md_blocks(left), md_blocks(right)
    sm = SequenceMatcher(None, [b['source'] for b in old], [b['source'] for b in new], autojunk=False)
    rows = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal': rows += [b | {'status': 'equal'} for b in new[j1:j2]]
        elif tag == 'insert': rows += [b | {'status': 'added'} for b in new[j1:j2]]
        elif tag == 'delete': rows += [_removed(b) for b in old[i1:i2]]
        else:
            # Inside a replaced run, pair by construct rather than by position: a heading
            # lined up with a same-offset paragraph would report an edit to text that was
            # never a heading. Pairing stays in document order.
            olds = list(old[i1:i2])
            for nb in new[j1:j2]:
                k = first(x for x, ob in enumerate(olds) if ob['type'] == nb['type'])
                if k is None: rows.append(nb | {'status': 'added'}); continue
                rows += [_removed(b) for b in olds[:k]]
                rows.append(_paired(nb, olds[k]))
                olds = olds[k + 1:]
            rows += [_removed(b) for b in olds]
    added, removed = _line_stat(left, right)
    return {'blocks': rows, 'added': added, 'removed': removed,
            'changed': any(r['status'] != 'equal' for r in rows)}
