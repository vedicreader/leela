"An agent turn in a test carries none of this machine's beat notes."
from pathlib import Path
import ramabana.monitor as rmon

def test_the_beat_reads_no_real_pob_db():
    p = rmon.pob_path()
    assert Path.home()/'.pobblebonk' not in p.parents and not p.exists()
