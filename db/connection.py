"""One checked-out connection per transaction; no shared live connection."""
from contextlib import contextmanager
from threading import Lock
from mysql.connector.pooling import MySQLConnectionPool
from config import get_settings


class Database:
    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self._pool = None
        self._lock = Lock()

    def connection(self):
        with self._lock:
            if self._pool is None:
                self._pool = MySQLConnectionPool(pool_name=None,
                    pool_size=self.settings.db_pool_size, pool_reset_session=True,
                    **self.settings.connection_kwargs())
        return self._pool.get_connection()

    @contextmanager
    def transaction(self):
        conn = self.connection()
        try:
            conn.start_transaction(isolation_level='READ COMMITTED')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


database = Database()
