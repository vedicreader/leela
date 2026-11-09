import json, logging, threading, time
from fastcore.basics import AttrDict
from fastcore.xtras import Path
from ... import errstr

log = logging.getLogger(__name__)

def learn_settings(ws):
    "The Learn rows of `ws` for one Abhyasa call. With `workspace_folders` on, `sources.roots` also names the ticked workspace folders that Abhyasa accepts."
    from ..settings.settings import Settings
    d = dict(Settings(ws.project_root).effective().get('learn', {}))
    if d.get('workspace_folders') and (r := [x.path for x in learn_sources(ws) if x.origin == 'workspace' and x.on and not x.why]):
        from abhyasa.learner import dflt
        d['sources.roots'] = '\n'.join([*str(dflt('sources.roots')).splitlines(), *r])
    return d


def _src(ws):
    "The Learn source state of `ws`, with its three parts in place: `off` (workspace folders that are not ticked), `added` (attached paths) and `filed` (path to the docs filed from it)."
    s = ws.learn_src
    for k, t in (('off', list), ('added', list), ('filed', dict)):
        if not isinstance(s.get(k), t): s[k] = t()
    return s

def _why(path, kind):
    "Why Abhyasa does not file `path` (its own rules), or ''."
    from abhyasa.sources import file_why, folder_why
    return (folder_why if kind == 'folder' else file_why)(path)

def learn_sources(ws) -> list:
    "The Learn sources of `ws`, each `AttrDict(path, name, kind, origin, on, why, filed)`: its open folders when `workspace_folders` is on (ticked unless in `off`), then the attached paths. `why` is Abhyasa's plain reason for a path it refuses; `filed` says if Abhyasa filed it."
    s, rows, seen = _src(ws), [], set()
    def add(p, origin, on):
        p = str(Path(p).expanduser().resolve())
        if p in seen: return
        seen.add(p)
        kind = 'file' if Path(p).is_file() else 'folder'
        rows.append(AttrDict(path=p, name=Path(p).name, kind=kind, origin=origin, on=on, why=_why(p, kind), filed=p in s['filed']))
    if learn_settings_on(ws):
        loose = getattr(ws.fs, 'loose', None)
        for r in ws.fs.roots:
            if r != loose: add(r, 'workspace', str(Path(r).resolve()) not in s['off'])
    for p in s['added']: add(p, 'attached', True)
    return rows

def learn_settings_on(ws) -> bool:
    "Whether the setting `learn.workspace_folders` is on for `ws`."
    from ..settings.settings import Settings
    return bool(Settings(ws.project_root).effective().get('learn', {}).get('workspace_folders'))

def sync_sources(ws) -> list:
    "File each ticked source that Abhyasa accepts, in the way a hand-added one is (`file_folder`, `file_file`), and un-file what is off or gone, from the Learn vault only. A refused path is never read. Return `learn_sources(ws)`."
    from abhyasa.sources import file_file, file_folder, unfile
    s, rows = _src(ws), learn_sources(ws)
    keep = {r.path: r for r in rows if r.on and not r.why}
    _, lr = learn_store(ws, write=True)
    for p in [p for p in s['filed'] if p not in keep]: unfile(lr, s['filed'].pop(p))
    for p, r in keep.items():
        if p in s['filed']: continue
        try: docs = (file_folder if r.kind == 'folder' else file_file)(lr, p)
        except Exception as e: r.why = errstr(e); continue
        s['filed'][p] = [dict(shelf=d.shelf, doc_id=d.doc_id, mtime=d.mtime) for d in docs.added]
    ws.save(only=('learn_src',))
    return learn_sources(ws)

def learn_attach(ws, refs) -> list:
    "Attach the paths `refs` as Learn sources and file them. An attachment that is no path of a file or folder is skipped."
    s = _src(ws)
    for r in refs:
        if isinstance(r, str) and (p := Path(r).expanduser()).exists() and str(p.resolve()) not in s['added']: s['added'].append(str(p.resolve()))
    return sync_sources(ws)

def learn_untick(ws, path, on=False) -> list:
    "Tick or untick the workspace folder `path`, or detach the attached path `path`; then sync. A detached source leaves the Learn vault. The path itself is never changed."
    s, p = _src(ws), str(Path(path).expanduser().resolve())
    if p in s['added'] and not on: s['added'].remove(p)
    elif on: s['off'] = [x for x in s['off'] if x != p]
    elif p not in s['off']: s['off'].append(p)
    return sync_sources(ws)

