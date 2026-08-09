"""The hands: what the application under the agent must provide, and every tool built on top of it.

## The host

`Host` is the application under an agent, as an interface. Every method may raise, and
the tools catch rather than let an exception end a turn. A capability that cannot be
supported raises `NotImplementedError`, which `tools_for` reads as "do not offer this tool"
-- an agent told about a tool that always fails is worse off than one never told about it.

`NullHost` is a host with nothing behind it, and it is the reference implementation of
"absent" -- the harness runs bare on it, which is how the probing in `tools_for` gets
tested without a real application.

## Skills

A skill is know-how the agent can read on demand: a package that documents itself, or a
`SKILL.md` file in a repository. Only names and one-line descriptions go in the system
prompt; the bodies are fetched by the `read_skill` tool, which is what keeps a dozen skills
affordable.

Skills come from installed packages (the `pyskills` entry-point group) and from
`<name>/SKILL.md` directories. The precedence is deliberate: a file beats a package,
because the package's skill is the general advice and the one in your own repository is
the correction.

`skill_index` is what goes in the system prompt, and `find` is how `read_skill` resolves
what the model asked for.

## Extensions

An extension is a Python file the user drops in a directory. `Registry` is everything it
is handed: tools, skills, slash commands, lifecycle hooks and the approval policy. What is
deliberately absent is any route to a backend's internals -- an extension that pokes at a
litert conversation would break on the next model switch, and break silently.

## Tool plumbing

Three things every tool shares: a clip, because the context window is the scarce resource;
a parser for the hash-verified edit commands models emit as JSON; and a probe that asks a
host whether a capability exists. `WRITE_TOOLS` names the tools that change something,
which is the line an approval policy draws.

## Seeing the code

The first group any host gets: search the index, find code shaped like a given function,
outline a file, list the files. Every result names the exact path and how to address it,
because a model that has to guess whether something is a notebook will guess wrong.

## Files

Files are read and written by hash-verified address. `view_file` returns
`lineno|hash|content` lines, and those hashes are the addresses `edit_file` takes -- so the
view is also the address book, and an edit built on a stale view fails instead of damaging
the wrong line.

## Notebooks

The harness deliberately does not own a notebook representation: exhash addresses cells by
path and id without one, so only the two operations that genuinely need to know what a
notebook *is* are delegated to the host.

## The web and remembered research

Two groups, and the split matters: the web tools go out now, while the memory tools recall
pages read earlier as whole document sections. A question that was researched last week
should cost a memory search rather than another crawl.

## The live session

The user's kernel, and the terminal they are looking at. `run_python` lands in their
namespace and is a write tool; `inspect_python` cannot change anything and is not, which is
why the briefing tells the model to reach for it first. `read_terminal` is read-only by
construction: it shows what the user ran and cannot run anything.

## Skills as tools

`read_skill` is what makes the index in the system prompt affordable: names and
descriptions go out with every turn, bodies only when asked for. `create_skill` writes a
project-local `SKILL.md`, and never overwrites one.

## Assembling the tool list

`tools_for` probes each group with a harmless call and drops the whole group when the host
does not implement it. Whole groups rather than individual tools, because the groups are the
real units of capability: a host with no notebook representation cannot support any of the
four notebook tools.

## Sub-agents

Delegation is a context strategy, not a speed one. A broad question that takes twenty tool
calls to answer costs the caller one question and one answer, because the sub-agent's
working is discarded with its conversation. A sub-agent gets read-only tools, and cannot
delegate further: recursion here is a fan-out tree whose width nobody chose.

`delegate` runs one question in a throwaway conversation on the same engine, and closes it
in a `finally` -- a sub-agent whose context leaks back into the session is just a slower way
of doing the work inline.

The tools themselves take callables rather than a backend, so a model switch mid-session is
picked up -- the tool the model is holding must not be pinned to whichever backend happened
to be current when the list was built.
"""


__all__ = ['GROUP', 'EXTRA_MODULES', 'MAX_SKILL_CHARS', 'EVENTS', 'MAX_TOOL_CHARS', 'MAX_HITS', 'MAX_GREP_HITS',
           'WRITE_TOOLS', 'ERR', 'SUB_MAX_STEPS', 'SUB_SP', 'NO_SUB', 'Hit', 'Host', 'NullHost', 'Skill',
           'skill_dirs', 'discover', 'skill_index', 'find', 'Registry', 'ext_dirs', 'load', 'clip', 'clip_lines',
           'err', 'failed', 'code_tools', 'file_tools', 'notebook_tools', 'web_tools', 'memory_tools',
           'session_tools', 'shell_tools', 'skill_tools', 'tools_for', 'read_only', 'delegate', 'delegate_many',
           'subagent_tools']

import functools, json, re, runpy, threading
from dataclasses import dataclass, field
from pathlib import Path
from fastcore.docments import frontmatter
from .core import agent_err

class Hit:
    "One search result, in the shape every backend of `Host.search` returns."
    def __init__(self, path, line=1, symbol='', text=''):
        self.path, self.line, self.symbol, self.text = path, line, symbol, text
    def __repr__(self): return f'{self.path}:{self.line}  {self.symbol}  {self.text}'

