"dhrona in the agent pane: which rounds fit this conversation's tools, why the rest did not, and the capture → review → accept loop."

import json, re
from pathlib import Path

__all__ = ['NoDhrona', 'with_messages', 'assess_session', 'capture_round', 'round_name', 'accept_round']


class NoDhrona(RuntimeError):
    "dhrona is not installed, or too old for this seam."


def _core():
    try: from dhrona import core; return core
    except ImportError as e: raise NoDhrona('warm starts need `uv add dhrona`') from e

def _rounds():
    try: from dhrona import rounds; return rounds
    except ImportError as e: raise NoDhrona('capturing rounds needs `uv add dhrona`') from e


def _call(tc):
    "One urai `ToolCall` (OpenAI-shaped: `function.name`) as the flat row the pane paints."
    fn = tc.get('function') or {}
    return {'id': tc.get('id', ''), 'name': fn.get('name', ''), 'arguments': fn.get('arguments') or {}}

def _plain_msgs(msgs):
    "Urai messages as JSON: `tool_calls` become `{id, name, arguments}` rows."
    return [{**m, 'tool_calls': [_call(tc) for tc in m['tool_calls']]} if m.get('tool_calls') else dict(m) for m in msgs]

def with_messages(report, dirs=None):
    "ramabana's warm report with the messages each used round replayed, for the transcript block; a round the library no longer has gets none."
    core = _core()
    by_name = {r['meta'].get('name', ''): r for r in core.load_rounds(dirs)}
    used = [{**row, 'messages': _plain_msgs(core.round_msgs(by_name[row['name']])) if row['name'] in by_name else []}
            for row in report.get('used', [])]
    return {**report, 'used': used}


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

def round_name(name):
    "A round's file name in the library: one path component, no leading dots, `round` when nothing is left."
    return re.sub(r'[^A-Za-z0-9._-]+', '-', str(name or '')).strip('.-') or 'round'

def accept_round(source, reviewer):
    "Accept a reviewed notebook into the rounds library under the notebook's own name; the installed path comes back."
    rounds = _rounds(); source = Path(source)
    name = round_name(source.stem)      # the notebook names the round; its metadata does not choose a path
    compiled = Path(rounds.accept(str(source), reviewer))
    data = json.loads(compiled.read_text()); data['meta']['name'] = name
    compiled.write_text(json.dumps(data, indent=2))
    return str(rounds.install_round(compiled, name=name))
