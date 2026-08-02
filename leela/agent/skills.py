"""Skills, discovered rather than written.

`ai.system_prompt` has always pasted `exhash.skill.__doc__` into the briefing verbatim,
with a comment explaining that a paraphrase would drift from the parser. That instinct was
right and it was one package deep. This is the general version of it.

Two sources, because two conventions exist and both are good:

**pyskills.** `aidialog` and `aai-coding` publish this in their `pyproject.toml`:

    [project.entry-points.pyskills]
    "aidialog.dlgskill" = "aidialog.dlgskill"

A skill is a *module docstring*. That is a better idea than it first looks: the text lives
beside the functions it describes, it is versioned and released with them, `pip install -U`
updates it, and it cannot rot into describing an API that changed. `aidialog.dlgskill`'s
docstring is a fully-formed skill about editing notebooks -- so installing aidialog hands
this agent competent notebook editing with no code written here. That is the test of
whether this feature is real rather than architectural, and it passes.

**SKILL.md.** The Agent Skills layout everyone now uses -- `<dir>/<name>/SKILL.md` with
YAML frontmatter -- loaded from user and project directories in increasing precedence, so
a project can override a user skill of the same name. Taken from tau, including the
detail that a bare `.md` at the root of a skills directory is *not* a skill and should say
so rather than be silently ignored.

Only names and descriptions go in the system prompt; bodies come through the `read_skill`
tool. Tau is explicit about why and it is right: a dozen full skill texts would crowd out
the code the model is supposed to be looking at. In leela this compounds with something no
other harness has -- the code index covers installed packages, so a skill that mentions
`lnhashview_msg` is one `search_code` away from its implementation and every call site.
Elsewhere a skill is prose about code the agent cannot see.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field

from . import agent_err

__all__ = ['GROUP', 'EXTRA_MODULES', 'Skill', 'skill_dirs', 'discover', 'skill_index', 'find', 'frontmatter']

GROUP = 'pyskills'      # the entry-point group aidialog and aai-coding publish under

# Skills we know exist but whose packages do not publish the entry point yet. exhash's is
# the editing reference the agent cannot work without, and leela quoted it by hand long
# before this module existed; listing it here is how that hand-wiring retires.
EXTRA_MODULES = ('exhash.skill',)

MAX_SKILL_CHARS = 20_000    # a skill longer than this is documentation, and is clipped as such


def frontmatter(text):
    "`(metadata, body)` for a markdown file with optional YAML-ish frontmatter. No yaml dependency."
    if not text.startswith('---'): return {}, text
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n?(.*)$', text, re.DOTALL)
    if not m: return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ':' in line and not line.lstrip().startswith('#'):
            k, _, v = line.partition(':')
            meta[k.strip()] = v.strip().strip('"\'')
    return meta, m.group(2)


def _describe(text, mx=300):
    """A one-line description from a skill body: its first paragraph, collapsed.

    First *paragraph* rather than first line because a module docstring's opening line is
    often a title ("Read, search, and edit dialogs...") whose useful qualification is on
    the next line. A description that stops at the title is a description that never
    matches a task.
    """
    body = (text or '').strip()
    if not body: return ''
    para = body.split('\n\n', 1)[0]
    one = ' '.join(para.split())
    return one if len(one) <= mx else one[:mx - 1].rstrip() + '…'


@dataclass
class Skill:
    """One skill: how to name it, when it applies, and how to get the whole text.

    `text` is a callable and not a string. Reading every skill body at startup to build an
    index of one-liners would be exactly the waste this design exists to avoid -- and a
    pyskill body means importing its module, which for a package like pandas is seconds.
    """
    name: str
    source: str                   # 'pyskill' | 'md'
    description: str = ''
    where: str = ''               # module path or file path, shown so a person can go read it
    _text: object = field(default=None, repr=False)

    def text(self):
        "The full skill body, clipped. Never raises: a broken skill reports itself as one."
        try: t = self._text() if callable(self._text) else (self._text or '')
        except Exception as e: return f'could not read skill {self.name}: {agent_err(e)}'
        t = str(t)
        return t if len(t) <= MAX_SKILL_CHARS else t[:MAX_SKILL_CHARS] + f'\n…[{len(t)-MAX_SKILL_CHARS} more chars]'

    def dict(self): return {'name': self.name, 'source': self.source,
                            'description': self.description, 'where': self.where}


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------
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


def skill_index(skills):
    "The block that goes in the system prompt: names and descriptions, never bodies."
    if not skills: return ''
    rows = '\n'.join(f'- `{s.name}` — {s.description}' for s in skills)
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