class Host:
    """The application under an agent.

    Every method may raise; the tools in `tools.py` catch and report rather than let an
    exception end a turn. Methods that cannot be supported should raise
    `NotImplementedError`, which the tool list reads as "do not offer this tool" -- an
    agent told about a tool that always fails is worse off than one never told about it.
    """

    # -- where it is allowed to be -------------------------------------------
    @property
    def roots(self):
        "The open folders, as absolute paths. The agent is told about these and confined to them."
        raise NotImplementedError

    def check(self, path, must_exist=False):
        """Resolve `path` and refuse anything outside `roots`, returning a `Path`.

        This is the single chokepoint. exhash and fossick both write to disk on their own
        account, so each is handed a path this has already approved rather than a path the
        model supplied. Every other method here may assume its argument came through here.
        """
        raise NotImplementedError

    def walk(self):
        "Every readable file under the open folders."
        raise NotImplementedError

    def read(self, path):
        "One file's text, or None when it cannot be read."
        raise NotImplementedError

    def write(self, path, text):
        "Write `text` to `path`, through the same sandbox `check` enforces. Returns the path written."
        raise NotImplementedError

    def text_at(self, path):
        """One file as a single diffable document, `''` when it does not exist yet, None on error.

        Distinct from `read` because a notebook diffs as cell sources rather than as
        nbformat JSON, and because a file the agent is about to create must diff as a pure
        addition instead of as an error. This is what `Agent.changes()` compares.
        """
        raise NotImplementedError

    # -- seeing the code -----------------------------------------------------
    def search(self, query, limit=20):
        "Search the code index for `query`, returning `Hit`s. Semantic if an index exists, literal if not."
        raise NotImplementedError

    def peers(self, path, line, limit=20):
        "Code shaped like whatever is defined at `path`:`line` -- every place a pattern was already used."
        raise NotImplementedError

    def symbols(self, path):
        "The defs and classes in one file, as `Hit`s whose `score` is the indent depth."
        raise NotImplementedError

    @property
    def search_note(self):
        "Which engine answered, and anything it wants to say about why. Shown when a search finds nothing."
        return ''

    # -- reading the web -----------------------------------------------------
    def web_search(self, query, n=20):
        "Search the web; returns objects with `.title` and `.url`."
        raise NotImplementedError

    def read_url(self, url, remember=True):
        "One page as markdown; `remember=False` keeps sensitive/low-quality results ephemeral."
        raise NotImplementedError

    def research(self, query):
        "Search and read the top results into one cited digest. Slower than `web_search`."
        raise NotImplementedError

    @property
    def research_note(self): return ''

    # -- durable research memory --------------------------------------------
    def memory_search(self, query, limit=8):
        "Search remembered pages as whole tree sections, returning structured rows."
        raise NotImplementedError

    def memory_tree(self, document=''):
        "The heading tree for remembered documents; an empty document lists every root."
        raise NotImplementedError

    def memory_read(self, node_id):
        "Read one remembered section and its children by stable node id."
        raise NotImplementedError

    def memory_topics(self, limit=12):
        "Labelled semantic clusters across remembered research."
        raise NotImplementedError

    def memory_forget(self, doc_id):
        "Purge one remembered document and all derived tree/chunk/vector data."
        raise NotImplementedError

    # -- notebooks -----------------------------------------------------------
    # The harness deliberately does not own a notebook representation. exhash addresses
    # cells by path and id without one, so only the two operations that genuinely need to
    # know what a notebook *is* are delegated here.
    def nb_cells(self, path):
        "`[(id, cell_type, first_line)]` for one notebook."
        raise NotImplementedError

    def nb_add_cell(self, path, source, index=-1, cell_type='code'):
        "Insert a cell (-1 appends), creating the notebook if needed. Returns the new cell's id."
        raise NotImplementedError

    # -- the live session ----------------------------------------------------
    def run_python(self, code):
        """Run `code` in the user's live namespace under whatever restrictions the host imposes.

        The contract the agent is briefed on: read anything, bind results to new names,
        never rebind or delete the owner's. Enforcing it is the host's job -- the harness
        only promises to tell the model about it.
        """
        raise NotImplementedError

    def inspect_python(self, code, scope='isolated'):
        """Run `code` against the live namespace without touching what the user has.

        Two scopes, and the difference is the interpreter you get rather than the safety you
        get -- both protect the owner's variables, by different means:

        - `'isolated'` runs in an allowlist sandbox on a *copy*. Attribute reads and builtins
          work; most library method calls are refused. Nothing can reach the real namespace
          at all, which is why it is the default and why it needs no trust.
        - `'overlay'` runs the real interpreter against the real namespace under an AST
          policy: the agent may read anything and bind its own names, which persist in its
          own layer, and cannot delete, rebind in place, or mutate the owner's. `list(df.columns)`
          and `df.head().to_dict()` work here; in the sandbox they do not.

        A host may refuse `'overlay'` (see `scopes`) and fall back to isolated, which is what
        a locked-down deployment does. Under a concurrent kernel either scope runs *alongside*
        a busy cell rather than queueing behind it.
        """
        raise NotImplementedError

    @property
    def scopes(self):
        "The scopes `inspect_python` will actually honour, most trusted last."
        return ('isolated',)

    @property
    def kernel_kind(self):
        """What runs the live namespace, and whether it can execute concurrently.

        `'ipymini'` means an inspection can run while a cell is busy; anything else means
        it queues behind whatever the kernel is already doing. The agent is told which,
        because "read the dataframe" is good advice under one and a way to hang the session
        under the other.
        """
        return 'ipykernel'

    @property
    def concurrent(self): return self.kernel_kind == 'ipymini'

    def list_vars(self):
        "What is in the live namespace: name, type, and a short value, one per line."
        raise NotImplementedError

    def terminal_text(self, lines=200):
        "What the IDE's terminal has printed. Read-only: this shows what the user ran, it cannot run anything."
        raise NotImplementedError

    # -- running a command ---------------------------------------------------
    def run_cmd(self, command, cwd=None, timeout=120):
        """Run `command` in a shell and return `(exit_code, combined_output)`.

        This is the capability the harness went longest without, and its absence was the
        single biggest reason the loop did not converge: an agent that can edit but cannot
        run `pytest` has no way to find out whether the edit was right, so it reports
        success instead of checking. Everything else here answers questions about the
        code; this is the only thing that can contradict the model.

        Contract a host must keep, because the tool trusts it:

        - `cwd` is resolved through `check`, so a command cannot be started outside the
          open folders. Confining the *working directory* is not confining the command --
          a shell can still name any path -- which is exactly why `run_shell` is in
          `WRITE_TOOLS` and goes to a person for approval.
        - stdout and stderr come back interleaved, in one string, as the person would see
          them. A failing test is its traceback; splitting the streams loses the order.
        - `timeout` is enforced and the whole process *group* is killed on expiry, or a
          hung `pytest -f` keeps a worker forever.
        - It returns a non-zero exit code rather than raising. A failed command is a
          result, not an exception; the model needs to read it.
        - An **empty** command is a no-op returning `(0, '')` and must not spawn anything.
          That is how `tools_for` asks "can you run commands?" without running one.
        """
        raise NotImplementedError

    @property
    def shell_note(self):
        "How commands are run here (the interpreter, the default directory), or why they are not."
        return ''

    # -- the person ----------------------------------------------------------
    @property
    def approvals(self):
        "The `Approvals` this host uses to put a write in front of a person, or None to approve everything."
        return None

    def note(self, text):
        "Tell the user something out of band (a status line). Never blocks; a host may drop it."
        pass

class NullHost(Host):
    "A host with nothing behind it: every capability absent, so the harness runs bare in a test."

    def __init__(self, roots=()): self._roots = [str(r) for r in roots]

    @property
    def roots(self): return self._roots

    def check(self, path, must_exist=False):
        from pathlib import Path
        return Path(path)

    def walk(self): return []
    def read(self, path): return None
    def write(self, path, text): raise NotImplementedError
    def text_at(self, path): return None
    def search(self, query, limit=20): return []
    def peers(self, path, line, limit=20): return []
    def symbols(self, path): return []
    def web_search(self, query, n=20): return []
    def read_url(self, url, remember=True): return None
    def research(self, query): return ''
    def memory_search(self, query, limit=8): raise NotImplementedError
    def memory_tree(self, document=''): raise NotImplementedError
    def memory_read(self, node_id): raise NotImplementedError
    def memory_topics(self, limit=12): raise NotImplementedError
    def memory_forget(self, doc_id): raise NotImplementedError
    def nb_cells(self, path): raise NotImplementedError
    def nb_add_cell(self, path, source, index=-1, cell_type='code'): raise NotImplementedError
    def run_python(self, code): raise NotImplementedError
    def inspect_python(self, code, scope='isolated'): raise NotImplementedError
    def list_vars(self): raise NotImplementedError
    def terminal_text(self, lines=200): raise NotImplementedError
    def run_cmd(self, command, cwd=None, timeout=120): raise NotImplementedError

GROUP,EXTRA_MODULES,MAX_SKILL_CHARS = 'pyskills',('exhash.skill',),20_000

