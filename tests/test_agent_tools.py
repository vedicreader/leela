"""Tests for the tools the loop actually turns on: a shell, exact-text edits, and grep.

These are the capabilities the harness went without, and each test here is written against
the failure that made it worth adding rather than against the happy path:

- an agent that can edit but cannot run a command has no way to be contradicted, so it
  reports success instead of checking;
- an edit that is applied one span at a time leaves a half-edited file behind when the
  third span is stale, which is worse than doing nothing;
- a truncated tool result with no way to resume is a dead end the model fills in by
  guessing.

Nothing here loads a model, and nothing touches the disk except through `tmp_path`.
"""

import pytest

from leela.agent.agent import RULES, project_context, system_prompt, work_rules
from leela.agent.testing import MemHost
from leela.agent.tools import (ERR, WRITE_TOOLS, clip, clip_lines, err, failed, file_tools,
                               code_tools, shell_tools, tools_for)


def named(tools):
    return {t.__name__: t for t in tools}


# ---------------------------------------------------------------------------
# the failure convention
# ---------------------------------------------------------------------------
def test_every_failure_is_spelled_the_same_way():
    """Neither engine carries an `is_error` flag through to the model, so the flag has to
    be in the text -- and it is only useful if there is exactly one of it."""
    assert failed(err('could not read x'))
    assert failed(err('write failed', ValueError('nope')))
    assert not failed('exit 0\nall tests passed')
    assert err('a', ValueError('b')) == f'{ERR}a: ValueError: b'


def test_a_truncated_result_says_how_to_continue():
    "A model that cannot resume a truncated read invents the rest or reads the same half again."
    out = clip_lines([f'line {i}' for i in range(1, 500)], start=1, n=120,
                     more='call view_file(path, start={next}) to continue')
    assert 'more line(s) not shown' in out
    assert 'start=' in out and 'start={next}' not in out
    assert clip_lines([], empty='(nothing)') == '(nothing)'


def test_truncation_never_ends_mid_line():
    out = clip_lines(['x' * 50, 'y' * 50, 'z' * 50], n=60)
    assert 'y' not in out.split('…')[0].split('\n')[-1]


def test_clip_keeps_a_short_result_untouched():
    assert clip('short') == 'short'
    assert 'truncated' in clip('x' * 100, n=50)


# ---------------------------------------------------------------------------
# a shell, which is what lets the model be contradicted
# ---------------------------------------------------------------------------
def test_a_host_that_cannot_run_commands_is_not_offered_the_tool():
    from leela.agent.tools import NullHost
    assert 'run_shell' not in named(tools_for(NullHost(['/x'])))


def test_a_host_that_can_run_commands_gets_the_tool_without_running_one():
    "The capability probe must not itself be a side effect: a command is not a harmless call."
    h = MemHost()
    assert 'run_shell' in named(tools_for(h))
    assert h.cmds == []


def test_a_failing_command_comes_back_marked_as_a_failure():
    """The whole point of the tool. A non-zero exit that reads like ordinary output is a
    test suite the model will report as passing."""
    h = MemHost(commands={'pytest -q': (1, '2 failed, 3 passed')})
    run = named(shell_tools(h))['run_shell']
    out = run('pytest -q')
    assert failed(out) and 'exit 1' in out and 'FAILED' in out and '2 failed' in out


def test_a_passing_command_is_not_marked_as_a_failure():
    h = MemHost(commands={'pytest -q': (0, '5 passed')})
    out = named(shell_tools(h))['run_shell']('pytest -q')
    assert not failed(out) and out.startswith('exit 0') and '5 passed' in out


def test_a_silent_command_still_says_it_ran():
    out = named(shell_tools(MemHost()))['run_shell']('ruff check .')
    assert 'exit 0' in out and '(no output)' in out


def test_an_empty_command_is_refused_rather_than_run():
    h = MemHost()
    assert failed(named(shell_tools(h))['run_shell']('   '))
    assert h.cmds == []


