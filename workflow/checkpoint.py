"""One durable SQLite checkpointer rooted under PROCUREFLOW_DATA_ROOT."""
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
from config import get_settings


def create_checkpointer():
    settings=get_settings()
    directory=settings.require_persistent_path(settings.langgraph_dir)
    directory.mkdir(parents=True,exist_ok=True)
    path=settings.require_persistent_path(settings.checkpoint_path)
    connection=sqlite3.connect(path,check_same_thread=False)
    saver=SqliteSaver(connection)
    saver.setup()
    return connection,saver
