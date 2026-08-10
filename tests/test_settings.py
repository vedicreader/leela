import json
from pathlib import Path

import pytest

from leela.blocks.settings.settings import DEFAULT_SETTINGS, Settings


def test_settings_layer_default_user_workspace_and_language(tmp_path):
    root, user = tmp_path/'project', tmp_path/'user.json'
    root.mkdir(); (root/'.leela').mkdir()
    user.write_text(json.dumps({'editor': {'fontSize': 14}, 'languages': {
        'python': {'editor': {'lineLength': 88}}}}))
    (root/'.leela/settings.json').write_text(json.dumps({'editor': {'fontSize': 15}, 'languages': {
        'python': {'editor': {'fontSize': 16}}}}))
    settings = Settings(root, user)
    assert settings.effective()['editor']['fontSize'] == 15
    effective = settings.effective('python')
    assert effective['editor']['fontSize'] == 16 and effective['editor']['lineLength'] == 88
    described = settings.describe('python')
    assert described['origins']['editor']['fontSize'] == 'workspace:python'
    assert described['origins']['editor']['lineLength'] == 'user:python'


def test_settings_save_validates_known_keys_enums_and_ranges(tmp_path):
    root, user = tmp_path/'project', tmp_path/'user.json'; root.mkdir()
    settings = Settings(root, user)
    settings.save('user', 'editor', {'fontSize': 17, 'wordWrap': 'column'})
    assert settings.effective()['editor']['fontSize'] == 17
    with pytest.raises(ValueError): settings.save('user', 'editor', {'fontSize': 99})
    with pytest.raises(ValueError): settings.save('user', 'editor', {'wordWrap': 'sometimes'})
    with pytest.raises(ValueError): settings.save('user', 'editor', {'imaginary': True})


def test_legacy_full_workspace_snapshot_does_not_override_later_user_choices(tmp_path):
    root, user = tmp_path/'project', tmp_path/'user.json'; root.mkdir(); (root/'.leela').mkdir()
    # The original UI wrote every default into Workspace. It must not pin defaults over a
    # later explicit User preference.
    snapshot = {section: dict(values) for section, values in DEFAULT_SETTINGS.items()}
    (root/'.leela/settings.json').write_text(json.dumps(snapshot))
    user.write_text(json.dumps({'editor': {'ligatures': False, 'useTabs': True}}))
    effective = Settings(root, user).effective()
    assert effective['editor']['ligatures'] is False
    assert effective['editor']['useTabs'] is True


def test_legacy_snapshot_keeps_non_default_values(tmp_path):
    root, user = tmp_path/'project', tmp_path/'user.json'; root.mkdir()
    snapshot = {section: dict(values) for section, values in DEFAULT_SETTINGS.items()}
    snapshot['editor']['fontSize'] = 17
    user.write_text(json.dumps(snapshot))
    settings = Settings(root, user)
    assert settings.raw('user') == {'editor': {'fontSize': 17}}


def test_settings_writes_are_atomic_and_leave_valid_json(tmp_path, monkeypatch):
    import leela.blocks.settings.settings as module
    user = tmp_path/'nested'/'settings.json'
    calls = []
    original = module.atomic_save

    def atomic(path, **kwargs):
        calls.append((Path(path), kwargs))
        return original(path, **kwargs)

    monkeypatch.setattr(module, 'atomic_save', atomic)
    Settings(user_path=user).save('user', 'editor', {'fontSize': 17})
    assert calls == [(user, {'mode': 'w', 'encoding': 'utf-8'})]
    assert json.loads(user.read_text()) == {'editor': {'fontSize': 17}}


def test_workspace_settings_are_project_local_and_resettable(tmp_path):
    root, user = tmp_path/'project', tmp_path/'user.json'; root.mkdir()
    settings = Settings(root, user)
    settings.save('workspace', 'files', {'autoSave': 'off'})
    assert settings.workspace_path == root/'.leela/settings.json'
    assert settings.effective()['files']['autoSave'] == 'off'
    settings.reset('workspace', 'files')
    assert settings.effective()['files']['autoSave'] == DEFAULT_SETTINGS['files']['autoSave']