def sources_line(ws) -> str:
    "One line for the Learn context: what the agent may use from this workspace, and what Abhyasa refused."
    rows = learn_sources(ws)
    use, no = [r.name for r in rows if r.on and not r.why], [f'{r.name} ({r.why})' for r in rows if r.on and r.why]
    on = learn_settings_on(ws)
    if not (use or no or on): return ''
    return f"Workspace folders as sources: {'on' if on else 'off'}. Sources of this workspace: {', '.join(use) or 'none'}." + (f" Not used: {'; '.join(no)}." if no else '')


def learn_store(ws, vault=None, write=False):
    from abhyasa.learner import Learning
    from ..memory.memory import learning_store
    ref = ws.vaults.get(vault) if vault else ws.vaults.learn()
    if ref is None: raise KeyError('Learning vault is not attached.')
    if write and not ref.agent_writable: raise PermissionError('Learning vault is read-only for the agent.')
    memory = ws.vaults.memory(ref.name)
    return ref.name, Learning(learning_store(memory))


def learn_view(ws):
    "`(vault, None, page)` of the active tab when it is a Learn tab: its vault and the saved path of the page it shows. Else `(None, None, '')`."
    tab = getattr(ws, 'tab', None)
    if getattr(tab, 'kind', '') != 'learn': return None, None, ''
    ref = json.loads(tab.ref or '[]')
    return (ref[0] if ref else None), None, getattr(tab, 'page', '') or ''


def on_screen(ai, lr):
    "`dict(jid, i)` of the walk step that the active Learn tab shows. `KeyError` says why when it shows none."
    from abhyasa.agent_tools import page_of, walk_state
    pg = page_of(learn_view(ai.ws)[2])
    jid = pg['jid'] if pg['kind'] in ('step', 'walk') else None
    if not jid: raise KeyError('The Learn tab shows no walk step. Ask the learner to open one.')
    i = pg['i'] if pg['kind'] == 'step' else (walk_state(lr, jid)['data'] or {}).get('current')
    return dict(jid=jid, i=0 if i is None else i)


def learn_guard(ai, text, spec=None):
    from abhyasa.models import guard
    return guard(text, spec or ai.spec_or_none('plan'), ai.ws.vault_pii)


def learn_ask(ai, task='plan'):
    from abhyasa.agent_tools import ModelRefused
    from ramabana.runtime import AgentError, OneshotTimeout
    def prepare(prompt, sp, backend):
        return learn_guard(ai, prompt, backend.spec), learn_guard(ai, sp, backend.spec)
    def ask(prompt, sp=''):
        try: return ai.oneshot(prompt, sp, task, 2048, prepare=prepare, deadline=120, wait=True, strict=True)
        except (AgentError, OneshotTimeout) as e: raise ModelRefused(str(e)) from e
    return ask


def picture_why(spec, pii) -> str:
    "Why a picture may not go to the model `spec` with the privacy setting `pii`, in words for the learner; '' when it may. Pixels cannot be redacted, so `redact` counts as `refuse` for a model off this Mac."
    from abhyasa.show import keeps_images
    from ramabana.core import accepts
    if not accepts(spec, 'image'): return f'{spec.name} cannot see pictures.'
    if not spec.local and pii != 'off':
        return (f'The privacy setting is "{pii}". A picture cannot have personal data hidden, so no picture goes to a model off this Mac. '
                'Pick a model on this Mac for pictures to read figure labels and the screen.')
    return '' if keeps_images(spec) else f'{spec.name} does not get pictures on this route.'


def learn_vision_why(ai) -> str:
    "Why Abhyasa's picture call may not run now (`picture_why` for the model of the `vision` task), or ''."
    spec = ai.spec_or_none('vision')
    return picture_why(spec, ai.ws.vault_pii) if spec is not None else 'Leela has no model for pictures.'


