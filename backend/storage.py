"""The account's shared pool: Brain files and Sites blobs, including reservations."""


def used(conn, list_id: int) -> int:
    return conn.execute(
        "SELECT (SELECT COALESCE(SUM(size), 0) FROM brain_files WHERE list_id = ?) + "
        "(SELECT COALESCE(SUM(bytes), 0) FROM site_blobs WHERE list_id = ?)",
        (list_id, list_id),
    ).fetchone()[0]
