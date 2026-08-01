"""What the agent is doing, while it is doing it.

An agentic turn is mostly silence. The model reads six files, runs four searches, fetches
a page and then, forty seconds later, says something. Without a running account of that,
the only honest thing an IDE can display is a spinner -- and a spinner is indistinguishable
from a hang, which is why people kill turns that were about to succeed.

So every tool call becomes a **message**: a one-line summary in the imperative, and the
result folded underneath it. `Search AgentSession|agent_tools`. `View leela/ai.py:240-290`.
`Web fetch: https://github.com/AnswerDotAI/ipymini`. The line alone is usually enough to
follow the reasoning; the fold is there for when it is not.

Two things follow from putting this in the harness rather than in a frontend:

**Both frontends show the same thing.** `rows()` is what the web client renders and what
the TUI's pane iterates, in the same order with the same words, for the same reason
`keys.py` exists.

**It is saved.** `md()` renders the stream as markdown with `<details>` folds, which is
what goes into the prompt cell's reply alongside the answer. So a notebook read next week
still shows which files the answer came from, and still opens in plain Jupyter, where
`<details>` is just HTML.
"""

from __future__ import annotations
import threading, time, uuid
from dataclasses import dataclass, field

__all__ = ['Act', 'Activity', 'summarise', 'ICONS', 'MAX_DETAIL']

MAX_DETAIL = 4000     # chars of a tool result kept for the fold
MAX_ACTS = 500        # a very long turn should not grow without bound

ICONS = {'search': '🔍', 'view': '📄', 'edit': '✏️', 'web': '🌐',
         'run': '▶️', 'skill': '📚', 'delegate': '🤝', 'tool': '🔧'}

_KIND = {
    'search_code': 'search', 'similar_code': 'search', 'outline': 'search', 'list_files': 'search',
    'view_file': 'view', 'notebook_cells': 'view', 'view_cell': 'view', 'read_terminal': 'view',
    'edit_file': 'edit', 'create_file': 'edit', 'edit_cell': 'edit', 'add_cell': 'edit',
    'web_search': 'web', 'read_url': 'web', 'research': 'web',
    'run_python': 'run', 'list_vars': 'run',
    'read_skill': 'skill', 'delegate_search': 'delegate',
}


def _s(v, n=90):
    "One line of a value, short enough to sit in a list."
    t = ' '.join(str(v or '').split())
    return t if len(t) <= n else t[:n - 1] + '…'


def summarise(tool, args):
    """The imperative one-liner for a call: what a person would say they just did.

    Per tool rather than a generic `name(args)` render, because the useful summary is
    different every time and the generic one is unreadable at a glance -- which is the
    only way this list is ever read.
    """
    a = args if isinstance(args, dict) else {}
    p, q = a.get('path', ''), a.get('query', '')
    if tool == 'search_code':    return f'Search {_s(q)}'
    if tool == 'similar_code':   return f'Similar to {p}:{a.get("line", 1)}'
    if tool == 'outline':        return f'Outline {p}'
    if tool == 'list_files':     return f'List files {_s(a.get("pattern", "")) or "(all)"}'
    if tool == 'view_file':
        rng = f':{a["start"]}-{a["end"]}' if a.get('start') or a.get('end') else ''
        return f'View {p}{rng}'
    if tool == 'edit_file':      return f'Edit {p}'
    if tool == 'create_file':    return f'Create {p}'
    if tool == 'notebook_cells': return f'Cells of {p}'
    if tool == 'view_cell':      return f'View {p} cell {a.get("cell_id", "?")}'
    if tool == 'edit_cell':      return f'Edit {p} cell {a.get("cell_id", "?")}'
    if tool == 'add_cell':       return f'Add {a.get("cell_type", "code")} cell to {p}'
    if tool == 'web_search':     return f'Web search: {_s(q)}'
    if tool == 'read_url':       return f'Web fetch: {_s(a.get("url", ""), 120)}'
    if tool == 'research':       return f'Research: {_s(q)}'
    if tool == 'run_python':     return f'Run python: {_s((a.get("code", "") or "").strip().splitlines()[0] if a.get("code") else "")}'
    if tool == 'list_vars':      return 'List variables'
    if tool == 'read_terminal':  return 'Read terminal'
    if tool == 'read_skill':     return f'Read skill {a.get("name", "?")}'
    if tool == 'delegate_search': return f'Delegate: {_s(a.get("question", ""), 120)}'
    inner = ', '.join(f'{k}={_s(v, 30)!r}' for k, v in a.items())
    return f'{tool}({inner})'


