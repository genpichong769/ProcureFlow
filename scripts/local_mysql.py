"""Compatibility entry point; controls the project Docker service only."""
from scripts.docker_mysql import main

if __name__ == '__main__':
    main()