def test_the_command_and_its_directory_reach_the_host_unchanged():
    h = MemHost()
    named(shell_tools(h))['run_shell']('git status --short', cwd='/proj/sub', timeout=30)
    assert h.cmds == [('git status --short', '/proj/sub', 30)]


def test_running_a_command_needs_approval():
    "A shell can name any path, so confining the working directory is not the sandbox: the person is."
    assert 'run_shell' in WRITE_TOOLS


# ---------------------------------------------------------------------------
# exact-text editing
# ---------------------------------------------------------------------------
SRC = 'def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n'


def editor(files=None):
    h = MemHost(files if files is not None else {'/proj/m.py': SRC})
    return h, named(file_tools(h))['replace_text']


def test_two_edits_to_one_file_land_in_one_call():
    h, edit = editor()
    out = edit('/proj/m.py', '[{"oldText": "a + b", "newText": "a + b + 1"},'
                             ' {"oldText": "a - b", "newText": "a - b - 1"}]')
    assert not failed(out) and 'replaced 2 block(s)' in out
    assert h.files['/proj/m.py'] == SRC.replace('a + b', 'a + b + 1').replace('a - b', 'a - b - 1')


def test_the_diff_comes_back_so_the_result_can_be_checked():
    _, edit = editor()
    out = edit('/proj/m.py', '[{"oldText": "a + b", "newText": "a * b"}]')
    assert '-    return a + b' in out and '+    return a * b' in out


def test_an_ambiguous_oldtext_is_refused_and_says_what_to_do():
    """`return a` appears twice. Picking one is how an agent silently edits the wrong
    function; saying which and why is how it recovers in one turn instead of three."""
    h, edit = editor()
    out = edit('/proj/m.py', '[{"oldText": "return a", "newText": "return 0"}]')
    assert failed(out) and 'matches 2 places' in out and 'more surrounding' in out
    assert h.files['/proj/m.py'] == SRC


def test_a_stale_oldtext_is_refused_and_says_what_to_do():
    h, edit = editor()
    out = edit('/proj/m.py', '[{"oldText": "def add(a, b, c):", "newText": "x"}]')
    assert failed(out) and 'not found' in out and 'Re-read' in out
    assert h.files['/proj/m.py'] == SRC


def test_one_bad_edit_leaves_the_whole_file_alone():
    "Atomicity is the reason to locate every span before applying any of them."
    h, edit = editor()
    out = edit('/proj/m.py', '[{"oldText": "a + b", "newText": "ok"},'
                             ' {"oldText": "not in the file", "newText": "x"}]')
    assert failed(out) and 'edit 2' in out
    assert h.files['/proj/m.py'] == SRC


def test_overlapping_edits_are_refused_rather_than_applied_in_some_order():
    h, edit = editor()
    out = edit('/proj/m.py', '[{"oldText": "def add(a, b):\\n    return a + b", "newText": "x"},'
                             ' {"oldText": "return a + b", "newText": "y"}]')
    assert failed(out) and 'overlap' in out
    assert h.files['/proj/m.py'] == SRC


def test_an_empty_oldtext_is_refused_with_the_tool_that_does_want_it():
    _, edit = editor()
    out = edit('/proj/m.py', '[{"oldText": "", "newText": "x"}]')
    assert failed(out) and 'create_file' in out


def test_a_no_op_edit_is_reported_rather_than_called_a_success():
    "A model told 'replaced 1 block' when nothing moved will build its next edit on a fiction."
    _, edit = editor()
    out = edit('/proj/m.py', '[{"oldText": "a + b", "newText": "a + b"}]')
    assert failed(out) and 'changed nothing' in out


def test_editing_a_file_that_is_not_there_points_at_create_file():
    _, edit = editor()
    out = edit('/proj/nope.py', '[{"oldText": "a", "newText": "b"}]')
    assert failed(out) and 'create_file' in out


def test_the_shapes_a_model_actually_sends_are_all_accepted():
    """A JSON string, a list of dicts, and a list of pairs are each unambiguous. Refusing
    one costs a turn to a message that says 'send it the other way'."""
    for edits in ['[{"oldText": "a + b", "newText": "z"}]',
                  [{'oldText': 'a + b', 'newText': 'z'}],
                  [['a + b', 'z']],
                  {'oldText': 'a + b', 'newText': 'z'}]:
        h, edit = editor()
        assert not failed(edit('/proj/m.py', edits)), edits
        assert 'return z' in h.files['/proj/m.py']


