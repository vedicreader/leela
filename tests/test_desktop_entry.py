def test_the_frozen_entry_takes_the_shell_environment_the_window_was_denied():
    """`leela.cli` asks the login shell for the environment, and the bundle does not run it: py2app freezes `leela_app.py`."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]/'leela_app.py').read_text()
    frozen = src[src.index("if getattr(sys, 'frozen'"):src.index('def free_port')]
    assert 'import_login_env' in frozen, 'the entry the bundle freezes asks for it too'
    assert 'use_extras' in frozen and 'use_login_path' in frozen, 'and still does what it did'
    assert "LEELA_SHELL_ENV" in frozen, 'and the same switch turns it off'
