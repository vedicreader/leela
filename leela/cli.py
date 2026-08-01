"""`leela` — the IDE entry point.

    leela                 open the saved workspace in the terminal
    leela .               open a folder in the terminal
    leela --web src tests open two folders in the browser
"""

import argparse, os

__all__ = ['main']


def main(argv=None):
    p = argparse.ArgumentParser(prog='leela', description='notebooks, files and live variables')
    p.add_argument('folders', nargs='*', help='folders to open (default: the saved workspace, else cwd)')
    p.add_argument('--web', action='store_true', help='run the browser frontend instead of the terminal one')
    p.add_argument('--port', type=int, default=5001, help='web IDE port (default: 5001)')
    p.add_argument('--host', default='127.0.0.1', help='web IDE host (default: 127.0.0.1)')
    p.add_argument('--kernel-port', type=int, default=8400, help='base port for kernel inspectors')
    p.add_argument('--agent', default='restricted', choices=['restricted', 'readonly', 'off'],
                   help='agent surface on each kernel (default: restricted)')
    p.add_argument('--kernel', default='ipykernel', choices=['ipykernel', 'ipymini'],
                   help='kernel launcher for notebook tabs (default: ipykernel). '
                        'ipymini lets inspector/agent execs run concurrently with a busy cell '
                        'via its subshell helper; install with `pip install "leela[ipymini]"`.')
    p.add_argument('--model', default=None,
                   help='the agent\'s model: a short name (sonnet, opus, flash, gemma-e2b, ...) '
                        'or any vendor/model spec. Cheap jobs -- completion, classification, '
                        'summaries, sub-agents -- stay on the local model whatever this says; '
                        'override per job with LEELA_MODEL_SUMMARY and friends.')
    p.add_argument('--approvals', default='ask', choices=['ask', 'auto', 'off'],
                   help='what happens when the agent wants to write: ask a person (default), '
                        'approve everything, or refuse everything')
    p.add_argument('--allow-remote-terminal', action='store_true',
                   help='serve the web terminal even on a non-loopback host (this is a remote shell)')
    a = p.parse_args(argv)
    roots = [os.path.abspath(f) for f in a.folders]
    for r in roots:
        if not os.path.isdir(r): p.error(f'not a directory: {r}')
    if a.web:
        from .web.app import serve_ide
        serve_ide(roots, port=a.port, host=a.host, agent=a.agent, kernel_port=a.kernel_port,
                  kernel=a.kernel, model=a.model, approvals=a.approvals,
                  allow_remote_terminal=a.allow_remote_terminal)
    else:
        from .tui.app import run
        run(roots, agent=a.agent, kernel_port=a.kernel_port, kernel=a.kernel,
            model=a.model, approvals=a.approvals)


if __name__ == '__main__': main()
