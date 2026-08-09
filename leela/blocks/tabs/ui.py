"""The tab strip.

Titles disambiguate only when they have to. Two files called `app.py` would be
indistinguishable, so a duplicated title is shown as `root/relative/path` while a unique
one stays short — the panel is narrow, and widening every label to disambiguate the rare
collision would cost the common case.

Each tab carries two independent states: `running` (cells executing) and `dirty` (unsaved).
They are separate spans because they answer different questions and can both be true.
"""

from __future__ import annotations

from pathlib import Path

from fasthtml.common import Button, Div, Span

__all__ = ['tab_bar', 'kernel_pill']


def tab_bar(ws):
    "The open tabs. `alt+1..9` selects, the x closes."
    if not ws.tabs: return Div(Span('no files open', cls='lee-dim'), id='tabbar', cls='lee-tabbar', role='tablist')
    kids=[];counts={}
    for t in ws.tabs:counts[t.title]=counts.get(t.title,0)+1
    def label(t):
        if counts[t.title]<2 or not t.path:return t.title
        try:
            root=ws.fs.root_of(t.path);return f'{root.name}/{Path(t.path).relative_to(root)}'
        except Exception:return t.path
    for i,t in enumerate(ws.tabs):
        cls='lee-tab'+(' active' if i==ws.active else '')+(' dirty' if t.dirty else '')
        kids.append(Div(
            Span(cls='lee-tab-run', title=f'{t.running} cell(s) running') if t.running else '',
            Span(cls='lee-save-state '+('pending' if t.dirty else 'saved'),
                 title='changes waiting for autosave' if t.dirty else 'saved on disk',
                 aria_label='changes waiting for autosave' if t.dirty else 'saved on disk'),
            Span(label(t),cls='lee-tab-name'),
            Button('×', cls='lee-tab-x', title=f'close {t.title}', aria_label=f'close {t.title}',
                   onclick=f'event.stopPropagation();leeCloseTab({i})'),
            cls=cls,title=t.path or t.title,data_i=i,data_kind=t.kind,role='tab',
            aria_selected='true' if i == ws.active else 'false', tabindex='0' if i == ws.active else '-1',
            hx_post=f'/tab/select?i={i}', hx_target='#tabbar', hx_swap='outerHTML'))
    return Div(*kids, id='tabbar', cls='lee-tabbar', role='tablist', aria_label='open files')


def kernel_pill(ws):
    "Kernel identity and liveness for the active tab. Clicking it opens the picker."
    common = dict(id='kpill', onclick='leeAct("pick_kernel")')
    if (k := ws.runtime_peek()) is None:
        return Span('no kernel', cls='lee-pill lee-pill-off', title='choose a kernel', **common)
    if not k.alive: return Span('kernel dead', cls='lee-pill lee-pill-err', title='choose a kernel', **common)
    nm = getattr(k, 'name', '') or Path(ws.kernel_key()).name or 'kernel'
    return Span(f'⏺ {nm}', cls='lee-pill lee-pill-on',
                title=f'{k.base or "no inspector"} · pid {k.pid} — click to change', **common)
