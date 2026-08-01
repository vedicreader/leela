"""Approval as a conversation.

Every harness that gates tool calls does it with a modal: *"Allow edit_file? [y/N]"*. It
works, and it teaches the model nothing. A refusal arrives at the model as the string
`Denied by human operator`, which tells it that something is wrong and not what, so the
next thing it does is try the same edit again with the indentation changed.

So approval here is a **turn in the conversation**, not a dialog box:

- The request is rendered as markdown, with a preview of what would actually change --
  the exhash commands, the first lines of a new file, the cell being rewritten. A person
  approving a write should be looking at the write.
- The answer carries an optional reason, and **the reason goes back to the model**. "no,
  that file is generated, edit the notebook instead" is a redirection; "Denied by human
  operator" is a wall.
- Both halves are recorded, so what the exchange looks like afterwards is a conversation
  that happened, in order, in the document -- see `leela.ai.notebook_approvals`, which
  writes each one into the notebook as markdown cells beside the prompt cell that caused
  it. The negotiation is saved with the work, re-readable next week, and legible in plain
  Jupyter.

The blocking is the fiddly part and worth being explicit about. `gate` runs on the model's
worker thread and has to stop there until a person answers on the UI thread, so it waits
on an `Event`. Two failure modes are handled rather than hoped about: nobody is listening
(no frontend has registered) and nobody answers (the person walked away). Both end as a
*denial with an explanation*, never as an IDE that has stopped taking keys.
"""

from __future__ import annotations
import json, threading, time, uuid
from dataclasses import dataclass, field

__all__ = ['DENIED', 'Ask', 'Approvals', 'always', 'never', 'policy', 'preview_for', 'ask_md', 'answer_md']

# What a refused tool call returns to the model when there is nothing more to say. Kept
# identical to rishi's own wording so a transcript reads the same on either backend.
DENIED = 'Denied by human operator'

DFLT_TIMEOUT = 300      # seconds to wait for a person before giving up on one request
MAX_PREVIEW = 2000      # chars of "what would change"; a person will not read more


def _args(args):
    "A tool call's arguments as a dict, whether the model sent a dict or a JSON string."
    if isinstance(args, str):
        try: args = json.loads(args)
        except Exception: return {}
    return args if isinstance(args, dict) else {}


def _tc(tool_call):
    "`(name, args)` from a tool call in either backend's shape."
    if hasattr(tool_call, 'name'): return tool_call.name, _args(getattr(tool_call, 'arguments', {}))
    fn = (tool_call or {}).get('function', {}) if isinstance(tool_call, dict) else {}
    return fn.get('name', '?'), _args(fn.get('arguments', {}))


# ---------------------------------------------------------------------------
# what the person is actually being asked
# ---------------------------------------------------------------------------
def _fmt_cmds(commands):
    "exhash commands as one readable block, rather than as a JSON blob nobody reads."
    try:
        cmds = json.loads(commands) if isinstance(commands, str) else commands
        if not isinstance(cmds, list): raise ValueError
    except Exception:
        return str(commands)[:MAX_PREVIEW]
    out = []
    for c in cmds:
        if not isinstance(c, (list, tuple)) or not c: out.append(str(c)); continue
        addr, op, rest = c[0], (c[1] if len(c) > 1 else ''), list(c[2:])
        body = '\n'.join('    ' + str(r).replace('\n', '\n    ') for r in rest)
        out.append(f'{addr} {op}' + (f'\n{body}' if body else ''))
    return '\n'.join(out)