def test_malformed_edits_say_what_the_shape_should_be():
    _, edit = editor()
    assert failed(edit('/proj/m.py', 'not json'))
    assert failed(edit('/proj/m.py', '[]'))
    assert 'oldText' in edit('/proj/m.py', '[{"old": "a"}]')


# ---------------------------------------------------------------------------
# grep and ls: the questions an index answers badly
# ---------------------------------------------------------------------------
FILES = {'/proj/a.py': 'import json\nvalue = compute(1)\n',
         '/proj/tests/test_a.py': 'from a import compute\n\ndef test_compute():\n    assert compute(1)\n',
         '/proj/notes.md': 'compute is described here\n'}


def test_grep_finds_every_literal_occurrence_with_its_line_number():
    """`search_code` answers with what is *like* the query. A rename needs every place the
    string actually occurs, which is a different question."""
    out = named(code_tools(MemHost(FILES)))['grep']('compute')
    assert '/proj/a.py:2' in out and '/proj/tests/test_a.py:1' in out and '/proj/notes.md:1' in out
    assert 'match(es) in 3 file(s) searched' in out


def test_grep_can_be_confined_to_part_of_the_tree():
    out = named(code_tools(MemHost(FILES)))['grep']('compute', path_filter='tests/')
    assert '/proj/tests/test_a.py' in out and '/proj/a.py:' not in out


def test_grep_takes_a_regex_and_can_be_told_not_to():
    g = named(code_tools(MemHost(FILES)))['grep']
    assert '/proj/a.py' in g(r'compute\(\d\)')
    assert 'no matches' in g('compute(1)', regex=True)      # unbalanced group, as a regex
    assert '/proj/a.py' in g('compute(1)', regex=False)


def test_grep_matches_case_only_when_told_to_ignore_it():
    g = named(code_tools(MemHost({'/proj/a.py': 'Value = 1\n'})))['grep']
    assert 'no matches' in g('value')
    assert '/proj/a.py' in g('value', ignore_case=True)


def test_grep_says_what_it_searched_when_it_finds_nothing():
    "'no matches' with no denominator reads like a broken tool; with one it reads like an answer."
    out = named(code_tools(MemHost(FILES)))['grep']('nowhere')
    assert 'no matches' in out and '3 file(s)' in out


def test_grep_needs_a_pattern_and_reports_a_bad_one():
    g = named(code_tools(MemHost(FILES)))['grep']
    assert failed(g(''))
    assert failed(g('(unclosed'))


def test_ls_lists_the_open_folders_when_asked_for_nothing(tmp_path):
    from leela.agent.tools import NullHost

    class H(NullHost):
        def check(self, path, must_exist=False):
            from pathlib import Path
            return Path(path)

    (tmp_path/'pkg').mkdir()
    (tmp_path/'x.py').write_text('x = 1\n')
    out = named(code_tools(H([str(tmp_path)])))['ls']('')
    assert 'pkg/' in out and 'x.py' in out


# ---------------------------------------------------------------------------
# the briefing, which must describe the tools that exist
# ---------------------------------------------------------------------------
def test_a_rule_about_a_missing_tool_does_not_appear():
    """The briefing described a `scale_numeric` that had been deleted, and promised
    verification the harness could not perform. A rule is chosen by its tool now."""
    everything = work_rules()
    assert 'run_shell' in everything and 'grep' in everything
    narrow = work_rules({'search_code', 'view_file'})
    assert 'run_shell' not in narrow and 'delegate_parallel' not in narrow
    assert 'search_code' in narrow


def test_the_rules_that_always_apply_survive_any_tool_list():
    "Honesty is not a capability, so it cannot be filtered out with one."
    narrow = work_rules({'view_file'})
    assert 'unless a tool\n  result in this conversation says so' in narrow
    assert 'ERROR:' in narrow
    assert 'inside the folders above' in narrow


