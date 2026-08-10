"""The keymap, as data the browser asks for rather than chords it hardcodes.

The whole point of serving the map is that nothing in the frontend needs to know a chord.
`/keys.json` hands over the bindings, the help rows, the menus and the button bars in one
fetch, and the page renders whatever it is given -- which is also why editing the keymap
applies without a restart: rewrite the file, re-read it, return the rebuilt map.

Keeps no state. Nothing here touches the workspace, which is why `CAPS` is empty -- and
why this was the right block to extract first.
"""

from __future__ import annotations

import json

from fasthtml.common import JSONResponse

from ... import errstr
from ...core import keys as keymap
from ...core.buttons import bar as btn_bar
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
        from ...core.buttons import BARS
        return JSONResponse({'keys': web_keymap(), 'help': help_rows(), 'menus': web_menus(),
                             'path': str(keymap_path()), 'notes': list(keymap.NOTES),
                             'bars': {n: [{'action': b.action, 'label': b.label, 'title': b.tooltip,
                                           'kind': b.kind} for b in btn_bar(n)] for n in BARS}})

    # -- the user's keymap -------------------------------------------------
    # Editable from the IDE and applied without a restart: rewriting the file, re-reading
    # it, and returning the rebuilt browser map is the entire update path.
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
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        except Exception as e: return fail(e)
        keymap.reload()
        return {'ok': True, 'path': str(p), 'notes': list(keymap.NOTES),
                'keys': web_keymap(), 'help': help_rows()}

    @rt('/keys/reset')
    def keys_reset():
        "Put leela's own defaults back, so a keymap you cannot use is one click from gone."
        p = keymap.write_keymap(keys=keymap.DEFAULTS)
        keymap.reload()
        return {'ok': True, 'path': str(p), 'notes': list(keymap.NOTES),
                'keys': web_keymap(), 'help': help_rows()}
