"The tab strip, and the kernel pill beside it."

from __future__ import annotations

from collections import Counter
from pathlib import Path

from fasthtml.common import Button, Div, Span

__all__ = ['tab_bar', 'kernel_pill']

def tab_bar(ws):
    "The open tabs. `alt+1..9` selects, the x closes."
    if not ws.tabs: return Div(Span('no files open', cls='lee-dim'), id='tabbar', cls='lee-tabbar')
    counts = Counter(t.title for t in ws.tabs)
    def label(t):
        "A shared title widens to `root/relative/path`; a unique one stays short."
        if counts[t.title] < 2 or not t.path: return t.title
        try:
            root = ws.fs.root_of(t.path)
            return f'{root.name}/{Path(t.path).relative_to(root)}'
        except Exception: return t.path
    def tab(i, t):
        active, saved = i == ws.active, 'changes waiting for autosave' if t.dirty else 'saved on disk'
        return Div(
            Span(cls='lee-tab-run', title=f'{t.running} cell(s) running') if t.running else '',
            Span(cls='lee-save-state ' + ('pending' if t.dirty else 'saved'), title=saved, aria_label=saved),
            Span(label(t), cls='lee-tab-name'),
            Span('read-only', cls='lee-dim') if t.path and ws.fs.read_only(t.path) else '',
            Button('×', cls='lee-tab-x', title=f'close {t.title}', aria_label=f'close {t.title}',
                   onclick=f'event.stopPropagation();leeCloseTab({i})'),
            cls='lee-tab' + (' active' if active else '') + (' dirty' if t.dirty else '') + ('' if t.path else ' untitled'),
            title=t.path or t.title, data_i=i, data_kind=t.kind, role='tab', draggable='true',
            aria_selected='true' if active else 'false', tabindex='0' if active else '-1',
            hx_post=f'/tab/select?i={i}', hx_target='#tabbar', hx_swap='outerHTML')
    return Div(*[tab(i, t) for i, t in enumerate(ws.tabs)], id='tabbar', cls='lee-tabbar',
        role='tablist', aria_label='open files')

def kernel_pill(ws):
    "Kernel identity and liveness for the active tab. Clicking it opens the picker."
    common = dict(id='kpill', role='button', tabindex='0', onclick='leeAct("pick_kernel")',
                  onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();leeAct('pick_kernel')}")
    if (k := ws.runtime_peek()) is None:
        return Span('no kernel', cls='lee-pill lee-pill-off', title='choose a kernel', **common)
    if not k.alive: return Span('kernel dead', cls='lee-pill lee-pill-err', title='choose a kernel', **common)
    nm = ws.runtime_label(k=k)
    return Span(f'⏺ {nm}', cls='lee-pill lee-pill-on',
                title=f'{k.base or "no inspector"} · pid {k.pid}. Click to change.', **common)
