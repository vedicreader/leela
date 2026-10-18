"The agent as routes: its threads, turns, approvals, budgets, memory and history."

from __future__ import annotations

import asyncio, json, os, re
from pathlib import Path

from fasthtml.common import JSONResponse, StreamingResponse
from fastcore.all import L, atomic_save, first, ifnone

from ... import errstr
from ...agent.agent import subject
from ...agent.core import model_note
from ...agent.runtime import estimate_tokens
from ...core.web import diff_payload, fail, off_loop, sse
from ...blocks.memory.memory import pii_gate
from ...workspace import STEP_RANGE, TOOL_RANGE
from .threads import TurnError
from .warm import NoDhrona, accept_round, assess_session, capture_round
from .turns import (edit_diffs, indexed_sessions, latest_started_here, project_state_context,
                    surfaces, tool_preview, tool_schemas, with_capabilities)

__all__ = ['CAPS', 'connect']

#: Attachment shapes a turn accepts beside a path. `Workspace._attachment_context` renders these.
ATTACH_KINDS = ('selection', 'vault')

CAPS = ('fs', 'memory', 'ai', 'inline_ai', 'docs', 'gate')

def connect(app, ctx):
    rt = app.route
    ws = ctx.session
    def _doc(): return ctx.docs.current()
    async def api(path, params=None, timeout=15):
        client = await ws.runtime()
        return await client.api(path, params, timeout) if client else None
    async def api_peek(path, params=None, timeout=15):
        "The runtime's inspector, but only where one is already running."
        client = ws.kernel_peek()
        return await client.api(path, params, timeout) if client else None

    def live_assistants():
        "Only the assistants already built -- reaching for `ctx.ai` here would construct one."
        rows = ws.threads.rows() if ws._threads is not None else []
        return L(*[t.ai for t in rows], ws._ai, ws._inline_ai).filter(lambda a: a is not None).unique()
    def refresh_assistants():
        for a in live_assistants(): a.refresh()
    def _set_agent_state(text, layer='task', enabled=True, source='user'):
        "State is the workspace's: every live conversation is re-briefed, not only the one on screen."
        out = ctx.ai.set_state(text, layer=layer, enabled=enabled, source=source)
        refresh_assistants()
        return out
    def _run_missing(t, run_id):
        return JSONResponse({'ok': False, 'code': 'run_not_found', 'thread': t.id, 'run': run_id,
                             'message': 'that run is not in this conversation'}, status_code=404)
    def _thread(target=''):
        "The conversation a request names, resolved once. Omitted means the one on screen now."
        target = str(target or '').strip()
        return ws.threads.require(target) if target else ws.threads.active
    def _thread_error(e):
        "Only a refusal is a conflict. Anything else is a bad request, or a bug wearing its own name."
        from .threads import TurnError
        if isinstance(e, TurnError): return JSONResponse(e.dict(), status_code=409)
        return fail(e, 400 if isinstance(e, (KeyError, ValueError)) else 500)
    def _grouped_history(ai, execution):
        "Every conversation in the log, without turns, computed once per state of the log."
        here = surfaces(getattr(ai, 'cfg', None))
        key = (ws.sessions_key(ai), repr(sorted(r.get('id', '') for r in execution)), len(here))
        # `ai.history` is the log's last 8 MB, a few dozen turns once pictures are pasted; the index covers it all
        if _history_cache.get('key') != key: _history_cache.update(key=key, groups=indexed_sessions(ws.logged_sessions(ai), execution, here))
        return _history_cache['groups']
    def _settled_thread(target=''):
        "The conversation a branch operation may act on."
        t = _thread(target)
        if t.state == 'working': raise TurnError('thread_busy', 'stop this conversation before reshaping it', t.id)
        if t.state == 'waiting': raise TurnError('thread_busy', 'answer the waiting checkpoint first', t.id)
        return t
    def _history_changed(t, held):
        return JSONResponse({'ok': False, 'code': 'history_changed', 'thread': t.id,
                             'message': f'this conversation moved to revision {held["revision"]}',
                             'revision': held['revision']}, status_code=409)
    def _branch_reply(t, branch, **extra):
        return {'ok': True, 'thread': t.id, 'active': t.ai.current_branch_id, **branch, **extra}
    def _branch_error(e, t=None):
        if isinstance(e, TurnError): return JSONResponse(e.dict(), status_code=409)
        code = 'branch_point_invalid' if isinstance(e, (KeyError, ValueError)) else 'branch_failed'
        if type(e).__name__ == 'BranchChanged': code = 'history_changed'
        return JSONResponse({'ok': False, 'code': code, 'message': errstr(e),
                             'thread': getattr(t, 'id', '')}, status_code=409 if t is not None else 400)
    _history_cache = {}
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
        "Resume a saved conversation as an isolated live thread."
        d = await req.json()
        session = str(d.get('session') or 'latest')
        if session == 'latest':
            await off_loop(ws.fresh_history, ws.ai)
            session = (first((s['id'] for s in ws.ai.sessions()), '') if d.get('everything') else latest_started_here(ws.ai)) or 'latest'
        try: thread = await off_loop(ws.threads.resume, session)
        except Exception as e:
            from .threads import TurnError
            return _thread_error(e) if isinstance(e, TurnError) else fail(e)
        # `ai.history` is the log's last 8 MB; the index reads this conversation's own byte range
        turns = [t for t in await off_loop(thread.ai.session_turns, thread.id) if t.get('model') != 'scripted']
        return {'ok': True, 'session': thread.id, 'note': thread.ai.note,
                'turns': with_capabilities(thread.ai, ws.with_timelines(turns))}
    @rt('/agent/threads')
    def agent_threads():
        active = ws.threads.active
        # `threads` hides an empty conversation, so `live` is what says a pane's own one still exists
        return {'active': active.id, 'threads': ws.threads.dicts(), 'live': [r.id for r in ws.threads.rows()],
                'attention': ws.threads.attention()}
    def _optin(names):
        "Opt-in group names as a tuple, checked against what this shalya offers; None stands for the workspace default."
        if names is None: return None
        from shalya.tools import OPTIN
        names = tuple(str(n) for n in (names if isinstance(names, (list, tuple)) else [names]))
        if unknown := [n for n in names if n not in OPTIN]:
            raise ValueError(f"unknown opt-in {', '.join(unknown)}; one of {', '.join(OPTIN)}")
        return names
    @rt('/agent/thread/new')
    async def agent_thread_new(req):
        "A fresh conversation; `warm` seeds it from dhrona's rounds, `optin` names its opt-in tool groups. An empty body is the old client: cold, on the workspace's opt-ins."
        d = await req.json() if int(req.headers.get('content-length') or 0) else {}
        try: optin, profile = _optin(d.get('optin')), _profile(d.get('profile'))
        except ValueError as e: return fail(e)
        try: thread = await off_loop(ws.threads.new, None, bool(d.get('warm')), optin, profile)
        except Exception as e: return _thread_error(e)
        return {'ok': True, 'active': thread.id, 'thread': thread.dict(), 'warm': thread.ai.warm, 'optin': list(thread.ai.optin),
                'profile': thread.ai.profile}
    def _profile(name):
        "One of ramabana's profiles, or None for the workspace default."
        from ...agent.core import PROFILES
        if name is None or name == '': return None
        if name not in PROFILES: raise ValueError(f'unknown profile {name!r}; one of {", ".join(PROFILES)}')
        return name
    @rt('/agent/profile')
    async def agent_profile(req):
        "How a new conversation here is briefed unless it says otherwise: `auto` (small for a local or ≤32k model), `small`, or `full`."
        d = await req.json()
        try: ws.agent_profile = _profile(d.get('profile')) or 'auto'
        except ValueError as e: return fail(e)
        ws.save()
        return {'ok': True, 'profile': ws.agent_profile, 'note': f'new conversations are briefed with the {ws.agent_profile} profile'}
    @rt('/agent/optin')
    async def agent_optin(req):
        "Which opt-in tool groups a new conversation here gets unless it says otherwise."
        d = await req.json()
        try: names = _optin(d.get('optin')) or ()
        except ValueError as e: return fail(e)
        ws.agent_optin = names; ws.save()
        return {'ok': True, 'optin': list(names), 'note': f"new conversations opt into {', '.join(names) or 'nothing'} by default"}
    @rt('/agent/thread/switch')
    async def agent_thread_switch(req):
        d = await req.json()
        try: thread = ws.threads.switch(str(d.get('thread') or ''))
        except Exception as e: return _thread_error(e)
        return {'ok': True, 'active': thread.id, 'thread': thread.dict()}
    @rt('/agent/thread/close')
    async def agent_thread_close(req):
        d = await req.json()
        try: closed = await off_loop(ws.threads.close, str(d.get('thread') or ''))
        except Exception as e: return _thread_error(e)
        return {'ok': True, 'closed': closed, 'active': ws.threads.active_id, 'threads': ws.threads.dicts()}
    @rt('/agent/thread/mute')
    async def agent_thread_mute(req):
        "Silence one conversation's notifications without hiding that it is waiting."
        d = await req.json()
        try: thread = ws.threads.mute(str(d.get('thread') or ''), bool(d.get('muted', True)))
        except Exception as e: return _thread_error(e)
        return {'ok': True, 'thread': thread.dict(), 'attention': ws.threads.attention()}
    @rt('/agent/thread/turns')
    async def agent_thread_turns(thread: str = ''):
        "One conversation's durable turns, and the point in its feed a live turn replays from."
        try: t = _thread(thread)
        except Exception as e: return _thread_error(e)
        await off_loop(ws.fresh_history, t.ai)
        turns = [r for r in t.ai.history if r.get('session') == t.id]
        # `dict` is where a summarised name lives; `title` alone is only what a person typed
        row = t.dict()
        return {'ok': True, 'thread': t.id, 'state': row['state'], 'seq': t.feed.settled_seq,
                'title': row['title'], 'turns': with_capabilities(t.ai, ws.with_timelines(turns)),
                # the warm-start block repaints from here: what was replayed, and why the rest was not
                'warm': t.ai.warm_report if t.ai.warm and t.ai._warmed else None, 'warm_on': bool(t.ai.warm)}
    def _round_dir():
        "Review notebooks live in the workspace, where `/tab/open` can reach them: `<first root>/.dhrona/`."
        root = first(ws.fs.roots)
        if root is None: raise ValueError('open a folder first: review notebooks live in its .dhrona/')
        return Path(root)/'.dhrona'
    def _review_source(source):
        "The notebook `accept` may act on: dhrona saves it and writes beside it, so only one under `.dhrona/` will do."
        p = Path(str(source or '')).expanduser().resolve()
        if p.suffix != '.ipynb' or _round_dir().resolve() not in p.parents:
            raise ValueError(f'source must be a review notebook under {_round_dir()}')
        return p
    @rt('/agent/thread/assess')
    async def agent_thread_assess(req):
        "dhrona's score and findings for one conversation, each finding tagged with its turn."
        d = await req.json()
        try: t = _thread(d.get('thread')); await off_loop(ws.fresh_history, t.ai)
        except Exception as e: return _thread_error(e)
        try: return {'ok': True, 'thread': t.id, **await off_loop(assess_session, t.ai.history_path, t.id)}
        except NoDhrona as e: return fail(e, 501)
        except Exception as e: return fail(e, 400)
    @rt('/agent/thread/capture')
    async def agent_thread_capture(req):
        "One conversation as a dhrona review notebook under `.dhrona/`, named after the conversation unless told otherwise."
        d = await req.json()
        try: t = _thread(d.get('thread')); await off_loop(ws.fresh_history, t.ai)
        except Exception as e: return _thread_error(e)
        name = re.sub(r'[^a-z0-9]+', '-', str(d.get('name') or t.name() or t.id).lower()).strip('-')[:40] or t.id
        try: path = await off_loop(capture_round, t.ai.history_path, t.id, _round_dir()/f'{name}.ipynb', name)
        except NoDhrona as e: return fail(e, 501)
        except ValueError as e: return fail(e, 400)     # no completed turns, or an ambiguous session
        return {'ok': True, 'thread': t.id, 'path': path, 'name': name}
    @rt('/agent/round/accept')
    async def agent_round_accept(req):
        "Accept a reviewed notebook into the rounds library; the next warm conversation may replay it."
        d = await req.json()
        # no fallback to `$USER`: accepting is a person putting their name to the round
        try: path = await off_loop(accept_round, _review_source(d.get('source')), str(d.get('reviewer') or '').strip())
        except NoDhrona as e: return fail(e, 501)
        except (ValueError, FileNotFoundError) as e: return fail(e, 400)
        return {'ok': True, 'installed': path}
    @rt('/agent/thread/title')
    async def agent_thread_title(req):
        d = await req.json()
        try: thread = await off_loop(ws.threads.title, str(d.get('thread') or ''), d.get('title') or '')
        except Exception as e: return _thread_error(e)
        return {'ok': True, 'thread': thread.dict()}
    @rt('/agent/new')
    async def agent_new():
        try: thread = await off_loop(ws.threads.new)
        except Exception as e: return _thread_error(e)
        return {'ok': True, 'session': thread.id}
    @rt('/agent/history')
    async def agent_history(thread: str = '', everything: bool = False):
        "Leela's durable conversations, newest first, without their turns. `everything` adds the CLI's."
        try: t = _thread(thread)
        except Exception as e: return _thread_error(e)
        ai = t.ai
        execution = await api_peek('/agent/api/sessions') or {'sessions': []}
        await off_loop(ws.fresh_history, ai)
        groups = _grouped_history(ai, execution.get('sessions', []))
        theirs = len([g for g in groups if g.get('app') != 'leela'])
        if not everything: groups = [g for g in groups if g.get('app') == 'leela']
        return {'sessions': groups, 'model': ai.model.name, 'current': ai.session_id,
                'thread': t.id, 'only_leela': not everything, 'hidden': 0 if everything else theirs}
    @rt('/agent/history/session')
    async def agent_history_session(id: str = '', thread: str = ''):
        "One stored conversation's turns, fetched when it is opened rather than with the list."
        try: t = _thread(thread)
        except Exception as e: return _thread_error(e)
        await off_loop(ws.fresh_history, t.ai)
        execution = await api('/agent/api/sessions') or {'sessions': []}
        group = first(g for g in _grouped_history(t.ai, execution.get('sessions', []))
                      if g['id'] == str(id))
        if group is None: return fail(f'no such conversation {id}', 404)
        turns = ws.with_timelines([r for r in await off_loop(t.ai.session_turns, group['id']) if r.get('model') != 'scripted'])
        return {'ok': True, **group, 'count': len(turns), 'turns': with_capabilities(t.ai, turns)}
    @rt('/agent/models')
    def agent_models(legacy: bool = True, refresh: bool = False):
        "Every model the picker offers, and which one each routed job is on."
        from ...agent.core import DFLT_SMALL, DFLT_TURN, available_models, auth_status, resolve
        from .models import JOB_HELP, catalog, forget_probes, load_models, mark_models, probed, runtimes
        notes = {}
        def _try(what, f, dflt=None):
            "`f()`, or `dflt` and a note saying why: no one failure may blank the picker."
            try: return f()
            except Exception as e: notes[what] = errstr(e); return dflt
        # `selected` and the dedupe both resolve every row, so the same name is asked for many
        # times in one request. Once each.
        _specs = {}
        def _spec(name):
            if name not in _specs: _specs[name] = _try(name, lambda: resolve(name))
            return _specs[name]
        def _name(what, get, dflt): return _try(what, get, dflt) or dflt
        saved = _try('saved models', load_models, []) or []
        # The catalog and the id each row resolves to are the machine's, not this workspace's.
        # Probed together, served from the last answer, refreshed behind this. `catalog2` since ramabana
        # 0.1.42 owns the catalog: a list saved under the old key would hide the current models.
        if refresh: forget_probes(disk=True)   # the button means ask again, not read the last answer
        rows, by_id = _try('model catalog', lambda: probed(f'catalog2:{legacy}',
                                                           lambda: catalog(legacy)), ([], {})) or ([], {})
        rows = [dict(r) for r in rows]      # decorated below with this workspace's own choices
        rows += [{'value':x['name'],'label':x['name'],'provider':x['runtime'],
                  'source':f"saved · {x['model_id']}",'custom':True} for x in saved]
        agent_dflt = ws.model or os.environ.get('LEELA_MODEL') or DFLT_TURN
        agent = _name('agent model', lambda: ctx.ai.model.name, agent_dflt) if ws._ai is not None else agent_dflt
        inline_dflt = ws.inline_model or os.environ.get('LEELA_MODEL_INLINE') or DFLT_SMALL
        inline = (_name('inline model', lambda: ctx.inline_ai.model.name, inline_dflt)
                  if ws._inline_ai is not None else inline_dflt)
        completion_dflt = ws.completion_model or os.environ.get('LEELA_MODEL_COMPLETION') or DFLT_SMALL
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
            if spec.model_id not in by_id:
                provider = spec.model_id.partition('/')[0] if not spec.local else spec.runtime
                rows.append({'value': current, 'label': current, 'provider': provider,
                             'source': 'saved choice · provider credentials may be required'})
        def selected(current):
            "Which row a chosen model is, by the id it resolves to. A lookup, not a scan."
            spec = _spec(current)
            return current if spec is None else by_id.get(spec.model_id, current)
        # The routed jobs with no field of their own, reported chosen or not.
        from ...agent.core import JOBS, Routing
        routing = ctx.ai.routing if ws._ai is not None else Routing(turn=agent)
        if ws._ai is None:   # `set`, so a saved choice counts as chosen and a local turn does not hide it
            for j, n in (ws.job_models or {}).items(): _try(f'{j} model', lambda j=j, n=n: routing.set(n, j))
        # `**jobs` is spread last, and `inline` has a field of its own.
        jobs = {j: _name(f'{j} model', lambda j=j: routing.name_for(j), '')
                for j in JOBS if j not in ('turn', 'completion', 'inline')}
        # The catalog's rows are marked already; only the saved aliases and the rows added for
        # an unavailable choice still need it.
        return {'models': mark_models(rows), 'saved':saved, 'notes': notes,
                # Asking every account whether it is signed in is the other slow half.
                'auth': _try('auth', lambda: probed('auth', auth_status), {}) or {},
                # What is installed here, which is a second cold and another machine-wide answer.
                'runtimes': _try('runtimes', lambda: probed('runtimes', runtimes), []) or [],
                'jobs': jobs, 'job_help': JOB_HELP,
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
    @rt('/agent/setup')
    def agent_setup():
        "The first-run choice: what already works here, and what a download would add."
        from .models import setup_plan
        try: return {'ok': True, **setup_plan()}
        except Exception as e: return fail(e)
    @rt('/agent/setup/dismiss')
    async def agent_setup_dismiss(req):
        "Answered, so stop offering it. Reopening it is the runtimes control in settings."
        from .models import dismiss_setup
        try: return {'ok': True, 'dismissed': dismiss_setup(bool((await req.json()).get('dismissed', True)))}
        except Exception as e: return fail(e)
    @rt('/agent/updates')
    def agent_updates():
        "What is installed here with a newer release, and whether this Leela has one."
        from .models import updates
        try: return {'ok': True, **updates()}
        except Exception as e: return fail(e)
    @rt('/agent/runtimes')
    def agent_runtimes():
        "The backends and what each is doing, for the pane to poll while one installs."
        from .models import runtimes
        try: return {'ok': True, 'runtimes': runtimes()}
        except Exception as e: return fail(e)
    @rt('/agent/runtimes/install')
    async def agent_runtimes_install(req):
        "Start fetching one on-device backend. Returns at once; the row carries the state."
        from .models import install_runtime
        try: return {'ok': True, 'install': install_runtime(str((await req.json()).get('runtime') or ''))}
        except Exception as e: return fail(e)
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
    @rt('/agent/vault-pii')
    async def agent_vault_pii(req):
        "What a vault retrieval hands the model: everything, masked identifiers, or nothing at all."
        d = await req.json()
        try: policy = pii_gate(d.get('pii'))
        except ValueError as e: return fail(e)
        ws.vault_pii = policy; ws.save()
        said = {'off': 'the model reads the vault as it is',
                'redact': 'identifiers are masked before the model sees them',
                'refuse': 'sections holding personal information are withheld from the model'}
        return {'ok': True, 'pii': policy, 'note': said[policy]}
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
            note = model_note(spec) + (f' · {assistant.profile} profile' if job == 'turn' else '')   # what the turn model resolves `auto` to
            return {'ok': True, 'target': target, 'model': spec.name, 'note': note}
        except Exception as e: return fail(e)
    @rt('/agent/memory')
    async def agent_memory():
        "Editable notes and their explicit per-model session routing."
        notes = await off_loop(ctx.memory.agent_notes)
        rows = [{**note, 'text': await off_loop(ctx.memory.exact_text, str(note['id']))} for note in notes]
        return {'notes': rows, 'selected': ws.agent_memory_selection,
                'targets': {'agent': 'Agent conversation', 'inline': 'Prompt cells and inline AI',
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
    def _state_origin(state):
        "One saved state with where it came from: its layer, its folders, and whether they are ours."
        agent = dict(((state.get('meta') or {}).get('agent') or {}))
        roots = [str(r) for r in (agent.get('roots') or [])]
        def resolved(paths):
            out = set()
            for r in paths:
                try: out.add(str(Path(r).expanduser().resolve()))
                except (OSError, ValueError): out.add(str(r))
            return out
        mine = resolved(roots) == resolved(str(r) for r in ctx.fs.roots) if roots else False
        return {**state, 'layer': str(agent.get('layer') or ''), 'roots': roots,
                'where': ', '.join(Path(r).name for r in roots), 'mine': mine,
                'revision': agent.get('revision') or 0}
    @rt('/agent/states')
    def agent_states(scope: str = 'everywhere'):
        "Saved states, each saying where it came from, and the state now in the briefing."
        active = any(str(layer.get('text') or '').strip() and layer.get('enabled', True)
                     for layer in ws.agent_state_layers.values())
        states = [_state_origin(s) for s in ctx.memory.agent_states()]
        if scope == 'project': states = [s for s in states if s['mine']]
        return {'active': active, 'active_text': ws.agent_state, 'scope': scope,
                'layers': ws.agent_state_layers, 'states': states,
                'layers_seen': sorted({s['layer'] for s in states if s['layer']})}
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
        layer = (d.get('layer') or 'task').strip()
        # The layer is saved with the state: which of organization, project or task a charter was
        # written for is most of what makes somebody else's reusable.
        saved = await off_loop(ctx.memory.remember_agent_state, title, text,
                                 {'session': ctx.ai.session_id if ws._ai is not None else '',
                                  'turns': len(ctx.ai.history) if ws._ai is not None else 0,
                                  'layer': layer,
                                  'roots': [str(root) for root in ctx.fs.roots]})
        if not saved: return fail(ctx.memory.note)
        if d.get('activate', True): _set_agent_state(text, layer=layer, source='memory')
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
        try: _set_agent_state(text, layer=layer, enabled=d.get('enabled', True), source='user')
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
        try: _set_agent_state(text, layer=layer, source='memory')
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
            'tools': [{'name': t.__name__, 'help': describe(t)} for t in ctx.ai._plain],
            'skills': [{'name': s.name, 'help': s.description} for s in ctx.ai.skills],
        }
    @rt('/agent/status')
    def agent_status(thread: str = ''):
        "Whether the assistant is loaded, what model it is on, and what it is doing right now."
        try: t = _thread(thread)
        except Exception as e: return _thread_error(e)
        held = t.runner.held()
        return {**t.ai.status(), 'thread': t.id, 'held': held, **({'busy': True} if held else {})}
    @rt('/agent/stop')
    async def agent_stop(req):
        "Cancel the foreground root run of one conversation, and clear a start that never arrived."
        try:
            d = await req.json()
        except Exception: d = {}
        try: t = _thread(d.get('thread'))
        except Exception as e: return _thread_error(e)
        try: return {'ok': True, 'thread': t.id, **t.runner.stop((d.get('run_id') or '').strip(), ai=t.ai)}
        except Exception as e: return {'ok': False, 'error': errstr(e), 'thread': t.id}
    @rt('/agent/runs')
    def agent_runs(thread: str = ''):
        try: t = _thread(thread)
        except Exception as e: return _thread_error(e)
        return {'thread': t.id, 'runs': t.ai.runs(active=True)}
    @rt('/agent/runs/{run_id}/cancel')
    def agent_run_cancel(run_id: str, thread: str = ''):
        try: t = _thread(thread)
        except Exception as e: return _thread_error(e)
        if t.ai.run(run_id) is None: return _run_missing(t, run_id)
        try: return {'ok': True, 'thread': t.id, **t.ai.cancel(run_id)}
        except Exception as e: return {'ok': False, 'error': errstr(e), 'thread': t.id}
    @rt('/agent/runs/{run_id}/terminate')
    def agent_run_terminate(run_id: str, thread: str = ''):
        try: t = _thread(thread)
        except Exception as e: return _thread_error(e)
        if t.ai.run(run_id) is None: return _run_missing(t, run_id)
        try: return {'ok': True, 'thread': t.id, **t.ai.terminate(run_id)}
        except Exception as e: return {'ok': False, 'error': errstr(e), 'thread': t.id}
    @rt('/agent/runs/{run_id}/steer')
    async def agent_run_steer(req, run_id: str):
        "Say one thing to a delegated sub-agent, delivered on its next tool result."
        try: d = await req.json()
        except Exception: return fail('steer body must be JSON')
        try: t = _thread(str(d.get('thread') or ''))
        except Exception as e: return _thread_error(e)
        run = t.ai.run(run_id)
        if run is None: return _run_missing(t, run_id)
        text = str(d.get('text') or '').strip()
        if not text: return fail('nothing to say to it')
        if run.terminal:
            return JSONResponse({'ok': False, 'code': 'run_over', 'thread': t.id, 'run': run_id,
                                 'message': f'that sub-agent is {run.state} and will read nothing more'},
                                status_code=409)
        note = t.ai.tell(run_id, text)
        if not note.startswith('told'): return fail(note)
        return {'ok': True, 'thread': t.id, 'note': note, **run.dict()}
    @rt('/agent/subagents')
    def agent_subagents(action_id: str = '', thread: str = '', limit: int = 40):
        "One delegation: the call that asked, what its sub-agents did as a tree of nested delegations, and the runs still going."
        try: t = _thread(thread)
        except Exception as e: return _thread_error(e)
        rows = t.ai.activity.rows()
        under, delegations = {}, {r.get('id') for r in rows if r.get('kind') == 'delegate'}
        for r in rows: under.setdefault(r.get('parent_action_id') or '', []).append(r)
        def tree(d): return {**d, 'calls': [tree(c) if c.get('kind') == 'delegate' else c for c in under.get(d.get('id'), [])]}
        # a nested delegation is drawn under the one that asked, not again at the top
        wanted = [r for r in rows if r.get('kind') == 'delegate'
                  and (r.get('id') == action_id if action_id else r.get('parent_action_id') not in delegations)]
        # newest first and bounded: recording every sub-agent call makes a session's whole stream
        # far larger than it was, and this is polled while a delegation is running
        wanted = list(reversed(wanted))[:max(1, limit)]
        def flat(runs):
            return [x for r in runs for x in (r, *flat(r.get('children') or []))]
        # `runs(active=True)` keeps a live root's finished children, which are not running now
        live = [r for r in flat(t.ai.runs(active=True))
                if r.get('kind') == 'child' and r.get('state') in ('pending', 'running', 'cancelling')]
        return {'ok': True, 'thread': t.id,
                'delegations': [tree(d) for d in wanted],
                'runs': live, 'records_sub_calls': any(r.get('parent_action_id') for r in rows)}
    async def _warm_runtime():
        "Start a kernel for the turn about to run, and let a failure be the tool's to report."
        try: await ws.runtime()
        except Exception: pass

    @rt('/agent/turn')
    async def agent_turn(req):
        try: d = await req.json()
        except Exception: return fail('turn body must be JSON')
        if not isinstance(d, dict): return fail('turn body must be a JSON object')
        if not isinstance(d.get('prompt', ''), str): return fail('prompt must be text')
        q = (d.get('prompt') or '').strip()
        if not q: return fail('nothing to ask')
        attachments = d.get('attachments') or []
        if not isinstance(attachments, list): return fail('attachments must be a JSON array')
        #: A path, or one of the shapes `Workspace._attachment_context` already renders. The guard
        #: took strings only, so every selection and vault ref the pane sends answered 400.
        if not all(isinstance(ref, str) or (isinstance(ref, dict) and ref.get('kind') in ATTACH_KINDS)
                   for ref in attachments):
            return fail(f'an attachment is a path, or an object whose kind is one of {", ".join(ATTACH_KINDS)}')
        if not isinstance(d.get('reasoning', ''), str): return fail('reasoning must be text')
        reasoning = (d.get('reasoning') or '').lower()
        if reasoning not in ('', 'auto', 'low', 'medium', 'high'):
            return fail('reasoning must be auto, low, medium or high')
        reasoning = None if reasoning in ('', 'auto') else reasoning
        nb = _doc()
        context = nb.context(len(nb)) if nb is not None else ''
        context_path = nb.path if nb is not None else ''
        # the browser names the conversation it is looking at; the active one is only a default,
        # and a switch in another tab must not move this turn
        try: runner = _thread(d.get('thread')).runner
        except Exception as e: return _thread_error(e)
        try: grounding = await off_loop(ws.prepare_turn, attachments, context)
        except Exception as e: return fail(e)
        # Started here, on the loop that owns the kernels, so the first tool call meets a live one.
        if ws.runtime_peek() is None: asyncio.ensure_future(_warm_runtime())
        try: return await off_loop(runner.start, q, attachments, reasoning,
                                    context, context_path, grounding)
        except Exception as e:
            from .threads import TurnError
            if isinstance(e, TurnError): return JSONResponse(e.dict(), status_code=409)
            return fail(e, 409)
    @rt('/agent/stream')
    async def agent_stream(req):
        try: since = max(0, int(req.query_params.get('since') or 0))
        except ValueError: return fail('since must be an integer')
        try: th = _thread(req.query_params.get('thread'))
        except Exception as e: return _thread_error(e)
        feed = th.feed
        follow = req.query_params.get('follow') in ('1', 'true', 'yes')
        async def events():
            seq, ended = since, False
            while not feed.closed and (follow or not feed.finished(seq)):
                # the feed wakes this loop directly: a subscriber must not hold a shared worker.
                # a finite replay polls briefly and breaks when caught up; only `follow` keeps the 15s keepalive
                rows = await feed.anext(seq, 1 if ended else (0.1 if not follow else 15))
                if await req.is_disconnected(): break
                if not rows:
                    # A finite replay ends at settlement. Neither a producer that never settles nor
                    # a conversation with no turn in flight leaves one waiting for something else.
                    if not follow and (ended or th.state != 'working'): break
                    yield ': keepalive\n\n'
                    continue
                for row in rows:
                    seq = max(seq, row['seq'])
                    ended = ended or row['event'] == 'done'
                    yield sse(row['event'], {'seq': row['seq'], **row['data']})
                if rows[-1]['event'] == 'resync': break
        return StreamingResponse(events(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    @rt('/agent/approval')
    def agent_approval(thread: str = ''):
        "The call waiting for a person, or None. It stays inline so the rest of the IDE remains usable."
        try: t = _thread(thread)
        except Exception as e: return _thread_error(e)
        # A prompt cell runs on the inline assistant, which the pane cannot otherwise see. Its
        # approval is still a person's to answer, and this is where a person is looking.
        holder, a = t.approvals, t.approvals.pending
        if a is None and (nb_pending := ws._notebook_approvals.pending) is not None:
            holder, a = ws._notebook_approvals, nb_pending
        source = t.ai if holder is t.approvals else ws.inline_ai
        pending = ({**a.dict(), 'schemas': tool_schemas(source)} if a is not None else None)
        return {'thread': t.id, 'pending': pending, 'waiting': ws.threads.waiting(),
                'surface': 'notebook' if holder is not t.approvals else 'agent',
                'control': getattr(holder, 'control', 'guided')}
    @rt('/agent/control')
    async def agent_control(req):
        "Choose how often tool proposals become editable checkpoints."
        d = await req.json()
        try: th = _thread(d.get('thread'))
        except Exception as e: return _thread_error(e)
        want = (d.get('control') or '').strip()
        try: control = th.approvals.set_control('autopilot' if want == 'edits' else want)
        except ValueError as e: return fail(e)
        note = th.approvals.set_mode('edits') if want == 'edits' else (th.approvals.set_mode(ws.approvals_mode) if th.approvals.mode == 'edits' else '')
        return {'ok': True, 'thread': th.id, 'control': want if want == 'edits' else control, 'mode': th.approvals.mode, 'note': note}
    @rt('/agent/run-policy')
    async def agent_run_policy(req):
        "Run through bounded future calls, or pause immediately after the current one."
        d = await req.json()
        try: th = _thread(d.get('thread'))
        except Exception as e: return _thread_error(e)
        if d.get('policy') == 'pause':
            th.approvals.set_pause_next()
            return {'ok': True, 'thread': th.id, **th.approvals.state()}
        try: policy = th.approvals.set_run_policy(d.get('policy') or 'once', d.get('count') or 1)
        except (ValueError, TypeError) as e: return fail(e)
        return {'ok': True, 'thread': th.id, 'policy': policy, **th.approvals.state()}
    @rt('/agent/steer')
    async def agent_steer(req):
        "Queue guidance after the current tool; the next proposed call is skipped and replaced by it."
        d = await req.json()
        text = (d.get('text') or '').strip()
        try: th = _thread(d.get('thread'))
        except Exception as e: return _thread_error(e)
        # The run this steer belongs to. Without it `Feed.for_run` cannot keep the event, and a
        # steer is missing from the turn the moment the pane is rebuilt from the server.
        here = getattr(th.ai.run(), 'id', '') or ''
        if d.get('cancel'):
            th.approvals.queue_steer('')
            state = th.approvals.state()
            th.feed.emit('steer', {'text': '', 'cancelled': True, **state, 'run': here})
            return {'ok': True, 'thread': th.id, **state}
        if not text: return fail('steering instruction is empty')
        if d.get('force'):
            from .threads import TERMINAL_CANCEL
            busy = bool(th.ai.runs(active=True))
            try: run = th.ai.cancel()
            except Exception as e: return fail(errstr(e))
            # nothing was running: the draft is an ordinary turn, not a cancellation that failed
            if busy and run.get('state') not in TERMINAL_CANCEL:
                return JSONResponse({'ok': False, 'code': 'cancellation_incomplete',
                                     'message': f"run is {run.get('state', 'cancelling')}",
                                     'thread': th.id, 'run': run}, status_code=409)
            state = th.approvals.state()
            th.feed.emit('steer', {'text': text, 'forced': True, 'cancelled': run, **state, 'run': here})
            return {'ok': True, 'thread': th.id, 'forced': True, 'run': run, 'text': text, **state}
        th.approvals.queue_steer(text)
        state = th.approvals.state(); th.feed.emit('steer', {'text': text, **state, 'run': here})
        return {'ok': True, 'thread': th.id, **state}
    @rt('/agent/tool-preview')
    async def agent_tool_preview(req):
        "Preview the resolved call without executing it."
        d = await req.json()
        tool, args = (d.get('tool') or '').strip(), d.get('args')
        try: ai = _thread(d.get('thread')).ai
        except Exception as e: return _thread_error(e)
        if tool not in {t.__name__ for t in ai.tools}: return fail(f'unknown tool {tool}')
        if not isinstance(args, dict): return fail('tool arguments must be an object')
        try: return {'ok': True, 'preview': tool_preview(ai, tool, args)}
        except Exception as e: return fail(e)
    @rt('/agent/branches')
    def agent_branches(thread: str = ''):
        "Where a conversation can be branched, and every branch it already has."
        try: t = _thread(thread)
        except Exception as e: return _thread_error(e)
        a = t.ai
        return {'thread': t.id, 'active': a.current_branch_id, 'branches': a.branches(),
                'turns': [{'turn_id': tid, 'branch_id': cp.get('branch_id', 'main'),
                           'before': 'before' in cp, 'after': 'after' in cp}
                          for tid, cp in a.checkpoints.items()]}
    @rt('/agent/branch/parts')
    def agent_branch_parts(turn_id: str = '', stage: str = 'after', thread: str = ''):
        "One conversation as the ordered parts a person can branch from or shape."
        try: t = _thread(thread)
        except Exception as e: return _thread_error(e)
        try: return {'ok': True, 'thread': t.id, 'turn_id': turn_id, 'stage': stage,
                     'parts': t.ai.context_parts(turn_id, stage)}
        except Exception as e: return _branch_error(e, t)
    @rt('/agent/fork')
    async def agent_fork(req):
        "Restore a checkpoint, or a part inside one, as a new active conversation branch."
        d = await req.json()
        try: t = _settled_thread(d.get('thread'))
        except Exception as e: return _branch_error(e)
        try: branch = t.ai.fork(d.get('turn_id') or '', d.get('stage') or 'after',
                                d.get('branch_id') or '', str(d.get('part_id') or ''),
                                d.get('manifest') or None)
        except Exception as e: return _branch_error(e, t)
        return _branch_reply(t, branch)
    @rt('/agent/branch/switch')
    async def agent_branch_switch(req):
        "Make another branch active by rebuilding its context, not by copying a conversation."
        d = await req.json()
        try: t = _settled_thread(d.get('thread'))
        except Exception as e: return _branch_error(e)
        try: branch = t.ai.switch_branch(str(d.get('branch_id') or ''))
        except Exception as e: return _branch_error(e, t)
        return _branch_reply(t, branch)
    @rt('/agent/undo-turn')
    async def agent_undo_turn(req):
        "Undo a turn from the conversation: a branch that stops before it."
        d = await req.json()
        try: t = _settled_thread(d.get('thread'))
        except Exception as e: return _branch_error(e)
        turns = [str(x) for x in (d.get('turn_ids') or []) if str(x)] or [str(d.get('turn_id') or '')]
        order = list(t.ai.checkpoints)
        unknown = [tid for tid in turns if tid not in order]
        if unknown:
            return JSONResponse({'ok': False, 'code': 'branch_point_invalid', 'thread': t.id,
                                 'message': f'no captured turn boundary for {unknown[0]}'}, status_code=409)
        earliest = min(turns, key=order.index) if turns else ''
        try: branch = t.ai.undo_turn(earliest, d.get('branch_id') or '')
        except Exception as e: return _branch_error(e, t)
        return _branch_reply(t, branch, undone=turns, files_restored=None)
    @rt('/agent/conversation/parts')
    def agent_conversation_parts(thread: str = '', session: str = ''):
        "One stored conversation as the ordered parts a person can keep, drop or rewrite."
        try: th = _thread(thread)
        except Exception as e: return _thread_error(e)
        try: parts = th.ai.conversation_parts(session or None)
        except Exception as e: return _branch_error(e, th)
        return {'ok': True, 'thread': th.id, 'session': session or th.id, 'parts': parts,
                'branch_id': th.ai.current_branch_id,
                'revision': th.ai.branch_meta(th.ai.current_branch_id)['revision']}
    @rt('/agent/conversation/notebook')
    async def agent_conversation_notebook(req):
        "Write one conversation out as a notebook a person can edit like any other."
        d = await req.json() if req.method == 'POST' else {}
        try: th = _thread(d.get('thread'))
        except Exception as e: return _thread_error(e)
        session = str(d.get('session') or th.id)
        try: parts = th.ai.conversation_parts(session)
        except Exception as e: return _branch_error(e, th)
        if not parts: return fail('this conversation has no recorded turns to edit', 404)
        from ..nb.nb import Cell, Notebook
        held = th.ai.branch_meta(th.ai.current_branch_id)
        head = (f'# Reshape this conversation\n\n'
                f'Conversation `{session}` as {len(parts)} parts. Edit the **you** and **agent** '
                f'cells to change what the model remembers. Delete any cell to drop that part; a '
                f'call and its result go together. Save, then apply from the agent pane.\n\n'
                f'_Nothing here changes the recorded conversation._')
        cells = [Cell(source=head, cell_type='markdown')]
        for part in parts:
            label = {'user': 'you', 'assistant': 'agent', 'call': 'call', 'result': 'result'}[part['kind']]
            body = f'<!-- {label} · {part["part_id"]} -->\n{part["text"]}'
            cell = Cell(source=body, cell_type='markdown')
            cell.approval = {'kind': 'reshape', 'part_id': part['part_id'], 'part_kind': part['kind'],
                             'editable': part['editable'], 'group': part['group']}
            cells.append(cell)
        nb = Notebook(cells)
        name = f'reshape-{session.replace(":", "-")}.ipynb'
        path = str(Path(ws.cwd_for())/name)
        try: nb.save(path)
        except Exception as e: return fail(e)
        return {'ok': True, 'thread': th.id, 'session': session, 'path': path,
                'parts': len(parts), 'branch_id': held['branch_id'], 'revision': held['revision']}
    @rt('/agent/conversation/reshape')
    async def agent_conversation_reshape(req):
        "Read an edited notebook back as one reshaped branch."
        d = await req.json()
        try: th = _settled_thread(d.get('thread'))
        except Exception as e: return _branch_error(e)
        session, path = str(d.get('session') or th.id), str(d.get('path') or '')
        if not path: return fail('name the notebook to read the edits from')
        from ..nb.nb import Notebook
        try: nb = ctx.docs.docs.get(path) or Notebook.load(path)
        except Exception as e: return fail(e)
        try: parts = th.ai.conversation_parts(session)
        except Exception as e: return _branch_error(e, th)
        seen = {}
        for cell in nb:
            # the notebook format renames `kind` on save, so the part id is what identifies a cell
            meta = getattr(cell, 'approval', None) or {}
            part_id = str(meta.get('part_id') or '')
            if not part_id: continue
            body = str(cell.source or '')
            seen[part_id] = body.split('\n', 1)[1] if body.startswith('<!--') and '\n' in body else body
        # a notebook with no part cells is one we failed to read, not a conversation to erase
        if not seen:
            return JSONResponse({'ok': False, 'code': 'branch_point_invalid', 'thread': th.id,
                                 'message': 'no conversation parts found in that notebook; nothing was changed'},
                                status_code=409)
        manifest = {p['part_id']: 'discard' for p in parts if p['part_id'] not in seen}
        rewrites = {p['part_id']: seen[p['part_id']] for p in parts
                    if p['editable'] and p['part_id'] in seen and seen[p['part_id']] != p['text']}
        held = th.ai.branch_meta(str(d.get('branch_id') or th.ai.current_branch_id))
        if d.get('revision') is not None and int(d['revision']) != int(held['revision']):
            return _history_changed(th, held)
        try: branch = th.ai.reshape(session, manifest, rewrites)
        except Exception as e: return _branch_error(e, th)
        return _branch_reply(th, branch, discarded=sorted(manifest), rewritten=sorted(rewrites))
    @rt('/agent/history/preview')
    async def agent_history_preview(req):
        "What reshaping this conversation would send, before anything is written."
        d = await req.json()
        try: th = _thread(d.get('thread'))
        except Exception as e: return _thread_error(e)
        base = str(d.get('branch_id') or th.ai.current_branch_id)
        held = th.ai.branch_meta(base)
        if d.get('revision') is not None and int(d['revision']) != int(held['revision']):
            return _history_changed(th, held)
        try: compiled = th.ai.compile_conversation(d.get('session') or None,
                                                  d.get('manifest') or None, d.get('rewrites') or None)
        except Exception as e: return _branch_error(e, th)
        text = '\n'.join(str(m.get('content') or '') for m in compiled['messages'])
        return {'ok': True, 'thread': th.id, 'branch_id': base, 'revision': held['revision'],
                'next_revision': held['revision'] + 1, 'parts': compiled['parts'],
                'groups': compiled['groups'], 'adjusted': compiled['adjusted'],
                'rewritten': compiled['rewritten'], 'kept': compiled['kept'],
                'omitted': compiled['omitted'], 'messages': len(compiled['messages']),
                'tokens': max(1, len(text) // 4) if text else 0}
    @rt('/agent/history/apply')
    async def agent_history_apply(req):
        "Commit a reshaped conversation as a new branch, revalidated at the revision it was shown."
        d = await req.json()
        try: th = _settled_thread(d.get('thread'))
        except Exception as e: return _branch_error(e)
        base = str(d.get('branch_id') or th.ai.current_branch_id)
        if d.get('revision') is None: return fail('a reshaped branch needs the revision it was previewed at')
        held = th.ai.branch_meta(base)
        if int(d['revision']) != int(held['revision']): return _history_changed(th, held)
        try: branch = th.ai.reshape(d.get('session') or None, d.get('manifest') or None,
                                   d.get('rewrites') or None, d.get('branch_id_new') or '')
        except Exception as e: return _branch_error(e, th)
        return _branch_reply(th, branch, base_branch_id=base)
    @rt('/agent/revise')
    async def agent_revise(req):
        "Create a branch whose last assistant prose is the user's edited response."
        d = await req.json(); text = (d.get('text') or '').strip()
        if not text: return fail('revised response is empty')
        try: t = _settled_thread(d.get('thread'))
        except Exception as e: return _branch_error(e)
        try: branch = t.ai.revise(d.get('turn_id') or '', text, d.get('branch_id') or '')
        except Exception as e: return _branch_error(e, t)
        return _branch_reply(t, branch)
    @rt('/agent/retry-tool')
    async def agent_retry_tool(req):
        "Rerun a completed read-only call; return its result without changing model history."
        from .ai import WRITE_TOOLS, path_write
        d = await req.json()
        tool, args = (d.get('tool') or '').strip(), d.get('args')
        if tool in WRITE_TOOLS or path_write(tool, args if isinstance(args, dict) else {}): return fail('only read-only calls can be retried from a checkpoint')
        try: choices = {c.__name__: c for c in _thread(d.get('thread')).ai.tools}
        except Exception as e: return _thread_error(e)
        if tool not in choices: return fail(f'unknown tool {tool}')
        if not isinstance(args, dict): return fail('tool arguments must be an object')
        try: result = await off_loop(choices[tool], **args)
        except Exception as e: return fail(e)
        return {'ok': True, 'tool': tool, 'args': args, 'result': str(result)}
    @rt('/agent/turn-transaction')
    def agent_turn_transaction(turn_id: str = '', thread: str = ''):
        try: t = _thread(thread)
        except Exception as e: return _thread_error(e)
        tx = t.ai.turn_transactions.get(turn_id)
        if tx is None: return fail(f'no transaction for {turn_id}', 404)
        return {'transaction': {**tx, 'files': [{'path': p, **diff_payload(s['before'], s['after'], p)}
                                                for p, s in tx['files'].items()]}}
    @rt('/agent/rollback-turn')
    async def agent_rollback_turn(req):
        d = await req.json()
        try: t = _thread(d.get('thread'))
        except Exception as e: return _thread_error(e)
        try: tx = t.ai.rollback_turn(d.get('turn_id') or '')
        except Exception as e: return fail(e)
        return {'ok': True, 'thread': t.id, 'turn_id': tx['turn_id'], 'paths': list(tx['files']),
                'git': tx.get('git_result', ''), 'irreversible': tx['irreversible']}
    @rt('/agent/rollback-tool')
    async def agent_rollback_tool(req):
        "Rollback one snapshotted file call when its output is still the current file."
        d = await req.json()
        try: t = _thread(d.get('thread'))
        except Exception as e: return _thread_error(e)
        try: path = t.approvals.rollback((d.get('id') or '').strip())
        except Exception as e: return fail(e)
        return {'ok': True, 'thread': t.id, 'path': path}
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
        try: t = _thread(d.get('thread'))
        except Exception as e: return _thread_error(e)
        try: timeout = min(3600, max(1, float(d.get('timeout', t.approvals.timeout))))
        except (TypeError, ValueError): return fail('timeout must be a number of seconds')
        a = await off_loop(t.approvals.request, name, args, True, timeout)
        return {'ok': True, 'thread': t.id, 'answer': a.dict()}
    @rt('/agent/approve')
    async def agent_approve(req):
        "Answer a pending approval. `note` is the reason, and the reason goes back to the model."
        d = await req.json()
        args = d.get('args')
        if args is not None and not isinstance(args, dict): return fail('tool arguments must be an object')
        tool = (d.get('tool') or '').strip() or None
        try: t = _thread(d.get('thread'))
        except Exception as e: return _thread_error(e)
        # answered wherever it was raised: a prompt cell's approval is held by the notebook's
        holder = (ws._notebook_approvals
                  if t.approvals.pending is None and ws._notebook_approvals.pending is not None
                  else t.approvals)
        choices = {c.__name__: c for c in (t.ai if holder is t.approvals else ws.inline_ai).tools}
        if tool and tool not in choices: return fail(f'unknown tool {tool}')
        if bool(d.get('ok')) and tool and args is not None:
            import inspect
            try: inspect.signature(choices[tool]).bind(**args)
            except TypeError as e: return fail(f'invalid {tool} arguments: {e}')
        a = holder.answer(d.get('id') or '', bool(d.get('ok')), (d.get('note') or '').strip(),
                          session=bool(d.get('session')), tool=tool, args=args)
        if a is None: return fail('nothing is waiting for an answer')
        return {'ok': True, 'thread': t.id, 'answer': a.dict()}
    @rt('/agent/approval/always')
    async def agent_approval_always(req):
        "Save the pending call, as edited, as an allow rule, then run it."
        d = await req.json()
        args = d.get('args')
        if args is not None and not isinstance(args, dict): return fail('tool arguments must be an object')
        tool = (d.get('tool') or '').strip() or None
        try: t = _thread(d.get('thread'))
        except Exception as e: return _thread_error(e)
        a = t.approvals.pending
        if a is None or a.id != (d.get('id') or ''): return fail('nothing is waiting for an answer')
        choices = {c.__name__: c for c in t.ai.tools}
        if tool and tool not in choices: return fail(f'unknown tool {tool}')
        if tool and args is not None:
            import inspect
            try: inspect.signature(choices[tool]).bind(**args)
            except TypeError as e: return fail(f'invalid {tool} arguments: {e}')
        name = tool or a.tool
        rule = t.approvals.always(name, subject(name, a.args if args is None else args))
        t.approvals.answer(a.id, True, 'always allowed', tool=tool, args=args)
        return {'ok': True, 'thread': t.id, 'rule': rule, 'rules': t.approvals.rules}
    @rt('/agent/approval/rules')
    def agent_approval_rules(thread: str = ''):
        try: t = _thread(thread)
        except Exception as e: return _thread_error(e)
        return {'ok': True, 'thread': t.id, 'rules': t.approvals.rules, 'path': str(t.approvals.rules_path or '')}
    @rt('/agent/approval/rules/delete')
    async def agent_approval_rules_delete(req):
        d = await req.json()
        try: t = _thread(d.get('thread'))
        except Exception as e: return _thread_error(e)
        rules = list(t.approvals.rules)
        try: rules.remove(tuple(d.get('rule') or ()))
        except ValueError: return fail('no such rule')
        if (path := t.approvals.rules_path) is not None:
            with atomic_save(path, 'w') as f: json.dump(rules, f, indent=1)
        for th in ws.threads.rows(): th.approvals.rules = list(rules)
        return {'ok': True, 'thread': t.id, 'rules': rules}
    @rt('/agent/runs/{run_id}/log')
    def agent_run_log(run_id: str, since: int = 0, thread: str = ''):
        "New transcript text since byte `since`: a run's log, `monitors`, or a background command's output."
        try: t = _thread(thread)
        except Exception as e: return _thread_error(e)
        if run_id.startswith('cmd_'):
            try: state, text = t.ai.host.cmd_output(run_id, 0)
            except Exception: return _run_missing(t, run_id)
            b, done = text.encode(), state != 'running'
        else:
            run = None if run_id == 'monitors' else t.ai.run(run_id)
            log = t.ai.monitors.log if run_id == 'monitors' else getattr(run, 'log', None)
            if log is None: return _run_missing(t, run_id)
            b, done, state = log.read_bytes() if log.exists() else b'', bool(run is not None and run.terminal), getattr(run, 'state', 'watching')
        return {'ok': True, 'thread': t.id, 'run': run_id, 'text': b[since:].decode(errors='replace'), 'since': len(b), 'done': done, 'state': state}
    @rt('/agent/environment')
    def agent_environment(thread: str = ''):
        try: t = _thread(thread)
        except Exception as e: return _thread_error(e)
        return {'ok': True, 'thread': t.id, 'text': t.ai.host.environment()}
    @rt('/agent/shell/{run_id}/stop')
    def agent_shell_stop(run_id: str, thread: str = ''):
        try: t = _thread(thread)
        except Exception as e: return _thread_error(e)
        try: return {'ok': True, 'thread': t.id, 'run': run_id, 'state': t.ai.host.cmd_stop(run_id)}
        except Exception: return _run_missing(t, run_id)
    @rt('/agent/shell-run', methods=['POST'])
    async def agent_shell_run(req):
        "Start a reply's snippet as a background command the person chose; the model is never told."
        d = await req.json()
        try: ctx.gate.check(d.get('token'))
        except PermissionError as e: return fail(e, 403)
        if not (command := str(d.get('command') or '').strip()): return fail('no command to run')
        try: t = _thread(d.get('thread'))
        except Exception as e: return _thread_error(e)
        try: return {'ok': True, 'thread': t.id, 'run': t.ai.host.run_cmd_bg(command)}
        except NotImplementedError as e: return fail(e)
    @rt('/agent/command')
    async def agent_command(req):
        "Run a slash command (`/model`, `/cost`, `/compact`, `/skills`, `/tools`, `/reload`)."
        d = await req.json()
        line = (d.get('line') or '').strip()
        try: ai = _thread(d.get('thread')).ai
        except Exception as e: return _thread_error(e)
        if not line: return {'ok': True, 'text': 'commands: ' + ', '.join('/' + c for c in ai.commands())}
        out = await off_loop(ai.command, line)
        if out is None: return fail(f'unknown command {line.split()[0]}')
        if line.lstrip('/').split(' ')[0] in ('tool-budget', 'steps'):
            ws.tool_budget, ws.step_budget = ai.tool_budget, ai.step_budget
            for agent in live_assistants(): agent.tool_budget, agent.step_budget = ws.tool_budget, ws.step_budget
            ws.save()
        if line.lstrip('/').split(' ')[0] == 'subagents' and hasattr(ai, 'subagent_depth'):
            # the conversation that ran it is the source; the workspace and every idle conversation follow it
            from ...workspace import SUBAGENT_SETTINGS
            ws.subagent_writes = ai.subagent_writes
            for k in SUBAGENT_SETTINGS: setattr(ws, k, getattr(ai, k))
            kept = 0
            for agent in live_assistants():
                if agent is ai: continue
                try:
                    agent.set_subagent_writes(ws.subagent_writes)
                    for k in SUBAGENT_SETTINGS: getattr(agent, f'set_{k}')(getattr(ws, k))
                except RuntimeError: kept += 1
            ws.save()
            if kept: out += f'\n{kept} working conversation(s) keep their sub-agent settings until they finish'
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
