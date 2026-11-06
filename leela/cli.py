"`leela`, the browser IDE entry point."

import argparse, ipaddress, os, sys
from . import PORT

__all__ = ['main']

def main(argv=None):
    p = argparse.ArgumentParser(prog='leela', description='notebooks, files and live variables')
    p.add_argument('folders', nargs='*', help='folders to open (default: the saved workspace, else cwd)')
    p.add_argument('--app', action='store_true',
                   help='open each folder as an independent app window in fossick’s persistent CDP Chrome')
    p.add_argument('--cdp-port', type=int, default=9223,
                   help='Chrome remote-debugging port for --app and the inline browser (default: 9223)')
    p.add_argument('--shell', choices=['chrome', 'webview', 'none'], default=None,
                   help='what opens on top of the server: chrome (fossick’s persistent CDP app '
                        'window, the default under --app), webview (the native window the packaged '
                        'app runs), or none. The inline browser uses the CDP Chrome either way.')
    p.add_argument('--port', type=int, default=PORT, help=f'web IDE port (default: {PORT})')
    p.add_argument('--host', default='127.0.0.1', help='web IDE host (default: 127.0.0.1)')
    p.add_argument('--kernel-port', type=int, default=8400, help='base port for kernel inspectors')
    p.add_argument('--transport', choices=['auto', 'direct', 'gateway'], default='auto',
                   help='kernel transport; auto uses the shared gateway for app windows')
    p.add_argument('--gateway-port', type=int, default=8787,
                   help='shared jupygate port when gateway transport is active')
    p.add_argument('--agent', default='restricted', choices=['restricted', 'readonly', 'off'],
                   help='agent surface on each kernel (default: restricted)')
    p.add_argument('--kernel', default='ipykernel', choices=['ipykernel', 'ipymini'],
                   help='kernel launcher for notebook tabs (default: ipykernel). '
                        'ipymini lets inspector/agent execs run concurrently with a busy cell; '
                        'both launchers ship with Leela and can be installed into a project from the picker.')
    p.add_argument('--model', default=None,
                   help='the agent\'s model: a short name (opus, sonnet, flash, qwen-4b, ...) '
                        'or any vendor/model spec (default: claude-opus-5-5). Completion and classification '
                        'run on claude-haiku-5-5, oneshot and summaries on gpt-6.1-luna, sub-agents on '
                        'claude-sonnet-5-5; without OPENAI_API_KEY the gpt jobs use the turn model. A local model keeps every '
                        'job without a model of its own on the machine. Override per job with '
                        'LEELA_MODEL_SUMMARY and friends. Nothing is chosen for you: without Claude Code, add a '
                        'provider with + model in the agent pane or `ramabana setup`.')
    p.add_argument('--approvals', default='ask', choices=['ask', 'auto', 'off'],
                   help='what happens when the agent wants to write: ask a person (default), '
                        'approve everything, or refuse everything')
    p.add_argument('--agent-scope', default='overlay', choices=['overlay', 'isolated'],
                   help="widest scope the agent's read-only inspection may use. overlay "
                        '(default) gives it the real interpreter against your namespace, '
                        'with your variables protected by policy and its own bindings kept '
                        'in a separate layer; isolated confines it to an allowlist sandbox '
                        'on a copy, which refuses most library calls')
    p.add_argument('--python', default=None,
                   help='interpreter to launch kernels under (default: the one running leela). '
                        'Also selectable from the kernel picker in either frontend.')
    p.add_argument('--keymap', default=None,
                   help='keybindings file to apply over the defaults '
                        '(default: $LEELA_KEYMAP, else keys.json in leela’s config dir)')
    p.add_argument('--write-keymap', action='store_true',
                   help='write the chords you have changed to that file, with every action and its '
                        'default listed beside them, then exit — the starting point for rebinding '
                        'anything your terminal swallows')
    a = p.parse_args(argv)
    if a.keymap: os.environ['LEELA_KEYMAP'] = os.path.abspath(a.keymap)
    if a.write_keymap:
        from .core.keys import write_keymap, keymap_path, NOTES
        path = write_keymap()
        print(f'wrote {path}')
        print('  action -> chord, or several chords separated by spaces; "" unbinds it.')
        print('  "keys" holds what you changed; copy a line out of "_defaults" to change one more.')
        for n in NOTES: print(f'  ⚠ {n}')
        return
    from .core import host
    # The Mac app runs this server as its child: its env, its dialogs, and no extras folder to shadow the pinned packages.
    if host.take(): host.setup()
    else: _plain_setup()
    roots = [os.path.abspath(f) for f in a.folders]
    for r in roots:
        if not os.path.isdir(r): p.error(f'not a directory: {r}')
    try:
        loopback = a.host == 'localhost' or ipaddress.ip_address(a.host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        p.error('Leela executes code and is intentionally loopback-only; use 127.0.0.1, ::1, or localhost')
    shell = a.shell or ('chrome' if a.app else 'none')
    from .app import serve_ide
    serve = lambda s: serve_ide(roots, port=a.port, host=a.host, agent=a.agent,
                                kernel_port=a.kernel_port, kernel=a.kernel, model=a.model,
                                approvals=a.approvals, agent_scope=a.agent_scope,
                                python=a.python, app_window=a.app, cdp_port=a.cdp_port,
                                transport=a.transport, gateway_port=a.gateway_port, shell=s)
    if shell != 'webview': return serve(shell)
    import threading
    from .desktop import run_shell, shell_ready, warm_cdp
    from .hub import workspace_urls
    ok, why = shell_ready()
    if not ok: p.error(f'--shell webview: {why}')
    urls = workspace_urls(roots, a.port) if (a.app and roots) else [f'http://{a.host}:{a.port}/']
    titles = [f'leela — {os.path.basename(r)}' for r in roots] if len(urls) == len(roots) else ['leela']
    threading.Thread(target=serve, args=('none',), daemon=True, name='leela-server').start()
    warm_cdp(a.cdp_port)
    run_shell(urls, titles=titles)

def _plain_setup():
    # Put the extras directory on the path where the process starts, not only after an install.
    from . import use_extras
    use_extras()
    # A window opened from Finder has launchd's environment, not a shell's, so the keys and the
    # tools a profile exports are missing. `LEELA_SHELL_ENV=0` keeps the environment as launched.
    if os.environ.get('LEELA_SHELL_ENV', '1') != '0' and (getattr(sys, 'frozen', False)
                                                          or os.environ.get('LEELA_SHELL_ENV') == '1'):
        from .core.envs import import_login_env
        import_login_env()
    # Leela's own, whatever the launch was, and last: a value typed into Leela is the answer for a
    # machine where asking the shell gives the wrong one.
    from .core.envs import apply_stored_env
    apply_stored_env()

if __name__ == '__main__': main()