def preview_for(name, args, host=None):
    """What this call would actually do, as text a person can read in a couple of seconds.

    Per tool rather than generic, because the useful preview is different every time: for
    an edit it is the commands, for a new file it is the head of the file, for a cell it is
    which cell. Anything unrecognised falls back to the arguments, which is still better
    than the tool's name alone.
    """
    p = args.get('path', '')
    if name == 'edit_file':   return f'{p}\n\n{_fmt_cmds(args.get("commands", ""))}'[:MAX_PREVIEW]
    if name == 'edit_cell':   return f'{p} cell {args.get("cell_id","?")}\n\n{_fmt_cmds(args.get("commands",""))}'[:MAX_PREVIEW]
    if name == 'create_file':
        text, exists = args.get('text', ''), False
        try: exists = bool(host and host.check(p).exists())
        except Exception: pass
        head = f'{p}  ({"OVERWRITES an existing file" if exists else "new file"}, {len(text)} chars)\n\n'
        return (head + text)[:MAX_PREVIEW]
    if name == 'add_cell':
        return f'{p}  (new {args.get("cell_type","code")} cell at {args.get("index",-1)})\n\n{args.get("source","")}'[:MAX_PREVIEW]
    if name == 'run_python':  return str(args.get('code', ''))[:MAX_PREVIEW]
    return json.dumps(args, indent=2, default=str)[:MAX_PREVIEW]


def _summary(name, args):
    "The one-line version, for a status bar or a footer."
    if p := args.get('path'): return f'{name} → {p}'
    return f'{name}({", ".join(sorted(args))})'


@dataclass
class Ask:
    """One request, and the person's answer to it.

    `answer` is None while it is pending, which is also what the frontends poll on. The
    `Event` is what the model's thread is sitting on; nothing outside this module should
    touch it, and `answer()` is the only thing that sets it.
    """
    tool: str
    args: dict = field(default_factory=dict)
    summary: str = ''
    preview: str = ''
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    answer: bool = None
    note: str = ''
    asked: float = field(default_factory=time.time)
    _done: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)

    @property
    def pending(self): return self.answer is None

    def __bool__(self):
        """Truthy exactly when approved, so an `Ask` *is* the approval decision.

        This is what lets `Approvals.gate` return the whole object instead of a bool.
        Rishi's `if not ok` and fastllm's guard both keep working, and the reason the user
        gave travels with the decision to whoever formats the refusal.
        """
        return self.answer is True

    def dict(self):
        return {'id': self.id, 'tool': self.tool, 'summary': self.summary, 'preview': self.preview,
                'answer': self.answer, 'note': self.note, 'pending': self.pending}

    def resolve(self, ok, note=''):
        self.answer, self.note = bool(ok), note or ''
        self._done.set()
        return self

    def wait(self, timeout):
        "Block until answered or `timeout` seconds pass. Returns whether it was answered."
        return self._done.wait(timeout)

    def reply(self):
        """What the model is told. A refusal with a reason is the whole point of this module.

        An approval with a note carries it too: "yes, but keep the docstring" is guidance
        the model should have while it is making the edit, not after.
        """
        if self.answer: return f'Approved by the user. Note from the user: {self.note}' if self.note else None
        return f'{DENIED}. Reason given: {self.note}' if self.note else DENIED


def ask_md(ask):
    "An approval request as markdown -- what a person reads, and what is saved in the notebook."
    body = ask.preview.strip()
    fence = '```\n' + body + '\n```\n\n' if body else ''
    return (f'**🔐 approval needed — `{ask.tool}`**\n\n{ask.summary}\n\n{fence}'
            'Approve, or refuse with a reason — the reason goes back to the model.')


