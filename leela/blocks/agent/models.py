"Persistent user-added local and hosted model aliases."
import json, subprocess, sys, threading, time
from fastcore.all import Path
from fastcore.net import urljson
from ... import extras_site, leela_cfg, use_extras
from kunda.pythons import clean_env
from ...core.update import RELEASE_PAGE, latest_release, newer

__all__ = ['model_path', 'MODELS_FILE', 'load_models', 'save_model', 'delete_model', 'runtimes',
           'model_marks', 'mark_models', 'JOB_HELP', 'INSTALLABLE', 'runtime_requirements',
           'install_runtime', 'probe_dir', 'probe_path', 'probed', 'catalog', 'forget_probes',
           'warm_probes', 'install_state', 'setup_plan', 'dismiss_setup', 'setup_dismissed',
           'SETUP_SIZES', 'RECOMMENDED', 'TOOLS', 'tool_rows', 'updates', 'unavailable', 'default_model', 'providers',
           'turn_move', 'GEMMA', 'gemma_row', 'download_model']

#: What each routed job spends its model on. One copy: the settings pane renders three of these
#: server-side and the rest from `/agent/models`, and two copies drifted apart the first time.
JOB_HELP = {
 'turn': 'Every turn of this conversation and every tool call it makes. The model the agent is. Defaults to claude-opus-5-5;\n'
         'without Claude Code, add a provider with + model or in config.toml. Nothing is chosen for you.',
 'inline': 'The assistant inside a notebook prompt cell, and the one the inline AI panel asks\n'
           'about a selection. Unset, it falls back to oneshot.',
 'completion': 'Inline code completion as you type, and "AI edit" on an editor selection. Unset, it falls back to oneshot.',
 'oneshot': 'The fallback for the cheap jobs with no model of their own: classify, completion and inline. Nothing calls it directly, so setting it only moves the jobs you have left unset. Defaults to gpt-4.1, or claude-sonnet-5 without OPENAI_API_KEY. On a local turn model, every job without a model of its own stays on the turn model.',
 'classify': 'One-label questions the agent asks itself mid-turn. Unset, it falls back to oneshot.',
 'summary': 'Context compaction, conversation titles, agent charter drafts, and "summarise selection". Defaults to gpt-4.1, or claude-sonnet-5 without OPENAI_API_KEY; on a local turn model it stays on the turn model.',
 'subagent': 'Delegated searches, which run as their own read-only agent. Defaults to claude-sonnet-5, not to oneshot; on a local turn model it stays on the turn model.'}

def unavailable(model):
    "Why `model`, a name or a spec, cannot run here, a missing runtime or a missing key, and how to add a provider; '' when it can."
    from ...agent.core import SETUP_HINT, missing_key, missing_runtime, needs, reachable_hint, resolve
    try: spec = resolve(model) if isinstance(model, str) else model
    except Exception: return ''
    m = missing_runtime(spec) or ((k := missing_key(spec)) and needs(k))
    return f'{m}. {reachable_hint().replace(SETUP_HINT, "+ model adds a provider")}' if m else ''

def providers():
    "Each provider Ramabana can use, what it needs, and whether it is set up here; nothing is chosen by it."
    from ...agent.core import PROVIDERS, auth_status, provider_ready
    try: auth = probed('auth', auth_status)
    except Exception: auth = {}
    return [{**p, 'ready': provider_ready(p['key'], auth)} for p in PROVIDERS]

def turn_move():
    "The turn a new conversation gets when nobody named one, moved as `Agent.settle` moves it, and the line that says so or ''."
    from ...agent.core import Routing, use_aliases
    use_aliases(model_path())
    r = Routing()
    return (alt, r.settled_line(alt)) if (alt := r.settled()) else (r.turn, '')

def default_model(job='turn'):
    "The model Ramabana's routing gives `job` when nobody chose one, so this pane and the CLI agree: config.toml's `[jobs]`, then the defaults, moved to a model ready here when the turn cannot run."
    from ...agent.core import Routing, use_aliases
    use_aliases(model_path())
    try: return turn_move()[0] if job == 'turn' else Routing().name_for(job)
    except Exception: return None

def _runtimes():
    from ...agent.core import RUNTIME_NAMES
    return RUNTIME_NAMES

