"kavacha's native window, wearing Leela's name, keymap and menu bar."

from __future__ import annotations

from kavacha.window import (ALT, CMD, CTRL, DEFAULT_SIZE, DOCK_RECENT, MIN_SIZE, NO_SUBSTITUTION,
    SHIFT, BACKENDS, ShellApi, backend, eval_js, install_menu_patch, keep_running_in_dock,  # noqa: F401
    mac_key, make_window, off_main_thread, open_window, quiet_text_substitution, shell_api,
    quit_cleanly, shell_ready, splash, start_cdp, use_app, wait_for_http, warm_cdp, watch_open_events,
    window_size, OpenHandler, RecentTarget, hidden_windows, keyed_windows)
from kavacha.window import dock_menu as _dock_menu, menu_bar as _menu_bar
from kavacha.window import menu_chord as _menu_chord, menus as _menus, run_shell as _run_shell

from . import leela_cfg
from .core.projects import last_folder, last_folders, recent_folders, remember, session  # noqa: F401

__all__ = ['BACKENDS', 'backend', 'shell_ready', 'wait_for_http', 'start_cdp', 'warm_cdp',
           'window_size', 'run_shell', 'quiet_text_substitution', 'NO_SUBSTITUTION',
           'keep_running_in_dock', 'dock_menu', 'DOCK_RECENT',
           'watch_open_events', 'ShellApi', 'shell_api', 'make_window', 'open_window',
           'off_main_thread', 'menus', 'menu_bar', 'mac_key', 'menu_chord',
           'session', 'remember', 'last_folders', 'last_folder', 'recent_folders']

use_app('leela', leela_cfg, 'LEELA_')
#: The page reaches this as `window.pywebview.api.recent()`, and the Dock menu reads the same hook.
shell_api().on_recent = recent_folders

def _act(action):
    "What picking a menu row does: the client's own dispatcher, in the window that has focus."
    return eval_js(f'leeAct("{action}")')

def _table():
    from .blocks.keys.menus import BAR
    from .core.keys import lookup
    return BAR, lookup

def dock_menu(on_folder, recent=None):
    "The Dock's own menu: the folders you last had open, newest first."
    return _dock_menu(on_folder, recent_folders() if recent is None else recent)

def menu_chord(action):
    "The chord to put on a menu row, or None to leave it bare."
    return _menu_chord(action, _table()[1])

def menu_bar(run=None):
    "pywebview menus for `BAR`, plus the table `install_menu_patch` needs to finish them off."
    return _menu_bar(*_table(), _act, run)

def menus():
    "The menu bar, or an empty bar off macOS."
    return _menus(*_table(), _act)

def run_shell(urls, titles=(), **kw):
    "One native window per workspace URL, until they all close. Blocks, on the main thread."
    bar, lookup = _table()
    for k, v in dict(bar=bar, lookup=lookup, on_action=_act, on_recent=recent_folders).items():
        kw.setdefault(k, v)
    # The page repaints the native background on every theme change; this is the colour before it loads.
    if 'background' not in kw:
        from .blocks.settings.settings import theme_background
        try: kw['background'] = theme_background()
        except Exception: pass
    # Off the Dock delegate a quit returns here; reap before finalisation joins a pool that may never finish.
    try: return _run_shell(urls, titles, **kw)
    finally: quit_cleanly()
