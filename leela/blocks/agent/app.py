"The agent as routes: the turn, its approvals, its budgets, its memory and its history."

from __future__ import annotations

import asyncio, json, os, re

from fasthtml.common import StreamingResponse
from fastcore.all import L, first, ifnone

from ... import errstr
from ...agent.core import model_note
from ...agent.runtime import estimate_tokens
from ...core.web import diff_payload, fail, off_loop, sse
from ...workspace import STEP_RANGE, TOOL_RANGE
from .turns import (activity_changes, edit_diffs, history_sessions, project_state_context,
                    tool_preview, tool_schemas, turn_media)

__all__ = ['CAPS', 'connect']

CAPS = ('fs', 'memory', 'approvals', 'ai', 'inline_ai', 'pending_approval', 'docs')

def connect(app, ctx):
    rt = app.route
    ws = ctx.session
    def _doc(): return ctx.docs.current()
    async def api(path, params=None, timeout=15):
        client = await ws.runtime()
        return await client.api(path, params, timeout) if client else None

    def live_assistants():
        "Only the assistants already built -- reaching for `ctx.ai` here would construct one."
        return L(ws._ai, ws._inline_ai).filter(lambda a: a is not None)
    def refresh_assistants():
        for a in live_assistants(): a.refresh()
    @rt('/agent/attachment')
    async def agent_attachment(req):
        """Save a pasted image inside the active workspace and return its attachment path."""
        d = await req.json()
        path = str(d.get('path') or '').strip()
        if path:
            image_exts = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
            p = ctx.fs._check(path, must_exist=True)
            if not p.is_file() or p.suffix.lower() not in image_exts:
                return fail('attachment is not a workspace image')
            return {'ok': True, 'path': str(p), 'name': p.name}
        url = str(d.get('data_url') or '')
        if not url.startswith('data:image/'):
            return fail('no image attachment')
        if len(url) > 12_000_000:
            return fail('image attachment is larger than 9 MB', 413)
        import base64
        try: data = base64.b64decode(url.split(',', 1)[1], validate=True)
        except Exception as e: return fail(e)
        if len(data) > 9_000_000: return fail('image attachment is larger than 9 MB', 413)
        ext = '.png' if url.startswith('data:image/png') else '.jpg'
        folder = ws.cwd_for() / '.leela-attachments'
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / f'paste-{os.urandom(6).hex()}{ext}'
        p.write_bytes(data)
        return {'ok': True, 'path': str(p), 'name': p.name}
    @rt('/agent/info')
    async def agent_info(): return await api('/agent/api/info') or {'mode': 'off'}
    @rt('/agent/sessions')
    async def agent_sessions():
        return await api('/agent/api/sessions') or {'current': None, 'sessions': []}
    @rt('/agent/transcript')
    async def agent_transcript(session: str = ''):
        live = await api('/agent/api/transcript', {'session': session}) or {'cells': []}
        return {'id': live.get('id'), 'path': live.get('path'), 'cells': live.get('cells', []),
                'agent': list(ctx.ai.history) if not session else [],
                'inline': list(ctx.inline_ai.history) if not session else []}
    @rt('/agent/resume')
    async def agent_resume(req):
        "Put a saved conversation back into the model's context, and return its turns."
        d = await req.json()
        if ctx.ai.busy: return fail('cannot resume while the agent is working', 409)
        try: s = await off_loop(ctx.ai.resume_session, str(d.get('session') or 'latest'))
        except Exception as e: return fail(e)
        return {'ok': True, 'session': s['id'], 'note': ctx.ai.note,
                'turns': [t for t in ctx.ai.history if t.get('session') == s['id']]}
    @rt('/agent/new')
    async def agent_new():
        if ctx.ai.busy: return fail('cannot start a new conversation while the agent is working', 409)
        from .ai import Assistant
        old = ws._ai
        ws._ai = Assistant(ws, model=old.model.name, surface='agent', local_multimodal=ws.local_multimodal,
                           on_compact=ws._compacted, history_name='agent')
        ws.sync_agent_routing(ws._ai)
        ctx.approvals.host = ws._ai.host
        old.close()
        return {'ok': True, 'session': ctx.ai.session_id}
    @rt('/agent/history')
    async def agent_history():
        "All durable turns grouped by model-context session, newest session first."
        execution = await api('/agent/api/sessions') or {'sessions': []}
        turns = [t for t in ctx.ai.history if t.get('model') != 'scripted']
        return {'sessions': history_sessions(turns, execution.get('sessions', [])),
                'model': ctx.ai.model.name, 'current': ctx.ai.session_id}
    @rt('/agent/models')
    def agent_models(legacy: bool = True):
        from ...agent.core import DFLT_LOCAL, available_models, auth_status, resolve
        from .models import load_models, mark_models, runtimes
        notes = {}
        def _try(what, f, dflt=None):
            "`f()`, or `dflt` and a note saying why: no one failure may blank the picker."
            try: return f()
            except Exception as e: notes[what] = errstr(e); return dflt
        def _spec(name): return _try(name, lambda: resolve(name))
        def _name(what, get, dflt): return _try(what, get, dflt) or dflt
        saved = _try('saved models', load_models, []) or []
        rows = _try('model catalog', lambda: available_models(include_legacy=legacy), []) or []
        rows += [{'value':x['name'],'label':x['name'],'provider':x['runtime'],
                  'source':f"saved · {x['model_id']}",'custom':True} for x in saved]
        agent_dflt = ws.model or os.environ.get('LEELA_MODEL') or DFLT_LOCAL
        agent = _name('agent model', lambda: ctx.ai.model.name, agent_dflt) if ws._ai is not None else agent_dflt
        inline_dflt = ws.inline_model or os.environ.get('LEELA_MODEL_INLINE') or 'gpt-mini'
        inline = (_name('inline model', lambda: ctx.inline_ai.model.name, inline_dflt)
                  if ws._inline_ai is not None else inline_dflt)
        completion_dflt = ws.completion_model or os.environ.get('LEELA_MODEL_COMPLETION') or 'gpt-4.1'
        completion = (_name('completion model', lambda: ctx.ai.routing.name_for('completion'), completion_dflt)
                      if ws._ai is not None else completion_dflt)
        for current in (agent, inline, completion):
            spec = _spec(current)
            if spec is None:
                why = f'unavailable ({notes.get(current, "")})'
                row = first(r for r in rows if r['value'] == current)
                if row is None: rows.append(row := {'value': current, 'label': current})
                row.update(provider='unavailable', source=why, unavailable=True)
                continue
            if not any((s := _spec(r['value'])) and s.model_id == spec.model_id for r in rows):
                provider = spec.model_id.partition('/')[0] if not spec.local else spec.runtime
                rows.append({'value': current, 'label': current, 'provider': provider,
                             'source': 'saved choice · provider credentials may be required'})
        def selected(current):
            spec = _spec(current)
            if spec is None: return current
            return ifnone(first(r['value'] for r in rows
                                if (s := _spec(r['value'])) and s.model_id == spec.model_id), current)
        # The routed jobs with no field of their own, reported chosen or not.
        from ...agent.core import JOBS, Routing
        routing = ctx.ai.routing if ws._ai is not None else Routing(turn=agent)
        if ws._ai is None: routing.policy.update(ws.job_models)
        jobs = {j: _name(f'{j} model', lambda j=j: routing.name_for(j), '')
                for j in JOBS if j not in ('turn', 'completion')}
        return {'models': mark_models(rows), 'saved':saved, 'notes': notes,
                'auth': _try('auth', auth_status, {}) or {}, 'runtimes': _try('runtimes', runtimes, []) or [],
                'jobs': jobs,
                'selected': {'agent': selected(agent), 'inline': selected(inline),
                             'completion': selected(completion), **jobs}}
    @rt('/agent/models/add')
    async def agent_models_add(req):
        "Save a Hugging Face repo/URL or hosted provider model alias."
        from .models import save_model
        try:return {'ok':True,'model':save_model(await req.json())}
        except Exception as e:return fail(e)
    @rt('/agent/models/remove')
    async def agent_models_remove(req):
        from .models import delete_model
        try:return {'ok':True,'name':delete_model((await req.json()).get('name',''))}
        except Exception as e:return fail(e)
    @rt('/agent/settings')
    async def agent_settings(req):
        "Set engine-level agent options. LiteRT engines reload lazily after a change."
        d = await req.json()
        if 'litert_backend' in d:
            try:
                from .ai import Assistant
                which = str(d.get('litert_backend') or '').strip().lower()
                if which not in Assistant.LITERT_BACKENDS:
                    raise ValueError(f'litert backend must be one of {", ".join(Assistant.LITERT_BACKENDS)}')
                live = live_assistants()
                for a in live: a.set_litert_backend(which)
                if not live: os.environ['LEELA_LITERT_BACKEND'] = which
                ws.litert_backend = which
                ws.save()
                return {'ok': True, 'litert_backend': which,
                        'note': f'LiteRT runs on the {which.upper()}; engines reload on the next request'}
            except Exception as e: return fail(e)
        try:
            enabled = d.get('local_multimodal')
            if not isinstance(enabled, bool): raise ValueError('local_multimodal must be true or false')
            live = live_assistants()
            if any(a.busy for a in live): raise RuntimeError('cannot change local multimodal while an assistant is working')
            for a in live: a.set_local_multimodal(enabled)
            ws.local_multimodal = enabled
            ws.save()
            return {'ok': True, 'local_multimodal': enabled,
                    'note': f'local image/audio encoders {"enabled" if enabled else "disabled"}'}
        except Exception as e: return fail(e)
    @rt('/agent/workspace-repo-writes')
    async def agent_workspace_repo_writes(req):
        d = await req.json(); enabled = d.get('enabled')
        if not isinstance(enabled, bool): return fail('enabled must be true or false')
        ws.allow_workspace_repo_writes = enabled; ws.save()
        return {'ok': True, 'enabled': enabled,
                'note': f'workspace repository writes {"enabled" if enabled else "disabled"}; approval rules still apply'}
    @rt('/agent/subagent-writes')
    async def agent_subagent_writes(req):
        "Whether delegated sub-agents get the write tools. Approvals and recording apply either way."
        d = await req.json(); enabled = d.get('enabled')
        if not isinstance(enabled, bool): return fail('enabled must be true or false')
        try:
            live = live_assistants()
            if any(a.busy for a in live): raise RuntimeError('cannot change sub-agent writes while an assistant is working')
            for a in live: a.set_subagent_writes(enabled)
        except Exception as e: return fail(e)
        ws.subagent_writes = enabled; ws.save()
        return {'ok': True, 'enabled': enabled,
                'note': ('sub-agents may write, run commands and run Python. Every call is recorded and approved'
                         if enabled else 'sub-agents read only again')}
    @rt('/agent/read-outside')
    async def agent_read_outside(req):
        "Reads outside the open folders. Writes are unaffected, and credentials stay refused."
        d = await req.json(); enabled = d.get('enabled')
        if not isinstance(enabled, bool): return fail('enabled must be true or false')
        ws.agent_read_outside = enabled; ws.save()
        return {'ok': True, 'enabled': enabled,
                'note': f'reads outside the open folders {"allowed" if enabled else "refused"}; writes are unchanged'}
    @rt('/agent/compaction')
    async def agent_compaction(req):
        "Configure visible automatic compaction without restarting the model conversation."
        d = await req.json(); strategy = d.get('strategy', ws.compact_strategy)
        if strategy not in {'surgical', 'summary'}: return fail('strategy must be surgical or summary')
        auto = d.get('auto', ws.compact_auto)
        if not isinstance(auto, bool): return fail('auto must be true or false')
        ws.compact_auto, ws.compact_strategy = auto, strategy
        for agent in live_assistants():
            agent.compactor.auto, agent.compactor.strategy = auto, strategy
        ws.save()
        return {'ok': True, 'auto': auto, 'strategy': strategy,
                'note': f'auto compaction {"on" if auto else "off"} · {strategy}'}
    @rt('/agent/budget')
    async def agent_budget(req):
        "How much work one turn may do, changed without restarting the conversation."
        from ...workspace import budget_value
        d = await req.json()
        for key, given in (('tool_budget', d.get('tools')), ('step_budget', d.get('steps'))):
            if given is None: continue
            lo, hi = TOOL_RANGE if key == 'tool_budget' else STEP_RANGE
            value = budget_value(given, lo, hi)
            if value == 'auto' and str(given).strip().lower() != 'auto':
                return fail(f'{key}: use auto, or a number from {lo} to {hi}')
            setattr(ws, key, value)
        for agent in live_assistants(): agent.tool_budget, agent.step_budget = ws.tool_budget, ws.step_budget
        ws.save()
        return {'ok': True, 'tools': ws.tool_budget, 'steps': ws.step_budget,
                'note': f'tool budget {ws.tool_budget} · steps {ws.step_budget}'}
    @rt('/agent/budget/state')
    def agent_budget_state():
        "What is actually in force, so a refused edit can put the box back rather than blank it."
        return {'ok': True, 'tools': ws.tool_budget, 'steps': ws.step_budget,
                'tool_range': list(TOOL_RANGE), 'step_range': list(STEP_RANGE)}
    @rt('/agent/model')
    async def agent_model(req):
        d = await req.json()
        try:
            from ...agent.core import JOBS
            from .models import load_models
            load_models()
            # `agent` and `inline` are two assistants, each on its own `turn`; the rest are jobs.
            target = d.get('target', 'agent')
            if target not in ('agent', 'inline') and target not in JOBS:
                return fail(f'unknown model target {target!r}')
            assistant = ctx.inline_ai if target == 'inline' else ctx.ai
            job = 'turn' if target in ('agent', 'inline') else target
            spec = assistant.set_model((d.get('model') or '').strip(), job=job)
            if target == 'inline': ws.inline_model = spec.name
            elif target == 'completion': ws.completion_model = spec.name
            elif target == 'agent': ws.model = spec.name
            else: ws.job_models[job] = spec.name
            ws.save()
            return {'ok': True, 'target': target, 'model': spec.name, 'note': model_note(spec)}
        except Exception as e: return fail(e)
    @rt('/agent/memory')
    async def agent_memory():
        "Editable notes and their explicit per-model session routing."
        notes = await off_loop(ctx.memory.agent_notes)
        rows = [{**note, 'text': await off_loop(ctx.memory.exact_text, str(note['id']))} for note in notes]
        return {'notes': rows, 'selected': ws.agent_memory_selection,
                'targets': {'agent': 'Agent conversation', 'inline': 'Prompt cells',
                            'completion': 'Code completion'}}
    @rt('/agent/memory/save')
    async def agent_memory_save(req):
        d = await req.json(); title = (d.get('title') or '').strip(); text = (d.get('text') or '').strip()
        if not text: return fail('memory note is empty')
        previous = str(d.get('id') or '')
        saved = await off_loop(ctx.memory.remember_agent_note, title, text, previous)
        if not saved: return fail(ctx.memory.note)
        new_id = str(saved.get('doc_id') or '')
        if previous and new_id:
            for target, ids in ws.agent_memory_selection.items():
                ws.agent_memory_selection[target] = [new_id if value == previous else value for value in ids]
        requested = d.get('targets', [])
        if not isinstance(requested, list): return fail('targets must be a list')
        for target in requested:
            if target not in ws.agent_memory_selection: return fail('targets must contain only agent, inline, or completion')
            if new_id and new_id not in ws.agent_memory_selection[target]: ws.agent_memory_selection[target].append(new_id)
        ws.save()
        refresh_assistants()
        return {'ok': True, 'id': new_id, 'note': ctx.memory.note}
    @rt('/agent/memory/select')
    async def agent_memory_select(req):
        d = await req.json(); target = str(d.get('target') or '')
        if target not in ws.agent_memory_selection: return fail('target must be agent, inline, or completion')
        ids = d.get('ids')
        if not isinstance(ids, list): return fail('ids must be a list')
        known = {str(note['id']) for note in await off_loop(ctx.memory.agent_notes)}
        selected = list(dict.fromkeys(str(value) for value in ids if str(value) in known))
        ws.agent_memory_selection[target] = selected; ws.save()
        assistant = ws._ai if target in {'agent', 'completion'} else ws._inline_ai
        if assistant is not None: assistant.refresh()
        tokens = sum([estimate_tokens(await off_loop(ctx.memory.exact_text, v)) for v in selected])
        return {'ok': True, 'target': target, 'ids': selected, 'tokens': tokens}
    @rt('/agent/memory/delete')
    async def agent_memory_delete(req):
        doc_id = str((await req.json()).get('id') or '')
        known = {str(note['id']) for note in await off_loop(ctx.memory.agent_notes)}
        if doc_id not in known: return fail('unknown agent memory note')
        for target, ids in ws.agent_memory_selection.items():
            ws.agent_memory_selection[target] = [value for value in ids if value != doc_id]
        ok = await off_loop(ctx.memory.forget, doc_id); ws.save()
        refresh_assistants()
        return {'ok': ok, 'note': ctx.memory.note}
    @rt('/agent/states')
    def agent_states():
        "Saved conversation states and the state currently injected into the briefing."
        active = any(str(layer.get('text') or '').strip() and layer.get('enabled', True)
                     for layer in ws.agent_state_layers.values())
        return {'active': active, 'active_text': ws.agent_state,
                'layers': ws.agent_state_layers, 'states': ctx.memory.agent_states()}
    @rt('/agent/state/template')
    def agent_state_template():
        "A complete, usable rules template with this workspace's actual tool catalog."
        from .ai import STATE_TEMPLATE
        tools = tool_schemas(ctx.ai)
        catalog = '\n'.join(f"- `{t['name']}` ({t['group']}): {t['description']}" for t in tools)
        return {'template': STATE_TEMPLATE, 'tools': tools,
                'catalog': '## Available tools\n' + (catalog or '- No tools are currently available.')}
    @rt('/agent/state/bootstrap')
    async def agent_state_bootstrap(req):
        "Ask the summary model to fill a transparent charter from the template and real tools."
        from .ai import STATE_TEMPLATE
        d = await req.json(); intent = (d.get('intent') or '').strip()
        tools = tool_schemas(ctx.ai)
        catalog = '\n'.join(f"- {t['name']} [{t['group']}]: {t['description']}" for t in tools)
        project = '\n'.join(f'- {root}' for root in ctx.ai.host.roots) or '- no folder open'
        prompt = (f'<workspace>\n{project}\n</workspace>\n\n<available-tools>\n{catalog}\n</available-tools>\n\n'
                  f'<user-intent>\n{intent or "Help me configure a safe, effective coding agent for this workspace."}\n</user-intent>\n\n'
                  f'<template>\n{STATE_TEMPLATE}\n</template>\n\nFill every bracketed field with concrete, concise guidance. '
                  'Keep the headings exactly. Mention tools only when they actually appear in available-tools. '
                  'Do not invent project facts; mark unknown facts as needing confirmation.')
        text = await off_loop(ctx.ai.oneshot, prompt,
                               'Design a user-owned coding-agent charter. Return complete Markdown only.', 'summary', 1800)
        if not text: text = STATE_TEMPLATE + '\n\n## Available tools\n' + catalog
        return {'ok': True, 'text': text, 'tools': tools,
                'model': ctx.ai.routing.name_for('summary'), 'generated': text != STATE_TEMPLATE}
    @rt('/agent/state/draft')
    def agent_state_draft():
        "A structured, editable state distilled deterministically from the visible conversation."
        turns = list(ctx.ai.history[-12:]) if ws._ai is not None else []
        conversation = '\n\n'.join(f"### User\n{t.get('prompt','')}\n\n### Agent\n{t.get('reply','')}"
                                   for t in turns)
        from .ai import STATE_TEMPLATE
        state = ws.agent_state or STATE_TEMPLATE
        return {'state': state, 'layers': ws.agent_state_layers,
                'conversation': conversation, 'turns': len(turns)}
    @rt('/agent/state/save')
    async def agent_state_save(req):
        "Save the user's edited state to durable semantic memory and optionally activate it."
        d = await req.json(); text = (d.get('text') or '').strip()
        if not text: return fail('agent state is empty')
        title = (d.get('title') or '').strip() or 'Agent state'
        saved = await off_loop(ctx.memory.remember_agent_state, title, text,
                                 {'session': ctx.ai.session_id if ws._ai is not None else '',
                                  'turns': len(ctx.ai.history) if ws._ai is not None else 0,
                                  'roots': [str(root) for root in ctx.fs.roots]})
        if not saved: return fail(ctx.memory.note)
        layer = (d.get('layer') or 'task').strip()
        if d.get('activate', True): ctx.ai.set_state(text, layer=layer, source='memory')
        return {'ok': True, 'saved': saved, 'active': ws.agent_state}
    @rt('/agent/state/suggest')
    def agent_state_suggest(q: str = ''):
        "Relevant saved states remain advisory; the browser decides whether to attach one."
        states = {str(s['id']): s for s in ctx.memory.agent_states()}
        hits = ctx.memory.search(q, limit=12) if q.strip() else []
        ids = [i for i in dict.fromkeys(str(h.get('doc_id') or '') for h in hits) if i in states]
        return {'query': q, 'states': [states[i] for i in ids[:5]]}
    @rt('/agent/state/diagnostics')
    async def agent_state_diagnostics(req):
        "Token budget, stale paths, and duplicate/conflicting headings for edited state."
        d = await req.json(); text = str(d.get('text') or '')
        tokens = estimate_tokens(text, ctx.ai.backend.count_tokens if ws._ai is not None else None)
        paths = set(re.findall(r'(?<![\w.-])(?:[\w.-]+/)+[\w.-]+', text))
        def absent(path):
            try: return not ctx.fs._check(path).exists()
            except Exception: return True
        missing = [p for p in paths if absent(p)]
        headings = [h.strip().lower() for h in re.findall(r'^#{1,3}\s+(.+)$', text, re.M)]
        duplicate = sorted({h for h in headings if headings.count(h) > 1})
        return {'tokens': tokens, 'context': ctx.ai.model.ctx if ws._ai is not None else None,
                'missing_paths': sorted(missing), 'duplicate_headings': duplicate}
    @rt('/agent/state/update')
    async def agent_state_update(req):
        "Use the summary model to propose a reviewed state replacement; never activate automatically."
        d = await req.json(); current = str(d.get('current') or ''); conversation = str(d.get('conversation') or '')
        project = project_state_context(ws)
        prompt = (f'<current-state>\n{current}\n</current-state>\n\n<conversation>\n{conversation[-20000:]}\n</conversation>\n\n'
                  f'<current-project>\n{project}\n</current-project>\n\n'
                  'Return the complete updated state using Goal, Constraints, Progress (Done/In progress/Blocked), '
                  'Key decisions, Next steps, and Critical context. Reconcile stale assumptions with current-project evidence. '
                  'Preserve still-valid user preferences, remove completed next steps, and never invent project facts.')
        text = await off_loop(ctx.ai.oneshot, prompt,
                               'Update explicit agent state. Return Markdown only, without a fence.', 'summary', 1600)
        if not text: return fail(ctx.ai.note or 'state update model returned nothing')
        return {'ok': True, 'text': text, 'diff': diff_payload(current, text)}
    @rt('/agent/state/activate')
    async def agent_state_activate(req):
        "Activate an edited state without adding it to durable memory."
        d = await req.json(); text = (d.get('text') or '').strip(); layer = d.get('layer') or 'task'
        try: ctx.ai.set_state(text, layer=layer, enabled=d.get('enabled', True), source='user')
        except ValueError as e: return fail(e)
        return {'ok': True, 'state': text, 'layer': layer}
    @rt('/agent/state/compare')
    async def agent_state_compare(req):
        "Compare one remembered revision with edited text before replacing or merging it."
        d = await req.json(); text = await off_loop(ctx.memory.agent_state_text, str(d.get('id') or ''))
        if not text: return fail(ctx.memory.note or 'saved state is empty')
        current = str(d.get('current') or '')
        return {'ok': True, 'state': text, 'diff': diff_payload(current, text)}
    @rt('/agent/state/load')
    async def agent_state_load(req):
        "Load a remembered state into the live agent briefing, preserving its conversation history."
        d = await req.json(); doc_id = str(d.get('id') or ''); layer = d.get('layer') or 'task'
        text = await off_loop(ctx.memory.agent_state_text, doc_id)
        if not text: return fail(ctx.memory.note or 'saved state is empty')
        try: ctx.ai.set_state(text, layer=layer, source='memory')
        except ValueError as e: return fail(e)
        return {'ok': True, 'state': text, 'layer': layer}
    @rt('/agent/commands')
    def agent_commands():
        "Slash-command metadata for the prompt's inline command picker."
        help_by_name = {name: help for name, (_, help) in ctx.ai.registry.commands.items()}
        builtins = {
            'model': 'show or change the model', 'cost': 'show token and cost totals',
            'compact': 'compact the current context', 'skills': 'list available skills',
            'skill': 'read one skill', 'tools': 'list tools available to the agent',
            'extensions': 'show loaded tool extensions', 'reload': 'reload tools, skills and extensions',
        }
        describe = lambda item: (getattr(item, '__doc__', '') or '').strip().split('\n')[0]
        return {
            'commands': [{'name': n, 'help': help_by_name.get(n) or builtins.get(n, '')}
                         for n in ctx.ai.commands()],
            'tools': [{'name': t.__name__, 'help': describe(t)} for t in ctx.ai.tools],
            'skills': [{'name': s.name, 'help': s.description} for s in ctx.ai.skills],
        }
    @rt('/agent/status')
    def agent_status():
        "Whether the assistant is loaded, what model it is on, and what it is doing right now."
        return ctx.ai.status()
    @rt('/agent/stop')
    async def agent_stop(req):
        "Cancel the foreground root run."
        try:
            d = await req.json()
        except Exception: d = {}
        try: return {'ok': True, **ctx.ai.cancel((d.get('run_id') or '').strip())}
        except Exception as e: return {'ok': False, 'error': errstr(e)}
    @rt('/agent/runs')
    def agent_runs(): return {'runs': ctx.ai.runs(active=True)}
    @rt('/agent/runs/{run_id}/cancel')
    def agent_run_cancel(run_id: str):
        try: return {'ok': True, **ctx.ai.cancel(run_id)}
        except Exception as e: return {'ok': False, 'error': errstr(e)}
    @rt('/agent/runs/{run_id}/terminate')
    def agent_run_terminate(run_id: str):
        try: return {'ok': True, **ctx.ai.terminate(run_id)}
        except Exception as e: return {'ok': False, 'error': errstr(e)}
    @rt('/agent/stream')
    async def agent_stream(req):
        "One turn as server-sent events, so the browser fills in as the model writes."
        q = (req.query_params.get('prompt') or '').strip()
        if not q: return fail('nothing to ask')
        try: attachments = json.loads(req.query_params.get('attachments') or '[]')
        except Exception: return fail('attachments must be a JSON array')
        if not isinstance(attachments, list): return fail('attachments must be a JSON array')
        reasoning = (req.query_params.get('reasoning') or '').lower()
        if reasoning not in ('', 'auto', 'low', 'medium', 'high'):
            return fail('reasoning must be auto, low, medium or high')
        reasoning = None if reasoning in ('', 'auto') else reasoning
        a = ctx.ai
        if a.busy: return fail('the assistant is already working; use steering or stop it first', 409)
        async def events():
            import queue as _q
            out, done = _q.Queue(), object()
            def pump():
                try:
                    nb = _doc()
                    context = nb.context(len(nb)) if nb is not None else ''
                    context_path = nb.path if nb is not None else ''
                    for c in ws.ask_stream(q, attachments=attachments, reasoning=reasoning,
                                           context=context, context_path=context_path): out.put(('chunk', c))
                except Exception as e: out.put(('error', errstr(e)))
                finally: out.put((done, None))
            loop = asyncio.get_running_loop()
            task = loop.run_in_executor(None, pump)
            run_id = ''
            finished, approval_id, activity_versions, execution_version = False, None, {}, None
            compact_count = a.compactor.count
            def changed_activity(): return activity_changes(a, activity_versions)
            try:
                while True:
                    try:
                        kind, val = await off_loop(out.get, True, 0.25)
                    except _q.Empty:
                        kind = val = None
                    if a.compactor.count != compact_count:
                        compact_count = a.compactor.count
                        yield sse('compaction', {'count': compact_count, 'strategy': a.compactor.strategy,
                                                  'note': a.compactor.note, 'text': a.compactor.last})
                    runs = a.runs(active=True)
                    if not run_id and runs: run_id = runs[-1]['id']
                    state = {**ctx.approvals.state(), 'runs': runs}
                    version = json.dumps(state, sort_keys=True)
                    if version != execution_version:
                        execution_version = version
                        yield sse('execution', state)
                    pending = ctx.pending_approval
                    if pending is not None and pending.id != approval_id:
                        approval_id = pending.id
                        proposal = {**pending.dict(), 'schemas': tool_schemas(a)}
                        yield sse('approval', proposal)
                    for row in changed_activity(): yield sse('activity', row)
                    if await req.is_disconnected(): break
                    run = a.run(run_id) if run_id else None
                    if run is not None and run.cancelled and run.terminal:
                        finished = True
                        yield sse('run', run.dict())
                        break
                    if kind is None: continue
                    if kind is done:
                        finished = True
                        for row in changed_activity(): yield sse('activity', row)
                        break
                    yield sse(kind, {'text': val} if kind == 'chunk' else {'error': val})
            finally:
                if not finished:
                    if not run_id:
                        end = loop.time() + a.cancel_grace
                        while not run_id and not task.done() and loop.time() < end:
                            runs = a.runs(active=True)
                            if runs: run_id = runs[-1]['id']
                            else: await asyncio.sleep(0.01)
                    try: a.cancel(run_id)
                    except Exception: pass
            if not finished: return
            if not task.done(): return
            await task
            capabilities = a.turn_capabilities(a.current_turn_id)
            yield sse('done', {'ok': a.ready, 'note': a.note, 'media': turn_media(a),
                                'usage': a.turn_use.dict(), 'usage_label': repr(a.turn_use),
                                'session_usage': a.use.dict(), 'session_usage_label': repr(a.use),
                                'model': a.model.name, 'turn_id': a.current_turn_id,
                                'branch_id': a.current_branch_id, 'capabilities': capabilities,
                                'problems': a.problems,
                                'activity': a.activity.rows(mark=a.activity._mark),
                                'edits': edit_diffs(a)})
        return StreamingResponse(events(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    @rt('/agent/approval')
    def agent_approval():
        "The call waiting for a person, or None. It stays inline so the rest of the IDE remains usable."
        a = ctx.pending_approval
        pending = ({**a.dict(), 'schemas': tool_schemas(ctx.ai)} if a is not None else None)
        return {'pending': pending, 'control': getattr(ctx.approvals, 'control', 'guided')}
    @rt('/agent/control')
    async def agent_control(req):
        "Choose how often tool proposals become editable checkpoints."
        d = await req.json()
        try: control = ctx.approvals.set_control((d.get('control') or '').strip())
        except ValueError as e: return fail(e)
        return {'ok': True, 'control': control}
    @rt('/agent/run-policy')
    async def agent_run_policy(req):
        "Run through bounded future calls, or pause immediately after the current one."
        d = await req.json()
        if d.get('policy') == 'pause':
            ctx.approvals.set_pause_next()
            return {'ok': True, **ctx.approvals.state()}
        try: policy = ctx.approvals.set_run_policy(d.get('policy') or 'once', d.get('count') or 1)
        except (ValueError, TypeError) as e: return fail(e)
        return {'ok': True, 'policy': policy, **ctx.approvals.state()}
    @rt('/agent/steer')
    async def agent_steer(req):
        """Queue guidance after the current tool; the next proposed call is skipped and replaced by it.

        `force` cancels the foreground run and returns the unsent text. A queued steer waits for a
        tool call, and a turn writing its answer never makes another one.
        """
        d = await req.json()
        text = (d.get('text') or '').strip()
        if d.get('cancel'):
            ctx.approvals.queue_steer('')
            return {'ok': True, **ctx.approvals.state()}
        if not text: return fail('steering instruction is empty')
        if d.get('force'):
            try: run = ctx.ai.cancel()
            except Exception as e: return fail(errstr(e))
            return {'ok': True, 'forced': True, 'run': run, 'text': text, **ctx.approvals.state()}
        ctx.approvals.queue_steer(text)
        return {'ok': True, **ctx.approvals.state()}
    @rt('/agent/tool-preview')
    async def agent_tool_preview(req):
        "Preview the resolved call without executing it."
        d = await req.json()
        tool, args = (d.get('tool') or '').strip(), d.get('args')
        if tool not in {t.__name__ for t in ctx.ai.tools}: return fail(f'unknown tool {tool}')
        if not isinstance(args, dict): return fail('tool arguments must be an object')
        try: return {'ok': True, 'preview': tool_preview(ctx.ai, tool, args)}
        except Exception as e: return fail(e)
    @rt('/agent/branches')
    def agent_branches():
        "Turn boundaries available for a true model-context fork in this running session."
        a = ctx.ai
        return {'active': a.current_branch_id,
                'turns': [{'turn_id': tid, 'branch_id': cp.get('branch_id', 'main'),
                           'before': 'before' in cp, 'after': 'after' in cp}
                          for tid, cp in a.checkpoints.items()]}
    @rt('/agent/fork')
    async def agent_fork(req):
        "Restore a model-history checkpoint as a new active conversation branch."
        d = await req.json()
        try: branch = ctx.ai.fork(d.get('turn_id') or '', d.get('stage') or 'after', d.get('branch_id') or '')
        except Exception as e: return fail(e)
        return {'ok': True, **branch}
    @rt('/agent/revise')
    async def agent_revise(req):
        "Create a branch whose last assistant prose is the user's edited response."
        d = await req.json(); text = (d.get('text') or '').strip()
        if not text: return fail('revised response is empty')
        try: branch = ctx.ai.revise(d.get('turn_id') or '', text, d.get('branch_id') or '')
        except Exception as e: return fail(e)
        return {'ok': True, **branch}
    @rt('/agent/retry-tool')
    async def agent_retry_tool(req):
        "Rerun a completed read-only call; return its result without changing model history."
        from .ai import WRITE_TOOLS
        d = await req.json()
        tool, args = (d.get('tool') or '').strip(), d.get('args')
        if tool in WRITE_TOOLS: return fail('only read-only calls can be retried from a checkpoint')
        choices = {t.__name__: t for t in ctx.ai.tools}
        if tool not in choices: return fail(f'unknown tool {tool}')
        if not isinstance(args, dict): return fail('tool arguments must be an object')
        try: result = await off_loop(choices[tool], **args)
        except Exception as e: return fail(e)
        return {'ok': True, 'tool': tool, 'args': args, 'result': str(result)}
    @rt('/agent/turn-transaction')
    def agent_turn_transaction(turn_id: str = ''):
        tx = ctx.ai.turn_transactions.get(turn_id)
        if tx is None: return fail(f'no transaction for {turn_id}', 404)
        return {'transaction': {**tx, 'files': [{'path': p, **diff_payload(s['before'], s['after'])}
                                                for p, s in tx['files'].items()]}}
    @rt('/agent/rollback-turn')
    async def agent_rollback_turn(req):
        d = await req.json()
        try: tx = ctx.ai.rollback_turn(d.get('turn_id') or '')
        except Exception as e: return fail(e)
        return {'ok': True, 'turn_id': tx['turn_id'], 'paths': list(tx['files']),
                'irreversible': tx['irreversible']}
    @rt('/agent/rollback-tool')
    async def agent_rollback_tool(req):
        "Rollback one snapshotted file call when its output is still the current file."
        d = await req.json()
        try: path = ctx.approvals.rollback((d.get('id') or '').strip())
        except Exception as e: return fail(e)
        return {'ok': True, 'path': path}
    @rt('/agent/approval/request')
    async def agent_approval_request(req):
        "Ask for a decision in this browser on behalf of an external Rishi session."
        try: d = await req.json()
        except Exception as e: return fail(f'approval request must be valid JSON: {e}')
        tc = d.get('tool_call') or {}
        fn = tc.get('function') or {} if isinstance(tc, dict) else {}
        name, args = fn.get('name'), fn.get('arguments', {})
        if args in (None, ''): args = {}
        if not name: return fail('tool_call.function.name is required')
        if isinstance(args, str):
            try: args = json.loads(args)
            except json.JSONDecodeError as e: return fail(f'tool_call.function.arguments is not valid JSON at position {e.pos}')
        if not isinstance(args, dict): return fail('tool_call.function.arguments must be an object')
        try: timeout = min(3600, max(1, float(d.get('timeout', ctx.approvals.timeout))))
        except (TypeError, ValueError): return fail('timeout must be a number of seconds')
        a = await off_loop(ctx.approvals.request, name, args, True, timeout)
        return {'ok': True, 'answer': a.dict()}
    @rt('/agent/approve')
    async def agent_approve(req):
        "Answer a pending approval. `note` is the reason, and the reason goes back to the model."
        d = await req.json()
        args = d.get('args')
        if args is not None and not isinstance(args, dict): return fail('tool arguments must be an object')
        tool = (d.get('tool') or '').strip() or None
        choices = {t.__name__: t for t in ctx.ai.tools}
        if tool and tool not in choices: return fail(f'unknown tool {tool}')
        if bool(d.get('ok')) and tool and args is not None:
            import inspect
            try: inspect.signature(choices[tool]).bind(**args)
            except TypeError as e: return fail(f'invalid {tool} arguments: {e}')
        a = ws.answer_approval(d.get('id') or '', bool(d.get('ok')), (d.get('note') or '').strip(),
                               session=bool(d.get('session')), tool=tool, args=args)
        if a is None: return fail('nothing is waiting for an answer')
        return {'ok': True, 'answer': a.dict()}
    @rt('/agent/command')
    async def agent_command(req):
        "Run a slash command (`/model`, `/cost`, `/compact`, `/skills`, `/tools`, `/reload`)."
        d = await req.json()
        line = (d.get('line') or '').strip()
        if not line: return {'ok': True, 'text': 'commands: ' + ', '.join('/' + c for c in ctx.ai.commands())}
        out = await off_loop(ctx.ai.command, line)
        if out is None: return fail(f'unknown command {line.split()[0]}')
        if line.lstrip('/').split(' ')[0] in ('tool-budget', 'steps'):
            ws.tool_budget, ws.step_budget = ctx.ai.tool_budget, ctx.ai.step_budget
            for agent in live_assistants(): agent.tool_budget, agent.step_budget = ws.tool_budget, ws.step_budget
            ws.save()
        return {'ok': True, 'text': out}
    @rt('/agent/ask')
    async def agent_ask(req):
        "One turn with the assistant."
        d = await req.json()
        q = (d.get('prompt') or '').strip()
        if not q: return fail('nothing to ask')
        a = ctx.ai
        text = await off_loop(ws.ask, q)
        return {'ok': a.ready, 'text': text, 'note': a.note,
                'activity': a.activity.rows(mark=a.activity._mark),
                'usage': a.turn_use.dict(), 'usage_label': repr(a.turn_use),
                'session_usage': a.use.dict(), 'session_usage_label': repr(a.use), 'model': a.model.name,
                'edits': edit_diffs(a)}
