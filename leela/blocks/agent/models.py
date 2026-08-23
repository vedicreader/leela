"Persistent user-added local and hosted model aliases."
import json, re, subprocess, sys, threading
from fastcore.all import Path
from ... import extras_site, leela_cfg, use_extras

__all__ = ['model_path', 'load_models', 'save_model', 'delete_model', 'runtimes', 'model_marks',
           'mark_models', 'JOB_HELP', 'INSTALLABLE', 'runtime_requirements', 'install_runtime',
           'install_state', 'setup_plan', 'dismiss_setup', 'setup_dismissed', 'SETUP_SIZES']

#: What each routed job spends its model on. One copy: the settings pane renders three of these
#: server-side and the rest from `/agent/models`, and two copies drifted apart the first time.
JOB_HELP = {
 'turn': 'Every turn of this conversation and every tool call it makes. The model the agent is.',
 'inline': 'The assistant inside a notebook prompt cell. Unset, it falls back to oneshot.',
 'completion': 'Inline code completion as you type, and "AI edit" on an editor selection. Unset, it falls back to oneshot.',
 'oneshot': 'The fallback for the cheap jobs with no model of their own: classify, completion and inline. Nothing calls it directly, so setting it only moves the jobs you have left unset.',
 'classify': 'One-label questions the agent asks itself mid-turn. Unset, it falls back to oneshot.',
 'summary': 'Context compaction, conversation titles, agent charter drafts, and "summarise selection". Unset, it follows the turn model, so a long conversation is summarised by the model holding it.',
 'subagent': 'Delegated searches and folder-monitor reviews, which run as their own read-only agent. Defaults to gpt-4.1, not to oneshot.'}

API_KEYS = ('base_url', 'api_key_env', 'vendor_name', 'api_name')

def _runtimes():
    from ...agent.core import RUNTIMES
    return tuple(RUNTIMES)

LABELS = {'litert': 'LiteRT', 'mlx': 'MLX', 'llama': 'llama.cpp', 'remote': 'hosted API / FastLLM',
          'cursor': 'Cursor agent', 'claude': 'Claude Code', 'copilot': 'GitHub Copilot'}

def _why(runtime, agents):
    """What to do about a runtime that cannot be reached.

    The answer comes from ramabana, which is where the runtimes are declared. Only the local
    backends are pip extras now; naming one for a harness or a hosted model sends a person to
    install something empty and come back to the same error.
    """
    from ...agent.core import runtime_remedy
    return runtime_remedy(runtime)

#: Runtimes a package can supply, which is the on-device ones, named as rishi's own extras. The
#: rest are not a download: `claude` wants its CLI, `ollama` its daemon, `remote` an API key, and
#: `runtime_remedy` already says so for each. What every backend *needs* is rishi's to declare.
INSTALLABLE = ('litert', 'mlx', 'llama')

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
    """What to install with, which is a different question frozen and not.

    uv resolves better and far faster, and a uv-made venv often has no pip at all, so it wins in a
    normal environment. It cannot drive a frozen app: `--python` makes uv *run* the interpreter to
    interrogate it, and a py2app binary answers that by starting Leela, so the install hangs
    instead of failing. There the shipped pip runs as a module inside the interpreter that already
    is the app, which needs no introspection.
    """
    import importlib.util, shutil
    into = ['--target', str(target)] if target else []
    if not getattr(sys, 'frozen', False) and (uv := shutil.which('uv')):
        return [uv, 'pip', 'install', '--python', sys.executable, *into]
    if importlib.util.find_spec('pip') is not None:
        return [sys.executable, '-m', 'pip', 'install', '--upgrade', *into]
    raise RuntimeError('neither uv nor pip is here, so nothing can be installed for you')

def _run_install(runtime, cmd):
    "The subprocess, on its own thread. Output is kept whole: a resolver error is the useful part."
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
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
    with _lock:
        _installs[runtime].update(state='ok' if ok else 'error', log=log[-4000:],
                                  available=bool(runtime_available(runtime)))

def install_runtime(runtime):
    """Fetch one on-device backend and put it where a frozen app can import it.

    Pinned to what the rishi *here* asks for, never the newest: the bundle freezes one rishi, and a
    backend resolved against a later one is a version skew that shows up as an import error much
    later. A frozen app installs beside itself because its own library is signed and read-only.
    """
    if runtime not in INSTALLABLE:
        raise ValueError(f'{runtime} is not something a package provides; see its remedy')
    if not (reqs := runtime_requirements(runtime)):
        raise ValueError(f'rishi declares no {runtime} backend for this platform')
    with _lock:
        if (cur := _installs.get(runtime)) and cur.get('state') == 'running': return dict(cur)
        target = extras_site() if getattr(sys, 'frozen', False) else None
        if target: target.mkdir(parents=True, exist_ok=True)
        cmd = [*_installer(target), *reqs]
        _installs[runtime] = row = {'runtime': runtime, 'state': 'running', 'log': '',
                                    'cmd': ' '.join(cmd), 'requirements': reqs,
                                    'via': Path(cmd[0]).name, 'target': str(target or '')}
    threading.Thread(target=_run_install, args=(runtime, cmd), daemon=True,
                     name=f'leela-install-{runtime}').start()
    return dict(row)

#: Roughly what each backend weighs once installed, measured on this bundle. Approximate on
#: purpose: the number is there so nobody starts a 400MB download without being told, and a figure
#: that is close is worth more than one that is exact and stale.
SETUP_SIZES = {'mlx': 400, 'llama': 120, 'litert': 70}

