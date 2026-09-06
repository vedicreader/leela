"The document drawn as a standalone page: both views, and the basket that feeds the model."

from __future__ import annotations
import json
from importlib.resources import files
from fastcore.all import Path

from .context import SCOPES, Spec, WRAP, body_text, members, spec_of
from .doc import Doc

__all__ = ['payload', 'paint']

def payload(doc):
    "Everything the prototype needs: blocks, frames, edges, and each prompt's scope membership."
    blocks = []
    for b in doc.blocks:
        if b.kind == 'edge': continue
        t = body_text(b, doc)
        blocks.append({'id': b.id, 'kind': b.kind, 'frame': b.frame, 'mode': b.mode,
                       'x': b.x, 'y': b.y, 'w': b.w, 'h': b.h, 'stale': doc.stale(b.id),
                       'label': (b.title or b.source or b.kind).strip().splitlines()[0][:60],
                       'chars': len(t), 'text': t, 'props': b.props})
    prompts = {p.id: {'spec': spec_of(p).dict(),
                      'members': {s: [x.id for x in members(doc, p, s) if x.kind != 'edge']
                                  for s in SCOPES}}
               for p in doc.of('prompt')}
    frames = [{'id': f.id, 'title': f.title, 'x': f.x, 'y': f.y, 'w': f.w, 'h': f.h}
              for f in doc.of('frame') if f.placed]
    return {'title': doc.meta.get('title') or Path(doc.path).stem or 'untitled',
            'blocks': blocks, 'frames': frames, 'scopes': list(SCOPES), 'wrap': WRAP,
            'edges': [{'src': e.get('src'), 'dst': e.get('dst'), 'rel': e.get('rel', 'feeds')}
                      for e in doc.edges],
            'goal': doc.goal.id if doc.goal else '',
            'firstPrompt': next(iter(prompts), ''), 'prompts': prompts}

def _asset(name): return files(__package__).joinpath(name).read_text(encoding='utf-8')

def paint(doc, path=None, shell='bare'):
    "Write the prototype to `path`. `shell='leela'` draws it inside the IDE it would live in."
    d = payload(doc)
    tpl = 'proto-ide.html' if shell == 'leela' else 'proto.html'
    html = (_asset(tpl)
            .replace('__CSS__', _asset('proto.css'))
            .replace('__CSS2__', _asset('proto-ide.css') if shell == 'leela' else '')
            .replace('__JS__', _asset('proto.js'))
            .replace('__TITLE__', d['title'])
            .replace('__FILE__', Path(doc.path).name or 'plan.pata')
            .replace('__GOAL__', doc.goal.source if doc.goal else '')
            .replace('__DATA__', json.dumps(d, ensure_ascii=False)))
    p = Path(path or (Path(doc.path).with_suffix('.html') if doc.path else 'pata.html'))
    p.write_text(html, encoding='utf-8')
    return p
