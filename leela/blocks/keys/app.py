"The keymap, as data the browser asks for rather than chords it hardcodes."

from __future__ import annotations

import json

from fasthtml.common import JSONResponse

from ... import errstr
from fastcore.all import L

from ...core import keys as keymap
from ...core.ui import bar as btn_bar
from ...core.web import fail
from ...core.keys import help_rows, keymap_json, keymap_path, web_keymap
from .menus import web_menus

__all__ = ['CAPS', 'connect']

CAPS = ()

def connect(app, ctx):
    rt = app.route
    @rt('/keys.json')
    def keys_json():
        "The keymap, and the buttons that run the same actions -- one fetch, one source."
        from ...core.ui import BARS
        return JSONResponse({'keys': web_keymap(), 'help': help_rows(), 'menus': web_menus(),
                             'path': str(keymap_path()), 'notes': list(keymap.NOTES),
                             'bars': {n: [{'action': b.action, 'label': b.label, 'title': b.tooltip,
                                           'kind': b.kind} for b in btn_bar(n)] for n in BARS}})
    @rt('/keys/file')
    def keys_file():
        p = keymap_path()
        try: text = p.read_text()
        except Exception: text = json.dumps(keymap_json(), indent=2) + '\n'
        return {'path': str(p), 'exists': p.exists(), 'text': text, 'notes': list(keymap.NOTES)}
    @rt('/keys/save')
    async def keys_save(req):
        "Write the keymap, re-read it, and hand back what it now says -- including what it refused."
        d = await req.json()
        text = d.get('text') or ''
        try: json.loads(text)
        except Exception as e: return fail(f'that is not valid JSON — {errstr(e)}')
        p = keymap_path()
        try: p.mk_write(text)
        except Exception as e: return fail(e)
        keymap.reload()
        return {'ok': True, 'path': str(p), 'notes': list(keymap.NOTES),
                'keys': web_keymap(), 'help': help_rows()}
    @rt('/keys/check')
    async def keys_check(req):
        """What a proposed map would be refused for, without writing it.

        The same `apply_overrides` the save runs, on a throwaway note list, so what the editor warns
        about while a person types cannot drift from what saving would actually reject.
        """
        d = await req.json()
        over = d.get('keys') or {}
        if not isinstance(over, dict): return fail('keys must be an object of action to chord')
        notes = L()
        applied = keymap.apply_overrides(keymap.DEFAULTS, {str(k): str(v) for k, v in over.items()}, notes)
        return {'ok': not notes, 'notes': list(notes),
                'keys': [{'action': k.action, 'key': k.key, 'keys': list(k.keys),
                          'scope': k.scope, 'label': k.label} for k in applied]}
    @rt('/keys/reset')
    def keys_reset():
        "Put leela's own defaults back, so a keymap you cannot use is one click from gone."
        p = keymap.write_keymap(keys=keymap.DEFAULTS)
        keymap.reload()
        return {'ok': True, 'path': str(p), 'notes': list(keymap.NOTES),
                'keys': web_keymap(), 'help': help_rows()}
