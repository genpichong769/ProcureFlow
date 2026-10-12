import pytest
from config import get_settings
from scripts.phase3_stack import stack,listening


@pytest.fixture(scope='session')
def real_phase3_stack():
    settings=get_settings()
    ports=[getattr(settings,f'a2a_{r}_port') for r in ('budget','supplier','compliance','procurement')]
    ports += [getattr(settings,f'mcp_{r}_port') for r in ('budget','supplier','compliance','procurement')]
    if all(listening(port) for port in ports):yield
    else:
        with stack():yield