LABELS = {'litert': 'LiteRT', 'mlx': 'MLX', 'llama': 'llama.cpp', 'remote': 'hosted API / FastLLM',
          'cursor': 'Cursor agent', 'claude': 'Claude Code', 'copilot': 'GitHub Copilot'}

#: Runtimes a package can supply, named as rishi's own extras. The rest want a CLI, a daemon or a key.
INSTALLABLE = ('mlx', 'llama')

#: Optional tools that are not a model: `(label, requirements, approximate MB, what it gives you)`.
TOOLS = {'langserver': ('Language server',
                        ['basedpyright>=1.39'], 70,
                        'Red squiggles, hover types, go to definition and rename.')}

def probe_dir():
    "Where a probe's last answer is kept between runs. Read per call: `leela_cfg` moves under a test."
    return leela_cfg/'probes'

def probe_path(key):
    "Where one probe's last answer is kept between runs."
    from ...agent.core import probe_path as at
    return at(key, dir=probe_dir())

def probed(key, fn, ttl=None):
    "`fn()`'s last answer, with a stale one refreshed behind whoever asked."
    from ...agent.core import PROBE_TTL, probed as memo
    return memo(key, fn, ttl=PROBE_TTL if ttl is None else ttl, dir=probe_dir())

def catalog(legacy=True):
    "Every model this machine offers, and the id each row resolves to."
    from ...agent.core import available_models, resolve
    rows = list(available_models(include_legacy=legacy) or [])
    index = {}
    for r in rows:
        # Here rather than per request: `spec_caps` scans the Hugging Face cache, and once per row
        # per request was seconds of the picker.
        r.update(model_marks(r.get('value')))
        try: spec = resolve(r['value'])
        except Exception: continue
        if spec is not None: index.setdefault(spec.model_id, r['value'])
    return rows, index

def forget_probes(disk=False):
    "Drop every cached probe. The cache is process-wide, because what it holds is the machine's."
    from ...agent.core import forget_probes as forget
    return forget(disk=disk, dir=probe_dir())

def warm_probes():
    "Pay for the first probe at startup rather than on the first click."
    from ...agent.core import auth_status
    for legacy in (True, False):
        try: probed(f'catalog2:{legacy}', lambda legacy=legacy: catalog(legacy))
        except Exception: pass
    for key, fn in (('auth', auth_status), ('runtimes', runtimes)):
        try: probed(key, fn)
        except Exception: pass

def tool_rows():
    "Each optional tool, whether it is here, and what installing it would fetch."
    from ..lsp.lsp import find_server
    found = find_server()[0]
    return [{'value': name, 'label': label, 'requirements': reqs, 'mb': mb, 'blurb': blurb,
             'available': bool(found) if name == 'langserver' else False,
             'found': found or '', 'install': install_state(name)}
            for name, (label, reqs, mb, blurb) in TOOLS.items()]

def runtime_requirements(runtime):
    "What rishi asks for to serve `runtime` here, straight out of its metadata rather than copied."
    import importlib.metadata as md
    from packaging.requirements import Requirement
    if runtime not in INSTALLABLE: return []
    out = []
    for line in md.distribution('rishi').requires or []:
        if f"extra == '{runtime}'" not in line: continue
        req = Requirement(line)
        # The rest of the marker is this machine's business: mlx is darwin/arm64 only.
        if req.marker and not req.marker.evaluate({'extra': runtime}): continue
        out.append(f'{req.name}{req.specifier}')
    return out

_installs, _lock = {}, threading.Lock()

def install_state(runtime=None):
    "What the last install of each runtime did. One dict per runtime, or all of them."
    with _lock: return dict(_installs.get(runtime) or {}) if runtime else {k: dict(v) for k, v in _installs.items()}

def _installer(target):
    "pip or uv, whichever can install here."
    # `--python` makes uv run the interpreter to interrogate it, and a py2app binary answers that
    # by starting Leela, so a frozen app uses the pip it ships.
    import importlib.util, shutil
    into = ['--target', str(target)] if target else []
    if not getattr(sys, 'frozen', False) and (uv := shutil.which('uv')):
        return [uv, 'pip', 'install', '--python', sys.executable, *into]
    if importlib.util.find_spec('pip') is not None:
        # `runtime_python`: in a bundle `sys.executable` is the app, and installing a backend would
        # launch a second Leela rather than a pip.
        from ..runtime.kernels import runtime_python
        return [runtime_python(), '-m', 'pip', 'install', '--upgrade', *into]
    raise RuntimeError('neither uv nor pip is here, so nothing can be installed for you')

