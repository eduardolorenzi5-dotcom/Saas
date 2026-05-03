import os, sqlite3

DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_PG = bool(DATABASE_URL)


class _PGConn:
    """Wrap psycopg2 para ter a mesma API do sqlite3 (conn.execute().fetchone())."""
    def __init__(self, raw):
        self._raw = raw
        self._cur = raw.cursor()

    def execute(self, sql, params=()):
        self._cur.execute(sql, params)
        return self._cur

    def executemany(self, sql, params_list):
        self._cur.executemany(sql, params_list)
        return self._cur

    def commit(self):
        self._raw.commit()

    def close(self):
        try:
            self._cur.close()
        except Exception:
            pass
        self._raw.close()


class _SQLiteConn:
    """Wrap sqlite3 para aceitar placeholders %s (mesmo padrão do PostgreSQL)."""
    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=()):
        return self._raw.execute(sql.replace("%s", "?"), params)

    def executemany(self, sql, params_list):
        return self._raw.executemany(sql.replace("%s", "?"), params_list)

    def commit(self):
        self._raw.commit()

    def close(self):
        self._raw.close()


def get_db():
    if USE_PG:
        import psycopg2, psycopg2.extras
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        raw = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
        return _PGConn(raw)
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gastos.db")
    raw = sqlite3.connect(db_path)
    raw.row_factory = sqlite3.Row
    return _SQLiteConn(raw)