def test_every_rule_names_a_real_tool():
    "A rule tagged with a tool that no longer exists would silently never appear again."
    real = {t.__name__ for t in tools_for(MemHost())} | {'notebook_cells', 'delegate_parallel',
                                                         'memory_search', 'web_search', 'run_python'}
    assert {tool for tool, _ in RULES if tool} <= real


def test_the_briefing_carries_the_projects_own_instructions():
    "A repository can tell every other agent how to work here; it could not tell this one."
    h = MemHost({'/proj/AGENTS.md': '# House rules\n\nUse uv, never pip.\n'})
    ctx = project_context(h)
    assert 'Use uv, never pip' in ctx and '/proj/AGENTS.md' in ctx
    assert 'Use uv, never pip' in system_prompt(h, tools=tools_for(h))


def test_project_instructions_are_capped_rather_than_dropped():
    h = MemHost({'/proj/AGENTS.md': 'rule\n' + 'filler\n' * 5000})
    ctx = project_context(h, mx=200)
    assert 'rule' in ctx and 'truncated' in ctx and len(ctx) < 900


def test_no_project_instructions_means_no_empty_block():
    assert project_context(MemHost()) == ''
    assert '<project_context>' not in system_prompt(MemHost(), tools=tools_for(MemHost()))


def test_the_briefing_says_where_it_may_work():
    sp = system_prompt(MemHost(), tools=tools_for(MemHost()))
    assert '/proj' in sp


# ---------------------------------------------------------------------------
# what the turn records
# ---------------------------------------------------------------------------
def agent_on(host):
    "An `Agent` over `host` with no model behind it: these tests are about the tool layer."
    from leela.agent.testing import fake_agent
    return fake_agent(host, replies=['done'], subagents=False, compact=False)[0]


def test_a_failed_tool_call_is_recorded_as_failed():
    """The old test was a list of prefixes ('edit failed', 'could not') that each new tool
    had to remember to match; a tool that phrased it any other way was recorded green."""
    h = MemHost({'/proj/m.py': SRC}, commands={'pytest': (1, 'boom')})
    a = agent_on(h)
    tools = named(a.tools)
    tools['run_shell']('pytest')
    tools['replace_text']('/proj/m.py', '[{"oldText": "nope", "newText": "x"}]')
    rows = a.activity.rows()
    assert [r['ok'] for r in rows[-2:]] == [False, False]


def test_a_successful_tool_call_is_recorded_as_successful():
    a = agent_on(MemHost(commands={'pytest': (0, '5 passed')}))
    named(a.tools)['run_shell']('pytest')
    assert a.activity.rows()[-1]['ok'] is True


def test_an_exact_text_edit_shows_up_in_the_turns_changes():
    "`changes()` reports the file, not the tool's account of the file."
    h = MemHost({'/proj/m.py': SRC})
    a = agent_on(h)
    named(a.tools)['replace_text']('/proj/m.py', '[{"oldText": "a + b", "newText": "a * b"}]')
    before, after = a.changes()['/proj/m.py']
    assert 'a + b' in before and 'a * b' in after


def test_a_refused_edit_does_not_show_up_as_a_change():
    h = MemHost({'/proj/m.py': SRC})
    a = agent_on(h)
    named(a.tools)['replace_text']('/proj/m.py', '[{"oldText": "nope", "newText": "x"}]')
    assert a.changes() == {}


def test_a_capability_lost_mid_session_is_a_failure_not_the_end_of_the_turn():
    """A kernel dies, a folder closes. Raising here ends the turn; a failure the model can
    read lets it say so, or work another way."""
    class Gone(MemHost):
        def run_cmd(self, command, cwd=None, timeout=120):
            if not str(command or '').strip(): return 0, ''
            raise NotImplementedError('the shell went away')

    a = agent_on(Gone())
    out = named(a.tools)['run_shell']('pytest')
    assert failed(out) and 'not available' in out
    assert a.activity.rows()[-1]['ok'] is False


