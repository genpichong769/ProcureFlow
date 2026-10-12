"""Retired entry point. Native MySQL initialization is no longer supported."""

if __name__ == '__main__':
    raise SystemExit('Use python -m scripts.docker_mysql prepare, then docker compose up -d mysql. Native MySQL creation is disabled.')
