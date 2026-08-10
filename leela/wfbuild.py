"""Building a workflow by choosing, not by typing YAML.

The catalogue in `leela.workflows` answers "which workflow does this project want"; this
answers the next question, which is the one that actually stops people: *now change it*.
Add a lint job before the tests. Publish on a release instead of on every push. Run it on
Mondays. Every one of those is one line of YAML in the right place and an afternoon of
guessing at indentation, `needs`, and which of `on:`'s three shapes applies.

So the panel edits a **spec** -- triggers, and a list of jobs with their options -- and
`compose` turns that spec into gheasy's `WorkflowBuilder` calls. Nothing here writes YAML:
every job is a gheasy preset or gheasy's DSL, so the file is the one the `gheasy` CLI would
have produced and stays readable to gheasy's own tools.

`PRESETS` is the whole vocabulary, and it is *data* -- each entry declares its options with
a type and a default, so the browser renders a form from it and a preset gained here appears
in the panel without a line of frontend. That is what makes this teachable rather than
merely convenient: the form is the list of decisions a workflow actually has.

The spec is saved beside the file it produced (`.leela/workflows/<file>.json`), because
reading a workflow back into a spec is lossy -- someone edits the YAML by hand and the
builder would either lose the edit or refuse to open. Keeping the spec means reopening what
*you built*, and the panel says plainly when the file on disk has moved on from it.
"""

from __future__ import annotations

import json
from pathlib import Path

__all__ = ['PRESETS', 'TRIGGERS', 'compose', 'spec_path', 'load_spec', 'save_spec', 'preset_rows']

SPEC_DIR = '.leela/workflows'

# Every trigger the panel offers, in the shape gheasy's `TriggerBuilder` takes them. `kind`
# is what the form renders: a checkbox, a comma list of branches, or a cron string.
TRIGGERS = [
    {'id': 'push', 'label': 'on push', 'kind': 'branches', 'default': 'main',
     'doc': 'Every push to these branches.'},
    {'id': 'pull_request', 'label': 'on pull request', 'kind': 'branches', 'default': 'main',
     'doc': 'Every pull request targeting these branches.'},
    {'id': 'workflow_dispatch', 'label': 'run button', 'kind': 'flag', 'default': True,
     'doc': 'Adds a Run button, here and on GitHub. Worth having on almost everything.'},
    {'id': 'release', 'label': 'on release', 'kind': 'flag', 'default': False,
     'doc': 'When a GitHub release is published — what a PyPI publish job waits for.'},
    {'id': 'schedule', 'label': 'on a schedule', 'kind': 'cron', 'default': '0 9 * * 1',
     'doc': 'A cron expression in UTC. `0 9 * * 1` is Mondays at 09:00.'},
]