def learn_vision(ai, task='vision'):
    "Abhyasa's picture call `(prompt, img, sp) -> str` on `ai.oneshot`: each route checks `picture_why` and passes the text through the guard before anything is sent."
    from abhyasa.agent_tools import ModelRefused
    from abhyasa.models import Withheld
    from ramabana.runtime import AgentError, OneshotTimeout
    def prepare(prompt, sp, backend, img):
        if why := picture_why(backend.spec, ai.ws.vault_pii): raise Withheld(why)
        return ai.compose(learn_guard(ai, prompt, backend.spec), image=img), learn_guard(ai, sp, backend.spec)
    def call(prompt, img, sp=''):
        try: return ai.oneshot(prompt, sp, task, 1024, prepare=lambda p, s, b: prepare(p, s, b, img), deadline=120, wait=True, strict=True)
        except (AgentError, OneshotTimeout) as e: raise ModelRefused(str(e)) from e
    return call


class Polled(threading.Event):
    "A stop event that is set once `stopping()` is true: Abhyasa's stop for a job whose stop is a flag of its row."
    def __init__(self, stopping): super().__init__(); self.stopping = stopping
    def is_set(self): return super().is_set() or bool(self.stopping())


RESEARCH_OFF = 'Web research is off in this preview, so no source was looked for. Start it with --web to allow it.'

def research_on(ws): return getattr(ws, 'learn_research', True)

def learn_web(ws):
    "`(search, fetch)` for Abhyasa's research from the workspace's own web tools, with Leela's query rule; nothing is kept in a folder or a vault. With `ws.learn_research` False both refuse in words."
    from abhyasa.sources import public_url
    from ..memory.memory import PrivacyBlocked, query_refusal, source_kind
    def search(q, n):
        if not research_on(ws): raise LookupError(RESEARCH_OFF)
        if why := query_refusal(q): raise PrivacyBlocked(why, 'pii_blocked')
        return [dict(title=h.title, href=h.url) for h in ws.research.search(q, n=n)]
    def fetch(url):
        if not research_on(ws): raise LookupError(RESEARCH_OFF)
        if source_kind(str(url)) != 'url': raise ValueError(f'{url} is not a web address')
        public_url(url)
        if not (d := ws.research.read(url, remember=False)): raise LookupError(ws.research.note or f'no content at {url}')
        return AttrDict(url=d.url, title=d.title, text=d.text)
    return search, fetch


def learn_gather(ai, lr, jid, stopping, say=None, settings=None):
    "Abhyasa's `gather_loop` on walk `jid`: the model calls are the `research` task of `ai.oneshot`, the pages come from the workspace, and `stopping()` is Stop."
    from abhyasa import learner, path
    if not research_on(ai.ws): return AttrDict(passages=0, read=0, why=RESEARCH_OFF, stopped='')
    search, fetch = learn_web(ai.ws)
    with learner.use_settings(settings): return path.gather_loop(lr, jid, Polled(stopping), learn_ask(ai, 'research'), search, fetch, say=say)


def learn_say(report):
    "Abhyasa's `say(line, done)` as the card of a job: the line is its current step and `done` moves its bar."
    return lambda line, done=None: report(current=line, **({} if done is None else dict(progress=.05 + .9 * done)))


def gather_job_actions(job, result):
    "The line of a finished `learn_gather` card: how many sources it found and what the rest got, in words."
    from fasthtml.common import Span
    return [Span(said, cls='lee-job-note')] if (said := (result.get('data') or {}).get('said')) else []


def run_gather(ai, lr, jid, stop):
    "Abhyasa's hosted `gather` hook: the job `learn_gather` on walk `jid`, waited for here; setting `stop` cancels it. Return what `gather_loop` returns."
    from ..vault.jobs import JobError
    ai = ai.ws.ai
    jobs = ai.ws.jobs
    r = start_learn_job(ai, jid, 'learn_gather', lr=lr)
    if r['status'] != 'ok': return AttrDict(passages=0, read=0, why=r['data']['message'], stopped='')
    while jobs.get(r['operation_id']).active:
        if stop.is_set():
            try: jobs.cancel(r['operation_id'])
            except JobError: pass
        time.sleep(.2)
    job = jobs.get(r['operation_id'])
    if job.status == 'error': lr.merge_journey(jid, gather_why=f'Research stopped: {job.error}')
    out = (job.result or {}).get('data') or {}
    return AttrDict(passages=out.get('passages', 0), read=out.get('read', 0), why=out.get('said') or job.error or '', stopped='you' if job.status == 'cancelled' else '')


HOST_API_NEEDED = 1

