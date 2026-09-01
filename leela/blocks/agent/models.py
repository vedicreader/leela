"Persistent user-added local and hosted model aliases."
import json, os, re, subprocess, sys, threading, time
from fastcore.all import Path
from fastcore.net import urljson
from ... import extras_site, leela_cfg, use_extras
from ..runtime.support import clean_env

__all__ = ['model_path', 'load_models', 'save_model', 'delete_model', 'runtimes', 'model_marks',
           'mark_models', 'JOB_HELP', 'INSTALLABLE', 'runtime_requirements', 'install_runtime', 'probed', 'catalog', 'forget_probes', 'warm_probes',
           'install_state', 'setup_plan', 'dismiss_setup', 'setup_dismissed', 'SETUP_SIZES', 'RECOMMENDED',
           'unavailable_detail', 'HARNESS', 'TOOLS', 'tool_rows',
           'updates']

#: What each routed job spends its model on. One copy: the settings pane renders three of these
#: server-side and the rest from `/agent/models`, and two copies drifted apart the first time.
JOB_HELP = {
 'turn': 'Every turn of this conversation and every tool call it makes. The model the agent is.',
 'inline': 'The assistant inside a notebook prompt cell, and the one the inline AI panel asks\n'
           'about a selection. Unset, it falls back to oneshot.',
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
    "What to do about an unreachable runtime, from ramabana, which declares them."
    from ...agent.core import runtime_remedy
    return runtime_remedy(runtime)

#: The harness runtimes and what reaching one needs, so an unavailable one can say more than "no".
HARNESS = {'claude': ('rishi.claude', 'claude_bin'), 'copilot': ('rishi.copilot', 'copilot_oauth')}

def unavailable_detail(runtime):
    "The error behind an unavailable harness. `runtime_available` only ever answers yes or no."
    import importlib
    from ... import errstr
    mod, fn = HARNESS.get(runtime) or (None, None)
    if not mod: return ''
    try: m = importlib.import_module(mod)
    except Exception as e: return f'import {mod}: {errstr(e)}'
    try: return '' if getattr(m, fn)() else f'{fn}() found nothing'
    except Exception as e: return f'{fn}(): {errstr(e)}'

#: Runtimes a package can supply, named as rishi's own extras. The rest want a CLI, a daemon or a key.
#: LiteRT left this list in rishi 0.1.32, which took `litert-lm-api` on as a base dependency: there
#: is no `rishi[litert]` to install any more, and nothing to install, because it is always there.
INSTALLABLE = ('mlx', 'llama')

#: Optional tools that are not a model: `(label, requirements, approximate MB, what it gives you)`.
#: `basedpyright` over `ty` and `pyrefly` because it answers everything the LSP client asks for and
#: carries its own node, so it needs neither a system node nor a download when first run.
TOOLS = {'langserver': ('Language server',
                        ['basedpyright>=1.39'], 70,
                        'Red squiggles, hover types, go to definition and rename.')}

#: The last answer from a probe, and the thread refreshing it. Asking what is installed reaches for
#: every backend, and asking who is signed in asks every account: seconds on a cold machine, and the
#: model picker is on the boot path.
_PROBED, PROBE_TTL = {}, 90
_probe_lock = threading.Lock()
#: Bumped whenever the answers are dropped. A probe gathering across that moment was asked about a
#: machine that no longer applies, and its answer is discarded rather than written in behind.
_probe_gen = 0

def probe_path(key):
    "Where one probe's last answer is kept between runs."
    return leela_cfg/'probes'/f"{re.sub(r'[^A-Za-z0-9_.-]', '_', str(key))}.json"

def _read_probe(key):
    "The answer a previous run left, or None. A malformed one is simply not there."
    try: return json.loads(probe_path(key).read_text())['value']
    except Exception: return None

def _write_probe(key, value):
    p = probe_path(key)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f'.{p.name}.{os.getpid()}.tmp')
        tmp.write_text(json.dumps({'at': time.time(), 'value': value}))
        tmp.replace(p)
    except Exception: pass          # a probe that cannot be kept is still an answer

def _keep(key, value, gen):
    "Write an answer in, unless it was gathered about a machine `forget_probes` has since dropped."
    with _probe_lock:
        if gen != _probe_gen: return
        _PROBED[key] = {'at': time.time(), 'value': value, 'busy': False}
    _write_probe(key, value)