# Each preset is one job. `options` are rendered as a form; `id` is the job id gheasy gives
# it, which is what other jobs name in `needs`.
PRESETS = [
    {'id': 'uv_test', 'job': 'test', 'name': 'Test (uv)',
     'doc': 'Checkout, install with uv, run the tests.',
     'options': [
         {'key': 'test_cmd', 'label': 'test command', 'type': 'text', 'default': 'pytest',
          'doc': 'Run through `uv run`, so `pytest -x` becomes `uv run pytest -x`.'},
         {'key': 'python_versions', 'label': 'python versions', 'type': 'list', 'default': '',
          'doc': 'Comma separated. More than one adds a matrix; empty runs once.'}]},
    {'id': 'uv_lint', 'job': 'lint', 'name': 'Lint (ruff)',
     'doc': 'ruff check and a formatting check.',
     'options': [{'key': 'lint_cmd', 'label': 'lint command', 'type': 'text',
                  'default': 'uv run ruff check . && uv run ruff format --check .', 'doc': ''}]},
    {'id': 'nbdev_test', 'job': 'test', 'name': 'Test (nbdev)',
     'doc': 'nbdev_test, and a check that the notebooks are clean — what breaks in an nbdev repo.',
     'options': []},
    {'id': 'uv_pypi', 'job': 'publish', 'name': 'Publish to PyPI',
     'doc': 'Build and publish through trusted publishing. Only runs on a release event, so '
            'pair it with the release trigger.',
     'options': []},
    {'id': 'docker', 'job': 'docker', 'name': 'Docker image',
     'doc': 'Build and push to GHCR as :latest.',
     'options': [{'key': 'app_name', 'label': 'image name', 'type': 'text', 'default': '',
                  'doc': 'Defaults to the project name.'}]},
    {'id': 'node', 'job': 'frontend', 'name': 'Node build', 'doc': 'npm ci, build, test.',
     'options': []},
    {'id': 'rust', 'job': 'build', 'name': 'Rust build', 'doc': 'cargo build, test, clippy.',
     'options': []},
    {'id': 'go', 'job': 'build', 'name': 'Go build', 'doc': 'go build, test, vet.', 'options': []},
    {'id': 'deploy', 'job': 'deploy', 'name': 'Deploy to a VPS',
     'doc': 'Every key in env_schema as a secret or a variable, the deploy key, then your '
            'deploy command. The shape lego uses.',
     'options': [
         {'key': 'cmd', 'label': 'deploy command', 'type': 'text', 'default': 'python deploy.py deploy',
          'doc': ''},
         {'key': 'lfs', 'label': 'checkout LFS files', 'type': 'flag', 'default': True, 'doc': ''}]},
    {'id': 'run', 'job': 'run', 'name': 'Anything else',
     'doc': 'Checkout, install with uv, then the commands you give it — one per line.',
     'options': [
         {'key': 'job_id', 'label': 'job id', 'type': 'text', 'default': 'run',
          'doc': 'What other jobs name in `needs`.'},
         {'key': 'cmds', 'label': 'commands', 'type': 'lines', 'default': 'echo hello',
          'doc': 'One step per line.'},
         {'key': 'install', 'label': 'install dependencies first', 'type': 'flag', 'default': True,
          'doc': ''}]},
]


def preset_rows():
    "The vocabulary, as the panel renders it. Data, so a new preset needs no frontend change."
    return {'presets': PRESETS, 'triggers': TRIGGERS}


def _listy(value):
    if isinstance(value, (list, tuple)): return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in str(value or '').split(',') if v.strip()]


def _lines(value):
    if isinstance(value, (list, tuple)): return [str(v) for v in value if str(v).strip()]
    return [l for l in str(value or '').splitlines() if l.strip()]


def _triggers(wfb, on):
    """Apply the trigger part of a spec.

    `on:` has three shapes in the file format and one builder here, which is the point of
    the spec: a checkbox cannot produce the wrong one.
    """
    used = False
    push = on.get('push')
    if push not in (None, False):
        wfb.on.push(branches=_listy(push if push is not True else 'main') or ['main'])
        used = True
    pr = on.get('pull_request')
    if pr not in (None, False):
        wfb.on.pull_request(branches=_listy(pr if pr is not True else 'main') or ['main'])
        used = True
    if on.get('workflow_dispatch'):
        wfb.on.workflow_dispatch()
        used = True
    if on.get('release'):
        wfb.on.release(types=['published'])
        used = True
    cron = on.get('schedule')
    if cron:
        wfb.on.schedule(str(cron).strip())
        used = True
    if not used:
        # A workflow with no triggers can only ever be started by hand, so say so in the
        # file rather than producing one that silently never runs.
        wfb.on.workflow_dispatch()


def _deploy_job(wfb, job_id, opts, schema, app):
    "lego's deploy job: the schema as `env:`, the key, then the command."
    env = {k: (f'${{{{ secrets.{k} }}}}' if v is None else f'${{{{ vars.{k} }}}}')
           for k, v in (schema or {}).items()}
    env['DEPLOY_KEY'] = '${{ secrets.DEPLOY_KEY }}'
    ssh = ('mkdir -p ~/.ssh && name="${SERVER_NAME:-' + app + '}" '
           '&& echo "$DEPLOY_KEY" > ~/.ssh/"$name" && chmod 600 ~/.ssh/"$name"')
    job = wfb.job(job_id, needs=opts.get('needs') or None).runs_on('ubuntu-latest').env(**env)
    step = job.checkout()
    if opts.get('lfs', True): step = step.with_(lfs=True)
    (step.end_step().setup_uv().with_(python_version='3.13').end_step()
         .uv_install('uv sync --group dev').end_step()
         .step('Install SSH key').if_("env.DEPLOY_KEY != ''").run(ssh).end_step()
         .step('Deploy').run(str(opts.get('cmd') or 'python deploy.py deploy')).end_job())