def _describe(text, mx=300):
    'A one-line description from a skill body: its first paragraph, collapsed.'
    body = (text or '').strip()
    if not body: return ''
    para = body.split('\n\n', 1)[0]
    one = ' '.join(para.split())
    return one if len(one) <= mx else one[:mx - 1].rstrip() + '…'

@dataclass
class Skill:
    'One skill: how to name it, when it applies, and how to get the whole text.'
    name: str
    source: str                   # 'pyskill' | 'md'
    description: str = ''
    where: str = ''               # module path or file path, shown so a person can go read it
    _text: object = field(default=None, repr=False)

    def text(self):
        'The full skill body, clipped. Never raises: a broken skill reports itself as one.'
        try: t = self._text() if callable(self._text) else (self._text or '')
        except Exception as e: return f'could not read skill {self.name}: {agent_err(e)}'
        t = str(t)
        return t if len(t) <= MAX_SKILL_CHARS else t[:MAX_SKILL_CHARS] + f'\n…[{len(t)-MAX_SKILL_CHARS} more chars]'

    def dict(self): return {'name': self.name, 'source': self.source,'description': self.description, 'where': self.where}

def _mod_skill(name, modpath):
    "A `Skill` for a module, without importing it until someone asks for the body."
    def load():
        from importlib import import_module
        return import_module(modpath).__doc__ or ''
    # The description does need the docstring, and there is no way to read one without
    # importing. Failing quietly is right: a package whose import breaks should cost the
    # agent one missing skill, not a session.
    try:
        from importlib import import_module
        doc = import_module(modpath).__doc__ or ''
    except Exception:
        return None
    if not doc.strip(): return None
    return Skill(name=name, source='pyskill', description=_describe(doc), where=modpath, _text=load)

def _pyskills():
    "Every module published under the `pyskills` entry-point group, plus the known stragglers."
    out, seen = [], set()
    try:
        from importlib.metadata import entry_points
        eps = list(entry_points(group=GROUP))
    except Exception:
        eps = []
    for ep in eps:
        mod = getattr(ep, 'value', None) or ep.name
        if mod in seen: continue
        seen.add(mod)
        if (s := _mod_skill(ep.name.split('.')[-1] or ep.name, mod)): out.append(s)
    for mod in EXTRA_MODULES:
        if mod in seen: continue
        seen.add(mod)
        if (s := _mod_skill(mod.split('.')[0], mod)): out.append(s)
    return out

def skill_dirs(roots=(), cfg=None):
    """Where SKILL.md files are looked for, in increasing precedence.

    User directories first so a project can override a personal skill of the same name --
    which is the way round that matters, since the project is the shared thing and the
    personal one is the habit.
    """
    from pathlib import Path
    ds = []
    if cfg is not None: ds.append(Path(cfg)/'skills')
    ds.append(Path.home()/'.agents'/'skills')
    for r in roots: ds += [Path(r)/'.leela'/'skills', Path(r)/'.agents'/'skills']
    return ds

def _md_skills(d):
    "Skills in one directory, following the Agent Skills layout: `<name>/SKILL.md`."
    from pathlib import Path
    d = Path(d)
    if not d.is_dir(): return []
    out = []
    for p in sorted(d.iterdir()):
        if not p.is_dir(): continue
        f = p/'SKILL.md'
        if not f.exists(): continue
        try: raw = f.read_text(encoding='utf-8')
        except Exception: continue
        meta, body = frontmatter(raw)
        out.append(Skill(name=meta.get('name') or p.name, source='md',
                         description=meta.get('description') or _describe(body),
                         where=str(f), _text=body))
    return out

def discover(roots=(), cfg=None, extra=()):
    """Every skill available to this agent, later sources winning on a name clash.

    Order is pyskills, then each skill directory in `skill_dirs` order, then `extra` (what
    an extension registered). A file beats a package deliberately: the package's skill is
    the general advice, and the one you wrote in your own repository is the correction.
    """
    by_name = {}
    for s in _pyskills(): by_name[s.name] = s
    for d in skill_dirs(roots, cfg):
        for s in _md_skills(d): by_name[s.name] = s
    for s in extra or (): by_name[s.name] = s
    return sorted(by_name.values(), key=lambda s: s.name)

SKILL_DESC_MAX = 160   # per skill, so one verbose description cannot crowd out the rest

def _clip(s, n=SKILL_DESC_MAX):
    """One line, clipped at a word boundary.

    Descriptions are written to be *found* — some enumerate every trigger word their author
    could think of, running to a thousand characters. In the index they only have to be
    distinguishable enough to pick, since `read_skill` then supplies the whole text.
    """
    s = ' '.join(str(s).split())
    if len(s) <= n: return s
    cut = s.rfind(' ', 0, n)
    return s[:cut if cut > 0 else n].rstrip(' .,;:—-') + '…'

def skill_index(skills):
    "The block that goes in the system prompt: names and clipped descriptions, never bodies."
    if not skills: return ''
    rows = '\n'.join(f'- `{s.name}` — {_clip(s.description)}' for s in skills)
    return ('\n\n## Skills\n\nKnow-how available to you. Read one with `read_skill(name)` when its '
            'description matches what you are about to do, *before* you do it — several of these '
            'describe tools already installed in this environment, so the code they discuss is '
            'also searchable with `search_code`.\n\n' + rows)

def find(skills, name):
    """A skill by exact name, then by unique prefix, then by unique substring.

    Ambiguity returns None rather than a guess. A model that asked for `edit` and silently
    got `editskill` will read the wrong reference and then confidently do the wrong thing,
    which is worse than being told to be specific.
    """
    if not name: return None
    n = name.strip().lower()
    if (exact := [s for s in skills if s.name.lower() == n]): return exact[0]
    for pred in (lambda s: s.name.lower().startswith(n), lambda s: n in s.name.lower()):
        if len(hits := [s for s in skills if pred(s)]) == 1: return hits[0]
    return None

EVENTS = ('before_turn', 'after_turn', 'before_tool', 'after_tool', 'compact', 'approval')

class Registry:
    """What `setup(ext)` is handed: everything an extension may add, and nothing else.

    `host` and `agent` are exposed because an extension that cannot read a file or see the
    conversation is not worth writing. What is deliberately *not* here is any way to reach
    a backend's internals -- an extension that pokes at a litert conversation would break
    on the next model switch, and would break silently.
    """

    def __init__(self, host=None, agent=None):
        self.host, self.agent = host, agent
        self.tools, self.skills, self.commands = [], [], {}
        self.hooks = {e: [] for e in EVENTS}
        self.approve = None
        self.notes = []          # one line per extension: loaded, or why not

    # -- registration --------------------------------------------------------
    def tool(self, f):
        """Add a tool. Usable as a decorator.

        The contract is the backends' own: a plain function with type hints and a
        docstring. That docstring is what the model reads, so it is documentation and not
        a comment.
        """
        self.tools.append(f)
        return f

    def skill(self, name, text, description=''):
        "Add a skill the discovery pass would not find -- a file, a string, anything callable."
        s = Skill(name=name, source='ext', description=description or _describe(text if isinstance(text, str) else ''),
                  where='extension', _text=text)
        self.skills.append(s)
        return s

    def command(self, name, fn, help=''):
        "Add a slash command. `fn(agent, arg)` returns text for the frontend to show."
        self.commands[name.lstrip('/')] = (fn, help)
        return fn

    def on(self, event, fn):
        "Hook a harness lifecycle event. Unknown event names are an error, not a silent no-op."
        if event not in EVENTS: raise KeyError(f'unknown event {event!r}; known: {", ".join(EVENTS)}')
        self.hooks[event].append(fn)
        return fn

    def approval(self, fn):
        "Replace the approval policy wholesale. The last extension to call this wins."
        self.approve = fn
        return fn

    # -- dispatch ------------------------------------------------------------
    def fire(self, event, *args, **kw):
        "Run every hook for `event`, swallowing failures. Returns how many ran cleanly."
        n = 0
        for f in self.hooks.get(event, ()):
            try: f(*args, **kw); n += 1
            except Exception as e: self.notes.append(f'{event} hook failed: {agent_err(e)}')
        return n

