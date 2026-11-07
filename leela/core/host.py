"Host mode: the Leela Mac app runs this server as its child and answers on a loopback control server. kavacha.host is the client; see docs/thin-app.md."
import os, sys
from kavacha.host import HostClient, HostError, owned, agent_scripts as _scripts, link_tools as _link, scrub

__all__ = ['HostError', 'OWNED', 'AGENT_TOOLS', 'client', 'take', 'on', 'is_app', 'unbuild', 'tools_dir', 'agent_scripts', 'link_tools', 'with_tools', 'steered', 'call', 'status', 'confirm', 'grant_ok', 'setup', 'app_version', 'lock_n']

#: What the launcher sets for its child. No shell and no stored value replaces these.
OWNED = owned('LEELA_')
#: Packages of the app's env whose console scripts an agent's shell runs by name.
AGENT_TOOLS = ('ramabana', 'koshas', 'exhash', 'fossick', 'litesearch', 'vishalakshi', 'gheasy', 'safepyrun', 'pyskills', 'rgapi', 'mdhtml')

client = HostClient('LEELA_', 'Leela')
take, on, is_app, steered, app_version, lock_n = client.take, client.on, client.is_app, client.steered, client.app_version, client.lock_n
call, grant_ok, status, tools_dir, with_tools = client.call, client.grant_ok, client.status, client.tools_dir, client.with_tools

#: what app 1.0.0's launcher gave this server and its children would inherit
unbuild = scrub

def agent_scripts(pkgs=AGENT_TOOLS): return _scripts(pkgs)
def link_tools(names=None, src=None, dst=None): return _link(agent_scripts() if names is None else names, src, dst or client.tools_dir())

def confirm(question):
    "Ask in a native dialog of the app. Every failure is `NoWindow`, so a broken answer is never taken as a No."
    from ..hub import NoWindow
    try: return client.ask(question)
    except HostError as e: raise NoWindow(str(e)) from e

def setup():
    "What a launch from the app needs: no build settings, UTF-8, the login PATH and keys, Leela's stored values, the app's dialogs. No extras folder: the env is the app's."
    from .. import use_login_path, use_utf8
    from ..hub import set_confirmer
    from .envs import apply_stored_env, import_login_env
    # first: the login shell and stored values only fill a name that is empty
    unbuild()
    use_utf8(); use_login_path()
    if os.environ.get('LEELA_SHELL_ENV', '1') != '0': import_login_env()
    apply_stored_env()
    try: link_tools()
    except OSError as e: print(f'leela: the agent tools are not linked: {e}', file=sys.stderr)
    set_confirmer(confirm)
