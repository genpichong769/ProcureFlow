import pytest
from config import get_settings
from scripts.phase2_stack import stack,listening


@pytest.fixture(scope='session')
def real_stack():
    settings=get_settings()
    ports=[getattr(settings,f'a2a_{r}_port') for r in ('budget','supplier','compliance','procurement')]
    ports += [getattr(settings,f'mcp_{r}_port') for r in ('budget','supplier','compliance')]
    if all(listening(p) for p in ports):yield
    else:
        with stack():yield
