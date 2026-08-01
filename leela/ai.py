"""The IDE's agent: a Rishi chat whose tools are the IDE's own capabilities.

The point of this module is that the model gets the *same* four powers the human
sitting in front of leela has, through the same code paths:

- **see the code** -- kosha's index, so "where is this already done" searches the
  repo *and* every installed package, not just open files.
- **read the web** -- fossick, so a question about an unfamiliar API is answered
  from the actual docs rather than from training data.
- **edit files** -- exhash, so every edit is addressed by `line|hash|` and fails
  loudly if the file moved under it. A model working from a stale read cannot
  quietly corrupt a file; it gets an error and has to look again.
- **run code** -- the existing `AgentSession`, which already refuses to rebind the
  owner's variables and logs every attempt to a transcript notebook.

Two invariants hold across all of it:

*Every path goes through `Sandbox`.* exhash and fossick both write to disk on
their own; each is handed a path that `Sandbox._check` has already resolved and
approved, so the agent cannot edit or download outside the open folders.

*Every tool returns a string.* Rishi feeds tool results straight back into the
context window, so results are truncated here rather than after they have already
cost tokens.

The model itself is loaded lazily and is allowed to be missing: `Assistant.ready`
reports why it is not available, the way `Search.backend` reports which search
engine answered. An IDE that will not open because a 3GB checkpoint failed to
download is a worse IDE.
"""

from __future__ import annotations
import json, threading
from fastcore.all import L

from . import errstr

__all__ = ['MAX_TOOL_CHARS', 'WRITE_TOOLS', 'ide_tools', 'system_prompt', 'confirm_writes', 'Assistant',
           'COMPLETE_SP', 'Completer']

MAX_TOOL_CHARS = 6000     # per tool result; the context window is the scarce resource here
MAX_HITS = 20

# The tools that change something on disk. Named as a set because that is the line a
# confirmation policy needs to draw -- see `confirm_writes`.
WRITE_TOOLS = frozenset({'edit_file', 'create_file', 'edit_cell', 'add_cell'})


def _clip(s, n=MAX_TOOL_CHARS):
    s = str(s)
    return s if len(s) <= n else s[:n] + f'\n…[{len(s)-n} more chars]'


def _arg_path(args):
    "The `path` argument of a tool call, whether the model sent a dict or a JSON string."
    if isinstance(args, str):
        try: args = json.loads(args)
        except Exception: return None
    return args.get('path') if isinstance(args, dict) else None


def _cmds(commands):
    """Parse exhash commands from what a tool call can carry.

    Models emit JSON, exhash wants tuples: `[["12|a1b2|","s","old","new"]]` becomes
    `[("12|a1b2|","s","old","new")]`. Nested command tuples (`g`/`v`) recurse.
    """
    if isinstance(commands, str): commands = json.loads(commands)
    if not isinstance(commands, list): raise ValueError('commands must be a JSON list of command arrays')
    def _t(c):
        if not isinstance(c, (list, tuple)): raise ValueError(f'each command must be an array, got {type(c).__name__}')
        return tuple(_t(x) if isinstance(x, (list, tuple)) else x for x in c)
    return [_t(c) for c in commands]


def system_prompt(ws):
    """The agent's briefing: what it is, where it is, and how to edit.

    exhash ships its own command reference as a module docstring, so that is quoted
    verbatim rather than paraphrased -- a paraphrase would drift from the parser.
    """
    try:
        import exhash.skill as sk
        edit_ref = sk.__doc__ or ''
    except Exception:
        edit_ref = ''
    roots = '\n'.join(f'  {r}' for r in ws.fs.roots) or '  (no folder open)'
    return f"""You are the assistant inside leela, a Python IDE. You are working in these folders:
{roots}

You can search the code index (the repo *and* installed packages), read the web,
edit files, and run Python in the user's live kernel namespace.

How to work:
- Before writing code that uses a library, `search_code` for it. The index covers
  installed packages, so prior art usually already exists in the environment.
- Prefer `view_file` over guessing. Its output doubles as the address book for edits.
- To change a file: `view_file` it, then `edit_file` with addresses from that view.
  Work bottom-to-top when making several structural edits in one call.
- `run_python` shares the user's kernel namespace. Read anything; bind results to NEW
  names. You cannot rebind or delete the user's variables, so do not try.
- Use `web_search`/`read_url` when the answer depends on current documentation.
- Paths must be inside the folders above. Anything else is refused.

## Editing reference (exhash)

{edit_ref}"""


