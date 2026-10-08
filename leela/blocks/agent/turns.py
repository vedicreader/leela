"How one assistant turn is formatted for the browser: tool schemas, previews, diffs, media."

from __future__ import annotations

import base64, json
from pathlib import Path

from fastcore.basics import first
from fastcore.xtras import atomic_save

from ...core.web import diff_payload

__all__ = ['GROUP_LABELS', 'LEELA_TOOLS', 'tool_group', 'tool_schemas', 'tool_preview', 'edit_diffs',
           'activity_changes', 'history_sessions', 'indexed_sessions', 'project_state_context', 'turn_media',
           'with_capabilities', 'SURFACES_FILE', 'mark_surface', 'surfaces', 'latest_started_here']

SURFACES_FILE = 'agent-surfaces.json'   #: sessions Leela started, beside Ramabana's own metadata

def surfaces(cfg):
    "Session id -> the Leela surface that started it. Anything absent was not started here."
    if not cfg: return {}
    p = Path(cfg)/SURFACES_FILE
    if not p.exists(): return {}
    try:
        rows = json.loads(p.read_text()).get('sessions', {})
        return rows if isinstance(rows, dict) else {}
    except Exception: return {}

def latest_started_here(ai):
    "The newest conversation this Leela started, by the mark the history list filters on."
    here = surfaces(getattr(ai, 'cfg', None))
    if not here: return ''
    return first((s['id'] for s in ai.sessions() if s['id'] in here), '')

def mark_surface(cfg, sid, surface='agent', keep=4000):
    "Record that Leela started `sid`. The CLI writes the same log and leaves no such mark."
    if not cfg or not sid: return {}
    rows = surfaces(cfg)
    if rows.get(sid) == surface: return rows
    rows[sid] = surface
    if len(rows) > keep: rows = dict(list(rows.items())[-keep:])
    p = Path(cfg)/SURFACES_FILE
    try:
        with atomic_save(p, mode='w', encoding='utf-8') as f:
            f.write(json.dumps({'version': 1, 'sessions': rows}, ensure_ascii=False))
    except Exception: pass
    return rows

def project_state_context(ws, max_files=120, max_chars=12_000):
    "Bounded, current-disk evidence used when a person asks the charter to follow the code."
    files = [p for p in ws.fs.walk(limit=max_files) if p.is_file()]
    names = '\n'.join(f'- {p}' for p in files)
    preferred = ('README.md', 'pyproject.toml', 'package.json', 'Cargo.toml', 'go.mod',
                 'requirements.txt', 'Makefile')
    excerpts, used = [], 0
    for path in sorted(files, key=lambda p: (p.name not in preferred, len(p.parts), str(p))):
        if path.name not in preferred and len(excerpts) >= 4: continue
        try: text = ws.fs.read(path)
        except Exception: continue
        room = max_chars - used
        if room <= 0: break
        excerpt = text[:min(3000, room)].strip()
        if excerpt:
            excerpts.append(f'### {path}\n{excerpt}')
            used += len(excerpt)
    return ('## Open roots\n' + ('\n'.join(f'- {root}' for root in ws.fs.roots) or '- none') +
            '\n\n## Current file map\n' + (names or '- no files') +
            '\n\n## Project-file excerpts\n' + ('\n\n'.join(excerpts) or '- none'))

def tool_preview(agent, tool, args):
    "Dry-run preview for editable calls; never invokes the tool or mutates the workspace."
    args = dict(args or {})
    if tool == 'create_file':
        path = args.get('path', '')
        before = agent.host.text_at(path) or ''
        return {'kind': 'diff', **diff_payload(before, str(args.get('text', '')))}
    if tool == 'edit_file':
        from shalya.core import cmds
        from exhash import exhash
        path = args.get('path', '')
        before = agent.host.text_at(path)
        if before is None: raise ValueError(f'no such file: {path}')
        result = exhash(before, cmds(args.get('commands') or []))
        return {'kind': 'patch', 'text': str(result)}
    if tool == 'replace_text' or (tool == 'edit_cell' and 'edits' in args):
        from shalya.core import apply_edits, edits
        es = edits(args.get('edits') or [])
        if not es: return {'kind': 'code', 'text': 'no edits given'}
        path = args.get('path', '')
        if tool == 'edit_cell': before = agent.host.nb_cell(path, args.get('cell_id', ''))[2]
        else:
            before = agent.host.text_at(path)
            if before is None: raise ValueError(f'no such file: {path}')
        return {'kind': 'diff', **diff_payload(before, apply_edits(before, es))}
    if tool in {'run_python', 'inspect_python'}:
        return {'kind': 'code', 'text': str(args.get('code', '')), 'language': 'python'}
    if tool == 'run_cell':
        return {'kind': 'code', 'text': f"{args.get('path', '')}  {args.get('cell_id', '')}".strip()}
    if tool == 'run_shell':
        return {'kind': 'code', 'text': str(args.get('command', '')), 'language': 'bash'}
    if tool in {'edit_cell', 'add_cell'}:
        return {'kind': 'code', 'text': str(args.get('source') or args.get('commands') or ''), 'language': 'python'}
    if tool in {'web_search', 'read_url', 'research'}:
        return {'kind': 'network', 'text': str(args.get('url') or args.get('query') or '')}
    return {'kind': 'json', 'text': json.dumps(args, indent=2, default=str)}

#: shalya's capability groups under the names the checkpoint form shows. Two groups share a label
#: where the distinction is shalya's and not a person's: reading a file is repository work, and a
#: shell command is the runtime.
GROUP_LABELS = {'code': 'Repository', 'file': 'Repository', 'notebook': 'Notebook', 'web': 'Web', 'browser': 'Browser',
                'memory': 'Memory', 'ask': 'Memory', 'watch': 'Watches', 'api': 'API',
                'session': 'Runtime', 'shell': 'Runtime', 'git': 'Git', 'skill': 'Skills',
                'image': 'Media'}
