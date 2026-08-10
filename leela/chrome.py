"""Open Leela in the persistent Chrome managed by :mod:`fossick.cdp`.

Chrome's profile singleton is useful here: launching the same executable and user-data
folder with ``--app=URL`` asks the already-running debug Chrome to create an app window.
It does not create another resident browser.  If the CDP endpoint is absent, fossick's
setup function starts that persistent browser first.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
import urllib.request
from pathlib import Path

__all__ = ['cdp_ready', 'open_cdp_app']


def cdp_ready(port=9223, timeout=.35):
    "Return the debug endpoint metadata, or ``None`` when no Chrome answers."
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{int(port)}/json/version', timeout=timeout) as r:
            data = json.load(r)
        return data if data.get('webSocketDebuggerUrl') else None
    except Exception:
        return None


def open_cdp_app(url, port=9223, user_data_dir=None, wait=15):
    """Open ``url`` as an app window in fossick's persistent CDP Chrome.

    The returned dict is intentionally observable enough for the CLI and tests to report
    whether an existing browser was reused.  Chrome exits the short launcher process after
    handing the app-window request to its profile owner; that is success, not a crash.
    """
    from fossick.cdp import cdp_setup, chrome_bin, _debug_ready

    profile = Path(user_data_dir).expanduser() if user_data_dir else Path.home()/'.cache'/'fastcdp'/'cdp-chrome'
    reused = _debug_ready(port)
    if not reused: profile = Path(asyncio.run(cdp_setup(port=port, user_data_dir=profile, headless=False, timeout=wait)))
    args = [chrome_bin(), f'--remote-debugging-port={int(port)}', f'--user-data-dir={profile}',
            f'--app={url}', '--no-first-run', '--no-default-browser-check']
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    deadline = time.time() + min(float(wait), 5.0)
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{int(port)}/json/list', timeout=.35) as r:
                targets = json.load(r)
            if any(t.get('url', '').rstrip('/') == url.rstrip('/') for t in targets):
                return {'ok': True, 'url': url, 'port': int(port), 'profile': str(profile),
                        'reused': reused, 'target': next(t.get('id') for t in targets
                                                       if t.get('url', '').rstrip('/') == url.rstrip('/'))}
        except Exception:
            pass
        time.sleep(.1)
    return {'ok': True, 'url': url, 'port': int(port), 'profile': str(profile),
            'reused': reused, 'target': None}
