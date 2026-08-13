"""Markdown as blocks, so a rendering can be read as a diff.

A rendered paragraph has no line numbers. Nothing in the HTML says which source lines
produced it, which is why a "rich diff" is usually either a second renderer that emits its
own markers, or a guess. Neither is wanted here: `/markdown/render` is the only renderer in
the product and its sanitisation posture is the one the browser must keep.

mdhtml already answers the missing question. `mdhtml.blocks` reports the *top-level source
span* of every construct in a document, using the same Figure and template promotion the
renderer applies, so the nth block it names is the nth element the renderer emits. That
gives two things this module hands to the browser:

- **where a block came from** -- `md_blocks`, a line range per block plus the tag it is
  expected to render as. The tag is what makes the correspondence checkable rather than
  assumed: the browser zips blocks against the top-level nodes it actually got, and if any
  expectation misses, or a node is left over, it draws no marks at all. A missing bar is a
  small loss; a bar beside the wrong paragraph is a lie about the diff.
- **which blocks changed** -- `md_block_diff`, two versions paired block against block.
  Line ranges are the wrong unit for a rendered diff: a one-word edit high in the file
  shifts every line below it, and the reader cannot see lines anyway. Blocks survive that,
  and a fenced code block that was edited keeps both texts so the browser can show the
  line-level change *inside* the rendering, where it is legible.

Rendering stays in the browser. This module returns records; nothing here emits HTML.
"""

from __future__ import annotations
from difflib import SequenceMatcher

__all__ = ['md_blocks', 'md_block_diff', 'md_change_kinds', 'MARKDOWN_SUFFIXES']

MARKDOWN_SUFFIXES = ('.md', '.markdown', '.mdown', '.mkd', '.mkdn')

# The element each block type renders as, for the browser's alignment check. An empty tuple
# means "not knowable": a raw HTML block can produce a comment, one element, three, or none,
# and a math or template block depends on the dialect's mode. Those blocks still occupy their
# place in the sequence, they simply cannot be verified, and a document whose HTML blocks do
# not line up one-for-one is exactly the document that ends up unmarked.
_MD_TAGS = {'paragraph': ('p',), 'code_block': ('pre',), 'list': ('ul', 'ol'), 'table': ('table',),
            'block_quote': ('blockquote',), 'thematic_break': ('hr',), 'figure': ('figure',),
            'html_block': (), 'math_block': (), 'template': ()}

# Definitions render nothing of their own: a link reference contributes a URL to a link
# somewhere else, and a footnote definition contributes to the generated footnotes section.
# They hold source lines, so a diff must still report them, but they consume no element.
_MD_SILENT = frozenset({'link_ref', 'footnote_def'})

# The renderer's own dialect options, so `blocks` promotes exactly what `to_mdhtml` promotes.
# If these drift apart the block sequence stops matching the element sequence -- an
# image-only paragraph is one `figure` block here and one `<figure>` there only because both
# calls say `implicit_figures=True`.
_MD_OPTS = dict(math='on', implicit_figures=True)


def _tags(b):
    "The tags a block may render as; `('h2',)` for a level-2 heading, `()` when unknowable."
    if b.get('type') == 'heading':
        level = int(b.get('level') or 1)
        return (f'h{min(max(level, 1), 6)}',)
    return _MD_TAGS.get(str(b.get('type') or ''), ())


def md_blocks(text):
    """Every top-level block of `text`: its source lines, its expected tag, its code.

    Lines are 1-based and inclusive, which is the convention `GitRepo.file_changes` and the
    editor's gutter already speak, so a hunk range can be intersected with a block range
    without either side converting. A document mdhtml cannot scan yields no blocks rather
    than an error: the rendering is still readable, it merely carries no marks.
    """
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
        # A fenced block's `text` is its contents without the fences, which is what a
        # line-level diff inside the rendering has to compare.
        if kind == 'code_block': row |= {'lang': str(b.get('lang') or ''), 'code': str(b.get('text') or '')}
        out.append(row)
    return out


def md_change_kinds(blocks, ranges):
    """Mark each block of `blocks` with the kind of the changed line ranges it contains.

    This is the line-range route, for the file being read next to its own working-tree
    changes: `/git/file` reports ranges in the *new* text, and a block owns a range when the
    two overlap. Git reports a pure deletion at the line that closed over it, so a removal
    lands on the block that now sits there -- the only place a reader could be shown it.
    Nothing is guessed: a block no range touches is left alone.
    """
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
    """Two Markdown documents paired block against block, in the new document's order.

    The result is `md_blocks(right)` with a status on every block, plus a `removed` record
    wherever the old document had a block the new one does not. A removed block has nothing
    to render -- its text is gone from the document being read -- so it is carried as a
    record the browser can attach to the block that now stands where it stood, with the old
    source available for a tooltip. That is the honest rendering of a deletion in a view
    whose whole subject is the new text.
    """
    old, new = md_blocks(left), md_blocks(right)
    sm = SequenceMatcher(None, [b['source'] for b in old], [b['source'] for b in new], autojunk=False)
    rows = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal': rows += [b | {'status': 'equal'} for b in new[j1:j2]]
        elif tag == 'insert': rows += [b | {'status': 'added'} for b in new[j1:j2]]
        elif tag == 'delete': rows += [_removed(b) for b in old[i1:i2]]
        else:
            # Inside a replaced run, blocks are paired by construct rather than by position. A
            # heading lined up with the paragraph that happened to sit at the same offset would
            # report "this heading was edited" about text that was never a heading; matching the
            # next old block of the same type instead leaves the paragraph as the removal it is,
            # and reports it just before the block it preceded, which is where a reader looking
            # for the missing text would look. Pairing stays in document order, so nothing is
            # matched across a block it already matched past.
            olds = list(old[i1:i2])
            for nb in new[j1:j2]:
                k = next((x for x, ob in enumerate(olds) if ob['type'] == nb['type']), None)
                if k is None: rows.append(nb | {'status': 'added'}); continue
                rows += [_removed(b) for b in olds[:k]]
                rows.append(_paired(nb, olds[k]))
                olds = olds[k + 1:]
            rows += [_removed(b) for b in olds]
    added, removed = _line_stat(left, right)
    return {'blocks': rows, 'added': added, 'removed': removed,
            'changed': any(r['status'] != 'equal' for r in rows)}
