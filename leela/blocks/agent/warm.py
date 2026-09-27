"dhrona in the agent pane: which rounds fit this conversation's tools, why the rest did not, and the capture → review → accept loop."

__all__ = ['WARM_ROUNDS', 'NoDhrona', 'fit_rounds', 'warm_messages', 'warm_report', 'assess_session', 'capture_round',
           'accept_round']

WARM_ROUNDS = 3   #: rounds a fresh conversation is seeded with; each is a few hundred tokens


class NoDhrona(RuntimeError):
    "dhrona is not installed, or too old for this seam."


def _core():
    try: from dhrona import core; return core
    except ImportError as e: raise NoDhrona('warm starts need `uv add dhrona`') from e

def _rounds():
    try: from dhrona import rounds; return rounds
    except ImportError as e: raise NoDhrona('capturing rounds needs `uv add dhrona`') from e


def fit_rounds(tools, model=None, limit=WARM_ROUNDS, dirs=None):
    "`(used, skipped)`: dhrona's ranking of the accepted rounds against `tools`, and `(round, reason)` for every one left out."
    return _core().fit_rounds(tools, model, limit, dirs)

def warm_messages(used):
    "The canonical Urai messages `used` replays, in order: what the backend is seeded with."
    core = _core()
    return [m for r in used for m in core.round_msgs(r)]

def _call(tc):
    "One urai `ToolCall` (OpenAI-shaped: `function.name`) as the flat row the pane paints."
    fn = tc.get('function') or {}
    return {'id': tc.get('id', ''), 'name': fn.get('name', ''), 'arguments': fn.get('arguments') or {}}

def _plain_msgs(msgs):
    "Urai messages as JSON: `tool_calls` become `{id, name, arguments}` rows."
    return [{**m, 'tool_calls': [_call(tc) for tc in m['tool_calls']]} if m.get('tool_calls') else dict(m) for m in msgs]

def warm_report(used, skipped):
    "What the transcript block paints: names, replayed messages, and the reason for every skip."
    core = _core()
    return {'used': [{'name': r['meta'].get('name', ''), 'rank': r['meta'].get('rank', 50),
                      'model': r['meta'].get('model'), 'messages': _plain_msgs(core.round_msgs(r))} for r in used],
            'skipped': [{'name': r['meta'].get('name', ''), 'reason': why} for r, why in skipped]}


def assess_session(history, session):
    "dhrona's score and findings for one conversation; each finding carries the turn it came from."
    from dataclasses import asdict
    core = _core(); turns = list(core.read_history(history, session))
    a = core.assess_history(turns)
    rows = [{**asdict(f), 'turn_id': turns[f.turn].get('turn_id', '') if f.turn is not None else ''} for f in a.findings]
    return {'score': a.score, 'calls': a.calls, 'turns': len(turns), 'findings': rows}

def capture_round(history, session, output, name=None):
    "One conversation as a dhrona review notebook at `output`."
    return str(_rounds().capture(str(output), session=session, history=str(history), name=name))

def accept_round(source, reviewer):
    "Accept a reviewed notebook into the rounds library; the installed path comes back."
    rounds = _rounds()
    return str(rounds.install_round(rounds.accept(str(source), reviewer)))