def _run_install(runtime, cmd):
    "The subprocess, on its own thread. Output is kept whole: a resolver error is the useful part."
    try:
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL, start_new_session=True, capture_output=True, text=True, timeout=3600, env=clean_env())
        ok, log = p.returncode == 0, (p.stdout or '') + (p.stderr or '')
    except Exception as e:
        from ... import errstr
        ok, log = False, errstr(e)
    if ok: use_extras()                       # so the new backend is importable without a restart
    import importlib
    importlib.invalidate_caches()
    from ...agent.core import runtime_available
    try: runtime_available.cache_clear()      # only `ollama` memoises, and only it would go stale
    except AttributeError: pass
    if runtime in TOOLS:
        from ..lsp.lsp import find_server
        here = bool(find_server()[0])
    else: here = bool(runtime_available(runtime))
    with _lock:
        _installs[runtime].update(state='ok' if ok else 'error', log=log[-4000:], available=here)

#: The on-device model the setup panel offers to download: the smallest Gemma.
GEMMA = 'gemma-e2b'

def gemma_row():
    "The setup row that downloads `GEMMA`, or None where LiteRT cannot run it."
    from ...agent.core import LOCAL_SIZE, runtime_available, weights_here
    if not runtime_available('litert'): return None
    return {'value': GEMMA, 'label': 'Gemma 4 E2B', 'size': LOCAL_SIZE[GEMMA], 'model': True, 'requirements': [],
            'blurb': f'Download Gemma 4 E2B ({LOCAL_SIZE[GEMMA]}) to run on this Mac. No account needed.',
            'available': weights_here(GEMMA), 'install': install_state(GEMMA)}

def _fetch(name):
    "Download `name`'s weights into the Hugging Face cache, then forget every probe that said they were missing."
    from ...agent.core import LOCAL, weights_here
    log = ''
    try:
        from rishi.litert import get_model
        get_model(LOCAL[name])
    except Exception as e:
        from ... import errstr
        log = errstr(e)
    forget_probes(disk=True)
    here = weights_here(name)
    with _lock: _installs[name].update(state='ok' if here else 'error', log=log[-4000:] or ('' if here else 'the download ended with no weights on disk'), available=here)

def download_model(name=GEMMA):
    "Start the download of a local model's weights, once, on its own thread; only ever because someone asked."
    from ...agent.core import LOCAL, LOCAL_SIZE
    with _lock:
        if (cur := _installs.get(name)) and cur.get('state') == 'running': return dict(cur)
        _installs[name] = row = {'runtime': name, 'state': 'running', 'log': '', 'cmd': f'download {LOCAL[name]}', 'requirements': [],
                                 'via': 'Hugging Face', 'target': '', 'size': LOCAL_SIZE.get(name, '')}
        out = dict(row)   # before the thread starts: it changes `row` in place
    threading.Thread(target=_fetch, args=(name,), daemon=True, name=f'leela-download-{name}').start()
    return out

def install_runtime(runtime):
    "Fetch one backend, tool or `GEMMA`'s weights, pinned to the rishi here, where a frozen app can reach it."
    if runtime == GEMMA: return download_model(runtime)
    if runtime in TOOLS: reqs = list(TOOLS[runtime][1])
    elif runtime not in INSTALLABLE:
        raise ValueError(f'{runtime} is not something a package provides; see its remedy')
    elif not (reqs := runtime_requirements(runtime)):
        raise ValueError(f'rishi declares no {runtime} backend for this platform')
    with _lock:
        if (cur := _installs.get(runtime)) and cur.get('state') == 'running': return dict(cur)
        target = extras_site() if getattr(sys, 'frozen', False) else None
        if target: target.mkdir(parents=True, exist_ok=True)
        cmd = [*_installer(target), *reqs]
        _installs[runtime] = row = {'runtime': runtime, 'state': 'running', 'log': '',
                                    'cmd': ' '.join(cmd), 'requirements': reqs,
                                    'via': Path(cmd[0]).name, 'target': str(target or '')}
        out = dict(row)
    threading.Thread(target=_run_install, args=(runtime, cmd), daemon=True,
                     name=f'leela-install-{runtime}').start()
    return out

