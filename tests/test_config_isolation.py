"""The suite must never write to the developer's own `~/.config/leela`.

`tests/conftest.py` points `XDG_CONFIG_HOME` at a temp directory before importing leela.
That has to happen there, above the imports: `leela_cfg` is computed at import time, and
modules capture it at import too -- `settings.py` derives `USER_SETTINGS_FILE` once and
never looks again -- so patching afterwards would leave them aimed at the real directory.

These assertions exist because the failure is silent and cumulative. `Workspace.__init__`
builds memory with no path, so `memory_path(None)` resolves to the real `memory/web.db`,
and one route test posting to `/agent/memory/save` appends a row nothing cleans up. Nothing
goes red. It surfaced only when a developer opened the memory panel and found fifteen copies
of a test fixture's note, alongside a journal file per suite run.
"""

from pathlib import Path

from tests.conftest import TEST_CONFIG_HOME


def test_leela_cfg_and_everything_derived_from_it_stay_in_the_temp_dir():
    from leela import leela_cfg
    from leela.blocks.memory.memory import memory_path
    from leela.blocks.settings.settings import USER_SETTINGS_FILE
    from leela.workspace import ws_path
    for p in (leela_cfg, memory_path(), USER_SETTINGS_FILE, ws_path()):
        assert str(p).startswith(TEST_CONFIG_HOME), f'{p} escapes the test config dir'


def test_a_workspace_writes_its_memory_and_journal_under_the_temp_dir(tmp_path):
    "The two a `Workspace` opens on construction, which is how the real store got polluted."
    from leela.workspace import Workspace
    ws = Workspace(roots=[tmp_path])
    assert str(ws.memory.path).startswith(TEST_CONFIG_HOME)
    assert str(ws.journal.path).startswith(TEST_CONFIG_HOME)


def test_the_real_config_dir_is_not_touched_by_importing_leela():
    "A guard against someone reintroducing a module-level write to the real directory."
    real = Path.home()/'.config'/'leela'
    assert not str(real).startswith(TEST_CONFIG_HOME)     # the test is meaningful
    from leela import leela_cfg
    assert Path(leela_cfg) != real
