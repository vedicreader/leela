"The keymap, as data the browser asks for rather than chords it hardcodes."

from __future__ import annotations

import json

from fasthtml.common import JSONResponse

from ... import errstr
from fastcore.all import L

from ...core import keys as keymap
from ...core.backups import guard
from ...core.ui import bar as btn_bar
from ...core.web import fail
from ...core.keys import glyphs, help_rows, keymap_json, keymap_path, legacy_rows, web_keymap
from .menus import menu_chords, web_menus

__all__ = ['CAPS', 'connect', 'keys_payload']

CAPS = ()

def keys_payload():
    "The keymap, and the buttons that run the same actions, from one source in one fetch."
    from ...core.ui import BARS
    return {**_live(), 'menus': web_menus(), 'menuChords': menu_chords(),
            'path': str(keymap_path()), 'notes': list(keymap.NOTES),
            'bars': {n: [{'action': b.action, 'label': b.label, 'title': b.tooltip,
                          'kind': b.kind} for b in btn_bar(n)] for n in BARS}}

def _live():
    "What changes when the keymap does: the rows, the help, the glyphs and the old chords."
    return {'keys': web_keymap(), 'help': help_rows(), 'glyphs': glyphs(), 'legacy': legacy_rows()}

def connect(app, ctx):
    rt = app.route
    @rt('/keys.json')
    def keys_json(): return JSONResponse(keys_payload())
    def _file(p):
        "What the file now holds, for a panel that must not save from a stale copy of it."
        try: text = p.read_text()
        except Exception: text = json.dumps(keymap_json(), indent=2) + '\n'
        return {'text': text, 'overrides': keymap.read_overrides(p, notes=L()),
                'defaults': {k.action: k.key for k in keymap.DEFAULTS}}
    @rt('/keys/file')
    def keys_file():
        p = keymap_path()
        return {'path': str(p), 'exists': p.exists(), 'notes': list(keymap.NOTES), 'took': list(keymap.TOOK), **_file(p)}
    @rt('/keys/save')
    async def keys_save(req):
        "Write the keymap, re-read it, and hand back what it now says, including what it refused."
        d = await req.json()
        text = d.get('text') or ''
        try: posted = json.loads(text)
        except Exception as e: return fail(f'that is not valid JSON: {errstr(e)}')
        over = posted.get('keys') if isinstance(posted, dict) else None
        if isinstance(over, dict) and (set(posted) == {'keys'} or keymap.bulk_map(over)):
            over = {str(a): str(c) for a, c in over.items()}
            if keymap.bulk_map(over): over = keymap.only_changed(over)
            text = json.dumps(keymap_json(over=over), indent=2) + '\n'
        p = keymap_path()
        guard(p, reason='before the keymap was saved')
        try: p.mk_write(text)
        except Exception as e: return fail(e)
        keymap.reload()
        return {'ok': True, 'path': str(p), 'notes': list(keymap.NOTES), 'took': list(keymap.TOOK),
                **_live(), **_file(p)}
    @rt('/keys/check')
    async def keys_check(req):
        "Why a proposed keymap would be refused, and the map it would produce, without writing either."
        d = await req.json()
        over = d.get('keys') or {}
        if not isinstance(over, dict): return fail('keys must be an object of action to chord')
        notes, took = L(), L()
        applied = keymap.apply_overrides(keymap.DEFAULTS, {str(k): str(v) for k, v in over.items()}, notes, took)
        return {'ok': not notes, 'notes': list(notes), 'took': list(took),
                'keys': [{'action': k.action, 'key': k.key, 'keys': list(k.keys),
                          'scope': k.scope, 'label': k.label} for k in applied]}
    @rt('/keys/reset')
    def keys_reset():
        "Put leela's own defaults back, so a keymap you cannot use is one click from gone."
        p = keymap.write_keymap(keys=keymap.DEFAULTS, keep=False)
        keymap.reload()
        return {'ok': True, 'path': str(p), 'notes': list(keymap.NOTES), 'took': list(keymap.TOOK),
                **_live(), **_file(p)}