#: Approximate installed size, so nobody starts a 400MB download without being told.
SETUP_SIZES = {'mlx': 400, 'llama': 120}

#: The local runtime Leela recommends of the ones left to install.
RECOMMENDED = 'llama'

#: The first-run wording for an account runtime. `runtime_remedy` is the terser picker version.
ACCOUNTS = (
 ('claude', 'Claude Code', 'Sign in once with `claude /login` and Leela drives it. No key to manage.'),
 ('remote', 'An API key', 'Set OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY or OPENROUTER_API_KEY, or add Azure OpenAI, '
            'AWS Bedrock or any OpenAI-compatible model with + model or in config.toml. Nothing is chosen for you.'),
 ('ollama', 'Ollama', 'Runs its own daemon, so the weights are on your machine and Leela adds nothing.'),
 ('copilot', 'GitHub Copilot', 'Sign in to Copilot in an editor and its models appear here.'))

def _setup_marker(): return leela_cfg/'setup.json'

def setup_dismissed():
    try: return bool(json.loads(_setup_marker().read_text()).get('dismissed'))
    except Exception: return False

def dismiss_setup(dismissed=True):
    "Remember the pane was answered, so it stops offering itself."
    p = _setup_marker(); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({'dismissed': bool(dismissed)}) + '\n')
    return bool(dismissed)

_latest, _latest_at = {}, 0.0
LATEST_TTL = 3600          #: a courtesy check, not a heartbeat

def _latest_versions(dists):
    "Newest published version of each distribution and of Leela. No network means no offer."
    import time
    # Both, or `_latest` is a local that line one reads before line last writes it: the first call
    # short-circuited on `_latest_at` being 0 and every call inside the hour after it raised
    # `UnboundLocalError`, so the check worked once per process and then threw.
    global _latest, _latest_at
    if time.time() - _latest_at < LATEST_TTL and _latest: return dict(_latest)
    out = {}
    for d in dists:
        try: out[d] = urljson(f'https://pypi.org/pypi/{d}/json', timeout=4)['info']['version']
        except Exception: pass
    rel = latest_release()
    out['leela'], out['leela_url'] = rel.get('version'), rel.get('url') or ''
    _latest, _latest_at = out, time.time()
    return dict(out)

def _installed_version(dist):
    import importlib.metadata as md
    try: return md.version(dist)
    except Exception: return None


def updates(check=True):
    "What is installed here with a newer release. The app names its own release rather than self-updating."
    from packaging.requirements import Requirement
    dists = {}
    for r in INSTALLABLE:
        for req in runtime_requirements(r):
            spec = Requirement(req)
            if (v := _installed_version(spec.name)): dists.setdefault(spec.name, (r, v, spec.specifier))
    latest = _latest_versions(list(dists)) if check else {}
    from ... import __version__

    def movable(cur, new, spec):
        # rishi pins some of these exactly, and a release we cannot take is not an update.
        return newer(new, cur) and bool(new and spec.contains(new, prereleases=True))

    rows = [{'runtime': rt, 'dist': name, 'installed': cur, 'latest': latest.get(name),
             'pin': str(spec) or 'any', 'outdated': movable(cur, latest.get(name), spec)}
            for name, (rt, cur, spec) in sorted(dists.items())]
    return {'backends': rows, 'outdated': [r for r in rows if r['outdated']],
            'leela': {'current': __version__, 'latest': latest.get('leela'),
                      'url': latest.get('leela_url') or RELEASE_PAGE,
                      'outdated': newer(latest.get('leela'), __version__)},
            'checked': bool(latest)}