#: What an account-based runtime is called on the wizard, and what to do about it. `runtime_remedy`
#: says the same thing for the picker; this is the first-run wording, which has room for a sentence.
ACCOUNTS = (
 ('claude', 'Claude Code', 'Sign in once with `claude /login` and Leela drives it. No key to manage.'),
 ('remote', 'An API key', 'Set ANTHROPIC_API_KEY, OPENAI_API_KEY or GEMINI_API_KEY and its models appear.'),
 ('ollama', 'Ollama', 'Runs its own daemon, so the weights are on your machine and Leela adds nothing.'),
 ('copilot', 'GitHub Copilot', 'Sign in to Copilot in an editor and its models appear here.'))

def _setup_marker(): return leela_cfg/'setup.json'

def setup_dismissed():
    try: return bool(json.loads(_setup_marker().read_text()).get('dismissed'))
    except Exception: return False

def dismiss_setup(dismissed=True):
    "Remember that the first-run pane was answered, so it stops offering itself."
    p = _setup_marker(); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({'dismissed': bool(dismissed)}) + '\n')
    return bool(dismissed)

def setup_plan():
    """The first-run choice: what already works here, and what a download would add.

    Accounts come first and cost nothing to add, which is the honest order -- a hosted model is
    better than a 400MB local one for most work. The offline half is whatever rishi declares a
    backend for *on this machine*, so Windows is never offered mlx and nobody is told to install
    something that has no wheel for them.
    """
    rows = {r['value']: r for r in runtimes()}
    accounts = [{'value': v, 'label': label, 'blurb': blurb,
                 'ready': bool(rows.get(v, {}).get('available')),
                 'why': rows.get(v, {}).get('why', '')} for v, label, blurb in ACCOUNTS]
    offline = [{**rows[v], 'mb': SETUP_SIZES.get(v)} for v in INSTALLABLE
               if v in rows and rows[v]['requirements']]
    return {'frozen': bool(getattr(sys, 'frozen', False)), 'dismissed': setup_dismissed(),
            'accounts': accounts, 'offline': offline,
            'ready': [a['value'] for a in accounts if a['ready']]}

def runtimes():
    "Every runtime, whether rishi can reach it here, and what it wants when it cannot."
    from ...agent.core import AGENTS, runtime_available
    return [{'value': r, 'label': LABELS.get(r, r), 'available': bool(runtime_available(r)),
             'why': _why(r, AGENTS), 'installable': r in INSTALLABLE,
             'requirements': runtime_requirements(r), 'install': install_state(r)}
            for r in _runtimes()]

def model_marks(name):
    "The modality line the CLI banner shows for one model, its runtime, and whether it can draw."
    from ...agent.core import resolve, spec_caps
    try: spec = resolve(name)
    except Exception: return {}
    out = {'runtime': rt} if (rt := getattr(spec, 'runtime', None)) else {}   # the pane warns on cursor
    try: c = spec_caps(spec)
    except Exception: c = None
    return out if c is None else {**out, 'modalities': c.fmt(), 'gen_image': c.gen_image,
                                  'gen_video': c.gen_video}

def mark_models(rows):
    "Stamp every picker row with what its model accepts and returns. No row may fail the picker."
    for r in rows: r.update(model_marks(r.get('value')))
    return rows

def model_path(path=None): return Path(path or leela_cfg/'models.json')

def _rows(path=None):
    try: d = json.loads(model_path(path).read_text())
    except Exception: return []
    return d if isinstance(d, list) else []

def _without(name, path=None):
    "The saved rows, minus any alias called `name`."
    return [x for x in _rows(path) if x.get('name') != name]

def _write(rows, path=None):
    "Persist the alias list, creating the config directory on first save."
    p = model_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, indent=2)+'\n')

def load_models(path=None):
    "Register saved aliases with Ramabana and return valid rows."
    from ...agent.core import register_model
    out = []
    for row in _rows(path):
        try:
            cfg = {k: row.get(k) for k in API_KEYS if row.get(k)}
            spec = register_model(row.get('name'), row.get('model_id'), row.get('runtime'),
                                  row.get('ctx', 128_000), 'saved model', **cfg)
            out.append({**row, 'name': spec.name, 'model_id': spec.model_id, 'runtime': spec.runtime, 'ctx': spec.ctx})
        except Exception: continue
    return out

def save_model(row, path=None):
    "Validate, register and persist one model alias. API keys are never stored here."
    from ...agent.core import MODELS, CUSTOM, register_model
    name = str(row.get('name') or '').strip()
    model_id = str(row.get('model_id') or '').strip()
    runtime = str(row.get('runtime') or '').strip()
    if not re.match(r'^[A-Za-z0-9][\w.-]{0,63}$', name): raise ValueError('name must use letters, numbers, _, . or -')
    if runtime not in (rts := _runtimes()): raise ValueError(f'runtime must be one of {", ".join(rts)}')
    if name in MODELS and name not in CUSTOM: raise ValueError(f'{name!r} is a built-in model name')
    ctx = int(row.get('ctx') or 128_000)
    if not 1024 <= ctx <= 10_000_000: raise ValueError('context must be between 1,024 and 10,000,000 tokens')
    cfg = {k: str(row.get(k) or '').strip() for k in API_KEYS if row.get(k)}
    if runtime != 'remote' and cfg: raise ValueError('API settings apply only to the remote runtime')
    spec = register_model(name, model_id, runtime, ctx, 'saved model', **cfg)
    clean = {'name': name, 'model_id': spec.model_id, 'runtime': runtime, 'ctx': ctx, **cfg}
    _write(_without(name, path)+[clean], path)
    return clean

def delete_model(name, path=None):
    from ...agent.core import unregister_model
    _write(_without(name, path), path)
    unregister_model(name)
    return name
