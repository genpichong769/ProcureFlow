"""Internal SQL helpers; callers supply only fixed application SQL."""
def all_rows(conn, sql, params=()):
    with conn.cursor(dictionary=True, buffered=True) as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def one(conn, sql, params=()):
    rows = all_rows(conn, sql, params)
    return rows[0] if rows else None


def execute(conn, sql, params=()):
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.lastrowid