def host_api():
    "The `HOST_API` of the installed Abhyasa, or None when it has none."
    try: from abhyasa.core.hostapi import HOST_API
    except ImportError: return None
    return HOST_API

def host_line() -> str:
    "The one line that says the installed Abhyasa is too old for this host, else an empty string."
    have = host_api()
    return '' if have is not None and have >= HOST_API_NEEDED else f"Abhyasa too old: needs host API {HOST_API_NEEDED}, has {'none' if have is None else have}"

def missing_line(missing) -> str:
    "The one line for `contract_missing()`'s result."
    return missing[0] if missing and missing[0].startswith('Abhyasa too old') else f"Abhyasa too old: lacks {', '.join(missing)}"

def contract_missing() -> list[str]:
    "What this install lacks of Abhyasa's native contract: the host API line, else the names of `agent_tools.TOOLS`, `agent_tools.page_of` and `learner.use_settings`."
    from importlib import import_module
    if line := host_line(): return [line]
    out = []
    for mod, name in (('abhyasa.agent_tools', 'TOOLS'), ('abhyasa.agent_tools', 'page_of'), ('abhyasa.learner', 'use_settings')):
        try: have = hasattr(import_module(mod), name)
        except ImportError: have = False
        if not have: out.append(f'{mod}.{name}')
    return out


def show_walk(ws, vault, walk):
    "Open the Learn tab at the walk, keep the layout, and tell the pages showing this workspace. A failure is logged: the walk exists, so the job stays ok."
    try:
        tab = ws.open_walk(vault, walk)
        ws.save()
        ws.fs_watch.announce_tab(tab.kind, tab.ref)
    except Exception as e: log.error('Learn walk %s was made but its tab did not open: %s', walk, errstr(e))


LEARN_EDITS = ('keep_idea', 'drop_idea', 'move_idea', 'add_source', 'restore_version')

def register_learn_jobs(ws):
    if contract_missing(): return
    from abhyasa import agent_tools as engine
    from ..vault.ui import register_job_actions
    register_job_actions('learn_gather', gather_job_actions)
    def held(job, again):
        if not (h := ws.jobs.take(job.id)): raise RuntimeError(f'The originating learning session is no longer available. {again}')
        return h['ai'], h['lr']
    def run(job, report):
        ai, lr = held(job, 'Start a new walk.')
        r = engine.create_walk(lr, learn_ask(ai), job.target, stopping=lambda: ws.jobs.stopping(job.id), progress=lambda stage, frac: report(progress=frac, current=stage),
                               settings=job.params['settings'], guard=lambda text: learn_guard(ai, text))
        r.update(operation_id=job.id, vault=job.params['vault'])
        if r['status'] == 'ok':
            from ...workspace import walk_path
            r['data']['tab'] = dict(kind='learn', vault=r['vault'], walk=r['walk'], path=walk_path(r['walk']))
            if ws.threads.active_id == job.params['thread'] and ai.mode == 'learn': show_walk(ws, r['vault'], r['walk'])
            ws.fs_watch.announce_learn(r['walk'])
        if r['status'] == 'ok' and job.params.get('research'):
            try: r['data']['research'] = run_gather(ai, lr, r['walk'], Polled(lambda: ws.jobs.stopping(job.id))).why
            except Exception as e: r['data']['research'] = f'Research stopped: {errstr(e)}'
        if r['status'] == 'stopped': r['cancelled'] = True
        return r
    ws.jobs.register('learn_walk', run)
    def change(job, report):
        ai, lr = held(job, 'Ask for the change again.')
        r = engine.change_walk(lr, learn_ask(ai, 'plan'), job.target, job.params['instruction'], stopping=lambda: ws.jobs.stopping(job.id), settings=job.params['settings'])
        r.update(operation_id=job.id, vault=job.params['vault'])
        if r['status'] == 'stopped': r['cancelled'] = True
        if r['status'] == 'ok': ws.fs_watch.announce_learn(job.target)
        return r
    ws.jobs.register('learn_change', change)
    def gather(job, report):
        ai, lr = held(job, 'Ask for sources again.')
        g = learn_gather(ai, lr, job.target, lambda: ws.jobs.stopping(job.id), learn_say(report), job.params['settings'])
        r = engine.result('stopped' if g.stopped == 'you' else 'ok', **({'error': 'stopped'} if g.stopped == 'you' else {}), walk=job.target, vault=job.params['vault'],
                          operation_id=job.id, data=dict(passages=g.passages, read=g.read, said=g.why))
        if g.stopped == 'you': r['cancelled'] = True
        return r
    ws.jobs.register('learn_gather', gather)


