"""The chrome every panel is built from.

Four helpers, shared because a block's panel has to look like the rest of the IDE without
knowing anything about the rest of the IDE. They live in core rather than in a block for
the reason stated in `leela/core/__init__.py`: what two blocks both need belongs here.

The buttons matter more than they look. `btn(b)` renders a row from `leela.core.buttons` with
`onclick="leeAct(action)"` -- the *same* action name the keymap binds to a chord. One table,
one code path, so a button and its keyboard shortcut cannot drift into doing different
things, and `/keys.json` can serve both to the browser together.
"""

from __future__ import annotations

from fasthtml.common import Button, Div, NotStr

from .buttons import bar as btn_bar

__all__ = ['btn', 'action_bar', 'menu_button', 'activity_icon', 'ICONS']


def btn(b):
    "One button from the shared table. The click runs the same action its key runs."
    return Button(b.label, cls='lee-btn ' + (b.kind or 'plain'), title=b.tooltip,
                  data_action=b.action, onclick=f'leeAct("{b.action}")')


def action_bar(name, **kw):
    "A whole bar of them, in the order `leela.core.buttons` declares."
    return Div(*[btn(b) for b in btn_bar(name)], cls=f'lee-bar lee-bar-{name}', **kw)


def menu_button(surface):
    "Mouse-discoverable door into the same contextual registry used by right-click."
    return Button('⋯', cls='lee-more', title=f'{surface} actions', aria_label=f'{surface} actions',
                  onclick=f'leeMenuAt("{surface}", this)')


ICONS = {
    'files': '<path d="M2.5 5.5h6l1.7 2h7.3v8.5h-15zM2.5 5.5V4h5l1.5 1.5"/>',
    'symbols': '<path d="M5 3.5h10M5 10h10M5 16.5h10"/><circle cx="3" cy="3.5" r="1"/>'
               '<circle cx="3" cy="10" r="1"/><circle cx="3" cy="16.5" r="1"/>',
    # a workflow is a graph: one job fanning into two
    'workflows': '<circle cx="4" cy="10" r="2"/><circle cx="16" cy="5" r="2"/><circle cx="16" cy="15" r="2"/>'
                 '<path d="M6 9.3 14 5.7M6 10.7 14 14.3"/>',
    # a release is a tagged thing leaving: a box with an arrow out of it
    'releases': '<path d="M3 7.5 10 4l7 3.5v5L10 16l-7-3.5z"/><path d="M10 9.5 17 6M10 9.5 3 6M10 9.5V16"/>',
    # a deploy is a thing leaving for somewhere else: a box on a wire
    'deploys': '<rect x="2.5" y="11" width="7" height="6" rx="1"/><rect x="11.5" y="3" width="6" height="5" rx="1"/>'
               '<path d="M9.5 12.5h3a2 2 0 0 0 2-2V8"/>',
    # driving the parts directly: three blocks stacked, each its own thing
    'drive': '<rect x="3" y="3" width="14" height="3.5" rx="1"/><rect x="3" y="8.25" width="14" height="3.5" rx="1"/>'
             '<rect x="3" y="13.5" width="14" height="3.5" rx="1"/>',
    'git': '<circle cx="5" cy="4" r="2"/><circle cx="15" cy="6" r="2"/><circle cx="5" cy="16" r="2"/>'
           '<path d="M5 6v8m2-7h4a4 4 0 0 1 4 4v-3"/>',
}


def activity_icon(kind):
    "Small monochrome activity-bar icons; labels remain available to assistive tech."
    return NotStr(f'<svg viewBox="0 0 20 20" aria-hidden="true">{ICONS.get(kind, ICONS["git"])}</svg>')
