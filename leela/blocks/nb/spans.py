"Mapping between file lines of an `.ipynb` and (cell, line-in-cell) coordinates."

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
    "The 1-based file line numbers holding each cell's source strings, or `None` where they cannot."
    lines, spans, idx = (text or '').splitlines(), [], 0
    for cell in cells:
        source = cell.get('source')
        count = len(source) if isinstance(source, list) else max(1, len(str(source or '').splitlines()))
        while idx < len(lines) and '"source"' not in lines[idx]: idx += 1
        if idx >= len(lines):
            spans.append(None)
            continue
        head, idx = lines[idx], idx + 1
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
    "The address of a line inside cell `i`. `id` is `''` before nbformat 4.5, so the index is always."
    span = spans[i]
    return dict(index=i, id=str(cells[i].get('id') or ''), line=line_in_cell,
        file_line=(span[0] + line_in_cell - 1) if span else 0, kind=str(cells[i].get('cell_type') or 'code'))

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
    "The cell holding `snippet`, when exactly one does; `None` for none or several."
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