def probed(key, fn, ttl=PROBE_TTL):
    """`fn()`'s last answer, with a stale one refreshed behind whoever asked.

    Kept on disk as well as in memory, because a desktop app is a fresh process every launch and an
    in-memory cache is empty exactly when the picker is first drawn. What a previous run learned is
    served at once and re-probed behind it: a model installed since is worth showing a moment late,
    and a pane that will not open is not worth a fresher list.
    """
    with _probe_lock: row, gen = _PROBED.get(key), _probe_gen
    if row is None and (kept := _read_probe(key)) is not None:
        # `at: 0` so the refresh below fires: what a previous run saw is a starting point, not news.
        row = {'at': 0.0, 'value': kept, 'busy': False}
        with _probe_lock:
            if gen == _probe_gen: _PROBED[key] = row
    if row is None:
        value = fn()
        _keep(key, value, gen)
        return value
    if time.time() - row['at'] < ttl or row['busy']: return row['value']
    row['busy'] = True
    def again():
        try: _keep(key, fn(), gen)
        except Exception:
            with _probe_lock: row['at'], row['busy'] = time.time(), False
    threading.Thread(target=again, daemon=True, name=f'leela-probe-{key}').start()
    return row['value']

def catalog(legacy=True):
    """Every model this machine offers, and the id each row resolves to.

    Both halves are probed together because the index is what makes a lookup a lookup: `selected`
    used to scan all ninety-odd rows resolving each one, three times per request, to answer which
    row a chosen model is.
    """
    from ...agent.core import available_models, resolve
    rows = list(available_models(include_legacy=legacy) or [])
    index = {}
    for r in rows:
        # The modality marks go on here rather than per request: `spec_caps` scans the Hugging Face
        # cache for a local model, and doing that once per row per request was three and a half
        # seconds of the picker.
        r.update(model_marks(r.get('value')))
        try: spec = resolve(r['value'])
        except Exception: continue
        if spec is not None: index.setdefault(spec.model_id, r['value'])
    return rows, index

def forget_probes(disk=False):
    "Drop every cached probe. The cache is process-wide, because what it holds is the machine's."
    global _probe_gen
    with _probe_lock: keys, _probe_gen, _ = list(_PROBED), _probe_gen+1, _PROBED.clear()
    if not disk: return
    for key in keys:
        try: probe_path(key).unlink(missing_ok=True)
        except Exception: pass

def warm_probes():
    "Pay for the first probe at startup rather than on the first click."
    from ...agent.core import auth_status
    for legacy in (True, False):
        try: probed(f'catalog:{legacy}', lambda legacy=legacy: catalog(legacy))
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
        # `_runtime_python`: in a bundle `sys.executable` is the app, and installing a backend would
        # launch a second Leela rather than a pip.
        from ..runtime.kernels import _runtime_python
        return [_runtime_python(), '-m', 'pip', 'install', '--upgrade', *into]
    raise RuntimeError('neither uv nor pip is here, so nothing can be installed for you')

def _run_install(runtime, cmd):
    "The subprocess, on its own thread. Output is kept whole: a resolver error is the useful part."
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, env=clean_env())
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

def install_runtime(runtime):
    "Fetch one backend or tool, pinned to the rishi here, where a frozen app can reach it."
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
    threading.Thread(target=_run_install, args=(runtime, cmd), daemon=True,
                     name=f'leela-install-{runtime}').start()
    return dict(row)

#: Approximate installed size, so nobody starts a 400MB download without being told.
SETUP_SIZES = {'mlx': 400, 'llama': 120}

#: The local runtime Leela recommends of the ones left to install. LiteRT arrives with rishi and
#: the vault answers with it, so memory works before anything here is chosen; llama.cpp is the
#: smaller of the two remaining and the only one that runs off a Mac.
RECOMMENDED = 'llama'

#: The first-run wording for an account runtime. `runtime_remedy` is the terser picker version.
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
    "Remember the pane was answered, so it stops offering itself."
    p = _setup_marker(); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({'dismissed': bool(dismissed)}) + '\n')
    return bool(dismissed)

