"Getting work back out: a notebook, a report, or the modules the code blocks were always for."

from __future__ import annotations
import re
from fastcore.all import L, Path

from .doc import Doc, Block, short

__all__ = ['to_ipynb', 'from_ipynb', 'to_markdown', 'modules', 'write_modules', 'directives']

def _md(source, meta=None):
    c = {'cell_type': 'markdown', 'source': source, 'metadata': {}}
    if meta: c['metadata'] = {'leela' if meta.get('kind') == 'prompt' else 'pata': meta}
    return c

def to_ipynb(doc):
    """The document as nbformat v4.

    Code blocks are code cells. Prompt blocks take Leela's own `metadata.leela` shape, so a
    document opened as a notebook keeps its prompts. Everything else is markdown carrying
    `metadata.pata`, which `from_ipynb` reads back.
    """
    cells = []
    for b in doc.blocks:
        if b.kind == 'edge': continue
        m = {'flavour': b.flavour, **{k: v for k, v in
             (('frame', b.frame), ('mode', b.mode), ('x', b.x), ('y', b.y), ('w', b.w), ('h', b.h))
             if v not in ('', None, 'auto')}}
        if b.kind == 'code':
            c = {'cell_type': 'code', 'source': b.source, 'outputs': b.outputs, 'id': b.id,
                 'execution_count': b.get('execution_count'), 'metadata': {'pata': m}}
        elif b.kind == 'prompt':
            c = _md(b.source, {'kind': 'prompt', 'reply': b.get('reply', ''),
                               'calls': b.get('calls', []), 'usage': b.get('usage', {}), **m})
            c['id'] = b.id
        else:
            c = _md(_as_markdown(b), {**m, 'props': {k: v for k, v in b.props.items() if k != 'source'}})
            c['id'] = b.id
        cells.append(c)
    edges = [e.dict() for e in doc.edges]
    meta = {'pata': {'edges': edges, **doc.meta}} if (edges or doc.meta) else {}
    return {'cells': cells, 'metadata': {'kernelspec': {'name': 'python3', 'language': 'python',
            'display_name': 'Python 3'}, **meta}, 'nbformat': 4, 'nbformat_minor': 5}

def from_ipynb(nb, path=''):
    "Read a notebook back, or migrate one Leela already had. Unmarked cells become text and code."
    doc = Doc(path=path)
    seen = set()
    for c in (nb.get('cells') or []):
        src = c.get('source')
        src = ''.join(src) if isinstance(src, list) else str(src or '')
        lee, pm = (c.get('metadata') or {}).get('leela') or {}, (c.get('metadata') or {}).get('pata') or {}
        kind = short(pm.get('flavour') or ('prompt' if lee.get('kind') == 'prompt'
                                           else 'code' if c.get('cell_type') == 'code' else 'text'))
        props = dict(pm.get('props') or {})
        props['source'] = src
        if kind == 'code':
            props.update(outputs=list(c.get('outputs') or []), execution_count=c.get('execution_count'))
        if kind == 'prompt':
            props.update(reply=lee.get('reply', ''), calls=list(lee.get('calls') or []),
                         usage=dict(lee.get('usage') or {}))
        if kind in ('source', 'frame') and not props.get('title'):
            props['title'] = src.strip().splitlines()[0].lstrip('# ') if src.strip() else ''
        bid = str(c.get('id') or '')
        b = Block(kind=kind, props=props, frame=str(pm.get('frame') or ''),
                  mode=str(pm.get('mode') or 'auto'),
                  **{k: pm.get(k) for k in ('x', 'y', 'w', 'h')},
                  **({'id': bid} if bid and bid not in seen else {}))
        seen.add(b.id)
        doc.add(b)
    for e in ((nb.get('metadata') or {}).get('pata') or {}).get('edges') or []:
        doc.add(Block.from_dict(e))
    doc.meta = {k: v for k, v in (((nb.get('metadata') or {}).get('pata')) or {}).items() if k != 'edges'}
    return doc

def _as_markdown(b):
    if b.kind == 'goal':
        bits = [f'**{k}**: {b.get(k)}' for k in ('measure', 'baseline', 'target', 'by') if b.get(k)]
        return '\n\n'.join(x for x in [f'# {b.source}'.strip(), '  \n'.join(bits)] if x)
    if b.kind == 'task':
        mark = 'x' if b.get('status') == 'done' else ' '
        owner = f" ({b.get('owner')})" if b.get('owner') else ''
        return f'- [{mark}] {b.source}{owner}'
    if b.kind == 'source':
        where = b.get('url') or b.get('path') or ''
        head = f'[{b.title or where}]({where})' if where else (b.title or '')
        return '\n\n'.join(x for x in [f'> {head}', str(b.get('text') or '')] if x.strip())
    if b.kind == 'frame': return f'## {b.title}'
    if b.kind == 'data': return f'`{b.get("name") or b.get("path") or ""}`\n\n{b.get("preview") or ""}'
    return b.source

def to_markdown(doc, code=True):
    "The document as a report. `code` keeps the code blocks; without it, only the narrative."
    out = []
    for b in doc.blocks:
        if b.kind == 'edge': continue
        if b.kind == 'code':
            if not code: continue
            out.append(f'```{b.get("lang") or "python"}\n{b.source}\n```')
        elif b.kind == 'prompt':
            out.append(f'**{b.source.strip()}**\n\n{str(b.get("reply") or "").strip()}')
        else: out.append(_as_markdown(b))
    return '\n\n'.join(x for x in out if x.strip()) + '\n'

_DIRECT = re.compile(r'^#\|\s*(\S+)(?:\s+(\S+))?\s*$', re.M)

def directives(source):
    "The nbdev `#|` lines a code block opens with, as `{name: value}`."
    head = []
    for line in (source or '').splitlines():
        if not line.lstrip().startswith('#|'): break
        head.append(line)
    return {m.group(1): (m.group(2) or '') for m in _DIRECT.finditer('\n'.join(head))}

def _body(source):
    lines = (source or '').splitlines(True)
    n = 0
    while n < len(lines) and lines[n].lstrip().startswith('#|'): n += 1
    return ''.join(lines[n:]).strip('\n')

def modules(doc, default=None):
    """`{relative path: source}` for the code blocks marked `#|export`.

    `#|default_exp pkg.mod` names where an unqualified `#|export` goes. `#|export other.mod`
    overrides it for one block. A document with no export directive yields nothing.
    """
    default = default or doc.meta.get('default_exp') or ''
    for b in doc.of('code'):
        d = directives(b.source)
        if d.get('default_exp'): default = d['default_exp']
    out = {}
    for b in doc.of('code'):
        d = directives(b.source)
        if 'export' not in d and 'exporti' not in d: continue
        mod = d.get('export') or d.get('exporti') or default
        if not mod: continue
        out.setdefault(mod.replace('.', '/') + '.py', []).append(_body(b.source))
    head = f'"""Generated by pata from {Path(doc.path).name or "a dynamic document"}. Edit the document."""\n'
    return {p: head + '\n' + '\n\n'.join(v) + '\n' for p, v in out.items()}

def write_modules(doc, root, default=None):
    "Write `modules` under `root`, returning the paths written."
    root, out = Path(root), L()
    for rel, src in modules(doc, default).items():
        p = root/rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src, encoding='utf-8')
        out.append(p)
    return out
