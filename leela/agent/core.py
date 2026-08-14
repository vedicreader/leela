import sys, ramabana.core
ramabana.core.use_env_prefix('LEELA_', 'RAMABANA_')
sys.modules[__name__] = ramabana.core
