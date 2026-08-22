"""Desktop shortcuts that reach a running Leela. Copy beside `config.py` and import it.

A hotkey starts outside Leela's window, which is why the two things a window cannot do live here:
summoning it, and handing it what you are looking at somewhere else. Nothing imports `leela` --
the address is a JSON file a running workspace writes, so the standard library finds one.

    # ~/.config/macmage/config.py
    from leela import summon_leela, clip_to_leela, ask_leela, open_in_leela   # noqa: F401
"""

from __future__ import annotations

import json, os, urllib.error, urllib.request
from pathlib import Path

from macmage import get_clip, mage, notify, open_app, open_url

__all__ = ['SERVING', 'serving', 'call', 'summon_leela', 'clip_to_leela', 'ask_leela',
           'open_in_leela']

#: Written by `serve_ide` while it is answering, removed when it stops.
SERVING = Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'leela'/'serving.json'
TIMEOUT = 30

def serving():
    "Where a running Leela is answering, or None."
    # The pid is checked, not trusted: a killed workspace leaves a file naming somebody else's
    # port, which is the one way this could post your clipboard where you did not mean.
    try: d = json.loads(SERVING.read_text())
    except (OSError, ValueError): return None
    if not isinstance(d, dict) or not d.get('port'): return None
    try: os.kill(int(d.get('pid') or 0), 0)
    except (OSError, ValueError, TypeError): return None
    return d

def call(path, payload=None):
    "POST to a running workspace and return its answer. Raises `LookupError` when none is up."
    live = serving()
    if live is None: raise LookupError('no Leela is running')
    body = json.dumps(payload or {}).encode()
    req = urllib.request.Request(live['url'].rstrip('/') + path, data=body,
                                 headers={'content-type': 'application/json'})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r: return json.loads(r.read() or b'{}')

async def _tell(title, answer):
    "One banner, whatever the route called it a problem or not."
    ok = answer.get('ok', True) if isinstance(answer, dict) else True
    await notify('Leela', title if ok else str(answer.get('error') or 'refused'))
    return ok

@mage(keys='alt-cmd-l')
async def summon_leela():
    "Bring Leela to the front, launching it when it is not running."
    live = serving()
    if live is None: return open_app('Leela')
    # A workspace served into a browser has no application of its own to raise; its URL does.
    try: open_app('Leela')
    except ValueError: open_url(live['url'])

@mage(keys='alt-cmd-shift-l')
async def clip_to_leela():
    "Keep what is on the clipboard as an agent memory note."
    text = (get_clip() or '').strip()
    if not text: return await notify('Leela', 'the clipboard holds no text')
    title = ' '.join(text.split())[:60]
    try: answer = call('/agent/memory/save', {'title': title, 'text': text})
    except LookupError: return await notify('Leela', 'no Leela is running')
    except urllib.error.URLError as e: return await notify('Leela', f'could not reach it: {e.reason}')
    await _tell(f'remembered · {title}', answer)

@mage(keys='alt-cmd-k')
async def ask_leela():
    "Send the clipboard to the conversation on screen as a turn, and raise the window to watch it."
    text = (get_clip() or '').strip()
    if not text: return await notify('Leela', 'the clipboard holds no text')
    try: answer = call('/agent/turn', {'prompt': text})
    except LookupError: return await notify('Leela', 'no Leela is running')
    except urllib.error.URLError as e: return await notify('Leela', f'could not reach it: {e.reason}')
    if await _tell('asked', answer): await summon_leela()

@mage(keys='alt-cmd-o')
async def open_in_leela():
    "Open the folder whose path is on the clipboard. A file opens the folder holding it."
    raw = (get_clip() or '').strip().strip('"\'')
    p = Path(raw).expanduser() if raw else None
    if p is None or not p.exists(): return await notify('Leela', 'the clipboard is not a path')
    folder = p if p.is_dir() else p.parent
    try: answer = call('/fs/add-root', {'path': str(folder)})   # the JSON one; `add_root` repaints
    except LookupError:
        open_app('Leela')
        return await notify('Leela', f'starting, then open {folder.name} yourself')
    except urllib.error.URLError as e: return await notify('Leela', f'could not reach it: {e.reason}')
    if await _tell(f'opened · {folder.name}', answer): await summon_leela()