def ide_tools(ws, session=None):
    """Every tool the agent gets, bound to one `Workspace`.

    Plain functions with type hints and docstrings: that is Rishi's tool contract, and
    it is why these read as documentation rather than as schema declarations.
    """
    fs, search = ws.fs, ws.search

    def _p(path):
        "Resolve a path through the sandbox, so no tool can address anything outside it."
        return fs._check(path)

    # -- seeing the code ---------------------------------------------------
    def search_code(query: str) -> str:
        """Search the codebase and every installed package for `query`.

        Semantic when the code index is built, a literal scan otherwise. Use this before
        writing anything non-trivial: the answer is usually already in the environment.
        """
        hits = search.search(query, limit=MAX_HITS)
        if not hits: return f'no matches ({search.backend}: {search.note})'
        rows = [f'{h.path}:{h.line}  {h.symbol or ""}  {h.text}' for h in hits]
        return _clip(f'[{search.backend}] ' + (search.note or '') + '\n' + '\n'.join(rows))

    def similar_code(path: str, line: int = 1) -> str:
        "Find code shaped like the function at `path`:`line` -- every place a pattern was already used."
        hits = search.peers(str(_p(path)), int(line), limit=MAX_HITS)
        if not hits: return f'nothing similar ({search.note})'
        return _clip('\n'.join(f'{h.path}:{h.line}  {h.symbol or ""}  {h.text}' for h in hits))

    def outline(path: str) -> str:
        "The defs and classes in one file, with line numbers."
        syms = search.symbols(str(_p(path)))
        if not syms: return f'no symbols in {path}'
        return _clip('\n'.join(f'{int(s.score)*" "}{s.line}: {s.symbol}' for s in syms))

    def list_files(pattern: str = '') -> str:
        "Files in the open folders, optionally filtered by a substring of the path."
        ps = fs.walk()
        if pattern: ps = ps.filter(lambda p: pattern.lower() in str(p).lower())
        return _clip('\n'.join(str(p) for p in ps[:400]) or 'no matching files')

    # -- reading and editing files ----------------------------------------
    def view_file(path: str, start: int = 0, end: int = 0) -> str:
        """Read a file as `lineno|hash|content` lines. Optionally limit to lines `start`..`end`.

        Always read this way before editing: `edit_file` addresses lines by the exact
        hashes this returns, so the view is also the address book.
        """
        from exhash import lnhashview_file
        p = _p(path)
        if not p.exists(): return f'no such file: {p}'
        return _clip(str(lnhashview_file(str(p), start or None, end or None)))

    def edit_file(path: str, commands: str) -> str:
        """Edit a file with hash-verified exhash commands, and return the diff.

        `commands` is a JSON array of command arrays, each starting with an address taken
        from `view_file`, e.g.
          [["12|a1b2|", "s", "old text", "new text"],
           ["30|9f3c|", "a", "a new line appended after line 30"]]
        Every address's hash is checked immediately before it runs, so an edit built on a
        stale view fails instead of damaging the wrong line. Nothing is written unless
        every command succeeds.
        """
        from exhash import file_exhash
        p = _p(path)
        try: cmds = _cmds(commands)
        except Exception as e: return f'could not parse commands: {errstr(e)}'
        if not cmds: return 'no commands given'
        try: return _clip(str(file_exhash(str(p), *cmds)))
        except Exception as e: return f'edit failed: {errstr(e)}'

    def create_file(path: str, text: str = '') -> str:
        "Create (or overwrite) a whole file. For changes to an existing file prefer `edit_file`."
        try: return f'wrote {fs.write(path, text).path}'
        except Exception as e: return f'write failed: {errstr(e)}'

    # -- notebooks ---------------------------------------------------------
    def notebook_cells(path: str) -> str:
        "List a notebook's cells: id, type, and first line. Cell ids are what `edit_cell` addresses."
        from .nb import Notebook
        try: nb = Notebook.load(_p(path))
        except Exception as e: return f'could not read notebook: {errstr(e)}'
        rows = [f'{c.id}  {c.cell_type:8} {(c.source.strip().split(chr(10)) or [""])[0][:100]}' for c in nb.cells]
        return _clip('\n'.join(rows) or '(empty notebook)')

    def view_cell(path: str, cell_id: str) -> str:
        "Read one notebook cell as `lineno|hash|content` lines, ready to address with `edit_cell`."
        from exhash import lnhashview_cell
        try: return _clip(str(lnhashview_cell(str(_p(path)), cell_id)))
        except Exception as e: return f'could not read cell: {errstr(e)}'

    def edit_cell(path: str, cell_id: str, commands: str) -> str:
        "Edit one notebook cell's source with exhash commands from `view_cell`. Same format as `edit_file`."
        from exhash import cell_exhash
        try: cmds = _cmds(commands)
        except Exception as e: return f'could not parse commands: {errstr(e)}'
        try: return _clip(str(cell_exhash(str(_p(path)), cell_id, *cmds)))
        except Exception as e: return f'edit failed: {errstr(e)}'

    def add_cell(path: str, source: str, index: int = -1, cell_type: str = 'code') -> str:
        "Insert a new cell into a notebook at `index` (-1 appends). Creates the notebook if needed."
        from .nb import Notebook, Cell
        try:
            p = _p(path)
            nb = Notebook.load(p) if p.exists() else Notebook.blank(p)
            c = nb.insert(len(nb) if index < 0 else int(index), Cell(source=source, cell_type=cell_type))
            # `Notebook.blank` seeds one empty cell so a human always has somewhere to type.
            # Filling a notebook by tool call does not need that, and leaving it behind means
            # every agent-created notebook opens with a stray blank cell at the top.
            if len(nb) == 2 and not nb[0].source.strip() and nb[1] is c: nb.delete(0)
            nb.save(p, sandbox=fs)
            return f'added cell {c.id} to {p}'
        except Exception as e: return f'could not add cell: {errstr(e)}'

    # -- the web -----------------------------------------------------------
    def web_search(query: str) -> str:
        "Search the web. Returns titles and urls; follow up with `read_url` on the useful ones."
        docs = ws.research.search(query, n=MAX_HITS)
        if not docs: return f'no results ({ws.research.note})'
        return _clip('\n'.join(f'{d.title}\n  {d.url}' for d in docs))

    def read_url(url: str) -> str:
        "Read one web page (or GitHub file, or arxiv paper) as markdown."
        d = ws.research.read(url)
        return _clip(d.text if d else f'could not read {url} ({ws.research.note})')

    def research(query: str) -> str:
        "Search the web and read the top results into one cited digest. Slower than `web_search`; use for depth."
        _, digest = ws.research.dig(query)
        return _clip(digest or f'nothing found ({ws.research.note})')

    # -- the terminal ------------------------------------------------------
    def read_terminal(lines: int = 200) -> str:
        """Read what the IDE's terminal has printed -- a failing build, a stack trace, a test run.

        This is *read only*: it shows what the user ran, and cannot run anything. Use it
        when they mention an error they are looking at rather than asking them to paste it.
        """
        terms = ws.terms.all()
        if not terms: return 'no terminal is open in the IDE'
        parts = [f'--- terminal {t.pid} ({" ".join(t.argv)}) ---\n{t.text(lines)}' for t in terms]
        return _clip('\n\n'.join(parts).strip() or 'the terminal has printed nothing yet')

    tools = [search_code, similar_code, outline, list_files,
             view_file, edit_file, create_file,
             notebook_cells, view_cell, edit_cell, add_cell,
             web_search, read_url, research, read_terminal]
    if session is not None:
        from dhrishti.agent import agent_tools
        tools += list(agent_tools(session))
    return tools


