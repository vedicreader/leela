"Managed kernels: kunda's, told which languages Leela knows and where it keeps its logs."

from __future__ import annotations

from kunda.kernel import (GATEWAY_DEPS, KERNELS, SHUTDOWN_WAIT, GatewayKernel,  # noqa: F401
    GatewayService, InspectorClient, Kernel, check_gateway_deps, give_up_after, ipymini_available)
from kunda.pool import (IDLE_SECONDS, SWEEP_SECONDS, KernelLimit,  # noqa: F401
    KernelPool as _KernelPool, RuntimeBroker)
from kunda.pythons import (VENV_BINS, VENV_DIRS, VENV_PYTHONS,  # noqa: F401
    project_python, use_app, venv_env, venv_roots)
from kunda.pythons import find_pythons as _find_pythons, nearest_python
from kunda.pythons import python_for as _python_for
from kunda.spec import (ExecOutcome, KernelStartError, bootstrap_src as _bootstrap_src,  # noqa: F401
    installed_kernels, missing_kernel_module, output_text, run_file_src)
from kunda.spec import frozen_pythonpath, runtime_python  # noqa: F401  blocks ask which interpreter to spawn, and what its bundle needs
from kunda.spec import kernel_spec
from kunda.spec import installed_spec as _installed_spec, kernelspec_for as _kernelspec_for

from .support import LEELA_PY

from fastcore.xtras import Path
from kunda.pythons import clean_env, strip_bundle

from kunda.support import support_paths, work_dir

__all__ = ['ExecOutcome', 'Kernel', 'KernelStartError', 'GatewayKernel', 'GatewayService', 'KernelPool',
           'RuntimeBroker', 'KernelLimit', 'check_gateway_deps',
           'bootstrap_src', 'output_text', 'ipymini_available', 'missing_kernel_module', 'find_pythons',
           'installed_kernels', 'kernelspec_for', 'installed_spec',
           'project_python', 'nearest_python', 'python_for', 'project_of', 'python_project', 'venv_env', 'run_file_src', 'NoVenv']

#: Names kunda's app and env prefix Leela's way; must run on the import other modules reach kunda through.
use_app('leela', 'LEELA_')

#: Where the conversation logs a bootstrapped kernel writes go, under the folder it runs in.
SESSIONS, AGENT_SESSIONS = '_leela_sessions', '_leela_agent_sessions'

def _known(lang=None):
    "Leela's `{language: kernelspec}`, with the alias a caller asked about resolved into it."
    from ...core.langs import LANGS, lang_named
    out = {l.id: l.kernel for l in LANGS.values() if l.kernel}
    out |= {l.kernel: l.kernel for l in LANGS.values() if l.kernel}
    if lang and (l := lang_named(lang)) and l.kernel: out[str(lang)] = l.kernel
    return out

def _installs():
    from ...core.langs import LANGS
    return {l.id: l.install for l in LANGS.values() if l.install}

def _install_for(lang):
    from ...core.langs import lang_named
    l = lang_named(lang)
    return l.install if l else ''

def project_of(cwd, session=None):
    "The project folder `cwd` belongs to: its nearest checkout inside the open folder, else that folder; None outside every folder."
    from ...core.projects import project_dir
    if not cwd or session is None: return None
    try: root = session.fs.root_of(cwd)
    except Exception: return None
    return project_dir(cwd, root) or root

class NoVenv(KernelStartError):
    "A project with no venv and no chosen interpreter: Leela runs no Python there until the person sets one up or picks one."
    kind = 'no_venv'
    def __init__(self, proj):
        self.proj = Path(proj); self.refs = [str(self.proj)]
        self.said = f'No Python environment for {self.proj.name}. Set up .venv or choose an interpreter.'
        super().__init__(self.said)
    @property
    def for_agent(self):
        "The tool error the agent gets: the two choices are the person's."
        return (f'{self.said} Leela runs no code in {self.proj.name} until the person presses Set up .venv or '
                'Choose interpreter… in the notice. Ask them; do not make a venv unless they ask you to.')

def python_project(root):
    "Whether `root` is a Python project, whose runs belong in its own venv."
    return any((Path(root)/m).exists() for m in ('pyproject.toml', 'setup.py', 'setup.cfg', 'settings.ini'))

def python_for(cwd=None, session=None, stop=None):
    "The interpreter anything Leela spawns for `cwd` should be inside: the chosen one, else the project's nearest venv; None is Leela's own."
    if session is None: return _python_for(cwd, stop or cwd)
    proj = project_of(cwd, session)
    if (py := (getattr(session, 'chosen_python', None) or {}).get(str(proj))): return py
    return _python_for(cwd, stop or proj or cwd, default=session.pool.default_python)

def find_pythons(roots=(), current=None):
    "Interpreters a kernel could be launched under, this one among them."
    return _find_pythons(roots, current, 'this one (leela’s own)')

def bootstrap_src(name=None, port=8000, agent='restricted', token=True, kernel='ipykernel'):
    "The bootstrap cell source for a kernel that should host an inspector."
    return _bootstrap_src(name, port, agent, token, SESSIONS, AGENT_SESSIONS)

def kernelspec_for(lang):
    "The installed kernelspec name that runs `lang`, or None. Leela's registry wins."
    return _kernelspec_for(lang, _known(lang))

def installed_spec(lang):
    "The `KernelSpec` for `lang`, or a `KernelStartError` naming what would install one."
    return _installed_spec(lang, _known(lang), _install_for(lang))

def _spec(python=None, name='python3', kernel='ipykernel', lang='python'):
    "A kernelspec pinned to a specific interpreter, so the kernel runs in *this* venv."
    return kernel_spec(python, name, kernel, lang, _known(lang), _install_for(lang))

class KernelPool(_KernelPool):
    "The IDE's kernels: Leela's language registry, and its own runners where no kernel is installed."
    def __init__(self, port=8000, default_kernel='ipykernel', default_python=None, broker=None,
        transport='direct', gateway=None, idle=None):
        from .runners import runner_for
        super().__init__(port, default_kernel, default_python, broker, transport, gateway, idle,
                         runner_for=runner_for, known_kernels=_known(), install_hints=_installs())
    async def close_all(self):
        "Leaving waits for nothing still coming up: a kernel that has not answered yet is cancelled, and the rest is given a deadline."
        for task in list(self._starting.values()): task.cancel()
        await give_up_after(super().close_all(), SHUTDOWN_WAIT * 3)
