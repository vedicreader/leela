"Know-how Leela owns, and the push that hands it to an agent for as long as a mode is on."

from importlib import import_module
from shalya.skills import Skill

__all__ = ['NAMES', 'skill', 'push', 'drop', 'pushed']

#: Mode name -> module whose docstring is its body. Kept here, not in a `pyskills` entry point, so a canvas-only skill does not reach every agent.
NAMES = {'canvas': 'leela.skills.canvas'}

def _describe(text, mx=300):
    one = ' '.join((text or '').strip().split('\n\n', 1)[0].split())
    return one if len(one) <= mx else one[:mx - 1].rstrip() + '…'

def skill(name):
    "One of Leela's own skills, in the shape shalya's registry takes."
    body = import_module(NAMES[name]).__doc__ or ''
    return Skill(name=name, source='leela', description=_describe(body), where=NAMES[name], _text=body)

def pushed(agent): return {s.name for s in getattr(agent.registry, 'skills', [])}

def push(agent, *names):
    "Put Leela's skills on the agent's registry, and rebuild what reads them. Idempotent."
    fresh = [n for n in (names or NAMES) if n not in pushed(agent)]
    for n in fresh: agent.registry.skill(skill(n).name, skill(n)._text, skill(n).description)
    if fresh: agent._forget()
    return fresh

def drop(agent, *names):
    "Take them off again. What canvas mode does when it goes off."
    want = set(names or NAMES)
    keep = [s for s in agent.registry.skills if s.name not in want]
    gone = len(agent.registry.skills) - len(keep)
    if gone: agent.registry.skills[:] = keep; agent._forget()
    return gone