def confirm_writes(ask):
    """A Rishi approval policy that waves through reads and puts every write to `ask`.

    Rishi approves every tool call when no policy is given. That is the right default
    for a chat with read-only tools and the wrong one here, where four of them change
    files. `ask(tool_call) -> bool` is the frontend's confirmation prompt.

    Worth knowing what already stands between a bad edit and a damaged file, so the
    prompt is a third line of defence rather than the only one: every path is resolved
    through `Sandbox`, so nothing outside the open folders is reachable at all; and
    exhash verifies each addressed line's hash immediately before writing, so an edit
    built on a stale read fails instead of landing on the wrong line.
    """
    from rishi.core import hitl_policy
    return hitl_policy({t: 'check' for t in WRITE_TOOLS}, ask=ask)


class Assistant:
    """The IDE's Rishi chat, built on first use and allowed to be unavailable.

    Loading is deferred and failure is reported rather than raised, for the same reason
    the code index is: the model is a multi-gigabyte download, and an editor must open
    without it. `ready` and `note` are what the frontends display.

    `approve` is passed straight to Rishi: `None` keeps Rishi's own behaviour (every
    call runs), and `confirm_writes(ask)` makes the writing tools ask first.
    """

    def __init__(self, ws, session=None, model_id=None, sp=None, approve=None):
        self.ws, self.session, self.model_id, self._sp = ws, session, model_id, sp
        self.approve = approve
        self.calls = L()        # (tool, args) per call this session -- what the UI shows as activity
        self.before = {}        # path -> its text just before a write tool touched it, this turn
        self.chat = None
        self._tried = False
        self.note = 'assistant not started'
        # One engine, one generation at a time. Held here rather than inside `ask` because
        # `Completer` shares this engine and needs to *see* that a turn is in flight, so it
        # can decline instead of queueing behind a tool loop the user is watching.
        self.lock = threading.Lock()

    @property
    def ready(self): return self.chat is not None

    @property
    def busy(self): return self.lock.locked()

    @property
    def tools(self): return ide_tools(self.ws, self.session)

    def start(self):
        "Build the chat, once. Returns it, or None with `note` explaining why not."
        if self._tried: return self.chat
        self._tried = True
        try:
            from rishi.core import Chat
            kw = {'model_id': self.model_id} if self.model_id else {}
            tools = self.tools
            self.chat = Chat(sp=self._sp or system_prompt(self.ws), tools=tools,
                             approve=self.approve, tool_max_len=MAX_TOOL_CHARS, **kw)
            self.chat.add_cb(self._logger())
            self.note = f'{len(tools)} tools'
        except Exception as e:
            self.note = f'assistant unavailable ({errstr(e)})'
        return self.chat

    def _logger(self):
        """Record every tool call, and snapshot any file a write tool is about to touch.

        The snapshot has to happen *here* because this is the last moment the `before`
        still exists -- by the time the turn returns, every edit has landed. It is what
        lets `changes()` report the diff of what the assistant actually did, rather than
        repeating the model's own account of what it did.
        """
        from rishi.core import ChatCallback
        calls, before, read = self.calls, self.before, self.ws.text_at
        class ToolLog(ChatCallback):
            def before_tool_calls(self):
                fn = (self.chat.turn_tc or {}).get('function', {})
                name, args = fn.get('name', '?'), fn.get('arguments', {})
                calls.append((name, args))
                # first touch only: later edits in the same turn are part of one change
                if name in WRITE_TOOLS and (p := _arg_path(args)) and p not in before:
                    before[p] = read(p) or ''
        return ToolLog()

    def changes(self):
        """`{path: (before, after)}` for every file this turn's write tools actually moved.

        A tool that reported success but changed nothing does not appear here, which is
        the whole point: this is the file, not the claim about the file.
        """
        out = {}
        for p, was in self.before.items():
            now = self.ws.text_at(p)
            if now is not None and now != was: out[p] = (was, now)
        return out

    def retry(self):
        "Forget a previous failure, so a model that has since downloaded can be picked up."
        self._tried, self.chat = False, None
        return self.start()

    def ask(self, prompt):
        "One turn. Returns the assistant's text, or the reason there isn't any."
        c = self.start()
        if c is None: return self.note
        # Cleared in place, not rebound: the tool-log callback closed over this dict.
        self.before.clear()                 # `changes()` reports this turn, not the session
        with self.lock:
            try:
                from rishi.core import resp_text
                return resp_text(c(prompt)) or '(no reply)'
            except Exception as e:
                self.note = f'assistant failed ({errstr(e)})'
                return self.note

    def ask_with(self, prompt, context='', screen='', image=None):
        """One turn, with whatever the frontend can supply attached: the notebook above the
        question, a captured screen as text, and a captured screen as a picture.

        `image` is raw PNG bytes and goes in as a *content part* rather than as a tool
        result: rishi's `mk_msg` turns a list into parts and `mk_content` recognises image
        bytes, so this is the supported path to a multimodal turn. It also puts the
        picture where it belongs -- alongside the question asked about it, instead of
        behind a tool the model has to think to call.

        `screen` is the terminal frontend's equivalent, and stays text on purpose: a
        terminal screen is a grid of characters, so sending it as prose is both exact and
        far cheaper than a rendering of it would be.
        """
        parts = []
        if context: parts.append(f'<notebook>\n{context}\n</notebook>')
        if screen: parts.append(f'<screen>\n{screen}\n</screen>')
        parts.append(prompt)
        ask = '\n\n'.join(parts)
        return self.ask([image, ask] if image else ask)

    def close(self):
        if self.chat is not None:
            try: self.chat.close()
            except Exception: pass
            self.chat = None