def answer_md(ask):
    "The person's half of the exchange, in the same voice."
    head = '**✅ approved**' if ask.answer else '**⛔ refused**'
    return f'{head} — `{ask.tool}`' + (f'\n\n{ask.note}' if ask.note else '')


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------
class Approvals:
    """The queue of one, and the thread handshake behind it.

    One at a time on purpose. A model that wants to edit four files should be answered
    four times, because "yes to all of that" is exactly the answer people give when they
    have not read any of it -- and the tools run sequentially on the local backend anyway.
    `mode` is where a bulk answer belongs instead: set it to `'auto'` for a session where
    the user has decided to stop being asked, and it is a deliberate act rather than a
    slip of the return key.

    `listeners` is not decoration. If no frontend has registered, nobody will ever answer,
    and `gate` would block the model's worker thread until the timeout for no reason. With
    zero listeners it refuses immediately and says why, which is a bad outcome that is at
    least a fast and legible one.
    """

    def __init__(self,
                 tools=(),                  # tool names that need approval; everything else runs
                 mode='ask',                # 'ask' | 'auto' (approve everything) | 'off' (refuse everything)
                 timeout=DFLT_TIMEOUT,
                 host=None,                 # for previews that need to look at disk
                 on_ask=None,               # called with the `Ask` when one is raised
                 on_answer=None):           # called with the `Ask` when it is answered
        self.tools, self.mode, self.timeout, self.host = frozenset(tools), mode, timeout, host
        self.on_ask, self.on_answer = on_ask, on_answer
        self.current = None                 # the `Ask` in flight, or None
        self.history = []                   # every `Ask` this session, answered or not
        self.listeners = 0                  # how many frontends are watching
        self._lock = threading.Lock()

    # -- the frontend side ---------------------------------------------------
    def listen(self):
        "Register a frontend. Returns a callable that unregisters it."
        with self._lock: self.listeners += 1
        done = [False]
        def stop():
            if done[0]: return
            done[0] = True
            with self._lock: self.listeners -= 1
        return stop

    @property
    def pending(self):
        "The request waiting for an answer, or None. What both frontends poll."
        a = self.current
        return a if (a is not None and a.pending) else None

    def answer(self, id, ok, note=''):
        "Answer the pending request. A stale id (the turn moved on) is ignored rather than an error."
        a = self.current
        if a is None or a.id != id or not a.pending: return None
        a.resolve(ok, note)
        if self.on_answer:
            try: self.on_answer(a)
            except Exception: pass
        return a

    def cancel_all(self, note='the turn was cancelled'):
        "Refuse anything in flight, so a stopped turn does not leave a worker thread parked."
        a = self.pending
        if a is not None: self.answer(a.id, False, note)

    # -- the model side ------------------------------------------------------
    def gate(self, tool_call):
        """The `approve(tool_call)` both backends call. Blocks the model's thread.

        Returns the `Ask`, not a bool: it is falsy when refused, so every existing
        `if not approve(tc)` still reads correctly, and it carries `reply()` so the reason
        the person gave can reach the model instead of being flattened to "denied".
        """
        return self.request(*_tc(tool_call))

    def request(self, name, args):
        """Raise one request and wait for it. Returns the resolved `Ask`.

        Returned rather than a bare bool because the caller needs `reply()` -- the reason
        the user gave is the part worth carrying back, and a bool has nowhere to put it.
        """
        a = Ask(tool=name, args=args, summary=_summary(name, args), preview=preview_for(name, args, self.host))
        self.history.append(a)
        if name not in self.tools:        return a.resolve(True)
        if self.mode == 'auto':           return a.resolve(True)
        if self.mode == 'off':            return a.resolve(False, 'approval is switched off for this session')
        if self.listeners < 1:            return a.resolve(False, 'nothing is listening for approvals, so this could not be asked')
        self.current = a
        if self.on_ask:
            try: self.on_ask(a)
            except Exception: pass
        if not a.wait(self.timeout):
            a.resolve(False, f'no answer after {self.timeout}s')
            if self.on_answer:
                try: self.on_answer(a)
                except Exception: pass
        return a


# ---------------------------------------------------------------------------
# policies
# ---------------------------------------------------------------------------
def always(tool_call): return True
def never(tool_call): return False


def policy(modes, ask):
    """`approve(tool_call)` from per-tool modes: 'approved' | 'check' | 'dont_run'.

    Rishi ships this as `hitl_policy` and fastllm has no equivalent at all, so it is
    written out here rather than imported: the harness needs one approval shape across
    both backends, and it must not stop working because the local engine is not installed.
    `fastllm_hitl.py` is what teaches the cloud side to call it.
    """
    def approve(tc):
        name, _ = _tc(tc)
        mode = (modes or {}).get(name, 'check')
        return True if mode == 'approved' else False if mode == 'dont_run' else ask(tc)
    return approve