def test_the_briefing_the_agent_sends_matches_the_tools_it_has():
    h = MemHost({'/proj/AGENTS.md': 'Use uv, never pip.\n'})
    a = agent_on(h)
    sp = a.system_prompt()
    assert 'run_shell' in sp and 'Use uv, never pip' in sp
    assert 'scale_numeric' not in sp


# ---------------------------------------------------------------------------
# the real thing: leela's own host, running real commands
# ---------------------------------------------------------------------------
@pytest.fixture
def project(tmp_path):
    from leela.ai import WorkspaceHost
    from leela.workspace import Workspace
    (tmp_path/'src').mkdir()
    (tmp_path/'src'/'app.py').write_text('value = 1\n')
    return WorkspaceHost(Workspace(roots=[tmp_path]))


def test_a_real_command_returns_its_output_and_exit_code(project):
    assert project.run_cmd('echo hello') == (0, 'hello\n')
    code, out = project.run_cmd('exit 3')
    assert code == 3 and out == ''


def test_stdout_and_stderr_come_back_in_the_order_they_happened(project):
    "A failing test *is* its traceback. Splitting the streams loses which line came first."
    code, out = project.run_cmd('echo out; echo err 1>&2; echo after')
    assert out.splitlines() == ['out', 'err', 'after']


def test_a_command_runs_in_the_project_by_default(project):
    code, out = project.run_cmd('ls')
    assert code == 0 and 'src' in out


def test_a_command_can_be_run_in_a_subdirectory(project):
    code, out = project.run_cmd('ls', cwd=str(project.roots[0] + '/src'))
    assert code == 0 and 'app.py' in out


def test_a_command_cannot_be_started_outside_the_open_folders(project):
    from leela.blocks.fs.fs import Unsafe
    with pytest.raises(Unsafe):
        project.run_cmd('ls', cwd='/etc')


def test_a_hung_command_is_killed_and_says_so(project):
    code, out = project.run_cmd('sleep 30', timeout=1)
    assert code == 124 and 'killed after 1s' in out


def test_a_timeout_takes_the_children_with_it(project):
    """`pytest -n 4` behind a pipe leaves children that outlive the shell, and a leaked
    runner holding a port is a failure the *next* run reports."""
    import os, signal, time
    marker = project.roots[0] + '/child.pid'
    project.run_cmd(f'(sleep 30 & echo $! > {marker}); sleep 30', timeout=2)
    pid = int(open(marker).read().strip())
    time.sleep(0.2)
    with pytest.raises(OSError):
        os.kill(pid, 0)          # gone: the whole group went, not just the shell


def test_the_probe_command_never_spawns_anything(project):
    assert project.run_cmd('') == (0, '')
    assert project.run_cmd('   ') == (0, '')


def test_leelas_own_agent_is_offered_the_shell(project):
    from leela.ai import ide_tools
    assert 'run_shell' in named(ide_tools(project))


def test_the_browser_previews_an_exact_text_edit_as_a_diff_without_writing_it(project):
    "The checkpoint form shows what the call would do. It must not do it."
    from leela.app import _tool_preview
    path = project.roots[0] + '/src/app.py'
    args = {'path': path, 'edits': '[{"oldText": "value = 1", "newText": "value = 2"}]'}
    preview = _tool_preview(project.ws.ai, 'replace_text', args)
    assert preview['kind'] == 'diff'
    assert open(path).read() == 'value = 1\n'


def test_the_browser_previews_a_command_as_a_command(project):
    from leela.app import _tool_preview
    p = _tool_preview(project.ws.ai, 'run_shell', {'command': 'pytest -q'})
    assert p['text'] == 'pytest -q' and p['language'] == 'bash'


def test_a_sub_agent_does_not_get_a_shell(project):
    "A research sub-agent reports; it does not act, and a command is an action."
    from leela.agent.tools import read_only
    from leela.ai import ide_tools
    assert 'run_shell' not in named(read_only(ide_tools(project)))
    assert 'replace_text' not in named(read_only(ide_tools(project)))
    assert 'grep' in named(read_only(ide_tools(project)))