# ---------------------------------------------------------------------------
# inline completion
# ---------------------------------------------------------------------------
COMPLETE_SP = """You are a code completion engine inside an editor. You are given the code before \
the cursor in <before> and the code after it in <after>.

Reply with ONLY the code that belongs at the cursor. No explanation, no markdown fence, no \
repetition of <before> or <after>. Keep it short -- finish the current expression, statement or \
short block and stop. Match the surrounding indentation and style exactly. If nothing sensible \
belongs there, reply with nothing at all."""

MAX_COMPLETION_LINES = 4     # a suggestion longer than this is a guess about the design, not a completion
COMPLETION_TOKENS = 96
CTX_BEFORE, CTX_AFTER = 2000, 600   # chars of surrounding code sent as context


def _strip_echo(before, out):
    "Drop a re-emitted tail of `before` from the front of `out` -- models like to restate the line they continue."
    tail = before[-200:]
    for n in range(len(tail), 0, -1):
        if out.startswith(tail[-n:]): return out[n:]
    return out


def _clean(text, before, max_lines):
    """A raw model reply as something safe to insert: fences off, echo off, `max_lines` long.

    `fenced_blocks` rather than rishi's `extract_code` because it takes any fence, not
    only a ```python one -- a completion model asked for bare code and fencing it anyway
    rarely bothers with an info string. It also keeps this function testable without a
    model installed.
    """
    from fastcore.xtras import fenced_blocks
    out = (blocks[-1][1] if (blocks := fenced_blocks(text or '')) else text) or ''
    out = _strip_echo(before, out.strip('\n'))
    lines = out.split('\n')[:max_lines]
    while lines and not lines[-1].strip(): lines.pop()
    return '\n'.join(lines)