def ext_dirs(roots=(), cfg=None, project=False):
    "Where extensions are looked for. Project directories only when explicitly allowed."
    ds = []
    if cfg is not None: ds.append(Path(cfg)/'extensions')
    if project:
        for r in roots: ds.append(Path(r)/'.leela'/'extensions')
    return ds


def load(reg, roots=(), cfg=None, project=False, paths=()):
    """Run every extension found, calling its `setup(reg)`. Returns the registry.

    A file with no `setup` is loaded and left alone rather than reported as broken: that is
    how a shared helper module sitting in the same directory should behave.
    """
    files = []
    for d in ext_dirs(roots, cfg, project):
        if Path(d).is_dir(): files += sorted(p for p in Path(d).glob('*.py') if not p.name.startswith('_'))
    for p in paths or ():
        p = Path(p)
        files += sorted(p.glob('*.py')) if p.is_dir() else [p]
    for f in files:
        try:
            ns = runpy.run_path(str(f))
        except Exception as e:
            reg.notes.append(f'{f.name}: failed to load ({agent_err(e)})')
            continue
        fn = ns.get('setup')
        if not callable(fn):
            reg.notes.append(f'{f.name}: loaded, no setup()')
            continue
        before = (len(reg.tools), len(reg.skills), len(reg.commands))
        try: fn(reg)
        except Exception as e:
            reg.notes.append(f'{f.name}: setup() failed ({agent_err(e)})')
            continue
        d = [n - b for n, b in zip((len(reg.tools), len(reg.skills), len(reg.commands)), before)]
        reg.notes.append(f'{f.name}: {d[0]} tool(s), {d[1]} skill(s), {d[2]} command(s)')
    return reg

# How many chars one tool result may spend, by default. Deliberately small: this is a
# budget against the *smallest* model the harness runs, and an on-device model with a
# 16k window is spent by three generous results. A host that knows it is talking to a
# large-context model raises it -- `Agent(tool_max_len=…)`, threaded into `tools_for`.
MAX_TOOL_CHARS = 6000
MAX_HITS = 20
MAX_GREP_HITS = 60

# The tools that change something on disk, in the live session, or on the machine. Named
# as a set because that is the line an approval policy needs to draw -- see `Approvals`.
WRITE_TOOLS = frozenset({'edit_file', 'replace_text', 'create_file', 'edit_cell', 'add_cell', 'run_python',
                         'run_shell', 'memory_forget', 'create_skill'})

# Every tool failure starts with this. A tool result is just text to the engines underneath
# us -- neither rishi nor fastllm carries an `is_error` flag through to the model -- so the
# flag has to be *in* the text, spelled the same way every time. That is what lets the
# activity feed mark a call as failed, `Agent.problems` collect them, and the model tell
# "the file says X" apart from "I could not read the file".
ERR = 'ERROR: '


def err(what, e=None):
    "One tool failure, spelled the way every other tool spells it."
    return f'{ERR}{what}' + (f': {agent_err(e)}' if e is not None else '')


def failed(result):
    "Whether a tool result is a failure. The one place that knows how a failure is spelled."
    return str(result or '').startswith(ERR)


def clip(s, n=MAX_TOOL_CHARS, more=''):
    """Truncate a tool result to `n` chars, saying how to get the rest.

    Truncation happens here rather than in the context window because a tool result goes
    straight back into the prompt, so the tokens are cheaper to not spend than to spend.
    But a truncated result the model cannot *resume* is a dead end: it will either invent
    the remainder or call the same tool again and get the same first half. So a caller
    with a way to continue passes it as `more`, and it is included in the notice.
    """
    s = str(s)
    if len(s) <= n: return s
    cut = s[:n]
    nl = cut.rfind('\n')                    # never end mid-line: the line would look complete
    if nl > n * 0.6: cut = cut[:nl]
    note = f'[truncated: {len(cut)} of {len(s)} chars shown'
    return cut + f'\n…{note}. {more}]' if more else cut + f'\n…{note}]'


def clip_lines(lines, start=1, n=MAX_TOOL_CHARS, more='', empty='(nothing)'):
    """Render `lines` within the budget, and say which line to resume from.

    The line-oriented half of `clip`. It counts what it dropped rather than describing it
    in characters, because everything that produces lines here -- a file view, a grep, a
    directory -- is resumed by *line or offset*, not by character.
    """
    lines = list(lines)
    if not lines: return empty
    out, used = [], 0
    for i, line in enumerate(lines):
        line = str(line)
        if used + len(line) + 1 > n and out:
            rest = len(lines) - i
            tail = f'\n…[{rest} more line(s) not shown'
            hint = more.format(next=start + i) if '{next}' in more else more
            return '\n'.join(out) + (f'{tail}. {hint}]' if hint else f'{tail}]')
        out.append(line); used += len(line) + 1
    return '\n'.join(out)


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


def _edits(edits):
    """Parse `replace_text`'s edits from what a tool call can carry.

    Models send this three ways and all three are unambiguous, so all three are accepted:
    a JSON string, a list of `{'oldText','newText'}` dicts, or a list of `[old, new]`
    pairs. Rejecting a shape a model reliably produces buys nothing -- it just costs a
    turn to a message that says "send it the other way".
    """
    if isinstance(edits, str): edits = json.loads(edits)
    if isinstance(edits, dict): edits = [edits]
    if not isinstance(edits, (list, tuple)): raise ValueError('edits must be a JSON array')
    out = []
    for e in edits:
        if isinstance(e, dict):
            if 'oldText' not in e or 'newText' not in e:
                raise ValueError("each edit needs 'oldText' and 'newText'")
            out.append((str(e['oldText']), str(e['newText'])))
        elif isinstance(e, (list, tuple)) and len(e) == 2: out.append((str(e[0]), str(e[1])))
        else: raise ValueError('each edit must be {"oldText":…,"newText":…} or [old, new]')
    return out


