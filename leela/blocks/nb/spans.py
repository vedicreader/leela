"""Where each cell's source lives in the `.ipynb` file, and the way back out again.

A notebook on disk is JSON, so everything that works in file lines -- `git blame`, ripgrep,
a symbol scan -- reports a line of that JSON: `    "def f(x):\\n",`. The number is true and
useless, because nobody reads the file, and there is no single editor to scroll: a notebook
is a column of per-cell editors, each with its own line 1. Translating between the two
coordinate systems is what these functions are for.

They live here, in the notebook block, because there is only one correct mapping and two
implementations of it would eventually disagree about a notebook someone actually has. Git's
notebook blame was the first caller and search is the second; neither owns the format. The
scan is deliberately over the raw text rather than a parse: the whole question is *which line
of this file*, which a parsed notebook has already thrown away.

Nothing here guesses. A notebook that cannot be read, or a cell whose lines cannot be found
in the file, is reported as unknown -- a plausible-looking wrong line is worse than no line,
because the caller has no way to tell it is wrong.
"""

from __future__ import annotations

import json

__all__ = ['read_cells', 'source_spans', 'cell_lines', 'cell_at', 'cell_of']


def read_cells(text):
    "The cells of a notebook's JSON text, or `None` when this is not a notebook we can read."
    try: nb = json.loads(text or '')
    except (TypeError, json.JSONDecodeError): return None
    if not isinstance(nb, dict): return None
    cells = nb.get('cells')
    return cells if isinstance(cells, list) else None


def source_spans(text, cells):
    """The 1-based line numbers in the file that hold each cell's source strings.

    nbformat writes one JSON string per source line, in cell order, which is what makes this
    a scan rather than a parse: find each `"source"` key in turn and take the next `n` lines,
    where `n` is how many strings that cell's source has. A cell whose value is inline (one
    short line, or the plain-string form) is the head line itself.

    `None` for a cell whose lines could not be located -- a hand-minified notebook, say. The
    caller reports that rather than guessing, because a wrong line here attributes someone
    else's code to you.
    """
    lines, spans, idx = (text or '').splitlines(), [], 0
    for cell in cells:
        source = cell.get('source')
        count = len(source) if isinstance(source, list) else max(1, len(str(source or '').splitlines()))
        while idx < len(lines) and '"source"' not in lines[idx]: idx += 1
        if idx >= len(lines):
            spans.append(None)
            continue
        head, idx = lines[idx], idx + 1            # idx is now the head line's 1-based number
        after = head.split('"source"', 1)[1]
        if ']' in after or '[' not in after: spans.append((idx, idx))
        else:
            spans.append((idx + 1, idx + count))
            idx += count
    return spans


def cell_lines(cell):
    "One cell's source as a list of lines, whichever of nbformat's two shapes it is in."
    source = cell.get('source') or ''
    return list(source) if isinstance(source, list) else str(source).splitlines(True)


def _at(cells, spans, i, line_in_cell):
    """The address of a line inside cell `i`: id, index, in-cell line, and the file line.

    `id` is `''` for a notebook written before nbformat 4.5, which gave cells no identity of
    their own; the index is what stays addressable there, so both are always reported.
    """
    span = spans[i]
    return {'index': i, 'id': str(cells[i].get('id') or ''), 'line': line_in_cell,
            'file_line': (span[0] + line_in_cell - 1) if span else 0,
            'kind': str(cells[i].get('cell_type') or 'code')}


def cell_at(text, line, cells=None):
    "The cell containing file line `line`, or `None` when no cell's source does."
    cells = read_cells(text) if cells is None else cells
    if not cells: return None
    try: line = int(line)
    except (TypeError, ValueError): return None
    spans = source_spans(text, cells)
    for i, span in enumerate(spans):
        if span and span[0] <= line <= span[1]: return _at(cells, spans, i, line - span[0] + 1)
    return None


def cell_of(text, snippet, cells=None):
    """The cell holding `snippet`, when exactly one does.

    For a hit whose only trustworthy coordinate is its text -- an index that chunks a notebook
    by cell knows which *cell* it matched and reports line 1 of the file for all of them. One
    matching cell is an answer; none or several is not, and returns `None` rather than the
    first of them.
    """
    needle = str(snippet or '').strip().split('\n')[0].strip()
    if not needle: return None
    cells = read_cells(text) if cells is None else cells
    if not cells: return None
    spans, found = source_spans(text, cells), []
    for i, cell in enumerate(cells):
        for n, line in enumerate(cell_lines(cell), 1):
            if needle in str(line):
                found.append((i, n))
                break
    if len(found) != 1: return None
    i, n = found[0]
    return _at(cells, spans, i, n)
