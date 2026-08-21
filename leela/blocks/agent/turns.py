"How one assistant turn is shaped for the browser: tool schemas, previews, diffs, media."

from __future__ import annotations

import json

from fastcore.basics import first

from ...core.web import diff_payload

__all__ = ['TOOL_GROUPS', 'tool_group', 'tool_schemas', 'tool_preview', 'edit_diffs',
           'activity_changes', 'history_sessions', 'project_state_context', 'turn_media']

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
        from ...agent.tools import _cmds
        from exhash import exhash
        path = args.get('path', '')
        before = agent.host.text_at(path)
        if before is None: raise ValueError(f'no such file: {path}')
        result = exhash(before, _cmds(args.get('commands', '[]')))
        return {'kind': 'patch', 'text': str(result)}
    if tool == 'replace_text':
        from ...agent.tools import _apply_edits, _edits
        path = args.get('path', '')
        before = agent.host.text_at(path)
        if before is None: raise ValueError(f'no such file: {path}')
        return {'kind': 'diff', **diff_payload(before, _apply_edits(before, _edits(args.get('edits', '[]'))))}
    if tool in {'run_python', 'inspect_python'}:
        return {'kind': 'code', 'text': str(args.get('code', '')), 'language': 'python'}
    if tool == 'run_shell':
        return {'kind': 'code', 'text': str(args.get('command', '')), 'language': 'bash'}
    if tool in {'edit_cell', 'add_cell'}:
        return {'kind': 'code', 'text': str(args.get('source') or args.get('commands') or ''), 'language': 'python'}
    if tool in {'web_search', 'read_url', 'research'}:
        return {'kind': 'network', 'text': str(args.get('url') or args.get('query') or '')}
    return {'kind': 'json', 'text': json.dumps(args, indent=2, default=str)}

TOOL_GROUPS = {
    'Repository': {'search_code', 'similar_code', 'outline', 'list_files', 'grep', 'ls',
                   'view_file', 'edit_file', 'replace_text', 'create_file'},
    'Runtime': {'run_python', 'inspect_python', 'list_vars', 'read_terminal', 'run_shell'},
    'Web': {'web_search', 'read_url', 'research'},
}

def tool_group(name):
    "Which browser-facing family a tool belongs to."
    group = first(g for g, names in TOOL_GROUPS.items() if name in names)
    if group: return group
    return 'Notebook' if 'cell' in name or 'notebook' in name else 'Other'

def tool_schemas(agent):
    "Browser-sized schemas for editable checkpoint forms; callable validation remains authoritative."
    import inspect
    from .ai import WRITE_TOOLS
    out = []
    for tool in agent.tools:
        sig = inspect.signature(tool)
        fields = []
        for name, p in sig.parameters.items():
            ann = p.annotation
            kind = ('boolean' if ann is bool else 'integer' if ann is int else
                    'number' if ann is float else 'string')
            fields.append({'name': name, 'kind': kind, 'required': p.default is inspect.Parameter.empty,
                           'default': None if p.default is inspect.Parameter.empty else p.default,
                           'multiline': name in {'code', 'text', 'commands', 'edits', 'source',
                                                 'questions', 'command'}})
        out.append({'name': tool.__name__, 'description': (inspect.getdoc(tool) or '').split('\n')[0],
                    'changes_state': tool.__name__ in WRITE_TOOLS,
                    'retryable': tool.__name__ not in WRITE_TOOLS,
                    'group': tool_group(tool.__name__), 'fields': fields})
    return out

def edit_diffs(a):
    "Per-file diffs for what an assistant turn actually wrote."
    return [{'path': p, **diff_payload(was, now)} for p, (was, now) in a.changes().items()]

def activity_changes(a, versions):
    "Activity rows that moved since the last poll: new calls and in-place transitions"
    changed = []
    for row in a.activity.rows(mark=a.activity._mark):
        version = (row.get('done'), row.get('ok'), row.get('line'), row.get('detail'), row.get('secs'))
        if versions.get(row['id']) != version:
            versions[row['id']] = version
            changed.append(row)
    return changed

def history_sessions(turns, execution=()):
    "Turns grouped by durable model-context id; old untagged history splits after 30m."
    groups, by_id, legacy_n, legacy_last = [], {}, 0, None
    for turn in turns or ():
        sid, at = turn.get('session') or '', float(turn.get('at') or 0)
        if not sid:
            if legacy_last is None or at - legacy_last > 1800: legacy_n += 1
            sid, legacy_last = f'legacy-{legacy_n}', at
        if sid not in by_id:
            by_id[sid] = {'id': sid, 'started': at, 'ended': at, 'turns': [], 'models': [],
                          'context_continues': True, 'code': 0}
            groups.append(by_id[sid])
        g = by_id[sid]; g['turns'].append(turn); g['ended'] = max(g['ended'], at)
        if (model := turn.get('model')) and model not in g['models']: g['models'].append(model)
    for row in execution or ():
        sid = row['id']
        if sid in by_id: by_id[sid]['code'] = row.get('code', 0)
        else: groups.append({'id': sid, 'started': 0, 'ended': 0, 'turns': [], 'models': [],
                             'context_continues': True, 'code': row.get('code', 0)})
    return list(reversed(groups))

def turn_media(a):
    "Pictures the turn produced, as data URLs. A tool result is a path, which a browser cannot draw."
    import base64
    out = []
    for m in (getattr(a, 'turn_media', None) or []):
        data = m.get('data')
        if not data: continue
        out.append({'mime': m.get('mime') or 'image/png',
                    'url': f"data:{m.get('mime') or 'image/png'};base64,{base64.b64encode(data).decode()}"})
    return out