def _apply_edits(text, edits):
    """Apply exact-text edits to `text`, or raise saying which one is wrong and why.

    Everything is located against the *original* text first, and only then applied. That
    ordering is the whole design: it is what makes the operation atomic, what lets
    overlap be detected at all, and what means a model whose third edit is stale does not
    have to work out what its first two did to the file.
    """
    spans = []
    for i, (old, new) in enumerate(edits, 1):
        if not old: raise ValueError(f'edit {i}: oldText is empty; use create_file to write a whole file')
        n = text.count(old)
        if n == 0:
            raise ValueError(f'edit {i}: oldText not found. It must match the file exactly, '
                             f'including indentation. Re-read the file and try again')
        if n > 1:
            raise ValueError(f'edit {i}: oldText matches {n} places. Include more surrounding '
                             f'lines so it matches exactly one')
        at = text.index(old)
        spans.append((at, at + len(old), new, i))
    spans.sort()
    for (s1, e1, _, i1), (s2, _, _, i2) in zip(spans, spans[1:]):
        if s2 < e1: raise ValueError(f'edits {i1} and {i2} overlap; merge them into one edit')
    out, at = [], 0
    for s, e, new, _ in spans:
        out.append(text[at:s]); out.append(new); at = e
    out.append(text[at:])
    return ''.join(out)


def _diff(before, after, path='file'):
    "A unified diff, which is what a person approving an edit should be looking at."
    import difflib
    d = difflib.unified_diff(before.splitlines(), after.splitlines(),
                             f'a/{path}', f'b/{path}', lineterm='', n=2)
    return '\n'.join(d)


def _probe(host, *calls):
    "Whether every one of `calls` is supported. A host says 'no' by raising `NotImplementedError`."
    for f in calls:
        try: f()
        except NotImplementedError: return False
        except Exception: pass
    return True


def _supports(host, name):
    """Whether `host` implements `name`, without calling it.

    Every other capability here is probed by making a harmless call. `run_cmd` has no
    harmless call -- running a command is the side effect -- so this one is answered by
    asking whether the host overrode the method at all.

    Not calling it also means this cannot detect a host that overrides the method and then
    refuses anyway, so `run_cmd`'s contract closes that: an empty command is a no-op that
    returns `(0, '')`, and a host that cannot run commands raises `NotImplementedError`
    from it like any other absent capability.
    """
    own, base = getattr(type(host), name, None), getattr(Host, name, None)
    if own is None or own is base: return False
    try: host.run_cmd('')
    except NotImplementedError: return False
    except Exception: pass
    return True

def code_tools(host, mx=MAX_TOOL_CHARS):
    "Seeing the code: the index, the shapes in it, and the files it covers."

    def search_code(query: str) -> str:
        """Search the codebase and every installed package for `query`.

        Semantic when the code index is built, a literal scan otherwise. Use this before
        writing anything non-trivial: the answer is usually already in the environment.
        """
        hits = host.search(query, limit=MAX_HITS)
        if not hits: return f'no matches ({host.search_note})'
        rows = []
        for h in hits:
            target = (f'NOTEBOOK — use this exact path with notebook_cells, then view_cell/edit_cell'
                      if str(h.path).lower().endswith('.ipynb')
                      else 'FILE — use this exact path with view_file/edit_file')
            rows.append(f'{h.path}:{h.line}  {h.symbol or ""}  {h.text}\n  {target}')
        return clip(f'[{host.search_note}]\n' + '\n'.join(rows), mx)

    def similar_code(path: str, line: int = 1) -> str:
        "Find code shaped like the function at `path`:`line` -- every place a pattern was already used."
        hits = host.peers(str(host.check(path)), int(line), limit=MAX_HITS)
        if not hits: return f'nothing similar ({host.search_note})'
        return clip('\n'.join(f'{h.path}:{h.line}  {h.symbol or ""}  {h.text}' for h in hits), mx)

    def outline(path: str) -> str:
        "The defs and classes in one file, with line numbers."
        syms = host.symbols(str(host.check(path)))
        if not syms: return f'no symbols in {path}'
        return clip('\n'.join(f'{int(getattr(s, "score", 0))*" "}{s.line}: {s.symbol}' for s in syms), mx)

    def list_files(pattern: str = '') -> str:
        "Files in the open folders, optionally filtered by a substring of the path."
        ps = [str(p) for p in host.walk()]
        if pattern: ps = [p for p in ps if pattern.lower() in p.lower()]
        return clip_lines(ps, n=mx, more='narrow `pattern`', empty='no matching files')

    def grep(pattern: str, path_filter: str = '', regex: bool = True, ignore_case: bool = False) -> str:
        """Find every line in the open folders matching `pattern`, exactly.

        The literal counterpart to `search_code`, and not a replacement for it. Use
        `search_code` for "how does this work" -- it is a semantic index and it covers
        installed packages. Use `grep` when you know the string: a symbol you are about to
        rename, an error message, an import, a call site you must not miss. An index answers
        with what is *like* the query; this answers with what *is* the query, which is what
        a rename or an audit needs.

        `path_filter` is a substring of the path (`tests/`, `.py`). Set `regex=False` to
        match `pattern` literally when it contains regex punctuation.
        """
        if not str(pattern or '').strip(): return err('grep needs a pattern')
        flags = re.IGNORECASE if ignore_case else 0
        try: rx = re.compile(pattern if regex else re.escape(pattern), flags)
        except re.error as e: return err('bad pattern', e)
        pf, hits, scanned, capped = str(path_filter or '').lower(), [], 0, False
        for p in host.walk():
            sp = str(p)
            if pf and pf not in sp.lower(): continue
            try: text = host.read(sp)
            except Exception: continue
            if not text: continue
            scanned += 1
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f'{sp}:{i}: {line.strip()[:200]}')
                    if len(hits) >= MAX_GREP_HITS: capped = True; break
            if capped: break
        if not hits: return f'no matches for {pattern!r} in {scanned} file(s)'
        head = f'{len(hits)}{"+" if capped else ""} match(es) in {scanned} file(s) searched'
        return clip_lines([head] + hits, n=mx, more='narrow `pattern` or set `path_filter`')

    def ls(path: str = '') -> str:
        """List one directory: its subdirectories, then its files with sizes.

        For finding your way around. `list_files` walks everything and `grep` reads
        everything; this just says what is here, which is usually the cheaper question.
        Empty `path` lists each open folder.
        """
        roots = [host.check(path)] if str(path or '').strip() else [host.check(r) for r in host.roots]
        out = []
        for d in roots:
            if not d.exists(): out.append(f'{d}: does not exist'); continue
            if d.is_file(): out.append(f'{d}  ({d.stat().st_size} bytes, a file)'); continue
            try: kids = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except Exception as e: out.append(err(f'cannot list {d}', e)); continue
            out.append(f'{d}/')
            for k in kids:
                if k.name.startswith('.') and k.name not in ('.agents', '.leela'): continue
                try: out.append(f'  {k.name}/' if k.is_dir() else f'  {k.name}  {k.stat().st_size}')
                except Exception: out.append(f'  {k.name}')
        return clip_lines(out, n=mx, more='name a subdirectory to list it', empty='(nothing)')

    return [search_code, grep, ls, similar_code, outline, list_files]