@dataclass
class Act:
    "One tool call, from the moment it starts to whatever it returned."
    tool: str
    args: dict = field(default_factory=dict)
    summary: str = ''
    detail: str = ''
    ok: bool = True
    done: bool = False
    secs: float = 0.0
    started: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    @property
    def kind(self): return _KIND.get(self.tool, 'tool')

    @property
    def icon(self): return ICONS.get(self.kind, ICONS['tool'])

    def finish(self, out, ok=True):
        self.detail = _clip(out)
        self.ok, self.done = ok, True
        self.secs = round(time.time() - self.started, 2)
        return self

    def line(self):
        "The single line: icon, what it did, and how long -- or an hourglass while it runs."
        if not self.done: return f'⏳ {self.summary}'
        tail = f'  ({self.secs:.1f}s)' if self.secs >= 0.5 else ''
        return f'{"" if self.ok else "⚠️ "}{self.icon} {self.summary}{tail}'

    def md(self, fold=True):
        "This call as markdown: the line, with the result folded under it when there is one."
        if not (self.detail and fold): return f'- {self.line()}'
        body = self.detail.replace('```', '`​``')     # a fence in a result must not end ours
        return (f'- {self.line()}\n\n'
                f'  <details><summary>result</summary>\n\n  ```\n{_indent(body)}\n  ```\n\n  </details>')

    def dict(self):
        return {'id': self.id, 'tool': self.tool, 'kind': self.kind, 'icon': self.icon,
                'summary': self.summary, 'line': self.line(), 'detail': self.detail,
                'ok': self.ok, 'done': self.done, 'secs': self.secs,
                'args': {k: _s(v, 300) for k, v in (self.args or {}).items()}}


def _clip(out, n=MAX_DETAIL):
    s = '' if out is None else str(out)
    return s if len(s) <= n else s[:n] + f'\n…[{len(s)-n} more chars]'


def _indent(s, pad='  '):
    return '\n'.join(pad + l for l in s.splitlines())


class Activity:
    """The stream of calls for a session, and the hook a frontend hangs a redraw on.

    `on_change` fires twice per call -- once when it starts and once when it finishes --
    so a frontend can show `⏳ Web fetch: …` while the fetch is happening rather than only
    afterwards. That is the entire difference between a UI that looks alive and one that
    looks stuck, and it is why this is not simply a list appended to after the fact.

    Thread-safe because tools run on the model's worker thread and frontends read from
    theirs. The lock is around list mutation only; `on_change` is called outside it, so a
    slow frontend cannot stall the model.
    """

    def __init__(self, on_change=None, max_acts=MAX_ACTS):
        self.acts, self.on_change, self.max_acts = [], on_change, max_acts
        self._lock = threading.Lock()
        self._mark = 0

    def __len__(self): return len(self.acts)

    def start(self, tool, args):
        a = Act(tool=tool, args=dict(args or {}), summary=summarise(tool, args))
        with self._lock:
            self.acts.append(a)
            if len(self.acts) > self.max_acts: del self.acts[:-self.max_acts]
        self._changed(a)
        return a

    def finish(self, act, out, ok=True):
        act.finish(out, ok)
        self._changed(act)
        return act

    def _changed(self, act):
        if not self.on_change: return
        try: self.on_change(act)
        except Exception: pass

    # -- reading it ----------------------------------------------------------
    def mark(self):
        "Remember where the stream is now, so `since()` can report one turn's worth."
        self._mark = len(self.acts)
        return self._mark

    def since(self, mark=None):
        return self.acts[(self._mark if mark is None else mark):]

    def rows(self, n=None, mark=None):
        "The stream as dicts, for a frontend. `mark` limits it to one turn."
        acts = self.since(mark) if mark is not None else self.acts
        return [a.dict() for a in (acts[-n:] if n else acts)]

    def md(self, mark=None, fold=True, title='what I did'):
        """The stream as markdown, for saving into a notebook cell.

        Wrapped in a `<details>` of its own so a reply is readable at a glance and the
        working is one click away -- an answer buried under thirty tool calls is an answer
        nobody reads.
        """
        acts = self.since(mark) if mark is not None else self.acts
        if not acts: return ''
        body = '\n'.join(a.md(fold) for a in acts)
        return f'<details><summary>{title} ({len(acts)} steps)</summary>\n\n{body}\n\n</details>'

    def lines(self, mark=None):
        "Just the summary lines, for a status pane with no room for folds."
        return [a.line() for a in (self.since(mark) if mark is not None else self.acts)]