#: The tools Leela adds to shalya's, which shalya has no way to name for us.
LEELA_TOOLS = {'run_cell': 'Runtime', 'generate_video': 'Media', 'video_status': 'Media',
               'video_jobs': 'Media', 'news_feeds': 'Web', 'news_latest': 'Web',
               'news_story': 'Web', 'news_follow': 'Web', 'news_unfollow': 'Web',
               'news_refresh': 'Web'}

def tool_group(name):
    "Which browser-facing family a tool belongs to: shalya's group for it, or one of Leela's own."
    from shalya.tools import group_of
    return LEELA_TOOLS.get(name) or GROUP_LABELS.get(group_of(name)) or 'Other'

def tool_schemas(agent):
    "Browser-sized schemas for editable checkpoint forms, over what the model is offered; callable validation remains authoritative."
    import inspect, typing
    from .ai import WRITE_TOOLS, PATH_WRITES
    out = []
    for tool in agent._plain:
        sig = inspect.signature(tool)
        fields = []
        for name, p in sig.parameters.items():
            ann = p.annotation
            kind = ('boolean' if ann is bool else 'integer' if ann is int else 'number' if ann is float else
                    'json' if ann in (list, dict) or typing.get_origin(ann) in (list, dict) else 'string')
            default = None if p.default is inspect.Parameter.empty else p.default
            fields.append({'name': name, 'kind': kind, 'required': p.default is inspect.Parameter.empty,
                           'default': json.dumps(default) if kind == 'json' and default is not None else default,
                           'multiline': kind == 'json' or name in {'code', 'text', 'source', 'command'}})
        out.append({'name': tool.__name__, 'description': (inspect.getdoc(tool) or '').split('\n')[0],
                    'changes_state': tool.__name__ in WRITE_TOOLS | PATH_WRITES,   # a drawing may name a path
                    'retryable': tool.__name__ not in WRITE_TOOLS | PATH_WRITES,
                    'group': tool_group(tool.__name__), 'fields': fields})
    return out

def with_capabilities(ai, turns):
    "Each turn with what can still be done to it, so a painted turn carries its own controls."
    out = []
    for turn in turns or ():
        try: caps = ai.turn_capabilities(turn.get('turn_id') or '')
        except Exception: caps = {}
        out.append({**turn, 'capabilities': caps})
    return out

def edit_diffs(a):
    "Per-file diffs for what an assistant turn actually wrote."
    return [{'path': p, **diff_payload(was, now)} for p, (was, now) in a.changes().items()]

def activity_changes(a, versions):
    "Activity rows that moved since the last poll: new calls and in-place transitions."
    changed = []
    for row in a.activity.rows(mark=a.activity._mark):
        version = (row.get('done'), row.get('ok'), row.get('line'), row.get('detail'), row.get('secs'))
        if versions.get(row['id']) != version:
            versions[row['id']] = version
            changed.append(row)
    return changed

def history_sessions(turns, execution=(), started_here=None):
    "Turns grouped by durable model-context id; old untagged history splits after 30m. `started_here` marks Leela's own."
    here = started_here or {}
    groups, by_id, legacy_n, legacy_last = [], {}, 0, None
    for turn in turns or ():
        sid, at = turn.get('session') or '', float(turn.get('at') or 0)
        if not sid:
            if legacy_last is None or at - legacy_last > 1800: legacy_n += 1
            sid, legacy_last = f'legacy-{legacy_n}', at
        if sid not in by_id:
            by_id[sid] = {'id': sid, 'started': at, 'ended': at, 'turns': [], 'models': [],
                          'context_continues': True, 'code': 0,
                          'app': 'leela' if sid in here else 'ramabana'}
            groups.append(by_id[sid])
        g = by_id[sid]; g['turns'].append(turn); g['ended'] = max(g['ended'], at)
        if (model := turn.get('model')) and model not in g['models']: g['models'].append(model)
    for row in execution or ():
        sid = row['id']
        if sid in by_id: by_id[sid]['code'] = row.get('code', 0)
        else: groups.append({'id': sid, 'started': 0, 'ended': 0, 'turns': [], 'models': [],
                             'context_continues': True, 'code': row.get('code', 0),
                             'app': 'leela' if sid in here else 'ramabana'})
    return list(reversed(groups))

def indexed_sessions(rows, execution=(), started_here=None):
    "Ramabana's index rows as history groups, in their order, then kernel runs no row names. `started_here` marks Leela's own."
    here, code = started_here or {}, {r['id']: r.get('code', 0) for r in execution or ()}
    def group(sid, **kw): return {'id': sid, 'turns': [], 'context_continues': True, 'code': code.get(sid, 0),
                                  'app': 'leela' if sid in here else 'ramabana', **kw}
    out = [group(r['id'], started=r.get('first_at') or r.get('at', 0), ended=r.get('at', 0), count=int(r.get('turns', 0)),
                 models=[r['model']] if r.get('model') else [], title=r.get('title', ''), muted=bool(r.get('muted')))
           for r in rows if r.get('model') != 'scripted']   # the index keeps only the last model
    named = {r['id'] for r in rows}
    return out + [group(sid, started=0, ended=0, count=0, models=[]) for sid in code if sid not in named]

def turn_media(ai):
    "Pictures the turn produced, as data URLs. A tool result is a path, which a browser cannot draw."
    out = []
    for m in (getattr(ai, 'turn_media', None) or []):
        data = m.get('data')
        if not data: continue
        mime = m.get('mime') or 'image/png'
        out.append({'mime': mime, 'url': f'data:{mime};base64,{base64.b64encode(data).decode()}'})
    return out