def file_tools(host, mx=MAX_TOOL_CHARS):
    "Reading and editing files, always by hash-verified address."

    def view_file(path: str, start: int = 0, end: int = 0) -> str:
        """Read a file as `lineno|hash|content` lines. Optionally limit to lines `start`..`end`.

        Always read this way before editing: `edit_file` addresses lines by the exact
        hashes this returns, so the view is also the address book.
        """
        from exhash import lnhashview_file
        p = host.check(path)
        if not p.exists(): return err(f'no such file: {p}')
        view = str(lnhashview_file(str(p), start or None, end or None))
        return clip_lines(view.splitlines(), start=(start or 1), n=mx,
                          more='call view_file(path, start={next}) to continue')

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
        p = host.check(path)
        try: cmds = _cmds(commands)
        except Exception as e: return err('could not parse commands', e)
        if not cmds: return err('no commands given')
        try: return clip(str(file_exhash(str(p), *cmds)), mx)
        except Exception as e: return err('edit failed', e)

    def replace_text(path: str, edits: str) -> str:
        """Edit a file by exact text replacement, and return the diff. Usually the easier editor.

        `edits` is a JSON array of objects, applied together:
          [{"oldText": "def old(a):", "newText": "def new(a, b):"},
           {"oldText": "return a", "newText": "return a + b"}]

        Rules, all of them checked *before* anything is written, so a rejected edit leaves
        the file exactly as it was:

        - Every `oldText` must appear **exactly once** in the file. If it appears twice,
          include more surrounding lines until it is unique -- do not guess which one.
        - Every `oldText` is matched against the file as it is **now**, not against the
          result of the earlier edits in the same call. Overlapping or nested spans are
          refused; merge them into one edit instead.
        - Keep `oldText` as short as it can be while still unique. Do not paste a whole
          function to change one line of it.
        - An empty `oldText` is refused. To create a file use `create_file`; to append,
          include the last existing line in `oldText`.

        This and `edit_file` do the same job by different addresses: `edit_file` names
        lines by hash, which catches a stale read but costs a `view_file` before every
        edit and again after each one. Prefer this for ordinary edits; prefer `edit_file`
        when you must be certain the line you are changing is the line you read.
        """
        p = host.check(path)
        try: items = _edits(edits)
        except Exception as e: return err('could not parse edits', e)
        if not items: return err('no edits given')
        try: before = host.read(str(p))
        except Exception as e: return err(f'could not read {p}', e)
        if before is None: return err(f'no such file: {p}. Use create_file to create it')
        try: after = _apply_edits(before, items)
        except ValueError as e: return err(str(e))
        if after == before: return err('the edits changed nothing; check oldText against a fresh view_file')
        try: host.write(str(p), after)
        except Exception as e: return err('write failed', e)
        return clip(f'replaced {len(items)} block(s) in {p}\n' + _diff(before, after, str(p)), mx)

    def create_file(path: str, text: str = '') -> str:
        "Create (or overwrite) a whole file. For changes to an existing file prefer `replace_text`."
        try: return f'wrote {host.write(path, text)}'
        except Exception as e: return err('write failed', e)

    return [view_file, replace_text, edit_file, create_file]

def notebook_tools(host, mx=MAX_TOOL_CHARS):
    "Notebooks, addressed by cell id rather than by line."

    def notebook_cells(path: str) -> str:
        "List a notebook's cells: id, type, and first line. Cell ids are what `edit_cell` addresses."
        try: rows = host.nb_cells(str(host.check(path)))
        except NotImplementedError: raise
        except Exception as e: return f'could not read notebook: {agent_err(e)}'
        return clip('\n'.join(f'{i}  {t:8} {(s or "").strip().splitlines()[0][:100] if (s or "").strip() else ""}'
                              for i, t, s in rows) or '(empty notebook)', mx)

    def view_cell(path: str, cell_id: str) -> str:
        "Read one notebook cell as `lineno|hash|content` lines, ready to address with `edit_cell`."
        from exhash import lnhashview_cell
        try: return clip(str(lnhashview_cell(str(host.check(path)), cell_id)), mx)
        except Exception as e: return f'could not read cell: {agent_err(e)}'

    def edit_cell(path: str, cell_id: str, commands: str) -> str:
        "Edit one notebook cell's source with exhash commands from `view_cell`. Same format as `edit_file`."
        from exhash import cell_exhash
        try: cmds = _cmds(commands)
        except Exception as e: return f'could not parse commands: {agent_err(e)}'
        try: return clip(str(cell_exhash(str(host.check(path)), cell_id, *cmds)), mx)
        except Exception as e: return f'edit failed: {agent_err(e)}'

    def add_cell(path: str, source: str, index: int = -1, cell_type: str = 'code') -> str:
        "Insert a new cell into a notebook at `index` (-1 appends). Creates the notebook if needed."
        try: return f'added cell {host.nb_add_cell(str(host.check(path)), source, int(index), cell_type)} to {path}'
        except NotImplementedError: raise
        except Exception as e: return f'could not add cell: {agent_err(e)}'

    return [notebook_cells, view_cell, edit_cell, add_cell]

def web_tools(host, mx=MAX_TOOL_CHARS):
    "The web, for the questions whose answer depends on current documentation."

    def web_search(query: str) -> str:
        "Search the web. Returns titles and urls; follow up with `read_url` on the useful ones."
        docs = host.web_search(query, n=MAX_HITS)
        if not docs: return f'no results ({host.research_note})'
        return clip('\n'.join(f'{d.title}\n  {d.url}' for d in docs), mx)

    def read_url(url: str, remember: bool = True) -> str:
        """Read one web page (or GitHub file, arxiv paper) as markdown.

        It enters durable research memory by default. Pass `remember=False` for sensitive,
        obviously irrelevant, or exploratory results that should remain ephemeral.
        """
        d = host.read_url(url, remember=remember)
        return clip(d.text if d else f'could not read {url} ({host.research_note})', mx)

    def research(query: str) -> str:
        "Search the web and read the top results into one cited digest. Slower than `web_search`; use for depth."
        return clip(host.research(query) or f'nothing found ({host.research_note})', mx)

    return [web_search, read_url, research]

def memory_tools(host, mx=MAX_TOOL_CHARS):
    "Durable pages and research recalled as document sections rather than flat snippets."

    def memory_search(query: str, limit: int = 8) -> str:
        """Search pages remembered from earlier reads and research.

        Returns whole operative sections with breadcrumbs plus related semantic paths. Use
        this before searching the live web when the question may have been researched before.
        """
        try: return clip(json.dumps(host.memory_search(query, int(limit)), default=str), mx * 2)
        except Exception as e: return f'memory search failed: {agent_err(e)}'

    def memory_tree(document: str = '') -> str:
        """Browse remembered document headings without embedding a query.

        `document` may be a title substring or stable document id. Leave it empty to list
        all remembered roots, then call again with the relevant document.
        """
        try: return clip(json.dumps(host.memory_tree(document), default=str), mx * 2)
        except Exception as e: return f'memory tree failed: {agent_err(e)}'

    def memory_read(node_id: str) -> str:
        "Read one whole remembered section by the node id returned by memory_search/tree."
        try: return clip(json.dumps(host.memory_read(node_id), default=str), mx * 3)
        except Exception as e: return f'memory read failed: {agent_err(e)}'

    def memory_topics(limit: int = 12) -> str:
        "Map remembered material into labelled semantic clusters and representative members."
        try: return clip(json.dumps(host.memory_topics(int(limit)), default=str), mx * 2)
        except Exception as e: return f'memory topics failed: {agent_err(e)}'

    def memory_forget(doc_id: str) -> str:
        """Purge one bad, sensitive, stale or irrelevant remembered document by id.

        This removes its tree, chunks and ANN entries. Use only when the user requests it;
        do not silently curate their memory.
        """
        try: return 'forgot document' if host.memory_forget(doc_id) else 'document was not forgotten'
        except Exception as e: return f'memory purge failed: {agent_err(e)}'

    return [memory_search, memory_tree, memory_read, memory_topics, memory_forget]