class Completer:
    """Inline code completion from the same local model the assistant runs on.

    The engine is the expensive part -- gigabytes, loaded once -- so this does not build
    its own. It borrows the `Assistant`'s and opens a *throwaway* conversation per
    request, which is what keeps a completion stateless: a suggestion is a question about
    the code on screen, not a turn in a conversation, and letting suggestions accumulate
    would poison the assistant's context as well as their own.

    One engine means one generation at a time, so a completion asked for while the
    assistant is mid-turn declines immediately instead of queueing behind a tool loop.
    "The model is thinking" is a better answer than an editor that stops taking keys.

    Nothing here is automatic. The kernel's own completions (`Kernel.complete`) are
    instant and correct and stay bound to typing; this costs a forward pass, so it fires
    only when asked for -- and the first ask loads the model, exactly as the first
    question to the assistant does.
    """

    def __init__(self, assistant, max_lines=MAX_COMPLETION_LINES, max_tokens=COMPLETION_TOKENS):
        self.a, self.max_lines, self.max_tokens = assistant, max_lines, max_tokens
        self.note = 'not asked yet'

    @property
    def ready(self): return self.a.ready

    def _prompt(self, code, pos, lang):
        return (f'Language: {lang}\n\n<before>\n{code[:pos][-CTX_BEFORE:]}\n</before>\n'
                f'<after>\n{code[pos:][:CTX_AFTER]}\n</after>')

    def complete(self, code, pos, lang='python'):
        "The text to insert at `pos` in `code`, or `''` with `note` saying why there isn't any."
        chat = self.a.start()
        if chat is None:
            self.note = self.a.note
            return ''
        if not self.a.lock.acquire(blocking=False):
            self.note = 'model busy — the assistant is mid-turn'
            return ''
        try:
            from rishi.core import mk_msg, resp_text
            with chat.engine.create_conversation(
                    messages=[{'role': 'system', 'content': COMPLETE_SP}]) as conv:
                text = resp_text(conv.send_message(mk_msg(self._prompt(code, pos, lang)),
                                                   max_output_tokens=self.max_tokens))
        except Exception as e:
            self.note = f'completion failed ({errstr(e)})'
            return ''
        finally:
            self.a.lock.release()
        out = _clean(text, code[:pos], self.max_lines)
        self.note = f"{len(out.split(chr(10)))} line(s) from the model" if out else 'no suggestion'
        return out
