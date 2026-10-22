"Cells written with IPython shell escapes and magics: analysed as Python, and run as ipykernel runs them."
import asyncio, pytest
from leela.blocks.nb.nb import Cell, assigned_lines
from leela.core.session import assigned_names

CELL = '! git --version\n%cd sub\nx = 1\n%time y = x\nz: int = 2'

def test_analysis_reads_past_shell_escapes_and_magics():
    assert assigned_lines(CELL) == [(3, 'x'), (5, 'z')]
    assert assigned_names(CELL) == ['x', 'z']
    assert assigned_names('%%bash\necho hi') == []

@pytest.mark.slow
def test_a_real_kernel_runs_escapes_and_magics_from_a_notebook(tmp_path):
    from leela.blocks.runtime.kernels import Kernel
    from leela.blocks.nb.nb import Notebook
    (tmp_path/'sub').mkdir()
    async def go():
        k = Kernel(inspect=False, cwd=str(tmp_path))
        await k.start(timeout=90)
        try:
            nb = Notebook([Cell(source=s) for s in ('!echo hi', '%cd sub\n%pwd', '%%bash\necho from-bash', '%env FOO=bar\nx = 1')])
            return [await nb.run(i, k) for i in range(len(nb))]
        finally: await k.shutdown()
    echo, cd, bash, env = asyncio.run(go())
    assert not any(c.has_error for c in (echo, cd, bash, env))
    assert 'hi' in str(echo.outputs) and 'from-bash' in str(bash.outputs)
    assert str(tmp_path/'sub').replace('/private', '') in str(cd.outputs).replace('/private', '')
    assert 'FOO=bar' in str(env.outputs)
    assert [n for _, n in assigned_lines(env.source)] == ['x']