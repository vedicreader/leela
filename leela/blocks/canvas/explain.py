"Drafting the prose a literate page needs. The rules are the installed writing skills."

from __future__ import annotations
from importlib.resources import files
from fastcore.all import L, Path

from .change import bundle_of, snip
from .context import Spec, body_text, render, resolve

__all__ = ['RULES', 'DRAFTED', 'rule_text', 'prompt_for', 'explain', 'drafted',
           'capture', 'replay']

#: The skills that set the register. A snippet caption is reference prose.
RULES = ('write_docs',)
#: What marks a body the model drafted, so a reviewer can tell the two apart.
DRAFTED = 'wrote'
#: How much of the section a prompt carries.
CONTEXT_BUDGET = 6000

def _asset(name): return files(__package__).joinpath(name).read_text(encoding='utf-8')

def rule_text(names=RULES):
    "The named skills, read from where they are installed. This package holds no copy of them."
    try: from shalya.skills import discover, find
    except ImportError as e:
        raise LookupError('shalya is not installed, so the skills cannot be read; pass `rules=`') from e
    found = discover()
    out = []
    for n in names:
        s = find(found, n)
        if s is None: raise LookupError(f'skill {n!r} is not installed; pass `rules=` instead')
        out.append(f'## {s.name}\n\n{s.text()}')
    return '\n\n'.join(out)

def _code(b, root):
    "What the prompt shows: the file a snippet cites, or the hunks a diff carries."
    return b.body if b.kind == 'diff' else snip(b, root)

def prompt_for(
    doc,               # the document
    bid,               # which brick to explain
    root='.',          # where a `snippet` brick's `path` is relative to
    sentences=3,       # how many sentences to ask for
    rules=None,        # the writing rules, else read from ramabana
    scope='region',    # how much of the document the prompt carries
):
    "The whole prompt for one brick."
    b = doc.by_id(bid)
    if b is None: raise KeyError(bid)
    goal = doc.goal_for(bid)
    change = bundle_of(doc, bid)
    ctx = render(resolve(doc, bid, Spec(scope=scope, budget=CONTEXT_BUDGET, goal=False)), doc)
    return _asset('explain.md').format(
        rules=rules if rules is not None else rule_text(),
        ste=_asset('ste.md').strip(),
        goal='\n'.join(x for x in [body_text(goal) if goal is not None else '',
                                   f'change: {change.title}' if change is not None else '',
                                   f'worth: {change.contributes}' if change and change.contributes else '']
                       if x),
        section=b.region, context=ctx or '(nothing else in this section yet)',
        path=b.attrs.get('path', ''),
        where=' '.join(f'{k}="{b.attrs[k]}"' for k in ('symbol', 'lines') if b.attrs.get(k)),
        code=_code(b, root), sentences=sentences)

def explain(
    doc,                          # the document, edited in place
    ask,                          # `ask(prompt, brick) -> str`, the host's model
    root='.',                     # where a `snippet` brick's `path` is relative to
    kinds=('snippet', 'diff'),    # which brick kinds to draft
    overwrite=False,              # redraft a brick that already has a body
    sentences=3,                  # how many sentences to ask for
    rules=None,                   # the writing rules, else read from the installed skills
    on=None,                      # called with each brick as it is drafted
):
    "Draft the missing prose into the document, and return the bricks it changed."
    rules = rules if rules is not None else rule_text()
    done = L()
    for b in doc.of(*kinds):
        if b.body.strip() and not overwrite: continue
        if not _code(b, root).strip(): continue
        text = str(ask(prompt_for(doc, b.id, root, sentences, rules), b) or '').strip()
        if not text: continue
        b.body = text
        b.attrs[DRAFTED] = 'ai'
        done.append(b)
        if on: on(b)
    return done

def drafted(doc):
    "Every brick whose body the model wrote, for a reviewer who wants to read those first."
    return L(b for b in doc.bricks if b.attrs.get(DRAFTED) == 'ai')

def capture(path):
    "An `ask` that writes each prompt out and answers nothing. For a model that is not here."
    import json
    out = {}
    def ask(prompt, brick):
        out[brick.id] = prompt
        Path(path).write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding='utf-8')
        return ''
    return ask

def replay(path):
    "An `ask` that answers from a file of `{brick id: sentences}`. What a model already said."
    import json
    said = json.loads(Path(path).read_text(encoding='utf-8'))
    return lambda prompt, brick: said.get(brick.id, '')