def start_learn_job(ai, goal, kind='learn_walk', lr=None, **params):
    "Start the cancellable job `kind` on `goal` (a goal, or a walk id for `learn_change` and `learn_gather`), or return the one that runs now with the same `params`. `lr` is the store of a caller that has one; else the Learn vault."
    from abhyasa.agent_tools import result, failed
    ws = ai.ws
    vault, lr = (Path(str(lr.v.path)).name, lr) if lr is not None else learn_store(ws, write=True)
    if kind in ('learn_change', 'learn_gather') and ((j := lr.journey(goal)) is None or (kind == 'learn_change' and j.get('mode') != 'walk')): return failed('not_found', f'no walk {goal!r}', walk=goal)
    job = ws.jobs.start_once(kind, goal, held=dict(ai=ai, lr=lr), also=dict(settings=learn_settings(ws), _cancel=True), vault=vault, thread=ai.session_id, **params)
    return result('ok', operation_id=job.id, vault=vault, data=dict(job=job.id))


def learn_context(ai):
    "The Learn mode block of the system prompt: the learner, the walk and the page on screen."
    from abhyasa.agent_tools import learner_context
    from abhyasa.learner import use_settings
    vault, walk, page = learn_view(ai.ws)
    try: _, lr = learn_store(ai.ws, vault)
    except (KeyError, FileNotFoundError): return 'Learn mode. The learning vault is unavailable. Attach it before continuing.'
    with use_settings(learn_settings(ai.ws)): return '\n'.join(filter(None, [learner_context(lr, walk, page=page), sources_line(ai.ws)]))


def learn_tools(ai):
    if contract_missing(): return []
    import inspect
    from abhyasa import agent_tools as engine
    from ...agent.tools import small_tool
    from shalya.core import writes
    reads = getattr(engine, 'READS', (engine.walk_state.__name__,))
    cfg = lambda: dict(settings=learn_settings(ai.ws))
    extra = dict(record_attempt=lambda: dict(ask=learn_ask(ai, 'grade'), **cfg()), walk_state=cfg, add_source=cfg, explain_here=cfg)
    def wrap(name, args):
        def call(**kwargs):
            if ai.mode != 'learn':
                r = engine.failed('mode_off', 'Turn Learn mode on before using learning tools.', extra=('mode_off',))
                r['data'].update(mode=ai.mode, needs='learn')
                return r
            try:
                if name == 'create_walk': return start_learn_job(ai, kwargs['goal'], research=research_on(ai.ws) and str(kwargs.get('research') or 'yes').lower() not in ('no', 'false', '0'))
                if name == 'change_walk': return start_learn_job(ai, kwargs['jid'], 'learn_change', instruction=kwargs['instruction'])
                vault, lr = learn_store(ai.ws, learn_view(ai.ws)[0] if name == 'explain_here' else None, write=name not in reads)
                if name == 'explain_here': kwargs = {**kwargs, **on_screen(ai, lr)}
                r = getattr(engine, name)(lr, **kwargs, **extra.get(name, dict)())
                r['vault'] = vault
                if name in LEARN_EDITS and r.get('status') == 'ok': ai.ws.fs_watch.announce_learn(r.get('walk') or kwargs.get('jid'))
                return r
            except PermissionError as e: return engine.failed('read_only', str(e))
            except KeyError as e: return engine.failed('not_found', str(e.args[0] if e.args else e))
        call.__name__ = name
        call.__doc__ = getattr(engine, name).__doc__ or ''
        call.__annotations__ = {k: {'str': str, 'int': int}[v.split(':', 1)[0]] for k, v in args.items()}
        call.__signature__ = inspect.Signature([inspect.Parameter(k, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=call.__annotations__[k], **({'default': ''} if k == 'research' else {})) for k in args])
        call.__doc__ += '\n\n' + '\n'.join(f'{k}: {v}' for k, v in args.items())
        if name not in reads: writes(call)
        return small_tool(call)
    return [wrap(name, args) for name, args in engine.TOOLS]