def _run_job(wfb, job_id, opts):
    job = wfb.job(job_id, needs=opts.get('needs') or None).runs_on('ubuntu-latest')
    step = job.checkout().end_step().setup_uv().end_step()
    if opts.get('install', True): step = step.uv_install().end_step()
    cmds = _lines(opts.get('cmds')) or ['echo hello']
    for i, cmd in enumerate(cmds):
        step = step.step(f'Step {i + 1}').run(cmd)
        step = step.end_step() if i + 1 < len(cmds) else step
    step.end_job()


def compose(spec, schema=None, app=''):
    """A spec as YAML, built entirely with gheasy.

    Job ids are made unique as they are added: two "Anything else" jobs are a normal thing
    to want, and a builder that produced two jobs with the same id would emit a file GitHub
    rejects for a reason the person who clicked "add" could not be expected to see.
    """
    from gheasy.workflow import Workflow
    spec = spec or {}
    app = str(app or spec.get('app') or 'app')
    wfb = Workflow(str(spec.get('name') or 'ci'))
    _triggers(wfb, spec.get('on') or {})
    by_id = {p['id']: p for p in PRESETS}
    used = set()
    for row in spec.get('jobs') or ():
        preset = by_id.get(str((row or {}).get('preset') or ''))
        if preset is None: continue
        opts = dict(row.get('options') or {})
        needs = [n for n in _listy(row.get('needs')) if n]
        opts['needs'] = needs or None
        job_id = str(row.get('id') or opts.get('job_id') or preset['job'])
        n = 2
        while job_id in used: job_id, n = f"{preset['job']}{n}", n + 1
        used.add(job_id)
        pid = preset['id']
        if pid == 'uv_test':
            wfb.uv_test_job(test_cmd=str(opts.get('test_cmd') or 'pytest'), needs=opts['needs'],
                            python_versions=_listy(opts.get('python_versions')) or None)
        elif pid == 'uv_lint':
            wfb.uv_lint_job(lint_cmd=str(opts.get('lint_cmd') or
                                         'uv run ruff check . && uv run ruff format --check .'),
                            needs=opts['needs'])
        elif pid == 'uv_pypi': wfb.uv_pypi_job(needs=opts['needs'])
        elif pid == 'docker': wfb.docker_job(str(opts.get('app_name') or app), needs=opts['needs'])
        elif pid == 'node': wfb.node_job()
        elif pid == 'rust': wfb.rust_job()
        elif pid == 'go': wfb.go_job()
        elif pid == 'nbdev_test':
            (wfb.job(job_id, needs=opts['needs']).runs_on('ubuntu-latest')
                .checkout().end_step().setup_uv().end_step().uv_install().end_step()
                .uv_run('nbdev_test').end_step()
                .step('Notebooks are clean').run('uv run nbdev_clean --check_all').end_job())
        elif pid == 'deploy': _deploy_job(wfb, job_id, opts, schema, app)
        elif pid == 'run': _run_job(wfb, job_id, opts)
    return wfb.build().to_yaml()


def spec_path(root, file):
    return Path(root)/SPEC_DIR/(str(file).rsplit('.', 1)[0] + '.json')


def load_spec(root, file):
    "The spec a workflow was built from, or None when it was written some other way."
    try: return json.loads(spec_path(root, file).read_text(encoding='utf-8'))
    except (OSError, ValueError): return None


def save_spec(root, file, spec):
    p = spec_path(root, file)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(spec, indent=2) + '\n', encoding='utf-8')
    return p