def setup_plan():
    "The first-run choice. Accounts cost nothing, so they lead; the offline half is rishi's markers."
    from ...agent.core import auth_status, remote_models
    rows = {r['value']: r for r in runtimes()}
    auth = {}
    # Asking every account whether it is signed in is over a second cold, and this is the first
    # thing a packaged app draws.
    try: auth = probed('auth', auth_status)
    except Exception: pass
    def ready(v):
        # `runtime_available` says the CLI is installed; being signed in is what `auth_status` knows.
        if v == 'claude': return bool(auth.get('claude', {}).get('available'))
        if v == 'copilot': return bool(auth.get('copilot', {}).get('available'))
        if v == 'remote':
            if any(auth.get(k, {}).get('available') for k in ('anthropic', 'openai', 'gemini', 'codex')): return True
            load_models()   # Leela's own saved models count as configured too
            try: return bool(remote_models())   # config.toml's definitions and saved aliases with their key set
            except Exception: return False
        return bool(rows.get(v, {}).get('available'))
    accounts = [{'value': v, 'label': label, 'blurb': blurb, 'ready': ready(v),
                 'why': rows.get(v, {}).get('why', ''),
                 'detail': '' if ready(v) else rows.get(v, {}).get('detail', '')}
                for v, label, blurb in ACCOUNTS]
    offline = [{**rows[v], 'mb': SETUP_SIZES.get(v), 'recommended': v == RECOMMENDED}
               for v in INSTALLABLE if v in rows and rows[v]['requirements']]
    offline.sort(key=lambda r: not r['recommended'])   # the one we recommend is the one offered first
    if (g := gemma_row()): offline.insert(0, g)
    ready_now = [a['value'] for a in accounts if a['ready']]
    installed = [o['value'] for o in offline if o['available']]
    return {'frozen': bool(getattr(sys, 'frozen', False)), 'dismissed': setup_dismissed(),
            'accounts': accounts, 'offline': offline, 'tools': tool_rows(), 'ready': ready_now,
            # Set up means: something can answer a prompt. Until then the modal leads with setup;
            # after it, the same modal is where an update shows up.
            'done': bool(ready_now or installed)}

def runtimes():
    "Every runtime, whether rishi can reach it here, and what it wants when it cannot."
    from ...agent.core import runtime_available, runtime_detail, runtime_remedy
    return [{'value': r, 'label': LABELS.get(r, r), 'available': bool(runtime_available(r)),
             'why': runtime_remedy(r), 'installable': r in INSTALLABLE,
             'requirements': runtime_requirements(r), 'install': install_state(r),
             'detail': '' if runtime_available(r) else runtime_detail(r)}
            for r in _runtimes()]

def model_marks(name):
    "The modality line the CLI banner shows for one model, its runtime, and whether it can draw."
    from ...agent.core import resolve, spec_caps
    try: spec = resolve(name)
    except Exception: return {}
    out = {'runtime': rt} if (rt := getattr(spec, 'runtime', None)) else {}   # the pane warns on cursor
    out['local'] = bool(getattr(spec, 'local', False))   # pickers say "on this Mac" or "hosted"
    try: c = spec_caps(spec)
    except Exception: c = None
    return out if c is None else {**out, 'modalities': c.fmt(), 'gen_image': c.gen_image,
                                  'gen_video': c.gen_video}

def mark_models(rows):
    "Stamp every picker row with what its model accepts and returns. No row may fail the picker."
    for r in rows:
        if 'modalities' in r or 'gen_image' in r: continue
        r.update(model_marks(r.get('value')))
    return rows

#: Where this application keeps its aliases. `register_model` is in-process only, so the file that
#: outlives the process is Ramabana's now: its own CLI wanted the same one for the same reason.
MODELS_FILE = 'models.json'

def model_path(path=None):
    "The alias file, Leela's own unless a caller names another."
    return Path(path or leela_cfg/MODELS_FILE)

def load_models(path=None):
    "Register saved aliases with Ramabana and return the rows that took."
    from ...agent.core import load_models as load, use_aliases
    if path is None: use_aliases(model_path())   # Ramabana's own loads read Leela's file, never the CLI's
    return load(path=model_path(path))

def save_model(row, path=None):
    "Validate, register and persist one model alias. API keys are never stored here."
    from ...agent.core import save_model as save
    return save(row, path=model_path(path))

def delete_model(name, path=None):
    "Forget one alias, on disk and in this process."
    from ...agent.core import delete_model as forget
    return forget(name, path=model_path(path))