#: The tag the desktop workflow builds from is the version.
RELEASES = 'https://api.github.com/repos/vedicreader/leela/releases/latest'
_latest, _latest_at = {}, 0.0
LATEST_TTL = 3600          #: a courtesy check, not a heartbeat

def _latest_versions(dists):
    "Newest published version of each distribution and of Leela. No network means no offer."
    import time
    global _latest_at
    if time.time() - _latest_at < LATEST_TTL and _latest: return dict(_latest)
    out = {}
    for d in dists:
        try: out[d] = urljson(f'https://pypi.org/pypi/{d}/json', timeout=4)['info']['version']
        except Exception: pass
    try:
        rel = urljson(RELEASES, timeout=4)
        out['leela'] = str(rel.get('tag_name') or '').lstrip('v')
        out['leela_url'] = rel.get('html_url') or ''
    except Exception: pass
    _latest, _latest_at = out, time.time()
    return dict(out)

def _installed_version(dist):
    import importlib.metadata as md
    try: return md.version(dist)
    except Exception: return None

def _newer(installed, latest):
    "Whether `latest` is a later release than `installed`, by the packaging rules and not by string."
    if not (installed and latest): return False
    try:
        from packaging.version import Version
        return Version(latest) > Version(installed)
    except Exception: return False

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
        return _newer(cur, new) and bool(new and spec.contains(new, prereleases=True))

    rows = [{'runtime': rt, 'dist': name, 'installed': cur, 'latest': latest.get(name),
             'pin': str(spec) or 'any', 'outdated': movable(cur, latest.get(name), spec)}
            for name, (rt, cur, spec) in sorted(dists.items())]
    return {'backends': rows, 'outdated': [r for r in rows if r['outdated']],
            'leela': {'current': __version__, 'latest': latest.get('leela'),
                      'url': latest.get('leela_url') or RELEASES.replace('api.github.com/repos', 'github.com'),
                      'outdated': _newer(__version__, latest.get('leela'))},
            'checked': bool(latest)}

def setup_plan():
    "The first-run choice. Accounts cost nothing, so they lead; the offline half is rishi's markers."
    from ...agent.core import auth_status
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
        if v == 'remote': return any(auth.get(k, {}).get('available') for k in ('anthropic', 'openai', 'gemini', 'codex'))
        return bool(rows.get(v, {}).get('available'))
    accounts = [{'value': v, 'label': label, 'blurb': blurb, 'ready': ready(v),
                 'why': rows.get(v, {}).get('why', ''),
                 'detail': '' if ready(v) else rows.get(v, {}).get('detail', '')}
                for v, label, blurb in ACCOUNTS]
    offline = [{**rows[v], 'mb': SETUP_SIZES.get(v), 'recommended': v == RECOMMENDED}
               for v in INSTALLABLE if v in rows and rows[v]['requirements']]
    offline.sort(key=lambda r: not r['recommended'])   # the one we recommend is the one offered first
    ready_now = [a['value'] for a in accounts if a['ready']]
    installed = [o['value'] for o in offline if o['available']]
    return {'frozen': bool(getattr(sys, 'frozen', False)), 'dismissed': setup_dismissed(),
            'accounts': accounts, 'offline': offline, 'tools': tool_rows(), 'ready': ready_now,
            # Set up means: something can answer a prompt. Until then the modal leads with setup;
            # after it, the same modal is where an update shows up.
            'done': bool(ready_now or installed)}

def runtimes():
    "Every runtime, whether rishi can reach it here, and what it wants when it cannot."
    from ...agent.core import AGENTS, runtime_available
    return [{'value': r, 'label': LABELS.get(r, r), 'available': bool(runtime_available(r)),
             'why': _why(r, AGENTS), 'installable': r in INSTALLABLE,
             'requirements': runtime_requirements(r), 'install': install_state(r),
             'detail': '' if runtime_available(r) else unavailable_detail(r)}
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
    """Stamp every picker row with what its model accepts and returns. No row may fail the picker.

    A row the catalog already marked is left alone. `model_marks` reaches `spec_caps`, which scans
    the Hugging Face cache for a local model, and running that over ninety rows on every request
    was three and a half seconds of a picker that is drawn on load.
    """
    for r in rows:
        if 'modalities' in r or 'gen_image' in r: continue
        r.update(model_marks(r.get('value')))
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