def session_tools(host, mx=MAX_TOOL_CHARS):
    "The live kernel the user is working in, and the terminal they are looking at."

    def list_vars() -> str:
        "List the variables visible in the user's live session: name, type, and a short value."
        return clip(host.list_vars() or '(empty session)', mx)

    def run_python(code: str) -> str:
        """Run Python in the user's live kernel namespace.

        Read any variable freely; bind results to NEW names so they survive to the next
        call. Mutating or deleting the user's variables is refused -- rebind instead
        (`df2 = df.drop(...)`). Call `list_vars` first if you do not know what is there.
        """
        try: return clip(host.run_python(code), mx)
        except NotImplementedError: raise
        except Exception as e: return f'run failed: {agent_err(e)}'

    def inspect_python(code: str, scope: str = 'isolated') -> str:
        """Look at the user's live variables by running Python that cannot change them.

        Two scopes. Both leave the user's variables exactly as they were; they differ in
        how much Python you get, so pick by what the question needs:

        - `scope='isolated'` (default) runs in an allowlist sandbox on a copy. Attribute
          reads and builtins work — `df.shape`, `len(df)`, `type(x).__name__` — and most
          library method calls are refused. Costs nothing to be wrong about.
        - `scope='overlay'` runs the real interpreter against the real namespace. Library
          calls work: `list(df.columns)`, `df.head(3).to_dict()`, `model.summary()`. Names
          you bind persist into your own layer for later calls. You still cannot delete,
          rebind or mutate anything the user made — that is refused, with an explanation.

        Start isolated; move to overlay when the sandbox refuses something you need. Neither
        needs approval, and both run while one of the user's cells is still going. For work
        that must land in the *user's* namespace, use `run_python` instead.
        """
        try: return clip(host.inspect_python(code, scope=scope), mx)
        except NotImplementedError: raise
        except Exception as e: return f'inspection failed: {agent_err(e)}'

    def read_terminal(lines: int = 200) -> str:
        """Read what the IDE's terminal has printed -- a failing build, a stack trace, a test run.

        This is *read only*: it shows what the user ran, and cannot run anything. Use it
        when they mention an error they are looking at rather than asking them to paste it.
        """
        return clip(host.terminal_text(int(lines)) or 'the terminal has printed nothing yet', mx)

    return [list_vars, run_python, inspect_python, read_terminal]

def shell_tools(host, mx=MAX_TOOL_CHARS):
    "Running a command, which is the only way to find out whether the work is done."

    def run_shell(command: str, cwd: str = '', timeout: int = 120) -> str:
        """Run one shell command in the project and return its exit code and output.

        This is how you check your work, and you are expected to use it: after an edit, run
        the tests; after a change to a signature, run the type checker or the linter the
        project already uses; before saying something passes, make it pass here. A claim
        with no command behind it is a guess, and will be read as one.

        - stdout and stderr come back interleaved, as a person would see them, with the
          exit code on the first line. A non-zero exit is a *result*: read the output and
          fix the cause, do not run it again unchanged.
        - `cwd` defaults to the first open folder and must stay inside the open folders.
        - `timeout` is in seconds; the command is killed when it expires. Do not start
          servers, watchers, REPLs, or anything else that does not exit on its own.
        - Use the project's own commands -- the ones in its README, `pyproject.toml`, or
          `Makefile` -- rather than a global tool that may not be what it uses.
        - This may be put to the user for approval, so send one purposeful command rather
          than a chain of exploratory ones.
        """
        cmd = str(command or '').strip()
        if not cmd: return err('no command given')
        try: code, out = host.run_cmd(cmd, cwd=(str(cwd).strip() or None), timeout=int(timeout))
        except NotImplementedError: raise
        except Exception as e: return err('command could not be run', e)
        head = f'exit {code}' + ('' if code == 0 else '  (command FAILED)')
        body = clip((out or '').rstrip() or '(no output)', mx - 200,
                    more='re-run narrowing the command (a single test, `| tail -50`) rather than repeating it')
        return f'{head}\n{body}' if code == 0 else f'{ERR}{head}\n{body}'

    return [run_shell]

def skill_tools(host, get_skills, mx=MAX_TOOL_CHARS):
    "Reading discovered skills and creating project-local Agent Skills."

    def read_skill(name: str) -> str:
        """Read one skill in full: how to use a tool or a library that is already installed here.

        The skill list in your briefing gives names and one-line descriptions. Read the
        matching one *before* doing the work it describes, not after it has gone wrong.
        """
        ss = get_skills()
        s = find(ss, name)
        if s is None:
            return f'no skill matching {name!r}. Available: ' + ', '.join(x.name for x in ss)
        return clip(f'<skill name="{s.name}" from="{s.where}">\n{s.text()}\n</skill>', mx * 3)

    def create_skill(name: str, description: str, instructions: str) -> str:
        """Create a reusable project skill at `.agents/skills/NAME/SKILL.md`.

        Use this only when the user asks to preserve repeatable project know-how as a
        skill, not for ordinary task notes. `name` must be lowercase kebab-case;
        `description` says when it applies; `instructions` is the complete Markdown body.
        Existing skills are never overwritten. Run `/reload` after creation to make the
        current agent advertise it immediately.
        """
        from pathlib import Path
        name = str(name or '').strip()
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name):
            return 'skill name must be lowercase kebab-case (for example, notebook-tests)'
        if not str(description or '').strip(): return 'skill description is required'
        if not str(instructions or '').strip(): return 'skill instructions are required'
        roots = list(host.roots or ())
        if not roots: return 'open a project folder before creating a skill'
        target = Path(host.check(Path(roots[0])/'.agents'/'skills'/name/'SKILL.md'))
        exists = target.exists()
        if not exists:
            try: exists = host.read(str(target)) is not None
            except Exception: pass
        if exists: return f'refusing to overwrite existing skill: {target}'
        title = json.dumps(name, ensure_ascii=False)
        desc = json.dumps(' '.join(str(description).split()), ensure_ascii=False)
        text = f'---\nname: {title}\ndescription: {desc}\n---\n\n{str(instructions).strip()}\n'
        try: host.write(str(target), text)
        except Exception as e: return f'could not create skill: {agent_err(e)}'
        return f'created {target}; run /reload to load it into the current agent'

    return [read_skill, create_skill]

