"""What Leela configures in the libraries it composes."""


def test_the_configuration_leela_sets_in_a_library_takes():
    """`kunda.use_app` and `pullup.use_spec_dir` are module globals, which is the only seam either offers."""
    from kunda.pythons import app_name, env_name
    import leela.blocks.runtime.kernels                     # noqa: F401  the import that calls it
    assert app_name() == 'leela'
    assert env_name('MAX_KERNELS') == 'LEELA_MAX_KERNELS'
    from pullup.wfbuild import spec_dir
    from leela.blocks.workflows.workflows import SPEC_DIR
    import leela.blocks.workflows.workflows                 # noqa: F401
    assert spec_dir() == SPEC_DIR == '.leela/workflows'