def tools_for(host, get_skills=None, extra=(), mx=MAX_TOOL_CHARS):
    """Every tool this host can actually support, plus whatever extensions registered.

    Each group is probed with a harmless call and dropped whole if the host does not
    implement it. Whole groups rather than individual tools because the groups are the
    real units of capability: a host with no notebook representation cannot support any of
    the four notebook tools, and one with no kernel cannot support any of the session ones.

    `mx` is what one tool result may spend. It belongs here rather than in each tool
    because it is a property of the *model* the results are going to, not of the tool: the
    same `view_file` that should return 300 lines to a frontier model has to return 60 to
    an on-device one, and getting that wrong is not a formatting problem -- a turn whose
    tool results overflow a 16k window fails outright.
    """
    tools = []
    tools += code_tools(host, mx)
    tools += file_tools(host, mx)
    if _probe(host, lambda: host.nb_cells('.')): tools += notebook_tools(host, mx)
    if _probe(host, lambda: host.web_search('', n=1)): tools += web_tools(host, mx)
    if _probe(host, lambda: host.memory_tree('')): tools += memory_tools(host, mx)
    if _probe(host, lambda: host.list_vars(), lambda: host.terminal_text(1)): tools += session_tools(host, mx)
    if _supports(host, 'run_cmd'): tools += shell_tools(host, mx)
    if get_skills is not None: tools += skill_tools(host, get_skills, mx)
    tools += list(extra or ())
    return tools

SUB_MAX_STEPS = 12

SUB_SP = """You are a research sub-agent inside a Python IDE. Another agent has delegated one \
question to you because answering it takes many tool calls and the answer is short.

- Answer exactly the question asked. Nothing else.
- Use your tools as much as you need; nobody is paying attention to how many calls it takes.
- Report what you found, with file paths and line numbers, not what you infer or expect.
- If the answer is that there is nothing, say so plainly. A confident wrong answer is far \
worse than "no matches, and here is what I searched for".
- You cannot edit anything. If the answer implies a change, describe the change and stop.
- `inspect_python` answers questions about the user's live variables without changing them. \
Its default scope is a sandbox that refuses most library calls; pass `scope='overlay'` to \
get the real interpreter. Use it rather than guessing at what is in memory."""


# A sub-agent does not get to spawn sub-agents. Not a safety rule so much as an economic
# one: recursion here is a fan-out tree whose width nobody chose, and the second level
# never has enough context to ask a good question anyway.
NO_SUB = frozenset({'delegate_search', 'delegate_parallel'})

def read_only(tools, max_calls=None):
    "The read-only tools a sub-agent may have, optionally behind a hard per-task call budget."
    allowed = [t for t in tools if getattr(t, '__name__', '') not in (WRITE_TOOLS | NO_SUB)]
    if max_calls is None: return allowed
    state, lock = {'n': 0}, threading.Lock()

    def guarded(f):
        @functools.wraps(f)
        def call(*args, **kw):
            with lock:
                state['n'] += 1
                over = state['n'] > max_calls
            if over:
                return ('Sub-agent tool budget exhausted. Stop calling tools and return the '
                        'best evidence-backed answer now.')
            return f(*args, **kw)
        return call
    return [guarded(t) for t in allowed]

def delegate(backend, question, tools=(), sp=SUB_SP, max_steps=SUB_MAX_STEPS):
    """Ask `question` in a throwaway conversation on `backend`'s engine. Returns the answer text.

    The conversation is closed in a `finally` because the whole benefit is that it does not
    outlive the question -- a sub-agent whose context leaks back into the session is just a
    slower way of doing the work inline.
    """
    sub = None
    try:
        # Native local engines own their internal tool loop, so the tool wrappers are the
        # backend-independent hard stop. Allow several parallel calls per logical round.
        sub = backend.spawn(sp=sp, tools=read_only(tools, max_calls=max_steps * 4))
        if hasattr(sub, 'max_steps'): sub.max_steps = max_steps
        return sub.send(question)
    except Exception as e:
        return f'delegation failed: {agent_err(e)}'
    finally:
        if sub is not None:
            try: sub.close()
            except Exception: pass

def delegate_many(backend, questions, tools=(), sp=SUB_SP, max_steps=SUB_MAX_STEPS, n_workers=4):
    """Ask several questions at once. Returns answers in the order the questions were given.

    Whether this is genuinely parallel depends on what is underneath, and it is worth being
    exact rather than optimistic:

    - **Generation** overlaps on a cloud backend, where each sub-agent is its own HTTP
      request. On a local engine it does not -- litert holds one conversation at a time --
      so local fan-out is run one after another rather than racing for the same engine and
      finding out what happens.
    - **Tool work** overlaps either way, and is usually the bulk of it: three sub-agents
      each doing six searches is eighteen searches, and they do not wait for each other.
      Under a concurrent kernel (`Host.kernel_kind == 'ipymini'`) that includes
      `inspect_python`, which is the case that used to be hopeless -- an inspection queued
      behind the user's running cell, and then behind the other two sub-agents' inspections.

    The point of the whole thing is context, not speed. Three questions answered in
    parallel cost the caller three short answers instead of sixty tool results.
    """
    qs = list(questions)
    if not qs: return []
    if len(qs) == 1 or getattr(backend.spec, 'local', False) or n_workers < 2:
        return [delegate(backend, q, tools, sp, max_steps) for q in qs]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(min(n_workers, len(qs))) as ex:
        return list(ex.map(lambda q: delegate(backend, q, tools, sp, max_steps), qs))

def subagent_tools(get_backend, get_tools):
    """The `delegate` tool, bound to whatever backend routing says sub-agents run on.

    Both arguments are callables so a model switch mid-session is picked up: the tool the
    model is holding must not be pinned to the backend that happened to be current when
    the tool list was built.
    """

    def delegate_search(question: str) -> str:
        """Hand a broad search question to a sub-agent and get back only its conclusion.

        Use this when answering would take many `search_code` / `view_file` / `read_url` /
        `inspect_python` calls whose results you do not need to keep -- "where else do we
        do X", "which files import Y", "what shape is everything in this namespace". The
        sub-agent has your read-only tools and none of your write tools, and its working is
        discarded, so the cost to your context is one question and one answer.

        Ask one self-contained question. The sub-agent cannot see this conversation.
        """
        b = get_backend()
        if b is None: return 'no model is available to delegate to'
        return clip(delegate(b, question, get_tools()), MAX_TOOL_CHARS)

    def delegate_parallel(questions: str) -> str:
        """Hand several independent questions to sub-agents at once, and get back every answer.

        `questions` is a JSON array of strings, e.g.
          ["which files import fastllm?", "where is compaction triggered?", "what is df's shape?"]

        Use it when you have two or more questions that do not depend on each other. They
        run concurrently, each in its own throwaway conversation with your read-only tools,
        so three questions cost you three short answers rather than the sixty tool results
        it would take to answer them yourself.

        Every question must be self-contained: a sub-agent cannot see this conversation or
        the other questions.
        """
        b = get_backend()
        if b is None: return 'no model is available to delegate to'
        try:
            qs = json.loads(questions) if isinstance(questions, str) else list(questions)
            if not isinstance(qs, list) or not all(isinstance(q, str) for q in qs):
                raise ValueError('expected a JSON array of strings')
        except Exception as e:
            return f'could not parse questions: {agent_err(e)}'
        if not qs: return 'no questions given'
        answers = delegate_many(b, qs, get_tools())
        return clip('\n\n'.join(f'### {q}\n{a}' for q, a in zip(qs, answers)), MAX_TOOL_CHARS * 2)

    return [delegate_search, delegate_parallel]
